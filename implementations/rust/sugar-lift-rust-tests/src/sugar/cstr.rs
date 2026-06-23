// SPDX-License-Identifier: Apache-2.0
//
// C string literals are compiler-checked byte sequences with an implicit trailing
// NUL. When the receiver bottoms out in a literal `c"..."`, the stdlib CStr
// accessors are compiler axioms over those bytes, not opaque runtime calls.

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, ExprLit, Lit};
use tracing::debug;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    bytes_literal_term_from_bytes, bytes_to_hex, num, Desugared, Effect, Outcome, Sugar, SugarCtx,
    STRUCTURAL_BACKSTOP_REASON,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term("cstr", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if direct_cstr_expr(expr) {
        debug!(
            target: "sugar_lift_rust_tests::sugar::cstr",
            "cstr literal claimed as compiler-axiom bytes"
        );
        return Some(Box::new(CStrSugar::identity(expr.clone())));
    }

    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    let receiver = (*call.receiver).clone();
    if !cstr_receiver_is_literal(&receiver, fcx) {
        return None;
    }
    match call.method.to_string().as_str() {
        "count_bytes" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "count_bytes",
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::method(receiver, CStrKind::CountBytes)))
        }
        "to_bytes" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "to_bytes",
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::method(receiver, CStrKind::ToBytes)))
        }
        "to_bytes_with_nul" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "to_bytes_with_nul",
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::method(
                receiver,
                CStrKind::ToBytesWithNul,
            )))
        }
        _ => None,
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct CStrBytes {
    without_nul: Vec<u8>,
    with_nul: Vec<u8>,
}

impl CStrBytes {
    fn from_lit(lit: &syn::LitCStr) -> Self {
        let value = lit.value();
        Self {
            without_nul: value.as_bytes().to_vec(),
            with_nul: value.as_bytes_with_nul().to_vec(),
        }
    }
}

#[derive(Clone, Copy)]
enum CStrKind {
    Identity,
    CountBytes,
    ToBytes,
    ToBytesWithNul,
}

pub(crate) struct CStrSugar {
    expr: Expr,
    kind: CStrKind,
}

impl CStrSugar {
    fn identity(expr: Expr) -> Self {
        Self {
            expr,
            kind: CStrKind::Identity,
        }
    }

    fn method(expr: Expr, kind: CStrKind) -> Self {
        Self { expr, kind }
    }
}

impl Sugar for CStrSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let Some(bytes) = cstr_receiver_bytes_in_ctx(&self.expr, ctx, &mut Vec::new()) else {
            return Outcome::Incomplete(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            });
        };
        let term = match self.kind {
            CStrKind::Identity => cstr_literal_term_from_bytes_with_nul(&bytes.with_nul),
            CStrKind::CountBytes => num(bytes.without_nul.len() as i128),
            CStrKind::ToBytes => bytes_literal_term_from_bytes(&bytes.without_nul),
            CStrKind::ToBytesWithNul => bytes_literal_term_from_bytes(&bytes.with_nul),
        };
        Outcome::Complete(Desugared::Term(term))
    }
}

fn cstr_literal_term_from_bytes_with_nul(bytes: &[u8]) -> Rc<Term> {
    make_var(format!("literal:cstr({})", bytes_to_hex(bytes)))
}

fn direct_cstr_bytes(expr: &Expr) -> Option<CStrBytes> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::CStr(cstr),
            ..
        }) => Some(CStrBytes::from_lit(cstr)),
        Expr::Paren(paren) => direct_cstr_bytes(&paren.expr),
        Expr::Group(group) => direct_cstr_bytes(&group.expr),
        _ => None,
    }
}

fn direct_cstr_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::CStr(_), ..
        }) => true,
        Expr::Paren(paren) => direct_cstr_expr(&paren.expr),
        Expr::Group(group) => direct_cstr_expr(&group.expr),
        _ => false,
    }
}

fn cstr_receiver_is_literal(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    if direct_cstr_expr(expr) {
        return true;
    }
    match expr {
        Expr::Reference(reference) if reference.mutability.is_none() => {
            cstr_receiver_is_literal(&reference.expr, fcx)
        }
        Expr::Paren(paren) => cstr_receiver_is_literal(&paren.expr, fcx),
        Expr::Group(group) => cstr_receiver_is_literal(&group.expr, fcx),
        Expr::Path(path) if path.qself.is_none() => {
            let Some(ident) = path.path.get_ident() else {
                return false;
            };
            let name = ident.to_string();
            if fcx.resolving_bound_path(&name) {
                return false;
            }
            if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
                let child_fcx = fcx.with_bound_path(&name);
                return cstr_receiver_is_literal(&current, &child_fcx);
            }
            let Some(init) = fcx.scope().stable_let_binding_for_term(&name) else {
                return false;
            };
            let child_fcx = fcx.with_bound_path(&name);
            cstr_receiver_is_literal(init, &child_fcx)
        }
        _ => false,
    }
}

fn cstr_receiver_bytes_in_ctx(
    expr: &Expr,
    ctx: &SugarCtx,
    resolving: &mut Vec<String>,
) -> Option<CStrBytes> {
    if let Some(bytes) = direct_cstr_bytes(expr) {
        return Some(bytes);
    }
    match expr {
        Expr::Reference(reference) if reference.mutability.is_none() => {
            cstr_receiver_bytes_in_ctx(&reference.expr, ctx, resolving)
        }
        Expr::Paren(paren) => cstr_receiver_bytes_in_ctx(&paren.expr, ctx, resolving),
        Expr::Group(group) => cstr_receiver_bytes_in_ctx(&group.expr, ctx, resolving),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if resolving.iter().any(|current| current == &name) {
                return None;
            }
            resolving.push(name.clone());
            let out = if let Some(current) = ctx.scope.temporal_rewrite_expr_for(&name) {
                cstr_receiver_bytes_in_ctx(&current, ctx, resolving)
            } else {
                ctx.scope
                    .stable_let_binding_for_term(&name)
                    .and_then(|init| cstr_receiver_bytes_in_ctx(init, ctx, resolving))
            };
            resolving.pop();
            out
        }
        _ => None,
    }
}
