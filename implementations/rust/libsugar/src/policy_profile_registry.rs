// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeMap;

use sugar_ir_types::{
    PolicyProfileDecision, PolicyProfileDecisionKind, PolicyProfileMemento, PolicyProfileThreshold,
};

#[derive(Debug, Clone, Default)]
pub struct PolicyProfileRegistry {
    profiles: BTreeMap<String, PolicyProfileMemento>,
}

#[derive(Debug, thiserror::Error)]
pub enum PolicyProfileRegistryError {
    #[error("policy-profile-registry: parse failed as PolicyProfileMemento: {0}")]
    Parse(String),
    #[error("policy-profile-registry: invalid profile: {0}")]
    Invalid(String),
    #[error("policy-profile-registry: invalid threshold predicate in profile {profile_cid} decision {decision_kind} axis {axis}: `{predicate}`: {reason}")]
    InvalidThresholdPredicate {
        profile_cid: String,
        decision_kind: String,
        axis: String,
        predicate: String,
        reason: String,
    },
}

impl PolicyProfileRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn admit_json_str(&mut self, text: &str) -> Result<(), PolicyProfileRegistryError> {
        let profile: PolicyProfileMemento = serde_json::from_str(text)
            .map_err(|err| PolicyProfileRegistryError::Parse(err.to_string()))?;
        self.admit(profile)
    }

    pub fn admit(
        &mut self,
        profile: PolicyProfileMemento,
    ) -> Result<(), PolicyProfileRegistryError> {
        profile
            .validate()
            .map_err(|err| PolicyProfileRegistryError::Invalid(err.to_string()))?;

        for decision in &profile.decisions {
            for threshold in &decision.thresholds {
                parse_predicate(&threshold.predicate).map_err(|reason| {
                    PolicyProfileRegistryError::InvalidThresholdPredicate {
                        profile_cid: profile.cid.clone(),
                        decision_kind: decision.decision_kind.as_str().to_string(),
                        axis: threshold.axis.clone(),
                        predicate: threshold.predicate.clone(),
                        reason,
                    }
                })?;
            }
        }

        self.profiles.insert(profile.cid.clone(), profile);
        Ok(())
    }

    pub fn get(&self, profile_cid: &str) -> Option<&PolicyProfileMemento> {
        self.profiles.get(profile_cid)
    }

    pub fn decision(
        &self,
        profile_cid: &str,
        decision_kind: &PolicyProfileDecisionKind,
    ) -> Option<&PolicyProfileDecision> {
        self.get(profile_cid)?
            .decisions
            .iter()
            .find(|decision| decision.decision_kind.as_str() == decision_kind.as_str())
    }

    pub fn thresholds(
        &self,
        profile_cid: &str,
        decision_kind: &PolicyProfileDecisionKind,
    ) -> Option<&[PolicyProfileThreshold]> {
        self.decision(profile_cid, decision_kind)
            .map(|decision| decision.thresholds.as_slice())
    }
}

fn parse_predicate(predicate: &str) -> Result<(&str, &str, u64), String> {
    for op in [">=", "<=", "==", ">", "<"] {
        if let Some((left, right)) = predicate.split_once(op) {
            let left = left.trim();
            if left.is_empty() {
                return Err("metric is empty".to_string());
            }
            let right = right
                .trim()
                .parse::<u64>()
                .map_err(|err| format!("threshold is not an integer: {err}"))?;
            return Ok((left, op, right));
        }
    }
    Err("unsupported predicate grammar".to_string())
}
