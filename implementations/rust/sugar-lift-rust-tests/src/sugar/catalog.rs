// SPDX-License-Identifier: Apache-2.0
//
// Sugar claim catalog and candidate resolution.

use std::cmp::Ordering;
use std::collections::BTreeMap;

use syn::{Expr, Item};

use crate::sugar::backstop::unsupported;
use crate::sugar::claim::{ExprSugarClaim, ItemSugarClaim, SugarCandidate, SugarRole};
use crate::sugar::factory::{AccountedSugar, FactoryAuditSeed, SugarBuildCtx};
use crate::sugar::{
    addr_of_mut, aggregate_decomp, array_repeat, array_term, array_try_from, assign_op,
    atomic_load, await_term, binop, block_term, bool_bitwise, bool_method, bound_path, call,
    cast_term, cell_refcell, cfg_select, chain, char_method, char_range_collect_string,
    char_range_filter_map, closure_iter_advance_body, closure_mutating_body,
    closure_opaque_accessor, closure_runtime_receiver, closure_term, closure_tls_accessor, collect,
    collection_literal, compute_float, concat_macro, conditional, const_block, const_if,
    const_item, const_path, constraint, control_flow_term, cstr, dormant_mut_ref,
    duration_accessor, dyn_any, enumerate, field_term, filter, filter_map, flat_map, flatten,
    float_literal_method, float_refinement, fold, for_each, for_loop_mutation, for_replay,
    forall_loop, format_args, format_macro, from_bool, function_map, identity_map, impl_method,
    index, infinity_eq, inspect, int_midpoint, int_pow, int_sqrt, integer_decode, intersperse,
    intersperse_collect_string, intersperse_concat, into, ip_addr, is_empty, is_sorted, iter_next,
    iter_terminal, iterator, kmerge, len, literal, literal_iterator_quantifier, literal_slice,
    loop_break_term, macro_assertion_surface, macro_term, map, match_node, match_scrutinee,
    matches_macro, maybe_uninit_new, maybe_uninit_zeroed, memchr, method, monadic, nonzero,
    offset_of, option_adaptor, option_predicate, option_unwrap, partition_point, path, peekable,
    primitive_int, ptr_metadata, range_accessor, range_bounds_contains, range_construct,
    range_contains, range_term, raw_addr_term, raw_pointer_arithmetic, reference_sequence,
    reference_term, regex_match, repeat_term, result_predicate, result_transpose_collect, rev,
    runtime_iterator_source, size_hint, sizeof, skip, skip_while, slice_accessor,
    slice_chunk_window, slice_index, slice_search, source_location, statement_async_future,
    statement_control_flow, statement_future_handoff, statement_loop_advance,
    statement_nested_assertion, statement_reflection, statement_runtime_expr, step_by, str_method,
    string_add, string_predicate, struct_term, take, take_while, term_literal, to_string,
    transparent_term, try_from, try_from_fn, try_map, tuple_decomp, tuple_term, unary,
    unsafe_memory, value_if, vec_literal, vec_macro, wrapping_neg, zip,
};
use crate::{FactoryCandidateAudit, Sugar};

/// The unified expression-Sugar catalog. This is wiring only: each entry points at
/// metadata owned by the Sugar module itself.
const EXPR_CLAIMS: &[&ExprSugarClaim] = &[
    &cfg_select::ASSERTION_SURFACE_EXPR_SUGAR,
    &tuple_decomp::ASSERTION_SURFACE_EXPR_SUGAR,
    &slice_search::ASSERTION_SURFACE_EXPR_SUGAR,
    &bound_path::TUPLE_PRODUCER_EXPR_SUGAR,
    &tuple_term::TUPLE_PRODUCER_EXPR_SUGAR,
    &integer_decode::TUPLE_PRODUCER_EXPR_SUGAR,
    &size_hint::TUPLE_PRODUCER_EXPR_SUGAR,
    &primitive_int::TUPLE_PRODUCER_EXPR_SUGAR,
    &infinity_eq::ASSERTION_SURFACE_EXPR_SUGAR,
    &char_range_filter_map::ASSERTION_SURFACE_EXPR_SUGAR,
    &peekable::ASSERTION_SURFACE_EXPR_SUGAR,
    &constraint::BOUNDED_LITERAL_MACRO_ASSERTION_SURFACE,
    &aggregate_decomp::ASSERTION_SURFACE_EXPR_SUGAR,
    &constraint::RELATION_MACRO_ASSERTION_SURFACE,
    &constraint::ASSERT_MACRO_ASSERTION_SURFACE,
    &macro_assertion_surface::EXPR_SUGAR,
    &constraint::BOUNDED_LITERAL_MACRO_SUGAR,
    &tuple_decomp::CONSTRAINT_EXPR_SUGAR,
    &infinity_eq::CONSTRAINT_EXPR_SUGAR,
    &constraint::RELATION_MACRO_SUGAR,
    &char_range_filter_map::EXPR_SUGAR,
    &constraint::ASSERT_MACRO_SUGAR,
    &constraint::IF_PANIC_SUGAR,
    &constraint::NO_PANIC_CALL_SUGAR,
    &assign_op::EXPR_SUGAR,
    &statement_runtime_expr::CONSTRAINT_EXPR_SUGAR,
    &bool_bitwise::CONSTRAINT_EXPR_SUGAR,
    &matches_macro::CONSTRAINT_EXPR_SUGAR,
    &literal_iterator_quantifier::CONSTRAINT_EXPR_SUGAR,
    &match_node::CONSTRAINT_EXPR_SUGAR,
    &match_scrutinee::CONSTRAINT_EXPR_SUGAR,
    &regex_match::CONSTRAINT_EXPR_SUGAR,
    &constraint::CFG_MACRO_SUGAR,
    &ip_addr::CONSTRAINT_EXPR_SUGAR,
    &char_method::CONSTRAINT_EXPR_SUGAR,
    &string_predicate::CONSTRAINT_EXPR_SUGAR,
    &float_refinement::CONSTRAINT_EXPR_SUGAR,
    &constraint::BOOL_EXPR_SUGAR,
    &monadic::EXPR_SUGAR,
    &monadic::COMPOSITE_EXPR_SUGAR,
    &cstr::EXPR_SUGAR,
    &term_literal::EXPR_SUGAR,
    &const_block::EXPR_SUGAR,
    &cell_refcell::EXPR_SUGAR,
    &unary::EXPR_SUGAR,
    &dormant_mut_ref::EXPR_SUGAR,
    &bound_path::CONSTRAINT_EXPR_SUGAR,
    &bound_path::EXPR_SUGAR,
    &nonzero::ASSOC_CONST_EXPR_SUGAR,
    &const_path::EXPR_SUGAR,
    &path::EXPR_SUGAR,
    &sizeof::EXPR_SUGAR,
    &nonzero::NEW_EXPR_SUGAR,
    &array_try_from::EXPR_SUGAR,
    &try_from::EXPR_SUGAR,
    &compute_float::EXPR_SUGAR,
    &float_literal_method::EXPR_SUGAR,
    &ptr_metadata::EXPR_SUGAR,
    &memchr::EXPR_SUGAR,
    &raw_addr_term::PTR_EQ_EXPR_SUGAR,
    &atomic_load::EXPR_SUGAR,
    &ip_addr::EXPR_SUGAR,
    &call::EXPR_SUGAR,
    &array_term::EXPR_SUGAR,
    &tuple_term::EXPR_SUGAR,
    &repeat_term::EXPR_SUGAR,
    &struct_term::EXPR_SUGAR,
    &result_transpose_collect::EXPR_SUGAR,
    &collect::EXPR_SUGAR,
    &iter_terminal::EXPR_SUGAR,
    &len::EXPR_SUGAR,
    &to_string::EXPR_SUGAR,
    &str_method::EXPR_SUGAR,
    &bool_method::EXPR_SUGAR,
    &char_method::EXPR_SUGAR,
    &char_range_collect_string::EXPR_SUGAR,
    &intersperse_collect_string::EXPR_SUGAR,
    &intersperse_concat::EXPR_SUGAR,
    &try_map::EXPR_SUGAR,
    &try_from_fn::EXPR_SUGAR,
    &maybe_uninit_new::EXPR_SUGAR,
    &maybe_uninit_zeroed::ASSUME_INIT_EXPR_SUGAR,
    &maybe_uninit_zeroed::MEM_ZEROED_EXPR_SUGAR,
    &unsafe_memory::EXPR_SUGAR,
    &slice_index::EXPR_SUGAR,
    &wrapping_neg::EXPR_SUGAR,
    &int_sqrt::EXPR_SUGAR,
    &int_midpoint::EXPR_SUGAR,
    &raw_pointer_arithmetic::EXPR_SUGAR,
    &primitive_int::EXPR_SUGAR,
    &into::EXPR_SUGAR,
    &from_bool::EXPR_SUGAR,
    &int_pow::EXPR_SUGAR,
    &option_adaptor::EXPR_SUGAR,
    &option_predicate::EXPR_SUGAR,
    &inspect::TERM_EXPR_SUGAR,
    &result_predicate::EXPR_SUGAR,
    &dyn_any::EXPR_SUGAR,
    &option_unwrap::EXPR_SUGAR,
    &partition_point::EXPR_SUGAR,
    &is_empty::EXPR_SUGAR,
    &is_sorted::EXPR_SUGAR,
    &slice_accessor::EXPR_SUGAR,
    &slice_search::EXPR_SUGAR,
    &duration_accessor::EXPR_SUGAR,
    &nonzero::GET_EXPR_SUGAR,
    &function_map::TERM_EXPR_SUGAR,
    &map::TERM_EXPR_SUGAR,
    &format_args::ESTIMATED_CAPACITY_EXPR_SUGAR,
    &range_accessor::EXPR_SUGAR,
    &range_bounds_contains::EXPR_SUGAR,
    &source_location::EXPR_SUGAR,
    &method::EXPR_SUGAR,
    &match_node::TERM_EXPR_SUGAR,
    &match_scrutinee::TERM_EXPR_SUGAR,
    &await_term::EXPR_SUGAR,
    &reference_term::EXPR_SUGAR,
    &raw_addr_term::EXPR_SUGAR,
    &cast_term::EXPR_SUGAR,
    &range_contains::EXPR_SUGAR,
    &range_term::EXPR_SUGAR,
    &range_construct::EXPR_SUGAR,
    &field_term::EXPR_SUGAR,
    &index::EXPR_SUGAR,
    &string_add::EXPR_SUGAR,
    &binop::EXPR_SUGAR,
    &const_if::EXPR_SUGAR,
    &value_if::EXPR_SUGAR,
    &transparent_term::TERM_EXPR_SUGAR,
    &format_macro::EXPR_SUGAR,
    &concat_macro::EXPR_SUGAR,
    &vec_macro::EXPR_SUGAR,
    &offset_of::EXPR_SUGAR,
    &addr_of_mut::EXPR_SUGAR,
    &macro_term::EXPR_SUGAR,
    &closure_term::EXPR_SUGAR,
    &block_term::EXPR_SUGAR,
    &loop_break_term::EXPR_SUGAR,
    &control_flow_term::TERM_EXPR_SUGAR,
    &transparent_term::COMPOSITE_EXPR_SUGAR,
    &bound_path::COMPOSITE_EXPR_SUGAR,
    &const_path::COMPOSITE_EXPR_SUGAR,
    &conditional::EXPR_SUGAR,
    &match_node::EXPR_SUGAR,
    &for_replay::EXPR_SUGAR,
    &for_loop_mutation::EXPR_SUGAR,
    &forall_loop::EXPR_SUGAR,
    &array_repeat::EXPR_SUGAR,
    &control_flow_term::COMPOSITE_EXPR_SUGAR,
    &literal_slice::EXPR_SUGAR,
    &vec_literal::EXPR_SUGAR,
    &collection_literal::EXPR_SUGAR,
    &literal::EXPR_SUGAR,
    &statement_future_handoff::COMPOSITE_EXPR_SUGAR,
    &runtime_iterator_source::EXPR_SUGAR,
    &kmerge::EXPR_SUGAR,
    &chain::EXPR_SUGAR,
    &flatten::EXPR_SUGAR,
    &flat_map::EXPR_SUGAR,
    &slice_chunk_window::EXPR_SUGAR,
    &iterator::EXPR_SUGAR,
    &iter_next::EXPR_SUGAR,
    &reference_sequence::EXPR_SUGAR,
    &rev::EXPR_SUGAR,
    &inspect::EXPR_SUGAR,
    &peekable::EXPR_SUGAR,
    &enumerate::EXPR_SUGAR,
    &zip::EXPR_SUGAR,
    &filter::EXPR_SUGAR,
    &identity_map::EXPR_SUGAR,
    &function_map::EXPR_SUGAR,
    &map::EXPR_SUGAR,
    &filter_map::EXPR_SUGAR,
    &intersperse::EXPR_SUGAR,
    &skip::EXPR_SUGAR,
    &take::EXPR_SUGAR,
    &step_by::EXPR_SUGAR,
    &skip_while::EXPR_SUGAR,
    &take_while::EXPR_SUGAR,
    &fold::EXPR_SUGAR,
    &for_each::EXPR_SUGAR,
    &closure_tls_accessor::EXPR_SUGAR,
    &closure_opaque_accessor::EXPR_SUGAR,
    &closure_iter_advance_body::EXPR_SUGAR,
    &closure_mutating_body::EXPR_SUGAR,
    &closure_runtime_receiver::EXPR_SUGAR,
    &statement_async_future::EXPR_SUGAR,
    &statement_control_flow::EXPR_SUGAR,
    &statement_future_handoff::EXPR_SUGAR,
    &statement_reflection::EXPR_SUGAR,
    &statement_loop_advance::EXPR_SUGAR,
    &statement_nested_assertion::EXPR_SUGAR,
    &unsafe_memory::STATEMENT_EXPR_SUGAR,
    &statement_runtime_expr::EXPR_SUGAR,
    &match_scrutinee::VERDICT_EXPR_SUGAR,
];

const ITEM_CLAIMS: &[&ItemSugarClaim] = &[&const_item::ITEM_SUGAR, &impl_method::ITEM_SUGAR];

pub(crate) fn build_expr_role(expr: &Expr, fcx: &SugarBuildCtx, role: SugarRole) -> Box<dyn Sugar> {
    let mut candidates = matching_expr_claims_for_role(expr, fcx, role);
    let selected_index = candidates
        .iter()
        .position(|candidate| candidate.role() == role);
    let candidate_audits = candidate_audits(&candidates, selected_index);
    let selected = selected_index.map(|index| candidates[index].name());
    let seed = FactoryAuditSeed::expr(expr, role, selected, candidate_audits);
    let node = match selected_index {
        Some(index) => candidates.swap_remove(index).into_node(),
        None => unsupported(seed.unresolved_reason()),
    };
    AccountedSugar::new(seed, node)
}

pub(crate) fn matching_expr_claims_for_role(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    role: SugarRole,
) -> Vec<SugarCandidate> {
    let mut candidates: Vec<_> = EXPR_CLAIMS
        .iter()
        .filter(|claim| claim.role() == role)
        .filter_map(|claim| (*claim).candidate(expr, fcx))
        .collect();
    order_candidates_or_panic(&mut candidates);
    candidates
}

pub(crate) fn build_item_role(item: &Item, fcx: &SugarBuildCtx, role: SugarRole) -> Box<dyn Sugar> {
    let mut candidates = matching_item_claims_for_role(item, fcx, role);
    let selected_index = candidates
        .iter()
        .position(|candidate| candidate.role() == role);
    let candidate_audits = candidate_audits(&candidates, selected_index);
    let selected = selected_index.map(|index| candidates[index].name());
    let seed = FactoryAuditSeed::item(item, role, selected, candidate_audits);
    let node = match selected_index {
        Some(index) => candidates.swap_remove(index).into_node(),
        None => unsupported(seed.unresolved_reason()),
    };
    AccountedSugar::new(seed, node)
}

pub(crate) fn matching_item_claims_for_role(
    item: &Item,
    fcx: &SugarBuildCtx,
    role: SugarRole,
) -> Vec<SugarCandidate> {
    let mut candidates: Vec<_> = ITEM_CLAIMS
        .iter()
        .filter(|claim| claim.role() == role)
        .filter_map(|claim| (*claim).candidate(item, fcx))
        .collect();
    order_candidates_or_panic(&mut candidates);
    candidates
}

fn candidate_audits(
    candidates: &[SugarCandidate],
    selected_index: Option<usize>,
) -> Vec<FactoryCandidateAudit> {
    candidates
        .iter()
        .enumerate()
        .map(|(index, candidate)| FactoryCandidateAudit {
            name: candidate.name(),
            role: format!("{:?}", candidate.role()),
            comes_before: candidate.comes_before().to_vec(),
            selected: selected_index == Some(index),
        })
        .collect()
}

fn order_candidates_or_panic(candidates: &mut Vec<SugarCandidate>) {
    if candidates.len() < 2 {
        return;
    }

    let role = candidates[0].role();
    let mut by_name = BTreeMap::new();
    for (index, candidate) in candidates.iter().enumerate() {
        if candidate.role() != role {
            panic!(
                "mixed Sugar roles in candidate ordering: {:?} and {:?}",
                role,
                candidate.role()
            );
        }
        if by_name.insert(candidate.name(), index).is_some() {
            panic!(
                "duplicate Sugar candidate name for role {:?}: {}",
                role,
                candidate.name()
            );
        }
    }

    let mut reach = vec![vec![false; candidates.len()]; candidates.len()];
    for (index, candidate) in candidates.iter().enumerate() {
        for target in candidate.comes_before() {
            if let Some(target_index) = by_name.get(target).copied() {
                reach[index][target_index] = true;
            }
        }
    }
    for left in 0..candidates.len() {
        for right in 0..candidates.len() {
            if left == right {
                continue;
            }
            if !candidates[left].is_fallback_well() && candidates[right].is_fallback_well() {
                reach[left][right] = true;
            }
        }
    }

    for pivot in 0..candidates.len() {
        for from in 0..candidates.len() {
            if !reach[from][pivot] {
                continue;
            }
            for to in 0..candidates.len() {
                reach[from][to] = reach[from][to] || reach[pivot][to];
            }
        }
    }

    for index in 0..candidates.len() {
        if reach[index][index] {
            panic!(
                "cyclic Sugar candidate ordering for role {:?}: {}",
                role,
                candidates[index].name()
            );
        }
    }

    for left in 0..candidates.len() {
        for right in (left + 1)..candidates.len() {
            if !reach[left][right] && !reach[right][left] {
                panic!(
                    "ambiguous Sugar candidates for role {:?}: no comes_before relation between {} and {}",
                    role,
                    candidates[left].name(),
                    candidates[right].name()
                );
            }
        }
    }

    let mut order: Vec<_> = (0..candidates.len()).collect();
    order.sort_by(|left, right| {
        if reach[*left][*right] {
            Ordering::Less
        } else if reach[*right][*left] {
            Ordering::Greater
        } else {
            Ordering::Equal
        }
    });

    let mut slots: Vec<_> = candidates.drain(..).map(Some).collect();
    candidates.extend(order.into_iter().map(|index| slots[index].take().unwrap()));
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use syn::{Expr, Item};

    use crate::sugar::claim::{ExprSugarClaim, SugarRole};
    use crate::sugar::factory::SugarBuildCtx;
    use crate::{
        record_simple_value_binding, FactoryAuditLog, FactoryDisposition, LiftOptions,
        MacroRegistry, Outcome, ReductionCtx, Sugar, SugarCtx, TemporalPlan, TemporalScope,
    };

    struct NoopSugar;

    impl Sugar for NoopSugar {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            panic!("catalog NoopSugar is candidate-only and must not desugar")
        }
    }

    fn recognize(_: &Expr, _: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
        Some(Box::new(NoopSugar))
    }

    fn candidate_names(expr: &Expr) -> Vec<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let candidates: Vec<_> = [
            SugarRole::Term,
            SugarRole::Composite,
            SugarRole::Constraint,
            SugarRole::AssertionSurface,
            SugarRole::TupleProducer,
            SugarRole::SupportConstraint,
            SugarRole::StatementEffect,
            SugarRole::ClosureAdaptorVerdict,
            SugarRole::MatchScrutineeVerdict,
        ]
        .into_iter()
        .flat_map(|role| super::matching_expr_claims_for_role(expr, &fcx, role))
        .collect();
        candidates
            .into_iter()
            .map(|candidate| candidate.name())
            .collect()
    }

    fn candidate_names_for_role(expr: &Expr, role: SugarRole) -> Vec<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        super::matching_expr_claims_for_role(expr, &fcx, role)
            .into_iter()
            .map(|candidate| candidate.name())
            .collect()
    }

    fn candidate_names_for_role_with_let_inits(
        expr: &Expr,
        role: SugarRole,
        let_inits: &BTreeMap<String, Expr>,
    ) -> Vec<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let borrowed_let_inits: BTreeMap<_, _> = let_inits
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .collect();
        let fcx = SugarBuildCtx::new(&scope, &options, &borrowed_let_inits);
        super::matching_expr_claims_for_role(expr, &fcx, role)
            .into_iter()
            .map(|candidate| candidate.name())
            .collect()
    }

    fn selected_candidate_name_for_role(expr: &Expr, role: SugarRole) -> Option<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        super::matching_expr_claims_for_role(expr, &fcx, role)
            .into_iter()
            .next()
            .map(|candidate| candidate.name())
    }

    fn selected_candidate_name_for_role_with_macros(
        expr: &Expr,
        role: SugarRole,
        macros: MacroRegistry,
    ) -> Option<&'static str> {
        let scope =
            TemporalScope::new("catalog-test", TemporalPlan::default()).with_macro_registry(macros);
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        super::matching_expr_claims_for_role(expr, &fcx, role)
            .into_iter()
            .next()
            .map(|candidate| candidate.name())
    }

    fn selected_candidate_name_for_role_with_let_inits(
        expr: &Expr,
        role: SugarRole,
        let_inits: &BTreeMap<String, Expr>,
    ) -> Option<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let borrowed_let_inits: BTreeMap<_, _> = let_inits
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .collect();
        let fcx = SugarBuildCtx::new(&scope, &options, &borrowed_let_inits);
        super::matching_expr_claims_for_role(expr, &fcx, role)
            .into_iter()
            .next()
            .map(|candidate| candidate.name())
    }

    fn item_candidate_names_for_role(item: &Item, role: SugarRole) -> Vec<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        super::matching_item_claims_for_role(item, &fcx, role)
            .into_iter()
            .map(|candidate| candidate.name())
            .collect()
    }

    #[test]
    fn literal_tuple_has_tuple_producer_candidate() {
        let expr: Expr = syn::parse_str("(1, 2)").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::TupleProducer);
        assert!(
            names.contains(&"literal_tuple_producer"),
            "literal tuple must expose its component floor through TupleProducer: {names:?}"
        );
    }

    #[test]
    fn monadic_value_if_has_term_candidate() {
        let expr: Expr = syn::parse_str("if x > 1 { Err(x) } else { Ok(x) }").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("value_if")
        );
    }

    #[test]
    fn monadic_option_constructors_are_composite_iter_sources() {
        let some: Expr = syn::parse_str("Some(42)").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&some, SugarRole::Composite),
            Some("monadic_composite")
        );

        let none: Expr = syn::parse_str("None").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&none, SugarRole::Composite),
            Some("monadic_composite")
        );
    }

    #[test]
    fn opaque_runtime_iterator_source_is_composite_fallback() {
        let range_new: Expr = syn::parse_str("RangeInclusive::new(1usize, 5usize)").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&range_new, SugarRole::Composite),
            Some("range_construct")
        );

        let opaque_call: Expr = syn::parse_str("opaque([1i32, 2, 3])").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&opaque_call, SugarRole::Composite),
            Some("runtime_iterator_source")
        );
    }

    #[test]
    fn async_future_handoff_owns_composite_before_runtime_iterator_fallback() {
        let expr: Expr = syn::parse_str("block_on(async { assert_eq!(1, 1); })").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert!(
            names.contains(&"statement_future_handoff_composite"),
            "future handoff should be visible as a Composite effect owner: {names:?}"
        );
        assert!(
            names.contains(&"runtime_iterator_source"),
            "generic runtime iterator fallback remains visible for opaque call sources: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Composite),
            Some("statement_future_handoff_composite"),
            "async future handoff owns the real effect before the opaque call fallback"
        );
    }

    #[test]
    fn bound_literal_tuple_has_tuple_producer_candidate() {
        let expr: Expr = syn::parse_str("pair").unwrap();
        let mut let_inits = BTreeMap::new();
        let_inits.insert("pair".to_string(), syn::parse_str("(1, 2)").unwrap());
        let names =
            candidate_names_for_role_with_let_inits(&expr, SugarRole::TupleProducer, &let_inits);
        assert!(
            names.contains(&"bound_path_tuple_producer"),
            "bound tuple must forward its component floor through TupleProducer: {names:?}"
        );
    }

    fn run_expr_with_audit(expr: &Expr, role: SugarRole) -> Vec<crate::FactoryAudit> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let items = Vec::<Item>::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = crate::FloatWidthScope::new();
        let audits = FactoryAuditLog::default();
        let ctx = crate::sugar_ctx_with_factory_audits(
            &scope,
            &options,
            &reducer,
            &mut float_widths,
            0,
            Some(&audits),
        );
        super::build_expr_role(expr, &fcx, role).desugar(&ctx);
        audits.into_inner()
    }

    static FIRST: ExprSugarClaim = ExprSugarClaim::new("first", SugarRole::Term, recognize);
    static SECOND: ExprSugarClaim = ExprSugarClaim::new("second", SugarRole::Term, recognize);
    static FIRST_BEFORE_SECOND: ExprSugarClaim =
        ExprSugarClaim::with_ordering("first", SugarRole::Term, &["second"], recognize);
    static SECOND_BEFORE_FIRST: ExprSugarClaim =
        ExprSugarClaim::with_ordering("second", SugarRole::Term, &["first"], recognize);
    static SECOND_BEFORE_THIRD: ExprSugarClaim =
        ExprSugarClaim::with_ordering("second", SugarRole::Term, &["third"], recognize);
    static THIRD: ExprSugarClaim = ExprSugarClaim::new("third", SugarRole::Term, recognize);
    static FALLBACK: ExprSugarClaim = ExprSugarClaim::fallback_term("fallback", recognize);

    #[test]
    #[should_panic(expected = "ambiguous Sugar candidates for role Term")]
    fn same_role_unordered_candidates_are_invalid() {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("1").unwrap();
        let mut candidates = vec![
            FIRST.candidate(&expr, &fcx).unwrap(),
            SECOND.candidate(&expr, &fcx).unwrap(),
        ];

        super::order_candidates_or_panic(&mut candidates);
    }

    #[test]
    fn same_role_candidates_order_by_declared_edge() {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("1").unwrap();
        let mut candidates = vec![
            SECOND.candidate(&expr, &fcx).unwrap(),
            FIRST_BEFORE_SECOND.candidate(&expr, &fcx).unwrap(),
        ];

        super::order_candidates_or_panic(&mut candidates);

        let names: Vec<_> = candidates
            .into_iter()
            .map(|candidate| candidate.name())
            .collect();
        assert_eq!(names, vec!["first", "second"]);
    }

    #[test]
    fn same_role_candidates_order_by_transitive_edges() {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("1").unwrap();
        let mut candidates = vec![
            THIRD.candidate(&expr, &fcx).unwrap(),
            FIRST_BEFORE_SECOND.candidate(&expr, &fcx).unwrap(),
            SECOND_BEFORE_THIRD.candidate(&expr, &fcx).unwrap(),
        ];

        super::order_candidates_or_panic(&mut candidates);

        let names: Vec<_> = candidates
            .into_iter()
            .map(|candidate| candidate.name())
            .collect();
        assert_eq!(names, vec!["first", "second", "third"]);
    }

    #[test]
    fn same_role_specific_candidate_orders_before_fallback_well() {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("1").unwrap();
        let mut candidates = vec![
            FALLBACK.candidate(&expr, &fcx).unwrap(),
            FIRST.candidate(&expr, &fcx).unwrap(),
        ];

        super::order_candidates_or_panic(&mut candidates);

        let names: Vec<_> = candidates
            .into_iter()
            .map(|candidate| candidate.name())
            .collect();
        assert_eq!(names, vec!["first", "fallback"]);
    }

    #[test]
    #[should_panic(expected = "ambiguous Sugar candidates for role Term")]
    fn same_role_fallback_wells_still_need_an_ordering_relation() {
        static OTHER_FALLBACK: ExprSugarClaim =
            ExprSugarClaim::fallback_term("other_fallback", recognize);

        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("1").unwrap();
        let mut candidates = vec![
            FALLBACK.candidate(&expr, &fcx).unwrap(),
            OTHER_FALLBACK.candidate(&expr, &fcx).unwrap(),
        ];

        super::order_candidates_or_panic(&mut candidates);
    }

    #[test]
    #[should_panic(expected = "cyclic Sugar candidate ordering for role Term")]
    fn same_role_candidate_cycles_are_invalid() {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("1").unwrap();
        let mut candidates = vec![
            FIRST_BEFORE_SECOND.candidate(&expr, &fcx).unwrap(),
            SECOND_BEFORE_FIRST.candidate(&expr, &fcx).unwrap(),
        ];

        super::order_candidates_or_panic(&mut candidates);
    }

    #[test]
    fn source_site_enumerates_every_applicable_sugar() {
        let expr: Expr = syn::parse_str("[1, 2, 3]").unwrap();
        let names = candidate_names(&expr);

        assert!(
            names.contains(&"array_term"),
            "term-position array sugar should be visible: {names:?}"
        );
        assert!(
            names.contains(&"literal"),
            "composite sequence-floor sugar should be visible: {names:?}"
        );
    }

    #[test]
    fn iterator_next_chain_has_owned_sugar_at_each_ast_node() {
        let expr: Expr = syn::parse_str("[1, 2, 3].iter().next()").unwrap();
        let names = candidate_names(&expr);
        assert!(
            names.contains(&"iter_terminal"),
            "terminal call should be claimed by next/terminal sugar: {names:?}"
        );

        let Expr::MethodCall(next_call) = &expr else {
            panic!("test expression should be a method call");
        };
        let iter_names = candidate_names(&next_call.receiver);
        assert!(
            iter_names.contains(&"iterator"),
            "receiver should be claimed by IteratorSugar: {iter_names:?}"
        );

        let Expr::MethodCall(iter_call) = next_call.receiver.as_ref() else {
            panic!("next receiver should be the iterator method call");
        };
        let base_names = candidate_names(&iter_call.receiver);
        assert!(
            base_names.contains(&"literal"),
            "iterator receiver should be claimed by array/range LiteralSugar: {base_names:?}"
        );
    }

    #[test]
    fn fold_method_call_prioritizes_fold_before_generic_method_sugar() {
        let expr: Expr =
            syn::parse_str("[1, 2].iter().fold(0, |acc, x| { assert_eq!(x, x); acc + x })")
                .unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Composite),
            Some("fold")
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("method"),
            "fold is composite sugar; generic method remains the term fallback"
        );
    }

    #[test]
    fn unrecognized_fold_method_call_falls_back_to_generic_method_sugar() {
        let expr: Expr = syn::parse_str("xs.fold(0, |acc, x| { assert_eq!(x, x); acc })").unwrap();
        let names = candidate_names(&expr);

        assert!(
            !names.contains(&"fold"),
            "unknown receiver fold should not be claimed by FoldSugar: {names:?}"
        );
        assert!(
            names.contains(&"method"),
            "unknown receiver fold should still be claimed by generic MethodSugar: {names:?}"
        );
    }

    #[test]
    fn unrecognized_iter_method_call_falls_back_to_generic_method_sugar() {
        let expr: Expr = syn::parse_str("xs.iter()").unwrap();
        let names = candidate_names(&expr);

        assert!(
            !names.contains(&"iterator"),
            "unknown receiver iter should not be claimed by IteratorSugar: {names:?}"
        );
        assert!(
            names.contains(&"method"),
            "unknown receiver iter should still be claimed by generic MethodSugar: {names:?}"
        );
    }

    #[test]
    fn unrecognized_next_method_call_falls_back_to_generic_method_sugar() {
        let expr: Expr = syn::parse_str("xs.iter().next()").unwrap();
        let names = candidate_names(&expr);

        assert!(
            !names.contains(&"iter_terminal"),
            "unknown receiver next should not be claimed by IterTerminalSugar: {names:?}"
        );
        assert!(
            names.contains(&"method"),
            "unknown receiver next should still be claimed by generic MethodSugar: {names:?}"
        );
    }

    #[test]
    fn literal_iterator_quantifier_owns_constraint_before_bool_method_fallback() {
        let inline: Expr = syn::parse_str("[1, 2, 3].iter().all(|&x| x < 10)").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&inline, SugarRole::Constraint),
            Some("constraint_literal_iterator_quantifier")
        );

        let boxed: Expr = syn::parse_str("v.iter().any(|&x| x % 2 == 0)").unwrap();
        let let_inits = BTreeMap::from([(
            "v".to_string(),
            syn::parse_str::<Expr>("Box::new([1, 2, 3, 4, 5])").unwrap(),
        )]);
        assert_eq!(
            selected_candidate_name_for_role_with_let_inits(
                &boxed,
                SugarRole::Constraint,
                &let_inits
            ),
            Some("constraint_literal_iterator_quantifier")
        );

        let bytes: Expr = syn::parse_str("b\"abc\".iter().all(|b| b.is_ascii())").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&bytes, SugarRole::Constraint),
            Some("constraint_literal_iterator_quantifier")
        );

        let chars: Expr = syn::parse_str("\"abc\".chars().all(|ch| ch.is_ascii())").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&chars, SugarRole::Constraint),
            Some("constraint_literal_iterator_quantifier")
        );
    }

    #[test]
    fn arbitrary_predicate_method_names_are_not_builtin_constraint_semantics() {
        let expr: Expr = syn::parse_str("value().is(3)").unwrap();
        let constraint_names = candidate_names_for_role(&expr, SugarRole::Constraint);
        let term_names = candidate_names_for_role(&expr, SugarRole::Term);

        assert_eq!(
            constraint_names,
            vec!["constraint_bool_expr"],
            "method names like `is`/`isnt` are examples, not builtin assertion semantics; \
             the generic bool-call shape owns the constraint without name-specific meaning"
        );
        assert!(
            term_names.contains(&"method"),
            "without a source-shaped or vendor-backed assertion Sugar this is generic MethodSugar: {term_names:?}"
        );
    }

    #[test]
    fn map_method_call_prioritizes_map_before_generic_method_sugar() {
        let expr: Expr = syn::parse_str("[1, 2].iter().map(|x| x * 2)").unwrap();
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Composite),
            Some("map")
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("map_term"),
            "map_term owns the term role before generic method fallback"
        );
    }

    #[test]
    fn identity_map_method_call_prioritizes_identity_map_before_map_sugar() {
        let expr: Expr = syn::parse_str("[\"a\", \"b\"].iter().map(|x| *x)").unwrap();
        let names = candidate_names(&expr);
        let identity_map = names
            .iter()
            .position(|name| *name == "identity_map")
            .expect("identity map adaptor should be claimed by IdentityMapSugar");
        let map = names
            .iter()
            .position(|name| *name == "map")
            .expect("identity map should also be claimed by general MapSugar");

        assert!(
            identity_map < map,
            "IdentityMapSugar should outrank general MapSugar: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Composite),
            Some("identity_map")
        );
    }

    #[test]
    fn unrecognized_map_method_call_falls_back_to_generic_method_sugar() {
        let expr: Expr = syn::parse_str("xs.map(|x| x)").unwrap();
        let names = candidate_names(&expr);

        assert!(
            !names.contains(&"map"),
            "unknown receiver map should not be claimed by MapSugar: {names:?}"
        );
        assert!(
            names.contains(&"method"),
            "unknown receiver map should still be claimed by generic MethodSugar: {names:?}"
        );
    }

    #[test]
    fn unrecognized_pow_method_call_falls_back_to_generic_method_sugar() {
        let expr: Expr = syn::parse_str("xs.pow(2)").unwrap();
        let names = candidate_names(&expr);

        assert!(
            !names.contains(&"int_pow"),
            "unknown receiver pow should not be claimed by IntPowSugar: {names:?}"
        );
        assert!(
            names.contains(&"method"),
            "unknown receiver pow should still be claimed by generic MethodSugar: {names:?}"
        );
    }

    #[test]
    fn format_macro_prioritizes_format_before_generic_macro_sugar() {
        let expr: Expr = syn::parse_str("format!(\"{}\", 1)").unwrap();
        let names = candidate_names(&expr);
        let format = names
            .iter()
            .position(|name| *name == "format_macro")
            .expect("format! should be claimed by FormatMacroSugar");
        let macro_term = names
            .iter()
            .position(|name| *name == "macro_term")
            .expect("format! should also be claimed by generic MacroTermSugar");

        assert!(
            format < macro_term,
            "FormatMacroSugar should outrank generic MacroTermSugar: {names:?}"
        );
    }

    #[test]
    fn format_macro_claims_shape_before_literal_resolution() {
        let expr: Expr = syn::parse_str("format!(\"{}\", some_var)").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);

        assert!(
            names.contains(&"format_macro"),
            "format! recognition is shape-only; payload resolution belongs to desugar: {names:?}"
        );
        assert!(
            names.contains(&"macro_term"),
            "generic macro fallback remains visible behind the format-specific owner: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("format_macro")
        );
    }

    #[test]
    fn format_args_estimated_capacity_prioritizes_builtin_before_generic_method() {
        let expr: Expr = syn::parse_str(r#"format_args!("Hello").estimated_capacity()"#).unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);

        assert!(
            names.contains(&"format_args_estimated_capacity"),
            "format_args!(...).estimated_capacity() should be claimed by builtin FormatArgsSugar: {names:?}"
        );
        assert!(
            names.contains(&"method"),
            "generic method fallback remains visible behind the builtin owner: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("format_args_estimated_capacity")
        );
    }

    #[test]
    fn referenced_format_macro_prioritizes_format_before_reference_wrapper() {
        let expr: Expr = syn::parse_str("&format!(\"{}\", 1)").unwrap();
        let names = candidate_names(&expr);
        let format = names
            .iter()
            .position(|name| *name == "format_macro")
            .expect("&format! should be claimed by FormatMacroSugar");
        let reference = names
            .iter()
            .position(|name| *name == "reference_term")
            .expect("&format! should still have the generic reference wrapper candidate");

        assert!(
            format < reference,
            "FormatMacroSugar should outrank ReferenceTermSugar for referenced format terms: {names:?}"
        );
    }

    #[test]
    fn addr_of_mut_prioritizes_capability_sugar_before_macro_fallback() {
        let expr: Expr = syn::parse_str("addr_of_mut!(x)").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);
        let addr = names
            .iter()
            .position(|name| *name == "addr_of_mut")
            .expect("addr_of_mut! should be claimed by AddrOfMutSugar");
        let macro_term = names
            .iter()
            .position(|name| *name == "macro_term")
            .expect("addr_of_mut! should still have the generic macro fallback candidate");

        assert!(
            addr < macro_term,
            "AddrOfMutSugar should outrank generic MacroTermSugar: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("addr_of_mut")
        );
    }

    #[test]
    fn concat_macro_prioritizes_concat_before_generic_macro_sugar() {
        let expr: Expr = syn::parse_str("concat!(\"a\", \"b\")").unwrap();
        let names = candidate_names(&expr);
        let concat = names
            .iter()
            .position(|name| *name == "concat_macro")
            .expect("concat! should be claimed by ConcatMacroSugar");
        let macro_term = names
            .iter()
            .position(|name| *name == "macro_term")
            .expect("concat! should also be claimed by generic MacroTermSugar");

        assert!(
            concat < macro_term,
            "ConcatMacroSugar should outrank generic MacroTermSugar: {names:?}"
        );
    }

    #[test]
    fn to_string_method_prioritizes_to_string_before_generic_method_sugar() {
        let expr: Expr = syn::parse_str("\"x\".to_string()").unwrap();
        let names = candidate_names(&expr);
        let to_string = names
            .iter()
            .position(|name| *name == "to_string")
            .expect("to_string should be claimed by ToStringSugar");
        let method = names
            .iter()
            .position(|name| *name == "method")
            .expect("to_string should also be claimed by generic MethodSugar");

        assert!(
            to_string < method,
            "ToStringSugar should outrank generic MethodSugar: {names:?}"
        );
    }

    #[test]
    fn parenthesized_to_string_prioritizes_to_string_before_transparent_recursion() {
        let expr: Expr = syn::parse_str("(\"x\".to_string())").unwrap();
        let selected = selected_candidate_name_for_role(&expr, SugarRole::Term);

        assert_eq!(
            selected,
            Some("to_string"),
            "specific ToStringSugar should outrank generic transparent recursion"
        );
    }

    #[test]
    fn char_literal_method_prioritizes_char_floor_before_generic_method_sugar() {
        let expr: Expr = syn::parse_str("'a'.len_utf8()").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);
        let char_method = names
            .iter()
            .position(|name| *name == "char_literal_method")
            .expect("char literal method should be claimed by CharMethodSugar");
        let method = names
            .iter()
            .position(|name| *name == "method")
            .expect("char literal method should also be claimed by generic MethodSugar");

        assert!(
            char_method < method,
            "CharMethodSugar should outrank generic MethodSugar: {names:?}"
        );
    }

    #[test]
    fn char_to_string_prioritizes_char_floor_before_generic_to_string() {
        let expr: Expr = syn::parse_str("'a'.to_string()").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);
        assert!(
            names.contains(&"char_literal_method"),
            "char literal receiver should be claimed by CharMethodSugar: {names:?}"
        );
        assert!(
            names.contains(&"to_string"),
            "char literal receiver should also be claimed by generic ToStringSugar: {names:?}"
        );

        let selected = selected_candidate_name_for_role(&expr, SugarRole::Term);
        assert_eq!(
            selected,
            Some("char_literal_method"),
            "char receiver semantics belong to the char floor before generic stringification"
        );
    }

    #[test]
    fn bound_char_to_string_prioritizes_char_floor_before_generic_to_string() {
        let mut let_inits = BTreeMap::new();
        let_inits.insert("ch".to_string(), syn::parse_str::<Expr>("'z'").unwrap());
        let expr: Expr = syn::parse_str("ch.to_string()").unwrap();
        let names = candidate_names_for_role_with_let_inits(&expr, SugarRole::Term, &let_inits);
        assert!(
            names.contains(&"char_literal_method"),
            "bound char literal receiver should be claimed by CharMethodSugar: {names:?}"
        );
        assert!(
            names.contains(&"to_string"),
            "bound char literal receiver should also be claimed by generic ToStringSugar: {names:?}"
        );

        let selected =
            selected_candidate_name_for_role_with_let_inits(&expr, SugarRole::Term, &let_inits);
        assert_eq!(
            selected,
            Some("char_literal_method"),
            "SSA-resolved char literals keep the char-floor owner"
        );
    }

    #[test]
    fn range_bounds_contains_prioritizes_range_bounds_owner_before_generic_method() {
        let mut let_inits = BTreeMap::new();
        let_inits.insert(
            "r".to_string(),
            syn::parse_str::<Expr>("(Bound::Included(1u32), Bound::Excluded(5u32))").unwrap(),
        );
        let expr: Expr = syn::parse_str("r.contains(&3)").unwrap();
        let names = candidate_names_for_role_with_let_inits(&expr, SugarRole::Term, &let_inits);
        assert!(
            names.contains(&"range_bounds_contains"),
            "RangeBounds tuple receiver should claim contains before generic method: {names:?}"
        );
        assert!(
            names.contains(&"method"),
            "generic MethodSugar still recognizes the bridge shape: {names:?}"
        );

        let selected =
            selected_candidate_name_for_role_with_let_inits(&expr, SugarRole::Term, &let_inits);
        assert_eq!(
            selected,
            Some("range_bounds_contains"),
            "RangeBounds trait boundary is the verdict owner; MethodSugar is only the fallback bridge"
        );
    }

    #[test]
    fn unknown_to_string_receiver_stays_with_generic_to_string() {
        let expr: Expr = syn::parse_str("id.to_string()").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);
        assert!(
            names.contains(&"to_string"),
            "unknown receiver still belongs to the generic formatting sugar: {names:?}"
        );
        assert!(
            !names.contains(&"char_literal_method"),
            "CharMethodSugar must not pretend an unknown receiver is a char: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("to_string")
        );
    }

    #[test]
    fn char_method_path_receiver_is_recognized_lazily() {
        let expr: Expr = syn::parse_str("c.to_ascii_lowercase()").unwrap();
        let selected = selected_candidate_name_for_role(&expr, SugarRole::Term);

        assert_eq!(
            selected,
            Some("char_literal_method"),
            "path receivers must not be rejected at recognize time; desugar owns the literal check"
        );
    }

    #[test]
    fn char_bool_method_constraint_owns_assert_predicate_before_generic_bool() {
        let expr: Expr = syn::parse_str("'a'.is_lowercase()").unwrap();
        let selected = selected_candidate_name_for_role(&expr, SugarRole::Constraint);

        assert_eq!(
            selected,
            Some("constraint_char_literal_method"),
            "assert-style char bool predicates keep a teethed constraint owner"
        );
    }

    #[test]
    fn runtime_ascii_char_predicate_declines_string_predicate_lane() {
        let expr: Expr = syn::parse_str("c.is_ascii_lowercase()").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Constraint);

        assert!(
            !names.contains(&"constraint_string_predicate"),
            "a runtime/source char receiver is not a literal string predicate floor: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Constraint),
            Some("constraint_bool_expr"),
            "runtime char predicates fall through to the generic bool-term owner"
        );
    }

    #[test]
    fn atomic_load_method_is_owned_by_atomic_runtime_sugar_before_generic_method() {
        let expr: Expr = syn::parse_str("witness[3].1.load(Ordering::Relaxed)").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);

        assert!(
            names.contains(&"atomic_load"),
            "atomic .load should be a named runtime boundary before the generic method bridge: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("atomic_load")
        );
    }

    #[test]
    fn source_location_methods_are_owned_before_generic_method() {
        let expr: Expr = syn::parse_str("Location::caller().file()").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);

        assert!(
            names.contains(&"source_location"),
            "Location::caller().file() should be a named source-location boundary: {names:?}"
        );
        assert!(
            names.contains(&"method"),
            "generic method remains a fallback candidate for the source-location call: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("source_location")
        );
    }

    #[test]
    fn string_ascii_method_stays_with_string_literal_owner() {
        let expr: Expr = syn::parse_str("\"x\".to_ascii_uppercase()").unwrap();
        let selected = selected_candidate_name_for_role(&expr, SugarRole::Term);

        assert_eq!(
            selected,
            Some("str_method"),
            "string literal methods remain in the str_method lane"
        );
    }

    #[test]
    fn shared_text_and_slice_methods_dispatch_by_bound_receiver_domain() {
        let mut string_inits = BTreeMap::new();
        string_inits.insert(
            "s".to_string(),
            syn::parse_str::<Expr>(r#""needle""#).unwrap(),
        );
        let string_expr: Expr = syn::parse_str(r#"s.contains("eed")"#).unwrap();
        let string_names =
            candidate_names_for_role_with_let_inits(&string_expr, SugarRole::Term, &string_inits);
        assert!(
            string_names.contains(&"str_method"),
            "text-bound receiver should stay in the str_method lane: {string_names:?}"
        );
        assert!(
            !string_names.contains(&"slice_accessor"),
            "text-bound receiver must not be claimed as a slice accessor: {string_names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role_with_let_inits(
                &string_expr,
                SugarRole::Term,
                &string_inits
            ),
            Some("str_method")
        );
        let string_constraint_names = candidate_names_for_role_with_let_inits(
            &string_expr,
            SugarRole::Constraint,
            &string_inits,
        );
        assert!(
            string_constraint_names.contains(&"constraint_string_predicate"),
            "text-bound assert predicate should stay in the string predicate lane: \
             {string_constraint_names:?}"
        );

        let mut slice_inits = BTreeMap::new();
        slice_inits.insert(
            "xs".to_string(),
            syn::parse_str::<Expr>("[1, 2, 3]").unwrap(),
        );
        let slice_expr: Expr = syn::parse_str("xs.contains(&2)").unwrap();
        let slice_names =
            candidate_names_for_role_with_let_inits(&slice_expr, SugarRole::Term, &slice_inits);
        assert!(
            slice_names.contains(&"slice_accessor"),
            "array-bound receiver should stay in the slice_accessor lane: {slice_names:?}"
        );
        assert!(
            !slice_names.contains(&"str_method"),
            "array-bound receiver must not be claimed as a string method: {slice_names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role_with_let_inits(
                &slice_expr,
                SugarRole::Term,
                &slice_inits
            ),
            Some("slice_accessor")
        );
        let slice_prefix_expr: Expr = syn::parse_str("xs.starts_with(&[1, 2])").unwrap();
        let slice_constraint_names = candidate_names_for_role_with_let_inits(
            &slice_prefix_expr,
            SugarRole::Constraint,
            &slice_inits,
        );
        assert!(
            !slice_constraint_names.contains(&"constraint_string_predicate"),
            "array-bound starts_with must not be claimed as a string predicate: \
             {slice_constraint_names:?}"
        );
    }

    #[test]
    fn string_add_prioritizes_string_add_before_generic_binop_sugar() {
        let expr: Expr = syn::parse_str("\"a\".to_string() + \"b\"").unwrap();
        let names = candidate_names(&expr);
        let string_add = names
            .iter()
            .position(|name| *name == "string_add")
            .expect("string add should be claimed by StringAddSugar");
        let binop = names
            .iter()
            .position(|name| *name == "binop")
            .expect("string add should also be claimed by generic BinopSugar");

        assert!(
            string_add < binop,
            "StringAddSugar should outrank generic BinopSugar: {names:?}"
        );
    }

    #[test]
    fn numeric_addition_stays_with_binop_not_string_add() {
        let expr: Expr = syn::parse_str("n + n").unwrap();
        let names = candidate_names(&expr);
        assert!(
            !names.contains(&"string_add"),
            "plain numeric/opaque `+` must not be stolen by StringAddSugar: {names:?}"
        );
        assert!(
            names.contains(&"binop"),
            "plain numeric/opaque `+` remains owned by BinOpSugar: {names:?}"
        );
    }

    #[test]
    fn char_range_filter_map_axiom_outranks_generic_assert_macro() {
        let expr: Expr = syn::parse_str(
            "assert!((from..=to).rev().eq((from as u32..=to as u32).filter_map(char::from_u32).rev()))",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Constraint);

        assert_eq!(
            names,
            vec!["char_range_filter_map_eq", "constraint_assert_macro"]
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Constraint),
            Some("char_range_filter_map_eq")
        );
    }

    #[test]
    fn unrecognized_stdlib_sequence_adaptors_decline_primary_sugar() {
        let cases = [
            ("xs.into_iter()", "iterator"),
            ("xs.cloned()", "iterator"),
            ("xs.rev()", "rev"),
            ("xs.enumerate()", "enumerate"),
            ("xs.filter(|x| true)", "filter"),
            ("xs.filter_map(|x| Some(x))", "filter_map"),
            ("xs.skip(1)", "skip"),
            ("xs.take(1)", "take"),
            ("xs.skip_while(|x| true)", "skip_while"),
            ("xs.take_while(|x| true)", "take_while"),
            ("xs.iter().sum::<i32>()", "iter_terminal"),
            ("xs.iter().count()", "iter_terminal"),
            ("xs.iter().nth(0)", "iter_terminal"),
            ("xs.for_each(|x| assert!(x > 0))", "for_each"),
        ];

        for (src, sugar_name) in cases {
            let expr: Expr = syn::parse_str(src).unwrap();
            let names = candidate_names(&expr);

            assert!(
                !names.contains(&sugar_name),
                "unknown receiver `{src}` should not be claimed by {sugar_name}: {names:?}"
            );
            assert!(
                names.contains(&"method"),
                "unknown receiver `{src}` should keep a recursive/effect fallback: {names:?}"
            );
        }
    }

    #[test]
    fn for_each_over_literal_sequence_adaptors_is_owned_by_for_each_sugar() {
        let expr: Expr =
            syn::parse_str("[1, 2, 3].iter().map(|x| x + 1).for_each(|x| assert!(x > 0))").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert!(
            names.contains(&"for_each"),
            "for_each over literal-derived sequence should be owned by ForEachSugar: {names:?}"
        );
    }

    #[test]
    fn iterator_clone_over_literal_bound_receiver_is_identity_composite() {
        let mut let_inits = BTreeMap::new();
        let_inits.insert(
            "iter".to_string(),
            syn::parse_str("[1, 2, 3].iter()").unwrap(),
        );
        let expr: Expr = syn::parse_str("iter.clone()").unwrap();
        let names =
            candidate_names_for_role_with_let_inits(&expr, SugarRole::Composite, &let_inits);

        assert!(
            names.contains(&"iterator"),
            "clone over a literal-derived iterator should be a composite identity adaptor: {names:?}"
        );
    }

    #[test]
    fn parenthesized_literal_range_composite_is_owned_by_transparent_wrapper() {
        let expr: Expr = syn::parse_str("(0..3)").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert_eq!(names, vec!["transparent_composite"]);
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Composite),
            Some("transparent_composite")
        );
    }

    #[test]
    fn for_loop_over_literal_range_is_owned_by_forall_loop_sugar() {
        let expr: Expr = syn::parse_str("for x in 0..3 { assert!(x >= 0); }").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert_eq!(names, vec!["forall_loop"]);
    }

    #[test]
    fn for_loop_over_runtime_collection_is_owned_by_forall_loop_sugar() {
        let expr: Expr = syn::parse_str("for x in items { assert_eq!(x, x); }").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert_eq!(names, vec!["forall_loop"]);
    }

    #[test]
    fn for_loop_over_side_effecting_iterator_domain_is_owned_by_mutation_sugar() {
        let expr: Expr = syn::parse_str("for _ in xs.iter_mut().map(|x| *x += 1) {}").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert!(
            names.contains(&"for_loop_mutation"),
            "side-effecting iterator-domain loop should be a named Mutation effect, not a factory gap: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Composite),
            Some("for_loop_mutation")
        );
    }

    #[test]
    fn const_if_local_loop_is_owned_by_for_replay_before_forall_loop() {
        let expr: Expr = syn::parse_str(
            "for i in 96..99 {
                let upper =
                    if 'a' as u32 <= i && i <= 'z' as u32 { i + 'A' as u32 - 'a' as u32 } else { i };
                assert_eq!(upper, upper);
            }",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert_eq!(names, vec!["for_replay", "forall_loop"]);
    }

    #[test]
    fn btree_extract_if_loop_is_owned_by_for_replay_before_forall_loop() {
        let expr: Expr = syn::parse_str(
            "for sacred in 0..3 {
                let mut map = BTreeMap::from_iter(pairs.clone());
                map.extract_if(.., |i, _| *i != sacred).for_each(drop);
                assert!(map.keys().copied().eq(sacred..=sacred));
            }",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert_eq!(names, vec!["for_replay", "forall_loop"]);
    }

    #[test]
    fn btree_insert_loop_is_owned_by_for_replay_before_forall_loop() {
        let expr: Expr = syn::parse_str(
            "for pos in 0..=size {
                let mut map = BTreeMap::from_iter((0..size).map(|i| (i * 2 + 1, ())));
                assert!(map.insert(pos * 2, ()).is_none());
            }",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Composite);

        assert_eq!(names, vec!["for_replay", "forall_loop"]);
    }

    #[test]
    fn none_path_prioritizes_monadic_before_generic_path_sugar() {
        let expr: Expr = syn::parse_str("None").unwrap();
        let names = candidate_names(&expr);
        let monadic = names
            .iter()
            .position(|name| *name == "monadic")
            .expect("None should be claimed by MonadicSugar");
        let path = names
            .iter()
            .position(|name| *name == "path")
            .expect("None should also be claimed by generic PathSugar");

        assert!(
            monadic < path,
            "MonadicSugar should outrank generic PathSugar: {names:?}"
        );
    }

    #[test]
    fn let_bound_cstr_literal_is_owned_by_cstr_floor_before_bound_path() {
        let mut scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let stmt: syn::Stmt = syn::parse_quote! { let a: &CStr = c"hello"; };
        let syn::Stmt::Local(local) = stmt else {
            panic!("catalog CStr fixture must parse as a local binding")
        };
        record_simple_value_binding(&mut scope, &local);
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("a").unwrap();
        let names: Vec<_> = super::matching_expr_claims_for_role(&expr, &fcx, SugarRole::Term)
            .into_iter()
            .map(|candidate| candidate.name())
            .collect();

        assert!(
            names.contains(&"cstr"),
            "let-bound CStr literal should be claimed by the literal CStr floor: {names:?}"
        );
        assert!(
            names.contains(&"bound_path"),
            "bound-path transparency remains visible behind the concrete floor owner: {names:?}"
        );
        assert_eq!(
            names.first().copied(),
            Some("cstr"),
            "compiler-axiom CStr bytes own the term before generic bound-path transparency"
        );
    }

    #[test]
    fn option_map_over_literal_some_is_owned_by_option_adaptor_before_sequence_map() {
        let expr: Expr = syn::parse_str("Some(1).map(|x| x + 1)").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);

        assert!(
            names.contains(&"option_adaptor"),
            "monadic map should be claimed by OptionAdaptorSugar: {names:?}"
        );
        assert!(
            names.contains(&"map_term"),
            "generic term map remains visible for non-monadic map-shaped terms: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("option_adaptor"),
            "Option/Result value adaptors own monadic map before sequence map_term"
        );
    }

    #[test]
    fn statement_control_flow_effect_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str("async { assert_eq!(1, 1); }.await").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_control_flow"]);
    }

    #[test]
    fn nested_async_assertion_statement_effect_is_future_handoff() {
        let expr: Expr = syn::parse_str("spawn(async { assert_eq!(1, 1); })").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_future_handoff"]);
    }

    #[test]
    fn bare_async_assertion_is_not_a_future_handoff_driver() {
        let expr: Expr = syn::parse_str("async { assert_eq!(1, 1); }").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(
            names,
            vec!["statement_async_future"],
            "bare async construction is inert/dormant, not a handoff driver"
        );
    }

    #[test]
    fn named_block_on_is_not_a_compiler_axiom() {
        let expr: Expr = syn::parse_str("block_on(async { assert_eq!(1, 1); })").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_future_handoff"]);
    }

    #[test]
    fn statement_reflection_effect_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str(
            "match const { Type::of::<[u16; 4]>() }.kind { TypeKind::Array(array) => assert_eq!(array.len, 4), _ => unreachable!() }",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_reflection"]);
    }

    #[test]
    fn statement_loop_advance_effect_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str(
            "loop { let (lower, upper) = iter.size_hint(); assert!(lower <= upper.unwrap()); }",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_loop_advance"]);
    }

    #[test]
    fn overlapping_statement_effects_resolve_by_declared_edges() {
        let expr: Expr = syn::parse_str(
            "loop { let _borrow = &mut value; let (lower, upper) = iter.size_hint(); assert!(lower <= upper.unwrap()); }",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(
            names,
            vec!["statement_loop_advance", "statement_runtime_expr"]
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::StatementEffect),
            Some("statement_loop_advance")
        );
    }

    #[test]
    fn statement_runtime_expr_effect_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str(
            "(assert_eq!(*MutRefWithDrop(&mut val).0, 0), std::mem::take(&mut val))",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_runtime_expr"]);
    }

    #[test]
    fn statement_nested_assertion_effect_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str("assert_eq!(i, 1)").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_nested_assertion"]);
    }

    #[test]
    fn unsafe_memory_statement_effect_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str("a.clone_to_uninit(dst)").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_unsafe_memory"]);
    }

    #[test]
    fn runtime_assignment_constraint_outranks_bool_fallback() {
        let expr: Expr = syn::parse_str("*ref_mut.get_mut() += 5").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Constraint);

        assert_eq!(names, vec!["constraint_runtime_expr"]);
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Constraint),
            Some("constraint_runtime_expr")
        );
    }

    #[test]
    fn relation_macro_assertion_surface_outranks_macro_expansion_surface() {
        let expr: Expr = syn::parse_str("assert_eq_const_safe!(u8: make_val(), 42)").unwrap();
        let mut macros = MacroRegistry::new();
        macros.scan_source(
            r#"
            macro_rules! assert_eq_const_safe {
                ($t:ty: $left:expr, $right:expr) => {
                    assert_eq!($left, $right);
                };
            }
            "#,
        );

        assert_eq!(
            selected_candidate_name_for_role_with_macros(
                &expr,
                SugarRole::AssertionSurface,
                macros
            ),
            Some("assertion_surface_relation_macro")
        );
    }

    #[test]
    fn pure_literal_statement_declines_effect_claim() {
        let expr: Expr = syn::parse_str("{ assert_eq!(1, 1); }").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert!(
            names.is_empty(),
            "pure literal statement should not claim an effect verdict: {names:?}"
        );
    }

    #[test]
    fn closure_runtime_receiver_verdict_is_a_catalog_claim() {
        let expr: Expr =
            syn::parse_str("std::env::args().for_each(|x| assert!(!x.is_empty()))").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(names, vec!["closure_runtime_receiver"]);
    }

    #[test]
    fn closure_tls_accessor_verdict_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str("DROPS.with(|d| assert_eq!(*d.borrow(), [0]))").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(
            names,
            vec!["closure_tls_accessor", "closure_runtime_receiver"]
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::ClosureAdaptorVerdict),
            Some("closure_tls_accessor")
        );
    }

    #[test]
    fn closure_opaque_accessor_verdict_is_a_catalog_claim() {
        let expr: Expr =
            syn::parse_str("cursor.with_unfilled_buf(|buf| assert!(!buf.is_empty()))").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(
            names,
            vec!["closure_opaque_accessor", "closure_runtime_receiver"]
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::ClosureAdaptorVerdict),
            Some("closure_opaque_accessor")
        );
    }

    #[test]
    fn closure_mutating_body_verdict_is_a_catalog_claim() {
        let expr: Expr =
            syn::parse_str("[1, 2, 3].iter().for_each(|x| { total += x; assert!(total > 0); })")
                .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(names, vec!["closure_mutating_body"]);
    }

    #[test]
    fn mutating_non_with_closure_adaptor_owns_opaque_accessor_overlap() {
        let expr: Expr = syn::parse_str(
            "cursor.with_unfilled_buf(|buf| { buf.unfilled().append(&[1, 2, 3]); assert_eq!(buf.filled(), &[1, 2, 3]); })",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert!(
            names.contains(&"closure_opaque_accessor"),
            "non-`.with` closure adaptor must still expose the opaque accessor candidate: {names:?}"
        );
        assert!(
            names.contains(&"closure_mutating_body"),
            "side-effecting closure body must expose the mutating-body candidate: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::ClosureAdaptorVerdict),
            Some("closure_mutating_body")
        );
    }

    #[test]
    fn closure_iter_advance_body_verdict_is_a_catalog_claim() {
        let expr: Expr =
            syn::parse_str("iter.clone().for_each(|x| assert_eq!(Some(x), iter.next()))").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(
            names,
            vec![
                "closure_iter_advance_body",
                "closure_mutating_body",
                "closure_runtime_receiver"
            ]
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::ClosureAdaptorVerdict),
            Some("closure_iter_advance_body")
        );
    }

    #[test]
    fn overlapping_closure_adaptor_verdicts_resolve_by_declared_edges() {
        let expr: Expr = syn::parse_str(
            "std::env::args().for_each(|x| { total += 1; assert!(!x.is_empty()); })",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(
            names,
            vec!["closure_mutating_body", "closure_runtime_receiver"]
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::ClosureAdaptorVerdict),
            Some("closure_mutating_body")
        );
    }

    #[test]
    fn pure_literal_closure_adaptor_declines_effect_verdict_claim() {
        let expr: Expr = syn::parse_str("[1, 2, 3].iter().for_each(|x| assert!(*x > 0))").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert!(
            names.is_empty(),
            "pure closure over literal sequence should not claim an effect verdict: {names:?}"
        );
    }

    #[test]
    fn match_scrutinee_verdict_is_a_catalog_claim() {
        let expr: Expr =
            syn::parse_str("match b.binary_search(&3) { Ok(_) => true, _ => false }").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::MatchScrutineeVerdict);

        assert_eq!(names, vec!["match_scrutinee"]);
    }

    #[test]
    fn runtime_call_match_constraint_is_owned_by_match_scrutinee_not_closed_match() {
        let expr: Expr = syn::parse_str(
            "match c.case() { None => false, Some(CharCase::Lower) => true, _ => false }",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Constraint);

        assert!(
            names.contains(&"constraint_match_scrutinee"),
            "runtime-call match scrutinees must be recognized by the runtime effect sugar: {names:?}"
        );
        assert!(
            !names.contains(&"constraint_closed_match"),
            "closed-match sugar must decline runtime-call scrutinees; otherwise the catalog \
             correctly panics over constraint_closed_match vs constraint_match_scrutinee"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Constraint),
            Some("constraint_match_scrutinee")
        );
    }

    #[test]
    fn runtime_match_scrutinee_term_is_a_catalog_claim() {
        let init: Expr = syn::parse_str("std::env::args().count()").unwrap();
        let mut let_inits = BTreeMap::new();
        let_inits.insert("r".to_string(), init);
        let expr: Expr = syn::parse_str("match r { 0 => 1u32, _ => 2u32 }").unwrap();
        let names = candidate_names_for_role_with_let_inits(&expr, SugarRole::Term, &let_inits);

        assert_eq!(names, vec!["match_scrutinee_term"]);
        assert_eq!(
            selected_candidate_name_for_role_with_let_inits(&expr, SugarRole::Term, &let_inits),
            Some("match_scrutinee_term")
        );
    }

    #[test]
    fn match_value_term_beats_runtime_scrutinee_term_for_divergent_arm_value() {
        let expr: Expr =
            syn::parse_str("match make_result() { Ok(v) => v, Err(e) => panic!(\"{e:?}\") }")
                .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::Term);

        assert!(
            names.contains(&"match_value_term"),
            "value match must keep its precise value owner: {names:?}"
        );
        assert!(
            names.contains(&"match_scrutinee_term"),
            "runtime scrutinee candidate should also be visible for ordering: {names:?}"
        );
        assert_eq!(
            selected_candidate_name_for_role(&expr, SugarRole::Term),
            Some("match_value_term")
        );
    }

    #[test]
    fn statement_item_is_a_catalog_claim() {
        let item: Item =
            syn::parse_str("impl W { fn write(&self) { assert_eq!(1, 1); } }").unwrap();
        let names = item_candidate_names_for_role(&item, SugarRole::StatementItem);

        assert_eq!(names, vec!["impl_method"]);
    }

    #[test]
    fn assertion_free_const_item_is_a_catalog_claim() {
        let item: Item = syn::parse_str("const SIZE: usize = 1 << 47;").unwrap();
        let names = item_candidate_names_for_role(&item, SugarRole::StatementItem);

        assert_eq!(names, vec!["const_item"]);
    }

    #[test]
    fn asserting_const_item_declines_inert_catalog_claim() {
        let item: Item = syn::parse_str("const _: () = { assert!(1 == 1); };").unwrap();
        let names = item_candidate_names_for_role(&item, SugarRole::StatementItem);

        assert!(
            names.is_empty(),
            "asserting const items must recurse into their body, not be inert support: {names:?}"
        );
    }

    #[test]
    fn assertion_free_block_const_item_is_inert_catalog_claim() {
        let item: Item = syn::parse_str("const VALUE: usize = { helper() };").unwrap();
        let names = item_candidate_names_for_role(&item, SugarRole::StatementItem);

        assert_eq!(names, vec!["const_item"]);
    }

    #[test]
    fn factory_audit_marks_literal_term_warranted() {
        let expr: Expr = syn::parse_str("1 + 2").unwrap();
        let audits = run_expr_with_audit(&expr, SugarRole::Term);
        let audit = audits
            .iter()
            .find(|audit| audit.site == "1 + 2" && audit.requested_role == "Term")
            .expect("binary expression site is audited");

        assert_eq!(audit.selected, Some("binop"));
        assert_eq!(audit.disposition, FactoryDisposition::Warranted);
        assert_eq!(audit.output, "term");
        assert!(audit.reason.is_none(), "{audit:?}");
    }

    #[test]
    fn factory_no_candidate_site_is_a_structural_gap_panic() {
        let expr: Expr = syn::parse_str("|| 1").unwrap();
        let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            run_expr_with_audit(&expr, SugarRole::Composite);
        }))
        .expect_err("factory gaps must panic instead of becoming an auditable outcome");
        let message = panic
            .downcast_ref::<String>()
            .map(String::as_str)
            .or_else(|| panic.downcast_ref::<&str>().copied())
            .expect("factory gap panic should carry a string message");
        assert!(
            message.contains("factory structural gap"),
            "unexpected panic message: {message}"
        );
        assert!(
            message.contains("no Sugar candidate for role Composite at `| | 1`"),
            "unexpected panic message: {message}"
        );
    }

    #[test]
    fn factory_audit_marks_mut_reference_construction_warranted() {
        let expr: Expr = syn::parse_str("&mut x").unwrap();
        let audits = run_expr_with_audit(&expr, SugarRole::Term);
        let audit = audits
            .iter()
            .find(|audit| audit.site == "& mut x" && audit.requested_role == "Term")
            .expect("mutable-reference term site is audited");

        assert_eq!(audit.selected, Some("reference_term"));
        assert_eq!(audit.disposition, FactoryDisposition::Warranted);
        assert!(audit.reason.is_none(), "{audit:?}");
    }
}
