// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-lsp-rust: NDJSON LSP plugin for Rust.
//
// Speaks the per-language plugin protocol used by every kit's LSP plugin:
//
//   {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
//   {"jsonrpc":"2.0","id":2,"method":"parse","params":{"path":"...","source":"..."}}
//   {"jsonrpc":"2.0","id":3,"method":"analyzeDocument","params":{"file":"...","text":"..."}}
//   {"jsonrpc":"2.0","id":4,"method":"shutdown"}
//
// The `parse` handler parses the source with `syn`, runs all registered
// lift adapters (proptest, contracts, kani, prusti, rust-tests, etc.),
// and returns the lifted ContractDecls as a JSON array in the shape:
//
//   {"declarations": [...], "warnings": [...]}
//
// Used by tooling that consumes lifter output directly (e.g. snapshot
// pipelines, CI checks), and spawned as the per-kit plugin by `sugar-lsp`'s
// per-plugin subprocess mode.
//
// This binary previously also had a daemon-client mode (`--daemon-socket
// <path>`) that forwarded `parse` requests to the `sugar-linkerd` daemon
// (LSP+linker step 3a, #137). That daemon and its protocol are retired
// (#3844 flipped the real editor path to `sugar-lsp --in-process`; the
// daemon-3-delete cut removed sugar-linkerd itself), and nothing ever
// invoked this plugin's daemon-client mode outside its own test suite, so
// it is retired along with it. Default mode is the only mode.
//
// Usage:
//   sugar-lsp-rust

use std::io::{BufRead, Write};

use sugar_lsp_rust::forward_propagator::ForwardPropagator;

const KIT_ID: &str = "rust";
const SHARED_LSP_PROTOCOL_VERSION: &str = "sugar-lsp-shared/1";

fn main() {
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue,
        };
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        let req: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(e) => {
                let resp = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": null,
                    "error": {"code": -32700, "message": format!("parse error: {e}")}
                });
                let _ = writeln!(stdout, "{resp}");
                let _ = stdout.flush();
                continue;
            }
        };

        let id = req.get("id").cloned().unwrap_or(serde_json::Value::Null);
        let method = req.get("method").and_then(|v| v.as_str()).unwrap_or("");

        match method {
            "initialize" => {
                let resp = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "name": "sugar-lsp-rust",
                        "version": "0.1.0",
                        "protocol_version": SHARED_LSP_PROTOCOL_VERSION,
                        "kit_id": KIT_ID,
                        "capabilities": {
                            "source_surfaces": ["rust-source"],
                            "entry_kinds": ["bind-lift-entry"],
                            "diagnostic_codes": [
                                "sugar.lsp.parse_error",
                                "sugar.lsp.implication_failed"
                            ],
                            "status_kinds": ["lift", "emit", "check", "prove"]
                        }
                    }
                });
                let _ = writeln!(stdout, "{resp}");
                let _ = stdout.flush();
            }
            "analyzeDocument" => {
                let params = req.get("params").cloned().unwrap_or_default();
                let resp = handle_analyze_document(id.clone(), params);
                let _ = writeln!(stdout, "{resp}");
                let _ = stdout.flush();
            }
            "parse" => {
                let params = req.get("params").cloned().unwrap_or_default();
                let path = params
                    .get("path")
                    .and_then(|v| v.as_str())
                    .unwrap_or("source.rs");
                let source = params.get("source").and_then(|v| v.as_str()).unwrap_or("");

                let resp = handle_parse(id.clone(), source, path);

                let _ = writeln!(stdout, "{resp}");
                let _ = stdout.flush();
            }
            "shutdown" => {
                let resp = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": null
                });
                let _ = writeln!(stdout, "{resp}");
                let _ = stdout.flush();
                std::process::exit(0);
            }
            _ => {
                let resp = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "error": {
                        "code": -32601,
                        "message": format!("unknown method: {method}")
                    }
                });
                let _ = writeln!(stdout, "{resp}");
                let _ = stdout.flush();
            }
        }
    }
}

fn handle_analyze_document(id: serde_json::Value, params: serde_json::Value) -> serde_json::Value {
    let file = params
        .get("file")
        .or_else(|| params.get("path"))
        .and_then(|v| v.as_str())
        .unwrap_or("source.rs");
    let uri = params
        .get("uri")
        .and_then(|v| v.as_str())
        .map(str::to_owned)
        .unwrap_or_else(|| format!("file://{file}"));
    let source = params
        .get("text")
        .or_else(|| params.get("source"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    let parse_resp = handle_parse(serde_json::Value::Null, source, file);
    let result = match parse_resp.get("result") {
        Some(result) => result,
        None => {
            let message = parse_resp
                .get("error")
                .and_then(|err| err.get("message"))
                .and_then(|message| message.as_str())
                .unwrap_or("rust source parse failed");
            return analyze_document_response(
                id,
                &uri,
                file,
                source,
                Vec::new(),
                vec![parse_error_diagnostic(message)],
                Vec::new(),
            );
        }
    };

    let entries = result
        .get("declarations")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
        .cloned()
        .map(|entry| {
            serde_json::json!({
                "kind": "bind-lift-entry",
                "entry": entry,
                "range": whole_document_range(source)
            })
        })
        .collect();

    let diagnostics = result
        .get("diagnostics")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
        .map(shared_diagnostic_from_lsp_diagnostic)
        .collect();

    analyze_document_response(id, &uri, file, source, entries, diagnostics, Vec::new())
}

fn analyze_document_response(
    id: serde_json::Value,
    uri: &str,
    file: &str,
    source: &str,
    entries: Vec<serde_json::Value>,
    diagnostics: Vec<serde_json::Value>,
    statuses: Vec<serde_json::Value>,
) -> serde_json::Value {
    serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": {
            "kind": "lsp-document-analysis",
            "schema_version": "1",
            "kit_id": KIT_ID,
            "uri": uri,
            "file": file,
            "document_cid": blake3_512_cid(source.as_bytes()),
            "entries": entries,
            "diagnostics": diagnostics,
            "statuses": statuses,
            "project": null
        }
    })
}

fn parse_error_diagnostic(message: &str) -> serde_json::Value {
    serde_json::json!({
        "code": "sugar.lsp.parse_error",
        "message": message,
        "severity": "error",
        "range": first_byte_range(),
        "producer": "kit",
        "kit_id": KIT_ID,
    })
}

fn shared_diagnostic_from_lsp_diagnostic(diagnostic: &serde_json::Value) -> serde_json::Value {
    let code = diagnostic
        .get("data")
        .and_then(|data| data.get("kind"))
        .and_then(|kind| kind.as_str())
        .or_else(|| diagnostic.get("code").and_then(|code| code.as_str()))
        .unwrap_or("sugar.lsp.lift_gap");
    let message = diagnostic
        .get("message")
        .and_then(|message| message.as_str())
        .unwrap_or("Sugar diagnostic");
    let severity = diagnostic
        .get("severity")
        .and_then(|severity| severity.as_u64())
        .map(shared_severity)
        .unwrap_or("information");
    let range = diagnostic
        .get("range")
        .map(lsp_range_to_source_range)
        .unwrap_or_else(first_byte_range);

    let mut shared = serde_json::json!({
        "code": code,
        "message": message,
        "severity": severity,
        "range": range,
        "producer": "forward-propagation",
        "kit_id": KIT_ID,
    });
    if let Some(data) = diagnostic.get("data") {
        shared["data"] = data.clone();
    }
    shared
}

fn shared_severity(severity: u64) -> &'static str {
    match severity {
        1 => "error",
        2 => "warning",
        3 => "information",
        4 => "hint",
        _ => "information",
    }
}

fn lsp_range_to_source_range(range: &serde_json::Value) -> serde_json::Value {
    let start = range.get("start").unwrap_or(&serde_json::Value::Null);
    let end = range.get("end").unwrap_or(&serde_json::Value::Null);
    let start_line = start.get("line").and_then(|v| v.as_u64()).unwrap_or(0) + 1;
    let start_col = start.get("character").and_then(|v| v.as_u64()).unwrap_or(0);
    let end_line = end.get("line").and_then(|v| v.as_u64()).unwrap_or(0) + 1;
    let end_col = end
        .get("character")
        .and_then(|v| v.as_u64())
        .unwrap_or(start_col);
    serde_json::json!({
        "start_line": start_line,
        "start_col": start_col,
        "end_line": end_line,
        "end_col": end_col
    })
}

fn whole_document_range(source: &str) -> serde_json::Value {
    let mut line = 1u64;
    let mut col = 0u64;
    for ch in source.chars() {
        if ch == '\n' {
            line += 1;
            col = 0;
        } else {
            col += 1;
        }
    }
    serde_json::json!({
        "start_line": 1,
        "start_col": 0,
        "end_line": line,
        "end_col": col
    })
}

fn first_byte_range() -> serde_json::Value {
    serde_json::json!({
        "start_line": 1,
        "start_col": 0,
        "end_line": 1,
        "end_col": 0
    })
}

fn blake3_512_cid(bytes: &[u8]) -> String {
    use std::fmt::Write as _;

    let mut hasher = blake3::Hasher::new();
    hasher.update(bytes);
    let mut output = [0u8; 64];
    hasher.finalize_xof().fill(&mut output);

    let mut cid = String::from("blake3-512:");
    for byte in output {
        write!(&mut cid, "{byte:02x}").expect("write to string");
    }
    cid
}

/// Default mode: parse Rust `source` with syn, run the lift adapters, and
/// return a JSON-RPC result object containing `declarations` and `warnings`.
fn handle_parse(id: serde_json::Value, source: &str, path: &str) -> serde_json::Value {
    let file = match syn::parse_str::<syn::File>(source) {
        Ok(f) => f,
        Err(e) => {
            return serde_json::json!({
                "jsonrpc": "2.0",
                "id": id,
                "error": {
                    "code": -32603,
                    "message": format!("syn parse error: {e}")
                }
            });
        }
    };

    // The syn parse above is a fast in-process pre-check that yields a
    // precise editor error. `file` is otherwise unused now: contract
    // lifting goes OVER RPC (THE SEVER) instead of the old static
    // the static contracts-adapter lift_file.
    let _ = file;

    let mut warnings: Vec<serde_json::Value> = Vec::new();

    // THE SEVER: dispatch the rust-contracts lift kit over RPC instead of
    // statically linking `lift_file`. The editor hands us in-memory
    // `source`; mirror linkerd's temp-dir pattern (the established way to
    // feed in-memory source to the disk-reading lifter) — write the source
    // to a fresh temp file, invoke the kit, and forward the returned
    // ir-document `ir` array verbatim as `declarations` (it is already the
    // marshalled `kind:"contract"` shape the old static path produced).
    let decls_value: serde_json::Value = match rpc_lift_source(source, path) {
        Ok((ir, gaps)) => {
            for gap in gaps {
                warnings.push(gap);
            }
            ir
        }
        Err(message) => {
            warnings.push(serde_json::json!({
                "adapter": "contracts",
                "path": path,
                "reason": format!("rpc lift failed: {message}")
            }));
            serde_json::Value::Array(vec![])
        }
    };

    let floor_stmts = ForwardPropagator::lower_floor_source(source);
    let diagnostics: Vec<serde_json::Value> = ForwardPropagator::floor_v1_seed_index()
        .emit_diagnostics(&floor_stmts)
        .into_iter()
        .map(|diagnostic| diagnostic.to_lsp_json())
        .collect();

    serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": {
            "declarations": decls_value,
            "warnings": warnings,
            "diagnostics": diagnostics
        }
    })
}

/// THE SEVER: lift `source`'s `#[requires]`/`#[ensures]` contracts by
/// spawning the `contracts_rpc` kit (via `sugar-lift-rpc-client`),
/// instead of statically calling the static contracts-adapter lift_file.
///
/// The editor supplies in-memory source. The kit reads from disk, so we
/// write the source to a fresh temp file under a temp workspace (mirroring
/// `sugar-linkerd::lift_rust_source`), invoke the kit against that one
/// file, and return `(ir_array, lift_gap_warnings)`. The `ir` array is the
/// marshalled `kind:"contract"` shape the static path produced verbatim.
fn rpc_lift_source(
    source: &str,
    path: &str,
) -> Result<(serde_json::Value, Vec<serde_json::Value>), String> {
    let file_name = std::path::Path::new(path)
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "lifted.rs".to_string());

    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let tmp_dir = std::env::temp_dir().join(format!(
        "sugar-lsp-rust-lift-{}-{nanos}",
        std::process::id()
    ));
    std::fs::create_dir_all(&tmp_dir).map_err(|e| format!("create temp dir: {e}"))?;
    let tmp_file = tmp_dir.join(&file_name);
    std::fs::write(&tmp_file, source).map_err(|e| format!("write temp file: {e}"))?;

    let result = sugar_lift_rpc_client::invoke_lift(&tmp_dir, &[file_name.clone()])
        .map_err(|e| e.to_string());
    let _ = std::fs::remove_dir_all(&tmp_dir);
    let doc = result?;

    let ir = doc
        .get("ir")
        .cloned()
        .unwrap_or_else(|| serde_json::Value::Array(vec![]));

    // Carry lift-gap diagnostics through as `contracts` warnings (the kit
    // reports parse/read failures and untranslatable predicates here).
    let mut gaps: Vec<serde_json::Value> = Vec::new();
    if let Some(arr) = doc.get("diagnostics").and_then(|d| d.as_array()) {
        for d in arr {
            gaps.push(serde_json::json!({
                "adapter": "contracts",
                "path": d.get("path").and_then(|v| v.as_str()).unwrap_or(path),
                "item": d.get("item").and_then(|v| v.as_str()).unwrap_or(""),
                "reason": d.get("reason").and_then(|v| v.as_str()).unwrap_or("lift-gap"),
            }));
        }
    }

    Ok((ir, gaps))
}
