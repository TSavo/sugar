// SPDX-License-Identifier: Apache-2.0
//
// Pretty + JSON formatting for the verifier `Report`.

use owo_colors::OwoColorize;
use serde_json::{json, Value as Json};
use sugar_verifier::superposition::{reports_from_report, Strength, SuperpositionReport};
use sugar_verifier::{LoadError, Report, ReportRow};

pub fn report_to_json(r: &Report) -> Json {
    let rows: Vec<Json> = r.rows.iter().map(row_to_json).collect();
    let load_errors: Vec<Json> = r.load_errors.iter().map(load_error_to_json).collect();
    let call_edges: Vec<Json> = r
        .call_edges
        .iter()
        .map(|ce| {
            json!({
                "sourceContractCid": ce.source_contract_cid,
                "targetContractCid": ce.target_contract_cid,
                "file": ce.file,
            })
        })
        .collect();
    json!({
        "totalCallsites": r.total_callsites,
        "discharged": r.discharged,
        "violations": r.violations,
        "refused": r.refused,
        "dischargeSplit": discharge_split_to_json(r),
        "rows": rows,
        "loadErrors": load_errors,
        "callEdges": call_edges,
        // Per-symbol superposition verdict: the N z3 compiles this run already
        // performed, folded by callee symbol. strength = surviving universe count.
        "superposition": superposition_to_json(r),
    })
}

fn superposition_to_json(r: &Report) -> Json {
    let reports = reports_from_report(r);
    let entries: Vec<Json> = reports.iter().map(superposition_report_to_json).collect();
    json!({
        "symbols": reports.len(),
        "strong": reports.iter().filter(|s| s.strength == Strength::Strong).count(),
        "weak": reports.iter().filter(|s| s.strength == Strength::Weak).count(),
        "undecidable": reports.iter().filter(|s| s.strength == Strength::Undecidable).count(),
        "reports": entries,
    })
}

fn superposition_report_to_json(s: &SuperpositionReport) -> Json {
    json!({
        "symbol": s.symbol,
        "strength": s.strength.tag(),
        "verdict": s.verdict,
        "levers": s.levers,
        "licensing": s.licensing,
        "findings": s.findings,
        "cid": s.cid,
    })
}

fn row_to_json(row: &ReportRow) -> Json {
    json!({
        "bridge": row.callsite.bridge_ir_name,
        "targetCid": row.callsite.bridge_target_cid,
        "sourceLayer": row.callsite.bridge_source_layer,
        "targetLayer": row.callsite.bridge_target_layer,
        "property": row.callsite.property_name,
        "propertyCid": row.callsite.property_cid,
        "status": row.status,
        "reason": row.reason,
        "dischargeMethod": row.discharge_method,
        "bodyDischargeTier": row.body_discharge_tier,
        "file": row.callsite.file,
        "line": row.callsite.line,
        "callee": row.callsite.callee,
        "callsiteBundleCid": row.callsite.callsite_bundle_cid,
        "panicSite": row.callsite.panic_site,
    })
}

fn discharge_split_to_json(r: &Report) -> Json {
    let mut panic_safe = 0usize;
    let mut reflexive = 0usize;
    let mut solver_substantive = 0usize;
    let mut vacuous = 0usize;
    let mut hash_tier = 0usize;
    let mut undecidable = 0usize;
    let mut false_pass = 0usize;

    for row in &r.rows {
        if row.status != "discharged" {
            undecidable += 1;
            continue;
        }
        let method = row.discharge_method.as_deref();
        if row.callsite.panic_site && method != Some("panic-safe") {
            false_pass += 1;
            continue;
        }
        match method {
            Some("panic-safe") if row.callsite.panic_site => panic_safe += 1,
            Some("panic-safe") => solver_substantive += 1,
            Some("reflexive") => reflexive += 1,
            Some("solver-substantive") => solver_substantive += 1,
            Some("vacuous") => vacuous += 1,
            Some("hash-tier") => hash_tier += 1,
            _ => solver_substantive += 1,
        }
    }

    json!({
        "panicSafe": panic_safe,
        "reflexive": reflexive,
        "solverSubstantive": solver_substantive,
        "vacuous": vacuous,
        "hashTier": hash_tier,
        "undecidable": undecidable,
        "falsePass": false_pass,
    })
}

fn load_error_to_json(e: &LoadError) -> Json {
    json!({
        "proofPath": e.proof_path,
        "reason": e.reason,
    })
}

pub fn print_report_pretty(r: &Report, quiet: bool) {
    if !quiet {
        println!("{}", "Sugar verifier report".bold());
        println!("  total callsites : {}", r.total_callsites);
        println!("  discharged      : {}", r.discharged.to_string().green());
        println!(
            "  violations      : {}",
            if r.violations == 0 {
                r.violations.to_string().green().to_string()
            } else {
                r.violations.to_string().red().to_string()
            }
        );
        println!(
            "  load errors     : {}",
            if r.load_errors.is_empty() {
                "0".green().to_string()
            } else {
                r.load_errors.len().to_string().red().to_string()
            }
        );
        println!();
        for row in &r.rows {
            let status_pretty = match row.status.as_str() {
                "discharged" => "discharged".green().to_string(),
                "unsatisfied" => "unsatisfied".red().to_string(),
                "undecidable" => "undecidable".yellow().to_string(),
                other => other.to_string(),
            };
            println!(
                "  [{}] {}  ({} -> {})",
                status_pretty,
                row.callsite.bridge_ir_name,
                row.callsite.bridge_source_layer,
                row.callsite.bridge_target_layer
            );
            if !row.reason.is_empty() {
                println!("      reason: {}", row.reason);
            }
            if let Some(tier) = &row.body_discharge_tier {
                println!("      body tier: {}", tier);
            }
        }
        let superpositions = reports_from_report(r);
        if !superpositions.is_empty() {
            println!();
            println!("{}", "Superposition (strength per symbol):".bold());
            for s in &superpositions {
                let strength_pretty = match s.strength {
                    Strength::Strong => s.strength.tag().green().to_string(),
                    Strength::Weak => s.strength.tag().yellow().to_string(),
                    Strength::Undecidable => s.strength.tag().red().to_string(),
                };
                println!("  [{}] {}", strength_pretty, s.symbol);
                if !s.findings.is_empty() {
                    println!("      findings: {}", s.findings.len());
                }
                if !s.levers.is_empty() {
                    println!("      collapse: {}", s.levers.join(" | "));
                }
            }
        }
        if !r.load_errors.is_empty() {
            println!();
            println!("{}", "Load errors:".red().bold());
            for e in &r.load_errors {
                println!("  {}: {}", e.proof_path, e.reason);
            }
        }
        if !r.call_edges.is_empty() {
            println!();
            println!("{}", "Call edges:".dimmed());
            for ce in &r.call_edges {
                println!(
                    "  {} -> {}  ({})",
                    ce.source_contract_cid.chars().take(32).collect::<String>(),
                    ce.target_contract_cid.chars().take(32).collect::<String>(),
                    ce.file
                );
            }
        }
    }
}

/// Decide an exit code from a proof report. A load-bearing `prove` run must
/// have checked at least one callsite; zero-callsite reports are vacuous.
pub fn report_exit_code(r: &Report) -> u8 {
    if r.violations > 0 || !r.load_errors.is_empty() || r.total_callsites == 0 {
        crate::EXIT_VERIFY_FAIL
    } else {
        crate::EXIT_OK
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_verifier::{CallSite, Report, ReportRow};

    #[test]
    fn empty_report_is_not_a_successful_proof() {
        let r = Report::default();
        assert_eq!(report_exit_code(&r), crate::EXIT_VERIFY_FAIL);
        let j = report_to_json(&r);
        assert_eq!(j["totalCallsites"], 0);
        assert_eq!(j["violations"], 0);
    }

    #[test]
    fn report_with_violation_exits_fail() {
        let mut r = Report::default();
        r.violations = 1;
        assert_eq!(report_exit_code(&r), crate::EXIT_VERIFY_FAIL);
    }

    #[test]
    fn report_with_load_error_exits_fail() {
        let mut r = Report::default();
        r.load_errors.push(LoadError {
            proof_path: "x.proof".into(),
            reason: "bogus".into(),
        });
        assert_eq!(report_exit_code(&r), crate::EXIT_VERIFY_FAIL);
    }

    #[test]
    fn report_json_includes_body_discharge_tier() {
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "double".into(),
                ..CallSite::default()
            },
            status: "discharged".into(),
            reason: "ok".into(),
            discharge_method: Some("reflexive".into()),
            body_discharge_tier: Some("body-eq-same-callee".into()),
        });

        let j = report_to_json(&r);
        assert_eq!(j["rows"][0]["bodyDischargeTier"], "body-eq-same-callee");
    }

    #[test]
    fn report_json_includes_callsite_bundle_cid_when_present() {
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "method:unwrap".into(),
                callsite_bundle_cid: Some("blake3-512:caller-bundle".into()),
                panic_site: true,
                ..CallSite::default()
            },
            status: "undecidable".into(),
            reason: "synthetic panic row".into(),
            discharge_method: None,
            body_discharge_tier: None,
        });

        let j = report_to_json(&r);

        assert_eq!(
            j["rows"][0]["callsiteBundleCid"],
            "blake3-512:caller-bundle"
        );
    }

    #[test]
    fn report_json_nulls_callsite_bundle_cid_when_absent() {
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "method:unwrap".into(),
                panic_site: true,
                ..CallSite::default()
            },
            status: "undecidable".into(),
            reason: "synthetic panic row".into(),
            discharge_method: None,
            body_discharge_tier: None,
        });

        let j = report_to_json(&r);

        assert!(
            j["rows"][0]["callsiteBundleCid"].is_null(),
            "absent callsite bundle should serialize as null to match existing Option field style"
        );
    }
}
