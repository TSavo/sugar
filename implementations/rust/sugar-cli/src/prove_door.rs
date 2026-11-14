// SPDX-License-Identifier: MIT OR Apache-2.0
//
// prove_door.rs: the one prove door (step 9). `sugar prove` and the LSP
// both prove through `build_prove_outcome_with_options` and render its rows
// through `prove_rows`: the minted `.proof`
// at the root plus the `.proof` files staged directly in `.sugar/imports`,
// solved by `solve_project_with_pool`. It never starts a lift kit.

use std::path::Path;

use owo_colors::OwoColorize;

use sugar_verifier::{
    LegacyZ3Fallback, PlanArtifactInput, ProofRunArtifact, RunnerConfig, SolversConfig,
};

use crate::component_plan::{self, ComponentPlan, ComponentPlanOptions, PlanIntent};
use crate::project_config::read_project_config;

/// Production prove door: full `ProvenOutcome` so the face can apply the
/// #3893 exit-code law (unresolved links redden) without a second solve.
pub fn build_prove_outcome_with_options(
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
    // and there is no `[verify]` callee list (it went with
    // `sugar verify --project`, item 39); a sibling project's proof reaches
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

/// Prove's rows, rendered once: the `rows` of `sugar prove --json` and the
/// rows the LSP reports for a buffer are this function's output.
pub fn prove_rows(report: &sugar_verifier::Report) -> Vec<serde_json::Value> {
    report
        .rows
        .iter()
        .map(sugar_verifier::report::row_to_json)
        .collect()
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
