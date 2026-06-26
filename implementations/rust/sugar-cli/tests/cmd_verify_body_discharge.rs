// SPDX-License-Identifier: Apache-2.0
//
// End-to-end body-discharge proof for `sugar verify` (PR-22, #1440).
//
// THE LOAD-BEARING TEST. Unlike `cmd_verify_integration.rs` (whose claims
// are body-INDEPENDENT tautologies `n >= n` / `n > n` that discharge in
// pure LIA with no user symbol), this test proves the verification SPINE:
// that `verify` reduces a harvested assertion THROUGH the callee function
// BODY, so the solver sees the body's value-semantics instead of an
// uninterpreted symbol.
//
// The example: `fn double(x) = x * 2`, harvested test `assert_eq!(double(3), 6)`.
//
//   POSITIVE: the body-derived op-contract for `double` carries
//     `post = (result == *(x, 2))`. verify runs `wp(double(3), result==6)`
//     -> `*(3, 2) == 6` -> z3 discharges -> pass, signed witness minted.
//
//   NEGATIVE: break the body to `x * 3` -> `post = (result == *(x, 3))` ->
//     `wp(double(3), result==6)` -> `*(3, 3) == 6` -> z3 finds `9 != 6` SAT
//     on the negation -> Unsatisfied, exit 1, NO witness. The negative case
//     fails HONESTLY (Unsatisfied, not Undecidable) precisely because no
//     uninterpreted symbol survives the body reduction.
//
// Requires `z3` on PATH; skips the solver-dependent asserts otherwise.

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
    let p = std::env::temp_dir().join(format!("sugar-verify-body-{stamp}-{suffix}"));
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

fn string_array(value: &Json) -> Vec<String> {
    value
        .as_array()
        .expect("array")
        .iter()
        .map(|item| item.as_str().expect("string").to_string())
        .collect()
}

fn cvalue_array(value: &Json) -> Vec<Arc<CValue>> {
    value
        .as_array()
        .expect("array")
        .iter()
        .map(json_to_cvalue)
        .collect()
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

/// An Int constant IR term.
fn int_const(n: i64) -> Json {
    json!({"kind": "const", "value": n, "sort": {"kind": "primitive", "name": "Int"}})
}

/// Publish a `.proof` catalog proving (or refuting) `double(3) == 6`,
/// where `double`'s body is `x * <body_factor>`.
///
/// Three members, in the v1.1-flat `evidence.body` shape:
///   - TARGET contract `double`: the body-derived op-contract. Its `post`
///     is `result == *(x, <body_factor>)` (the lifted body) and it carries
///     `formals: ["x"]`. This is what the catalog resolver projects into an
///     `OpContractInfo` for wp.
///   - SOURCE contract: carries the harvested assertion
///     `=(double(3), 6)` in its `inv` slot (one bridged callsite).
///   - BRIDGE: `sourceSymbol "double" -> targetContractCid <double>`.
fn publish_double_project(suffix: &str, body_factor: i64) -> PathBuf {
    // The harvested test assertion `assert_eq!(double(3), 6)` -> inv =(call, 6).
    let inv = json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "ctor", "name": "double", "args": [int_const(3)]},
            int_const(6)
        ]
    });
    publish_double_project_with_inv(suffix, body_factor, inv)
}

/// Like `publish_double_project` but with an explicit harvested `inv`
/// formula, so a test can drive an assertion shape OTHER than
/// `=(<call>, <expected>)` (the reviewer's `<=` false-green probe).
fn publish_double_project_with_inv(suffix: &str, body_factor: i64, inv: Json) -> PathBuf {
    // The body-derived op-contract for `double`: post = result == *(x, k).
    let post = json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "var", "name": "result"},
            {"kind": "ctor", "name": "*", "args": [
                {"kind": "var", "name": "x"},
                int_const(body_factor)
            ]}
        ]
    });
    publish_double_project_full(suffix, post, inv)
}

/// Fully parameterized publisher: explicit body-derived op-contract `post`
/// AND harvested `inv`. The target ALWAYS carries `formals: ["x"]` (it is a
/// body-bearing op-contract) and NO `pre`. Lets a test drive a `post` that
/// is not a `result == <expr>` equation -- the trigger for the second
/// false-green the reviewer found, where the resolver drops the contract
/// and the claim falls through to the vacuous branch.
fn publish_double_project_full(suffix: &str, post: Json, inv: Json) -> PathBuf {
    publish_double_project_with_formals(
        suffix,
        json!(["x"]),
        json!([{"kind": "primitive", "name": "Int"}]),
        post,
        inv,
    )
}

/// Like `publish_double_project_full` but with an explicit `formals` /
/// `formalSorts` on the target op-contract. Lets a test drive the zero-arg
/// `formals: []` shape -- a body-derived contract for a zero-parameter
/// function is STILL body-bearing (it has a body, just no parameters), and
/// must not slip into the vacuous-discharge branch. The `double(3)` callsite
/// from `inv` still enumerates regardless of the target's formals count.
fn publish_double_project_with_formals(
    suffix: &str,
    formals: Json,
    formal_sorts: Json,
    post: Json,
    inv: Json,
) -> PathBuf {
    let dir = unique_dir(suffix);
    let proof_dir = dir.join(".sugar");
    fs::create_dir_all(&proof_dir).expect("mkdir .sugar");
    install_smt_compiler_manifest(&dir);

    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let declared_at = "2026-05-23T00:00:00.000Z";

    let mut graph = ProofGraph::new();
    let formals_vec = string_array(&formals);
    let formal_sorts_vec = cvalue_array(&formal_sorts);

    // The body-derived op-contract for `double`: carries `formals` (so it is
    // body-bearing) and the supplied `post`; NO `pre`.
    let target_contract = mint_contract(&MintContractArgs {
        evidence_term: None,
        formals: formals_vec.clone(),
        emit_empty_formals: formals_vec.is_empty(),
        formal_sorts: formal_sorts_vec,
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        contract_name: "double".into(),
        pre: None,
        post: Some(json_to_cvalue(&post)),
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

    // The harvested test assertion in the source contract's `inv` slot
    // (one bridged callsite). The default is `=(double(3), 6)`.
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
        contract_name: "double_test".into(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(&inv)),
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
    .expect("mint source contract");
    push_claim_contract(&mut graph, source_contract);

    // The bridge: double (sourceSymbol) -> the body-derived contract.
    let bridge = mint_bridge(&MintBridgeArgs {
        produced_by: "test".into(),
        produced_at: declared_at.into(),
        source_symbol: "double".into(),
        source_layer: "rust".into(),
        target_contract: ContractMementoRef::new(target_cid),
        target_layer: "rust-kit".into(),
        ir_arg_sorts: vec!["Int".into()],
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
        name: format!("@test/verify-body-{suffix}"),
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

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

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

/// POSITIVE: `double(x) = x*2`, `assert_eq!(double(3), 6)`. The body
/// reduction yields `*(3, 2) == 6`; z3 discharges; a signed witness is
/// minted. This is the proof that verify discharges a real BODY-obligation
/// (not a body-independent tautology).
#[test]
fn verify_double_body_discharges_and_mints_witness() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping body-discharge positive test");
        return;
    }
    let project = publish_double_project("pos", 2);
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    assert_eq!(receipt["kind"], "verification-receipt");
    assert_eq!(
        receipt["totalClaims"], 1,
        "exactly one body-bearing callsite enumerated; receipt: {receipt}"
    );
    let claim = &receipt["claims"].as_array().expect("claims")[0];

    // The body reduction left a concrete LIA formula `*(3,2) == 6` — NO
    // uninterpreted `double` symbol. So z3 discharges it.
    assert_eq!(
        claim["pass"], true,
        "double(3)==6 must discharge through the body x*2; claim: {claim}"
    );
    assert_eq!(
        claim["status"], "discharged",
        "positive body-obligation must be discharged (not undecidable); claim: {claim}"
    );
    assert_eq!(
        claim["bodyDischargeTier"], "body-call-expected",
        "standard body-discharge route must be named in the receipt; claim: {claim}"
    );

    let solver = claim["dischargingSolver"].as_str().unwrap_or("");
    assert!(
        solver.starts_with("z3@"),
        "discharging solver must be z3; got `{solver}`"
    );

    // A signed witness was minted. Capture its CID for the #1440 report:
    //   cargo test verify_double_body_discharges -- --nocapture
    let witness_cid = claim["witnessCid"].as_str().expect("witness minted");
    assert!(witness_cid.starts_with("blake3-512:"));
    eprintln!("POSITIVE_WITNESS_CID={witness_cid}");

    let hex = witness_cid.trim_start_matches("blake3-512:");
    let wpath = witnesses.join(format!("witness-{hex}.json"));
    let bytes = fs::read_to_string(&wpath).expect("witness file written");
    let witness: sugar_ir_types::WitnessMemento =
        serde_json::from_str(&bytes).expect("witness re-parses");
    assert_eq!(witness.outcome, "pass");
    assert!(witness.signature.is_some(), "witness must be signed");

    assert_eq!(receipt["ok"], true);
    assert_eq!(code, 0, "positive run exits clean; got {code}");

    let _ = fs::remove_dir_all(&project);
}

/// NEGATIVE: break the body to `double(x) = x*3`. The body reduction
/// yields `*(3, 3) == 6`; z3 finds `9 != 6` SAT on the negation ->
/// Unsatisfied, exit 1, NO witness. This is THE load-bearing proof: the
/// negative case must fail HONESTLY (Unsatisfied, not Undecidable),
/// because no uninterpreted symbol survives the body reduction.
#[test]
fn verify_double_broken_body_fails_unsatisfied_no_witness() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping body-discharge negative test");
        return;
    }
    let project = publish_double_project("neg", 3);
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    let claim = &receipt["claims"].as_array().expect("claims")[0];

    // The decisive assertion: a BROKEN body makes the claim UNSATISFIED,
    // not UNDECIDABLE. Undecidable here would mean the callee stayed an
    // uninterpreted symbol (the #1440 bug); Unsatisfied means the body was
    // reduced and z3 actually refuted `*(3,3) == 6`.
    assert_eq!(
        claim["status"], "unsatisfied",
        "broken body x*3 must be UNSATISFIED (not undecidable); claim: {claim}"
    );
    assert_eq!(
        claim["pass"], false,
        "broken-body claim must not pass; claim: {claim}"
    );

    // No witness for a violated claim.
    assert!(
        claim["witnessCid"].is_null(),
        "no witness may be minted for a violated claim; claim: {claim}"
    );
    assert_eq!(receipt["ok"], false);

    let witness_files: Vec<_> = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).collect())
        .unwrap_or_default();
    assert!(
        witness_files.is_empty(),
        "witness dir must be empty for a violated claim; found {} files",
        witness_files.len()
    );

    // Exit 1 = EXIT_VERIFY_FAIL (a hard violation, not a solver miss/exit 3).
    assert_eq!(
        code, 1,
        "broken-body claim must exit 1 (EXIT_VERIFY_FAIL, not 3=undecidable); got {code}"
    );
    eprintln!("NEGATIVE_EXIT_CODE={code} STATUS={}", claim["status"]);

    let _ = fs::remove_dir_all(&project);
}

/// FALSE-GREEN REGRESSION (PR-22 review blocker). The reviewer's exact
/// probe: take the POSITIVE fixture and change the assertion predicate from
/// `=` to `<=`. The callee `double` STILL has a body-derived op-contract,
/// but `<=(double(3), 10)` is NOT the reducible `=(<call>, <expected>)`
/// shape.
///
/// Before the fix, `extract_body_obligation` returned `Ok(None)` for the
/// unrecognized shape, the claim fell through to `resolve_target` +
/// `instantiate`, the body-derived op-contract (post/formals, NO `pre`) hit
/// the "vacuous: target carries no precondition" branch, and verify
/// reported `status:"discharged", pass:true, exit 0` -- a GREEN PASS for a
/// claim it never checked. That is the one thing the verify spine must
/// never do.
///
/// The fix: once a callee is body-bearing, an unreducible obligation
/// REFUSES (not vacuous-pass). This test asserts the false green is closed:
/// the claim must NOT be discharged and must NOT pass.
#[test]
fn verify_body_bearing_unrecognized_shape_refuses_not_vacuous_pass() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping false-green regression test");
        return;
    }
    // `<=(double(3), 10)` -- a body-bearing callee, but not the `=` shape.
    let inv = json!({
        "kind": "atomic", "name": "<=",
        "args": [
            {"kind": "ctor", "name": "double", "args": [int_const(3)]},
            int_const(10)
        ]
    });
    let project = publish_double_project_with_inv("falsegreen", 2, inv);
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    let claim = &receipt["claims"].as_array().expect("claims")[0];

    // THE BLOCKER ASSERTION: a body-bearing claim whose shape we cannot
    // reduce must NOT report a green pass.
    assert_ne!(
        claim["status"], "discharged",
        "unreducible body-bearing claim must NOT be discharged (no false green); claim: {claim}"
    );
    assert_eq!(
        claim["pass"], false,
        "unreducible body-bearing claim must NOT pass; claim: {claim}"
    );
    assert_ne!(
        claim["obligationClass"], "vacuous",
        "must NOT take the vacuous-discharge branch; claim: {claim}"
    );

    // It refuses with a body-discharge reason (the honest posture).
    let reason = claim["reason"].as_str().unwrap_or("");
    assert!(
        reason.contains("body-discharge") && reason.contains("refuse"),
        "refusal reason must be surfaced; got `{reason}`"
    );

    // No witness for a claim that was never discharged.
    assert!(
        claim["witnessCid"].is_null(),
        "no witness for a refused claim; claim: {claim}"
    );
    let witness_files: Vec<_> = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).collect())
        .unwrap_or_default();
    assert!(
        witness_files.is_empty(),
        "witness dir must be empty for a refused claim; found {} files",
        witness_files.len()
    );

    // Must NOT exit 0 (clean pass). Undecidable -> the receipt is not `ok`.
    assert_ne!(
        code, 0,
        "a refused claim must not exit 0 (clean); got {code}"
    );
    assert_eq!(
        receipt["ok"], false,
        "receipt must not be ok when a claim was refused; receipt: {receipt}"
    );
    eprintln!("FALSEGREEN_STATUS={} EXIT={code}", claim["status"]);

    let _ = fs::remove_dir_all(&project);
}

/// FALSE-GREEN REGRESSION #2 (the false green MOVED, not closed -- caught
/// in re-review). The first fix put the honesty boundary AFTER the resolver
/// lookup gate. But `CatalogResolver::lookup` itself drops a body-bearing
/// contract whose `post` is NOT a `result == <expr>` equation (the
/// `value_expr()?` early-return), so it returns `None` -> `Ok(None)` ->
/// fall-through -> the target has `formals` but no `pre` -> the
/// vacuous-discharge branch fired -> GREEN PASS, exit 0. Same cardinal sin,
/// narrower trigger.
///
/// The trigger: a body-bearing op-contract (`formals: ["x"]`, NO `pre`)
/// whose `post` is a non-equation predicate `<=(result, x)`, with a
/// harvested `=(double(3), 6)` assertion (so a callsite enumerates).
///
/// The consumer-side fix: `verify_one_claim` checks
/// `resolved.target_is_body_bearing` BEFORE the vacuous branch and refuses.
/// This test asserts the false green is closed for THIS variant too: the
/// claim must NOT be discharged, must NOT pass, must NOT be vacuous.
#[test]
fn verify_body_bearing_non_equation_post_refuses_not_vacuous_pass() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping false-green-2 regression test");
        return;
    }
    // Body-bearing op-contract whose post is NOT `result == <expr>` -- the
    // resolver's `value_expr()` returns None and it drops the contract.
    let post = json!({
        "kind": "atomic", "name": "<=",
        "args": [
            {"kind": "var", "name": "result"},
            {"kind": "var", "name": "x"}
        ]
    });
    // A normal `=(double(3), 6)` assertion, so exactly one callsite enumerates.
    let inv = json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "ctor", "name": "double", "args": [int_const(3)]},
            int_const(6)
        ]
    });
    let project = publish_double_project_full("falsegreen2", post, inv);
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    let claim = &receipt["claims"].as_array().expect("claims")[0];

    // THE BLOCKER ASSERTION: a body-bearing claim that the resolver dropped
    // must NOT slip through to a vacuous green pass.
    assert_ne!(
        claim["status"], "discharged",
        "body-bearing contract dropped by the resolver must NOT be discharged; claim: {claim}"
    );
    assert_eq!(claim["pass"], false, "must NOT pass; claim: {claim}");
    assert_ne!(
        claim["obligationClass"], "vacuous",
        "must NOT take the vacuous-discharge branch; claim: {claim}"
    );

    // The consumer-side refusal reason is surfaced.
    let reason = claim["reason"].as_str().unwrap_or("");
    assert!(
        reason.contains("body-discharge") && reason.contains("refuse"),
        "refusal reason must be surfaced; got `{reason}`"
    );

    assert!(
        claim["witnessCid"].is_null(),
        "no witness for a refused claim; claim: {claim}"
    );
    let witness_files: Vec<_> = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).collect())
        .unwrap_or_default();
    assert!(
        witness_files.is_empty(),
        "witness dir must be empty for a refused claim; found {} files",
        witness_files.len()
    );

    assert_ne!(
        code, 0,
        "a refused claim must not exit 0 (clean); got {code}"
    );
    assert_eq!(
        receipt["ok"], false,
        "receipt must not be ok when a claim was refused; receipt: {receipt}"
    );
    eprintln!("FALSEGREEN2_STATUS={} EXIT={code}", claim["status"]);

    let _ = fs::remove_dir_all(&project);
}

/// FALSE-GREEN REGRESSION #3 (the empty-`formals` corner -- caught in the
/// third-pass review as a writer-unreachable nit, closed on principle:
/// honesty must hold for ALL inputs, not just what today's writer emits).
///
/// The `target_is_body_bearing` marker once gated on `!formals.is_empty()`,
/// so a ZERO-ARG body-derived contract (`formals: []`) with a non-equation
/// post and no `pre` was classified NON-body-bearing -> it slipped back into
/// the vacuous-discharge branch -> GREEN PASS, exit 0. A zero-parameter
/// function still has a body; its contract is body-bearing. The marker now
/// gates on `formals` PRESENT (the key exists), not non-empty.
///
/// This test asserts the corner is closed: `formals: []` + non-equation post
/// + no pre must REFUSE, exactly like the `formals: ["x"]` variants.
#[test]
fn verify_zero_arg_body_bearing_non_equation_post_refuses_not_vacuous_pass() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping false-green-3 (zero-arg) regression test");
        return;
    }
    // Body-bearing op-contract with EMPTY formals + a non-equation post.
    let post = json!({
        "kind": "atomic", "name": "<=",
        "args": [
            {"kind": "var", "name": "result"},
            int_const(10)
        ]
    });
    // A normal `=(double(3), 6)` assertion, so exactly one callsite enumerates.
    let inv = json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "ctor", "name": "double", "args": [int_const(3)]},
            int_const(6)
        ]
    });
    let project =
        publish_double_project_with_formals("falsegreen3", json!([]), json!([]), post, inv);
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    let claim = &receipt["claims"].as_array().expect("claims")[0];

    // THE BLOCKER ASSERTION: an empty-formals body-bearing contract must NOT
    // vacuous-pass.
    assert_ne!(
        claim["status"], "discharged",
        "zero-arg body-bearing contract must NOT be discharged; claim: {claim}"
    );
    assert_eq!(claim["pass"], false, "must NOT pass; claim: {claim}");
    assert_ne!(
        claim["obligationClass"], "vacuous",
        "must NOT take the vacuous-discharge branch; claim: {claim}"
    );

    assert!(
        claim["witnessCid"].is_null(),
        "no witness for a refused claim; claim: {claim}"
    );
    let witness_files: Vec<_> = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).collect())
        .unwrap_or_default();
    assert!(
        witness_files.is_empty(),
        "witness dir must be empty for a refused claim; found {} files",
        witness_files.len()
    );

    assert_ne!(
        code, 0,
        "a refused claim must not exit 0 (clean); got {code}"
    );
    assert_eq!(
        receipt["ok"], false,
        "receipt must not be ok when a claim was refused; receipt: {receipt}"
    );
    eprintln!("FALSEGREEN3_STATUS={} EXIT={code}", claim["status"]);

    let _ = fs::remove_dir_all(&project);
}

/// EQ-BOTH-CALLS POSITIVE (z3-backed): `=(double(3), double(3))` must discharge.
///
/// This is the eq-both-calls tier of body discharge. The assertion has BOTH
/// sides as the same callee: `inv = =(double(3), double(3))`. The spine
/// reduces EACH call through the body (`double(x)=x*2`), producing the
/// concrete obligation `=(*(3,2), *(3,2))` = `=(6, 6)`. z3 returns UNSAT
/// (the obligation holds), the claim is Discharged with method=reflexive,
/// and a signed witness is minted.
///
/// This test closes the z3-reachability question: the new both-calls path
/// not only produces a reduced formula, but that formula actually reaches
/// z3 and returns UNSAT. The obligation is NOT silently skipped-as-pass.
#[test]
fn verify_double_eq_both_calls_same_args_discharges_reflexive() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping eq-both-calls positive test");
        return;
    }
    // `=(double(3), double(3))` -- BOTH sides are the same callee with same args.
    let inv = json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "ctor", "name": "double", "args": [int_const(3)]},
            {"kind": "ctor", "name": "double", "args": [int_const(3)]}
        ]
    });
    let project = publish_double_project_with_inv("eq-both-same", 2, inv);
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    // `=(double(3), double(3))` enumerates TWO callsites (one per `double`
    // ctor in the inv). Each one sees the full `=` atomic as its
    // `containing_atomic` and is processed by the eq-both-calls path.
    let claims = receipt["claims"].as_array().expect("claims");
    assert!(
        !claims.is_empty(),
        "eq-both-calls same-args must enumerate at least one claim; receipt: {receipt}"
    );

    // THE DECISIVE ASSERTION: ALL claims must be DISCHARGED.
    for (i, claim) in claims.iter().enumerate() {
        assert_eq!(
            claim["status"], "discharged",
            "eq-both-calls same-args claim[{i}] must be DISCHARGED (body reduces \
             =(6,6) -> UNSAT); claim: {claim}"
        );
        assert_eq!(
            claim["pass"], true,
            "eq-both-calls same-args claim[{i}] must pass; claim: {claim}"
        );

        // Method must be reflexive: both sides reduce to the same body expression.
        let method = claim["dischargeMethod"].as_str().unwrap_or("");
        assert_eq!(
            method, "reflexive",
            "eq-both-calls same-args claim[{i}] must classify as reflexive (sides \
             are identical after body reduction); claim: {claim}"
        );
        assert_eq!(
            claim["bodyDischargeTier"], "body-eq-same-callee",
            "eq-both-calls same-args claim[{i}] must report the body route separately \
             from dischargeMethod; claim: {claim}"
        );

        // A signed witness is minted for a discharged claim.
        assert!(
            !claim["witnessCid"].is_null(),
            "witness must be minted for discharged eq-both-calls claim[{i}]; claim: {claim}"
        );
    }

    assert_eq!(receipt["ok"], true);
    assert_eq!(code, 0, "eq-both-calls same-args must exit 0; got {code}");

    let _ = fs::remove_dir_all(&project);
}

/// EQ-BOTH-CALLS NEGATIVE (z3-backed): `=(double(3), double(4))` must NOT
/// discharge.
///
/// THE LOAD-BEARING DISCRIMINATION TEST. The assertion `=(double(3), double(4))`
/// has both sides as the same callee but DIFFERENT args. The spine reduces each
/// through the body: `=(*(3,2), *(4,2))` = `=(6, 8)`. z3 returns SAT on the
/// negation (`6 != 8` is satisfiable) -> Unsatisfied, exit 1, NO witness.
///
/// This is the negative control the soundness argument requires: if the reduced
/// formula had stayed uninterpreted or been silently skipped, the obligation
/// would be Undecidable (not Unsatisfied). Unsatisfied proves z3 ran on the
/// concrete formula and found a real counterexample. NEVER a false pass.
#[test]
fn verify_double_eq_both_calls_different_args_is_unsatisfied() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping eq-both-calls negative test");
        return;
    }
    // `=(double(3), double(4))` -- same callee, DIFFERENT args.
    // Body: double(x)=x*2, so this reduces to =(6, 8) -> z3 finds 6!=8 SAT.
    let inv = json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "ctor", "name": "double", "args": [int_const(3)]},
            {"kind": "ctor", "name": "double", "args": [int_const(4)]}
        ]
    });
    let project = publish_double_project_with_inv("eq-both-diff", 2, inv);
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    // `=(double(3), double(4))` also enumerates TWO callsites (one per `double` ctor).
    // Both must be UNSATISFIED: the first callee `double(3)` is processed by the
    // eq-both-calls path and produces `=(*(3,2), *(4,2))` = `=(6,8)`. z3 finds
    // the negation SAT (there exists a model where 6 != 8).
    let claims = receipt["claims"].as_array().expect("claims");
    assert!(
        !claims.is_empty(),
        "eq-both-calls different-args must enumerate at least one claim; receipt: {receipt}"
    );

    // THE DECISIVE ASSERTION: ALL claims must be UNSATISFIED (z3 refuted them).
    for (i, claim) in claims.iter().enumerate() {
        assert_eq!(
            claim["status"], "unsatisfied",
            "eq-both-calls different-args claim[{i}] must be UNSATISFIED (z3 \
             refutes =(6,8) with SAT on the negation); claim: {claim}"
        );
        assert_eq!(
            claim["pass"], false,
            "eq-both-calls different-args claim[{i}] must not pass; claim: {claim}"
        );
        assert_eq!(
            claim["bodyDischargeTier"], "body-eq-same-callee",
            "eq-both-calls different-args claim[{i}] must still report the attempted \
             body route on a violation; claim: {claim}"
        );
        assert!(
            claim["dischargeMethod"].is_null(),
            "unsatisfied eq-both-calls claim[{i}] must not claim a proof method; claim: {claim}"
        );

        // No witness for a violated claim.
        assert!(
            claim["witnessCid"].is_null(),
            "no witness may be minted for unsatisfied claim[{i}]; claim: {claim}"
        );
    }

    let witness_files: Vec<_> = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).collect())
        .unwrap_or_default();
    assert!(
        witness_files.is_empty(),
        "witness dir must be empty for unsatisfied claims; found {} files",
        witness_files.len()
    );

    // Exit 1 = EXIT_VERIFY_FAIL (a hard violation found by z3, not a solver
    // miss / exit 3). This is the proof that z3 ran and found the counterexample.
    assert_eq!(
        code, 1,
        "different-args eq-both-calls must exit 1 (EXIT_VERIFY_FAIL, z3-counterexample \
         found for =(6,8)); got {code}"
    );
    assert_eq!(receipt["ok"], false);

    let _ = fs::remove_dir_all(&project);
}
