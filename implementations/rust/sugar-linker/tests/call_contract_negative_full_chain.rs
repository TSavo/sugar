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

#[test]
fn python_intake_rejects_duplicate_and_misbound_resolution_rows() {
    let repo = support::repo();
    let demand = support::enrolled_demand(&repo, SOURCE);
    let mut catalog = support::catalog(&[7]);
    catalog.install_exports(vec![AuthenticatedCallExportV1 {
        exported_symbol: "python:pandas.public.pair".into(),
        target_symbol: "python:pandas.fixture.pair".into(),
        provider_id: "fixture".into(),
    }]);
    let table = ResolvedCallContractRefsV1::new(&catalog, &[demand]);
    let wire = table.to_wire_value();

    let mut duplicate = wire.clone();
    duplicate["byUseSite"]
        .as_array_mut()
        .unwrap()
        .push(wire["byUseSite"][0].clone());
    let verdict = support::python_chain_verdict(&repo, SOURCE, &duplicate);
    assert_eq!(verdict["stage"], "intake");
    assert!(verdict["gap"]
        .as_str()
        .unwrap()
        .contains("duplicate use-site"));

    let mut wrong_row = wire.clone();
    wrong_row["byUseSite"][0]["useSite"]["startLine"] = serde_json::json!(9);
    wrong_row["enrolledUseSites"][0]["startLine"] = serde_json::json!(9);
    let verdict = support::python_chain_verdict(&repo, SOURCE, &wrong_row);
    assert_eq!(verdict["stage"], "intake");
    assert!(verdict["gap"]
        .as_str()
        .unwrap()
        .contains("row use-site mismatch"));

    let mut wrong_catalog = wire;
    let replacement = if wrong_catalog["catalogCid"] == support::cid('f').to_string() {
        support::cid('e')
    } else {
        support::cid('f')
    };
    wrong_catalog["catalogCid"] = serde_json::json!(replacement.to_string());
    let verdict = support::python_chain_verdict(&repo, SOURCE, &wrong_catalog);
    assert_eq!(verdict["stage"], "intake");
    assert!(
        verdict["gap"]
            .as_str()
            .unwrap()
            .contains("catalog CID mismatch"),
        "{verdict}"
    );
}
