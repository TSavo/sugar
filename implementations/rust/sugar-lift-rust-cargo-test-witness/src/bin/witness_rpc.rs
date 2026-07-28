// SPDX-License-Identifier: MIT OR Apache-2.0
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
// The ONE construction door. There is no `lift` kit method: full-tree
// construction is `sugar.enumerate` over the SourceTree (#6222). This kit is
// the Rust twin of `sugar_pytest_witness.lift_lsp`, which crossed the same
// membrane first; the level protocol is
// `protocol/specs/2026-07-08-enumeration-protocol.md`.
const ENUMERATE_RPC_METHOD: &str = "sugar.enumerate";

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

// ---------------------------------------------------------------------------
// `sugar.enumerate` -- the ONE construction door
// ---------------------------------------------------------------------------

/// Levels a SOURCE kit censuses that a witness PRODUCER has nothing to say
/// about. Answering an empty census (rather than an error) keeps `prove`/report
/// walks that sweep every registered surface from failing on this kit. Byte-for
/// byte the python witness kit's `_EMPTY_CENSUS_LEVELS`.
const EMPTY_CENSUS_LEVELS: &[&str] = &[
    "functions",
    "call_sites",
    "assertions",
    "facts",
    "implications",
    "exports",
    "contract-declarations",
    "provider-contract-members",
    "contract-demands",
    "context-manager-edges",
    "parameter-contract-resume",
];

fn enumerate_result(id: &Value, nodes: Vec<Value>, gaps: Vec<Value>) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "result": {"nodes": nodes, "gaps": gaps}})
}

/// `sugar.enumerate`: `source_files` censuses the crate's real source closure;
/// `universe` emits this kit's contribution.
///
/// A witness package is a WHOLE-SUITE artifact, not a per-file one, so the
/// suite runs exactly once: the census reports every `.rs` file (so the Rust
/// fold's `sourceMementos`/`sourceLedger` testify the real source closure), and
/// the package's two IR rows -- the custom-evidence contract and its signed
/// WitnessPackageMemento -- are emitted at the ANCHOR file only (the first code
/// file in sorted order). Every other file answers an empty universe, which is
/// the truth: it contributes no contract of its own.
///
/// `discover_rust_files` returns `["."]` as its test-file handle -- a stable
/// suite identifier, not a real path -- so the anchor is taken from the CODE
/// files, which are real files with real mementos.
fn handle_enumerate(id: &Value, params: &Value) -> Value {
    let level = params.get("level").and_then(Value::as_str).unwrap_or("");
    let ws = resolve_root(params);

    if level == "parameter-contract-link-units" {
        // A witness producer enrolls no parameter-contract link units.
        return json!({"jsonrpc": "2.0", "id": id, "result": {"rows": []}});
    }
    if EMPTY_CENSUS_LEVELS.contains(&level) {
        return enumerate_result(id, Vec::new(), Vec::new());
    }

    if level == "source_files" {
        let (code_files, _test_files) = kit::discover_rust_files(&ws);
        let mut nodes = Vec::new();
        let mut gaps = Vec::new();
        for rel in &code_files {
            match kit::file_source_memento(&ws, rel) {
                Ok(memento) => nodes.push(
                    json!({"memento": memento, "audit": Value::Null, "payload": Value::Null}),
                ),
                Err(reason) => gaps.push(json!({
                    "memento": kit::degenerate_file_memento(rel, None),
                    "reason": reason,
                })),
            }
        }
        return enumerate_result(id, nodes, gaps);
    }

    if level == "universe" {
        let at = params.get("at").cloned().unwrap_or(Value::Null);
        let file_rel = at.get("file").and_then(Value::as_str);
        let Some(anchor) = kit::enumerate_anchor_file(&ws) else {
            // No readable code file at all means no package -- an empty
            // universe, not a gap (the census already testified the reason).
            return enumerate_result(id, Vec::new(), Vec::new());
        };
        if file_rel != Some(anchor.as_str()) {
            // Not the anchor: no contract of its own.
            return enumerate_result(id, Vec::new(), Vec::new());
        }
        let result = match kit::lift_project(&ws) {
            // No tests -> no witness package. An empty universe, not a gap.
            Ok(None) => return enumerate_result(id, Vec::new(), Vec::new()),
            Ok(Some(result)) => result,
            Err(e) => return err_reply(id, e),
        };
        // Write the package bundle to disk (audit material; never fail lift).
        let _ = kit::write_bundle_package(&ws, &result.bundle_cid, &result.bundle_bytes);
        let anchor_memento = match kit::file_source_memento(&ws, &anchor) {
            Ok(memento) => memento,
            Err(reason) => return err_reply(id, reason),
        };
        let nodes = result
            .ir
            .into_iter()
            .map(|row| {
                json!({"memento": anchor_memento.clone(), "audit": row, "payload": Value::Null})
            })
            .collect();
        return enumerate_result(id, nodes, Vec::new());
    }

    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": -32602,
            "message": format!("sugar.enumerate: unknown level `{level}`"),
        },
    })
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
            // lift is not a kit method: full-tree construction is
            // sugar.enumerate only (#6222). Same eviction the python kits made.
            {"name": ENUMERATE_RPC_METHOD, "required": true},
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
            ENUMERATE_RPC_METHOD => send(&handle_enumerate(&id, &params)),
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
