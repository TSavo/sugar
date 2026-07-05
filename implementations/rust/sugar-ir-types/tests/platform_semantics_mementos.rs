// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeMap;

use serde_json::json;
use sugar_ir_types::{
    DimensionValueMemento, IrFormula, LiteralEncodingMemento, PlatformSemanticTag,
};

const KIT_CID: &str = "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
const OP_CID: &str = "blake3-512:22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222";
// CIDs updated post-#1260: kit_cid no longer participates in content-hash.
// Identical (dimension_name, value_name, compare_to) content now yields the
// same CID regardless of kit_cid provenance. Tag CID shifted because its
// content includes the dimension value CIDs.
const WRAPPING_CID: &str = "blake3-512:8b196b5993cafc3d9f3ae6f28b2128e27f5e272e10b90b636ed097b25308bce826b60bcf7166940a63146f9808b20d09e0189df71e05c0b34228ec933495d4c6";
const TRUNCATE_CID: &str = "blake3-512:2824e54f472b2c31b9ce572e6930cebf039470661ed8ff1a4b6926862399e79fcdd7ac48340ada6d9ca34bc952eccc4530bc4728e409d32b19fdc0296204d676";
const TAG_CID: &str = "blake3-512:41d3b232fc77410ef94698030b201c02a2a86801cf676b8560871a485a30332428a913b7e973c1596dbc37a97757c1525c70fe0c8614310c621408f73dba1f5a";

fn true_formula() -> IrFormula {
    IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    }
}

#[test]
fn dimension_value_memento_round_trips_and_recomputes_cid() {
    let value = DimensionValueMemento::new(
        KIT_CID.to_string(),
        "ArithmeticOverflowMode".to_string(),
        "Wrapping".to_string(),
        true_formula(),
    );

    let encoded = value.to_jcs_string();
    let decoded: DimensionValueMemento =
        serde_json::from_str(&encoded).expect("dimension value decodes");

    assert_eq!(decoded, value);
    assert_eq!(decoded.cid, decoded.recompute_cid());
    assert_eq!(decoded.cid, WRAPPING_CID);
}

#[test]
fn platform_semantic_tag_round_trips_and_recomputes_cid() {
    let wrapping = DimensionValueMemento::new(
        KIT_CID.to_string(),
        "ArithmeticOverflowMode".to_string(),
        "Wrapping".to_string(),
        true_formula(),
    );
    let truncate = DimensionValueMemento::new(
        KIT_CID.to_string(),
        "IntegerDivisionRoundingMode".to_string(),
        "Truncate".to_string(),
        true_formula(),
    );
    let mut dimensions = BTreeMap::new();
    dimensions.insert(
        "IntegerDivisionRoundingMode".to_string(),
        truncate.cid.clone(),
    );
    dimensions.insert("ArithmeticOverflowMode".to_string(), wrapping.cid.clone());

    let tag = PlatformSemanticTag::new(KIT_CID.to_string(), OP_CID.to_string(), dimensions);

    let encoded = tag.to_jcs_string();
    let decoded: PlatformSemanticTag = serde_json::from_str(&encoded).expect("tag decodes");

    assert_eq!(wrapping.cid, WRAPPING_CID);
    assert_eq!(truncate.cid, TRUNCATE_CID);
    assert_eq!(decoded, tag);
    assert_eq!(decoded.cid, decoded.recompute_cid());
    assert_eq!(decoded.cid, TAG_CID);
    assert!(
        encoded
            .find("ArithmeticOverflowMode")
            .expect("overflow key")
            < encoded
                .find("IntegerDivisionRoundingMode")
                .expect("division key")
    );
}

const SORT_INT_CID: &str = "blake3-512:30ffc51350121a7172f3e4064a33c45bbd345756979fccff6875cd2ab33e4964d098a99df80cfbdf1ec1a0738c5ac3476f0ff8f75589ea511d1acd82c74ecd58";

/// LiteralEncodingMemento round-trips through JCS and recomputes its own
/// CID. Per #1262, this records what concept:literal node the kit's bind-lift
/// emits for a representative source-language literal.
#[test]
fn literal_encoding_memento_round_trips_and_recomputes_cid() {
    let memento = LiteralEncodingMemento::new(
        KIT_CID.to_string(),
        "rust".to_string(),
        SORT_INT_CID.to_string(),
        "42".to_string(),
        json!(42),
    );

    let encoded = memento.to_jcs_string();
    let decoded: LiteralEncodingMemento =
        serde_json::from_str(&encoded).expect("literal encoding decodes");

    assert_eq!(decoded, memento);
    assert_eq!(decoded.cid, decoded.recompute_cid());
    assert_eq!(decoded.kind, LiteralEncodingMemento::KIND);
    assert_eq!(
        decoded.schema_version,
        LiteralEncodingMemento::SCHEMA_VERSION
    );
    assert!(decoded
        .expected_term_shape_node
        .op_cid
        .starts_with("blake3-512:"));
    assert_eq!(decoded.expected_term_shape_node.sort, SORT_INT_CID);
    assert_eq!(decoded.expected_term_shape_node.value, json!(42));
}

/// Substrate-uniform property (cross-kit equivalence): two kits with
/// identical (language, sort_cid, source_example, decoded value) tuples
/// produce byte-identical LiteralEncodingMemento CIDs even when kit_cid
/// differs. Mirrors the post-#1271 kit_cid elision behavior already
/// exercised by DimensionValueMemento + PlatformSemanticTag.
#[test]
fn literal_encoding_memento_cross_kit_equivalence_via_kit_cid_elision() {
    let kit_a = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    let kit_b = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    let memento_a = LiteralEncodingMemento::new(
        kit_a.to_string(),
        "rust".to_string(),
        SORT_INT_CID.to_string(),
        "42".to_string(),
        json!(42),
    );
    let memento_b = LiteralEncodingMemento::new(
        kit_b.to_string(),
        "rust".to_string(),
        SORT_INT_CID.to_string(),
        "42".to_string(),
        json!(42),
    );

    assert_ne!(memento_a.kit_cid, memento_b.kit_cid);
    assert_eq!(
        memento_a.cid, memento_b.cid,
        "kit_cid is elided from content-hash; identical (lang, sort, source, value) MUST collide"
    );
}
