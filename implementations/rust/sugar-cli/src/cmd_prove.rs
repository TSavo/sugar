// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar prove` / `sugar verify`: runs the six-stage pipeline.
//
// The witness-discharge path resolves each lift surface's manifest (the SAME
// dispatch lift uses) into a typed `WitnessDischargeContext` (project_dir +
// resolvers). SEAM 6 / #3809: that resolution lives in `crate::discharge_config`,
// shared with `cmd_verify`. Step 3: no SUGAR_WITNESS_PROJECT_DIR/RESOLVERS env.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use owo_colors::OwoColorize;
use serde_json::{json, Value};
use sugar_canonicalizer::{blake3_512_of, jcs_cid_of_json};
use sugar_proof_envelope::cid_from_proof_stem;
use walkdir::WalkDir;

use sugar_verifier::{
    LegacyZ3Fallback, MementoCid, PlanArtifactInput, ProofRunArtifact, RunnerConfig, SolversConfig,
};

use crate::component_plan::{
    self, ComponentPlan, ComponentPlanOptions, PlanIntent, PlannedLiftManifest,
};
use crate::project_config::{read_project_config, ProjectConfig, WitnessEntry};
use crate::report_fmt;
use crate::report_witness::{
    mint_witness_bundle, WitnessBundle, WitnessMintOptions, WitnessSource,
};
use crate::ProveArgs;

// Witness-discharge config loads lift surface manifests for resolve plugins
// (and optional DISCHARGE_* lie-env keys). No hardcoded `sugar-lift-<kit>`.
// Lives in `crate::discharge_config` (shared with `cmd_verify`).

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
    let proven = match build_prove_outcome_with_options(
        &project_root,
        &args.z3,
        &args.with,
        component_plan_options,
    ) {
        Ok(proven) => proven,
        Err(error) => {
            return emit_prove_setup_error(&error, args.out.json);
        }
    };
    let report = &proven.artifact.report;
    let report_json = report_fmt::report_to_json(report);
    if let Some(witness_dir) = &args.emit_witnesses {
        match emit_configured_witnesses(
            &project_root,
            &report_json,
            witness_dir,
            proven.artifact.plan_artifact.as_ref(),
        ) {
            Ok(witnesses) => {
                if !args.out.quiet {
                    for witness in &witnesses {
                        eprintln!(
                            "witness: {} witness={} proof={} evidence={} -> {}",
                            witness.name,
                            witness.witness_cid,
                            witness.proof_cid,
                            witness.evidence_cid,
                            witness.proof_file.display()
                        );
                        eprintln!("         body: {}", witness.evidence_file.display());
                    }
                }
            }
            Err(error) => {
                let error = format!("emit prove witnesses: {error}");
                return emit_prove_setup_error(&error, args.out.json);
            }
        }
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

pub(crate) fn build_prove_report_with_options(
    project_root: &Path,
    z3: &str,
    with: &[String],
    component_plan_options: ComponentPlanOptions,
) -> Result<sugar_verifier::Report, String> {
    build_prove_artifact_with_options(project_root, z3, with, component_plan_options)
        .map(|artifact| artifact.report)
}

pub(crate) fn build_prove_artifact_with_options(
    project_root: &Path,
    z3: &str,
    with: &[String],
    component_plan_options: ComponentPlanOptions,
) -> Result<ProofRunArtifact, String> {
    build_prove_outcome_with_options(project_root, z3, with, component_plan_options)
        .map(|proven| proven.artifact)
}

/// Production prove door: full `ProvenOutcome` so the face can apply the
/// #3893 exit-code law (unresolved links redden) without a second solve.
pub(crate) fn build_prove_outcome_with_options(
    project_root: &Path,
    z3: &str,
    with: &[String],
    component_plan_options: ComponentPlanOptions,
) -> Result<sugar_compiler::orchestrate::ProvenOutcome, String> {
    let cfg_doc = read_project_config(project_root);
    let component_plan = component_plan::plan_workspace_with_options(
        project_root,
        PlanIntent::Prove,
        component_plan_options,
    );
    check_component_plan_errors(&component_plan)?;
    if component_plan_options.allow_failed_components {
        emit_component_plan_warnings(&component_plan);
    }

    let witness_discharge = crate::discharge_config::witness_discharge_for_plan(
        project_root,
        &cfg_doc,
        Some(&component_plan),
    );
    let plan_artifact = component_plan::plan_artifact_memento(
        project_root,
        PlanIntent::Prove,
        component_plan_options,
        &component_plan,
    );

    // Resolve `--with` paths relative to project_root unless absolute,
    // matching how `[verify].callees` is resolved (project-root-anchored).
    // Without this, `--with foo` depends on CWD and breaks when prove is
    // invoked outside the project root.
    let mut extra_projects: Vec<PathBuf> = with
        .iter()
        .map(|s| {
            let p = PathBuf::from(s);
            if p.is_absolute() {
                p
            } else {
                project_root.join(p)
            }
        })
        .collect();

    for callee in &cfg_doc.callees {
        let p = project_root.join(callee);
        if p.exists() {
            extra_projects.push(p);
        }
    }

    let dependency_proofs = match crate::kit_dispatch::dependency_proofs_via_rpc(project_root) {
        Ok(proofs) => proofs,
        Err(error) => {
            return Err(format!("dependency proof resolution failed: {error}"));
        }
    };

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
        extra_projects,
        extra_proofs: dependency_proofs,
        trusted_implication_signers: cfg_doc.trusted_implication_signers.clone(),
        solvers_config,
        link_bundle_cid,
        plugin_registry_cid,
        plan_artifact: plan_artifact.as_ref().map(|artifact| PlanArtifactInput {
            plan_cid: artifact.plan_cid.clone(),
            member_cid: artifact.member_cid.clone(),
            member_bytes: artifact.member_bytes.clone(),
        }),
        witness_discharge,
        ..Default::default()
    };
    let compilers = component_plan::compiler_registry_from_plan(
        project_root,
        &component_plan,
        &component_plan::VerifierComponentRegistry,
    );

    // Task 9 (#3809): when a lift kit can rendezvous for the project surface,
    // prove through the fold path (`prove_from_kit`) instead of requiring a
    // prior `sugar mint` + disk `.proof` load. Mint remains the door for
    // sealed `.proof` publish; local project prove is fold + discharge.
    //
    // Fail-loud (PR #3897 High): if a kit **did** rendezvous, a fold/solve
    // failure is the prove result — never silent-fallback to disk. Disk
    // `solve_project` is only for projects with no planned lift kit (or
    // rendezvous skipped), where the fold path was never the chosen face.
    let mut proven = if let Some(kit) = try_rendezvous_prove_kit(project_root, &component_plan) {
        let speaker = sugar_verifier::Speaker::consumer("sugar-cli:prove");
        sugar_compiler::orchestrate::prove_from_kit(&kit, project_root, speaker, cfg, compilers)
            .map_err(|error| error.to_string())?
    } else {
        // Disk-load face (sugar#3859): no lift kit for this project — prove
        // over minted `.proof` files. Discharge always runs; dirty link
        // surface reddens `outcome_class` under #3893.
        sugar_compiler::orchestrate::solve_project(cfg, compilers)
            .map_err(|error| error.to_string())?
    };
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

/// Build a live `Kit` when the plan has exactly one lift surface.
///
/// A `Kit` is one enumerate connection.  Selecting the first member of a
/// multi-surface component plan silently drops every sibling surface (for
/// example Rust assertions, function contracts, implications, and witness
/// packages).  Until the fold door accepts the composed plan itself, a
/// multi-surface project must use the already-composed durable `.proof` face.
/// Returns `None` for that shape, for no lift surface, or when rendezvous
/// fails, and the caller falls back to disk `.proof` prove.
fn try_rendezvous_prove_kit(
    project_root: &Path,
    component_plan: &ComponentPlan,
) -> Option<sugar_compiler::kit::Kit> {
    use sugar_compiler::kit::LiftManifest;

    let planned = single_surface_fold_manifest(component_plan)?;
    if planned.command.is_empty() {
        return None;
    }
    let working_dir =
        crate::lift_plugin::resolved_working_dir_for(project_root, planned).map(|dir| {
            // Kit::rendezvous requires absolute working_dir.
            dir.canonicalize().unwrap_or(dir)
        });
    let dialect = match planned.surface.as_str() {
        "rust" => libsugar::core::Dialect::Rust,
        "c" => libsugar::core::Dialect::C,
        "python" => libsugar::core::Dialect::Other("python".into()),
        other => libsugar::core::Dialect::Other(other.to_string()),
    };
    let manifest = LiftManifest {
        surface: planned.surface.clone(),
        name: planned.name.clone(),
        dialect,
        command: planned.command.clone(),
        working_dir,
        method: planned.method.clone(),
    };
    match sugar_compiler::kit::Kit::rendezvous(manifest) {
        Ok(kit) if kit.supports_rpc_method("sugar.enumerate") => Some(kit),
        Ok(kit) => {
            eprintln!(
                "{}: lift kit {} does not advertise sugar.enumerate; using composed proof files",
                "warning".yellow().bold(),
                kit.declaration().kit.id
            );
            None
        }
        Err(error) => {
            eprintln!(
                "{}: lift kit rendezvous for prove skipped ({error})",
                "warning".yellow().bold()
            );
            None
        }
    }
}

fn single_surface_fold_manifest(component_plan: &ComponentPlan) -> Option<&PlannedLiftManifest> {
    let [planned] = component_plan.lift_manifests.as_slice() else {
        return None;
    };
    Some(planned)
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

fn emit_configured_witnesses(
    project_root: &Path,
    report_json: &Value,
    out_dir: &Path,
    plan_artifact: Option<&PlanArtifactInput>,
) -> Result<Vec<crate::report_witness::ReportWitnessProof>, String> {
    let mut out = Vec::new();
    let cfg = read_project_config(project_root);
    let replay_pins = build_replay_pins(project_root, report_json, out_dir, &cfg, plan_artifact)?;
    if cfg.witnesses.is_empty() {
        out.push(mint_witness_bundle(
            WitnessBundle::from_source(
                WitnessSource::report(project_root, report_json.clone(), replay_pins.clone()),
                WitnessMintOptions::default(),
            )?,
            out_dir,
        )?);
        return Ok(out);
    }
    for witness in cfg.witnesses {
        if witness.kind.eq_ignore_ascii_case("report") {
            out.push(mint_witness_bundle(
                WitnessBundle::from_source(
                    WitnessSource::report(project_root, report_json.clone(), replay_pins.clone()),
                    WitnessMintOptions::default(),
                )?,
                out_dir,
            )?);
            continue;
        }
        if witness.kind.eq_ignore_ascii_case("command") {
            let evidence = run_command_witness(project_root, &witness)?;
            out.push(mint_witness_bundle(
                WitnessBundle::from_source(
                    WitnessSource::command(
                        project_root,
                        witness.name.clone(),
                        witness.command.clone(),
                        evidence,
                    )?,
                    WitnessMintOptions::default(),
                )?,
                out_dir,
            )?);
            continue;
        }
        if witness.kind.eq_ignore_ascii_case("file") {
            let evidence = read_file_witness(project_root, &witness)?;
            let path = witness.path.clone().ok_or_else(|| {
                format!(
                    "crime: file witness without path; owner: sugar-cli::cmd_prove; illegal shape: witness `{}` has kind=file with no path; replacement: set path before constructing WitnessSource::File",
                    witness.name
                )
            })?;
            out.push(mint_witness_bundle(
                WitnessBundle::from_source(
                    WitnessSource::file(project_root, witness.name.clone(), path, evidence)?,
                    WitnessMintOptions::default(),
                )?,
                out_dir,
            )?);
            continue;
        }
        return Err(format!(
            "crime: unsupported witness source kind; owner: sugar-cli::cmd_prove; illegal shape: witness `{}` for `{}` is not report/command/file; replacement: configure kind = \"report\", \"command\", or \"file\" so cmd_prove can construct WitnessSource before minting",
            witness.kind, witness.name
        ));
    }
    Ok(out)
}

fn build_replay_pins(
    project_root: &Path,
    report_json: &Value,
    out_dir: &Path,
    cfg: &ProjectConfig,
    plan_artifact: Option<&PlanArtifactInput>,
) -> Result<Value, String> {
    let mut pins = json!({
        "kind": "sugar-prove-replay-pins",
        "schemaVersion": "1",
        "producer": {
            "package": env!("CARGO_PKG_NAME"),
            "version": env!("CARGO_PKG_VERSION"),
        },
        "projectConfig": project_config_pin(project_root)?,
        "lifters": lifter_pins(project_root, cfg),
        "solvers": solver_pins_from_report(report_json),
        "proofInputs": proof_input_pins(project_root, out_dir)?,
        "witnessSources": witness_source_pins(cfg),
    });
    if let Some(plan_artifact) = plan_artifact {
        pins.as_object_mut()
            .expect("replay pins object")
            .insert("planArtifact".to_string(), plan_artifact_pin(plan_artifact));
    }
    Ok(pins)
}

fn plan_artifact_pin(plan_artifact: &PlanArtifactInput) -> Value {
    json!({
        "kind": "component-plan-artifact-pin",
        "schemaVersion": "1",
        "planCid": plan_artifact.plan_cid,
        "planMementoCid": plan_artifact.member_cid,
    })
}

fn project_config_pin(project_root: &Path) -> Result<Value, String> {
    let path = project_root.join(".sugar/config.toml");
    if !path.exists() {
        return Ok(pin_memento(json!({
            "kind": "file-bytes-memento",
            "schemaVersion": "1",
            "role": "sugar-project-config",
            "present": false,
            "path": ".sugar/config.toml",
        })));
    }
    let bytes = std::fs::read(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
    Ok(pin_memento(json!({
        "kind": "file-bytes-memento",
        "schemaVersion": "1",
        "role": "sugar-project-config",
        "present": true,
        "path": ".sugar/config.toml",
        "byteCid": blake3_512_of(&bytes),
        "byteLength": bytes.len(),
    })))
}

fn lifter_pins(project_root: &Path, cfg: &ProjectConfig) -> Vec<Value> {
    cfg.plugins
        .iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .map(|plugin| {
            let manifest = lift_manifest_file_pin(project_root, &plugin.surface);
            pin_memento(json!({
                "kind": "lifter-config-memento",
                "schemaVersion": "1",
                "displayName": plugin.display_name(),
                "plugin": {
                    "name": plugin.name.as_deref(),
                    "kind": plugin.kind.as_deref(),
                    "surface": &plugin.surface,
                    "workspaceOverride": plugin.workspace_override.as_deref(),
                    "emit": plugin.emit.as_deref(),
                    "layer": plugin.layer.as_deref(),
                },
                "manifest": manifest,
            }))
        })
        .collect()
}

fn lift_manifest_file_pin(project_root: &Path, surface: &str) -> Value {
    let project_local = project_root
        .join(".sugar")
        .join("lift")
        .join(surface)
        .join("manifest.toml");
    let global = std::env::var_os("HOME").map(|home| {
        PathBuf::from(home)
            .join(".config")
            .join("sugar")
            .join("lift")
            .join(surface)
            .join("manifest.toml")
    });
    let path = if project_local.exists() {
        Some(project_local)
    } else {
        global.filter(|p| p.exists())
    };
    let Some(path) = path else {
        return json!({
            "present": false,
            "surface": surface,
        });
    };
    match std::fs::read(&path) {
        Ok(bytes) => json!({
            "present": true,
            "path": path.display().to_string(),
            "byteCid": blake3_512_of(&bytes),
            "byteLength": bytes.len(),
        }),
        Err(error) => json!({
            "present": true,
            "path": path.display().to_string(),
            "error": error.to_string(),
        }),
    }
}

fn witness_source_pins(cfg: &ProjectConfig) -> Vec<Value> {
    if cfg.witnesses.is_empty() {
        return vec![pin_memento(json!({
            "kind": "witness-source-memento",
            "schemaVersion": "1",
            "witnessKind": "report",
            "builtin": true,
        }))];
    }
    cfg.witnesses
        .iter()
        .map(|witness| {
            pin_memento(json!({
                "kind": "witness-source-memento",
                "schemaVersion": "1",
                "witnessKind": &witness.kind,
                "config": {
                    "name": &witness.name,
                    "command": &witness.command,
                    "workingDir": &witness.working_dir,
                    "path": &witness.path,
                }
            }))
        })
        .collect()
}

fn solver_pins_from_report(report_json: &Value) -> Vec<Value> {
    let mut out: BTreeMap<String, Value> = BTreeMap::new();
    let Some(rows) = report_json.get("rows").and_then(Value::as_array) else {
        return Vec::new();
    };
    for row in rows {
        let Some(invs) = row
            .get("verification")
            .and_then(|v| v.get("solverInvocations"))
            .and_then(Value::as_array)
        else {
            continue;
        };
        for inv in invs {
            let memento = json!({
                "kind": "solver-report-pin-memento",
                "schemaVersion": "1",
                "solverInvocationCid": inv.get("solverInvocationCid"),
                "solverArtifactCid": inv.get("solverArtifactCid"),
                "solverVendorMementoCid": inv.get("solverVendorMementoCid"),
                "solverVendorMemento": inv.get("solverVendorMemento"),
                "compiler": inv.get("compiler"),
                "verdict": inv.get("verdict"),
                "authoritative": inv.get("authoritative"),
            });
            let pin = pin_memento(memento);
            if let Some(cid) = pin.get("cid").and_then(Value::as_str) {
                out.insert(cid.to_string(), pin);
            }
        }
    }
    out.into_values().collect()
}

fn proof_input_pins(project_root: &Path, out_dir: &Path) -> Result<Vec<Value>, String> {
    let project_abs = absolute_path(project_root)?;
    let out_abs = absolute_path(out_dir)?;
    let mut out: BTreeMap<String, Value> = BTreeMap::new();
    for entry in WalkDir::new(&project_abs) {
        let entry = entry.map_err(|e| format!("walk {}: {e}", project_abs.display()))?;
        let path = entry.path();
        if path.starts_with(&out_abs) || !entry.file_type().is_file() {
            continue;
        }
        if path.extension().and_then(|s| s.to_str()) != Some("proof") {
            continue;
        }
        let bytes = std::fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
        let stem = path.file_stem().and_then(|s| s.to_str()).ok_or_else(|| {
            format!(
                "proof input file `{}` missing CID filename stem",
                path.display()
            )
        })?;
        let declared_cid = cid_from_proof_stem(stem).ok_or_else(|| {
            format!(
                "proof input file `{}` has invalid proof CID stem `{stem}`; expected blake3-512 filename form with 128 hex characters",
                path.display()
            )
        })?;
        let declared_cid = MementoCid::try_parse(declared_cid).map_err(|raw| {
                format!(
                    "proof input file `{}` has invalid proof CID stem `{raw}`; expected blake3-512 plus 128 hex characters",
                    path.display()
                )
            })?;
        let memento = json!({
            "kind": "proof-file-memento",
            "schemaVersion": "1",
            "path": path_for_report(&project_abs, path),
            "declaredProofCid": declared_cid.to_string(),
            "fileByteCid": blake3_512_of(&bytes),
            "byteLength": bytes.len(),
        });
        let pin = pin_memento(memento);
        if let Some(cid) = pin.get("cid").and_then(Value::as_str) {
            out.insert(cid.to_string(), pin);
        }
    }
    Ok(out.into_values().collect())
}

fn pin_memento(memento: Value) -> Value {
    let cid = jcs_cid_of_json(&memento);
    json!({
        "cid": cid,
        "memento": memento,
    })
}

fn absolute_path(path: &Path) -> Result<PathBuf, String> {
    if path.is_absolute() {
        Ok(path.to_path_buf())
    } else {
        let cwd = std::env::current_dir().map_err(|e| format!("current dir: {e}"))?;
        Ok(cwd.join(path))
    }
}

fn path_for_report(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .display()
        .to_string()
}

fn run_command_witness(project_root: &Path, witness: &WitnessEntry) -> Result<Value, String> {
    if witness.command.is_empty() {
        return Err(format!(
            "crime: command witness without argv; owner: sugar-cli::cmd_prove; illegal shape: witness `{}` has empty command; replacement: configure command before constructing WitnessSource::Command",
            witness.name
        ));
    }
    let working_dir = witness
        .working_dir
        .as_ref()
        .map(PathBuf::from)
        .map(|p| {
            if p.is_absolute() {
                p
            } else {
                project_root.join(p)
            }
        })
        .unwrap_or_else(|| project_root.to_path_buf());
    let mut cmd = Command::new(&witness.command[0]);
    cmd.args(&witness.command[1..]).current_dir(&working_dir);
    let output = cmd
        .output()
        .map_err(|e| format!("run witness `{}`: {e}", witness.name))?;
    let status_code = output.status.code();
    Ok(json!({
        "kind": "command-output-witness",
        "schemaVersion": "1",
        "name": witness.name,
        "command": witness.command,
        "workingDir": working_dir.display().to_string(),
        "status": if output.status.success() { "passed" } else { "failed" },
        "exitCode": status_code,
        "stdout": String::from_utf8_lossy(&output.stdout).to_string(),
        "stderr": String::from_utf8_lossy(&output.stderr).to_string(),
    }))
}

fn read_file_witness(project_root: &Path, witness: &WitnessEntry) -> Result<Value, String> {
    let path = witness
        .path
        .as_ref()
        .ok_or_else(|| {
            format!(
                "crime: file witness without path; owner: sugar-cli::cmd_prove; illegal shape: witness `{}` has kind=file with no path; replacement: set path before constructing WitnessSource::File",
                witness.name
            )
        })?;
    let path = PathBuf::from(path);
    let full = if path.is_absolute() {
        path
    } else {
        project_root.join(path)
    };
    let bytes = std::fs::read(&full).map_err(|e| format!("read {}: {e}", full.display()))?;
    let byte_cid = blake3_512_of(&bytes);
    let text = std::str::from_utf8(&bytes).ok().map(str::to_string);
    Ok(json!({
        "kind": "file-witness",
        "schemaVersion": "1",
        "name": witness.name,
        "path": full.display().to_string(),
        "byteCid": byte_cid,
        "byteLength": bytes.len(),
        "text": text,
        "bodyB64": B64.encode(&bytes),
    }))
}

// SEAM 6: witness-discharge env staging moved to `crate::discharge_config`
// (shared with `cmd_verify`, closing the old face-to-face reach-in).

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
    // component-plan error, dependency-proof resolution failure, witness
    // minting failure, or JSON serialization failure), the caller must still
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

    #[test]
    fn multi_surface_prove_does_not_drop_siblings_into_first_kit() {
        let mut plan = ComponentPlan::default();
        plan.lift_manifests = vec![
            PlannedLiftManifest {
                surface: "rust-cargo-test-witness".to_string(),
                name: "witness".to_string(),
                command: vec!["witness-rpc".to_string()],
                ..Default::default()
            },
            PlannedLiftManifest {
                surface: "rust-test-assertions".to_string(),
                name: "assertions".to_string(),
                command: vec!["assertions-rpc".to_string()],
                ..Default::default()
            },
        ];

        assert!(
            single_surface_fold_manifest(&plan).is_none(),
            "one Kit cannot honestly represent a composed component plan"
        );
    }

    #[test]
    fn single_surface_prove_keeps_the_live_fold_path() {
        let mut plan = ComponentPlan::default();
        plan.lift_manifests.push(PlannedLiftManifest {
            surface: "python".to_string(),
            name: "python-lift".to_string(),
            command: vec!["python-rpc".to_string()],
            ..Default::default()
        });

        assert_eq!(
            single_surface_fold_manifest(&plan).map(|manifest| manifest.surface.as_str()),
            Some("python")
        );
    }

    #[test]
    fn proof_input_pins_refuse_bad_prefix_proof_filename() {
        let temp = tempfile::tempdir().expect("tempdir");
        let out_dir = temp.path().join("out");
        std::fs::create_dir(&out_dir).expect("out dir");
        std::fs::write(temp.path().join("sha512:not-a-sugar-cid.proof"), b"proof")
            .expect("write proof");

        let err = proof_input_pins(temp.path(), &out_dir)
            .expect_err("bad proof filename prefix must refuse");

        assert!(
            err.contains("sha512:not-a-sugar-cid"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn proof_input_pins_refuse_bad_hex_proof_filename() {
        let temp = tempfile::tempdir().expect("tempdir");
        let out_dir = temp.path().join("out");
        std::fs::create_dir(&out_dir).expect("out dir");
        let bad = format!("blake3-512:{}g.proof", "a".repeat(127));
        std::fs::write(temp.path().join(&bad), b"proof").expect("write proof");

        let err = proof_input_pins(temp.path(), &out_dir)
            .expect_err("bad proof filename hex must refuse");

        assert!(err.contains("blake3-512:"), "unexpected error: {err}");
    }

    #[test]
    fn replay_pins_reference_the_plan_artifact_when_present() {
        let temp = tempfile::tempdir().expect("tempdir");
        let out_dir = temp.path().join("out");
        std::fs::create_dir(&out_dir).expect("out dir");
        let cfg = ProjectConfig::default();
        let mut plan = ComponentPlan::default();
        plan.lift_manifests.push(PlannedLiftManifest {
            surface: "rust-test-assertions".to_string(),
            name: "rust-test-assertions-lift".to_string(),
            version: Some("0.1.0".to_string()),
            command: vec!["rust-test-assertions-rpc".to_string()],
            ..Default::default()
        });
        let artifact = component_plan::plan_artifact_memento(
            temp.path(),
            PlanIntent::Prove,
            ComponentPlanOptions::default(),
            &plan,
        )
        .expect("plan artifact minted");
        let verifier_artifact = PlanArtifactInput {
            plan_cid: artifact.plan_cid.clone(),
            member_cid: artifact.member_cid.clone(),
            member_bytes: artifact.member_bytes.clone(),
        };

        let replay_pins = build_replay_pins(
            temp.path(),
            &json!({"solvers": []}),
            &out_dir,
            &cfg,
            Some(&verifier_artifact),
        )
        .expect("replay pins build");

        assert_eq!(
            replay_pins
                .pointer("/planArtifact/planCid")
                .and_then(Value::as_str),
            Some(artifact.plan_cid.as_str())
        );
        assert_eq!(
            replay_pins
                .pointer("/planArtifact/planMementoCid")
                .and_then(Value::as_str),
            Some(artifact.member_cid.as_str())
        );
    }
}
