// SPDX-License-Identifier: Apache-2.0
//
// `IsEmptySugar`: `.is_empty()` over a range literal with const integer/char
// endpoints, or over an array / repeat literal, is value sugar. The emptiness is
// determined ENTIRELY by the program text:
//
//   * a half-open `a..b` is empty iff `a >= b`,
//   * an inclusive `a..=b` is empty iff `a > b`,
//   * an array literal `[..]` is empty iff it has no elements,
//   * a repeat `[x; N]` is empty iff `N == 0`.
//
// So we COMPUTE the bool at recognize time and lower it to a ground `Bool` const
// that z3 reasons about directly (a real value, NOT an opaque `method:is_empty`
// EUF var with no teeth).
//
// EXACT-OR-NONE. We claim ONLY when the result is fully determinable from the
// text: a range needs BOTH endpoints present AND const-foldable to a scalar (an
// int/char/byte literal, possibly negated, through paren/group/ref wrappers); a
// repeat needs a const count. A runtime endpoint, an open-ended range, a
// non-literal receiver (a path / `Vec` / `String` / slice local) -- anything we
// cannot decide -- returns `None`, so the generic method machinery keeps the
// existing opaque handling (no regression, never a guess).
//
// TEETH. The lowered `Bool` is a real value: `assert!((0..5).is_empty())` lowers
// to `Bool(false)` -> the obligation is z3-UNSAT (a wrong claim is REFUTED);
// `assert!((5..5).is_empty())` lowers to `Bool(true)` -> discharged.

use syn::{Expr, ExprLit, Lit, UnOp};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{bool_const, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "is_empty",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "is_empty" || !call.args.is_empty() {
        return None;
    }
    let value = match strip_refs_groups(&call.receiver) {
        Expr::Range(range) => range_is_empty(range)?,
        Expr::Array(arr) => arr.elems.is_empty(),
        Expr::Repeat(rep) => endpoint_const_scalar(&rep.len)? == 0,
        _ => return None,
    };
    Some(Box::new(IsEmptySugar { value }))
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
    value: bool,
}

impl Sugar for IsEmptySugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::is_empty",
            value = self.value,
            "resolved range/array is_empty stdlib axiom to a ground bool"
        );
        Outcome::Dug(Desugared::Term(bool_const(self.value)))
    }
}
