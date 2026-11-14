use std::path::PathBuf;
use std::process::{Command, Stdio};
use sugar_claim_envelope::{
    body_contract_cid, mint_contract, mint_contract_with_body_cid, Authoring, MintContractArgs,
    MintedEnvelope,
};
use sugar_ir_types::Sort;
use sugar_linker::{
    final_check_call_contract_ref, resolve_call_contract_demand, AuthenticatedCallContractCatalog,
    AuthenticatedCallExportV1, CallContractDemandV1, CallContractResolutionGapKindV1,
    CallContractResolutionV1, Cid, SourceFragmentCoordinateV1,
};

fn cid(fill: char) -> Cid {
    Cid::from(format!("blake3-512:{}", fill.to_string().repeat(128)))
}

#[test]
fn alias_and_reexport_terminate_at_the_same_contract_and_call_edge() {
    let (mut catalog, _, contract_cid) = catalog();
    catalog.install_exports(vec![
        AuthenticatedCallExportV1 {
            exported_symbol: "python:pandas.fixture.pair".into(),
            target_symbol: "python:pandas.fixture.pair".into(),
            provider_id: "fixture".into(),
        },
        AuthenticatedCallExportV1 {
            exported_symbol: "python:pandas.public.pair".into(),
            target_symbol: "python:pandas.fixture.pair".into(),
            provider_id: "fixture".into(),
        },
    ]);
    let direct = CallContractDemandV1::new(
        use_site(),
        cid('8'),
        "python:pandas.fixture.pair".into(),
        vec![],
        vec![Sort::Primitive {
            name: "Value".into(),
        }],
    );
    let mut alias_site = use_site();
    alias_site.start_line = 3;
    alias_site.end_line = 3;
    let reexport = CallContractDemandV1::new(
        alias_site,
        cid('9'),
        "python:pandas.public.pair".into(),
        vec![],
        vec![Sort::Primitive {
            name: "Value".into(),
        }],
    );
    let CallContractResolutionV1::Resolved(direct_ref) =
        resolve_call_contract_demand(&direct, &catalog)
    else {
        panic!("direct")
    };
    let CallContractResolutionV1::Resolved(reexport_ref) =
        resolve_call_contract_demand(&reexport, &catalog)
    else {
        panic!("reexport")
    };
    assert_ne!(
        direct_ref.import_binding_cid(),
        reexport_ref.import_binding_cid()
    );
    assert_eq!(direct_ref.contract_cid(), &contract_cid);
    assert_eq!(reexport_ref.contract_cid(), &contract_cid);
    assert_eq!(
        direct_ref.to_call_edge(cid('a'), None).target_contract_cid,
        reexport_ref
            .to_call_edge(cid('a'), None)
            .target_contract_cid
    );
}

#[test]
fn ambiguous_export_and_wrong_provider_are_distinct_typed_gaps() {
    let (mut ambiguous, _, _) = catalog();
    ambiguous.install_exports(vec![
        AuthenticatedCallExportV1 {
            exported_symbol: "python:public.pair".into(),
            target_symbol: "python:pandas.fixture.pair".into(),
            provider_id: "fixture".into(),
        },
        AuthenticatedCallExportV1 {
            exported_symbol: "python:public.pair".into(),
            target_symbol: "python:other.pair".into(),
            provider_id: "fixture".into(),
        },
    ]);
    let demand = CallContractDemandV1::new(
        use_site(),
        cid('9'),
        "python:public.pair".into(),
        vec![],
        vec![Sort::Primitive {
            name: "Value".into(),
        }],
    );
    assert!(
        matches!(resolve_call_contract_demand(&demand, &ambiguous), CallContractResolutionV1::Unresolved(gap) if gap.kind == CallContractResolutionGapKindV1::AmbiguousTarget)
    );

    let (mut wrong, _, _) = catalog();
    wrong.install_exports(vec![AuthenticatedCallExportV1 {
        exported_symbol: "python:public.pair".into(),
        target_symbol: "python:pandas.fixture.pair".into(),
        provider_id: "wrong-kit".into(),
    }]);
    assert!(
        matches!(resolve_call_contract_demand(&demand, &wrong), CallContractResolutionV1::Unresolved(gap) if gap.kind == CallContractResolutionGapKindV1::WrongProvider)
    );
}

#[test]
fn authenticated_export_without_contract_is_typed_loud() {
    let (mut missing, _, _) = catalog();
    missing.install_exports(vec![AuthenticatedCallExportV1 {
        exported_symbol: "python:public.missing".into(),
        target_symbol: "python:provider.missing".into(),
        provider_id: "fixture".into(),
    }]);
    let demand = CallContractDemandV1::new(
        use_site(),
        cid('9'),
        "python:public.missing".into(),
        vec![],
        vec![],
    );
    assert!(
        matches!(resolve_call_contract_demand(&demand, &missing), CallContractResolutionV1::Unresolved(gap) if gap.kind == CallContractResolutionGapKindV1::NoAuthenticatedContract)
    );
}

fn json_to_cvalue(j: &serde_json::Value) -> std::sync::Arc<sugar_canonicalizer::Value> {
    use sugar_canonicalizer::Value as CValue;
    match j {
        serde_json::Value::Null => CValue::null(),
        serde_json::Value::Bool(value) => CValue::boolean(*value),
        serde_json::Value::Number(value) => CValue::integer(i128::from(value.as_i64().unwrap())),
        serde_json::Value::String(value) => CValue::string(value.clone()),
        serde_json::Value::Array(items) => {
            CValue::array(items.iter().map(json_to_cvalue).collect())
        }
        serde_json::Value::Object(map) => CValue::object(
            map.iter()
                .map(|(key, value)| (key.clone(), json_to_cvalue(value)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn use_site() -> SourceFragmentCoordinateV1 {
    SourceFragmentCoordinateV1 {
        source_cid: cid('1'),
        start_line: 2,
        start_col: 4,
        end_line: 2,
        end_col: 11,
    }
}

fn contract_args(seed: u8) -> MintContractArgs {
    let post = serde_json::json!({
        "kind":"atomic", "name":"=", "args":[
            {"kind":"var","name":"out"},
            {"kind":"ctor","name":"python:tuple","args":[{"kind":"var","name":"x"}]}
        ]
    });
    MintContractArgs {
        contract_name: "pandas.fixture.pair".into(),
        pre: None,
        post: Some(json_to_cvalue(&post)),
        inv: None,
        evidence_term: None,
        out_binding: "out".into(),
        produced_by: "call-contract-prebind-test".into(),
        produced_at: "2026-07-22T00:00:00.000Z".into(),
        input_cids: vec![],
        authoring: Authoring::KitAuthor {
            author: "fixture".into(),
            note: None,
        },
        signer_seed: [seed; 32],
        formals: vec!["x".into()],
        emit_empty_formals: false,
        formal_sorts: vec![json_to_cvalue(
            &serde_json::json!({"kind":"primitive","name":"Value"}),
        )],
        library: None,
        bridge_source_symbol: Some("python:pandas.fixture.pair".into()),
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: vec![],
        class_shapes: vec![],
        source_warrants: vec![],
        proofir_provenance: None,
    }
}

fn minted(seed: u8) -> MintedEnvelope {
    mint_contract(&contract_args(seed)).unwrap()
}

fn catalog() -> (AuthenticatedCallContractCatalog, Cid, Cid) {
    let minted = minted(7);
    let member_cid = Cid::from(minted.cid.clone());
    let contract_cid = Cid::from(minted.contract_cid.clone());
    let envelope = serde_json::from_slice(&minted.canonical_bytes).unwrap();
    (
        AuthenticatedCallContractCatalog::freeze(vec![(member_cid.clone(), envelope)]).unwrap(),
        member_cid,
        contract_cid,
    )
}

#[test]
fn semantic_contract_identity_is_signer_independent() {
    let first = minted(7);
    let second = minted(8);
    assert_eq!(first.contract_cid, second.contract_cid);
    assert_ne!(first.cid, second.cid);
}

#[test]
fn body_pointer_is_part_of_semantic_contract_identity() {
    let args = contract_args(7);
    let body_a = cid('a');
    let rust_cid = body_contract_cid(&args, body_a.as_str());
    assert_ne!(rust_cid, body_contract_cid(&args, cid('b').as_str()));
    let declaration = serde_json::json!({
        "kind": "contract",
        "name": args.contract_name,
        "outBinding": args.out_binding,
        "bodyCid": body_a,
        "formals": args.formals,
        "formalSorts": [{"kind": "primitive", "name": "Value"}],
    });
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let mut child = Command::new("python3")
        .env("PYTHONPATH", repo.join("implementations/python/sugar-lift-py-tests/src"))
        .arg("-c")
        .arg("import json,sys; from sugar_lift_py_tests.canonicalizer import blake3_512_of,encode_jcs; from sugar_lift_py_tests.context_manager_contract import _json_value; print(blake3_512_of(encode_jcs(_json_value(json.load(sys.stdin))).encode()))")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
    serde_json::to_writer(child.stdin.as_mut().unwrap(), &declaration).unwrap();
    drop(child.stdin.take());
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8(output.stdout).unwrap().trim(), rust_cid);
}

#[test]
fn in_corpus_contract_resolves_to_semantic_contract_cid_not_member_cid() {
    let (catalog, member_cid, contract_cid) = catalog();
    let demand = CallContractDemandV1::new(
        use_site(),
        cid('9'),
        "python:pandas.fixture.pair".into(),
        vec![],
        vec![Sort::Primitive {
            name: "Value".into(),
        }],
    );

    let CallContractResolutionV1::Resolved(reference) =
        resolve_call_contract_demand(&demand, &catalog)
    else {
        panic!("resolved")
    };
    assert_eq!(reference.member_cid(), &member_cid);
    assert_eq!(reference.contract_cid(), &contract_cid);
    assert_ne!(reference.member_cid(), reference.contract_cid());
    assert!(final_check_call_contract_ref(&reference, &catalog).is_ok());
    let edge = reference.to_call_edge(cid('7'), None);
    assert_eq!(edge.target_contract_cid.as_ref(), Some(&contract_cid));
    assert_ne!(edge.target_contract_cid.as_ref(), Some(&member_cid));
}

#[test]
fn nontrivial_precondition_never_projects_an_unconditional_return() {
    let mut args = contract_args(7);
    args.pre = Some(json_to_cvalue(&serde_json::json!({
        "kind":"atomic", "name":"eligible", "args":[{"kind":"var","name":"x"}]
    })));
    let minted = mint_contract_with_body_cid(&args, Some(cid('b').as_str())).unwrap();
    let member_cid = Cid::from(minted.cid.clone());
    let envelope = serde_json::from_slice(&minted.canonical_bytes).unwrap();
    let catalog = AuthenticatedCallContractCatalog::freeze(vec![(member_cid, envelope)]).unwrap();
    let demand = CallContractDemandV1::new(
        use_site(),
        cid('9'),
        "python:pandas.fixture.pair".into(),
        vec![],
        vec![Sort::Primitive {
            name: "Value".into(),
        }],
    );
    let CallContractResolutionV1::Resolved(reference) =
        resolve_call_contract_demand(&demand, &catalog)
    else {
        panic!("resolved")
    };
    assert!(reference.return_term().is_none());
}

#[test]
fn stale_contract_reference_is_rejected_against_changed_semantic_declaration() {
    let (old_catalog, _, old_contract_cid) = catalog();
    let demand = CallContractDemandV1::new(
        use_site(),
        cid('9'),
        "python:pandas.fixture.pair".into(),
        vec![],
        vec![Sort::Primitive {
            name: "Value".into(),
        }],
    );
    let CallContractResolutionV1::Resolved(old_ref) =
        resolve_call_contract_demand(&demand, &old_catalog)
    else {
        panic!("old resolved")
    };

    let args = contract_args(7);
    let changed = mint_contract_with_body_cid(&args, Some(cid('c').as_str())).unwrap();
    assert_ne!(changed.contract_cid, old_contract_cid.as_str());
    let changed_member = Cid::from(changed.cid.clone());
    let changed_envelope = serde_json::from_slice(&changed.canonical_bytes).unwrap();
    let changed_catalog =
        AuthenticatedCallContractCatalog::freeze(vec![(changed_member, changed_envelope)]).unwrap();
    assert_eq!(
        final_check_call_contract_ref(&old_ref, &changed_catalog),
        Err(CallContractResolutionGapKindV1::StaleOrMalformedContractRef)
    );
}

#[test]
fn missing_target_and_signature_mismatch_are_typed_gaps() {
    let (catalog, _, _) = catalog();
    let missing = CallContractDemandV1::new(
        use_site(),
        cid('8'),
        "python:not.in.corpus".into(),
        vec![],
        vec![],
    );
    let mismatch = CallContractDemandV1::new(
        use_site(),
        cid('9'),
        "python:pandas.fixture.pair".into(),
        vec![],
        vec![],
    );

    assert!(matches!(
        resolve_call_contract_demand(&missing, &catalog),
        CallContractResolutionV1::Unresolved(gap)
            if gap.kind == CallContractResolutionGapKindV1::TargetNotInCorpus
    ));
    assert!(matches!(
        resolve_call_contract_demand(&mismatch, &catalog),
        CallContractResolutionV1::Unresolved(gap)
            if gap.kind == CallContractResolutionGapKindV1::ImportSignatureMismatch
    ));
}
