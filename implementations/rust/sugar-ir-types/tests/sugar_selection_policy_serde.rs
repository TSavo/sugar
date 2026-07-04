// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_ir_types::{
    SugarSelectionMode, SugarSelectionPolicyMemento, SugarSelectionPolicyValidationError,
    SugarSelectionTieBreaking,
};

#[test]
fn sugar_selection_policy_round_trips_from_jcs_byte_identical() {
    let mut policy: SugarSelectionPolicyMemento =
        serde_json::from_str(&policy_json("")).expect("parse sugar selection policy");
    policy.cid = policy
        .recompute_cid()
        .expect("recompute sugar selection policy cid");
    let jcs = policy.to_jcs_string().expect("canonicalize policy");

    let parsed =
        SugarSelectionPolicyMemento::from_jcs(&jcs).expect("parse policy from canonical bytes");
    let reserialized = parsed.to_jcs_string().expect("canonicalize parsed policy");

    assert_eq!(reserialized, jcs);
    assert_eq!(parsed.kind, "sugar-selection-policy");
    assert_eq!(parsed.schema_version, "1");
    assert_eq!(parsed.mode, SugarSelectionMode::Inclusive);
    assert_eq!(
        parsed.tie_breaking,
        SugarSelectionTieBreaking::LoadOrderThenEntryIndex
    );
    assert_eq!(parsed.recompute_cid().unwrap(), parsed.cid);
}

#[test]
fn sugar_selection_policy_requires_at_least_one_apply_match() {
    let mut policy: SugarSelectionPolicyMemento =
        serde_json::from_str(&policy_json("")).expect("parse sugar selection policy");
    policy.applies_to.clear();
    policy.cid = policy
        .recompute_cid()
        .expect("recompute sugar selection policy cid");

    let err = policy.validate().expect_err("empty applies_to must reject");

    assert_eq!(err, SugarSelectionPolicyValidationError::EmptyAppliesTo);
}

#[test]
fn sugar_selection_policy_rejects_policy_profile_kind() {
    let mut policy: SugarSelectionPolicyMemento =
        serde_json::from_str(&policy_json("")).expect("parse sugar selection policy");
    policy.kind = "policy-profile".to_string();
    policy.cid = policy
        .recompute_cid()
        .expect("recompute sugar selection policy cid");

    let err = policy
        .validate()
        .expect_err("policy-profile kind must not parse as sugar selection policy");

    assert!(matches!(
        err,
        SugarSelectionPolicyValidationError::InvalidKind { .. }
    ));
}

fn policy_json(cid_value: &str) -> String {
    format!(
        r#"{{
  "applies_to": [
    {{"concept": "concept:non-null", "language": "java"}}
  ],
  "cid": "{cid_value}",
  "eligible_sugars": [
    "{eligible_sugar}"
  ],
  "forbidden_sugars": [
    "{forbidden_sugar}"
  ],
  "kind": "sugar-selection-policy",
  "mode": "inclusive",
  "schemaVersion": "1",
  "scoring": "{scoring}",
  "tie_breaking": "load-order-then-entry-index"
}}"#,
        cid_value = cid_value,
        eligible_sugar = cid('a'),
        forbidden_sugar = cid('b'),
        scoring = cid('c')
    )
}

fn cid(ch: char) -> String {
    format!("blake3-512:{}", ch.to_string().repeat(128))
}
