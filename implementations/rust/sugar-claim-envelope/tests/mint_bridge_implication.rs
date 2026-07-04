// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Tests for `mint_bridge` and `mint_implication`. Pins:
//
// mint_bridge:
//   - bindingHash  = BLAKE3-512(JCS({sourceLayer, sourceSymbol}))
//   - propertyHash = BLAKE3-512("bridge:" + sourceSymbol)
//   - inputCids[0] == targetContractCid
//
// mint_implication:
//   - bindingHash  = BLAKE3-512(JCS({antecedentHash, consequentHash}))
//   - propertyHash = BLAKE3-512("implication:" + ah + ":" + ch)
//   - inputCids contains both antecedent and consequent CIDs (lex-sorted
//     by the wrapper)
//   - antecedentSlot / consequentSlot are stored verbatim (no validation)

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_claim_envelope::{mint_bridge, mint_implication, MintBridgeArgs, MintImplicationArgs};
use sugar_proof_envelope::{
    BridgeMemento, ContractMementoRef, Ed25519Seed, ImplicationMemento, ProofGraph,
};

fn seed() -> Ed25519Seed {
    [0x42u8; 32]
}

fn fixture_cid(hex: char) -> String {
    format!("blake3-512:{}", hex.to_string().repeat(128))
}

// ---------------------------------------------------------------------------
// mint_bridge
// ---------------------------------------------------------------------------

fn bridge_args() -> MintBridgeArgs {
    MintBridgeArgs {
        produced_by: "rust-test@1.0".into(),
        produced_at: "2026-04-30T00:00:00.000Z".into(),
        source_symbol: "parseInt".into(),
        source_layer: "ts".into(),
        target_contract: ContractMementoRef::new(fixture_cid('c')),
        target_layer: "rust-kit".into(),
        ir_arg_sorts: vec!["String".into()],
        ir_return_sort: "Int".into(),
        notes: String::new(),
        signer_seed: seed(),
        target_proof_cid: None,
        callsite: None,
    }
}

#[test]
fn bridge_cid_is_blake3_512_prefixed() {
    let m = mint_bridge(&bridge_args());
    assert!(m.cid.starts_with("blake3-512:"));
    assert_eq!(m.cid.len(), "blake3-512:".len() + 128);
}

#[test]
fn bridge_property_hash_is_blake3_of_bridge_prefix_plus_source_symbol() {
    let m = mint_bridge(&bridge_args());
    let mut g = ProofGraph::new();
    g.push_bridge(BridgeMemento::new(m.canonical_bytes.clone()));
    let view = g.bridges().next().unwrap();
    let ph = view.field("propertyHash").unwrap();
    let expected = blake3_512_of(b"bridge:parseInt");
    assert_eq!(ph, expected);
}

#[test]
fn bridge_binding_hash_is_blake3_of_jcs_source_layer_and_source_symbol() {
    let m = mint_bridge(&bridge_args());
    let mut g = ProofGraph::new();
    g.push_bridge(BridgeMemento::new(m.canonical_bytes.clone()));
    let view = g.bridges().next().unwrap();
    let bh = view.field("bindingHash").unwrap();

    let v = Value::object([
        ("sourceLayer", Value::string("ts")),
        ("sourceSymbol", Value::string("parseInt")),
    ]);
    let expected = blake3_512_of(encode_jcs(&v).as_bytes());
    assert_eq!(bh, expected);
}

#[test]
fn bridge_input_cids_first_entry_is_target_contract_cid() {
    let m = mint_bridge(&bridge_args());
    let mut g = ProofGraph::new();
    g.push_bridge(BridgeMemento::new(m.canonical_bytes.clone()));
    let view = g.bridges().next().unwrap();
    let json = view.json();
    let cids = json
        .get("header")
        .and_then(|h| h.get("inputCids"))
        .and_then(|v| v.as_array())
        .expect("inputCids array");
    assert_eq!(cids.len(), 1);
    assert_eq!(cids[0].as_str(), Some(fixture_cid('c').as_str()));
}

#[test]
fn bridge_evidence_kind_is_bridge() {
    let m = mint_bridge(&bridge_args());
    let mut g = ProofGraph::new();
    g.push_bridge(BridgeMemento::new(m.canonical_bytes.clone()));
    let view = g.bridges().next().unwrap();
    assert_eq!(view.kind().map(|kind| kind.as_str()), Some("bridge"));
}

#[test]
fn bridge_body_carries_all_input_fields() {
    // Substrate-load-bearing bridge fields live in the header (spec §3
    // bridge example). The legacy `/evidence/body/X` location is gone.
    let m = mint_bridge(&bridge_args());
    let mut g = ProofGraph::new();
    g.push_bridge(BridgeMemento::new(m.canonical_bytes.clone()));
    let view = g.bridges().next().unwrap();
    assert_eq!(view.field("sourceSymbol").as_deref(), Some("parseInt"));
    assert_eq!(view.field("sourceLayer").as_deref(), Some("ts"));
    assert_eq!(
        view.field("targetContractCid").as_deref(),
        Some(fixture_cid('c').as_str())
    );
    assert_eq!(view.field("targetLayer").as_deref(), Some("rust-kit"));
    assert_eq!(view.field("irReturnSort").as_deref(), Some("Int"));
    let json = view.json();
    let arg_sorts = json
        .get("header")
        .and_then(|h| h.get("irArgSorts"))
        .and_then(|v| v.as_array())
        .unwrap();
    assert_eq!(arg_sorts.len(), 1);
    assert_eq!(arg_sorts[0].as_str(), Some("String"));
}

#[test]
fn bridge_notes_omitted_when_empty() {
    // `notes` is producer-attached metadata, not substrate. It rides
    // in the body (`metadata`) when non-empty; absent when empty.
    let m = mint_bridge(&bridge_args());
    let mut g = ProofGraph::new();
    g.push_bridge(BridgeMemento::new(m.canonical_bytes.clone()));
    let view = g.bridges().next().unwrap();
    assert!(view.field("notes").is_none());
}

#[test]
fn bridge_notes_included_when_provided() {
    let mut a = bridge_args();
    a.notes = "smoke from kit".into();
    let m = mint_bridge(&a);
    let mut g = ProofGraph::new();
    g.push_bridge(BridgeMemento::new(m.canonical_bytes.clone()));
    let view = g.bridges().next().unwrap();
    assert_eq!(view.field("notes").as_deref(), Some("smoke from kit"));
}

#[test]
fn bridge_is_deterministic() {
    let a = mint_bridge(&bridge_args());
    let b = mint_bridge(&bridge_args());
    assert_eq!(a.cid, b.cid);
    assert_eq!(a.canonical_bytes, b.canonical_bytes);
}

#[test]
fn bridge_changing_source_symbol_changes_property_hash() {
    let mut a = bridge_args();
    let mut b = bridge_args();
    b.source_symbol = "atoi".into();
    let m_a = mint_bridge(&a);
    let m_b = mint_bridge(&b);
    let mut g_a = ProofGraph::new();
    g_a.push_bridge(BridgeMemento::new(m_a.canonical_bytes.clone()));
    let view_a = g_a.bridges().next().unwrap();
    let mut g_b = ProofGraph::new();
    g_b.push_bridge(BridgeMemento::new(m_b.canonical_bytes.clone()));
    let view_b = g_b.bridges().next().unwrap();
    let ph_a = view_a.field("propertyHash").unwrap();
    let ph_b = view_b.field("propertyHash").unwrap();
    assert_ne!(ph_a, ph_b);
    a.source_symbol = "x".into();
    let _ = a;
}

// ---------------------------------------------------------------------------
// mint_implication
// ---------------------------------------------------------------------------

fn impl_args() -> MintImplicationArgs {
    MintImplicationArgs {
        produced_by: "z3".into(),
        produced_at: "2026-04-30T00:00:00.000Z".into(),
        antecedent_hash: fixture_cid('a'),
        consequent_hash: fixture_cid('c'),
        antecedent: ContractMementoRef::new(fixture_cid('f')),
        consequent: ContractMementoRef::new(fixture_cid('b')),
        additional_inputs: Vec::new(),
        antecedent_slot: "pre".into(),
        consequent_slot: "post".into(),
        prover: "z3@4.13".into(),
        prover_run_ms: 42,
        smt_lib_input: String::new(),
        proof_witness: String::new(),
        signer_seed: seed(),
    }
}

#[test]
fn implication_cid_is_blake3_512_prefixed() {
    let m = mint_implication(&impl_args());
    assert!(m.cid.starts_with("blake3-512:"));
    assert_eq!(m.cid.len(), "blake3-512:".len() + 128);
}

#[test]
fn implication_evidence_kind_is_implication() {
    let m = mint_implication(&impl_args());
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    assert_eq!(view.kind().map(|kind| kind.as_str()), Some("implication"));
}

#[test]
fn implication_property_hash_is_blake3_of_implication_prefix_plus_hashes() {
    let m = mint_implication(&impl_args());
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    let ph = view.field("propertyHash").unwrap();
    let expected =
        blake3_512_of(format!("implication:{}:{}", fixture_cid('a'), fixture_cid('c')).as_bytes());
    assert_eq!(ph, expected);
}

#[test]
fn implication_binding_hash_is_blake3_of_jcs_antecedent_consequent_hashes() {
    let m = mint_implication(&impl_args());
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    let bh = view.field("bindingHash").unwrap();

    let v = Value::object([
        ("antecedentHash", Value::string(fixture_cid('a'))),
        ("consequentHash", Value::string(fixture_cid('c'))),
    ]);
    let expected = blake3_512_of(encode_jcs(&v).as_bytes());
    assert_eq!(bh, expected);
}

#[test]
fn implication_input_cids_contain_both_antecedent_and_consequent_lex_sorted() {
    let m = mint_implication(&impl_args());
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    let json = view.json();
    // antecedent_cid="ffff...", consequent_cid="bbbb..."; envelope wrapper sorts.
    let cids = json
        .get("header")
        .and_then(|h| h.get("inputCids"))
        .and_then(|v| v.as_array())
        .expect("array");
    assert_eq!(cids.len(), 2);
    assert_eq!(cids[0].as_str(), Some(fixture_cid('b').as_str()));
    assert_eq!(cids[1].as_str(), Some(fixture_cid('f').as_str()));
}

#[test]
fn implication_body_carries_slots_verbatim() {
    // antecedentSlot / consequentSlot are header-level: they bind the
    // implication to specific slots in the antecedent/consequent
    // contracts and are part of the substrate's resolution view.
    let m = mint_implication(&impl_args());
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    assert_eq!(view.field("antecedentSlot").as_deref(), Some("pre"));
    assert_eq!(view.field("consequentSlot").as_deref(), Some("post"));
}

#[test]
fn implication_smt_input_omitted_when_empty() {
    // SMT input + proof witness ride in metadata: prover-generated
    // tooling artifacts, not substrate-load-bearing.
    let m = mint_implication(&impl_args());
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    assert!(view.field("smtLibInput").is_none());
    assert!(view.field("proofWitness").is_none());
}

#[test]
fn implication_smt_input_included_when_provided() {
    let mut a = impl_args();
    a.smt_lib_input = "(declare-const x Int)\n(check-sat)".into();
    a.proof_witness = "(unsat)".into();
    let m = mint_implication(&a);
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    assert_eq!(
        view.field("smtLibInput").as_deref(),
        Some("(declare-const x Int)\n(check-sat)")
    );
    assert_eq!(view.field("proofWitness").as_deref(), Some("(unsat)"));
}

#[test]
fn implication_prover_run_ms_round_trips() {
    let m = mint_implication(&impl_args());
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    let json = view.json();
    assert_eq!(
        json.get("metadata")
            .and_then(|m| m.get("proverRunMs"))
            .and_then(|v| v.as_i64()),
        Some(42)
    );
}

#[test]
fn implication_is_deterministic() {
    let a = mint_implication(&impl_args());
    let b = mint_implication(&impl_args());
    assert_eq!(a.cid, b.cid);
}

#[test]
fn implication_changing_antecedent_hash_changes_property_hash() {
    let a = mint_implication(&impl_args());
    let mut other = impl_args();
    other.antecedent_hash = fixture_cid('d');
    let b = mint_implication(&other);
    let mut g_a = ProofGraph::new();
    g_a.push_implication(ImplicationMemento::new(a.canonical_bytes.clone()));
    let view_a = g_a.implications().next().unwrap();
    let mut g_b = ProofGraph::new();
    g_b.push_implication(ImplicationMemento::new(b.canonical_bytes.clone()));
    let view_b = g_b.implications().next().unwrap();
    assert_ne!(
        view_a.field("propertyHash").unwrap(),
        view_b.field("propertyHash").unwrap()
    );
}

#[test]
fn implication_envelope_carries_producer_signature() {
    let m = mint_implication(&impl_args());
    let mut g = ProofGraph::new();
    g.push_implication(ImplicationMemento::new(m.canonical_bytes.clone()));
    let view = g.implications().next().unwrap();
    let json = view.json();
    let sig = json
        .get("envelope")
        .and_then(|e| e.get("signature"))
        .and_then(|v| v.as_str())
        .unwrap();
    assert!(sig.starts_with("ed25519:"));
}

#[test]
fn bridge_envelope_carries_producer_signature() {
    let m = mint_bridge(&bridge_args());
    let mut g = ProofGraph::new();
    g.push_bridge(BridgeMemento::new(m.canonical_bytes.clone()));
    let view = g.bridges().next().unwrap();
    let json = view.json();
    let sig = json
        .get("envelope")
        .and_then(|e| e.get("signature"))
        .and_then(|v| v.as_str())
        .unwrap();
    assert!(sig.starts_with("ed25519:"));
}
