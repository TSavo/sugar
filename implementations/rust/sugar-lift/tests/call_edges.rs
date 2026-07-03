// SPDX-License-Identifier: Apache-2.0
//
// Integration tests for call-edge stream emission (spec #114 §1 R1).
//
// Test 1: b() calls a(), both have contracts → edge has correct source and
//         target contractCids.
// Test 2: b() calls an extern "C" function → targetContractCid is null,
//         targetSymbol is populated.
// Test 3: JCS bytes of a call-edge memento are byte-deterministic across
//         two independent lifts of the same source.

use std::collections::BTreeMap;

// THE SEVER: the lifter is no longer re-exported from sugar-lift (it is
// now an RPC kit). This test exercises the lifter's `lift_file` directly via
// the dev-dependency on `sugar-lift-contracts` — the sanctioned way to
// keep lifter-behavior coverage without spawning RPC in a unit test.
use sugar_lift::extract_call_edges_from_file;
use sugar_lift_contracts as adapter_contracts;

use sugar_claim_envelope::{contract_cid as compute_contract_cid, Authoring, MintContractArgs};
use sugar_ir_symbolic::serialize::formula_to_value;

// ---------------------------------------------------------------------------
// Test 1: b() calls a(); both have contracts.
// ---------------------------------------------------------------------------

#[test]
fn test1_call_edge_both_contracted_has_target_cid() {
    // Source: `a` and `b` are annotated functions; `b` calls `a`.
    let src = r#"
#[requires(x > 0)]
#[ensures(result >= 0)]
fn a(x: i64) -> i64 { x }

#[requires(n > 0)]
#[ensures(result >= 0)]
fn b(n: i64) -> i64 { a(n) }
"#;

    let parsed = syn::parse_file(src).expect("parse_file");

    // Lift the contracts adapter to get the ContractDecls.
    let adapter_out = adapter_contracts::lift_file(&parsed, "test1.rs");
    assert!(adapter_out.lifted >= 2, "expected >=2 contracts (a and b)");

    // Build the name→CID map the same way lift_path does.
    let cid_map: BTreeMap<String, String> = adapter_out
        .decls
        .iter()
        .map(|d| {
            let args = MintContractArgs {
                evidence_term: None,
                formals: Vec::new(),
                emit_empty_formals: false,
                formal_sorts: Vec::new(),
                library: None,
                body_discharge_eligible: true,
                body_discharge_refusal_reason: None,
                panic_loci: Vec::new(),
                class_shapes: Vec::new(),
                source_warrants: Vec::new(),
                proofir_provenance: None,
                contract_name: d.name.clone(),
                pre: d.pre.as_deref().map(formula_to_value),
                post: d.post.as_deref().map(formula_to_value),
                inv: d.inv.as_deref().map(formula_to_value),
                out_binding: d.out_binding.clone(),
                produced_by: "sugar-lift".into(),
                produced_at: "2026-01-01T00:00:00.000Z".into(),
                input_cids: vec![],
                authoring: Authoring::Lift {
                    lifter: "sugar-lift".into(),
                    evidence: String::new(),
                    source_cid: None,
                },
                signer_seed: [0u8; 32],
            };
            (d.name.clone(), compute_contract_cid(&args))
        })
        .collect();

    assert!(
        cid_map.contains_key("a"),
        "expected `a` in contract map; got {:?}",
        cid_map.keys().collect::<Vec<_>>()
    );
    assert!(cid_map.contains_key("b"), "expected `b` in contract map");

    let edges = extract_call_edges_from_file(&parsed, "test1.rs", &cid_map);

    // b calls a → exactly one edge.
    assert!(!edges.is_empty(), "expected at least one call edge");

    let b_to_a = edges
        .iter()
        .find(|e| e.source_contract_cid == *cid_map.get("b").unwrap() && e.target_symbol == "a");

    let b_to_a = b_to_a.expect("expected a call edge from b to a");

    // target_contract_cid must be set (a is in the same unit).
    assert_eq!(
        b_to_a.target_contract_cid.as_deref(),
        Some(cid_map.get("a").unwrap().as_str()),
        "targetContractCid must match a's contractCid"
    );

    // sourceContractCid must match b's.
    assert_eq!(
        b_to_a.source_contract_cid,
        *cid_map.get("b").unwrap(),
        "sourceContractCid must match b's contractCid"
    );
}

// ---------------------------------------------------------------------------
// Test 2: b() calls extern "C" function → targetContractCid null, targetSymbol set.
// ---------------------------------------------------------------------------

#[test]
fn test2_extern_c_callee_has_null_target_and_symbol() {
    // Source: b calls `rust_add` which is declared extern "C".
    let src = r#"
extern "C" {
    fn rust_add(x: i64, y: i64) -> i64;
}

#[requires(x > 0)]
#[ensures(result >= 0)]
fn b(x: i64) -> i64 {
    unsafe { rust_add(x, 1) }
}
"#;

    let parsed = syn::parse_file(src).expect("parse_file");
    let adapter_out = adapter_contracts::lift_file(&parsed, "test2.rs");
    assert!(adapter_out.lifted >= 1, "expected >=1 contract (b)");

    let cid_map: BTreeMap<String, String> = adapter_out
        .decls
        .iter()
        .map(|d| {
            let args = MintContractArgs {
                evidence_term: None,
                formals: Vec::new(),
                emit_empty_formals: false,
                formal_sorts: Vec::new(),
                library: None,
                body_discharge_eligible: true,
                body_discharge_refusal_reason: None,
                panic_loci: Vec::new(),
                class_shapes: Vec::new(),
                source_warrants: Vec::new(),
                proofir_provenance: None,
                contract_name: d.name.clone(),
                pre: d.pre.as_deref().map(formula_to_value),
                post: d.post.as_deref().map(formula_to_value),
                inv: d.inv.as_deref().map(formula_to_value),
                out_binding: d.out_binding.clone(),
                produced_by: "sugar-lift".into(),
                produced_at: "2026-01-01T00:00:00.000Z".into(),
                input_cids: vec![],
                authoring: Authoring::Lift {
                    lifter: "sugar-lift".into(),
                    evidence: String::new(),
                    source_cid: None,
                },
                signer_seed: [0u8; 32],
            };
            (d.name.clone(), compute_contract_cid(&args))
        })
        .collect();

    // `rust_add` is not in the contract map (no annotations).
    assert!(
        !cid_map.contains_key("rust_add"),
        "rust_add should not have a contract"
    );

    let edges = extract_call_edges_from_file(&parsed, "test2.rs", &cid_map);

    let to_rust_add = edges.iter().find(|e| e.target_symbol == "rust_add");
    let to_rust_add = to_rust_add.expect("expected call edge to rust_add");

    // targetContractCid must be null (not in this unit's contract set).
    assert!(
        to_rust_add.target_contract_cid.is_none(),
        "targetContractCid must be None for extern callee; got {:?}",
        to_rust_add.target_contract_cid
    );

    // targetSymbol must be populated.
    assert_eq!(
        to_rust_add.target_symbol, "rust_add",
        "targetSymbol must be `rust_add`"
    );
}

// ---------------------------------------------------------------------------
// Test 3: JCS bytes are byte-deterministic across two independent lifts.
// ---------------------------------------------------------------------------

#[test]
fn test3_jcs_bytes_are_deterministic_across_two_lifts() {
    let src = r#"
#[requires(x > 0)]
#[ensures(result >= 0)]
fn a(x: i64) -> i64 { x }

#[requires(n > 0)]
#[ensures(result >= 0)]
fn b(n: i64) -> i64 { a(n) }
"#;

    let parsed = syn::parse_file(src).expect("parse_file");

    let build_cid_map = || {
        let adapter_out = adapter_contracts::lift_file(&parsed, "test3.rs");
        adapter_out
            .decls
            .iter()
            .map(|d| {
                let args = MintContractArgs {
                    evidence_term: None,
                    formals: Vec::new(),
                    emit_empty_formals: false,
                    formal_sorts: Vec::new(),
                    library: None,
                    body_discharge_eligible: true,
                    body_discharge_refusal_reason: None,
                    panic_loci: Vec::new(),
                    class_shapes: Vec::new(),
                    source_warrants: Vec::new(),
                    proofir_provenance: None,
                    contract_name: d.name.clone(),
                    pre: d.pre.as_deref().map(formula_to_value),
                    post: d.post.as_deref().map(formula_to_value),
                    inv: d.inv.as_deref().map(formula_to_value),
                    out_binding: d.out_binding.clone(),
                    produced_by: "sugar-lift".into(),
                    produced_at: "2026-01-01T00:00:00.000Z".into(),
                    input_cids: vec![],
                    authoring: Authoring::Lift {
                        lifter: "sugar-lift".into(),
                        evidence: String::new(),
                        source_cid: None,
                    },
                    signer_seed: [0u8; 32],
                };
                (d.name.clone(), compute_contract_cid(&args))
            })
            .collect::<BTreeMap<_, _>>()
    };

    let cid_map1 = build_cid_map();
    let cid_map2 = build_cid_map();

    // CID maps must be identical across two runs.
    assert_eq!(cid_map1, cid_map2, "contractCid maps must be deterministic");

    let edges1 = extract_call_edges_from_file(&parsed, "test3.rs", &cid_map1);
    let edges2 = extract_call_edges_from_file(&parsed, "test3.rs", &cid_map2);

    assert_eq!(edges1.len(), edges2.len(), "edge counts must match");

    for (e1, e2) in edges1.iter().zip(edges2.iter()) {
        assert_eq!(
            e1.canonical_bytes, e2.canonical_bytes,
            "JCS bytes must be byte-deterministic across two lifts"
        );
        assert_eq!(
            e1.cid, e2.cid,
            "CIDs must be byte-deterministic across two lifts"
        );
    }

    // At least one edge must have been emitted.
    assert!(!edges1.is_empty(), "expected at least one call edge");
}

// ---------------------------------------------------------------------------
// Test 4: #[no_mangle] pub extern "C" fn foo lifts with name = "foo"
//         and pre = (n > 0): the Rust-side reciprocal for the Go cgo
//         resolver round-trip (spec #114 R3 / dispatch Part 3).
//
// The Go resolver emits targetSymbol = "rust-kit:foo". The linker resolves
// this against the Rust contract set by matching (kit="rust-kit", name="foo").
// This test asserts that the Rust contracts adapter produces a contract with
// name "foo" (not "foo::0" or any mangled variant) when given the canonical
// #[no_mangle] pub extern "C" fn shape.
// ---------------------------------------------------------------------------

#[test]
fn test4_extern_c_fn_lifts_with_canonical_name_and_pre() {
    let src = r#"
#[requires(n > 0)]
#[no_mangle]
pub extern "C" fn foo(n: i32) -> i32 {
    n
}
"#;

    let parsed = syn::parse_file(src).expect("parse_file");
    let adapter_out = adapter_contracts::lift_file(&parsed, "test4.rs");

    assert!(
        adapter_out.lifted >= 1,
        "expected at least 1 contract for extern C fn; got {} (warnings: {:?})",
        adapter_out.lifted,
        adapter_out.warnings
    );

    // Find the contract named "foo": name must be the bare function name,
    // not a mangled or namespace-prefixed variant. The Go resolver emits
    // targetSymbol = "rust-kit:foo"; the linker resolves by matching name "foo".
    let foo_contract = adapter_out
        .decls
        .iter()
        .find(|d| d.name == "foo")
        .expect("expected a contract with name == \"foo\" for extern C fn");

    // The contract must have a non-trivial precondition lifted from
    // #[requires(n > 0)].
    assert!(
        foo_contract.pre.is_some(),
        "contract for `foo` must have a precondition from #[requires(n > 0)]"
    );

    // Verify it round-trips through the CID computation without panic.
    let args = MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: None,
        contract_name: foo_contract.name.clone(),
        pre: foo_contract.pre.as_deref().map(formula_to_value),
        post: foo_contract.post.as_deref().map(formula_to_value),
        inv: foo_contract.inv.as_deref().map(formula_to_value),
        out_binding: foo_contract.out_binding.clone(),
        produced_by: "sugar-lift".into(),
        produced_at: "2026-01-01T00:00:00.000Z".into(),
        input_cids: vec![],
        authoring: Authoring::Lift {
            lifter: "sugar-lift".into(),
            evidence: String::new(),
            source_cid: None,
        },
        signer_seed: [0u8; 32],
    };
    let cid = compute_contract_cid(&args);
    assert!(
        cid.starts_with("blake3-512:"),
        "contractCid must start with blake3-512: prefix; got {cid}"
    );

    // The contract name "foo" must match what the Go resolver expects.
    // Go emits: targetSymbol = "rust-kit:foo"
    // Linker resolves: split on ":", kit="rust-kit", name="foo"
    // This contract's name == "foo" → round-trip succeeds.
    assert_eq!(
        foo_contract.name, "foo",
        "contract name must be \"foo\" for the Go resolver round-trip"
    );
}
