// SPDX-License-Identifier: Apache-2.0
//
// `sugar emit`: dispatch neutral contract predicates to a target test
// emitter kit. The target kit owns framework syntax and native check
// semantics; the CLI only resolves the manifest, invokes the kit, and writes
// the emitted artifact.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use clap::Parser;
use owo_colors::OwoColorize;
use serde_json::{json, Value as Json};

use crate::kit_dispatch::{dispatch_emit, dispatch_emit_check, dispatch_emit_witness};
use crate::report_witness::{mint_json_witness_with_options, JsonWitnessOptions};
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

    let mut metadata = BTreeMap::new();
    metadata.insert("sugar.emit.mode".into(), "witness".into());
    metadata.insert("sugar.emit.surface".into(), surface.to_string());
    metadata.insert("sugar.emit.claimKind".into(), claim_kind.clone());
    let minted = mint_json_witness_with_options(
        &format!("emit-witness-{surface}-{claim_kind}"),
        &claim_kind,
        claim_body,
        evidence,
        out_dir,
        JsonWitnessOptions {
            produced_by: Some(produced_by),
            produced_at: Some(produced_at),
            verifier_cid: Some(verifier_cid),
            policy_cid: Some(policy_cid),
            extra_input_cids: input_cids,
            proof_metadata: metadata,
            plan_cid: None,
            actual_output_cids: Vec::new(),
        },
    )
    .map_err(|e| format!("mint emit witness memento: {e}"))?;

    Ok(EmitWitnessProof {
        filename_cid: minted.proof_cid,
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

    #[test]
    fn emit_witness_proof_contains_pointer_not_body() {
        let temp = tempfile::tempdir().expect("tempdir");
        let plan = json!({
            "kind": "RealizerPlan",
            "policyCid": "builtin:test-policy"
        });
        let emit_result = json!({
            "claimKind": "orp-witness",
            "verifierCid": "builtin:test-verifier",
            "policyCid": "builtin:test-policy",
            "producedAt": DEFAULT_WITNESS_PRODUCED_AT,
            "inputCids": ["blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
            "claimBody": {
                "claimKind": "orp-witness",
                "subjectCids": ["blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]
            },
            "evidence": {
                "kind": "test-evidence",
                "artifactCid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
            },
            "output": {
                "status": "witnessed",
                "emitter": {"name": "test-emitter"},
                "observedArtifactCids": ["blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"]
            }
        });

        let minted = mint_witness_proof(
            Path::new("/tmp/project"),
            "test-surface",
            &plan,
            &emit_result,
            temp.path(),
        )
        .expect("emit witness minted");
        let proof_file = temp
            .path()
            .join(sugar_proof_envelope::proof_filename(&minted.filename_cid));
        let proof_bytes = std::fs::read(proof_file).expect("read witness proof");
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
            envelope.pointer("/body/verifierCid").and_then(Json::as_str),
            Some("builtin:test-verifier")
        );
        assert!(
            envelope.pointer("/metadata/evidence").is_none()
                && envelope.pointer("/metadata/claimBody").is_none()
                && envelope.pointer("/body/evidence").is_none()
                && envelope.pointer("/body/claimBody").is_none(),
            "emit witness proof must carry only the structured pointer, not the witness body: {envelope:#}"
        );
    }
}
