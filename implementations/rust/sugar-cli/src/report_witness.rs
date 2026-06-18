// SPDX-License-Identifier: Apache-2.0
//
// Prove-report witness adapter.
//
// The report is already the bounded artifact: facts, universes, linked vendor
// posts, and solver discharges. This module only routes that JSON through the
// existing witness-bundle machinery (`mint_witness` + `.proof` envelope).

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_claim_envelope::{mint_witness, MintWitnessArgs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, Ed25519Seed, ProofEnvelopeInput,
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
    let evidence_cid = jcs_cid(evidence);
    let mut input_cids = collect_cid_strings(evidence);
    collect_cid_strings_inner(claim_body, &mut input_cids);
    input_cids.insert(evidence_cid.clone());
    let input_cids: Vec<String> = input_cids.into_iter().collect();
    let claim_body_cid = jcs_cid(&claim_body);
    let produced_by = format!("sugar-witness:{name}");
    let produced_at = chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
    let signer_seed = deterministic_signer_seed(&produced_by);

    let witness = mint_witness(&MintWitnessArgs {
        claim_kind: claim_kind.to_string(),
        claim_body_cid,
        verifier_cid: format!("builtin:{claim_kind}"),
        policy_cid: format!("builtin:{claim_kind}-policy"),
        evidence_root_cid: evidence_cid.clone(),
        input_cids,
        produced_by: produced_by.clone(),
        produced_at: produced_at.clone(),
        claim_body: json_to_cvalue(&claim_body),
        evidence: json_to_cvalue(evidence),
        signer_seed,
    })
    .map_err(|e| format!("mint {name} witness memento: {e}"))?;

    let witness_cid = witness.cid.clone();
    let mut members = BTreeMap::new();
    members.insert(witness.cid, witness.canonical_bytes);
    let mut metadata = BTreeMap::new();
    metadata.insert("sugar.witness.name".into(), name.to_string());
    metadata.insert("sugar.witness.claimKind".into(), claim_kind.to_string());
    metadata.insert("sugar.witness.evidenceCid".into(), evidence_cid.clone());
    metadata.insert("sugar.witness.witnessCid".into(), witness_cid.clone());

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
    let proof_file = out_dir.join(format!("{}.proof", proof.cid));
    std::fs::write(&proof_file, &proof.bytes)
        .map_err(|e| format!("write {}: {e}", proof_file.display()))?;
    let evidence_file = out_dir.join(format!(
        "{}-{}.json",
        sanitize_filename(name),
        evidence_cid.trim_start_matches("blake3-512:")
    ));
    let evidence_bytes = serde_json::to_vec_pretty(evidence)
        .map_err(|e| format!("serialize report witness body: {e}"))?;
    std::fs::write(&evidence_file, [&evidence_bytes[..], b"\n"].concat())
        .map_err(|e| format!("write {}: {e}", evidence_file.display()))?;

    Ok(ReportWitnessProof {
        name: name.to_string(),
        proof_cid: proof.cid,
        proof_file,
        witness_cid,
        evidence_cid,
        evidence_file,
    })
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
}
