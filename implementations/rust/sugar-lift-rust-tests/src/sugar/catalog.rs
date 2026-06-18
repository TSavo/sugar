// SPDX-License-Identifier: Apache-2.0
//
// Sugar claim catalog and candidate resolution.

use syn::{Expr, Item};

use crate::sugar::backstop::unsupported;
use crate::sugar::claim::{ExprSugarClaim, ItemSugarClaim, SugarCandidate, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::{
    array_repeat, array_term, await_term, binop, block_term, call, cast_term, closure_adaptor,
    closure_term, conditional, const_block, control_flow_term, enumerate, field_term, filter,
    filter_map, fold, forall, impl_method, index, iter_terminal, iterator, literal, macro_term,
    map, match_node, match_scrutinee, method, monadic, path, range_term, raw_addr_term,
    reference_term, repeat_term, rev, skip, skip_while, statement_control_flow,
    statement_loop_advance, statement_reflection, statement_runtime_expr, struct_term, take,
    take_while, term_literal, transparent_term, tuple_term, unary,
};
use crate::Sugar;

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
    &method::EXPR_SUGAR,
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
    &closure_adaptor::TLS_ACCESSOR_EXPR_SUGAR,
    &closure_adaptor::OPAQUE_ACCESSOR_EXPR_SUGAR,
    &closure_adaptor::ITER_ADVANCE_BODY_EXPR_SUGAR,
    &closure_adaptor::MUTATING_BODY_EXPR_SUGAR,
    &closure_adaptor::RUNTIME_RECEIVER_EXPR_SUGAR,
    &statement_control_flow::EXPR_SUGAR,
    &statement_reflection::EXPR_SUGAR,
    &statement_loop_advance::EXPR_SUGAR,
    &statement_runtime_expr::EXPR_SUGAR,
    &match_scrutinee::VERDICT_EXPR_SUGAR,
];

const ITEM_CLAIMS: &[&ItemSugarClaim] = &[&impl_method::ITEM_SUGAR];

/// Ask every expression Sugar whether it handles this source site. Multiple
/// candidates are first-class; equal-priority candidates for the same role are not.
pub(crate) fn matching_expr_claims(expr: &Expr, fcx: &SugarBuildCtx) -> Vec<SugarCandidate> {
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

pub(crate) fn build_expr_role(expr: &Expr, fcx: &SugarBuildCtx, role: SugarRole) -> Box<dyn Sugar> {
    select_expr_role(matching_expr_claims(expr, fcx), role)
        .map(|candidate| candidate.into_node())
        .unwrap_or_else(unsupported)
}

pub(crate) fn matching_item_claims(item: &Item, fcx: &SugarBuildCtx) -> Vec<SugarCandidate> {
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

pub(crate) fn build_item_role(item: &Item, fcx: &SugarBuildCtx, role: SugarRole) -> Box<dyn Sugar> {
    select_item_role(matching_item_claims(item, fcx), role)
        .map(|candidate| candidate.into_node())
        .unwrap_or_else(unsupported)
}

fn assert_no_ambiguous_role_priority(candidates: &[SugarCandidate]) {
    for (index, candidate) in candidates.iter().enumerate() {
        if candidates[..index].iter().any(|prior| {
            prior.role() == candidate.role() && prior.priority() == candidate.priority()
        }) {
            continue;
        }

        let names: Vec<_> = candidates
            .iter()
            .filter(|other| {
                other.role() == candidate.role() && other.priority() == candidate.priority()
            })
            .map(|candidate| candidate.name())
            .collect();
        if names.len() > 1 {
            panic!(
                "ambiguous Sugar candidates for role {:?} at priority {:?}: {}",
                candidate.role(),
                candidate.priority(),
                names.join(", ")
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use syn::{Expr, Item};

    use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
    use crate::sugar::factory::SugarBuildCtx;
    use crate::{LiftOptions, Outcome, Sugar, SugarCtx, TemporalPlan, TemporalScope};

    struct NoopSugar;

    impl Sugar for NoopSugar {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::from_opt(None)
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
        super::matching_expr_claims(expr, &fcx)
            .into_iter()
            .map(|candidate| candidate.name())
            .collect()
    }

    fn candidate_names_for_role(expr: &Expr, role: SugarRole) -> Vec<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        super::matching_expr_claims(expr, &fcx)
            .into_iter()
            .filter(|candidate| candidate.role() == role)
            .map(|candidate| candidate.name())
            .collect()
    }

    fn selected_candidate_name_for_role(expr: &Expr, role: SugarRole) -> Option<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        super::select_expr_role(super::matching_expr_claims(expr, &fcx), role)
            .map(|candidate| candidate.name())
    }

    fn item_candidate_names_for_role(item: &Item, role: SugarRole) -> Vec<&'static str> {
        let scope = TemporalScope::new("catalog-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        super::matching_item_claims(item, &fcx)
            .into_iter()
            .filter(|candidate| candidate.role() == role)
            .map(|candidate| candidate.name())
            .collect()
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
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let expr: Expr = syn::parse_str("1").unwrap();
        let candidates = vec![
            FIRST.candidate(&expr, &fcx).unwrap(),
            SECOND.candidate(&expr, &fcx).unwrap(),
        ];

        let _ = super::select_expr_role(candidates, SugarRole::Term);
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
        let names = candidate_names(&expr);
        let fold = names
            .iter()
            .position(|name| *name == "fold")
            .expect("fold-shaped method call should be claimed by FoldSugar");
        let method = names
            .iter()
            .position(|name| *name == "method")
            .expect("fold-shaped method call should also be claimed by generic MethodSugar");

        assert!(
            fold < method,
            "FoldSugar should outrank generic MethodSugar: {names:?}"
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
    fn map_method_call_prioritizes_map_before_generic_method_sugar() {
        let expr: Expr = syn::parse_str("[1, 2].iter().map(|x| x * 2)").unwrap();
        let names = candidate_names(&expr);
        let map = names
            .iter()
            .position(|name| *name == "map")
            .expect("map adaptor should be claimed by MapSugar");
        let method = names
            .iter()
            .position(|name| *name == "method")
            .expect("map adaptor should also be claimed by generic MethodSugar");

        assert!(
            map < method,
            "MapSugar should outrank generic MethodSugar: {names:?}"
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
    fn statement_control_flow_effect_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str("async { assert_eq!(1, 1); }.await").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_control_flow"]);
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
    fn overlapping_statement_effects_resolve_by_declared_priority() {
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
            "(assert_matches!(*MutRefWithDrop(&mut val).0, 0), std::mem::take(&mut val))",
        )
        .unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_runtime_expr"]);
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

        assert_eq!(names, vec!["closure_tls_accessor"]);
    }

    #[test]
    fn closure_opaque_accessor_verdict_is_a_catalog_claim() {
        let expr: Expr =
            syn::parse_str("cursor.with_unfilled_buf(|buf| assert!(!buf.is_empty()))").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(names, vec!["closure_opaque_accessor"]);
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
    fn closure_iter_advance_body_verdict_is_a_catalog_claim() {
        let expr: Expr =
            syn::parse_str("iter.clone().for_each(|x| assert_eq!(Some(x), iter.next()))").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(names, vec!["closure_iter_advance_body"]);
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
    fn statement_item_is_a_catalog_claim() {
        let item: Item =
            syn::parse_str("impl W { fn write(&self) { assert_eq!(1, 1); } }").unwrap();
        let names = item_candidate_names_for_role(&item, SugarRole::StatementItem);

        assert_eq!(names, vec!["impl_method"]);
    }
}
