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
use sugar_canonicalizer::{blake3_512_of, Value as CValue};
use sugar_claim_envelope::{
    mint_bridge, mint_contract, Authoring, MintBridgeArgs, MintContractArgs, MintedEnvelope,
};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, BridgeMemento, ClaimContractMemento,
    ContractMementoRef, Ed25519Seed, ProofEnvelopeInput, ProofGraph,
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
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    built.cid
}

fn publish_vendor_positive_contract(vendor_dir: &Path) -> (String, String, PathBuf, Vec<u8>) {
    let signer_seed: Ed25519Seed = [0x51u8; 32];
    let mut graph = ProofGraph::new();
    let target = mint_contract(&MintContractArgs {
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
        contract_name: "must_be_positive".into(),
        pre: Some(json_to_cvalue(&json!({
            "kind": "atomic",
            "name": ">=",
            "args": [var("x"), int_const(0)]
        }))),
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
    })
    .expect("mint vendor contract");
    let target_cid = push_claim_contract(&mut graph, target);
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
    let source = mint_contract(&MintContractArgs {
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
        contract_name: "user_calls_vendor".into(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(&json!({
            "kind": "atomic",
            "name": "observed",
            "args": [{
                "kind": "ctor",
                "name": "must_be_positive",
                "args": [int_const(-1)]
            }]
        }))),
        out_binding: "result".into(),
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    })
    .expect("mint source contract");
    push_claim_contract(&mut graph, source);
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
    let producer = mint_contract(&MintContractArgs {
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
        contract_name: "produce_zero".into(),
        pre: None,
        post: Some(json_to_cvalue(&json!({
            "kind": "atomic",
            "name": "=",
            "args": [var("result"), int_const(0)]
        }))),
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
    })
    .expect("mint producer contract");
    let producer_cid = push_claim_contract(&mut graph, producer);

    let consumer = mint_contract(&MintContractArgs {
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
        contract_name: "requires_positive".into(),
        pre: Some(json_to_cvalue(&json!({
            "kind": "atomic",
            "name": ">",
            "args": [var("x"), int_const(0)]
        }))),
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
    })
    .expect("mint consumer contract");
    let consumer_cid = push_claim_contract(&mut graph, consumer);

    let source = mint_contract(&MintContractArgs {
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
        contract_name: "contradictory_callsite".into(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(&json!({
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
        }))),
        out_binding: "result".into(),
        produced_by: "test".into(),
        produced_at: produced_at.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "test".into(),
            note: None,
        },
        signer_seed,
    })
    .expect("mint source contract");
    push_claim_contract(&mut graph, source);

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

fn install_dependency_proof_stub(project_dir: &Path, proof_cid: &str, proof_bytes: &[u8]) {
    install_smt_compiler_manifest(project_dir);
    let bin = project_dir.join("resolve-deps-stub.sh");
    let proof_bytes_base64 = BASE64.encode(proof_bytes);
    fs::write(
        &bin,
        format!(
            "#!/bin/sh\nwhile IFS= read -r line; do\n  case \"$line\" in\n    *resolve_dependency_proofs*) echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{{\"proofs\":[{{\"cid\":\"{}\",\"bytes_base64\":\"{}\",\"source\":\"stub-package-proof\"}}]}}}}' ;;\n    *shutdown*) echo '{{\"jsonrpc\":\"2.0\",\"id\":2,\"result\":null}}'; exit 0 ;;\n    *) echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{{}}}}' ;;\n  esac\ndone\n",
            proof_cid, proof_bytes_base64
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

fn z3_available() -> bool {
    std::process::Command::new("z3")
        .arg("-version")
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
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
        dependency_proofs[0].expected_cid.as_deref(),
        Some(bundle_cid.as_str())
    );

    let runner = Runner::new(RunnerConfig {
        project_root: project.clone(),
        extra_proofs: dependency_proofs,
        ..Default::default()
    });
    let (pool, _callsites) = runner.run_load_and_enumerate();
    assert!(
        pool.mementos.get(&target_cid).is_some(),
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
    assert_eq!(report["violations"], 1, "report: {report}");
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
