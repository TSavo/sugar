// SPDX-License-Identifier: MIT OR Apache-2.0
//
// contracts_rpc: the RPC kit entrypoint for the rust `#[requires]` /
// `#[ensures]` contract lifter.
//
// THE SEVER (engine-sever first cut):
//
//   The rust substrate USED to call `sugar_lift_contracts::lift_file`
//   STATICALLY (compile-time linked) at four sites (sugar-lift,
//   sugar-build, sugar-cli, sugar-lsp-rust). That made the
//   substrate language-bound: a rust lifter was welded into the core.
//
//   This binary makes the rust-contracts lifter a real RPC kit, exactly
//   like the python bind kit
//   (`sugar_lift_python_source.bind_rpc`). The CLI's mint pipeline
//   spawns it per its manifest, drives `initialize` / `lift` /
//   `shutdown` over NDJSON stdin/stdout, and consumes the returned
//   `ir-document`. The substrate carries ZERO compile-time dependency
//   on this lifter.
//
// PROTOCOL (mirrors `bind_rpc.py` + `walk_rpc.rs`, the working RPC-lift
// pattern; PEP 1.7.0 `kind = "lift"` over the legacy-retained
// `initialize` / `lift` / `shutdown` JSON-RPC shape per
// `2026-04-30-lift-plugin-protocol.md`):
//
//   initialize                       -> capabilities (authoring_surfaces)
//   sugar.plugin.kit_declaration  -> kit id / language / rpc methods
//   lift                             -> { kind: "ir-document", ir, ... }
//   shutdown                         -> null
//
// `lift` reads the requested rust source files, calls the EXISTING
// `lift_file` (the lifting logic is WRAPPED, never reimplemented), and
// marshals the resulting `ContractDecl`s into the `kind: "contract"`
// IR-JSON shape the CLI's `cmd_mint` ir-document path consumes (via
// `sugar_ir_symbolic::serialize::marshal_declarations`, the SAME
// serializer `sugar-lsp-rust` already used for the static path).

use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use sugar_ir_symbolic::serialize::marshal_declarations;
use sugar_lift_contracts::lift_file;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const SURFACE: &str = "rust-contracts";
const KIT_DECLARATION_RPC_METHOD: &str = "sugar.plugin.kit_declaration";

fn initialize_result() -> Value {
    json!({
        "name": "sugar-lift-contracts-rpc",
        "version": VERSION,
        "protocol_version": "pep/1.7.0",
        "capabilities": {
            "authoring_surfaces": ["rust-contracts"],
            "ir_version": "v1.1.0",
            "emits_signed_mementos": false,
        },
    })
}

fn kit_declaration_result() -> Value {
    json!({
        "kit": {
            "id": SURFACE,
            "language": "rust",
            "version": VERSION,
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": true},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": true},
                {"name": "lift", "required": true},
                {"name": "shutdown", "required": false},
            ]
        },
        "proofResolution": {"strategy": "cargo"},
        "effectKinds": [],
        "effectLeaves": [],
        "guardPredicates": [],
        "controlCarriers": [],
        "residueCategories": [],
    })
}

/// `lift`: read the requested rust source files, run the EXISTING
/// `lift_file` over each, and return an `ir-document` whose `ir` array is
/// the marshalled `kind: "contract"` entries.
///
/// Request params (PEP 1.7.0 lift shape, same as walk_rpc/bind_rpc):
///   {
///     "workspace_root": "/abs/path",
///     "source_paths":   ["src/lib.rs", ...]   // relative to workspace_root
///   }
///
/// When `source_paths` is absent or empty, every `.rs` file under
/// `workspace_root` is walked (mirrors the python kit's `"."` default and
/// the old `lift_path` behavior).
fn lift(params: &Value) -> Value {
    let workspace_root = params
        .get("workspace_root")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));

    // Resolve the request's `source_paths` into concrete `.rs` files
    // (relative to `workspace_root`). The CLI's `build_lift_params`
    // always sends `["."]` (the whole project), so each entry that is a
    // directory (or absent) expands to a deterministic walk of its `.rs`
    // files. A `.rs` file entry passes through verbatim. This mirrors the
    // python bind kit's `lift_paths` directory-walking and the pre-sever
    // `lift_path` whole-workspace walk.
    let requested: Vec<String> = match params.get("source_paths").and_then(Value::as_array) {
        Some(arr) if !arr.is_empty() => arr
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect(),
        _ => vec![".".to_string()],
    };
    let mut rel_paths: Vec<String> = Vec::new();
    let mut diagnostics: Vec<Value> = Vec::new();
    for entry in &requested {
        let abs = workspace_root.join(entry);
        if abs.is_dir() {
            // Walk the directory; emit paths relative to workspace_root so
            // the lifted contract's source path is host-independent.
            match enumerate_rs_files(&abs) {
                Ok(files) => {
                    for rel in files {
                        let joined = if entry == "." {
                            rel
                        } else {
                            format!("{}/{}", entry.trim_end_matches('/'), rel)
                        };
                        rel_paths.push(joined);
                    }
                }
                Err(e) => {
                    diagnostics.push(json!({
                        "kind": "lift-gap",
                        "path": entry,
                        "reason": format!("enumerate source files: {e}"),
                    }));
                }
            }
        } else {
            rel_paths.push(entry.clone());
        }
    }
    rel_paths.sort();
    rel_paths.dedup();

    let mut entries: Vec<Value> = Vec::new();

    for rel in &rel_paths {
        let abs = workspace_root.join(rel);
        let bytes = match std::fs::read(&abs) {
            Ok(b) => b,
            Err(e) => {
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": format!("read: {e}"),
                }));
                continue;
            }
        };
        let src = match std::str::from_utf8(&bytes) {
            Ok(s) => s,
            Err(_) => {
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": "non-utf8 source",
                }));
                continue;
            }
        };
        let file = match syn::parse_file(src) {
            Ok(f) => f,
            Err(e) => {
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": format!("parse: {e}"),
                }));
                continue;
            }
        };

        // WRAP, do not reimplement: this is the same call the static
        // substrate used to make at sugar-lift/lib.rs and lift_pass.rs.
        let out = lift_file(&file, rel);

        // Marshal to the locked IR-JSON `kind: "contract"` shape, then
        // parse it back so each entry embeds as a JSON object (not a
        // string) in the `ir` array.
        let marshalled = marshal_declarations(&out.decls);
        let parsed: Value = serde_json::from_str(&marshalled).unwrap_or_else(|_| json!([]));
        if let Some(arr) = parsed.as_array() {
            entries.extend(arr.iter().cloned());
        }

        for w in &out.warnings {
            diagnostics.push(json!({
                "kind": "lift-gap",
                "path": w.source_path,
                "item": w.item_name,
                "reason": w.reason,
            }));
        }
    }

    json!({
        "kind": "ir-document",
        "ir": entries,
        "diagnostics": diagnostics,
        "refusals": [],
    })
}

/// Directory names that are never part of a rust source tree. Mirrors
/// `sugar_lift::IGNORED_DIRS` so a no-`source_paths` lift walks the
/// same set the old static `lift_path` walked.
const IGNORED_DIRS: &[&str] = &[
    "target",
    ".git",
    "node_modules",
    "__pycache__",
    ".DS_Store",
    ".idea",
    ".vscode",
];

/// Walk `root` for `.rs` files, returning relative POSIX paths sorted in
/// deterministic byte order. Mirrors `sugar_lift::enumerate_rs_files`
/// so CIDs are byte-identical to the pre-sever static path.
fn enumerate_rs_files(root: &Path) -> Result<Vec<String>, String> {
    let mut out: Vec<String> = Vec::new();
    if !root.exists() {
        return Ok(out);
    }
    for entry in walkdir::WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_entry(|e| {
            let n = e.file_name().to_string_lossy();
            !IGNORED_DIRS.iter().any(|&ig| n == ig)
        })
    {
        let entry = entry.map_err(|e| format!("walk {}: {e}", root.display()))?;
        if entry.file_type().is_file() {
            if entry.path().extension().is_some_and(|ext| ext == "rs") {
                if let Ok(rel) = entry.path().strip_prefix(root) {
                    let posix = rel
                        .components()
                        .map(|c| c.as_os_str().to_string_lossy().into_owned())
                        .collect::<Vec<_>>()
                        .join("/");
                    if !posix.is_empty() && !posix.starts_with("..") {
                        out.push(posix);
                    }
                }
            }
        }
    }
    out.sort();
    Ok(out)
}

fn dispatch(request: &Value) -> Value {
    let id = match request.get("id") {
        Some(id) => id.clone(),
        None => Value::Null,
    };
    let method = match request.get("method").and_then(Value::as_str) {
        Some(method) => method,
        None => "",
    };
    let params = request.get("params").cloned().unwrap_or_else(|| json!({}));

    match method {
        "initialize" => json!({"jsonrpc": "2.0", "id": id, "result": initialize_result()}),
        KIT_DECLARATION_RPC_METHOD => {
            json!({"jsonrpc": "2.0", "id": id, "result": kit_declaration_result()})
        }
        "lift" => json!({"jsonrpc": "2.0", "id": id, "result": lift(&params)}),
        "shutdown" => json!({"jsonrpc": "2.0", "id": id, "result": Value::Null}),
        other => json!({
            "jsonrpc": "2.0",
            "id": id,
            "error": {"code": -32601, "message": format!("METHOD_NOT_FOUND: {other}")},
        }),
    }
}

fn main() {
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let request: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(e) => {
                let resp = json!({
                    "jsonrpc": "2.0",
                    "id": Value::Null,
                    "error": {"code": -32700, "message": format!("PARSE_ERROR: {e}")},
                });
                let _ = writeln!(out, "{resp}");
                let _ = out.flush();
                continue;
            }
        };
        let is_shutdown = request.get("method").and_then(Value::as_str) == Some("shutdown");
        let response = dispatch(&request);
        let _ = writeln!(out, "{response}");
        let _ = out.flush();
        if is_shutdown {
            break;
        }
    }
}
