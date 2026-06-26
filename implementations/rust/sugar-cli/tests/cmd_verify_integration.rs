// SPDX-License-Identifier: Apache-2.0
//
// End-to-end integration test for `sugar verify` (PR-9, #1405).
//
// Builds a real `.proof` catalog on disk (a contract claim + its bridge,
// minted via the claim-envelope kit, exactly as `sugar lift`/`mint`
// would emit), then invokes the `sugar verify --project <dir> --json`
// binary and asserts the verification receipt:
//
//   - the contract claim is enumerated and discharged,
//   - the obligation was routed through the solver-dispatch table to the
//     z3 SMT seat,
//   - a signed witness memento was minted citing the discharging solver,
//   - the receipt's JSON shape carries per-claim solver + witness CID.
//
// This is the load-bearing "shows the discharge flow end-to-end" check.
// It requires `z3` on PATH; when z3 is absent the test asserts the
// graceful-degradation path instead (the verb still emits a receipt and
// routes the obligation, the solver row just reports undecidable).

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, Value as CValue};
use sugar_claim_envelope::{
    mint_bridge, mint_contract, Authoring, MintBridgeArgs, MintContractArgs, MintedEnvelope,
};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, BridgeMemento, ClaimContractMemento,
    ContractMementoRef, Ed25519Seed, ProofEnvelopeInput, ProofGraph,
};

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-verify-it-{stamp}-{suffix}"));
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

fn json_to_cvalue(j: &Json) -> Arc<CValue> {
    match j {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => CValue::integer(i128::from(n.as_i64().unwrap_or(0))),
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(json_to_cvalue).collect()),
        Json::Object(map) => CValue::object(
            map.iter()
                .map(|(k, v)| (k.clone(), json_to_cvalue(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn push_claim_contract(graph: &mut ProofGraph, minted: MintedEnvelope) -> String {
    let cid = minted.cid.clone();
    let memento = ClaimContractMemento::new(minted.canonical_bytes);
    assert_eq!(memento.cid().as_str(), cid);
    graph.push_claim_contract(memento);
    cid
}

fn push_bridge(graph: &mut ProofGraph, minted: MintedEnvelope) -> String {
    let cid = minted.cid.clone();
    let memento = BridgeMemento::new(minted.canonical_bytes);
    assert_eq!(memento.cid().as_str(), cid);
    graph.push_bridge(memento);
    cid
}

/// Publish a `.proof` catalog with one contract claim plus a self-call
/// bridge, in the v1.1-flat `evidence.body` shape `enumerate_callsites`
/// consumes, so it yields exactly one callsite. The TARGET contract's
/// `pre` is `forall n:Int. <body>` — the obligation that gets
/// discharged. The SOURCE contract carries a single `parseInt` ctor in
/// its `post` slot so exactly one callsite enumerates. Returns the
/// project dir.
fn publish_claim_project(suffix: &str, name: &str, target_pre_body: Json) -> PathBuf {
    let dir = unique_dir(suffix);
    let proof_dir = dir.join(".sugar");
    fs::create_dir_all(&proof_dir).expect("mkdir .sugar");
    install_smt_compiler_manifest(&dir);

    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let declared_at = "2026-04-30T00:00:00.000Z";

    let mut graph = ProofGraph::new();

    let target_contract = mint_contract(&MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        contract_name: "parseInt_target".into(),
        pre: Some(json_to_cvalue(&json!({
            "kind": "forall",
            "name": "n",
            "sort": {"kind": "primitive", "name": "Int"},
            "body": target_pre_body
        }))),
        post: None,
        inv: None,
        out_binding: "result".into(),
        produced_by: "test".into(),
        produced_at: declared_at.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    })
    .expect("mint target contract");
    let target_cid = push_claim_contract(&mut graph, target_contract);

    let source_contract = mint_contract(&MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        contract_name: name.into(),
        pre: None,
        post: Some(json_to_cvalue(&json!({
            "kind": "atomic", "name": "=",
            "args": [
                {"kind": "var", "name": "out"},
                {"kind": "ctor", "name": "parseInt",
                 "args": [{"kind": "var", "name": "s"}]}
            ]
        }))),
        inv: None,
        out_binding: "out".into(),
        produced_by: "test".into(),
        produced_at: declared_at.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    })
    .expect("mint source contract");
    push_claim_contract(&mut graph, source_contract);

    let bridge = mint_bridge(&MintBridgeArgs {
        produced_by: "test".into(),
        produced_at: declared_at.into(),
        source_symbol: "parseInt".into(),
        source_layer: "ts".into(),
        target_contract: ContractMementoRef::new(target_cid),
        target_layer: "rust-kit".into(),
        ir_arg_sorts: vec!["String".into()],
        ir_return_sort: "Int".into(),
        notes: String::new(),
        signer_seed,
        target_proof_cid: None,
        callsite: None,
    });
    push_bridge(&mut graph, bridge);

    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let input = ProofEnvelopeInput {
        name: format!("@test/verify-{suffix}"),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: declared_at.into(),
    };
    let built = build_proof_envelope(&input);
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    fs::write(proof_dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    dir
}

/// A valid linear-arithmetic claim: `forall n:Int. n >= n` (a
/// tautology, so z3 returns unsat for the negation = discharged).
fn publish_lia_claim_project() -> PathBuf {
    publish_claim_project(
        "lia",
        "parseInt",
        json!({
            "kind": "atomic", "name": ">=",
            "args": [
                {"kind": "var", "name": "n"},
                {"kind": "var", "name": "n"}
            ]
        }),
    )
}

/// A VIOLATED linear-arithmetic claim: `forall n:Int. n > n` (false for
/// every n, so z3 returns sat for the negation = unsatisfied). No valid
/// witness must be minted for this claim.
fn publish_violated_claim_project() -> PathBuf {
    publish_claim_project(
        "violated",
        "parseInt",
        json!({
            "kind": "atomic", "name": ">",
            "args": [
                {"kind": "var", "name": "n"},
                {"kind": "var", "name": "n"}
            ]
        }),
    )
}

fn sugar_bin() -> PathBuf {
    // CARGO_BIN_EXE_<name> is set by cargo for integration tests of a
    // binary crate.
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Run `sugar verify --project <p> --json` and return (receipt, exit_code).
fn run_verify_json_with_code(project: &Path, witness_dir: &Path) -> (Json, i32) {
    let out = Command::new(sugar_bin())
        .arg("verify")
        .arg("--project")
        .arg(project)
        .arg("--emit-witnesses")
        .arg(witness_dir)
        .arg("--json")
        .output()
        .expect("spawn sugar verify");
    let stdout = String::from_utf8_lossy(&out.stdout);
    let receipt = serde_json::from_str(&stdout)
        .unwrap_or_else(|e| panic!("verify JSON parse failed: {e}\nstdout: {stdout}"));
    (receipt, out.status.code().unwrap_or(-1))
}

fn run_verify_json(project: &Path, witness_dir: &Path) -> Json {
    run_verify_json_with_code(project, witness_dir).0
}

#[test]
fn verify_empty_catalog_is_not_a_successful_proof() {
    // A project with no .proof claims: verify must emit a receipt, but it
    // must not report a successful proof when it checked zero claims.
    let dir = unique_dir("empty");
    let witnesses = dir.join("w");
    let (receipt, code) = run_verify_json_with_code(&dir, &witnesses);
    assert_eq!(receipt["kind"], "verification-receipt");
    assert_eq!(receipt["totalClaims"], 0);
    assert_eq!(receipt["ok"], false);
    assert_ne!(code, 0, "zero-claim verify must exit nonzero: {receipt}");
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn verify_lia_claim_routes_to_smt_and_mints_witness() {
    let project = publish_lia_claim_project();
    let witnesses = project.join("witnesses-out");
    let receipt = run_verify_json(&project, &witnesses);

    // Emit the receipt under a stable marker so a real sample can be
    // captured for documentation:
    //   SUGAR_VERIFY_SAMPLE=1 cargo test ... -- --nocapture
    if std::env::var("SUGAR_VERIFY_SAMPLE").is_ok() {
        eprintln!(
            "SAMPLE-RECEIPT\n{}",
            serde_json::to_string_pretty(&receipt).unwrap()
        );
    }

    assert_eq!(receipt["kind"], "verification-receipt");
    assert_eq!(
        receipt["totalClaims"], 1,
        "exactly one contract claim enumerated; receipt: {receipt}"
    );

    let claims = receipt["claims"].as_array().expect("claims array");
    let claim = &claims[0];

    // The solver-dispatch table routed the LIA obligation to the z3 SMT
    // seat. This is the "at least one obligation routed to SMT-LIB/Z3"
    // requirement, observed end-to-end through the binary.
    assert_eq!(
        claim["routedSolver"], "z3",
        "LIA obligation must route to the z3 SMT seat; claim: {claim}"
    );
    assert_eq!(
        claim["obligationClass"], "linear-arithmetic",
        "obligation must classify as linear-arithmetic; claim: {claim}"
    );

    if z3_available() {
        // z3 present: the obligation discharges and a signed witness is
        // minted citing the discharging solver.
        assert_eq!(
            claim["pass"], true,
            "LIA `> 0` obligation must discharge with z3; claim: {claim}"
        );
        let solver = claim["dischargingSolver"].as_str().unwrap_or("");
        assert!(
            solver.starts_with("z3@"),
            "discharging solver must be z3; got `{solver}`"
        );
        let witness_cid = claim["witnessCid"].as_str().expect("witness minted");
        assert!(witness_cid.starts_with("blake3-512:"));

        // The minted witness file exists, re-parses, and cites the solver.
        let hex = witness_cid.trim_start_matches("blake3-512:");
        let wpath = witnesses.join(format!("witness-{hex}.json"));
        let bytes = fs::read_to_string(&wpath).expect("witness file written");
        let witness: sugar_ir_types::WitnessMemento =
            serde_json::from_str(&bytes).expect("witness re-parses");
        assert_eq!(witness.outcome, "pass");
        assert!(witness.signature.is_some(), "witness must be signed");
        assert_eq!(
            witness.measurements["solver"].as_str().unwrap_or(""),
            solver,
            "witness must cite the discharging solver"
        );
        assert_eq!(receipt["ok"], true);
    } else {
        // z3 absent: the verb still routes the obligation through the
        // dispatch table and emits a receipt; the row reports the
        // solver could not decide (no witness). Graceful degradation.
        eprintln!("z3 not on PATH: asserting graceful-degradation path");
        assert_eq!(claim["pass"], false);
        assert!(claim["witnessCid"].is_null());
    }

    let _ = fs::remove_dir_all(&project);
}

/// NEGATIVE / regression test: a claim that VIOLATES its contract must
/// fail loudly. `forall n:Int. n > n` is false for every n, so z3
/// returns sat for the negation = `unsatisfied`. The verb must report
/// `pass: false`, `status: unsatisfied`, exit code 1
/// (`EXIT_VERIFY_FAIL`), and mint NO witness. Without this the "catch"
/// path ships untested — this is the gate that proves verify can fail.
#[test]
fn verify_violated_claim_fails_and_mints_no_witness() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping the violated-claim negative test");
        return;
    }
    let project = publish_violated_claim_project();
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    let claim = &receipt["claims"].as_array().expect("claims")[0];

    // The obligation routed to z3 (LIA), and z3 found it unsatisfiable:
    // the claim is VIOLATED.
    assert_eq!(claim["obligationClass"], "linear-arithmetic");
    assert_eq!(
        claim["status"], "unsatisfied",
        "violated `n > n` claim must be unsatisfied; claim: {claim}"
    );
    assert_eq!(
        claim["pass"], false,
        "violated claim must not pass; claim: {claim}"
    );

    // No witness for a violated claim.
    assert!(
        claim["witnessCid"].is_null(),
        "no witness may be minted for a violated claim; claim: {claim}"
    );
    assert_eq!(receipt["ok"], false);

    // No witness file was written.
    let witness_files: Vec<_> = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).collect())
        .unwrap_or_default();
    assert!(
        witness_files.is_empty(),
        "witness dir must be empty for a violated claim; found {} files",
        witness_files.len()
    );

    // Exit code 1 = EXIT_VERIFY_FAIL (a hard violation, not a solver miss).
    assert_eq!(
        code, 1,
        "violated claim must exit 1 (EXIT_VERIFY_FAIL); got {code}"
    );

    let _ = fs::remove_dir_all(&project);
}
