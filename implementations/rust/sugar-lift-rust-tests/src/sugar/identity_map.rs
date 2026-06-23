// SPDX-License-Identifier: Apache-2.0
//
// `IdentityMapSugar`: the `.map(|x| x)` / `.map(|x| *x)` adaptor over a
// literal-derived sequence. Unlike `MapSugar`, this does not inspect or transform the
// element's `ConstVal`; it preserves the element sequence exactly. That makes string
// literal arrays sound here without broadening the global exact const evaluator.

use syn::{Expr, ExprClosure};
use tracing::debug;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family;
use crate::{closure_single_param_ident, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite_before(
        "identity_map",
        &["map"],
        recognize_composite,
    );

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    if !is_identity_closure(f) {
        return None;
    }
    debug!(
        target: "sugar_lift_rust_tests::sugar::identity_map",
        receiver = %crate::token_key(&call.receiver),
        "recognized literal identity map"
    );
    Some(Box::new(IdentityMapSugar {
        inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
    }))
}

pub(crate) fn is_identity_closure(closure: &ExprClosure) -> bool {
    let Some(param) = identity_param(closure) else {
        return false;
    };
    closure_body_expr(closure).is_some_and(|body| identity_body_expr(body, &param))
}

fn identity_param(closure: &ExprClosure) -> Option<String> {
    if closure.inputs.len() != 1 {
        return None;
    }
    closure_single_param_ident(&closure.inputs[0])
}

fn closure_body_expr(closure: &ExprClosure) -> Option<&Expr> {
    match strip_refs_groups(&closure.body) {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => Some(expr),
            _ => None,
        },
        other => Some(other),
    }
}

fn identity_body_expr(expr: &Expr, param: &str) -> bool {
    match strip_refs_groups(expr) {
        Expr::Path(path) => path.path.get_ident().is_some_and(|ident| ident == param),
        Expr::Unary(unary) if matches!(unary.op, syn::UnOp::Deref(_)) => {
            matches!(strip_refs_groups(&unary.expr), Expr::Path(path) if path.path.get_ident().is_some_and(|ident| ident == param))
        }
        _ => false,
    }
}

/// `.map(|x| x)` / `.map(|x| *x)`: pass the inner element sequence through unchanged.
pub(crate) struct IdentityMapSugar {
    pub(crate) inner: Box<dyn Sugar>,
}

impl Sugar for IdentityMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).complete()?.into_seq()?;
            debug!(
                target: "sugar_lift_rust_tests::sugar::identity_map",
                len = seq.len(),
                "literal identity map preserved sequence"
            );
            Some(Desugared::Seq(seq))
        })())
    }
}
