// SPDX-License-Identifier: MIT OR Apache-2.0
//
// SEAM 5 discrimination gate: `ProofGraph::solve`'s two-reds `Outcome` must
// NEVER collapse a link failure into a solver verdict, or vice versa. Both
// arms are exercised here, same box, over the same `solve()` door:
//
//   (a) a cross-kit call edge with no answering contract -> `LinkError`,
//       carrying `LinkerErrorKind::UnresolvedSymbol` -- the solver never runs.
//   (b) two contracts sharing one contract name asserting contradictory
//       facts (`add(2,3) == 5` vs `add(2,3) == 6`) -> `Verdicts` containing
//       `ObligationVerdict::Unsatisfied` -- beat 1 found nothing to bind (no
//       call edges at all), so beat 2 ran and the solver refused it.
//
// Fixture (b) follows `sugar-cli/tests/support/contradiction.rs`'s
// same-contract-name conjoin pattern (the cross-proof twin of mint's
// same-name coalesce, see `consistency.rs`'s "CROSS-PROOF CONJOIN" comment),
// simplified to a single conjoined group with no bridges: two `inv`-bearing
// contracts under one `contract_name` is the minimal input that reaches
// `verify_consistency`'s conjoin-then-SAT path.

use std::collections::HashMap;
use std::path::Path;

use serde_json::{json, Value as Json};
use sugar_claim_envelope::{mint_contract_with_body_cid, Authoring, MintContractArgs};
use sugar_compiler::orchestrate::Orchestrate;
use sugar_compiler::outcome::Outcome;
use sugar_linker::{CallSiteLocus, LinkerCallEdge, LinkerErrorKind, LinkerInputs};
use sugar_proof_envelope::{
    ClaimContractMemento, ContractBody, Ed25519Seed, FlatAtom, ProofGraph,
};
use sugar_verifier::solvers::registry;
use sugar_verifier::{ObligationVerdict, SolverPlan, SolverSeat};

fn int_sort() -> Json {
    json!({"kind": "primitive", "name": "Int"})
}
fn int_const(n: i64) -> Json {
    json!({"kind": "const", "value": n, "sort": int_sort()})
}

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

fn push_named_contract_with_inv(graph: &mut ProofGraph, contract_name: &str, inv: &Json, seed: Ed25519Seed) {
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
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: Some(json_to_cvalue(&json!({
            "warrants": [{
                "kind": "Stated",
                "locus": {"path": "sugar-compiler/tests/solve_two_reds.rs", "line": 1, "column": 0}
            }]
        }))),
        contract_name: contract_name.to_string(),
        pre: None,
        post: None,
        inv: Some(json_to_cvalue(inv)),
        out_binding: "result".into(),
        produced_by: "seam5-discrimination-test".into(),
        produced_at: "2026-07-08T00:00:00.000Z".into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: "seam5-discrimination-test".into(),
            note: None,
        },
        signer_seed: seed,
    };
    let minted = mint_contract_with_body_cid(&args, Some(&body_cid)).expect("mint contract");
    let memento = ClaimContractMemento::new(minted.canonical_bytes);
    graph.push_claim_contract(memento);
}

fn empty_registry() -> HashMap<SolverSeat, sugar_verifier::SolverHandle> {
    HashMap::new()
}

fn test_compilers() -> sugar_ir_compiler::registry::Registry {
    let mut compilers = sugar_ir_compiler::registry::Registry::new();
    compilers.register(std::sync::Arc::new(
        sugar_ir_compiler_smt_lib::SmtLibCompiler::new(),
    ));
    compilers
}

/// (a) LinkError arm: a call edge whose target symbol answers nothing in
/// the contract union. `bind`'s only two outcomes for an edge are
/// `Ok(BoundContractCid)` or the typed `UnresolvedSymbol`/`SignatureMismatch`
/// refusal (`sugar-linker/src/lib.rs`'s `bind`); this fixture hits the first
/// of those. `solve` must short-circuit to `Outcome::LinkError` WITHOUT
/// touching the graph's (empty) contents at all.
#[test]
fn unresolved_cross_kit_symbol_yields_link_error_not_verdicts() {
    let call_edge = LinkerCallEdge {
        source_contract_cid: ("blake3-512:".to_string() + &"aa".repeat(64)).into(),
        target_contract_cid: None, // cross-kit -> null, must resolve by symbol
        target_symbol: "nonexistent-kit:does_not_exist".into(),
        call_site_locus: Some(CallSiteLocus {
            file: "seam5_fixture.rs".into(),
            line: Some(1),
            column: Some(1),
        }),
        ..Default::default()
    };
    let links = LinkerInputs {
        contracts: Vec::new(), // no contract answers the target symbol
        call_edges: vec![call_edge],
    };
    let graph = ProofGraph::empty();
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let registry = empty_registry();
    let compilers = test_compilers();

    let outcome = graph.solve(links, &plan, &registry, &compilers, Path::new("."));

    match outcome {
        Outcome::LinkError(errors) => {
            assert_eq!(errors.len(), 1, "exactly one unresolved edge: {errors:?}");
            assert_eq!(
                errors[0].kind,
                LinkerErrorKind::UnresolvedSymbol,
                "must be UnresolvedSymbol, not a solver-side kind: {errors:?}"
            );
        }
        Outcome::Verdicts(v) => panic!(
            "link failure must NEVER surface as a solver verdict (frontier-masked green): {v:?}"
        ),
    }
}

/// (b) Verdicts arm: no call edges to bind (beat 1 is vacuously clean), so
/// beat 2 runs. Two contracts sharing one `contract_name` assert
/// contradictory facts about the same callsite; the cross-proof conjoin in
/// `verify_consistency` ANDs them, Z3 finds UNSAT, and the group refuses as
/// `Unsatisfied`.
#[test]
fn same_name_contradiction_yields_unsatisfied_verdict_not_link_error() {
    let seed: Ed25519Seed = [0x55; 32];
    let mut graph = ProofGraph::new();
    let name = "seam5::add#euf#fixture";

    let inv_eq_5 = json!({
        "kind": "atomic", "name": "=",
        "args": [{"kind": "var", "name": "add_2_3"}, int_const(5)]
    });
    let inv_eq_6 = json!({
        "kind": "atomic", "name": "=",
        "args": [{"kind": "var", "name": "add_2_3"}, int_const(6)]
    });
    push_named_contract_with_inv(&mut graph, name, &inv_eq_5, seed);
    push_named_contract_with_inv(&mut graph, name, &inv_eq_6, seed);

    let links = LinkerInputs {
        contracts: Vec::new(),
        call_edges: Vec::new(), // nothing to bind -> beat 1 is clean
    };
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let registry = registry::build_default_z3("z3");
    let compilers = test_compilers();

    let outcome = graph.solve(links, &plan, &registry, &compilers, Path::new("."));

    match outcome {
        Outcome::LinkError(errors) => panic!(
            "a real UNSAT verdict must never be masked as an (empty) link failure: {errors:?}"
        ),
        Outcome::Verdicts(results) => {
            assert!(
                results
                    .iter()
                    .any(|r| r.verdict == ObligationVerdict::Unsatisfied),
                "contradictory same-name assertions must yield Unsatisfied: {results:?}"
            );
        }
    }
}
