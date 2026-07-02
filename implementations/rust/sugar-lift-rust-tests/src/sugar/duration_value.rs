// SPDX-License-Identifier: Apache-2.0
//
// `DurationValueSugar`: the CarrierEmbedding floor for `std::time::Duration`
// values that are source-closed and canonical. Duration is not a peer SMT sort
// here; it is a refinement of the canonical Int total-nanoseconds carrier.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, gt, gte, lt, lte, ne, num, Formula, Term};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    const_eval, const_fold_int_term, token_key, Desugared, Effect, Outcome, RelationOp, Sugar,
    SugarCtx,
};

const NANOS_PER_SEC: i128 = 1_000_000_000;
pub(crate) const DURATION_TERM_CTOR: &str = "duration:Duration";

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("duration_value", &["const_path", "path", "call"], recognize);

fn recognize(
    frag: &SourceFragment,
    _fcx: &crate::sugar::factory::SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    Some(Box::new(DurationValueSugar {
        decision: duration_decision_from_frag(frag)?,
    }))
}

struct DurationValueSugar {
    decision: DurationDecision,
}

impl Sugar for DurationValueSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        match &self.decision {
            DurationDecision::Complete(term) => Outcome::Complete(Desugared::Term(Rc::clone(term))),
            DurationDecision::Refused { boundary, reason } => {
                Outcome::Incomplete(Effect::DurationCarrierEmbedding {
                    boundary: boundary.clone(),
                    reason: reason.clone(),
                })
            }
        }
    }
}

enum DurationDecision {
    Complete(Rc<Term>),
    Refused { boundary: String, reason: String },
}

fn duration_decision_from_frag(frag: &SourceFragment) -> Option<DurationDecision> {
    let frag = frag.strip_refs_groups();
    if let Some(path) = frag.path_full_name() {
        return duration_path_term(&path).map(DurationDecision::Complete);
    }
    if frag.observed() != "Call" {
        return None;
    }
    let func = frag.call_func()?;
    let full_path = func.path_full_name()?;
    let (ty_name, ctor_name) = duration_path_parts(&full_path)?;
    if ty_name != "Duration" {
        return None;
    }
    let boundary = token_key(frag.as_expr()?);
    let args = frag
        .call_args()
        .iter()
        .map(arg_u128_const)
        .collect::<Option<Vec<u128>>>()?;
    let result = match (ctor_name.as_str(), args.as_slice()) {
        ("new", [secs, nanos]) => {
            let secs = i128::try_from(*secs).ok()?;
            let nanos = i128::try_from(*nanos).ok()?;
            if !(0..NANOS_PER_SEC).contains(&nanos) {
                return Some(DurationDecision::Refused {
                    boundary,
                    reason: format!(
                        "Duration CarrierEmbedding non-canonical constructor nanos={nanos}; \
                         expected 0 <= nanos < {NANOS_PER_SEC}"
                    ),
                });
            }
            secs.checked_mul(NANOS_PER_SEC)?.checked_add(nanos)?
        }
        ("from_secs", [secs]) => i128::try_from(*secs).ok()?.checked_mul(NANOS_PER_SEC)?,
        ("from_mins", [mins]) => duration_unit_nanos(*mins, 60)?,
        ("from_hours", [hours]) => duration_unit_nanos(*hours, 60 * 60)?,
        ("from_days", [days]) => duration_unit_nanos(*days, 24 * 60 * 60)?,
        ("from_weeks", [weeks]) => duration_unit_nanos(*weeks, 7 * 24 * 60 * 60)?,
        ("from_millis", [millis]) => i128::try_from(*millis).ok()?.checked_mul(1_000_000)?,
        ("from_micros", [micros]) => i128::try_from(*micros).ok()?.checked_mul(1_000)?,
        ("from_nanos", [nanos]) => i128::try_from(*nanos).ok()?,
        ("from_nanos_u128", [nanos]) => i128::try_from(*nanos).ok()?,
        _ => return None,
    };
    Some(DurationDecision::Complete(duration_term_from_total_nanos(
        result,
    )?))
}

fn duration_unit_nanos(value: u128, seconds_per_unit: i128) -> Option<i128> {
    i128::try_from(value)
        .ok()?
        .checked_mul(seconds_per_unit)?
        .checked_mul(NANOS_PER_SEC)
}

fn duration_path_term(path: &str) -> Option<Rc<Term>> {
    let (ty_name, assoc_name) = duration_path_parts(path)?;
    (ty_name == "Duration" && assoc_name == "ZERO").then(|| duration_term(0, 0))
}

fn duration_path_parts(path: &str) -> Option<(String, String)> {
    let segs: Vec<&str> = path.split("::").collect();
    (segs.len() >= 2).then(|| {
        (
            segs[segs.len() - 2].to_string(),
            segs[segs.len() - 1].to_string(),
        )
    })
}

fn arg_u128_const(frag: &SourceFragment) -> Option<u128> {
    let expr = frag.strip_refs_groups().as_expr()?;
    const_eval(expr, &BTreeMap::new())?.as_u128()
}

pub(crate) fn duration_total_nanos_from_expr(expr: &syn::Expr) -> Option<i128> {
    let frag = SourceFragment::expr(expr, "<duration-carrier>");
    match duration_decision_from_frag(&frag)? {
        DurationDecision::Complete(term) => duration_total_nanos_from_term(&term),
        DurationDecision::Refused { .. } => None,
    }
}

pub(crate) fn duration_term_from_total_nanos(total: i128) -> Option<Rc<Term>> {
    if total < 0 {
        return None;
    }
    let secs = total.checked_div(NANOS_PER_SEC)?;
    let nanos = total.checked_rem(NANOS_PER_SEC)?;
    u64::try_from(secs).ok()?;
    Some(duration_term(secs, nanos))
}

pub(crate) fn duration_term(secs: i128, nanos: i128) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: DURATION_TERM_CTOR.to_string(),
        args: vec![num(secs), num(nanos)],
    })
}

pub(crate) fn duration_total_nanos_from_term(term: &Rc<Term>) -> Option<i128> {
    let (secs, nanos) = duration_parts_from_term(term)?;
    if !(0..NANOS_PER_SEC).contains(&nanos) {
        return None;
    }
    secs.checked_mul(NANOS_PER_SEC)?.checked_add(nanos)
}

fn duration_parts_from_term(term: &Rc<Term>) -> Option<(i128, i128)> {
    let Term::Ctor { name, args } = term.as_ref() else {
        return None;
    };
    if name != DURATION_TERM_CTOR || args.len() != 2 {
        return None;
    }
    Some((
        const_fold_int_term(&args[0])?,
        const_fold_int_term(&args[1])?,
    ))
}

pub(crate) fn duration_relation_atom(
    lhs: &Rc<Term>,
    rhs: &Rc<Term>,
    op: RelationOp,
) -> Option<Rc<Formula>> {
    let (lhs_secs, lhs_nanos) = duration_parts_from_term(lhs)?;
    let (rhs_secs, rhs_nanos) = duration_parts_from_term(rhs)?;
    let lhs_total = duration_total_nanos_from_term(lhs)?;
    let rhs_total = duration_total_nanos_from_term(rhs)?;
    let relation = match op {
        RelationOp::Eq => eq(num(lhs_total), num(rhs_total)),
        RelationOp::Ne => ne(num(lhs_total), num(rhs_total)),
        RelationOp::Lt => lt(num(lhs_total), num(rhs_total)),
        RelationOp::Le => lte(num(lhs_total), num(rhs_total)),
        RelationOp::Gt => gt(num(lhs_total), num(rhs_total)),
        RelationOp::Ge => gte(num(lhs_total), num(rhs_total)),
    };
    Some(and_(vec![
        gte(num(lhs_secs), num(0)),
        gte(num(rhs_secs), num(0)),
        gte(num(lhs_nanos), num(0)),
        lt(num(lhs_nanos), num(NANOS_PER_SEC)),
        gte(num(rhs_nanos), num(0)),
        lt(num(rhs_nanos), num(NANOS_PER_SEC)),
        relation,
    ]))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn total_nanos(src: &str) -> Option<i128> {
        let expr = syn::parse_str::<syn::Expr>(src).expect("duration expr parses");
        duration_total_nanos_from_expr(&expr)
    }

    #[test]
    fn recognizes_corpus_native_duration_constructors() {
        assert_eq!(total_nanos("Duration::from_secs(2)"), Some(2_000_000_000));
        assert_eq!(
            total_nanos("Duration::from_millis(1500)"),
            Some(1_500_000_000)
        );
        assert_eq!(total_nanos("Duration::from_micros(1500)"), Some(1_500_000));
        assert_eq!(total_nanos("Duration::from_nanos(1500)"), Some(1_500));
        assert_eq!(total_nanos("Duration::from_nanos_u128(1500)"), Some(1_500));
        assert_eq!(total_nanos("Duration::from_mins(1)"), Some(60_000_000_000));
        assert_eq!(
            total_nanos("Duration::from_hours(1)"),
            Some(3_600_000_000_000)
        );
        assert_eq!(
            total_nanos("Duration::from_days(1)"),
            Some(86_400_000_000_000)
        );
        assert_eq!(
            total_nanos("Duration::from_weeks(1)"),
            Some(604_800_000_000_000)
        );
    }

    #[test]
    fn rejects_total_nanos_beyond_u64_seconds() {
        assert_eq!(
            total_nanos("Duration::from_nanos_u128(18446744073709551616000000000u128)"),
            None
        );
    }
}
