// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Reference`. Mirrors the three source-of-truth guard arms
// in order: `&x` -> `ref` ctor; `&mut <immutable value>` -> `ref_mut` ctor; any other
// `&mut <place>` -> reasoned Incomplete (mutable reference). Byte-identical to the
// `Expr::Reference` arms of the old fat factory.
//
// THE `ref`/`ref_mut` CTORS ARE STRUCTURAL: they keep a borrowed value distinct as a
// term so that an EUF call-result key (`r.contains(&i)` -> `..c:ref(i)`) and a pointer-
// identity predicate (`ptr::eq(&a, &b)`) stay sound. They are deliberately UNINTERPRETED.
// The value-equality READING of a shared borrow (`&a == &b` <=> `a == b`, Rust's
// `PartialEq for &T`) is recovered NOT here but at the relation surface: the single
// assertion-surface relation builder (`assertion_entry_from_relation` in `lib.rs`) strips
// a redundant outer shared-`ref` from each operand via `strip_shared_ref`. That keeps the
// EUF call-result arg keys and `ptr::eq` pointer-identity terms intact (a `ref` nested
// inside a call ctor is NOT a relational operand) while letting `&place == value` warrant
// the pointee instead of an uninterpreted `ref(..)` a bad twin could mis-satisfy.

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::sugar::term_leaf::reasoned_incomplete;
use crate::{is_immutable_value_expr, token_key, Effect, Sugar, UnsupportedTermCause};
use syn::Expr;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::fallback_term("reference_term", recognize);

/// TERM recognizer for `Expr::Reference`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Reference(reference) = expr else {
        return None;
    };
    if reference.mutability.is_none() {
        return Some(Box::new(CtorSugar::new(
            "ref",
            vec![SugarBody::term(&reference.expr, fcx)],
        )));
    }
    if is_immutable_value_expr(&reference.expr) {
        return Some(Box::new(CtorSugar::new(
            "ref_mut",
            vec![SugarBody::term(&reference.expr, fcx)],
        )));
    }
    // reference.mutability.is_some() && not an immutable value place.
    let effect = Effect::unsupported_term(&token_key(expr), UnsupportedTermCause::MutableReference);
    Some(reasoned_incomplete(effect.reason()))
}
