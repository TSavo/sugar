// SPDX-License-Identifier: Apache-2.0
//
// Shared JSON-RPC stdio server for IR compiler binaries.

use std::io::{self, BufRead, Write};

use serde_json::{json, Value as Json};
use tracing::{debug, error, warn};

use crate::{Capabilities, CompileError, CompilerInput, IrCompiler};

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

        let (resp, control) = handle_request(&compiler, req);
        emit_line(&mut out, &resp);
        if matches!(control, ServerControl::Shutdown) {
            break;
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ServerControl {
    Continue,
    Shutdown,
}

fn handle_request(compiler: &impl IrCompiler, req: Json) -> (Json, ServerControl) {
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
        "sugar.ir.compile" => compile_response(compiler, id, params),
        "shutdown" | "sugar.ir.shutdown" => {
            return (
                json!({"jsonrpc": "2.0", "id": id, "result": {}}),
                ServerControl::Shutdown,
            );
        }
        other => error_response(id, -32601, &format!("method not found: {other}"), None),
    };

    (resp, ServerControl::Continue)
}

fn compile_response(compiler: &impl IrCompiler, id: Json, params: Json) -> Json {
    let dialect = params
        .get("target_dialect")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let ir = match params.get("ir_json") {
        Some(v) => v.clone(),
        None => return error_response(id, -32602, "missing param: ir_json", None),
    };
    if dialect.is_empty() {
        return error_response(id, -32602, "missing param: target_dialect", None);
    }

    let typed = match CompilerInput::decode_json(ir) {
        Ok(typed) => typed,
        Err(error) => {
            let error = CompileError::from(error);
            warn!(
                dialect,
                error = %error,
                "ir compiler rpc server: frontend decode failed"
            );
            return compile_error_response(id, &error);
        }
    };

    match compiler.compile_typed(&typed, dialect) {
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
            compile_error_response(id, &e)
        }
    }
}

fn compile_error_response(id: Json, error: &CompileError) -> Json {
    error_response(
        id,
        error.code() as i64,
        error.symbolic(),
        compile_error_data(error),
    )
}

fn compile_error_data(error: &CompileError) -> Option<Json> {
    match error {
        CompileError::Frontend(payload) => serde_json::to_value(payload).ok(),
        _ => Some(json!(error.to_string())),
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

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use super::*;
    use crate::{
        CompileError, CompiledFormula, CompilerInput, FreeVar, OpacityManifest, PROTOCOL_VERSION,
    };

    struct CountingCompiler {
        compile_calls: AtomicUsize,
        compile_typed_calls: AtomicUsize,
    }

    impl CountingCompiler {
        fn new() -> Self {
            Self {
                compile_calls: AtomicUsize::new(0),
                compile_typed_calls: AtomicUsize::new(0),
            }
        }
    }

    impl IrCompiler for CountingCompiler {
        fn compile(&self, _ir: &Json, _dialect: &str) -> Result<CompiledFormula, CompileError> {
            self.compile_calls.fetch_add(1, Ordering::SeqCst);
            panic!("RPC server must decode ir_json and call compile_typed, not backend compile")
        }

        fn compile_typed(
            &self,
            _ir: &CompilerInput,
            dialect: &str,
        ) -> Result<CompiledFormula, CompileError> {
            self.compile_typed_calls.fetch_add(1, Ordering::SeqCst);
            assert_eq!(dialect, "smt-lib-v2.6");
            Ok(CompiledFormula {
                preamble: "; typed\n".to_string(),
                body: "(check-sat)\n".to_string(),
                free_vars: vec![FreeVar {
                    name: "x".to_string(),
                    sort: "Int".to_string(),
                }],
                opacity_manifest: OpacityManifest::default(),
                metadata: Json::Null,
            })
        }

        fn capabilities(&self) -> Capabilities {
            Capabilities {
                name: "counting".to_string(),
                version: "0.0.0".to_string(),
                protocol_version: PROTOCOL_VERSION.to_string(),
                dialects: vec!["smt-lib-v2.6".to_string()],
                supported_sorts: vec!["Int".to_string()],
                supported_predicates: vec!["=".to_string()],
            }
        }
    }

    fn compile_request(ir_json: Json) -> Json {
        json!({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "sugar.ir.compile",
            "params": {
                "ir_json": ir_json,
                "target_dialect": "smt-lib-v2.6"
            }
        })
    }

    #[test]
    fn compile_request_decodes_transport_json_before_backend() {
        let compiler = CountingCompiler::new();
        let (response, control) = handle_request(
            &compiler,
            compile_request(json!({
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "x"},
                    {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            })),
        );

        assert!(matches!(control, ServerControl::Continue));
        assert!(response.get("error").is_none(), "{response}");
        assert_eq!(response["result"]["body"], "(check-sat)\n");
        assert_eq!(compiler.compile_calls.load(Ordering::SeqCst), 0);
        assert_eq!(compiler.compile_typed_calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn malformed_ir_json_returns_structured_frontend_error_data() {
        let compiler = CountingCompiler::new();
        let (response, control) = handle_request(&compiler, compile_request(Json::Null));

        assert!(matches!(control, ServerControl::Continue));
        let error = response.get("error").expect("frontend error response");
        assert_eq!(error["code"], 2003);
        assert_eq!(error["message"], "compile_error.frontend_decode");
        let data = error.get("data").expect("typed frontend payload data");
        assert_eq!(data["kind"], "malformed_transport");
        assert_eq!(
            data["frontend"],
            "sugar-ir-compiler::frontend::CompilerInput::decode_json"
        );
        assert_eq!(data["input_format"], "proofir-json");
        assert_eq!(data["path"], "$");
        assert!(data["detail"].as_str().unwrap().contains("JSON object"));
        assert!(data["retirement"].as_str().unwrap().contains("S7 deletes"));
        assert_eq!(compiler.compile_calls.load(Ordering::SeqCst), 0);
        assert_eq!(compiler.compile_typed_calls.load(Ordering::SeqCst), 0);
    }
}
