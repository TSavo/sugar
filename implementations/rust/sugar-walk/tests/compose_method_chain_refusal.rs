// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::HashMap;

use sugar_walk::build_function_contract;
use sugar_walk::chain::{compose_method_chain, MethodCallStep};

fn contract(src: &str) -> sugar_walk::contract::FunctionContractMemento {
    build_function_contract(&syn::parse_str::<syn::ItemFn>(src).unwrap(), None)
}

#[test]
fn compose_method_chain_impure_input_returns_stable_refusal_cid() {
    let mut registry = HashMap::new();
    registry.insert("iter".to_string(), contract("fn iter(v: u32) -> u32 { v }"));
    registry.insert(
        "sum".to_string(),
        contract(r#"fn sum(x: u32) -> u32 { println!("{}", x); x }"#),
    );
    let chain = vec![
        MethodCallStep {
            method_name: "iter".to_string(),
            _arg_count: 0,
        },
        MethodCallStep {
            method_name: "sum".to_string(),
            _arg_count: 0,
        },
    ];

    let refusal = compose_method_chain(&chain, &registry).expect_err("impure input refuses");
    let refusal2 = compose_method_chain(&chain, &registry).expect_err("impure input refuses");

    assert!(
        !refusal.header.cid.is_empty(),
        "refusal CID must be populated"
    );
    assert_eq!(refusal.header.failure_kind, "impure-input");
    assert_eq!(
        refusal.header.cid, refusal2.header.cid,
        "same impure input must produce deterministic refusal CID"
    );
}
