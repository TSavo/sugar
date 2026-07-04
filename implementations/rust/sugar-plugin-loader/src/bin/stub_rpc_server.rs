// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Minimal JSON-RPC stdio sidecar for tests.
//
// Reads one JSON-RPC request on stdin.  If the method is
// `sugar.plugin.describe`, emits a canned plugin memento response and
// exits 0.  Any other method returns a JSON-RPC error.
//
// Usage (for integration tests only):
//   sugar-plugin-loader-stub-rpc [--kind <kind>]
//
// The CID embedded in the response is pre-computed over the fixture
// plugin-memento payload so load_plugin_from_rpc can verify it.
//
// NOTE: This binary is a test helper; it is NOT a real plugin.

use std::io::{self, BufRead, Write};

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let req: serde_json::Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(e) => {
                let err_resp = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": null,
                    "error": { "code": -32700, "message": format!("parse error: {e}") }
                });
                writeln!(out, "{}", serde_json::to_string(&err_resp).unwrap()).unwrap();
                break;
            }
        };

        let id = req.get("id").cloned().unwrap_or(serde_json::Value::Null);
        let method = req.get("method").and_then(|v| v.as_str()).unwrap_or("");

        match method {
            "sugar.plugin.describe" => {
                // Emit the canned fixture memento (pre-computed CID).
                // The CID is computed in integration tests via compute_plugin_cid()
                // over this exact payload.
                let response = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": fixture_plugin_memento()
                });
                writeln!(out, "{}", serde_json::to_string(&response).unwrap()).unwrap();
            }
            "sugar.plugin.shutdown" => {
                let response = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": null
                });
                writeln!(out, "{}", serde_json::to_string(&response).unwrap()).unwrap();
                break;
            }
            other => {
                let err_resp = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "error": { "code": -32601, "message": format!("method not found: {other}") }
                });
                writeln!(out, "{}", serde_json::to_string(&err_resp).unwrap()).unwrap();
            }
        }

        break; // one request per invocation
    }
}

/// Build the canonical test:dummy plugin memento.
///
/// N1 (§6.2 delivery-independence): the stub server MUST emit byte-identical
/// JCS content to the fixture file `tests/fixtures/dummy-sugar.json` so that
/// the CID the loader computes over the RPC response equals the CID computed
/// over the file.  Any divergence means the test exercises the wrong invariant.
///
/// The content, kind, protocol_versions, provenance_cid, schemaVersion, and
/// version fields MUST match the fixture file exactly.
fn fixture_plugin_memento() -> serde_json::Value {
    // Compute the CID at startup to guarantee it matches the payload.
    // The inputs mirror tests/fixtures/dummy-sugar.json exactly.
    use sugar_plugin_loader::cid::compute_plugin_cid;
    use sugar_plugin_loader::types::PluginHeader;

    let header = PluginHeader {
        cid: String::new(), // placeholder; will be replaced
        content: serde_json::json!({
            "data": "test-dummy-fixture-2026-05-12",
            "kind": "test:dummy",
            "version": "0.1.0"
        }),
        critical: false,
        kind: "test:dummy".to_string(),
        protocol_versions: vec!["pep/1.7.0".to_string()],
        provenance_cid: "blake3-512:provenance-test-dummy-fixture-2026-05-12".to_string(),
        schema_version: "1".to_string(),
        version: "0.1.0".to_string(),
    };
    let cid = compute_plugin_cid(&header);

    serde_json::json!({
        "envelope": {
            "declaredAt": "2026-05-12T00:00:00.000Z",
            "signature": "ed25519:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "signer": "ed25519:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        },
        "header": {
            "cid": cid,
            "content": {
                "data": "test-dummy-fixture-2026-05-12",
                "kind": "test:dummy",
                "version": "0.1.0"
            },
            "critical": false,
            "kind": "test:dummy",
            "protocol_versions": ["pep/1.7.0"],
            "provenance_cid": "blake3-512:provenance-test-dummy-fixture-2026-05-12",
            "schemaVersion": "1",
            "version": "0.1.0"
        },
        "metadata": {
            "note": "Test fixture for sugar-plugin-loader integration tests. Not a real plugin.",
            "source_url": "tests/fixtures/dummy-sugar.json"
        }
    })
}
