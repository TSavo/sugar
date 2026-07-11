// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Supply-chain admission gate -- SEAM 6 of the compiler-shape plan
// (`~/.claude/plans/sugar-compiler-liftshift.md`, "SEAM 6").
//
// Verifies a package release receipt (binaryCid / policyCid match) against
// `--artifact` / `--proof` / `--policy`. This logic predates the keystone
// `verify` verb and originally lived in `cmd_prove`; `cmd_verify` used to
// reach into `cmd_prove::run_admission_gate_with` directly (a
// face-to-face coupling). Both faces now call the ONE copy here.
use std::path::{Path, PathBuf};

use owo_colors::OwoColorize;
use serde_json::{json, Value};
use sugar_canonicalizer::blake3_512_of;

/// Shared admission-gate entry point. Threading the three `Option<PathBuf>`
/// values directly (rather than a command-specific args struct) lets both
/// `cmd_prove` (legacy alias) and `cmd_verify` (PR-9 / #1405) reuse this
/// without either coupling to the other's arg type.
pub fn run_admission_gate_with(
    artifact: &Option<PathBuf>,
    proof: &Option<PathBuf>,
    policy: &Option<PathBuf>,
    json: bool,
    quiet: bool,
) -> u8 {
    match verify_artifact_or_policy(artifact, proof, policy) {
        Ok(report) => {
            let ok = report["ok"].as_bool().unwrap_or(false);
            if json {
                println!("{}", serde_json::to_string_pretty(&report).unwrap());
            } else if !quiet {
                let verdict = report["verdict"].as_str().unwrap_or("unknown");
                println!("verify admission: {verdict}");
                if let Some(reason) = report.get("reason").and_then(Value::as_str) {
                    println!("  reason: {reason}");
                }
            }
            if ok {
                crate::EXIT_OK
            } else {
                crate::EXIT_VERIFY_FAIL
            }
        }
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            crate::EXIT_USER_ERROR
        }
    }
}

fn verify_artifact_or_policy(
    artifact: &Option<PathBuf>,
    proof: &Option<PathBuf>,
    policy: &Option<PathBuf>,
) -> Result<Value, String> {
    let proof_path = proof
        .as_ref()
        .ok_or_else(|| "--proof is required for admission verification".to_string())?;
    let proof = read_json_value(proof_path)?;

    let policy_report = policy
        .as_ref()
        .map(|policy_path| verify_policy_receipt(&proof, policy_path))
        .transpose()?;
    let artifact_report = artifact
        .as_ref()
        .map(|artifact_path| verify_artifact_receipt(&proof, artifact_path))
        .transpose()?;

    match (policy_report, artifact_report) {
        (Some(policy), Some(artifact)) => {
            let policy_ok = value_ok(&policy);
            let artifact_ok = value_ok(&artifact);
            let ok = policy_ok && artifact_ok;
            Ok(json!({
                "ok": ok,
                "verdict": if ok { "accepted" } else { "rejected" },
                "reason": combined_admission_reason(policy_ok, artifact_ok),
                "policy": policy,
                "artifact": artifact,
            }))
        }
        (Some(policy), None) => Ok(policy),
        (None, Some(artifact)) => Ok(artifact),
        (None, None) => Err("--artifact or --policy is required for admission verification".into()),
    }
}

fn verify_policy_receipt(proof: &Value, policy_path: &Path) -> Result<Value, String> {
    let policy = read_json_value(policy_path)?;
    let pinned = policy
        .get("policyCid")
        .and_then(Value::as_str)
        .ok_or_else(|| "policy receipt missing policyCid".to_string())?;
    let candidate = proof
        .get("policyCid")
        .and_then(Value::as_str)
        .ok_or_else(|| "proof receipt missing policyCid".to_string())?;
    let ok = pinned == candidate;
    Ok(json!({
        "ok": ok,
        "verdict": if ok { "accepted" } else { "rejected" },
        "reason": if ok { "policyCid matched" } else { "policyCid mismatch" },
        "pinnedPolicyCid": pinned,
        "candidatePolicyCid": candidate,
    }))
}

fn verify_artifact_receipt(proof: &Value, artifact_path: &Path) -> Result<Value, String> {
    let artifact_bytes = std::fs::read(artifact_path)
        .map_err(|e| format!("read artifact {}: {e}", artifact_path.display()))?;
    let observed_binary_cid = blake3_512_of(&artifact_bytes);
    let attested_binary_cid = proof
        .get("binaryCid")
        .and_then(Value::as_str)
        .ok_or_else(|| "proof receipt missing binaryCid".to_string())?;
    let ok = observed_binary_cid == attested_binary_cid;
    Ok(json!({
        "ok": ok,
        "verdict": if ok { "accepted" } else { "rejected" },
        "reason": if ok { "binaryCid matched" } else { "binaryCid mismatch" },
        "artifact": artifact_path,
        "attestedBinaryCid": attested_binary_cid,
        "observedBinaryCid": observed_binary_cid,
    }))
}

fn value_ok(value: &Value) -> bool {
    value.get("ok").and_then(Value::as_bool).unwrap_or(false)
}

fn combined_admission_reason(policy_ok: bool, artifact_ok: bool) -> &'static str {
    match (policy_ok, artifact_ok) {
        (true, true) => "policyCid and binaryCid matched",
        (false, true) => "policyCid mismatch",
        (true, false) => "binaryCid mismatch",
        (false, false) => "policyCid and binaryCid mismatch",
    }
}

fn read_json_value(path: &Path) -> Result<Value, String> {
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_json(dir: &Path, name: &str, value: &Value) -> PathBuf {
        let path = dir.join(name);
        std::fs::write(&path, serde_json::to_string_pretty(value).unwrap()).unwrap();
        path
    }

    // -- verify_policy_receipt: match / mismatch / missing-field --

    #[test]
    fn policy_receipt_match_is_accepted() {
        let dir = tempfile::tempdir().unwrap();
        let policy_path = write_json(dir.path(), "policy.json", &json!({"policyCid": "cid-A"}));
        let proof = json!({"policyCid": "cid-A"});
        let report = verify_policy_receipt(&proof, &policy_path).unwrap();
        assert_eq!(report["ok"], json!(true));
        assert_eq!(report["verdict"], json!("accepted"));
        assert_eq!(report["reason"], json!("policyCid matched"));
        assert_eq!(report["pinnedPolicyCid"], json!("cid-A"));
        assert_eq!(report["candidatePolicyCid"], json!("cid-A"));
    }

    #[test]
    fn policy_receipt_mismatch_is_rejected() {
        let dir = tempfile::tempdir().unwrap();
        let policy_path = write_json(dir.path(), "policy.json", &json!({"policyCid": "cid-A"}));
        let proof = json!({"policyCid": "cid-B"});
        let report = verify_policy_receipt(&proof, &policy_path).unwrap();
        assert_eq!(report["ok"], json!(false));
        assert_eq!(report["verdict"], json!("rejected"));
        assert_eq!(report["reason"], json!("policyCid mismatch"));
    }

    #[test]
    fn policy_receipt_missing_policy_side_field_is_loud_typed_error() {
        let dir = tempfile::tempdir().unwrap();
        let policy_path = write_json(dir.path(), "policy.json", &json!({"somethingElse": 1}));
        let proof = json!({"policyCid": "cid-A"});
        let err = verify_policy_receipt(&proof, &policy_path).unwrap_err();
        assert_eq!(err, "policy receipt missing policyCid");
    }

    #[test]
    fn policy_receipt_missing_proof_side_field_is_loud_typed_error() {
        let dir = tempfile::tempdir().unwrap();
        let policy_path = write_json(dir.path(), "policy.json", &json!({"policyCid": "cid-A"}));
        let proof = json!({"notPolicyCid": "cid-A"});
        let err = verify_policy_receipt(&proof, &policy_path).unwrap_err();
        assert_eq!(err, "proof receipt missing policyCid");
    }

    // -- verify_artifact_receipt: match / mismatch / missing-field --

    #[test]
    fn artifact_receipt_match_is_accepted() {
        let dir = tempfile::tempdir().unwrap();
        let artifact_path = dir.path().join("artifact.bin");
        std::fs::write(&artifact_path, b"artifact bytes").unwrap();
        let cid = blake3_512_of(b"artifact bytes");
        let proof = json!({"binaryCid": cid});
        let report = verify_artifact_receipt(&proof, &artifact_path).unwrap();
        assert_eq!(report["ok"], json!(true));
        assert_eq!(report["verdict"], json!("accepted"));
        assert_eq!(report["reason"], json!("binaryCid matched"));
        assert_eq!(report["attestedBinaryCid"], json!(cid));
        assert_eq!(report["observedBinaryCid"], json!(cid));
    }

    #[test]
    fn artifact_receipt_mismatch_is_rejected() {
        let dir = tempfile::tempdir().unwrap();
        let artifact_path = dir.path().join("artifact.bin");
        std::fs::write(&artifact_path, b"artifact bytes").unwrap();
        let proof = json!({"binaryCid": "not-the-real-cid"});
        let report = verify_artifact_receipt(&proof, &artifact_path).unwrap();
        assert_eq!(report["ok"], json!(false));
        assert_eq!(report["verdict"], json!("rejected"));
        assert_eq!(report["reason"], json!("binaryCid mismatch"));
        assert_eq!(report["attestedBinaryCid"], json!("not-the-real-cid"));
        assert_eq!(
            report["observedBinaryCid"],
            json!(blake3_512_of(b"artifact bytes"))
        );
    }

    #[test]
    fn artifact_receipt_missing_binary_cid_is_loud_typed_error() {
        let dir = tempfile::tempdir().unwrap();
        let artifact_path = dir.path().join("artifact.bin");
        std::fs::write(&artifact_path, b"artifact bytes").unwrap();
        let proof = json!({"policyCid": "cid-A"});
        let err = verify_artifact_receipt(&proof, &artifact_path).unwrap_err();
        assert_eq!(err, "proof receipt missing binaryCid");
    }

    #[test]
    fn artifact_receipt_unreadable_artifact_is_loud_error() {
        let dir = tempfile::tempdir().unwrap();
        let artifact_path = dir.path().join("does-not-exist.bin");
        let proof = json!({"binaryCid": "cid"});
        let err = verify_artifact_receipt(&proof, &artifact_path).unwrap_err();
        assert!(err.starts_with("read artifact "), "unexpected error: {err}");
    }

    // -- combined driver: both receipts, both verdict arms in one box --

    #[test]
    fn combined_policy_and_artifact_report_both_arms() {
        let dir = tempfile::tempdir().unwrap();
        let artifact_path = dir.path().join("artifact.bin");
        std::fs::write(&artifact_path, b"payload").unwrap();
        let cid = blake3_512_of(b"payload");
        let policy_path = write_json(dir.path(), "policy.json", &json!({"policyCid": "cid-A"}));
        let proof_path = write_json(
            dir.path(),
            "proof.json",
            &json!({"policyCid": "cid-A", "binaryCid": cid}),
        );

        // Accepted arm: both match.
        let report = verify_artifact_or_policy(
            &Some(artifact_path.clone()),
            &Some(proof_path),
            &Some(policy_path.clone()),
        )
        .unwrap();
        assert_eq!(report["ok"], json!(true));
        assert_eq!(report["reason"], json!("policyCid and binaryCid matched"));

        // Rejected arm: policy mismatches, artifact matches.
        let bad_proof_path = write_json(
            dir.path(),
            "bad-proof.json",
            &json!({"policyCid": "cid-B", "binaryCid": cid}),
        );
        let report = verify_artifact_or_policy(
            &Some(artifact_path),
            &Some(bad_proof_path),
            &Some(policy_path),
        )
        .unwrap();
        assert_eq!(report["ok"], json!(false));
        assert_eq!(report["verdict"], json!("rejected"));
        assert_eq!(report["reason"], json!("policyCid mismatch"));
    }

    #[test]
    fn missing_proof_or_targets_are_loud_user_errors() {
        let err = verify_artifact_or_policy(&None, &None, &None).unwrap_err();
        assert_eq!(err, "--proof is required for admission verification");

        let dir = tempfile::tempdir().unwrap();
        let proof_path = write_json(dir.path(), "proof.json", &json!({"policyCid": "cid-A"}));
        let err = verify_artifact_or_policy(&None, &Some(proof_path), &None).unwrap_err();
        assert_eq!(
            err,
            "--artifact or --policy is required for admission verification"
        );
    }
}
