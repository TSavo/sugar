// SPDX-License-Identifier: Apache-2.0
//
// `TryFromSugar`: `<DST as TryFrom<SRC>>::try_from(int-literal)` (and the
// `DST::try_from(int-literal)` / `<DST>::try_from(..)` spellings) over an integer
// destination type is value sugar. Whether the literal fits the destination
// range is decided ENTIRELY by the program text, so we RANGE-CHECK the literal at
// the destination type in the host and lower the concrete `Result`:
//
//   in range  -> `Ok(value)`   (the value is unchanged; try_from never truncates)
//   out range -> `Err(_)`      (a `TryFromIntError`; only the Err discriminant is
//                               observable -- the inner is a placeholder)
//
// This replaces the opaque `method:try_from` / `call:try_from` EUF var (no teeth)
// with the ADT-backed `res:ok`/`res:err`, so the EXISTING `option_unwrap`
// (`unwrap`/`expect` peel `res:ok` -> value, `res:err` -> panic) and the
// `result_predicate` (`is_ok`/`is_err`) get real teeth.
//
// EXACT-OR-NONE. We claim ONLY for an INTEGER destination type with a single
// integer-LITERAL argument (allowing a unary `-`, through paren/group/ref). A
// non-integer destination (`String`/`char`/`NonZero`/a user type), an inferred
// `TryFrom::try_from` with no spelled destination, a runtime/non-literal arg, or
// a source value that does not fit `i128` -> `None`, so the existing handling
// stands (no regression, never a guess).
//
// TEETH. `u8::try_from(255u16)` -> `Ok(255)` (`.unwrap()` -> 255, discharged);
// `u8::try_from(256u16)` -> `Err(_)` (`.is_err()` -> true; `.unwrap()` panics).

use syn::{Expr, ExprCall, ExprLit, Lit, UnOp};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::monadic::{err_term, ok_term};
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};
use sugar_ir_symbolic::num;

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "try_from",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    let (bounds, value) = try_from_fold_inputs(call)?;
    let in_range = value >= bounds.0 && value <= bounds.1;
    Some(Box::new(TryFromSugar { value, in_range }))
}

/// Does this call fold to a `Result` (an integer-destination `try_from` over an
/// integer literal)? Exposed so `result_predicate` can recognize the receiver
/// without re-deriving the shape.
pub(crate) fn folds_to_result(call: &ExprCall) -> bool {
    try_from_fold_inputs(call).is_some()
}

/// The `(destination bounds, source value)` of a foldable integer `try_from`
/// call, or `None` if it is not one.
fn try_from_fold_inputs(call: &ExprCall) -> Option<((i128, i128), i128)> {
    if call.args.len() != 1 {
        return None;
    }
    let dst = try_from_destination(&call.func)?;
    let bounds = int_dst_bounds(&dst)?;
    let value = scalar_int_value(&call.args[0])?;
    Some((bounds, value))
}

/// The spelled destination type of a `try_from` call:
///   `<DST as TryFrom<SRC>>::try_from`  /  `<DST>::try_from`  -> qself `DST`
///   `DST::try_from`                                          -> the `DST` segment
/// `None` when the final segment is not `try_from`, or the destination is the
/// bare trait `TryFrom` (an inferred destination we cannot pin).
fn try_from_destination(func: &Expr) -> Option<String> {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return None;
    };
    if path.path.segments.last()?.ident != "try_from" {
        return None;
    }
    if let Some(qself) = &path.qself {
        let syn::Type::Path(tp) = &*qself.ty else {
            return None;
        };
        return Some(tp.path.segments.last()?.ident.to_string());
    }
    if path.path.segments.len() < 2 {
        return None;
    }
    let dst = path.path.segments.iter().rev().nth(1)?.ident.to_string();
    // `TryFrom::try_from(..)` leaves the destination inferred -- not foldable.
    (dst != "TryFrom").then_some(dst)
}

/// The inclusive `(min, max)` value range of a primitive integer type, expressed
/// in `i128` (the lane our source value lives in). `None` for a non-integer type.
/// For the 128-bit types the bounds are clamped to the `i128` lane: a source
/// value that does not fit `i128` is already declined upstream, so any
/// representable `i128` source fits `i128`/`u128` exactly as Rust would decide.
fn int_dst_bounds(name: &str) -> Option<(i128, i128)> {
    let (signed, bits): (bool, u32) = match name {
        "i8" => (true, 8),
        "i16" => (true, 16),
        "i32" => (true, 32),
        "i64" => (true, 64),
        "i128" => (true, 128),
        "isize" => (true, isize::BITS),
        "u8" => (false, 8),
        "u16" => (false, 16),
        "u32" => (false, 32),
        "u64" => (false, 64),
        "u128" => (false, 128),
        "usize" => (false, usize::BITS),
        _ => return None,
    };
    if signed {
        if bits >= 128 {
            return Some((i128::MIN, i128::MAX));
        }
        let max = (1i128 << (bits - 1)) - 1;
        Some((-(1i128 << (bits - 1)), max))
    } else {
        if bits >= 128 {
            // Any non-negative `i128` source fits `u128` (and `i128` source can
            // never exceed `i128::MAX < u128::MAX`).
            return Some((0, i128::MAX));
        }
        let max = (1i128 << bits) - 1;
        Some((0, max))
    }
}

/// A closed integer-literal source value (`255u16`, `-1i32`, `256`), through a
/// unary `-` and paren/group/ref wrappers. `None` for a non-literal, a float, or
/// a value that does not fit `i128`.
fn scalar_int_value(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<i128>().ok(),
        Expr::Lit(ExprLit {
            lit: Lit::Byte(b), ..
        }) => Some(i128::from(b.value())),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => {
            scalar_int_value(&u.expr).and_then(i128::checked_neg)
        }
        _ => None,
    }
}

struct TryFromSugar {
    value: i128,
    in_range: bool,
}

impl Sugar for TryFromSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::try_from",
            value = self.value as i64,
            in_range = self.in_range,
            "resolved TryFrom range check stdlib axiom to Ok/Err"
        );
        let term = if self.in_range {
            ok_term(num(self.value))
        } else {
            // `TryFromIntError` carries no observable value; the Err discriminant
            // is what `is_err`/`unwrap` read. A placeholder inner keeps it well-sorted.
            err_term(num(0))
        };
        Outcome::Dug(Desugared::Term(term))
    }
}
