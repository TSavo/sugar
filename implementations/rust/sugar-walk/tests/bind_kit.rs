// SPDX-License-Identifier: MIT OR Apache-2.0

use libsugar::core::{address, Input, Kit, Term};
use sugar_walk::{
    bind_term_document, named_term_document_from_bind_payload,
    strip_realize_sidecar_from_lift_term, BindKit, BindOptions,
};
use serde_json::{json, Value};
use sugar_ir_types::Sort;

fn primitive_sort(name: &str) -> Sort {
    Sort::Primitive {
        name: name.to_string(),
    }
}

fn bind_input_value() -> Value {
    json!({
        "kind": "ir-document",
        "sourceLanguage": "rust",
        "workspaceRoot": "/tmp/sugar-bind-kit-test",
        "ir": [{
            "kind": "bind-lift-entry",
            "file": "src/lib.rs",
            "fn_name": "deposit",
            "fn_line": 14,
            "concept_annotation": "deposit-then-balance",
            "param_names": ["balance", "amount"],
            "param_types": ["i64", "i64"],
            "return_type": "i64",
            "term_shape": {
                "kind": "body",
                "stmts": [
                    {"kind": "let"},
                    {"kind": "bin", "op": "+"}
                ]
            },
            "term_shape_cid": "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111",
            "witnesses": [{
                "role": "post",
                "predicate_text": "out == balance + amount",
                "source_kind": "annotation"
            }]
        }]
    })
}

fn witnessless_concept_input(concept: &str) -> Value {
    let mut value = bind_input_value();
    let entry = value["ir"][0]
        .as_object_mut()
        .expect("bind-lift-entry is object");
    entry.insert("concept_annotation".to_string(), json!(concept));
    entry.insert("witnesses".to_string(), json!([]));
    value
}

fn cluster_input(entries: Vec<Value>) -> Value {
    json!({
        "kind": "ir-document",
        "sourceLanguage": "rust",
        "workspaceRoot": "/tmp/sugar-bind-kit-test",
        "ir": entries
    })
}

fn test_cid(cid_digit: char) -> String {
    format!(
        "blake3-512:{}",
        std::iter::repeat(cid_digit).take(128).collect::<String>()
    )
}

fn cluster_entry(
    fn_name: &str,
    operator_digit: char,
    shape_digit: char,
    witnesses: Vec<Value>,
) -> Value {
    json!({
        "kind": "bind-lift-entry",
        "file": "src/lib.rs",
        "fn_name": fn_name,
        "fn_line": 14,
        "op_cid": test_cid(operator_digit),
        "param_names": ["x"],
        "param_types": ["i64"],
        "return_type": "i64",
        "term_shape": {"kind": "bin", "op": "+"},
        "term_shape_cid": test_cid(shape_digit),
        "witnesses": witnesses
    })
}

fn candidate_cluster_manifest(named: &Value) -> &Value {
    named
        .get("candidateClusterManifest")
        .expect("candidateClusterManifest emitted")
}

fn candidate_cluster_count(named: &Value, op_cid: &str) -> u64 {
    candidate_cluster_manifest(named)["clusters"]
        .as_array()
        .expect("clusters array")
        .iter()
        .find(|cluster| cluster["opCluster"] == op_cid)
        .unwrap_or_else(|| panic!("cluster {op_cid} missing"))
        .get("candidateCount")
        .and_then(Value::as_u64)
        .expect("candidateCount is u64")
}

#[test]
fn bind_kit_transform_emits_named_term_document_payload() {
    let term_value = bind_input_value();
    let input_term = Term::Const {
        value: term_value.clone(),
        sort: primitive_sort("LiftPluginResponse"),
    };
    let mut expected_named =
        bind_term_document(&term_value, &BindOptions::default()).expect("existing binder succeeds");
    for term in &mut expected_named.terms {
        // function is cleared in the wire form (preserving #1093 CID invariant);
        // fn_name_sugar carries the source name as a non-CID-affecting annotation
        if !term.function.is_empty() {
            term.fn_name_sugar = Some(term.function.clone());
        }
        term.function.clear();
        // Source-language display metadata is not part of the wire payload.
        term.visibility.clear();
        term.generic_params.clear();
        term.doc_lines.clear();
    }

    let claim = BindKit::default()
        .transform(&Input::Term(input_term.clone()))
        .expect("bind kit transforms term input");

    // Bind cites the canonical content CID of its input, which matches
    // lift.to under the same canonicalization (strip realize sidecar).
    let canonical_input = strip_realize_sidecar_from_lift_term(input_term.clone());
    assert_eq!(claim.from, vec![address(&canonical_input)]);
    let payload = claim.payload.as_ref().expect("bind claim carries payload");
    assert_eq!(claim.to, address(payload));
    let recovered =
        named_term_document_from_bind_payload(payload).expect("bind payload recovers named terms");
    assert_eq!(
        serde_json::to_value(&recovered).expect("recovered named term serializes"),
        serde_json::to_value(&expected_named).expect("expected named term serializes")
    );

    // Bind is deterministic: running the same input twice produces the same payload bytes
    let first_jcs = libsugar::canonical::serializable_jcs(payload).expect("payload canonicalizes");
    let second_claim = BindKit::default()
        .transform(&Input::Term(input_term.clone()))
        .expect("bind kit transforms term input again");
    let second_payload = second_claim
        .payload
        .as_ref()
        .expect("second bind claim carries payload");
    assert_eq!(
        first_jcs,
        libsugar::canonical::serializable_jcs(second_payload)
            .expect("second payload canonicalizes")
    );
}

#[test]
fn bind_emits_candidate_cluster_manifest_with_cardinality_per_concept() {
    let input = cluster_input(vec![
        cluster_entry("add_one", 'a', '1', vec![]),
        cluster_entry("add_two", 'a', '2', vec![]),
        cluster_entry("sub_one", 'b', '3', vec![]),
        cluster_entry("mul_one", 'c', '4', vec![]),
    ]);

    let named = bind_term_document(&input, &BindOptions::default()).expect("bind succeeds");
    let named_json = serde_json::to_value(&named).expect("named term serializes");
    let manifest = candidate_cluster_manifest(&named_json);

    assert_eq!(manifest["kind"], "candidate-cluster-manifest");
    assert_eq!(manifest["schemaVersion"], "1");
    assert_eq!(manifest["totalCandidates"], 4);
    assert_eq!(candidate_cluster_count(&named_json, &test_cid('a')), 2);
    assert_eq!(candidate_cluster_count(&named_json, &test_cid('b')), 1);
    assert_eq!(candidate_cluster_count(&named_json, &test_cid('c')), 1);
}

#[test]
fn candidate_cluster_manifest_groups_by_op_cid_not_function_name() {
    let input = cluster_input(vec![
        cluster_entry("add_one", 'a', '1', vec![]),
        cluster_entry("add_two", 'a', '1', vec![]),
    ]);

    let named = bind_term_document(&input, &BindOptions::default()).expect("bind succeeds");
    let named_json = serde_json::to_value(&named).expect("named term serializes");
    let clusters = candidate_cluster_manifest(&named_json)["clusters"]
        .as_array()
        .expect("clusters array");

    assert_eq!(clusters.len(), 1);
    assert_eq!(clusters[0]["opCluster"], test_cid('a'));
    assert_eq!(clusters[0]["candidateCount"], 2);
}

#[test]
fn candidate_cluster_manifest_groups_by_op_cid_not_shape_cid() {
    let input = cluster_input(vec![
        cluster_entry("add_one", 'a', '1', vec![]),
        cluster_entry("add_two", 'a', '2', vec![]),
    ]);

    let named = bind_term_document(&input, &BindOptions::default()).expect("bind succeeds");
    let named_json = serde_json::to_value(&named).expect("named term serializes");
    let clusters = candidate_cluster_manifest(&named_json)["clusters"]
        .as_array()
        .expect("clusters array");

    assert_eq!(clusters.len(), 1);
    assert_eq!(clusters[0]["opCluster"], test_cid('a'));
    assert_eq!(clusters[0]["candidateCount"], 2);
}

#[test]
fn candidate_cluster_manifest_counts_candidates_not_witnesses() {
    let witness = json!({
        "role": "post",
        "predicate_text": "out == x",
        "source_kind": "annotation"
    });
    let input = cluster_input(vec![
        cluster_entry("add_one", 'a', '1', vec![witness.clone(), witness]),
        cluster_entry("add_two", 'a', '2', vec![]),
    ]);

    let named = bind_term_document(&input, &BindOptions::default()).expect("bind succeeds");
    let named_json = serde_json::to_value(&named).expect("named term serializes");
    let clusters = candidate_cluster_manifest(&named_json)["clusters"]
        .as_array()
        .expect("clusters array");

    assert_eq!(clusters.len(), 1);
    assert_eq!(clusters[0]["opCluster"], test_cid('a'));
    assert_eq!(clusters[0]["candidateCount"], 2);
}

#[test]
fn bind_witnessless_entry_is_loudly_bounded_lossy() {
    let input = witnessless_concept_input("add");

    let named = bind_term_document(
        &input,
        &BindOptions {
            lang: "rust".to_string(),
        },
    )
    .expect("bind succeeds");
    let named_json = serde_json::to_value(&named).expect("named term serializes");
    let term = named_json["terms"]
        .as_array()
        .expect("terms array")
        .first()
        .expect("one term");

    // No signed witness evidence -> the trichotomy verdict is loudly-bounded-lossy.
    // (There is no transport gap record: contracts meet at the callsite by EUF.)
    assert_eq!(term["dischargeVerdict"], "loudly-bounded-lossy");
    assert!(named_json.get("gapRecords").is_none());
}

#[test]
fn bind_witnessed_entry_is_exact() {
    let named = bind_term_document(
        &bind_input_value(),
        &BindOptions {
            lang: "rust".to_string(),
        },
    )
    .expect("bind succeeds");
    let named_json = serde_json::to_value(&named).expect("named term serializes");
    let term = named_json["terms"]
        .as_array()
        .expect("terms array")
        .first()
        .expect("one term");

    assert_eq!(term["dischargeVerdict"], "exact");
}
