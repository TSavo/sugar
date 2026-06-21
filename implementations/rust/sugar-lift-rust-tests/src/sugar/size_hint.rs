// SPDX-License-Identifier: Apache-2.0
//
// `size_hint` — a tuple-valued PRODUCER for the shared `tuple_decomp` decomposition.
//
// `(a..b).size_hint()` / `(a..=b).size_hint()` over const integer endpoints is the exact
// pair `(n, Some(n))` where `n` is the element count (half-open: `max(b - a, 0)`; inclusive:
// `0` if `b < a` else `b - a + 1`). We return the two COMPONENT source exprs -- the
// lower-bound int `n` and the upper-bound `Some(n)` -- so `tuple_decomp` compares them
// component-wise to the literal tuple with REAL teeth: a wrong count is int-UNSAT, a wrong
// upper (`Some(m)` / `None`) is Option-ADT-UNSAT. We do NOT build a local `(n, Some(n))`
// tuple (which would lower to a teethless `literal:Tuple` congruence constant).
//
// EXACT-OR-NONE: only a range with BOTH endpoints const-foldable to an integer AND a count
// that fits `usize` (otherwise real `size_hint` is `(usize::MAX, None)`, not `(n, Some(n))`).
// A runtime endpoint, an open-ended range, or an overflowing count -> `None` -> tuple_decomp
// declines (the ordinary equality path applies; no regression, never a wrong fold).

use syn::{Expr, ExprLit, ExprMethodCall, Lit, UnOp};

use crate::strip_refs_groups;

/// The `(lower, upper)` component source exprs of a const-range `size_hint()`, or `None`.
pub(crate) fn decomposed_component_exprs(call: &ExprMethodCall) -> Option<Vec<Expr>> {
    if call.method != "size_hint" || !call.args.is_empty() {
        return None;
    }
    let Expr::Range(range) = strip_refs_groups(&call.receiver) else {
        return None;
    };
    let start = endpoint_const_scalar(range.start.as_deref()?)?;
    let end = endpoint_const_scalar(range.end.as_deref()?)?;
    let n: i128 = match range.limits {
        // `a..b`: count is `max(b - a, 0)`.
        syn::RangeLimits::HalfOpen(_) => end.checked_sub(start)?.max(0),
        // `a..=b`: count is `0` when `b < a`, else `b - a + 1`.
        syn::RangeLimits::Closed(_) => {
            if end < start {
                0
            } else {
                end.checked_sub(start)?.checked_add(1)?
            }
        }
    };
    // A count beyond `usize` is `(usize::MAX, None)` in real `size_hint`, not `(n, Some(n))`
    // -- decline rather than fold a wrong pair.
    if n > usize::MAX as i128 {
        return None;
    }
    // Component exprs: the lower bound `n` and the upper bound `Some(n)`. They are rebuilt by
    // tuple_decomp via the factory (so `Some(n)` grounds to the `opt:some` ADT, with teeth).
    let lower = syn::parse_str::<Expr>(&n.to_string()).ok()?;
    let upper = syn::parse_str::<Expr>(&format!("Some({n})")).ok()?;
    Some(vec![lower, upper])
}

/// A const integer range endpoint: an int/byte literal, optionally negated, through
/// paren/group/ref wrappers. `None` for anything non-const.
fn endpoint_const_scalar(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<i128>().ok(),
        Expr::Lit(ExprLit {
            lit: Lit::Byte(b), ..
        }) => Some(i128::from(b.value())),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => {
            endpoint_const_scalar(&u.expr).and_then(i128::checked_neg)
        }
        _ => None,
    }
}
