// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Round-trip and CID-recompute tests for ProofRunMemento + StageReceipt.
//
// Source of truth:
//   protocol/specs/2026-05-13-proof-run-memento.md §1 and §4
//
// The tests intentionally do NOT pin a hardcoded `header.cid` against a
// magic string. Instead they exercise canonicalization invariants directly:
//   1. recompute is deterministic (same input → same output)
//   2. recompute elides `cid` before hashing (so setting the stored value
//      to the recomputed result still hashes to the same bytes)
//   3. round-trip via `to_jcs_string` → `from_str` is the identity on a
//      memento whose stored `cid` matches the recomputed value
//
// The fixtures use placeholder all-zero CIDs for the referenced artifacts;
// only `header.cid` is derived. JCS-canonical key order applies.

use sugar_ir_types::{ProofRunMemento, StageReceipt};

const PROOF_RUN_FIXTURE_PLACEHOLDER_CID: &str = r#"{"envelope":{"declaredAt":"2026-05-13T18:00:00Z","signature":"ed25519:fixture-signature","signer":"ed25519:fixture-signer"},"header":{"cid":"blake3-512:PENDING","input_artifact_cids":["blake3-512:1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111","blake3-512:2222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222"],"input_run_cids":[],"kind":"proof-run","link_bundle_cid":"blake3-512:3333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333","output_artifact_cids":["blake3-512:4444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444"],"plugin_registry_cid":"blake3-512:5555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555","proof_envelope_cid":"blake3-512:6666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666","schemaVersion":"1","sealed_at":"2026-05-13T18:00:00Z","stage_receipt_cids":["blake3-512:7777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777","blake3-512:8888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888"],"verdict":"admissible","verifier_pipeline_cid":"blake3-512:9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999"},"metadata":{"note":"Reference proof-run fixture."}}"#;

const STAGE_RECEIPT_FIXTURE_PLACEHOLDER_CID: &str = r#"{"envelope":{"declaredAt":"2026-05-13T18:00:00Z","signature":"ed25519:fixture-signature","signer":"ed25519:fixture-signer"},"header":{"cid":"blake3-512:PENDING","diagnostics":[],"finished_at":"2026-05-13T18:00:01Z","input_cids":["blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],"kind":"stage-receipt","output_cids":["blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],"refusal_cids":[],"schemaVersion":"1","stage_name":"load_all_proofs","started_at":"2026-05-13T18:00:00Z","verdict":"ok"},"metadata":{}}"#;

fn parse_proof_run() -> ProofRunMemento {
    serde_json::from_str(PROOF_RUN_FIXTURE_PLACEHOLDER_CID).expect("parse proof-run fixture")
}

fn parse_stage_receipt() -> StageReceipt {
    serde_json::from_str(STAGE_RECEIPT_FIXTURE_PLACEHOLDER_CID)
        .expect("parse stage-receipt fixture")
}

#[test]
fn proof_run_recompute_is_deterministic_and_elides_cid() {
    let mut m = parse_proof_run();
    let computed = m.recompute_header_cid().expect("recompute");

    // Recompute is deterministic.
    assert_eq!(m.recompute_header_cid().expect("recompute again"), computed);

    // Setting `cid` to the computed value still produces the same hash
    // because §4 elides `cid` before JCS-hashing the header.
    m.header.cid = computed.clone();
    assert_eq!(
        m.recompute_header_cid().expect("recompute with real cid"),
        computed
    );

    // Sanity: a different placeholder produces the same recomputed value
    // because `cid` is elided.
    m.header.cid = "blake3-512:DIFFERENT_PLACEHOLDER".to_string();
    assert_eq!(
        m.recompute_header_cid()
            .expect("recompute with different placeholder"),
        computed
    );
}

#[test]
fn proof_run_round_trips_via_jcs_bytes() {
    let mut m = parse_proof_run();
    m.header.cid = m.recompute_header_cid().expect("recompute");

    let serialized = m.to_jcs_string().expect("canonicalize");
    let reparsed: ProofRunMemento =
        serde_json::from_str(&serialized).expect("reparse canonical bytes");

    assert_eq!(reparsed, m);
}

#[test]
fn proof_run_input_artifact_cids_are_sorted_in_cid_input() {
    // §2.1: input_artifact_cids sorts ascending (set semantics).
    // Reordering must NOT change the recomputed CID.
    let mut m = parse_proof_run();
    let cid_before = m.recompute_header_cid().expect("recompute before reorder");

    m.header.input_artifact_cids.reverse();
    let cid_after = m.recompute_header_cid().expect("recompute after reorder");

    assert_eq!(cid_before, cid_after);
}

#[test]
fn proof_run_output_artifact_cids_are_sorted_in_cid_input() {
    // §2.1: output_artifact_cids sorts ascending (set semantics).
    let mut m = parse_proof_run();
    let cid_before = m.recompute_header_cid().expect("recompute before reorder");

    m.header.output_artifact_cids.reverse();
    let cid_after = m.recompute_header_cid().expect("recompute after reorder");

    assert_eq!(cid_before, cid_after);
}

#[test]
fn proof_run_stage_receipt_cids_preserve_order_in_cid_input() {
    // §2.1: stage_receipt_cids preserves execution order (it matches the
    // verifier-pipeline stage vocabulary). Reordering MUST change the
    // recomputed CID.
    let mut m = parse_proof_run();
    let cid_before = m.recompute_header_cid().expect("recompute before reorder");

    m.header.stage_receipt_cids.reverse();
    let cid_after = m.recompute_header_cid().expect("recompute after reorder");

    assert_ne!(cid_before, cid_after);
}

#[test]
fn stage_receipt_recompute_is_deterministic_and_elides_cid() {
    let mut s = parse_stage_receipt();
    let computed = s.recompute_header_cid().expect("recompute");

    assert_eq!(s.recompute_header_cid().expect("recompute again"), computed);

    s.header.cid = computed.clone();
    assert_eq!(
        s.recompute_header_cid().expect("recompute with real cid"),
        computed
    );
}

#[test]
fn stage_receipt_round_trips_via_jcs_bytes() {
    let mut s = parse_stage_receipt();
    s.header.cid = s.recompute_header_cid().expect("recompute");

    let serialized = s.to_jcs_string().expect("canonicalize");
    let reparsed: StageReceipt =
        serde_json::from_str(&serialized).expect("reparse canonical bytes");

    assert_eq!(reparsed, s);
}

#[test]
fn stage_receipt_input_output_and_refusal_cids_are_sorted_in_cid_input() {
    // §2.2: input_cids, output_cids, and refusal_cids all sort ascending
    // (set semantics). The earlier draft of this test pinned input_cids
    // as order-preserving; that was wrong per §2.2 ("Non-empty set of
    // CIDs read by the stage, sorted ascending by bytewise CID").
    let mut s = parse_stage_receipt();
    // Add a second input so reversal is observable.
    s.header.input_cids.push(
        "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
            .to_string(),
    );
    let cid_before = s.recompute_header_cid().expect("recompute before reorder");

    s.header.input_cids.reverse();
    s.header.output_cids.reverse();
    let cid_after = s.recompute_header_cid().expect("recompute after reorder");

    assert_eq!(cid_before, cid_after);
}
