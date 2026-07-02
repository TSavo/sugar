// SPDX-License-Identifier: Apache-2.0

use std::collections::BTreeMap;

use serde_json::{json, Value};

pub const FLOOR_RUNTIME_DOMAIN: &str = "floor";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FloorCheckMode {
    // These modes intentionally parallel DoctorMode without importing it.
    // Floor aggregation is a substrate runtime check; doctor and self-check
    // translate policy modes at the boundary.
    Structural,
    Strict,
    ReleaseGate,
}

impl FloorCheckMode {
    fn as_str(self) -> &'static str {
        match self {
            FloorCheckMode::Structural => "structural",
            FloorCheckMode::Strict => "strict",
            FloorCheckMode::ReleaseGate => "releaseGate",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FloorCheckStatus {
    Pass,
    Warn,
    Fail,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FloorCheckSeverity {
    Advisory,
    Hard,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FloorSignals {
    pub silently_dropped: u64,
    pub false_pass: u64,
    pub dropped_sites_count: usize,
    pub panic_census_unnamed_count: usize,
    pub total_callsites: u64,
    pub discharge_split_present: bool,
    pub monoid_fold_gaps_by_element_type: BTreeMap<String, u64>,
}

#[derive(Debug, Clone)]
pub struct FloorRuntimeCheck {
    pub id: String,
    pub name: String,
    pub status: FloorCheckStatus,
    pub severity: FloorCheckSeverity,
    pub domain: String,
    pub detail: String,
    pub evidence: Value,
}

impl FloorRuntimeCheck {
    fn new(
        id: impl Into<String>,
        name: impl Into<String>,
        status: FloorCheckStatus,
        severity: FloorCheckSeverity,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self {
            id: id.into(),
            name: name.into(),
            status,
            severity,
            domain: FLOOR_RUNTIME_DOMAIN.to_string(),
            detail: detail.into(),
            evidence,
        }
    }
}

pub fn floor_runtime_check(signals: FloorSignals, mode: FloorCheckMode) -> Vec<FloorRuntimeCheck> {
    vec![
        silently_dropped_check(&signals, mode),
        false_pass_check(&signals, mode),
        dropped_sites_check(&signals, mode),
        panic_census_named_check(&signals, mode),
        monoid_fold_gap_check(&signals, mode),
        total_callsites_check(&signals, mode),
        discharge_split_check(&signals, mode),
    ]
}

fn silently_dropped_check(signals: &FloorSignals, mode: FloorCheckMode) -> FloorRuntimeCheck {
    hard_zero_check(
        "floor.silently_dropped.zero",
        "floor-silently-dropped-zero",
        signals.silently_dropped,
        "silentlyDropped",
        mode,
    )
}

fn false_pass_check(signals: &FloorSignals, mode: FloorCheckMode) -> FloorRuntimeCheck {
    hard_zero_check(
        "floor.false_pass.zero",
        "floor-false-pass-zero",
        signals.false_pass,
        "falsePass",
        mode,
    )
}

fn dropped_sites_check(signals: &FloorSignals, mode: FloorCheckMode) -> FloorRuntimeCheck {
    let count = signals.dropped_sites_count as u64;
    hard_zero_check(
        "floor.dropped_sites.empty",
        "floor-dropped-sites-empty",
        count,
        "droppedSites",
        mode,
    )
}

fn panic_census_named_check(signals: &FloorSignals, mode: FloorCheckMode) -> FloorRuntimeCheck {
    let count = signals.panic_census_unnamed_count;
    // Naming coverage is advisory until the exhaustive coverage slice lands.
    // The hard v1 floor is no silent drops and no false passes; unnamed
    // unproven rows stay loud without blocking today's honest self-check.
    let (status, detail) = if count == 0 {
        (
            FloorCheckStatus::Pass,
            "panicCensus has no unnamed unproven rows".to_string(),
        )
    } else {
        (
            FloorCheckStatus::Warn,
            format!("panicCensus has {count} unnamed unproven row(s)"),
        )
    };
    FloorRuntimeCheck::new(
        "floor.panic_census.named",
        "floor-panic-census-named",
        status,
        FloorCheckSeverity::Advisory,
        detail,
        json!({
            "mode": mode.as_str(),
            "unnamedCount": count,
        }),
    )
}

fn monoid_fold_gap_check(signals: &FloorSignals, mode: FloorCheckMode) -> FloorRuntimeCheck {
    let total = signals
        .monoid_fold_gaps_by_element_type
        .values()
        .copied()
        .sum::<u64>();
    let (status, detail) = if total == 0 {
        (
            FloorCheckStatus::Pass,
            "MonoidFold has no CarrierEmbedding gaps".to_string(),
        )
    } else {
        let breakdown = signals
            .monoid_fold_gaps_by_element_type
            .iter()
            .map(|(element_type, count)| format!("{element_type}={count}"))
            .collect::<Vec<_>>()
            .join(", ");
        (
            FloorCheckStatus::Warn,
            format!("MonoidFold CarrierEmbedding gaps: {breakdown}"),
        )
    };
    FloorRuntimeCheck::new(
        "floor.monoid_fold.carrier_embedding_gaps",
        "floor-monoid-fold-carrier-embedding-gaps",
        status,
        FloorCheckSeverity::Advisory,
        detail,
        json!({
            "mode": mode.as_str(),
            "total": total,
            "byElementType": &signals.monoid_fold_gaps_by_element_type,
        }),
    )
}

fn total_callsites_check(signals: &FloorSignals, mode: FloorCheckMode) -> FloorRuntimeCheck {
    let total = signals.total_callsites;
    let (status, detail) = if total > 0 {
        (
            FloorCheckStatus::Pass,
            format!("totalCallsites is nonzero ({total})"),
        )
    } else {
        (
            FloorCheckStatus::Fail,
            "totalCallsites is zero; refusing a vacuous proof".to_string(),
        )
    };
    FloorRuntimeCheck::new(
        "floor.total_callsites.nonzero",
        "floor-total-callsites-nonzero",
        status,
        FloorCheckSeverity::Hard,
        detail,
        json!({
            "mode": mode.as_str(),
            "totalCallsites": total,
        }),
    )
}

fn discharge_split_check(signals: &FloorSignals, mode: FloorCheckMode) -> FloorRuntimeCheck {
    let (status, detail) = if signals.discharge_split_present {
        (
            FloorCheckStatus::Pass,
            "dischargeSplit is present".to_string(),
        )
    } else {
        (
            FloorCheckStatus::Fail,
            "dischargeSplit is missing".to_string(),
        )
    };
    FloorRuntimeCheck::new(
        "floor.discharge_split.present",
        "floor-discharge-split-present",
        status,
        FloorCheckSeverity::Hard,
        detail,
        json!({
            "mode": mode.as_str(),
            "present": signals.discharge_split_present,
        }),
    )
}

fn hard_zero_check(
    id: &'static str,
    name: &'static str,
    value: u64,
    field: &'static str,
    mode: FloorCheckMode,
) -> FloorRuntimeCheck {
    let (status, detail) = if value == 0 {
        (FloorCheckStatus::Pass, format!("{field} is zero"))
    } else {
        (
            FloorCheckStatus::Fail,
            format!("{field} is {value}; hard floor requires zero"),
        )
    };
    FloorRuntimeCheck::new(
        id,
        name,
        status,
        FloorCheckSeverity::Hard,
        detail,
        json!({
            "mode": mode.as_str(),
            "field": field,
            "value": value,
        }),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn passing_signals() -> FloorSignals {
        FloorSignals {
            silently_dropped: 0,
            false_pass: 0,
            dropped_sites_count: 0,
            panic_census_unnamed_count: 0,
            total_callsites: 42,
            discharge_split_present: true,
            monoid_fold_gaps_by_element_type: BTreeMap::new(),
        }
    }

    fn check_by_id<'a>(checks: &'a [FloorRuntimeCheck], id: &str) -> &'a FloorRuntimeCheck {
        checks
            .iter()
            .find(|check| check.id == id)
            .unwrap_or_else(|| panic!("{id} check in {checks:#?}"))
    }

    #[test]
    fn silently_dropped_zero_passes() {
        let checks = floor_runtime_check(passing_signals(), FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.silently_dropped.zero");

        assert_eq!(check.status, FloorCheckStatus::Pass);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn false_pass_zero_passes() {
        let checks = floor_runtime_check(passing_signals(), FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.false_pass.zero");

        assert_eq!(check.status, FloorCheckStatus::Pass);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn dropped_sites_empty_passes() {
        let checks = floor_runtime_check(passing_signals(), FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.dropped_sites.empty");

        assert_eq!(check.status, FloorCheckStatus::Pass);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn panic_census_named_passes_when_no_unnamed_unproven_rows() {
        let checks = floor_runtime_check(passing_signals(), FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.panic_census.named");

        assert_eq!(check.status, FloorCheckStatus::Pass);
        assert_eq!(check.severity, FloorCheckSeverity::Advisory);
    }

    #[test]
    fn monoid_fold_gap_counts_warn_advisory_by_element_type() {
        let mut signals = passing_signals();
        signals
            .monoid_fold_gaps_by_element_type
            .insert("Duration".to_string(), 2);

        let checks = floor_runtime_check(signals, FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.monoid_fold.carrier_embedding_gaps");

        assert_eq!(check.status, FloorCheckStatus::Warn);
        assert_eq!(check.severity, FloorCheckSeverity::Advisory);
        assert_eq!(check.evidence["byElementType"]["Duration"], 2);
    }

    #[test]
    fn total_callsites_nonzero_passes() {
        let checks = floor_runtime_check(passing_signals(), FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.total_callsites.nonzero");

        assert_eq!(check.status, FloorCheckStatus::Pass);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn discharge_split_present_passes() {
        let checks = floor_runtime_check(passing_signals(), FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.discharge_split.present");

        assert_eq!(check.status, FloorCheckStatus::Pass);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn silently_dropped_positive_fails_hard() {
        let mut signals = passing_signals();
        signals.silently_dropped = 1;

        let checks = floor_runtime_check(signals, FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.silently_dropped.zero");

        assert_eq!(check.status, FloorCheckStatus::Fail);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn false_pass_positive_fails_hard() {
        let mut signals = passing_signals();
        signals.false_pass = 1;

        let checks = floor_runtime_check(signals, FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.false_pass.zero");

        assert_eq!(check.status, FloorCheckStatus::Fail);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn dropped_sites_nonempty_fails_hard() {
        let mut signals = passing_signals();
        signals.dropped_sites_count = 1;

        let checks = floor_runtime_check(signals, FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.dropped_sites.empty");

        assert_eq!(check.status, FloorCheckStatus::Fail);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn unnamed_panic_census_rows_warn_advisory_until_coverage_slice() {
        let mut signals = passing_signals();
        signals.panic_census_unnamed_count = 1;

        let checks = floor_runtime_check(signals, FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.panic_census.named");

        assert_eq!(check.status, FloorCheckStatus::Warn);
        assert_eq!(check.severity, FloorCheckSeverity::Advisory);
    }

    #[test]
    fn total_callsites_zero_fails_hard() {
        let mut signals = passing_signals();
        signals.total_callsites = 0;

        let checks = floor_runtime_check(signals, FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.total_callsites.nonzero");

        assert_eq!(check.status, FloorCheckStatus::Fail);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn discharge_split_missing_fails_hard() {
        let mut signals = passing_signals();
        signals.discharge_split_present = false;

        let checks = floor_runtime_check(signals, FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.discharge_split.present");

        assert_eq!(check.status, FloorCheckStatus::Fail);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn structural_false_pass_violation_still_fails_hard() {
        let mut signals = passing_signals();
        signals.false_pass = 1;

        let checks = floor_runtime_check(signals, FloorCheckMode::Structural);
        let check = check_by_id(&checks, "floor.false_pass.zero");

        assert_eq!(check.status, FloorCheckStatus::Fail);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn strict_false_pass_violation_fails_hard() {
        let mut signals = passing_signals();
        signals.false_pass = 1;

        let checks = floor_runtime_check(signals, FloorCheckMode::Strict);
        let check = check_by_id(&checks, "floor.false_pass.zero");

        assert_eq!(check.status, FloorCheckStatus::Fail);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn release_gate_false_pass_violation_fails_hard() {
        let mut signals = passing_signals();
        signals.false_pass = 1;

        let checks = floor_runtime_check(signals, FloorCheckMode::ReleaseGate);
        let check = check_by_id(&checks, "floor.false_pass.zero");

        assert_eq!(check.status, FloorCheckStatus::Fail);
        assert_eq!(check.severity, FloorCheckSeverity::Hard);
    }

    #[test]
    fn floor_runtime_check_accepts_projection_without_self_check_scoreboard() {
        let checks = floor_runtime_check(
            FloorSignals {
                silently_dropped: 0,
                false_pass: 0,
                dropped_sites_count: 0,
                panic_census_unnamed_count: 0,
                total_callsites: 1,
                discharge_split_present: true,
                monoid_fold_gaps_by_element_type: BTreeMap::new(),
            },
            FloorCheckMode::ReleaseGate,
        );

        assert_eq!(checks.len(), 7);
        assert!(checks
            .iter()
            .all(|check| check.status == FloorCheckStatus::Pass));
    }
}
