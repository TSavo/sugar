use std::collections::BTreeSet;

use serde_json::json;
use sugar_ir_types::{IrFormula, IrTerm, Sort};
use sugar_linker::caller_parameter::{
    discharge_parameter_candidate, AuthenticatedCallerV1, CallEdgeV2, ClosedCallerUniverseV1,
    ContractConditionalConstructionV1, FormalActualBindingV1, FormalParameterCoordinateV1,
    FormalParameterDeclarationV1, ParameterContractDemandV1, ParameterKindV1,
    ParameterOwnedContractV1, ParameterResolutionGapV1, SourceFragmentCoordinateV1,
    ValueOccurrenceCoordinateV1,
};
use sugar_linker::{canonical_json_cid, Cid};

fn value_sort() -> Sort {
    Sort::Primitive {
        name: "Value".into(),
    }
}

fn locus(source_cid: &Cid, line: usize) -> SourceFragmentCoordinateV1 {
    SourceFragmentCoordinateV1 {
        source_cid: source_cid.clone(),
        start_line: line,
        start_col: 0,
        end_line: line,
        end_col: 1,
    }
}

struct Fixture {
    contract: ParameterOwnedContractV1,
    candidate: ContractConditionalConstructionV1,
    edge: CallEdgeV2,
    caller_contract_decl: serde_json::Value,
}

fn fixture() -> Fixture {
    let source_cid = canonical_json_cid(&json!({"source": "def consume(xs): return xs[0]"}));
    let owner_locus = locus(&source_cid, 1);
    let declaration_locus = locus(&source_cid, 1);
    let mut coordinate = FormalParameterCoordinateV1 {
        kind: "formal-parameter-coordinate".into(),
        schema_version: "1".into(),
        owner_source_identity_cid: source_cid.clone(),
        owner_definition_locus: owner_locus.clone(),
        declaration_locus,
        ordinal: 0,
        parameter_kind: ParameterKindV1::PositionalOrKeyword,
        declared_name: "xs".into(),
        sort: value_sort(),
        coordinate_cid: Cid::from("pending"),
    };
    coordinate.coordinate_cid = canonical_json_cid(&coordinate.preimage());
    let declarations = vec![FormalParameterDeclarationV1 {
        coordinate: coordinate.clone(),
    }];
    let semantic_decl = json!({
        "ownerSourceIdentityCid": source_cid,
        "ownerDefinitionLocus": owner_locus,
        "formalDeclarations": declarations,
        "declaredDemandCids": [],
    });
    let contract_cid = canonical_json_cid(&semantic_decl);
    let contract = ParameterOwnedContractV1 {
        contract_cid: contract_cid.clone(),
        semantic_decl,
        owner_source_identity_cid: source_cid.clone(),
        owner_definition_locus: owner_locus.clone(),
        formal_declarations: declarations,
        formal_sorts: vec![value_sort()],
        declared_demand_cids: BTreeSet::new(),
    };

    let source_node = locus(&source_cid, 1);
    let candidate_term = IrTerm::Ctor {
        name: "python:getitem".into(),
        args: vec![
            IrTerm::Var { name: "xs".into() },
            IrTerm::Const {
                value: json!(0),
                sort: Sort::Primitive { name: "Int".into() },
            },
        ],
    };
    let candidate_cid = canonical_json_cid(&json!({
        "kind": "parameter-contract-candidate",
        "schemaVersion": "1",
        "sourceNode": source_node,
        "candidate": candidate_term,
    }));
    let mut demand = ParameterContractDemandV1 {
        kind: "parameter-contract-demand".into(),
        schema_version: "1".into(),
        owner_source_identity_cid: source_cid.clone(),
        formal_coordinate_cid: coordinate.coordinate_cid.clone(),
        operation_site: source_node.clone(),
        demanded_formula: IrFormula::Atomic {
            name: "python:indexable".into(),
            args: vec![IrTerm::Var { name: "xs".into() }],
        },
        demanded_effect_bound: None,
        candidate_cid: candidate_cid.clone(),
        demand_cid: Cid::from("pending"),
    };
    demand.demand_cid = canonical_json_cid(&demand.preimage());
    let candidate = ContractConditionalConstructionV1 {
        kind: "contract-conditional-construction".into(),
        schema_version: "1".into(),
        source_node,
        candidate: candidate_term,
        candidate_cid,
        demand,
    };

    let call_site = locus(&source_cid, 20);
    let actual_source = locus(&source_cid, 20);
    let mut occurrence = ValueOccurrenceCoordinateV1 {
        source: actual_source,
        occurrence_cid: Cid::from("pending"),
    };
    occurrence.occurrence_cid = canonical_json_cid(&json!({
        "kind": "value-occurrence",
        "source": occurrence.source,
    }));
    let binding = FormalActualBindingV1 {
        formal_coordinate_cid: coordinate.coordinate_cid,
        actual_occurrence: occurrence,
        actual_term: IrTerm::Ctor {
            name: "python:list".into(),
            args: vec![],
        },
        actual_contract_ref_cid: None,
    };
    let proved_formula = IrFormula::Atomic {
        name: "python:indexable".into(),
        args: vec![binding.actual_term.clone()],
    };
    let caller_contract_decl = json!({
        "provedFormulas": [proved_formula],
    });
    let caller_contract_cid = canonical_json_cid(&caller_contract_decl);
    let mut edge = CallEdgeV2 {
        kind: "call-edge".into(),
        schema_version: "2".into(),
        source_contract_cid: caller_contract_cid,
        target_contract_cid: contract_cid,
        call_site,
        formal_actual_bindings: vec![binding],
        edge_cid: Cid::from("pending"),
    };
    edge.edge_cid = canonical_json_cid(&edge.preimage());
    Fixture {
        contract,
        candidate,
        edge,
        caller_contract_decl,
    }
}

#[test]
fn one_authenticated_caller_discharge_preserves_candidate_identity() {
    let f = fixture();
    let candidate_wire = serde_json::to_value(&f.candidate).unwrap();
    let candidate_round_trip: ContractConditionalConstructionV1 =
        serde_json::from_value(candidate_wire).unwrap();
    assert_eq!(candidate_round_trip, f.candidate);
    candidate_round_trip.validate().unwrap();
    let universe = ClosedCallerUniverseV1 {
        closed: true,
        has_external_callers: false,
        callers: vec![AuthenticatedCallerV1 {
            caller_contract_cid: f.edge.source_contract_cid.clone(),
            caller_contract_decl: f.caller_contract_decl,
            edge: f.edge,
        }],
    };
    let resolved = discharge_parameter_candidate(&f.candidate, &f.contract, &universe)
        .expect("the authenticated caller proves the exact demand");
    assert_eq!(resolved.candidate_cid, f.candidate.candidate_cid);
    assert_eq!(resolved.demand_cid, f.candidate.demand.demand_cid);
}

#[test]
fn declared_formal_contract_discharges_without_caller_specialization() {
    let mut f = fixture();
    f.contract
        .declared_demand_cids
        .insert(f.candidate.demand.demand_cid.clone());
    f.contract.semantic_decl["declaredDemandCids"] =
        serde_json::to_value(&f.contract.declared_demand_cids).unwrap();
    f.contract.contract_cid = canonical_json_cid(&f.contract.semantic_decl);
    let resolved = discharge_parameter_candidate(
        &f.candidate,
        &f.contract,
        &ClosedCallerUniverseV1 {
            closed: false,
            has_external_callers: true,
            callers: vec![],
        },
    )
    .expect("the callee's own declared formal contract is authoritative");
    assert_eq!(resolved.candidate_cid, f.candidate.candidate_cid);
}

#[test]
fn disagreeing_callers_do_not_globally_specialize_the_callee() {
    let f = fixture();
    let proving = AuthenticatedCallerV1 {
        caller_contract_cid: f.edge.source_contract_cid.clone(),
        caller_contract_decl: f.caller_contract_decl,
        edge: f.edge.clone(),
    };
    let disagreeing_decl = json!({"provedFormulas": []});
    let disagreeing_cid = canonical_json_cid(&disagreeing_decl);
    let mut disagreeing_edge = proving.edge.clone();
    disagreeing_edge.source_contract_cid = disagreeing_cid.clone();
    disagreeing_edge.edge_cid = canonical_json_cid(&disagreeing_edge.preimage());
    let disagreeing = AuthenticatedCallerV1 {
        caller_contract_cid: disagreeing_cid,
        caller_contract_decl: disagreeing_decl,
        edge: disagreeing_edge,
    };
    let gap = discharge_parameter_candidate(
        &f.candidate,
        &f.contract,
        &ClosedCallerUniverseV1 {
            closed: true,
            has_external_callers: false,
            callers: vec![proving, disagreeing],
        },
    )
    .unwrap_err();
    assert_eq!(gap, ParameterResolutionGapV1::DisagreeingCallers);
}

#[test]
fn external_caller_universe_stays_loud() {
    let f = fixture();
    let gap = discharge_parameter_candidate(
        &f.candidate,
        &f.contract,
        &ClosedCallerUniverseV1 {
            closed: false,
            has_external_callers: true,
            callers: vec![],
        },
    )
    .unwrap_err();
    assert_eq!(gap, ParameterResolutionGapV1::OpenCallerUniverse);
}

#[test]
fn entry_point_without_authenticated_callers_stays_loud() {
    let f = fixture();
    let gap = discharge_parameter_candidate(
        &f.candidate,
        &f.contract,
        &ClosedCallerUniverseV1 {
            closed: true,
            has_external_callers: false,
            callers: vec![],
        },
    )
    .unwrap_err();
    assert_eq!(gap, ParameterResolutionGapV1::NoIncomingCaller);
}

#[test]
fn stale_formal_identity_is_not_accepted_by_name() {
    let mut f = fixture();
    f.edge.formal_actual_bindings[0].formal_coordinate_cid =
        canonical_json_cid(&json!({"sameSpelling": "xs", "differentOwner": true}));
    f.edge.edge_cid = canonical_json_cid(&f.edge.preimage());
    let gap = f.edge.validate_against(&f.contract).unwrap_err();
    assert_eq!(gap, ParameterResolutionGapV1::FormalCoordinateMismatch);
}

#[test]
fn unverified_actual_contract_reference_stays_loud() {
    let mut f = fixture();
    f.edge.formal_actual_bindings[0].actual_contract_ref_cid =
        Some(canonical_json_cid(&json!({"unverified": true})));
    f.edge.edge_cid = canonical_json_cid(&f.edge.preimage());
    let gap = f.edge.validate_against(&f.contract).unwrap_err();
    assert_eq!(
        gap,
        ParameterResolutionGapV1::UnauthenticatedActualContractRef
    );
}
