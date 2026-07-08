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

use serde_json::{json, Value};
use sugar_claim_envelope::{KitDeclaration, KitDeclarationError, KIT_DECLARATION_RPC_METHOD};

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
    let mut reader = BufReader::new(stdout);

    let init = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "client": {"name": "sugar-cli-kit-declaration-loader", "version": env!("CARGO_PKG_VERSION")},
            "protocol_version": "pep/1.7.0",
        }
    });
    writeln!(stdin, "{init}")
        .map_err(|e| KitDeclarationLoadError::Io(format!("write initialize: {e}")))?;
    let _ = read_response(&mut reader, "initialize", 1)?;

    let req = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": KIT_DECLARATION_RPC_METHOD,
        "params": {}
    });
    writeln!(stdin, "{req}").map_err(|e| {
        KitDeclarationLoadError::Io(format!("write {KIT_DECLARATION_RPC_METHOD}: {e}"))
    })?;
    let response = read_response(&mut reader, KIT_DECLARATION_RPC_METHOD, 2)?;

    let shutdown = json!({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "shutdown",
    });
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    let result =
        response
            .get("result")
            .cloned()
            .ok_or_else(|| KitDeclarationLoadError::MissingResult {
                method: KIT_DECLARATION_RPC_METHOD,
                response: response.to_string(),
            })?;
    let declaration: KitDeclaration =
        serde_json::from_value(result).map_err(KitDeclarationLoadError::Shape)?;
    declaration.validate()?;
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

fn read_response<R: BufRead>(
    reader: &mut R,
    method: &'static str,
    expected_id: i64,
) -> Result<Value, KitDeclarationLoadError> {
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| KitDeclarationLoadError::Io(format!("read {method}: {e}")))?;
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
