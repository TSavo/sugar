// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Emits pinned test fixtures for the C kit's cross-kit byte-equivalence tests.
// Run: cargo run --release -p sugar-claim-envelope --bin emit_c_fixtures
//
// Prints to stdout:
//   1. ed25519 pubkey string for seed=[0x42;32]
//   2. ed25519 sig string for (seed=[0x42;32], message=b"hello")
//   3. mint_contract canonical_bytes (hex) + attestation CID for the standard fixture
//   4. proof envelope bytes (hex) + CID for the standard fixture

use std::sync::Arc;

use sugar_canonicalizer::Value;
use sugar_claim_envelope::{mint_contract, Authoring, MintContractArgs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, ed25519_sign_string, ed25519_sign_with_seed,
    ClaimContractMemento, Ed25519Seed, ProofEnvelopeInput, ProofGraph,
};

const SEED: Ed25519Seed = [0x42u8; 32];
const PRODUCED_AT: &str = "2026-04-30T00:00:00.000Z";
const PRODUCED_BY: &str = "c-kit@1.0";

fn pre_n_gt_0() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("atomic")),
        ("name", Value::string(">")),
        (
            "args",
            Value::array(vec![
                Value::object([("kind", Value::string("var")), ("name", Value::string("n"))]),
                Value::object([
                    ("kind", Value::string("const")),
                    ("value", Value::integer(0)),
                    (
                        "sort",
                        Value::object([
                            ("kind", Value::string("primitive")),
                            ("name", Value::string("Int")),
                        ]),
                    ),
                ]),
            ]),
        ),
    ])
}

fn main() {
    // --- 1. Ed25519 pubkey string ---
    let pubkey_str = ed25519_pubkey_string(&SEED);
    println!("=== ED25519_PUBKEY_STRING ===");
    println!("{}", pubkey_str);

    // --- 2. Ed25519 signature of "hello" ---
    let sig_str = ed25519_sign_string(&SEED, b"hello");
    println!("=== ED25519_SIG_HELLO ===");
    println!("{}", sig_str);

    // --- 3. Raw signature bytes of "hello" as hex ---
    let raw_sig = ed25519_sign_with_seed(&SEED, b"hello");
    let hex: String = raw_sig.iter().map(|b| format!("{:02x}", b)).collect();
    println!("=== ED25519_SIG_HELLO_RAW_HEX ===");
    println!("{}", hex);

    // --- 4. mint_contract canonical_bytes + CID ---
    let args = MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        bridge_source_symbol: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: None,
        contract_name: "parseInt".into(),
        pre: Some(pre_n_gt_0()),
        post: None,
        inv: None,
        out_binding: "out".into(),
        produced_by: PRODUCED_BY.into(),
        produced_at: PRODUCED_AT.into(),
        input_cids: vec![],
        authoring: Authoring::KitAuthor {
            author: PRODUCED_BY.into(),
            note: None,
        },
        signer_seed: SEED,
    };
    let m = mint_contract(&args).expect("mint_contract");
    let hex: String = m
        .canonical_bytes
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect();
    println!("=== MINT_CONTRACT_HEX ===");
    println!("{}", hex);
    println!("=== MINT_CONTRACT_CID ===");
    println!("{}", m.cid);
    println!("=== MINT_CONTRACT_CONTRACT_CID ===");
    println!("{}", m.contract_cid);
    println!("=== MINT_CONTRACT_BYTES_LEN ===");
    println!("{}", m.canonical_bytes.len());

    // --- 5. proof envelope with the contract as sole member ---
    let contract_memento = ClaimContractMemento::new(m.canonical_bytes.clone());
    assert_eq!(contract_memento.cid().as_str(), m.cid);
    let mut graph = ProofGraph::new();
    graph.push_claim_contract(contract_memento);
    let proof_input = ProofEnvelopeInput {
        name: "@sugar/c-test".into(),
        version: "0.0.1".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid: pubkey_str.clone(),
        signer_seed: SEED,
        declared_at: PRODUCED_AT.into(),
        manifest: None,
    };
    let proof_out = build_proof_envelope(&proof_input);
    let hex: String = proof_out
        .bytes
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect();
    println!("=== PROOF_ENVELOPE_HEX ===");
    println!("{}", hex);
    println!("=== PROOF_ENVELOPE_CID ===");
    println!("{}", proof_out.cid);
}
