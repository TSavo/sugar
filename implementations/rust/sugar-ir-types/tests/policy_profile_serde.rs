// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_ir_types::{
    PolicyProfileDecisionKind, PolicyProfileMemento, PolicyProfileValidationError,
};

#[test]
fn policy_profile_round_trips_and_recomputes_cid() {
    let mut profile: PolicyProfileMemento =
        serde_json::from_str(&profile_json("")).expect("parse policy profile");
    profile.cid = profile.recompute_cid().expect("recompute profile cid");

    let serialized = serde_json::to_string(&profile).expect("serialize policy profile");
    let parsed: PolicyProfileMemento =
        serde_json::from_str(&serialized).expect("round-trip policy profile");

    assert_eq!(parsed.kind, "policy-profile");
    assert_eq!(parsed.schema_version, "1");
    assert_eq!(parsed.name, "smoke");
    assert_eq!(parsed.decisions.len(), 3);
    assert_eq!(parsed.recompute_cid().unwrap(), parsed.cid);
    assert_eq!(
        parsed.decisions[0].decision_kind,
        PolicyProfileDecisionKind::WitnessConsensus
    );
}

#[test]
fn policy_profile_validation_rejects_cid_mismatch() {
    let mut profile: PolicyProfileMemento =
        serde_json::from_str(&profile_json("")).expect("parse policy profile");
    profile.cid = cid('f');

    let err = profile
        .validate()
        .expect_err("mismatched profile cid must reject");

    assert!(matches!(
        err,
        PolicyProfileValidationError::CidMismatch { .. }
    ));
}

#[test]
fn policy_profile_validation_requires_emission_decisions_to_be_witnessed() {
    let mut profile: PolicyProfileMemento =
        serde_json::from_str(&profile_json("")).expect("parse policy profile");
    profile.cid = profile.recompute_cid().expect("recompute profile cid");
    let emission = profile
        .decisions
        .iter_mut()
        .find(|decision| decision.decision_kind == PolicyProfileDecisionKind::EmissionGating)
        .expect("emission decision exists");
    emission.requires_witnessed_decision = false;
    profile.cid = profile.recompute_cid().expect("recompute profile cid");

    let err = profile
        .validate()
        .expect_err("unwitnessed emission decisions must reject");

    assert_eq!(
        err,
        PolicyProfileValidationError::UnwitnessedEmissionDecision
    );
}

fn profile_json(cid_value: &str) -> String {
    format!(
        r#"{{
  "cid": "{cid_value}",
  "decisions": [
    {{
      "decision_kind": "witness-consensus",
      "policy_cid": "{consensus_policy}",
      "required": true,
      "requires_witnessed_decision": false,
      "thresholds": [
        {{"axis": "min-witnesses-floor", "predicate": "n>=1"}}
      ]
    }},
    {{
      "decision_kind": "sugar-selection",
      "policy_cid": "{sugar_policy}",
      "required": true,
      "requires_witnessed_decision": false,
      "thresholds": [
        {{"axis": "max-loss-score", "predicate": "loss_score<=1"}}
      ]
    }},
    {{
      "decision_kind": "emission-gating",
      "emission_mode": "gate",
      "policy_cid": "{emission_policy}",
      "required": true,
      "requires_witnessed_decision": true,
      "thresholds": [
        {{"axis": "witnessed-decision", "predicate": "witnessed_decisions>=1"}}
      ]
    }}
  ],
  "kind": "policy-profile",
  "name": "smoke",
  "schemaVersion": "1"
}}"#,
        cid_value = cid_value,
        consensus_policy = cid('a'),
        sugar_policy = cid('b'),
        emission_policy = cid('c')
    )
}

fn cid(ch: char) -> String {
    format!("blake3-512:{}", ch.to_string().repeat(128))
}
