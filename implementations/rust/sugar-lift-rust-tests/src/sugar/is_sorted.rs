// SPDX-License-Identifier: Apache-2.0
//
// `IsSortedSugar`: `.is_sorted()` over a literal array -- directly, or behind an
// order-PRESERVING view/iter adaptor (`.iter()` / `.into_iter()` / `.iter_mut()`
// / `.copied()` / `.cloned()` / `.as_slice()` / `.by_ref()`) -- is value sugar.
// Sortedness is determined entirely by the literal elements, so we COMPUTE it at
// recognize time and lower a ground `Bool`, replacing the opaque
// `method:is_sorted` EUF var (which had no teeth).
//
// THE RULE. std `is_sorted` is the NON-STRICT consecutive-pair rule: sorted iff
// every adjacent pair `v[i] <= v[i+1]` (so `[1,2,2,9]` is sorted; `[1,3,2]` is
// not). The empty and single-element cases are trivially sorted (true).
//
// EXACT-OR-NONE. We claim ONLY when the receiver bottoms out to a literal array
// of CLOSED SCALAR elements (int/byte/char/bool, allowing a unary `-`), each of
// which folds to its exact ordering value (codepoint for `char`, 0/1 for `bool`).
// A runtime receiver, a non-literal element, the closure-bearing
// `is_sorted_by`/`is_sorted_by_key` (args present), or an order-CHANGING adaptor
// (e.g. `.rev()`) is NOT matched -> we decline, leaving the existing opaque
// handling (no regression, never a guess).
//
// TEETH. `[1,3,2].iter().is_sorted()` folds to `Bool(false)` -> asserting it is
// z3-UNSAT (REFUTED); `[1,2,2,9].iter().is_sorted()` -> `Bool(true)` ->
// discharged.

use syn::{Expr, ExprLit, Lit, UnOp};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    bool_const, scalar_literal_array_elems, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("is_sorted", SugarRole::Term, recognize);

fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    // Bare `is_sorted` only: `is_sorted_by`/`is_sorted_by_key` carry a closure
    // (args), which we do not evaluate here.
    if call.method != "is_sorted" || !call.args.is_empty() {
        return None;
    }
    let elems = literal_array_under_view(&call.receiver)?;
    let mut vals = Vec::with_capacity(elems.len());
    for e in &elems {
        vals.push(scalar_lit_value(&e)?);
    }
    // std `is_sorted`: non-strict consecutive pairs. Empty/single -> true.
    let sorted = vals.windows(2).all(|w| w[0] <= w[1]);
    Some(Box::new(IsSortedSugar { value: sorted }))
}

/// Peel order-preserving view/iter adaptors off the receiver down to a literal
/// array of closed scalar elements. `None` for a runtime receiver, a non-array,
/// or an order-changing adaptor (only the listed no-arg, order-preserving views
/// are peeled).
fn literal_array_under_view(expr: &Expr) -> Option<Vec<Expr>> {
    let stripped = strip_refs_groups(expr);
    if let Some(elems) = scalar_literal_array_elems(stripped) {
        return Some(elems);
    }
    if let Expr::MethodCall(call) = stripped {
        if call.args.is_empty()
            && matches!(
                call.method.to_string().as_str(),
                "iter" | "into_iter" | "iter_mut" | "copied" | "cloned" | "as_slice" | "by_ref"
            )
        {
            return literal_array_under_view(&call.receiver);
        }
    }
    None
}

/// The exact ordering value of a closed scalar literal element: the integer
/// value, the byte, the `char` codepoint, or `0`/`1` for a bool; through a unary
/// `-` and paren/group/ref wrappers. `scalar_literal_array_elems` already vetted
/// the shape, so this folds; `None` is the defensive bail (never a guess).
fn scalar_lit_value(expr: &Expr) -> Option<i128> {
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
        Expr::Lit(ExprLit {
            lit: Lit::Bool(b), ..
        }) => Some(i128::from(b.value)),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => {
            scalar_lit_value(&u.expr).and_then(i128::checked_neg)
        }
        _ => None,
    }
}

struct IsSortedSugar {
    value: bool,
}

impl Sugar for IsSortedSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::is_sorted",
            value = self.value,
            "resolved literal-array is_sorted stdlib axiom to a ground bool"
        );
        Outcome::Dug(Desugared::Term(bool_const(self.value)))
    }
}
