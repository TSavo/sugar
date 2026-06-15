// SPDX-License-Identifier: Apache-2.0
//
// Generate the proof catalog used by examples/forall-vampire-showcase.

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, encode_jcs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, Ed25519Seed, ProofEnvelopeInput,
};

fn json_to_canonical_jcs(j: &Json) -> String {
    fn to_cv(j: &Json) -> std::sync::Arc<sugar_canonicalizer::Value> {
        use sugar_canonicalizer::Value as CV;
        match j {
            Json::Null => CV::null(),
            Json::Bool(b) => CV::boolean(*b),
            Json::Number(n) => CV::integer(i128::from(n.as_i64().unwrap_or(0))),
            Json::String(s) => CV::string(s.clone()),
            Json::Array(items) => CV::array(items.iter().map(to_cv).collect()),
            Json::Object(map) => CV::object(
                map.iter()
                    .map(|(k, v)| (k.clone(), to_cv(v)))
                    .collect::<Vec<_>>(),
            ),
        }
    }
    encode_jcs(&to_cv(j))
}

fn flat_member(mut env: Json) -> (String, Vec<u8>) {
    if let Json::Object(map) = &mut env {
        map.remove("cid");
        map.remove("producerSignature");
    }
    let canonical = json_to_canonical_jcs(&env);
    let cid = blake3_512_of(canonical.as_bytes());
    (cid, canonical.into_bytes())
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

    let good_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": "forall_vampire_good_right_identity",
                "invVerification": "obligation",
                "inv": good_group_right_identity_obligation()
            }
        }
    });
    let bad_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": "forall_vampire_bad_false_universal",
                "invVerification": "obligation",
                "inv": bad_false_universal_obligation()
            }
        }
    });

    let mut members: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    let (good_cid, good_bytes) = flat_member(good_env);
    let (bad_cid, bad_bytes) = flat_member(bad_env);
    members.insert(good_cid, good_bytes);
    members.insert(bad_cid, bad_bytes);

    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@example/forall-vampire".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        members,
        signer_cid,
        signer_seed,
        declared_at: "2026-06-09T00:00:00.000Z".into(),
    });
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
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
