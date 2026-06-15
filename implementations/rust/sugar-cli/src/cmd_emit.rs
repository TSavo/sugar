// SPDX-License-Identifier: Apache-2.0
//
// `sugar emit`: dispatch neutral contract predicates to a target test
// emitter kit. The target kit owns framework syntax and native check
// semantics; the CLI only resolves the manifest, invokes the kit, and writes
// the emitted artifact.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use clap::Parser;
use owo_colors::OwoColorize;
use serde_json::{json, Value as Json};

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_claim_envelope::{mint_witness, MintWitnessArgs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, Ed25519Seed, ProofEnvelopeInput,
};

use crate::kit_dispatch::{dispatch_emit, dispatch_emit_check, dispatch_emit_witness};
use crate::{OutputFlags, EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

const DEFAULT_WITNESS_PRODUCED_AT: &str = "2026-05-08T00:00:00Z";

#[derive(Debug, Clone)]
pub(crate) struct EmitWitnessProof {
    pub filename_cid: String,
}

#[derive(Parser, Debug, Clone)]
pub struct EmitArgs {
    /// Project root containing `.sugar/emit/<target>-<framework>/manifest.toml`.
    #[arg(long)]
    pub project: Option<PathBuf>,
    /// Target language for the emitted artifact, for example `go`.
    #[arg(long)]
    pub target: String,
    /// Target test framework. `go --framework testing` resolves `.sugar/emit/go-testing`.
    #[arg(long)]
    pub framework: String,
    /// JSON EmitPlan passed through to the emitter kit.
    #[arg(long)]
    pub plan: PathBuf,
    /// Directory where the emitted artifact should be written.
    #[arg(long = "out-dir")]
    pub out_dir: PathBuf,
    /// After writing the artifact, ask the selected emit kit to run its
    /// native compile/test check over the emitted project.
    #[arg(long = "compile-check")]
    pub compile_check: bool,
    #[command(flatten)]
    pub out: OutputFlags,
}

pub fn run(args: EmitArgs) -> u8 {
    let project_root = args.project.clone().unwrap_or_else(|| PathBuf::from("."));
    if !project_root.exists() {
        return user_error(
            args.out.json,
            json!({
                "ok": false,
                "error": format!("project not found: {}", project_root.display()),
            }),
        );
    }
    if !args.out_dir.exists() {
        if let Err(error) = std::fs::create_dir_all(&args.out_dir) {
            return user_error(
                args.out.json,
                json!({
                    "ok": false,
                    "error": format!("create {}: {error}", args.out_dir.display()),
                }),
            );
        }
    }
    let plan = match read_plan(&args.plan) {
        Ok(plan) => plan,
        Err(error) => {
            return user_error(
                args.out.json,
                json!({
                    "ok": false,
                    "error": error,
                }),
            )
        }
    };

    let emitted = match dispatch_emit(&project_root, &args.target, &args.framework, &plan) {
        Ok(emitted) => emitted,
        Err(error) => {
            let payload = json!({
                "ok": false,
                "targetLanguage": args.target,
                "targetFramework": args.framework,
                "error": error.to_string(),
            });
            if args.out.json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&payload).expect("serialize emit error")
                );
            } else {
                eprintln!("{}: {}", "error".red().bold(), error);
            }
            return EXIT_VERIFY_FAIL;
        }
    };

    let source = match emitted.result.get("source").and_then(Json::as_str) {
        Some(source) => source,
        None => {
            return user_error(
                args.out.json,
                json!({
                    "ok": false,
                    "targetLanguage": args.target,
                    "targetFramework": args.framework,
                    "error": "emit kit response missing result.source",
                    "result": emitted.result,
                }),
            )
        }
    };
    let artifact_path = match write_emitted_source(
        &args.out_dir,
        &args.target,
        &args.framework,
        &emitted.result,
        source,
    ) {
        Ok(path) => path,
        Err(error) => {
            return user_error(
                args.out.json,
                json!({
                    "ok": false,
                    "targetLanguage": args.target,
                    "targetFramework": args.framework,
                    "error": error,
                }),
            )
        }
    };

    let compile = if args.compile_check {
        match dispatch_emit_check(
            &project_root,
            &args.target,
            &args.framework,
            &plan,
            &args.out_dir,
            &artifact_path,
            &emitted.result,
        ) {
            Ok(report) if report.get("ok").and_then(Json::as_bool).unwrap_or(false) => Some(report),
            Ok(report) => {
                emit_receipt(
                    args.out.json,
                    false,
                    &args,
                    &emitted,
                    &artifact_path,
                    Some(report),
                );
                return EXIT_VERIFY_FAIL;
            }
            Err(error) => {
                emit_receipt(
                    args.out.json,
                    false,
                    &args,
                    &emitted,
                    &artifact_path,
                    Some(json!({"ok": false, "error": error.to_string()})),
                );
                return EXIT_VERIFY_FAIL;
            }
        }
    } else {
        None
    };

    let complete = emitted
        .result
        .get("is_complete")
        .and_then(Json::as_bool)
        .unwrap_or(true);
    emit_receipt(
        args.out.json,
        complete,
        &args,
        &emitted,
        &artifact_path,
        compile,
    );
    if complete {
        EXIT_OK
    } else {
        EXIT_VERIFY_FAIL
    }
}

/// Surviving contract -> witness emission path. The public `lower` verb is
/// retired; mint and future witness surfaces should route through `emit`.
pub(crate) fn emit_witness_requirement(
    project_root: &Path,
    requirement: &Json,
    out_dir: &Path,
    quiet: bool,
) -> Result<EmitWitnessProof, String> {
    let surface = required_str(requirement, "surface", "witness requirement")?;
    emit_witness_requirement_for_surface(project_root, surface, requirement, out_dir, quiet)
}

fn read_plan(path: &Path) -> Result<Json, String> {
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    serde_json::from_str::<Json>(&text).map_err(|e| format!("parse {}: {e}", path.display()))
}

fn write_emitted_source(
    out_dir: &Path,
    target: &str,
    framework: &str,
    result: &Json,
    source: &str,
) -> Result<PathBuf, String> {
    let path = result
        .get("path")
        .and_then(Json::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| default_artifact_path(target, framework, result));
    let full = if path.is_absolute() {
        path
    } else {
        out_dir.join(path)
    };
    if let Some(parent) = full.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("create {}: {e}", parent.display()))?;
    }
    std::fs::write(&full, source).map_err(|e| format!("write {}: {e}", full.display()))?;
    Ok(full)
}

fn default_artifact_path(target: &str, _framework: &str, result: &Json) -> PathBuf {
    let extension = result
        .get("extension")
        .and_then(Json::as_str)
        .filter(|s| !s.is_empty())
        .unwrap_or(target);
    PathBuf::from(format!("sugar_emitted.{extension}"))
}

fn emit_receipt(
    json_output: bool,
    ok: bool,
    args: &EmitArgs,
    emitted: &crate::kit_dispatch::EmitDispatchResult,
    artifact_path: &Path,
    compile: Option<Json>,
) {
    let receipt = json!({
        "ok": ok,
        "targetLanguage": args.target,
        "targetFramework": args.framework,
        "surface": emitted.surface,
        "source": emitted.source,
        "path": artifact_path,
        "emittedArtifactCid": emitted
            .result
            .get("emitted_artifact_cid")
            .and_then(Json::as_str),
        "emittedPredicates": emitted.result.get("emitted_predicates").cloned().unwrap_or(Json::Array(vec![])),
        "unsupportedPredicates": emitted.result.get("unsupported_predicates").cloned().unwrap_or(Json::Array(vec![])),
        "isComplete": emitted.result.get("is_complete").and_then(Json::as_bool).unwrap_or(ok),
        "compileCheck": compile,
    });
    if json_output {
        println!(
            "{}",
            serde_json::to_string_pretty(&receipt).expect("serialize emit receipt")
        );
    } else if ok {
        println!("{}", "emit".green().bold());
        println!("  artifact : {}", artifact_path.display());
        if let Some(cid) = receipt.get("emittedArtifactCid").and_then(Json::as_str) {
            println!("  CID      : {cid}");
        }
    } else {
        eprintln!(
            "{}: emit incomplete for {} / {}",
            "error".red().bold(),
            args.target,
            args.framework
        );
    }
}

fn user_error(json_output: bool, payload: Json) -> u8 {
    if json_output {
        println!(
            "{}",
            serde_json::to_string_pretty(&payload).expect("serialize user error")
        );
    } else {
        let error = payload
            .get("error")
            .and_then(Json::as_str)
            .unwrap_or("invalid emit arguments");
        eprintln!("{}: {error}", "error".red().bold());
    }
    EXIT_USER_ERROR
}

fn emit_witness_requirement_for_surface(
    project_root: &Path,
    surface: &str,
    requirement: &Json,
    out_dir: &Path,
    _quiet: bool,
) -> Result<EmitWitnessProof, String> {
    let plan = build_witness_emit_plan(requirement)?;
    let emit_result = dispatch_emit_witness(project_root, surface, &plan)?;
    mint_witness_proof(project_root, surface, &plan, &emit_result, out_dir)
}

fn build_witness_emit_plan(requirement: &Json) -> Result<Json, String> {
    if requirement.get("kind").and_then(Json::as_str) == Some("RealizerPlan") {
        return Ok(requirement.clone());
    }
    let obligation = requirement
        .get("obligation")
        .cloned()
        .ok_or_else(|| "witness requirement missing obligation".to_string())?;
    let host = requirement
        .get("host")
        .cloned()
        .ok_or_else(|| "witness requirement missing host".to_string())?;
    let bindings = requirement
        .get("bindings")
        .cloned()
        .unwrap_or_else(|| json!([]));
    let input_cids = requirement
        .get("inputCids")
        .cloned()
        .unwrap_or_else(|| json!([]));
    let policy_cid = requirement
        .pointer("/policy/policyCid")
        .or_else(|| requirement.get("policyCid"))
        .and_then(Json::as_str)
        .unwrap_or("builtin:sugar-emit-witness-policy");
    Ok(json!({
        "kind": "RealizerPlan",
        "schemaVersion": "1",
        "mode": "attest",
        "obligation": obligation,
        "host": host,
        "bindings": bindings,
        "policyCid": policy_cid,
        "inputCids": input_cids,
    }))
}

fn mint_witness_proof(
    _project_root: &Path,
    surface: &str,
    plan: &Json,
    emit_result: &Json,
    out_dir: &Path,
) -> Result<EmitWitnessProof, String> {
    let output = emit_result
        .get("output")
        .ok_or_else(|| "emit witness result missing output".to_string())?;
    let status = output
        .get("status")
        .and_then(Json::as_str)
        .ok_or_else(|| "emit witness output missing status".to_string())?;
    if status != "witnessed" {
        let message = output
            .get("message")
            .and_then(Json::as_str)
            .unwrap_or("emit witness rejected");
        return Err(message.to_string());
    }

    let claim_body = emit_result
        .get("claimBody")
        .ok_or_else(|| "witnessed emit result missing claimBody".to_string())?;
    let evidence = emit_result
        .get("evidence")
        .ok_or_else(|| "witnessed emit result missing evidence".to_string())?;
    let claim_body_cid = jcs_cid(claim_body);
    let evidence_root_cid = emit_result
        .get("evidenceCid")
        .and_then(Json::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| jcs_cid(evidence));
    let claim_kind = emit_result
        .get("claimKind")
        .or_else(|| claim_body.get("claimKind"))
        .and_then(Json::as_str)
        .unwrap_or("orp-witness")
        .to_string();
    let verifier_cid = emit_result
        .get("verifierCid")
        .or_else(|| claim_body.get("verifierCid"))
        .and_then(Json::as_str)
        .unwrap_or("builtin:sugar-emit-witness")
        .to_string();
    let policy_cid = emit_result
        .get("policyCid")
        .or_else(|| claim_body.get("policyCid"))
        .or_else(|| plan.get("policyCid"))
        .and_then(Json::as_str)
        .unwrap_or("builtin:sugar-emit-witness-policy")
        .to_string();
    let produced_by = output
        .pointer("/emitter/name")
        .or_else(|| output.pointer("/realizer/name"))
        .and_then(Json::as_str)
        .unwrap_or("sugar-emit")
        .to_string();
    let produced_at = emit_result
        .get("producedAt")
        .and_then(Json::as_str)
        .unwrap_or(DEFAULT_WITNESS_PRODUCED_AT)
        .to_string();

    let mut input_cids = Vec::new();
    collect_cid_array(emit_result.get("inputCids"), &mut input_cids);
    collect_cid_array(output.get("observedArtifactCids"), &mut input_cids);
    collect_cid_strings(claim_body.get("subjectCids"), &mut input_cids);
    input_cids.sort();
    input_cids.dedup();

    let signer_seed = deterministic_signer_seed(&produced_by);
    let witness = mint_witness(&MintWitnessArgs {
        claim_kind: claim_kind.clone(),
        claim_body_cid,
        verifier_cid,
        policy_cid,
        evidence_root_cid,
        input_cids,
        produced_by: produced_by.clone(),
        produced_at: produced_at.clone(),
        claim_body: json_to_cvalue(claim_body),
        evidence: json_to_cvalue(evidence),
        signer_seed,
    })
    .map_err(|e| format!("mint emit witness memento: {e}"))?;

    let mut members = BTreeMap::new();
    members.insert(witness.cid, witness.canonical_bytes);
    let mut metadata = BTreeMap::new();
    metadata.insert("sugar.emit.mode".into(), "witness".into());
    metadata.insert("sugar.emit.surface".into(), surface.to_string());
    metadata.insert("sugar.emit.claimKind".into(), claim_kind.clone());
    let proof = build_proof_envelope(&ProofEnvelopeInput {
        name: format!("@sugar/emit-witness/{claim_kind}"),
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

    Ok(EmitWitnessProof {
        filename_cid: proof.cid,
    })
}

fn optional_str<'a>(value: &'a Json, field: &str) -> Option<&'a str> {
    value.get(field).and_then(Json::as_str)
}

fn required_str<'a>(value: &'a Json, field: &str, context: &str) -> Result<&'a str, String> {
    optional_str(value, field).ok_or_else(|| format!("{context} missing `{field}`"))
}

fn collect_cid_array(value: Option<&Json>, out: &mut Vec<String>) {
    let Some(values) = value.and_then(Json::as_array) else {
        return;
    };
    out.extend(
        values
            .iter()
            .filter_map(Json::as_str)
            .filter(|value| value.starts_with("blake3-512:"))
            .map(str::to_string),
    );
}

fn collect_cid_strings(value: Option<&Json>, out: &mut Vec<String>) {
    match value {
        Some(Json::String(s)) if s.starts_with("blake3-512:") => out.push(s.clone()),
        Some(Json::Array(items)) => {
            for item in items {
                collect_cid_strings(Some(item), out);
            }
        }
        Some(Json::Object(map)) => {
            for item in map.values() {
                collect_cid_strings(Some(item), out);
            }
        }
        _ => {}
    }
}

fn jcs_cid(value: &Json) -> String {
    let canonical = json_to_cvalue(value);
    let jcs = encode_jcs(&canonical);
    blake3_512_of(jcs.as_bytes())
}

fn deterministic_signer_seed(principal: &str) -> Ed25519Seed {
    let digest = blake3_512_of(format!("sugar-emit-signer:{principal}").as_bytes());
    let hex = digest
        .strip_prefix("blake3-512:")
        .expect("blake3_512_of returns tagged digest");
    let mut seed = [0u8; 32];
    for (idx, slot) in seed.iter_mut().enumerate() {
        let hi = hex_nibble(hex.as_bytes()[idx * 2]);
        let lo = hex_nibble(hex.as_bytes()[idx * 2 + 1]);
        *slot = (hi << 4) | lo;
    }
    seed
}

fn hex_nibble(byte: u8) -> u8 {
    match byte {
        b'0'..=b'9' => byte - b'0',
        b'a'..=b'f' => byte - b'a' + 10,
        b'A'..=b'F' => byte - b'A' + 10,
        _ => 0,
    }
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
            } else if let Some(f) = n.as_f64() {
                CValue::integer(f as i128)
            } else {
                CValue::integer(0)
            }
        }
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => {
            let v: Vec<_> = items.iter().map(json_to_cvalue).collect();
            CValue::array(v)
        }
        Json::Object(map) => {
            let entries: Vec<(String, Arc<CValue>)> = map
                .iter()
                .map(|(k, v)| (k.clone(), json_to_cvalue(v)))
                .collect();
            CValue::object(entries)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_witness_emit_plan_maps_requirement_to_attest_plan() {
        let requirement = json!({
            "surface": "c",
            "mode": "witness",
            "obligation": {"kind": "predicate", "name": "checked_add_u8.postcondition"},
            "host": {"kit": "c", "artifact": "artifacts/software/checked_add_u8.c"},
            "policy": {"policyCid": "builtin:bridgeworks.checked-add-u8"}
        });
        let plan = build_witness_emit_plan(&requirement).expect("plan builds");
        assert_eq!(plan["kind"], "RealizerPlan");
        assert_eq!(plan["mode"], "attest");
        assert_eq!(plan["obligation"]["name"], "checked_add_u8.postcondition");
        assert_eq!(plan["policyCid"], "builtin:bridgeworks.checked-add-u8");
    }

    #[test]
    fn default_artifact_path_is_not_language_framework_special_cased() {
        let path = default_artifact_path("go", "testing", &json!({}));

        assert_eq!(path, PathBuf::from("sugar_emitted.go"));
    }
}
