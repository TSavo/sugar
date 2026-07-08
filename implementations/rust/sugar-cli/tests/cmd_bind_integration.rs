// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

use libsugar::core::Term;
use sugar_walk::named_term_document_from_bind_payload;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn term_document() -> &'static [u8] {
    br#"{
  "kind": "ir-document",
  "sourceLanguage": "rust",
  "workspaceRoot": "/tmp/sugar-bind-test",
  "ir": [{
    "kind": "bind-lift-entry",
    "file": "src/lib.rs",
    "fn_name": "deposit",
    "fn_line": 14,
    "concept_annotation": "deposit-then-balance",
    "param_names": ["balance", "amount"],
    "param_types": ["i64", "i64"],
    "return_type": "i64",
    "term_shape": {"kind": "body", "stmts": [{"kind": "opaque"}]},
    "term_shape_cid": "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111",
    "witnesses": [{
      "role": "post",
      "predicate_text": "out == balance + amount",
      "source_kind": "annotation",
      "line": 14,
      "col": 0
    }]
  }]
}"#
}

fn witnessless_add_term_document() -> &'static [u8] {
    br#"{
  "kind": "ir-document",
  "sourceLanguage": "rust",
  "workspaceRoot": "/tmp/sugar-bind-test",
  "ir": [{
    "kind": "bind-lift-entry",
    "file": "src/lib.rs",
    "fn_name": "add",
    "fn_line": 4,
    "concept_annotation": "add",
    "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "param_names": ["x", "y"],
    "param_types": ["i64", "i64"],
    "return_type": "i64",
    "term_shape": {"kind": "bin", "op": "+"},
    "term_shape_cid": "blake3-512:22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222",
    "witnesses": []
  }]
}"#
}

fn cluster_cardinality_term_document() -> &'static [u8] {
    br#"{
  "kind": "ir-document",
  "sourceLanguage": "rust",
  "workspaceRoot": "/tmp/sugar-bind-test",
  "ir": [{
    "kind": "bind-lift-entry",
    "file": "src/lib.rs",
    "fn_name": "add_one",
    "fn_line": 4,
    "concept_annotation": "add",
    "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "param_names": ["x"],
    "param_types": ["i64"],
    "return_type": "i64",
    "term_shape": {"kind": "bin", "op": "+"},
    "term_shape_cid": "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111",
    "witnesses": []
  }, {
    "kind": "bind-lift-entry",
    "file": "src/lib.rs",
    "fn_name": "add_two",
    "fn_line": 8,
    "concept_annotation": "add",
    "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "param_names": ["x"],
    "param_types": ["i64"],
    "return_type": "i64",
    "term_shape": {"kind": "bin", "op": "+"},
    "term_shape_cid": "blake3-512:22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222",
    "witnesses": []
  }, {
    "kind": "bind-lift-entry",
    "file": "src/lib.rs",
    "fn_name": "sub_one",
    "fn_line": 12,
    "concept_annotation": "sub",
    "op_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "param_names": ["x"],
    "param_types": ["i64"],
    "return_type": "i64",
    "term_shape": {"kind": "bin", "op": "-"},
    "term_shape_cid": "blake3-512:33333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333",
    "witnesses": []
  }]
}"#
}

fn assert_success(label: &str, output: &std::process::Output) {
    assert!(
        output.status.success(),
        "{label} failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn bind_from_stdin_emits_named_term_document_without_promotion() {
    let mut child = Command::new(sugar_bin())
        .arg("bind")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn bind");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(term_document())
        .expect("write term");
    let output = child.wait_with_output().expect("wait bind");
    assert_success("bind stdin", &output);

    // cmd_bind's stdout is the NamedTermDocument payload. fn_name is
    // intentionally stripped from the payload (#1093), so the recovered term
    // has empty `function`.
    let payload: Term = serde_json::from_slice(&output.stdout).expect("bind payload parses");
    let named =
        named_term_document_from_bind_payload(&payload).expect("bind payload recovers named term");
    let named = serde_json::to_value(named).expect("named term serializes");
    assert_eq!(named["sourceLanguage"], "rust");
    assert!(named["terms"][0]["opCid"]
        .as_str()
        .expect("op cid")
        .starts_with("blake3-512:"));
    // fn_name was stripped per #1093 before encoding into the bind-result
    // payload; recovered NamedTermDocument has no function field.
    assert!(named["terms"][0]["function"].is_null() || named["terms"][0]["function"] == "");
    assert_eq!(
        named["terms"][0]["witnesses"][0]["predicateText"],
        "out == balance + amount"
    );
    // Promotion was torn out of the bind/verify pipeline; bind must NOT emit
    // promotion-decision mementos anymore. Guard the teardown.
    assert!(
        named["promotionDecisionMementos"].is_null(),
        "promotion teardown: bind must not emit promotion-decision mementos, got {:?}",
        named["promotionDecisionMementos"]
    );
}

#[test]
fn bind_from_stdin_emits_candidate_cluster_manifest() {
    let mut child = Command::new(sugar_bin())
        .arg("bind")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn bind");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(cluster_cardinality_term_document())
        .expect("write term");
    let output = child.wait_with_output().expect("wait bind");
    assert_success("bind stdin", &output);

    let payload: Term = serde_json::from_slice(&output.stdout).expect("bind payload parses");
    let named =
        named_term_document_from_bind_payload(&payload).expect("bind payload recovers named term");
    let named = serde_json::to_value(named).expect("named term serializes");
    let manifest = named["candidateClusterManifest"]
        .as_object()
        .expect("candidateClusterManifest object");
    let clusters = manifest["clusters"].as_array().expect("clusters array");

    assert_eq!(manifest["kind"], "candidate-cluster-manifest");
    assert_eq!(manifest["schemaVersion"], "1");
    assert_eq!(manifest["totalCandidates"], 3);
    assert_eq!(
        clusters[0]["opCluster"],
        "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    );
    assert_eq!(clusters[0]["candidateCount"], 2);
    assert_eq!(
        clusters[1]["opCluster"],
        "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    );
    assert_eq!(clusters[1]["candidateCount"], 1);
}

#[test]
fn bind_file_and_pipe_forms_are_byte_equivalent() {
    let temp = tempfile::tempdir().expect("tempdir");
    let term = temp.path().join("term.json");
    let named = temp.path().join("named.json");
    fs::write(&term, term_document()).expect("write term");

    let file = Command::new(sugar_bin())
        .arg("bind")
        .arg(&term)
        .arg("-o")
        .arg(&named)
        .output()
        .expect("spawn bind file");
    assert_success("bind file", &file);
    let file_bytes = fs::read(&named).expect("read named file");

    let mut child = Command::new(sugar_bin())
        .arg("bind")
        .arg("-")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn bind pipe");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(term_document())
        .expect("write term");
    let pipe = child.wait_with_output().expect("wait bind pipe");
    assert_success("bind pipe", &pipe);

    assert_eq!(pipe.stdout, file_bytes);
}

#[test]
fn bind_cli_witnessless_entry_is_loudly_bounded_lossy() {
    let mut child = Command::new(sugar_bin())
        .arg("bind")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn bind");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(witnessless_add_term_document())
        .expect("write term");
    let output = child.wait_with_output().expect("wait bind");
    assert_success("bind stdin", &output);

    let payload: Term = serde_json::from_slice(&output.stdout).expect("bind payload parses");
    let named =
        named_term_document_from_bind_payload(&payload).expect("bind payload recovers named term");
    let named = serde_json::to_value(named).expect("named term serializes");

    // No signed witness evidence -> loudly-bounded-lossy verdict, and no transport
    // gap record (contracts meet at the callsite by EUF).
    let term = named["terms"]
        .as_array()
        .expect("terms array")
        .first()
        .expect("one term");
    assert_eq!(term["dischargeVerdict"], "loudly-bounded-lossy");
    assert!(named.get("gapRecords").is_none());
}
