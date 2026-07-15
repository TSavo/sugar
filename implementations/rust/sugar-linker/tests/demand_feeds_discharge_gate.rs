// SPDX-License-Identifier: MIT OR Apache-2.0
//
// RED GATE for the implication-demand -> per-edge discharge seam.
// See docs/analysis/implication-linker-seam-2026-07-15.md (SEAM 1).
//
// `demand_implication` (sugar-linker/src/lib.rs:749) discharges via
// `link()` with an EMPTY solver registry (lib.rs:802), while the real
// discharge path `link_with_solvers` (lib.rs:847) consults the solver
// registry in `discharge_obligation` (lib.rs:1562). Consequence: a
// structurally-distinct-but-solver-equivalent implication is reported
// Unsatisfied by demand while the real linker discharges it cleanly.
//
// Two tests share ONE fixture:
//   * `gate_demand_answer_must_equal_real_discharge_verdict` — the
//     missing gate. RED by design today (#[ignore] so `cargo test`
//     stays green); it asserts demand's answer equals what
//     `link_with_solvers` produces for the same edge. When the seam is
//     closed (demand_implication takes registry+plan; one per-edge
//     entry), remove the #[ignore] and it must pass.
//   * `companion_demand_currently_reports_solverless_unsatisfied` —
//     pins TODAY's solverless behaviour. When the seam is fixed this
//     goes red and must be retired, making Delta R visible in both
//     directions.

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_linker::solver_api::{
    ObligationVerdict, SolverHandle, SolverPlan, SolverSeat, StubSolver,
};
use sugar_linker::{
    demand_implication, link_with_solvers, CallSiteLocus, ImplicationDemand,
    ImplicationDemandStatus, ImplicationTargetCandidate, LinkerCallEdge, LinkerContract,
    LinkerInputs, Registry,
};

// -------------------------------------------------------------------
// Shared fixture: structurally distinct, solver-equivalent contracts.
// Caller post: x >= 0 AND x < 100
// Callee pre:  x < 100 AND x >= 0
// Not JCS-equal (operand order differs), so solverless structural
// matching cannot discharge it; a solver (stubbed Discharged here,
// exactly as discharge_obligation.rs does) can.
// -------------------------------------------------------------------

const CALLER_CID: &str = "blake3-512:caller";
const CALLEE_CID: &str = "blake3-512:callee";

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
    serde_json::from_value(v).expect("valid test formula")
}

fn caller_post() -> Json {
    and_of(ge_x_n(0), lt_x_n(100))
}

fn callee_pre() -> Json {
    and_of(lt_x_n(100), ge_x_n(0))
}

fn source_contract() -> LinkerContract {
    LinkerContract {
        name: "caller".into(),
        kit: "python".into(),
        contract_cid: CALLER_CID.into(),
        post_json: Some(to_formula(caller_post())),
        ..Default::default()
    }
}

fn target_contract() -> LinkerContract {
    LinkerContract {
        name: "module.callee".into(),
        kit: "python".into(),
        contract_cid: CALLEE_CID.into(),
        pre_json: Some(to_formula(callee_pre())),
        ..Default::default()
    }
}

fn edge() -> LinkerCallEdge {
    LinkerCallEdge {
        source_contract_cid: CALLER_CID.into(),
        target_contract_cid: Some(CALLEE_CID.into()),
        target_symbol: "call:callee".into(),
        call_site_locus: Some(CallSiteLocus {
            file: "fixture.py".into(),
            line: Some(4),
            column: Some(8),
        }),
        ..Default::default()
    }
}

fn demand() -> ImplicationDemand {
    ImplicationDemand {
        source_contract: source_contract(),
        target_candidates: vec![ImplicationTargetCandidate {
            bridge_source_symbol: "call:callee".into(),
            contract: target_contract(),
        }],
        call_edge: edge(),
    }
}

fn stub_registry_and_plan() -> (Registry, SolverPlan) {
    let mut r: HashMap<SolverSeat, SolverHandle> = HashMap::new();
    r.insert(
        SolverSeat::Z3,
        Arc::new(StubSolver::new("fake", ObligationVerdict::Discharged)) as SolverHandle,
    );
    (r, SolverPlan::Single(SolverSeat::Z3))
}

fn real_discharge_succeeds() -> bool {
    let (registry, plan) = stub_registry_and_plan();
    let out = link_with_solvers(
        LinkerInputs {
            contracts: vec![source_contract(), target_contract()],
            call_edges: vec![edge()],
        },
        &registry,
        &plan,
    );
    out.linker_errors.is_empty()
}

// -------------------------------------------------------------------
// THE GATE (red by design today).
// -------------------------------------------------------------------

#[test]
#[ignore = "seam: demand_implication discharges solverless via link() with an empty registry \
            (sugar-linker/src/lib.rs:802) while the real discharge path link_with_solvers \
            (lib.rs:847) consults the registry; owner demand_implication (lib.rs:749) must \
            take registry+plan so it is the single per-edge discharge entry; see \
            docs/analysis/implication-linker-seam-2026-07-15.md"]
fn gate_demand_answer_must_equal_real_discharge_verdict() {
    // The real per-edge discharge path succeeds for this edge.
    assert!(
        real_discharge_succeeds(),
        "fixture invariant: link_with_solvers must discharge the \
         structurally-distinct-but-solver-equivalent implication"
    );

    // The demanded answer for the SAME edge must agree.
    let answer = demand_implication(demand());
    assert_eq!(
        answer.status,
        ImplicationDemandStatus::Discharged,
        "SEAM: demand_implication (lib.rs:749) answered {:?} for an edge the real \
         discharge path (link_with_solvers, lib.rs:847) discharges. Demand runs \
         solverless link() with an empty registry (lib.rs:802) instead of taking \
         registry+plan and being the ONE per-edge discharge entry. reason: {}",
        answer.status,
        answer.reason
    );
}

// -------------------------------------------------------------------
// GREEN COMPANION: pins today's solverless truth for the SAME fixture.
// When demand_implication is reconciled to consult the registry, this
// test goes red and must be retired together with the gate's #[ignore].
// -------------------------------------------------------------------

#[test]
fn companion_demand_currently_reports_solverless_unsatisfied() {
    // Invariant: the real discharge path succeeds — that is what makes
    // the demand answer below a seam and not a correct rejection.
    assert!(
        real_discharge_succeeds(),
        "fixture invariant: link_with_solvers must discharge this edge"
    );

    let answer = demand_implication(demand());
    assert_eq!(
        answer.status,
        ImplicationDemandStatus::Unsatisfied,
        "This companion pins demand_implication's CURRENT solverless answer \
         (empty registry at lib.rs:802 -> implication-undecidable -> Unsatisfied). \
         If it now reports {:?}, the seam has been closed: retire this test and \
         un-#[ignore] gate_demand_answer_must_equal_real_discharge_verdict. \
         See docs/analysis/implication-linker-seam-2026-07-15.md. reason: {}",
        answer.status,
        answer.reason
    );
}
