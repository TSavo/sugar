// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::path::Path;
use std::process::Command;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, Value as CValue};
use sugar_claim_envelope::{
    mint_bridge, mint_contract_with_body_cid, Authoring, MintBridgeArgs, MintContractArgs,
    MintedEnvelope,
};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, BridgeMemento, ClaimContractMemento, ContractBody,
    ContractMementoRef, Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};

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
        declared_at: "2026-05-29T00:00:00.000Z".into(),
    });
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    built.cid
}

pub fn plant_contradictory_implication_proof(
    proof_dir: &Path,
    source_layer: &str,
    target_layer: &str,
    symbol_prefix: &str,
) -> String {
    let producer = format!("{symbol_prefix}_produces_zero");
    let consumer = format!("{symbol_prefix}_requires_positive");
    let callsite = format!("{symbol_prefix}_contradictory_callsite");
    let signer_seed: Ed25519Seed = [0x51u8; 32];
    let produced_at = "2026-05-29T00:00:00.000Z";
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
        contract_name: producer.clone(),
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
        contract_name: consumer.clone(),
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
            "name": consumer,
            "args": [{
                "kind": "ctor",
                "name": producer,
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
        contract_name: callsite,
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
        source_symbol: producer,
        source_layer: source_layer.to_string(),
        target_contract: ContractMementoRef::new(producer_cid),
        target_layer: target_layer.to_string(),
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
        source_symbol: consumer,
        source_layer: source_layer.to_string(),
        target_contract: ContractMementoRef::new(consumer_cid),
        target_layer: target_layer.to_string(),
        ir_arg_sorts: vec!["Int".into()],
        ir_return_sort: "Bool".into(),
        notes: String::new(),
        signer_seed,
        target_proof_cid: None,
        callsite: None,
    });
    push_bridge(&mut graph, consumer_bridge);

    write_proof(
        proof_dir,
        &format!("@sugar/{symbol_prefix}-contradictory-implication"),
        graph,
    )
}

pub fn run_prove_json_with_code(sugar_bin: &Path, project: &Path) -> (Json, i32) {
    let output = Command::new(sugar_bin)
        .arg("prove")
        .arg(project)
        .arg("--json")
        .output()
        .expect("spawn sugar prove");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let report = serde_json::from_str(&stdout)
        .unwrap_or_else(|error| panic!("prove JSON parse failed: {error}\nstdout: {stdout}"));
    (report, output.status.code().unwrap_or(-1))
}

pub fn assert_green_proves_one_bridge(report: &Json, code: i32) {
    assert_eq!(
        code, 0,
        "base project must prove before planting contradiction; report: {report}"
    );
    assert_eq!(
        report["violations"], 0,
        "base project must have no violations before planting contradiction; report: {report}"
    );
    let rows = report["rows"].as_array().expect("rows");
    let bridge_rows: Vec<_> = rows
        .iter()
        .filter(|row| {
            row["bridge"]
                .as_str()
                .map(|bridge| !bridge.is_empty())
                .unwrap_or(false)
        })
        .collect();
    assert_eq!(
        bridge_rows.len(),
        1,
        "base project must prove exactly one language bridge before planting contradiction; report: {report}"
    );
    let row = bridge_rows[0];
    assert_eq!(
        row["status"], "discharged",
        "base project bridge must discharge before planting contradiction; row: {row}; report: {report}"
    );
    assert_ne!(
        row["dischargeMethod"], "vacuous",
        "base project bridge must not discharge vacuously before planting contradiction; row: {row}; report: {report}"
    );
}

pub fn assert_prove_refuses_contradiction(report: &Json, code: i32, expected_bridge: &str) {
    assert_eq!(
        code, 1,
        "planted contradictory implication must exit 1; report: {report}"
    );
    assert!(
        report["violations"].as_u64().unwrap_or(0) >= 1,
        "planted contradictory implication must report a violation; report: {report}"
    );
    assert!(
        report["totalCallsites"].as_u64().unwrap_or(0) > 1,
        "contradiction test must include the language route plus the planted implication; report: {report}"
    );
    assert!(
        report["rows"]
            .as_array()
            .expect("rows")
            .iter()
            .any(|row| row["bridge"] == expected_bridge && row["status"] == "unsatisfied"),
        "{expected_bridge} must be unsatisfied; report: {report}"
    );
}
