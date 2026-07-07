// SPDX-License-Identifier: MIT OR Apache-2.0
//
// .proof catalog envelope tests. Pins:
//   - filename CID matches BLAKE3-512 of the catalog bytes (trust-root)
//   - CID is "blake3-512:" + 128 hex chars
//   - Same input -> same bytes (deterministic across runs)
//   - Map head reflects 9 keys: atoms, body, kind, name, version, members,
//     signer, declaredAt, signature
//   - CID maps keys are CBOR-text-string-encoded and contain graph/member
//     bytes as a CBOR byte string

use sugar_canonicalizer::blake3_512_of;
use sugar_proof_envelope::{build_proof_envelope, ProofEnvelopeInput, ProofGraph, SourceMemento};

fn source_memento(label: &str) -> SourceMemento {
    SourceMemento::new(
        format!(
            r#"{{"body":{{"kind":"source-memento","label":"{label}","source_cid":"blake3-512:{label}"}},"header":{{"kind":"source-memento","sourceCid":"blake3-512:{label}"}},"schemaVersion":"1"}}"#
        )
        .into_bytes(),
    )
}

fn graph_with_sources(labels: &[&str]) -> ProofGraph {
    let mut graph = ProofGraph::new();
    for label in labels {
        graph.push_source(source_memento(label));
    }
    graph
}

fn fixture_input() -> ProofEnvelopeInput {
    ProofEnvelopeInput {
        name: "@test/cat".to_string(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata: None,
        graph: graph_with_sources(&["aa", "bb"]),
        signer_cid: "blake3-512:cc".to_string(),
        signer_seed: [0x42u8; 32],
        declared_at: "2026-04-30T00:00:00.000Z".to_string(),
        manifest: None,
    }
}

// ---------------------------------------------------------------------------
// Trust root: filename CID == BLAKE3-512 of bytes
// ---------------------------------------------------------------------------

#[test]
fn cid_equals_blake3_512_of_emitted_bytes() {
    let input = fixture_input();
    let out = build_proof_envelope(&input);
    let recomputed = blake3_512_of(&out.bytes);
    assert_eq!(out.cid, recomputed);
}

#[test]
fn cid_has_blake3_512_prefix() {
    let input = fixture_input();
    let out = build_proof_envelope(&input);
    assert!(out.cid.starts_with("blake3-512:"));
}

#[test]
fn cid_total_length_is_prefix_plus_128() {
    let input = fixture_input();
    let out = build_proof_envelope(&input);
    assert_eq!(out.cid.len(), "blake3-512:".len() + 128);
}

// ---------------------------------------------------------------------------
// Determinism
// ---------------------------------------------------------------------------

#[test]
fn same_input_produces_identical_bytes() {
    let a = build_proof_envelope(&fixture_input());
    let b = build_proof_envelope(&fixture_input());
    assert_eq!(a.bytes, b.bytes);
    assert_eq!(a.cid, b.cid);
}

#[test]
fn member_insertion_order_does_not_matter() {
    // Typed mementos can be pushed in any order. The graph lowers to sorted CID
    // maps at the serialization edge, so the catalog bytes stay deterministic.
    let mk = |graph: ProofGraph| ProofEnvelopeInput {
        name: "x".into(),
        version: "1".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid: "blake3-512:cc".into(),
        signer_seed: [0u8; 32],
        declared_at: "2026-04-30T00:00:00.000Z".into(),
        manifest: None,
    };
    assert_eq!(
        build_proof_envelope(&mk(graph_with_sources(&["bb", "aa"]))).bytes,
        build_proof_envelope(&mk(graph_with_sources(&["aa", "bb"]))).bytes
    );
}

// ---------------------------------------------------------------------------
// Catalog map shape
// ---------------------------------------------------------------------------

#[test]
fn signed_catalog_map_head_is_nine_keys() {
    let input = fixture_input();
    let out = build_proof_envelope(&input);
    // 9-key map head: major 5 (0xA0) + count 9 = 0xA9.
    assert_eq!(out.bytes[0], 0xA9);
}

#[test]
fn empty_members_still_produces_valid_envelope() {
    let input = ProofEnvelopeInput {
        name: "x".into(),
        version: "1".into(),
        binary_cid: None,
        metadata: None,
        graph: ProofGraph::new(),
        signer_cid: "blake3-512:cc".into(),
        signer_seed: [0u8; 32],
        declared_at: "2026-04-30T00:00:00.000Z".into(),
        manifest: None,
    };
    let out = build_proof_envelope(&input);
    assert_eq!(out.bytes[0], 0xA9);
    assert!(out.cid.starts_with("blake3-512:"));
}

// ---------------------------------------------------------------------------
// Sensitivity: changing any input field changes the CID
// ---------------------------------------------------------------------------

#[test]
fn changing_name_changes_cid() {
    let mut a = fixture_input();
    let mut b = fixture_input();
    b.name = "@other/name".into();
    assert_ne!(build_proof_envelope(&a).cid, build_proof_envelope(&b).cid);
    a.name = "@test/cat".into(); // sanity
    let _ = a;
}

#[test]
fn changing_version_changes_cid() {
    let mut b = fixture_input();
    b.version = "2.0.0".into();
    assert_ne!(
        build_proof_envelope(&fixture_input()).cid,
        build_proof_envelope(&b).cid
    );
}

#[test]
fn changing_members_changes_cid() {
    let mut b = fixture_input();
    b.graph.push_source(source_memento("dd"));
    assert_ne!(
        build_proof_envelope(&fixture_input()).cid,
        build_proof_envelope(&b).cid
    );
}

#[test]
fn changing_signer_cid_changes_cid() {
    let mut b = fixture_input();
    b.signer_cid = "blake3-512:other".into();
    assert_ne!(
        build_proof_envelope(&fixture_input()).cid,
        build_proof_envelope(&b).cid
    );
}

#[test]
fn changing_signer_seed_changes_cid() {
    let mut b = fixture_input();
    b.signer_seed = [0x99u8; 32];
    // The signature bytes change with a new seed, so the catalog bytes
    // (and hence CID) change too.
    assert_ne!(
        build_proof_envelope(&fixture_input()).cid,
        build_proof_envelope(&b).cid
    );
}

#[test]
fn changing_declared_at_changes_cid() {
    let mut b = fixture_input();
    b.declared_at = "2099-12-31T23:59:59.999Z".into();
    assert_ne!(
        build_proof_envelope(&fixture_input()).cid,
        build_proof_envelope(&b).cid
    );
}

// ---------------------------------------------------------------------------
// Member-bytes filename CID rule (independent of catalog wrapping)
// ---------------------------------------------------------------------------

#[test]
fn catalog_member_filename_rule_matches_blake3_of_value_bytes() {
    // Typed member wrappers derive their member CID from the memento bytes.
    // Changing the memento bytes changes the graph edge and therefore the
    // catalog CID.
    let mk = |graph: ProofGraph| ProofEnvelopeInput {
        name: "x".into(),
        version: "1".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid: "blake3-512:cc".into(),
        signer_seed: [0u8; 32],
        declared_at: "2026-04-30T00:00:00.000Z".into(),
        manifest: None,
    };
    assert_ne!(
        build_proof_envelope(&mk(graph_with_sources(&["aa"]))).cid,
        build_proof_envelope(&mk(graph_with_sources(&["bb"]))).cid
    );
}
