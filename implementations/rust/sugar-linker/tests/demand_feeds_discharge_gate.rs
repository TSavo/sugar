// SPDX-License-Identifier: MIT OR Apache-2.0
//
// GATE for the implication-demand -> per-edge discharge seam.
// See docs/analysis/implication-linker-seam-2026-07-15.md (SEAM 1).
//
// The seam is CLOSED: `demand_implication` takes registry+plan and both
// public paths project the same private per-edge worker (`derive_edge`),
// so the demanded answer IS the discharged verdict. These tests pin:
//   * demand verdict == bundle discharge verdict for the same edge;
//   * exact LinkerErrorKind + reason survive into the demand row for
//     undecidable / timeout / refused obligations;
//   * report obligation bytes == bridge evidenceTerm bytes (and their
//     CIDs, computed in-test);
//   * two-edge bundles retain batch-owned, non-singleton set-CID
//     semantics while running the shared worker once per edge.

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_linker::solver_api::{
    ObligationVerdict, SolverHandle, SolverPlan, SolverSeat, StubSolver,
};
use sugar_linker::{
    demand_implication, link_with_solvers, CallSiteLocus, ImplicationDemand,
    ImplicationDemandStatus, ImplicationTargetCandidate, ImportSignature, LinkerCallEdge,
    LinkerContract, LinkerErrorKind, LinkerInputs, Registry, Signature,
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

fn stub_registry_and_plan_with(verdict: ObligationVerdict) -> (Registry, SolverPlan) {
    let mut r: HashMap<SolverSeat, SolverHandle> = HashMap::new();
    r.insert(
        SolverSeat::Z3,
        Arc::new(StubSolver::new("fake", verdict)) as SolverHandle,
    );
    (r, SolverPlan::Single(SolverSeat::Z3))
}

fn bundle_for_edges(
    contracts: Vec<LinkerContract>,
    edges: Vec<LinkerCallEdge>,
    registry: &Registry,
    plan: &SolverPlan,
) -> sugar_linker::LinkerOutput {
    link_with_solvers(
        LinkerInputs {
            contracts,
            call_edges: edges,
        },
        registry,
        plan,
    )
}

// -------------------------------------------------------------------
// THE GATE: demand's answer equals the real discharge verdict.
// -------------------------------------------------------------------

#[test]
fn gate_demand_answer_must_equal_real_discharge_verdict() {
    // The real per-edge discharge path succeeds for this edge.
    assert!(
        real_discharge_succeeds(),
        "fixture invariant: link_with_solvers must discharge the \
         structurally-distinct-but-solver-equivalent implication"
    );

    // The demanded answer for the SAME edge, through the SAME registry+plan,
    // must agree.
    let (registry, plan) = stub_registry_and_plan();
    let answer = demand_implication(demand(), &registry, &plan);
    assert_eq!(
        answer.status,
        ImplicationDemandStatus::Discharged,
        "demand_implication answered {:?} for an edge the real discharge path \
         (link_with_solvers) discharges; both must project the same per-edge \
         worker. reason: {}",
        answer.status,
        answer.reason
    );
    assert!(answer.error_kind.is_none());
}

// -------------------------------------------------------------------
// Verdict floor: exact LinkerErrorKind + reason survive into the row.
// -------------------------------------------------------------------

#[test]
fn demand_row_preserves_exact_error_kind_and_reason_from_discharge() {
    for (verdict, expected_kind) in [
        (
            ObligationVerdict::Undecidable,
            LinkerErrorKind::ImplicationUndecidable,
        ),
        (
            ObligationVerdict::SolverTimeout,
            LinkerErrorKind::ImplicationSolverTimeout,
        ),
        (
            ObligationVerdict::Refused,
            LinkerErrorKind::ImplicationRefused,
        ),
        (
            ObligationVerdict::Unsatisfied,
            LinkerErrorKind::ImplicationUnprovable,
        ),
    ] {
        let (registry, plan) = stub_registry_and_plan_with(verdict);

        // Aggregate projection: the bundle's linker error for this edge.
        let bundle = bundle_for_edges(
            vec![source_contract(), target_contract()],
            vec![edge()],
            &registry,
            &plan,
        );
        let bundle_error = bundle
            .linker_errors
            .first()
            .expect("bundle must carry the discharge failure");
        assert_eq!(bundle_error.kind, expected_kind);

        // Report projection: the demand row for the SAME edge.
        let answer = demand_implication(demand(), &registry, &plan);
        assert_eq!(
            answer.status,
            ImplicationDemandStatus::Failed,
            "obligation failure must be `failed`, never a collapsed status"
        );
        assert_eq!(
            answer.error_kind,
            Some(expected_kind),
            "the demand row must retain the exact LinkerErrorKind"
        );
        assert_eq!(
            answer.reason, bundle_error.reason,
            "the demand reason must be the discharge path's reason verbatim"
        );

        // Wire projection: `errorKind` serializes to the exact kebab string.
        let row = serde_json::to_value(&answer).expect("answer serializes");
        assert_eq!(
            row["errorKind"].as_str(),
            Some(expected_kind.wire_str()),
            "flat row must carry the kebab errorKind"
        );
        assert_eq!(row["status"].as_str(), Some("failed"));
    }
}

// -------------------------------------------------------------------
// Join floor: zero / ambiguous discovery is typed unjoined; binding
// failures keep their typed errorKind on the unjoined row.
// -------------------------------------------------------------------

#[test]
fn demand_zero_and_ambiguous_candidates_are_typed_unjoined() {
    let (registry, plan) = stub_registry_and_plan();

    let none = demand_implication(
        ImplicationDemand {
            source_contract: source_contract(),
            target_candidates: vec![],
            call_edge: edge(),
        },
        &registry,
        &plan,
    );
    assert_eq!(none.status, ImplicationDemandStatus::Unjoined);
    assert!(none.error_kind.is_none());
    assert!(
        none.reason.contains("no target candidate"),
        "{}",
        none.reason
    );

    let ambiguous = demand_implication(
        ImplicationDemand {
            source_contract: source_contract(),
            target_candidates: vec![
                ImplicationTargetCandidate {
                    bridge_source_symbol: "call:callee".into(),
                    contract: target_contract(),
                },
                ImplicationTargetCandidate {
                    bridge_source_symbol: "call:callee".into(),
                    contract: LinkerContract {
                        name: "other.callee".into(),
                        kit: "python".into(),
                        contract_cid: "blake3-512:other".into(),
                        pre_json: Some(to_formula(callee_pre())),
                        ..Default::default()
                    },
                },
            ],
            call_edge: edge(),
        },
        &registry,
        &plan,
    );
    assert_eq!(ambiguous.status, ImplicationDemandStatus::Unjoined);
    assert!(ambiguous.error_kind.is_none());
    assert!(
        ambiguous.reason.contains("ambiguous target candidates"),
        "{}",
        ambiguous.reason
    );
}

#[test]
fn demand_binding_failure_is_unjoined_with_typed_error_kind() {
    // POLICY (pinned): a failure from the authoritative bind() constructor —
    // unresolved-symbol / signature-mismatch — classifies as `unjoined` WITH
    // the typed errorKind preserved on the row (unjoined-with-typed-errorKind).
    let (registry, plan) = stub_registry_and_plan();
    let mut mismatched_edge = edge();
    mismatched_edge.import_signature = Some(ImportSignature {
        symbol: "call:callee".into(),
        signature: Signature {
            formals: vec!["a".into(), "b".into()],
            ..Default::default()
        },
    });
    let answer = demand_implication(
        ImplicationDemand {
            source_contract: source_contract(),
            target_candidates: vec![ImplicationTargetCandidate {
                bridge_source_symbol: "call:callee".into(),
                contract: target_contract(), // exports no formals
            }],
            call_edge: mismatched_edge,
        },
        &registry,
        &plan,
    );
    assert_eq!(answer.status, ImplicationDemandStatus::Unjoined);
    assert_eq!(
        answer.error_kind,
        Some(LinkerErrorKind::SignatureMismatch),
        "binding failures keep their typed errorKind on the unjoined row"
    );
    assert!(answer.obligation.is_none(), "no bind, no obligation mint");
}

// -------------------------------------------------------------------
// Single-mint floor: report obligation bytes/CID == bridge evidenceTerm
// bytes/CID.
// -------------------------------------------------------------------

#[test]
fn report_obligation_equals_bridge_evidence_term_bytes_and_cid() {
    let (registry, plan) = stub_registry_and_plan();

    let answer = demand_implication(demand(), &registry, &plan);
    let report_obligation = answer.obligation.expect("bound edge mints an obligation");

    let bundle = bundle_for_edges(
        vec![source_contract(), target_contract()],
        vec![edge()],
        &registry,
        &plan,
    );
    let bridges = bundle.bundle.json["bridges"]
        .as_array()
        .expect("bundle bridges");
    assert_eq!(bridges.len(), 1);
    let bridge_evidence = &bridges[0]["metadata"]["derivedRelation"]["evidenceTerm"];

    // Value equality.
    assert_eq!(
        &report_obligation, bridge_evidence,
        "report obligation and bridge evidenceTerm must be projections of the \
         same minted obligation"
    );

    // CID equality, computed in-test (the wire format is not widened).
    let cid_of = |v: &serde_json::Value| {
        sugar_canonicalizer::blake3_512_of(
            serde_json::to_string(v)
                .expect("obligation serializes")
                .as_bytes(),
        )
    };
    assert_eq!(cid_of(&report_obligation), cid_of(bridge_evidence));
}

// -------------------------------------------------------------------
// Multi-edge floor: bundle aggregation runs the shared worker per edge
// while set CIDs stay batch-owned (non-singleton semantics).
// -------------------------------------------------------------------

#[test]
fn two_edge_bundle_keeps_batch_owned_set_cids_and_per_edge_verdicts() {
    let (registry, plan) = stub_registry_and_plan();

    let second_target = LinkerContract {
        name: "module.callee2".into(),
        kit: "python".into(),
        contract_cid: "blake3-512:callee2".into(),
        pre_json: Some(to_formula(callee_pre())),
        ..Default::default()
    };
    let mut second_edge = edge();
    second_edge.target_contract_cid = Some("blake3-512:callee2".into());
    second_edge.target_symbol = "call:callee2".into();
    second_edge.call_site_locus = Some(CallSiteLocus {
        file: "fixture.py".into(),
        line: Some(9),
        column: Some(2),
    });

    let contracts = vec![source_contract(), target_contract(), second_target.clone()];
    let edges = vec![edge(), second_edge.clone()];

    let two = bundle_for_edges(contracts.clone(), edges.clone(), &registry, &plan);
    assert!(two.linker_errors.is_empty(), "{:?}", two.linker_errors);
    assert_eq!(two.bundle.json["bridges"].as_array().map(Vec::len), Some(2));

    // Batch-owned set CIDs: the two-edge bundle's set CIDs are NOT any
    // singleton's — they hash the whole sorted batch.
    let single_a = bundle_for_edges(
        vec![source_contract(), target_contract()],
        vec![edge()],
        &registry,
        &plan,
    );
    let single_b = bundle_for_edges(
        vec![source_contract(), second_target],
        vec![second_edge],
        &registry,
        &plan,
    );
    for singleton in [&single_a, &single_b] {
        assert_ne!(
            two.bundle.contract_set_cid,
            singleton.bundle.contract_set_cid
        );
        assert_ne!(
            two.bundle.call_edge_set_cid,
            singleton.bundle.call_edge_set_cid
        );
        assert_ne!(two.bundle.bridge_set_cid, singleton.bundle.bridge_set_cid);
        assert_ne!(two.bundle.link_bundle_cid, singleton.bundle.link_bundle_cid);
    }

    // Deterministic sorting: reversed input order yields byte-identical CIDs.
    let reversed = bundle_for_edges(
        contracts.into_iter().rev().collect(),
        edges.into_iter().rev().collect(),
        &registry,
        &plan,
    );
    assert_eq!(two.bundle.link_bundle_cid, reversed.bundle.link_bundle_cid);
    assert_eq!(two.bundle.bridge_set_cid, reversed.bundle.bridge_set_cid);

    // Per-edge verdict parity: each edge's demand row agrees with the bundle.
    for (target, symbol, cid) in [
        (target_contract(), "call:callee", CALLEE_CID),
        (
            LinkerContract {
                name: "module.callee2".into(),
                kit: "python".into(),
                contract_cid: "blake3-512:callee2".into(),
                pre_json: Some(to_formula(callee_pre())),
                ..Default::default()
            },
            "call:callee2",
            "blake3-512:callee2",
        ),
    ] {
        let mut demand_edge = edge();
        demand_edge.target_contract_cid = Some(cid.into());
        demand_edge.target_symbol = symbol.into();
        let answer = demand_implication(
            ImplicationDemand {
                source_contract: source_contract(),
                target_candidates: vec![ImplicationTargetCandidate {
                    bridge_source_symbol: symbol.into(),
                    contract: target,
                }],
                call_edge: demand_edge,
            },
            &registry,
            &plan,
        );
        assert_eq!(answer.status, ImplicationDemandStatus::Discharged);
    }
}
