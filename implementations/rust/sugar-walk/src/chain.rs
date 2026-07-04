// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Iterator-chain detection from a Rust expression. Walks consecutive
// `MethodCall` nodes (vec.iter().map(f).filter(g).sum()) and
// composes each method's FunctionContractMemento into a single
// ComposedFunctionContract.
//
// Per #376 phase 5. Pure-method chains collapse to one CID; the
// substrate caches that CID; future programs hitting structurally-
// equivalent chains discharge in O(1).
//
// MVP scope: takes a contract registry as input (hand-supplied for
// the MVP demo). Once #377 lands the substrate-side automatic
// lookup, the registry is replaced by a substrate query.

use std::collections::HashMap;

use syn::Expr;

use crate::contract::{
    compose_chain_contracts, ChainStep, ComposedFunctionContract, CompositionRefusalMemento,
    FunctionContractMemento,
};

/// One method-call in a detected chain. The receiver is the implicit
/// first argument (formal_idx = 0 in the substrate's method
/// normalization).
#[derive(Debug, Clone)]
pub struct MethodCallStep {
    pub method_name: String,
    pub _arg_count: usize,
}

/// Walk an expression for consecutive `MethodCall` nodes. Returns the
/// chain in source order (leftmost first). The chain's first step is
/// the chain's "source" — the expression on the leftmost receiver.
///
/// Returns None if the expression isn't a method-call chain of length
/// ≥ 2.
pub fn detect_method_chain(expr: &Expr) -> Option<Vec<MethodCallStep>> {
    let mut steps = Vec::new();
    let mut current = expr;
    while let Expr::MethodCall(m) = current {
        steps.push(MethodCallStep {
            method_name: m.method.to_string(),
            _arg_count: m.args.len(),
        });
        current = &m.receiver;
    }
    if steps.len() < 2 {
        return None;
    }
    steps.reverse();
    Some(steps)
}

/// Compose an iterator chain by looking up each step's contract in
/// the registry. Returns Ok(None) if any contract is missing, and
/// propagates the canonical refusal memento if composition is refused.
///
/// All chain steps use formal_idx = 0 because methods are normalized
/// as `method:foo(receiver, args)` per the lifter (paper 07
/// normalization: methods are sugar for free functions with receiver
/// as first argument).
pub fn compose_method_chain(
    chain: &[MethodCallStep],
    registry: &HashMap<String, FunctionContractMemento>,
) -> Result<Option<ComposedFunctionContract>, CompositionRefusalMemento> {
    if chain.len() < 2 {
        return Ok(None);
    }
    let mut contracts: Vec<&FunctionContractMemento> = Vec::with_capacity(chain.len());
    for step in chain {
        let Some(contract) = registry.get(&step.method_name) else {
            return Ok(None);
        };
        contracts.push(contract);
    }
    let steps: Vec<ChainStep<'_>> = contracts
        .into_iter()
        .map(|c| ChainStep {
            contract: c,
            formal_idx: 0,
        })
        .collect();
    compose_chain_contracts(&steps).map(Some)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::build_function_contract;

    fn parse_expr(src: &str) -> Expr {
        syn::parse_str(src).unwrap()
    }

    #[test]
    fn detects_two_method_chain() {
        let chain = detect_method_chain(&parse_expr("v.iter().sum()")).unwrap();
        assert_eq!(chain.len(), 2);
        assert_eq!(chain[0].method_name, "iter");
        assert_eq!(chain[1].method_name, "sum");
    }

    #[test]
    fn detects_four_method_chain_in_source_order() {
        let chain = detect_method_chain(&parse_expr("v.iter().map(f).filter(g).sum()")).unwrap();
        assert_eq!(chain.len(), 4);
        assert_eq!(chain[0].method_name, "iter");
        assert_eq!(chain[1].method_name, "map");
        assert_eq!(chain[2].method_name, "filter");
        assert_eq!(chain[3].method_name, "sum");
    }

    #[test]
    fn rejects_non_chain_expression() {
        assert!(detect_method_chain(&parse_expr("42")).is_none());
        assert!(detect_method_chain(&parse_expr("x + y")).is_none());
        assert!(
            detect_method_chain(&parse_expr("v.iter()")).is_none(),
            "single call is not a chain"
        );
    }

    #[test]
    fn compose_method_chain_collapses_pure_chain_to_single_cid() {
        // Build hand-rolled pure contracts for a 3-step chain.
        let identity = build_function_contract(
            &syn::parse_str::<syn::ItemFn>(
                r#"
                fn iter(v: u32) -> u32 { v }
            "#,
            )
            .unwrap(),
            None,
        );
        let inc = build_function_contract(
            &syn::parse_str::<syn::ItemFn>(
                r#"
                fn map(x: u32) -> u32 { x + 1 }
            "#,
            )
            .unwrap(),
            None,
        );
        let double = build_function_contract(
            &syn::parse_str::<syn::ItemFn>(
                r#"
                fn sum(x: u32) -> u32 { x * 2 }
            "#,
            )
            .unwrap(),
            None,
        );
        // Build a registry keyed by method name (matching MethodCallStep).
        let mut registry = HashMap::new();
        registry.insert("iter".to_string(), identity);
        registry.insert("map".to_string(), inc);
        registry.insert("sum".to_string(), double);

        let chain = detect_method_chain(&parse_expr("v.iter().map(f).sum()")).unwrap();
        let composed = compose_method_chain(&chain, &registry)
            .expect("compose does not refuse")
            .expect("compose succeeds");
        assert!(composed.cid.starts_with("blake3-512:"));
        // The chain has 3 steps → 3 component CIDs.
        assert_eq!(composed.component_cids.len(), 3);

        // Re-composition is deterministic.
        let composed2 = compose_method_chain(&chain, &registry).unwrap().unwrap();
        assert_eq!(composed.cid, composed2.cid);
        assert_eq!(composed.canonical_bytes, composed2.canonical_bytes);
    }

    #[test]
    fn compose_method_chain_returns_none_on_missing_contract() {
        let registry: HashMap<String, FunctionContractMemento> = HashMap::new();
        let chain = detect_method_chain(&parse_expr("v.iter().sum()")).unwrap();
        assert!(compose_method_chain(&chain, &registry).unwrap().is_none());
    }
}
