// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Smoke test for the canonical `compose_chain_contracts` primitive.
//
// This test composes two trivial pure atoms (an inner contract whose post
// is `result = y` and an outer contract whose post is `result = x`) and
// asserts:
//
//   1. Composition succeeds.
//   2. The composed CID is byte-stable across runs.
//   3. The composed CID matches a pinned hex value.
//
// The pinned CID is the CCP v1.0.0 conformance witness for this fixture.
// Any CCP version bump that alters the algebra will change this CID and
// require regenerating the pin under the new version's signature
// (per spec §5 "Test corpus" and §11 "Versioning and revocation").

use std::sync::Arc;

use libsugar::compose::{
    build_value, cid_of_value, compose_chain_contracts, jcs_bytes_of_value, ChainStep, Effect,
    EffectSet, FunctionContractMemento, Locus,
};
use sugar_canonicalizer::Value;
use sugar_ir_types::{composition_refusal_header_cid, IrFormula, IrTerm, Sort};

/// Build a trivial pure FunctionContractMemento whose post is
/// `result = <formal>`. The result-equation is the algebraic input that
/// `compose_chain_contracts` substitutes through. No effects, no
/// auto-minted mementos, no body cid.
fn pure_identity_contract(fn_name: &str, formal: &str) -> FunctionContractMemento {
    let formals = vec![formal.to_string()];
    let formal_sorts = vec![Sort::Primitive {
        name: "u32".to_string(),
    }];
    let return_sort = Sort::Primitive {
        name: "u32".to_string(),
    };
    let pre = IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    };
    let post = IrFormula::Atomic {
        name: "=".to_string(),
        args: vec![
            IrTerm::Var {
                name: "result".to_string(),
            },
            IrTerm::Var {
                name: formal.to_string(),
            },
        ],
    };
    let effects = EffectSet::empty();
    let locus = Locus::unknown();

    let value: Arc<Value> = build_value(
        fn_name,
        &formals,
        &formal_sorts,
        &return_sort,
        &pre,
        &post,
        None,
        &effects,
        &locus,
        &[],
    );
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);

    FunctionContractMemento {
        fn_name: fn_name.to_string(),
        formals,
        formal_sorts,
        formal_regions: vec![],
        return_sort,
        return_region: None,
        pre,
        post,
        body_cid: None,
        effects,
        locus,
        canonical_bytes,
        cid,
        auto_minted_mementos: vec![],
        panic_loci: vec![],
        concept_hint: None,
    }
}

fn impure_identity_contract(fn_name: &str, formal: &str) -> FunctionContractMemento {
    let mut contract = pure_identity_contract(fn_name, formal);
    contract.effects.add(Effect::Io);
    let value: Arc<Value> = build_value(
        &contract.fn_name,
        &contract.formals,
        &contract.formal_sorts,
        &contract.return_sort,
        &contract.pre,
        &contract.post,
        contract.body_cid.as_deref(),
        &contract.effects,
        &contract.locus,
        &contract.auto_minted_mementos,
    );
    contract.canonical_bytes = jcs_bytes_of_value(&value);
    contract.cid = cid_of_value(&value);
    contract
}

#[test]
fn compose_chain_two_pure_atoms_pins_cid() {
    let inner = pure_identity_contract("inner", "y");
    let outer = pure_identity_contract("outer", "x");

    let chain = vec![
        ChainStep {
            contract: &inner,
            formal_idx: 0, // unused for the leaf step
        },
        ChainStep {
            contract: &outer,
            formal_idx: 0,
        },
    ];

    let composed = compose_chain_contracts(&chain).expect("compose succeeds for two pure atoms");
    assert!(composed.cid.starts_with("blake3-512:"));
    assert_eq!(
        composed.component_cids.len(),
        2,
        "two-step chain has two component cids"
    );

    // Re-compose: must be byte-identical.
    let composed2 = compose_chain_contracts(&chain).expect("recompose succeeds");
    assert_eq!(composed.cid, composed2.cid);
    assert_eq!(composed.canonical_bytes, composed2.canonical_bytes);

    // Pinned CID under CCP v1.0.0. If this changes, the algebra changed;
    // back out and bump the CCP version.
    const PINNED_CID: &str = "blake3-512:36212b7bf7b9ccf264950940a33d64e1cfe88b6f4d8a47c01949fc64d9359d1813d6147aa2e1afe82b01e6e7ebcbe0a413683284b5f47ffef5bf364213304665";
    assert_eq!(
        composed.cid, PINNED_CID,
        "composed CID drifted; algebra must not change without a CCP version bump"
    );
}

#[test]
fn compose_chain_impure_input_returns_stable_refusal_memento() {
    let inner = pure_identity_contract("inner", "y");
    let outer = impure_identity_contract("outer", "x");

    let chain = vec![
        ChainStep {
            contract: &inner,
            formal_idx: 0,
        },
        ChainStep {
            contract: &outer,
            formal_idx: 0,
        },
    ];

    let refusal = compose_chain_contracts(&chain).expect_err("impure input refuses");
    assert_eq!(refusal.header.failure_kind, "impure-input");
    assert_eq!(refusal.header.kind, "composition-refusal");
    assert_eq!(refusal.header.schema_version, "1");
    assert_eq!(
        refusal
            .header
            .blocking_effects
            .as_ref()
            .expect("impure refusal has blocking effects")[0]
            .atom_cid,
        outer.cid
    );
    assert_eq!(
        composition_refusal_header_cid(&refusal.header),
        refusal.header.cid
    );

    let refusal2 = compose_chain_contracts(&chain).expect_err("impure input refuses again");
    assert_eq!(refusal.header.cid, refusal2.header.cid);
}
