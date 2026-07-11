// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3802 + #3808: warm overlay soundness floor.
//
// Invariant: solve_buffer / the overlay feed must NEVER return
// 0-diagnostics with degraded=false when the overlay produced no real
// consumer-anchored testimony, or when declared import deps need vendor
// universe bridges and none are present.
//
// Shapes:
//   (a) empty pool → guard fires (no consumer testimony)
//   (b) declared post-bearing deps + zero bridges → guard fires
//   (c) inject_dependency_bridges populates Bridge members from imports
//   (d) empty rust-style overlay feed → solve_buffer degraded
//   (e) planted lie → contradiction OR degraded (never false green)
//   (f) truthful twin stays free of unsatisfied when un-degraded

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::Value as CValue;
use sugar_claim_envelope::{
    mint_bridge, mint_contract_with_body_cid, Authoring, MintBridgeArgs, MintContractArgs,
};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, BridgeMemento, ClaimContractMemento, ContractBody,
    ContractMementoRef, Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};
use sugar_verifier::types::{MemberKind, MementoPool};

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn unique_dir(label: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!(
        "sugar-lsp-warm-overlay-{}-{}-{}",
        label,
        std::process::id(),
        stamp
    ));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn hex128(ch: char) -> String {
    std::iter::repeat(ch).take(128).collect()
}

fn seed() -> Ed25519Seed {
    [0x42u8; 32]
}

fn json_to_cvalue(j: &Json) -> Arc<CValue> {
    match j {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => CValue::integer(i128::from(n.as_i64().unwrap_or(0))),
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(arr) => CValue::array(arr.iter().map(json_to_cvalue).collect::<Vec<_>>()),
        Json::Object(map) => CValue::object(
            map.iter()
                .map(|(k, v)| (k.clone(), json_to_cvalue(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn write_executable(path: &Path, text: &str) {
    {
        let mut f = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(path)
            .unwrap_or_else(|e| panic!("open {}: {e}", path.display()));
        f.write_all(text.as_bytes()).expect("write");
        f.sync_all().expect("sync");
    }
    #[cfg(unix)]
    {
        let mut perms = fs::metadata(path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).expect("chmod");
    }
}

/// Mint a minimal vendor .proof: post-bearing encodeBase64 universe + inv fact.
///
/// The post MUST close after ambient specialization (formals + outBinding
/// substituted at the consumer callsite). An open post (free vars other than
/// formals/out) is dropped by `formula_is_closed` -- linkedPosts stays empty,
/// the obligation refuses vacuous, and a planted lie becomes a silent green
/// (degraded=false, 0 ERROR diagnostics). That is the #3802/#3808 false-green
/// shape the warm path must never publish.
fn mint_base64_style_vendor_proof() -> (String, Vec<u8>) {
    // Universe: encodeBase64 always yields "eHl6" (base64 of "xyz"). After
    // specialisation at call:encodeBase64("xyz") this becomes the closed
    // ground fact `= (call:encodeBase64("xyz"), "eHl6")` which conjoins with
    // the consumer inv -- good twin matches, planted lie contradicts.
    let post = json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "var", "name": "out"},
            {"kind": "const", "sort": {"kind": "primitive", "name": "String"}, "value": "eHl6"}
        ]
    });
    let inv = json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "ctor", "name": "call:encodeBase64", "args": [
                {"kind": "const", "sort": {"kind": "primitive", "name": "String"}, "value": "abc"}
            ]},
            {"kind": "const", "sort": {"kind": "primitive", "name": "String"}, "value": "YWJj"}
        ]
    });

    let mut graph = ProofGraph::new();
    let post_atom = graph.register_atom(FlatAtom::new(json_to_cvalue(&post)));
    let inv_atom = graph.register_atom(FlatAtom::new(json_to_cvalue(&inv)));
    let body = graph.register_body(ContractBody::from_slots(vec![
        ("post", &post_atom),
        ("inv", &inv_atom),
    ]));
    let body_cid = body.cid().as_str().to_string();

    let args = MintContractArgs {
        evidence_term: None,
        formals: vec!["value".into()],
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: Some("b64vendor".into()),
        bridge_source_symbol: Some("call:encodeBase64".into()),
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: Some(json_to_cvalue(&json!({
            "warrants": [{
                "kind": "Stated",
                "locus": {"path": "vendor/b64vendor.py", "line": 1, "column": 0}
            }]
        }))),
        contract_name: "encodeBase64".into(),
        pre: None,
        post: Some(json_to_cvalue(&post)),
        inv: Some(json_to_cvalue(&inv)),
        out_binding: "out".into(),
        produced_by: "warm-overlay-test".into(),
        produced_at: "1970-01-01T00:00:00.000Z".into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "warm-overlay-test".into(),
            note: None,
        },
        signer_seed: seed(),
    };
    let minted = mint_contract_with_body_cid(&args, Some(&body_cid)).expect("mint vendor");
    graph.push_claim_contract(ClaimContractMemento::new(minted.canonical_bytes));

    let bridge = mint_bridge(&MintBridgeArgs {
        produced_by: "warm-overlay-test".into(),
        produced_at: "1970-01-01T00:00:00.000Z".into(),
        source_symbol: "call:encodeBase64".into(),
        source_layer: "source".into(),
        target_contract: ContractMementoRef::new(minted.cid.clone()),
        target_layer: "kit".into(),
        ir_arg_sorts: vec![],
        ir_return_sort: String::new(),
        notes: "vendor body bridge".into(),
        signer_seed: seed(),
        target_proof_cid: None,
        callsite: None,
    });
    graph.push_bridge(BridgeMemento::new(bridge.canonical_bytes));

    let sealed = build_proof_envelope(&ProofEnvelopeInput {
        name: "vendor".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid: ed25519_pubkey_string(&seed()),
        signer_seed: seed(),
        declared_at: "1970-01-01T00:00:00.000Z".into(),
        manifest: None,
    });
    (sealed.cid, sealed.bytes)
}

fn mint_consumer_assertion_pool(name: &str, inv: &Json) -> MementoPool {
    let mut graph = ProofGraph::new();
    let inv_atom = graph.register_atom(FlatAtom::new(json_to_cvalue(inv)));
    let body = graph.register_body(ContractBody::from_slots(vec![("inv", &inv_atom)]));
    let body_cid = body.cid().as_str().to_string();
    let args = MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        bridge_source_symbol: None,
        body_discharge_eligible: false,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: vec![json_to_cvalue(&json!({
            "kind": "source-memento",
            "file": "src/lib.rs",
            "source_function_name": "t",
            "source_cid": format!("blake3-512:{}", hex128('c')),
            "template_cid": format!("blake3-512:{}", hex128('d')),
            "span": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 5},
            "param_names": []
        }))],
        proofir_provenance: Some(json_to_cvalue(&json!({
            "kind": "proofir-provenance",
            "nodeClass": "EqualityFact",
            "constructionSite": {"path": "src/lib.rs", "line": 1, "column": 0},
            "warrants": [{"kind": "Stated", "locus": {"path": "src/lib.rs", "line": 1, "column": 0}}]
        }))),
        contract_name: name.into(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(inv)),
        out_binding: "out".into(),
        produced_by: "warm-overlay-test".into(),
        produced_at: "1970-01-01T00:00:00.000Z".into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "warm-overlay-test".into(),
            note: None,
        },
        signer_seed: seed(),
    };
    let minted = mint_contract_with_body_cid(&args, Some(&body_cid)).expect("mint consumer");
    graph.push_claim_contract(ClaimContractMemento::new(minted.canonical_bytes));
    let sealed = build_proof_envelope(&ProofEnvelopeInput {
        name: "consumer".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid: ed25519_pubkey_string(&seed()),
        signer_seed: seed(),
        declared_at: "1970-01-01T00:00:00.000Z".into(),
        manifest: None,
    });
    let mut pool = MementoPool::default();
    let pb = sugar_verifier::load_all_proofs::ProofBytes::try_from_parts(
        "consumer",
        sealed.cid,
        sealed.bytes,
        sugar_verifier::Speaker::consumer("test"),
    )
    .unwrap();
    sugar_verifier::load_all_proofs::load_proof_bytes_into_pool(&[pb], &mut pool);
    pool
}

fn contract_ir_document(name: &str, file: &str, rhs: &str) -> Json {
    // Call terms are IrTerm ctors (kind=ctor), never kind=atomic -- atomic is
    // only the formula shell of `=`. A wrong kind makes sugar.enumerate fact
    // payload decode fail and the warm path degrade (honest, but never
    // exercises un-degraded contradiction).
    json!({
        "kind": "ir-document",
        "diagnostics": [],
        "ir": [{
            "kind": "contract",
            "name": name,
            "outBinding": "out",
            "inv": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "ctor", "name": "call:encodeBase64", "args": [
                        {"kind": "const", "sort": {"kind": "primitive", "name": "String"}, "value": "xyz"}
                    ]},
                    {"kind": "const", "sort": {"kind": "primitive", "name": "String"}, "value": rhs}
                ]
            },
            "proofirProvenance": {
                "kind": "proofir-provenance",
                "nodeClass": "EqualityFact",
                "constructionSite": {"path": file, "line": 1, "column": 0},
                "warrants": [
                    {"kind": "Stated", "locus": {"path": file, "line": 1, "column": 0}}
                ]
            },
            "sourceWarrants": [{
                "kind": "source-memento",
                "role": "fixture.consumer",
                "file": file,
                "source_function_name": "test_consumer",
                "source_cid": format!("blake3-512:{}", hex128('a')),
                "template_cid": format!("blake3-512:{}", hex128('b')),
                "span": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 10},
                "param_names": []
            }]
        }]
    })
}

fn mock_kit_declaration(surface: &str) -> Json {
    json!({
        "kit": {"id": surface, "language": "mock", "version": "0.0.1"},
        "rpc": {"methods": [
            {"name": "initialize", "required": true},
            {"name": "sugar.plugin.kit_declaration", "required": true},
            {"name": "sugar.enumerate", "required": true},
            {"name": "lift", "required": true},
            {"name": "shutdown", "required": false}
        ]},
        "proofResolution": {"strategy": "none"},
        "residueCategories": []
    })
}

fn write_mock_kit(project: &Path, surface: &str, mode: &str, good: &Json, bad: &Json) {
    let lift_dir = project.join(".sugar").join("lift").join(surface);
    fs::create_dir_all(&lift_dir).expect("lift dir");
    let py_path = lift_dir.join("mock_kit.py");
    let good_json = serde_json::to_string(good).unwrap();
    let bad_json = serde_json::to_string(bad).unwrap();
    let decl_json = serde_json::to_string(&mock_kit_declaration(surface)).unwrap();
    let body = format!(
        r##"#!/usr/bin/env python3
import json, sys, os
SURFACE = {surface}
MODE = {mode}
GOOD = json.loads({good_json})
BAD = json.loads({bad_json})
DECL = json.loads({decl_json})

def pick(wr):
    if MODE == "static":
        return GOOD
    if MODE == "empty":
        return {{"kind": "ir-document", "diagnostics": [], "ir": []}}
    path = os.path.join(wr or "", "src", "lib.rs")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        text = ""
    return GOOD if "GOOD_MARKER" in text else BAD

def memento(file, fn="test_consumer", line=1):
    return {{
        "kind": "source-memento",
        "file": file,
        "function_name": fn,
        "sourceFunctionName": fn,
        "span": {{"start_line": line, "start_col": 0, "end_line": line, "end_col": 10}},
        "param_names": [],
        "paramNames": [],
        "source_cid": "blake3-512:" + ("a" * 128),
        "template_cid": "blake3-512:" + ("b" * 128),
    }}

def reply(msg_id, result):
    sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg_id, "result": result}}) + "\n")
    sys.stdout.flush()

def enumerate_nodes(level, wr):
    doc = pick(wr)
    if not doc.get("ir"):
        return []
    contract = doc["ir"][0]
    inv = contract["inv"]
    warrants = contract.get("sourceWarrants") or [{{}}]
    file = warrants[0].get("file") or "src/lib.rs"
    site = memento(file)
    if level == "source_files":
        return [{{"memento": memento(file, fn=""), "audit": None, "payload": None}}]
    if level == "functions":
        return [{{"memento": memento(file), "audit": None, "payload": None}}]
    if level == "call_sites":
        return [{{
            "memento": site,
            "audit": {{
                "kind": "contract",
                "name": contract["name"],
                "bridgeSourceSymbol": "call:encodeBase64",
                "inv": inv,
                "outBinding": "out",
                "sourceWarrants": contract.get("sourceWarrants", []),
            }},
            "payload": None,
        }}]
    if level in ("assertions", "facts"):
        return [{{
            "memento": site,
            "audit": {{
                "kind": "contract",
                "name": contract["name"],
                "inv": inv,
                "outBinding": "out",
                "sourceWarrants": contract.get("sourceWarrants", []),
            }},
            "payload": inv if level == "facts" else None,
        }}]
    return []

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = msg.get("method") or ""
    msg_id = msg.get("id")
    params = msg.get("params") or {{}}
    if method == "initialize":
        reply(msg_id, {{"name": SURFACE, "protocol_version": "pep/1.7.0"}})
    elif method == "sugar.plugin.kit_declaration":
        reply(msg_id, DECL)
    elif method == "sugar.enumerate":
        nodes = enumerate_nodes(params.get("level") or "", params.get("workspace_root") or "")
        reply(msg_id, {{"nodes": nodes, "gaps": []}})
    elif method == "lift":
        wr = (params.get("workspace_root")
              or (params.get("options") or {{}}).get("workspaceRoot")
              or "")
        reply(msg_id, pick(wr))
    elif method in ("shutdown", "sugar.plugin.shutdown"):
        if msg_id is not None:
            reply(msg_id, {{}})
        break
"##,
        surface = serde_json::to_string(surface).unwrap(),
        mode = serde_json::to_string(mode).unwrap(),
        good_json = serde_json::to_string(&good_json).unwrap(),
        bad_json = serde_json::to_string(&bad_json).unwrap(),
        decl_json = serde_json::to_string(&decl_json).unwrap(),
    );
    fs::write(&py_path, &body).expect("write kit");
    write_executable(&py_path, &body);
    fs::write(
        lift_dir.join("manifest.toml"),
        format!(
            "name = \"{surface}\"\ncommand = [\"python3\", \"{}\"]\nworking_dir = \".\"\n",
            py_path.display()
        ),
    )
    .expect("manifest");
}

fn assert_never_false_green(outcome: &sugar_lsp::prove_engine::SolveOutcome, label: &str) {
    let unsatisfied = outcome
        .rows
        .iter()
        .filter(|r| r.get("status").and_then(|s| s.as_str()) == Some("unsatisfied"))
        .count();
    let empty_undegraded = outcome.rows.is_empty() && !outcome.degraded;
    assert!(
        !empty_undegraded,
        "{label}: NEVER 0-diagnostics un-degraded (false green). degraded={:?} reason={:?} rows={}",
        outcome.degraded,
        outcome.degraded_reason,
        outcome.rows.len()
    );
    assert!(
        unsatisfied > 0 || outcome.degraded,
        "{label}: planted lie must yield contradiction or degraded=true; rows={:?} reason={:?}",
        outcome.rows,
        outcome.degraded_reason
    );
}

// ---------------------------------------------------------------------------
// Unit: pure guard shapes (no kit, no z3)
// ---------------------------------------------------------------------------

#[test]
fn guard_empty_pool_is_not_consumer_testimony() {
    let pool = MementoPool::default();
    let err = sugar_lsp::prove_engine::assess_consumer_overlay_testimony(&pool)
        .expect_err("empty pool must fail testimony guard");
    assert!(
        err.contains("no consumer testimony"),
        "reason must name empty testimony: {err}"
    );
}

#[test]
fn guard_declared_deps_without_bridges_when_posts_need_them() {
    let root = unique_dir("deps-no-bridge");
    fs::create_dir_all(root.join(".sugar").join("imports")).unwrap();

    let (cid, bytes) = mint_base64_style_vendor_proof();
    fs::write(
        root.join(".sugar")
            .join("imports")
            .join(format!("{cid}.proof")),
        &bytes,
    )
    .unwrap();

    let inv = json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 1}
        ]
    });
    let pool = mint_consumer_assertion_pool("consumer#euf#c:1::assertion", &inv);
    assert_eq!(
        pool.member_count_by_kind(MemberKind::Bridge),
        0,
        "fixture must start with zero bridges"
    );
    sugar_lsp::prove_engine::assess_consumer_overlay_testimony(&pool)
        .expect("consumer candidate must pass testimony half");

    let err = sugar_lsp::prove_engine::assess_overlay_vendor_bindings(&pool, &root)
        .expect_err("post-bearing deps + zero bridges must degrade");
    assert!(
        err.contains("no vendor bindings despite declared dependencies"),
        "reason must name missing bindings: {err}"
    );

    let mut pool = pool;
    let n = sugar_cli::cmd_mint::inject_dependency_bridges_into_pool(&root, &mut pool);
    assert!(n > 0, "injection must mint at least one dependency bridge");
    assert!(
        pool.member_count_by_kind(MemberKind::Bridge) > 0,
        "pool must carry bridges after injection"
    );
    sugar_lsp::prove_engine::assess_overlay_vendor_bindings(&pool, &root)
        .expect("binding guard must pass after injection");

    fs::remove_dir_all(&root).ok();
}

#[test]
fn inject_dependency_bridges_from_imports_populates_overlay() {
    let root = unique_dir("inject");
    fs::create_dir_all(root.join(".sugar").join("imports")).unwrap();
    let (cid, bytes) = mint_base64_style_vendor_proof();
    fs::write(
        root.join(".sugar")
            .join("imports")
            .join(format!("{cid}.proof")),
        bytes,
    )
    .unwrap();

    let mut pool = MementoPool::default();
    let n = sugar_cli::cmd_mint::inject_dependency_bridges_into_pool(&root, &mut pool);
    assert!(
        n > 0,
        "must inject at least one bridge for post-bearing vendor"
    );
    assert!(
        pool.member_count_by_kind(MemberKind::Bridge) > 0,
        "overlay pool must list Bridge members"
    );
    assert!(
        pool.member_count_by_kind(MemberKind::Contract) > 0,
        "vendor contracts must be staged for body resolution"
    );
    fs::remove_dir_all(&root).ok();
}

// ---------------------------------------------------------------------------
// Integration: solve_buffer discrimination (mock kit + optional z3)
// ---------------------------------------------------------------------------

fn stage_consumer_with_vendor(
    label: &str,
    mode: &str,
    good_rhs: &str,
    bad_rhs: &str,
) -> (PathBuf, PathBuf) {
    let root = unique_dir(label);
    fs::create_dir_all(root.join("src")).unwrap();
    fs::create_dir_all(root.join(".sugar")).unwrap();
    fs::write(
        root.join(".sugar").join("config.toml"),
        "[[plugins]]\nsurface = \"mockconsumer\"\n",
    )
    .unwrap();
    fs::write(root.join("src").join("lib.rs"), "// BAD_MARKER\n").unwrap();

    let name = "encodeBase64#euf#c:call:encodeBase64(xyz)::assertion";
    write_mock_kit(
        &root,
        "mockconsumer",
        mode,
        &contract_ir_document(name, "src/lib.rs", good_rhs),
        &contract_ir_document(name, "src/lib.rs", bad_rhs),
    );

    let imports = root.join(".sugar").join("imports");
    fs::create_dir_all(&imports).unwrap();
    let (cid, bytes) = mint_base64_style_vendor_proof();
    fs::write(imports.join(format!("{cid}.proof")), bytes).unwrap();

    let file = root.join("src").join("lib.rs");
    (root, file)
}

#[test]
fn empty_rust_style_overlay_degrades_not_false_green() {
    let (root, file) = stage_consumer_with_vendor("empty-rust", "empty", "eHl6", "AAAA");
    let ctx = sugar_lsp::prove_engine::build_prove_context_for(&root);
    let outcome = sugar_lsp::prove_engine::solve_buffer(&ctx, &file, "// empty lift\n");
    assert!(
        outcome.degraded,
        "empty ir-document overlay must degrade, not false-green; reason={:?}",
        outcome.degraded_reason
    );
    let reason = outcome.degraded_reason.as_deref().unwrap_or("");
    assert!(
        reason.contains("no consumer testimony")
            || reason.contains("no consumer-anchored")
            || reason.contains("feed failed"),
        "degraded reason must name testimony/feed gap: {reason}"
    );
    fs::remove_dir_all(&root).ok();
}

#[test]
fn planted_lie_never_returns_zero_diagnostics_undegraded() {
    if !z3_available() {
        eprintln!("SKIP: z3 required for discharge discrimination");
        return;
    }
    let (root, file) = stage_consumer_with_vendor("lie", "dynamic", "eHl6", "AAAA");
    let ctx = sugar_lsp::prove_engine::build_prove_context_for(&root);

    let outcome = sugar_lsp::prove_engine::solve_buffer(&ctx, &file, "// BAD_MARKER lie\n");
    assert_never_false_green(&outcome, "planted lie");

    if !outcome.degraded {
        let unsat = outcome
            .rows
            .iter()
            .any(|r| r.get("status").and_then(|s| s.as_str()) == Some("unsatisfied"));
        assert!(
            unsat,
            "un-degraded warm path must surface contradiction: {:?}",
            outcome.rows
        );
    }

    fs::remove_dir_all(&root).ok();
}

#[test]
fn truthful_twin_stays_green_or_honestly_degrades() {
    if !z3_available() {
        eprintln!("SKIP: z3 required for truthful twin");
        return;
    }
    let (root, file) = stage_consumer_with_vendor("truth", "dynamic", "eHl6", "AAAA");
    let ctx = sugar_lsp::prove_engine::build_prove_context_for(&root);

    let outcome =
        sugar_lsp::prove_engine::solve_buffer(&ctx, &file, "// GOOD_MARKER truthful\n");
    if !outcome.degraded {
        let unsat = outcome
            .rows
            .iter()
            .filter(|r| r.get("status").and_then(|s| s.as_str()) == Some("unsatisfied"))
            .count();
        assert_eq!(
            unsat, 0,
            "truthful un-degraded path must not report unsatisfied: {:?}",
            outcome.rows
        );
    }
    fs::remove_dir_all(&root).ok();
}

/// Real daemon-path receipt for #3802 + #3808: same `solve_buffer` door the
/// LSP `didOpen`/`didChange` path calls (not a hand-built pool). Prints the
/// twin flip so a re-verify can read the statuses without re-deriving them.
#[test]
fn real_solve_buffer_path_twin_flip_receipts_3802_3808() {
    if !z3_available() {
        eprintln!("SKIP: z3 required for twin-flip receipts");
        return;
    }
    let (root, file) = stage_consumer_with_vendor("receipts", "dynamic", "eHl6", "AAAA");
    // Declared import deps (post-bearing vendor) -- #3808 surface.
    assert!(
        sugar_cli::cmd_mint::project_declares_import_dependencies(&root),
        "fixture must declare .sugar/imports deps"
    );
    let ctx = sugar_lsp::prove_engine::build_prove_context_for(&root);

    let bad = sugar_lsp::prove_engine::solve_buffer(&ctx, &file, "// BAD_MARKER lie\n");
    let good =
        sugar_lsp::prove_engine::solve_buffer(&ctx, &file, "// GOOD_MARKER truthful\n");

    let summarize = |label: &str, o: &sugar_lsp::prove_engine::SolveOutcome| {
        let statuses: Vec<&str> = o
            .rows
            .iter()
            .filter_map(|r| r.get("status").and_then(|s| s.as_str()))
            .collect();
        let unsat = statuses.iter().filter(|s| **s == "unsatisfied").count();
        eprintln!(
            "RECEIPT {label}: degraded={} reason={:?} rows={} statuses={:?} unsat={}",
            o.degraded,
            o.degraded_reason,
            o.rows.len(),
            statuses,
            unsat
        );
        (unsat, o.degraded, o.rows.is_empty())
    };

    let (bad_unsat, bad_degraded, bad_empty) = summarize("consumer-bad", &bad);
    let (good_unsat, good_degraded, _good_empty) = summarize("consumer-good", &good);

    // #3802: planted lie -- never un-degraded empty, and never silent green.
    assert!(
        !(bad_empty && !bad_degraded),
        "LAW VIOLATION #3802: consumer-bad un-degraded 0-diagnostics (false green)"
    );
    assert!(
        bad_unsat > 0 || bad_degraded,
        "LAW VIOLATION #3802: consumer-bad neither contradiction nor degraded"
    );

    // Prefer the live warm path: un-degraded feed + real contradiction on the
    // lie, green twin free of unsatisfied. That is the #3808 inject-then-solve
    // shape the unit guards alone cannot prove.
    assert!(
        !bad_degraded,
        "warm feed must be live for this fixture (not degrade); reason={:?}",
        bad.degraded_reason
    );
    assert!(
        bad_unsat > 0,
        "consumer-bad un-degraded must surface contradiction: {:?}",
        bad.rows
    );
    let mut probe = MementoPool::default();
    let n = sugar_cli::cmd_mint::inject_dependency_bridges_into_pool(&root, &mut probe);
    assert!(
        n > 0,
        "LAW VIOLATION #3808: inject minted 0 bridges for declared post-bearing imports"
    );
    assert!(
        !good_degraded,
        "consumer-good warm feed must be live; reason={:?}",
        good.degraded_reason
    );
    assert_eq!(
        good_unsat, 0,
        "consumer-good un-degraded must not report unsatisfied: {:?}",
        good.rows
    );

    fs::remove_dir_all(&root).ok();
}
