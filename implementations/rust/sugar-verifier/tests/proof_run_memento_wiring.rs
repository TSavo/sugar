// SPDX-License-Identifier: Apache-2.0

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use sugar_canonicalizer::blake3_512_of;
use sugar_ir_types::{ProofRunMemento, StageReceipt};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, Ed25519Seed, ProofEnvelopeInput, ProofGraph,
};
use sugar_verifier::load_all_proofs;
use sugar_verifier::{Runner, RunnerConfig, VERIFIER_STAGE_VOCABULARY};

fn make_unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("sugar-run-memento-{stamp}-{suffix}"));
    fs::create_dir_all(&path).expect("create temp dir");
    path
}

fn write_empty_fixture_proof(project_root: &Path) -> String {
    let signer_seed: Ed25519Seed = [0x61; 32];
    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@test/empty-run-input".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph: ProofGraph::new(),
        signer_cid,
        signer_seed,
        declared_at: "2026-05-13T00:00:00.000Z".into(),
    });
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    fs::write(project_root.join(format!("{hex}.proof")), built.bytes).expect("write fixture");
    built.cid
}

fn read_members(path: &Path) -> BTreeMap<String, Vec<u8>> {
    let bytes = fs::read(path).expect("read proof run bundle");
    let graph = ProofGraph::read(&bytes).expect("decode proof run bundle");
    graph
        .members_view()
        .map(|view| (view.cid().as_str().to_string(), view.bytes().to_vec()))
        .collect()
}

#[test]
fn prove_run_emits_durable_content_addressed_run_and_stage_receipts() {
    let project_root = make_unique_dir("fixture");
    let input_proof_cid = write_empty_fixture_proof(&project_root);

    let runner = Runner::new(RunnerConfig {
        project_root: project_root.clone(),
        z3_path: "z3".into(),
        ..Default::default()
    });
    let run = runner
        .run_with_proof_run()
        .expect("run emits proof-run memento bundle");

    assert!(run.bundle_path.exists(), "proof-run bundle must be durable");
    assert_eq!(run.stage_receipts.len(), VERIFIER_STAGE_VOCABULARY.len());
    assert_eq!(
        run.memento.header.stage_receipt_cids.len(),
        VERIFIER_STAGE_VOCABULARY.len()
    );
    assert!(run
        .memento
        .header
        .input_artifact_cids
        .contains(&input_proof_cid));
    assert_eq!(
        run.memento.recompute_header_cid().expect("run recompute"),
        run.memento.header.cid
    );

    let members = read_members(&run.bundle_path);
    assert!(members.contains_key(&run.memento.header.cid));
    for receipt in &run.stage_receipts {
        let cid = receipt.recompute_header_cid().expect("stage recompute");
        assert_eq!(cid, receipt.header.cid);
        assert!(members.contains_key(&cid));
        let jcs = receipt.to_jcs_string().expect("stage jcs");
        let reparsed: StageReceipt = serde_json::from_str(&jcs).expect("stage round trip");
        assert_eq!(reparsed, *receipt);
    }

    let run_jcs = run.memento.to_jcs_string().expect("run jcs");
    let reparsed: ProofRunMemento = serde_json::from_str(&run_jcs).expect("run round trip");
    assert_eq!(reparsed, run.memento);

    let reloaded = load_all_proofs::run(&project_root);
    assert!(
        reloaded.load_errors.is_empty(),
        "generated run bundle must reload cleanly: {:?}",
        reloaded.load_errors
    );
    assert!(reloaded.mementos.contains_key(&run.memento.header.cid));
    for receipt in &run.stage_receipts {
        assert!(reloaded.mementos.contains_key(&receipt.header.cid));
    }

    let _ = fs::remove_dir_all(&project_root);
}
