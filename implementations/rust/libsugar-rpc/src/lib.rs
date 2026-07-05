// SPDX-License-Identifier: MIT OR Apache-2.0
//
//! # libsugar-rpc
//!
//! JSON-RPC 2.0 / NDJSON-over-stdio server for Sugar's lift-plugin
//! protocol (`pep/1.7.0`). **Cleanroom implementation**: this crate
//! has zero `sugar-*` dependencies. The only external crates it
//! pulls in are [`blake3`] (for the BLAKE3-512 content-address hash)
//! and [`serde_json`] (for the on-wire JSON values). The JSON
//! Canonicalization Scheme (RFC 8785) used to canonicalize mementos
//! before hashing is implemented inline in this file; see [`encode_jcs`].
//!
//! ## Layering / responsibilities
//!
//! Adapter binaries (e.g. proptest, kani, creusot, rust-tests, ...)
//! depend on this crate and call [`run_server`] from `main`, passing
//! an implementation of [`AdapterLifter`]. **The adapter owns**:
//!
//! * source enumeration (which files / directories to walk),
//! * parsing (`syn`, `tree-sitter`, regex, whatever),
//! * conversion of its parsed results into canonical-JSON contract
//!   mementos of the shape:
//!
//!   ```json
//!   {
//!     "kind": "contract",
//!     "name": "<adapter-supplied-original-name>",
//!     "outBinding": "out",
//!     "inv":  <ir-json>,
//!     "pre":  <ir-json>,   // optional
//!     "post": <ir-json>    // optional
//!   }
//!   ```
//!
//! **The library owns**:
//!
//! * JSON-RPC 2.0 / NDJSON framing,
//! * the `initialize` / `lift` / `shutdown` method set,
//! * RFC-8785 JCS canonicalization,
//! * BLAKE3-512 content-addressed naming
//!   (`<original-name>#blake3-512:<128-hex>`),
//! * dedup by content-addressed name,
//! * the `kind: "ir-document"` response envelope.
//!
//! This split makes the library vendorable -- any future Sugar
//! library that wants the same JSON-RPC contract can depend on this
//! crate alone and still talk to the rest of the substrate, because
//! every byte that crosses the wire is hashable, byte-deterministic
//! JSON.
//!
//! ## Protocol surface
//!
//! * `initialize` -> [`initialize_result`] built from
//!   [`AdapterLifter::name`] / [`AdapterLifter::surface`].
//! * `lift` with `options.emit == "ir-document"` (the default) ->
//!   [`build_ir_document`] over the adapter's [`LiftResult`].
//! * `shutdown` -> `null` result; the read loop exits cleanly.
//!
//! Unknown methods produce JSON-RPC error `-32601`; malformed input
//! produces `-32700`; missing required parameters produce `-32602`;
//! any other failure produces `-32603`.

use std::collections::BTreeSet;
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

// ---------------------------------------------------------------------
// Public protocol constants
// ---------------------------------------------------------------------

/// Protocol-version token advertised in the `initialize` response, per
/// `protocol/specs/2026-04-30-lift-plugin-protocol.md` as renamed under
/// `pep/1.7.0`.
pub const PROTOCOL_VERSION: &str = "pep/1.7.0";

/// IR shape version the server emits in `initialize`.
pub const IR_VERSION: &str = "v1.1.0";

/// Plugin version reported in the `initialize` response. Adapters get
/// to advertise a name and surface; the wire version is owned by this
/// library so all adapters that depend on it report the same value.
pub const PLUGIN_VERSION: &str = "0.1.0";

/// String prefix used by the BLAKE3-512 self-identifying hash form.
/// The protocol cut is scorched earth: `blake3-512` is the only hash
/// function permitted, always 512 bits wide, no truncation.
pub const BLAKE3_512_PREFIX: &str = "blake3-512:";

// ---------------------------------------------------------------------
// AdapterLifter trait + result type
// ---------------------------------------------------------------------

/// The result of one `lift` call delegated to the adapter. The adapter
/// returns canonical-JSON mementos and diagnostics; the library does
/// the content-addressing, dedup, and envelope construction.
///
/// Each entry in `mementos` should be a JSON object roughly shaped like:
///
/// ```json
/// {
///   "kind": "contract",
///   "name": "<adapter-original-name>",
///   "outBinding": "out",
///   "inv":  { ... ir-json ... },
///   "pre":  { ... ir-json ... },   // optional
///   "post": { ... ir-json ... }    // optional
/// }
/// ```
///
/// Anything else in the object is preserved verbatim in the output IR
/// document but does *not* contribute to the content-address (only
/// `inv` / `pre` / `post` do). The library rewrites `name` to
/// `<original-name>#<content-cid>` on the way out.
///
/// `diagnostics` follow the protocol's free-form diagnostic shape
/// (e.g. `{"kind": "parse-error", "path": "...", "detail": "..."}`);
/// the library passes them through to the response untouched.
pub struct LiftResult {
    /// Contract mementos discovered by the adapter, before dedup.
    pub mementos: Vec<Value>,
    /// Diagnostics emitted during the lift, surfaced to the client.
    pub diagnostics: Vec<Value>,
}

/// A lift adapter. The adapter owns source enumeration, parsing, and
/// memento construction; the library owns the protocol mechanics.
pub trait AdapterLifter {
    /// Walk the supplied source paths under `workspace_root`, lift
    /// whatever this adapter understands, and return the
    /// canonical-JSON mementos plus diagnostics.
    ///
    /// `workspace_root` is the absolute path the JSON-RPC client
    /// supplied (no normalization by the library). `source_paths` are
    /// adapter-resolution-relative paths (typically POSIX-style and
    /// joined with `workspace_root`). The adapter is free to ignore
    /// either argument -- some adapters (e.g. environment-driven
    /// linters) may not need them.
    fn lift(&self, workspace_root: &Path, source_paths: &[String]) -> LiftResult;

    /// Human-readable authoring-surface name advertised in
    /// `initialize.result.capabilities.authoring_surfaces`. The client
    /// selects a plugin by matching `[authoring] surface = ...` from
    /// `.sugar/config.toml` against this string.
    fn surface(&self) -> &str;

    /// Plugin name advertised in `initialize.result.name`.
    fn name(&self) -> &str;
}

// ---------------------------------------------------------------------
// JSON-RPC server loop
// ---------------------------------------------------------------------

/// Run the JSON-RPC server on stdio. Reads one request per line from
/// stdin and writes one response per line to stdout. Returns
/// `Ok(())` when the loop exits cleanly (either `shutdown` was
/// received or stdin closed).
pub fn run_server<A: AdapterLifter>(adapter: A) -> io::Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    let _ = writeln!(
        io::stderr(),
        "{} listening on stdio (JSON-RPC 2.0, NDJSON)",
        adapter.name()
    );
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let (response, stop) = handle_line(&line, &adapter);
        let response_str = serde_json::to_string(&response).unwrap_or_else(|e| {
            json!({
                "jsonrpc": "2.0",
                "id": Value::Null,
                "error": { "code": -32603, "message": e.to_string() }
            })
            .to_string()
        });
        writeln!(stdout, "{}", response_str)?;
        stdout.flush()?;
        if stop {
            break;
        }
    }
    Ok(())
}

/// Parse one JSON-RPC request line, dispatch, and produce the JSON
/// response value plus a "should stop" flag (set by `shutdown`).
fn handle_line<A: AdapterLifter>(line: &str, adapter: &A) -> (Value, bool) {
    let req: Value = match serde_json::from_str(line) {
        Ok(v) => v,
        Err(e) => {
            return (
                error_response(Value::Null, -32700, format!("parse error: {}", e)),
                false,
            );
        }
    };
    let id = req.get("id").cloned().unwrap_or(Value::Null);
    let method = req.get("method").and_then(|m| m.as_str()).unwrap_or("");
    let params = req.get("params").cloned().unwrap_or(Value::Null);

    match method {
        "initialize" => (ok_response(id, initialize_result(adapter)), false),
        "lift" => match lift(&params, adapter) {
            Ok(v) => (ok_response(id, v), false),
            Err(LiftError::InvalidParams(msg)) => (error_response(id, -32602, msg), false),
            Err(LiftError::Internal(msg)) => (error_response(id, -32603, msg), false),
        },
        "shutdown" => (ok_response(id, Value::Null), true),
        "" => (
            error_response(id, -32600, "missing `method` field".into()),
            false,
        ),
        other => (
            error_response(id, -32601, format!("unknown method: {}", other)),
            false,
        ),
    }
}

/// Build the `initialize` result for a given adapter. Pulled out so
/// it can be unit-tested without spinning up the read loop.
pub fn initialize_result<A: AdapterLifter>(adapter: &A) -> Value {
    json!({
        "name": adapter.name(),
        "version": PLUGIN_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "capabilities": {
            "authoring_surfaces": [adapter.surface()],
            "ir_version": IR_VERSION,
            "emits_signed_mementos": false,
        }
    })
}

/// Internal classification of failures during `lift`.
enum LiftError {
    InvalidParams(String),
    Internal(String),
}

/// Handle a single `lift` request. Reads `workspace_root` and
/// `source_paths`, delegates the actual lifting to the adapter, then
/// content-addresses + dedups the returned mementos. Only
/// `options.emit == "ir-document"` (the default) is supported.
fn lift<A: AdapterLifter>(params: &Value, adapter: &A) -> Result<Value, LiftError> {
    let workspace_root = params
        .get("workspace_root")
        .and_then(Value::as_str)
        .ok_or_else(|| LiftError::InvalidParams("missing `workspace_root`".into()))?;
    let source_paths_raw = params
        .get("source_paths")
        .and_then(Value::as_array)
        .ok_or_else(|| LiftError::InvalidParams("missing `source_paths`".into()))?;
    let source_paths: Vec<String> = source_paths_raw
        .iter()
        .filter_map(|v| v.as_str().map(str::to_string))
        .collect();

    let options = params.get("options").cloned().unwrap_or(Value::Null);
    let emit = options
        .get("emit")
        .and_then(Value::as_str)
        .unwrap_or("ir-document");
    if emit != "ir-document" {
        return Err(LiftError::Internal(format!(
            "emit mode `{}` not implemented (only `ir-document` is supported in this version)",
            emit
        )));
    }

    let root = PathBuf::from(workspace_root);
    Ok(build_ir_document(&root, &source_paths, adapter))
}

/// Invoke the adapter, content-address each returned memento, dedup
/// by content-addressed name, and assemble the `"ir-document"`
/// response value (including the `diagnostics` array).
///
/// Exposed so callers can drive a `lift` synchronously in tests
/// without going through the JSON-RPC framing layer.
pub fn build_ir_document<A: AdapterLifter>(
    workspace_root: &Path,
    source_paths: &[String],
    adapter: &A,
) -> Value {
    let LiftResult {
        mementos,
        diagnostics,
    } = adapter.lift(workspace_root, source_paths);

    let mut ir_entries: Vec<Value> = Vec::new();
    let mut seen_names: BTreeSet<String> = BTreeSet::new();
    for mut memento in mementos {
        let original_name = memento
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let addressed_name = content_addressed_name(&original_name, &memento);
        if !seen_names.insert(addressed_name.clone()) {
            continue;
        }
        if let Value::Object(map) = &mut memento {
            map.insert("name".to_string(), Value::String(addressed_name));
        }
        ir_entries.push(memento);
    }

    json!({
        "kind": "ir-document",
        "ir": ir_entries,
        "diagnostics": diagnostics,
    })
}

// ---------------------------------------------------------------------
// Content-addressed naming
// ---------------------------------------------------------------------

/// Compute the content-addressed name for a memento:
///
/// 1. JCS-encode each present slot (`inv`, `pre`, `post`).
/// 2. BLAKE3-512 each JCS-encoded slot to its self-identifying CID
///    string. Absent slots contribute the empty string.
/// 3. Concatenate `"<inv_cid>|<pre_cid>|<post_cid>"` and hash the
///    bytes once more to produce a single content CID.
/// 4. Return `format!("{}#{}", original_name, content_cid)`.
///
/// "Absent" means either the key is missing OR its value is
/// `Value::Null` -- the library treats explicit-null and omitted
/// identically, matching the existing IR-emission contract that drops
/// empty slots rather than serializing them as `null`.
fn content_addressed_name(original_name: &str, memento: &Value) -> String {
    let inv_cid = slot_cid(memento, "inv");
    let pre_cid = slot_cid(memento, "pre");
    let post_cid = slot_cid(memento, "post");
    let composed = format!("{}|{}|{}", inv_cid, pre_cid, post_cid);
    let content_cid = blake3_512_of(composed.as_bytes());
    format!("{}#{}", original_name, content_cid)
}

/// JCS-encode + BLAKE3-512 a single slot, returning the empty string
/// for slots that are missing or explicitly null.
fn slot_cid(memento: &Value, key: &str) -> String {
    match memento.get(key) {
        Some(v) if !v.is_null() => blake3_512_of(encode_jcs(v).as_bytes()),
        _ => String::new(),
    }
}

// ---------------------------------------------------------------------
// BLAKE3-512 helper (inline; no sugar-* dep)
// ---------------------------------------------------------------------

/// Hash arbitrary bytes into the self-identifying BLAKE3-512 string
/// form `"blake3-512:" + lowercase-hex(64-byte-digest)`. The
/// 512-bit width is non-negotiable in protocol v1.1.0; we use the
/// `blake3` crate's XOF to extract exactly 64 bytes.
pub fn blake3_512_of(bytes: &[u8]) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(bytes);
    let mut out = [0u8; 64];
    hasher.finalize_xof().fill(&mut out);
    let mut s = String::with_capacity(BLAKE3_512_PREFIX.len() + 128);
    s.push_str(BLAKE3_512_PREFIX);
    write_hex_lower(&out, &mut s);
    s
}

/// Append the lowercase-hex encoding of `bytes` to `out`. Inlined to
/// avoid a `hex` crate dependency for so trivial a routine.
fn write_hex_lower(bytes: &[u8], out: &mut String) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    out.reserve(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0F) as usize] as char);
    }
}

// ---------------------------------------------------------------------
// JCS encoder (RFC 8785), inlined for `serde_json::Value`
// ---------------------------------------------------------------------

/// JCS-encode (RFC 8785, "JSON Canonicalization Scheme") a
/// `serde_json::Value` to a deterministic string. The output is the
/// exact byte sequence that should be hashed for content-address
/// purposes.
///
/// Rules:
///
/// * Object keys sorted by Unicode code-point order. We explicitly
///   collect-and-sort here because the workspace builds `serde_json`
///   with the `preserve_order` feature, so the on-`Map` iteration
///   order is insertion order, not sorted order.
/// * Numbers: integers (`i64` or `u64`) are written as their decimal
///   form via `Number::to_string()`, which matches the bare decimal
///   form ECMA-262 ToString applied to a finite integer (no leading
///   `+`, no fractional `.0`). Floats are not expected in the
///   canonical IR; if one is encountered we fall back to
///   `Number::to_string()` and document this as best-effort -- the
///   kit/mint pipeline does not produce floats.
/// * Strings: UTF-8 verbatim. Escape `"` and `\\`. Escape
///   U+0000..U+001F as `\u00XX` with lowercase hex. RFC 8785 also
///   permits the named short escapes (`\n`, `\t`, ...) but the C++
///   peer chose `\u00XX` for determinism; we match.
/// * `true` / `false` / `null` literal.
/// * No whitespace.
pub fn encode_jcs(v: &Value) -> String {
    let mut out = String::new();
    encode_value(v, &mut out);
    out
}

fn encode_value(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => {
            // `serde_json::Number::to_string()` produces the same bytes
            // as `i64::to_string()` / `u64::to_string()` for integral
            // values, and `f64::to_string()` for floats. Integer cases
            // are what the protocol exercises.
            out.push_str(&n.to_string());
        }
        Value::String(s) => encode_string(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                encode_value(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            // serde_json builds with `preserve_order` here, so we must
            // explicitly sort keys -- iterating the map directly would
            // yield insertion order, breaking canonicalization.
            let mut sorted: Vec<(&String, &Value)> = map.iter().collect();
            sorted.sort_by(|a, b| a.0.cmp(b.0));
            out.push('{');
            for (i, (k, val)) in sorted.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                encode_string(k, out);
                out.push(':');
                encode_value(val, out);
            }
            out.push('}');
        }
    }
}

fn encode_string(s: &str, out: &mut String) {
    out.push('"');
    // Iterate over Unicode scalar values. Non-ASCII characters emit
    // verbatim; pushing a `char` into a Rust `String` re-encodes it as
    // the same UTF-8 bytes the input carried, so cross-language hash
    // agreement is preserved. (Byte-iteration would corrupt
    // U+0080..U+10FFFF by treating continuation bytes as Latin-1.)
    for c in s.chars() {
        if c == '"' {
            out.push_str("\\\"");
        } else if c == '\\' {
            out.push_str("\\\\");
        } else if (c as u32) < 0x20 {
            const HEX: &[u8; 16] = b"0123456789abcdef";
            let n = c as u32;
            out.push_str("\\u00");
            out.push(HEX[((n >> 4) & 0xF) as usize] as char);
            out.push(HEX[(n & 0xF) as usize] as char);
        } else {
            out.push(c);
        }
    }
    out.push('"');
}

// ---------------------------------------------------------------------
// JSON-RPC response helpers
// ---------------------------------------------------------------------

/// Build a JSON-RPC 2.0 success response.
fn ok_response(id: Value, result: Value) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": result,
    })
}

/// Build a JSON-RPC 2.0 error response.
fn error_response(id: Value, code: i64, message: String) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": { "code": code, "message": message },
    })
}

// ---------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ----- Test adapters -----

    /// Adapter that returns no mementos and no diagnostics.
    struct EmptyAdapter;
    impl AdapterLifter for EmptyAdapter {
        fn lift(&self, _root: &Path, _src: &[String]) -> LiftResult {
            LiftResult {
                mementos: Vec::new(),
                diagnostics: Vec::new(),
            }
        }
        fn surface(&self) -> &str {
            "empty-surface"
        }
        fn name(&self) -> &str {
            "empty-adapter"
        }
    }

    /// Adapter that returns a fixed list of mementos plus optional
    /// diagnostics. Used to exercise the library's content-addressing,
    /// dedup, and pass-through behavior without touching the
    /// filesystem.
    struct FixedAdapter {
        mementos: Vec<Value>,
        diagnostics: Vec<Value>,
    }
    impl AdapterLifter for FixedAdapter {
        fn lift(&self, _root: &Path, _src: &[String]) -> LiftResult {
            LiftResult {
                mementos: self.mementos.clone(),
                diagnostics: self.diagnostics.clone(),
            }
        }
        fn surface(&self) -> &str {
            "fixed-surface"
        }
        fn name(&self) -> &str {
            "fixed-adapter"
        }
    }

    // ----- Protocol surface -----

    #[test]
    fn initialize_advertises_adapter_name_and_surface() {
        let r = initialize_result(&EmptyAdapter);
        assert_eq!(r["name"], "empty-adapter");
        assert_eq!(r["protocol_version"], PROTOCOL_VERSION);
        assert_eq!(r["capabilities"]["authoring_surfaces"][0], "empty-surface");
        assert_eq!(r["capabilities"]["ir_version"], IR_VERSION);
        assert_eq!(r["capabilities"]["emits_signed_mementos"], false);
    }

    #[test]
    fn unknown_method_yields_minus_32601() {
        let line = r#"{"jsonrpc":"2.0","id":1,"method":"who-knows"}"#;
        let (resp, stop) = handle_line(line, &EmptyAdapter);
        assert!(!stop);
        assert_eq!(resp["error"]["code"], -32601);
    }

    #[test]
    fn shutdown_returns_null_and_stops_loop() {
        let line = r#"{"jsonrpc":"2.0","id":7,"method":"shutdown"}"#;
        let (resp, stop) = handle_line(line, &EmptyAdapter);
        assert!(stop);
        assert_eq!(resp["result"], Value::Null);
        assert_eq!(resp["id"], 7);
    }

    #[test]
    fn parse_error_id_is_null_per_jsonrpc_spec() {
        let (resp, stop) = handle_line("{not-json", &EmptyAdapter);
        assert!(!stop);
        assert_eq!(resp["error"]["code"], -32700);
        assert_eq!(resp["id"], Value::Null);
    }

    #[test]
    fn lift_missing_workspace_root_is_invalid_params() {
        let line = r#"{"jsonrpc":"2.0","id":2,"method":"lift","params":{"source_paths":["src"]}}"#;
        let (resp, _) = handle_line(line, &EmptyAdapter);
        assert_eq!(resp["error"]["code"], -32602);
    }

    #[test]
    fn lift_unknown_emit_mode_is_internal_error() {
        let line = r#"{"jsonrpc":"2.0","id":3,"method":"lift","params":{
            "workspace_root":"/tmp","source_paths":["src"],"options":{"emit":"proof-envelope"}
        }}"#;
        let (resp, _) = handle_line(line, &EmptyAdapter);
        assert_eq!(resp["error"]["code"], -32603);
    }

    #[test]
    fn adapter_diagnostics_pass_through_to_response() {
        // The old `missing_source_path_emits_diagnostic_not_error`
        // test exercised library-side file walking; that responsibility
        // is now the adapter's. Today we verify the library faithfully
        // surfaces whatever diagnostics the adapter emits.
        let diag = json!({
            "kind": "source-path-missing",
            "path": "src",
            "detail": "src does not exist under workspace_root",
        });
        let adapter = FixedAdapter {
            mementos: Vec::new(),
            diagnostics: vec![diag.clone()],
        };
        let doc = build_ir_document(Path::new("/tmp"), &["src".to_string()], &adapter);
        assert_eq!(doc["kind"], "ir-document");
        assert!(doc["ir"].as_array().unwrap().is_empty());
        let diags = doc["diagnostics"].as_array().unwrap();
        assert_eq!(diags.len(), 1);
        assert_eq!(diags[0], diag);
    }

    #[test]
    fn empty_source_paths_yields_empty_ir_no_diagnostics() {
        let doc = build_ir_document(Path::new("/tmp"), &[], &EmptyAdapter);
        assert_eq!(doc["kind"], "ir-document");
        assert!(doc["ir"].as_array().unwrap().is_empty());
        assert!(doc["diagnostics"].as_array().unwrap().is_empty());
    }

    // ----- New tests: dedup, content-addressed name format, JCS -----

    #[test]
    fn dedup_collapses_identical_mementos_to_one_entry() {
        // Same original name + same `inv` slot -> same content CID
        // -> one entry in the ir-document. The library must drop
        // duplicates, not pass them both through.
        let m = json!({
            "kind": "contract",
            "name": "foo",
            "outBinding": "out",
            "inv": {"kind": "atomic", "name": "=", "args": [{"var": "out"}, {"int": 1}]},
        });
        let adapter = FixedAdapter {
            mementos: vec![m.clone(), m],
            diagnostics: Vec::new(),
        };
        let doc = build_ir_document(Path::new("/tmp"), &[], &adapter);
        let ir = doc["ir"].as_array().unwrap();
        assert_eq!(ir.len(), 1, "dedup must collapse identical mementos");
    }

    #[test]
    fn distinct_inv_slots_yield_distinct_content_addressed_names() {
        // Same original name, different `inv` slot -> different
        // content CIDs -> two entries (no false collapse).
        let m1 = json!({
            "kind": "contract",
            "name": "foo",
            "outBinding": "out",
            "inv": {"kind": "atomic", "name": "=", "args": [{"var": "out"}, {"int": 1}]},
        });
        let m2 = json!({
            "kind": "contract",
            "name": "foo",
            "outBinding": "out",
            "inv": {"kind": "atomic", "name": "=", "args": [{"var": "out"}, {"int": 2}]},
        });
        let adapter = FixedAdapter {
            mementos: vec![m1, m2],
            diagnostics: Vec::new(),
        };
        let doc = build_ir_document(Path::new("/tmp"), &[], &adapter);
        let ir = doc["ir"].as_array().unwrap();
        assert_eq!(ir.len(), 2);
        let n0 = ir[0]["name"].as_str().unwrap();
        let n1 = ir[1]["name"].as_str().unwrap();
        assert_ne!(n0, n1);
        assert!(n0.starts_with("foo#blake3-512:"));
        assert!(n1.starts_with("foo#blake3-512:"));
    }

    #[test]
    fn content_addressed_name_format_is_original_hash_blake3_512_128hex() {
        let m = json!({
            "kind": "contract",
            "name": "my-contract",
            "outBinding": "out",
            "inv": {"kind": "atomic", "name": "=", "args": [{"var": "out"}, {"int": 1}]},
        });
        let adapter = FixedAdapter {
            mementos: vec![m],
            diagnostics: Vec::new(),
        };
        let doc = build_ir_document(Path::new("/tmp"), &[], &adapter);
        let name = doc["ir"][0]["name"].as_str().unwrap();
        // Shape: <original>#blake3-512:<128 lowercase hex chars>
        let (orig, cid) = name.split_once('#').expect("name must contain '#'");
        assert_eq!(orig, "my-contract");
        assert!(
            cid.starts_with("blake3-512:"),
            "expected blake3-512: prefix, got {}",
            cid
        );
        let hex = &cid["blake3-512:".len()..];
        assert_eq!(hex.len(), 128, "must be 128 lowercase hex chars");
        assert!(
            hex.chars().all(|c| matches!(c, '0'..='9' | 'a'..='f')),
            "must be lowercase hex"
        );
    }

    #[test]
    fn absent_and_explicit_null_slots_are_treated_identically() {
        // Whether a slot is missing or explicitly null, the resulting
        // content-addressed name must be the same. This is the
        // "absent == null" rule called out in the module docs.
        let m_missing = json!({
            "kind": "contract",
            "name": "x",
            "outBinding": "out",
            "inv": {"kind": "true"},
            // no pre, no post
        });
        let m_null = json!({
            "kind": "contract",
            "name": "x",
            "outBinding": "out",
            "inv": {"kind": "true"},
            "pre": null,
            "post": null,
        });
        let name_missing = content_addressed_name("x", &m_missing);
        let name_null = content_addressed_name("x", &m_null);
        assert_eq!(name_missing, name_null);
    }

    // ----- JCS encoder: byte-equal to reference impl on representative inputs -----
    //
    // The reference is in `sugar-canonicalizer/src/jcs.rs`. We
    // avoid a dev-dep on it (acceptance criterion 1: external crates
    // only) and instead hardcode the expected byte sequences that
    // the reference produces for these same inputs. Each expected
    // string below has been verified byte-equal against
    // `sugar_canonicalizer::encode_jcs` on the matching input.

    #[test]
    fn jcs_primitives() {
        assert_eq!(encode_jcs(&Value::Null), "null");
        assert_eq!(encode_jcs(&Value::Bool(true)), "true");
        assert_eq!(encode_jcs(&Value::Bool(false)), "false");
        assert_eq!(encode_jcs(&json!(0)), "0");
        assert_eq!(encode_jcs(&json!(42)), "42");
        assert_eq!(encode_jcs(&json!(-17)), "-17");
        assert_eq!(encode_jcs(&json!("hello")), r#""hello""#);
    }

    #[test]
    fn jcs_empty_collections() {
        assert_eq!(encode_jcs(&json!({})), "{}");
        assert_eq!(encode_jcs(&json!([])), "[]");
    }

    #[test]
    fn jcs_object_keys_sorted_by_codepoint() {
        // Out-of-order insertion: serde_json (preserve_order) would
        // yield insertion order, but JCS demands sorted-by-codepoint.
        let v = json!({"b": 1, "a": "x"});
        assert_eq!(encode_jcs(&v), r#"{"a":"x","b":1}"#);
    }

    #[test]
    fn jcs_nested_array_and_object() {
        let v = json!({"xs": [1, 2]});
        assert_eq!(encode_jcs(&v), r#"{"xs":[1,2]}"#);
    }

    #[test]
    fn jcs_string_escapes_quote_and_backslash() {
        let v = json!(r#"a"b\c"#);
        assert_eq!(encode_jcs(&v), r#""a\"b\\c""#);
    }

    #[test]
    fn jcs_string_escapes_control_chars_as_u00xx_lowercase() {
        // Control characters U+0001 and U+001F must encode as the
        // literal 6-byte sequences `` and `` (lowercase
        // hex), wrapped in quotes. The expected bytes are spelled
        // out as a byte literal to make the assertion unambiguous
        // (Rust string literals would re-interpret `\u{...}`).
        let v = json!("\u{0001}\u{001f}");
        let expected_bytes: &[u8] = b"\"\\u0001\\u001f\"";
        assert_eq!(encode_jcs(&v).as_bytes(), expected_bytes);
    }

    #[test]
    fn jcs_unicode_emits_verbatim_utf8() {
        // Atomic-predicate names use these (>=, <=, !=). The encoded
        // form is the input wrapped in quotes; the bytes inside the
        // quotes are the same UTF-8 bytes the input carried.
        for sym in ["\u{2265}", "\u{2264}", "\u{2260}"] {
            let encoded = encode_jcs(&json!(sym));
            assert_eq!(encoded, format!("\"{}\"", sym));
            let inner = &encoded[1..encoded.len() - 1];
            assert_eq!(inner.as_bytes(), sym.as_bytes());
        }
    }

    #[test]
    fn jcs_unicode_in_object_key_and_value_byte_equal_to_cpp_peer() {
        // Used as an atomic name in IR-JSON.
        let v = json!({"name": "\u{2265}"});
        let encoded = encode_jcs(&v);
        assert_eq!(encoded, "{\"name\":\"\u{2265}\"}");
        // The byte sequence below is what the C++ peer (and the
        // sugar-canonicalizer Rust peer) produce for this input.
        assert_eq!(encoded.as_bytes(), b"{\"name\":\"\xe2\x89\xa5\"}");
    }

    #[test]
    fn jcs_representative_ir_contract_byte_equal() {
        // Representative ir-contract shape. Expected output was
        // computed by `sugar_canonicalizer::encode_jcs` on the
        // same input value and hardcoded here. If the inline encoder
        // drifts byte-for-byte from the reference, this test fails.
        let v = json!({
            "kind": "contract",
            "name": "foo",
            "outBinding": "out",
            "inv": {
                "kind": "atomic",
                "name": "\u{2265}",
                "args": [{"var": "out"}, {"int": 0}],
            },
        });
        // Keys sorted at every level: outer = inv, kind, name, outBinding
        // inv inner = args, kind, name. args entries are objects with one
        // key each so sorting is trivial.
        let expected = concat!(
            r#"{"inv":{"args":[{"var":"out"},{"int":0}],"#,
            r#""kind":"atomic","name":""#,
            "\u{2265}",
            r#""},"#,
            r#""kind":"contract","name":"foo","outBinding":"out"}"#,
        );
        assert_eq!(encode_jcs(&v), expected);
    }

    // ----- BLAKE3-512 helper -----

    #[test]
    fn blake3_512_format_is_prefixed_128hex() {
        let h = blake3_512_of(b"");
        assert!(h.starts_with(BLAKE3_512_PREFIX));
        assert_eq!(h.len(), BLAKE3_512_PREFIX.len() + 128);
        let hex = &h[BLAKE3_512_PREFIX.len()..];
        assert!(hex.chars().all(|c| matches!(c, '0'..='9' | 'a'..='f')));
    }

    #[test]
    fn blake3_512_is_deterministic_and_input_sensitive() {
        assert_eq!(blake3_512_of(b"hello"), blake3_512_of(b"hello"));
        assert_ne!(blake3_512_of(b"hello"), blake3_512_of(b"world"));
    }
}
