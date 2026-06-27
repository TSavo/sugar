// SPDX-License-Identifier: Apache-2.0
//
// The cargo-test witness lift surface (sugar-lift/1 NDJSON). At LIFT time this
// is the PRODUCER: it runs the crate's tests under `cargo test` and emits a
// ContractDecl carrying the witnessed run as a `custom` EvidenceTerm plus a signed
// WitnessPackageMemento. At RESOLVE time it is the ORACLE: it resolves a witness
// body (from the package, or by re-running) and hands back the bytes -- never a
// verdict. The rust verifier blake3's those bytes itself.
//
// Argv is ignored (the verifier appends `--rpc`); the protocol is one NDJSON
// JSON-RPC request per stdin line, one reply per stdout line.

use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use sugar_lift_rust_cargo_test_witness as kit;

const KIT_ID: &str = "rust-cargo-test-witness";
const KIT_VERSION: &str = "0.1.0";
const SURFACE: &str = "rust-cargo-test-witness";
const KIT_DECLARATION_RPC_METHOD: &str = "sugar.plugin.kit_declaration";
const COMPONENT_PLAN_RPC_METHOD: &str = "sugar.component.plan";
const RESOLVE_WITNESS_RPC_METHOD: &str = "sugar.plugin.resolve_witness";

fn send(obj: &Value) {
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{}", serde_json::to_string(obj).unwrap_or_default());
    let _ = out.flush();
}

fn err_reply(id: &Value, msg: String) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": {"code": -32603, "message": msg}})
}

fn resolve_root(params: &Value) -> PathBuf {
    params
        .get("workspace_root")
        .and_then(|v| v.as_str())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn handle_lift(id: &Value, params: &Value) -> Value {
    let root = resolve_root(params);
    match kit::lift_project(&root) {
        Ok(Some(result)) => {
            // Write the package bundle to disk (audit material; never fail lift).
            let _ = kit::write_bundle_package(&root, &result.bundle_cid, &result.bundle_bytes);
            json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "kind": "ir-document",
                    "ir": result.ir,
                    "witness_mementos": result.mementos,
                    "implications": [],
                    "diagnostics": [],
                    "warnings": [],
                }
            })
        }
        Ok(None) => json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "kind": "ir-document",
                "ir": [],
                "witness_mementos": [],
                "implications": [],
                "diagnostics": [],
                "warnings": [],
            }
        }),
        Err(e) => err_reply(id, e),
    }
}

/// The ORACLE's resolve surface (mirror python `handle_resolve_witness`). Given a
/// WitnessPackageMemento (and where its body lives), RESOLVE the body bytes and
/// return them base64-encoded. CONTENT, never a verdict.
///
/// Resolution order:
///   1. PACKAGE -- read `.sugar/witnesses/<cid>.witness` if present.
///   2a. PACKAGE RECOMPUTE -- a `cargo-test-witness-package` reproduces by
///      re-running the suite and rebuilding the content-addressed bundle (ERROR if
///      the recomputed cid != pinned).
///   2b. PER-TEST RECOMPUTE -- a single `cargo-test-witness` reproduces by
///      re-running its ONE pinned test. An ANTI-TAMPER pre-check refuses to run
///      anything if the memento's fields don't reconstruct its pinned cid
///      (byte-for-byte the python pytest-witness guard).
fn handle_resolve_witness(id: &Value, params: &Value) -> Value {
    let memento = params.get("memento").cloned().unwrap_or(Value::Null);
    let cid = memento
        .get("witness_cid")
        .and_then(|v| v.as_str())
        .or_else(|| params.get("witness_cid").and_then(|v| v.as_str()));
    let Some(cid) = cid else {
        return err_reply(id, "resolve_witness requires a witness_cid".to_string());
    };
    let cid = cid.to_string();
    let ws = params.get("workspace_root").and_then(|v| v.as_str());
    let package_dir = params.get("package_dir").and_then(|v| v.as_str());

    // 1. PACKAGE -- CID-named witness body, deployed separately.
    if let Some(pd) = package_dir {
        let pdir = if Path::new(pd).is_absolute() {
            PathBuf::from(pd)
        } else {
            PathBuf::from(ws.unwrap_or(".")).join(pd)
        };
        let path = pdir.join(kit::cid_filename(&cid, ".witness"));
        if path.is_file() {
            if let Ok(bytes) = std::fs::read(&path) {
                return json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "witness_cid": cid,
                        "body_b64": kit::b64(&bytes),
                        "resolved_by": "package",
                    }
                });
            }
        }
    }

    // 2a. PACKAGE RECOMPUTE -- a whole-suite memento re-runs the suite, rebuilds
    // the bundle.
    let witness_kind = memento.get("witness_kind").and_then(|v| v.as_str());
    if let (Some(ws), Some("cargo-test-witness-package")) = (ws, witness_kind) {
        let code_files = kit::memento_str_list(&memento, "code_files");
        match kit::recompute_bundle_body(Path::new(ws), &code_files, &cid) {
            Ok(bytes) => {
                return json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "witness_cid": cid,
                        "body_b64": kit::b64(&bytes),
                        "resolved_by": "recompute",
                    }
                });
            }
            Err(e) => return err_reply(id, e),
        }
    }

    // 2b. PER-TEST RECOMPUTE -- a single `cargo-test-witness` memento reproduces
    // by re-running its ONE pinned test. The per-test cid won't name a
    // `<cid>.witness` package file (only the bundle is written at lift), so it
    // falls through here. The anti-tamper PRE-CHECK (inside `recompute_one_test_body`)
    // reconstructs the probe witness and refuses to spawn `cargo test` if the
    // memento's own fields don't hash to its pinned cid -- byte-for-byte the
    // python guard. The re-run body is returned (a now-failing test yields a
    // `failed` body the verifier's reproduction check refuses).
    if let (Some(ws), Some("cargo-test-witness")) = (ws, witness_kind) {
        let code_files = kit::memento_str_list(&memento, "code_files");
        let test_id = memento.get("test").and_then(|v| v.as_str());
        let Some(test_id) = test_id else {
            return err_reply(
                id,
                format!("per-test witness memento {cid} is missing a `test` field"),
            );
        };
        let code_cid = memento
            .get("code_cid")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let runtime_cid = memento
            .get("runtime_cid")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let outcome = memento
            .get("outcome")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let wsp = ws.to_string();
        match kit::recompute_one_test_body(
            &cid,
            code_cid,
            runtime_cid,
            test_id,
            outcome,
            &code_files,
            |tid, cfs| kit::run_one_test_witness(Path::new(&wsp), tid, cfs),
        ) {
            Ok(bytes) => {
                return json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "witness_cid": cid,
                        "body_b64": kit::b64(&bytes),
                        "resolved_by": "recompute",
                    }
                });
            }
            Err(e) => return err_reply(id, e),
        }
    }

    err_reply(
        id,
        format!("cannot resolve witness body for {cid}: no package file and not re-runnable"),
    )
}

fn kit_declaration() -> Value {
    json!({
        "kit": {"id": KIT_ID, "language": "rust", "version": KIT_VERSION},
        "rpc": {"methods": [
            {"name": "initialize", "required": true},
            {"name": KIT_DECLARATION_RPC_METHOD, "required": true},
            {"name": COMPONENT_PLAN_RPC_METHOD, "required": false},
            {"name": "lift", "required": true},
            {"name": RESOLVE_WITNESS_RPC_METHOD, "required": false},
            {"name": "shutdown", "required": false},
        ]},
        "proofResolution": {"strategy": "cargo"},
        "effectKinds": [],
        "effectLeaves": [],
        "guardPredicates": [],
        "controlCarriers": [],
        "residueCategories": [],
    })
}

fn component_plan(params: &Value) -> Value {
    let workspace_root = params
        .get("workspace_root")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    if !has_rust_project_candidate(params, &workspace_root) {
        return json!({
            "decision": "decline",
            "reason": "Cargo.toml not present",
        });
    }
    let command = std::env::current_exe()
        .ok()
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| "witness_rpc".to_string());
    let discharge = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|dir| dir.join("discharge_cli")))
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| "discharge_cli".to_string());
    json!({
        "decision": "claim",
        "claims": [{
            "item": "file:Cargo.toml",
            "role": "witness-producer",
            "surface": SURFACE,
        }],
        "plugins": [{
            "name": "rust-cargo-test-witness-lift",
            "kind": "lift",
            "surface": SURFACE,
        }],
        "lift_manifests": [{
            "surface": SURFACE,
            "name": "rust-cargo-test-witness-lift",
            "version": KIT_VERSION,
            "protocol_version": "pep/1.7.0",
            "kind": "lift",
            "command": [command.clone()],
            "discharge_command": [discharge],
            "witness_tool": "cargo-test",
            "resolve_witness_command": [command],
            "resolve_witness_method": RESOLVE_WITNESS_RPC_METHOD,
            "working_dir": ".",
        }],
        "diagnostics": [],
    })
}

fn has_rust_project_candidate(params: &Value, workspace_root: &Path) -> bool {
    forensic_items(params).iter().any(|item| {
        item.get("path").and_then(Value::as_str) == Some("Cargo.toml")
            && item
                .get("language_hint")
                .or_else(|| item.get("languageHint"))
                .and_then(Value::as_str)
                == Some("rust")
    }) || workspace_root.join("Cargo.toml").is_file()
}

fn forensic_items(params: &Value) -> Vec<&Value> {
    params
        .get("project_forensics")
        .or_else(|| params.get("projectForensics"))
        .and_then(|value| value.get("items"))
        .or_else(|| {
            params
                .get("workspace_evidence")
                .or_else(|| params.get("workspaceEvidence"))
                .and_then(|value| value.get("items"))
        })
        .and_then(Value::as_array)
        .map(|items| items.iter().collect())
        .unwrap_or_default()
}

fn main() {
    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Ok(msg): Result<Value, _> = serde_json::from_str(line) else {
            continue;
        };
        let method = msg.get("method").and_then(|v| v.as_str()).unwrap_or("");
        let id = msg.get("id").cloned().unwrap_or(Value::Null);
        let params = msg.get("params").cloned().unwrap_or(Value::Null);
        match method {
            "initialize" => send(&json!({
                "jsonrpc": "2.0", "id": id, "result": {
                    "name": "sugar-lsp-rust-cargo-test-witness",
                    "version": KIT_VERSION,
                    "protocol_version": "sugar-lsp-shared/1",
                    "kit_id": KIT_ID,
                    "capabilities": {
                        "source_surfaces": [SURFACE],
                        "entry_kinds": [],
                        "diagnostic_codes": [],
                        "status_kinds": ["prove"],
                    }
                }
            })),
            KIT_DECLARATION_RPC_METHOD => {
                send(&json!({"jsonrpc": "2.0", "id": id, "result": kit_declaration()}))
            }
            COMPONENT_PLAN_RPC_METHOD => {
                send(&json!({"jsonrpc": "2.0", "id": id, "result": component_plan(&params)}))
            }
            "lift" => send(&handle_lift(&id, &params)),
            RESOLVE_WITNESS_RPC_METHOD => send(&handle_resolve_witness(&id, &params)),
            "shutdown" => {
                send(&json!({"jsonrpc": "2.0", "id": id, "result": Value::Null}));
                break;
            }
            _ => {
                if !id.is_null() {
                    send(&json!({"jsonrpc": "2.0", "id": id, "result": Value::Null}));
                }
            }
        }
    }
}
