// SPDX-License-Identifier: Apache-2.0
//
// Shared JSON-RPC stdio server for IR compiler binaries.

use std::io::{self, BufRead, Write};

use serde_json::{json, Value as Json};
use tracing::{debug, error, warn};

use crate::{Capabilities, IrCompiler};

const COMPONENT_PLAN_RPC_METHOD: &str = "sugar.component.plan";

/// Serve one line-delimited JSON-RPC request per stdin line and write one
/// response per stdout line. Compiler binaries should be thin wrappers around
/// this function so every dialect speaks the same protocol.
pub fn serve_stdio(compiler: impl IrCompiler) {
    let stdin = io::stdin();
    let stdout = io::stdout();

    let mut out = stdout.lock();
    let mut in_ = stdin.lock();
    let mut buf = String::new();

    loop {
        buf.clear();
        let n = match in_.read_line(&mut buf) {
            Ok(n) => n,
            Err(e) => {
                error!(error = %e, "ir compiler rpc server: stdin read error");
                std::process::exit(1);
            }
        };
        if n == 0 {
            break;
        }
        let trimmed = buf.trim();
        if trimmed.is_empty() {
            continue;
        }

        let req: Json = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(e) => {
                warn!(error = %e, "ir compiler rpc server: parse error");
                let resp = error_response(json!(null), -32700, &format!("parse error: {e}"), None);
                emit_line(&mut out, &resp);
                continue;
            }
        };

        let id = req.get("id").cloned().unwrap_or(Json::Null);
        let method = req.get("method").and_then(|m| m.as_str()).unwrap_or("");
        let params = req.get("params").cloned().unwrap_or(Json::Null);
        debug!(method, id = %id, "ir compiler rpc server: request");

        let resp = match method {
            "initialize" => json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": compiler.capabilities(),
            }),
            COMPONENT_PLAN_RPC_METHOD => component_plan_response(id, &compiler.capabilities()),
            "sugar.ir.handshake" => json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": compiler.capabilities(),
            }),
            "sugar.ir.compile" => {
                let dialect = params
                    .get("target_dialect")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let ir = match params.get("ir_json") {
                    Some(v) => v.clone(),
                    None => {
                        let r = error_response(id.clone(), -32602, "missing param: ir_json", None);
                        emit_line(&mut out, &r);
                        continue;
                    }
                };
                if dialect.is_empty() {
                    let r =
                        error_response(id.clone(), -32602, "missing param: target_dialect", None);
                    emit_line(&mut out, &r);
                    continue;
                }
                match compiler.compile(&ir, dialect) {
                    Ok(c) => {
                        debug!(
                            dialect,
                            free_vars = c.free_vars.len(),
                            opacities = c.opacity_manifest.opacities.len(),
                            "ir compiler rpc server: compile complete"
                        );
                        json!({
                            "jsonrpc": "2.0",
                            "id": id,
                            "result": c,
                        })
                    }
                    Err(e) => {
                        warn!(
                            dialect,
                            error = %e,
                            "ir compiler rpc server: compile failed"
                        );
                        error_response(
                            id,
                            e.code() as i64,
                            e.symbolic(),
                            Some(json!(e.to_string())),
                        )
                    }
                }
            }
            "shutdown" | "sugar.ir.shutdown" => {
                let r = json!({"jsonrpc": "2.0", "id": id, "result": {}});
                emit_line(&mut out, &r);
                break;
            }
            other => error_response(id, -32601, &format!("method not found: {other}"), None),
        };

        emit_line(&mut out, &resp);
    }
}

fn component_plan_response(id: Json, caps: &Capabilities) -> Json {
    let command = std::env::current_exe()
        .ok()
        .map(|path| vec![path.display().to_string()])
        .unwrap_or_else(|| vec![caps.name.clone()]);
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": {
            "decision": "claim",
            "claims": [{
                "role": "ir-compiler",
                "name": caps.name.clone(),
                "dialects": caps.dialects.clone(),
            }],
            "ir_compilers": [{
                "name": caps.name.clone(),
                "version": caps.version.clone(),
                "protocol_version": caps.protocol_version.clone(),
                "command": command,
                "dialects": caps.dialects.clone(),
                "supported_sorts": caps.supported_sorts.clone(),
                "supported_predicates": caps.supported_predicates.clone(),
            }],
        },
    })
}

fn error_response(id: Json, code: i64, message: &str, data: Option<Json>) -> Json {
    let mut err = json!({"code": code, "message": message});
    if let Some(d) = data {
        err["data"] = d;
    }
    json!({"jsonrpc": "2.0", "id": id, "error": err})
}

fn emit_line(out: &mut impl Write, v: &Json) {
    let s = serde_json::to_string(v).unwrap_or_else(|_| "{}".to_string());
    let _ = writeln!(out, "{s}");
    let _ = out.flush();
}
