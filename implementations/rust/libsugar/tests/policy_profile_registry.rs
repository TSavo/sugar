// SPDX-License-Identifier: MIT OR Apache-2.0

use libsugar::policy_profile_registry::{PolicyProfileRegistry, PolicyProfileRegistryError};
use sugar_ir_types::PolicyProfileDecisionKind;

#[test]
fn registry_indexes_profile_by_cid_and_returns_decision_thresholds() {
    let mut profile: sugar_ir_types::PolicyProfileMemento =
        serde_json::from_str(&profile_json("")).expect("parse profile");
    profile.cid = profile.recompute_cid().expect("recompute profile cid");
    let profile_cid = profile.cid.clone();

    let mut registry = PolicyProfileRegistry::new();
    registry.admit(profile).expect("profile admitted");

    let thresholds = registry
        .thresholds(&profile_cid, &PolicyProfileDecisionKind::WitnessConsensus)
        .expect("witness consensus thresholds");
    assert_eq!(thresholds[0].axis, "min-witnesses-floor");
    assert_eq!(thresholds[0].predicate, "n>=1");

    let emission = registry
        .decision(&profile_cid, &PolicyProfileDecisionKind::EmissionGating)
        .expect("emission decision");
    assert_eq!(emission.emission_mode.as_deref(), Some("gate"));
    assert!(emission.requires_witnessed_decision);
}

#[test]
fn registry_rejects_profiles_with_malformed_threshold_predicates() {
    let mut profile: sugar_ir_types::PolicyProfileMemento =
        serde_json::from_str(&profile_json("")).expect("parse profile");
    profile.decisions[0].thresholds[0].predicate = "n roughly one".to_string();
    profile.cid = profile.recompute_cid().expect("recompute profile cid");

    let mut registry = PolicyProfileRegistry::new();
    let err = registry
        .admit(profile)
        .expect_err("malformed predicate must reject");

    assert!(matches!(
        err,
        PolicyProfileRegistryError::InvalidThresholdPredicate { .. }
    ));
}

#[test]
fn registry_admits_reference_smoke_and_prod_profiles() {
    let mut registry = PolicyProfileRegistry::new();
    for path in [
        "../../../protocol/policies/smoke.json",
        "../../../protocol/policies/prod.json",
    ] {
        let text = std::fs::read_to_string(path).expect("read reference profile");
        registry
            .admit_json_str(&text)
            .unwrap_or_else(|err| panic!("{path} must admit: {err}"));
    }

    let smoke = registry
        .get("blake3-512:3166b9224022a79ed498ad08617b1461ded2fb40809d4f8127b72f00d3d2bc85d1de1aa2014563880d1e67946416b9939e274eae943e53b0aa57dea8591c1467")
        .expect("smoke profile indexed");
    let prod = registry
        .get("blake3-512:7f9c6b9f754ce5e41150ea9d8733920bd18f081f733a5f820aae0fba099f67e376928103fa6bd1b2651cd548650a6a52a23b1579512ea60d900cb2f7322da856")
        .expect("prod profile indexed");

    assert_eq!(smoke.name, "smoke");
    assert_eq!(prod.name, "prod");
    assert_eq!(
        registry
            .decision(&smoke.cid, &PolicyProfileDecisionKind::EmissionGating)
            .and_then(|decision| decision.emission_mode.as_deref()),
        Some("gate")
    );
    assert_eq!(
        registry
            .decision(&prod.cid, &PolicyProfileDecisionKind::EmissionGating)
            .and_then(|decision| decision.emission_mode.as_deref()),
        Some("monitor")
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
