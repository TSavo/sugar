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
    bytes_literal_term_from_bytes, bytes_to_hex, num, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term("cstr", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(bytes) = direct_cstr_bytes(expr) {
        debug!(
            target: "sugar_lift_rust_tests::sugar::cstr",
            bytes = bytes.with_nul.len(),
            "cstr literal claimed as compiler-axiom bytes"
        );
        return Some(Box::new(CStrSugar::identity(bytes)));
    }

    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    let bytes = cstr_receiver_bytes(&call.receiver, fcx)?;
    match call.method.to_string().as_str() {
        "count_bytes" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "count_bytes",
                bytes_without_nul = bytes.without_nul.len(),
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::count_bytes(bytes)))
        }
        "to_bytes" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "to_bytes",
                bytes_without_nul = bytes.without_nul.len(),
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::bytes(bytes.without_nul)))
        }
        "to_bytes_with_nul" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "to_bytes_with_nul",
                bytes_with_nul = bytes.with_nul.len(),
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::bytes(bytes.with_nul)))
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

enum CStrTerm {
    Identity(Vec<u8>),
    CountBytes(usize),
    Bytes(Vec<u8>),
}

pub(crate) struct CStrSugar {
    term: CStrTerm,
}

impl CStrSugar {
    fn identity(bytes: CStrBytes) -> Self {
        Self {
            term: CStrTerm::Identity(bytes.with_nul),
        }
    }

    fn count_bytes(bytes: CStrBytes) -> Self {
        Self {
            term: CStrTerm::CountBytes(bytes.without_nul.len()),
        }
    }

    fn bytes(bytes: Vec<u8>) -> Self {
        Self {
            term: CStrTerm::Bytes(bytes),
        }
    }
}

impl Sugar for CStrSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        let term = match &self.term {
            CStrTerm::Identity(bytes) => cstr_literal_term_from_bytes_with_nul(bytes),
            CStrTerm::CountBytes(len) => num(*len as i128),
            CStrTerm::Bytes(bytes) => bytes_literal_term_from_bytes(bytes),
        };
        Outcome::Dug(Desugared::Term(term))
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

fn cstr_receiver_bytes(expr: &Expr, fcx: &SugarBuildCtx) -> Option<CStrBytes> {
    if let Some(bytes) = direct_cstr_bytes(expr) {
        return Some(bytes);
    }
    match expr {
        Expr::Reference(reference) if reference.mutability.is_none() => {
            cstr_receiver_bytes(&reference.expr, fcx)
        }
        Expr::Paren(paren) => cstr_receiver_bytes(&paren.expr, fcx),
        Expr::Group(group) => cstr_receiver_bytes(&group.expr, fcx),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if fcx.resolving_bound_path(&name) {
                return None;
            }
            if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
                let child_fcx = fcx.with_bound_path(&name);
                return cstr_receiver_bytes(&current, &child_fcx);
            }
            let init = fcx.scope().stable_let_binding_for_term(&name)?;
            let child_fcx = fcx.with_bound_path(&name);
            cstr_receiver_bytes(init, &child_fcx)
        }
        _ => None,
    }
}
