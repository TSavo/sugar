use serde_json::Value as Json;
use sugar_claim_envelope::{
    mint_context_manager_contract, Authoring, MintContextManagerContractArgs,
};
use sugar_ir_types::Sort;
use sugar_linker::{
    final_check_context_manager_ref, resolve_context_manager_demand,
    AuthenticatedContextManagerCatalog, Cid, ContextManagerContractDemandV1,
    ContextManagerResolutionGapKindV1, ContextManagerResolutionV1, SourceFragmentCoordinateV1,
};
use sugar_proof_envelope::{
    ContextManagerSemanticsV1, EnterResultContractV1, ExitContractV1, ExitDispositionV1,
    ImportSignatureV1,
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
        import_signature: ImportSignatureV1 {
            formals: vec![],
            sorts: vec![],
        },
        semantics: ContextManagerSemanticsV1 {
            enter: EnterResultContractV1 {
                sort: Sort::Primitive {
                    name: "Value".into(),
                },
            },
            exit: ExitContractV1 {
                disposition: ExitDispositionV1::NeverSuppresses,
            },
        },
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
        ImportSignatureV1 {
            formals: vec![],
            sorts: vec![],
        },
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
        reference.semantics().exit.disposition,
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
