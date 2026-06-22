// SPDX-License-Identifier: Apache-2.0
//
// `RangeContainsSugar`: `(a..b).contains(&x)` / `(a..=b).contains(&x)` (and the open-ended
// variants) over a range literal with const INTEGER endpoints and a const integer argument
// is value sugar -- membership is determined ENTIRELY by the program text:
//
//   * `a..b`  contains x  iff  a <= x < b,
//   * `a..=b` contains x  iff  a <= x <= b,
//   * `a..`   contains x  iff  a <= x,
//   * `..b`   contains x  iff  x < b,
//   * `..=b`  contains x  iff  x <= b,
//   * `..`    contains x  always.
//
// We COMPUTE the bool at recognize time and lower it to a ground `Bool` const that z3
// reasons about directly (a real value, NOT an opaque `method:contains` EUF var with no
// teeth). TEETH: `assert!((1..5).contains(&3))` -> `Bool(true)` discharged;
// `assert!((1..5).contains(&5))` -> `Bool(false)` -> z3-UNSAT (a wrong claim is REFUTED).
//
// EXACT-OR-NONE. We claim ONLY when the receiver is an INLINE range literal whose present
// endpoints AND the argument all const-fold to an INTEGER scalar (an int/byte literal,
// possibly negated, through paren/group/ref wrappers). A runtime endpoint/argument, a
// let-bound range path (`let r = ..; r.contains(..)` -- fires once the let-desugar lever
// lands), a CHAR range (left to the char lane), or a non-literal argument returns `None`,
// so the generic method machinery keeps its opaque handling (no regression, never a guess).

use syn::{Expr, ExprLit, ExprRange, Lit, RangeLimits, UnOp};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{bool_const, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("range_contains", SugarRole::Term, recognize);

fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "contains" || call.args.len() != 1 {
        return None;
    }
    let Expr::Range(range) = strip_refs_groups(&call.receiver) else {
        return None;
    };
    let x = int_scalar(&call.args[0])?;
    let value = range_contains(range, x)?;
    Some(Box::new(RangeContainsSugar { value }))
}

/// Membership of `x` in a range literal whose present endpoints const-fold to integer
/// scalars. `None` if an endpoint is present but not const-foldable -- left for the generic
/// machinery (never a guess).
fn range_contains(range: &ExprRange, x: i128) -> Option<bool> {
    let start = match range.start.as_deref() {
        None => None,
        Some(e) => Some(int_scalar(e)?),
    };
    let end = match range.end.as_deref() {
        None => None,
        Some(e) => Some(int_scalar(e)?),
    };
    let lower_ok = start.map_or(true, |s| x >= s);
    let upper_ok = match (end, range.limits) {
        (Some(e), RangeLimits::HalfOpen(_)) => x < e,
        (Some(e), RangeLimits::Closed(_)) => x <= e,
        // open upper bound (`a..` / `..`): no upper constraint.
        (None, _) => true,
    };
    Some(lower_ok && upper_ok)
}

/// Const-fold a range endpoint / argument to its exact INTEGER scalar: an int/byte literal,
/// optionally negated, through paren/group/ref wrappers. CHAR is intentionally EXCLUDED
/// (char ranges are the char lane's). Anything else is `None` -> the caller declines.
fn int_scalar(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<i128>().ok(),
        Expr::Lit(ExprLit {
            lit: Lit::Byte(b), ..
        }) => Some(i128::from(b.value())),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => {
            int_scalar(&u.expr).and_then(i128::checked_neg)
        }
        _ => None,
    }
}

struct RangeContainsSugar {
    value: bool,
}

impl Sugar for RangeContainsSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::range_contains",
            value = self.value,
            "resolved range contains stdlib axiom to a ground bool"
        );
        Outcome::Dug(Desugared::Term(bool_const(self.value)))
    }
}
