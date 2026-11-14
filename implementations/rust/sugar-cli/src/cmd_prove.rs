// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar prove` / `sugar verify`: runs the six-stage pipeline.
//
// Step 9: a witness row is decided from the package body the proof states
// (the `witness-memento` member's `body_b64`, packaged by mint). Prove asks no
// kit to resolve or re-run a witness.

use std::path::{Path, PathBuf};

use owo_colors::OwoColorize;
use serde_json::{json, Value};

use sugar_verifier::{
    LegacyZ3Fallback, PlanArtifactInput, ProofRunArtifact, RunnerConfig, SolversConfig,
};

use crate::component_plan::{self, ComponentPlan, ComponentPlanOptions, PlanIntent};
use crate::project_config::read_project_config;
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
    let report_json = report_fmt::report_to_json(report);
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

/// Production prove door: full `ProvenOutcome` so the face can apply the
/// #3893 exit-code law (unresolved links redden) without a second solve.
pub(crate) fn build_prove_outcome_with_options(
    project_root: &Path,
    z3: &str,
    component_plan_options: ComponentPlanOptions,
) -> Result<sugar_compiler::orchestrate::ProvenOutcome, String> {
    let cfg_doc = read_project_config(project_root);
    // Step 9 (ruling 2 on #7766): prove starts IR compilers only, never a
    // lift kit. The plan holds no lift surfaces, and nothing in prove reads
    // one: witness bodies come from the proof (#7830).
    let component_plan =
        component_plan::plan_ir_compilers_for_prove(project_root, component_plan_options);
    check_component_plan_errors(&component_plan)?;
    if component_plan_options.allow_failed_components {
        emit_component_plan_warnings(&component_plan);
    }

    let plan_artifact = component_plan::plan_artifact_memento(
        project_root,
        PlanIntent::Prove,
        component_plan_options,
        &component_plan,
    );

    // Ruling 3c on #7766: prove reads no other project. There is no `--with`,
    // and prove does not consult the `[verify]` callee list (that is
    // `sugar verify --project`'s, item 39); a sibling project's proof reaches
    // prove only when mint stages it in `.sugar/imports`.

    // Step 9 (ruling 3 on #7766): prove's input is the minted `.proof` plus
    // the imported `.proof` files mint staged in `.sugar/imports`; the walk
    // below `project_root` loads both. Prove never asks a kit for a
    // dependency proof. A call into a dependency that is not staged is
    // undecidable by name (its target CID is not in the pool) and its edge
    // stays on the link surface.

    // #3809 PR A: CLI is the client that reads config.toml. Solve receives
    // signers + solvers already on RunnerConfig — never re-opens config.
    let solvers_config = SolversConfig::load(project_root)
        .map_err(|e| format!("load solvers from .sugar/config.toml: {e}"))?;
    // #3809 cut #2: CLI hashes named run inputs; solve does not open them.
    let link_bundle_cid =
        sugar_verifier::runner::hash_named_project_artifact(project_root, "link-bundle.json");
    let plugin_registry_cid =
        sugar_verifier::runner::hash_named_project_artifact(project_root, "plugin-registry.json");

    let cfg = RunnerConfig {
        project_root: project_root.to_path_buf(),
        legacy_z3_fallback: Some(LegacyZ3Fallback::compat(z3.to_string())),
        trusted_implication_signers: cfg_doc.trusted_implication_signers.clone(),
        solvers_config,
        link_bundle_cid,
        plugin_registry_cid,
        plan_artifact: plan_artifact.as_ref().map(|artifact| PlanArtifactInput {
            plan_cid: artifact.plan_cid.clone(),
            member_cid: artifact.member_cid.clone(),
            member_bytes: artifact.member_bytes.clone(),
        }),
        ..Default::default()
    };
    let compilers = component_plan::compiler_registry_from_plan(
        project_root,
        &component_plan,
        &component_plan::VerifierComponentRegistry,
    );

    // Step 9 (owner, 2026-11-13: "Yes, read the proof"): prove's input is the
    // `.proof` files mint packaged and the imported ones it joins. Prove never
    // starts a lift kit to re-walk the project. Discharge always runs; a dirty
    // link surface reddens `outcome_class` under #3893.
    //
    // Ruling 3b on #7766 (inventory item 40): those inputs are read by name
    // and location -- the minted `.proof` at the root and the staged
    // `.sugar/imports/*.proof` -- not by walking the root, so prove never
    // takes its own earlier output (`.sugar/runs/*.proof`) back as input.
    let pool = sugar_verifier::load_all_proofs::run_prove_inputs(project_root);
    let mut proven = sugar_compiler::orchestrate::solve_project_with_pool(cfg, compilers, pool)
        .map_err(|error| error.to_string())?;
    proven.artifact = cli_persist_proof_run(project_root, proven.artifact);
    Ok(proven)
}

/// #3809 cut #8: solve seals the proof-run in memory; the CLI face persists
/// durable receipts under `project_root/.sugar/runs/`.
fn cli_persist_proof_run(project_root: &Path, mut artifact: ProofRunArtifact) -> ProofRunArtifact {
    if artifact.bundle_bytes.is_empty() {
        return artifact;
    }
    match sugar_verifier::runner::persist_proof_run_to_project(
        project_root,
        &artifact.bundle_cid,
        &artifact.bundle_bytes,
    ) {
        Ok(path) => {
            artifact.bundle_path = path;
        }
        Err(error) => {
            // Non-fatal for prove result: seal already succeeded; durable
            // write is a face concern. Surface loudly.
            eprintln!(
                "{}: could not persist proof-run under .sugar/runs: {error}",
                "warning".yellow().bold()
            );
        }
    }
    artifact
}

fn check_component_plan_errors(component_plan: &ComponentPlan) -> Result<(), String> {
    if let Some(diagnostic) = component_plan::first_error_diagnostic(component_plan) {
        return Err(diagnostic.message.clone());
    }
    Ok(())
}

fn emit_component_plan_warnings(component_plan: &ComponentPlan) {
    for diagnostic in component_plan::warning_diagnostics(component_plan) {
        eprintln!("{}: {}", "warning".yellow().bold(), diagnostic.message);
    }
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
        let production = src
            .split("#[cfg(test)]")
            .next()
            .expect("cmd_prove has a test module");
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
