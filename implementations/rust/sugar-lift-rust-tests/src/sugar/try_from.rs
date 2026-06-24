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
// integer argument determined by the program text: a literal, a primitive MIN/MAX
// const path, or a stable let-bound scalar. The helper carries signed/unsigned
// 128-bit values exactly, so `u128::MAX` stays `u128::MAX` and never clamps into
// the signed i128 lane. A non-integer destination (`String`/`char`/`NonZero`/a
// user type), an inferred `TryFrom::try_from` with no spelled destination, or a
// runtime/non-literal arg -> `None`, so existing handling stands.
//
// TEETH. `u8::try_from(255u16)` -> `Ok(255)` (`.unwrap()` -> 255, discharged);
// `u8::try_from(256u16)` -> `Err(_)` (`.is_err()` -> true; `.unwrap()` panics).

use std::rc::Rc;

use syn::{Expr, ExprCall};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{exact_int_value, primitive_int_kind, ExactInt, IntKind};
use crate::sugar::monadic::{err_term, ok_term};
use crate::{expr_head_key, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};
use sugar_ir_symbolic::{num, Term};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("try_from", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let _ = fcx;
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let dst = try_from_destination(&call.func)?;
    primitive_int_kind(&dst)?;
    Some(Box::new(TryFromSugar {
        func_key: expr_head_key(&call.func),
        arg: SugarBody::term(&call.args[0], fcx),
        folded: try_from_fold_inputs(call, Some(fcx)),
    }))
}

/// Does this call fold to a `Result` (an integer-destination `try_from` over a
/// scalar that resolves to an integer)? Exposed so `result_predicate` /
/// `option_unwrap` can recognize the receiver without re-deriving the shape.
/// `fcx`: `Some` resolves a let-bound / const-path argument to its value (see
/// `exact_int_value`); `None` is the inline-literal-only check (syntactic callers
/// with no scope, e.g. the width-hint path).
pub(crate) fn folds_to_result(call: &ExprCall, fcx: Option<&SugarBuildCtx>) -> bool {
    try_from_fold_inputs(call, fcx).is_some()
}

/// The `(destination kind, source value)` of a foldable integer `try_from` call,
/// or `None` if it is not one.
fn try_from_fold_inputs(
    call: &ExprCall,
    fcx: Option<&SugarBuildCtx>,
) -> Option<(IntKind, ExactInt)> {
    if call.args.len() != 1 {
        return None;
    }
    let dst = try_from_destination(&call.func)?;
    let kind = primitive_int_kind(&dst)?;
    let value = exact_int_value(&call.args[0], fcx)?;
    Some((kind, value))
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

struct TryFromSugar {
    func_key: String,
    arg: SugarBody<TermFloor>,
    folded: Option<(IntKind, ExactInt)>,
}

impl Sugar for TryFromSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some((kind, value)) = self.folded {
            let in_range = value.fits_kind(kind);
            debug!(
                target: "sugar_lift_rust_tests::sugar::try_from",
                value = %value.label(),
                dst = kind.name,
                in_range = in_range,
                "resolved TryFrom range check stdlib axiom to Ok/Err"
            );
            let term = if in_range {
                let value = value
                    .term_for_kind(kind)
                    .unwrap_or_else(|| try_from_gap("in-range TryFrom value did not materialize"));
                ok_term(value)
            } else {
                // `TryFromIntError` carries no observable value; the Err discriminant
                // is what `is_err`/`unwrap` read. A placeholder inner keeps it well-sorted.
                err_term(num(0))
            };
            Outcome::Complete(Desugared::Term(term))
        } else {
            self.fallback_call(ctx)
        }
    }
}

impl TryFromSugar {
    fn fallback_call(&self, ctx: &SugarCtx) -> Outcome {
        let arg = match self.arg.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| try_from_gap("TryFrom argument reduced to non-Term")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("call:{}", self.func_key),
            args: vec![arg],
        })))
    }
}

fn try_from_gap(reason: &str) -> ! {
    panic!("try_from did not reach a lawful floor: {reason}")
}
