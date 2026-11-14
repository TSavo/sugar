use std::collections::BTreeSet;

use serde_json::json;
use sugar_ir_types::{IrFormula, IrTerm, Sort};
use sugar_linker::caller_parameter::{
    discharge_parameter_candidate, ClosedCallerUniverseV1, ContractConditionalConstructionV1,
    FormalParameterCoordinateV1, FormalParameterDeclarationV1, ParameterContractDemandV1,
    ParameterContractResolutionV1, ParameterKindV1, ParameterOwnedContractV1,
    ParameterResolutionGapV1, ResolutionBasisV1, SourceFragmentCoordinateV1,
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

    Fixture {
        contract,
        candidate,
    }
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
        },
    )
    .expect("the callee's own declared formal contract is authoritative");
    assert_eq!(resolved.candidate_cid, f.candidate.candidate_cid);
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
        },
    )
    .unwrap_err();
    assert_eq!(gap, ParameterResolutionGapV1::OpenCallerUniverse);
}

/// No call is recorded as a caller-side edge (PR B on #7766: a Python call's
/// only record is its `undecided` member), so even a closed universe has no
/// authenticated caller and a non-declared demand stays loud.
#[test]
fn entry_point_without_authenticated_callers_stays_loud() {
    let f = fixture();
    let gap = discharge_parameter_candidate(
        &f.candidate,
        &f.contract,
        &ClosedCallerUniverseV1 {
            closed: true,
            has_external_callers: false,
        },
    )
    .unwrap_err();
    assert_eq!(gap, ParameterResolutionGapV1::NoIncomingCaller);
}

#[test]
fn declared_demand_resolution_carries_no_caller_universe() {
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
        },
    )
    .unwrap();
    assert_eq!(resolved.basis, ResolutionBasisV1::DeclaredDemand);
    assert_eq!(resolved.caller_universe_cid, None);
    assert_eq!(resolved.contract_cid, f.contract.contract_cid);
    resolved.validate().unwrap();
}

#[test]
fn resolution_round_trips_and_stale_cid_is_rejected() {
    let mut f = fixture();
    f.contract
        .declared_demand_cids
        .insert(f.candidate.demand.demand_cid.clone());
    f.contract.semantic_decl["declaredDemandCids"] =
        serde_json::to_value(&f.contract.declared_demand_cids).unwrap();
    f.contract.contract_cid = canonical_json_cid(&f.contract.semantic_decl);
    let universe = ClosedCallerUniverseV1 {
        closed: false,
        has_external_callers: true,
    };
    let resolved = discharge_parameter_candidate(&f.candidate, &f.contract, &universe).unwrap();
    let wire = serde_json::to_value(&resolved).unwrap();
    let round_trip: ParameterContractResolutionV1 = serde_json::from_value(wire).unwrap();
    assert_eq!(round_trip, resolved);
    round_trip.validate().unwrap();

    // A tampered demand CID (leaving resolution_cid stale) is rejected.
    let mut tampered = resolved.clone();
    tampered.demand_cid = Cid::from("forged-demand");
    assert_eq!(
        tampered.validate().unwrap_err(),
        ParameterResolutionGapV1::StaleResolution
    );

    // A closed-callers basis with no caller universe is basis-inconsistent.
    let mut orphaned = ParameterContractResolutionV1::mint(
        resolved.demand_cid.clone(),
        resolved.candidate_cid.clone(),
        resolved.contract_cid.clone(),
        ResolutionBasisV1::ClosedCallers,
        None,
    );
    // mint recomputes the CID, so the CID is fresh but the basis invariant fails.
    orphaned.caller_universe_cid = None;
    assert_eq!(
        orphaned.validate().unwrap_err(),
        ParameterResolutionGapV1::StaleResolution
    );
}
