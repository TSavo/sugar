// SPDX-License-Identifier: Apache-2.0
//
// Stage 7: report. Aggregate per-callsite verdicts plus load-error
// rows. Mirrors .../verifier/report.cpp.

use serde_json::Value as Json;

use crate::types::{
    CallSite, LoadError, MementoCid, MementoPool, ObligationVerdict, Report, ReportRow,
    ToolchainPlanReport,
};

pub fn add_callsite(cs: &CallSite, verdict: ObligationVerdict, reason: &str, r: &mut Report) {
    add_callsite_with_discharge(cs.clone(), verdict, reason, None, None, r);
}

pub fn add_callsite_with_method(
    cs: &CallSite,
    verdict: ObligationVerdict,
    reason: &str,
    discharge_method: Option<String>,
    r: &mut Report,
) {
    add_callsite_with_discharge(cs.clone(), verdict, reason, discharge_method, None, r);
}

pub fn add_callsite_with_discharge(
    cs: CallSite,
    verdict: ObligationVerdict,
    reason: &str,
    discharge_method: Option<String>,
    body_discharge_tier: Option<String>,
    r: &mut Report,
) {
    r.total_callsites += 1;
    r.rows.push(ReportRow {
        callsite: cs,
        status: verdict,
        reason: reason.to_string(),
        discharge_method,
        body_discharge_tier,
        verification: None,
    });
    if verdict == ObligationVerdict::Discharged {
        r.discharged += 1;
    } else if verdict == ObligationVerdict::Refused {
        // A refusal is the trichotomy's third arm: a named, honest "no sound
        // discharger for this obligation". It is NOT a discharge (no false pass)
        // and NOT a violation (it does not redden the gate). The row stays visible
        // (status `refused` + reason); the scoreboard simply does not score it
        // against correctness, because we never claimed to decide it.
        r.refused += 1;
    } else {
        r.violations += 1;
    }
}

/// Add a contract self-post verification row. A self-post obligation
/// (`post[result := body]`, proving a contract's own body-derived post
/// reflexively, `body == body`) is a contract-level self-consistency
/// check, NOT a call site. It MUST NOT count toward `total_callsites`
/// (which counts only bridge/call-site obligations), so we synthesize a
/// minimal `CallSite` for the row but deliberately do NOT increment
/// `total_callsites`. The row still flows into `discharged`/`violations`
/// (a failing self-post must still fail the run) and remains visible in
/// the discharge split's `reflexive` bucket (computed by iterating
/// `rows`), so reflexive self-post coverage stays honest in the
/// scoreboard without being conflated with real call sites.
pub fn add_self_post(contract_cid: &str, verdict: ObligationVerdict, reason: &str, r: &mut Report) {
    add_self_post_with_method(contract_cid, verdict, reason, None, r);
}

pub fn add_self_post_with_method(
    contract_cid: &str,
    verdict: ObligationVerdict,
    reason: &str,
    discharge_method: Option<String>,
    r: &mut Report,
) {
    // NOTE: intentionally NO `r.total_callsites += 1` here. A self-post is
    // a contract self-consistency obligation, not a call site (#fix/self-post-not-a-callsite).
    let cs = CallSite {
        property_name: format!("self-post:{contract_cid}"),
        property_cid: MementoCid::try_parse(contract_cid.to_string()).ok(),
        ..CallSite::default()
    };
    r.rows.push(ReportRow {
        callsite: cs,
        status: verdict,
        reason: reason.to_string(),
        discharge_method,
        body_discharge_tier: None,
        verification: None,
    });
    if verdict == ObligationVerdict::Discharged {
        r.discharged += 1;
    } else if verdict == ObligationVerdict::Refused {
        // A refusal is the trichotomy's third arm: a named, honest "no sound
        // discharger for this obligation". It is NOT a discharge (no false pass)
        // and NOT a violation (it does not redden the gate). The row stays visible
        // (status `refused` + reason); the scoreboard simply does not score it
        // against correctness, because we never claimed to decide it.
        r.refused += 1;
    } else {
        r.violations += 1;
    }
}

/// Add a test-assertion consistency row (receipt 1). Like a self-post, this
/// is a contract self-consistency obligation, NOT a call site, so it does not
/// increment `total_callsites`. A `Discharged` verdict here is a CONSISTENCY
/// claim ("test assertions mutually consistent about callsite X"), not a
/// code-correctness claim; a non-`Discharged` verdict (contradictory inv, or
/// an undecidable/ill-sorted encoding STOP) drives a visible violation so the
/// contradiction is surfaced loudly rather than swallowed.
pub fn add_consistency(
    contract_cid: &str,
    property_name: &str,
    verdict: ObligationVerdict,
    reason: &str,
    r: &mut Report,
) {
    add_consistency_with_verification(contract_cid, property_name, verdict, reason, None, r);
}

pub fn add_consistency_with_verification(
    contract_cid: &str,
    property_name: &str,
    verdict: ObligationVerdict,
    reason: &str,
    verification: Option<Json>,
    r: &mut Report,
) {
    let cs = CallSite {
        property_name: format!("consistency:{property_name}"),
        property_cid: MementoCid::try_parse(contract_cid.to_string()).ok(),
        ..CallSite::default()
    };
    r.rows.push(ReportRow {
        callsite: cs,
        status: verdict,
        reason: reason.to_string(),
        discharge_method: Some("consistency".to_string()),
        body_discharge_tier: None,
        verification,
    });
    if verdict == ObligationVerdict::Discharged {
        r.discharged += 1;
    } else if verdict == ObligationVerdict::Refused {
        // A refusal is the trichotomy's third arm: a named, honest "no sound
        // discharger for this obligation". It is NOT a discharge (no false pass)
        // and NOT a violation (it does not redden the gate). The row stays visible
        // (status `refused` + reason); the scoreboard simply does not score it
        // against correctness, because we never claimed to decide it.
        r.refused += 1;
    } else {
        r.violations += 1;
    }
}

pub fn add_load_errors(errs: &[LoadError], r: &mut Report) {
    r.load_errors = errs.to_vec();
}

pub fn add_toolchain_plans(pool: &MementoPool, r: &mut Report) {
    r.toolchain_plans.extend(toolchain_plan_reports(pool));
}

pub fn toolchain_plan_reports(pool: &MementoPool) -> Vec<ToolchainPlanReport> {
    let mut witness_outputs = Vec::new();
    for (cid, member) in pool.witness_memento_members() {
        let actual = member
            .field("actualOutputCids")
            .and_then(json_str_vec)
            .or_else(|| member.field("actual_output_cids").and_then(json_str_vec))
            .unwrap_or_default();
        if actual.is_empty() {
            continue;
        }
        let plan_cid = member
            .field("planCid")
            .and_then(|v| v.as_str().map(str::to_string))
            .or_else(|| {
                member
                    .field("plan_cid")
                    .and_then(|v| v.as_str().map(str::to_string))
            });
        witness_outputs.push(WitnessOutputs {
            memento_cid: cid.to_string(),
            plan_cid,
            actual,
        });
    }

    let mut rows = Vec::new();
    for (cid, member) in pool.plan_memento_members() {
        let plan_cid = member
            .field("planCid")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let expected = member
            .field("expectedOutputCids")
            .and_then(json_str_vec)
            .or_else(|| member.field("expected_output_cids").and_then(json_str_vec))
            .unwrap_or_default();
        let plan_specific: Vec<&WitnessOutputs> = witness_outputs
            .iter()
            .filter(|witness| witness.plan_cid.as_deref() == Some(plan_cid.as_str()))
            .collect();
        let unscoped: Vec<&WitnessOutputs> = witness_outputs
            .iter()
            .filter(|witness| witness.plan_cid.is_none())
            .collect();
        let decision = toolchain_plan_decision(&expected, &plan_specific, &unscoped);
        rows.push(ToolchainPlanReport {
            plan_memento_cid: cid.to_string(),
            plan_cid,
            status: decision.status,
            reason: decision.reason,
            expected_output_cids: expected,
            witness_memento_cid: decision.witness_memento_cid,
            actual_output_cids: decision.actual_output_cids,
        });
    }
    rows.sort_by(|a, b| a.plan_memento_cid.cmp(&b.plan_memento_cid));
    rows
}

struct WitnessOutputs {
    memento_cid: String,
    plan_cid: Option<String>,
    actual: Vec<String>,
}

struct ToolchainPlanDecision {
    status: String,
    reason: String,
    witness_memento_cid: Option<String>,
    actual_output_cids: Vec<String>,
}

fn toolchain_plan_decision(
    expected: &[String],
    plan_specific: &[&WitnessOutputs],
    unscoped: &[&WitnessOutputs],
) -> ToolchainPlanDecision {
    if !plan_specific.is_empty() {
        if let Some(witness) = matching_witness(expected, plan_specific) {
            return confirmed(
                witness,
                "plan expected output CIDs match a plan-scoped witness-memento's actual output CIDs",
            );
        }
        return refuted(
            plan_specific[0],
            "plan expected output CIDs do not match loaded plan-scoped witness-memento actual output CIDs",
        );
    }

    if let Some(witness) = unscoped.first() {
        return declared_with_witness(
            witness,
            "toolchain output witness is missing planCid; ignored for plan settlement because toolchain witnesses must be scoped to a plan CID",
        );
    }

    ToolchainPlanDecision {
        status: "declared".to_string(),
        reason: "plan is pinned in the proof envelope; no matching witness-memento was loaded"
            .to_string(),
        witness_memento_cid: None,
        actual_output_cids: Vec::new(),
    }
}

fn matching_witness<'a>(
    expected: &[String],
    witnesses: &[&'a WitnessOutputs],
) -> Option<&'a WitnessOutputs> {
    witnesses
        .iter()
        .copied()
        .find(|witness| witness.actual.as_slice() == expected)
}

fn confirmed(witness: &WitnessOutputs, reason: &str) -> ToolchainPlanDecision {
    decision("confirmed", reason, Some(witness), witness.actual.clone())
}

fn refuted(witness: &WitnessOutputs, reason: &str) -> ToolchainPlanDecision {
    decision("refuted", reason, Some(witness), witness.actual.clone())
}

fn declared_with_witness(witness: &WitnessOutputs, reason: &str) -> ToolchainPlanDecision {
    decision("declared", reason, Some(witness), witness.actual.clone())
}

fn decision(
    status: &str,
    reason: &str,
    witness: Option<&WitnessOutputs>,
    actual_output_cids: Vec<String>,
) -> ToolchainPlanDecision {
    ToolchainPlanDecision {
        status: status.to_string(),
        reason: reason.to_string(),
        witness_memento_cid: witness.map(|witness| witness.memento_cid.clone()),
        actual_output_cids,
    }
}

fn json_str_vec(val: &Json) -> Option<Vec<String>> {
    Some(
        val.as_array()?
            .iter()
            .filter_map(|value| value.as_str().map(str::to_string))
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn cid(seed: &str) -> MementoCid {
        MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(seed.as_bytes()))
            .expect("test CID must parse")
    }

    fn cid_string(seed: &str) -> String {
        cid(seed).to_string()
    }

    #[test]
    fn self_post_does_not_count_as_a_callsite() {
        let mut r = Report::default();
        let cs = CallSite {
            bridge_ir_name: "bridge.demo".into(),
            ..CallSite::default()
        };
        // One real call site, then one self-post obligation.
        add_callsite_with_method(&cs, ObligationVerdict::Discharged, "ok", None, &mut r);
        add_self_post_with_method(
            "blake3-512:contract",
            ObligationVerdict::Discharged,
            "reflexive self-post",
            Some("reflexive".into()),
            &mut r,
        );

        // The self-post MUST NOT inflate the call-site count: only the
        // genuine bridge obligation counts as a call site.
        assert_eq!(
            r.total_callsites, 1,
            "self-post must not count as a callsite"
        );
        // But it stays visible as a discharged row in the scoreboard.
        assert_eq!(r.discharged, 2, "self-post still counts toward discharged");
        assert_eq!(r.rows.len(), 2, "self-post row must remain visible");
        assert!(
            r.rows
                .iter()
                .any(|row| row.callsite.property_name == "self-post:blake3-512:contract"),
            "self-post row must be present for the discharge split to see it"
        );
    }

    #[test]
    fn failing_self_post_still_drives_a_violation() {
        let mut r = Report::default();
        add_self_post_with_method(
            "blake3-512:bad",
            ObligationVerdict::Unsatisfied,
            "internally inconsistent contract",
            None,
            &mut r,
        );
        // Excluding self-posts from the callsite count must NOT turn a
        // failing self-post into a green run.
        assert_eq!(r.total_callsites, 0, "self-post is not a callsite");
        assert_eq!(
            r.violations, 1,
            "a failing self-post must still fail the run"
        );
    }

    #[test]
    fn toolchain_plan_without_witness_is_declared() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:out"]
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, "declared");
        assert_eq!(rows[0].plan_memento_cid, cid_string("plan-member"));
        assert_eq!(rows[0].plan_cid, "blake3-512:plan-letter");
        assert_eq!(rows[0].expected_output_cids, vec!["blake3-512:out"]);
        assert!(rows[0].witness_memento_cid.is_none());
    }

    #[test]
    fn toolchain_plan_matching_witness_pointer_is_confirmed() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:out"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "planCid": "blake3-512:plan-letter",
                    "actualOutputCids": ["blake3-512:out"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, "confirmed");
        assert_eq!(
            rows[0].witness_memento_cid.as_deref(),
            Some(cid_string("witness-member").as_str())
        );
        assert_eq!(rows[0].actual_output_cids, vec!["blake3-512:out"]);
    }

    #[test]
    fn toolchain_plan_mismatched_witness_pointer_is_refuted() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:expected"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "planCid": "blake3-512:plan-letter",
                    "actualOutputCids": ["blake3-512:actual"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, "refuted");
        assert_eq!(rows[0].expected_output_cids, vec!["blake3-512:expected"]);
        assert_eq!(rows[0].actual_output_cids, vec!["blake3-512:actual"]);
    }

    #[test]
    fn toolchain_plan_unscoped_matching_witness_is_declared_not_confirmed() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:out"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "actualOutputCids": ["blake3-512:out"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(
            rows[0].status, "declared",
            "a toolchain output witness without planCid must not confirm any plan"
        );
        assert_eq!(
            rows[0].witness_memento_cid.as_deref(),
            Some(cid_string("witness-member").as_str())
        );
        assert_eq!(rows[0].actual_output_cids, vec!["blake3-512:out"]);
        assert!(
            rows[0].reason.contains("missing planCid"),
            "report should say the toolchain witness was ignored because it is unscoped"
        );
    }

    #[test]
    fn toolchain_plan_unscoped_mismatched_witness_is_declared_not_refuted() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:expected"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "actualOutputCids": ["blake3-512:actual"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(
            rows[0].status, "declared",
            "unscoped witnesses must not refute a plan"
        );
        assert_eq!(
            rows[0].witness_memento_cid.as_deref(),
            Some(cid_string("witness-member").as_str())
        );
        assert_eq!(rows[0].actual_output_cids, vec!["blake3-512:actual"]);
        assert!(
            rows[0].reason.contains("missing planCid"),
            "report should make the missing scope visible"
        );
    }

    #[test]
    fn toolchain_plan_ignores_witness_scoped_to_other_plan() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:expected"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "planCid": "blake3-512:other-plan-letter",
                    "actualOutputCids": ["blake3-512:actual"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(
            rows[0].status, "declared",
            "a witness scoped to another plan is not evidence for this plan"
        );
        assert!(rows[0].witness_memento_cid.is_none());
    }
}
