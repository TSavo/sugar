// Sugar LSP Language Plugin: Rust
//
// A standalone binary that speaks `sugar-lsp-plugin/1` over stdio.
// Parses Rust source files and extracts sugar annotations.
//
// Usage: sugar-lsp-rust --rpc
//
// To use this plugin, add to `.sugar/config.toml`:
//   [[language]]
//   name = "rust"
//   extensions = [".rs"]
//   plugin = "sugar-lsp-rust"

use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{BufRead, Write};

#[derive(Serialize)]
struct Annotation {
    function_name: String,
    kind: String,
    target_cid: Option<String>,
    range: Range,
}

#[derive(Serialize)]
struct Range {
    start: Position,
    end: Position,
}

#[derive(Serialize)]
struct Position {
    line: u32,
    character: u32,
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if !args.iter().any(|a| a == "--rpc") {
        eprintln!("Usage: sugar-lsp-rust --rpc");
        std::process::exit(1);
    }

    let re_impl = Regex::new(
        r#"#\[ensures\s*\(\s*result\s*==\s*([^\)]*)\)\]"#
    ).unwrap();
    let re_contract = Regex::new(r#"#\[requires"#).unwrap();
    let re_verify = Regex::new(r#"#\[ensures"#).unwrap();
    let re_fn = Regex::new(r#"\bfn\s+(\w+)"#).unwrap();

    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue,
        };
        let req: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                let resp = json!({"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":format!("parse error: {e}")}});
                let _ = writeln!(stdout, "{resp}");
                continue;
            }
        };

        let id = req.get("id").cloned().unwrap_or(json!(null));
        let method = req.get("method").and_then(|v| v.as_str()).unwrap_or("");

        match method {
            "initialize" => {
                let resp = json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "name": "sugar-lsp-rust",
                        "version": env!("CARGO_PKG_VERSION"),
                        "capabilities": []
                    }
                });
                let _ = writeln!(stdout, "{resp}");
            }
            "parse" => {
                let params = req.get("params").cloned().unwrap_or(json!({}));
                let text = params.get("text").and_then(|v| v.as_str()).unwrap_or("");
                let annotations = parse_rust(text, &re_impl, &re_contract, &re_verify, &re_fn);
                let resp = json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {"annotations": annotations}
                });
                let _ = writeln!(stdout, "{resp}");
            }
            "shutdown" => {
                let resp = json!({"jsonrpc":"2.0","id":id,"result":null});
                let _ = writeln!(stdout, "{resp}");
                return;
            }
            _ => {
                let resp = json!({"jsonrpc":"2.0","id":id,"error":{"code":-32601,"message":format!("unknown method: {method}")}});
                let _ = writeln!(stdout, "{resp}");
            }
        }
    }
}

fn parse_rust(
    text: &str,
    re_impl: &Regex,
    re_contract: &Regex,
    re_verify: &Regex,
    re_fn: &Regex,
) -> Vec<Annotation> {
    let mut annotations = Vec::new();
    let lines: Vec<&str> = text.lines().collect();

    for (idx, line_text) in lines.iter().enumerate() {
        let line_num = idx as u32;

        if let Some(cap) = re_impl.captures(line_text) {
            let target_cid = cap.get(1).map(|m| m.as_str().to_string());
            // Look ahead for function name
            let mut fn_name = "unknown".to_string();
            for j in (idx + 1)..lines.len().min(idx + 10) {
                if let Some(fcap) = re_fn.captures(lines[j]) {
                    fn_name = fcap.get(1).unwrap().as_str().to_string();
                    break;
                }
            }
            annotations.push(Annotation {
                function_name: fn_name,
                kind: "implement".to_string(),
                target_cid,
                range: Range {
                    start: Position { line: line_num, character: 0 },
                    end: Position { line: line_num + 1, character: 0 },
                },
            });
        }

        if re_contract.is_match(line_text) {
            let mut fn_name = "unknown".to_string();
            for j in (idx + 1)..lines.len().min(idx + 10) {
                if let Some(fcap) = re_fn.captures(lines[j]) {
                    fn_name = fcap.get(1).unwrap().as_str().to_string();
                    break;
                }
            }
            annotations.push(Annotation {
                function_name: fn_name,
                kind: "contract".to_string(),
                target_cid: None,
                range: Range {
                    start: Position { line: line_num, character: 0 },
                    end: Position { line: line_num + 1, character: 0 },
                },
            });
        }

        if re_verify.is_match(line_text) {
            let mut fn_name = "unknown".to_string();
            for j in (idx + 1)..lines.len().min(idx + 10) {
                if let Some(fcap) = re_fn.captures(lines[j]) {
                    fn_name = fcap.get(1).unwrap().as_str().to_string();
                    break;
                }
            }
            annotations.push(Annotation {
                function_name: fn_name,
                kind: "verify".to_string(),
                target_cid: None,
                range: Range {
                    start: Position { line: line_num, character: 0 },
                    end: Position { line: line_num + 1, character: 0 },
                },
            });
        }
    }

    annotations
}
