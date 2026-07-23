#[path = "support/call_contract_full_chain.rs"]
mod support;

use sugar_linker::{
    AuthenticatedCallExportV1, CallContractResolutionGapKindV1, ResolvedCallContractRefsV1,
};

const SOURCE: &str = "from pandas.public import pair\nresult = pair(value)\n";

#[test]
fn stale_contract_cid_is_loud_across_final_check_and_python_intake() {
    let repo = support::repo();
    let demand = support::enrolled_demand(&repo, SOURCE);
    let mut original_catalog = support::catalog(&[7]);
    original_catalog.install_exports(vec![AuthenticatedCallExportV1 {
        exported_symbol: "python:pandas.public.pair".into(),
        target_symbol: "python:pandas.fixture.pair".into(),
        provider_id: "fixture".into(),
    }]);
    let table = ResolvedCallContractRefsV1::new(&original_catalog, &[demand]);

    let mut changed_catalog = support::catalog(&[8]);
    changed_catalog.install_exports(vec![AuthenticatedCallExportV1 {
        exported_symbol: "python:pandas.public.pair".into(),
        target_symbol: "python:pandas.fixture.pair".into(),
        provider_id: "fixture".into(),
    }]);
    assert_eq!(
        table.final_check(&changed_catalog),
        Err(CallContractResolutionGapKindV1::StaleOrMalformedContractRef)
    );

    let mut stale_wire = table.to_wire_value();
    stale_wire["byUseSite"][0]["resolution"]["reference"]["contractCid"] =
        serde_json::Value::String(support::cid('f').to_string());
    let verdict = support::python_chain_verdict(&repo, SOURCE, &stale_wire);
    assert_eq!(verdict["stage"], "intake");
    assert!(
        verdict["gap"]
            .as_str()
            .unwrap()
            .contains("stale semantic contract CID"),
        "{verdict}"
    );
    assert!(verdict["edge"].is_null());
}

#[test]
fn two_provider_exports_are_ambiguous_through_python_construction() {
    let repo = support::repo();
    let demand = support::enrolled_demand(&repo, SOURCE);
    let mut catalog = support::catalog(&[7]);
    catalog.install_exports(vec![
        AuthenticatedCallExportV1 {
            exported_symbol: "python:pandas.public.pair".into(),
            target_symbol: "python:pandas.fixture.pair".into(),
            provider_id: "provider-a".into(),
        },
        AuthenticatedCallExportV1 {
            exported_symbol: "python:pandas.public.pair".into(),
            target_symbol: "python:pandas.fixture.pair".into(),
            provider_id: "provider-b".into(),
        },
    ]);
    let table = ResolvedCallContractRefsV1::new(&catalog, &[demand]);
    table.final_check(&catalog).unwrap();

    let wire = table.to_wire_value();
    assert_eq!(
        wire["byUseSite"][0]["resolution"]["gap"]["kind"],
        "ambiguous-target"
    );
    let verdict = support::python_chain_verdict(&repo, SOURCE, &wire);
    assert_eq!(verdict["stage"], "construction");
    assert!(verdict["gap"]
        .as_str()
        .unwrap()
        .contains("ambiguous-target"));
    assert!(verdict["edge"].is_null());
}

#[test]
fn wrong_provider_is_loud_through_python_construction() {
    let repo = support::repo();
    let demand = support::enrolled_demand(&repo, SOURCE);
    let mut catalog = support::catalog(&[7]);
    catalog.install_exports(vec![AuthenticatedCallExportV1 {
        exported_symbol: "python:pandas.public.pair".into(),
        target_symbol: "python:pandas.fixture.pair".into(),
        provider_id: "wrong-provider".into(),
    }]);
    let table = ResolvedCallContractRefsV1::new(&catalog, &[demand]);
    table.final_check(&catalog).unwrap();

    let wire = table.to_wire_value();
    assert_eq!(
        wire["byUseSite"][0]["resolution"]["gap"]["kind"],
        "wrong-provider"
    );
    let verdict = support::python_chain_verdict(&repo, SOURCE, &wire);
    assert_eq!(verdict["stage"], "construction");
    assert!(verdict["gap"].as_str().unwrap().contains("wrong-provider"));
    assert!(verdict["edge"].is_null());
}
