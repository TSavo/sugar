// SPDX-License-Identifier: MIT OR Apache-2.0
//
// pull_diagnostics.rs: regression gate for the `-32601: Method not found`
// bug a standard LSP client (e.g. Neovim 0.10+, which enables pull
// diagnostics whenever a server advertises `diagnosticProvider`) hits
// against this server.
//
// ROOT CAUSE: `initialize`'s `ServerCapabilities` declares
// `diagnostic_provider: Some(...)`, which per the LSP 3.17 spec means "this
// server implements `textDocument/diagnostic`". But `LanguageServer::diagnostic`
// was never overridden, so tower-lsp's default trait method
// (`Err(Error::method_not_found())`) answered instead -- a real client that
// honors the advertised capability and pulls gets `-32601` the moment it
// asks. This test drives the REAL LSP stdio transport (same harness shape as
// `in_process_prove.rs`) and asserts the fix: the request now gets a real
// (non-error) `DocumentDiagnosticReportResult`.

use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};

use serde_json::{json, Value};

fn lsp_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar-lsp"))
}

fn missing_config_path(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "sugar-lsp-pull-diagnostics-missing-config-{label}-{}.toml",
        std::process::id()
    ))
}

struct LspServer {
    child: Child,
    stdin: std::process::ChildStdin,
    stdout: BufReader<std::process::ChildStdout>,
    next_id: i64,
}

impl LspServer {
    fn spawn_in_process(missing_config: &Path) -> Self {
        let mut cmd = Command::new(lsp_bin());
        cmd.arg("--config")
            .arg(missing_config)
            .arg("--in-process")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        let mut child = cmd.spawn().expect("spawn sugar-lsp --in-process");
        let stdin = child.stdin.take().expect("lsp stdin");
        let stdout = BufReader::new(child.stdout.take().expect("lsp stdout"));
        Self {
            child,
            stdin,
            stdout,
            next_id: 1,
        }
    }

    fn send(&mut self, msg: &Value) {
        let body = serde_json::to_string(msg).unwrap();
        let header = format!("Content-Length: {}\r\n\r\n", body.len());
        self.stdin.write_all(header.as_bytes()).expect("write header");
        self.stdin.write_all(body.as_bytes()).expect("write body");
        self.stdin.flush().expect("flush");
    }

    fn recv(&mut self) -> Value {
        let mut content_length: usize = 0;
        loop {
            let mut line = String::new();
            self.stdout.read_line(&mut line).expect("read header line");
            let trimmed = line.trim();
            if trimmed.is_empty() {
                break;
            }
            if let Some(rest) = trimmed.strip_prefix("Content-Length:") {
                content_length = rest.trim().parse().expect("parse Content-Length");
            }
        }
        assert!(content_length > 0, "no Content-Length header received");
        let mut body = vec![0u8; content_length];
        self.stdout.read_exact(&mut body).expect("read LSP body");
        serde_json::from_slice(&body).expect("parse LSP JSON body")
    }

    fn request(&mut self, method: &str, params: Value) -> Value {
        let id = self.next_id;
        self.next_id += 1;
        self.send(&json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params}));
        loop {
            let msg = self.recv();
            if msg.get("id") == Some(&Value::Number(id.into())) {
                return msg;
            }
        }
    }

    fn notify(&mut self, method: &str, params: Value) {
        self.send(&json!({"jsonrpc": "2.0", "method": method, "params": params}));
    }

    fn initialize(&mut self, root_uri: &str) -> Value {
        self.request(
            "initialize",
            json!({"processId": null, "capabilities": {}, "rootUri": root_uri}),
        )
    }

    fn initialized(&mut self) {
        self.notify("initialized", json!({}));
    }

    fn kill(mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// `textDocument/diagnostic`, the LSP 3.17 pull-diagnostics request this
/// server's advertised `diagnosticProvider` capability commits it to
/// answering, must no longer come back `-32601: Method not found`.
#[test]
fn pull_diagnostic_request_is_not_method_not_found() {
    let tmp = std::env::temp_dir().join(format!(
        "sugar-lsp-pull-diagnostics-project-{}",
        std::process::id()
    ));
    std::fs::create_dir_all(&tmp).expect("mkdir fixture project");
    let root_uri = format!("file://{}", tmp.display());
    let file_uri = format!("file://{}/a.rs", tmp.display());

    let mut lsp = LspServer::spawn_in_process(&missing_config_path("pull"));
    let init_resp = lsp.initialize(&root_uri);
    assert!(init_resp.get("result").is_some(), "initialize failed: {init_resp}");

    // The capability this server declares is exactly what makes a real
    // client (Neovim 0.10+, VS Code) decide to pull via
    // `textDocument/diagnostic` in the first place.
    let capabilities = init_resp["result"]["capabilities"].clone();
    assert!(
        capabilities.get("diagnosticProvider").is_some(),
        "server must still advertise diagnosticProvider for this regression to be meaningful: {capabilities}"
    );

    lsp.initialized();
    lsp.notify(
        "textDocument/didOpen",
        json!({
            "textDocument": {
                "uri": file_uri,
                "languageId": "rust",
                "version": 1,
                "text": "fn main() {}\n",
            }
        }),
    );

    let resp = lsp.request(
        "textDocument/diagnostic",
        json!({"textDocument": {"uri": file_uri}}),
    );

    assert!(
        resp.get("error").is_none(),
        "textDocument/diagnostic must not error, got: {resp}"
    );
    let error_code = resp
        .get("error")
        .and_then(|e| e.get("code"))
        .and_then(|c| c.as_i64());
    assert_ne!(
        error_code,
        Some(-32601),
        "textDocument/diagnostic regressed to Method not found: {resp}"
    );
    assert!(
        resp.get("result").is_some(),
        "expected a DocumentDiagnosticReportResult in `result`, got: {resp}"
    );
    // Full-report shape: `{"kind": "full", "items": [...]}`.
    assert_eq!(
        resp["result"]["kind"].as_str(),
        Some("full"),
        "expected a full document diagnostic report, got: {resp}"
    );
    assert!(
        resp["result"]["items"].is_array(),
        "expected `items` to be an array, got: {resp}"
    );

    lsp.kill();
    std::fs::remove_dir_all(&tmp).ok();
}

/// A method genuinely absent from the LSP spec (and from tower-lsp's own
/// `LanguageServer` trait) must still come back `-32601` -- this test is the
/// discriminator proving the fix targets the specific `diagnostic` handler
/// rather than suppressing `MethodNotFound` responses generally.
#[test]
fn genuinely_unknown_method_still_returns_method_not_found() {
    let tmp = std::env::temp_dir().join(format!(
        "sugar-lsp-pull-diagnostics-unknown-{}",
        std::process::id()
    ));
    std::fs::create_dir_all(&tmp).expect("mkdir fixture project");
    let root_uri = format!("file://{}", tmp.display());

    let mut lsp = LspServer::spawn_in_process(&missing_config_path("unknown"));
    lsp.initialize(&root_uri);
    lsp.initialized();

    let resp = lsp.request("textDocument/thisMethodDoesNotExist", json!({}));
    assert_eq!(
        resp["error"]["code"].as_i64(),
        Some(-32601),
        "a genuinely unimplemented method should still 404, got: {resp}"
    );

    lsp.kill();
    std::fs::remove_dir_all(&tmp).ok();
}
