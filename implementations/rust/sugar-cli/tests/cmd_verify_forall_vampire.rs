// SPDX-License-Identifier: Apache-2.0
//
// End-to-end quantified-dispatch showcase:
// a real forall obligation that z3 does not close in the gate probe,
// routed through verify to Vampire, with GOOD/BAD verdicts read from
// the JSON receipt shape.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, cid_hex, Value as CValue};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, ContractBody, ContractMemento, Ed25519Seed,
    FlatAtom, ProofEnvelopeInput, ProofGraph,
};

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-verify-forall-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn install_smt_compiler_manifest(project: &Path) {
    let manifest_dir = project.join(".sugar").join("ir-compilers").join("smt-lib");
    fs::create_dir_all(&manifest_dir).expect("mkdir ir compiler manifest");
    let rust_workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-cli has a parent workspace");
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            r#"name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["cargo", "run", "-p", "sugar-ir-compiler-smt-lib", "--bin", "sugar-ir-smt-lib", "--quiet", "--"]
working_dir = "{}"
dialects = ["smt-lib-v2.6"]
"#,
            rust_workspace.display()
        ),
    )
    .expect("write ir compiler manifest");
}

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

fn solver_available(binary: &str) -> bool {
    Command::new(binary)
        .arg("--version")
        .output()
        .map(|o| o.status.success() || !o.stdout.is_empty() || !o.stderr.is_empty())
        .unwrap_or(false)
}

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
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

fn forall(name: &str, sort: Json, body: Json) -> Json {
    json!({"kind": "forall", "name": name, "sort": sort, "body": body})
}

fn forall_int(name: &str, body: Json) -> Json {
    forall(name, int_sort(), body)
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

fn push_direct_obligation_contract(
    graph: &mut ProofGraph,
    name: &str,
    inv: Json,
    signer_seed: Ed25519Seed,
    declared_at: &str,
) {
    let metadata = graph.register_atom(FlatAtom::empty_metadata());
    let inv_atom = graph.register_atom(FlatAtom::new(json_to_canonical_value(&inv)));
    let body = graph.register_body(ContractBody::new_inv(&inv_atom));
    graph.register_contract(ContractMemento::new_obligation_with_metadata_at(
        name,
        &body,
        &metadata,
        signer_seed,
        declared_at,
    ));
}

fn publish_forall_project() -> PathBuf {
    let dir = unique_dir("vampire");
    let proof_dir = dir.join(".sugar");
    fs::create_dir_all(&proof_dir).expect("mkdir .sugar");
    install_smt_compiler_manifest(&dir);
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
    )
    .expect("write solver config");

    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let mut graph = ProofGraph::new();
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
        push_direct_obligation_contract(
            &mut graph,
            name,
            inv,
            signer_seed,
            "2026-06-09T00:00:00.000Z",
        );
    }

    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@test/forall-vampire".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: "2026-06-09T00:00:00.000Z".into(),
    });
    let hex = cid_hex(&built.cid).unwrap();
    fs::write(proof_dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    dir
}

fn run_verify_json_with_code(project: &Path) -> (Json, i32) {
    let witnesses = project.join("witnesses-out");
    let out = Command::new(sugar_bin())
        .arg("verify")
        .arg("--project")
        .arg(project)
        .arg("--emit-witnesses")
        .arg(&witnesses)
        .arg("--json")
        .output()
        .expect("spawn sugar verify");
    let stdout = String::from_utf8_lossy(&out.stdout);
    let receipt = serde_json::from_str(&stdout)
        .unwrap_or_else(|e| panic!("verify JSON parse failed: {e}\nstdout: {stdout}"));
    (receipt, out.status.code().unwrap_or(-1))
}

#[test]
fn verify_forall_obligations_route_to_vampire_with_good_and_bad_receipts() {
    if !solver_available("vampire") {
        eprintln!("vampire not on PATH: skipping quantified Vampire showcase test");
        return;
    }

    let project = publish_forall_project();
    let (receipt, code) = run_verify_json_with_code(&project);

    assert_eq!(receipt["kind"], "verification-receipt");
    assert_eq!(receipt["totalClaims"], 2, "receipt: {receipt}");
    assert_eq!(receipt["ok"], false, "bad twin must keep the run non-green");
    assert_eq!(
        code, 1,
        "bad twin must refuse with EXIT_VERIFY_FAIL; receipt: {receipt}"
    );

    let claims = receipt["claims"].as_array().expect("claims array");
    let claim_by_name = |name: &str| -> &Json {
        claims
            .iter()
            .find(|claim| claim["property"] == name)
            .unwrap_or_else(|| panic!("missing claim {name}; receipt: {receipt}"))
    };

    let good = claim_by_name("forall_vampire_good_right_identity");
    assert_eq!(good["obligationClass"], "first-order", "claim: {good}");
    assert_eq!(good["routedSolver"], "vampire", "claim: {good}");
    assert_eq!(good["status"], "discharged", "claim: {good}");
    assert_eq!(good["pass"], true, "claim: {good}");
    assert!(
        good["dischargingSolver"]
            .as_str()
            .unwrap_or_default()
            .starts_with("vampire@"),
        "claim: {good}"
    );

    let bad = claim_by_name("forall_vampire_bad_false_universal");
    assert_eq!(bad["obligationClass"], "first-order", "claim: {bad}");
    assert_eq!(bad["routedSolver"], "vampire", "claim: {bad}");
    assert_eq!(bad["status"], "unsatisfied", "claim: {bad}");
    assert_eq!(bad["pass"], false, "claim: {bad}");
    assert!(bad["witnessCid"].is_null(), "claim: {bad}");

    let _ = fs::remove_dir_all(project);
}
