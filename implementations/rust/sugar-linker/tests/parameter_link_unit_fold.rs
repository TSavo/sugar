//! Phase-2 fold proof: the Python-emitted encodeBase64 link unit (its own
//! formal declares the python:indexable demand) discharges via the SELF-DECLARED
//! branch -- a DeclaredDemand resolution with no invented caller universe.

use sugar_linker::caller_parameter::{
    fold_parameter_contract_link_units, ParameterContractLinkUnitV1, ResolutionBasisV1,
};

#[test]
fn encodebase64_self_declared_discharges_without_callers() {
    let raw = include_str!("fixtures/link_unit_encodebase64_selfdeclared.json");
    let unit: ParameterContractLinkUnitV1 =
        serde_json::from_str(raw).expect("Python link unit must deserialize");
    unit.validate()
        .expect("link unit must validate byte-identically");

    // #2 grounded report: the ACTUAL emitted link unit carries the exact pending
    // demand CID in declaredDemandCids -- that is precisely why the fold selects
    // ResolutionBasisV1::DeclaredDemand (the prior "empty set" claim was false).
    let demand_cid = &unit.candidates[0].demand.demand_cid;
    assert!(
        unit.parameter_owned_contract
            .declared_demand_cids
            .contains(demand_cid),
        "declaredDemandCids MUST contain the pending demand (non-empty)"
    );

    let sets = fold_parameter_contract_link_units(std::slice::from_ref(&unit))
        .expect("self-declared candidate must discharge");
    assert_eq!(sets.len(), 1);
    let set = &sets[0];
    assert_eq!(
        set.link_unit_cid, unit.link_unit_cid,
        "set binds its link unit"
    );
    assert_eq!(set.resolutions.len(), 1);
    let res = &set.resolutions[0];
    res.validate().expect("resolution must validate");
    assert_eq!(res.basis, ResolutionBasisV1::DeclaredDemand);
    assert!(
        res.caller_universe_cid.is_none(),
        "self-declared invents no caller"
    );
    assert_eq!(res.demand_cid, unit.candidates[0].demand.demand_cid);
    assert_eq!(res.contract_cid, unit.parameter_owned_contract.contract_cid);
}
