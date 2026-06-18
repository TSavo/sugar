// SPDX-License-Identifier: Apache-2.0
//
// Stage 7: report. Aggregate per-callsite verdicts plus load-error
// rows. Mirrors .../verifier/report.cpp.

use serde_json::Value as Json;

use crate::types::{CallSite, LoadError, ObligationVerdict, Report, ReportRow};

pub fn add_callsite(cs: &CallSite, verdict: ObligationVerdict, reason: &str, r: &mut Report) {
    add_callsite_with_discharge(cs, verdict, reason, None, None, r);
}

pub fn add_callsite_with_method(
    cs: &CallSite,
    verdict: ObligationVerdict,
    reason: &str,
    discharge_method: Option<String>,
    r: &mut Report,
) {
    add_callsite_with_discharge(cs, verdict, reason, discharge_method, None, r);
}

pub fn add_callsite_with_discharge(
    cs: &CallSite,
    verdict: ObligationVerdict,
    reason: &str,
    discharge_method: Option<String>,
    body_discharge_tier: Option<String>,
    r: &mut Report,
) {
    r.total_callsites += 1;
    r.rows.push(ReportRow {
        callsite: cs.clone(),
        status: verdict.as_str().to_string(),
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
        property_cid: contract_cid.to_string(),
        ..CallSite::default()
    };
    r.rows.push(ReportRow {
        callsite: cs,
        status: verdict.as_str().to_string(),
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
        property_cid: contract_cid.to_string(),
        ..CallSite::default()
    };
    r.rows.push(ReportRow {
        callsite: cs,
        status: verdict.as_str().to_string(),
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

#[cfg(test)]
mod tests {
    use super::*;

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
}
