// SPDX-License-Identifier: Apache-2.0
//
// `IsEmptySugar`: `.is_empty()` over a range literal with const integer/char
// endpoints, or over a literal collection sequence (array / repeat / Vec-constructor),
// direct or through an SSA-stable binding, is value sugar. The emptiness is determined
// ENTIRELY by the program text:
//
//   * a half-open `a..b` is empty iff `a >= b`,
//   * an inclusive `a..=b` is empty iff `a > b`,
//   * an array literal `[..]` is empty iff it has no elements,
//   * a repeat `[x; N]` is empty iff `N == 0`.
//
// Recognition constructs the receiver body and any static-length verifier body without
// reducing them. `desugar`/`reduce` composes those bodies to a literal sequence floor and
// lowers the resulting emptiness to a ground `Bool` const that z3 reasons about directly
// (a real value, NOT an opaque `method:is_empty` EUF var with no teeth).
//
// EXACT-OR-NONE. We claim ONLY when the result is fully determinable from the
// text: a range needs BOTH endpoints present AND const-foldable to a scalar (an
// int/char/byte literal, possibly negated, through paren/group/ref wrappers); a
// repeat needs a const count. A runtime endpoint, an open-ended range, a
// runtime / mutated / opaque receiver (a runtime `Vec` / `String` / unstable local) takes
// a named `Incomplete`; anything desugar completes as the wrong floor panics. No guess
// is made in recognition.
//
// TEETH. The lowered `Bool` is a real value: `assert!((0..5).is_empty())` lowers
// to `Bool(false)` -> the obligation is z3-UNSAT (a wrong claim is REFUTED);
// `assert!((5..5).is_empty())` lowers to `Bool(true)` -> discharged.

use syn::{Expr, ExprLit, Lit, UnOp};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method_family;
use crate::{
    bool_const, simple_path_name, strip_refs_groups, Desugared, DesugaredElem, Effect, Outcome,
    Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("is_empty", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "is_empty" || !call.args.is_empty() {
        return None;
    }
    if !is_empty_receiver_is_owned_by_literal_sugar(&call.receiver, fcx) {
        return None;
    }
    let literal_empty = literal_empty_without_elements(&call.receiver);
    let static_len = method_family::literal_sequence_static_len_in_scope(
        &call.receiver,
        fcx.let_inits(),
        fcx.scope(),
    );
    let static_collection_len = method_family::literal_collection_adapter_static_len_in_scope(
        &call.receiver,
        fcx.let_inits(),
        fcx.scope(),
    )
    .map(|static_len| StaticLenSource {
        len: static_len.len,
        source: sequence_body(&static_len.source, fcx),
    });
    Some(IsEmptySugar::new(
        literal_empty,
        sequence_body(&call.receiver, fcx),
        static_len,
        static_collection_len,
    ))
}

fn is_empty_receiver_is_owned_by_literal_sugar(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    literal_empty_without_elements(expr).is_some()
        || method_family::resolves_literal_sequence(expr, fcx.let_inits())
        || method_family::literal_sequence_static_len_in_scope(expr, fcx.let_inits(), fcx.scope())
            .is_some()
        || method_family::literal_collection_adapter_static_len_in_scope(
            expr,
            fcx.let_inits(),
            fcx.scope(),
        )
        .is_some()
        || simple_path_name(expr).is_some_and(|name| fcx.scope().is_consumed_iterator_local(&name))
}

/// The emptiness of a range literal whose BOTH endpoints const-fold to a scalar.
/// `None` for an open-ended range (`a..` / `..b` / `..`) or a non-const endpoint
/// -- left for the generic machinery.
fn range_is_empty(range: &syn::ExprRange) -> Option<bool> {
    let start = endpoint_const_scalar(range.start.as_deref()?)?;
    let end = endpoint_const_scalar(range.end.as_deref()?)?;
    Some(match range.limits {
        // `a..b`: empty iff start is not below end.
        syn::RangeLimits::HalfOpen(_) => start >= end,
        // `a..=b`: empty iff start is strictly above end.
        syn::RangeLimits::Closed(_) => start > end,
    })
}

/// Const-fold a range endpoint / repeat count to its exact scalar value: an
/// int/byte/char literal, optionally negated, through paren/group/ref wrappers.
/// Strict by design -- anything else (a path, a method call, a float) is `None`,
/// so the caller declines rather than guesses.
fn endpoint_const_scalar(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<i128>().ok(),
        Expr::Lit(ExprLit {
            lit: Lit::Byte(b), ..
        }) => Some(i128::from(b.value())),
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(i128::from(u32::from(c.value()))),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => {
            endpoint_const_scalar(&u.expr).and_then(i128::checked_neg)
        }
        _ => None,
    }
}

struct IsEmptySugar {
    literal_empty: Option<bool>,
    receiver: SugarBody<CompositeFloor>,
    static_len: Option<usize>,
    static_collection_len: Option<StaticLenSource>,
}

struct StaticLenSource {
    len: usize,
    source: SugarBody<CompositeFloor>,
}

impl Sugar for IsEmptySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(value) = self.literal_empty {
            debug!(
                target: "sugar_lift_rust_tests::sugar::is_empty",
                value,
                "resolved range is_empty stdlib axiom to a ground bool"
            );
            return Outcome::Complete(Desugared::Term(bool_const(value)));
        }
        if self.static_len == Some(0) {
            debug!(
                target: "sugar_lift_rust_tests::sugar::is_empty",
                "resolved zero-length literal-sequence is_empty stdlib axiom to true"
            );
            return Outcome::Complete(Desugared::Term(bool_const(true)));
        }
        let value = match sequence_from_body(&self.receiver, ctx, "is_empty receiver") {
            Ok(seq) => seq.is_empty(),
            Err(Outcome::Incomplete(effect))
                if effect.is_literal_domain_reason(EMPTY_DOMAIN_REASON)
                    && self.static_len == Some(0) =>
            {
                true
            }
            Err(Outcome::Complete(_)) => {
                is_empty_gap("is_empty receiver sequence helper returned unexpected Complete")
            }
            Err(Outcome::Incomplete(effect)) => return Outcome::Incomplete(effect),
            Err(gap) => {
                if let Some(static_len) = &self.static_collection_len {
                    match source_reduces_to_sequence(&static_len.source, ctx) {
                        Ok(true) => static_len.len == 0,
                        Ok(false) => return gap,
                        Err(outcome) => return outcome,
                    }
                } else {
                    return gap;
                }
            }
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::is_empty",
            value,
            "resolved literal-sequence is_empty stdlib axiom to a ground bool"
        );
        Outcome::Complete(Desugared::Term(bool_const(value)))
    }
}

impl IsEmptySugar {
    fn new(
        literal_empty: Option<bool>,
        receiver: SugarBody<CompositeFloor>,
        static_len: Option<usize>,
        static_collection_len: Option<StaticLenSource>,
    ) -> Box<dyn Sugar> {
        Box::new(Self {
            literal_empty,
            receiver,
            static_len,
            static_collection_len,
        })
    }
}

fn literal_empty_without_elements(expr: &Expr) -> Option<bool> {
    match strip_refs_groups(expr) {
        Expr::Range(range) => range_is_empty(range),
        _ => None,
    }
}

fn sequence_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
    SugarBody::from_node(
        method_family::build_literal_sequence_composite(expr, fcx)
            .unwrap_or_else(|| build_composite(expr, fcx)),
    )
}

fn sequence_from_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Vec<DesugaredElem>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .ok_or_else(|| is_empty_gap(&format!("{label} reduced to non-sequence"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn source_reduces_to_sequence(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
) -> Result<bool, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d.into_seq().is_some()),
        Outcome::Incomplete(effect) if effect.is_literal_domain_reason(EMPTY_DOMAIN_REASON) => {
            Ok(true)
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn is_empty_gap(reason: &str) -> ! {
    panic!("is_empty completed without a literal sequence floor: {reason}")
}
