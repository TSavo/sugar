// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use sugar_canonicalizer::{blake3_512_of, cid_hex};
use sugar_ir_types::{ProofRunEnvelope, StageReceiptHeader, StageReceiptMetadata, StageVerdict};
use sugar_ir_types::{ProofRunMemento, StageReceipt};
use sugar_proof_envelope::{
    build_proof_envelope, cbor_encode_bstr, cbor_encode_map_head, cbor_encode_tstr,
    ed25519_pubkey_string, CborValue, Ed25519Seed, ProofEnvelopeInput, ProofGraph,
    StageReceiptMemento,
};
use sugar_verifier::load_all_proofs;
use sugar_verifier::{LegacyZ3Fallback, Runner, RunnerConfig, VERIFIER_STAGE_VOCABULARY};

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
        manifest: None,
    });
    let hex = cid_hex(&built.cid).unwrap();
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

fn encode_cbor(value: &CborValue, out: &mut Vec<u8>) {
    match value {
        CborValue::Uint(n) => sugar_proof_envelope::cbor_encode_uint(out, *n),
        CborValue::Bstr(bytes) => cbor_encode_bstr(out, bytes),
        CborValue::Tstr(text) => cbor_encode_tstr(out, text),
        CborValue::Array(items) => {
            sugar_proof_envelope::cbor_encode_array_head(out, items.len() as u64);
            for item in items {
                encode_cbor(item, out);
            }
        }
        CborValue::Map(map) => {
            cbor_encode_map_head(out, map.len() as u64);
            for (key, value) in map {
                cbor_encode_tstr(out, key);
                encode_cbor(value, out);
            }
        }
    }
}

fn rewrite_single_member_key(proof_bytes: &[u8], replacement_cid: &str) -> Vec<u8> {
    let mut catalog = sugar_proof_envelope::decode_for_conformance(proof_bytes)
        .expect("decode proof catalog for forged fixture");
    let root = match &mut catalog {
        CborValue::Map(root) => root,
        other => panic!("proof catalog root must be a map, got {other:?}"),
    };
    let members = root
        .get_mut("members")
        .and_then(|value| match value {
            CborValue::Map(map) => Some(map),
            _ => None,
        })
        .expect("catalog has members map");
    assert_eq!(members.len(), 1, "fixture must carry one member");
    let (_, bytes) = members.pop_first().expect("single member");
    members.insert(replacement_cid.to_string(), bytes);
    let mut out = Vec::new();
    encode_cbor(&catalog, &mut out);
    out
}

fn write_proof_bytes(project_root: &Path, bytes: &[u8]) -> String {
    let cid = blake3_512_of(bytes);
    let path = project_root.join(sugar_proof_envelope::proof_filename(&cid));
    fs::write(path, bytes).expect("write proof bytes");
    cid
}

fn forged_stage_receipt_bytes(claimed_cid: &str) -> Vec<u8> {
    let receipt = StageReceipt {
        envelope: ProofRunEnvelope {
            declared_at: "2026-07-01T00:00:00.000Z".into(),
            signature: "ed25519:attacker-chosen-signature-label".into(),
            signer: ed25519_pubkey_string(&[0x33; 32]),
        },
        header: StageReceiptHeader {
            cid: claimed_cid.to_string(),
            diagnostics: vec![serde_json::json!({"kind": "forged-stage-receipt"})],
            finished_at: "2026-07-01T00:00:01.000Z".into(),
            input_cids: Vec::new(),
            kind: "stage-receipt".into(),
            output_cids: Vec::new(),
            refusal_cids: Vec::new(),
            schema_version: "1".into(),
            stage_name: "load_all_proofs".into(),
            started_at: "2026-07-01T00:00:00.000Z".into(),
            verdict: StageVerdict::Ok,
        },
        metadata: StageReceiptMetadata::default(),
    };
    receipt
        .to_jcs_string()
        .expect("canonicalize forged stage receipt")
        .into_bytes()
}

#[test]
fn forged_stage_receipt_cid_is_rejected() {
    let project_root = make_unique_dir("forged-stage-receipt");
    let claimed_cid = format!("blake3-512:{}", "f".repeat(128));
    let member_bytes = forged_stage_receipt_bytes(&claimed_cid);
    let mut graph = ProofGraph::new();
    graph.push_stage_receipt(StageReceiptMemento::new(member_bytes));
    let signer_seed: Ed25519Seed = [0x44; 32];
    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@test/forged-stage-receipt".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: "2026-07-01T00:00:00.000Z".into(),
        manifest: None,
    });
    let forged = rewrite_single_member_key(&built.bytes, &claimed_cid);
    let bundle_cid = write_proof_bytes(&project_root, &forged);

    let pool = load_all_proofs::run(&project_root);

    assert!(
        pool.load_errors.iter().any(|err| {
            err.proof_path
                .contains(&sugar_proof_envelope::proof_filename(&bundle_cid))
                && err.reason.contains("rule 2")
                && err.reason.contains(&claimed_cid)
                && err.reason.contains("derives to")
        }),
        "forged stage-receipt member CID must be a load error: {:#?}",
        pool.load_errors
    );
    assert!(
        !pool.mementos.contains_key(claimed_cid.as_str()),
        "forged stage-receipt must not enter the memento pool"
    );

    let _ = fs::remove_dir_all(&project_root);
}

#[test]
fn honest_stage_receipt_roundtrip() {
    let project_root = make_unique_dir("honest-stage-receipt");
    write_empty_fixture_proof(&project_root);

    let runner = Runner::new(RunnerConfig {
        project_root: project_root.clone(),
        legacy_z3_fallback: Some(LegacyZ3Fallback::compat("z3")),
        ..Default::default()
    });
    let run = runner
        .run_with_proof_run()
        .expect("run emits honest proof-run bundle");

    let reloaded = load_all_proofs::run(&project_root);

    assert!(
        reloaded.load_errors.is_empty(),
        "honest proof-run/stage-receipt producer output must reload cleanly: {:#?}",
        reloaded.load_errors
    );
    for receipt in &run.stage_receipts {
        assert!(
            reloaded.mementos.contains_key(receipt.header.cid.as_str()),
            "stage receipt {} must be indexed",
            receipt.header.cid
        );
    }

    let _ = fs::remove_dir_all(&project_root);
}

#[test]
fn prove_run_emits_durable_content_addressed_run_and_stage_receipts() {
    let project_root = make_unique_dir("fixture");
    let input_proof_cid = write_empty_fixture_proof(&project_root);

    let runner = Runner::new(RunnerConfig {
        project_root: project_root.clone(),
        legacy_z3_fallback: Some(LegacyZ3Fallback::compat("z3")),
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
    let run_jcs = run.memento.to_jcs_string().expect("run jcs");
    let run_member_cid = sugar_proof_envelope::ProofRunMemento::new(run_jcs.clone().into_bytes())
        .cid()
        .as_str()
        .to_string();
    assert_eq!(run_member_cid, run.memento.header.cid);

    let members = read_members(&run.bundle_path);
    assert!(members.contains_key(&run.memento.header.cid));
    for receipt in &run.stage_receipts {
        let jcs = receipt.to_jcs_string().expect("stage jcs");
        let cid = StageReceiptMemento::new(jcs.clone().into_bytes())
            .cid()
            .as_str()
            .to_string();
        assert_eq!(cid, receipt.header.cid);
        assert!(members.contains_key(&cid));
        let reparsed: StageReceipt = serde_json::from_str(&jcs).expect("stage round trip");
        assert_eq!(reparsed, *receipt);
    }

    let reparsed: ProofRunMemento = serde_json::from_str(&run_jcs).expect("run round trip");
    assert_eq!(reparsed, run.memento);

    let reloaded = load_all_proofs::run(&project_root);
    assert!(
        reloaded.load_errors.is_empty(),
        "generated run bundle must reload cleanly: {:?}",
        reloaded.load_errors
    );
    assert!(reloaded
        .mementos
        .contains_key(run.memento.header.cid.as_str()));
    for receipt in &run.stage_receipts {
        assert!(reloaded.mementos.contains_key(receipt.header.cid.as_str()));
    }

    let _ = fs::remove_dir_all(&project_root);
}
