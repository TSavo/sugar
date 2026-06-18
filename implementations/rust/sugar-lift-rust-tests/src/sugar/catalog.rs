// SPDX-License-Identifier: Apache-2.0
//
// Sugar claim catalog and candidate resolution.

use syn::{Expr, Item};

use crate::sugar::claim::{
    ExprSugarClaim, ItemSugarClaim, SugarCandidate, SugarPriority, SugarRole,
};
use crate::sugar::factory::FactoryCtx;
use crate::sugar::{
    array_repeat, array_term, await_term, binop, block_term, call, cast_term, closure_adaptor,
    closure_term, conditional, const_block, control_flow_term, enumerate, field_term, filter,
    filter_map, fold, forall, impl_method, index, iter_terminal, iterator, literal, macro_term,
    map, match_node, match_scrutinee, method_call_term, monadic, path, range_term, raw_addr_term,
    reference_term, repeat_term, rev, skip, skip_while, statement_position, struct_term, take,
    take_while, term_literal, transparent_term, tuple_term, unary,
};

/// The unified expression-Sugar catalog. This is wiring only: each entry points at
/// metadata owned by the Sugar module itself.
const EXPR_CLAIMS: &[&ExprSugarClaim] = &[
    &monadic::EXPR_SUGAR,
    &term_literal::EXPR_SUGAR,
    &const_block::EXPR_SUGAR,
    &unary::EXPR_SUGAR,
    &path::EXPR_SUGAR,
    &call::EXPR_SUGAR,
    &array_term::EXPR_SUGAR,
    &tuple_term::EXPR_SUGAR,
    &repeat_term::EXPR_SUGAR,
    &struct_term::EXPR_SUGAR,
    &iter_terminal::EXPR_SUGAR,
    &method_call_term::EXPR_SUGAR,
    &await_term::EXPR_SUGAR,
    &reference_term::EXPR_SUGAR,
    &raw_addr_term::EXPR_SUGAR,
    &cast_term::EXPR_SUGAR,
    &range_term::EXPR_SUGAR,
    &field_term::EXPR_SUGAR,
    &index::EXPR_SUGAR,
    &binop::EXPR_SUGAR,
    &transparent_term::TERM_EXPR_SUGAR,
    &macro_term::EXPR_SUGAR,
    &closure_term::EXPR_SUGAR,
    &block_term::EXPR_SUGAR,
    &control_flow_term::TERM_EXPR_SUGAR,
    &transparent_term::COMPOSITE_EXPR_SUGAR,
    &conditional::EXPR_SUGAR,
    &match_node::EXPR_SUGAR,
    &forall::FOR_LOOP_EXPR_SUGAR,
    &array_repeat::EXPR_SUGAR,
    &control_flow_term::COMPOSITE_EXPR_SUGAR,
    &literal::EXPR_SUGAR,
    &iterator::EXPR_SUGAR,
    &rev::EXPR_SUGAR,
    &enumerate::EXPR_SUGAR,
    &filter::EXPR_SUGAR,
    &map::EXPR_SUGAR,
    &filter_map::EXPR_SUGAR,
    &skip::EXPR_SUGAR,
    &take::EXPR_SUGAR,
    &skip_while::EXPR_SUGAR,
    &take_while::EXPR_SUGAR,
    &fold::EXPR_SUGAR,
    &forall::FOR_EACH_EXPR_SUGAR,
    &closure_adaptor::EXPR_SUGAR,
    &match_scrutinee::EXPR_SUGAR,
    &closure_adaptor::VERDICT_EXPR_SUGAR,
    &statement_position::EXPR_SUGAR,
    &match_scrutinee::VERDICT_EXPR_SUGAR,
];

const ITEM_CLAIMS: &[&ItemSugarClaim] = &[&impl_method::ITEM_SUGAR];

const ALL_ROLES: &[SugarRole] = &[
    SugarRole::Term,
    SugarRole::Composite,
    SugarRole::StatementEffect,
    SugarRole::ClosureAdaptorVerdict,
    SugarRole::MatchScrutineeVerdict,
    SugarRole::StatementItem,
];

/// Ask every expression Sugar whether it handles this source site. Multiple
/// candidates are first-class; equal-priority candidates for the same role are not.
pub(crate) fn matching_expr_claims(expr: &Expr, fcx: &FactoryCtx) -> Vec<SugarCandidate> {
    let mut candidates: Vec<_> = EXPR_CLAIMS
        .iter()
        .filter_map(|claim| (*claim).candidate(expr, fcx))
        .collect();
    candidates.sort_by_key(|candidate| candidate.priority());
    assert_no_ambiguous_role_priority(&candidates);
    candidates
}

pub(crate) fn select_expr_role(
    candidates: Vec<SugarCandidate>,
    role: SugarRole,
) -> Option<SugarCandidate> {
    assert_no_ambiguous_role_priority(&candidates);
    candidates
        .into_iter()
        .find(|candidate| candidate.role() == role)
}

pub(crate) fn matching_item_claims(item: &Item, fcx: &FactoryCtx) -> Vec<SugarCandidate> {
    let mut candidates: Vec<_> = ITEM_CLAIMS
        .iter()
        .filter_map(|claim| (*claim).candidate(item, fcx))
        .collect();
    candidates.sort_by_key(|candidate| candidate.priority());
    assert_no_ambiguous_role_priority(&candidates);
    candidates
}

pub(crate) fn select_item_role(
    candidates: Vec<SugarCandidate>,
    role: SugarRole,
) -> Option<SugarCandidate> {
    assert_no_ambiguous_role_priority(&candidates);
    candidates
        .into_iter()
        .find(|candidate| candidate.role() == role)
}

fn assert_no_ambiguous_role_priority(candidates: &[SugarCandidate]) {
    for role in ALL_ROLES {
        for priority in [SugarPriority::Primary, SugarPriority::Fallback] {
            let names: Vec<_> = candidates
                .iter()
                .filter(|candidate| candidate.role() == *role && candidate.priority() == priority)
                .map(|candidate| candidate.name())
                .collect();
            if names.len() > 1 {
                panic!(
                    "ambiguous Sugar candidates for role {:?} at priority {:?}: {}",
                    role,
                    priority,
                    names.join(", ")
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use syn::Expr;

    use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
    use crate::sugar::factory::FactoryCtx;
    use crate::{LiftOptions, Outcome, Sugar, SugarCtx, TemporalPlan, TemporalScope};

    struct NoopSugar;

    impl Sugar for NoopSugar {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::from_opt(None)
        }
    }

    fn recognize(_: &Expr, _: &FactoryCtx) -> Option<Box<dyn Sugar>> {
        Some(Box::new(NoopSugar))
    }

    static FIRST: ExprSugarClaim =
        ExprSugarClaim::new("first", SugarRole::Term, SugarPriority::Primary, recognize);
    static SECOND: ExprSugarClaim =
        ExprSugarClaim::new("second", SugarRole::Term, SugarPriority::Primary, recognize);

    #[test]
    #[should_panic(
        expected = "ambiguous Sugar candidates for role Term at priority Primary: first, second"
    )]
    fn same_role_same_priority_candidates_are_invalid() {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = FactoryCtx {
            scope: &scope,
            options: &options,
            let_inits: &let_inits,
        };
        let expr: Expr = syn::parse_str("1").unwrap();
        let candidates = vec![
            FIRST.candidate(&expr, &fcx).unwrap(),
            SECOND.candidate(&expr, &fcx).unwrap(),
        ];

        let _ = super::select_expr_role(candidates, SugarRole::Term);
    }
}
