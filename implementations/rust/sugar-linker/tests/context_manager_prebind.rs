use serde_json::Value as Json;
use sugar_claim_envelope::{
    mint_context_manager_contract, Authoring, MintContextManagerContractArgs,
};
use sugar_ir_types::Sort;
use sugar_linker::{
    decode_context_manager_edge, final_check_context_manager_edge,
    final_check_context_manager_edges, final_check_context_manager_ref,
    resolve_context_manager_demand, AuthenticatedContextManagerCatalog, Cid,
    ContextManagerContractDemandV1, ContextManagerEdgeV1, ContextManagerResolutionGapKindV1,
    ContextManagerResolutionV1, ResolvedContractRefsV1, SourceFragmentCoordinateV1,
};
use sugar_proof_envelope::{
    ContextManagerSemanticsV1, EnterResultContractV1, ExitContractV1, ExitDispositionV1,
    ImportSignatureV2, ResourceSemanticsV1, TotalCompletionV1,
};

fn cid(fill: char) -> Cid {
    Cid::from(format!("blake3-512:{}", fill.to_string().repeat(128)))
}

fn use_site() -> SourceFragmentCoordinateV1 {
    SourceFragmentCoordinateV1 {
        source_cid: cid('1'),
        start_line: 3,
        start_col: 9,
        end_line: 3,
        end_col: 22,
    }
}

fn minted(symbol: &str, seed_byte: u8) -> (Cid, Json) {
    let m = mint_context_manager_contract(&MintContextManagerContractArgs {
        bridge_source_symbol: symbol.into(),
        import_signature: ImportSignatureV2 { parameters: vec![] },
        semantics: ContextManagerSemanticsV1::ProtocolResource(ResourceSemanticsV1 {
            enter: EnterResultContractV1 {
                completion: TotalCompletionV1,
                sort: Sort::Primitive {
                    name: "Value".into(),
                },
            },
            exit: ExitContractV1 {
                completion: TotalCompletionV1,
                disposition: ExitDispositionV1::NeverSuppresses,
            },
        }),
        source_warrants: vec![],
        produced_by: "fixture".into(),
        produced_at: "2026-07-22T00:00:00.000Z".into(),
        authoring: Authoring::KitAuthor {
            author: "fixture".into(),
            note: None,
        },
        signer_seed: [seed_byte; 32],
    })
    .unwrap();
    (
        Cid::from(m.cid),
        serde_json::from_slice(&m.canonical_bytes).unwrap(),
    )
}

fn demand(symbol: &str) -> ContextManagerContractDemandV1 {
    ContextManagerContractDemandV1::new(
        use_site(),
        symbol.into(),
        ImportSignatureV2 { parameters: vec![] },
    )
}

#[test]
fn truthful_member_prebinds_to_immutable_typed_ref() {
    let member = minted("context-manager:fixture.never_closing", 7);
    let catalog = AuthenticatedContextManagerCatalog::freeze(vec![member.clone()]).unwrap();
    let ContextManagerResolutionV1::Resolved(reference) =
        resolve_context_manager_demand(&demand("context-manager:fixture.never_closing"), &catalog)
    else {
        panic!("resolved")
    };
    assert_eq!(reference.member_cid(), &member.0);
    assert_eq!(reference.catalog_cid(), catalog.catalog_cid());
    assert_eq!(
        match reference.semantics() {
            ContextManagerSemanticsV1::ProtocolResource(resource) => resource.exit.disposition,
            ContextManagerSemanticsV1::EffectBoundary(_) => panic!("resource"),
        },
        ExitDispositionV1::NeverSuppresses
    );
    final_check_context_manager_ref(&reference, &catalog)
        .expect("same frozen catalog remains valid");
}

#[test]
fn zero_and_many_candidates_are_loud_and_many_is_sorted() {
    let empty = AuthenticatedContextManagerCatalog::freeze(vec![]).unwrap();
    let ContextManagerResolutionV1::Unresolved(gap) =
        resolve_context_manager_demand(&demand("context-manager:missing"), &empty)
    else {
        panic!("gap")
    };
    assert_eq!(
        gap.kind,
        ContextManagerResolutionGapKindV1::UnresolvedSymbol
    );

    let a = minted("context-manager:fixture.never_closing", 8);
    let b = minted("context-manager:fixture.never_closing", 9);
    let catalog = AuthenticatedContextManagerCatalog::freeze(vec![b.clone(), a.clone()]).unwrap();
    let ContextManagerResolutionV1::Unresolved(gap) =
        resolve_context_manager_demand(&demand("context-manager:fixture.never_closing"), &catalog)
    else {
        panic!("gap")
    };
    assert_eq!(gap.kind, ContextManagerResolutionGapKindV1::AmbiguousSymbol);
    assert_eq!(gap.candidate_member_cids.len(), 2);
    assert!(gap.candidate_member_cids[0] < gap.candidate_member_cids[1]);
}

#[test]
fn removing_selected_member_makes_final_check_stale_without_relinking() {
    let member = minted("context-manager:fixture.never_closing", 10);
    let catalog = AuthenticatedContextManagerCatalog::freeze(vec![member]).unwrap();
    let ContextManagerResolutionV1::Resolved(reference) =
        resolve_context_manager_demand(&demand("context-manager:fixture.never_closing"), &catalog)
    else {
        panic!("resolved")
    };
    let drifted = AuthenticatedContextManagerCatalog::freeze(vec![]).unwrap();
    assert_eq!(
        final_check_context_manager_ref(&reference, &drifted).unwrap_err(),
        "stale-resolution"
    );
}

#[test]
fn rust_owned_table_decodes_to_frozen_typed_python_refs() {
    let member = minted("context-manager:fixture.never_closing", 11);
    let catalog = AuthenticatedContextManagerCatalog::freeze(vec![member]).unwrap();
    let table =
        ResolvedContractRefsV1::new(&catalog, &[demand("context-manager:fixture.never_closing")]);
    assert_eq!(table.catalog_cid(), catalog.catalog_cid());
    assert!(matches!(
        table.get(&use_site()),
        Some(ContextManagerResolutionV1::Resolved(_))
    ));

    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let mut child = Command::new("python3")
        .env(
            "PYTHONPATH",
            repo.join("implementations/python/sugar-lift-py-tests/src"),
        )
        .arg("-c")
        .arg("import json,sys; from sugar_lift_py_tests.context_manager_resolution import decode_resolved_contract_refs, ContextManagerContractRefV1; t=decode_resolved_contract_refs(json.load(sys.stdin)); v=t.require(next(iter(t.by_use_site))); assert isinstance(v, ContextManagerContractRefV1); assert v.member_cid and v.semantics.exit.disposition.kind == 'never-suppresses'; print(t.table_cid)")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    serde_json::to_writer(child.stdin.as_mut().unwrap(), &table.to_wire_value()).unwrap();
    child.stdin.as_mut().unwrap().flush().unwrap();
    drop(child.stdin.take());
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        String::from_utf8(output.stdout).unwrap().trim(),
        table.table_cid().as_str()
    );
}

#[test]
fn runtime_selected_and_mutated_signed_member_never_construct_a_ref() {
    let empty = AuthenticatedContextManagerCatalog::freeze(vec![]).unwrap();
    let runtime = ContextManagerContractDemandV1::runtime_selected(
        use_site(),
        ImportSignatureV2 { parameters: vec![] },
    );
    let ContextManagerResolutionV1::Unresolved(gap) =
        resolve_context_manager_demand(&runtime, &empty)
    else {
        panic!("runtime-selected gap")
    };
    assert_eq!(gap.kind, ContextManagerResolutionGapKindV1::RuntimeSelected);
    assert!(gap.target_symbol.is_none());

    let (cid, mut envelope) = minted("context-manager:fixture.never_closing", 12);
    envelope["header"]["payload"]["exit"]["disposition"]["kind"] =
        Json::String("unknown-disposition".into());
    let error = AuthenticatedContextManagerCatalog::freeze(vec![(cid, envelope)]).unwrap_err();
    assert!(
        error.contains("attestation") || error.contains("signature"),
        "{error}"
    );
}

#[test]
fn final_edge_is_pinned_to_the_exact_resolution_and_catalog() {
    let member = minted("context-manager:fixture.never_closing", 13);
    let catalog = AuthenticatedContextManagerCatalog::freeze(vec![member]).unwrap();
    let ContextManagerResolutionV1::Resolved(reference) =
        resolve_context_manager_demand(&demand("context-manager:fixture.never_closing"), &catalog)
    else {
        panic!("resolved")
    };
    let edge = ContextManagerEdgeV1::from_resolved(&reference);
    final_check_context_manager_edge(&edge, &reference, &catalog).expect("exact pinned edge");
    let drifted = AuthenticatedContextManagerCatalog::freeze(vec![]).unwrap();
    assert_eq!(
        final_check_context_manager_edge(&edge, &reference, &drifted).unwrap_err(),
        "stale-resolution"
    );
}

#[test]
fn exact_symbol_with_different_signature_stays_a_typed_gap() {
    let member = minted("context-manager:fixture.never_closing", 14);
    let catalog = AuthenticatedContextManagerCatalog::freeze(vec![member]).unwrap();
    let mismatched = ContextManagerContractDemandV1::new(
        use_site(),
        "context-manager:fixture.never_closing".into(),
        ImportSignatureV2 {
            parameters: vec![sugar_proof_envelope::CallParameterV1 {
                name: "value".into(),
                sort: Sort::Primitive {
                    name: "Value".into(),
                },
                passing: sugar_proof_envelope::ParameterPassingV1::PositionalOrKeyword,
                required: true,
                default: sugar_proof_envelope::ParameterDefaultV1::NoDefault,
            }],
        },
    );
    let ContextManagerResolutionV1::Unresolved(gap) =
        resolve_context_manager_demand(&mismatched, &catalog)
    else {
        panic!("signature-mismatch gap")
    };
    assert_eq!(
        gap.kind,
        ContextManagerResolutionGapKindV1::SignatureMismatch
    );
}

#[test]
fn strict_context_manager_edge_round_trips_and_final_checks_every_pin() {
    let member = minted("context-manager:fixture.never_closing", 15);
    let catalog = AuthenticatedContextManagerCatalog::freeze(vec![member]).unwrap();
    let table =
        ResolvedContractRefsV1::new(&catalog, &[demand("context-manager:fixture.never_closing")]);
    let Some(ContextManagerResolutionV1::Resolved(reference)) = table.get(&use_site()) else {
        panic!("resolved")
    };
    let edge = ContextManagerEdgeV1::from_resolved(reference);
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let mut child = Command::new("python3")
        .env("PYTHONPATH", repo.join("implementations/python/sugar-lift-py-tests/src"))
        .arg("-c")
        .arg("import json,sys; from sugar_lift_py_tests.context_manager_resolution import decode_resolved_contract_refs, ContextManagerContractRefV1; from sugar_lift_py_tests.kit_rpc.context_manager_edge_dto import ContextManagerEdgeDtoV1; t=decode_resolved_contract_refs(json.load(sys.stdin)); r=t.require(next(iter(t.by_use_site))); assert isinstance(r, ContextManagerContractRefV1); json.dump(ContextManagerEdgeDtoV1.from_resolved(r, r.use_site).to_rpc(), sys.stdout)")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().unwrap();
    serde_json::to_writer(child.stdin.as_mut().unwrap(), &table.to_wire_value()).unwrap();
    child.stdin.as_mut().unwrap().flush().unwrap();
    drop(child.stdin.take());
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let wire: Json = serde_json::from_slice(&output.stdout).unwrap();
    let decoded = decode_context_manager_edge(&wire).expect("strict edge decode");
    assert_eq!(decoded, edge);
    final_check_context_manager_edges(&[decoded], &table, &catalog)
        .expect("same frozen table and catalog");
}

#[test]
fn malformed_cross_schema_and_unresolved_context_manager_edges_are_loud() {
    let member = minted("context-manager:fixture.never_closing", 16);
    let catalog = AuthenticatedContextManagerCatalog::freeze(vec![member]).unwrap();
    let table =
        ResolvedContractRefsV1::new(&catalog, &[demand("context-manager:fixture.never_closing")]);
    let Some(ContextManagerResolutionV1::Resolved(reference)) = table.get(&use_site()) else {
        panic!("resolved")
    };
    let wire = ContextManagerEdgeV1::from_resolved(reference).to_wire_value();
    for field in ["edgeCid", "targetContractCid", "payloadCid"] {
        let mut changed = wire.clone();
        changed[field] = Json::String(cid('f').to_string());
        assert!(
            decode_context_manager_edge(&changed).is_err(),
            "field={field}"
        );
    }
    let mut stringly = wire.clone();
    stringly["semantics"]["exit"]["disposition"] = Json::String("never-suppresses".into());
    assert!(decode_context_manager_edge(&stringly).is_err());
    assert!(decode_context_manager_edge(&serde_json::json!({
        "kind": "call-edge", "schemaVersion": "1"
    }))
    .is_err());
    assert!(serde_json::from_value::<sugar_linker::LinkerCallEdge>(wire).is_err());

    let unresolved_table = ResolvedContractRefsV1::new(
        &AuthenticatedContextManagerCatalog::freeze(vec![]).unwrap(),
        &[demand("context-manager:fixture.never_closing")],
    );
    assert_eq!(
        final_check_context_manager_edges(
            &[ContextManagerEdgeV1::from_resolved(reference)],
            &unresolved_table,
            &catalog,
        )
        .unwrap_err()
        .to_string(),
        "unresolved-context-manager-edge"
    );
}
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};
