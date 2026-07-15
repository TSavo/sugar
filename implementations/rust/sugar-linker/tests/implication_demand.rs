// SPDX-License-Identifier: MIT OR Apache-2.0

use serde_json::json;
use sugar_ir_types::IrFormula;
use sugar_linker::solver_api::{SolverPlan, SolverSeat};
use sugar_linker::{
    demand_implication, CallSiteLocus, ImplicationDemand, ImplicationDemandStatus,
    ImplicationTargetCandidate, LinkerCallEdge, LinkerContract, Registry,
};

/// Demand always names its registry + plan now; these fixtures are
/// JCS-equal (`true ⊃ true`), so structural equality discharges them
/// without consulting any solver seat.
fn registry_and_plan() -> (Registry, SolverPlan) {
    (Registry::new(), SolverPlan::Single(SolverSeat::Z3))
}

fn formula(value: serde_json::Value) -> IrFormula {
    serde_json::from_value(value).expect("valid test formula")
}

fn source_contract() -> LinkerContract {
    LinkerContract {
        name: "caller".into(),
        kit: "python".into(),
        contract_cid: "blake3-512:caller".into(),
        post_json: Some(formula(json!({"kind":"atomic", "name":"true", "args":[]}))),
        ..Default::default()
    }
}

fn target_contract() -> LinkerContract {
    LinkerContract {
        name: "module.callee".into(),
        kit: "python".into(),
        contract_cid: "blake3-512:callee".into(),
        pre_json: Some(formula(json!({"kind":"atomic", "name":"true", "args":[]}))),
        ..Default::default()
    }
}

fn edge(line: usize) -> LinkerCallEdge {
    LinkerCallEdge {
        source_contract_cid: "blake3-512:caller".into(),
        target_symbol: "call:callee".into(),
        call_site_locus: Some(CallSiteLocus {
            file: "fixture.py".into(),
            line: Some(line),
            column: Some(8),
        }),
        ..Default::default()
    }
}

#[test]
fn one_resolvable_call_demand_mints_one_discharged_obligation() {
    let (registry, plan) = registry_and_plan();
    let answer = demand_implication(
        ImplicationDemand {
            source_contract: source_contract(),
            target_candidates: vec![ImplicationTargetCandidate {
                bridge_source_symbol: "call:callee".into(),
                contract: target_contract(),
            }],
            call_edge: edge(4),
        },
        &registry,
        &plan,
    );

    assert_eq!(answer.status, ImplicationDemandStatus::Discharged);
    assert_eq!(answer.target_contract.as_deref(), Some("module.callee"));
    assert_eq!(
        answer
            .obligation
            .as_ref()
            .and_then(|v| v.get("kind"))
            .and_then(|v| v.as_str()),
        Some("implies")
    );
}

#[test]
fn dangling_edge_demand_is_named_unjoined_debt_with_reason() {
    let (registry, plan) = registry_and_plan();
    let answer = demand_implication(
        ImplicationDemand {
            source_contract: source_contract(),
            target_candidates: vec![],
            call_edge: edge(9),
        },
        &registry,
        &plan,
    );

    assert_eq!(answer.status, ImplicationDemandStatus::Unjoined);
    assert_eq!(answer.target_symbol, "call:callee");
    assert!(
        answer.reason.contains("no target candidate"),
        "{}",
        answer.reason
    );
    assert!(answer.obligation.is_none());
}
