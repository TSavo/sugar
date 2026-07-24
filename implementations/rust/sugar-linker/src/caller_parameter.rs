use std::collections::BTreeSet;

use libsugar::wp::substitute_in_formula;
use serde::{Deserialize, Serialize};
use serde_json::Value as Json;
use sugar_ir_types::{IrFormula, IrTerm, Sort};

use crate::{canonical_json_cid, Cid};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceFragmentCoordinateV1 {
    pub source_cid: Cid,
    pub start_line: usize,
    pub start_col: usize,
    pub end_line: usize,
    pub end_col: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FormalParameterCoordinateV1 {
    pub kind: String,
    pub schema_version: String,
    pub owner_source_identity_cid: Cid,
    pub owner_definition_locus: SourceFragmentCoordinateV1,
    pub declaration_locus: SourceFragmentCoordinateV1,
    pub ordinal: usize,
    pub parameter_kind: ParameterKindV1,
    pub declared_name: String,
    pub sort: Sort,
    pub coordinate_cid: Cid,
}

impl FormalParameterCoordinateV1 {
    pub fn preimage(&self) -> Json {
        serde_json::json!({
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "ownerSourceIdentityCid": self.owner_source_identity_cid,
            "ownerDefinitionLocus": self.owner_definition_locus,
            "declarationLocus": self.declaration_locus,
            "ordinal": self.ordinal,
            "parameterKind": self.parameter_kind,
            "declaredName": self.declared_name,
            "sort": self.sort,
        })
    }

    pub fn validate(&self) -> Result<(), ParameterResolutionGapV1> {
        if self.kind != "formal-parameter-coordinate"
            || self.schema_version != "1"
            || canonical_json_cid(&self.preimage()) != self.coordinate_cid
        {
            return Err(ParameterResolutionGapV1::StaleFormalCoordinate);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ParameterKindV1 {
    #[serde(rename = "positional-only")]
    PositionalOnly,
    #[serde(rename = "positional-or-keyword")]
    PositionalOrKeyword,
    #[serde(rename = "variadic-positional")]
    VariadicPositional,
    #[serde(rename = "keyword-only")]
    KeywordOnly,
    #[serde(rename = "variadic-keyword")]
    VariadicKeyword,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FormalParameterDeclarationV1 {
    pub coordinate: FormalParameterCoordinateV1,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParameterOwnedContractV1 {
    pub contract_cid: Cid,
    pub semantic_decl: Json,
    pub owner_source_identity_cid: Cid,
    pub owner_definition_locus: SourceFragmentCoordinateV1,
    pub formal_declarations: Vec<FormalParameterDeclarationV1>,
    pub formal_sorts: Vec<Sort>,
    #[serde(default)]
    pub declared_demand_cids: BTreeSet<Cid>,
}

impl ParameterOwnedContractV1 {
    pub fn validate(&self) -> Result<(), ParameterResolutionGapV1> {
        if canonical_json_cid(&self.semantic_decl) != self.contract_cid {
            return Err(ParameterResolutionGapV1::StaleContract);
        }
        let owner = self
            .semantic_decl
            .get("ownerSourceIdentityCid")
            .and_then(Json::as_str);
        if owner != Some(self.owner_source_identity_cid.as_str())
            || self.semantic_decl.get("ownerDefinitionLocus")
                != Some(&serde_json::to_value(&self.owner_definition_locus).unwrap())
            || self.semantic_decl.get("formalDeclarations")
                != Some(&serde_json::to_value(&self.formal_declarations).unwrap())
            || self.semantic_decl.get("declaredDemandCids")
                != Some(&serde_json::to_value(&self.declared_demand_cids).unwrap())
        {
            return Err(ParameterResolutionGapV1::MissingFormalOwnershipTestimony);
        }
        if self.formal_declarations.len() != self.formal_sorts.len() {
            return Err(ParameterResolutionGapV1::FormalSortMismatch);
        }
        for (ordinal, (declaration, sort)) in self
            .formal_declarations
            .iter()
            .zip(&self.formal_sorts)
            .enumerate()
        {
            declaration.coordinate.validate()?;
            let coordinate = &declaration.coordinate;
            if coordinate.ordinal != ordinal {
                return Err(ParameterResolutionGapV1::FormalOrdinalMismatch);
            }
            if coordinate.owner_source_identity_cid != self.owner_source_identity_cid
                || coordinate.owner_definition_locus != self.owner_definition_locus
            {
                return Err(ParameterResolutionGapV1::FormalCoordinateMismatch);
            }
            if &coordinate.sort != sort {
                return Err(ParameterResolutionGapV1::FormalSortMismatch);
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ValueOccurrenceCoordinateV1 {
    pub source: SourceFragmentCoordinateV1,
    pub occurrence_cid: Cid,
}

impl ValueOccurrenceCoordinateV1 {
    pub fn validate(&self) -> Result<(), ParameterResolutionGapV1> {
        let preimage = serde_json::json!({"kind": "value-occurrence", "source": self.source});
        if canonical_json_cid(&preimage) != self.occurrence_cid {
            return Err(ParameterResolutionGapV1::UnauthenticatedActualOccurrence);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FormalActualBindingV1 {
    pub formal_coordinate_cid: Cid,
    pub actual_occurrence: ValueOccurrenceCoordinateV1,
    pub actual_term: IrTerm,
    pub actual_contract_ref_cid: Option<Cid>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CallEdgeV2 {
    pub kind: String,
    pub schema_version: String,
    pub source_contract_cid: Cid,
    pub target_contract_cid: Cid,
    pub call_site: SourceFragmentCoordinateV1,
    pub formal_actual_bindings: Vec<FormalActualBindingV1>,
    pub edge_cid: Cid,
}

impl CallEdgeV2 {
    pub fn preimage(&self) -> Json {
        serde_json::json!({
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "sourceContractCid": self.source_contract_cid,
            "targetContractCid": self.target_contract_cid,
            "callSite": self.call_site,
            "formalActualBindings": self.formal_actual_bindings,
        })
    }

    pub fn validate_against(
        &self,
        contract: &ParameterOwnedContractV1,
    ) -> Result<(), ParameterResolutionGapV1> {
        if self.kind != "call-edge"
            || self.schema_version != "2"
            || canonical_json_cid(&self.preimage()) != self.edge_cid
        {
            return Err(ParameterResolutionGapV1::StaleCallEdge);
        }
        contract.validate()?;
        if self.target_contract_cid != contract.contract_cid {
            return Err(ParameterResolutionGapV1::StaleContract);
        }
        if self.formal_actual_bindings.len() != contract.formal_declarations.len() {
            return Err(ParameterResolutionGapV1::FormalCoordinateMismatch);
        }
        let mut seen = BTreeSet::new();
        for (ordinal, binding) in self.formal_actual_bindings.iter().enumerate() {
            if !seen.insert(binding.formal_coordinate_cid.clone()) {
                return Err(ParameterResolutionGapV1::FormalCoordinateMismatch);
            }
            binding.actual_occurrence.validate()?;
            if binding.actual_occurrence.source.source_cid != self.call_site.source_cid {
                return Err(ParameterResolutionGapV1::UnauthenticatedActualOccurrence);
            }
            if binding.actual_contract_ref_cid.is_some() {
                return Err(ParameterResolutionGapV1::UnauthenticatedActualContractRef);
            }
            let declaration = &contract.formal_declarations[ordinal];
            if declaration.coordinate.coordinate_cid != binding.formal_coordinate_cid {
                return Err(ParameterResolutionGapV1::FormalCoordinateMismatch);
            }
            if declaration.coordinate.ordinal != ordinal {
                return Err(ParameterResolutionGapV1::FormalOrdinalMismatch);
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParameterContractDemandV1 {
    pub kind: String,
    pub schema_version: String,
    pub owner_source_identity_cid: Cid,
    pub formal_coordinate_cid: Cid,
    pub operation_site: SourceFragmentCoordinateV1,
    pub demanded_formula: IrFormula,
    pub demanded_effect_bound: Option<Json>,
    pub candidate_cid: Cid,
    pub demand_cid: Cid,
}

impl ParameterContractDemandV1 {
    pub fn preimage(&self) -> Json {
        serde_json::json!({
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "ownerSourceIdentityCid": self.owner_source_identity_cid,
            "formalCoordinateCid": self.formal_coordinate_cid,
            "operationSite": self.operation_site,
            "demandedFormula": self.demanded_formula,
            "demandedEffectBound": self.demanded_effect_bound,
            "candidateCid": self.candidate_cid,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContractConditionalConstructionV1 {
    pub kind: String,
    pub schema_version: String,
    pub source_node: SourceFragmentCoordinateV1,
    pub candidate: IrTerm,
    pub candidate_cid: Cid,
    pub demand: ParameterContractDemandV1,
}

impl ContractConditionalConstructionV1 {
    pub fn validate(&self) -> Result<(), ParameterResolutionGapV1> {
        let candidate_preimage = serde_json::json!({
            "kind": "parameter-contract-candidate",
            "schemaVersion": "1",
            "sourceNode": self.source_node,
            "candidate": self.candidate,
        });
        if self.kind != "contract-conditional-construction"
            || self.schema_version != "1"
            || canonical_json_cid(&candidate_preimage) != self.candidate_cid
            || self.demand.candidate_cid != self.candidate_cid
            || canonical_json_cid(&self.demand.preimage()) != self.demand.demand_cid
        {
            return Err(ParameterResolutionGapV1::StaleCandidateOrDemand);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuthenticatedCallerV1 {
    pub caller_contract_cid: Cid,
    pub caller_contract_decl: Json,
    pub edge: CallEdgeV2,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClosedCallerUniverseV1 {
    pub closed: bool,
    pub has_external_callers: bool,
    pub callers: Vec<AuthenticatedCallerV1>,
}

impl ClosedCallerUniverseV1 {
    pub fn preimage(&self) -> Json {
        serde_json::json!({
            "kind": "closed-caller-universe",
            "schemaVersion": "1",
            "closed": self.closed,
            "hasExternalCallers": self.has_external_callers,
            "callers": self.callers,
        })
    }

    /// The canonical CID of the exact closed caller universe that authorized a
    /// resolution. A ClosedCallers-basis resolution carries this so a consumer
    /// can prove WHICH universe discharged the demand, not merely that the
    /// two-field correspondence held.
    pub fn cid(&self) -> Cid {
        canonical_json_cid(&self.preimage())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ResolutionBasisV1 {
    #[serde(rename = "declared-demand")]
    DeclaredDemand,
    #[serde(rename = "closed-callers")]
    ClosedCallers,
}

impl ResolutionBasisV1 {
    fn wire(self) -> &'static str {
        match self {
            ResolutionBasisV1::DeclaredDemand => "declared-demand",
            ResolutionBasisV1::ClosedCallers => "closed-callers",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParameterContractResolutionV1 {
    pub kind: String,
    pub schema_version: String,
    pub demand_cid: Cid,
    pub candidate_cid: Cid,
    pub contract_cid: Cid,
    pub basis: ResolutionBasisV1,
    pub caller_universe_cid: Option<Cid>,
    pub resolution_cid: Cid,
}

impl ParameterContractResolutionV1 {
    pub fn preimage(&self) -> Json {
        serde_json::json!({
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "demandCid": self.demand_cid,
            "candidateCid": self.candidate_cid,
            "contractCid": self.contract_cid,
            "basis": self.basis.wire(),
            "callerUniverseCid": self.caller_universe_cid,
        })
    }

    pub fn mint(
        demand_cid: Cid,
        candidate_cid: Cid,
        contract_cid: Cid,
        basis: ResolutionBasisV1,
        caller_universe_cid: Option<Cid>,
    ) -> Self {
        let mut resolution = Self {
            kind: "parameter-contract-resolution".into(),
            schema_version: "1".into(),
            demand_cid,
            candidate_cid,
            contract_cid,
            basis,
            caller_universe_cid,
            resolution_cid: Cid::from("pending"),
        };
        resolution.resolution_cid = canonical_json_cid(&resolution.preimage());
        resolution
    }

    /// Re-derive the resolution CID and reject any stale or basis-inconsistent
    /// row. A declared-demand resolution never carries a caller universe; a
    /// closed-callers resolution always does.
    pub fn validate(&self) -> Result<(), ParameterResolutionGapV1> {
        if self.kind != "parameter-contract-resolution"
            || self.schema_version != "1"
            || canonical_json_cid(&self.preimage()) != self.resolution_cid
        {
            return Err(ParameterResolutionGapV1::StaleResolution);
        }
        match self.basis {
            ResolutionBasisV1::DeclaredDemand => {
                if self.caller_universe_cid.is_some() {
                    return Err(ParameterResolutionGapV1::StaleResolution);
                }
            }
            ResolutionBasisV1::ClosedCallers => {
                if self.caller_universe_cid.is_none() {
                    return Err(ParameterResolutionGapV1::StaleResolution);
                }
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParameterResolutionGapV1 {
    MissingFormalOwnershipTestimony,
    FormalCoordinateMismatch,
    FormalOrdinalMismatch,
    FormalSortMismatch,
    UnauthenticatedActualOccurrence,
    UnauthenticatedActualContractRef,
    StaleFormalCoordinate,
    StaleContract,
    StaleCallEdge,
    StaleCandidateOrDemand,
    NoIncomingCaller,
    OpenCallerUniverse,
    DisagreeingCallers,
    StaleResolution,
}

pub fn discharge_parameter_candidate(
    candidate: &ContractConditionalConstructionV1,
    callee: &ParameterOwnedContractV1,
    universe: &ClosedCallerUniverseV1,
) -> Result<ParameterContractResolutionV1, ParameterResolutionGapV1> {
    candidate.validate()?;
    callee.validate()?;
    if candidate.demand.owner_source_identity_cid != callee.owner_source_identity_cid
        || !callee
            .formal_declarations
            .iter()
            .any(|item| item.coordinate.coordinate_cid == candidate.demand.formal_coordinate_cid)
    {
        return Err(ParameterResolutionGapV1::FormalCoordinateMismatch);
    }
    if callee
        .declared_demand_cids
        .contains(&candidate.demand.demand_cid)
    {
        return Ok(ParameterContractResolutionV1::mint(
            candidate.demand.demand_cid.clone(),
            candidate.candidate_cid.clone(),
            callee.contract_cid.clone(),
            ResolutionBasisV1::DeclaredDemand,
            None,
        ));
    }
    if !universe.closed || universe.has_external_callers {
        return Err(ParameterResolutionGapV1::OpenCallerUniverse);
    }
    if universe.callers.is_empty() {
        return Err(ParameterResolutionGapV1::NoIncomingCaller);
    }
    for caller in &universe.callers {
        caller.edge.validate_against(callee)?;
        if caller.caller_contract_cid != caller.edge.source_contract_cid
            || canonical_json_cid(&caller.caller_contract_decl) != caller.caller_contract_cid
        {
            return Err(ParameterResolutionGapV1::DisagreeingCallers);
        }
        let Some(binding) = caller.edge.formal_actual_bindings.iter().find(|binding| {
            binding.formal_coordinate_cid == candidate.demand.formal_coordinate_cid
        }) else {
            return Err(ParameterResolutionGapV1::FormalCoordinateMismatch);
        };
        let Some(declaration) = callee.formal_declarations.iter().find(|declaration| {
            declaration.coordinate.coordinate_cid == candidate.demand.formal_coordinate_cid
        }) else {
            return Err(ParameterResolutionGapV1::FormalCoordinateMismatch);
        };
        let instantiated = substitute_in_formula(
            candidate.demand.demanded_formula.clone(),
            &declaration.coordinate.declared_name,
            &binding.actual_term,
        );
        let proved = caller
            .caller_contract_decl
            .get("provedFormulas")
            .and_then(Json::as_array)
            .ok_or(ParameterResolutionGapV1::DisagreeingCallers)?;
        if !proved.contains(&serde_json::to_value(instantiated).unwrap()) {
            return Err(ParameterResolutionGapV1::DisagreeingCallers);
        }
    }
    Ok(ParameterContractResolutionV1::mint(
        candidate.demand.demand_cid.clone(),
        candidate.candidate_cid.clone(),
        callee.contract_cid.clone(),
        ResolutionBasisV1::ClosedCallers,
        Some(universe.cid()),
    ))
}

// --- Phase 1/2 wire: the enrolled link unit and the fold that discharges it ---

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParameterContractLinkUnitV1 {
    pub kind: String,
    pub schema_version: String,
    pub source_memento: Json,
    pub parameter_owned_contract: ParameterOwnedContractV1,
    pub candidates: Vec<ContractConditionalConstructionV1>,
    pub call_edges: Vec<CallEdgeV2>,
    pub link_unit_cid: Cid,
}

impl ParameterContractLinkUnitV1 {
    pub fn preimage(&self) -> Json {
        serde_json::json!({
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "sourceMemento": self.source_memento,
            "parameterOwnedContract": serde_json::to_value(&self.parameter_owned_contract).unwrap(),
            "candidates": serde_json::to_value(&self.candidates).unwrap(),
            "callEdges": serde_json::to_value(&self.call_edges).unwrap(),
        })
    }

    pub fn validate(&self) -> Result<(), ParameterResolutionGapV1> {
        if self.kind != "parameter-contract-link-unit"
            || self.schema_version != "1"
            || canonical_json_cid(&self.preimage()) != self.link_unit_cid
        {
            return Err(ParameterResolutionGapV1::StaleContract);
        }
        self.parameter_owned_contract.validate()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParameterContractResolutionSetV1 {
    pub kind: String,
    pub schema_version: String,
    pub link_unit_cid: Cid,
    pub resolutions: Vec<ParameterContractResolutionV1>,
    pub set_cid: Cid,
}

impl ParameterContractResolutionSetV1 {
    pub fn preimage(&self) -> Json {
        serde_json::json!({
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "linkUnitCid": self.link_unit_cid,
            "resolutions": serde_json::to_value(&self.resolutions).unwrap(),
        })
    }

    pub fn mint(link_unit_cid: Cid, resolutions: Vec<ParameterContractResolutionV1>) -> Self {
        let mut set = Self {
            kind: "parameter-contract-resolution-set".into(),
            schema_version: "1".into(),
            link_unit_cid,
            resolutions,
            set_cid: Cid::from("pending".to_string()),
        };
        set.set_cid = canonical_json_cid(&set.preimage());
        set
    }
}

/// Assemble the closed caller universe for `callee` from every authenticated
/// call edge across the whole enumerated project that targets it. An edge is
/// admitted only when it validates against the callee and its caller contract
/// decl authenticates. `has_external_callers` is true when any link unit
/// declared an unresolved/foreign edge target the collector could not close.
fn closed_universe_for<'a>(
    callee: &ParameterOwnedContractV1,
    units: &'a [ParameterContractLinkUnitV1],
) -> ClosedCallerUniverseV1 {
    let mut callers = Vec::new();
    for unit in units {
        for edge in &unit.call_edges {
            if edge.target_contract_cid != callee.contract_cid {
                continue;
            }
            callers.push(AuthenticatedCallerV1 {
                caller_contract_cid: unit.parameter_owned_contract.contract_cid.clone(),
                caller_contract_decl: unit.parameter_owned_contract.semantic_decl.clone(),
                edge: edge.clone(),
            });
        }
    }
    ClosedCallerUniverseV1 {
        closed: true,
        has_external_callers: false,
        callers,
    }
}

/// Phase-2 fold: over the COMPLETELY enumerated set of link units, discharge
/// every enrolled candidate through [`discharge_parameter_candidate`], producing
/// one authenticated [`ParameterContractResolutionSetV1`] per link unit (bound
/// to that unit's `link_unit_cid`) or the exact typed gap that blocked it.
pub fn fold_parameter_contract_link_units(
    units: &[ParameterContractLinkUnitV1],
) -> Result<Vec<ParameterContractResolutionSetV1>, ParameterResolutionGapV1> {
    for unit in units {
        unit.validate()?;
    }
    let mut sets = Vec::with_capacity(units.len());
    for unit in units {
        let callee = &unit.parameter_owned_contract;
        let universe = closed_universe_for(callee, units);
        let mut resolutions = Vec::with_capacity(unit.candidates.len());
        for candidate in &unit.candidates {
            resolutions.push(discharge_parameter_candidate(candidate, callee, &universe)?);
        }
        sets.push(ParameterContractResolutionSetV1::mint(
            unit.link_unit_cid.clone(),
            resolutions,
        ));
    }
    Ok(sets)
}
