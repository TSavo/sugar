// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Integration test: spawn `sugar-lsp-rust`, drive it via NDJSON,
// assert protocol contract per spec.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

fn plugin_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar-lsp-rust"))
}

struct Plugin {
    child: std::process::Child,
    stdin: std::process::ChildStdin,
    stdout: BufReader<std::process::ChildStdout>,
}

impl Plugin {
    fn spawn() -> Self {
        let mut child = Command::new(plugin_bin())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn sugar-lsp-rust");
        let stdin = child.stdin.take().expect("stdin");
        let stdout = BufReader::new(child.stdout.take().expect("stdout"));
        Self {
            child,
            stdin,
            stdout,
        }
    }

    fn exchange(&mut self, payload: &Value) -> Value {
        let line = serde_json::to_string(payload).unwrap();
        writeln!(self.stdin, "{line}").expect("write to plugin stdin");
        self.stdin.flush().expect("flush");
        let mut buf = String::new();
        let n = self
            .stdout
            .read_line(&mut buf)
            .expect("read from plugin stdout");
        assert!(n > 0, "plugin closed stdout without responding");
        serde_json::from_str(buf.trim()).expect("decode plugin response as JSON")
    }

    fn wait_for_exit(mut self, timeout: Duration) -> std::process::ExitStatus {
        drop(self.stdin);
        let start = Instant::now();
        loop {
            match self.child.try_wait().expect("try_wait") {
                Some(status) => return status,
                None => {
                    if start.elapsed() > timeout {
                        let _ = self.child.kill();
                        panic!("plugin did not exit within {timeout:?}");
                    }
                    std::thread::sleep(Duration::from_millis(50));
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// 1. initialize returns a capabilities envelope
// ---------------------------------------------------------------------------

#[test]
fn initialize_returns_capabilities() {
    let mut plugin = Plugin::spawn();

    let resp = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }));

    assert_eq!(resp["jsonrpc"], "2.0");
    assert_eq!(resp["id"], 1);

    let result = resp
        .get("result")
        .unwrap_or_else(|| panic!("initialize returned error: {resp}"));

    assert_eq!(
        result["name"].as_str(),
        Some("sugar-lsp-rust"),
        "wrong plugin name: {result}"
    );
    assert!(
        result.get("version").and_then(|v| v.as_str()).is_some(),
        "missing version: {result}"
    );
    assert_eq!(
        result["protocol_version"].as_str(),
        Some("sugar-lsp-shared/1"),
        "rust helper must advertise the shared LSP protocol: {result}"
    );
    assert_eq!(
        result["kit_id"].as_str(),
        Some("rust"),
        "rust helper must identify its owning kit: {result}"
    );
    let caps = result["capabilities"]
        .as_object()
        .unwrap_or_else(|| panic!("missing capabilities object: {result}"));
    assert!(
        caps.get("source_surfaces")
            .and_then(|v| v.as_array())
            .into_iter()
            .flatten()
            .any(|c| c.as_str() == Some("rust-source")),
        "capabilities must include rust-source: {caps:?}"
    );
    assert!(
        caps.get("diagnostic_codes")
            .and_then(|v| v.as_array())
            .into_iter()
            .flatten()
            .any(|c| c.as_str() == Some("sugar.lsp.implication_failed")),
        "capabilities must include the stable implication diagnostic code: {caps:?}"
    );

    // Tidy shutdown.
    let _ = plugin.exchange(&json!({"jsonrpc":"2.0","id":99,"method":"shutdown"}));
    let _ = plugin.wait_for_exit(Duration::from_secs(10));
}

// ---------------------------------------------------------------------------
// 2. parse over a fixture emits at least one contract declaration
// ---------------------------------------------------------------------------

#[test]
fn parse_floor_fixture_emits_forward_propagation_diagnostic() {
    let fixture_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .join("tests/lsp/floor-fixture/rust.rs");
    let source = std::fs::read_to_string(&fixture_path)
        .unwrap_or_else(|err| panic!("read fixture {fixture_path:?}: {err}"));

    let mut plugin = Plugin::spawn();

    let _ = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }));

    let resp = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "parse",
        "params": {
            "path": "rust.rs",
            "source": source
        }
    }));

    let result = resp
        .get("result")
        .unwrap_or_else(|| panic!("parse returned error: {resp}"));
    let diagnostics = result["diagnostics"]
        .as_array()
        .unwrap_or_else(|| panic!("diagnostics must be an array: {result}"));

    assert_eq!(
        diagnostics.len(),
        1,
        "only the negative callsite should emit a diagnostic: {diagnostics:#?}"
    );
    let diagnostic = &diagnostics[0];
    assert_eq!(diagnostic["severity"].as_i64(), Some(1));
    assert_eq!(diagnostic["source"].as_str(), Some("sugar"));
    assert_eq!(
        diagnostic["code"].as_str(),
        Some("sugar.lsp.implication_failed")
    );
    assert_eq!(
        diagnostic["data"]["kind"].as_str(),
        Some("sugar.lsp.implication_failed")
    );
    assert_eq!(diagnostic["data"]["callee"].as_str(), Some("checkPositive"));
    assert_eq!(
        diagnostic["data"]["missing_conjuncts"]
            .as_array()
            .and_then(|items| items.first())
            .and_then(|item| item.as_str()),
        Some("x > 0")
    );

    let _ = plugin.exchange(&json!({"jsonrpc":"2.0","id":99,"method":"shutdown"}));
    let _ = plugin.wait_for_exit(Duration::from_secs(10));
}

#[test]
fn analyze_document_floor_fixture_emits_shared_callsite_diagnostic() {
    let fixture_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .join("tests/lsp/floor-fixture/rust.rs");
    let source = std::fs::read_to_string(&fixture_path)
        .unwrap_or_else(|err| panic!("read fixture {fixture_path:?}: {err}"));

    let mut plugin = Plugin::spawn();

    let _ = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "client": {"name": "sugar-lsp", "version": "0.0.0"},
            "protocol_version": "sugar-lsp-shared/1"
        }
    }));

    let resp = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "analyzeDocument",
        "params": {
            "kit_id": "rust",
            "uri": "file:///project/tests/lsp/floor-fixture/rust.rs",
            "file": "tests/lsp/floor-fixture/rust.rs",
            "text": source,
            "document_version": 42,
            "workspace_root": "/project",
            "accepted_protocol_catalog_cids": [],
            "policy_cids": []
        }
    }));

    let result = resp
        .get("result")
        .unwrap_or_else(|| panic!("analyzeDocument returned error: {resp}"));

    assert_eq!(result["kind"].as_str(), Some("lsp-document-analysis"));
    assert_eq!(result["schema_version"].as_str(), Some("1"));
    assert_eq!(result["kit_id"].as_str(), Some("rust"));
    assert_eq!(
        result["uri"].as_str(),
        Some("file:///project/tests/lsp/floor-fixture/rust.rs")
    );
    assert_eq!(
        result["file"].as_str(),
        Some("tests/lsp/floor-fixture/rust.rs")
    );
    let document_cid = result["document_cid"]
        .as_str()
        .unwrap_or_else(|| panic!("missing document CID: {result}"));
    assert!(
        document_cid.starts_with("blake3-512:") && document_cid.len() == "blake3-512:".len() + 128,
        "document CID must be a BLAKE3-512 CID: {document_cid}"
    );
    assert!(
        result["entries"].as_array().is_some(),
        "entries must be an array: {result}"
    );
    assert!(
        result["statuses"].as_array().is_some(),
        "statuses must be an array: {result}"
    );
    assert!(
        result["project"].is_null(),
        "project state must be null: {result}"
    );

    let diagnostics = result["diagnostics"]
        .as_array()
        .unwrap_or_else(|| panic!("diagnostics must be an array: {result}"));
    assert_eq!(
        diagnostics.len(),
        1,
        "only the negative callsite should emit a diagnostic: {diagnostics:#?}"
    );
    let diagnostic = &diagnostics[0];
    assert_eq!(
        diagnostic["code"].as_str(),
        Some("sugar.lsp.implication_failed")
    );
    assert_eq!(diagnostic["severity"].as_str(), Some("error"));
    assert_eq!(diagnostic["producer"].as_str(), Some("forward-propagation"));
    assert_eq!(diagnostic["kit_id"].as_str(), Some("rust"));
    assert_eq!(diagnostic["range"]["start_line"].as_u64(), Some(20));
    assert_eq!(diagnostic["range"]["start_col"].as_u64(), Some(17));
    assert_eq!(diagnostic["data"]["callee"].as_str(), Some("checkPositive"));

    let _ = plugin.exchange(&json!({"jsonrpc":"2.0","id":99,"method":"shutdown"}));
    let _ = plugin.wait_for_exit(Duration::from_secs(10));
}

// ---------------------------------------------------------------------------
// 3. Unknown method returns JSON-RPC -32601
// ---------------------------------------------------------------------------

#[test]
fn unknown_method_returns_method_not_found() {
    let mut plugin = Plugin::spawn();

    let _ = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }));

    let resp = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "no_such_method"
    }));

    let err = resp
        .get("error")
        .unwrap_or_else(|| panic!("expected JSON-RPC error, got: {resp}"));
    assert_eq!(
        err["code"].as_i64(),
        Some(-32601),
        "expected method-not-found error code (-32601): {err}"
    );

    // Tidy shutdown.
    let _ = plugin.exchange(&json!({"jsonrpc":"2.0","id":99,"method":"shutdown"}));
    let _ = plugin.wait_for_exit(Duration::from_secs(10));
}

// ---------------------------------------------------------------------------
// 4. shutdown exits cleanly (exit code 0)
// ---------------------------------------------------------------------------

#[test]
fn shutdown_exits_cleanly() {
    let mut plugin = Plugin::spawn();

    let _ = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }));

    let resp = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "shutdown"
    }));

    assert_eq!(resp["id"], 2);
    assert!(
        resp.get("result").map(|v| v.is_null()).unwrap_or(false),
        "shutdown should return null result, got: {resp}"
    );

    let status = plugin.wait_for_exit(Duration::from_secs(10));
    assert!(
        status.success(),
        "plugin exited with non-zero status: {status:?}"
    );
}
