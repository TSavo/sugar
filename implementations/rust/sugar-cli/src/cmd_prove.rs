// SPDX-License-Identifier: Apache-2.0
//
// `sugar prove` / `sugar verify`: runs the six-stage pipeline.
//
// The witness-discharge path resolves each lift surface's manifest (the SAME
// dispatch lift uses) to export SUGAR_WITNESS_DISCHARGE_<TOOL> per tool, so
// witness recompute rides the manifest with no bespoke config.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use owo_colors::OwoColorize;
use serde_json::{json, Value};
use sugar_canonicalizer::{blake3_512_of, jcs_cid_of_json};
use walkdir::WalkDir;

use sugar_verifier::{Runner, RunnerConfig};

use crate::component_plan::{
    self, ComponentPlan, ComponentPlanOptions, PlanIntent, PlannedLiftManifest,
};
use crate::project_config::{read_project_config, ProjectConfig, WitnessEntry};
use crate::report_fmt;
use crate::ProveArgs;

// The witness-discharge path loads the lift surface manifest at
// `<project>/.sugar/lift/<surface>/manifest.toml` to read its
// `discharge_command` + `witness_tool`. No hardcoded `sugar-lift-<kit>`.

// ---------------------------------------------------------------------------
// Plugin manifest (mirrors cmd_mint: kept local to avoid coupling)
// ---------------------------------------------------------------------------

#[derive(Debug, Default)]
struct PluginManifest {
    name: String,
    command: Vec<String>,
    working_dir: Option<PathBuf>,
    /// Execution-witness discharge command the kit ships (recompute entry).
    /// Declared alongside `command` so witness discharge rides the SAME manifest
    /// dispatch as lift -- no bespoke config. `prove` exports it as
    /// `SUGAR_WITNESS_DISCHARGE_<witness_tool>` for the verifier's witness arm.
    discharge_command: Vec<String>,
    /// The `tool` value this surface stamps on its witness certificates (e.g.
    /// `pytest`). Keys the per-tool discharge registry so a proof carrying
    /// witnesses from multiple kits routes each to its own recompute.
    witness_tool: Option<String>,
    resolve_witness_command: Vec<String>,
    resolve_witness_method: Option<String>,
}

fn parse_manifest(path: &std::path::Path) -> Result<PluginManifest, String> {
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let mut m = PluginManifest::default();
    let strip = |l: &str| -> String {
        match l.find('#') {
            Some(p) => l[..p].to_string(),
            None => l.to_string(),
        }
    };
    let raw: Vec<String> = text.lines().map(|l| strip(l).trim().to_string()).collect();
    let mut i = 0;
    while i < raw.len() {
        let line = raw[i].clone();
        i += 1;
        if line.is_empty() || line.starts_with('[') {
            continue;
        }
        let Some(eq) = line.find('=') else { continue };
        let key = line[..eq].trim().to_string();
        let mut val = line[eq + 1..].trim().to_string();
        // Multi-line array value: accumulate continuation lines until the
        // closing `]` (TOML allows `key = [` then elements on later lines).
        if val.starts_with('[') && !val.contains(']') {
            while i < raw.len() && !val.contains(']') {
                val.push(' ');
                val.push_str(&raw[i]);
                i += 1;
            }
        }
        let key = key.as_str();
        let val = val.as_str();
        match key {
            "name" => m.name = val.trim_matches('"').to_string(),
            "working_dir" => m.working_dir = Some(PathBuf::from(val.trim_matches('"'))),
            "witness_tool" => m.witness_tool = Some(val.trim_matches('"').to_string()),
            "resolve_witness_method" => {
                m.resolve_witness_method = Some(val.trim_matches('"').to_string())
            }
            "command" | "discharge_command" | "resolve_witness_command" => {
                let inner = val.trim_matches(|c| c == '[' || c == ']');
                let parsed: Vec<String> = inner
                    .split(',')
                    .map(|s| s.trim().trim_matches('"').to_string())
                    .filter(|s| !s.is_empty())
                    .collect();
                if key == "command" {
                    m.command = parsed;
                } else if key == "discharge_command" {
                    m.discharge_command = parsed;
                } else {
                    m.resolve_witness_command = parsed;
                }
            }
            _ => {}
        }
    }
    if m.command.is_empty() {
        return Err(format!("manifest {} has no `command`", path.display()));
    }
    Ok(m)
}

#[allow(dead_code)] // Kept as the default wrapper for callers without a classified plan.
fn find_manifest(project_root: &std::path::Path, surface: &str) -> Result<PluginManifest, String> {
    find_manifest_with_plan(project_root, surface, None)
}

fn find_manifest_with_plan(
    project_root: &std::path::Path,
    surface: &str,
    plan: Option<&ComponentPlan>,
) -> Result<PluginManifest, String> {
    let project_local = project_root
        .join(".sugar")
        .join("lift")
        .join(surface)
        .join("manifest.toml");
    if project_local.exists() {
        return parse_manifest(&project_local);
    }
    if let Some(home) = std::env::var_os("HOME") {
        let user_global = PathBuf::from(home)
            .join(".config")
            .join("sugar")
            .join("lift")
            .join(surface)
            .join("manifest.toml");
        if user_global.exists() {
            return parse_manifest(&user_global);
        }
    }
    if let Some(plan) = plan {
        if let Some(planned) = plan
            .lift_manifests
            .iter()
            .find(|manifest| manifest.surface == surface)
        {
            return Ok(plugin_manifest_from_planned(planned.clone()));
        }
    } else if let Some(planned) = component_plan::planned_lift_manifest(project_root, surface) {
        return Ok(plugin_manifest_from_planned(planned));
    }
    Err(format!(
        "no plugin manifest for surface `{surface}` (looked in .sugar/lift/{surface}/manifest.toml, ~/.config/sugar/lift/{surface}/manifest.toml, and discovered Sugar components)"
    ))
}

fn plugin_manifest_from_planned(planned: PlannedLiftManifest) -> PluginManifest {
    PluginManifest {
        name: planned.name,
        command: planned.command,
        working_dir: planned.working_dir,
        discharge_command: planned.discharge_command,
        witness_tool: planned.witness_tool,
        resolve_witness_command: planned.resolve_witness_command,
        resolve_witness_method: planned.resolve_witness_method,
    }
}

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
        eprintln!(
            "{}: project root does not exist: {}",
            "error".red().bold(),
            project_root.display()
        );
        return crate::EXIT_USER_ERROR;
    }

    let component_plan_options = ComponentPlanOptions {
        allow_failed_components: args.allow_failed_components,
    };
    let report = match build_prove_report_with_options(
        &project_root,
        &args.z3,
        &args.with,
        component_plan_options,
    ) {
        Ok(report) => report,
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            return crate::EXIT_USER_ERROR;
        }
    };
    let report_json = report_fmt::report_to_json(&report);
    if let Some(witness_dir) = &args.emit_witnesses {
        match emit_configured_witnesses(&project_root, &report_json, witness_dir) {
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
                eprintln!("{}: emit prove witnesses: {error}", "error".red().bold());
                return crate::EXIT_USER_ERROR;
            }
        }
    }

    if args.out.json {
        match serde_json::to_string_pretty(&report_json) {
            Ok(s) => println!("{s}"),
            Err(e) => {
                eprintln!("{}: serialize JSON: {e}", "error".red().bold());
                return crate::EXIT_USER_ERROR;
            }
        }
    } else {
        report_fmt::print_report_pretty(&report, args.out.quiet);
    }

    report_fmt::report_exit_code(&report)
}

#[allow(dead_code)] // Kept as the default wrapper for callers without component-plan options.
pub(crate) fn build_prove_report(
    project_root: &Path,
    z3: &str,
    with: &[String],
) -> Result<sugar_verifier::Report, String> {
    build_prove_report_with_options(project_root, z3, with, ComponentPlanOptions::default())
}

pub(crate) fn build_prove_report_with_options(
    project_root: &Path,
    z3: &str,
    with: &[String],
    component_plan_options: ComponentPlanOptions,
) -> Result<sugar_verifier::Report, String> {
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

    configure_witness_discharge_env_with_plan(project_root, &cfg_doc, Some(&component_plan));

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
            eprintln!(
                "{}: dependency proof resolution skipped: {error}",
                "warning".yellow().bold()
            );
            Vec::new()
        }
    };

    let cfg = RunnerConfig {
        project_root: project_root.to_path_buf(),
        z3_path: z3.to_string(),
        extra_projects,
        extra_proofs: dependency_proofs,
        ..Default::default()
    };
    let compilers = component_plan::compiler_registry_from_plan(project_root, &component_plan);
    Runner::new_with_compilers(cfg, compilers)
        .run_with_proof_run()
        .map(|artifact| artifact.report)
        .map_err(|error| error.to_string())
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
) -> Result<Vec<crate::report_witness::ReportWitnessProof>, String> {
    let mut out = Vec::new();
    let cfg = read_project_config(project_root);
    let replay_pins = build_replay_pins(project_root, report_json, out_dir, &cfg)?;
    if cfg.witnesses.is_empty() {
        out.push(crate::report_witness::mint_report_witness(
            project_root,
            report_json,
            &replay_pins,
            out_dir,
        )?);
        return Ok(out);
    }
    for witness in cfg.witnesses {
        if witness.kind.eq_ignore_ascii_case("report") {
            out.push(crate::report_witness::mint_report_witness(
                project_root,
                report_json,
                &replay_pins,
                out_dir,
            )?);
            continue;
        }
        if witness.kind.eq_ignore_ascii_case("command") {
            let evidence = run_command_witness(project_root, &witness)?;
            let claim_body = json!({
                "kind": "sugar-command-witness",
                "schemaVersion": "1",
                "name": &witness.name,
                "command": &witness.command,
                "project": project_root.display().to_string(),
            });
            out.push(crate::report_witness::mint_json_witness(
                &witness.name,
                "sugar-command-witness",
                &claim_body,
                &evidence,
                out_dir,
            )?);
            continue;
        }
        if witness.kind.eq_ignore_ascii_case("file") {
            let evidence = read_file_witness(project_root, &witness)?;
            let claim_body = json!({
                "kind": "sugar-file-witness",
                "schemaVersion": "1",
                "name": &witness.name,
                "path": &witness.path,
                "project": project_root.display().to_string(),
            });
            out.push(crate::report_witness::mint_json_witness(
                &witness.name,
                "sugar-file-witness",
                &claim_body,
                &evidence,
                out_dir,
            )?);
            continue;
        }
        return Err(format!(
            "unsupported witness kind `{}` for `{}`",
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
) -> Result<Value, String> {
    Ok(json!({
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
    }))
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
        let declared_cid = path
            .file_stem()
            .and_then(|s| s.to_str())
            .filter(|s| s.starts_with("blake3-512:"));
        let memento = json!({
            "kind": "proof-file-memento",
            "schemaVersion": "1",
            "path": path_for_report(&project_abs, path),
            "declaredProofCid": declared_cid,
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
        return Err(format!("witness `{}` has empty command", witness.name));
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
        .ok_or_else(|| format!("file witness `{}` missing path", witness.name))?;
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

// WITNESS DISCHARGE defaults: so `sugar prove <project>` and artifact-mode
// `sugar verify --project <project>` settle execution witnesses by recompute
// WITHOUT the caller exporting env vars. The discharge command is declared in
// the KIT'S MANIFEST (alongside its lift `command`) and resolved here through
// the SAME `find_manifest` dispatch lift uses -- no bespoke config.
#[allow(dead_code)] // Kept as the default wrapper for callers without a classified plan.
pub(crate) fn configure_witness_discharge_env(
    project_root: &Path,
    cfg_doc: &crate::project_config::ProjectConfig,
) {
    configure_witness_discharge_env_with_plan(project_root, cfg_doc, None);
}

pub(crate) fn configure_witness_discharge_env_with_plan(
    project_root: &Path,
    cfg_doc: &crate::project_config::ProjectConfig,
    component_plan: Option<&ComponentPlan>,
) {
    if std::env::var_os("SUGAR_WITNESS_PROJECT_DIR").is_none() {
        let p = project_root
            .canonicalize()
            .unwrap_or_else(|_| project_root.to_path_buf());
        std::env::set_var("SUGAR_WITNESS_PROJECT_DIR", &p);
    }
    let planned_plugins;
    let plugins: Vec<&crate::project_config::PluginEntry> =
        if cfg_doc.plugins.iter().any(|p| p.is_lift_plugin()) {
            cfg_doc
                .plugins
                .iter()
                .filter(|p| p.is_lift_plugin())
                .collect()
        } else {
            planned_plugins = component_plan
                .map(|plan| plan.plugins.clone())
                .unwrap_or_else(|| component_plan::planned_lift_plugins(project_root));
            planned_plugins
                .iter()
                .filter(|p| p.is_lift_plugin())
                .collect()
        };
    let mut witness_resolvers: Vec<Value> = Vec::new();
    for plugin in plugins {
        let manifest = match find_manifest_with_plan(project_root, &plugin.surface, component_plan)
        {
            Ok(m) => m,
            Err(_) => continue,
        };
        if !manifest.resolve_witness_command.is_empty() {
            let working_dir = manifest_working_dir(project_root, &manifest);
            witness_resolvers.push(json!({
                "argv": manifest.resolve_witness_command,
                "working_dir": working_dir.display().to_string(),
                "method": manifest
                    .resolve_witness_method
                    .unwrap_or_else(|| "sugar.plugin.resolve_witness".to_string()),
            }));
        }
        if manifest.discharge_command.is_empty() {
            continue;
        }
        let Some(tool) = manifest.witness_tool.as_deref() else {
            continue;
        };
        let key = format!(
            "SUGAR_WITNESS_DISCHARGE_{}",
            tool.to_uppercase()
                .replace(|c: char| !c.is_ascii_alphanumeric(), "_")
        );
        if std::env::var_os(&key).is_none() {
            std::env::set_var(&key, manifest.discharge_command.join(" "));
        }
    }
    if !witness_resolvers.is_empty() && std::env::var_os("SUGAR_WITNESS_RESOLVERS").is_none() {
        if let Ok(encoded) = serde_json::to_string(&witness_resolvers) {
            std::env::set_var("SUGAR_WITNESS_RESOLVERS", encoded);
        }
    }
}

fn manifest_working_dir(project_root: &Path, manifest: &PluginManifest) -> PathBuf {
    manifest
        .working_dir
        .as_ref()
        .map(|path| {
            if path.is_absolute() {
                path.clone()
            } else {
                project_root.join(path)
            }
        })
        .unwrap_or_else(|| project_root.to_path_buf())
}

fn run_admission_gate(args: &ProveArgs) -> u8 {
    run_admission_gate_with(
        &args.artifact,
        &args.proof,
        &args.policy,
        args.out.json,
        args.out.quiet,
    )
}

/// Shared admission-gate entry point. The supply-chain artifact/policy
/// verification logic is owned here (it predates the keystone `verify`
/// verb), but both `prove` (legacy alias) and `verify` (PR-9 / #1405)
/// surface the same `--artifact`/`--proof`/`--policy` flags. Threading the
/// three `Option<PathBuf>` values directly (rather than `&ProveArgs`) lets
/// `cmd_verify` reuse this without coupling to the prover's arg struct.
pub fn run_admission_gate_with(
    artifact: &Option<PathBuf>,
    proof: &Option<PathBuf>,
    policy: &Option<PathBuf>,
    json: bool,
    quiet: bool,
) -> u8 {
    match verify_artifact_or_policy(artifact, proof, policy) {
        Ok(report) => {
            let ok = report["ok"].as_bool().unwrap_or(false);
            if json {
                println!("{}", serde_json::to_string_pretty(&report).unwrap());
            } else if !quiet {
                let verdict = report["verdict"].as_str().unwrap_or("unknown");
                println!("verify admission: {verdict}");
                if let Some(reason) = report.get("reason").and_then(Value::as_str) {
                    println!("  reason: {reason}");
                }
            }
            if ok {
                crate::EXIT_OK
            } else {
                crate::EXIT_VERIFY_FAIL
            }
        }
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            crate::EXIT_USER_ERROR
        }
    }
}

fn verify_artifact_or_policy(
    artifact: &Option<PathBuf>,
    proof: &Option<PathBuf>,
    policy: &Option<PathBuf>,
) -> Result<Value, String> {
    let proof_path = proof
        .as_ref()
        .ok_or_else(|| "--proof is required for admission verification".to_string())?;
    let proof = read_json_value(proof_path)?;

    let policy_report = policy
        .as_ref()
        .map(|policy_path| verify_policy_receipt(&proof, policy_path))
        .transpose()?;
    let artifact_report = artifact
        .as_ref()
        .map(|artifact_path| verify_artifact_receipt(&proof, artifact_path))
        .transpose()?;

    match (policy_report, artifact_report) {
        (Some(policy), Some(artifact)) => {
            let policy_ok = value_ok(&policy);
            let artifact_ok = value_ok(&artifact);
            let ok = policy_ok && artifact_ok;
            Ok(json!({
                "ok": ok,
                "verdict": if ok { "accepted" } else { "rejected" },
                "reason": combined_admission_reason(policy_ok, artifact_ok),
                "policy": policy,
                "artifact": artifact,
            }))
        }
        (Some(policy), None) => Ok(policy),
        (None, Some(artifact)) => Ok(artifact),
        (None, None) => Err("--artifact or --policy is required for admission verification".into()),
    }
}

fn verify_policy_receipt(proof: &Value, policy_path: &Path) -> Result<Value, String> {
    let policy = read_json_value(policy_path)?;
    let pinned = policy
        .get("policyCid")
        .and_then(Value::as_str)
        .ok_or_else(|| "policy receipt missing policyCid".to_string())?;
    let candidate = proof
        .get("policyCid")
        .and_then(Value::as_str)
        .ok_or_else(|| "proof receipt missing policyCid".to_string())?;
    let ok = pinned == candidate;
    Ok(json!({
        "ok": ok,
        "verdict": if ok { "accepted" } else { "rejected" },
        "reason": if ok { "policyCid matched" } else { "policyCid mismatch" },
        "pinnedPolicyCid": pinned,
        "candidatePolicyCid": candidate,
    }))
}

fn verify_artifact_receipt(proof: &Value, artifact_path: &Path) -> Result<Value, String> {
    let artifact_bytes = std::fs::read(artifact_path)
        .map_err(|e| format!("read artifact {}: {e}", artifact_path.display()))?;
    let observed_binary_cid = blake3_512_of(&artifact_bytes);
    let attested_binary_cid = proof
        .get("binaryCid")
        .and_then(Value::as_str)
        .ok_or_else(|| "proof receipt missing binaryCid".to_string())?;
    let ok = observed_binary_cid == attested_binary_cid;
    Ok(json!({
        "ok": ok,
        "verdict": if ok { "accepted" } else { "rejected" },
        "reason": if ok { "binaryCid matched" } else { "binaryCid mismatch" },
        "artifact": artifact_path,
        "attestedBinaryCid": attested_binary_cid,
        "observedBinaryCid": observed_binary_cid,
    }))
}

fn value_ok(value: &Value) -> bool {
    value.get("ok").and_then(Value::as_bool).unwrap_or(false)
}

fn combined_admission_reason(policy_ok: bool, artifact_ok: bool) -> &'static str {
    match (policy_ok, artifact_ok) {
        (true, true) => "policyCid and binaryCid matched",
        (false, true) => "policyCid mismatch",
        (true, false) => "binaryCid mismatch",
        (false, false) => "policyCid and binaryCid mismatch",
    }
}

fn read_json_value(path: &Path) -> Result<Value, String> {
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))
}
