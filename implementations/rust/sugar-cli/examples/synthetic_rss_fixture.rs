// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Generate a deliberately large-but-boring proof pool for RSS measurements.
// This is a perf fixture builder, not a semantic showcase.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, Value as CValue};
use sugar_claim_envelope::{
    mint_bridge, mint_contract_with_body_cid, Authoring, MintBridgeArgs, MintContractArgs,
    MintedEnvelope,
};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, proof_filename, BridgeMemento,
    ClaimContractMemento, ContractBody, ContractMementoRef, Ed25519Seed, FlatAtom,
    ProofEnvelopeInput, ProofGraph,
};

const DEFAULT_CALLSITES: usize = 120;
const DECLARED_AT: &str = "2026-07-01T00:00:00.000Z";

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

fn int_const(n: i64) -> Json {
    json!({"kind": "const", "value": n, "sort": {"kind": "primitive", "name": "Int"}})
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

fn toml_string(value: &str) -> String {
    let escaped = value.replace('\\', "\\\\").replace('"', "\\\"");
    format!("\"{escaped}\"")
}

fn toml_array(values: &[String]) -> String {
    values
        .iter()
        .map(|value| toml_string(value))
        .collect::<Vec<_>>()
        .join(", ")
}

fn write_smt_compiler_manifest(
    project: &Path,
    compiler: Option<PathBuf>,
) -> Result<(), Box<dyn std::error::Error>> {
    let manifest_dir = project.join(".sugar").join("ir-compilers").join("smt-lib");
    fs::create_dir_all(&manifest_dir)?;

    let (command, working_dir) = if let Some(path) = compiler {
        (vec![path.canonicalize()?.display().to_string()], None)
    } else {
        let rust_workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("sugar-cli has a parent workspace")
            .canonicalize()?;
        (
            vec![
                "cargo".to_string(),
                "run".to_string(),
                "-p".to_string(),
                "sugar-ir-compiler-smt-lib".to_string(),
                "--bin".to_string(),
                "sugar-ir-smt-lib".to_string(),
                "--quiet".to_string(),
                "--".to_string(),
            ],
            Some(rust_workspace),
        )
    };

    let working_dir_line = working_dir
        .as_ref()
        .map(|path| {
            format!(
                "working_dir = {}\n",
                toml_string(&path.display().to_string())
            )
        })
        .unwrap_or_default();
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"smt-lib-reference\"\n\
version = \"0.1.0\"\n\
protocol_version = \"sugar-ir-compiler/1\"\n\
command = [{}]\n\
{working_dir_line}\
dialects = [\"smt-lib-v2.6\"]\n",
            toml_array(&command)
        ),
    )?;
    Ok(())
}

/// Truthful Stated provenance for a synthetic contract: the warrant points at
/// the synthetic body we actually minted (its real CID), so the verifier's
/// provenance-KIND gate reads `source-memento` -> Stated instead of refusing.
fn synthetic_source_warrant(symbol: &str, body_cid: &str) -> Arc<CValue> {
    CValue::object([
        ("kind", CValue::string("source-memento")),
        ("role", CValue::string("synthetic.rss-fixture")),
        ("file", CValue::string(format!("synthetic://{symbol}"))),
        ("source_function_name", CValue::string(symbol)),
        ("source_cid", CValue::string(body_cid)),
    ])
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

fn register_body_graph(
    graph: &mut ProofGraph,
    pre: Option<&Arc<CValue>>,
    post: Option<&Arc<CValue>>,
    inv: Option<&Arc<CValue>>,
) -> ContractBody {
    let mut slots: Vec<(&str, sugar_proof_envelope::AtomMemento)> = Vec::new();
    if let Some(formula) = pre {
        slots.push(("pre", graph.register_atom(FlatAtom::new(formula.clone()))));
    }
    if let Some(formula) = post {
        slots.push(("post", graph.register_atom(FlatAtom::new(formula.clone()))));
    }
    if let Some(formula) = inv {
        slots.push(("inv", graph.register_atom(FlatAtom::new(formula.clone()))));
    }
    let slot_refs = slots
        .iter()
        .map(|(slot, atom)| (*slot, atom))
        .collect::<Vec<_>>();
    let body = graph.register_body(ContractBody::from_slots(slot_refs));
    body
}

fn add_body_discharge_callsite(graph: &mut ProofGraph, index: usize, signer_seed: Ed25519Seed) {
    let symbol = format!("rss_double_{index:04}");
    let post = eq(var("result"), ctor("*", vec![var("x"), int_const(2)]));
    let inv = eq(ctor(&symbol, vec![int_const(3)]), int_const(6));
    let formal_sort = json_to_cvalue(&int_sort());
    let post_value = json_to_cvalue(&post);
    let inv_value = json_to_cvalue(&inv);

    let mut target_args = MintContractArgs {
        evidence_term: None,
        formals: vec!["x".into()],
        emit_empty_formals: false,
        formal_sorts: vec![formal_sort],
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: None,
        contract_name: symbol.clone(),
        pre: None,
        post: Some(post_value),
        inv: None,
        out_binding: "result".into(),
        produced_by: "synthetic_rss_fixture".into(),
        produced_at: DECLARED_AT.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "synthetic_rss_fixture".into(),
            note: None,
        },
        signer_seed,
    };
    let target_body = register_body_graph(
        graph,
        target_args.pre.as_ref(),
        target_args.post.as_ref(),
        target_args.inv.as_ref(),
    );
    let target_body_cid = target_body.cid().as_str().to_string();
    target_args.source_warrants = vec![synthetic_source_warrant(&symbol, &target_body_cid)];
    let target_contract = mint_contract_with_body_cid(&target_args, Some(&target_body_cid))
        .expect("mint target contract");
    let target_cid = push_claim_contract(graph, target_contract);

    let mut source_args = MintContractArgs {
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
        contract_name: format!("{symbol}_test"),
        pre: None,
        post: None,
        inv: Some(inv_value),
        out_binding: "result".into(),
        produced_by: "synthetic_rss_fixture".into(),
        produced_at: DECLARED_AT.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "synthetic_rss_fixture".into(),
            note: None,
        },
        signer_seed,
    };
    let source_body = register_body_graph(
        graph,
        source_args.pre.as_ref(),
        source_args.post.as_ref(),
        source_args.inv.as_ref(),
    );
    let source_body_cid = source_body.cid().as_str().to_string();
    source_args.source_warrants = vec![synthetic_source_warrant(
        &source_args.contract_name.clone(),
        &source_body_cid,
    )];
    let source_contract = mint_contract_with_body_cid(&source_args, Some(&source_body_cid))
        .expect("mint source contract");
    push_claim_contract(graph, source_contract);

    let bridge = mint_bridge(&MintBridgeArgs {
        produced_by: "synthetic_rss_fixture".into(),
        produced_at: DECLARED_AT.into(),
        source_symbol: symbol,
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
    push_bridge(graph, bridge);
}

fn build_graph(callsite_count: usize) -> ProofGraph {
    let signer_seed: Ed25519Seed = [0x52u8; 32];
    let mut graph = ProofGraph::new();

    for index in 0..callsite_count {
        add_body_discharge_callsite(&mut graph, index, signer_seed);
    }

    graph
}

fn write_fixture(
    project: &Path,
    callsite_count: usize,
    compiler: Option<PathBuf>,
) -> Result<String, Box<dyn std::error::Error>> {
    if project.exists() {
        fs::remove_dir_all(project)?;
    }
    fs::create_dir_all(project.join(".sugar"))?;
    write_smt_compiler_manifest(project, compiler)?;

    let signer_seed: Ed25519Seed = [0x52u8; 32];
    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: format!("@perf/rss-floor-synthetic-{callsite_count}"),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph: build_graph(callsite_count),
        signer_cid,
        signer_seed,
        declared_at: DECLARED_AT.into(),
    });
    fs::write(
        project.join(".sugar").join(proof_filename(&built.cid)),
        &built.bytes,
    )?;
    Ok(built.cid)
}

fn parse_args() -> Result<(PathBuf, usize, Option<PathBuf>), Box<dyn std::error::Error>> {
    let mut args = env::args_os().skip(1);
    let project = args
        .next()
        .map(PathBuf::from)
        .ok_or("usage: synthetic_rss_fixture <project-dir> [callsite-count] [--compiler <path>]")?;
    let mut callsite_count = DEFAULT_CALLSITES;
    let mut compiler = None;

    while let Some(arg) = args.next() {
        if arg == "--compiler" {
            compiler = Some(
                args.next()
                    .map(PathBuf::from)
                    .ok_or("--compiler requires a path")?,
            );
        } else {
            callsite_count = arg
                .to_string_lossy()
                .parse::<usize>()
                .map_err(|_| "callsite-count must be a positive integer")?;
        }
    }

    if callsite_count == 0 {
        return Err("callsite-count must be greater than zero".into());
    }
    Ok((project, callsite_count, compiler))
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (project, callsite_count, compiler) = parse_args()?;
    let cid = write_fixture(&project, callsite_count, compiler)?;
    println!(
        "synthetic_rss_fixture project={} callsites={} bridge_mementos={} proof_cid={}",
        project.display(),
        callsite_count,
        callsite_count,
        cid
    );
    Ok(())
}
