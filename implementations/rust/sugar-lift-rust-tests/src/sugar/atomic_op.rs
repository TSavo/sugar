// SPDX-License-Identifier: Apache-2.0
//
// `atomic_op`: an atomic read/modify method — `load` or
// `fetch_{min,max,nand,and,or,xor,add,sub}` over an atomic receiver — returns CONCURRENT
// STATE: a value produced by the runtime memory model, not determined by the source text.
// Asserting on it (`assert_eq!(COUNTER.load(Relaxed), 3)`) is genuine IO, OUTSIDE THE TEXT.
//
// We REFUSE it as a NAMED dragon ("atomic read/modify — outside-the-text concurrent
// state") instead of leaving the hollow opaque `method:load(..)` UNDECIDED. No better
// lifter could read concurrent memory state from source literals, so this is a SOURCE
// property (terminal Refusal, recognized by `refusal_disposition`), not a lifter gap —
// a more honest map. Refuse-side-safe: a refusal never false-discharges.
//
// PRECISION: the methods are gated by a memory-`Ordering` argument
// (`Relaxed`/`Acquire`/`Release`/`AcqRel`/`SeqCst`, `Ordering::X`, or an ordering
// variable), the universal shape of an atomic op, so a non-atomic same-named call is not
// over-refused. (`fetch_*` names are atomic-exclusive in any case.)

use syn::{Expr, ExprMethodCall};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::reasoned_hit;
use crate::Sugar;

/// The refusal reason. Carries the `atomic read/modify` marker `refusal_disposition`
/// recognizes as a terminal Refusal (a SOURCE property: runtime concurrent state).
pub(crate) const ATOMIC_REFUSE_REASON: &str =
    "atomic read/modify — outside-the-text concurrent state (`load`/`fetch_*`): the value \
     is runtime concurrent state, not a source literal; refused";

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("atomic_op", recognize);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !is_atomic_read_modify(call) {
        return None;
    }
    Some(reasoned_hit(ATOMIC_REFUSE_REASON.to_string()))
}

/// `load` / `fetch_{min,max,nand,and,or,xor,add,sub}` whose LAST argument is a memory
/// `Ordering` — the atomic read/modify shape.
fn is_atomic_read_modify(call: &ExprMethodCall) -> bool {
    let is_atomic_name = matches!(
        call.method.to_string().as_str(),
        "load"
            | "fetch_min"
            | "fetch_max"
            | "fetch_nand"
            | "fetch_and"
            | "fetch_or"
            | "fetch_xor"
            | "fetch_add"
            | "fetch_sub"
    );
    is_atomic_name && call.args.last().is_some_and(is_ordering_arg)
}

/// A memory-`Ordering` argument named explicitly: `Relaxed`/`Acquire`/`Release`/`AcqRel`/
/// `SeqCst`, or `Ordering::X` / `atomic::Ordering::X` (the last path segment is the variant).
/// These five are the complete std `Ordering` set, so the gate is precise — it does NOT
/// match an arbitrary `.load(<ident>)` (which would over-refuse a non-atomic look-alike).
/// A variable-ordering call (`a.load(ord)`) is left opaque rather than risk over-refusal;
/// it is a vanishingly rare corpus shape (the asserted loci all use named orderings).
fn is_ordering_arg(arg: &Expr) -> bool {
    let Expr::Path(path) = arg else {
        return false;
    };
    let Some(last) = path.path.segments.last() else {
        return false;
    };
    matches!(
        last.ident.to_string().as_str(),
        "Relaxed" | "Acquire" | "Release" | "AcqRel" | "SeqCst"
    )
}
