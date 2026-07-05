// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Round-trip serde and JCS CID tests for PipelineMemento and RunMemento.
//
// Source of truth:
//   protocol/specs/2026-05-13-pipeline-runmemento.md §1, §8

use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_ir_types::{PipelineKind, PipelineMemento, RunMemento, RunVerdict, ValidationError};

fn json_to_cvalue(j: &Json) -> Arc<CValue> {
    match j {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => CValue::integer(i128::from(n.as_i64().expect("fixture integer"))),
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(json_to_cvalue).collect()),
        Json::Object(obj) => {
            CValue::object(obj.iter().map(|(k, v)| (k.clone(), json_to_cvalue(v))))
        }
    }
}

fn cid_of_json(j: &Json) -> String {
    let value = json_to_cvalue(j);
    let jcs = encode_jcs(&value);
    blake3_512_of(jcs.as_bytes())
}

fn cid_of_serde<T: serde::Serialize>(value: &T) -> String {
    let json = serde_json::to_value(value).expect("serialize to JSON value");
    cid_of_json(&json)
}

fn sample_pipeline() -> PipelineMemento {
    PipelineMemento {
        accepted_input_kinds: vec!["proof-envelope".into(), "link-bundle".into()],
        emitted_output_kinds: vec!["domain-claim".into()],
        failure_kinds: vec!["invalid-proof".into(), "plugin-refusal".into()],
        pipeline_kind: PipelineKind::Verifier,
        pipeline_version: "1.0.0".into(),
        provenance_cid: "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111".into(),
        stage_vocabulary: vec!["load".into(), "check".into(), "seal".into()],
    }
}

fn sample_run(pipeline_cid: String) -> RunMemento {
    RunMemento {
        input_cids: vec![
            "blake3-512:22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222".into(),
        ],
        output_cids: vec![
            "blake3-512:33333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333".into(),
        ],
        pipeline_cid,
        plugin_registry_cid: "blake3-512:44444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444".into(),
        predecessor_run_cids: vec![],
        provenance_cid: "blake3-512:55555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555".into(),
        stage_receipt_cids: vec![
            "blake3-512:66666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666".into(),
            "blake3-512:77777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777".into(),
            "blake3-512:88888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888".into(),
        ],
        verdict: RunVerdict::Succeeded,
    }
}

#[test]
fn pipeline_memento_round_trips_and_recomputes_cid() {
    let pipeline = sample_pipeline();
    let serialized = serde_json::to_string(&pipeline).expect("serialize PipelineMemento");
    let reparsed: PipelineMemento =
        serde_json::from_str(&serialized).expect("reparse PipelineMemento");
    assert_eq!(pipeline, reparsed);

    let json = serde_json::to_value(&pipeline).expect("PipelineMemento JSON");
    assert_eq!(
        json,
        json!({
            "accepted_input_kinds": ["proof-envelope", "link-bundle"],
            "emitted_output_kinds": ["domain-claim"],
            "failure_kinds": ["invalid-proof", "plugin-refusal"],
            "pipeline_kind": "verifier",
            "pipeline_version": "1.0.0",
            "provenance_cid": "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111",
            "stage_vocabulary": ["load", "check", "seal"]
        })
    );

    let recomputed = cid_of_serde(&pipeline);
    assert!(recomputed.starts_with("blake3-512:"));
    assert_eq!(recomputed.len(), 139);
    assert_eq!(recomputed, cid_of_json(&json));
}

#[test]
fn run_memento_round_trips_and_recomputes_cid() {
    let pipeline = sample_pipeline();
    let pipeline_cid = cid_of_serde(&pipeline);
    let run = sample_run(pipeline_cid.clone());

    let serialized = serde_json::to_string(&run).expect("serialize RunMemento");
    let reparsed: RunMemento = serde_json::from_str(&serialized).expect("reparse RunMemento");
    assert_eq!(run, reparsed);

    let json = serde_json::to_value(&run).expect("RunMemento JSON");
    assert_eq!(
        json,
        json!({
            "input_cids": ["blake3-512:22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222"],
            "output_cids": ["blake3-512:33333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333"],
            "pipeline_cid": pipeline_cid,
            "plugin_registry_cid": "blake3-512:44444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444",
            "predecessor_run_cids": [],
            "provenance_cid": "blake3-512:55555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555",
            "stage_receipt_cids": [
                "blake3-512:66666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666",
                "blake3-512:77777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777",
                "blake3-512:88888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888"
            ],
            "verdict": "succeeded"
        })
    );

    let recomputed = cid_of_serde(&run);
    assert!(recomputed.starts_with("blake3-512:"));
    assert_eq!(recomputed.len(), 139);
    assert_eq!(recomputed, cid_of_json(&json));
}

#[test]
fn run_validate_rejects_stage_receipt_length_mismatch() {
    let pipeline = sample_pipeline();
    let mut run = sample_run(cid_of_serde(&pipeline));
    run.stage_receipt_cids.pop();

    let err = run
        .validate(&pipeline)
        .expect_err("mismatched stage lengths fail");
    assert_eq!(
        err,
        ValidationError::StageReceiptLengthMismatch {
            expected: 3,
            actual: 2,
        }
    );
}

#[test]
fn run_validate_accepts_matching_stage_receipt_length() {
    let pipeline = sample_pipeline();
    let run = sample_run(cid_of_serde(&pipeline));

    run.validate(&pipeline)
        .expect("matching stage lengths validate");
}

#[test]
fn pipeline_kind_rejects_bare_unknown() {
    // Per spec §3 + admissibility-spine namespaced-extensions rule, a bare
    // unknown pipeline_kind MUST fail closed at deserialization.
    use sugar_ir_types::PipelineKind;
    let result: Result<PipelineKind, _> = serde_json::from_str("\"benchmark\"");
    assert!(
        result.is_err(),
        "bare unknown pipeline_kind should fail closed, got {:?}",
        result
    );
}

#[test]
fn pipeline_kind_accepts_well_formed_namespaced_extension() {
    use sugar_ir_types::PipelineKind;
    let parsed: PipelineKind =
        serde_json::from_str("\"acme:benchmark\"").expect("parse namespaced");
    assert_eq!(
        parsed,
        PipelineKind::Namespaced("acme:benchmark".to_string())
    );
}

#[test]
fn pipeline_kind_rejects_multi_colon() {
    // Spec: extension labels are `<namespace>:<kind>` with EXACTLY one
    // colon. `a:b:c` is not a valid namespaced extension.
    use sugar_ir_types::PipelineKind;
    let result: Result<PipelineKind, _> = serde_json::from_str("\"a:b:c\"");
    assert!(
        result.is_err(),
        "multi-colon should fail closed, got {:?}",
        result
    );
}

#[test]
fn pipeline_validate_rejects_empty_required_arrays() {
    use sugar_ir_types::ValidationError;
    let mut pipeline = sample_pipeline();
    pipeline.stage_vocabulary.clear();
    assert_eq!(
        pipeline.validate(),
        Err(ValidationError::EmptyRequiredArray {
            field: "stage_vocabulary"
        })
    );

    let mut pipeline = sample_pipeline();
    pipeline.accepted_input_kinds.clear();
    assert_eq!(
        pipeline.validate(),
        Err(ValidationError::EmptyRequiredArray {
            field: "accepted_input_kinds"
        })
    );

    let mut pipeline = sample_pipeline();
    pipeline.emitted_output_kinds.clear();
    assert_eq!(
        pipeline.validate(),
        Err(ValidationError::EmptyRequiredArray {
            field: "emitted_output_kinds"
        })
    );

    let mut pipeline = sample_pipeline();
    pipeline.failure_kinds.clear();
    assert_eq!(
        pipeline.validate(),
        Err(ValidationError::EmptyRequiredArray {
            field: "failure_kinds"
        })
    );
}

#[test]
fn run_validate_rejects_empty_input_cids() {
    use sugar_ir_types::ValidationError;
    let pipeline = sample_pipeline();
    let mut run = sample_run(cid_of_serde(&pipeline));
    run.input_cids.clear();
    assert_eq!(
        run.validate(&pipeline),
        Err(ValidationError::EmptyRequiredArray {
            field: "input_cids"
        })
    );
}

#[test]
fn run_validate_rejects_empty_stage_receipt_cids() {
    use sugar_ir_types::ValidationError;
    let pipeline = sample_pipeline();
    let mut run = sample_run(cid_of_serde(&pipeline));
    run.stage_receipt_cids.clear();
    assert_eq!(
        run.validate(&pipeline),
        Err(ValidationError::EmptyRequiredArray {
            field: "stage_receipt_cids"
        })
    );
}
