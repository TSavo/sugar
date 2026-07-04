// SPDX-License-Identifier: MIT OR Apache-2.0
//
// §3 File interface + §4 JSON-RPC interface.
//
// load_plugin_from_file  — §3: read JSON, shape-validate, compute CID, verify match.
// load_plugin_from_rpc   — §4: stdio or http transport.  HTTP stubs with rpc-error
//                          ("http rpc not yet implemented") since stdio covers the
//                          integration test requirement.

use std::io::{BufRead, BufReader, Write as IoWrite};
use std::path::Path;
use std::process::{Command, Stdio};

use serde_json::Value as JsonValue;

use crate::cid::compute_plugin_cid;
use crate::error::LoadError;
use crate::types::{PluginEnvelope, PluginHeader, PluginMemento, PluginMetadata};

/// Protocol versions the runtime accepts (§5.1).
pub const RUNTIME_PROTOCOL_VERSIONS: &[&str] = &["pep/1.7.0"];

// ---------------------------------------------------------------------------
// §3 File interface
// ---------------------------------------------------------------------------

/// Load a `PluginMemento` from a JSON file on disk.
///
/// Per §3:
///   1. Parse JSON.
///   2. Shape-validate (required fields present, schemaVersion = "1").
///   3. Check `protocol_versions` contains a runtime-accepted token (§5).
///   4. Recompute CID per §6.1; compare to asserted `header.cid`.
///
/// Full CDDL validation of `content` is deferred to the consumer spec
/// (§1.2: "Validators of this protocol MUST NOT validate the inner shape").
pub fn load_plugin_from_file(path: &Path) -> Result<PluginMemento, LoadError> {
    // Step 1: read bytes.
    let bytes = std::fs::read(path).map_err(|e| {
        if e.kind() == std::io::ErrorKind::NotFound {
            LoadError::FileNotFound {
                path: path.display().to_string(),
            }
        } else {
            LoadError::ParseError {
                detail: format!("could not read {}: {e}", path.display()),
            }
        }
    })?;

    // Step 2: parse JSON.
    let raw: JsonValue = serde_json::from_slice(&bytes).map_err(|e| LoadError::ParseError {
        detail: format!("JSON parse error in {}: {e}", path.display()),
    })?;

    parse_and_validate(raw)
}

// ---------------------------------------------------------------------------
// §4 JSON-RPC interface
// ---------------------------------------------------------------------------

/// Load a `PluginMemento` from a JSON-RPC endpoint (§4).
///
/// Source detection per §3.1:
///   - `stdio:<command> [args...]`  → spawn subprocess, JSON-RPC over stdio.
///   - `http://...` / `https://...` / `tcp://...` → stubbed (rpc-error).
///
/// The `stdio:` form is the primary integration path.  HTTP will be
/// implemented in a follow-on PR (#738).
pub fn load_plugin_from_rpc(endpoint: &str) -> Result<PluginMemento, LoadError> {
    if let Some(cmd_str) = endpoint.strip_prefix("stdio:") {
        load_plugin_from_stdio_rpc(cmd_str)
    } else if endpoint.starts_with("http://")
        || endpoint.starts_with("https://")
        || endpoint.starts_with("tcp://")
    {
        Err(LoadError::RpcError {
            detail: "http/tcp rpc not yet implemented; use stdio: form".to_string(),
        })
    } else {
        Err(LoadError::RpcError {
            detail: format!("unrecognized rpc endpoint scheme: {endpoint}"),
        })
    }
}

/// Spawn `cmd_str` as a subprocess, send `sugar.plugin.describe`, parse
/// the returned plugin memento from the result.
///
/// The JSON-RPC request body (§4.2.1):
///   { "jsonrpc": "2.0", "id": 1, "method": "sugar.plugin.describe",
///     "params": { "runtime_protocol_versions": ["pep/1.7.0"] } }
///
/// Response must be `{ "jsonrpc": "2.0", "id": 1, "result": { ... } }`.
/// Any error response is a refuse (§4.3).
fn load_plugin_from_stdio_rpc(cmd_str: &str) -> Result<PluginMemento, LoadError> {
    let parts: Vec<&str> = cmd_str.splitn(2, ' ').collect();
    let (bin, rest_args) = (parts[0], parts.get(1).copied().unwrap_or(""));
    let args: Vec<&str> = if rest_args.is_empty() {
        vec![]
    } else {
        rest_args.split_whitespace().collect()
    };

    // NO-SILENT-FAILURE: a plugin subprocess's stderr carries its diagnostics
    // (lift gaps, oracle decisions, refusals). Nulling it by default is what hid
    // a load-bearing bug from five investigations. Inherit by default so plugin
    // diagnostics reach the operator's tracing stream; set SUGAR_PLUGIN_STDERR=null
    // only to deliberately silence them.
    let plugin_stderr = if std::env::var("SUGAR_PLUGIN_STDERR").as_deref() == Ok("null") {
        Stdio::null()
    } else {
        Stdio::inherit()
    };
    let mut child = Command::new(bin)
        .args(&args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(plugin_stderr)
        .spawn()
        .map_err(|e| LoadError::RpcError {
            detail: format!("failed to spawn stdio plugin `{bin}`: {e}"),
        })?;

    // Build request (§4.2.1).
    let request = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.describe",
        "params": {
            "runtime_protocol_versions": RUNTIME_PROTOCOL_VERSIONS
        }
    });
    let request_bytes = serde_json::to_vec(&request).expect("request serialization");

    // Write request + newline to child stdin.
    {
        let stdin = child.stdin.as_mut().ok_or_else(|| LoadError::RpcError {
            detail: "failed to open stdin of plugin subprocess".to_string(),
        })?;
        stdin
            .write_all(&request_bytes)
            .map_err(|e| LoadError::RpcError {
                detail: format!("write to plugin stdin failed: {e}"),
            })?;
        stdin.write_all(b"\n").map_err(|e| LoadError::RpcError {
            detail: format!("write newline to plugin stdin failed: {e}"),
        })?;
    }

    // Read one JSON line from child stdout.
    let stdout = child.stdout.take().ok_or_else(|| LoadError::RpcError {
        detail: "failed to open stdout of plugin subprocess".to_string(),
    })?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| LoadError::RpcError {
            detail: format!("read from plugin stdout failed: {e}"),
        })?;

    // Kill child (we only need the describe response).
    let _ = child.kill();
    let _ = child.wait();

    if line.trim().is_empty() {
        return Err(LoadError::RpcError {
            detail: "plugin subprocess produced no output".to_string(),
        });
    }

    // Parse response.
    let response: JsonValue =
        serde_json::from_str(line.trim()).map_err(|e| LoadError::RpcError {
            detail: format!("plugin response is not valid JSON: {e}"),
        })?;

    // Check for JSON-RPC error (§4.3).
    if response.get("error").is_some() {
        let msg = response["error"]
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown rpc error");
        return Err(LoadError::RpcError {
            detail: format!("plugin describe returned error: {msg}"),
        });
    }

    // Extract `result` object.
    let result = response.get("result").ok_or_else(|| LoadError::RpcError {
        detail: "plugin describe response missing 'result' field".to_string(),
    })?;

    // The result IS the plugin memento body (§4.2.1).
    parse_and_validate(result.clone())
}

// ---------------------------------------------------------------------------
// Shared: parse a raw JsonValue into a validated PluginMemento.
// ---------------------------------------------------------------------------

fn parse_and_validate(raw: JsonValue) -> Result<PluginMemento, LoadError> {
    // Shape-validate: require envelope, header, metadata keys.
    let envelope_raw = raw.get("envelope").ok_or_else(|| LoadError::ParseError {
        detail: "missing 'envelope' field".to_string(),
    })?;
    let header_raw = raw.get("header").ok_or_else(|| LoadError::ParseError {
        detail: "missing 'header' field".to_string(),
    })?;
    let metadata_raw = raw
        .get("metadata")
        .cloned()
        .unwrap_or(JsonValue::Object(Default::default()));

    // Deserialize envelope.
    let envelope: PluginEnvelope =
        serde_json::from_value(envelope_raw.clone()).map_err(|e| LoadError::ParseError {
            detail: format!("envelope parse failed: {e}"),
        })?;

    // Deserialize header.
    let header: PluginHeader =
        serde_json::from_value(header_raw.clone()).map_err(|e| LoadError::ParseError {
            detail: format!("header parse failed: {e}"),
        })?;

    // Deserialize metadata (optional; default to empty).
    let metadata: PluginMetadata =
        serde_json::from_value(metadata_raw).map_err(|e| LoadError::ParseError {
            detail: format!("metadata parse failed: {e}"),
        })?;

    // schemaVersion MUST be "1".
    if header.schema_version != "1" {
        return Err(LoadError::ValidationError {
            detail: format!(
                "unsupported schemaVersion '{}'; expected '1'",
                header.schema_version
            ),
        });
    }

    // protocol_versions check (§5): at least one must be in RUNTIME_PROTOCOL_VERSIONS.
    let version_match = header
        .protocol_versions
        .iter()
        .any(|v| RUNTIME_PROTOCOL_VERSIONS.contains(&v.as_str()));
    if !version_match {
        return Err(LoadError::ProtocolVersionMismatch {
            plugin_versions: header.protocol_versions.clone(),
            runtime_versions: RUNTIME_PROTOCOL_VERSIONS
                .iter()
                .map(|s| s.to_string())
                .collect(),
        });
    }

    // CID verification (§6.1): recompute and compare to asserted.
    let computed = compute_plugin_cid(&header);
    if computed != header.cid {
        return Err(LoadError::CidMismatch {
            asserted: header.cid.clone(),
            computed,
        });
    }

    Ok(PluginMemento {
        envelope,
        header,
        metadata,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_file_not_found() {
        let err = load_plugin_from_file(Path::new("/this/does/not/exist.json"));
        assert!(matches!(err, Err(LoadError::FileNotFound { .. })));
    }

    #[test]
    fn load_file_parse_error_on_bad_json() {
        let tmp = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(tmp.path(), b"not json {{{").unwrap();
        let err = load_plugin_from_file(tmp.path());
        assert!(matches!(err, Err(LoadError::ParseError { .. })));
    }

    #[test]
    fn load_file_missing_header_field() {
        let tmp = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(
            tmp.path(),
            br#"{"envelope": {"declaredAt": "x","signature":"s","signer":"k"}}"#,
        )
        .unwrap();
        let err = load_plugin_from_file(tmp.path());
        assert!(matches!(err, Err(LoadError::ParseError { .. })));
    }

    #[test]
    fn rpc_http_stub_returns_rpc_error() {
        let err = load_plugin_from_rpc("http://localhost:9999/plugin");
        assert!(matches!(err, Err(LoadError::RpcError { .. })));
    }

    #[test]
    fn rpc_unknown_scheme_returns_rpc_error() {
        let err = load_plugin_from_rpc("ftp://whatever");
        assert!(matches!(err, Err(LoadError::RpcError { .. })));
    }
}
