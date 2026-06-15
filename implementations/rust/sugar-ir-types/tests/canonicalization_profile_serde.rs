// SPDX-License-Identifier: Apache-2.0
//
// Round-trip serde and CID tests for CanonicalizationProfileMemento.
//
// Source of truth:
//   protocol/specs/2026-05-13-canonicalization-profile-memento.md §1, §7
//
// These tests pin the substrate declaration shape only. They do not
// execute canonicalization rules or define a rule sublanguage.

use std::sync::Arc;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_ir_types::{
    CanonicalizationProfileKind, CanonicalizationProfileMemento, CanonicalizationRuleDescriptor,
    UnsupportedEquivalencePolicy,
};

const PROVENANCE_CID: &str = "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
const LANGUAGE_SIGNATURE_CID: &str = "blake3-512:22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222";
const REFERENCE_CID: &str = "blake3-512:33333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333";
const EXPECTED_PROFILE_CID: &str = "blake3-512:e4ee17f130cf96b0a396c4660fae5721dd2e6bdd178346819e403e367936eeda92b95b0886f73be9dfceb63ce38efb3673f167049722f92843e106b2c58bbcca";

fn cvalue_from_json(value: &serde_json::Value) -> Arc<CValue> {
    match value {
        serde_json::Value::Null => CValue::null(),
        serde_json::Value::Bool(b) => CValue::boolean(*b),
        serde_json::Value::Number(n) => {
            CValue::integer(i128::from(n.as_i64().expect("test numbers fit i64")))
        }
        serde_json::Value::String(s) => CValue::string(s.clone()),
        serde_json::Value::Array(values) => {
            CValue::array(values.iter().map(cvalue_from_json).collect())
        }
        serde_json::Value::Object(map) => CValue::object(
            map.iter()
                .map(|(key, value)| (key.clone(), cvalue_from_json(value)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn cid_of_profile(profile: &CanonicalizationProfileMemento) -> String {
    let json = serde_json::to_value(profile).expect("profile serializes to JSON");
    let canonical = cvalue_from_json(&json);
    blake3_512_of(encode_jcs(&canonical).as_bytes())
}

fn rule(rule_id: &str, description: &str) -> CanonicalizationRuleDescriptor {
    CanonicalizationRuleDescriptor {
        description: description.to_string(),
        language_signature_cid: None,
        reference_cid: Some(REFERENCE_CID.to_string()),
        rule_id: rule_id.to_string(),
        rule_payload: None,
        rule_version: "1.0.0".to_string(),
    }
}

fn full_profile(policy: UnsupportedEquivalencePolicy) -> CanonicalizationProfileMemento {
    CanonicalizationProfileMemento {
        alpha_equivalence_rules: vec![rule(
            "alpha.bound-variable-renaming",
            "Bound-variable renaming preserves identity when binding structure is unchanged.",
        )],
        binder_normalization_rules: vec![rule(
            "binder.de-bruijn-index",
            "Bound variables may be represented by De Bruijn index under explicit binders.",
        )],
        formal_name_normalization_rules: vec![CanonicalizationRuleDescriptor {
            description: "Slot aliases normalize to the declared formal parameter slot."
                .to_string(),
            language_signature_cid: Some(LANGUAGE_SIGNATURE_CID.to_string()),
            reference_cid: Some(REFERENCE_CID.to_string()),
            rule_id: "formal.slot-alias".to_string(),
            rule_payload: Some(serde_json::json!({
                "canonical": "$arg0",
                "slot": 0,
                "variants": ["$arg0", "$arg_0", "$0"]
            })),
            rule_version: "1.0.0".to_string(),
        }],
        formula_canonicalization_rules: vec![rule(
            "formula.redundant-parentheses",
            "Redundant parentheses may be removed when parse structure is unchanged.",
        )],
        profile_kind: CanonicalizationProfileKind::IrFormula,
        profile_version: "2026-05-13.1".to_string(),
        provenance_cid: PROVENANCE_CID.to_string(),
        sort_alias_rules: vec![CanonicalizationRuleDescriptor {
            description: "Sort aliases collapse only under the pinned language signature."
                .to_string(),
            language_signature_cid: Some(LANGUAGE_SIGNATURE_CID.to_string()),
            reference_cid: Some(REFERENCE_CID.to_string()),
            rule_id: "sort.pinned-alias".to_string(),
            rule_payload: Some(serde_json::json!({
                "aliases": [["int", "i32"]]
            })),
            rule_version: "1.0.0".to_string(),
        }],
        unsupported_equivalence_policy: policy,
    }
}

#[test]
fn profile_with_all_rule_categories_round_trips_and_recomputes_cid() {
    let profile = full_profile(UnsupportedEquivalencePolicy::Preserve);

    let serialized = serde_json::to_string(&profile).expect("serialize");
    assert!(serialized.contains("\"alpha_equivalence_rules\""));
    assert!(serialized.contains("\"binder_normalization_rules\""));
    assert!(serialized.contains("\"formal_name_normalization_rules\""));
    assert!(serialized.contains("\"formula_canonicalization_rules\""));
    assert!(serialized.contains("\"sort_alias_rules\""));
    assert!(!serialized.contains("\"cid\""));

    let parsed: CanonicalizationProfileMemento =
        serde_json::from_str(&serialized).expect("parse serialized profile");
    assert_eq!(parsed, profile);
    assert_eq!(parsed.alpha_equivalence_rules.len(), 1);
    assert_eq!(parsed.binder_normalization_rules.len(), 1);
    assert_eq!(parsed.formal_name_normalization_rules.len(), 1);
    assert_eq!(parsed.formula_canonicalization_rules.len(), 1);
    assert_eq!(parsed.sort_alias_rules.len(), 1);

    assert_eq!(cid_of_profile(&profile), EXPECTED_PROFILE_CID);
    assert_eq!(cid_of_profile(&parsed), EXPECTED_PROFILE_CID);
}

#[test]
fn unsupported_equivalence_policy_round_trips() {
    let cases = [
        (UnsupportedEquivalencePolicy::Preserve, "\"preserve\""),
        (UnsupportedEquivalencePolicy::Refuse, "\"refuse\""),
        (
            UnsupportedEquivalencePolicy::Namespaced("vendor:diagnose-only".to_string()),
            "\"vendor:diagnose-only\"",
        ),
    ];

    for (policy, wire) in cases {
        let serialized = serde_json::to_string(&policy).expect("serialize policy");
        assert_eq!(serialized, wire);
        let parsed: UnsupportedEquivalencePolicy =
            serde_json::from_str(wire).expect("parse policy");
        assert_eq!(parsed, policy);
    }

    let refuse_profile = full_profile(UnsupportedEquivalencePolicy::Refuse);
    let serialized = serde_json::to_string(&refuse_profile).expect("serialize profile");
    assert!(serialized.contains("\"unsupported_equivalence_policy\":\"refuse\""));
    let parsed: CanonicalizationProfileMemento =
        serde_json::from_str(&serialized).expect("parse refuse profile");
    assert_eq!(
        parsed.unsupported_equivalence_policy,
        UnsupportedEquivalencePolicy::Refuse
    );
}

#[test]
fn profile_kind_rejects_bare_unknown() {
    // Per spec §3 + admissibility-spine namespaced-extensions rule, a bare
    // unknown profile_kind (no `:` separator) MUST fail closed at
    // deserialization, not silently become Other(s).
    let result: Result<CanonicalizationProfileKind, _> = serde_json::from_str("\"weird-kind\"");
    assert!(
        result.is_err(),
        "bare unknown profile_kind should fail closed, got {:?}",
        result
    );
}

#[test]
fn profile_kind_accepts_well_formed_namespaced_extension() {
    let parsed: CanonicalizationProfileKind =
        serde_json::from_str("\"acme:loop-shape\"").expect("parse namespaced");
    assert_eq!(
        parsed,
        CanonicalizationProfileKind::Namespaced("acme:loop-shape".to_string())
    );
}

#[test]
fn unsupported_equivalence_policy_rejects_bare_unknown() {
    let result: Result<UnsupportedEquivalencePolicy, _> = serde_json::from_str("\"ignore\"");
    assert!(
        result.is_err(),
        "bare unknown policy should fail closed, got {:?}",
        result
    );
}

#[test]
fn profile_kind_rejects_multi_colon() {
    let result: Result<CanonicalizationProfileKind, _> = serde_json::from_str("\"a:b:c\"");
    assert!(
        result.is_err(),
        "multi-colon should fail closed, got {:?}",
        result
    );
}

#[test]
fn unsupported_equivalence_policy_rejects_multi_colon() {
    let result: Result<UnsupportedEquivalencePolicy, _> = serde_json::from_str("\"a:b:c\"");
    assert!(
        result.is_err(),
        "multi-colon should fail closed, got {:?}",
        result
    );
}
