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
// Recognition captures only the raw receiver. `desugar` composes that receiver to the
// literal sequence floor in the live binding context and lowers the resulting emptiness
// to a ground `Bool` const that z3 reasons about directly (a real value, NOT an opaque
// `method:is_empty` EUF var with no teeth).
//
// EXACT-OR-NONE. We claim ONLY when the result is fully determinable from the
// text: a range needs BOTH endpoints present AND const-foldable to a scalar (an
// int/char/byte literal, possibly negated, through paren/group/ref wrappers); a
// repeat needs a const count. A runtime endpoint, an open-ended range, a
// runtime / mutated / opaque receiver (a runtime `Vec` / `String` / unstable local) --
// anything desugar cannot compose to a literal `Seq` structurally bails to the opaque
// term layer, while named receiver `Hit`s propagate. No guess is made in recognition.
//
// TEETH. The lowered `Bool` is a real value: `assert!((0..5).is_empty())` lowers
// to `Bool(false)` -> the obligation is z3-UNSAT (a wrong claim is REFUTED);
// `assert!((5..5).is_empty())` lowers to `Bool(true)` -> discharged.

use std::collections::BTreeMap;

use syn::{Expr, ExprLit, Lit, UnOp};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method;
use crate::sugar::method_family;
use crate::{bool_const, strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("is_empty", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "is_empty" || !call.args.is_empty() {
        return None;
    }
    Some(Box::new(IsEmptySugar {
        receiver: (*call.receiver).clone(),
        fallback: expr.clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
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
    receiver: Expr,
    fallback: Expr,
    let_inits: BTreeMap<String, Expr>,
}

impl Sugar for IsEmptySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> = stable
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .chain(
                self.let_inits
                    .iter()
                    .map(|(name, init)| (name.clone(), init)),
            )
            .collect();
        if let Some(value) = literal_empty_without_elements(&self.receiver) {
            debug!(
                target: "sugar_lift_rust_tests::sugar::is_empty",
                value,
                "resolved range is_empty stdlib axiom to a ground bool"
            );
            return Outcome::Dug(Desugared::Term(bool_const(value)));
        }
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let value = match build_composite(&self.receiver, &fcx).desugar(ctx) {
            Outcome::Dug(d) => match d.into_seq() {
                Some(seq) => seq.is_empty(),
                None => return self.fallback_method(ctx, &fcx),
            },
            Outcome::Hit(Effect::Unsupported { reason })
                if reason == EMPTY_DOMAIN_REASON
                    && method_family::literal_sequence_static_len_in_scope(
                        &self.receiver,
                        &let_inits,
                        ctx.scope,
                    ) == Some(0) =>
            {
                true
            }
            hit if hit.is_structural_bail() => {
                match method_family::build_literal_sequence_composite(&self.receiver, &fcx) {
                    Some(inner) => match inner.desugar(ctx) {
                        Outcome::Dug(d) => match d.into_seq() {
                            Some(seq) => seq.is_empty(),
                            None => return self.fallback_method(ctx, &fcx),
                        },
                        Outcome::Hit(Effect::Unsupported { reason })
                            if reason == EMPTY_DOMAIN_REASON =>
                        {
                            true
                        }
                        hit if hit.is_structural_bail() => return self.fallback_method(ctx, &fcx),
                        hit => return hit,
                    },
                    None => {
                        if let Some(static_len) =
                            method_family::literal_collection_adapter_static_len_in_scope(
                                &self.receiver,
                                &let_inits,
                                ctx.scope,
                            )
                        {
                            match self.verify_static_len_source(&static_len.source, ctx, &fcx) {
                                Ok(true) => static_len.len == 0,
                                Ok(false) => return self.fallback_method(ctx, &fcx),
                                Err(hit) => return hit,
                            }
                        } else {
                            return self.fallback_method(ctx, &fcx);
                        }
                    }
                }
            }
            hit => return hit,
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::is_empty",
            value,
            "resolved literal-sequence is_empty stdlib axiom to a ground bool"
        );
        Outcome::Dug(Desugared::Term(bool_const(value)))
    }
}

impl IsEmptySugar {
    fn verify_static_len_source(
        &self,
        source: &Expr,
        ctx: &SugarCtx,
        fcx: &SugarBuildCtx,
    ) -> Result<bool, Outcome> {
        let candidate = method_family::build_literal_sequence_composite(source, fcx)
            .unwrap_or_else(|| build_composite(source, fcx));
        match candidate.desugar(ctx) {
            Outcome::Dug(d) => Ok(d.into_seq().is_some()),
            Outcome::Hit(Effect::Unsupported { reason }) if reason == EMPTY_DOMAIN_REASON => {
                Ok(true)
            }
            hit if hit.is_structural_bail() => Ok(false),
            hit => Err(hit),
        }
    }

    fn fallback_method(&self, ctx: &SugarCtx, fcx: &SugarBuildCtx) -> Outcome {
        match method::recognize(&self.fallback, fcx) {
            Some(fallback) => fallback.desugar(ctx),
            None => Outcome::from_opt(None),
        }
    }
}

fn literal_empty_without_elements(expr: &Expr) -> Option<bool> {
    match strip_refs_groups(expr) {
        Expr::Range(range) => range_is_empty(range),
        _ => None,
    }
}
