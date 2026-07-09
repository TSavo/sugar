// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar#3857 discrimination gate: `derive_linker_inputs` must derive
// `LinkerInputs` from a pool's REAL bridge data (not hand-built
// `LinkerInputs`, which is `solve_two_reds.rs`'s SEAM-5 fixture and proves
// nothing about production shape). Both arms run over a `MementoPool` built
// through the SAME loader every `.proof` consumer uses
// (`load_proof_bytes_into_pool`), over a graph built through the SAME
// signed-contract minting path production uses (`mint_contract_with_body_cid`).
//
//   (a) UNRESOLVED: a contract's own panic-locus call occurrence names a
//       callee for which NO bridge memento was ever minted/loaded. This is
//       the silent-vacuous gap sugar#3857 exists to close: today,
//       `verify_consistency` over this exact pool reports NOTHING for that
//       callsite (no bridge => no obligation => nothing to fail on, a
//       vacuous pass by omission). `derive_linker_inputs` must turn that
//       SAME absence into a `LinkerCallEdge` whose `target_contract_cid` is
//       `None`; `Orchestrate::solve_deriving_links` must then yield
//       `Outcome::LinkError(UnresolvedSymbol)` naming the callee.
//   (b) RESOLVED: the same shape, but with a real `Bridge` memento present
//       (minted the same way `load_all_proofs` indexes one:
//       `MemberKind::Bridge`, `bridges_by_callsite`-keyed) naming the same
//       callee and pointing at a real contract member. The edge binds; the
//       `LinkError` arm is EMPTY; discharge proceeds to `Outcome::Verdicts`.

use std::path::Path;

use serde_json::{json, Value as Json};
use sugar_claim_envelope::{mint_contract_with_body_cid, Authoring, MintContractArgs};
use sugar_compiler::linker_inputs::derive_linker_inputs;
use sugar_compiler::orchestrate::Orchestrate;
use sugar_compiler::outcome::Outcome;
use sugar_linker::LinkerErrorKind;
use sugar_proof_envelope::{
    build_proof_envelope, BridgeMemento, ClaimContractMemento, ContractBody, Ed25519Seed, FlatAtom,
    ProofEnvelopeInput, ProofGraph,
};
use sugar_verifier::load_all_proofs::{load_proof_bytes_into_pool, ProofBytes};
use sugar_verifier::solvers::registry;
use sugar_verifier::{
    LegacyZ3Fallback, MementoPool, Runner, RunnerConfig, SolverPlan, SolverSeat, Speaker,
};

const SEED: Ed25519Seed = [0x57; 32]; // 'W' for #3857

const CALLEE_SYMBOL: &str = "kit:target_fn";
const CALLSITE_FILE: &str = "seam_3857_fixture.rs";
const CALLSITE_LINE: usize = 10;

fn json_to_cvalue(j: &Json) -> std::sync::Arc<sugar_canonicalizer::Value> {
    use sugar_canonicalizer::Value as CValue;
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

fn bare_cid(fill: char) -> String {
    format!("blake3-512:{}", fill.to_string().repeat(128))
}

/// A minimal but real, signed contract member: an `inv` claim (`true`), plus
/// -- for the caller -- a `panicLoci` occurrence naming `CALLEE_SYMBOL` at
/// `(CALLSITE_FILE, CALLSITE_LINE)`. This is the SAME per-occurrence field
/// `enumerate_callsites::run` reads regardless of whether a bridge answers
/// it (see `sugar-compiler/src/linker_inputs.rs`'s module doc).
fn push_caller_contract(graph: &mut ProofGraph, contract_name: &str) {
    let inv = json!({"kind": "atomic", "name": "true", "args": []});
    let inv_atom = graph.register_atom(FlatAtom::new(json_to_cvalue(&inv)));
    let body = graph.register_body(ContractBody::from_slots(vec![("inv", &inv_atom)]));
    let body_cid = body.cid().as_str().to_string();
    let panic_locus = json_to_cvalue(&json!({
        "callee": CALLEE_SYMBOL,
        "file": CALLSITE_FILE,
        "line": CALLSITE_LINE,
    }));
    let args = MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        bridge_source_symbol: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: vec![panic_locus],
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: Some(json_to_cvalue(&json!({
            "warrants": [{
                "kind": "Stated",
                "locus": {"path": "sugar-compiler/tests/derive_linker_inputs.rs", "line": 1, "column": 0}
            }]
        }))),
        contract_name: contract_name.to_string(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(&inv)),
        out_binding: "result".into(),
        produced_by: "seam-3857-discrimination-test".into(),
        produced_at: "2026-07-08T00:00:00.000Z".into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "seam-3857-discrimination-test".into(),
            note: None,
        },
        signer_seed: SEED,
    };
    let minted = mint_contract_with_body_cid(&args, Some(&body_cid)).expect("mint caller contract");
    graph.push_claim_contract(ClaimContractMemento::new(minted.canonical_bytes));
}

/// A minimal but real, signed contract member the bridge (arm b) points at.
/// Returns its contract CID.
fn push_callee_contract(graph: &mut ProofGraph, contract_name: &str) -> String {
    let inv = json!({"kind": "atomic", "name": "true", "args": []});
    let inv_atom = graph.register_atom(FlatAtom::new(json_to_cvalue(&inv)));
    let body = graph.register_body(ContractBody::from_slots(vec![("inv", &inv_atom)]));
    let body_cid = body.cid().as_str().to_string();
    let args = MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        bridge_source_symbol: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: Some(json_to_cvalue(&json!({
            "warrants": [{
                "kind": "Stated",
                "locus": {"path": "sugar-compiler/tests/derive_linker_inputs.rs", "line": 1, "column": 0}
            }]
        }))),
        contract_name: contract_name.to_string(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(&inv)),
        out_binding: "result".into(),
        produced_by: "seam-3857-discrimination-test".into(),
        produced_at: "2026-07-08T00:00:00.000Z".into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "seam-3857-discrimination-test".into(),
            note: None,
        },
        signer_seed: SEED,
    };
    let minted = mint_contract_with_body_cid(&args, Some(&body_cid)).expect("mint callee contract");
    let cid = minted.cid.clone();
    graph.push_claim_contract(ClaimContractMemento::new(minted.canonical_bytes));
    cid
}

/// A real `MemberKind::Bridge` member (the lean layered shape:
/// `envelope`+`header`+`metadata`, no signature -- `member_signature`
/// returns `None` for a member with no `envelope.signature`/
/// `producerSignature`/`signature` field, so `AnchoredMember::new` skips
/// crypto verification exactly as it does for any other unsigned bridge).
/// Its `header.callsite` is what `load_all_proofs` indexes into
/// `bridges_by_callsite` (`BundleScopedCallsiteKey`), which is the ONLY
/// index `enumerate_callsites::callsite_from_panic_locus` consults for a
/// panic-locus occurrence.
fn push_bridge(graph: &mut ProofGraph, target_contract_cid: &str) {
    let wire = json!({
        "envelope": {"signer": "ed25519:stub", "declaredAt": "2026-07-08T00:00:00.000Z"},
        "header": {
            "kind": "bridge",
            "cid": bare_cid('b'),
            "sourceSymbol": CALLEE_SYMBOL,
            "targetContractCid": target_contract_cid,
            "callsite": {"file": CALLSITE_FILE, "start_line": CALLSITE_LINE},
        },
        "metadata": {},
    });
    let bytes = wire.to_string().into_bytes();
    graph.push_bridge(BridgeMemento::new(bytes));
}

/// Self-load `graph` through the SAME loader every `.proof` consumer uses
/// (mirrors `sugar_compiler::orchestrate`'s own self-load round trip).
fn load_into_pool(graph: &ProofGraph) -> MementoPool {
    let proof_input = ProofEnvelopeInput {
        name: "seam-3857-fixture".to_string(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata: None,
        graph: graph.clone(),
        signer_cid: sugar_proof_envelope::ed25519_pubkey_string(&SEED),
        signer_seed: SEED,
        declared_at: "1970-01-01T00:00:00.000Z".to_string(),
        manifest: None,
    };
    let sealed = build_proof_envelope(&proof_input);
    let mut pool = MementoPool::default();
    let proof_bytes = ProofBytes::try_from_parts(
        "seam-3857-fixture",
        sealed.cid.clone(),
        sealed.bytes,
        Speaker::consumer("seam-3857-fixture"),
    )
    .expect("stage self-sealed fixture proof bytes");
    load_proof_bytes_into_pool(&[proof_bytes], &mut pool);
    assert!(
        pool.load_errors.is_empty(),
        "fixture pool must load cleanly: {:?}",
        pool.load_errors
    );
    pool
}

fn test_compilers() -> sugar_ir_compiler::registry::Registry {
    let mut compilers = sugar_ir_compiler::registry::Registry::new();
    compilers.register(std::sync::Arc::new(
        sugar_ir_compiler_smt_lib::SmtLibCompiler::new(),
    ));
    compilers
}

/// (a) UNRESOLVED arm: no bridge for `CALLEE_SYMBOL` was ever minted, so
/// `bridges_by_callsite` has no entry for it. Demonstrate the vacuous-pass
/// contrast FIRST -- `verify_consistency` over this exact pool reports
/// nothing for the missing callee (no obligation was ever derived for it) --
/// then show `derive_linker_inputs` + `solve_deriving_links` closes that gap.
#[test]
fn unresolved_callee_is_vacuous_in_verify_consistency_but_link_error_via_derivation() {
    let mut graph = ProofGraph::new();
    push_caller_contract(&mut graph, "seam3857::caller#unresolved");
    let pool = load_into_pool(&graph);

    // VACUOUS-PASS CONTRAST: today's `verify_consistency` never sees the
    // missing callee as a failure -- no row mentions it, because no bridge
    // means no obligation was ever constructed to fail on. This is the
    // silent-vacuous gap sugar#3857 names.
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let registry = registry::build_default_z3("z3");
    let compilers = test_compilers();
    let verdicts = sugar_verifier::consistency::verify_consistency(
        &pool,
        &plan,
        &registry,
        &compilers,
        Path::new("."),
    );
    assert!(
        verdicts
            .iter()
            .all(|r| !format!("{r:?}").contains(CALLEE_SYMBOL)),
        "vacuous-contrast premise violated: verify_consistency already mentions the \
         unresolved callee without any derivation -- {verdicts:?}"
    );

    // Derivation: the absence becomes a typed edge.
    let links = derive_linker_inputs(&pool).expect("well-formed pool must derive");
    let unresolved_edge = links
        .call_edges
        .iter()
        .find(|e| e.target_symbol.to_string() == CALLEE_SYMBOL)
        .unwrap_or_else(|| panic!("no call edge derived for {CALLEE_SYMBOL}: {links:?}"));
    assert!(
        unresolved_edge.target_contract_cid.is_none(),
        "unresolved callee must derive to a null target_contract_cid: {unresolved_edge:?}"
    );

    // solve_deriving_links: the typed edge must fire LinkError.
    let graph_for_solve = graph;
    let outcome = graph_for_solve
        .solve_deriving_links(&plan, &registry, &compilers, Path::new("."))
        .expect("solve_deriving_links must stage this well-formed graph");
    match outcome {
        Outcome::LinkError(errors) => {
            assert!(
                errors
                    .iter()
                    .any(|e| e.kind == LinkerErrorKind::UnresolvedSymbol
                        && e.target_symbol == CALLEE_SYMBOL),
                "expected UnresolvedSymbol naming {CALLEE_SYMBOL}: {errors:?}"
            );
        }
        Outcome::Verdicts(v) => panic!(
            "the pool's silence must never surface as a clean solver verdict \
             (frontier-masked green): {v:?}"
        ),
    }
}

/// Seal `graph` through the production envelope path and write it as a
/// `.proof` file under a fresh temp project dir, so `load_all_proofs::run`
/// (and therefore `solve_project`'s `load_pool`) picks it up exactly as it
/// picks up any on-disk project proof.
fn seal_to_temp_project(graph: &ProofGraph) -> tempfile::TempDir {
    let proof_input = ProofEnvelopeInput {
        name: "seam-3859-fixture".to_string(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata: None,
        graph: graph.clone(),
        signer_cid: sugar_proof_envelope::ed25519_pubkey_string(&SEED),
        signer_seed: SEED,
        declared_at: "1970-01-01T00:00:00.000Z".to_string(),
        manifest: None,
    };
    let sealed = build_proof_envelope(&proof_input);
    // v1.1.0 load rule 1: the `.proof` filename stem must be the hex
    // `blake3-512` CID, so the on-disk loader can content-address it.
    let stem = sealed
        .cid
        .strip_prefix("blake3-512:")
        .expect("sealed cid is blake3-512");
    let dir = tempfile::tempdir().expect("temp project dir");
    std::fs::write(dir.path().join(format!("{stem}.proof")), &sealed.bytes)
        .expect("write fixture proof");
    dir
}

/// sugar#3859 "annotate not block" receipt: `solve_project` over a pool with
/// an UNBRIDGED callsite must (1) carry a non-empty `link_errors` (beat 1
/// annotated the unresolved edge) AND (2) return an `artifact.report`
/// BYTE-IDENTICAL to a direct `Runner::run_with_proof_run` over the SAME
/// on-disk pool -- proving the link errors neither suppress nor alter the
/// real pipeline's output. If beat 1 short-circuited on the non-empty
/// link_errors, the report would be absent/empty and this would fail.
#[test]
fn solve_project_annotates_link_errors_without_altering_the_report() {
    let mut graph = ProofGraph::new();
    push_caller_contract(&mut graph, "seam3859::caller#unbridged");
    let dir = seal_to_temp_project(&graph);

    let make_cfg = || RunnerConfig {
        project_root: dir.path().to_path_buf(),
        legacy_z3_fallback: Some(LegacyZ3Fallback::compat("z3")),
        ..Default::default()
    };

    // Production door.
    let proven = sugar_compiler::orchestrate::solve_project(make_cfg(), test_compilers())
        .expect("solve_project must stage this well-formed on-disk pool");

    // (1) beat 1 ANNOTATED the unbridged callsite.
    assert!(
        proven.has_link_errors(),
        "an unbridged callsite must surface as a non-empty link_errors annotation: {:?}",
        proven.link_errors
    );
    assert!(
        proven
            .link_errors
            .iter()
            .any(|e| e.kind == LinkerErrorKind::UnresolvedSymbol
                && e.target_symbol == CALLEE_SYMBOL),
        "expected an UnresolvedSymbol naming {CALLEE_SYMBOL}: {:?}",
        proven.link_errors
    );

    // (2) beat 2's report is byte-identical to a direct Runner run over the
    // SAME on-disk pool -- the link errors did NOT block or alter it.
    let direct = Runner::new_with_compilers(make_cfg(), test_compilers())
        .run_with_proof_run()
        .expect("direct run over the same pool");
    assert_eq!(
        format!("{:?}", proven.artifact.report),
        format!("{:?}", direct.report),
        "solve_project's report must be byte-identical to a direct Runner run \
         over the same pool (annotate-not-block)"
    );
}

/// (b) RESOLVED arm: a real bridge memento names `CALLEE_SYMBOL` and points
/// at a real contract member. The edge binds; `LinkError` must be EMPTY and
/// discharge must proceed to `Outcome::Verdicts`.
#[test]
fn resolved_callee_binds_and_reaches_verdicts_not_link_error() {
    let mut graph = ProofGraph::new();
    let callee_cid = push_callee_contract(&mut graph, "seam3857::callee#resolved");
    push_caller_contract(&mut graph, "seam3857::caller#resolved");
    push_bridge(&mut graph, &callee_cid);

    let pool = load_into_pool(&graph);
    let links = derive_linker_inputs(&pool).expect("well-formed pool must derive");
    let resolved_edge = links
        .call_edges
        .iter()
        .find(|e| e.target_symbol.to_string() == CALLEE_SYMBOL)
        .unwrap_or_else(|| panic!("no call edge derived for {CALLEE_SYMBOL}: {links:?}"));
    assert_eq!(
        resolved_edge
            .target_contract_cid
            .as_ref()
            .map(|c| c.as_str()),
        Some(callee_cid.as_str()),
        "resolved callee must derive to the bridge's real target_contract_cid: {resolved_edge:?}"
    );

    let plan = SolverPlan::Single(SolverSeat::Z3);
    let registry = registry::build_default_z3("z3");
    let compilers = test_compilers();
    let outcome = graph
        .solve_deriving_links(&plan, &registry, &compilers, Path::new("."))
        .expect("solve_deriving_links must stage this well-formed graph");

    match outcome {
        Outcome::LinkError(errors) => {
            panic!("a real bridge resolution must never surface as a link failure: {errors:?}")
        }
        Outcome::Verdicts(results) => {
            eprintln!("resolved-arm verdicts: {results:?}");
        }
    }
}

/// Push a signed contract whose `formalSorts` carries the caller-supplied
/// raw JSON (well-formed or not): the mint path stores `formal_sorts` as raw
/// canonical values, so a malformed `Sort` rides through minting and loading
/// untouched -- exactly the shape sugar#3869's `.ok()` swallow used to thin
/// silently at derivation time.
/// Returns the minted contract CID: the resolved BODY shape carries no
/// `contractName` (the name rides in the member header), so the CID is the
/// name the typed error and the derived union key on.
fn push_contract_with_formal_sorts(
    graph: &mut ProofGraph,
    contract_name: &str,
    sort_json: &Json,
) -> String {
    let inv = json!({"kind": "atomic", "name": "true", "args": []});
    let inv_atom = graph.register_atom(FlatAtom::new(json_to_cvalue(&inv)));
    let body = graph.register_body(ContractBody::from_slots(vec![("inv", &inv_atom)]));
    let body_cid = body.cid().as_str().to_string();
    let args = MintContractArgs {
        evidence_term: None,
        formals: vec!["x".to_string()],
        emit_empty_formals: false,
        formal_sorts: vec![json_to_cvalue(sort_json)],
        library: None,
        bridge_source_symbol: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: Some(json_to_cvalue(&json!({
            "warrants": [{
                "kind": "Stated",
                "locus": {"path": "sugar-compiler/tests/derive_linker_inputs.rs", "line": 1, "column": 0}
            }]
        }))),
        contract_name: contract_name.to_string(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(&inv)),
        out_binding: "result".into(),
        produced_by: "seam-3869-discrimination-test".into(),
        produced_at: "2026-07-08T00:00:00.000Z".into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "seam-3869-discrimination-test".into(),
            note: None,
        },
        signer_seed: SEED,
    };
    let minted = mint_contract_with_body_cid(&args, Some(&body_cid)).expect("mint sorted contract");
    let cid = minted.cid.clone();
    graph.push_claim_contract(ClaimContractMemento::new(minted.canonical_bytes));
    cid
}

/// sugar#3869 discrimination pair, malformed arm: a `formalSorts` entry that
/// is not a decodable `Sort` must be a TYPED load error naming the contract
/// -- both from `derive_linker_inputs` directly and through
/// `solve_deriving_links` (as `SolveError::MalformedContract`) -- never a
/// silently-dropped element (the old `filter_map(.ok())` false green).
#[test]
fn malformed_formal_sort_is_typed_error_naming_the_contract() {
    const CONTRACT: &str = "seam3869::malformed_sort";
    let mut graph = ProofGraph::new();
    let cid = push_contract_with_formal_sorts(
        &mut graph,
        CONTRACT,
        &json!({"kind": "no-such-sort-kind"}),
    );
    let pool = load_into_pool(&graph);

    let err = derive_linker_inputs(&pool)
        .expect_err("a malformed formalSorts entry must be a typed error, not a dropped element");
    assert_eq!(
        err.contract_cid, cid,
        "the typed error must name the offending contract by CID: {err}"
    );
    assert_eq!(err.field, "formalSorts entry", "wrong field named: {err}");

    // Through the production door: solve_deriving_links must refuse with the
    // same typed precondition failure, never proceed to link/discharge over a
    // silently-thinned contract union.
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let registry = registry::build_default_z3("z3");
    let compilers = test_compilers();
    match graph.solve_deriving_links(&plan, &registry, &compilers, Path::new(".")) {
        Err(sugar_compiler::orchestrate::SolveError::MalformedContract(e)) => {
            assert_eq!(
                e.field, "formalSorts entry",
                "SolveError must carry the typed field naming: {e}"
            );
        }
        other => panic!(
            "expected SolveError::MalformedContract naming {CONTRACT}, got {other:?}"
        ),
    }
}

/// sugar#3869 discrimination pair, well-formed arm: the SAME contract shape
/// with a decodable `Sort` derives unchanged -- the sort arrives in the
/// derived contract, and `solve_deriving_links` proceeds past derivation
/// (no `MalformedContract`).
#[test]
fn well_formed_formal_sort_derives_unchanged() {
    const CONTRACT: &str = "seam3869::well_formed_sort";
    let mut graph = ProofGraph::new();
    let cid = push_contract_with_formal_sorts(
        &mut graph,
        CONTRACT,
        &json!({"kind": "primitive", "name": "Int"}),
    );
    let pool = load_into_pool(&graph);

    let links = derive_linker_inputs(&pool).expect("well-formed formalSorts must derive");
    let contract = links
        .contracts
        .iter()
        .find(|c| c.contract_cid.as_str() == cid)
        .unwrap_or_else(|| panic!("derived union must contain {CONTRACT} ({cid}): {links:?}"));
    assert_eq!(
        contract.formal_sorts.len(),
        1,
        "the well-formed sort must arrive, not be dropped: {contract:?}"
    );

    let plan = SolverPlan::Single(SolverSeat::Z3);
    let registry = registry::build_default_z3("z3");
    let compilers = test_compilers();
    match graph.solve_deriving_links(&plan, &registry, &compilers, Path::new(".")) {
        Err(e) => panic!("well-formed contract data must never refuse derivation: {e}"),
        Ok(outcome) => eprintln!("well-formed-arm outcome: {outcome:?}"),
    }
}
