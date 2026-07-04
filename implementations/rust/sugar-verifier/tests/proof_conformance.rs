// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Proof-file conformance tests. These are the first dogfood target:
// `.proof` bytes -> proof-file-format conformance report.

use std::fs;
use std::path::PathBuf;

use sugar_canonicalizer::cid_hex;
use sugar_claim_envelope::{mint_contract, Authoring, MintContractArgs};
use sugar_ir_symbolic::serialize::formula_to_value;
use sugar_ir_symbolic::{forall, gt, must, num, reset_collector, Int};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, ClaimContractMemento, Ed25519Seed,
    ProofEnvelopeInput, ProofGraph,
};
use sugar_verifier::proof_conformance::{
    validate_proof_file, PFCP_R1_FILENAME_CID, PFCP_R9_CATALOG_SIGNATURE,
};

fn make_unique_dir(suffix: &str) -> PathBuf {
    let base = std::env::temp_dir();
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = base.join(format!("sugar-proof-conformance-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn fixture_proof_bytes() -> (String, Vec<u8>) {
    reset_collector();
    must("positiveInput", forall(Int(), |n| gt(n, num(0))));
    let declarations = sugar_ir_symbolic::finish();
    let declaration = declarations.first().expect("one declaration");
    let signer_seed: Ed25519Seed = [0x44u8; 32];
    let declared_at = "2026-05-06T00:00:00.000Z";
    let member = mint_contract(&MintContractArgs {
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
        contract_name: declaration.name.clone(),
        pre: declaration.pre.as_deref().map(formula_to_value),
        post: declaration.post.as_deref().map(formula_to_value),
        inv: declaration.inv.as_deref().map(formula_to_value),
        out_binding: declaration.out_binding.clone(),
        produced_by: "rust-test@1.0".into(),
        produced_at: declared_at.into(),
        input_cids: vec![],
        authoring: Authoring::KitAuthor {
            author: "rust-test@1.0".into(),
            note: None,
        },
        signer_seed,
    })
    .expect("mint member");
    let contract = ClaimContractMemento::new(member.canonical_bytes);
    assert_eq!(contract.cid().as_str(), member.cid);
    let mut graph = ProofGraph::new();
    graph.push_claim_contract(contract);

    let input = ProofEnvelopeInput {
        name: "@test/proof-conformance".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid: ed25519_pubkey_string(&signer_seed),
        signer_seed,
        declared_at: declared_at.into(),
    };
    let built = build_proof_envelope(&input);
    (built.cid, built.bytes)
}

#[test]
fn valid_proof_file_reports_conformant() {
    let dir = make_unique_dir("valid");
    let (cid, bytes) = fixture_proof_bytes();
    let hex = cid_hex(&cid).expect("cid prefix");
    let path = dir.join(format!("{hex}.proof"));
    fs::write(&path, bytes).expect("write proof");

    let report = validate_proof_file(&path);

    assert!(report.ok(), "{report:#?}");
    assert_eq!(report.file_cid, cid);
    assert_eq!(report.member_count, 1);
    assert!(report.errors.is_empty());
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn filename_cid_mismatch_reports_rule_1() {
    let dir = make_unique_dir("filename-mismatch");
    let (_cid, bytes) = fixture_proof_bytes();
    let bogus_hex = "0".repeat(128);
    let path = dir.join(format!("{bogus_hex}.proof"));
    fs::write(&path, bytes).expect("write proof");

    let report = validate_proof_file(&path);

    assert!(!report.ok(), "{report:#?}");
    assert!(report
        .errors
        .iter()
        .any(|error| error.rule_id == PFCP_R1_FILENAME_CID));
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn unsigned_catalog_reports_catalog_signature_rule() {
    let dir = make_unique_dir("unsigned-catalog");
    let bytes = minimal_unsigned_catalog_bytes();
    let cid = sugar_canonicalizer::blake3_512_of(&bytes);
    let hex = cid_hex(&cid).expect("cid prefix");
    let path = dir.join(format!("{hex}.proof"));
    fs::write(&path, bytes).expect("write proof");

    let report = validate_proof_file(&path);

    assert!(!report.ok(), "{report:#?}");
    assert!(report
        .errors
        .iter()
        .any(|error| error.rule_id == PFCP_R9_CATALOG_SIGNATURE));
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn catalog_body_tamper_reports_catalog_signature_rule() {
    let dir = make_unique_dir("catalog-tamper");
    let (_cid, mut bytes) = fixture_proof_bytes();
    let date_offset = bytes
        .windows(b"2026".len())
        .position(|window| window == b"2026")
        .expect("fixture carries declaredAt");
    bytes[date_offset + 3] = b'7';
    let tampered_cid = sugar_canonicalizer::blake3_512_of(&bytes);
    let hex = cid_hex(&tampered_cid).expect("cid prefix");
    let path = dir.join(format!("{hex}.proof"));
    fs::write(&path, bytes).expect("write proof");

    let report = validate_proof_file(&path);

    assert!(!report.ok(), "{report:#?}");
    assert!(report
        .errors
        .iter()
        .any(|error| error.rule_id == PFCP_R9_CATALOG_SIGNATURE));
    let _ = fs::remove_dir_all(&dir);
}

fn minimal_unsigned_catalog_bytes() -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.push(0xa2);
    bytes.extend_from_slice(&[0x64, b'k', b'i', b'n', b'd']);
    bytes.extend_from_slice(&[0x67, b'c', b'a', b't', b'a', b'l', b'o', b'g']);
    bytes.extend_from_slice(&[0x67, b'm', b'e', b'm', b'b', b'e', b'r', b's']);
    bytes.push(0xa0);
    bytes
}
