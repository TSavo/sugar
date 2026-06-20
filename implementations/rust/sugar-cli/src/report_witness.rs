// SPDX-License-Identifier: Apache-2.0
//
// Prove-report witness adapter.
//
// The report is already the bounded artifact: facts, universes, linked vendor
// posts, and solver discharges. This module writes the witness body as an
// external sidecar and places only the signed witness-memento pointer in the
// proof envelope.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, ed25519_sign_string, proof_filename, Ed25519Seed,
    ProofEnvelopeInput,
};

#[derive(Debug, Clone)]
pub(crate) struct ReportWitnessProof {
    pub name: String,
    pub proof_cid: String,
    pub proof_file: PathBuf,
    pub witness_cid: String,
    pub evidence_cid: String,
    pub evidence_file: PathBuf,
}

#[derive(Debug, Clone, Default)]
pub(crate) struct JsonWitnessOptions {
    pub produced_by: Option<String>,
    pub produced_at: Option<String>,
    pub verifier_cid: Option<String>,
    pub policy_cid: Option<String>,
    pub extra_input_cids: Vec<String>,
    pub proof_metadata: BTreeMap<String, String>,
    pub plan_cid: Option<String>,
    pub actual_output_cids: Vec<String>,
}

pub(crate) fn mint_report_witness(
    project_root: &Path,
    report_json: &Json,
    replay_pins: &Json,
    out_dir: &Path,
) -> Result<ReportWitnessProof, String> {
    let summary = json!({
        "totalCallsites": report_json.get("totalCallsites").cloned().unwrap_or(Json::Null),
        "discharged": report_json.get("discharged").cloned().unwrap_or(Json::Null),
        "violations": report_json.get("violations").cloned().unwrap_or(Json::Null),
        "refused": report_json.get("refused").cloned().unwrap_or(Json::Null),
        "loadErrors": report_json
            .get("loadErrors")
            .and_then(Json::as_array)
            .map(|a| a.len())
            .unwrap_or(0),
    });
    let report_cid = jcs_cid(report_json);
    let replay_pins_cid = jcs_cid(replay_pins);
    let evidence = json!({
        "kind": "sugar-prove-report-evidence",
        "schemaVersion": "1",
        "reportCid": report_cid,
        "replayPinsCid": replay_pins_cid,
        "report": report_json,
        "replayPins": replay_pins,
    });
    let claim_body = json!({
        "kind": "sugar-prove-report-witness",
        "schemaVersion": "1",
        "reportCid": report_cid,
        "replayPinsCid": replay_pins_cid,
        "project": project_root.display().to_string(),
        "summary": summary,
    });
    mint_json_witness(
        "prove-report",
        "sugar-prove-report-witness",
        &claim_body,
        &evidence,
        out_dir,
    )
}

pub(crate) fn mint_json_witness(
    name: &str,
    claim_kind: &str,
    claim_body: &Json,
    evidence: &Json,
    out_dir: &Path,
) -> Result<ReportWitnessProof, String> {
    mint_json_witness_with_options(
        name,
        claim_kind,
        claim_body,
        evidence,
        out_dir,
        JsonWitnessOptions::default(),
    )
}

pub(crate) fn mint_json_witness_with_options(
    name: &str,
    claim_kind: &str,
    claim_body: &Json,
    evidence: &Json,
    out_dir: &Path,
    options: JsonWitnessOptions,
) -> Result<ReportWitnessProof, String> {
    let JsonWitnessOptions {
        produced_by,
        produced_at,
        verifier_cid,
        policy_cid,
        extra_input_cids,
        proof_metadata,
        plan_cid,
        actual_output_cids,
    } = options;
    if !actual_output_cids.is_empty() && plan_cid.is_none() {
        return Err("toolchain output witness carries actualOutputCids but no planCid".to_string());
    }

    let claim_body_cid = jcs_cid(&claim_body);
    let evidence_root_cid = jcs_cid(evidence);
    let verifier_cid = verifier_cid.unwrap_or_else(|| format!("builtin:{claim_kind}"));
    let policy_cid = policy_cid.unwrap_or_else(|| format!("builtin:{claim_kind}-policy"));
    let mut witness_body = json!({
        "kind": "sugar-json-witness-body",
        "schemaVersion": "1",
        "claimKind": claim_kind,
        "claimBodyCid": claim_body_cid,
        "evidenceRootCid": evidence_root_cid,
        "verifierCid": verifier_cid,
        "policyCid": policy_cid,
        "claimBody": claim_body,
        "evidence": evidence,
    });
    add_toolchain_scope(&mut witness_body, plan_cid.as_deref(), &actual_output_cids);
    let witness_cid = jcs_cid(&witness_body);
    let mut input_cids = collect_cid_strings(&witness_body);
    input_cids.extend(
        extra_input_cids
            .into_iter()
            .filter(|cid| cid.starts_with("blake3-512:")),
    );
    input_cids.insert(claim_body_cid.clone());
    input_cids.insert(evidence_root_cid.clone());
    let input_cids: Vec<String> = input_cids.into_iter().collect();
    let produced_by = produced_by.unwrap_or_else(|| format!("sugar-witness:{name}"));
    let produced_at = produced_at
        .unwrap_or_else(|| chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true));
    let signer_seed = deterministic_signer_seed(&produced_by);
    let signer = ed25519_pubkey_string(&signer_seed);
    let signature = ed25519_sign_string(&signer_seed, witness_cid.as_bytes());

    let mut witness_pointer = json!({
        "body": {
            "kind": "witness-memento",
            "schemaVersion": "1",
            "witness_cid": witness_cid,
            "witness_kind": claim_kind,
            "signer": signer,
            "signature": signature,
            "claimBodyCid": claim_body_cid,
            "evidenceRootCid": evidence_root_cid,
            "verifierCid": verifier_cid,
            "policyCid": policy_cid,
            "inputCids": input_cids,
            "producedBy": produced_by,
            "producedAt": produced_at,
        },
        "header": {
            "kind": "witness-memento",
            "signer": signer,
            "witnessCid": witness_cid,
            "witnessKind": claim_kind,
        },
        "schemaVersion": "1",
    });
    if let Some(body) = witness_pointer
        .get_mut("body")
        .and_then(serde_json::Value::as_object_mut)
    {
        if let Some(plan_cid) = &plan_cid {
            body.insert("planCid".to_string(), json!(plan_cid));
        }
        if !actual_output_cids.is_empty() {
            body.insert("actualOutputCids".to_string(), json!(actual_output_cids));
        }
    }
    let witness_pointer_bytes = encode_jcs(&json_to_cvalue(&witness_pointer));
    let witness_pointer_cid = blake3_512_of(witness_pointer_bytes.as_bytes());
    let mut members = BTreeMap::new();
    members.insert(witness_pointer_cid, witness_pointer_bytes.into_bytes());
    let mut metadata = BTreeMap::new();
    metadata.insert("sugar.witness.name".into(), name.to_string());
    metadata.insert("sugar.witness.claimKind".into(), claim_kind.to_string());
    metadata.insert(
        "sugar.witness.evidenceCid".into(),
        evidence_root_cid.clone(),
    );
    metadata.insert("sugar.witness.witnessCid".into(), witness_cid.clone());
    metadata.extend(proof_metadata);

    let proof = build_proof_envelope(&ProofEnvelopeInput {
        name: format!("@sugar/witness/{name}"),
        version: "0.1.0".into(),
        binary_cid: None,
        metadata: Some(metadata),
        members,
        signer_cid: ed25519_pubkey_string(&signer_seed),
        signer_seed,
        declared_at: produced_at,
    });

    std::fs::create_dir_all(out_dir).map_err(|e| format!("mkdir {}: {e}", out_dir.display()))?;
    let proof_file = out_dir.join(proof_filename(&proof.cid));
    std::fs::write(&proof_file, &proof.bytes)
        .map_err(|e| format!("write {}: {e}", proof_file.display()))?;
    let evidence_file = out_dir.join(format!(
        "{}-{}.json",
        sanitize_filename(name),
        witness_cid.trim_start_matches("blake3-512:")
    ));
    let evidence_bytes = serde_json::to_vec_pretty(&witness_body)
        .map_err(|e| format!("serialize report witness body: {e}"))?;
    std::fs::write(&evidence_file, [&evidence_bytes[..], b"\n"].concat())
        .map_err(|e| format!("write {}: {e}", evidence_file.display()))?;

    Ok(ReportWitnessProof {
        name: name.to_string(),
        proof_cid: proof.cid,
        proof_file,
        witness_cid,
        evidence_cid: evidence_root_cid,
        evidence_file,
    })
}

fn add_toolchain_scope(body: &mut Json, plan_cid: Option<&str>, actual_output_cids: &[String]) {
    let Some(obj) = body.as_object_mut() else {
        return;
    };
    if let Some(plan_cid) = plan_cid {
        obj.insert("planCid".to_string(), json!(plan_cid));
    }
    if !actual_output_cids.is_empty() {
        obj.insert("actualOutputCids".to_string(), json!(actual_output_cids));
    }
}

fn collect_cid_strings(value: &Json) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    collect_cid_strings_inner(value, &mut out);
    out
}

fn collect_cid_strings_inner(value: &Json, out: &mut BTreeSet<String>) {
    match value {
        Json::String(s) if s.starts_with("blake3-512:") => {
            out.insert(s.clone());
        }
        Json::Array(items) => {
            for item in items {
                collect_cid_strings_inner(item, out);
            }
        }
        Json::Object(obj) => {
            for value in obj.values() {
                collect_cid_strings_inner(value, out);
            }
        }
        _ => {}
    }
}

fn jcs_cid(value: &Json) -> String {
    let canonical = json_to_cvalue(value);
    blake3_512_of(encode_jcs(canonical.as_ref()).as_bytes())
}

fn deterministic_signer_seed(principal: &str) -> Ed25519Seed {
    let digest = blake3_512_of(format!("sugar-signer:{principal}").as_bytes());
    let hex = digest.trim_start_matches("blake3-512:");
    let mut seed = [0u8; 32];
    for i in 0..32 {
        seed[i] = u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).unwrap_or(0);
    }
    seed
}

fn sanitize_filename(name: &str) -> String {
    name.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '-'
            }
        })
        .collect()
}

fn json_to_cvalue(j: &Json) -> Arc<CValue> {
    match j {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                CValue::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                CValue::integer(i128::from(u))
            } else {
                CValue::string(n.to_string())
            }
        }
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(json_to_cvalue).collect()),
        Json::Object(obj) => CValue::object(
            obj.iter()
                .map(|(k, v)| (k.clone(), json_to_cvalue(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prove_report_mints_witness_proof_bundle() {
        let temp = tempfile::tempdir().expect("tempdir");
        let report = json!({
            "totalCallsites": 0,
            "discharged": 1,
            "violations": 0,
            "refused": 0,
            "rows": [{
                "propertyCid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "verification": {
                    "kind": "consistency",
                    "linkedPosts": [{
                        "targetProofCid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                    }]
                }
            }],
            "loadErrors": []
        });

        let replay_pins = json!({
            "kind": "sugar-prove-replay-pins",
            "schemaVersion": "1",
            "solvers": []
        });
        let minted = mint_report_witness(
            Path::new("/tmp/project"),
            &report,
            &replay_pins,
            temp.path(),
        )
        .expect("report witness minted");

        assert!(minted.proof_cid.starts_with("blake3-512:"));
        assert!(minted.witness_cid.starts_with("blake3-512:"));
        assert!(minted.evidence_cid.starts_with("blake3-512:"));
        assert!(minted.proof_file.exists());
        assert!(minted.evidence_file.exists());
    }

    #[test]
    fn prove_report_witness_proof_contains_pointer_not_body() {
        let temp = tempfile::tempdir().expect("tempdir");
        let report = json!({
            "totalCallsites": 0,
            "discharged": 1,
            "violations": 0,
            "refused": 0,
            "rows": [],
            "loadErrors": []
        });
        let replay_pins = json!({
            "kind": "sugar-prove-replay-pins",
            "schemaVersion": "1",
            "solvers": []
        });
        let minted = mint_report_witness(
            Path::new("/tmp/project"),
            &report,
            &replay_pins,
            temp.path(),
        )
        .expect("report witness minted");

        let proof_bytes = std::fs::read(&minted.proof_file).expect("read witness proof");
        let catalog = sugar_verifier::cbor_decode::decode(&proof_bytes).expect("decode proof");
        let members = catalog
            .as_map()
            .and_then(|m| m.get("members"))
            .and_then(|v| v.as_map())
            .expect("proof members");
        assert_eq!(members.len(), 1);
        let member_bytes = members
            .values()
            .next()
            .and_then(|member| member.as_bstr())
            .expect("member bytes");
        let envelope: Json = serde_json::from_slice(member_bytes).expect("member JSON");

        assert_eq!(
            envelope.pointer("/header/kind").and_then(Json::as_str),
            Some("witness-memento")
        );
        assert_eq!(
            envelope
                .pointer("/header/witnessCid")
                .and_then(Json::as_str),
            Some(minted.witness_cid.as_str())
        );
        assert_eq!(
            envelope
                .pointer("/body/evidenceRootCid")
                .and_then(Json::as_str),
            Some(minted.evidence_cid.as_str())
        );
        assert!(
            envelope.pointer("/metadata/evidence").is_none()
                && envelope.pointer("/metadata/claimBody").is_none()
                && envelope.pointer("/body/evidence").is_none()
                && envelope.pointer("/body/report").is_none(),
            "witness proof must carry only the structured pointer, not the witness body: {envelope:#}"
        );
    }

    #[test]
    fn toolchain_output_witness_requires_plan_cid() {
        let temp = tempfile::tempdir().expect("tempdir");
        let err = mint_json_witness_with_options(
            "toolchain",
            "toolchain-run",
            &json!({"kind": "toolchain-run"}),
            &json!({"kind": "toolchain-evidence"}),
            temp.path(),
            JsonWitnessOptions {
                actual_output_cids: vec!["blake3-512:out".to_string()],
                ..JsonWitnessOptions::default()
            },
        )
        .expect_err("toolchain output witnesses must be scoped to a plan");

        assert!(err.contains("planCid"), "{err}");
    }

    #[test]
    fn toolchain_output_witness_carries_plan_scope_in_pointer_and_body() {
        let temp = tempfile::tempdir().expect("tempdir");
        let plan_cid = "blake3-512:plan-letter".to_string();
        let output_cid = "blake3-512:out".to_string();
        let minted = mint_json_witness_with_options(
            "toolchain",
            "toolchain-run",
            &json!({"kind": "toolchain-run"}),
            &json!({"kind": "toolchain-evidence"}),
            temp.path(),
            JsonWitnessOptions {
                plan_cid: Some(plan_cid.clone()),
                actual_output_cids: vec![output_cid.clone()],
                ..JsonWitnessOptions::default()
            },
        )
        .expect("toolchain witness minted");

        let proof_bytes = std::fs::read(&minted.proof_file).expect("read witness proof");
        let catalog = sugar_verifier::cbor_decode::decode(&proof_bytes).expect("decode proof");
        let members = catalog
            .as_map()
            .and_then(|m| m.get("members"))
            .and_then(|v| v.as_map())
            .expect("proof members");
        let member_bytes = members
            .values()
            .next()
            .and_then(|member| member.as_bstr())
            .expect("member bytes");
        let envelope: Json = serde_json::from_slice(member_bytes).expect("member JSON");

        assert_eq!(
            envelope.pointer("/body/planCid").and_then(Json::as_str),
            Some(plan_cid.as_str())
        );
        assert_eq!(
            envelope
                .pointer("/body/actualOutputCids/0")
                .and_then(Json::as_str),
            Some(output_cid.as_str())
        );

        let body: Json = serde_json::from_slice(
            &std::fs::read(&minted.evidence_file).expect("read witness body"),
        )
        .expect("parse witness body");
        assert_eq!(
            body.pointer("/planCid").and_then(Json::as_str),
            Some(plan_cid.as_str())
        );
        assert_eq!(
            body.pointer("/actualOutputCids/0").and_then(Json::as_str),
            Some(output_cid.as_str())
        );
    }
}
