// SPDX-License-Identifier: Apache-2.0
//
//! The recursive Sugar factory: **source site in, Sugar candidates out**.
//!
//! `matching_expr_claims(expr, fcx)` asks every expression Sugar whether it handles the
//! source site and returns every candidate that says yes. `build_term(expr, fcx)` and
//! `build_composite(expr, fcx)` are compatibility wrappers over that candidate list:
//! they pick the first candidate with the requested old source-position role, or fall
//! to `unsupported()`. That walk is the ENTIRE factory dispatch -- there are no inline
//! node structs, no `decompose_*` calls, no term/ctor construction logic here.
//!
//! ## The recognizer-fn pattern
//!
//! Every construct is a SELF-CONTAINED node living in its own `src/sugar/*.rs` module,
//! owning BOTH a recognizer `fn recognize(expr: &Expr, fcx: &FactoryCtx) ->
//! Option<Box<dyn Sugar>>` (returns `Some(boxed self)` if this Sugar handles the site --
//! building any children via `build_term`/`build_composite` -- else `None`) AND its
//! `desugar`. The former free `decompose_*` functions are reused INSIDE these
//! recognizers; the old inline `MethodCallTermSugar`/`CtorSugar`/`ResolvedTermSugar`/
//! `ReasonedHitSugar` now live in their own modules. Ambiguity is represented by
//! MULTIPLE candidates, not by a hidden factory choice.
//!
//! ## The three laws
//!
//! 1. **TOTAL.** Every `Expr` maps to *some* `Box<dyn Sugar>`. A term shape with no
//!    constructible value becomes a reasoned leaf (a `ReasonedHitSugar` carrying the
//!    arm's EXACT refusal string, or [`UnsupportedSugar`] for the structural backstop)
//!    — NEVER a silent skip. The walk cannot return `None`.
//! 2. **RECURSIVE.** A composite term node builds each operand with `build_term(child)`
//!    and composes the child Sugar; transparent wrappers (`Paren`/`Group`) recurse
//!    straight through. `desugar` then collapses the whole tree inside-out.
//! 3. **NEVER DECIDE EARLY (the sin).** A recognizer only *recognizes and news*;
//!    degeneracy is a LEAF property that propagates for free through the composites.
//!
//! ## Candidate priority
//!
//! Multiple Sugars may correctly claim the same source shape. Each candidate carries its
//! Sugar-declared priority: lower numbers are better decompositions. The factory brokers
//! candidates and sorts by that declared priority; it does not encode exclusion lists.
//!
//! ## The genuinely dual shapes
//!
//! `Array`, `Repeat`, and `MethodCall` have DISTINCT term vs composite roles, so they
//! get SEPARATE nodes per role — never one node branching on a position flag. The
//! term `Expr::Array` is the `literal_aggregate` ctor (`array_term`); the composite
//! `Expr::Array` is the sequence-floor `LiteralSugar` (`literal`). The term `Expr::Repeat`
//! expands a literal-count aggregate (`repeat_term`); the composite one is the
//! `ArrayRepeat` refuse-shape (`array_repeat`). The term `Expr::MethodCall` is the
//! `method:` ctor (`method_call_term`); the composite one is the
//! `fold`/`for_each`/`closure_adaptor`/`match_scrutinee` quantifier chain.

use std::collections::BTreeMap;

use syn::{Expr, Item};

use crate::sugar::backstop::unsupported;
use crate::sugar::catalog;
use crate::sugar::claim::SugarRole;
use crate::{LiftOptions, Sugar, TemporalScope};

/// What a recognizer needs from its environment to construct a node: the temporal
/// `scope` (binding / mutability oracle), the lift `options`, and the in-scope `let`
/// initializers (`name -> &init_expr`) that binding-resolving recognizers (`fold`,
/// `for_each`, `closure_adaptor`) capture. This is the BUILD-time env; the dual
/// [`SugarCtx`] is the DESUGAR-time env.
pub(crate) struct FactoryCtx<'a, 'e> {
    pub(crate) scope: &'a TemporalScope,
    pub(crate) options: &'a LiftOptions,
    pub(crate) let_inits: &'a BTreeMap<String, &'e Expr>,
}

pub(crate) fn build_expr(expr: &Expr, fcx: &FactoryCtx, role: SugarRole) -> Box<dyn Sugar> {
    catalog::select_expr_role(catalog::matching_expr_claims(expr, fcx), role)
        .map(|candidate| candidate.into_node())
        .unwrap_or_else(unsupported)
}

/// Compatibility TERM wrapper: ask the unified candidate catalog, then return the first
/// candidate whose old source-position role is `Term`, else the structural backstop.
/// TOTAL — every shape news a node (a reasoned leaf for the no-value shapes).
/// RECURSIVE — composite term recognizers build their operands with `build_term`.
pub(crate) fn build_term(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Term)
}

/// Compatibility COMPOSITE wrapper: ask the unified candidate catalog, then return the
/// first candidate whose old source-position role is `Composite`, else the structural
/// backstop. Total: an unowned shape becomes the [`UnsupportedSugar`] backstop.
pub(crate) fn build_composite(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Composite)
}

pub(crate) fn build_item(item: &Item, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    catalog::select_item_role(
        catalog::matching_item_claims(item, fcx),
        SugarRole::StatementItem,
    )
    .map(|candidate| candidate.into_node())
    .unwrap_or_else(unsupported)
}

pub(crate) fn build_closure_adaptor(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::ClosureAdaptorVerdict)
}

pub(crate) fn build_statement_position(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::StatementEffect)
}

pub(crate) fn build_match_scrutinee(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::MatchScrutineeVerdict)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate_names(expr: &Expr) -> Vec<&'static str> {
        let scope = TemporalScope::new("factory-test", crate::TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = FactoryCtx {
            scope: &scope,
            options: &options,
            let_inits: &let_inits,
        };
        catalog::matching_expr_claims(expr, &fcx)
            .into_iter()
            .map(|candidate| candidate.name())
            .collect()
    }

    fn candidate_names_for_role(expr: &Expr, role: SugarRole) -> Vec<&'static str> {
        let scope = TemporalScope::new("factory-test", crate::TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = FactoryCtx {
            scope: &scope,
            options: &options,
            let_inits: &let_inits,
        };
        catalog::matching_expr_claims(expr, &fcx)
            .into_iter()
            .filter(|candidate| candidate.role() == role)
            .map(|candidate| candidate.name())
            .collect()
    }

    fn item_candidate_names_for_role(item: &Item, role: SugarRole) -> Vec<&'static str> {
        let scope = TemporalScope::new("factory-test", crate::TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = FactoryCtx {
            scope: &scope,
            options: &options,
            let_inits: &let_inits,
        };
        catalog::matching_item_claims(item, &fcx)
            .into_iter()
            .filter(|candidate| candidate.role() == role)
            .map(|candidate| candidate.name())
            .collect()
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
    fn fold_method_call_prioritizes_fold_before_generic_method_call_sugar() {
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
            .position(|name| *name == "method_call_term")
            .expect(
                "fold-shaped method call should also be claimed by generic MethodCallTermSugar",
            );

        assert!(
            fold < method,
            "FoldSugar should outrank generic MethodCallTermSugar: {names:?}"
        );
    }

    #[test]
    fn map_method_call_prioritizes_map_before_generic_method_call_sugar() {
        let expr: Expr = syn::parse_str("[1, 2].iter().map(|x| x * 2)").unwrap();
        let names = candidate_names(&expr);
        let map = names
            .iter()
            .position(|name| *name == "map")
            .expect("map adaptor should be claimed by MapSugar");
        let method = names
            .iter()
            .position(|name| *name == "method_call_term")
            .expect("map adaptor should also be claimed by generic MethodCallTermSugar");

        assert!(
            map < method,
            "MapSugar should outrank generic MethodCallTermSugar: {names:?}"
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
    fn statement_position_effect_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str("async { assert_eq!(1, 1); }.await").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::StatementEffect);

        assert_eq!(names, vec!["statement_position"]);
    }

    #[test]
    fn closure_adaptor_verdict_is_a_catalog_claim() {
        let expr: Expr = syn::parse_str("xs.iter().map(|x| { assert_eq!(x, x); x })").unwrap();
        let names = candidate_names_for_role(&expr, SugarRole::ClosureAdaptorVerdict);

        assert_eq!(names, vec!["closure_adaptor"]);
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
