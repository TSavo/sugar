// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::{BTreeMap, BTreeSet, VecDeque};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FunctionEffectInfo {
    pub forbidding_contract_cid: Option<String>,
    pub function_cid: String,
    pub name: String,
    pub signature_cid: String,
    pub admitted_effects: BTreeSet<String>,
    pub forbidden_effects: BTreeSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallsiteEdge {
    pub callee: Option<String>,
    pub cid: String,
    pub containing_fn: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChangedCallsite {
    pub callsite_cid: String,
    pub dimension_name: Option<String>,
    pub effect: String,
}

/// A non-empty collection of changed callsites.
///
/// The only constructor is `NonEmptyChangedCallsites::new`, which returns `None`
/// when given an empty `Vec`. Callers that receive `None` must skip propagation
/// entirely -- there is nothing to propagate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NonEmptyChangedCallsites(Vec<ChangedCallsite>);

/// Error returned when attempting to construct `NonEmptyChangedCallsites` from
/// an empty `Vec`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmptyChangedCallsitesError;

impl std::fmt::Display for EmptyChangedCallsitesError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("changed callsite list must not be empty")
    }
}

impl NonEmptyChangedCallsites {
    /// Construct from a `Vec<ChangedCallsite>`.
    ///
    /// Returns `Err(EmptyChangedCallsitesError)` if `callsites` is empty.
    pub fn new(callsites: Vec<ChangedCallsite>) -> Result<Self, EmptyChangedCallsitesError> {
        if callsites.is_empty() {
            Err(EmptyChangedCallsitesError)
        } else {
            Ok(Self(callsites))
        }
    }

    /// Iterate over the contained callsites.
    pub fn iter(&self) -> impl Iterator<Item = &ChangedCallsite> {
        self.0.iter()
    }

    /// The number of contained callsites (always >= 1).
    pub fn len(&self) -> usize {
        self.0.len()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PropagationInput {
    pub callsites: BTreeMap<String, CallsiteEdge>,
    pub changed_callsites: NonEmptyChangedCallsites,
    pub functions: BTreeMap<String, FunctionEffectInfo>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PropagationDecision {
    Widen {
        dimension_name: Option<String>,
        effect: String,
        function_cid: String,
        triggering_callsite_cid: String,
    },
    Halt {
        admitting_signature_cid: String,
        function_cid: String,
        reason: String,
    },
    Refuse {
        forbidding_contract_cid: String,
        function_cid: String,
        reason: String,
        triggering_callsite_cid: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PropagationPlan {
    pub decisions: BTreeMap<String, PropagationDecision>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PendingCallsite {
    callsite_cid: String,
    dimension_name: Option<String>,
    effect: String,
}

pub fn propagate_effects(input: &PropagationInput) -> Result<PropagationPlan, String> {
    let mut callers_by_callee: BTreeMap<String, Vec<&CallsiteEdge>> = BTreeMap::new();
    for callsite in input.callsites.values() {
        if let Some(callee) = &callsite.callee {
            callers_by_callee
                .entry(callee.clone())
                .or_default()
                .push(callsite);
        }
    }

    let mut worklist: VecDeque<PendingCallsite> = input
        .changed_callsites
        .iter()
        .map(|changed| PendingCallsite {
            callsite_cid: changed.callsite_cid.clone(),
            dimension_name: changed.dimension_name.clone(),
            effect: changed.effect.clone(),
        })
        .collect();
    let mut decisions: BTreeMap<String, PropagationDecision> = BTreeMap::new();

    while let Some(pending) = worklist.pop_front() {
        let callsite = input
            .callsites
            .get(&pending.callsite_cid)
            .ok_or_else(|| format!("unknown callsite {}", pending.callsite_cid))?;
        let function = input
            .functions
            .get(&callsite.containing_fn)
            .ok_or_else(|| format!("unknown function {}", callsite.containing_fn))?;
        if decisions.contains_key(&function.name) {
            continue;
        }

        if function.admitted_effects.contains(&pending.effect) {
            decisions.insert(
                function.name.clone(),
                PropagationDecision::Halt {
                    admitting_signature_cid: function.signature_cid.clone(),
                    function_cid: function.function_cid.clone(),
                    reason: "signature already admits".to_string(),
                },
            );
            continue;
        }

        if function.forbidden_effects.contains(&pending.effect) {
            let contract = function
                .forbidding_contract_cid
                .clone()
                .unwrap_or_else(|| function.signature_cid.clone());
            decisions.insert(
                function.name.clone(),
                PropagationDecision::Refuse {
                    forbidding_contract_cid: contract,
                    function_cid: function.function_cid.clone(),
                    reason: "contract forbids widening".to_string(),
                    triggering_callsite_cid: pending.callsite_cid.clone(),
                },
            );
            continue;
        }

        decisions.insert(
            function.name.clone(),
            PropagationDecision::Widen {
                dimension_name: pending.dimension_name.clone(),
                effect: pending.effect.clone(),
                function_cid: function.function_cid.clone(),
                triggering_callsite_cid: pending.callsite_cid.clone(),
            },
        );

        if let Some(callers) = callers_by_callee.get(&function.name) {
            for caller_callsite in callers {
                worklist.push_back(PendingCallsite {
                    callsite_cid: caller_callsite.cid.clone(),
                    dimension_name: pending.dimension_name.clone(),
                    effect: pending.effect.clone(),
                });
            }
        }
    }

    Ok(PropagationPlan { decisions })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn info(name: &str) -> FunctionEffectInfo {
        FunctionEffectInfo {
            forbidding_contract_cid: None,
            function_cid: format!("cid:function:{name}"),
            name: name.to_string(),
            signature_cid: format!("cid:signature:{name}"),
            admitted_effects: BTreeSet::new(),
            forbidden_effects: BTreeSet::new(),
        }
    }

    #[test]
    fn propagates_until_async_boundary_and_public_refusal() {
        let mut functions = BTreeMap::new();
        functions.insert("query".to_string(), info("query"));
        functions.insert("render".to_string(), info("render"));
        let mut handler = info("handler");
        handler.admitted_effects.insert("async".to_string());
        functions.insert("handler".to_string(), handler);
        let mut formatter = info("formatter");
        formatter.forbidden_effects.insert("async".to_string());
        formatter.forbidding_contract_cid = Some("cid:contract:formatter".to_string());
        functions.insert("formatter".to_string(), formatter);

        let mut callsites = BTreeMap::new();
        callsites.insert(
            "cs:sql".to_string(),
            CallsiteEdge {
                callee: None,
                cid: "cs:sql".to_string(),
                containing_fn: "query".to_string(),
            },
        );
        callsites.insert(
            "cs:render-query".to_string(),
            CallsiteEdge {
                callee: Some("query".to_string()),
                cid: "cs:render-query".to_string(),
                containing_fn: "render".to_string(),
            },
        );
        callsites.insert(
            "cs:handler-render".to_string(),
            CallsiteEdge {
                callee: Some("render".to_string()),
                cid: "cs:handler-render".to_string(),
                containing_fn: "handler".to_string(),
            },
        );
        callsites.insert(
            "cs:formatter-query".to_string(),
            CallsiteEdge {
                callee: Some("query".to_string()),
                cid: "cs:formatter-query".to_string(),
                containing_fn: "formatter".to_string(),
            },
        );

        let changed = NonEmptyChangedCallsites::new(vec![ChangedCallsite {
            callsite_cid: "cs:sql".to_string(),
            dimension_name: None,
            effect: "async".to_string(),
        }])
        .expect("non-empty callsites");
        let plan = propagate_effects(&PropagationInput {
            callsites,
            changed_callsites: changed,
            functions,
        })
        .expect("propagation succeeds");

        assert!(matches!(
            plan.decisions.get("query"),
            Some(PropagationDecision::Widen { .. })
        ));
        assert!(matches!(
            plan.decisions.get("render"),
            Some(PropagationDecision::Widen { .. })
        ));
        assert!(matches!(
            plan.decisions.get("handler"),
            Some(PropagationDecision::Halt { .. })
        ));
        assert!(matches!(
            plan.decisions.get("formatter"),
            Some(PropagationDecision::Refuse { .. })
        ));
    }

    #[test]
    fn non_empty_changed_callsites_accepts_non_empty_vec() {
        let callsite = ChangedCallsite {
            callsite_cid: "cs:test".to_string(),
            dimension_name: Some("ArithmeticOverflow".to_string()),
            effect: "async".to_string(),
        };
        let result = NonEmptyChangedCallsites::new(vec![callsite.clone()]);
        assert!(result.is_ok());
        let wrapped = result.unwrap();
        assert_eq!(wrapped.len(), 1);
        assert_eq!(wrapped.iter().next(), Some(&callsite));
    }

    #[test]
    fn non_empty_changed_callsites_rejects_empty_vec() {
        let result = NonEmptyChangedCallsites::new(vec![]);
        assert!(result.is_err());
        assert_eq!(
            result.unwrap_err().to_string(),
            "changed callsite list must not be empty"
        );
    }
}
