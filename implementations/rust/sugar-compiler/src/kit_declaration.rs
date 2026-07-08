// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Kit declaration loader.
//
// This is the additive Phase 4 step-3a surface: kits own their declaration and
// serve it over JSON-RPC. The CLI loader consumes an already-resolved manifest
// command; it does not search language-specific package paths or enumerate kits.

use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::time::Duration;

use serde_json::{json, Value};
use sugar_claim_envelope::{KitDeclaration, KitDeclarationError, KIT_DECLARATION_RPC_METHOD};

/// SEAM 6b hardening: the live handshake (`initialize` + `kit_declaration`)
/// must never hang the CLI indefinitely. A kit that never answers gets a
/// loud, named `Timeout`, not a silent block; the previous implementation's
/// `read_line` had no bound at all. Sized generously: parallel `cargo test`
/// runs on a saturated box showed python fixture kits exceeding 5s of
/// startup latency, so the bound protects against HANGS, not slowness.
const HANDSHAKE_READ_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Debug, thiserror::Error)]
pub enum KitDeclarationLoadError {
    #[error("kit declaration command is empty")]
    EmptyCommand,
    #[error("spawn kit declaration command {command:?}: {source}")]
    Spawn {
        command: Vec<String>,
        source: std::io::Error,
    },
    #[error("kit declaration RPC I/O failed: {0}")]
    Io(String),
    #[error("kit declaration RPC response is invalid JSON: {0}; raw={1}")]
    Json(serde_json::Error, String),
    #[error("kit declaration RPC returned error for {method}: {message}")]
    RpcError {
        method: &'static str,
        message: String,
    },
    #[error("kit declaration RPC protocol error for {method}: {message}")]
    Protocol {
        method: &'static str,
        message: String,
    },
    #[error("kit declaration RPC response missing result for {method}: {response}")]
    MissingResult {
        method: &'static str,
        response: String,
    },
    #[error("kit declaration result shape is invalid: {0}")]
    Shape(serde_json::Error),
    #[error("{0}")]
    Invalid(#[from] KitDeclarationError),
    /// The kit command spawned and (possibly) answered `initialize`, but
    /// never produced a response to `{method}` within {timeout_secs}s. Named
    /// so a caller sees "this kit hung", not a process that silently never
    /// returns control to the CLI.
    #[error(
        "kit `{command:?}` never answered `{method}` within {timeout_secs}s (handshake timed out)"
    )]
    Timeout {
        command: Vec<String>,
        method: &'static str,
        timeout_secs: u64,
    },
    /// The kit answered `initialize` and returned SOMETHING for the
    /// `sugar.plugin.kit_declaration` request, but not a valid
    /// `KitDeclaration` -- i.e. it does not actually implement the
    /// declaration RPC (a common shape for older/fixture kits that just
    /// echo back their default `ir-document` response for any unrecognized
    /// method). Named explicitly so this reads as "kit doesn't implement
    /// kit_declaration", not a generic shape-mismatch panic.
    #[error(
        "kit `{command:?}` does not implement `sugar.plugin.kit_declaration` (missing or invalid declaration): {detail}"
    )]
    MissingDeclaration { command: Vec<String>, detail: String },
}

pub fn load_kit_declaration_with_command(
    command: &[String],
    working_dir: Option<&Path>,
) -> Result<KitDeclaration, KitDeclarationLoadError> {
    if command.is_empty() {
        return Err(KitDeclarationLoadError::EmptyCommand);
    }

    let mut child = spawn_kit_declaration_command(command, working_dir)?;

    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| KitDeclarationLoadError::Io("stdin unavailable".to_string()))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| KitDeclarationLoadError::Io("stdout unavailable".to_string()))?;
    let lines = LineReader::spawn(stdout);

    let init = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "client": {"name": "sugar-cli-kit-declaration-loader", "version": env!("CARGO_PKG_VERSION")},
            "protocol_version": "pep/1.7.0",
        }
    });
    let write_result = writeln!(stdin, "{init}")
        .map_err(|e| KitDeclarationLoadError::Io(format!("write initialize: {e}")));
    if let Err(error) = write_result {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    if let Err(error) = read_response(&lines, "initialize", 1, command) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }

    let req = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": KIT_DECLARATION_RPC_METHOD,
        "params": {}
    });
    let write_result = writeln!(stdin, "{req}").map_err(|e| {
        KitDeclarationLoadError::Io(format!("write {KIT_DECLARATION_RPC_METHOD}: {e}"))
    });
    if let Err(error) = write_result {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    let response = match read_response(&lines, KIT_DECLARATION_RPC_METHOD, 2, command) {
        Ok(response) => response,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };

    let shutdown = json!({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "shutdown",
    });
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    let result = response
        .get("result")
        .cloned()
        .ok_or_else(|| KitDeclarationLoadError::MissingDeclaration {
            command: command.to_vec(),
            detail: format!(
                "response missing `result` for {KIT_DECLARATION_RPC_METHOD}: {response}"
            ),
        })?;
    let declaration: KitDeclaration =
        serde_json::from_value(result).map_err(|error| KitDeclarationLoadError::MissingDeclaration {
            command: command.to_vec(),
            detail: format!("declaration shape invalid: {error}"),
        })?;
    declaration
        .validate()
        .map_err(|error| KitDeclarationLoadError::MissingDeclaration {
            command: command.to_vec(),
            detail: format!("declaration failed validation: {error}"),
        })?;
    Ok(declaration)
}

fn spawn_kit_declaration_command(
    command: &[String],
    working_dir: Option<&Path>,
) -> Result<Child, KitDeclarationLoadError> {
    const ETXTBSY: i32 = 26;
    const ATTEMPTS: usize = 5;
    const BACKOFF: std::time::Duration = std::time::Duration::from_millis(20);

    let mut last_etxtbsy = None;
    for attempt in 0..ATTEMPTS {
        let mut cmd = Command::new(&command[0]);
        cmd.args(&command[1..]);
        if let Some(working_dir) = working_dir {
            cmd.current_dir(working_dir);
        }
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());

        match cmd.spawn() {
            Ok(child) => return Ok(child),
            Err(source) if source.raw_os_error() == Some(ETXTBSY) && attempt + 1 < ATTEMPTS => {
                last_etxtbsy = Some(source);
                std::thread::sleep(BACKOFF);
            }
            Err(source) => {
                return Err(KitDeclarationLoadError::Spawn {
                    command: command.to_vec(),
                    source,
                });
            }
        }
    }

    Err(KitDeclarationLoadError::Spawn {
        command: command.to_vec(),
        source: last_etxtbsy.expect("ETXTBSY retry loop records the last error"),
    })
}

/// Background actor that owns the child's stdout and continuously pulls
/// lines off it, handing each completed line (or I/O error/EOF) to the
/// main thread over a channel. This is what makes the per-response read
/// boundable: the main thread calls `recv_timeout` instead of the
/// unbounded `BufRead::read_line` the pre-hardening loader used directly.
/// If the kit never writes a line, this thread stays blocked in its
/// underlying read forever -- but the caller does NOT block with it; on
/// timeout the caller kills the child, which unblocks (or simply leaks,
/// harmlessly, for the remaining lifetime of this short-lived CLI process)
/// this reader thread.
struct LineReader {
    rx: mpsc::Receiver<std::io::Result<Option<String>>>,
}

impl LineReader {
    fn spawn(stdout: std::process::ChildStdout) -> Self {
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                let outcome = match reader.read_line(&mut line) {
                    Ok(0) => Ok(None),
                    Ok(_) => Ok(Some(line)),
                    Err(error) => Err(error),
                };
                let is_terminal = !matches!(outcome, Ok(Some(_)));
                if tx.send(outcome).is_err() || is_terminal {
                    break;
                }
            }
        });
        Self { rx }
    }

    fn next_line(&self, timeout: Duration) -> Result<Option<String>, mpsc::RecvTimeoutError> {
        match self.rx.recv_timeout(timeout) {
            Ok(Ok(line)) => Ok(line),
            Ok(Err(_io_error)) => Ok(None),
            Err(error) => Err(error),
        }
    }
}

fn read_response(
    lines: &LineReader,
    method: &'static str,
    expected_id: i64,
    command: &[String],
) -> Result<Value, KitDeclarationLoadError> {
    let line = match lines.next_line(HANDSHAKE_READ_TIMEOUT) {
        Ok(Some(line)) => line,
        Ok(None) => {
            return Err(KitDeclarationLoadError::Io(format!(
                "kit `{command:?}` closed its stdout before answering {method}"
            )))
        }
        Err(mpsc::RecvTimeoutError::Timeout) => {
            return Err(KitDeclarationLoadError::Timeout {
                command: command.to_vec(),
                method,
                timeout_secs: HANDSHAKE_READ_TIMEOUT.as_secs(),
            })
        }
        Err(mpsc::RecvTimeoutError::Disconnected) => {
            return Err(KitDeclarationLoadError::Io(format!(
                "kit `{command:?}` reader disconnected before answering {method}"
            )))
        }
    };
    if line.trim().is_empty() {
        return Err(KitDeclarationLoadError::Io(format!(
            "empty response for {method}"
        )));
    }
    let value: Value = serde_json::from_str(line.trim())
        .map_err(|e| KitDeclarationLoadError::Json(e, line.trim().to_string()))?;
    let id = value.get("id").and_then(Value::as_i64).unwrap_or(-1);
    if id != expected_id {
        return Err(KitDeclarationLoadError::Protocol {
            method,
            message: format!("response id mismatch: expected {expected_id}, got {id}"),
        });
    }
    if let Some(error) = value.get("error") {
        let message = error
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("unknown RPC error")
            .to_string();
        return Err(KitDeclarationLoadError::RpcError { method, message });
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_executable(path: &std::path::Path, contents: &str) {
        std::fs::write(path, contents).expect("write script");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut perms = std::fs::metadata(path).expect("metadata").permissions();
            perms.set_mode(0o755);
            std::fs::set_permissions(path, perms).expect("chmod script");
        }
    }

    /// (a) A kit that never answers ANYTHING (not even `initialize`) must
    /// fail with a named `Timeout`, never hang the caller.
    #[test]
    fn never_answering_kit_times_out_named() {
        let dir = tempfile::tempdir().expect("tempdir");
        let script = dir.path().join("silent-kit.sh");
        write_executable(
            &script,
            "#!/usr/bin/env bash\nwhile true; do sleep 3600; done\n",
        );
        let command = vec![script.display().to_string()];
        let result = load_kit_declaration_with_command(&command, None);
        match result {
            Err(KitDeclarationLoadError::Timeout {
                method,
                timeout_secs,
                ..
            }) => {
                assert_eq!(method, "initialize");
                assert_eq!(timeout_secs, HANDSHAKE_READ_TIMEOUT.as_secs());
            }
            other => panic!("expected Timeout on `initialize`, got: {other:?}"),
        }
    }

    /// (b) A kit that answers `initialize` but has no idea what
    /// `sugar.plugin.kit_declaration` is (echoes back an unrelated shape)
    /// must fail with a named `MissingDeclaration`, not a bare shape-parse
    /// panic or a silent hang.
    #[test]
    fn initialize_only_kit_reports_missing_declaration_named() {
        let dir = tempfile::tempdir().expect("tempdir");
        let script = dir.path().join("initialize-only-kit.py");
        write_executable(
            &script,
            r#"#!/usr/bin/env python3
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {"name": "initialize-only", "protocol_version": "pep/1.7.0", "capabilities": {}}
    elif method == "shutdown":
        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": None}), flush=True)
        break
    else:
        # Doesn't know kit_declaration: echoes back an unrelated shape,
        # exactly like the pre-hardening static-vendor test fixture did.
        result = {"kind": "ir-document", "ir": [], "diagnostics": []}
    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
"#,
        );
        let command = vec![script.display().to_string()];
        let result = load_kit_declaration_with_command(&command, None);
        match result {
            Err(KitDeclarationLoadError::MissingDeclaration { command, detail }) => {
                assert!(command[0].ends_with("initialize-only-kit.py"));
                assert!(
                    detail.contains("shape invalid") || detail.contains("missing"),
                    "detail should name the shape/missing-field problem: {detail}"
                );
            }
            other => panic!("expected MissingDeclaration, got: {other:?}"),
        }
    }
}
