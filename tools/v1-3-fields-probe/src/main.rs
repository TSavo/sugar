// SPDX-License-Identifier: MIT OR Apache-2.0
//
// v1-3-fields-probe
//
// Emits JCS bytes + BLAKE3-512 hashes for every field tested in
// test_cross_impl_v1_3_fields.py. Output is structured so the
// Python test can consume it as pinned literals.
//
// The Value trees are hand-built here to exactly mirror the Python
// kit's construction in ir.py / proof_envelope.py, so the probe is
// self-contained and needs no dependency on sugar-ir-symbolic or
// sugar-proof-envelope.

use std::process::ExitCode;
use std::sync::Arc;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};

fn evidence_value() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("evidence")),
        ("proofType", Value::string("smt-lib")),
        (
            "certificate",
            Value::object([
                ("tool", Value::string("z3")),
                ("version", Value::string("4.13.0")),
                ("formulaHash", Value::string("blake3-512:aa")),
                ("proofData", Value::string("(proof ...)")),
            ]),
        ),
    ])
}

fn bridge_with_notes_value() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("bridge")),
        ("name", Value::string("myParseInt-implements-node24")),
        ("sourceSymbol", Value::string("myParseInt")),
        ("sourceLayer", Value::string("javascript")),
        ("sourceContractCid", Value::string("blake3-512:aaa")),
        ("targetContractCid", Value::string("blake3-512:bbb")),
        ("targetProofCid", Value::string("blake3-512:ccc")),
        ("targetLayer", Value::string("javascript")),
        ("notes", Value::string("shim bridge")),
    ])
}

fn bridge_no_notes_value() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("bridge")),
        ("name", Value::string("js-parseInt-to-ref")),
        ("sourceSymbol", Value::string("parseInt")),
        ("sourceLayer", Value::string("javascript")),
        ("sourceContractCid", Value::string("blake3-512:js-parseInt-v24")),
        ("targetContractCid", Value::string("blake3-512:ref-parseInt-v1")),
        ("targetProofCid", Value::string("blake3-512:ecma262-v14-proof")),
        ("targetLayer", Value::string("reference")),
    ])
}

fn int_sort_value() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("primitive")),
        ("name", Value::string("Int")),
    ])
}

fn contract_inv_value() -> Arc<Value> {
    // inv: gt(make_var("x"), num(0))
    //   = atomic with name ">" and args [var("x"), const(0, Int)]
    Value::object([
        ("kind", Value::string("atomic")),
        ("name", Value::string(">")),
        (
            "args",
            Value::array(vec![
                Value::object([
                    ("kind", Value::string("var")),
                    ("name", Value::string("x")),
                ]),
                Value::object([
                    ("kind", Value::string("const")),
                    ("value", Value::integer(0)),
                    ("sort", int_sort_value()),
                ]),
            ]),
        ),
    ])
}

fn contract_with_evidence_value() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("contract")),
        ("name", Value::string("contract1")),
        ("outBinding", Value::string("out")),
        ("inv", contract_inv_value()),
        ("evidence", evidence_value()),
    ])
}

fn env_with_binary_cid_value() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("catalog")),
        ("name", Value::string("@x/y")),
        ("version", Value::string("1.0.0")),
        (
            "members",
            Value::object([("blake3-512:mem1", Value::string("7b7d"))]),
        ),
        ("signer", Value::string("blake3-512:signer")),
        ("declaredAt", Value::string("2026-05-02T00:00:00.000Z")),
        ("binaryCid", Value::string("blake3-512:binary")),
    ])
}

fn emit(label: &str, v: &Arc<Value>) {
    let jcs = encode_jcs(v);
    let hash = blake3_512_of(jcs.as_bytes());
    println!("# {label}");
    println!("JCS:    {jcs}");
    println!("BLAKE3: {hash}");
    println!();
}

fn run() -> Result<(), String> {
    emit("EvidenceTerm (smt-lib)", &evidence_value());

    emit("BridgeDecl WITH notes", &bridge_with_notes_value());

    emit("BridgeDecl WITHOUT notes", &bridge_no_notes_value());

    emit("ContractDecl WITH evidence (inv: x > 0)", &contract_with_evidence_value());

    emit("ProofEnvelope body WITH binaryCid", &env_with_binary_cid_value());

    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("v1-3-fields-probe: {e}");
            ExitCode::FAILURE
        }
    }
}
