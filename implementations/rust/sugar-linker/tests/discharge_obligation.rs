// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Integration tests for the post-implies-pre discharge check
// (issue #249, the soundness hole closed by this commit).
//
// Acceptance cases (from #249):
//   1. identical predicate bodies                            -> discharged
//   2. structurally distinct, logically equivalent           -> discharged via solver
//   3. logically incompatible (post weaker than callee pre)  -> implication-unprovable
//   4. caller post implies callee pre via solver             -> discharged
//
// Plumbing tests (cases 2 / 3 / 4) use the verifier's `StubSolver` so
// they run hermetically without z3 / cvc5 / coq on PATH. The
// stub-driven tests prove the dispatch is wired correctly: registry
// lookup -> SolverPlan execution -> verdict mapping. They do NOT
// prove the SMT-LIB compile is semantically faithful (a real-solver
// integration test on top of a hermetic CI runner is the follow-up).
//
// A real-solver smoke test (#[ignore]'d unless `SUGAR_REAL_SOLVER`
// env var is set) runs against the configured z3 binary and exercises
// the full pipeline.

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_linker::solver_api::{
    registry, ObligationVerdict, SolverHandle, SolverPlan, SolverSeat, SolversConfig, StubSolver,
};
use sugar_linker::{
    link, link_with_solvers, CallSiteLocus, LinkerCallEdge, LinkerContract, LinkerInputs, Registry,
};

// -------------------------------------------------------------------
// Test-fixture helpers
// -------------------------------------------------------------------

const CALLER_CID: &str = "blake3-512:1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
const CALLEE_CID: &str = "blake3-512:2222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222";

fn ge_x_n(n: i64) -> Json {
    json!({
        "kind": "atomic",
        "name": ">=",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": n, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    })
}

fn lt_x_n(n: i64) -> Json {
    json!({
        "kind": "atomic",
        "name": "<",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": n, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    })
}

fn and_of(a: Json, b: Json) -> Json {
    json!({"kind": "and", "operands": [a, b]})
}

fn to_formula(v: Json) -> sugar_ir_types::IrFormula {
    serde_json::from_value(v).expect("test formula must be a valid IrFormula")
}

fn caller(post: Option<Json>) -> LinkerContract {
    LinkerContract {
        name: "caller".into(),
        kit: "rust-kit".into(),
        contract_cid: CALLER_CID.into(),
        pre_json: None,
        post_json: post.map(to_formula),
        ..Default::default()
    }
}

fn callee(pre: Option<Json>) -> LinkerContract {
    LinkerContract {
        name: "callee".into(),
        kit: "rust-kit".into(),
        contract_cid: CALLEE_CID.into(),
        pre_json: pre.map(to_formula),
        post_json: None,
        ..Default::default()
    }
}

fn cgo_edge() -> LinkerCallEdge {
    LinkerCallEdge {
        source_contract_cid: CALLER_CID.into(),
        target_contract_cid: Some(CALLEE_CID.into()),
        target_symbol: "rust-kit:callee".into(),
        call_site_locus: Some(CallSiteLocus {
            file: "caller.rs".into(),
            line: Some(1),
            column: Some(1),
        }),
        ..Default::default()
    }
}

fn inputs(caller_post: Option<Json>, callee_pre: Option<Json>) -> LinkerInputs {
    LinkerInputs {
        contracts: vec![caller(caller_post), callee(callee_pre)],
        call_edges: vec![cgo_edge()],
    }
}

/// Build a registry containing one stub solver returning a fixed
/// verdict, plus a Single plan referencing it. Mirrors the
/// `.sugar/config.toml` shape where a named solver seat owns a handle.
fn stub_registry_and_plan(verdict: ObligationVerdict) -> (Registry, SolverPlan) {
    let mut r: HashMap<SolverSeat, SolverHandle> = HashMap::new();
    r.insert(
        SolverSeat::Z3,
        Arc::new(StubSolver::new("fake", verdict)) as SolverHandle,
    );
    (r, SolverPlan::Single(SolverSeat::Z3))
}

// -------------------------------------------------------------------
// Acceptance case 1: identical predicate bodies (no solver needed)
// -------------------------------------------------------------------

#[test]
fn identical_predicates_discharged_without_solver() {
    // post == pre, character-for-character. JCS-canonical equality
    // wins before any solver is consulted; an empty registry suffices.
    let post = ge_x_n(0);
    let pre = post.clone();
    let out = link(inputs(Some(post), Some(pre)));
    assert!(
        out.linker_errors.is_empty(),
        "structurally identical predicates must discharge without error, got: {:?}",
        out.linker_errors
    );
}

// -------------------------------------------------------------------
// Acceptance case 1b: identical-modulo-key-order via JCS
// (no solver work: JCS canonicalizes object key ordering)
// -------------------------------------------------------------------

#[test]
fn jcs_canonical_equality_discharges_without_solver() {
    // Two predicates whose serde_json maps differ only by key
    // insertion order. JCS sorts keys lexicographically (RFC 8785),
    // so canonical bytes match; no solver should be invoked.
    //
    // Build the "same" predicate twice but force one to have a
    // distinct serialized order by reconstructing it manually.
    let post = json!({
        "kind": "atomic",
        "name": ">=",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let pre = json!({
        "args": [
            {"name": "x", "kind": "var"},
            {"sort": {"name": "Int", "kind": "primitive"}, "value": 0, "kind": "const"}
        ],
        "name": ">=",
        "kind": "atomic"
    });
    // Use an EMPTY registry: if the linker needed to invoke the
    // solver this would surface as "implication-undecidable".
    let registry: Registry = HashMap::new();
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let out = link_with_solvers(inputs(Some(post), Some(pre)), &registry, &plan);
    assert!(
        out.linker_errors.is_empty(),
        "JCS-canonical equality must discharge without invoking the solver, got: {:?}",
        out.linker_errors
    );
}

// -------------------------------------------------------------------
// Acceptance case 2: structurally distinct, logically equivalent
// (e.g. `x>=0 AND x<100` vs `x<100 AND x>=0`)
// -------------------------------------------------------------------

#[test]
fn structurally_distinct_logically_equivalent_discharged_via_solver_stub() {
    // Caller post: x >= 0 AND x < 100
    // Callee pre:  x < 100 AND x >= 0
    // These are not JCS-equal (the operand order differs); a stub
    // solver returning Discharged represents what a real solver
    // would do for this implication.
    let post = and_of(ge_x_n(0), lt_x_n(100));
    let pre = and_of(lt_x_n(100), ge_x_n(0));
    let (registry, plan) = stub_registry_and_plan(ObligationVerdict::Discharged);
    let out = link_with_solvers(inputs(Some(post), Some(pre)), &registry, &plan);
    assert!(
        out.linker_errors.is_empty(),
        "stub-discharged implication must produce no linker errors, got: {:?}",
        out.linker_errors
    );
}

// -------------------------------------------------------------------
// Acceptance case 3: logically incompatible
// (caller post: x>=0; callee pre: x>=10  -> not implied)
// -------------------------------------------------------------------

#[test]
fn logically_incompatible_emits_implication_unprovable() {
    // Caller post: x >= 0
    // Callee pre:  x >= 10
    // post does NOT imply pre: counterexample x = 5.
    // Stub solver returns Unsatisfied (= "sat with counterexample"
    // in the verifier's terminology) to represent that result.
    let post = ge_x_n(0);
    let pre = ge_x_n(10);
    let (registry, plan) = stub_registry_and_plan(ObligationVerdict::Unsatisfied);
    let out = link_with_solvers(inputs(Some(post), Some(pre)), &registry, &plan);
    assert_eq!(
        out.linker_errors.len(),
        1,
        "expected exactly one linker error"
    );
    assert_eq!(
        out.linker_errors[0].kind.wire_str(),
        "implication-unprovable",
        "weak-post case must surface implication-unprovable, got {:?}",
        out.linker_errors[0]
    );
    let err = &out.linker_errors[0];
    assert_eq!(err.target_symbol, "rust-kit:callee");
    assert_eq!(err.file.as_deref(), Some("caller.rs"));
    assert_eq!(
        err.call_site_locus.as_ref(),
        Some(&CallSiteLocus {
            file: "caller.rs".into(),
            line: Some(1),
            column: Some(1),
        }),
        "solver failure must preserve the callsite locus for LSP diagnostics"
    );
}

// -------------------------------------------------------------------
// Acceptance case 4: caller post implies callee pre (via solver)
// (caller post: x>=10; callee pre: x>=0  -> implied)
// -------------------------------------------------------------------

#[test]
fn strong_post_implies_weak_pre_discharged_via_solver_stub() {
    // Caller post: x >= 10
    // Callee pre:  x >= 0
    // post DOES imply pre. Stub solver returns Discharged.
    let post = ge_x_n(10);
    let pre = ge_x_n(0);
    let (registry, plan) = stub_registry_and_plan(ObligationVerdict::Discharged);
    let out = link_with_solvers(inputs(Some(post), Some(pre)), &registry, &plan);
    assert!(
        out.linker_errors.is_empty(),
        "stub-discharged implication must produce no linker errors, got: {:?}",
        out.linker_errors
    );
}

// -------------------------------------------------------------------
// Solver-undecidable case: emit implication-undecidable, do NOT
// silently discharge.
// -------------------------------------------------------------------

#[test]
fn solver_undecidable_does_not_silently_discharge() {
    let post = ge_x_n(0);
    let pre = ge_x_n(10);
    let (registry, plan) = stub_registry_and_plan(ObligationVerdict::Undecidable);
    let out = link_with_solvers(inputs(Some(post), Some(pre)), &registry, &plan);
    assert_eq!(out.linker_errors.len(), 1);
    assert_eq!(
        out.linker_errors[0].kind.wire_str(),
        "implication-undecidable"
    );
}

// -------------------------------------------------------------------
// Pure-`link()` fallback: no registry available. Structurally
// distinct predicates must NOT be silently discharged.
// -------------------------------------------------------------------

#[test]
fn pure_link_with_no_registry_emits_undecidable_for_distinct_predicates() {
    let post = ge_x_n(10);
    let pre = ge_x_n(0);
    let out = link(inputs(Some(post), Some(pre)));
    assert_eq!(out.linker_errors.len(), 1, "expected one error");
    assert_eq!(
        out.linker_errors[0].kind.wire_str(),
        "implication-undecidable",
        "pure link() with no solver must surface undecidable, never silent-discharge"
    );
}

// -------------------------------------------------------------------
// Vacuous discharge: callee has no pre-condition.
// -------------------------------------------------------------------

#[test]
fn callee_pre_absent_is_vacuously_discharged() {
    let out = link(inputs(Some(ge_x_n(0)), None));
    assert!(
        out.linker_errors.is_empty(),
        "callee with no pre-condition is vacuously discharged"
    );
}

// -------------------------------------------------------------------
// Caller post absent: legacy "unprovable-obligation" path.
// Pinned by the polyglot smoke fixtures (PR #128 baseline) and the
// linker's own `test_link_bundle_cid_byte_identity_gate`.
// -------------------------------------------------------------------

#[test]
fn caller_post_absent_emits_unprovable_obligation() {
    let out = link(inputs(None, Some(ge_x_n(0))));
    assert_eq!(out.linker_errors.len(), 1);
    assert_eq!(
        out.linker_errors[0].kind.wire_str(),
        "unprovable-obligation"
    );
}

// -------------------------------------------------------------------
// Registry-from-config plumbing: SolversConfig::from_toml +
// registry::build is the architect-mandated "use whatever
// Cargo.toml says" pathway. Verify the linker can be wired through
// it end-to-end with a stub backend.
// -------------------------------------------------------------------

#[test]
fn config_driven_registry_drives_discharge() {
    let toml = r#"
[solvers]
default = "z3"
[solvers.z3]
binary = "stub:unsat"
"#;
    let cfg = SolversConfig::from_toml(toml).expect("parse");
    let plan = SolverPlan::from_config(&cfg);
    let registry: Registry = registry::build(&cfg);
    // Non-trivial implication, but stub returns unsat -> Discharged.
    let post = ge_x_n(10);
    let pre = ge_x_n(0);
    let out = link_with_solvers(inputs(Some(post), Some(pre)), &registry, &plan);
    assert!(
        out.linker_errors.is_empty(),
        "config-driven stub registry must discharge, got: {:?}",
        out.linker_errors
    );
}

// -------------------------------------------------------------------
// Real-solver integration smoke. Ignored by default; run via
//   SUGAR_REAL_SOLVER=1 cargo test -p sugar-linker -- --ignored
// when z3 is on PATH.
// -------------------------------------------------------------------

#[test]
#[ignore = "requires z3 on PATH; run with --ignored when available"]
fn real_solver_z3_strong_post_implies_weak_pre() {
    let toml = r#"
[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 5
"#;
    let cfg = SolversConfig::from_toml(toml).expect("parse");
    let plan = SolverPlan::from_config(&cfg);
    let registry: Registry = registry::build(&cfg);
    let post = ge_x_n(10);
    let pre = ge_x_n(0);
    let out = link_with_solvers(inputs(Some(post), Some(pre)), &registry, &plan);
    assert!(
        out.linker_errors.is_empty(),
        "real z3 must discharge x>=10 implies x>=0, got: {:?}",
        out.linker_errors
    );
}
