// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Sequence projection for authenticated `Range { start, end }` construction.
// The generic range-construction owner emits field constraints; this consumer
// door instead asks those same authenticated TERM children for their bounds and
// delegates finite integer enumeration to the literal-range sequence owner.

use syn::Expr;

use crate::sugar::claim::SugarRole;
use crate::sugar::factory::{AccountedSugar, FactoryAuditSeed, SugarBuildCtx};
use crate::sugar::literal::finite_integer_range_sequence;
use crate::sugar::range_construct::AuthenticatedRangeFields;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const OWNER: &str = "range_sequence_projection";

/// Build the consumer-specific sequence projection without adding a second
/// generic Composite claim for the same Range syntax. The accounted wrapper
/// keeps the exact owner visible in factory testimony.
pub(crate) fn build(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let frag = SourceFragment::expr(expr, "<range-sequence-projection>");
    let range = AuthenticatedRangeFields::recognize(&frag, fcx)?;
    if range.inclusive() != Some(false) {
        return None;
    }
    let seed = FactoryAuditSeed::expr(expr, SugarRole::Composite, Some(OWNER), Vec::new());
    Some(AccountedSugar::new(
        seed,
        Box::new(RangeSequenceProjection { range }),
    ))
}

struct RangeSequenceProjection {
    range: AuthenticatedRangeFields,
}

impl Sugar for RangeSequenceProjection {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let inclusive = self
            .range
            .inclusive()
            .expect("range sequence projection admitted a non-finite range kind");
        let fields = match self.range.reduce(ctx) {
            Ok(fields) => fields,
            Err(effect) => return Outcome::Incomplete(effect),
        };
        let start = fields
            .iter()
            .find(|(name, _)| name == "start")
            .map(|(_, term)| term)
            .unwrap_or_else(|| panic!("range sequence projection lost authenticated start field"));
        let end = fields
            .iter()
            .find(|(name, _)| name == "end")
            .map(|(_, term)| term)
            .unwrap_or_else(|| panic!("range sequence projection lost authenticated end field"));
        match finite_integer_range_sequence(start, end, inclusive) {
            Ok(sequence) => Outcome::Complete(Desugared::Seq(sequence)),
            Err(reason) => Outcome::Incomplete(Effect::LiteralDomain {
                reason: reason.to_string(),
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use syn::{Expr, Item};

    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::{
        sugar_ctx_with_factory_audits, FactoryAuditLog, FactoryDisposition, FloatWidthScope,
        LiftOptions, ReductionCtx, TemporalPlan, TemporalScope,
    };

    // Refusal twin: the Range shape alone is not authority. Exercise the real
    // production projection door directly so this tooth stops at the boundary
    // it owns instead of being preempted by a later callsite gap.
    #[test]
    fn runtime_bound_refuses_at_range_sequence_projection() {
        let range: Expr = syn::parse_str("Range { start, end: 10 }").expect("parse range");
        let runtime_start: Expr =
            syn::parse_str("std::env::args().count()").expect("parse runtime bound");
        let scope = TemporalScope::new("range-sequence-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let mut let_inits = BTreeMap::new();
        let_inits.insert("start".to_string(), &runtime_start);
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = build(&range, &fcx).expect("Range struct must reach projection owner");

        let items = Vec::<Item>::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let audits = FactoryAuditLog::default();
        let ctx = sugar_ctx_with_factory_audits(
            &scope,
            &options,
            &reducer,
            &mut float_widths,
            0,
            Some(&audits),
        );

        assert!(
            matches!(node.desugar(&ctx), Outcome::Incomplete(_)),
            "a runtime-selected Range bound must not become a sequence"
        );
        let audits = audits.into_inner();
        assert!(
            audits.iter().any(|audit| {
                audit.requested_role == "Composite"
                    && audit.selected == Some(OWNER)
                    && audit.disposition == FactoryDisposition::Effect
                    && audit
                        .reason
                        .as_deref()
                        .is_some_and(|reason| reason.contains("unknown iterator consumption"))
            }),
            "the exact projection owner must loudly refuse the unauthenticated bound: {audits:?}"
        );
    }
}
