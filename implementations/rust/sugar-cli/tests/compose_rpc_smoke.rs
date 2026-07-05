// SPDX-License-Identifier: MIT OR Apache-2.0
//
// compose_rpc_smoke.rs: federation-witness test for `sugar compose --rpc`.
//
// Spawns the compiled `sugar` binary with `compose --rpc`, drives the
// JSON-RPC subprocess transport per CCP §6.3 (initialize + compose +
// shutdown), and asserts the composed CID matches the pinned hex value
// that libsugar's own compose_smoke.rs pins for the same algebra.
//
// "Same algebra produces the same CID via the canonical primitive" is
// the federation property CCP exists to guarantee. The Rust-link path
// (libsugar's compose_smoke.rs) and the JSON-RPC path (this file)
// hash to byte-identical bodies because both call the single canonical
// `compose_chain_contracts` function.
//
// Pinned CID: see libsugar::compose v1.0.0 conformance witness.
// Any CCP version bump that alters the algebra will change this CID
// and require regenerating both pins under the new version's signature.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde_json::{json, Value as JsonValue};

const PINNED_CID: &str = "blake3-512:36212b7bf7b9ccf264950940a33d64e1cfe88b6f4d8a47c01949fc64d9359d1813d6147aa2e1afe82b01e6e7ebcbe0a413683284b5f47ffef5bf364213304665";

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

/// Build the wire body for one of the trivial pure atoms used by
/// libsugar::compose_smoke. The shape matches WireFunctionContractMemento
/// in src/cmd_compose.rs; both atoms have an empty effect set, no body cid,
/// no aliasing mementos, an unknown locus, and one u32 formal whose post is
/// `result = <formal>`.
fn pure_identity_atom(fn_name: &str, formal: &str) -> JsonValue {
    json!({
        "fn_name": fn_name,
        "formals": [formal],
        "formal_sorts": [{"kind": "primitive", "name": "u32"}],
        "formal_regions": [],
        "return_sort": {"kind": "primitive", "name": "u32"},
        "return_region": null,
        "pre": {"kind": "atomic", "name": "true", "args": []},
        "post": {
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "result"},
                {"kind": "var", "name": formal}
            ]
        },
        "body_cid": null,
        "effects": {"effects": []},
        "locus": {"file": null, "line": 0, "col": 0},
        "auto_minted_mementos": [],
        "formal_idx": 0
    })
}

fn impure_identity_atom(fn_name: &str, formal: &str) -> JsonValue {
    let mut atom = pure_identity_atom(fn_name, formal);
    atom["effects"] = json!({
        "effects": [{"kind": "io"}]
    });
    atom
}

#[test]
fn compose_rpc_returns_pinned_cid() {
    let bin = sugar_bin();
    assert!(
        bin.exists(),
        "sugar test subject binary missing at {}; cargo should provide CARGO_BIN_EXE_sugar",
        bin.display()
    );

    let mut child = Command::new(&bin)
        .args(["compose", "--rpc"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("spawn sugar compose --rpc");

    let mut stdin = child.stdin.take().expect("stdin pipe");
    let stdout = child.stdout.take().expect("stdout pipe");
    let mut reader = BufReader::new(stdout);

    // initialize
    writeln!(
        stdin,
        "{}",
        json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        })
    )
    .unwrap();
    let init = read_response(&mut reader);
    assert_eq!(init["id"], json!(1));
    assert_eq!(
        init["result"]["protocol_version"],
        json!("sugar-compose/1"),
        "initialize must advertise the protocol version named in CCP §6.3"
    );
    assert_eq!(
        init["result"]["ccp_version"],
        json!("1.0.0"),
        "initialize must report libsugar::compose::CCP_VERSION"
    );

    // compose: two pure identity atoms (inner over `y`, outer over `x`).
    let inner = pure_identity_atom("inner", "y");
    let outer = pure_identity_atom("outer", "x");
    writeln!(
        stdin,
        "{}",
        json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "compose",
            "params": {
                "atoms": [inner, outer]
            }
        })
    )
    .unwrap();
    let compose = read_response(&mut reader);
    assert_eq!(compose["id"], json!(2));
    assert!(
        compose.get("error").is_none(),
        "compose returned error: {compose}"
    );
    let composed_cid = compose["result"]["composed_cid"]
        .as_str()
        .expect("composed_cid field");
    let body_jcs = compose["result"]["body_jcs"]
        .as_str()
        .expect("body_jcs field");
    assert!(
        composed_cid.starts_with("blake3-512:"),
        "composed_cid must be the spec's self-identifying form, got {composed_cid}"
    );
    assert!(
        !body_jcs.is_empty(),
        "body_jcs must be non-empty (canonical bytes of the composed memento)"
    );

    // Federation witness: same algebra, same canonical primitive,
    // therefore byte-identical CID.
    assert_eq!(
        composed_cid, PINNED_CID,
        "JSON-RPC compose CID must match libsugar's pinned CID via the canonical primitive"
    );

    // shutdown
    writeln!(
        stdin,
        "{}",
        json!({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "shutdown"
        })
    )
    .unwrap();
    let shutdown = read_response(&mut reader);
    assert_eq!(shutdown["id"], json!(3));
    assert_eq!(shutdown["result"], JsonValue::Null);

    drop(stdin);
    let status = child.wait().expect("wait child");
    assert!(
        status.success(),
        "sugar compose --rpc exited non-zero: {status:?}"
    );
}

#[test]
fn compose_rpc_impure_input_returns_refusal_memento_with_stable_cid() {
    let bin = sugar_bin();
    assert!(
        bin.exists(),
        "sugar test subject binary missing at {}; cargo should provide CARGO_BIN_EXE_sugar",
        bin.display()
    );

    let first = rpc_compose(json!([
        pure_identity_atom("inner", "y"),
        impure_identity_atom("outer", "x")
    ]));
    let second = rpc_compose(json!([
        pure_identity_atom("inner", "y"),
        impure_identity_atom("outer", "x")
    ]));

    for response in [&first, &second] {
        let err = response.get("error").expect("impure compose returns error");
        assert_eq!(err["kind"], json!("composition_refused"));
        let refusal_cid = err["refusal_cid"]
            .as_str()
            .expect("error includes refusal_cid");
        assert!(
            refusal_cid.starts_with("blake3-512:"),
            "refusal CID must be self-identifying, got {refusal_cid}"
        );
        assert_eq!(
            err["refusal"]["header"]["cid"],
            json!(refusal_cid),
            "error must carry the durable refusal artifact"
        );
        assert_eq!(
            err["refusal"]["header"]["failure_kind"],
            json!("impure-input")
        );
    }

    assert_eq!(
        first["error"]["refusal_cid"], second["error"]["refusal_cid"],
        "same impure input must produce deterministic refusal CID"
    );
}

fn rpc_compose(atoms: JsonValue) -> JsonValue {
    let bin = sugar_bin();
    let mut child = Command::new(&bin)
        .args(["compose", "--rpc"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("spawn sugar compose --rpc");

    let mut stdin = child.stdin.take().expect("stdin pipe");
    let stdout = child.stdout.take().expect("stdout pipe");
    let mut reader = BufReader::new(stdout);

    writeln!(
        stdin,
        "{}",
        json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "compose",
            "params": {"atoms": atoms}
        })
    )
    .unwrap();
    let response = read_response(&mut reader);
    drop(stdin);
    let status = child.wait().expect("wait child");
    assert!(
        status.success(),
        "sugar compose --rpc exited non-zero: {status:?}"
    );
    response
}

fn read_response<R: BufRead>(reader: &mut R) -> JsonValue {
    let mut line = String::new();
    let n = reader.read_line(&mut line).expect("read response line");
    assert!(n > 0, "EOF before response");
    serde_json::from_str(line.trim()).expect("parse response JSON")
}
