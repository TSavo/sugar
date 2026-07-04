// SPDX-License-Identifier: Apache-2.0
//
// Voltron pool assembly: sugar prove must ask configured kits for the
// dependency .proof files they resolve through their own package managers, then
// union those files into the verifier pool without teaching the substrate cargo,
// npm, classpath, sys.path, or any other platform graph.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, cid_hex, Value as CValue};
use sugar_claim_envelope::{
    mint_bridge, mint_contract_with_body_cid, Authoring, MintBridgeArgs, MintContractArgs,
    MintedEnvelope,
};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, BridgeMemento, ClaimContractMemento, ContractBody,
    ContractMementoRef, Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};
use sugar_verifier::{Runner, RunnerConfig};

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-dep-proof-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn rust_workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-cli has a parent workspace")
        .to_path_buf()
}

fn install_smt_compiler_manifest(project: &Path) {
    let manifest_dir = project.join(".sugar").join("ir-compilers").join("smt-lib");
    fs::create_dir_all(&manifest_dir).expect("mkdir ir compiler manifest");
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
            rust_workspace().display()
        ),
    )
    .expect("write ir compiler manifest");
}

fn int_sort() -> Json {
    json!({"kind": "primitive", "name": "Int"})
}

fn int_const(n: i64) -> Json {
    json!({"kind": "const", "value": n, "sort": int_sort()})
}

fn var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
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

fn register_contract_body_graph(
    graph: &mut ProofGraph,
    pre: Option<&Json>,
    post: Option<&Json>,
    inv: Option<&Json>,
) -> String {
    let mut atoms = Vec::new();
    if let Some(formula) = pre {
        atoms.push((
            "pre".to_string(),
            graph.register_atom(FlatAtom::new(json_to_cvalue(formula))),
        ));
    }
    if let Some(formula) = post {
        atoms.push((
            "post".to_string(),
            graph.register_atom(FlatAtom::new(json_to_cvalue(formula))),
        ));
    }
    if let Some(formula) = inv {
        atoms.push((
            "inv".to_string(),
            graph.register_atom(FlatAtom::new(json_to_cvalue(formula))),
        ));
    }
    let slots = atoms
        .iter()
        .map(|(slot, atom)| (slot.as_str(), atom))
        .collect::<Vec<_>>();
    let body = graph.register_body(ContractBody::from_slots(slots));
    body.cid().as_str().to_string()
}

fn push_body_contract(
    graph: &mut ProofGraph,
    args: &MintContractArgs,
    pre: Option<&Json>,
    post: Option<&Json>,
    inv: Option<&Json>,
    context: &str,
) -> String {
    let body_cid = register_contract_body_graph(graph, pre, post, inv);
    let minted = mint_contract_with_body_cid(args, Some(&body_cid)).expect(context);
    push_claim_contract(graph, minted)
}

fn write_proof(dir: &Path, name: &str, graph: ProofGraph) -> String {
    fs::create_dir_all(dir).expect("mkdir proof dir");
    let signer_seed: Ed25519Seed = [0x51u8; 32];
    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: name.to_string(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: "2026-05-27T00:00:00.000Z".into(),
    });
    let hex = cid_hex(&built.cid).unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    built.cid
}

fn publish_vendor_positive_contract(vendor_dir: &Path) -> (String, String, PathBuf, Vec<u8>) {
    let signer_seed: Ed25519Seed = [0x51u8; 32];
    let mut graph = ProofGraph::new();
    let target_pre = json!({
        "kind": "atomic",
        "name": ">=",
        "args": [var("x"), int_const(0)]
    });
    let target_args = MintContractArgs {
        evidence_term: None,
        formals: vec!["x".into()],
        emit_empty_formals: false,
        formal_sorts: vec![json_to_cvalue(&int_sort())],
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: None,
        contract_name: "must_be_positive".into(),
        pre: Some(json_to_cvalue(&target_pre)),
        post: None,
        inv: None,
        out_binding: "result".into(),
        produced_by: "test".into(),
        produced_at: "2026-05-27T00:00:00.000Z".into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    };
    let target_cid = push_body_contract(
        &mut graph,
        &target_args,
        Some(&target_pre),
        None,
        None,
        "mint vendor contract",
    );
    let bundle_cid = write_proof(vendor_dir, "@vendor/must-be-positive", graph);
    let proof_path = fs::read_dir(vendor_dir)
        .expect("read vendor proofs")
        .flatten()
        .map(|entry| entry.path())
        .find(|path| path.extension().and_then(|s| s.to_str()) == Some("proof"))
        .expect("vendor proof exists");
    let proof_bytes = fs::read(&proof_path).expect("read vendor proof bytes");
    (target_cid, bundle_cid, proof_path, proof_bytes)
}

fn publish_user_bridge(project_dir: &Path, target_cid: &str, target_bundle_cid: &str) {
    let signer_seed: Ed25519Seed = [0x51u8; 32];
    let produced_at = "2026-05-27T00:00:00.000Z";
    let mut graph = ProofGraph::new();
    let source_inv = json!({
        "kind": "atomic",
        "name": "observed",
        "args": [{
            "kind": "ctor",
            "name": "must_be_positive",
            "args": [int_const(-1)]
        }]
    });
    let source_args = MintContractArgs {
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
        proofir_provenance: None,
        contract_name: "user_calls_vendor".into(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(&source_inv)),
        out_binding: "result".into(),
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    };
    push_body_contract(
        &mut graph,
        &source_args,
        None,
        None,
        Some(&source_inv),
        "mint source contract",
    );
    let bridge = mint_bridge(&MintBridgeArgs {
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        source_symbol: "must_be_positive".into(),
        source_layer: "rust".into(),
        target_contract: ContractMementoRef::new(target_cid.to_string()),
        target_layer: "rust-kit".into(),
        ir_arg_sorts: vec!["Int".into()],
        ir_return_sort: "Bool".into(),
        notes: String::new(),
        signer_seed,
        target_proof_cid: Some(target_bundle_cid.to_string()),
        callsite: None,
    });
    push_bridge(&mut graph, bridge);
    write_proof(&project_dir.join(".sugar"), "@user/local-bridge", graph);
}

fn publish_contradictory_implication_project() -> PathBuf {
    let project = unique_dir("contradictory-implication");
    let proof_dir = project.join(".sugar");
    fs::create_dir_all(&proof_dir).expect("mkdir proof dir");
    install_smt_compiler_manifest(&project);

    let signer_seed: Ed25519Seed = [0x51u8; 32];
    let produced_at = "2026-05-27T00:00:00.000Z";
    let mut graph = ProofGraph::new();
    let producer_post = json!({
        "kind": "atomic",
        "name": "=",
        "args": [var("result"), int_const(0)]
    });
    let producer_args = MintContractArgs {
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
        proofir_provenance: None,
        contract_name: "produce_zero".into(),
        pre: None,
        post: Some(json_to_cvalue(&producer_post)),
        inv: None,
        out_binding: "result".into(),
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    };
    let producer_cid = push_body_contract(
        &mut graph,
        &producer_args,
        None,
        Some(&producer_post),
        None,
        "mint producer contract",
    );

    let consumer_pre = json!({
        "kind": "atomic",
        "name": ">",
        "args": [var("x"), int_const(0)]
    });
    let consumer_args = MintContractArgs {
        evidence_term: None,
        formals: vec!["x".into()],
        emit_empty_formals: false,
        formal_sorts: vec![json_to_cvalue(&int_sort())],
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: None,
        contract_name: "requires_positive".into(),
        pre: Some(json_to_cvalue(&consumer_pre)),
        post: None,
        inv: None,
        out_binding: "result".into(),
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    };
    let consumer_cid = push_body_contract(
        &mut graph,
        &consumer_args,
        Some(&consumer_pre),
        None,
        None,
        "mint consumer contract",
    );

    let source_inv = json!({
        "kind": "atomic",
        "name": "observed",
        "args": [{
            "kind": "ctor",
            "name": "requires_positive",
            "args": [{
                "kind": "ctor",
                "name": "produce_zero",
                "args": []
            }]
        }]
    });
    let source_args = MintContractArgs {
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
        proofir_provenance: None,
        contract_name: "contradictory_callsite".into(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(&source_inv)),
        out_binding: "result".into(),
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    };
    push_body_contract(
        &mut graph,
        &source_args,
        None,
        None,
        Some(&source_inv),
        "mint source contract",
    );

    let producer_bridge = mint_bridge(&MintBridgeArgs {
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        source_symbol: "produce_zero".into(),
        source_layer: "rust".into(),
        target_contract: ContractMementoRef::new(producer_cid),
        target_layer: "rust-tests".into(),
        ir_arg_sorts: Vec::new(),
        ir_return_sort: "Int".into(),
        notes: String::new(),
        signer_seed,
        target_proof_cid: None,
        callsite: None,
    });
    push_bridge(&mut graph, producer_bridge);

    let consumer_bridge = mint_bridge(&MintBridgeArgs {
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        source_symbol: "requires_positive".into(),
        source_layer: "rust".into(),
        target_contract: ContractMementoRef::new(consumer_cid),
        target_layer: "rust-tests".into(),
        ir_arg_sorts: vec!["Int".into()],
        ir_return_sort: "Bool".into(),
        notes: String::new(),
        signer_seed,
        target_proof_cid: None,
        callsite: None,
    });
    push_bridge(&mut graph, consumer_bridge);

    write_proof(&proof_dir, "@test/contradictory-implication", graph);
    project
}

fn install_dependency_proof_stub_with_entry(project_dir: &Path, proof_entry: &str) {
    install_smt_compiler_manifest(project_dir);
    let bin = project_dir.join("resolve-deps-stub.sh");
    fs::write(
        &bin,
        format!(
            "#!/bin/sh\nwhile IFS= read -r line; do\n  case \"$line\" in\n    *resolve_dependency_proofs*) echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{{\"proofs\":[{}]}}}}' ;;\n    *shutdown*) echo '{{\"jsonrpc\":\"2.0\",\"id\":2,\"result\":null}}'; exit 0 ;;\n    *) echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{{}}}}' ;;\n  esac\ndone\n",
            proof_entry
        ),
    )
    .expect("write stub");
    let manifest_dir = project_dir.join(".sugar").join("lift").join("rust");
    fs::create_dir_all(&manifest_dir).expect("mkdir manifest");
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"rust-dependency-proof-stub\"\nlibrary_tag = \"test\"\ncommand = [\"/bin/sh\", \"{}\"]\nworking_dir = \".\"\n",
            bin.display()
        ),
    )
    .expect("write manifest");
    fs::write(
        project_dir.join(".sugar").join("config.toml"),
        "[[plugins]]\nname = \"rust-dependency-proof-stub\"\nkind = \"lift\"\nsurface = \"rust\"\n",
    )
    .expect("write config");
    sugar_cli::kit_dispatch::reset_kit_dispatch_registry_cache_for_tests();
}

fn install_dependency_proof_stub(project_dir: &Path, proof_cid: &str, proof_bytes: &[u8]) {
    let proof_bytes_base64 = BASE64.encode(proof_bytes);
    let entry = format!(
        "{{\"cid\":\"{}\",\"bytes_base64\":\"{}\",\"source\":\"stub-package-proof\"}}",
        proof_cid, proof_bytes_base64
    );
    install_dependency_proof_stub_with_entry(project_dir, &entry);
}

fn z3_available() -> bool {
    std::process::Command::new("z3")
        .arg("-version")
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}

#[test]
fn dependency_proof_without_cid_is_refused() {
    let root = unique_dir("missing-cid");
    let project = root.join("user");
    let vendor = root.join("vendor");
    fs::create_dir_all(project.join(".sugar")).expect("mkdir project");
    let (_target_cid, _bundle_cid, _proof_path, proof_bytes) =
        publish_vendor_positive_contract(&vendor);
    let proof_bytes_base64 = BASE64.encode(&proof_bytes);
    let entry = format!(
        "{{\"bytes_base64\":\"{}\",\"source\":\"stub-package-proof\"}}",
        proof_bytes_base64
    );
    install_dependency_proof_stub_with_entry(&project, &entry);

    let err = sugar_cli::kit_dispatch::dependency_proofs_via_rpc(&project)
        .expect_err("dependency proof without cid must be a protocol error");

    assert!(
        err.contains("rust-dependency-proof-stub"),
        "error must name the kit: {err}"
    );
    assert!(
        err.contains("stub-package-proof"),
        "error must name the dependency proof label: {err}"
    );
    assert!(
        err.contains("kit returned dependency proof without a content address"),
        "error must describe the missing trust root: {err}"
    );

    let _ = fs::remove_dir_all(root);
}

#[test]
fn dependency_proof_with_wrong_cid_is_refused() {
    let root = unique_dir("wrong-cid");
    let project = root.join("user");
    let vendor = root.join("vendor");
    fs::create_dir_all(project.join(".sugar")).expect("mkdir project");
    let (_target_cid, _bundle_cid, _proof_path, proof_bytes) =
        publish_vendor_positive_contract(&vendor);
    let wrong_cid = format!("blake3-512:{}", "0".repeat(128));
    install_dependency_proof_stub(&project, &wrong_cid, &proof_bytes);

    let dependency_proofs = sugar_cli::kit_dispatch::dependency_proofs_via_rpc(&project)
        .expect("resolve dependency proofs");
    let runner = Runner::new(RunnerConfig {
        project_root: project.clone(),
        extra_proofs: dependency_proofs,
        ..Default::default()
    });
    let (pool, _callsites) = runner.run_load_and_enumerate();

    assert!(
        pool.load_errors.iter().any(|err| {
            err.proof_path.contains("stub-package-proof")
                && err.reason.contains("rule 1 (trust root)")
                && err.reason.contains(&wrong_cid)
                && err.reason.contains("content hash")
        }),
        "wrong dependency proof CID must be a load error: {:#?}",
        pool.load_errors
    );

    let _ = fs::remove_dir_all(root);
}

#[test]
fn dependency_proof_with_correct_cid_loads() {
    let root = unique_dir("correct-cid");
    let project = root.join("user");
    let vendor = root.join("vendor");
    fs::create_dir_all(project.join(".sugar")).expect("mkdir project");
    let (target_cid, bundle_cid, _proof_path, proof_bytes) =
        publish_vendor_positive_contract(&vendor);
    install_dependency_proof_stub(&project, &bundle_cid, &proof_bytes);

    let dependency_proofs = sugar_cli::kit_dispatch::dependency_proofs_via_rpc(&project)
        .expect("resolve dependency proofs");
    let runner = Runner::new(RunnerConfig {
        project_root: project.clone(),
        extra_proofs: dependency_proofs,
        ..Default::default()
    });
    let (pool, _callsites) = runner.run_load_and_enumerate();

    assert!(
        pool.load_errors.is_empty(),
        "correct dependency proof CID must load cleanly: {:#?}",
        pool.load_errors
    );
    assert!(
        pool.mementos.contains_key(target_cid.as_str()),
        "vendor contract {target_cid} must be reachable"
    );

    let _ = fs::remove_dir_all(root);
}

#[test]
fn dependency_rpc_union_makes_vendor_contract_reachable() {
    let root = unique_dir("reachable");
    let project = root.join("user");
    let vendor = root.join("vendor");
    fs::create_dir_all(project.join(".sugar")).expect("mkdir project");
    let (target_cid, bundle_cid, proof_path, proof_bytes) =
        publish_vendor_positive_contract(&vendor);
    publish_user_bridge(&project, &target_cid, &bundle_cid);
    install_dependency_proof_stub(&project, &bundle_cid, &proof_bytes);
    fs::remove_file(&proof_path).expect("remove dependency proof path after kit reads it");

    let dependency_proofs = sugar_cli::kit_dispatch::dependency_proofs_via_rpc(&project)
        .expect("resolve dependency proofs");
    assert_eq!(dependency_proofs.len(), 1);
    assert_eq!(
        dependency_proofs[0].expected_cid.as_str(),
        bundle_cid.as_str()
    );

    let runner = Runner::new(RunnerConfig {
        project_root: project.clone(),
        extra_proofs: dependency_proofs,
        ..Default::default()
    });
    let (pool, _callsites) = runner.run_load_and_enumerate();
    assert!(
        pool.mementos.get(target_cid.as_str()).is_some(),
        "vendor contract {target_cid} must be present after dependency proof assembly"
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn voltron_pool_refuses_cross_dependency_violation() {
    if !z3_available() {
        eprintln!("SKIP voltron_pool_refuses_cross_dependency_violation: z3 not on PATH");
        return;
    }

    let root = unique_dir("e2e");
    let project = root.join("user");
    let vendor = root.join("vendor");
    fs::create_dir_all(project.join(".sugar")).expect("mkdir project");
    let (target_cid, bundle_cid, proof_path, proof_bytes) =
        publish_vendor_positive_contract(&vendor);
    publish_user_bridge(&project, &target_cid, &bundle_cid);
    install_dependency_proof_stub(&project, &bundle_cid, &proof_bytes);
    fs::remove_file(&proof_path).expect("remove dependency proof path after kit reads it");

    let output = std::process::Command::new(env!("CARGO_BIN_EXE_sugar"))
        .arg("prove")
        .arg(&project)
        .arg("--z3")
        .arg("z3")
        .arg("--quiet")
        .output()
        .expect("run sugar prove");
    assert_eq!(
        output.status.code(),
        Some(1),
        "cross-dependency bridge to must_be_positive(-1) must be refused\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn prove_reports_violation_for_contradictory_implication() {
    if !z3_available() {
        eprintln!("SKIP prove_reports_violation_for_contradictory_implication: z3 not on PATH");
        return;
    }

    let project = publish_contradictory_implication_project();
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_sugar"))
        .arg("prove")
        .arg(&project)
        .arg("--z3")
        .arg("z3")
        .arg("--json")
        .output()
        .expect("run sugar prove");

    assert_eq!(
        output.status.code(),
        Some(1),
        "contradictory implication must be a proof violation\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    let report: Json =
        serde_json::from_str(&stdout).unwrap_or_else(|e| panic!("parse prove JSON: {e}\n{stdout}"));
    assert!(
        report["loadErrors"]
            .as_array()
            .expect("loadErrors")
            .is_empty(),
        "contradictory implication fixture must load cleanly: {report}"
    );
    assert!(
        report["violations"].as_u64().unwrap_or_default() >= 1,
        "contradictory implication must report at least one violation: {report}"
    );
    assert!(
        report["rows"]
            .as_array()
            .expect("rows")
            .iter()
            .any(|row| row["bridge"] == "requires_positive"
                && row["status"] == "unsatisfied"
                && row["reason"].as_str().unwrap_or("").contains("sat")),
        "requires_positive(produce_zero()) should violate `produce_zero.post -> requires_positive.pre`: {report}"
    );

    let _ = fs::remove_dir_all(project);
}
