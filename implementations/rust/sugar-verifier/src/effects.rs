// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Typed verification effects for #3482.
//
// Refused-not-green is still load-bearing. The migration here is narrower:
// verifier grounds are typed first, then lowered to today's legacy
// status/reason strings at the CLI/JSON boundary.

use std::fmt;

use serde_json::{json, Value as Json};

use crate::types::ObligationVerdict;

const NO_SIBLING_TO_CONTRADICT_REASON: &str =
    "consistency check vacuous: single constraint has no sibling to contradict and no covering universe joins the left-operand term — not a substantive discharge";
const MISSING_INDEPENDENT_KIND_REASON: &str =
    "consistency check lacks an independent-KIND witness: Stated testimony cannot corroborate Stated testimony";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifyEffectBoundary {
    pub verdict: ObligationVerdict,
    pub reason: String,
    pub verification: Option<Json>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VerifyEffect {
    MissingProvenanceKind {
        contract_cid: String,
        property_name: String,
        detail: String,
    },
    NoSiblingToContradict {
        contract_cid: String,
        property_name: String,
        constraint_count: usize,
    },
    MissingIndependentKindWitness {
        contract_cid: String,
        property_name: String,
    },
    ConsistencyNoSoundDischarger {
        property_name: String,
        solver_reason: String,
    },
    SolverTimeout {
        property_name: String,
        solver_reason: String,
    },
    SolverNoSoundDischarger {
        solver_name: String,
    },
    UnwitnessedDischarge {
        contract_cid: String,
        property_name: String,
        ground: WitnessDischargeGround,
    },
    WitnessOracleResolution {
        resolver: Option<String>,
        message: String,
    },
    WitnessVerification {
        witness_cid: String,
        check: WitnessVerificationCheck,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WitnessDischargeGround {
    PackageRecompute {
        error: String,
    },
    PackageBody {
        resolved_by: String,
        failed: usize,
        count: usize,
        failed_tests: Vec<String>,
        omitted: usize,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WitnessVerificationCheck {
    ComponentPlanFailed { reason: String },
    EnvelopeIntegrityMismatch,
    InvalidSignature,
    FailedOutcome,
    NoResolverDeclared,
    ReplayRefused { reason: String },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WitnessVerificationOutcome {
    Verified { resolved_by: String },
    Refused(VerifyEffect),
    BrokenOracle { reason: String },
}

impl VerifyEffect {
    pub fn to_legacy_boundary(&self) -> VerifyEffectBoundary {
        let verdict = match self {
            VerifyEffect::UnwitnessedDischarge { .. } => ObligationVerdict::Unsatisfied,
            VerifyEffect::SolverTimeout { .. } => ObligationVerdict::SolverTimeout,
            VerifyEffect::MissingProvenanceKind { .. }
            | VerifyEffect::NoSiblingToContradict { .. }
            | VerifyEffect::MissingIndependentKindWitness { .. }
            | VerifyEffect::ConsistencyNoSoundDischarger { .. }
            | VerifyEffect::SolverNoSoundDischarger { .. }
            | VerifyEffect::WitnessOracleResolution { .. }
            | VerifyEffect::WitnessVerification { .. } => ObligationVerdict::Refused,
        };
        let reason = self.to_string();
        let verification = match self {
            VerifyEffect::MissingProvenanceKind { property_name, .. } => Some(json!({
                "kind": "consistency-provenance-kind",
                "property": property_name,
                "finalVerdict": verdict.as_str(),
                "reason": reason,
            })),
            VerifyEffect::UnwitnessedDischarge { ground, .. } => match ground {
                WitnessDischargeGround::PackageRecompute { .. } => Some(json!({
                    "kind": "witness",
                    "witnessed": false,
                    "verdict": verdict.as_str(),
                    "reason": reason,
                })),
                WitnessDischargeGround::PackageBody {
                    resolved_by,
                    failed,
                    count,
                    failed_tests,
                    ..
                } => Some(json!({
                    "kind": "witness",
                    "witnessed": false,
                    "verdict": verdict.as_str(),
                    "resolvedBy": resolved_by,
                    "outcomes": count,
                    "failed": failed,
                    "failedTests": failed_tests,
                    "reason": reason,
                })),
            },
            VerifyEffect::NoSiblingToContradict { .. }
            | VerifyEffect::MissingIndependentKindWitness { .. }
            | VerifyEffect::ConsistencyNoSoundDischarger { .. }
            | VerifyEffect::SolverTimeout { .. }
            | VerifyEffect::SolverNoSoundDischarger { .. }
            | VerifyEffect::WitnessOracleResolution { .. }
            | VerifyEffect::WitnessVerification { .. } => None,
        };
        VerifyEffectBoundary {
            verdict,
            reason: self.to_string(),
            verification,
        }
    }

    pub fn legacy_solver_reason(&self) -> Option<&'static str> {
        match self {
            VerifyEffect::NoSiblingToContradict { .. } => Some(NO_SIBLING_TO_CONTRADICT_REASON),
            VerifyEffect::MissingIndependentKindWitness { .. } => {
                Some(MISSING_INDEPENDENT_KIND_REASON)
            }
            VerifyEffect::MissingProvenanceKind { .. }
            | VerifyEffect::ConsistencyNoSoundDischarger { .. }
            | VerifyEffect::SolverTimeout { .. }
            | VerifyEffect::SolverNoSoundDischarger { .. }
            | VerifyEffect::UnwitnessedDischarge { .. }
            | VerifyEffect::WitnessOracleResolution { .. }
            | VerifyEffect::WitnessVerification { .. } => None,
        }
    }
}

impl WitnessVerificationOutcome {
    pub fn is_ok(&self) -> bool {
        match self {
            WitnessVerificationOutcome::Verified { .. } => true,
            WitnessVerificationOutcome::Refused(_)
            | WitnessVerificationOutcome::BrokenOracle { .. } => false,
        }
    }

    pub fn verdict(&self) -> &'static str {
        match self {
            WitnessVerificationOutcome::Verified { .. } => "verified",
            WitnessVerificationOutcome::Refused(_) => "refused",
            WitnessVerificationOutcome::BrokenOracle { .. } => "broken-oracle",
        }
    }

    pub fn reason(&self) -> String {
        match self {
            WitnessVerificationOutcome::Verified { resolved_by } => {
                format!("oracle resolved via {resolved_by}; rust recomputed the CID and it matched")
            }
            WitnessVerificationOutcome::Refused(effect) => effect.to_string(),
            WitnessVerificationOutcome::BrokenOracle { reason } => reason.clone(),
        }
    }
}

impl fmt::Display for VerifyEffect {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            VerifyEffect::MissingProvenanceKind {
                property_name,
                detail,
                ..
            } => write!(
                f,
                "consistency check refused: contract `{property_name}` lacks required provenance KIND for ambient testimony ({detail})"
            ),
            VerifyEffect::NoSiblingToContradict { property_name, .. } => {
                write!(f, "{NO_SIBLING_TO_CONTRADICT_REASON} `{property_name}`")
            }
            VerifyEffect::MissingIndependentKindWitness { property_name, .. } => {
                write!(f, "{MISSING_INDEPENDENT_KIND_REASON} `{property_name}`")
            }
            VerifyEffect::ConsistencyNoSoundDischarger {
                property_name,
                solver_reason,
            } => write!(
                f,
                "refused: no sound discharger `{property_name}` [{solver_reason}]"
            ),
            VerifyEffect::SolverTimeout {
                property_name,
                solver_reason,
            } => write!(
                f,
                "solver-timeout: solver exceeded host timeout for `{property_name}` [{solver_reason}]"
            ),
            VerifyEffect::SolverNoSoundDischarger { solver_name } => {
                write!(f, "solver '{solver_name}' refused: no sound discharger")
            }
            VerifyEffect::UnwitnessedDischarge { ground, .. } => write!(f, "{ground}"),
            VerifyEffect::WitnessOracleResolution { message, .. } => {
                write!(f, "oracle refused resolution: {message}")
            }
            VerifyEffect::WitnessVerification { check, .. } => write!(f, "{check}"),
        }
    }
}

impl fmt::Display for WitnessDischargeGround {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            WitnessDischargeGround::PackageRecompute { error } => {
                write!(f, "witness REFUSED by rust package recompute: {error}")
            }
            WitnessDischargeGround::PackageBody {
                resolved_by,
                failed,
                count,
                failed_tests,
                omitted,
            } => {
                let more = if *omitted > 0 {
                    format!(" (+{omitted} more)")
                } else {
                    String::new()
                };
                write!(
                    f,
                    "witness REFUSED by rust package body: bundle reproduced via {resolved_by}; {failed}/{count} outcomes failed: {}{more}",
                    failed_tests.join(", ")
                )
            }
        }
    }
}

impl fmt::Display for WitnessVerificationCheck {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            WitnessVerificationCheck::ComponentPlanFailed { reason } => {
                write!(f, "component plan failed while resolving witnesses: {reason}")
            }
            WitnessVerificationCheck::EnvelopeIntegrityMismatch => write!(
                f,
                "envelope integrity: body witness_cid disagrees with header metadata"
            ),
            WitnessVerificationCheck::InvalidSignature => {
                write!(f, "signature invalid -- cannot trust the mark")
            }
            WitnessVerificationCheck::FailedOutcome => {
                write!(f, "witness records a FAILED run -- not a discharge")
            }
            WitnessVerificationCheck::NoResolverDeclared => write!(
                f,
                "no witness resolver declared (manifest `resolve_witness_command`); cannot resolve the body to recompute"
            ),
            WitnessVerificationCheck::ReplayRefused { reason } => f.write_str(reason),
        }
    }
}
