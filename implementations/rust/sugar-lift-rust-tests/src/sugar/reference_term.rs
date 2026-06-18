// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Reference`. Mirrors the three source-of-truth guard arms
// in order: `&x` -> `ref` ctor; `&mut <immutable value>` -> `ref_mut` ctor; any other
// `&mut <place>` -> reasoned Hit (mutable reference). Byte-identical to the
// `Expr::Reference` arms of the old fat factory.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, FactoryCtx};
use crate::sugar::term_leaf::reasoned_hit;
use crate::{is_immutable_value_expr, token_key, Effect, Sugar, UnsupportedTermCause};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("reference_term", recognize);

/// TERM recognizer for `Expr::Reference`.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Reference(reference) = expr else {
        return None;
    };
    if reference.mutability.is_none() {
        return Some(Box::new(CtorSugar::new(
            "ref",
            vec![build_term(&reference.expr, fcx)],
        )));
    }
    if is_immutable_value_expr(&reference.expr) {
        return Some(Box::new(CtorSugar::new(
            "ref_mut",
            vec![build_term(&reference.expr, fcx)],
        )));
    }
    // reference.mutability.is_some() && not an immutable value place.
    let effect = Effect::unsupported_term(&token_key(expr), UnsupportedTermCause::MutableReference);
    Some(reasoned_hit(effect.reason()))
}
