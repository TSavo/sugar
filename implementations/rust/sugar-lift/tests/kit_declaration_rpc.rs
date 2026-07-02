use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};

use serde_json::{json, Value};
use sugar_claim_envelope::{KitDeclaration, KIT_DECLARATION_RPC_METHOD};

#[test]
fn lift_rpc_serves_rust_contracts_kit_declaration() {
    let mut child = Command::new(env!("CARGO_BIN_EXE_sugar-lift"))
        .arg("--rpc")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("spawn sugar-lift --rpc");
    let mut stdin = child.stdin.take().expect("stdin");
    let stdout = child.stdout.take().expect("stdout");
    let mut reader = BufReader::new(stdout);

    writeln!(
        stdin,
        "{}",
        json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}})
    )
    .expect("write initialize");
    let init_response = read_response(&mut reader);
    assert!(
        init_response.get("error").is_none(),
        "initialize failed: {init_response}"
    );

    writeln!(
        stdin,
        "{}",
        json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": KIT_DECLARATION_RPC_METHOD,
            "params": {}
        })
    )
    .expect("write kit declaration request");
    let declaration_response = read_response(&mut reader);
    assert!(
        declaration_response.get("error").is_none(),
        "kit declaration RPC failed: {declaration_response}"
    );

    let declaration: KitDeclaration = serde_json::from_value(
        declaration_response
            .get("result")
            .cloned()
            .expect("kit declaration result"),
    )
    .expect("kit declaration schema");
    declaration.validate().expect("valid declaration");

    assert_eq!(declaration.kit.id, "sugar-lift");
    assert_eq!(declaration.kit.language, "rust");
    assert_method_declared(&declaration, "initialize");
    assert_method_declared(&declaration, "lift");
    assert_method_declared(&declaration, "shutdown");
    assert_method_declared(&declaration, KIT_DECLARATION_RPC_METHOD);
    assert_eq!(declaration.proof_resolution.strategy, "cargo");
    // concept hub removed: the kit no longer declares a concept vocabulary.

    writeln!(
        stdin,
        "{}",
        json!({"jsonrpc":"2.0","id":3,"method":"shutdown","params":{}})
    )
    .expect("write shutdown");
    let shutdown_response = read_response(&mut reader);
    assert!(
        shutdown_response.get("error").is_none(),
        "shutdown failed: {shutdown_response}"
    );
    drop(stdin);
    let status = child.wait().expect("wait for sugar-lift");
    assert!(status.success(), "sugar-lift exited with {status}");
}

#[test]
fn lift_rpc_refuses_request_without_method() {
    let mut child = Command::new(env!("CARGO_BIN_EXE_sugar-lift"))
        .arg("--rpc")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("spawn sugar-lift --rpc");
    let mut stdin = child.stdin.take().expect("stdin");
    let stdout = child.stdout.take().expect("stdout");
    let mut reader = BufReader::new(stdout);

    writeln!(stdin, "{}", json!({"jsonrpc":"2.0","id":41,"params":{}}))
        .expect("write malformed request");
    let response = read_response(&mut reader);
    let message = response
        .get("error")
        .and_then(|error| error.get("message"))
        .and_then(Value::as_str)
        .expect("missing-method request must return an error");
    assert!(
        message.contains("missing method"),
        "error must name the missing method field: {response}"
    );

    drop(stdin);
    let status = child.wait().expect("wait for sugar-lift");
    assert!(status.success(), "sugar-lift exited with {status}");
}

fn read_response(reader: &mut BufReader<std::process::ChildStdout>) -> Value {
    let mut line = String::new();
    reader.read_line(&mut line).expect("read response");
    assert!(!line.is_empty(), "child closed stdout before response");
    serde_json::from_str(&line).expect("JSON-RPC response")
}

fn assert_method_declared(declaration: &KitDeclaration, method: &str) {
    assert!(
        declaration
            .rpc
            .methods
            .iter()
            .any(|declared| declared.name == method),
        "declaration must advertise {method}: {:?}",
        declaration.rpc.methods
    );
}
