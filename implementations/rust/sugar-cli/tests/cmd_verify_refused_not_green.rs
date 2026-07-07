// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, cid_hex, Value as CValue};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, member_field, ContractBody, ContractMemento,
    Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};

const EXIT_VERIFY_FAIL: i32 = 1;
const MISSING_PROVENANCE_KIND_REASON: &str =
    "consistency check refused: contract `strings_consistency` lacks required provenance KIND";
const MISSING_PROVENANCE_KIND_DETAIL: &str =
    "contract memento lacks required proofirProvenance/sourceWarrants provenance KIND";

#[derive(Clone, Copy)]
enum SolverFixture {
    MissingSeat,
    StubPass,
}

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "sugar-verify-undecidable-not-green-{stamp}-{suffix}"
    ));
    fs::create_dir_all(&dir).expect("mkdir project");
    dir
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

fn write_stub_solver_config(project: &Path) {
    fs::write(
        project.join(".sugar").join("config.toml"),
        r#"[solvers]

[solvers.dispatch]
strings = "z3"
default = "z3"

[solvers.z3]
binary = "stub:sat"
ir_compiler = "smt-lib-v2.6"
flags = []
timeout_seconds = 1
version = "stub"
"#,
    )
    .expect("write solver config");
}

fn write_missing_solver_config(project: &Path) {
    fs::write(
        project.join(".sugar").join("config.toml"),
        r#"[solvers]

[solvers.dispatch]
strings = "bitwuzla"
default = "bitwuzla"
"#,
    )
    .expect("write missing solver config");
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

fn string_sort() -> Json {
    json!({"kind": "primitive", "name": "String"})
}

fn string_const(s: &str) -> Json {
    json!({"kind": "const", "value": s, "sort": string_sort()})
}

fn string_pred(name: &str, args: Vec<Json>) -> Json {
    json!({"kind": "atomic", "name": name, "args": args})
}

fn strings_consistency_formula() -> Json {
    json!({
        "kind": "and",
        "operands": [
            string_pred("contains", vec![string_const("abc"), string_const("a")]),
            string_pred("prefix-of", vec![string_const("a"), string_const("abc")]),
        ],
    })
}

fn publish_inv_project(suffix: &str, solver_fixture: SolverFixture) -> PathBuf {
    let dir = unique_dir(suffix);
    let proof_dir = dir.join(".sugar");
    fs::create_dir_all(&proof_dir).expect("mkdir .sugar");
    install_smt_compiler_manifest(&dir);
    match solver_fixture {
        SolverFixture::MissingSeat => write_missing_solver_config(&dir),
        SolverFixture::StubPass => write_stub_solver_config(&dir),
    }

    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let declared_at = "2026-07-01T00:00:00.000Z";
    let mut graph = ProofGraph::new();

    let metadata = graph.register_atom(FlatAtom::empty_metadata());
    let inv = graph.register_atom(FlatAtom::new(
        json_to_cvalue(&strings_consistency_formula()),
    ));
    let body = graph.register_body(ContractBody::new_inv(&inv));
    graph.register_contract(ContractMemento::new_with_metadata_at(
        "strings_consistency",
        &body,
        &metadata,
        signer_seed,
        declared_at,
    ));

    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: format!("@test/undecidable-not-green-{suffix}"),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: declared_at.into(),
        manifest: None,
    });
    let hex = cid_hex(&built.cid).expect("cid prefix");
    fs::write(proof_dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    dir
}

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn run_verify(project: &Path, json_out: bool) -> Output {
    let mut cmd = Command::new(sugar_bin());
    cmd.arg("verify").arg("--project").arg(project);
    if json_out {
        cmd.arg("--json");
    }
    cmd.output().expect("spawn sugar verify")
}

fn stdout_json(out: &Output) -> Json {
    let stdout = String::from_utf8_lossy(&out.stdout);
    serde_json::from_str(&stdout).unwrap_or_else(|e| {
        panic!(
            "verify JSON parse failed: {e}\nstdout:\n{stdout}\nstderr:\n{}",
            String::from_utf8_lossy(&out.stderr)
        )
    })
}

fn combined_output(out: &Output) -> String {
    format!(
        "{}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    )
}

fn strings_consistency_contract_member(project: &Path) -> Json {
    let proof_path = fs::read_dir(project.join(".sugar"))
        .expect("read .sugar proof dir")
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .find(|path| path.extension().is_some_and(|ext| ext == "proof"))
        .unwrap_or_else(|| panic!("fixture wrote no .proof under {}", project.display()));
    let bytes = fs::read(&proof_path).expect("read fixture proof");
    let graph = ProofGraph::read(&bytes).expect("decode fixture proof graph");
    let member = graph
        .members()
        .filter_map(|(_, bytes)| serde_json::from_slice::<Json>(bytes).ok())
        .find(|member| {
            member_field(member, "contractName").and_then(Json::as_str)
                == Some("strings_consistency")
        })
        .unwrap_or_else(|| panic!("fixture proof has no strings_consistency contract member"));
    member
}

fn assert_fixture_lacks_provenance_kind_fields(project: &Path) {
    let member = strings_consistency_contract_member(project);
    assert_eq!(
        member_field(&member, "contractName").and_then(Json::as_str),
        Some("strings_consistency"),
        "contract memento receipt: {member}"
    );
    assert!(
        member_field(&member, "proofirProvenance").is_none(),
        "fixture must predate proofirProvenance kind emission; contract memento receipt: {member}"
    );
    assert!(
        member_field(&member, "sourceWarrants").is_none(),
        "fixture must predate sourceWarrants kind emission; contract memento receipt: {member}"
    );
    assert!(
        member_field(&member, "source_warrants").is_none(),
        "fixture must predate source_warrants kind emission; contract memento receipt: {member}"
    );
}

fn assert_loud_provenance_kind_refusal(receipt: &Json) {
    assert_eq!(
        receipt["claims"][0]["status"], "refused",
        "fixture lacks provenance-kind fields, so discharge must refuse before solver dispatch; receipt: {receipt}"
    );
    assert_ne!(
        receipt["claims"][0]["status"], "discharged",
        "missing provenance kind must never green the claim; receipt: {receipt}"
    );
    let reason = receipt["claims"][0]["reason"].as_str().unwrap_or("");
    assert!(
        reason.contains(MISSING_PROVENANCE_KIND_REASON),
        "refusal must name the discharge-law violation; receipt: {receipt}"
    );
    assert!(
        reason.contains(MISSING_PROVENANCE_KIND_DETAIL),
        "refusal must name the missing memento fields; receipt: {receipt}"
    );
}

#[test]
fn fixture_contract_memento_lacks_provenance_kind_fields() {
    let project = publish_inv_project("memento-receipt", SolverFixture::MissingSeat);
    assert_fixture_lacks_provenance_kind_fields(&project);

    let _ = fs::remove_dir_all(project);
}

#[test]
fn refused_row_fails_artifact_project_verify() {
    let project = publish_inv_project("missing-seat-json", SolverFixture::MissingSeat);
    assert_fixture_lacks_provenance_kind_fields(&project);
    let out = run_verify(&project, true);
    let receipt = stdout_json(&out);
    let code = out.status.code().unwrap_or(-1);

    assert_eq!(receipt["kind"], "verification-receipt");
    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    assert_loud_provenance_kind_refusal(&receipt);
    assert_eq!(
        code, EXIT_VERIFY_FAIL,
        "refused rows must hard-fail artifact/project verify; receipt: {receipt}"
    );
    assert_eq!(
        receipt["ok"], false,
        "refused rows must preserve the not-green law; receipt: {receipt}"
    );

    let _ = fs::remove_dir_all(project);
}

#[test]
fn refused_reason_is_printed() {
    let project = publish_inv_project("missing-seat-human", SolverFixture::MissingSeat);
    assert_fixture_lacks_provenance_kind_fields(&project);
    let out = run_verify(&project, false);
    let code = out.status.code().unwrap_or(-1);
    let text = combined_output(&out);

    assert_eq!(
        code, EXIT_VERIFY_FAIL,
        "refused rows must exit with verification failure; output:\n{text}"
    );
    assert!(
        text.contains("refused"),
        "human output must print the loud refused row status; output:\n{text}"
    );
    assert!(
        text.contains(MISSING_PROVENANCE_KIND_REASON),
        "human output must carry the discharge-law refusal reason; output:\n{text}"
    );
    assert!(
        text.contains(MISSING_PROVENANCE_KIND_DETAIL),
        "human output must carry the row reason verbatim; output:\n{text}"
    );

    let _ = fs::remove_dir_all(project);
}

#[test]
fn stale_fixture_refuses_before_stub_solver_can_green() {
    let project = publish_inv_project("stub-green", SolverFixture::StubPass);
    assert_fixture_lacks_provenance_kind_fields(&project);
    let out = run_verify(&project, true);
    let receipt = stdout_json(&out);
    let code = out.status.code().unwrap_or(-1);

    assert_eq!(
        code, EXIT_VERIFY_FAIL,
        "missing provenance kind refuses before a stub solver can green the row; receipt: {receipt}"
    );
    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    assert_loud_provenance_kind_refusal(&receipt);
    assert_eq!(
        receipt["ok"], false,
        "stub solver must not green a claim whose ambient testimony lacks provenance kind; receipt: {receipt}"
    );

    let _ = fs::remove_dir_all(project);
}
