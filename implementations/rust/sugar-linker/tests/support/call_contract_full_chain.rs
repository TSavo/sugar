use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use sugar_claim_envelope::{mint_contract, Authoring, MintContractArgs};
use sugar_ir_types::Sort;
use sugar_linker::{
    AuthenticatedCallContractCatalog, CallContractDemandV1, Cid, SourceFragmentCoordinateV1,
};

pub fn cid(fill: char) -> Cid {
    Cid::from(format!("blake3-512:{}", fill.to_string().repeat(128)))
}

fn json_to_cvalue(j: &serde_json::Value) -> std::sync::Arc<sugar_canonicalizer::Value> {
    use sugar_canonicalizer::Value as CValue;
    match j {
        serde_json::Value::Null => CValue::null(),
        serde_json::Value::Bool(value) => CValue::boolean(*value),
        serde_json::Value::Number(value) => CValue::integer(i128::from(value.as_i64().unwrap())),
        serde_json::Value::String(value) => CValue::string(value.clone()),
        serde_json::Value::Array(items) => {
            CValue::array(items.iter().map(json_to_cvalue).collect())
        }
        serde_json::Value::Object(map) => CValue::object(
            map.iter()
                .map(|(key, value)| (key.clone(), json_to_cvalue(value)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn contract_args(seed: u8) -> MintContractArgs {
    MintContractArgs {
        contract_name: "pandas.fixture.pair".into(),
        pre: None,
        post: Some(json_to_cvalue(&serde_json::json!({
            "kind":"atomic", "name":"=", "args":[
                {"kind":"var","name":"out"},
                {"kind":"ctor","name":"python:tuple","args":[{"kind":"var","name":"x"}]}
            ]
        }))),
        inv: None,
        evidence_term: None,
        out_binding: "out".into(),
        produced_by: "call-contract-full-chain-negative-test".into(),
        produced_at: "2026-07-22T00:00:00.000Z".into(),
        input_cids: vec![],
        authoring: Authoring::KitAuthor {
            author: format!("provider-{seed}"),
            note: None,
        },
        signer_seed: [seed; 32],
        formals: vec!["x".into()],
        emit_empty_formals: false,
        formal_sorts: vec![json_to_cvalue(
            &serde_json::json!({"kind":"primitive","name":"Value"}),
        )],
        library: None,
        bridge_source_symbol: Some("python:pandas.fixture.pair".into()),
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: vec![],
        class_shapes: vec![],
        source_warrants: vec![],
        proofir_provenance: None,
    }
}

pub fn catalog(seeds: &[u8]) -> AuthenticatedCallContractCatalog {
    let members = seeds
        .iter()
        .map(|seed| {
            let minted = mint_contract(&contract_args(*seed)).unwrap();
            (
                Cid::from(minted.cid),
                serde_json::from_slice(&minted.canonical_bytes).unwrap(),
            )
        })
        .collect();
    AuthenticatedCallContractCatalog::freeze(members).unwrap()
}

pub fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf()
}

fn python_paths(repo: &Path) -> std::ffi::OsString {
    let roots = std::fs::read_dir(repo.join("implementations/python"))
        .unwrap()
        .filter_map(Result::ok)
        .map(|entry| entry.path().join("src"))
        .filter(|path| path.is_dir())
        .collect::<Vec<_>>();
    std::env::join_paths(roots).unwrap()
}

pub fn enrolled_demand(repo: &Path, source: &str) -> CallContractDemandV1 {
    let script = r#"
import json, pathlib, sys, tempfile
from sugar_lift_py_tests import lift_rpc
with tempfile.TemporaryDirectory() as raw:
    root = pathlib.Path(raw)
    (root / 'consumer.py').write_text(sys.stdin.read())
    rows = [r for r in lift_rpc._call_contract_demand_rows(root)
            if r.get('kind') == 'call-contract-demand']
    assert len(rows) == 1, rows
    print(json.dumps(rows[0]))
"#;
    let mut child = Command::new("python3")
        .env("PYTHONPATH", python_paths(repo))
        .arg("-c")
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .as_mut()
        .unwrap()
        .write_all(source.as_bytes())
        .unwrap();
    drop(child.stdin.take());
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let row: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let use_site: SourceFragmentCoordinateV1 =
        serde_json::from_value(row["useSite"].clone()).unwrap();
    let sorts: Vec<Sort> = serde_json::from_value(row["importSignature"]["sorts"].clone()).unwrap();
    let formals: Vec<String> =
        serde_json::from_value(row["importSignature"]["formals"].clone()).unwrap();
    CallContractDemandV1::new(
        use_site,
        Cid::from(row["importBindingCid"].as_str().unwrap()),
        row["targetSymbol"].as_str().unwrap().into(),
        formals,
        sorts,
    )
}

pub fn python_chain_verdict(
    repo: &Path,
    source: &str,
    table: &serde_json::Value,
) -> serde_json::Value {
    let script = r#"
import json, pathlib, sys, tempfile
from types import MappingProxyType
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.call_contract_resolution import CallContractRefProtocolError, decode_resolved_call_contract_refs
from sugar_lift_py_tests.context_manager_resolution import ResolvedContractRefsV1, TreeConstructionContextV1
from sugar_source_tree.nodes import Call
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
payload = json.load(sys.stdin)
try:
    table = decode_resolved_call_contract_refs(payload['table'])
except CallContractRefProtocolError as error:
    print(json.dumps({'stage':'intake', 'gap':str(error), 'edge':None}))
    raise SystemExit(0)
with tempfile.TemporaryDirectory() as raw:
    root = pathlib.Path(raw)
    path = root / 'consumer.py'
    path.write_text(payload['source'])
    cm = ResolvedContractRefsV1(table.catalog_cid, 'blake3-512:' + '0' * 128, MappingProxyType({}))
    tree = SourceFile(path_source(str(path)), construction_context=TreeConstructionContextV1(
        cm, call_contract_refs=table, workspace_root=str(root)))
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    try:
        outcome = call.sugar().desugar(None)
    except SugarNotWritten as error:
        print(json.dumps({'stage':'construction', 'gap':str(error), 'edge':None}))
        raise SystemExit(0)
    edges = outcome.value.callsites()
    print(json.dumps({'stage':'edge', 'gap':None, 'edgeCount':len(edges)}))
"#;
    let mut child = Command::new("python3")
        .env("PYTHONPATH", python_paths(repo))
        .arg("-c")
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    serde_json::to_writer(
        child.stdin.as_mut().unwrap(),
        &serde_json::json!({"source": source, "table": table}),
    )
    .unwrap();
    drop(child.stdin.take());
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
