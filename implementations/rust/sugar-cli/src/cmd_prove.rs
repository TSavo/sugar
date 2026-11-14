// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar prove` / `sugar verify`: runs the six-stage pipeline.
//
// Step 9: a witness row is decided from the package body the proof states
// (the `witness-memento` member's `body_b64`, packaged by mint). Prove asks no
// kit to resolve or re-run a witness.

use std::path::PathBuf;

use owo_colors::OwoColorize;
use serde_json::{json, Value};

use crate::component_plan::ComponentPlanOptions;
use crate::prove_door::build_prove_outcome_with_options;
use crate::report_fmt;
use crate::ProveArgs;

// ---------------------------------------------------------------------------
// pub fn run: entry point from main.rs
// ---------------------------------------------------------------------------

pub fn run(args: ProveArgs) -> u8 {
    if args.artifact.is_some() || args.proof.is_some() || args.policy.is_some() {
        return run_admission_gate(&args);
    }

    // Run the six-stage verifier pipeline.
    let project_root: PathBuf = args.project.unwrap_or_else(|| PathBuf::from("."));
    if !project_root.exists() {
        let error = format!("project root does not exist: {}", project_root.display());
        return emit_prove_setup_error(&error, args.out.json);
    }

    let component_plan_options = ComponentPlanOptions {
        allow_failed_components: args.allow_failed_components,
    };
    let proven =
        match build_prove_outcome_with_options(&project_root, &args.z3, component_plan_options) {
            Ok(proven) => proven,
            Err(error) => {
                return emit_prove_setup_error(&error, args.out.json);
            }
        };
    let report = &proven.artifact.report;
    let mut report_json = report_fmt::report_to_json(report);
    for (key, value) in report_fmt::verdict_fields(report) {
        report_json[key] = value;
    }
    if args.out.json {
        match serde_json::to_string_pretty(&report_json) {
            Ok(s) => println!("{s}"),
            Err(e) => {
                let error = format!("serialize JSON: {e}");
                return emit_prove_setup_error(&error, true);
            }
        }
    } else {
        report_fmt::print_report_pretty(report, args.out.quiet);
        if !args.out.quiet {
            print!("{}", report_fmt::format_verdict_lines(report));
        }
    }

    if !args.out.quiet && proven.has_unresolved_link_surface() {
        eprintln!(
            "{}: unresolved link surface ({} error(s)) — exit {} (EXIT_LINK_FAIL / feed more)",
            "link".red().bold(),
            proven.link_errors.len(),
            crate::EXIT_LINK_FAIL
        );
    }

    // sugar#3893: green over unbridged callsites is vacuous. Fold link
    // surface onto prove's existing report exit without rewriting that
    // face's report-only law for non-green cases.
    prove_exit_code(report, &proven)
}

/// Prove face exit: keep `report_exit_code`'s report law, then apply #3893
/// so a would-be green run with dirty link surface exits EXIT_LINK_FAIL.
fn prove_exit_code(
    report: &sugar_verifier::Report,
    proven: &sugar_compiler::orchestrate::ProvenOutcome,
) -> u8 {
    let report_code = report_fmt::report_exit_code(report);
    if report_code == crate::EXIT_OK && proven.has_unresolved_link_surface() {
        crate::EXIT_LINK_FAIL
    } else {
        report_code
    }
}

// `sugar prove --json` promises callers a parseable JSON report on stdout.
// Before this, setup failures (bad project root, component-plan errors,
// dependency-proof resolution, witness minting, JSON serialization) only
// printed a plain "error: ..." line to stderr, so `--json` callers (and the
// numpy-attribute-safety-showcase examples-gate check) saw NO JSON object at
// all instead of a red verdict they could parse. Route every prove-time
// setup error through this so `--json` always yields `{"ok": false, ...}`,
// matching the contract `--json` implies.
fn prove_setup_error_json(error: &str) -> Value {
    json!({
        "ok": false,
        "verdict": "error",
        "reason": error,
    })
}

fn emit_prove_setup_error(error: &str, json: bool) -> u8 {
    if json {
        let report = prove_setup_error_json(error);
        match serde_json::to_string_pretty(&report) {
            Ok(s) => println!("{s}"),
            Err(_) => println!("{{\"ok\": false, \"verdict\": \"error\"}}"),
        }
    }
    eprintln!("{}: {error}", "error".red().bold());
    crate::EXIT_USER_ERROR
}

fn run_admission_gate(args: &ProveArgs) -> u8 {
    crate::admission::run_admission_gate_with(
        &args.artifact,
        &args.proof,
        &args.policy,
        args.out.json,
        args.out.quiet,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    // Red instrument for the examples-gate shape `prove-output/no-json-report`:
    // when `sugar prove --json` hits a setup error (bad project root,
    // component-plan error, dependency-proof resolution failure, or JSON
    // serialization failure), the caller must still
    // get a parseable JSON object on stdout instead of a bare stderr line.
    #[test]
    fn prove_setup_error_json_is_a_parseable_report_object() {
        let report = prove_setup_error_json("dependency proof resolution failed: boom");
        assert_eq!(report["ok"].as_bool(), Some(false));
        assert_eq!(report["verdict"].as_str(), Some("error"));
        assert_eq!(
            report["reason"].as_str(),
            Some("dependency proof resolution failed: boom")
        );

        // Must round-trip through the exact serialize path `emit_prove_setup_error`
        // uses, and must contain a line starting with `{` so downstream
        // regex-based JSON extraction (e.g. the numpy-attribute-safety-showcase
        // examples gate) finds a JSON object at all.
        let s = serde_json::to_string_pretty(&report).expect("serialize");
        assert!(s.lines().next().unwrap().starts_with('{'));
        let round_tripped: Value = serde_json::from_str(&s).expect("parse back");
        assert_eq!(round_tripped, report);
    }

    /// Step 9 membrane (owner, 2026-11-13): prove reads `.proof` files only.
    /// The production half of this file never starts a lift kit or folds one.
    #[test]
    fn prove_never_starts_a_lift_kit() {
        let src = include_str!("cmd_prove.rs");
        let production = format!(
            "{}{}",
            src.split("#[cfg(test)]")
                .next()
                .expect("cmd_prove has a test module"),
            include_str!("prove_door.rs")
        );
        for forbidden in [
            "Kit::rendezvous",
            "prove_from_kit",
            "fold_kit_to_pool",
            "fold_claim_tree",
            "fold_project",
            "plan_workspace",
            "dependency_proofs_via_rpc",
            "resolve_testimony",
            "extra_projects",
            "callees",
            "report_witness",
            "mint_witness_bundle",
            "emit_witnesses",
        ] {
            assert!(
                !production.contains(forbidden),
                "sugar prove reaches back to the lifter through `{forbidden}`"
            );
        }
        assert!(production.contains("load_all_proofs::run_prove_inputs("));
        assert!(production.contains("orchestrate::solve_project_with_pool("));
        assert!(
            !production.contains("orchestrate::solve_project("),
            "sugar prove walks the root for .proof files through `solve_project`"
        );
    }

    /// Ruling 3c on #7766: prove takes no other project (`--with`), and lift
    /// never proves (`--prove`, `--z3`, `--with` are gone from `sugar lift`).
    /// Item 5 on #7766: prove packages nothing (`--emit-witnesses` is gone).
    #[test]
    fn prove_takes_no_other_project_and_lift_never_proves() {
        use clap::Parser;
        for argv in [
            &["sugar", "prove", ".", "--with", "elsewhere"][..],
            &["sugar", "prove", ".", "--emit-witnesses", "out"][..],
            &["sugar", "lift", ".", "--report", "--prove"][..],
            &["sugar", "lift", ".", "--report", "--z3", "z3"][..],
            &["sugar", "lift", ".", "--report", "--with", "elsewhere"][..],
        ] {
            let error = crate::Cli::try_parse_from(argv)
                .expect_err("the flag is gone and must be refused by name");
            assert_eq!(
                error.kind(),
                clap::error::ErrorKind::UnknownArgument,
                "{argv:?}: {error}"
            );
        }
        assert!(crate::Cli::try_parse_from(["sugar", "prove", "."]).is_ok());
        assert!(crate::Cli::try_parse_from(["sugar", "lift", ".", "--report"]).is_ok());
    }
}
