// SPDX-License-Identifier: Apache-2.0
//
// Pretty + JSON formatting for the verifier `Report`.

use owo_colors::OwoColorize;
use serde_json::{json, Value as Json};
use std::fmt::Write as _;
use sugar_verifier::superposition::{reports_from_report, Strength, SuperpositionReport};
use sugar_verifier::{LoadError, ObligationVerdict, Report, ReportRow};

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
    let toolchain_plans: Vec<Json> = r
        .toolchain_plans
        .iter()
        .map(|plan| {
            json!({
                "planMementoCid": plan.plan_memento_cid,
                "planCid": plan.plan_cid,
                "status": plan.status,
                "reason": plan.reason,
                "expectedOutputCids": plan.expected_output_cids,
                "witnessMementoCid": plan.witness_memento_cid,
                "actualOutputCids": plan.actual_output_cids,
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
        "toolchainPlans": toolchain_plans,
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
        "status": row.status.as_str(),
        "reason": row.reason,
        "dischargeMethod": row.discharge_method,
        "bodyDischargeTier": row.body_discharge_tier,
        "verification": row.verification.clone(),
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
        if row.status != ObligationVerdict::Discharged {
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

pub fn format_report_pretty(r: &Report, quiet: bool) -> String {
    let mut out = String::new();
    if !quiet {
        let _ = writeln!(out, "{}", "Sugar verifier report".bold());
        let _ = writeln!(out, "  total callsites : {}", r.total_callsites);
        let _ = writeln!(
            out,
            "  discharged      : {}",
            r.discharged.to_string().green()
        );
        let _ = writeln!(
            out,
            "  violations      : {}",
            if r.violations == 0 {
                r.violations.to_string().green().to_string()
            } else {
                r.violations.to_string().red().to_string()
            }
        );
        let _ = writeln!(
            out,
            "  load errors     : {}",
            if r.load_errors.is_empty() {
                "0".green().to_string()
            } else {
                r.load_errors.len().to_string().red().to_string()
            }
        );
        out.push('\n');
        for row in &r.rows {
            let status_pretty = match row.status {
                ObligationVerdict::Discharged => "discharged".green().to_string(),
                ObligationVerdict::Unsatisfied => "unsatisfied".red().to_string(),
                ObligationVerdict::Undecidable => "undecidable".yellow().to_string(),
                ObligationVerdict::Disagreement => "disagreement".to_string(),
                ObligationVerdict::Refused => "refused".to_string(),
            };
            let _ = writeln!(
                out,
                "  [{}] {}  ({} -> {})",
                status_pretty,
                row.callsite.bridge_ir_name,
                row.callsite.bridge_source_layer,
                row.callsite.bridge_target_layer
            );
            if !row.reason.is_empty() {
                let _ = writeln!(out, "      reason: {}", row.reason);
            }
            if let Some(tier) = &row.body_discharge_tier {
                let _ = writeln!(out, "      body tier: {}", tier);
            }
            if let Some(verification) = &row.verification {
                format_verification_detail(&mut out, verification);
            }
        }
        let superpositions = reports_from_report(r);
        if !superpositions.is_empty() {
            out.push('\n');
            let _ = writeln!(out, "{}", "Superposition (strength per symbol):".bold());
            for s in &superpositions {
                let strength_pretty = match s.strength {
                    Strength::Strong => s.strength.tag().green().to_string(),
                    Strength::Weak => s.strength.tag().yellow().to_string(),
                    Strength::Undecidable => s.strength.tag().red().to_string(),
                };
                let _ = writeln!(out, "  [{}] {}", strength_pretty, s.symbol);
                if !s.findings.is_empty() {
                    let _ = writeln!(out, "      findings: {}", s.findings.len());
                }
                if !s.levers.is_empty() {
                    let _ = writeln!(out, "      collapse: {}", s.levers.join(" | "));
                }
            }
        }
        if !r.load_errors.is_empty() {
            out.push('\n');
            let _ = writeln!(out, "{}", "Load errors:".red().bold());
            for e in &r.load_errors {
                let _ = writeln!(out, "  {}: {}", e.proof_path, e.reason);
            }
        }
        if !r.toolchain_plans.is_empty() {
            out.push('\n');
            let _ = writeln!(out, "{}", "Toolchain plans:".bold());
            for plan in &r.toolchain_plans {
                let status_pretty = match plan.status.as_str() {
                    "confirmed" => "confirmed".green().to_string(),
                    "refuted" => "refuted".red().to_string(),
                    "declared" => "declared".yellow().to_string(),
                    other => other.to_string(),
                };
                let _ = writeln!(out, "  [{}] plan {}", status_pretty, plan.plan_cid);
                let _ = writeln!(out, "      plan memento: {}", plan.plan_memento_cid);
                if let Some(witness) = &plan.witness_memento_cid {
                    let _ = writeln!(out, "      witness memento: {witness}");
                }
                let _ = writeln!(
                    out,
                    "      expected outputs: {}",
                    plan.expected_output_cids.len()
                );
                for cid in &plan.expected_output_cids {
                    let _ = writeln!(out, "        {cid}");
                }
                let _ = writeln!(
                    out,
                    "      actual outputs: {}",
                    plan.actual_output_cids.len()
                );
                for cid in &plan.actual_output_cids {
                    let _ = writeln!(out, "        {cid}");
                }
                if !plan.reason.is_empty() {
                    let _ = writeln!(out, "      reason: {}", plan.reason);
                }
            }
        }
        if !r.call_edges.is_empty() {
            out.push('\n');
            let _ = writeln!(out, "{}", "Call edges:".dimmed());
            for ce in &r.call_edges {
                let _ = writeln!(
                    out,
                    "  {} -> {}  ({})",
                    ce.source_contract_cid.chars().take(32).collect::<String>(),
                    ce.target_contract_cid.chars().take(32).collect::<String>(),
                    ce.file
                );
            }
        }
    }
    out
}

pub fn print_report_pretty(r: &Report, quiet: bool) {
    print!("{}", format_report_pretty(r, quiet));
}

fn compact_json(v: &Json) -> String {
    serde_json::to_string(v).unwrap_or_else(|_| v.to_string())
}

fn format_verification_detail(out: &mut String, v: &Json) {
    let kind = v
        .get("kind")
        .and_then(|x| x.as_str())
        .unwrap_or("verification");
    let _ = writeln!(out, "      verifier: {kind}");
    if let Some(cid) = v.get("checkedFormulaCid").and_then(|x| x.as_str()) {
        let _ = writeln!(out, "        checked formula (cid): {cid}");
    } else if let Some(formula) = v.get("checkedFormula") {
        // Legacy reports / fixtures that still carry the inline formula.
        let _ = writeln!(out, "        checked: {}", compact_json(formula));
    }
    if let Some(posts) = v.get("linkedPosts").and_then(|x| x.as_array()) {
        let _ = writeln!(out, "        linked posts: {}", posts.len());
        for post in posts {
            let source = post
                .get("sourceSymbol")
                .and_then(|x| x.as_str())
                .unwrap_or("<unknown>");
            let target = post
                .get("targetContractCid")
                .and_then(|x| x.as_str())
                .unwrap_or("<unknown>");
            let _ = writeln!(out, "          {} -> {}", source, target);
            if let Some(call) = post.get("call") {
                let _ = writeln!(out, "            call: {}", compact_json(call));
            }
            if let Some(instantiated) = post.get("instantiatedPost") {
                let _ = writeln!(out, "            post: {}", compact_json(instantiated));
            }
        }
    }
    if let Some(invs) = v.get("solverInvocations").and_then(|x| x.as_array()) {
        let _ = writeln!(out, "        solver invocations: {}", invs.len());
        for inv in invs {
            let solver = inv.get("solver").and_then(|x| x.as_str()).unwrap_or("?");
            let compiler = inv.get("compiler").and_then(|x| x.as_str()).unwrap_or("?");
            let verdict = inv.get("verdict").and_then(|x| x.as_str()).unwrap_or("?");
            let authoritative = inv
                .get("authoritative")
                .and_then(|x| x.as_bool())
                .unwrap_or(false);
            if let Some(ms) = inv.get("wallClockMs").and_then(|x| x.as_u64()) {
                let _ = writeln!(
                    out,
                    "          {solver} via {compiler}: {verdict} ({ms}ms, authoritative={authoritative})"
                );
            } else {
                let _ = writeln!(
                    out,
                    "          {solver} via {compiler}: {verdict} (authoritative={authoritative})"
                );
            }
            if let Some(cid) = inv.get("solverArtifactCid").and_then(|x| x.as_str()) {
                let _ = writeln!(out, "            artifact: {cid}");
            }
            if let Some(cid) = inv.get("solverInvocationCid").and_then(|x| x.as_str()) {
                let _ = writeln!(out, "            invocation: {cid}");
            }
            if let Some(cid) = inv.get("solverVendorMementoCid").and_then(|x| x.as_str()) {
                let _ = writeln!(out, "            vendor memento: {cid}");
            }
        }
    }
}

/// Decide an exit code from a proof report. A load-bearing `prove` run must
/// have checked at least one callsite or one contract-level obligation;
/// completely empty reports are vacuous.
pub fn report_exit_code(r: &Report) -> u8 {
    let toolchain_refuted = r
        .toolchain_plans
        .iter()
        .any(|plan| plan.status == "refuted");
    if r.violations > 0 || !r.load_errors.is_empty() || toolchain_refuted || r.rows.is_empty() {
        crate::EXIT_VERIFY_FAIL
    } else {
        crate::EXIT_OK
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_verifier::{CallSite, ObligationVerdict, Report, ReportRow, ToolchainPlanReport};

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
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("reflexive".into()),
            body_discharge_tier: Some("body-eq-same-callee".into()),
            verification: None,
        });

        let j = report_to_json(&r);
        assert_eq!(j["rows"][0]["bodyDischargeTier"], "body-eq-same-callee");
    }

    #[test]
    fn report_json_includes_verification_detail() {
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "consistency".into(),
                ..CallSite::default()
            },
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("consistency".into()),
            body_discharge_tier: None,
            verification: Some(json!({
                "kind": "consistency",
                "checkedFormula": { "kind": "literal", "value": true },
                "linkedPosts": [
                    {
                        "sourceSymbol": "call:enc",
                        "targetContractCid": "blake3-512:vendor",
                        "instantiatedPost": { "kind": "equals", "operands": [] }
                    }
                ],
                "solverInvocations": [
                    {
                        "solver": "cvc5",
                        "compiler": "smt-lib-v2.6",
                        "authoritative": true,
                        "verdict": "unsatisfied"
                    }
                ]
            })),
        });

        let j = report_to_json(&r);
        assert_eq!(j["rows"][0]["verification"]["kind"], "consistency");
        assert_eq!(
            j["rows"][0]["verification"]["solverInvocations"][0]["compiler"],
            "smt-lib-v2.6"
        );
        assert_eq!(
            j["rows"][0]["verification"]["linkedPosts"][0]["sourceSymbol"],
            "call:enc"
        );
    }

    #[test]
    fn report_json_includes_toolchain_plan_accounting() {
        let mut r = Report::default();
        r.toolchain_plans.push(ToolchainPlanReport {
            plan_memento_cid: "blake3-512:plan-member".into(),
            plan_cid: "blake3-512:plan-letter".into(),
            status: "declared".into(),
            reason: "plan is pinned".into(),
            expected_output_cids: vec!["blake3-512:out".into()],
            witness_memento_cid: None,
            actual_output_cids: Vec::new(),
        });

        let j = report_to_json(&r);

        assert_eq!(
            j["toolchainPlans"][0]["planMementoCid"],
            "blake3-512:plan-member"
        );
        assert_eq!(j["toolchainPlans"][0]["status"], "declared");
        assert_eq!(
            j["toolchainPlans"][0]["expectedOutputCids"][0],
            "blake3-512:out"
        );
    }

    #[test]
    fn pretty_report_includes_toolchain_plan_accounting() {
        let mut r = Report::default();
        r.toolchain_plans.push(ToolchainPlanReport {
            plan_memento_cid: "blake3-512:plan-member".into(),
            plan_cid: "blake3-512:plan-letter".into(),
            status: "refuted".into(),
            reason: "plan drifted".into(),
            expected_output_cids: vec!["blake3-512:expected".into()],
            witness_memento_cid: Some("blake3-512:witness-member".into()),
            actual_output_cids: vec!["blake3-512:actual".into()],
        });

        let pretty = format_report_pretty(&r, false);

        assert!(pretty.contains("Toolchain plans:"), "{pretty}");
        assert!(pretty.contains("plan blake3-512:plan-letter"), "{pretty}");
        assert!(
            pretty.contains("plan memento: blake3-512:plan-member"),
            "{pretty}"
        );
        assert!(
            pretty.contains("witness memento: blake3-512:witness-member"),
            "{pretty}"
        );
        assert!(
            pretty.contains("expected outputs: 1")
                && pretty.contains("blake3-512:expected")
                && pretty.contains("actual outputs: 1")
                && pretty.contains("blake3-512:actual"),
            "{pretty}"
        );
        assert!(pretty.contains("reason: plan drifted"), "{pretty}");
    }

    #[test]
    fn refuted_toolchain_plan_exits_fail() {
        let mut r = Report {
            discharged: 1,
            ..Report::default()
        };
        r.rows.push(ReportRow {
            callsite: CallSite::default(),
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("hash-tier".into()),
            body_discharge_tier: None,
            verification: None,
        });
        r.toolchain_plans.push(ToolchainPlanReport {
            plan_memento_cid: "blake3-512:plan-member".into(),
            plan_cid: "blake3-512:plan-letter".into(),
            status: "refuted".into(),
            reason: "drift".into(),
            expected_output_cids: vec!["blake3-512:expected".into()],
            witness_memento_cid: Some("blake3-512:witness-member".into()),
            actual_output_cids: vec!["blake3-512:actual".into()],
        });

        assert_eq!(report_exit_code(&r), crate::EXIT_VERIFY_FAIL);
    }

    #[test]
    fn discharged_consistency_row_is_not_vacuous() {
        let mut r = Report {
            discharged: 1,
            ..Report::default()
        };
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "consistency".into(),
                ..CallSite::default()
            },
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("consistency".into()),
            body_discharge_tier: None,
            verification: Some(json!({ "kind": "consistency" })),
        });

        assert_eq!(report_exit_code(&r), crate::EXIT_OK);
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
            status: ObligationVerdict::Undecidable,
            reason: "synthetic panic row".into(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
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
            status: ObligationVerdict::Undecidable,
            reason: "synthetic panic row".into(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
        });

        let j = report_to_json(&r);

        assert!(
            j["rows"][0]["callsiteBundleCid"].is_null(),
            "absent callsite bundle should serialize as null to match existing Option field style"
        );
    }
}
