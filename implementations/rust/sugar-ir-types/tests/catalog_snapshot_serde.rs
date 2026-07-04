// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Round-trip serde tests for CatalogSnapshotMemento and its canonical
// set-CID helper.
//
// Source of truth:
//   protocol/specs/2026-05-13-catalog-snapshot-memento.md §1, §3

use sugar_ir_types::{
    canonical_set_cid, CatalogKind, CatalogSnapshotGenesis, CatalogSnapshotMemento,
    CatalogSnapshotSuccessor, Cid, DuplicateInSetError,
};

const ROOT_CID: &str = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const PARENT_CID: &str = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const PROVENANCE_CID: &str = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const SIGNER_CID: &str = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
const SIGNATURE: &str = "ed25519:test-signature";
const SNAPSHOT_TIME: &str = "2026-05-13T12:00:00Z";

fn cid(hex: char) -> Cid {
    format!("blake3-512:{}", hex.to_string().repeat(128))
}

#[test]
fn canonical_set_cid_is_order_invariant() {
    let first = vec![cid('c'), cid('a'), cid('b')];
    let second = vec![cid('b'), cid('c'), cid('a')];

    let first_cid = canonical_set_cid(&first).expect("dedup-free input");
    let second_cid = canonical_set_cid(&second).expect("dedup-free input");

    assert_eq!(first_cid, second_cid);
    assert!(first_cid.starts_with("blake3-512:"));
    assert_eq!(first_cid.len(), "blake3-512:".len() + 128);
}

#[test]
fn canonical_set_cid_does_not_mutate_input() {
    // The new API takes &[Cid]; the caller MUST be able to retain the
    // original (unsorted) ordering.
    let input = vec![cid('c'), cid('a'), cid('b')];
    let _ = canonical_set_cid(&input).expect("dedup-free input");
    assert_eq!(input, vec![cid('c'), cid('a'), cid('b')]);
}

#[test]
fn canonical_set_cid_rejects_duplicates() {
    // A set CID cannot collapse a multiset silently. The spec says these
    // are SET CIDs; duplicates must be rejected before hashing so that
    // `[a, b]` and `[a, a, b]` do NOT produce different "set" CIDs.
    let input = vec![cid('a'), cid('b'), cid('a')];
    let err = canonical_set_cid(&input).expect_err("duplicate must fail closed");
    assert_eq!(err, DuplicateInSetError { cid: cid('a') });
}

#[test]
fn canonical_set_cid_rejects_adjacent_duplicates() {
    let input = vec![cid('z'), cid('z')];
    let err = canonical_set_cid(&input).expect_err("duplicate must fail closed");
    assert_eq!(err, DuplicateInSetError { cid: cid('z') });
}

#[test]
fn genesis_round_trips_and_set_cids_recompute() {
    let admitted = vec![cid('2'), cid('1')];
    let policies = vec![cid('4'), cid('3')];
    let decisions = vec![cid('6'), cid('5')];

    let snapshot = CatalogSnapshotMemento::Genesis(CatalogSnapshotGenesis {
        admitted_member_set_cid: canonical_set_cid(&admitted).expect("dedup"),
        catalog_kind: CatalogKind::ConceptShapes,
        catalog_root_cid: ROOT_CID.to_string(),
        genesis: "genesis".to_string(),
        policy_set_cid: canonical_set_cid(&policies).expect("dedup"),
        promotion_decision_set_cid: canonical_set_cid(&decisions).expect("dedup"),
        provenance_cid: PROVENANCE_CID.to_string(),
        signature: SIGNATURE.to_string(),
        signer_cid: SIGNER_CID.to_string(),
        snapshot_time: SNAPSHOT_TIME.to_string(),
    });

    let serialized = serde_json::to_string(&snapshot).expect("serialize genesis");
    assert!(serialized.contains(r#""genesis":"genesis""#));
    assert!(!serialized.contains("parent_snapshot_cid"));

    let parsed: CatalogSnapshotMemento = serde_json::from_str(&serialized).expect("parse genesis");
    assert_eq!(parsed, snapshot);

    let CatalogSnapshotMemento::Genesis(parsed) = parsed else {
        panic!("expected genesis variant");
    };
    assert_eq!(
        parsed.admitted_member_set_cid,
        canonical_set_cid(&admitted).expect("dedup")
    );
    assert_eq!(
        parsed.policy_set_cid,
        canonical_set_cid(&policies).expect("dedup")
    );
    assert_eq!(
        parsed.promotion_decision_set_cid,
        canonical_set_cid(&decisions).expect("dedup")
    );
}

#[test]
fn successor_round_trips_and_set_cids_recompute() {
    let admitted = vec![cid('9'), cid('7'), cid('8')];
    let policies = vec![cid('b'), cid('a')];
    let decisions = vec![cid('e'), cid('d'), cid('c')];

    let snapshot = CatalogSnapshotMemento::Successor(CatalogSnapshotSuccessor {
        admitted_member_set_cid: canonical_set_cid(&admitted).expect("dedup"),
        catalog_kind: CatalogKind::Namespaced("acme:custom-catalog".to_string()),
        catalog_root_cid: ROOT_CID.to_string(),
        parent_snapshot_cid: PARENT_CID.to_string(),
        policy_set_cid: canonical_set_cid(&policies).expect("dedup"),
        promotion_decision_set_cid: canonical_set_cid(&decisions).expect("dedup"),
        provenance_cid: PROVENANCE_CID.to_string(),
        signature: SIGNATURE.to_string(),
        signer_cid: SIGNER_CID.to_string(),
        snapshot_time: SNAPSHOT_TIME.to_string(),
    });

    let serialized = serde_json::to_string(&snapshot).expect("serialize successor");
    assert!(serialized.contains(r#""parent_snapshot_cid":"#));
    assert!(!serialized.contains(r#""genesis":"#));
    assert!(serialized.contains(r#""catalog_kind":"acme:custom-catalog""#));

    let parsed: CatalogSnapshotMemento =
        serde_json::from_str(&serialized).expect("parse successor");
    assert_eq!(parsed, snapshot);

    let CatalogSnapshotMemento::Successor(parsed) = parsed else {
        panic!("expected successor variant");
    };
    assert_eq!(
        parsed.admitted_member_set_cid,
        canonical_set_cid(&admitted).expect("dedup")
    );
    assert_eq!(
        parsed.policy_set_cid,
        canonical_set_cid(&policies).expect("dedup")
    );
    assert_eq!(
        parsed.promotion_decision_set_cid,
        canonical_set_cid(&decisions).expect("dedup")
    );
}

#[test]
fn catalog_kind_rejects_bare_unknown_at_deserialization() {
    // Per spec, extension catalog kinds MUST be `<namespace>:<kind>`.
    // A bare unknown like "custom-kind" (no namespace separator) must
    // fail closed at deserialization, not silently become Other("custom-kind").
    let bare = serde_json::json!("custom-kind").to_string();
    let result: Result<CatalogKind, _> = serde_json::from_str(&bare);
    assert!(
        result.is_err(),
        "bare unknown catalog kind should fail closed, got {:?}",
        result
    );
}

#[test]
fn catalog_kind_accepts_well_formed_namespaced_extension() {
    let valid = serde_json::json!("acme:custom-catalog").to_string();
    let parsed: CatalogKind = serde_json::from_str(&valid).expect("parse");
    assert_eq!(
        parsed,
        CatalogKind::Namespaced("acme:custom-catalog".to_string())
    );
}

#[test]
fn catalog_kind_rejects_multi_colon() {
    let result: Result<CatalogKind, _> = serde_json::from_str("\"a:b:c\"");
    assert!(
        result.is_err(),
        "multi-colon should fail closed, got {:?}",
        result
    );
}
