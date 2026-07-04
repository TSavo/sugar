// SPDX-License-Identifier: Apache-2.0
//
// Generate the proof catalog used by examples/forall-vampire-showcase.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, cid_hex, Value as CValue};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, ContractBody, ContractMemento, Ed25519Seed,
    FlatAtom, ProofEnvelopeInput, ProofGraph,
};

fn json_to_canonical_value(j: &Json) -> Arc<CValue> {
    match j {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => CValue::integer(i128::from(n.as_i64().unwrap_or(0))),
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(json_to_canonical_value).collect()),
        Json::Object(map) => CValue::object(
            map.iter()
                .map(|(k, v)| (k.clone(), json_to_canonical_value(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn int_sort() -> Json {
    json!({"kind": "primitive", "name": "Int"})
}

fn var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
}

fn ctor(name: &str, args: Vec<Json>) -> Json {
    json!({"kind": "ctor", "name": name, "args": args})
}

fn eq(lhs: Json, rhs: Json) -> Json {
    json!({"kind": "atomic", "name": "=", "args": [lhs, rhs]})
}

fn pred(name: &str, args: Vec<Json>) -> Json {
    json!({"kind": "atomic", "name": name, "args": args})
}

fn forall_int(name: &str, body: Json) -> Json {
    json!({"kind": "forall", "name": name, "sort": int_sort(), "body": body})
}

fn good_group_right_identity_obligation() -> Json {
    let x = var("x");
    let y = var("y");
    let z = var("z");
    let e = ctor("e", vec![]);
    let mul_xy = ctor("mul", vec![x.clone(), y.clone()]);
    let mul_yz = ctor("mul", vec![y.clone(), z.clone()]);

    let assoc = forall_int(
        "x",
        forall_int(
            "y",
            forall_int(
                "z",
                eq(
                    ctor("mul", vec![mul_xy, z]),
                    ctor("mul", vec![x.clone(), mul_yz]),
                ),
            ),
        ),
    );
    let left_identity = forall_int("x", eq(ctor("mul", vec![e.clone(), var("x")]), var("x")));
    let left_inverse = forall_int(
        "x",
        eq(
            ctor("mul", vec![ctor("inv", vec![var("x")]), var("x")]),
            e.clone(),
        ),
    );
    let right_identity = forall_int("x", eq(ctor("mul", vec![var("x"), e]), var("x")));

    json!({
        "kind": "implies",
        "operands": [
            {"kind": "and", "operands": [assoc, left_identity, left_inverse]},
            right_identity
        ]
    })
}

fn bad_false_universal_obligation() -> Json {
    forall_int("x", pred("must_hold", vec![var("x")]))
}

fn write_solver_config(proof_dir: &Path) -> Result<(), Box<dyn std::error::Error>> {
    fs::write(
        proof_dir.join("config.toml"),
        r#"[solvers]

[solvers.dispatch]
"first-order" = "vampire"
default = "z3"

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 1
version = "4.x"

[solvers.vampire]
binary = "vampire"
ir_compiler = "smt-lib-v2.6"
flags = ["--input_syntax", "smtlib2", "--output_mode", "smtcomp"]
timeout_seconds = 10
version = "5.x"
"#,
    )?;
    Ok(())
}

fn write_fixture(project: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let proof_dir = project.join(".sugar");
    fs::create_dir_all(&proof_dir)?;
    write_solver_config(&proof_dir)?;

    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let mut graph = ProofGraph::new();
    let metadata = graph.register_atom(FlatAtom::empty_metadata());
    for (name, inv) in [
        (
            "forall_vampire_good_right_identity",
            good_group_right_identity_obligation(),
        ),
        (
            "forall_vampire_bad_false_universal",
            bad_false_universal_obligation(),
        ),
    ] {
        let inv = graph.register_atom(FlatAtom::new(json_to_canonical_value(&inv)));
        let body = graph.register_body(ContractBody::new_inv(&inv));
        graph.register_contract(ContractMemento::new_with_metadata_at(
            name,
            &body,
            &metadata,
            signer_seed,
            "2026-06-09T00:00:00.000Z",
        ));
    }

    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@example/forall-vampire".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: "2026-06-09T00:00:00.000Z".into(),
    });
    let hex = cid_hex(&built.cid).unwrap();
    fs::write(proof_dir.join(format!("{hex}.proof")), &built.bytes)?;
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let project = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("usage: forall_vampire_fixture <project-dir>")?;
    if project.exists() {
        fs::remove_dir_all(&project)?;
    }
    fs::create_dir_all(&project)?;
    write_fixture(&project)?;
    println!("{}", project.display());
    Ok(())
}
