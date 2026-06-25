// SPDX-License-Identifier: Apache-2.0
//
// `sugar lift <PROJECT>`: dispatch the configured lift-plugin protocol
// and emit the raw lifted ProofIR response. Minting is a separate composition
// step owned by `sugar mint`.

use std::collections::{BTreeMap, BTreeSet};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use owo_colors::OwoColorize;
use serde_json::{Map, Value};

use sugar_claim_envelope::contract_cid_of_ir_decl;

use crate::lift_plugin::{self, LiftPluginError, LiftPluginOptions};
use crate::project_config::{read_project_config, read_user_config, PluginEntry, ProjectConfig};
use crate::report_fmt;
use crate::{cmd_mint, cmd_prove};
use crate::{LiftArgs, EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

pub fn run(args: LiftArgs) -> u8 {
    let project_root = args.project.clone().unwrap_or_else(|| PathBuf::from("."));
    if !project_root.exists() {
        eprintln!(
            "{}: project not found: {}",
            "error".red().bold(),
            project_root.display()
        );
        return EXIT_USER_ERROR;
    }

    let project_cfg = read_project_config(&project_root);
    let user_cfg = read_user_config();
    if args.report {
        let project_lift_plugins = lift_report_graph_plugins(&project_root, &project_cfg);
        if project_lift_plugins.len() > 1 {
            return run_configured_lift_report_graph(&args, &project_root, &project_lift_plugins);
        }
    }
    let resolved_surface = match configured_or_planned_lift_surface(
        &project_root,
        &project_cfg,
        &user_cfg,
        args.report,
    ) {
        Ok(surface) => surface,
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    let surface = resolved_surface.surface.clone();

    let mut lift_options = if let Some(plugin) = resolved_surface.plugin.as_ref() {
        lift_options_for_plugin(plugin)
    } else {
        lift_options_for_configured_surface(&project_cfg, &surface)
    };
    lift_options.identify_only = args.identify_only;
    lift_options.library_bindings = args.library_bindings;
    lift_options.report_summary = args.report_summary;
    tracing::trace!(
        surface = %surface,
        emit = ?lift_options.emit,
        layer = ?lift_options.layer,
        workspace_override = ?lift_options.workspace_override,
        identify_only = lift_options.identify_only,
        library_bindings = lift_options.library_bindings,
        report_summary = lift_options.report_summary,
        "lift: dispatching configured surface"
    );
    let source_oracle_routes = vec![source_oracle_route_for_surface(
        &surface,
        lift_options.workspace_override.clone(),
    )];

    match lift_plugin::dispatch_lift_path(&project_root, &surface, lift_options, true) {
        Ok(session) => {
            let response = session.response();
            if args.report {
                trace_lift_report_response("after_lift_plugin_response", response);
            }
            if args.identify_only
                && response
                    .get("kind")
                    .and_then(|value| value.as_str())
                    .is_none_or(|kind| {
                        kind != "identity-document" && kind != "package-inspection-document"
                    })
            {
                let kind = response
                    .get("kind")
                    .and_then(|value| value.as_str())
                    .unwrap_or("unknown");
                eprintln!(
                    "{}: identify-only lift returned `{kind}`; expected `identity-document` or `package-inspection-document`",
                    "error".red().bold()
                );
                return EXIT_VERIFY_FAIL;
            }
            if args.report {
                if args.report_summary {
                    trace_lift_report_checkpoint("before_source_report_summary_from_lift_response");
                    let summary =
                        match source_report_summary_from_lift_response(response, &project_root) {
                            Ok(summary) => summary,
                            Err(error) => {
                                eprintln!("{}: {error}", "error".red().bold());
                                return EXIT_USER_ERROR;
                            }
                        };
                    trace_lift_report_checkpoint("after_source_report_summary_from_lift_response");
                    let hard_failure = source_report_summary_has_hard_failures(&summary);
                    let rendered = if args.out.json {
                        match render_report_summary_json(&summary) {
                            Ok(rendered) => rendered,
                            Err(error) => {
                                eprintln!(
                                    "{}: render lift summary report: {error}",
                                    "error".red().bold()
                                );
                                return EXIT_USER_ERROR;
                            }
                        }
                    } else {
                        render_report_summary_human(&summary)
                    };
                    trace_lift_render_checkpoint("after_render_summary_report", rendered.len());
                    if let Err(error) = write_output(None, rendered.as_bytes()) {
                        eprintln!("{}: {error}", "error".red().bold());
                        return EXIT_USER_ERROR;
                    }
                    trace_lift_render_checkpoint("after_write_summary_report", rendered.len());
                    if hard_failure {
                        return EXIT_VERIFY_FAIL;
                    }
                    return EXIT_OK;
                }
                trace_lift_report_checkpoint("before_source_report_from_lift_response");
                let mut report =
                    match source_report_from_lift_response(response, args.contract.as_deref()) {
                        Ok(report) => report,
                        Err(error) => {
                            eprintln!("{}: {error}", "error".red().bold());
                            return EXIT_USER_ERROR;
                        }
                    };
                report.project_root = Some(project_root.clone());
                report.source_oracle_routes = source_oracle_routes.clone();
                trace_lift_source_report("after_source_report_from_lift_response", &report);
                let prove_with = if args.prove {
                    trace_lift_report_checkpoint("before_prepare_lift_report_prove_inputs");
                    match prepare_lift_report_prove_inputs(
                        &project_root,
                        &project_cfg,
                        &user_cfg,
                        &resolved_surface,
                        args.library_bindings,
                        &args.with,
                    ) {
                        Ok(with) => with,
                        Err(error) => {
                            eprintln!("{}: prepare prove report: {error}", "error".red().bold());
                            return EXIT_USER_ERROR;
                        }
                    }
                } else {
                    Vec::new()
                };
                if args.prove {
                    tracing::info!(
                        stage = "after_prepare_lift_report_prove_inputs",
                        rss_kib = current_rss_kib().unwrap_or_default(),
                        rss_available = current_rss_kib().is_some(),
                        prove_inputs = prove_with.len(),
                        "lift-report memory checkpoint"
                    );
                }
                let prove_report = if args.prove {
                    trace_lift_report_checkpoint("before_build_prove_report");
                    match cmd_prove::build_prove_report(&project_root, &args.z3, &prove_with) {
                        Ok(prove_report) => {
                            trace_lift_report_checkpoint("after_build_prove_report");
                            Some(prove_report)
                        }
                        Err(error) => {
                            eprintln!("{}: prove report: {error}", "error".red().bold());
                            return EXIT_USER_ERROR;
                        }
                    }
                } else {
                    None
                };
                let mut hard_failure = source_report_has_hard_failures(&report);
                if let Some(prove_report) = &prove_report {
                    hard_failure |= report_fmt::report_exit_code(prove_report) != EXIT_OK;
                }
                trace_lift_source_report("before_render_report", &report);
                let rendered = if args.out.json {
                    match render_report_json(&report, prove_report.as_ref()) {
                        Ok(rendered) => rendered,
                        Err(error) => {
                            eprintln!("{}: render lift report: {error}", "error".red().bold());
                            return EXIT_USER_ERROR;
                        }
                    }
                } else if args.visual {
                    render_report_visual(&report, prove_report.as_ref())
                } else {
                    render_report_human(&report, prove_report.as_ref())
                };
                trace_lift_render_checkpoint("after_render_report", rendered.len());
                if let Err(error) = write_output(None, rendered.as_bytes()) {
                    eprintln!("{}: {error}", "error".red().bold());
                    return EXIT_USER_ERROR;
                }
                trace_lift_render_checkpoint("after_write_report", rendered.len());
                if hard_failure {
                    return EXIT_VERIFY_FAIL;
                }
            } else {
                let output = match lift_output_document(&project_root, &surface, response) {
                    Ok(output) => output,
                    Err(error) => {
                        eprintln!(
                            "{}: canonicalize lift response: {error}",
                            "error".red().bold()
                        );
                        return EXIT_USER_ERROR;
                    }
                };
                if let Err(error) = write_output(args.output.as_ref(), output.as_bytes()) {
                    eprintln!("{}: {error}", "error".red().bold());
                    return EXIT_USER_ERROR;
                }
                if !args.out.quiet
                    && args
                        .output
                        .as_ref()
                        .is_some_and(|path| path.as_os_str() != "-")
                {
                    eprintln!("lift: wrote ProofIR term JSON");
                }
            }
            EXIT_OK
        }
        Err(LiftPluginError::MissingBinary { binary }) => {
            eprintln!(
                "{}: lifter binary `{binary}` not found",
                "error".red().bold()
            );
            EXIT_USER_ERROR
        }
        Err(LiftPluginError::Refused(refusal)) => {
            eprintln!(
                "{}: {}",
                "error".red().bold(),
                serde_json::to_string(&refusal).unwrap_or_else(|_| {
                    format!(
                        "{}: {}",
                        refusal.header.failure_kind, refusal.header.failure_detail
                    )
                })
            );
            EXIT_VERIFY_FAIL
        }
        Err(LiftPluginError::Failed(error)) => {
            eprintln!("{}: {error}", "error".red().bold());
            EXIT_VERIFY_FAIL
        }
    }
}

fn lift_report_graph_plugins(project_root: &Path, project_cfg: &ProjectConfig) -> Vec<PluginEntry> {
    project_cfg
        .plugins
        .iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .filter(|plugin| {
            plugin.emit.as_deref() == Some("ir-document")
                || lift_plugin::surface_phase(project_root, &plugin.surface) == "consumer"
        })
        .cloned()
        .collect()
}

#[derive(Debug, Clone)]
struct ResolvedLiftSurface {
    surface: String,
    plugin: Option<PluginEntry>,
}

fn configured_or_planned_lift_surface(
    project_root: &Path,
    project_cfg: &ProjectConfig,
    user_cfg: &ProjectConfig,
    prefer_report: bool,
) -> Result<ResolvedLiftSurface, String> {
    if let Some(surface) = project_cfg.surface_for("lift") {
        return Ok(ResolvedLiftSurface {
            surface,
            plugin: None,
        });
    }

    let lift_plugins = project_cfg
        .plugins
        .iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .collect::<Vec<_>>();
    if prefer_report {
        let report_plugins = lift_plugins
            .iter()
            .copied()
            .filter(|plugin| plugin.emit.as_deref() == Some("ir-document"))
            .collect::<Vec<_>>();
        if report_plugins.len() == 1 {
            return Ok(ResolvedLiftSurface {
                surface: report_plugins[0].surface.clone(),
                plugin: None,
            });
        }
    }
    if lift_plugins.len() == 1 {
        return Ok(ResolvedLiftSurface {
            surface: lift_plugins[0].surface.clone(),
            plugin: None,
        });
    }

    if let Some(surface) = user_cfg.surface_for("lift") {
        return Ok(ResolvedLiftSurface {
            surface,
            plugin: None,
        });
    }

    let component_plan = crate::component_plan::plan_workspace(project_root);
    let candidates = component_plan
        .plugins
        .iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .cloned()
        .collect::<Vec<_>>();
    let report_candidates = candidates
        .iter()
        .filter(|plugin| plugin.emit.as_deref() == Some("ir-document"))
        .cloned()
        .collect::<Vec<_>>();
    let selected = if report_candidates.len() == 1 {
        Some(report_candidates[0].clone())
    } else if candidates.len() == 1 {
        Some(candidates[0].clone())
    } else {
        None
    };
    if let Some(plugin) = selected {
        return Ok(ResolvedLiftSurface {
            surface: plugin.surface.clone(),
            plugin: Some(plugin),
        });
    }
    if report_candidates.len() > 1 {
        return Err(format!(
            "multiple report-capable lift components discovered: {}. Add [authoring.lift] surface or [[plugins]] to select one.",
            report_candidates
                .iter()
                .map(|plugin| plugin.display_name().to_string())
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if candidates.len() > 1 {
        return Err(format!(
            "multiple lift components discovered: {}. Add [authoring.lift] surface or [[plugins]] to select one.",
            candidates
                .iter()
                .map(|plugin| plugin.display_name().to_string())
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if let Some(diagnostic) = component_plan.diagnostics.iter().find(|diagnostic| {
        matches!(
            diagnostic.level,
            crate::component_plan::DiagnosticLevel::Error
        )
    }) {
        return Err(diagnostic.message.clone());
    }
    Err(
        "no lift surface configured. Set [[plugins]] or [authoring] surface in .sugar/config.toml, or install a Sugar kit component for this workspace."
            .to_string(),
    )
}

fn prepare_lift_report_prove_inputs(
    project_root: &Path,
    project_cfg: &ProjectConfig,
    user_cfg: &ProjectConfig,
    resolved_surface: &ResolvedLiftSurface,
    library_bindings: bool,
    configured_with: &[String],
) -> Result<Vec<String>, String> {
    let mut with = configured_with.to_vec();
    if !needs_lift_report_auto_mint(project_root, true) {
        tracing::info!(
            project = %project_root.display(),
            "lift-report-prove: existing .proof input found; skipping auto-mint"
        );
        return Ok(with);
    }

    let plugins = lift_report_mint_plugins(project_root, project_cfg, user_cfg, resolved_surface)?;
    if plugins.is_empty() {
        return Err(
            "no lift plugin available to mint a proof for `lift --report --prove`".to_string(),
        );
    }

    let out_dir = lift_report_auto_mint_dir(project_root);
    tracing::info!(
        project = %project_root.display(),
        out_dir = %out_dir.display(),
        plugins = plugins.len(),
        surfaces = ?plugins.iter().map(|plugin| plugin.surface.as_str()).collect::<Vec<_>>(),
        "lift-report-prove: auto-minting run-scoped proof input"
    );
    let proof_file =
        cmd_mint::mint_lift_plugins_for_report(project_root, &plugins, &out_dir, library_bindings)?;
    tracing::info!(
        project = %project_root.display(),
        out_dir = %out_dir.display(),
        proof_file = proof_file.as_ref().map(|path| path.display().to_string()).unwrap_or_else(|| "(none)".to_string()),
        "lift-report-prove: auto-mint complete"
    );
    with.push(absolute_path(&out_dir).display().to_string());
    Ok(with)
}

fn run_configured_lift_report_graph(
    args: &LiftArgs,
    project_root: &Path,
    plugins: &[PluginEntry],
) -> u8 {
    let out_dir = lift_report_auto_mint_dir(project_root);
    let response = match cmd_mint::lift_plugins_response_for_report(
        project_root,
        plugins,
        &out_dir,
        args.library_bindings,
        args.report_summary,
    ) {
        Ok(response) => response,
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    trace_lift_report_response("after_configured_lift_report_graph", &response);
    if args.report_summary {
        trace_lift_report_checkpoint("before_source_report_summary_from_lift_response");
        let summary = match source_report_summary_from_lift_response(&response, project_root) {
            Ok(summary) => summary,
            Err(error) => {
                eprintln!("{}: {error}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        };
        trace_lift_report_checkpoint("after_source_report_summary_from_lift_response");
        let hard_failure = source_report_summary_has_hard_failures(&summary);
        let rendered = if args.out.json {
            match render_report_summary_json(&summary) {
                Ok(rendered) => rendered,
                Err(error) => {
                    eprintln!(
                        "{}: render lift summary report: {error}",
                        "error".red().bold()
                    );
                    return EXIT_USER_ERROR;
                }
            }
        } else {
            render_report_summary_human(&summary)
        };
        trace_lift_render_checkpoint("after_render_summary_report", rendered.len());
        if let Err(error) = write_output(None, rendered.as_bytes()) {
            eprintln!("{}: {error}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
        trace_lift_render_checkpoint("after_write_summary_report", rendered.len());
        return if hard_failure {
            EXIT_VERIFY_FAIL
        } else {
            EXIT_OK
        };
    }

    trace_lift_report_checkpoint("before_source_report_from_lift_response");
    let mut report = match source_report_from_lift_response(&response, args.contract.as_deref()) {
        Ok(report) => report,
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    report.project_root = Some(project_root.to_path_buf());
    report.source_oracle_routes = source_oracle_routes_for_plugins(plugins);
    trace_lift_source_report("after_source_report_from_lift_response", &report);

    let prove_with = if args.prove {
        match prepare_lift_report_prove_inputs_for_plugins(
            project_root,
            plugins,
            args.library_bindings,
            &args.with,
        ) {
            Ok(with) => with,
            Err(error) => {
                eprintln!("{}: prepare prove report: {error}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        }
    } else {
        Vec::new()
    };
    let prove_report = if args.prove {
        trace_lift_report_checkpoint("before_build_prove_report");
        match cmd_prove::build_prove_report(project_root, &args.z3, &prove_with) {
            Ok(prove_report) => {
                trace_lift_report_checkpoint("after_build_prove_report");
                Some(prove_report)
            }
            Err(error) => {
                eprintln!("{}: prove report: {error}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        }
    } else {
        None
    };
    let mut hard_failure = source_report_has_hard_failures(&report);
    if let Some(prove_report) = &prove_report {
        hard_failure |= report_fmt::report_exit_code(prove_report) != EXIT_OK;
    }
    trace_lift_source_report("before_render_report", &report);
    let rendered = if args.out.json {
        match render_report_json(&report, prove_report.as_ref()) {
            Ok(rendered) => rendered,
            Err(error) => {
                eprintln!("{}: render lift report: {error}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        }
    } else if args.visual {
        render_report_visual(&report, prove_report.as_ref())
    } else {
        render_report_human(&report, prove_report.as_ref())
    };
    trace_lift_render_checkpoint("after_render_report", rendered.len());
    if let Err(error) = write_output(None, rendered.as_bytes()) {
        eprintln!("{}: {error}", "error".red().bold());
        return EXIT_USER_ERROR;
    }
    trace_lift_render_checkpoint("after_write_report", rendered.len());
    if hard_failure {
        EXIT_VERIFY_FAIL
    } else {
        EXIT_OK
    }
}

fn prepare_lift_report_prove_inputs_for_plugins(
    project_root: &Path,
    plugins: &[PluginEntry],
    library_bindings: bool,
    configured_with: &[String],
) -> Result<Vec<String>, String> {
    let mut with = configured_with.to_vec();
    if !needs_lift_report_auto_mint(project_root, true) {
        tracing::info!(
            project = %project_root.display(),
            "lift-report-prove: existing .proof input found; skipping auto-mint"
        );
        return Ok(with);
    }

    let out_dir = lift_report_auto_mint_dir(project_root);
    tracing::info!(
        project = %project_root.display(),
        out_dir = %out_dir.display(),
        plugins = plugins.len(),
        surfaces = ?plugins.iter().map(|plugin| plugin.surface.as_str()).collect::<Vec<_>>(),
        "lift-report-prove: auto-minting configured graph proof input"
    );
    let proof_file =
        cmd_mint::mint_lift_plugins_for_report(project_root, plugins, &out_dir, library_bindings)?;
    tracing::info!(
        project = %project_root.display(),
        out_dir = %out_dir.display(),
        proof_file = proof_file.as_ref().map(|path| path.display().to_string()).unwrap_or_else(|| "(none)".to_string()),
        "lift-report-prove: auto-mint complete"
    );
    with.push(absolute_path(&out_dir).display().to_string());
    Ok(with)
}

fn lift_report_mint_plugins(
    project_root: &Path,
    project_cfg: &ProjectConfig,
    user_cfg: &ProjectConfig,
    resolved_surface: &ResolvedLiftSurface,
) -> Result<Vec<PluginEntry>, String> {
    let project_plugins = project_cfg
        .plugins
        .iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .cloned()
        .collect::<Vec<_>>();
    if !project_plugins.is_empty() {
        return Ok(project_plugins);
    }

    if project_cfg
        .surface_for("lift")
        .or_else(|| user_cfg.surface_for("lift"))
        .is_none()
    {
        let component_plan = crate::component_plan::plan_workspace(project_root);
        let component_plugins = component_plan
            .plugins
            .iter()
            .filter(|plugin| plugin.is_lift_plugin())
            .cloned()
            .collect::<Vec<_>>();
        if !component_plugins.is_empty() {
            return Ok(component_plugins);
        }
        if let Some(diagnostic) = component_plan.diagnostics.iter().find(|diagnostic| {
            matches!(
                diagnostic.level,
                crate::component_plan::DiagnosticLevel::Error
            )
        }) {
            return Err(diagnostic.message.clone());
        }
    }

    if let Some(plugin) = &resolved_surface.plugin {
        return Ok(vec![plugin.clone()]);
    }

    Ok(vec![PluginEntry {
        kind: Some("lift".to_string()),
        surface: resolved_surface.surface.clone(),
        ..PluginEntry::default()
    }])
}

fn needs_lift_report_auto_mint(project_root: &Path, prove: bool) -> bool {
    prove && !project_has_proof_files(project_root)
}

fn project_has_proof_files(project_root: &Path) -> bool {
    if !project_root.exists() {
        return false;
    }
    std::fs::read_dir(project_root)
        .ok()
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .any(|entry| {
            entry.file_type().is_ok_and(|ty| ty.is_file())
                && entry.path().extension().is_some_and(|ext| ext == "proof")
        })
}

fn lift_report_auto_mint_dir(project_root: &Path) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    project_root
        .join(".sugar")
        .join("runs")
        .join(format!("lift-report-prove-{}-{nanos}", std::process::id()))
        .join("proofs")
}

fn absolute_path(path: &Path) -> PathBuf {
    if path.is_absolute() {
        return path.to_path_buf();
    }
    std::env::current_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join(path)
}

fn lift_options_for_configured_surface(
    project_cfg: &ProjectConfig,
    surface: &str,
) -> LiftPluginOptions {
    let Some(plugin) = matching_lift_plugin(project_cfg, surface) else {
        return LiftPluginOptions::default();
    };
    LiftPluginOptions {
        ..lift_options_for_plugin(plugin)
    }
}

fn lift_options_for_plugin(plugin: &PluginEntry) -> LiftPluginOptions {
    LiftPluginOptions {
        workspace_override: plugin.workspace_override.clone(),
        emit: plugin.emit.clone(),
        layer: plugin.layer.clone(),
        ..Default::default()
    }
}

fn source_oracle_routes_for_plugins(plugins: &[PluginEntry]) -> Vec<SourceOracleRoute> {
    plugins
        .iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .map(|plugin| {
            source_oracle_route_for_surface(&plugin.surface, plugin.workspace_override.clone())
        })
        .collect()
}

fn source_oracle_route_for_surface(
    surface: &str,
    workspace_override: Option<String>,
) -> SourceOracleRoute {
    SourceOracleRoute {
        surface: surface.to_string(),
        workspace_override,
    }
}

fn matching_lift_plugin<'a>(
    project_cfg: &'a ProjectConfig,
    surface: &str,
) -> Option<&'a PluginEntry> {
    project_cfg
        .plugins
        .iter()
        .find(|plugin| plugin.is_lift_plugin() && plugin.surface == surface)
}

#[derive(Debug, Clone, PartialEq)]
struct LiftSourceReport {
    ledger: Value,
    audits: Vec<Value>,
    factory_audits: Vec<Value>,
    factory_walk: Vec<Value>,
    assertion_surface_audits: Vec<Value>,
    source_mementos: Vec<Value>,
    contracts: Vec<Value>,
    call_edges: Vec<Value>,
    vendor_conjoins: Vec<VendorConjoinReport>,
    project_root: Option<PathBuf>,
    source_oracle_routes: Vec<SourceOracleRoute>,
}

#[derive(Debug, Clone, PartialEq)]
struct LiftReportSummary {
    ledger: Value,
    factory: FactoryAccountingSummary,
    unresolved_factory_sites: Vec<Value>,
    factory_walk: Vec<Value>,
    project_root: Option<PathBuf>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SourceOracleRoute {
    surface: String,
    workspace_override: Option<String>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct FactoryAccountingSummary {
    sites: usize,
    warranted: usize,
    refused: usize,
    support: usize,
    unresolved: usize,
}

#[derive(Debug, Clone, PartialEq)]
struct VendorConjoinReport {
    call: String,
    local_contract: String,
    local_fact: String,
    bridge_source_symbol: String,
    vendor_contract: String,
    vendor_contract_cid: String,
    vendor_proof_cid: Option<String>,
    vendor_post: String,
    instantiated_post: String,
    vendor_source: Option<VendorSourceResolution>,
}

#[derive(Debug, Clone, PartialEq)]
enum VendorSourceResolution {
    Resolved(String),
    Absent(String),
    Drifted(String),
}

const SOURCE_LEDGER_FIELDS: [&str; 7] = [
    "source_loci",
    "source_warranted",
    "source_support",
    "source_refused",
    "source_inactive",
    "source_unresolved",
    "unclassified_source",
];

const LIFT_REPORT_TRACE_EVERY: usize = 500;
const LIFT_REPORT_RSS_JUMP_KIB: u64 = 64 * 1024;

fn lift_report_array_len(value: &Value, keys: &[&str]) -> usize {
    keys.iter()
        .find_map(|key| value.get(*key).and_then(Value::as_array).map(Vec::len))
        .unwrap_or(0)
}

fn current_rss_kib() -> Option<u64> {
    #[cfg(target_os = "linux")]
    {
        let status = std::fs::read_to_string("/proc/self/status").ok()?;
        status.lines().find_map(|line| {
            let rest = line.strip_prefix("VmRSS:")?;
            rest.split_whitespace().next()?.parse::<u64>().ok()
        })
    }
    #[cfg(not(target_os = "linux"))]
    {
        None
    }
}

fn lift_report_ledger_count(ledger: &Value, keys: &[&str]) -> u64 {
    keys.iter()
        .find_map(|key| ledger.get(*key).and_then(Value::as_u64))
        .unwrap_or(0)
}

fn trace_lift_report_checkpoint(stage: &'static str) {
    let rss_kib = current_rss_kib();
    tracing::info!(
        stage = stage,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        "lift-report memory checkpoint"
    );
}

fn trace_lift_collection_checkpoint(stage: &'static str, rows: usize) {
    let rss_kib = current_rss_kib();
    tracing::info!(
        stage = stage,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        rows = rows,
        "lift-report memory checkpoint"
    );
}

fn trace_lift_report_response(stage: &'static str, response: &Value) {
    let ledger = response.get("sourceLedger").unwrap_or(&Value::Null);
    let rss_kib = current_rss_kib();
    tracing::info!(
        stage = stage,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        source_loci = lift_report_ledger_count(ledger, &["source_loci"]),
        source_warranted = lift_report_ledger_count(ledger, &["source_warranted"]),
        source_unresolved =
            lift_report_ledger_count(ledger, &["source_unresolved", "unclassified_source"]),
        source_audits = lift_report_array_len(response, &["sourceAudits", "source_audits"]),
        factory_audits = lift_report_array_len(response, &["factoryAudits", "factory_audits"]),
        assertion_surface_audits = lift_report_array_len(
            response,
            &["assertionSurfaceAudits", "assertion_surface_audits"]
        ),
        source_mementos = lift_report_array_len(response, &["sourceMementos", "source_mementos"]),
        contracts = lift_report_array_len(response, &["ir"]),
        call_edges = lift_report_array_len(response, &["callEdges", "call_edges"]),
        vendor_conjoins = lift_report_array_len(
            response,
            &[
                "vendorConjoins",
                "vendor_conjoins",
                "linkerConjoins",
                "linker_conjoins"
            ]
        ),
        "lift-report memory checkpoint"
    );
}

fn trace_lift_source_report(stage: &'static str, report: &LiftSourceReport) {
    let rss_kib = current_rss_kib();
    tracing::info!(
        stage = stage,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        source_loci = lift_report_ledger_count(&report.ledger, &["source_loci"]),
        source_warranted = lift_report_ledger_count(&report.ledger, &["source_warranted"]),
        source_unresolved = lift_report_ledger_count(
            &report.ledger,
            &["source_unresolved", "unclassified_source"]
        ),
        source_audits = report.audits.len(),
        factory_audits = report.factory_audits.len(),
        assertion_surface_audits = report.assertion_surface_audits.len(),
        source_mementos = report.source_mementos.len(),
        contracts = report.contracts.len(),
        call_edges = report.call_edges.len(),
        vendor_conjoins = report.vendor_conjoins.len(),
        "lift-report memory checkpoint"
    );
}

fn trace_lift_render_checkpoint(stage: &'static str, rendered_bytes: usize) {
    let rss_kib = current_rss_kib();
    tracing::info!(
        stage = stage,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        rendered_bytes = rendered_bytes,
        "lift-report memory checkpoint"
    );
}

fn clone_matching_report_values(
    stage: &'static str,
    rows: &[Value],
    mut matches: impl FnMut(&Value) -> bool,
    mut map: impl FnMut(Value) -> Value,
) -> Vec<Value> {
    let mut selected = Vec::new();
    for (input_index, row) in rows.iter().enumerate() {
        if !matches(row) {
            continue;
        }
        let selected_index = selected.len();
        if selected_index % LIFT_REPORT_TRACE_EVERY == 0 {
            trace_lift_report_value_progress(
                stage,
                "before_clone",
                input_index,
                selected_index,
                rows.len(),
                row,
                None,
            );
        }
        let before = current_rss_kib();
        let cloned = map(row.clone());
        let after = current_rss_kib();
        if selected_index % LIFT_REPORT_TRACE_EVERY == 0 {
            trace_lift_report_value_progress(
                stage,
                "after_clone",
                input_index,
                selected_index,
                rows.len(),
                row,
                rss_delta_kib(before, after),
            );
        }
        if rss_delta_kib(before, after).unwrap_or(0) >= LIFT_REPORT_RSS_JUMP_KIB {
            trace_lift_report_value_progress(
                stage,
                "rss_jump_after_clone",
                input_index,
                selected_index,
                rows.len(),
                row,
                rss_delta_kib(before, after),
            );
        }
        selected.push(cloned);
    }
    selected
}

fn rss_delta_kib(before: Option<u64>, after: Option<u64>) -> Option<u64> {
    Some(after?.saturating_sub(before?))
}

fn trace_lift_report_value_progress(
    stage: &'static str,
    event: &'static str,
    input_index: usize,
    selected_index: usize,
    total_rows: usize,
    value: &Value,
    rss_delta_kib: Option<u64>,
) {
    let rss_kib = current_rss_kib();
    let (source_file, source_line) = report_value_source_hint(value);
    tracing::info!(
        stage = stage,
        event = event,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        rss_delta_kib = rss_delta_kib.unwrap_or_default(),
        input_index = input_index,
        selected_index = selected_index,
        total_rows = total_rows,
        value_name = report_value_name(value),
        source_file = source_file,
        source_line = source_line,
        "lift-report memory checkpoint"
    );
}

fn report_value_name(value: &Value) -> &str {
    contract_value_name(value)
        .or_else(|| contract_name(value))
        .or_else(|| source_function_name(value))
        .or_else(|| value.get("role").and_then(Value::as_str))
        .unwrap_or("<unknown>")
}

fn report_value_source_hint(value: &Value) -> (&str, i64) {
    contract_source_warrant(value)
        .map(source_file_line_hint)
        .unwrap_or_else(|| source_file_line_hint(value))
}

fn source_file_line_hint(source: &Value) -> (&str, i64) {
    let file = source
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown file>");
    let line = source
        .get("line")
        .and_then(Value::as_i64)
        .or_else(|| {
            source
                .get("span")
                .and_then(|span| span.get("start_line"))
                .and_then(Value::as_i64)
        })
        .unwrap_or(-1);
    (file, line)
}

fn source_report_summary_from_lift_response(
    response: &Value,
    project_root: &Path,
) -> Result<LiftReportSummary, String> {
    if let Some(refused) = response.get("sugar-refused").and_then(Value::as_str) {
        let reason = response
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("(no reason emitted)");
        return Err(format!(
            "lift response was REFUSED upstream (`{refused}`): {reason}. The source-audit ledger could not be measured -- this is a hard failure, not an empty ledger."
        ));
    }
    let ledger = response
        .get("sourceLedger")
        .filter(|value| value.is_object())
        .ok_or_else(|| {
            "lift response did not include sourceLedger; the kit must emit source-audit accounting"
                .to_string()
        })?;
    if ledger.get("source_unresolved").is_none() && ledger.get("unclassified_source").is_none() {
        return Err(
            "lift response sourceLedger is missing source_unresolved; cannot measure unresolved source coverage"
                .to_string(),
        );
    }

    let moved_support_loci = response
        .get("sourceAudits")
        .and_then(Value::as_array)
        .map(|audits| {
            audits
                .iter()
                .map(|audit| normalize_source_audit_support(audit.clone()).1)
                .sum::<i64>()
        })
        .unwrap_or(0);
    let ledger = normalize_source_ledger_support(ledger.clone(), moved_support_loci);
    let factory = factory_accounting_summary_from_response(response)?;
    let unresolved_factory_sites = unresolved_factory_sites_from_response(response)?;
    let factory_walk = factory_walk_from_response(response)?;
    Ok(LiftReportSummary {
        ledger,
        factory,
        unresolved_factory_sites,
        factory_walk,
        project_root: Some(project_root.to_path_buf()),
    })
}

fn factory_walk_from_response(response: &Value) -> Result<Vec<Value>, String> {
    let rows = response
        .get("factoryAuditSummary")
        .and_then(|summary| summary.get("factoryWalk"))
        .and_then(Value::as_array)
        .cloned()
        .ok_or_else(|| {
            "lift response did not include factoryAuditSummary.factoryWalk; the kit must emit the memento roll-call report"
                .to_string()
        })?;
    for row in &rows {
        if row.get("term").is_some() || row.get("site").is_some() || row.get("source").is_some() {
            return Err(
                "factoryAuditSummary.factoryWalk carried plaintext source/term; walk rows must carry SourceMemento pins only"
                    .to_string(),
            );
        }
    }
    Ok(rows
        .into_iter()
        .map(normalize_factory_gap_walk_row)
        .collect())
}

fn normalize_factory_gap_walk_row(row: Value) -> Value {
    let status = normalized_source_status(row.get("status").and_then(Value::as_str));
    if status != "unresolved" {
        return row;
    }
    match row {
        Value::Object(mut object) => {
            object.insert(
                "status".to_string(),
                Value::String("unresolved".to_string()),
            );
            object.insert("verdict".to_string(), Value::String("gap".to_string()));
            object.insert("output".to_string(), Value::String("gap".to_string()));
            Value::Object(object)
        }
        other => other,
    }
}

fn factory_accounting_summary_from_response(
    response: &Value,
) -> Result<FactoryAccountingSummary, String> {
    let summary = response
        .get("factoryAuditSummary")
        .ok_or_else(|| {
            "lift response did not include factoryAuditSummary; the kit must emit factory walk accounting"
                .to_string()
        })?;
    let status_counts = summary.get("statusCounts").ok_or_else(|| {
        "lift response factoryAuditSummary is missing statusCounts; cannot measure factory coverage"
            .to_string()
    })?;
    let sites = summary
        .get("emittedRows")
        .and_then(Value::as_u64)
        .map(|value| value as usize)
        .ok_or_else(|| {
            "lift response factoryAuditSummary is missing emittedRows; cannot measure factory coverage"
                .to_string()
        })?;
    Ok(FactoryAccountingSummary {
        sites,
        warranted: status_count(status_counts, "warranted"),
        refused: status_count(status_counts, "refused"),
        support: status_count(status_counts, "support"),
        unresolved: status_count(status_counts, "unresolved"),
    })
}

fn unresolved_factory_sites_from_response(response: &Value) -> Result<Vec<Value>, String> {
    let rows = response
        .get("factoryAuditSummary")
        .and_then(|summary| summary.get("unresolvedSites"))
        .and_then(Value::as_array)
        .ok_or_else(|| {
            "lift response factoryAuditSummary is missing unresolvedSites; cannot report unresolved factory loci"
                .to_string()
        })?;
    for row in rows {
        if row.get("term").is_some() || row.get("site").is_some() || row.get("source").is_some() {
            return Err(
                "factoryAuditSummary.unresolvedSites carried plaintext source/term; unresolved rows must carry SourceMemento pins only"
                    .to_string(),
            );
        }
    }
    Ok(rows.to_vec())
}

fn status_count(value: &Value, status: &str) -> usize {
    value
        .get(status)
        .and_then(Value::as_u64)
        .map(|count| count as usize)
        .unwrap_or(0)
}

fn source_report_from_lift_response(
    response: &Value,
    contract_filter: Option<&str>,
) -> Result<LiftSourceReport, String> {
    // INSTRUMENT-NEVER-DARK: a response REFUSED upstream (e.g. the transport's
    // finite-or-refuse byte bound swapped the whole response for a `sugar-refused`
    // marker) carries no sourceLedger. Surface THAT as a loud, named hard-error -- not
    // the generic "missing sourceLedger" (which reads like a kit bug and hides the real
    // cause), and never a silent empty headline. A blind aggregate ledger cannot catch a
    // false discharge, so a clipped/over-bound response MUST fail visibly, naming the clip.
    if let Some(refused) = response.get("sugar-refused").and_then(Value::as_str) {
        let reason = response
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("(no reason emitted)");
        return Err(format!(
            "lift response was REFUSED upstream (`{refused}`): {reason}. The source-audit ledger could not be measured -- this is a hard failure, not an empty ledger."
        ));
    }
    let ledger = response
        .get("sourceLedger")
        .filter(|value| value.is_object())
        .ok_or_else(|| {
            "lift response did not include sourceLedger; the kit must emit source-audit accounting"
                .to_string()
        })?;
    if ledger.get("source_unresolved").is_none() && ledger.get("unclassified_source").is_none() {
        return Err(
            "lift response sourceLedger is missing source_unresolved; cannot measure unresolved source coverage"
                .to_string(),
        );
    }

    let audits = response
        .get("sourceAudits")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            "lift response did not include sourceAudits; the kit must emit line-level source accounting"
                .to_string()
        })?;

    let mut moved_support_loci = 0;
    let filtered_audits: Vec<Value> = audits
        .iter()
        .filter(|audit| {
            contract_filter.is_none_or(|filter| {
                contract_name(audit)
                    .or_else(|| audit.get("role").and_then(Value::as_str))
                    .is_some_and(|name| name.contains(filter))
            })
        })
        .map(|audit| {
            let (audit, moved) = normalize_source_audit_support(audit.clone());
            moved_support_loci += moved;
            audit
        })
        .collect();
    tracing::info!(
        stage = "source_report.filtered_audits",
        rss_kib = current_rss_kib().unwrap_or_default(),
        rss_available = current_rss_kib().is_some(),
        audits = filtered_audits.len(),
        moved_support_loci = moved_support_loci,
        contract_filter = contract_filter.unwrap_or("<none>"),
        "lift-report memory checkpoint"
    );

    if contract_filter.is_some() && filtered_audits.is_empty() {
        return Err(format!(
            "no source audits matched contract filter `{}`",
            contract_filter.unwrap()
        ));
    }

    let ledger = if contract_filter.is_some() {
        recompute_source_ledger(&filtered_audits)
    } else {
        normalize_source_ledger_support(ledger.clone(), moved_support_loci)
    };
    trace_lift_collection_checkpoint(
        "source_report.ledger",
        ledger.as_object().map_or(0, Map::len),
    );
    let factory_audits = matching_report_factory_audits(response, contract_filter)?;
    trace_lift_collection_checkpoint("source_report.factory_audits", factory_audits.len());
    let factory_walk = matching_report_factory_walk(response, contract_filter)?;
    trace_lift_collection_checkpoint("source_report.factory_walk", factory_walk.len());
    let assertion_surface_audits =
        matching_report_assertion_surface_audits(response, contract_filter);
    trace_lift_collection_checkpoint(
        "source_report.assertion_surface_audits",
        assertion_surface_audits.len(),
    );
    let contracts = matching_report_contracts(response, contract_filter, &filtered_audits);
    trace_lift_collection_checkpoint("source_report.contracts", contracts.len());
    let call_edges = matching_report_call_edges(response, contract_filter, &filtered_audits);
    trace_lift_collection_checkpoint("source_report.call_edges", call_edges.len());
    let source_mementos =
        matching_report_source_mementos(response, contract_filter, &filtered_audits)?;
    trace_lift_collection_checkpoint("source_report.source_mementos", source_mementos.len());
    let vendor_conjoins = vendor_conjoins_from_lift_response(response, contract_filter)?;
    trace_lift_collection_checkpoint("source_report.vendor_conjoins", vendor_conjoins.len());

    Ok(LiftSourceReport {
        ledger,
        audits: filtered_audits,
        factory_audits,
        factory_walk,
        assertion_surface_audits,
        source_mementos,
        contracts,
        call_edges,
        vendor_conjoins,
        project_root: None,
        source_oracle_routes: Vec::new(),
    })
}

fn matching_report_source_mementos(
    response: &Value,
    contract_filter: Option<&str>,
    audits: &[Value],
) -> Result<Vec<Value>, String> {
    let mementos = response
        .get("sourceMementos")
        .or_else(|| response.get("source_mementos"))
        .and_then(Value::as_array)
        .ok_or_else(|| {
            "lift response did not include sourceMementos; the kit must emit source mementos for envelope minting"
                .to_string()
        })?;
    if contract_filter.is_none() {
        return Ok(clone_matching_report_values(
            "matching_report_source_mementos",
            mementos,
            |_| true,
            |row| row,
        ));
    }

    let audit_bases = audits
        .iter()
        .filter_map(contract_name)
        .map(contract_group_key)
        .collect::<Vec<_>>();
    let filter = contract_filter.unwrap();
    Ok(clone_matching_report_values(
        "matching_report_source_mementos",
        mementos,
        |memento| {
            let names = [
                memento.get("claimName").and_then(Value::as_str),
                memento.get("contractName").and_then(Value::as_str),
                memento.get("eufName").and_then(Value::as_str),
                memento.get("role").and_then(Value::as_str),
                source_function_name(memento),
            ];
            names
                .into_iter()
                .flatten()
                .any(|name| name.contains(filter))
                || names.into_iter().flatten().any(|name| {
                    let group = contract_group_key(name);
                    audit_bases.iter().any(|base| base == &group)
                })
        },
        |row| row,
    ))
}

fn matching_report_contracts(
    response: &Value,
    contract_filter: Option<&str>,
    audits: &[Value],
) -> Vec<Value> {
    let Some(contracts) = response.get("ir").and_then(Value::as_array) else {
        return Vec::new();
    };
    let audit_bases = audits
        .iter()
        .filter_map(contract_name)
        .map(contract_group_key)
        .collect::<Vec<_>>();
    clone_matching_report_values(
        "matching_report_contracts",
        contracts,
        |contract| {
            let Some(name) = contract_value_name(contract) else {
                return false;
            };
            let group = contract_group_key(name);
            contract_filter.is_none_or(|filter| name.contains(filter))
                || audit_bases.iter().any(|base| base == &group)
        },
        |row| row,
    )
}

fn matching_report_call_edges(
    response: &Value,
    contract_filter: Option<&str>,
    audits: &[Value],
) -> Vec<Value> {
    let Some(edges) = response
        .get("callEdges")
        .or_else(|| response.get("call_edges"))
        .and_then(Value::as_array)
    else {
        return Vec::new();
    };
    if contract_filter.is_none() {
        return clone_matching_report_values(
            "matching_report_call_edges",
            edges,
            |_| true,
            |row| row,
        );
    }

    let audit_bases = audits
        .iter()
        .filter_map(contract_name)
        .map(contract_group_key)
        .collect::<Vec<_>>();
    let filter = contract_filter.unwrap();
    clone_matching_report_values(
        "matching_report_call_edges",
        edges,
        |edge| call_edge_matches_filter(edge, filter, &audit_bases),
        |row| row,
    )
}

fn call_edge_matches_filter(edge: &Value, filter: &str, audit_bases: &[String]) -> bool {
    [
        edge.get("sourceContract").and_then(Value::as_str),
        edge.get("source_contract").and_then(Value::as_str),
        edge.get("targetContract").and_then(Value::as_str),
        edge.get("target_contract").and_then(Value::as_str),
        edge.get("targetSymbol").and_then(Value::as_str),
        edge.get("target_symbol").and_then(Value::as_str),
        edge.get("sourceContractCid").and_then(Value::as_str),
        edge.get("source_contract_cid").and_then(Value::as_str),
        edge.get("targetContractCid").and_then(Value::as_str),
        edge.get("target_contract_cid").and_then(Value::as_str),
    ]
    .into_iter()
    .flatten()
    .any(|value| value.contains(filter))
        || [
            edge.get("sourceContract").and_then(Value::as_str),
            edge.get("source_contract").and_then(Value::as_str),
            edge.get("targetContract").and_then(Value::as_str),
            edge.get("target_contract").and_then(Value::as_str),
        ]
        .into_iter()
        .flatten()
        .any(|name| {
            let group = contract_group_key(name);
            audit_bases.iter().any(|base| base == &group)
        })
}

fn matching_report_factory_audits(
    response: &Value,
    contract_filter: Option<&str>,
) -> Result<Vec<Value>, String> {
    let Some(rows) = response
        .get("factoryAudits")
        .or_else(|| response.get("factory_audits"))
        .and_then(Value::as_array)
    else {
        return Ok(Vec::new());
    };
    for row in rows {
        if row.get("term").is_some() || row.get("site").is_some() || row.get("source").is_some() {
            return Err(
                "factoryAudits carried plaintext source/term; RPC rows must carry SourceMemento pins only"
                    .to_string(),
            );
        }
    }
    Ok(clone_matching_report_values(
        "matching_report_factory_audits",
        rows,
        |row| contract_filter.is_none_or(|filter| factory_audit_matches_filter(row, filter)),
        |row| row,
    ))
}

fn matching_report_factory_walk(
    response: &Value,
    contract_filter: Option<&str>,
) -> Result<Vec<Value>, String> {
    let Some(rows) = response
        .get("factoryAuditSummary")
        .and_then(|summary| summary.get("factoryWalk"))
        .and_then(Value::as_array)
    else {
        return Ok(Vec::new());
    };
    for row in rows {
        if row.get("term").is_some() || row.get("site").is_some() || row.get("source").is_some() {
            return Err(
                "factoryAuditSummary.factoryWalk carried plaintext source/term; walk rows must carry SourceMemento pins only"
                    .to_string(),
            );
        }
    }
    Ok(clone_matching_report_values(
        "matching_report_factory_walk",
        rows,
        |row| contract_filter.is_none_or(|filter| factory_audit_matches_filter(row, filter)),
        normalize_factory_gap_walk_row,
    ))
}

fn matching_report_assertion_surface_audits(
    response: &Value,
    contract_filter: Option<&str>,
) -> Vec<Value> {
    let Some(rows) = response
        .get("assertionSurfaceAudits")
        .or_else(|| response.get("assertion_surface_audits"))
        .and_then(Value::as_array)
    else {
        return Vec::new();
    };
    clone_matching_report_values(
        "matching_report_assertion_surface_audits",
        rows,
        |row| {
            contract_filter.is_none_or(|filter| assertion_surface_audit_matches_filter(row, filter))
        },
        normalize_assertion_surface_audit,
    )
}

fn normalize_assertion_surface_audit(mut row: Value) -> Value {
    let has_facts = assertion_surface_fact_count(&row) > 0;
    let Some(object) = row.as_object_mut() else {
        return row;
    };

    let support_facts = object
        .remove("supportFacts")
        .or_else(|| object.remove("support_facts"));
    if let Some(support_facts) = support_facts {
        object.insert("auxiliaryFacts".to_string(), support_facts);
    }
    if !has_facts {
        object.insert(
            "status".to_string(),
            Value::String("no-facts-emitted".to_string()),
        );
    }

    row
}

fn assertion_surface_audit_matches_filter(row: &Value, filter: &str) -> bool {
    [
        row.get("surface").and_then(Value::as_str),
        row.get("assertionSource")
            .or_else(|| row.get("assertion_source"))
            .and_then(Value::as_str),
        row.get("file").and_then(Value::as_str),
        row.get("status").and_then(Value::as_str),
        row.get("sourceStatus")
            .or_else(|| row.get("source_status"))
            .and_then(Value::as_str),
        row.get("reason").and_then(Value::as_str),
    ]
    .into_iter()
    .flatten()
    .any(|text| text.contains(filter))
        || row
            .get("facts")
            .and_then(Value::as_array)
            .is_some_and(|facts| {
                facts.iter().any(|fact| {
                    fact.get("contract")
                        .or_else(|| fact.get("contractName"))
                        .or_else(|| fact.get("contract_name"))
                        .and_then(Value::as_str)
                        .is_some_and(|contract| contract.contains(filter))
                })
            })
}

fn factory_audit_matches_filter(row: &Value, filter: &str) -> bool {
    [
        row.get("file").and_then(Value::as_str),
        row.get("requested_role").and_then(Value::as_str),
        row.get("selected").and_then(Value::as_str),
        row.get("status").and_then(Value::as_str),
        row.get("reason").and_then(Value::as_str),
    ]
    .into_iter()
    .flatten()
    .any(|text| text.contains(filter))
}

fn recompute_source_ledger(audits: &[Value]) -> Value {
    let mut ledger = Map::new();
    for field in SOURCE_LEDGER_FIELDS {
        let total = audits
            .iter()
            .map(|audit| {
                audit
                    .get("totals")
                    .map(|totals| source_total_for_field(totals, field))
                    .unwrap_or(0)
            })
            .sum::<i64>();
        ledger.insert(field.to_string(), Value::Number(total.into()));
    }
    Value::Object(ledger)
}

fn normalize_source_ledger_support(mut ledger: Value, moved_support_loci: i64) -> Value {
    strip_source_refuted_field(&mut ledger);
    if moved_support_loci <= 0 {
        return ledger;
    }
    adjust_source_support_totals(&mut ledger, moved_support_loci);
    ledger
}

fn strip_source_refuted_field(value: &mut Value) {
    if let Some(object) = value.as_object_mut() {
        object.remove("source_refuted");
    }
}

fn normalize_source_audit_support(mut audit: Value) -> (Value, i64) {
    let Some(audit_object) = audit.as_object_mut() else {
        return (audit, 0);
    };
    if let Some(totals) = audit_object.get_mut("totals") {
        strip_source_refuted_field(totals);
    }

    let has_full_loci = audit_object.get("loci").and_then(Value::as_array).is_some();
    let moved_loci = normalize_source_loci_array(audit_object.get_mut("loci"), true);
    let support_kind_counts = audit_object
        .get("supportKindCounts")
        .or_else(|| audit_object.get("support_kind_counts"))
        .cloned();
    let moved_ast_counts = normalize_source_ast_type_counts(
        audit_object.get_mut("ast_type_counts"),
        support_kind_counts.as_ref(),
    );
    normalize_source_loci_array(audit_object.get_mut("sample_loci"), false);

    let moved_for_totals = if has_full_loci {
        moved_loci
    } else {
        moved_ast_counts
    };
    if moved_for_totals > 0 {
        if let Some(totals) = audit_object.get_mut("totals") {
            adjust_source_support_totals(totals, moved_for_totals);
        }
    }

    (audit, moved_for_totals)
}

fn normalize_source_loci_array(value: Option<&mut Value>, count_toward_totals: bool) -> i64 {
    let Some(Value::Array(loci)) = value else {
        return 0;
    };

    let mut moved = 0;
    for locus in loci {
        if source_locus_support_is_not_inert(locus) {
            if count_toward_totals {
                moved += 1;
            }
            mark_source_locus_unresolved(locus);
        }
    }
    moved
}

fn source_locus_support_is_not_inert(locus: &Value) -> bool {
    normalized_source_status(locus.get("status").and_then(Value::as_str)) == "support"
        && !source_support_kind_is_inert(locus)
}

fn source_support_kind_is_inert(locus: &Value) -> bool {
    locus
        .get("supportKind")
        .or_else(|| locus.get("support_kind"))
        .and_then(Value::as_str)
        == Some("inert")
}

fn mark_source_locus_unresolved(locus: &mut Value) {
    let Some(object) = locus.as_object_mut() else {
        return;
    };
    object.insert(
        "status".to_string(),
        Value::String("unclassified".to_string()),
    );
    append_report_reason(
        object,
        "support is reserved for kit-marked inert source loci",
    );
}

fn normalize_source_ast_type_counts(
    value: Option<&mut Value>,
    support_kind_counts: Option<&Value>,
) -> i64 {
    let Some(Value::Object(by_status)) = value else {
        return 0;
    };

    let mut moved_counts = Vec::new();
    let mut remove_support_status = false;
    if let Some(Value::Object(support_counts)) = by_status.get_mut("support") {
        let keys = support_counts.keys().cloned().collect::<Vec<_>>();
        for kind in keys {
            let count = support_counts
                .get(&kind)
                .and_then(Value::as_i64)
                .unwrap_or(0)
                .max(0);
            let inert_count = inert_support_count_for_kind(support_kind_counts, &kind)
                .max(0)
                .min(count);
            if inert_count > 0 {
                support_counts.insert(kind.clone(), Value::Number(inert_count.into()));
            } else {
                support_counts.remove(&kind);
            }
            let moved_count = count - inert_count;
            if moved_count <= 0 {
                continue;
            }
            moved_counts.push((kind, moved_count));
        }
        remove_support_status = support_counts.is_empty();
    }
    if remove_support_status {
        by_status.remove("support");
    }

    let moved_total = moved_counts.iter().map(|(_, count)| *count).sum::<i64>();
    if moved_counts.is_empty() {
        return 0;
    }

    let target = by_status
        .entry("unclassified".to_string())
        .or_insert_with(|| Value::Object(Map::new()));
    if !target.is_object() {
        *target = Value::Object(Map::new());
    }
    let Some(target_counts) = target.as_object_mut() else {
        return moved_total;
    };
    for (kind, count) in moved_counts {
        let next = target_counts
            .get(&kind)
            .and_then(Value::as_i64)
            .unwrap_or(0)
            + count;
        target_counts.insert(kind, Value::Number(next.into()));
    }

    moved_total
}

fn inert_support_count_for_kind(support_kind_counts: Option<&Value>, kind: &str) -> i64 {
    support_kind_counts
        .and_then(|counts| counts.get("inert"))
        .and_then(Value::as_object)
        .and_then(|inert| inert.get(kind))
        .and_then(Value::as_i64)
        .unwrap_or(0)
}

fn adjust_source_support_totals(value: &mut Value, moved_support_loci: i64) {
    if moved_support_loci <= 0 {
        return;
    }
    let Some(object) = value.as_object_mut() else {
        return;
    };

    let support = object
        .get("source_support")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        .saturating_sub(moved_support_loci)
        .max(0);
    object.insert("source_support".to_string(), Value::Number(support.into()));

    let unresolved = object
        .get("source_unresolved")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        .max(
            object
                .get("unclassified_source")
                .and_then(Value::as_i64)
                .unwrap_or(0),
        )
        + moved_support_loci;
    object.insert(
        "source_unresolved".to_string(),
        Value::Number(unresolved.into()),
    );
    object.insert(
        "unclassified_source".to_string(),
        Value::Number(unresolved.into()),
    );
}

fn append_report_reason(object: &mut Map<String, Value>, reason: &str) {
    let existing = object
        .get("reason")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let reason = if existing.is_empty() {
        reason.to_string()
    } else if existing.contains(reason) {
        existing.to_string()
    } else {
        format!("{existing}; {reason}")
    };
    object.insert("reason".to_string(), Value::String(reason));
}

fn source_total_for_field(totals: &Value, field: &str) -> i64 {
    match field {
        "source_unresolved" | "unclassified_source" => source_unresolved_count(totals),
        _ => totals.get(field).and_then(Value::as_i64).unwrap_or(0),
    }
}

/// The symbol-under-test for a lifted assertion contract: each lifted assertion
/// is one candidate UNIVERSE about a callsite. The contract is named
/// `SYMBOL#euf#callresult_SYMBOL(args)::assertion` (args after `#euf#`); stripping
/// the arg tail groups the per-argument universes of one method under that method.
fn universe_symbol(name: &str) -> String {
    let n = name.strip_prefix("consistency:").unwrap_or(name);
    let n = n.split("#euf#").next().unwrap_or(n);
    n.strip_suffix("::assertion").unwrap_or(n).to_string()
}

/// One distinct universe within a method group: a single canonical contract
/// identity (its `contract_cid`), the FOL reading of its claim, and how many
/// lifted callsites collapsed onto it. Counting by CID is what tells "one
/// universe emitted N times" (identical copy-pasted asserts mint byte-identical
/// contracts) apart from "N genuinely distinct universes".
struct MethodUniverse {
    cid: String,
    reading: String,
    occurrences: usize,
}

/// `method -> [distinct universe]`. Two lifted contracts are the SAME universe
/// iff they share a canonical `contract_cid` — the identity `mint` assigns and
/// the verifier indexes by. The per-occurrence inflation of the raw contract
/// list (one contract per callsite, byte-identical across copy-pasted tests)
/// collapses here; universes that merely RENDER alike but differ in identity
/// (e.g. the same shape at different integer widths, whose sort the FOL renderer
/// elides) stay separate, because their CIDs differ. The recompute funnels
/// through the canonical `contract_cid_of_ir_decl`, so this never invents a
/// second identity scheme. A decl with no mintable contract identity (rare —
/// report contracts ARE the decls `mint` consumes) falls back to its reading
/// string so it is still accounted for, never silently dropped.
fn distinct_universes_per_method(contracts: &[Value]) -> BTreeMap<String, Vec<MethodUniverse>> {
    let mut m: BTreeMap<String, Vec<MethodUniverse>> = BTreeMap::new();
    for c in contracts {
        let Some(name) = contract_value_name(c) else {
            continue;
        };
        let reading = contract_universe_reading(c);
        let cid = contract_cid_of_ir_decl(c).unwrap_or_else(|| format!("reading:{reading}"));
        let universes = m.entry(universe_symbol(name)).or_default();
        match universes.iter_mut().find(|u| u.cid == cid) {
            Some(existing) => existing.occurrences += 1,
            None => universes.push(MethodUniverse {
                cid,
                reading,
                occurrences: 1,
            }),
        }
    }
    m
}

fn contract_universe_reading(contract: &Value) -> String {
    for field in ["post", "inv", "pre"] {
        if let Some(formula) = contract.get(field) {
            return proofir_formula_to_fol_with_instances(formula);
        }
    }
    "<no formula>".to_string()
}

fn source_report_json_value(report: &LiftSourceReport) -> Value {
    let universes = distinct_universes_per_method(&report.contracts);
    let distinct_universes: usize = universes.values().map(Vec::len).sum();
    let universe_rows: Vec<Value> = universes
        .iter()
        .map(|(method, us)| {
            let occurrences: usize = us.iter().map(|u| u.occurrences).sum();
            serde_json::json!({ "method": method, "universes": us.len(), "occurrences": occurrences })
        })
        .collect();
    serde_json::json!({
        "kind": "lift-source-report",
        "sourceLedger": report.ledger,
        "sourceAudits": report.audits,
        "factoryAudits": report.factory_audits,
        "factoryWalk": report.factory_walk,
        "assertionSurfaceAudits": report.assertion_surface_audits,
        "sourceMementos": report.source_mementos,
        "contracts": report.contracts,
        "callEdges": report.call_edges,
        "vendorConjoins": vendor_conjoins_to_json(&report.vendor_conjoins),
        // Lift-side superposition: distinct candidate universes per method.
        // `universes` counts by canonical contract CID (content-addressed
        // identity — the truth the verifier indexes by); `occurrences` is the
        // raw per-callsite count the factory visited (total accounting,
        // silent=0). Duplicates among the occurrences — byte-identical
        // contracts minted from copy-pasted asserts — collapse into one
        // universe; the gap between the two numbers IS that redundancy.
        "superposition": {
            "methods": universes.len(),
            "universes": distinct_universes,
            "occurrences": report.contracts.len(),
            "perMethod": universe_rows,
        },
    })
}

fn render_report_json(
    report: &LiftSourceReport,
    prove_report: Option<&sugar_verifier::Report>,
) -> Result<String, serde_json::Error> {
    let value = if let Some(prove_report) = prove_report {
        serde_json::json!({
            "kind": "lift-prove-report",
            "lift": source_report_json_value(report),
            "prove": report_fmt::report_to_json(prove_report),
        })
    } else {
        source_report_json_value(report)
    };
    serde_json::to_string_pretty(&value).map(|mut rendered| {
        rendered.push('\n');
        rendered
    })
}

fn render_report_summary_json(summary: &LiftReportSummary) -> Result<String, serde_json::Error> {
    let source_unresolved = source_unresolved_count(&summary.ledger);
    let source_accounting = serde_json::json!({
        "loci": source_count(&summary.ledger, "source_loci"),
        "warranted": source_count(&summary.ledger, "source_warranted"),
        "inactive": source_count(&summary.ledger, "source_inactive"),
        "support": source_count(&summary.ledger, "source_support"),
        "refused": source_count(&summary.ledger, "source_refused"),
        "unresolved": source_unresolved,
    });
    let value = serde_json::json!({
        "kind": "lift-source-report-summary",
        "sourceAccounting": source_accounting,
        "factoryAccounting": {
            "sites": summary.factory.sites,
            "warranted": summary.factory.warranted,
            "refused": summary.factory.refused,
            "support": summary.factory.support,
            "unresolved": summary.factory.unresolved,
        },
        "unresolvedSourceLines": unresolved_source_lines_json(&summary.unresolved_factory_sites),
        "unresolvedFactorySites": summary.unresolved_factory_sites,
        "factoryWalk": summary.factory_walk,
    });
    serde_json::to_string_pretty(&value).map(|mut rendered| {
        rendered.push('\n');
        rendered
    })
}

fn render_report_summary_human(summary: &LiftReportSummary) -> String {
    let mut out = String::new();
    let source_unresolved = source_unresolved_count(&summary.ledger);
    out.push_str(&format!(
        "source accounting: loci={} warranted={} inactive={} support={} refused={} unresolved={}\n",
        source_count(&summary.ledger, "source_loci"),
        source_count(&summary.ledger, "source_warranted"),
        source_count(&summary.ledger, "source_inactive"),
        source_count(&summary.ledger, "source_support"),
        source_count(&summary.ledger, "source_refused"),
        source_unresolved,
    ));
    if summary.factory.sites > 0 {
        out.push_str(&format!(
            "factory accounting: sites={} warranted={} refused={} support={} unresolved={}\n",
            summary.factory.sites,
            summary.factory.warranted,
            summary.factory.refused,
            summary.factory.support,
            summary.factory.unresolved,
        ));
    }
    if !summary.unresolved_factory_sites.is_empty() {
        let by_line = unresolved_factory_sites_by_line(&summary.unresolved_factory_sites);
        out.push_str(&format!("unresolved source lines: {}\n", by_line.len()));
        for ((file, line), rows) in by_line {
            out.push_str(&format!("  {file}:{line}\n"));
            for row in rows {
                out.push_str(&format!(
                    "    {}\n",
                    format_unresolved_factory_site_detail(summary.project_root.as_deref(), &row)
                ));
            }
        }
    }
    out.push_str(&render_factory_walk(summary));
    out
}

fn unresolved_source_lines_json(rows: &[Value]) -> Vec<Value> {
    unresolved_factory_sites_by_line(rows)
        .into_iter()
        .map(|((file, line), rows)| {
            serde_json::json!({
                "file": file,
                "line": line,
                "sites": rows,
            })
        })
        .collect()
}

fn unresolved_factory_sites_by_line(rows: &[Value]) -> BTreeMap<(String, String), Vec<Value>> {
    let mut by_line: BTreeMap<(String, String), Vec<Value>> = BTreeMap::new();
    for row in rows {
        let file = row
            .get("file")
            .and_then(Value::as_str)
            .unwrap_or("<unknown>")
            .to_string();
        let line = row
            .get("line")
            .and_then(Value::as_u64)
            .map(|line| line.to_string())
            .unwrap_or_else(|| "?".to_string());
        by_line.entry((file, line)).or_default().push(row.clone());
    }
    by_line
}

fn format_unresolved_factory_site_detail(project_root: Option<&Path>, row: &Value) -> String {
    let role = row
        .get("requested_role")
        .and_then(Value::as_str)
        .unwrap_or("<unknown-role>");
    let ast_kind = row
        .get("ast_kind")
        .and_then(Value::as_str)
        .unwrap_or("<unknown-ast>");
    let selected = row
        .get("selected")
        .and_then(Value::as_str)
        .unwrap_or("<none>");
    let reason = row
        .get("reason")
        .and_then(Value::as_str)
        .filter(|reason| !reason.is_empty())
        .unwrap_or("unclassified");
    let term = resolve_factory_walk_term(project_root, row);
    format!("[{role}/{ast_kind}] selected={selected} term=`{term}` reason={reason}")
}

fn render_factory_walk(summary: &LiftReportSummary) -> String {
    render_factory_walk_rows(&summary.factory_walk, summary.project_root.as_deref())
}

struct RenderedFactoryWalkRow<'a> {
    row: &'a Value,
    verdict: &'static str,
}

fn render_factory_walk_rows(factory_walk: &[Value], project_root: Option<&Path>) -> String {
    if factory_walk.is_empty() {
        return String::new();
    }
    let mut by_line: BTreeMap<(String, u64), Vec<RenderedFactoryWalkRow<'_>>> = BTreeMap::new();
    let mut incomplete_here_seen: BTreeSet<String> = BTreeSet::new();
    let mut gap_here_seen: BTreeSet<String> = BTreeSet::new();
    for row in factory_walk {
        let file = row
            .get("file")
            .and_then(Value::as_str)
            .unwrap_or("<unknown>")
            .to_string();
        let line = row
            .get("line")
            .and_then(Value::as_u64)
            .or_else(|| {
                row.get("sourceMemento")
                    .and_then(|memento| memento.get("span"))
                    .and_then(|span| span.get("start_line"))
                    .and_then(Value::as_u64)
            })
            .unwrap_or(0);
        let status = normalized_source_status(row.get("status").and_then(Value::as_str));
        let raw_verdict = if status == "unresolved" {
            "gap"
        } else {
            row.get("verdict")
                .and_then(Value::as_str)
                .unwrap_or("incomplete")
        };
        let context_key = factory_walk_context_key(row, &file);
        let verdict = if raw_verdict == "complete" {
            "complete"
        } else if raw_verdict == "gap" {
            if gap_here_seen.insert(context_key) {
                "GAP HERE"
            } else {
                "gap"
            }
        } else if incomplete_here_seen.insert(context_key) {
            "INCOMPLETE HERE"
        } else {
            "incomplete"
        };
        by_line
            .entry((file, line))
            .or_default()
            .push(RenderedFactoryWalkRow { row, verdict });
    }

    let mut out = String::new();
    out.push_str("factory whole-walk:\n");
    for ((file, line), rows) in by_line {
        out.push_str(&format!("  {file}:{line}\n"));
        for rendered in rows {
            let row = rendered.row;
            let verdict = rendered.verdict;
            let status = normalized_source_status(row.get("status").and_then(Value::as_str));
            let role = row
                .get("requested_role")
                .and_then(Value::as_str)
                .unwrap_or("?");
            let ast_kind = row.get("ast_kind").and_then(Value::as_str).unwrap_or("?");
            let selected = row
                .get("selected")
                .and_then(Value::as_str)
                .unwrap_or("<none>");
            let output = if status == "unresolved" {
                "gap"
            } else {
                row.get("output").and_then(Value::as_str).unwrap_or("?")
            };
            let term = resolve_factory_walk_term(project_root, row);
            out.push_str(&format!(
                "    {verdict} [{role}/{ast_kind}] selected={selected} output={output} term=`{term}`"
            ));
            if let Some(reason) = row
                .get("reason")
                .and_then(Value::as_str)
                .filter(|reason| !reason.is_empty())
            {
                out.push_str(&format!(" reason={reason}"));
            }
            if let Some(occurrences) = row.get("occurrences").and_then(Value::as_u64) {
                if occurrences > 1 {
                    out.push_str(&format!(" occurrences={occurrences}"));
                }
            }
            out.push('\n');
        }
    }
    out
}

const ANSI_GREEN: &str = "\u{1b}[32m";
const ANSI_RED: &str = "\u{1b}[31m";
const ANSI_RESET: &str = "\u{1b}[0m";

#[derive(Clone, Copy)]
enum VisualTone {
    Green,
    Red,
}

struct VisualFactoryWalkRow {
    context: String,
    source: String,
    label: String,
    tone: VisualTone,
}

#[derive(Clone, Copy)]
struct VisualSourceLookup<'a> {
    project_root: Option<&'a Path>,
    routes: &'a [SourceOracleRoute],
}

struct VisualBoundaryRow {
    context: String,
    sort_key: (u64, u64, u64, u64),
    source: String,
    label: String,
}

fn render_report_visual(
    report: &LiftSourceReport,
    prove_report: Option<&sugar_verifier::Report>,
) -> String {
    let mut out = render_visual_source_report(report);
    if let Some(prove_report) = prove_report {
        if !out.ends_with('\n') {
            out.push('\n');
        }
        out.push('\n');
        out.push_str("prove report (solver witness):\n");
        out.push_str(&report_fmt::format_report_pretty(prove_report, false));
    }
    out
}

fn render_visual_source_report(report: &LiftSourceReport) -> String {
    let source_lookup = VisualSourceLookup {
        project_root: report.project_root.as_deref(),
        routes: &report.source_oracle_routes,
    };
    let rows = visual_factory_walk_rows(&report.factory_walk, source_lookup);
    let mut out = String::new();
    out.push_str(&render_universe_visual_report(report, source_lookup));
    if !out.is_empty() && !out.ends_with('\n') {
        out.push('\n');
    }
    out.push_str("factory visual:\n");
    if rows.is_empty() {
        out.push_str("  <no factory walk emitted>\n");
        return out;
    }

    let mut current_context = String::new();
    for row in rows {
        if row.context != current_context {
            current_context = row.context.clone();
            out.push_str(&format!("  contract {current_context}\n"));
        }
        render_visual_source_annotation(&mut out, &row.source, row.tone, &row.label);
    }
    out
}

fn render_universe_visual_report(
    report: &LiftSourceReport,
    source_lookup: VisualSourceLookup<'_>,
) -> String {
    if report.contracts.is_empty() {
        return String::new();
    }
    let boundaries = visual_boundary_rows(&report.factory_walk, source_lookup);
    let mut out = String::new();
    out.push_str("universe visual:\n");
    for contract in &report.contracts {
        let name = contract_value_name(contract).unwrap_or("<unknown contract>");
        let predicates = contract_predicate_rows(contract);
        out.push_str(&format!("  universe {name}\n"));
        out.push_str(&format!(
            "    FOL: {}\n",
            format_contract_visual_fol(contract)
        ));
        let warrants = contract_source_warrants(contract);
        if warrants.is_empty() {
            out.push_str("    <no source warrants emitted>\n");
            continue;
        }
        render_universe_warrant_breakdown(
            &mut out,
            source_lookup,
            &boundaries,
            &report.factory_walk,
            &warrants,
            &predicates,
        );
    }
    out
}

fn format_contract_visual_fol(contract: &Value) -> String {
    let name = contract_value_name(contract).unwrap_or("<unknown contract>");
    let rendered = contract_universe_reading(contract);
    format!("{name} ⊢ {rendered}")
}

enum UniverseVisualItem<'a> {
    Boundary(&'a VisualBoundaryRow),
    Predicate {
        source: String,
        predicate: String,
        sort_key: (u64, u64, u64, u64),
    },
}

fn render_universe_warrant_breakdown(
    out: &mut String,
    source_lookup: VisualSourceLookup<'_>,
    boundaries: &[VisualBoundaryRow],
    factory_walk: &[Value],
    warrants: &[&Value],
    predicates: &[String],
) {
    let context = warrants
        .first()
        .map(|warrant| source_memento_context_key(warrant))
        .unwrap_or_else(|| "<unknown>".to_string());
    let mut items = Vec::new();
    for boundary in boundaries
        .iter()
        .filter(|boundary| boundary.context == context)
    {
        items.push(UniverseVisualItem::Boundary(boundary));
    }
    let factory_predicates = universe_factory_predicate_rows(factory_walk, source_lookup, &context);
    if factory_predicates.is_empty() {
        for (index, warrant) in warrants.iter().enumerate() {
            let predicate = predicates
                .get(index)
                .cloned()
                .unwrap_or_else(|| "<predicate unavailable>".to_string());
            let sort_key = warrant
                .get("span")
                .map(source_span_sort_key)
                .unwrap_or_default();
            items.push(UniverseVisualItem::Predicate {
                source: resolve_source_memento_visual_source(source_lookup, warrant),
                predicate,
                sort_key,
            });
        }
    } else {
        for predicate in factory_predicates {
            items.push(UniverseVisualItem::Predicate {
                source: predicate.source,
                predicate: predicate.predicate,
                sort_key: predicate.sort_key,
            });
        }
    }
    items.sort_by_key(|item| match item {
        UniverseVisualItem::Boundary(boundary) => (boundary.sort_key, 0_u8),
        UniverseVisualItem::Predicate { sort_key, .. } => (*sort_key, 1_u8),
    });

    let mut red = false;
    for item in items {
        match item {
            UniverseVisualItem::Boundary(boundary) => {
                red = true;
                render_visual_source_annotation(
                    out,
                    &boundary.source,
                    VisualTone::Red,
                    &boundary.label,
                );
            }
            UniverseVisualItem::Predicate {
                source, predicate, ..
            } => {
                let tone = if red {
                    VisualTone::Red
                } else {
                    VisualTone::Green
                };
                let status = if red { "RED" } else { "GREEN" };
                let annotation = if red {
                    status.to_string()
                } else {
                    format!("{status} ⊢ {predicate}")
                };
                render_visual_source_annotation(out, &source, tone, &annotation);
            }
        }
    }
}

fn render_visual_source_annotation(
    out: &mut String,
    source: &str,
    tone: VisualTone,
    annotation: &str,
) {
    let first = source.lines().next().unwrap_or("");
    if first.is_empty() {
        out.push_str(&format!("    {}  {annotation}\n", ansi_paint("", tone)));
        return;
    }
    out.push_str(&format!("    {}  {annotation}\n", ansi_paint(first, tone)));
}

struct UniverseFactoryPredicateRow {
    source: String,
    predicate: String,
    sort_key: (u64, u64, u64, u64),
}

fn universe_factory_predicate_rows(
    factory_walk: &[Value],
    source_lookup: VisualSourceLookup<'_>,
    context: &str,
) -> Vec<UniverseFactoryPredicateRow> {
    factory_walk
        .iter()
        .filter_map(|row| {
            let memento = row.get("sourceMemento")?;
            if source_memento_context_key(memento) != context {
                return None;
            }
            let status = normalized_source_status(row.get("status").and_then(Value::as_str));
            if status != "warranted" && status != "support" {
                return None;
            }
            let formula = row
                .get("emittedFormula")
                .or_else(|| row.get("emitted_formula"))
                .or_else(|| row.get("formula"))?;
            Some(UniverseFactoryPredicateRow {
                source: resolve_source_memento_visual_source(source_lookup, memento),
                predicate: proofir_formula_to_fol_with_instances(formula),
                sort_key: memento
                    .get("span")
                    .map(source_span_sort_key)
                    .unwrap_or_default(),
            })
        })
        .collect()
}

fn visual_boundary_rows(
    factory_walk: &[Value],
    source_lookup: VisualSourceLookup<'_>,
) -> Vec<VisualBoundaryRow> {
    let mut red_seen: BTreeSet<String> = BTreeSet::new();
    let mut rows = Vec::new();
    for row in factory_walk {
        let status = normalized_source_status(row.get("status").and_then(Value::as_str));
        let raw_verdict = if status == "unresolved" {
            "gap"
        } else {
            row.get("verdict")
                .and_then(Value::as_str)
                .unwrap_or("incomplete")
        };
        if raw_verdict == "complete" {
            continue;
        }
        let Some(memento) = row.get("sourceMemento") else {
            continue;
        };
        let context = source_memento_context_key(memento);
        let here = red_seen.insert(context.clone());
        let prefix = match raw_verdict {
            "gap" if here => "RED HERE gap",
            "gap" => "RED gap",
            _ if here => "RED HERE effect",
            _ => "RED effect",
        };
        let label = row
            .get("reason")
            .and_then(Value::as_str)
            .filter(|reason| !reason.is_empty())
            .map(|reason| format!("{prefix}: {reason}"))
            .unwrap_or_else(|| prefix.to_string());
        rows.push(VisualBoundaryRow {
            context,
            sort_key: memento
                .get("span")
                .map(source_span_sort_key)
                .unwrap_or_default(),
            source: resolve_source_memento_visual_source(source_lookup, memento),
            label,
        });
    }
    rows
}

fn visual_factory_walk_rows(
    factory_walk: &[Value],
    source_lookup: VisualSourceLookup<'_>,
) -> Vec<VisualFactoryWalkRow> {
    let mut red_seen: BTreeSet<String> = BTreeSet::new();
    let mut rows = Vec::new();
    for row in factory_walk {
        let file = row
            .get("file")
            .and_then(Value::as_str)
            .unwrap_or("<unknown>")
            .to_string();
        let status = normalized_source_status(row.get("status").and_then(Value::as_str));
        let raw_verdict = if status == "unresolved" {
            "gap"
        } else {
            row.get("verdict")
                .and_then(Value::as_str)
                .unwrap_or("incomplete")
        };
        let context = factory_walk_context_key(row, &file);
        let reason = row
            .get("reason")
            .and_then(Value::as_str)
            .filter(|reason| !reason.is_empty());
        let (tone, label) = if raw_verdict == "complete" {
            let predicate = row
                .get("emittedFormula")
                .or_else(|| row.get("emitted_formula"))
                .or_else(|| row.get("formula"))
                .map(proofir_formula_to_fol_with_instances);
            if red_seen.contains(&context) {
                (VisualTone::Red, "RED".to_string())
            } else {
                (
                    VisualTone::Green,
                    predicate
                        .map(|predicate| format!("GREEN ⊢ {predicate}"))
                        .unwrap_or_else(|| "GREEN".to_string()),
                )
            }
        } else if raw_verdict == "gap" {
            let here = red_seen.insert(context.clone());
            let prefix = if here { "RED HERE gap" } else { "RED gap" };
            (
                VisualTone::Red,
                reason
                    .map(|reason| format!("{prefix}: {reason}"))
                    .unwrap_or_else(|| prefix.to_string()),
            )
        } else {
            let here = red_seen.insert(context.clone());
            let prefix = if here {
                "RED HERE effect"
            } else {
                "RED effect"
            };
            (
                VisualTone::Red,
                reason
                    .map(|reason| format!("{prefix}: {reason}"))
                    .unwrap_or_else(|| prefix.to_string()),
            )
        };
        rows.push(VisualFactoryWalkRow {
            context,
            source: resolve_factory_walk_visual_source(source_lookup, row),
            label,
            tone,
        });
    }
    rows
}

fn ansi_paint(source: &str, tone: VisualTone) -> String {
    let color = match tone {
        VisualTone::Green => ANSI_GREEN,
        VisualTone::Red => ANSI_RED,
    };
    format!("{color}{source}{ANSI_RESET}")
}

fn resolve_factory_walk_visual_source(
    source_lookup: VisualSourceLookup<'_>,
    row: &Value,
) -> String {
    let Some(memento_value) = row.get("sourceMemento") else {
        return resolve_factory_walk_term(source_lookup.project_root, row);
    };
    resolve_source_memento_visual_source(source_lookup, memento_value)
}

fn resolve_source_memento_visual_source(
    source_lookup: VisualSourceLookup<'_>,
    memento_value: &Value,
) -> String {
    if let Some(resolved) =
        resolve_source_memento_visual_source_via_rpc(source_lookup, memento_value)
    {
        return resolved;
    }
    let Some(root) = source_lookup.project_root else {
        return "<source memento unresolved: missing project root>".to_string();
    };
    let Some(memento) = source_memento_from_report_json(memento_value) else {
        return "<source memento invalid>".to_string();
    };
    match sugar_walk::source_oracle::resolve_source_memento(root, &memento) {
        Ok(resolved) => source_lines_for_memento(root, &memento)
            .unwrap_or_else(|| resolved.fragment.body_text.trim().to_string()),
        Err(refusal) => format!("<source memento unresolved: {}>", refusal.reason),
    }
}

fn resolve_source_memento_visual_source_via_rpc(
    source_lookup: VisualSourceLookup<'_>,
    memento_value: &Value,
) -> Option<String> {
    let project_root = source_lookup.project_root?;
    let routed = routed_source_memento(project_root, source_lookup.routes, memento_value)?;
    match invoke_source_oracle_route(
        project_root,
        &routed.route,
        &routed.workspace_root,
        &routed.memento,
    ) {
        Ok(source) => Some(source),
        Err(error) => Some(format!("<source memento unresolved: {error}>")),
    }
}

struct RoutedSourceMemento {
    route: SourceOracleRoute,
    workspace_root: PathBuf,
    memento: Value,
}

fn routed_source_memento(
    project_root: &Path,
    routes: &[SourceOracleRoute],
    memento_value: &Value,
) -> Option<RoutedSourceMemento> {
    let file = memento_value.get("file").and_then(Value::as_str)?;
    let (route, routed_file) = select_source_oracle_route(routes, file)?;
    let mut memento = memento_value.clone();
    if let Value::Object(object) = &mut memento {
        object.insert("file".to_string(), Value::String(routed_file));
    }
    Some(RoutedSourceMemento {
        workspace_root: route_workspace_root(project_root, route),
        route: route.clone(),
        memento,
    })
}

fn select_source_oracle_route<'a>(
    routes: &'a [SourceOracleRoute],
    file: &str,
) -> Option<(&'a SourceOracleRoute, String)> {
    let normalized_file = normalize_report_path(file);
    let mut best: Option<(&SourceOracleRoute, String, usize)> = None;
    for route in routes {
        let Some(prefix) = normalized_workspace_prefix(route.workspace_override.as_deref()) else {
            continue;
        };
        let Some(stripped) = strip_report_path_prefix(&normalized_file, &prefix) else {
            continue;
        };
        if best
            .as_ref()
            .is_none_or(|(_, _, best_len)| prefix.len() > *best_len)
        {
            best = Some((route, stripped, prefix.len()));
        }
    }
    if let Some((route, file, _)) = best {
        return Some((route, file));
    }
    match routes {
        [route] if normalized_workspace_prefix(route.workspace_override.as_deref()).is_some() => {
            Some((route, normalized_file))
        }
        _ => None,
    }
}

fn strip_report_path_prefix(file: &str, prefix: &str) -> Option<String> {
    if file == prefix {
        return None;
    }
    file.strip_prefix(&format!("{prefix}/"))
        .map(str::to_string)
        .filter(|rest| !rest.is_empty())
}

fn normalized_workspace_prefix(workspace_override: Option<&str>) -> Option<String> {
    let raw = workspace_override?.trim();
    if raw.is_empty() || raw == "." {
        return None;
    }
    Some(normalize_report_path(raw).trim_end_matches('/').to_string())
        .filter(|prefix| !prefix.is_empty())
}

fn normalize_report_path(path: &str) -> String {
    path.replace('\\', "/").trim_start_matches("./").to_string()
}

fn route_workspace_root(project_root: &Path, route: &SourceOracleRoute) -> PathBuf {
    let root = match route.workspace_override.as_deref().and_then(|raw| {
        let trimmed = raw.trim();
        (!trimmed.is_empty() && trimmed != ".").then_some(trimmed)
    }) {
        Some(raw) => {
            let configured = PathBuf::from(raw);
            if configured.is_absolute() {
                configured
            } else {
                project_root.join(configured)
            }
        }
        None => project_root.to_path_buf(),
    };
    root.canonicalize().unwrap_or(root)
}

fn invoke_source_oracle_route(
    project_root: &Path,
    route: &SourceOracleRoute,
    workspace_root: &Path,
    memento: &Value,
) -> Result<String, String> {
    let manifest = lift_plugin::find_manifest_for_surface(project_root, &route.surface)?;
    let (program, args) = manifest.command.split_first().ok_or_else(|| {
        format!(
            "source oracle surface `{}` has empty command",
            route.surface
        )
    })?;
    let mut command = Command::new(program);
    command.args(args);
    if let Some(working_dir) = lift_plugin::resolved_working_dir_for(project_root, &manifest) {
        command.current_dir(working_dir);
    } else {
        command.current_dir(project_root);
    }
    command.stdin(Stdio::piped());
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|error| format!("spawn source oracle `{}`: {error}", route.surface))?;
    {
        let stdin = child
            .stdin
            .as_mut()
            .ok_or_else(|| format!("source oracle `{}` stdin closed", route.surface))?;
        let request = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sugar.plugin.resolve_source_memento",
            "params": {
                "workspace_root": workspace_root.to_string_lossy(),
                "sourceMemento": memento,
            }
        });
        writeln!(
            stdin,
            "{}",
            serde_json::to_string(&request).map_err(|error| error.to_string())?
        )
        .map_err(|error| format!("write source oracle request: {error}"))?;
        let shutdown = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "shutdown",
            "params": {}
        });
        writeln!(stdin, "{}", serde_json::to_string(&shutdown).unwrap())
            .map_err(|error| format!("write source oracle shutdown: {error}"))?;
    }
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| format!("source oracle `{}` stdout closed", route.surface))?;
    let mut reader = BufReader::new(stdout);
    let mut response_line = String::new();
    reader
        .read_line(&mut response_line)
        .map_err(|error| format!("read source oracle response: {error}"))?;
    let _ = child.wait();
    let response: Value = serde_json::from_str(&response_line).map_err(|error| {
        format!(
            "parse source oracle response: {error}; raw={}",
            response_line.trim_end()
        )
    })?;
    if let Some(error) = response.get("error") {
        let message = error
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("source oracle refused");
        return Err(message.to_string());
    }
    response
        .get("result")
        .and_then(|result| {
            result
                .get("source")
                .or_else(|| result.get("bodyText"))
                .and_then(Value::as_str)
        })
        .map(str::to_string)
        .ok_or_else(|| {
            format!(
                "source oracle `{}` response missing result.source",
                route.surface
            )
        })
}

fn source_lines_for_memento(
    root: &Path,
    memento: &sugar_walk::source_oracle::SourceMemento,
) -> Option<String> {
    let source = std::fs::read_to_string(root.join(&memento.file)).ok()?;
    let lines = source.lines().collect::<Vec<_>>();
    let start = memento.span.start_line.checked_sub(1)?;
    let end = memento.span.end_line.max(memento.span.start_line);
    let selected = lines.get(start..end)?;
    Some(selected.join("\n").trim().to_string())
}

fn factory_walk_context_key(row: &Value, file: &str) -> String {
    let source_function = row
        .get("sourceMemento")
        .and_then(|memento| {
            memento
                .get("sourceFunctionName")
                .or_else(|| memento.get("source_function_name"))
        })
        .and_then(Value::as_str)
        .filter(|name| !name.is_empty());
    match source_function {
        Some(function) => format!("{file}::{function}"),
        None => file.to_string(),
    }
}

fn source_memento_context_key(memento: &Value) -> String {
    let file = memento
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown>");
    let source_function = memento
        .get("sourceFunctionName")
        .or_else(|| memento.get("source_function_name"))
        .and_then(Value::as_str)
        .filter(|name| !name.is_empty());
    match source_function {
        Some(function) => format!("{file}::{function}"),
        None => file.to_string(),
    }
}

fn contract_source_warrants(contract: &Value) -> Vec<&Value> {
    contract
        .get("sourceWarrants")
        .or_else(|| contract.get("source_warrants"))
        .and_then(Value::as_array)
        .map(|warrants| warrants.iter().collect())
        .unwrap_or_default()
}

fn contract_predicate_rows(contract: &Value) -> Vec<String> {
    for field in ["post", "inv", "pre"] {
        if let Some(formula) = contract.get(field) {
            return formula_predicate_rows(formula);
        }
    }
    Vec::new()
}

fn formula_predicate_rows(formula: &Value) -> Vec<String> {
    if formula.get("kind").and_then(Value::as_str) == Some("and") {
        if let Some(operands) = formula.get("operands").and_then(Value::as_array) {
            return operands
                .iter()
                .map(proofir_formula_to_fol_with_instances)
                .collect();
        }
    }
    vec![proofir_formula_to_fol_with_instances(formula)]
}

fn source_span_sort_key(span: &Value) -> (u64, u64, u64, u64) {
    (
        span.get("start_line").and_then(Value::as_u64).unwrap_or(0),
        span.get("start_col").and_then(Value::as_u64).unwrap_or(0),
        span.get("end_line").and_then(Value::as_u64).unwrap_or(0),
        span.get("end_col").and_then(Value::as_u64).unwrap_or(0),
    )
}

fn resolve_factory_walk_term(project_root: Option<&Path>, row: &Value) -> String {
    let Some(root) = project_root else {
        return "<source memento unresolved: missing project root>".to_string();
    };
    let Some(memento_value) = row.get("sourceMemento") else {
        return "<source memento absent>".to_string();
    };
    let Some(memento) = source_memento_from_report_json(memento_value) else {
        return "<source memento invalid>".to_string();
    };
    match sugar_walk::source_oracle::resolve_source_memento(root, &memento) {
        Ok(resolved) => resolved.fragment.body_text,
        Err(refusal) => format!("<source memento unresolved: {}>", refusal.reason),
    }
}

fn source_memento_from_report_json(
    value: &Value,
) -> Option<sugar_walk::source_oracle::SourceMemento> {
    let file = value.get("file").and_then(Value::as_str)?.to_string();
    let span = value.get("span")?;
    let param_names = value
        .get("paramNames")
        .or_else(|| value.get("param_names"))
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    Some(sugar_walk::source_oracle::SourceMemento {
        file,
        function_name: value
            .get("sourceFunctionName")
            .or_else(|| value.get("source_function_name"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        span: sugar_walk::source_oracle::SrcSpan {
            start_line: span.get("start_line").and_then(Value::as_u64).unwrap_or(0) as usize,
            start_col: span.get("start_col").and_then(Value::as_u64).unwrap_or(0) as usize,
            end_line: span.get("end_line").and_then(Value::as_u64).unwrap_or(0) as usize,
            end_col: span.get("end_col").and_then(Value::as_u64).unwrap_or(0) as usize,
        },
        param_names,
        source_cid: value
            .get("source_cid")
            .or_else(|| value.get("sourceCid"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        template_cid: value
            .get("template_cid")
            .or_else(|| value.get("templateCid"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
    })
}

fn source_report_summary_has_hard_failures(summary: &LiftReportSummary) -> bool {
    source_unresolved_count(&summary.ledger) > 0 || summary.factory.unresolved > 0
}

fn render_source_report_human(report: &LiftSourceReport) -> String {
    trace_lift_source_report("render_source_report_human.start", report);
    let mut out = String::new();
    out.push_str(&format!(
        "source audit: {}\n",
        format_counts(&report.ledger)
    ));
    let universes = distinct_universes_per_method(&report.contracts);
    tracing::info!(
        stage = "render_source_report_human.after_superposition_scan",
        rss_kib = current_rss_kib().unwrap_or_default(),
        rss_available = current_rss_kib().is_some(),
        methods = universes.len(),
        universes = universes.values().map(Vec::len).sum::<usize>(),
        contracts = report.contracts.len(),
        rendered_bytes = out.len(),
        "lift-report memory checkpoint"
    );
    if !universes.is_empty() {
        let distinct_universes: usize = universes.values().map(Vec::len).sum();
        out.push_str(&format!(
            "superposition (universes detected): {} methods, {} universes ({} callsite occurrences)\n",
            universes.len(),
            distinct_universes,
            report.contracts.len(),
        ));
        for (method, us) in &universes {
            out.push_str(&format!("  {method} — {} universe(s):\n", us.len()));
            // Show up to 8 distinct universes side by side; beyond that, count
            // the tail. Annotate the per-callsite multiplicity (×N) so a
            // collapsed duplicate reads as "one universe, N callsites", and
            // disambiguate distinct universes that render to the same FOL (their
            // CIDs differ — e.g. a differing integer width the renderer elides)
            // with a short CID tag, so they read as distinct rather than
            // redundant.
            for u in us.iter().take(8) {
                let ambiguous_reading = us.iter().filter(|o| o.reading == u.reading).count() > 1;
                let mut line = u.reading.clone();
                if ambiguous_reading {
                    let tag: String = u.cid.chars().take(12).collect();
                    line.push_str(&format!("  [cid {tag}]"));
                }
                if u.occurrences > 1 {
                    line.push_str(&format!(" (×{})", u.occurrences));
                }
                out.push_str(&format!("      {line}\n"));
            }
            if us.len() > 8 {
                out.push_str(&format!("      (+{} more universes)\n", us.len() - 8));
            }
        }
    }
    if !report.call_edges.is_empty() {
        out.push_str("call edges observed:\n");
        for edge in &report.call_edges {
            out.push_str(&format!("  - {}\n", format_call_edge(edge)));
        }
    }
    if !report.vendor_conjoins.is_empty() {
        out.push_str("vendor conjoins:\n");
        for conjoin in &report.vendor_conjoins {
            out.push_str(&format!("  - call: {}\n", conjoin.call));
            out.push_str(&format!("    your contract: {}\n", conjoin.local_contract));
            out.push_str(&format!("    your fact: {}\n", conjoin.local_fact));
            out.push_str(&format!(
                "    bridge: {} -> {}\n",
                conjoin.bridge_source_symbol, conjoin.vendor_contract_cid
            ));
            let proof = conjoin.vendor_proof_cid.as_deref().unwrap_or("<unknown>");
            out.push_str(&format!(
                "    vendor contract: {} cid={} proof={}\n",
                conjoin.vendor_contract, conjoin.vendor_contract_cid, proof
            ));
            if let Some(source) = &conjoin.vendor_source {
                out.push_str(&format!(
                    "    vendor source: {}\n",
                    format_vendor_source_resolution(source)
                ));
            }
            out.push_str(&format!("    vendor post: {}\n", conjoin.vendor_post));
            out.push_str(&format!(
                "    instantiated post: {}\n",
                conjoin.instantiated_post
            ));
            out.push_str(&format!(
                "    conjoin here: {} ∧ ({})\n",
                conjoin.local_fact, conjoin.instantiated_post
            ));
        }
    }
    trace_lift_render_checkpoint(
        "render_source_report_human.after_call_vendor_sections",
        out.len(),
    );
    out.push_str(&render_assertion_surface_accounting(report));
    trace_lift_render_checkpoint(
        "render_source_report_human.after_assertion_surface_accounting",
        out.len(),
    );
    out.push_str(&render_factory_accounting(&report.factory_audits));
    trace_lift_render_checkpoint(
        "render_source_report_human.after_factory_accounting",
        out.len(),
    );
    out.push_str(&render_factory_walk_rows(
        &report.factory_walk,
        report.project_root.as_deref(),
    ));
    trace_lift_render_checkpoint("render_source_report_human.after_factory_walk", out.len());
    if report.audits.is_empty() {
        out.push_str("no source audits emitted\n");
        trace_lift_render_checkpoint("render_source_report_human.end", out.len());
        return out;
    }

    let mut group_keys = Vec::new();
    for audit in &report.audits {
        let key = audit_report_group_key(audit);
        if !group_keys.contains(&key) {
            group_keys.push(key);
        }
    }

    for contract in &report.contracts {
        let Some(name) = contract_value_name(contract) else {
            continue;
        };
        let key = report_contract_group_key(name);
        if !group_keys.contains(&key) {
            group_keys.push(key);
        }
    }

    for memento in &report.source_mementos {
        let key = report_memento_group_key(memento);
        if !group_keys.contains(&key) {
            group_keys.push(key);
        }
    }
    tracing::info!(
        stage = "render_source_report_human.after_group_key_collection",
        rss_kib = current_rss_kib().unwrap_or_default(),
        rss_available = current_rss_kib().is_some(),
        group_keys = group_keys.len(),
        rendered_bytes = out.len(),
        "lift-report memory checkpoint"
    );

    let group_count = group_keys.len();
    for (group_index, group_key) in group_keys.into_iter().enumerate() {
        if group_index % 250 == 0 {
            tracing::info!(
                stage = "render_source_report_human.group_progress",
                rss_kib = current_rss_kib().unwrap_or_default(),
                rss_available = current_rss_kib().is_some(),
                group_index = group_index,
                group_count = group_count,
                rendered_bytes = out.len(),
                "lift-report memory checkpoint"
            );
        }
        let group_audits = report
            .audits
            .iter()
            .filter(|audit| audit_report_group_key(audit) == group_key)
            .collect::<Vec<_>>();
        let group_contracts = report
            .contracts
            .iter()
            .filter(|contract| {
                contract_value_name(contract)
                    .map(report_contract_group_key)
                    .is_some_and(|key| key == group_key)
            })
            .collect::<Vec<_>>();
        let group_mementos = report
            .source_mementos
            .iter()
            .filter(|memento| report_memento_group_key(memento) == group_key)
            .collect::<Vec<_>>();

        let display_name = group_audits
            .first()
            .and_then(|audit| contract_name(audit))
            .or_else(|| {
                group_contracts
                    .first()
                    .and_then(|contract| contract_value_name(contract))
            })
            .unwrap_or(&group_key);
        out.push_str(&format!("\ncontract: {display_name}\n"));

        let fact_mementos = group_mementos
            .iter()
            .filter(|memento| is_fact_source_memento(memento))
            .copied()
            .collect::<Vec<_>>();
        let asserted_fact_rows = group_contracts
            .iter()
            .filter_map(|contract| format_contract_asserted_fact(report, contract))
            .collect::<Vec<_>>();
        if fact_mementos.is_empty() && asserted_fact_rows.is_empty() {
            if let Some(site) = assertion_site_for_group(&group_contracts) {
                out.push_str(&format!(
                    "facts observed:\n  - assertion source inferred from contract name: {site}\n"
                ));
            }
        } else {
            out.push_str("facts observed:\n");
            for memento in fact_mementos {
                out.push_str(&format!("  - {}\n", format_fact_memento(memento)));
            }
            for row in asserted_fact_rows {
                out.push_str(&format!("  - {row}\n"));
            }
        }
        let warranted_mementos = group_mementos
            .iter()
            .filter(|memento| !is_fact_source_memento(memento))
            .collect::<Vec<_>>();
        if !warranted_mementos.is_empty() || !group_audits.is_empty() {
            out.push_str("warranted complete walks:\n");
            for memento in warranted_mementos {
                out.push_str(&format!("  - {}\n", format_source_memento_value(memento)));
            }
            for audit in &group_audits {
                out.push_str(&format!("  - {}\n", format_source_memento(audit)));
            }
        }

        if !group_contracts.is_empty() {
            let generalized_rows = group_contracts
                .iter()
                .flat_map(|contract| generalized_contract_fol(contract))
                .collect::<Vec<_>>();
            if generalized_rows.is_empty() {
                let universe_rows = group_contracts
                    .iter()
                    .filter_map(|contract| format_contract_universe_fol(contract))
                    .collect::<Vec<_>>();
                if !universe_rows.is_empty() {
                    out.push_str("lifted FOL:\n");
                }
                for row in universe_rows {
                    out.push_str(&format!("  - {row}\n"));
                }
            } else {
                out.push_str("generalized FOL:\n");
                for row in generalized_rows {
                    out.push_str(&format!("  - {row}\n"));
                }
                out.push_str("instantiated FOL:\n");
                for contract in &group_contracts {
                    out.push_str(&format!("  - {}\n", format_contract_fol(contract)));
                }
            }
        }
        if group_audits.is_empty() {
            continue;
        }

        out.push_str("method breakdown:\n");
        for audit in group_audits {
            let role = audit
                .get("role")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            let universe = audit
                .get("universe_kind")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            out.push_str(&format!("  complete walk: {role} / {universe}\n"));
            if let Some(totals) = audit.get("totals") {
                out.push_str(&format!("  totals: {}\n", format_counts(totals)));
            }
            if audit
                .get("loci_elided")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                let mode = audit
                    .get("accounting_mode")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown");
                out.push_str(&format!("  loci: elided ({mode} package accounting)\n"));
            }
            if let Some(loci) = audit.get("loci").and_then(Value::as_array) {
                let mut loci = loci.iter().collect::<Vec<_>>();
                loci.sort_by_key(|locus| {
                    (
                        locus
                            .get("file")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                        locus
                            .get("line")
                            .and_then(Value::as_i64)
                            .unwrap_or(i64::MAX),
                        locus
                            .get("ast_path")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                    )
                });
                let ast_summary = format_ast_type_summary(&loci);
                if !ast_summary.is_empty() {
                    out.push_str("  ast types:\n");
                    for row in ast_summary {
                        out.push_str(&format!("    {row}\n"));
                    }
                }
                let ast_rollup = format_ast_rollup_summary(&loci);
                if !ast_rollup.is_empty() {
                    out.push_str("  ast rollup:\n");
                    for row in ast_rollup {
                        out.push_str(&format!("    {row}\n"));
                    }
                }
                for locus in loci {
                    let file = locus
                        .get("file")
                        .and_then(Value::as_str)
                        .unwrap_or("<unknown file>");
                    let line = locus
                        .get("line")
                        .and_then(Value::as_i64)
                        .map(|line| line.to_string())
                        .unwrap_or_else(|| "?".to_string());
                    let status =
                        normalized_source_status(locus.get("status").and_then(Value::as_str));
                    let ast_kind = locus.get("ast_kind").and_then(Value::as_str).unwrap_or("?");
                    let reason = locus.get("reason").and_then(Value::as_str).unwrap_or("");
                    if reason.is_empty() {
                        out.push_str(&format!("    {file}:{line} {status} {ast_kind}\n"));
                    } else {
                        out.push_str(&format!("    {file}:{line} {status} {ast_kind} {reason}\n"));
                    }
                }
            } else {
                let ast_summary = format_ast_type_counts_value(audit.get("ast_type_counts"));
                if !ast_summary.is_empty() {
                    out.push_str("  ast types:\n");
                    for row in ast_summary {
                        out.push_str(&format!("    {row}\n"));
                    }
                }
                if let Some(samples) = audit.get("sample_loci").and_then(Value::as_array) {
                    if !samples.is_empty() {
                        out.push_str("  sample loci:\n");
                        for locus in samples {
                            let file = locus
                                .get("file")
                                .and_then(Value::as_str)
                                .unwrap_or("<unknown file>");
                            let line = locus
                                .get("line")
                                .and_then(Value::as_i64)
                                .map(|line| line.to_string())
                                .unwrap_or_else(|| "?".to_string());
                            let status = normalized_source_status(
                                locus.get("status").and_then(Value::as_str),
                            );
                            let ast_kind =
                                locus.get("ast_kind").and_then(Value::as_str).unwrap_or("?");
                            let reason = locus.get("reason").and_then(Value::as_str).unwrap_or("");
                            if reason.is_empty() {
                                out.push_str(&format!("    {file}:{line} {status} {ast_kind}\n"));
                            } else {
                                out.push_str(&format!(
                                    "    {file}:{line} {status} {ast_kind} {reason}\n"
                                ));
                            }
                        }
                    }
                }
            }
        }
    }

    trace_lift_render_checkpoint("render_source_report_human.end", out.len());
    out
}

fn format_call_edge(edge: &Value) -> String {
    let source = report_text_field(edge, &["sourceContract", "source_contract"])
        .unwrap_or_else(|| "<unknown source contract>".to_string());
    let target_symbol = report_text_field(edge, &["targetSymbol", "target_symbol"])
        .unwrap_or_else(|| "<unknown target symbol>".to_string());
    let target = report_text_field(edge, &["targetContract", "target_contract"])
        .unwrap_or_else(|| "<unknown target contract>".to_string());
    let target_cid = report_text_field(edge, &["targetContractCid", "target_contract_cid"])
        .unwrap_or_else(|| "<unknown cid>".to_string());
    let locus = edge
        .get("callSiteLocus")
        .or_else(|| edge.get("call_site_locus"))
        .map(format_call_edge_locus)
        .unwrap_or_else(|| "<unknown locus>".to_string());
    format!("{source} -> {target_symbol} -> {target} cid={target_cid} @ {locus}")
}

fn format_call_edge_locus(locus: &Value) -> String {
    let file = locus
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown file>");
    let line = locus
        .get("line")
        .and_then(Value::as_i64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let slot = locus.get("slot").and_then(Value::as_str).unwrap_or("?");
    format!("{file}:{line} {slot}")
}

fn render_report_human(
    report: &LiftSourceReport,
    prove_report: Option<&sugar_verifier::Report>,
) -> String {
    let mut out = render_source_report_human(report);
    if let Some(prove_report) = prove_report {
        if !out.ends_with('\n') {
            out.push('\n');
        }
        out.push('\n');
        out.push_str("prove report (solver witness):\n");
        out.push_str(&report_fmt::format_report_pretty(prove_report, false));
    }
    out
}

fn source_report_has_hard_failures(report: &LiftSourceReport) -> bool {
    report
        .vendor_conjoins
        .iter()
        .any(|row| matches!(row.vendor_source, Some(VendorSourceResolution::Drifted(_))))
}

fn vendor_conjoins_from_lift_response(
    response: &Value,
    contract_filter: Option<&str>,
) -> Result<Vec<VendorConjoinReport>, String> {
    let Some(rows) = response
        .get("vendorConjoins")
        .or_else(|| response.get("vendor_conjoins"))
        .or_else(|| response.get("linkerConjoins"))
        .or_else(|| response.get("linker_conjoins"))
        .and_then(Value::as_array)
    else {
        return Ok(Vec::new());
    };

    rows.iter()
        .filter(|row| vendor_conjoin_matches_filter(row, contract_filter))
        .map(vendor_conjoin_from_value)
        .collect()
}

fn vendor_conjoin_matches_filter(row: &Value, contract_filter: Option<&str>) -> bool {
    let Some(filter) = contract_filter else {
        return true;
    };
    [
        "call",
        "localContract",
        "local_contract",
        "bridgeSourceSymbol",
        "bridge_source_symbol",
        "vendorContract",
        "vendor_contract",
        "vendorContractCid",
        "vendor_contract_cid",
        "vendorProofCid",
        "vendor_proof_cid",
    ]
    .into_iter()
    .filter_map(|key| row.get(key).and_then(Value::as_str))
    .any(|value| value.contains(filter))
}

fn vendor_conjoin_from_value(row: &Value) -> Result<VendorConjoinReport, String> {
    ensure_vendor_proof_resolved(row)?;
    Ok(VendorConjoinReport {
        call: report_text_field(row, &["call", "callTerm", "call_term"])
            .unwrap_or_else(|| "<unknown call>".to_string()),
        local_contract: required_report_text_field(row, &["localContract", "local_contract"])?,
        local_fact: required_report_text_field(row, &["localFact", "local_fact"])?,
        bridge_source_symbol: required_report_text_field(
            row,
            &[
                "bridgeSourceSymbol",
                "bridge_source_symbol",
                "sourceSymbol",
                "source_symbol",
            ],
        )?,
        vendor_contract: required_report_text_field(row, &["vendorContract", "vendor_contract"])?,
        vendor_contract_cid: required_report_text_field(
            row,
            &[
                "vendorContractCid",
                "vendor_contract_cid",
                "targetContractCid",
            ],
        )?,
        vendor_proof_cid: report_text_field(
            row,
            &["vendorProofCid", "vendor_proof_cid", "targetProofCid"],
        ),
        vendor_post: required_report_text_field(row, &["vendorPost", "vendor_post"])?,
        instantiated_post: required_report_text_field(
            row,
            &["instantiatedPost", "instantiated_post"],
        )?,
        vendor_source: vendor_source_resolution_from_value(row),
    })
}

fn ensure_vendor_proof_resolved(row: &Value) -> Result<(), String> {
    let resolution = row
        .get("vendorProofResolution")
        .or_else(|| row.get("vendor_proof_resolution"))
        .or_else(|| row.get("proofResolution"))
        .or_else(|| row.get("proof_resolution"));
    let Some(resolution) = resolution else {
        return Ok(());
    };
    let status = resolution
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("resolved");
    if matches!(status, "resolved" | "ok") {
        return Ok(());
    }
    let cid = resolution
        .get("cid")
        .and_then(Value::as_str)
        .or_else(|| {
            row.get("vendorProofCid")
                .or_else(|| row.get("vendor_proof_cid"))
                .or_else(|| row.get("targetProofCid"))
                .and_then(Value::as_str)
        })
        .unwrap_or("<unknown>");
    Err(format!(
        "kit referenced proof CID `{cid}` but did not resolve it; this is a kit/protocol panic"
    ))
}

fn vendor_source_resolution_from_value(row: &Value) -> Option<VendorSourceResolution> {
    let source = row
        .get("vendorSource")
        .or_else(|| row.get("vendor_source"))
        .or_else(|| row.get("vendorSourceResolution"))
        .or_else(|| row.get("vendor_source_resolution"))?;
    if let Some(rendered) = source.as_str() {
        return Some(VendorSourceResolution::Resolved(rendered.to_string()));
    }
    let status = source
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("resolved");
    let reason = source
        .get("reason")
        .and_then(Value::as_str)
        .or_else(|| source.get("message").and_then(Value::as_str))
        .unwrap_or("")
        .to_string();
    match status {
        "resolved" | "ok" => source
            .get("display")
            .and_then(Value::as_str)
            .map(|display| VendorSourceResolution::Resolved(display.to_string()))
            .or_else(|| {
                source
                    .get("memento")
                    .map(|memento| VendorSourceResolution::Resolved(format_source_ref(memento)))
            }),
        "absent" | "missing" | "unavailable" => Some(VendorSourceResolution::Absent(reason)),
        "drifted" | "drift" | "mismatch" => Some(VendorSourceResolution::Drifted(reason)),
        _ => Some(VendorSourceResolution::Absent(reason)),
    }
}

fn required_report_text_field(row: &Value, keys: &[&str]) -> Result<String, String> {
    report_text_field(row, keys).ok_or_else(|| {
        format!(
            "kit vendor conjoin row missing `{}`",
            keys.first().copied().unwrap_or("<field>")
        )
    })
}

fn report_text_field(row: &Value, keys: &[&str]) -> Option<String> {
    let value = keys.iter().find_map(|key| row.get(*key))?;
    if let Some(text) = value.as_str() {
        return Some(text.to_string());
    }
    if value.is_object() {
        let kind = value
            .get("kind")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if matches!(
            kind,
            "atomic" | "Atomic" | "and" | "or" | "not" | "implies" | "forall" | "exists"
        ) {
            return Some(proofir_formula_to_fol_with_instances(value));
        }
        return Some(proofir_term_to_fol(value));
    }
    serde_json::to_string(value).ok()
}

fn format_vendor_source_resolution(source: &VendorSourceResolution) -> String {
    match source {
        VendorSourceResolution::Resolved(display) => display.clone(),
        VendorSourceResolution::Absent(reason) if reason.is_empty() => "absent".to_string(),
        VendorSourceResolution::Absent(reason) => format!("absent - {reason}"),
        VendorSourceResolution::Drifted(reason) if reason.is_empty() => "DRIFTED".to_string(),
        VendorSourceResolution::Drifted(reason) => format!("DRIFTED - {reason}"),
    }
}

fn vendor_conjoins_to_json(rows: &[VendorConjoinReport]) -> Vec<Value> {
    rows.iter()
        .map(|row| {
            let mut value = serde_json::json!({
                "call": row.call,
                "localContract": row.local_contract,
                "localFact": row.local_fact,
                "bridgeSourceSymbol": row.bridge_source_symbol,
                "vendorContract": row.vendor_contract,
                "vendorContractCid": row.vendor_contract_cid,
                "vendorProofCid": row.vendor_proof_cid,
                "vendorPost": row.vendor_post,
                "instantiatedPost": row.instantiated_post,
            });
            if let Some(source) = &row.vendor_source {
                value["vendorSource"] = match source {
                    VendorSourceResolution::Resolved(display) => {
                        serde_json::json!({"status": "resolved", "display": display})
                    }
                    VendorSourceResolution::Absent(reason) => {
                        serde_json::json!({"status": "absent", "reason": reason})
                    }
                    VendorSourceResolution::Drifted(reason) => {
                        serde_json::json!({"status": "drifted", "reason": reason})
                    }
                };
            }
            value
        })
        .collect()
}

#[derive(Clone, Debug)]
struct AstRollupLocus {
    status: String,
    ast_kind: String,
    ast_path: String,
}

fn format_ast_type_summary(loci: &[&Value]) -> Vec<String> {
    let mut by_status: BTreeMap<String, BTreeMap<String, i64>> = BTreeMap::new();
    for locus in loci {
        let Some(ast_kind) = locus.get("ast_kind").and_then(Value::as_str) else {
            continue;
        };
        if ast_kind.is_empty() || ast_kind == "?" {
            continue;
        }
        let status = normalized_source_status(locus.get("status").and_then(Value::as_str));
        *by_status
            .entry(status.to_string())
            .or_default()
            .entry(ast_kind.to_string())
            .or_default() += 1;
    }

    let mut rows = by_status.into_iter().collect::<Vec<_>>();
    rows.sort_by_key(|(status, _)| (source_status_order(status), status.clone()));
    rows.into_iter()
        .map(|(status, counts)| {
            let counts = counts
                .into_iter()
                .map(|(kind, count)| format!("{kind}={count}"))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{status}: {counts}")
        })
        .collect()
}

fn format_ast_type_counts_value(value: Option<&Value>) -> Vec<String> {
    let Some(Value::Object(by_status)) = value else {
        return Vec::new();
    };
    let mut rows = by_status
        .iter()
        .filter_map(|(status, counts)| {
            let Value::Object(counts) = counts else {
                return None;
            };
            let counts = counts
                .iter()
                .filter_map(|(kind, count)| count.as_i64().map(|count| (kind.clone(), count)))
                .collect::<BTreeMap<_, _>>();
            if counts.is_empty() {
                return None;
            }
            Some((normalized_source_status(Some(status)).to_string(), counts))
        })
        .collect::<Vec<_>>();
    rows.sort_by_key(|(status, _)| (source_status_order(status), status.clone()));
    rows.into_iter()
        .map(|(status, counts)| {
            let counts = counts
                .into_iter()
                .map(|(kind, count)| format!("{kind}={count}"))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{status}: {counts}")
        })
        .collect()
}

fn format_ast_rollup_summary(loci: &[&Value]) -> Vec<String> {
    let ast_loci = loci
        .iter()
        .filter_map(|locus| {
            let ast_kind = locus.get("ast_kind").and_then(Value::as_str)?;
            if ast_kind.is_empty() || ast_kind == "?" {
                return None;
            }
            let ast_path = locus.get("ast_path").and_then(Value::as_str)?;
            if ast_path.is_empty() {
                return None;
            }
            Some(AstRollupLocus {
                status: normalized_source_status(locus.get("status").and_then(Value::as_str))
                    .to_string(),
                ast_kind: ast_kind.to_string(),
                ast_path: ast_path.to_string(),
            })
        })
        .collect::<Vec<_>>();
    if ast_loci.is_empty() {
        return Vec::new();
    }

    let mut roots_by_status: BTreeMap<String, BTreeMap<String, i64>> = BTreeMap::new();
    let mut constraint_roots_by_status: BTreeMap<String, BTreeMap<String, i64>> = BTreeMap::new();
    let mut constraint_children_by_status: BTreeMap<String, BTreeMap<String, i64>> =
        BTreeMap::new();
    let mut support_roots_by_status: BTreeMap<String, BTreeMap<String, i64>> = BTreeMap::new();
    let mut covered_by_status: BTreeMap<String, BTreeMap<String, i64>> = BTreeMap::new();

    for (index, locus) in ast_loci.iter().enumerate() {
        let covered_by_parent = ast_loci
            .iter()
            .enumerate()
            .any(|(candidate_index, candidate)| {
                candidate_index != index
                    && candidate.status == locus.status
                    && dominates_ast_subtree(candidate, locus)
            });
        if covered_by_parent {
            *covered_by_status
                .entry(locus.status.clone())
                .or_default()
                .entry(locus.ast_kind.clone())
                .or_default() += 1;
            if is_constraint_ast_kind(&locus.ast_kind) {
                *constraint_children_by_status
                    .entry(locus.status.clone())
                    .or_default()
                    .entry(locus.ast_kind.clone())
                    .or_default() += 1;
            }
            continue;
        }

        *roots_by_status
            .entry(locus.status.clone())
            .or_default()
            .entry(locus.ast_kind.clone())
            .or_default() += 1;
        if is_constraint_ast_kind(&locus.ast_kind) {
            *constraint_roots_by_status
                .entry(locus.status.clone())
                .or_default()
                .entry(locus.ast_kind.clone())
                .or_default() += 1;
        }
        if locus.status == "support" {
            *support_roots_by_status
                .entry(locus.status.clone())
                .or_default()
                .entry(locus.ast_kind.clone())
                .or_default() += 1;
        }
    }

    let mut statuses = roots_by_status.keys().cloned().collect::<Vec<_>>();
    statuses.sort_by_key(|status| (source_status_order(status), status.clone()));
    let mut rows = Vec::new();
    for status in statuses {
        if let Some(counts) = roots_by_status.get(&status) {
            rows.push(format!(
                "{status} roots: {}",
                format_ast_kind_counts(counts)
            ));
        }
        if let Some(counts) = constraint_roots_by_status.get(&status) {
            if !counts.is_empty() {
                rows.push(format!(
                    "{status} constraint roots: {}",
                    format_ast_kind_counts(counts)
                ));
            }
        }
        if let Some(counts) = constraint_children_by_status.get(&status) {
            if !counts.is_empty() {
                rows.push(format!(
                    "{status} constraint children: {}",
                    format_ast_kind_counts(counts)
                ));
            }
        }
        if let Some(counts) = support_roots_by_status.get(&status) {
            if !counts.is_empty() {
                rows.push(format!(
                    "{status} support roots: {}",
                    format_ast_kind_counts(counts)
                ));
            }
        }
        if let Some(counts) = covered_by_status.get(&status) {
            if !counts.is_empty() {
                rows.push(format!(
                    "{status} covered by parent: {}",
                    format_ast_kind_counts(counts)
                ));
            }
        }
    }
    rows
}

fn dominates_ast_subtree(parent: &AstRollupLocus, child: &AstRollupLocus) -> bool {
    let Some(relative_path) = child.ast_path.strip_prefix(&parent.ast_path) else {
        return false;
    };
    if !relative_path.starts_with('.') {
        return false;
    }
    if parent_is_structural_body_container(&parent.ast_kind) && relative_path.starts_with(".body[")
    {
        return false;
    }
    true
}

fn parent_is_structural_body_container(ast_kind: &str) -> bool {
    matches!(ast_kind, "FunctionDef" | "AsyncFunctionDef" | "ClassDef")
}

fn is_constraint_ast_kind(ast_kind: &str) -> bool {
    matches!(
        ast_kind,
        "Assert"
            | "Assign"
            | "AnnAssign"
            | "AugAssign"
            | "Await"
            | "BinOp"
            | "BoolOp"
            | "Call"
            | "Compare"
            | "Dict"
            | "DictComp"
            | "For"
            | "FormattedValue"
            | "GeneratorExp"
            | "If"
            | "IfExp"
            | "JoinedStr"
            | "List"
            | "ListComp"
            | "Match"
            | "Raise"
            | "Return"
            | "Set"
            | "SetComp"
            | "Subscript"
            | "Try"
            | "Tuple"
            | "UnaryOp"
            | "While"
            | "Yield"
    )
}

fn format_ast_kind_counts(counts: &BTreeMap<String, i64>) -> String {
    counts
        .iter()
        .map(|(kind, count)| format!("{kind}={count}"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn source_status_order(status: &str) -> usize {
    match status {
        "warranted" => 0,
        "refused" => 1,
        "support" => 2,
        "inactive" => 3,
        "unresolved" => 4,
        _ => 5,
    }
}

fn normalized_source_status(status: Option<&str>) -> &str {
    match status {
        Some("warranted") => "warranted",
        Some("inactive") => "inactive",
        Some("support") => "support",
        Some("refused") => "refused",
        Some("unresolved") | Some("unclassified") | Some("silent") => "unresolved",
        _ => "unresolved",
    }
}

fn memento_group_key(memento: &Value) -> Option<String> {
    [
        memento.get("contractName").and_then(Value::as_str),
        memento.get("claimName").and_then(Value::as_str),
        memento.get("eufName").and_then(Value::as_str),
    ]
    .into_iter()
    .flatten()
    .next()
    .map(report_contract_group_key)
}

fn audit_report_group_key(audit: &Value) -> String {
    contract_name(audit)
        .map(report_contract_group_key)
        .unwrap_or_else(|| audit_role_group_key(audit))
}

fn audit_role_group_key(audit: &Value) -> String {
    format!(
        "{} / {}",
        audit
            .get("role")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        audit
            .get("universe_kind")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
    )
}

fn report_contract_group_key(name: &str) -> String {
    if name.starts_with("rust-source::") {
        name.to_string()
    } else {
        contract_group_key(name)
    }
}

fn report_memento_group_key(memento: &Value) -> String {
    memento_group_key(memento)
        .or_else(|| source_function_name(memento).map(|name| format!("rust-source::{name}")))
        .unwrap_or_else(|| {
            memento
                .get("role")
                .and_then(Value::as_str)
                .unwrap_or("<unknown source memento>")
                .to_string()
        })
}

fn source_function_name(source: &Value) -> Option<&str> {
    source
        .get("sourceFunctionName")
        .or_else(|| source.get("source_function_name"))
        .and_then(Value::as_str)
}

fn is_fact_source_memento(memento: &Value) -> bool {
    memento
        .get("role")
        .and_then(Value::as_str)
        .is_some_and(|role| role.ends_with("test-fact") || role.ends_with(".fact"))
}

fn format_fact_memento(memento: &Value) -> String {
    let role = memento
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let claim = memento
        .get("claimName")
        .or_else(|| memento.get("claim_name"))
        .and_then(Value::as_str)
        .unwrap_or("<unknown claim>");
    let contract = memento
        .get("contractName")
        .or_else(|| memento.get("contract_name"))
        .and_then(Value::as_str)
        .unwrap_or("<unknown contract>");
    format!(
        "{} [{role}] claim={claim} contract={contract}",
        format_source_ref(memento)
    )
}

fn format_fact_source_memento_ref(source: &Value) -> String {
    let mut row = format_source_ref(source);
    let source_cid = source
        .get("source_cid")
        .or_else(|| source.get("sourceCid"))
        .and_then(Value::as_str)
        .unwrap_or("<missing source cid>");
    row.push_str(&format!(" source_cid={source_cid}"));
    row
}

fn format_fact_source_locus_ref(locus: &Value) -> String {
    let file = locus
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown file>");
    let line = locus
        .get("line")
        .and_then(Value::as_i64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let ast_path = locus
        .get("ast_path")
        .and_then(Value::as_str)
        .unwrap_or("<unknown locus>");
    format!("{file}:{line} {ast_path} source=audit-locus")
}

fn render_assertion_surface_accounting(report: &LiftSourceReport) -> String {
    if report.assertion_surface_audits.is_empty() {
        return String::new();
    }
    trace_lift_source_report("render_assertion_surface_accounting.start", report);

    let facts_by_contract = report
        .contracts
        .iter()
        .filter_map(|contract| contract_value_name(contract).map(|name| (name, contract)))
        .collect::<BTreeMap<_, _>>();
    let total_facts = report
        .assertion_surface_audits
        .iter()
        .map(assertion_surface_fact_count)
        .sum::<usize>();
    let total_support = report
        .assertion_surface_audits
        .iter()
        .map(assertion_surface_support_fact_count)
        .sum::<usize>();
    let no_fact_count = report
        .assertion_surface_audits
        .iter()
        .filter(|row| assertion_surface_fact_count(row) == 0)
        .filter(|row| assertion_surface_support_fact_count(row) == 0)
        .count();
    let mut out = format!(
        "assertion surface accounting: sources={} facts={} support={} no_facts={}\n",
        report.assertion_surface_audits.len(),
        total_facts,
        total_support,
        no_fact_count
    );
    trace_lift_render_checkpoint(
        "render_assertion_surface_accounting.after_header",
        out.len(),
    );

    let mut rows = report.assertion_surface_audits.iter().collect::<Vec<_>>();
    rows.sort_by_key(|row| {
        (
            assertion_surface_row_class(row),
            row.get("file")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            row.get("line").and_then(Value::as_i64).unwrap_or(i64::MAX),
            assertion_surface_name(row).to_string(),
        )
    });
    tracing::info!(
        stage = "render_assertion_surface_accounting.after_sort",
        rss_kib = current_rss_kib().unwrap_or_default(),
        rss_available = current_rss_kib().is_some(),
        rows = rows.len(),
        contracts = report.contracts.len(),
        rendered_bytes = out.len(),
        "lift-report memory checkpoint"
    );

    let emitted = rows
        .iter()
        .copied()
        .filter(|row| assertion_surface_fact_count(row) > 0)
        .collect::<Vec<_>>();
    if !emitted.is_empty() {
        out.push_str("assertion facts emitted:\n");
        for row in emitted {
            out.push_str(&format_assertion_surface_row(row));
            if let Some(facts) = row.get("facts").and_then(Value::as_array) {
                render_assertion_surface_contract_refs(
                    &mut out,
                    "facts",
                    report,
                    &facts_by_contract,
                    facts,
                    true,
                );
            }
            if let Some(auxiliary_facts) = assertion_surface_auxiliary_facts(row) {
                render_assertion_surface_contract_refs(
                    &mut out,
                    "auxiliary",
                    report,
                    &facts_by_contract,
                    auxiliary_facts,
                    false,
                );
            }
        }
    }
    trace_lift_render_checkpoint(
        "render_assertion_surface_accounting.after_emitted",
        out.len(),
    );

    let support_only = rows
        .iter()
        .copied()
        .filter(|row| assertion_surface_fact_count(row) == 0)
        .filter(|row| assertion_surface_support_fact_count(row) > 0)
        .collect::<Vec<_>>();
    if !support_only.is_empty() {
        out.push_str("assertion support emitted:\n");
        for row in support_only {
            out.push_str(&format_assertion_surface_row(row));
            if let Some(auxiliary_facts) = assertion_surface_auxiliary_facts(row) {
                render_assertion_surface_contract_refs(
                    &mut out,
                    "auxiliary",
                    report,
                    &facts_by_contract,
                    auxiliary_facts,
                    false,
                );
            }
            if let Some(reason) = row.get("reason").and_then(Value::as_str) {
                if !reason.is_empty() {
                    out.push_str(&format!("    reason: {reason}\n"));
                }
            }
        }
    }
    trace_lift_render_checkpoint(
        "render_assertion_surface_accounting.after_support_only",
        out.len(),
    );

    let no_facts = rows
        .iter()
        .copied()
        .filter(|row| assertion_surface_fact_count(row) == 0)
        .filter(|row| assertion_surface_support_fact_count(row) == 0)
        .collect::<Vec<_>>();
    if !no_facts.is_empty() {
        out.push_str("assertion sources without facts:\n");
        for row in no_facts {
            out.push_str(&format_assertion_surface_row(row));
            if let Some(auxiliary_facts) = assertion_surface_auxiliary_facts(row) {
                render_assertion_surface_contract_refs(
                    &mut out,
                    "auxiliary",
                    report,
                    &facts_by_contract,
                    auxiliary_facts,
                    false,
                );
            }
            if let Some(reason) = row.get("reason").and_then(Value::as_str) {
                if !reason.is_empty() {
                    out.push_str(&format!("    reason: {reason}\n"));
                }
            }
        }
    }

    trace_lift_render_checkpoint("render_assertion_surface_accounting.end", out.len());
    out
}

fn render_assertion_surface_contract_refs(
    out: &mut String,
    label: &str,
    report: &LiftSourceReport,
    facts_by_contract: &BTreeMap<&str, &Value>,
    facts: &[Value],
    observed_fact: bool,
) {
    if facts.is_empty() {
        return;
    }
    out.push_str(&format!("    {label}:\n"));
    for fact in facts {
        if let Some(contract_name) = assertion_surface_fact_contract(fact) {
            if let Some(contract) = facts_by_contract.get(contract_name) {
                let rendered = if observed_fact {
                    format_contract_asserted_fact(report, contract)
                        .unwrap_or_else(|| format_contract_fol(contract))
                } else {
                    format_contract_fol(contract)
                };
                out.push_str(&format!("      - {rendered}\n"));
            } else {
                out.push_str(&format!("      - contract: {contract_name}\n"));
            }
        }
    }
}

fn assertion_surface_row_class(row: &Value) -> u8 {
    if assertion_surface_fact_count(row) > 0 {
        0
    } else if assertion_surface_support_fact_count(row) > 0 {
        1
    } else {
        2
    }
}

fn assertion_surface_name(row: &Value) -> &str {
    row.get("assertionSource")
        .or_else(|| row.get("assertion_source"))
        .and_then(Value::as_str)
        .unwrap_or("<unknown assertion source>")
}

fn assertion_surface_fact_count(row: &Value) -> usize {
    row.get("facts")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0)
}

fn assertion_surface_support_fact_count(row: &Value) -> usize {
    row.get("supportFacts")
        .or_else(|| row.get("support_facts"))
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0)
}

fn assertion_surface_auxiliary_facts(row: &Value) -> Option<&[Value]> {
    row.get("auxiliaryFacts")
        .or_else(|| row.get("auxiliary_facts"))
        .and_then(Value::as_array)
        .map(Vec::as_slice)
}

fn assertion_surface_fact_contract(fact: &Value) -> Option<&str> {
    fact.get("contract")
        .or_else(|| fact.get("contractName"))
        .or_else(|| fact.get("contract_name"))
        .and_then(Value::as_str)
}

fn format_assertion_surface_row(row: &Value) -> String {
    let file = row
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown file>");
    let line = row
        .get("line")
        .and_then(Value::as_i64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let status = row
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let facts = assertion_surface_fact_count(row);
    let support = assertion_surface_support_fact_count(row);
    format!(
        "  - {file}:{line} {} {status} facts={facts} support={support}\n",
        assertion_surface_name(row)
    )
}

fn format_counts(value: &Value) -> String {
    format!(
        "loci={} warranted={} inactive={} support={} refused={} unresolved={}",
        source_count(value, "source_loci"),
        source_count(value, "source_warranted"),
        source_count(value, "source_inactive"),
        source_count(value, "source_support"),
        source_count(value, "source_refused"),
        source_unresolved_count(value),
    )
}

fn source_count(value: &Value, field: &str) -> i64 {
    value.get(field).and_then(Value::as_i64).unwrap_or(0)
}

fn source_unresolved_count(value: &Value) -> i64 {
    value
        .get("source_unresolved")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        .max(
            value
                .get("unclassified_source")
                .and_then(Value::as_i64)
                .unwrap_or(0),
        )
}

fn render_factory_accounting(factory_audits: &[Value]) -> String {
    if factory_audits.is_empty() {
        return String::new();
    }

    let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
    for audit in factory_audits {
        let status = normalized_source_status(audit.get("status").and_then(Value::as_str));
        *counts.entry(status).or_default() += 1;
    }
    let mut out = format!(
        "factory accounting: sites={} warranted={} refused={} support={} unresolved={}\n",
        factory_audits.len(),
        counts.get("warranted").copied().unwrap_or(0),
        counts.get("refused").copied().unwrap_or(0),
        counts.get("support").copied().unwrap_or(0),
        counts.get("unresolved").copied().unwrap_or(0),
    );

    let mut rows = factory_audits.iter().collect::<Vec<_>>();
    rows.sort_by_key(|audit| {
        let status = normalized_source_status(audit.get("status").and_then(Value::as_str));
        (
            factory_status_order(status),
            audit
                .get("file")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            audit
                .get("line")
                .and_then(Value::as_i64)
                .unwrap_or(i64::MAX),
            audit
                .get("span")
                .map(source_span_sort_key)
                .unwrap_or((0, 0, 0, 0)),
        )
    });

    for status in ["unresolved", "refused", "support", "warranted"] {
        let status_rows = rows
            .iter()
            .copied()
            .filter(|audit| {
                normalized_source_status(audit.get("status").and_then(Value::as_str)) == status
            })
            .collect::<Vec<_>>();
        if status_rows.is_empty() {
            continue;
        }
        let heading = if status == "refused" {
            "factory boundaries (refused)"
        } else {
            match status {
                "unresolved" => "factory gaps (unresolved)",
                "support" => "factory support",
                "warranted" => "factory warranted",
                _ => "factory other",
            }
        };
        out.push_str(&format!("{heading}:\n"));
        for audit in status_rows.iter().take(12) {
            out.push_str(&format_factory_audit_row(audit));
        }
        if status_rows.len() > 12 {
            out.push_str(&format!(
                "  (+{} more {status} sites)\n",
                status_rows.len() - 12
            ));
        }
    }

    out
}

fn factory_status_order(status: &str) -> usize {
    match status {
        "unresolved" => 0,
        "refused" => 1,
        "support" => 2,
        "warranted" => 3,
        _ => 4,
    }
}

fn format_factory_audit_row(audit: &Value) -> String {
    let file = audit
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown file>");
    let line = audit
        .get("line")
        .and_then(Value::as_i64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let ast_kind = audit.get("ast_kind").and_then(Value::as_str).unwrap_or("?");
    let role = audit
        .get("requested_role")
        .and_then(Value::as_str)
        .unwrap_or("?");
    let selected = audit
        .get("selected")
        .and_then(Value::as_str)
        .unwrap_or("<none>");
    let output = audit.get("output").and_then(Value::as_str).unwrap_or("?");
    let source = audit
        .get("sourceMemento")
        .map(format_source_memento_value)
        .unwrap_or_else(|| "<source memento absent>".to_string());
    let mut row = format!(
        "  - {file}:{line} {ast_kind} role={role} selected={selected} output={output}\n    source: {source}\n"
    );
    let candidates = format_factory_candidates(audit);
    if !candidates.is_empty() {
        row.push_str(&format!("    candidates: {candidates}\n"));
    }
    if let Some(reason) = audit.get("reason").and_then(Value::as_str) {
        if !reason.is_empty() {
            let label = if normalized_source_status(audit.get("status").and_then(Value::as_str))
                == "refused"
            {
                "boundary"
            } else {
                "reason"
            };
            row.push_str(&format!("    {label}: {reason}\n"));
        }
    }
    row
}

fn format_factory_candidates(audit: &Value) -> String {
    let Some(candidates) = audit.get("candidates").and_then(Value::as_array) else {
        return String::new();
    };
    candidates
        .iter()
        .filter_map(|candidate| {
            let name = candidate.get("name").and_then(Value::as_str)?;
            let role = candidate.get("role").and_then(Value::as_str).unwrap_or("?");
            let comes_before = candidate
                .get("comesBefore")
                .and_then(Value::as_array)
                .map(|edges| {
                    edges
                        .iter()
                        .filter_map(Value::as_str)
                        .collect::<Vec<_>>()
                        .join("|")
                })
                .filter(|edges| !edges.is_empty())
                .unwrap_or_else(|| "-".to_string());
            let selected = candidate
                .get("selected")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let suffix = if selected { "*" } else { "" };
            Some(format!("{name}[{role}/before={comes_before}]{suffix}"))
        })
        .collect::<Vec<_>>()
        .join(", ")
}

fn contract_name(audit: &Value) -> Option<&str> {
    audit
        .get("contract")
        .and_then(|contract| contract.get("name"))
        .and_then(Value::as_str)
}

fn contract_value_name(contract: &Value) -> Option<&str> {
    contract.get("name").and_then(Value::as_str)
}

fn contract_group_key(name: &str) -> String {
    name.strip_suffix("::assertion").unwrap_or(name).to_string()
}

fn assertion_site_for_group(contracts: &[&Value]) -> Option<String> {
    contracts
        .iter()
        .filter_map(|contract| contract_value_name(contract))
        .find_map(assertion_site_from_contract_name)
}

fn assertion_site_from_contract_name(name: &str) -> Option<String> {
    let (_, after_at) = name.split_once('@')?;
    let (site, _) = after_at.split_once("::").unwrap_or((after_at, ""));
    if site.is_empty() {
        None
    } else {
        Some(site.to_string())
    }
}

fn format_source_memento(audit: &Value) -> String {
    let source = audit
        .get("source_memento")
        .or_else(|| audit.get("sourceMemento"));
    let role = audit
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let universe = audit
        .get("universe_kind")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    if source.is_none() {
        if let Some(package) = audit.get("package").and_then(Value::as_str) {
            let root = audit
                .get("package_root")
                .or_else(|| audit.get("packageRoot"))
                .and_then(Value::as_str)
                .unwrap_or("<unknown root>");
            return format!("package {package} at {root} [{role} / {universe}]");
        }
    }
    let Some(source) = source else {
        return format!("source audit [{role} / {universe}]");
    };
    format_source_memento_with_role(source, role, universe)
}

fn format_source_memento_value(source: &Value) -> String {
    let role = source
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or("source-memento");
    format_source_memento_with_role(source, role, "source")
}

fn format_source_memento_with_role(source: &Value, role: &str, universe: &str) -> String {
    format!(
        "{} [{role} / {universe}] source_cid={}",
        format_source_ref(source),
        source
            .get("source_cid")
            .or_else(|| source.get("sourceCid"))
            .and_then(Value::as_str)
            .unwrap_or("<missing source cid>")
    )
}

fn format_source_ref(source: &Value) -> String {
    let file = source
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown file>");
    let function = source_function_name(source).unwrap_or("<unknown function>");
    let params = source
        .get("param_names")
        .or_else(|| source.get("paramNames"))
        .and_then(Value::as_array)
        .map(|params| {
            params
                .iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join(", ")
        })
        .unwrap_or_default();
    let span = source
        .get("span")
        .map(format_span)
        .unwrap_or_else(|| "?:?".to_string());
    format!("{file}:{span} {function}({params})")
}

fn format_span(span: &Value) -> String {
    let start = span
        .get("start_line")
        .and_then(Value::as_i64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let end = span
        .get("end_line")
        .and_then(Value::as_i64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    if start == end {
        start
    } else {
        format!("{start}-{end}")
    }
}

fn format_contract_fol(contract: &Value) -> String {
    let name = contract_value_name(contract).unwrap_or("<unknown contract>");
    let rendered = contract_universe_reading(contract);
    format!("{name} :: {rendered}")
}

fn format_contract_universe_fol(contract: &Value) -> Option<String> {
    let name = contract_value_name(contract).unwrap_or("<unknown contract>");
    for field in ["post", "pre"] {
        if let Some(formula) = contract.get(field) {
            let rendered = proofir_formula_to_fol_with_instances(formula);
            return Some(format!("{name} :: {rendered}"));
        }
    }
    if !contract_inv_is_observed_fact(contract) {
        if let Some(formula) = contract.get("inv") {
            let rendered = proofir_formula_to_fol_with_instances(formula);
            return Some(format!("{name} :: {rendered}"));
        }
    }
    None
}

fn format_contract_asserted_fact(report: &LiftSourceReport, contract: &Value) -> Option<String> {
    if !contract_inv_is_observed_fact(contract) {
        return None;
    }
    let name = contract_value_name(contract).unwrap_or("<unknown contract>");
    let rendered = contract
        .get("inv")
        .map(proofir_formula_to_fol_with_instances)?;
    let mut row = format!("{name} :: {rendered}");
    if let Some(source) =
        contract_source_warrant(contract).or_else(|| source_memento_for_contract(report, name))
    {
        row.push_str(" @ ");
        row.push_str(&format_fact_source_memento_ref(source));
    } else if let Some(locus) = source_locus_for_contract(report, name) {
        row.push_str(" @ ");
        row.push_str(&format_fact_source_locus_ref(locus));
    }
    Some(row)
}

fn contract_inv_is_observed_fact(contract: &Value) -> bool {
    let Some(name) = contract_value_name(contract) else {
        return false;
    };
    name.ends_with("::assertion") || name.contains("::tests::")
}

fn contract_source_warrant(contract: &Value) -> Option<&Value> {
    contract
        .get("sourceWarrants")
        .or_else(|| contract.get("source_warrants"))
        .and_then(Value::as_array)
        .and_then(|warrants| warrants.first())
}

fn source_memento_for_contract<'a>(
    report: &'a LiftSourceReport,
    contract_name: &str,
) -> Option<&'a Value> {
    let owner = owning_source_function_name(contract_name);
    if let Some(owner) = owner.as_deref() {
        if let Some(memento) = report.source_mementos.iter().find(|memento| {
            source_function_name(memento)
                .is_some_and(|name| source_function_name_matches_owner(name, owner))
        }) {
            return Some(memento);
        }
    }
    report.source_mementos.iter().find(|memento| {
        source_function_name(memento)
            .is_some_and(|name| contract_name_matches_source_function(contract_name, name))
    })
}

fn source_locus_for_contract<'a>(
    report: &'a LiftSourceReport,
    contract_name: &str,
) -> Option<&'a Value> {
    let owner = owning_source_function_name(contract_name);
    for audit in &report.audits {
        let Some(loci) = audit.get("loci").and_then(Value::as_array) else {
            continue;
        };
        if let Some(owner) = owner.as_deref() {
            if let Some(locus) = loci.iter().find(|locus| {
                locus
                    .get("ast_path")
                    .and_then(Value::as_str)
                    .is_some_and(|path| source_function_name_matches_owner(path, owner))
            }) {
                return Some(locus);
            }
        }
        if let Some(locus) = loci.iter().find(|locus| {
            locus
                .get("ast_path")
                .and_then(Value::as_str)
                .is_some_and(|path| contract_name_matches_source_function(contract_name, path))
        }) {
            return Some(locus);
        }
    }
    None
}

fn owning_source_function_name(contract_name: &str) -> Option<String> {
    if let Some(name) = contract_name.strip_prefix("rust-source::") {
        return Some(name.to_string());
    }
    if let Some((_, tail)) = contract_name.split_once("::tests::") {
        let owner = tail.split("::").next().unwrap_or(tail);
        let owner = owner
            .split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
            .next()
            .unwrap_or(owner);
        if !owner.is_empty() {
            return Some(owner.to_string());
        }
    }
    None
}

fn source_function_name_matches_owner(source_name: &str, owner: &str) -> bool {
    source_name == owner || source_name.ends_with(&format!("::{owner}"))
}

fn contract_name_matches_source_function(contract_name: &str, source_name: &str) -> bool {
    if contract_name == source_name || contract_name == format!("rust-source::{source_name}") {
        return true;
    }
    contract_name.ends_with(&format!("::{source_name}"))
        || contract_name.contains(&format!("::{source_name}::"))
}

fn generalized_contract_fol(contract: &Value) -> Vec<String> {
    let name = contract_value_name(contract).unwrap_or("<unknown contract>");
    contract
        .get("inv")
        .map(generalized_formula_rows)
        .unwrap_or_default()
        .into_iter()
        .map(|row| format!("{name} :: {row}"))
        .collect()
}

fn generalized_formula_rows(formula: &Value) -> Vec<String> {
    if let Some(row) = generalized_base64_block_formula(formula) {
        return vec![row];
    }
    formula_operands(formula)
        .iter()
        .flat_map(generalized_formula_rows)
        .collect()
}

fn generalized_base64_block_formula(formula: &Value) -> Option<String> {
    if formula.get("kind").and_then(Value::as_str) != Some("atomic")
        || formula.get("name").and_then(Value::as_str) != Some("str.eq-bv-blocks")
    {
        return None;
    }
    let args = formula.get("args").and_then(Value::as_array)?;
    if args.len() != 2 {
        return None;
    }
    let payload = base64_payload_from_term(&args[1])?;
    let vars = payload_vars(&payload);
    let output = generalized_call_output(&args[0], &vars);
    let blocks = format_base64_payload_with_input(&payload, &format!("[{}]", vars.join(", ")));
    let quantifiers = vars
        .iter()
        .map(|name| format!("∀ {name}:Int. "))
        .collect::<String>();
    Some(format!("{quantifiers}str.eq-bv-blocks({output}, {blocks})"))
}

fn proofir_formula_to_fol_with_instances(formula: &Value) -> String {
    if let Some(rendered) = instantiated_base64_block_formula(formula) {
        return rendered;
    }
    let Some(kind) = formula.get("kind").and_then(Value::as_str) else {
        return proofir_formula_to_fol(formula);
    };
    match kind {
        "and" => {
            let operands = formula_operands(formula);
            if operands.is_empty() {
                "⊤".to_string()
            } else {
                format_formula_join_with_instances(&operands, " ∧ ")
            }
        }
        "or" => {
            let operands = formula_operands(formula);
            if operands.is_empty() {
                "⊥".to_string()
            } else {
                format_formula_join_with_instances(&operands, " ∨ ")
            }
        }
        "not" => {
            let operands = formula_operands(formula);
            match operands.as_slice() {
                [one] => format!(
                    "¬{}",
                    parenthesize_formula(&proofir_formula_to_fol_with_instances(one))
                ),
                _ => proofir_formula_to_fol(formula),
            }
        }
        "implies" => {
            let operands = formula_operands(formula);
            match operands.as_slice() {
                [left, right] => format!(
                    "{} ⇒ {}",
                    parenthesize_formula(&proofir_formula_to_fol_with_instances(left)),
                    parenthesize_formula(&proofir_formula_to_fol_with_instances(right))
                ),
                _ => proofir_formula_to_fol(formula),
            }
        }
        "forall" | "exists" => {
            let symbol = if kind == "forall" { "∀" } else { "∃" };
            let name = formula.get("name").and_then(Value::as_str).unwrap_or("?");
            let sort = formula
                .get("sort")
                .map(proofir_sort_to_fol)
                .unwrap_or_else(|| "?".to_string());
            let body = formula
                .get("body")
                .map(proofir_formula_to_fol_with_instances)
                .unwrap_or_else(|| "<missing body>".to_string());
            format!("{symbol} {name}:{sort}. {body}")
        }
        _ => proofir_formula_to_fol(formula),
    }
}

fn format_formula_join_with_instances(operands: &[Value], separator: &str) -> String {
    operands
        .iter()
        .map(|operand| parenthesize_formula(&proofir_formula_to_fol_with_instances(operand)))
        .collect::<Vec<_>>()
        .join(separator)
}

fn instantiated_base64_block_formula(formula: &Value) -> Option<String> {
    if formula.get("kind").and_then(Value::as_str) != Some("atomic")
        || formula.get("name").and_then(Value::as_str) != Some("str.eq-bv-blocks")
    {
        return None;
    }
    let args = formula.get("args").and_then(Value::as_array)?;
    if args.len() != 2 {
        return None;
    }
    let payload = base64_payload_from_term(&args[1])?;
    let instantiation = format_instantiation(&payload);
    Some(format!(
        "{instantiation} ⊢ {}",
        proofir_formula_to_fol(formula)
    ))
}

fn proofir_formula_to_fol(formula: &Value) -> String {
    let Some(kind) = formula.get("kind").and_then(Value::as_str) else {
        return serde_json::to_string(formula)
            .unwrap_or_else(|_| "<unrenderable formula>".to_string());
    };
    match kind {
        "true" | "True" => "⊤".to_string(),
        "false" | "False" => "⊥".to_string(),
        "atomic" | "Atomic" => {
            let name = formula.get("name").and_then(Value::as_str).unwrap_or("?");
            let args = formula
                .get("args")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if args.is_empty() {
                return match name {
                    "true" | "⊤" => "⊤".to_string(),
                    "false" | "⊥" => "⊥".to_string(),
                    _ => name.to_string(),
                };
            }
            if args.len() == 2 && is_infix_predicate(name) {
                return format!(
                    "{} {} {}",
                    proofir_term_to_fol(&args[0]),
                    fol_predicate_symbol(name),
                    proofir_term_to_fol(&args[1])
                );
            }
            let rendered_args = args
                .iter()
                .map(proofir_term_to_fol)
                .collect::<Vec<_>>()
                .join(", ");
            format!("{name}({rendered_args})")
        }
        "and" => {
            let operands = formula_operands(formula);
            if operands.is_empty() {
                "⊤".to_string()
            } else {
                format_formula_join(&operands, " ∧ ")
            }
        }
        "or" => {
            let operands = formula_operands(formula);
            if operands.is_empty() {
                "⊥".to_string()
            } else {
                format_formula_join(&operands, " ∨ ")
            }
        }
        "not" => {
            let operands = formula_operands(formula);
            match operands.as_slice() {
                [one] => format!("¬{}", parenthesize_formula(&proofir_formula_to_fol(one))),
                _ => format!("not({})", format_formula_join(&operands, ", ")),
            }
        }
        "implies" => {
            let operands = formula_operands(formula);
            match operands.as_slice() {
                [left, right] => format!(
                    "{} ⇒ {}",
                    parenthesize_formula(&proofir_formula_to_fol(left)),
                    parenthesize_formula(&proofir_formula_to_fol(right))
                ),
                _ => format!("implies({})", format_formula_join(&operands, ", ")),
            }
        }
        "forall" | "exists" => {
            let symbol = if kind == "forall" { "∀" } else { "∃" };
            let name = formula.get("name").and_then(Value::as_str).unwrap_or("?");
            let sort = formula
                .get("sort")
                .map(proofir_sort_to_fol)
                .unwrap_or_else(|| "?".to_string());
            let body = formula
                .get("body")
                .map(proofir_formula_to_fol)
                .unwrap_or_else(|| "<missing body>".to_string());
            format!("{symbol} {name}:{sort}. {body}")
        }
        "choice" => {
            let name = formula
                .get("var_name")
                .or_else(|| formula.get("varName"))
                .and_then(Value::as_str)
                .unwrap_or("?");
            let sort = formula
                .get("sort")
                .map(proofir_sort_to_fol)
                .unwrap_or_else(|| "?".to_string());
            let body = formula
                .get("body")
                .map(proofir_formula_to_fol)
                .unwrap_or_else(|| "<missing body>".to_string());
            format!("ε {name}:{sort}. {body}")
        }
        other => serde_json::to_string(formula)
            .unwrap_or_else(|_| format!("<unrenderable {other} formula>")),
    }
}

fn formula_operands(formula: &Value) -> Vec<Value> {
    formula
        .get("operands")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn format_formula_join(operands: &[Value], separator: &str) -> String {
    operands
        .iter()
        .map(|operand| parenthesize_formula(&proofir_formula_to_fol(operand)))
        .collect::<Vec<_>>()
        .join(separator)
}

fn parenthesize_formula(rendered: &str) -> String {
    if rendered == "⊤"
        || rendered == "⊥"
        || rendered.starts_with('∀')
        || rendered.starts_with('∃')
        || (!rendered.contains(" ∧ ") && !rendered.contains(" ∨ ") && !rendered.contains(" ⇒ "))
    {
        rendered.to_string()
    } else {
        format!("({rendered})")
    }
}

fn is_infix_predicate(name: &str) -> bool {
    matches!(
        name,
        "=" | "==" | "!=" | "≠" | ">" | ">=" | "≥" | "<" | "<=" | "≤"
    )
}

fn fol_predicate_symbol(name: &str) -> &str {
    match name {
        "==" => "=",
        "!=" => "≠",
        ">=" => "≥",
        "<=" => "≤",
        other => other,
    }
}

fn proofir_term_to_fol(term: &Value) -> String {
    if let Some(name) = term.get("var").and_then(Value::as_str) {
        return name.to_string();
    }
    if let Some(value) = term.get("int").or_else(|| term.get("real")) {
        return scalar_value_to_fol(value);
    }
    if let Some(value) = term.get("str").and_then(Value::as_str) {
        return quoted_string(value);
    }

    let Some(kind) = term.get("kind").and_then(Value::as_str) else {
        return scalar_value_to_fol(term);
    };
    match kind {
        "var" | "Var" => term
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_string(),
        "const" | "Const" => term
            .get("value")
            .map(scalar_value_to_fol)
            .unwrap_or_else(|| "?".to_string()),
        "ctor" | "Ctor" => {
            let name = term.get("name").and_then(Value::as_str).unwrap_or("?");
            let args = term
                .get("args")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if args.is_empty() {
                // A `call:`-prefixed ctor is a function/method invocation; an
                // empty arg list is a zero-arg call (`answer()`, `B::new()`),
                // so render the parens — they're what makes the universe read
                // as a call rather than a bare symbol. Nullary data ctors
                // (unit variants like `None`) keep their bare form.
                if name.starts_with("call:") {
                    return format!("{name}()");
                }
                return name.to_string();
            }
            if let Some(rendered) = format_symbolic_ctor(name, &args) {
                return rendered;
            }
            let rendered_args = args
                .iter()
                .map(proofir_term_to_fol)
                .collect::<Vec<_>>()
                .join(", ");
            format!("{name}({rendered_args})")
        }
        "let" | "Let" => proofir_let_term_to_fol(term),
        other => {
            serde_json::to_string(term).unwrap_or_else(|_| format!("<unrenderable {other} term>"))
        }
    }
}

fn proofir_let_term_to_fol(term: &Value) -> String {
    let bindings = term
        .get("bindings")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let body = term
        .get("body")
        .map(proofir_term_to_fol)
        .unwrap_or_else(|| "<missing body>".to_string());
    if bindings.is_empty() {
        return body;
    }
    let rendered_bindings = bindings
        .iter()
        .map(|binding| {
            let name = binding.get("name").and_then(Value::as_str).unwrap_or("?");
            let bound = binding
                .get("boundTerm")
                .or_else(|| binding.get("bound_term"))
                .map(proofir_term_to_fol)
                .unwrap_or_else(|| "<missing bound>".to_string());
            format!("{name} = {bound}")
        })
        .collect::<Vec<_>>()
        .join("; ");
    format!("let {rendered_bindings} in {body}")
}

fn format_symbolic_ctor(name: &str, args: &[Value]) -> Option<String> {
    if name == "cf_ite" {
        return format_cf_ite_term(args);
    }
    let symbol = match name {
        "bv32.add" | "concept:add" | "+" => "+",
        "bv32.sub" | "concept:sub" | "-" => "-",
        "bv32.mul" | "concept:mul" | "*" => "*",
        "/" => "/",
        "%" => "%",
        "bv32.and" => "&",
        "bv32.or" => "|",
        "bv32.xor" => "⊕",
        "bv32.shl" => "<<",
        "bv32.lshr" => ">>>",
        "cf_eq" => "=",
        "cf_ne" => "≠",
        "cf_lt" => "<",
        "cf_le" => "≤",
        "cf_gt" => ">",
        "cf_ge" => "≥",
        _ => return None,
    };
    if args.len() != 2 {
        return None;
    }
    Some(format!(
        "({} {} {})",
        proofir_term_to_fol(&args[0]),
        symbol,
        proofir_term_to_fol(&args[1])
    ))
}

fn format_cf_ite_term(args: &[Value]) -> Option<String> {
    if args.len() != 3 {
        return None;
    }
    Some(format!(
        "if {} then {} else {}",
        trim_wrapping_parens(&proofir_term_to_fol(&args[0])),
        proofir_term_to_fol(&args[1]),
        proofir_term_to_fol(&args[2])
    ))
}

fn trim_wrapping_parens(rendered: &str) -> &str {
    if rendered.starts_with('(') && rendered.ends_with(')') {
        &rendered[1..rendered.len() - 1]
    } else {
        rendered
    }
}

fn scalar_value_to_fol(value: &Value) -> String {
    match value {
        Value::String(s) => render_embedded_proofir_json(s).unwrap_or_else(|| quoted_string(s)),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Null => "null".to_string(),
        _ => serde_json::to_string(value).unwrap_or_else(|_| "<unrenderable value>".to_string()),
    }
}

fn render_embedded_proofir_json(value: &str) -> Option<String> {
    if !value.trim_start().starts_with('{') {
        return None;
    }
    let parsed: Value = serde_json::from_str(value).ok()?;
    if let Some(kind) = parsed.get("kind").and_then(Value::as_str) {
        if is_formula_kind(kind) {
            return Some(proofir_formula_to_fol(&parsed));
        }
        if is_term_kind(kind) {
            return Some(proofir_term_to_fol(&parsed));
        }
    }
    render_structured_payload(&parsed)
}

fn render_structured_payload(value: &Value) -> Option<String> {
    let payload = base64_payload_from_value(value)?;
    let input = format_scalar_array(&payload.input_bytes);
    Some(format_base64_payload_with_input(&payload, &input))
}

#[derive(Debug, Clone)]
struct Base64BlockPayload {
    input_bytes: Vec<Value>,
    vars: Vec<String>,
    per_char: Vec<Value>,
    table: Option<String>,
}

fn base64_payload_from_term(term: &Value) -> Option<Base64BlockPayload> {
    let raw = term.get("value").and_then(Value::as_str)?;
    let parsed: Value = serde_json::from_str(raw).ok()?;
    base64_payload_from_value(&parsed)
}

fn base64_payload_from_value(value: &Value) -> Option<Base64BlockPayload> {
    let input_bytes = value.get("input_bytes").and_then(Value::as_array)?.clone();
    let per_char = value.get("per_char").and_then(Value::as_array)?.clone();
    let vars = value
        .get("vars")
        .and_then(Value::as_array)
        .map(|vars| {
            vars.iter()
                .filter_map(Value::as_str)
                .map(ToOwned::to_owned)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let table = value
        .get("table")
        .and_then(Value::as_array)
        .and_then(|values| bytes_array_to_ascii(values.as_slice()));
    Some(Base64BlockPayload {
        input_bytes,
        vars,
        per_char,
        table,
    })
}

fn format_base64_payload_with_input(payload: &Base64BlockPayload, input: &str) -> String {
    let chars = payload
        .per_char
        .iter()
        .map(proofir_term_to_fol)
        .collect::<Vec<_>>()
        .join(", ");
    let table = payload
        .table
        .as_deref()
        .map(|table| format!(", table={}", quoted_string(table)))
        .unwrap_or_default();
    format!("base64.blocks(input={input}, chars=[{chars}]{table})")
}

fn payload_vars(payload: &Base64BlockPayload) -> Vec<String> {
    if payload.vars.len() == payload.input_bytes.len() && !payload.vars.is_empty() {
        return payload.vars.clone();
    }
    (0..payload.input_bytes.len())
        .map(|index| format!("b{index}"))
        .collect()
}

fn generalized_call_output(term: &Value, vars: &[String]) -> String {
    if term.get("kind").and_then(Value::as_str) == Some("ctor") {
        if let Some(name) = term.get("name").and_then(Value::as_str) {
            if name.starts_with("call:") {
                return format!("{name}(bytes({}))", vars.join(", "));
            }
        }
    }
    "output".to_string()
}

fn format_instantiation(payload: &Base64BlockPayload) -> String {
    payload_vars(payload)
        .iter()
        .zip(payload.input_bytes.iter())
        .map(|(name, value)| format!("{name}={}", scalar_value_to_fol(value)))
        .collect::<Vec<_>>()
        .join(", ")
}

fn format_scalar_array(values: &[Value]) -> String {
    let rendered = values
        .iter()
        .map(scalar_value_to_fol)
        .collect::<Vec<_>>()
        .join(", ");
    format!("[{rendered}]")
}

fn bytes_array_to_ascii(values: &[Value]) -> Option<String> {
    let mut out = String::new();
    for value in values {
        let byte = value.as_u64()?;
        if !(32..=126).contains(&byte) {
            return None;
        }
        out.push(char::from_u32(byte as u32)?);
    }
    Some(out)
}

fn is_formula_kind(kind: &str) -> bool {
    matches!(
        kind,
        "true"
            | "True"
            | "false"
            | "False"
            | "atomic"
            | "Atomic"
            | "and"
            | "or"
            | "not"
            | "implies"
            | "forall"
            | "exists"
            | "choice"
    )
}

fn is_term_kind(kind: &str) -> bool {
    matches!(kind, "var" | "Var" | "const" | "Const" | "ctor" | "Ctor")
}

fn quoted_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"<unrenderable string>\"".to_string())
}

fn proofir_sort_to_fol(sort: &Value) -> String {
    if let Some(name) = sort.as_str() {
        return name.to_string();
    }
    sort.get("name")
        .or_else(|| sort.get("kind"))
        .and_then(Value::as_str)
        .unwrap_or("?")
        .to_string()
}

fn lift_output_document(
    project_root: &PathBuf,
    surface: &str,
    response: &serde_json::Value,
) -> Result<String, libsugar::SugarError> {
    let mut doc = response.clone();
    if let Some(object) = doc.as_object_mut() {
        object
            .entry("sourceLanguage".to_string())
            .or_insert_with(|| serde_json::Value::String(surface.to_string()));
        object
            .entry("workspaceRoot".to_string())
            .or_insert_with(|| {
                serde_json::Value::String(
                    project_root
                        .canonicalize()
                        .unwrap_or_else(|_| project_root.to_path_buf())
                        .display()
                        .to_string(),
                )
            });
    }
    libsugar::canonical::json_jcs(&doc)
}

fn write_output(path: Option<&PathBuf>, bytes: &[u8]) -> Result<(), String> {
    match path {
        Some(path) if path.as_os_str() != "-" => {
            std::fs::write(path, bytes).map_err(|e| format!("write {}: {e}", path.display()))
        }
        _ => {
            let mut stdout = std::io::stdout().lock();
            stdout
                .write_all(bytes)
                .map_err(|e| format!("write stdout: {e}"))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::project_config::PluginEntry;
    use crate::OutputFlags;
    use sugar_verifier::{CallSite, Report, ReportRow};
    use syn::spanned::Spanned;

    fn minimal_source_report() -> LiftSourceReport {
        LiftSourceReport {
            ledger: serde_json::json!({
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "source_unresolved": 0
            }),
            audits: vec![serde_json::json!({
                "role": "rust-test-assertions",
                "universe_kind": "test-assertion",
                "loci": []
            })],
            factory_audits: vec![],
            factory_walk: vec![],
            assertion_surface_audits: vec![],
            source_mementos: vec![],
            contracts: vec![],
            call_edges: vec![],
            vendor_conjoins: vec![],
            project_root: None,
            source_oracle_routes: Vec::new(),
        }
    }

    fn prove_report_with_sat_witness() -> Report {
        let mut report = Report {
            total_callsites: 1,
            discharged: 1,
            ..Report::default()
        };
        report.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "method:is_match".to_string(),
                bridge_source_layer: "rust-test".to_string(),
                bridge_target_layer: "proofir".to_string(),
                property_name: "consistency:method:is_match".to_string(),
                ..CallSite::default()
            },
            status: "discharged".to_string(),
            reason: "solver witness accepted".to_string(),
            discharge_method: Some("solver-substantive".to_string()),
            body_discharge_tier: None,
            verification: Some(serde_json::json!({
                "kind": "consistency",
                "checkedFormula": {"kind": "atomic", "name": "str.in-regex"},
                "solverInvocations": [{
                    "solver": "z3",
                    "compiler": "smt-lib-v2.6",
                    "verdict": "sat",
                    "authoritative": true,
                    "solverInvocationCid": "blake3-512:invoke",
                    "solverArtifactCid": "blake3-512:artifact",
                    "solverVendorMementoCid": "blake3-512:vendor"
                }]
            })),
        });
        report
    }

    fn lift_response_with_source_axis() -> serde_json::Value {
        serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "commons-codec.PureJavaCrc32::update(byte[],int,int)::assertion",
                    "outBinding": "out",
                    "inv": {
                        "kind": "and",
                        "operands": [
                            {
                                "kind": "atomic",
                                "name": "crc32.eq-walked",
                                "args": [
                                    {
                                        "kind": "const",
                                        "value": 3808858755i64,
                                        "sort": {"kind": "primitive", "name": "Int"}
                                    },
                                    {
                                        "kind": "const",
                                        "value": "{\"kind\":\"bv32\",\"value\":\"0xe3069283\"}",
                                        "sort": {"kind": "primitive", "name": "String"}
                                    }
                                ]
                            }
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 80,
                "source_warranted": 26,
                "source_refused": 22,
                "source_inactive": 32,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "kind": "source-audit",
                    "role": "java.strong-universe",
                    "contract": {"name": "commons-codec.Base64::encodeBase64String"},
                    "totals": {
                        "source_loci": 51,
                        "source_warranted": 11,
                        "source_refused": 21,
                        "source_inactive": 19,
                        "unclassified_source": 0
                    },
                    "loci": [
                        {
                            "line": 780,
                            "status": "warranted",
                            "ast_kind": "Assignment",
                            "reason": "base64.full-block"
                        }
                    ]
                },
                {
                    "kind": "source-audit",
                    "role": "java.crc-value-pin",
                    "contract": {"name": "commons-codec.PureJavaCrc32::update(byte[],int,int)"},
                    "totals": {
                        "source_loci": 29,
                        "source_warranted": 15,
                        "source_refused": 1,
                        "source_inactive": 13,
                        "unclassified_source": 0
                    },
                    "loci": [
                        {
                            "line": 605,
                            "status": "warranted",
                            "ast_kind": "Assignment",
                            "reason": "crc32.slicing-by-8 input fold"
                        },
                        {
                            "line": 606,
                            "status": "warranted",
                            "ast_kind": "Assignment",
                            "reason": "crc32.slicing-by-8 input fold"
                        },
                        {
                            "line": 612,
                            "status": "warranted",
                            "ast_kind": "Assignment",
                            "reason": "crc32.slicing-by-8 table relation"
                        }
                    ]
                }
            ],
            "callEdges": [
                {
                    "schemaVersion": "1",
                    "kind": "call-edge",
                    "sourceContract": "commons-codec.PureJavaCrc32::knownVector",
                    "sourceContractCid": "blake3-512:source",
                    "targetContract": "commons-codec.PureJavaCrc32::update(byte[],int,int)",
                    "targetContractCid": "blake3-512:target",
                    "targetSymbol": "call:update",
                    "callSiteLocus": {"file": "CommonsCodecCrc32Test.java", "line": 44, "slot": "inv"},
                    "evidenceTerm": {"kind": "ctor", "name": "call:update", "args": []}
                }
            ],
            "sourceMementos": [
                {
                    "kind": "source-memento",
                    "role": "java.strong-universe",
                    "claimName": "commons-codec.Base64::encodeBase64String",
                    "contractName": "commons-codec.Base64::encodeBase64String",
                    "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "file": "Base64.java"
                },
                {
                    "kind": "source-memento",
                    "role": "java.crc-value-pin",
                    "claimName": "commons-codec.PureJavaCrc32::update(byte[],int,int)",
                    "contractName": "commons-codec.PureJavaCrc32::update(byte[],int,int)",
                    "source_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "file": "PureJavaCrc32.java"
                },
                {
                    "kind": "source-memento",
                    "role": "java.test-fact",
                    "claimName": "commons-codec.PureJavaCrc32::update(byte[],int,int)::facts",
                    "contractName": "commons-codec.PureJavaCrc32::update(byte[],int,int)::assertion",
                    "source_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                    "file": "CommonsCodecCrc32Test.java",
                    "source_function_name": "testKnownVector",
                    "span": {"start_line": 44, "start_col": 8, "end_line": 44, "end_col": 64}
                }
            ]
        })
    }

    #[test]
    fn human_report_can_append_prove_sat_witness() {
        let lift = minimal_source_report();
        let prove = prove_report_with_sat_witness();
        let human = render_report_human(&lift, Some(&prove));

        assert!(
            human.contains("source audit: loci=1 warranted=1"),
            "{human}"
        );
        assert!(human.contains("prove report (solver witness):"), "{human}");
        assert!(human.contains("Sugar verifier report"), "{human}");
        assert!(human.contains("discharged"), "{human}");
        assert!(human.contains("method:is_match"), "{human}");
        assert!(human.contains("z3 via smt-lib-v2.6: sat"), "{human}");
        assert!(human.contains("invocation: blake3-512:invoke"), "{human}");
        assert!(human.contains("artifact: blake3-512:artifact"), "{human}");
        assert!(
            human.contains("vendor memento: blake3-512:vendor"),
            "{human}"
        );
    }

    #[test]
    fn json_report_can_append_prove_sat_witness() {
        let lift = minimal_source_report();
        let prove = prove_report_with_sat_witness();
        let rendered = render_report_json(&lift, Some(&prove)).expect("render");
        let parsed: Value = serde_json::from_str(&rendered).expect("json");

        assert_eq!(parsed["kind"], "lift-prove-report");
        assert_eq!(parsed["lift"]["kind"], "lift-source-report");
        assert_eq!(parsed["prove"]["discharged"], 1);
        assert_eq!(parsed["prove"]["rows"][0]["status"], "discharged");
        assert_eq!(
            parsed["prove"]["rows"][0]["verification"]["solverInvocations"][0]["verdict"],
            "sat"
        );
        assert_eq!(
            parsed["prove"]["rows"][0]["verification"]["solverInvocations"][0]
                ["solverInvocationCid"],
            "blake3-512:invoke"
        );
    }

    #[test]
    fn lift_report_array_len_counts_camel_and_snake_case_fields() {
        let response = serde_json::json!({
            "sourceAudits": [1, 2],
            "factory_audits": [3, 4, 5],
            "scalar": 9
        });

        assert_eq!(
            lift_report_array_len(&response, &["sourceAudits", "source_audits"]),
            2
        );
        assert_eq!(
            lift_report_array_len(&response, &["factoryAudits", "factory_audits"]),
            3
        );
        assert_eq!(lift_report_array_len(&response, &["scalar"]), 0);
        assert_eq!(lift_report_array_len(&response, &["missing"]), 0);
    }

    #[test]
    fn lift_returns_ok() {
        let args = LiftArgs {
            project: Some(PathBuf::from("/sugar/no/such/lift/project")),
            output: None,
            identify_only: false,
            library_bindings: false,
            report: false,
            report_summary: false,
            visual: false,
            prove: false,
            z3: "z3".to_string(),
            with: vec![],
            contract: None,
            out: OutputFlags::default(),
        };
        assert_eq!(run(args), crate::EXIT_USER_ERROR);
    }

    #[test]
    fn report_prove_auto_mint_is_needed_only_when_project_has_no_proofs() {
        let dir = tempfile::tempdir().expect("tempdir");
        assert!(needs_lift_report_auto_mint(dir.path(), true));
        assert!(!needs_lift_report_auto_mint(dir.path(), false));

        std::fs::write(dir.path().join("blake3-512:existing.proof"), b"proof").unwrap();
        assert!(!needs_lift_report_auto_mint(dir.path(), true));
    }

    #[test]
    fn report_prove_auto_mint_ignores_nested_proof_files() {
        let dir = tempfile::tempdir().expect("tempdir");
        let nested = dir.path().join(".sugar").join("runs");
        std::fs::create_dir_all(&nested).unwrap();
        std::fs::write(nested.join("blake3-512:nested.proof"), b"proof").unwrap();

        assert!(needs_lift_report_auto_mint(dir.path(), true));
    }

    #[test]
    fn lift_uses_single_project_plugin_surface_without_authoring_section() {
        let project_cfg = ProjectConfig {
            plugins: vec![PluginEntry {
                kind: Some("lift".to_string()),
                surface: "java-test-assertions".to_string(),
                ..PluginEntry::default()
            }],
            ..ProjectConfig::default()
        };

        let resolved = configured_or_planned_lift_surface(
            Path::new("."),
            &project_cfg,
            &ProjectConfig::default(),
            false,
        )
        .expect("surface");
        assert_eq!(resolved.surface, "java-test-assertions");
    }

    #[test]
    fn lift_options_for_configured_surface_forward_matching_plugin_options() {
        let project_cfg = ProjectConfig {
            surface_lift: Some("rust-fn-contracts".to_string()),
            plugins: vec![
                PluginEntry {
                    kind: Some("lift".to_string()),
                    surface: "rust-fn-contracts".to_string(),
                    workspace_override: Some("/tmp/vendor-src".to_string()),
                    emit: Some("ir-document".to_string()),
                    layer: Some("all".to_string()),
                    ..PluginEntry::default()
                },
                PluginEntry {
                    kind: Some("lift".to_string()),
                    surface: "rust-implications".to_string(),
                    emit: Some("bridge-only".to_string()),
                    ..PluginEntry::default()
                },
            ],
            ..ProjectConfig::default()
        };

        let options = lift_options_for_configured_surface(&project_cfg, "rust-fn-contracts");

        assert_eq!(
            options.workspace_override.as_deref(),
            Some("/tmp/vendor-src")
        );
        assert_eq!(options.emit.as_deref(), Some("ir-document"));
        assert_eq!(options.layer.as_deref(), Some("all"));
        assert!(
            !options.identify_only && !options.library_bindings,
            "CLI flags are layered on after config-derived plugin options"
        );
    }

    #[test]
    fn source_report_preserves_kit_ledger_and_audits() {
        let report = source_report_from_lift_response(&lift_response_with_source_axis(), None)
            .expect("source report");

        assert_eq!(report.ledger["source_loci"], 80);
        assert_eq!(report.ledger["unclassified_source"], 0);
        assert_eq!(report.audits.len(), 2);
        assert_eq!(report.source_mementos.len(), 3);
        assert_eq!(report.call_edges.len(), 1);
        assert_eq!(
            report.audits[1]["contract"]["name"],
            "commons-codec.PureJavaCrc32::update(byte[],int,int)"
        );
    }

    #[test]
    fn source_report_filters_by_contract_substring_and_recomputes_ledger() {
        let report =
            source_report_from_lift_response(&lift_response_with_source_axis(), Some("Crc32"))
                .expect("filtered source report");

        assert_eq!(report.audits.len(), 1);
        assert_eq!(report.source_mementos.len(), 2);
        assert_eq!(report.call_edges.len(), 1);
        assert_eq!(report.source_mementos[0]["role"], "java.crc-value-pin");
        assert_eq!(report.ledger["source_loci"], 29);
        assert_eq!(report.ledger["source_warranted"], 15);
        assert_eq!(report.ledger["source_refused"], 1);
        assert_eq!(report.ledger["source_inactive"], 13);
        assert_eq!(report.ledger["unclassified_source"], 0);
    }

    #[test]
    fn source_report_refuses_missing_source_axis() {
        let error =
            source_report_from_lift_response(&serde_json::json!({"kind": "ir-document"}), None)
                .expect_err("missing sourceLedger should fail");

        assert!(error.contains("sourceLedger"));
    }

    #[test]
    fn source_report_names_upstream_refusal_loudly_not_blank_ledger() {
        // INSTRUMENT-NEVER-DARK regression: when the transport's finite-or-refuse byte
        // bound swaps the whole response for a `sugar-refused` marker, the source-audit
        // gate must fail LOUDLY naming the clip -- never the generic "missing sourceLedger"
        // (which hides the cause and reads like a kit bug) and never a silent empty
        // headline. A blind aggregate ledger cannot catch a false discharge.
        let refused = serde_json::json!({
            "sugar-refused": "response-term-exceeds-byte-bound",
            "reason": "lift response term exceeds serialized byte bound (268435456) -- unbounded, refused before clone/address (finite-or-refuse)",
        });
        let error = source_report_from_lift_response(&refused, None)
            .expect_err("an upstream-refused response must not yield a silent/empty ledger");

        assert!(
            error.contains("REFUSED upstream"),
            "error must name the upstream refusal, got: {error}"
        );
        assert!(
            error.contains("response-term-exceeds-byte-bound"),
            "error must carry the refusal kind, got: {error}"
        );
        assert!(
            error.contains("byte bound"),
            "error must surface the byte-bound reason, got: {error}"
        );
        assert!(
            !error.contains("the kit must emit"),
            "must not masquerade as the generic missing-sourceLedger kit bug, got: {error}"
        );
    }

    #[test]
    fn human_report_shows_crc_line_606_as_warranted() {
        let report =
            source_report_from_lift_response(&lift_response_with_source_axis(), Some("Crc32"))
                .expect("filtered source report");
        let human = render_source_report_human(&report);

        assert!(human.contains(
            "source audit: loci=29 warranted=15 inactive=13 support=0 refused=1 unresolved=0"
        ));
        assert!(human.contains("commons-codec.PureJavaCrc32::update(byte[],int,int)"));
        assert!(human.contains("facts observed:"));
        assert!(human.contains("CommonsCodecCrc32Test.java:44 testKnownVector() [java.test-fact]"));
        assert!(human.contains(
            "commons-codec.PureJavaCrc32::update(byte[],int,int)::assertion :: crc32.eq-walked"
        ));
        assert!(human.contains("call edges observed:"));
        assert!(human.contains("commons-codec.PureJavaCrc32::knownVector -> call:update -> commons-codec.PureJavaCrc32::update(byte[],int,int) cid=blake3-512:target @ CommonsCodecCrc32Test.java:44 inv"));
        assert!(human.contains("warranted complete walks:"));
        assert!(human.contains("606 warranted Assignment crc32.slicing-by-8 input fold"));
    }

    #[test]
    fn human_report_counts_source_support_axis() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 3,
                "source_warranted": 1,
                "source_support": 2,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "kind": "source-audit",
                    "role": "python.package-source",
                    "contract": {"name": "vendpkg#source-accounting"},
                    "totals": {
                        "source_loci": 3,
                        "source_warranted": 1,
                        "source_support": 2,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "unclassified_source": 0
                    },
                    "loci": [
                        {
                            "line": 1,
                            "status": "support",
                            "supportKind": "inert",
                            "ast_kind": "VendorClassDecl",
                            "ast_path": "$.module.body[0]"
                        },
                        {
                            "line": 2,
                            "status": "support",
                            "support_kind": "inert",
                            "ast_kind": "VendorComment",
                            "ast_path": "$.module.body[1]"
                        },
                        {
                            "line": 4,
                            "status": "warranted",
                            "ast_kind": "Return",
                            "ast_path": "$.module.body[1]"
                        }
                    ]
                }
            ],
            "sourceMementos": []
        });
        let report =
            source_report_from_lift_response(&response, None).expect("source support report");
        let human = render_source_report_human(&report);

        assert!(human.contains(
            "source audit: loci=3 warranted=1 inactive=0 support=2 refused=0 unresolved=0"
        ));
        assert!(human
            .contains("totals: loci=3 warranted=1 inactive=0 support=2 refused=0 unresolved=0"));
        assert!(human.contains("support roots: VendorClassDecl=1, VendorComment=1"));
    }

    #[test]
    fn human_report_reclassifies_support_without_inert_support_kind() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 0,
                "source_support": 1,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "kind": "source-audit",
                    "role": "python.package-source",
                    "contract": {"name": "vendpkg#source-accounting"},
                    "totals": {
                        "source_loci": 1,
                        "source_warranted": 0,
                        "source_support": 1,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "unclassified_source": 0
                    },
                    "loci": [
                        {
                            "line": 1,
                            "status": "support",
                            "ast_kind": "ClassDef",
                            "ast_path": "$.module.body[0]"
                        }
                    ]
                }
            ],
            "sourceMementos": []
        });
        let report =
            source_report_from_lift_response(&response, None).expect("source support report");
        let human = render_source_report_human(&report);

        assert!(human.contains(
            "source audit: loci=1 warranted=0 inactive=0 support=0 refused=0 unresolved=1"
        ));
        assert!(human.contains("unresolved roots: ClassDef=1"), "{human}");
        assert!(!human.contains("support roots: ClassDef=1"), "{human}");
        assert!(human.contains("support is reserved for kit-marked inert source loci"));
    }

    #[test]
    fn source_report_rejects_plaintext_factory_audit_sites() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "source_unresolved": 1
            },
            "sourceAudits": [],
            "sourceMementos": [],
            "factoryAudits": [
                {
                    "file": "src/lib.rs",
                    "line": 7,
                    "ast_kind": "expr",
                    "site": "|| 1",
                    "requested_role": "Composite",
                    "selected": null,
                    "candidates": [
                        {
                            "name": "closure_term",
                            "role": "Term",
                            "comesBefore": [],
                            "selected": false
                        }
                    ],
                    "status": "unresolved",
                    "output": "structural-backstop",
                    "reason": "no Sugar candidate for role Composite at `|| 1`; write more Sugar for this AST"
                }
            ]
        });
        let error = source_report_from_lift_response(&response, None)
            .expect_err("plaintext source in factoryAudits must be a protocol error");

        assert!(
            error.contains("factoryAudits carried plaintext source/term"),
            "{error}"
        );
    }

    #[test]
    fn human_report_shows_package_source_accounting_without_memento() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 1
            },
            "sourceAudits": [
                {
                    "kind": "source-audit",
                    "role": "python.package-source",
                    "universe_kind": "package-accounting",
                    "package": "itsdangerous",
                    "package_root": "/site-packages/itsdangerous",
                    "contract": {"name": "itsdangerous#source-accounting"},
                    "totals": {
                        "source_loci": 1,
                        "source_warranted": 0,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "unclassified_source": 1
                    },
                    "loci": [
                        {
                            "file": "/site-packages/itsdangerous/serializer.py",
                            "line": 245,
                            "status": "unclassified",
                            "ast_kind": "FunctionDef",
                            "reason": "not classified by any emitted Python source warrant"
                        }
                    ]
                }
            ],
            "sourceMementos": []
        });
        let report =
            source_report_from_lift_response(&response, Some("itsdangerous")).expect("report");
        let human = render_source_report_human(&report);

        assert!(human.contains(
            "package itsdangerous at /site-packages/itsdangerous [python.package-source / package-accounting]"
        ));
        assert!(!human.contains("<missing source memento>"));
        assert!(
            human.contains("/site-packages/itsdangerous/serializer.py:245 unresolved FunctionDef")
        );
    }

    #[test]
    fn human_report_shows_compact_package_source_accounting() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 5,
                "source_warranted": 1,
                "source_support": 2,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 2
            },
            "sourceAudits": [
                {
                    "kind": "source-audit",
                    "role": "python.package-source",
                    "universe_kind": "package-accounting",
                    "accounting_mode": "structural",
                    "loci_elided": true,
                    "package": "pandas",
                    "package_root": "/site-packages/pandas",
                    "contract": {"name": "pandas#source-accounting"},
                    "totals": {
                        "source_loci": 5,
                        "source_warranted": 1,
                        "source_support": 2,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "unclassified_source": 2
                    },
                    "ast_type_counts": {
                        "warranted": {"Return": 1},
                        "support": {"FunctionDef": 1, "VendorDecl": 1},
                        "unclassified": {"Assign": 1, "Call": 1}
                    },
                    "supportKindCounts": {
                        "inert": {"VendorDecl": 1}
                    },
                    "sample_loci": [
                        {
                            "file": "/site-packages/pandas/core/frame.py",
                            "line": 10,
                            "status": "unclassified",
                            "ast_kind": "Assign",
                            "reason": "not classified by any emitted Python source warrant"
                        }
                    ]
                }
            ],
            "sourceMementos": []
        });
        let report = source_report_from_lift_response(&response, Some("pandas")).expect("report");
        let human = render_source_report_human(&report);

        assert!(human.contains("loci: elided (structural package accounting)"));
        assert!(human.contains("warranted: Return=1"));
        assert!(human.contains("support: VendorDecl=1"));
        assert!(!human.contains("support: FunctionDef=1"));
        assert!(human.contains("unresolved: Assign=1, Call=1, FunctionDef=1"));
        assert!(human.contains(
            "source audit: loci=5 warranted=1 inactive=0 support=1 refused=0 unresolved=3"
        ));
        assert!(human.contains("sample loci:"));
        assert!(human.contains("/site-packages/pandas/core/frame.py:10 unresolved Assign"));
    }

    #[test]
    fn human_report_summarizes_source_ast_types_by_status() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 4,
                "source_warranted": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 4
            },
            "sourceAudits": [
                {
                    "kind": "source-audit",
                    "role": "python.package-source",
                    "universe_kind": "package-accounting",
                    "package": "vendpkg",
                    "package_root": "/site-packages/vendpkg",
                    "contract": {"name": "vendpkg#source-accounting"},
                    "totals": {
                        "source_loci": 4,
                        "source_warranted": 0,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "unclassified_source": 4
                    },
                    "loci": [
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 10,
                            "status": "unclassified",
                            "ast_kind": "Assign"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 11,
                            "status": "unclassified",
                            "ast_kind": "If"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 11,
                            "status": "unclassified",
                            "ast_kind": "Compare"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 11,
                            "status": "unclassified",
                            "ast_kind": "Subscript"
                        }
                    ]
                }
            ],
            "sourceMementos": []
        });
        let report = source_report_from_lift_response(&response, Some("vendpkg")).expect("report");
        let human = render_source_report_human(&report);

        assert!(human.contains("  ast types:\n"));
        assert!(human.contains("    unresolved: Assign=1, Compare=1, If=1, Subscript=1"));
    }

    #[test]
    fn human_report_rolls_ast_children_up_to_actionable_parent_shapes() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 10,
                "source_warranted": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 10
            },
            "sourceAudits": [
                {
                    "kind": "source-audit",
                    "role": "python.package-source",
                    "universe_kind": "package-accounting",
                    "package": "vendpkg",
                    "package_root": "/site-packages/vendpkg",
                    "contract": {"name": "vendpkg#source-accounting"},
                    "totals": {
                        "source_loci": 10,
                        "source_warranted": 0,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "unclassified_source": 10
                    },
                    "loci": [
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 1,
                            "status": "unclassified",
                            "ast_kind": "ImportFrom",
                            "ast_path": "$.module.body[0]"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 1,
                            "status": "unclassified",
                            "ast_kind": "alias",
                            "ast_path": "$.module.body[0].names[0]"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 3,
                            "status": "unclassified",
                            "ast_kind": "FunctionDef",
                            "ast_path": "$.module.body[1]"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 3,
                            "status": "unclassified",
                            "ast_kind": "arg",
                            "ast_path": "$.module.body[1].args.args[0]"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 4,
                            "status": "unclassified",
                            "ast_kind": "Assign",
                            "ast_path": "$.module.body[1].body[0]"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 4,
                            "status": "unclassified",
                            "ast_kind": "Name",
                            "ast_path": "$.module.body[1].body[0].targets[0]"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 5,
                            "status": "unclassified",
                            "ast_kind": "If",
                            "ast_path": "$.module.body[1].body[1]"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 5,
                            "status": "unclassified",
                            "ast_kind": "Compare",
                            "ast_path": "$.module.body[1].body[1].test"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 5,
                            "status": "unclassified",
                            "ast_kind": "Subscript",
                            "ast_path": "$.module.body[1].body[1].test.comparators[0]"
                        },
                        {
                            "file": "/site-packages/vendpkg/core.py",
                            "line": 5,
                            "status": "unclassified",
                            "ast_kind": "Name",
                            "ast_path": "$.module.body[1].body[1].test.comparators[0].value"
                        }
                    ]
                }
            ],
            "sourceMementos": []
        });
        let report = source_report_from_lift_response(&response, Some("vendpkg")).expect("report");
        let human = render_source_report_human(&report);

        assert!(human.contains("  ast rollup:\n"));
        assert!(human.contains("    unresolved roots: Assign=1, FunctionDef=1, If=1, ImportFrom=1"));
        assert!(human.contains("    unresolved constraint roots: Assign=1, If=1"));
        assert!(human.contains("    unresolved constraint children: Compare=1, Subscript=1"));
        assert!(!human.contains("    unresolved support roots: FunctionDef=1"));
        assert!(human.contains(
            "    unresolved covered by parent: Compare=1, Name=2, Subscript=1, alias=1, arg=1"
        ));
    }

    #[test]
    fn proofir_fol_printer_renders_symbolic_quantifiers_and_connectives() {
        let formula = serde_json::json!({
            "kind": "forall",
            "name": "x",
            "sort": {"kind": "primitive", "name": "Int"},
            "body": {
                "kind": "implies",
                "operands": [
                    {
                        "kind": "and",
                        "operands": [
                            {
                                "kind": "atomic",
                                "name": ">=",
                                "args": [
                                    {"kind": "var", "name": "x"},
                                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                                ]
                            },
                            {
                                "kind": "atomic",
                                "name": "<",
                                "args": [
                                    {"var": "x"},
                                    {"int": 10}
                                ]
                            }
                        ]
                    },
                    {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "call:encode",
                                "args": [{"kind": "var", "name": "x"}]
                            },
                            {"kind": "const", "value": "baz", "sort": {"kind": "primitive", "name": "String"}}
                        ]
                    }
                ]
            }
        });

        assert_eq!(
            proofir_formula_to_fol(&formula),
            "∀ x:Int. (x ≥ 0 ∧ x < 10) ⇒ call:encode(x) = \"baz\""
        );
    }

    #[test]
    fn proofir_fol_printer_renders_embedded_proofir_term_strings() {
        let formula = serde_json::json!({
            "kind": "atomic",
            "name": "crc32.eq-walked",
            "args": [
                {"kind": "const", "value": 3421780262i64, "sort": {"kind": "primitive", "name": "Int"}},
                {
                    "kind": "const",
                    "value": "{\"kind\":\"ctor\",\"name\":\"bv32.xor\",\"args\":[{\"kind\":\"const\",\"value\":1},{\"kind\":\"const\",\"value\":2}]}",
                    "sort": {"kind": "primitive", "name": "String"}
                }
            ]
        });

        assert_eq!(
            proofir_formula_to_fol(&formula),
            "crc32.eq-walked(3421780262, (1 ⊕ 2))"
        );
    }

    #[test]
    fn proofir_fol_printer_renders_let_terms_symbolically_without_json() {
        let formula = serde_json::json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "result"},
                {
                    "kind": "let",
                    "bindings": [
                        {
                            "name": "rem",
                            "boundTerm": {
                                "kind": "ctor",
                                "name": "%",
                                "args": [
                                    {"kind": "var", "name": "bytes_len"},
                                    {"kind": "const", "value": 3, "sort": {"kind": "primitive", "name": "Int"}}
                                ]
                            }
                        }
                    ],
                    "body": {
                        "kind": "ctor",
                        "name": "cf_ite",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "cf_gt",
                                "args": [
                                    {"kind": "var", "name": "rem"},
                                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                                ]
                            },
                            {"kind": "var", "name": "some_len"},
                            {"kind": "ctor", "name": "Some", "args": [{"kind": "var", "name": "complete_chunk_output"}]}
                        ]
                    }
                }
            ]
        });

        let rendered = proofir_formula_to_fol(&formula);
        assert_eq!(
            rendered,
            "result = let rem = (bytes_len % 3) in if rem > 0 then some_len else Some(complete_chunk_output)"
        );
        assert!(
            !rendered.contains("boundTerm") && !rendered.contains("\"kind\""),
            "FOL output must not leak serialized ProofIR JSON: {rendered}"
        );
    }

    #[test]
    fn proofir_fol_printer_summarizes_structured_base64_payloads() {
        let formula = serde_json::json!({
            "kind": "atomic",
            "name": "str.eq-bv-blocks",
            "args": [
                {"kind": "ctor", "name": "call:encodeBase64String", "args": [{"kind": "const", "value": "foo"}]},
                {
                    "kind": "const",
                    "value": "{\"input_bytes\":[102,111,111],\"per_char\":[{\"kind\":\"ctor\",\"name\":\"bv32.and\",\"args\":[{\"kind\":\"ctor\",\"name\":\"bv32.lshr\",\"args\":[{\"kind\":\"var\",\"name\":\"bits\"},{\"kind\":\"const\",\"value\":18}]},{\"kind\":\"const\",\"value\":63}]}],\"table\":[65,66,67,43,47]}",
                    "sort": {"kind": "primitive", "name": "String"}
                }
            ]
        });

        assert_eq!(
            proofir_formula_to_fol(&formula),
            "str.eq-bv-blocks(call:encodeBase64String(\"foo\"), base64.blocks(input=[102, 111, 111], chars=[((bits >>> 18) & 63)], table=\"ABC+/\"))"
        );
    }

    #[test]
    fn human_report_shows_generalized_and_instantiated_base64_fol() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "encodeBase64String#euf#c:callresult_encodeBase64String_a1(s:foo)::assertion",
                    "outBinding": "out",
                    "inv": {
                        "kind": "atomic",
                        "name": "str.eq-bv-blocks",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "call:encodeBase64String",
                                "args": [{"kind": "const", "value": "foo", "sort": {"kind": "primitive", "name": "String"}}]
                            },
                            {
                                "kind": "const",
                                "value": "{\"input_bytes\":[102,111,111],\"vars\":[\"b0\",\"b1\",\"b2\"],\"per_char\":[{\"kind\":\"ctor\",\"name\":\"bv32.and\",\"args\":[{\"kind\":\"ctor\",\"name\":\"bv32.lshr\",\"args\":[{\"kind\":\"var\",\"name\":\"bits\"},{\"kind\":\"const\",\"value\":18}]},{\"kind\":\"const\",\"value\":63}]}],\"table\":[65,66,67,43,47]}",
                                "sort": {"kind": "primitive", "name": "String"}
                            }
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "kind": "source-audit",
                    "role": "java.strong-universe",
                    "universe_kind": "str.eq-bv-blocks",
                    "contract": {"name": "encodeBase64String#euf#c:callresult_encodeBase64String_a1(s:foo)::assertion"},
                    "source_memento": {
                        "kind": "source-memento",
                        "role": "java.strong-universe",
                        "file": "Base64.java",
                        "source_function_name": "encode",
                        "span": {"start_line": 723, "end_line": 793},
                        "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    },
                    "totals": {
                        "source_loci": 1,
                        "source_warranted": 1,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "unclassified_source": 0
                    },
                    "loci": []
                }
            ],
            "sourceMementos": [
                {
                    "kind": "source-memento",
                    "role": "java.strong-universe",
                    "claimName": "encodeBase64String#euf#c:callresult_encodeBase64String_a1(s:foo)::assertion",
                    "contractName": "encodeBase64String#euf#c:callresult_encodeBase64String_a1(s:foo)::assertion",
                    "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "file": "Base64.java"
                }
            ]
        });
        let report = source_report_from_lift_response(&response, Some("encodeBase64"))
            .expect("source report");
        let human = render_source_report_human(&report);

        assert!(human.contains("generalized FOL:"));
        assert!(human.contains("∀ b0:Int. ∀ b1:Int. ∀ b2:Int."));
        assert!(human.contains("call:encodeBase64String(bytes(b0, b1, b2))"));
        assert!(human.contains("instantiated FOL:"));
        assert!(human.contains(
            "b0=102, b1=111, b2=111 ⊢ str.eq-bv-blocks(call:encodeBase64String(\"foo\")"
        ));
    }

    #[test]
    fn json_report_wraps_ledger_and_audits() {
        let report =
            source_report_from_lift_response(&lift_response_with_source_axis(), Some("Crc32"))
                .expect("filtered source report");
        let rendered = render_report_json(&report, None).expect("json report");
        let parsed: serde_json::Value = serde_json::from_str(&rendered).expect("valid json");

        assert_eq!(parsed["kind"], "lift-source-report");
        assert_eq!(parsed["sourceLedger"]["source_loci"], 29);
        assert_eq!(parsed["sourceAudits"].as_array().unwrap().len(), 1);
        assert_eq!(parsed["sourceMementos"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn summary_report_renders_gate_accounting_without_universe_dump() {
        let root = tempfile::tempdir().expect("tempdir");
        let source_dir = root.path().join("tests");
        std::fs::create_dir_all(&source_dir).expect("mkdir source dir");
        std::fs::write(
            source_dir.join("foo.rs"),
            "fn sample() { let x = 1 + 2; let y = runtime(); }\n",
        )
        .expect("write source");
        let source: syn::File = syn::parse_file(
            &std::fs::read_to_string(source_dir.join("foo.rs")).expect("read source"),
        )
        .expect("parse source");
        let syn::Item::Fn(item) = &source.items[0] else {
            panic!("expected function");
        };
        let syn::Stmt::Local(first) = &item.block.stmts[0] else {
            panic!("expected first let");
        };
        let syn::Stmt::Local(second) = &item.block.stmts[1] else {
            panic!("expected second let");
        };
        let first_memento = sugar_walk::source_oracle::source_memento_of_term_span(
            "tests/foo.rs",
            &std::fs::read_to_string(source_dir.join("foo.rs")).expect("read source"),
            first.init.as_ref().expect("first init").expr.span(),
            "sample",
            &item.sig,
            &item.block,
        )
        .expect("first term memento")
        .to_json();
        let second_memento = sugar_walk::source_oracle::source_memento_of_term_span(
            "tests/foo.rs",
            &std::fs::read_to_string(source_dir.join("foo.rs")).expect("read source"),
            second.init.as_ref().expect("second init").expr.span(),
            "sample",
            &item.sig,
            &item.block,
        )
        .expect("second term memento")
        .to_json();
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "Foo::huge",
                    "outBinding": "out",
                    "post": { "kind": "atomic", "name": "=", "args": [
                        {"kind": "var", "name": "out"}, {"kind": "const", "value": 7}
                    ]}
                }
            ],
            "sourceLedger": {
                "source_loci": 2,
                "source_warranted": 1,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 1,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAuditSummary": {
                "emittedRows": 5,
                "statusCounts": {
                    "warranted": 3,
                    "refused": 1,
                    "support": 0,
                    "unresolved": 1
                },
                "unresolvedSites": [
                    {
                        "file": "tests/foo.rs",
                        "line": 1,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": null,
                        "reason": "no sugar recognizer reached bedrock",
                        "status": "unresolved",
                        "sourceMemento": second_memento
                    }
                ],
                "factoryWalk": [
                    {
                        "file": "tests/foo.rs",
                        "line": 1,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "binary",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "term",
                        "sourceMemento": first_memento
                    },
                    {
                        "file": "tests/foo.rs",
                        "line": 1,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": null,
                        "status": "unresolved",
                        "verdict": "incomplete",
                        "output": "structural-backstop",
                        "reason": "no sugar recognizer reached bedrock",
                        "sourceMemento": second_memento
                    }
                ]
            }
        });
        let summary =
            source_report_summary_from_lift_response(&response, root.path()).expect("summary");
        let human = render_report_summary_human(&summary);
        let json = render_report_summary_json(&summary).expect("summary json");
        let parsed_json: serde_json::Value =
            serde_json::from_str(&json).expect("valid summary json");

        assert!(human.contains(
            "source accounting: loci=2 warranted=1 inactive=0 support=0 refused=1 unresolved=0"
        ));
        assert!(human
            .contains("factory accounting: sites=5 warranted=3 refused=1 support=0 unresolved=1"));
        assert!(human.contains("unresolved source lines: 1"), "{human}");
        assert!(human.contains("  tests/foo.rs:1"), "{human}");
        assert!(
            human.contains(
                "    [Term/expr] selected=<none> term=`runtime()` reason=no sugar recognizer reached bedrock"
            ),
            "{human}"
        );
        assert!(human.contains("factory whole-walk:"), "{human}");
        assert!(human.contains("complete [Term/expr] selected=binary output=term term=`1 + 2`"));
        assert!(human.contains("GAP HERE [Term/expr] selected=<none> output=gap term=`runtime()`"));
        assert!(parsed_json.get("sourceLedger").is_none(), "{json}");
        assert_eq!(parsed_json["sourceAccounting"]["loci"], 2);
        assert_eq!(parsed_json["sourceAccounting"]["unresolved"], 0);
        assert_eq!(parsed_json["factoryAccounting"]["unresolved"], 1);
        assert_eq!(
            parsed_json["unresolvedSourceLines"][0]["file"],
            "tests/foo.rs"
        );
        assert_eq!(parsed_json["unresolvedSourceLines"][0]["line"], "1");
        assert_eq!(
            parsed_json["unresolvedSourceLines"][0]["sites"][0]["sourceMemento"]["file"],
            "tests/foo.rs"
        );
        assert_eq!(
            parsed_json["unresolvedFactorySites"][0]["file"],
            "tests/foo.rs"
        );
        assert_eq!(parsed_json["unresolvedFactorySites"][0]["line"], 1);
        assert_eq!(parsed_json["factoryWalk"][1]["status"], "unresolved");
        assert_eq!(parsed_json["factoryWalk"][1]["verdict"], "gap");
        assert_eq!(parsed_json["factoryWalk"][1]["output"], "gap");
        assert!(parsed_json["unresolvedFactorySites"][0]
            .get("term")
            .is_none());
        assert!(parsed_json["unresolvedFactorySites"][0]
            .get("site")
            .is_none());
        assert!(parsed_json["factoryWalk"][0].get("term").is_none());
        assert!(parsed_json["factoryWalk"][0].get("site").is_none());
        assert!(!human.contains("superposition"), "{human}");
        assert!(!human.contains("universe(s)"), "{human}");
        assert!(!human.contains("contract: Foo::huge"), "{human}");
        assert!(!human.contains("lifted FOL"), "{human}");
    }

    #[test]
    fn full_report_renders_factory_walk_from_summary() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 0,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 1,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 4,
                "statusCounts": {
                    "warranted": 3,
                    "refused": 1,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": [
                    {
                        "file": "src/lib.rs",
                        "line": 4,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "literal_int",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "term"
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 5,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "literal_int",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "term"
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 6,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "address_cast",
                        "status": "refused",
                        "verdict": "incomplete",
                        "output": "effect",
                        "reason": "runtime boundary: pointer identity"
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 7,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "literal_int",
                        "status": "refused",
                        "verdict": "incomplete",
                        "output": "effect",
                        "reason": "runtime boundary already reached"
                    }
                ]
            }
        });

        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(human.contains("factory whole-walk:"), "{human}");
        assert!(
            human.contains("complete [Term/expr] selected=literal_int output=term"),
            "{human}"
        );
        assert!(
            human.contains("INCOMPLETE HERE [Term/expr] selected=address_cast output=effect"),
            "{human}"
        );
        assert!(
            human.contains("incomplete [Term/expr] selected=literal_int output=effect"),
            "{human}"
        );
    }

    #[test]
    fn factory_walk_marks_incomplete_here_in_walk_order_not_span_order() {
        let child_memento = serde_json::json!({
            "file": "src/lib.rs",
            "sourceFunctionName": "demo",
            "span": {"start_line": 7, "start_col": 18, "end_line": 7, "end_col": 24},
            "paramNames": []
        });
        let parent_memento = serde_json::json!({
            "file": "src/lib.rs",
            "sourceFunctionName": "demo",
            "span": {"start_line": 7, "start_col": 4, "end_line": 7, "end_col": 25},
            "paramNames": []
        });
        let summary = LiftReportSummary {
            ledger: serde_json::json!({}),
            factory: FactoryAccountingSummary {
                sites: 2,
                warranted: 0,
                refused: 2,
                support: 0,
                unresolved: 0,
            },
            unresolved_factory_sites: vec![],
            factory_walk: vec![
                serde_json::json!({
                    "file": "src/lib.rs",
                    "line": 7,
                    "requested_role": "Term",
                    "ast_kind": "expr",
                    "selected": "address_cast",
                    "status": "refused",
                    "verdict": "incomplete",
                    "output": "effect",
                    "reason": "runtime boundary: pointer identity",
                    "sourceMemento": child_memento
                }),
                serde_json::json!({
                    "file": "src/lib.rs",
                    "line": 7,
                    "requested_role": "Term",
                    "ast_kind": "expr",
                    "selected": "let_binding",
                    "status": "refused",
                    "verdict": "incomplete",
                    "output": "effect",
                    "reason": "runtime boundary: pointer identity",
                    "sourceMemento": parent_memento
                }),
            ],
            project_root: None,
        };

        let human = render_factory_walk(&summary);
        let child = human
            .find("INCOMPLETE HERE [Term/expr] selected=address_cast")
            .unwrap_or_else(|| panic!("child boundary must be marked HERE:\n{human}"));
        let parent = human
            .find("incomplete [Term/expr] selected=let_binding")
            .unwrap_or_else(|| panic!("parent bubble must be plain incomplete:\n{human}"));

        assert!(child < parent, "{human}");
    }

    #[test]
    fn visual_report_prints_source_lines_green_and_red_with_effect_inline() {
        let root = tempfile::tempdir().expect("tempdir");
        let source_dir = root.path().join("src");
        std::fs::create_dir_all(&source_dir).expect("mkdir source dir");
        std::fs::write(
            source_dir.join("lib.rs"),
            r#"
fn sample() {
    let x = 1;
    let y = 2;
    let z = runtime();
    let a = 10;
}
"#,
        )
        .expect("write source");
        let source_text = std::fs::read_to_string(source_dir.join("lib.rs")).expect("read source");
        let source: syn::File = syn::parse_file(&source_text).expect("parse source");
        let syn::Item::Fn(item) = &source.items[0] else {
            panic!("expected function");
        };
        let memento_for_local = |stmt_index: usize| {
            let syn::Stmt::Local(local) = &item.block.stmts[stmt_index] else {
                panic!("expected local statement");
            };
            sugar_walk::source_oracle::source_memento_of_term_span(
                "src/lib.rs",
                &source_text,
                local.init.as_ref().expect("local init").expr.span(),
                "sample",
                &item.sig,
                &item.block,
            )
            .expect("term memento")
            .to_json()
        };
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 0,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 1,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 4,
                "statusCounts": {
                    "warranted": 3,
                    "refused": 1,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": [
                    {
                        "file": "src/lib.rs",
                        "line": 3,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "literal_int",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "term",
                        "sourceMemento": memento_for_local(0)
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 4,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "literal_int",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "term",
                        "sourceMemento": memento_for_local(1)
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 5,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "address_cast",
                        "status": "refused",
                        "verdict": "incomplete",
                        "output": "effect",
                        "reason": "runtime boundary: pointer identity",
                        "sourceMemento": memento_for_local(2)
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 6,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "literal_int",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "term",
                        "sourceMemento": memento_for_local(3)
                    }
                ]
            }
        });
        let mut report = source_report_from_lift_response(&response, None).expect("source report");
        report.project_root = Some(root.path().to_path_buf());

        let visual = render_visual_source_report(&report);

        assert!(
            visual.contains("\u{1b}[32mlet x = 1;\u{1b}[0m  GREEN"),
            "{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32mlet y = 2;\u{1b}[0m  GREEN"),
            "{visual}"
        );
        assert!(
            visual.contains(
                "\u{1b}[31mlet z = runtime();\u{1b}[0m  RED HERE effect: runtime boundary: pointer identity"
            ),
            "{visual}"
        );
        assert!(
            visual.contains("\u{1b}[31mlet a = 10;\u{1b}[0m  RED"),
            "{visual}"
        );
        assert!(
            !visual.contains("let a = 10;\u{1b}[0m  RED HERE"),
            "{visual}"
        );
    }

    #[test]
    fn visual_report_projects_universe_warrants_through_green_until_red_state() {
        let root = tempfile::tempdir().expect("tempdir");
        let source_dir = root.path().join("src");
        std::fs::create_dir_all(&source_dir).expect("mkdir source dir");
        std::fs::write(
            source_dir.join("lib.rs"),
            r#"
fn sample() {
    assert_eq!(1, 1);
    assert_eq!(2, 2);
    let z = runtime();
    assert_eq!(10, 10);
}
"#,
        )
        .expect("write source");
        let source_text = std::fs::read_to_string(source_dir.join("lib.rs")).expect("read source");
        let source: syn::File = syn::parse_file(&source_text).expect("parse source");
        let syn::Item::Fn(item) = &source.items[0] else {
            panic!("expected function");
        };
        let memento_for_stmt = |stmt_index: usize| {
            let stmt = &item.block.stmts[stmt_index];
            sugar_walk::source_oracle::source_memento_of_statement_span(
                "src/lib.rs",
                &source_text,
                stmt.span(),
                "sample",
                &item.sig,
                &item.block,
            )
            .expect("statement memento")
            .to_json()
        };
        let first_assert = memento_for_stmt(0);
        let second_assert = memento_for_stmt(1);
        let effect_site = memento_for_stmt(2);
        let downstream_assert = memento_for_stmt(3);
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "src/lib.rs::sample",
                    "outBinding": "out",
                    "inv": {
                        "kind": "and",
                        "operands": [
                            { "kind": "atomic", "name": "=", "args": [
                                {"kind": "const", "value": 1, "sort": {"name": "Int"}},
                                {"kind": "const", "value": 1, "sort": {"name": "Int"}}
                            ]},
                            { "kind": "atomic", "name": "=", "args": [
                                {"kind": "const", "value": 2, "sort": {"name": "Int"}},
                                {"kind": "const", "value": 2, "sort": {"name": "Int"}}
                            ]},
                            { "kind": "atomic", "name": "=", "args": [
                                {"kind": "const", "value": 10, "sort": {"name": "Int"}},
                                {"kind": "const", "value": 10, "sort": {"name": "Int"}}
                            ]}
                        ]
                    },
                    "sourceWarrants": [
                        first_assert.clone(),
                        second_assert.clone(),
                        downstream_assert.clone()
                    ]
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 4,
                "statusCounts": {
                    "warranted": 3,
                    "refused": 1,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": [
                    {
                        "file": "src/lib.rs",
                        "line": 3,
                        "requested_role": "AssertionSurface",
                        "ast_kind": "expr",
                        "selected": "assertion_surface_relation_macro",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "constraints",
                        "sourceMemento": first_assert
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 4,
                        "requested_role": "AssertionSurface",
                        "ast_kind": "expr",
                        "selected": "assertion_surface_relation_macro",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "constraints",
                        "sourceMemento": second_assert
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 5,
                        "requested_role": "Term",
                        "ast_kind": "expr",
                        "selected": "runtime_call",
                        "status": "refused",
                        "verdict": "incomplete",
                        "output": "effect",
                        "reason": "runtime boundary: pointer identity",
                        "sourceMemento": effect_site
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 6,
                        "requested_role": "AssertionSurface",
                        "ast_kind": "expr",
                        "selected": "assertion_surface_relation_macro",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "constraints",
                        "sourceMemento": downstream_assert
                    }
                ]
            }
        });
        let mut report = source_report_from_lift_response(&response, None).expect("source report");
        report.project_root = Some(root.path().to_path_buf());

        let visual = render_visual_source_report(&report);

        assert!(visual.contains("universe visual:"), "{visual}");
        assert!(visual.contains("  universe src/lib.rs::sample"), "{visual}");
        assert!(
            visual.contains("    FOL: src/lib.rs::sample ⊢ 1 = 1 ∧ 2 = 2 ∧ 10 = 10"),
            "{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32massert_eq!(1, 1);\u{1b}[0m  GREEN ⊢ 1 = 1"),
            "{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32massert_eq!(2, 2);\u{1b}[0m  GREEN ⊢ 2 = 2"),
            "{visual}"
        );
        assert!(
            visual.contains(
                "\u{1b}[31mlet z = runtime();\u{1b}[0m  RED HERE effect: runtime boundary: pointer identity"
            ),
            "{visual}"
        );
        assert!(
            visual.contains("\u{1b}[31massert_eq!(10, 10);\u{1b}[0m  RED"),
            "{visual}"
        );
        assert!(
            !visual.contains("\u{1b}[31massert_eq!(10, 10);\u{1b}[0m  RED ⊢ 10 = 10"),
            "red rows are effect-shadowed unknowns; move the predicate before RED HERE or do not print it:\n{visual}"
        );
        assert!(
            !visual.contains("RED ⊢"),
            "red source rows are unknown and must not render predicates:\n{visual}"
        );
    }

    #[test]
    fn visual_report_projects_function_universe_through_factory_emitted_formulas() {
        let root = tempfile::tempdir().expect("tempdir");
        let source_dir = root.path().join("src");
        std::fs::create_dir_all(&source_dir).expect("mkdir source dir");
        std::fs::write(
            source_dir.join("lib.rs"),
            r#"
fn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {
    let rem = bytes_len % 3;
    let encoded_rem = rem + 1;
    Some(encoded_rem)
}
"#,
        )
        .expect("write source");
        let source_text = std::fs::read_to_string(source_dir.join("lib.rs")).expect("read source");
        let source: syn::File = syn::parse_file(&source_text).expect("parse source");
        let syn::Item::Fn(item) = &source.items[0] else {
            panic!("expected function");
        };
        let function_memento = sugar_walk::source_oracle::source_memento_of_named_item_fn(
            "src/lib.rs",
            &source_text,
            "encoded_len",
            item,
        )
        .to_json();
        let memento_for_stmt = |stmt_index: usize| {
            let stmt = &item.block.stmts[stmt_index];
            sugar_walk::source_oracle::source_memento_of_statement_span(
                "src/lib.rs",
                &source_text,
                stmt.span(),
                "encoded_len",
                &item.sig,
                &item.block,
            )
            .expect("statement memento")
            .to_json()
        };
        let rem_stmt = memento_for_stmt(0);
        let encoded_rem_stmt = memento_for_stmt(1);
        let rem_formula = serde_json::json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "rem"},
                {"kind": "ctor", "name": "%", "args": [
                    {"kind": "var", "name": "bytes_len"},
                    {"kind": "const", "value": 3, "sort": {"name": "Int"}}
                ]}
            ]
        });
        let encoded_rem_formula = serde_json::json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "encoded_rem"},
                {"kind": "ctor", "name": "+", "args": [
                    {"kind": "var", "name": "rem"},
                    {"kind": "const", "value": 1, "sort": {"name": "Int"}}
                ]}
            ]
        });
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "function-contract",
                    "name": "encoded_len",
                    "outBinding": "result",
                    "post": {
                        "kind": "and",
                        "operands": [
                            rem_formula.clone(),
                            encoded_rem_formula.clone()
                        ]
                    },
                    "sourceWarrants": [
                        function_memento
                    ]
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 2,
                "statusCounts": {
                    "warranted": 2,
                    "refused": 0,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": [
                    {
                        "file": "src/lib.rs",
                        "line": 3,
                        "requested_role": "FunctionBodyConstraint",
                        "ast_kind": "stmt",
                        "selected": "let_statement_constraint",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "constraints",
                        "sourceMemento": rem_stmt,
                        "emittedFormula": rem_formula
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 4,
                        "requested_role": "FunctionBodyConstraint",
                        "ast_kind": "stmt",
                        "selected": "let_statement_constraint",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "constraints",
                        "sourceMemento": encoded_rem_stmt,
                        "emittedFormula": encoded_rem_formula
                    }
                ]
            }
        });
        let mut report = source_report_from_lift_response(&response, None).expect("source report");
        report.project_root = Some(root.path().to_path_buf());

        let visual = render_visual_source_report(&report);

        assert!(visual.contains("  universe encoded_len"), "{visual}");
        assert!(
            visual
                .contains("    FOL: encoded_len ⊢ rem = (bytes_len % 3) ∧ encoded_rem = (rem + 1)"),
            "{visual}"
        );
        assert!(
            !visual.contains("boundTerm") && !visual.contains("\"kind\""),
            "visual FOL must be human-readable symbols, not serialized ProofIR JSON:\n{visual}"
        );
        assert!(
            visual.contains(
                "\u{1b}[32mlet rem = bytes_len % 3;\u{1b}[0m  GREEN ⊢ rem = (bytes_len % 3)"
            ),
            "{visual}"
        );
        assert!(
            visual.contains(
                "\u{1b}[32mlet encoded_rem = rem + 1;\u{1b}[0m  GREEN ⊢ encoded_rem = (rem + 1)"
            ),
            "{visual}"
        );
        assert!(
            !visual.contains("fn encoded_len(bytes_len: usize, padding: bool) -> Option<usize>"),
            "function universe projection must use factory-emitted line pins instead of the whole-function source warrant:\n{visual}"
        );
    }

    #[test]
    fn visual_report_prints_source_line_per_predicate_not_multiline_blob() {
        let root = tempfile::tempdir().expect("tempdir");
        let source_dir = root.path().join("src");
        std::fs::create_dir_all(&source_dir).expect("mkdir source dir");
        std::fs::write(
            source_dir.join("lib.rs"),
            r#"
fn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {
    let rem = bytes_len % 3;
    if rem > 0 {
        if padding {
            Some(4)
        } else {
            Some(2)
        }
    } else {
        Some(0)
    }
}
"#,
        )
        .expect("write source");
        let source_text = std::fs::read_to_string(source_dir.join("lib.rs")).expect("read source");
        let source: syn::File = syn::parse_file(&source_text).expect("parse source");
        let syn::Item::Fn(item) = &source.items[0] else {
            panic!("expected function");
        };
        let function_memento = sugar_walk::source_oracle::source_memento_of_named_item_fn(
            "src/lib.rs",
            &source_text,
            "encoded_len",
            item,
        )
        .to_json();
        let tail_expr = match item.block.stmts.last().expect("tail stmt") {
            syn::Stmt::Expr(expr, None) => expr,
            other => panic!("expected tail expr, got {other:?}"),
        };
        let tail_memento = sugar_walk::source_oracle::source_memento_of_term_span(
            "src/lib.rs",
            &source_text,
            tail_expr.span(),
            "encoded_len",
            &item.sig,
            &item.block,
        )
        .expect("tail expression memento")
        .to_json();
        let result_formula = serde_json::json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "result"},
                {"kind": "ctor", "name": "cf_ite", "args": [
                    {"kind": "ctor", "name": "cf_gt", "args": [
                        {"kind": "var", "name": "rem"},
                        {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                    ]},
                    {"kind": "ctor", "name": "Some", "args": [{"kind": "const", "value": 4, "sort": {"kind": "primitive", "name": "Int"}}]},
                    {"kind": "ctor", "name": "Some", "args": [{"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}]}
                ]}
            ]
        });
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "function-contract",
                    "name": "encoded_len",
                    "outBinding": "result",
                    "post": result_formula.clone(),
                    "sourceWarrants": [function_memento]
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 1,
                    "refused": 0,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": [
                    {
                        "file": "src/lib.rs",
                        "line": 4,
                        "requested_role": "FunctionBodyConstraint",
                        "ast_kind": "expr",
                        "selected": "result_expression_constraint",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "constraints",
                        "sourceMemento": tail_memento,
                        "emittedFormula": result_formula
                    }
                ]
            }
        });
        let mut report = source_report_from_lift_response(&response, None).expect("source report");
        report.project_root = Some(root.path().to_path_buf());

        let visual = render_visual_source_report(&report);

        assert!(
            visual.contains("    FOL: encoded_len ⊢ result = if rem > 0 then Some(4) else Some(0)"),
            "visual FOL must use turnstile and symbols, not JSON:\n{visual}"
        );
        assert!(
            !visual.contains("boundTerm") && !visual.contains("\"kind\""),
            "visual FOL must not leak serialized ProofIR JSON:\n{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32mif rem > 0 {\u{1b}[0m  GREEN ⊢ result = if rem > 0 then Some(4) else Some(0)"),
            "source line must carry its emitted predicate inline:\n{visual}"
        );
        assert!(
            !visual.contains("if padding {"),
            "visual report must not collapse a multi-line source block into one predicate row:\n{visual}"
        );
    }

    #[test]
    fn visual_source_oracle_route_strips_workspace_override_prefix() {
        let root = tempfile::tempdir().expect("tempdir");
        let vendor = root.path().join("vendor/base64-0.22.1");
        std::fs::create_dir_all(&vendor).expect("create vendor dir");
        let route = SourceOracleRoute {
            surface: "rust-fn-contracts".to_string(),
            workspace_override: Some("vendor/base64-0.22.1".to_string()),
        };
        let memento = serde_json::json!({
            "file": "vendor/base64-0.22.1/src/encode.rs",
            "sourceFunctionName": "encoded_len",
            "span": {"start_line": 10, "start_col": 4, "end_line": 10, "end_col": 32},
            "paramNames": ["bytes_len"],
            "source_cid": "blake3-512:source",
            "template_cid": "blake3-512:template"
        });

        let routed = routed_source_memento(root.path(), &[route], &memento)
            .expect("workspace override route");

        assert_eq!(
            routed.memento["file"], "src/encode.rs",
            "visual source oracle requests must strip the report-only workspace prefix"
        );
        assert_eq!(
            routed.workspace_root,
            vendor.canonicalize().unwrap_or(vendor),
            "visual source oracle requests must run against the plugin workspace root"
        );
    }

    #[test]
    fn visual_source_oracle_route_keeps_local_files_out_of_vendor_override() {
        let root = tempfile::tempdir().expect("tempdir");
        let routes = [
            SourceOracleRoute {
                surface: "rust-test-assertions".to_string(),
                workspace_override: None,
            },
            SourceOracleRoute {
                surface: "rust-fn-contracts".to_string(),
                workspace_override: Some("vendor/base64-0.22.1".to_string()),
            },
        ];
        let memento = serde_json::json!({
            "file": "src/lib.rs",
            "sourceFunctionName": "tests::test_encoded_len_unpadded_0_exact_row",
            "span": {"start_line": 10, "start_col": 8, "end_line": 10, "end_col": 52},
            "paramNames": [],
            "source_cid": "blake3-512:source",
            "template_cid": "blake3-512:template"
        });

        assert!(
            routed_source_memento(root.path(), &routes, &memento).is_none(),
            "a configured graph must not send local showcase source to the only vendor override; visual should fall back to the local project source oracle"
        );
    }

    #[test]
    fn summary_report_rejects_plaintext_factory_walk_terms() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_unresolved": 0
            },
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 1,
                    "refused": 0,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": [
                    {
                        "file": "tests/foo.rs",
                        "line": 1,
                        "status": "warranted",
                        "verdict": "complete",
                        "term": "1 + 2"
                    }
                ]
            }
        });
        let error = source_report_summary_from_lift_response(&response, Path::new("."))
            .expect_err("plaintext term in factoryWalk must be rejected");

        assert!(
            error.contains("plaintext source/term"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn summary_report_rejects_plaintext_unresolved_sites() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 0,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_unresolved": 1
            },
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 0,
                    "refused": 0,
                    "support": 0,
                    "unresolved": 1
                },
                "unresolvedSites": [
                    {
                        "file": "tests/foo.rs",
                        "line": 1,
                        "status": "unresolved",
                        "site": "opaque()"
                    }
                ],
                "factoryWalk": []
            }
        });
        let error = source_report_summary_from_lift_response(&response, Path::new("."))
            .expect_err("plaintext unresolved site must be rejected");

        assert!(
            error.contains("plaintext source/term"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn summary_report_treats_unresolved_source_as_hard_failure() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 0,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_unresolved": 1
            },
            "sourceAudits": []
        });
        let response = {
            let mut response = response;
            response["factoryAuditSummary"] = serde_json::json!({
                "emittedRows": 0,
                "statusCounts": {
                    "warranted": 0,
                    "refused": 0,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": []
            });
            response
        };
        let summary =
            source_report_summary_from_lift_response(&response, Path::new(".")).expect("summary");

        assert!(source_report_summary_has_hard_failures(&summary));
    }

    #[test]
    fn summary_report_treats_unresolved_factory_sites_as_hard_failure() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_inactive": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_unresolved": 0
            },
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 0,
                    "refused": 0,
                    "support": 0,
                    "unresolved": 1
                },
                "unresolvedSites": [],
                "factoryWalk": []
            }
        });
        let summary =
            source_report_summary_from_lift_response(&response, Path::new(".")).expect("summary");

        assert!(source_report_summary_has_hard_failures(&summary));
    }

    #[test]
    fn superposition_groups_universes_by_cid_not_occurrence() {
        // A method whose every callsite mints the BYTE-IDENTICAL contract (the
        // copy-pasted-test case: same name, same post, same out binding) is ONE
        // universe, regardless of how many callsites produced it.
        let dup = serde_json::json!({
            "kind": "contract",
            "name": "Foo::dup",
            "outBinding": "out",
            "post": { "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "out"}, {"kind": "const", "value": 0}
            ]}
        });
        // Two contracts that RENDER to the same FOL but differ in IDENTITY
        // (here a differing out binding stands in for any identity-bearing
        // difference the FOL reading elides — e.g. integer width). They must
        // stay TWO distinct universes, never collapse to one by their shared
        // reading string.
        let twin_a = serde_json::json!({
            "kind": "contract", "name": "Foo::twin", "outBinding": "a",
            "post": { "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "out"}, {"kind": "const", "value": 7}
            ]}
        });
        let twin_b = serde_json::json!({
            "kind": "contract", "name": "Foo::twin", "outBinding": "b",
            "post": { "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "out"}, {"kind": "const", "value": 7}
            ]}
        });

        let contracts = vec![dup.clone(), dup.clone(), dup, twin_a, twin_b];
        let universes = distinct_universes_per_method(&contracts);

        let dup_universes = universes.get("Foo::dup").expect("Foo::dup present");
        assert_eq!(
            dup_universes.len(),
            1,
            "three byte-identical copies are ONE universe, not three"
        );
        assert_eq!(dup_universes[0].occurrences, 3, "all 3 callsites counted");

        let twin_universes = universes.get("Foo::twin").expect("Foo::twin present");
        assert_eq!(
            twin_universes.len(),
            2,
            "same-reading but distinct identity stays TWO universes"
        );
        assert_eq!(twin_universes[0].occurrences, 1);
        assert_eq!(twin_universes[1].occurrences, 1);
        assert_ne!(
            twin_universes[0].cid, twin_universes[1].cid,
            "distinct universes carry distinct CIDs"
        );
        assert_eq!(
            twin_universes[0].reading, twin_universes[1].reading,
            "the twins render identically — exactly what CID grouping must NOT merge"
        );
    }

    #[test]
    fn human_report_collapses_duplicate_universes_and_tags_ambiguous() {
        let dup = serde_json::json!({
            "kind": "contract",
            "name": "Foo::dup",
            "outBinding": "out",
            "post": { "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "out"}, {"kind": "const", "value": 0}
            ]}
        });
        let twin_a = serde_json::json!({
            "kind": "contract", "name": "Foo::twin", "outBinding": "a",
            "post": { "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "out"}, {"kind": "const", "value": 7}
            ]}
        });
        let twin_b = serde_json::json!({
            "kind": "contract", "name": "Foo::twin", "outBinding": "b",
            "post": { "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "out"}, {"kind": "const", "value": 7}
            ]}
        });
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [dup.clone(), dup.clone(), dup, twin_a, twin_b],
            "sourceLedger": {
                "source_loci": 0,
                "source_warranted": 0,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [],
            "sourceMementos": []
        });
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        // 2 methods, 3 distinct universes, 5 raw callsite occurrences.
        assert!(
            human.contains("2 methods, 3 universes (5 callsite occurrences)"),
            "{human}"
        );
        // The byte-identical triple collapses to one universe tagged with its
        // multiplicity, not three redundant lines.
        assert!(human.contains("(×3)"), "{human}");
        // The two same-rendering distinct universes are disambiguated by CID.
        assert!(human.contains("[cid "), "{human}");
    }

    #[test]
    fn human_report_renders_function_contract_post_readings() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "function-contract",
                    "name": "rust-source::Maker::x",
                    "bridgeSourceSymbol": "method:x",
                    "formals": ["self"],
                    "outBinding": "out",
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "ctor", "name": "method:y", "args": [
                                {"kind": "var", "name": "self"}
                            ]}
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "role": "rust-test-assertions",
                    "universe_kind": "test-assertion",
                    "loci": [
                        {
                            "file": "src/lib.rs",
                            "ast_path": "Maker::x",
                            "line": 10,
                            "status": "warranted"
                        }
                    ]
                }
            ],
            "sourceMementos": []
        });
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(human.contains("rust-source::Maker::x"));
        assert!(human.contains("out = method:y(self)"), "{human}");
        assert!(!human.contains("<no inv>"), "{human}");
    }

    #[test]
    fn human_report_does_not_claim_missing_facts_for_post_contracts_or_source_mementos() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "function-contract",
                    "name": "z",
                    "formals": ["v"],
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "var", "name": "v"}
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "role": "rust-fn-contracts",
                    "universe_kind": "function-contract",
                    "totals": {
                        "source_loci": 1,
                        "source_warranted": 1,
                        "source_support": 0,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "unclassified_source": 0
                    },
                    "loci": [
                        {
                            "file": "src/lib.rs",
                            "ast_kind": "fn",
                            "ast_path": "z",
                            "sourceFunctionName": "z",
                            "line": 1,
                            "status": "warranted"
                        }
                    ]
                }
            ],
            "sourceMementos": [
                {
                    "kind": "source-memento",
                    "file": "src/lib.rs",
                    "sourceFunctionName": "z",
                    "span": {"start_line": 1, "end_line": 3},
                    "paramNames": ["v"],
                    "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "template_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                }
            ]
        });
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(human.contains("contract: z"), "{human}");
        assert!(
            human.contains("lifted FOL:\n  - z :: result = v"),
            "{human}"
        );
        assert!(human.contains("warranted complete walks:"), "{human}");
        assert!(
            !human.contains("facts observed:\n  - not emitted by kit"),
            "{human}"
        );
    }

    #[test]
    fn human_report_renders_rust_source_inv_as_lifted_fol_not_fact() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "rust-source::enc",
                    "inv": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "const", "value": "def", "sort": {"name": "String"}}
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "role": "rust-test-assertions",
                    "universe_kind": "test-assertion",
                    "loci": [
                        {
                            "file": "src/lib.rs",
                            "ast_kind": "fn",
                            "ast_path": "enc",
                            "line": 1,
                            "status": "warranted"
                        }
                    ]
                }
            ],
            "sourceMementos": [
                {
                    "kind": "source-memento",
                    "file": "src/lib.rs",
                    "sourceFunctionName": "enc",
                    "span": {"start_line": 1, "end_line": 3},
                    "paramNames": ["input"],
                    "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "template_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                }
            ]
        });
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(human.contains("contract: rust-source::enc"), "{human}");
        assert!(
            human.contains("lifted FOL:\n  - rust-source::enc :: out = \"def\""),
            "{human}"
        );
        assert!(
            !human.contains("contract: rust-source::enc\nfacts observed:"),
            "{human}"
        );
    }

    #[test]
    fn human_report_groups_rust_audits_without_contract_name() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "function-contract",
                    "name": "rust-source::Maker::x",
                    "bridgeSourceSymbol": "method:x",
                    "formals": ["self"],
                    "outBinding": "out",
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "ctor", "name": "method:y", "args": [
                                {"kind": "var", "name": "self"}
                            ]}
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "role": "rust-test-assertions",
                    "universe_kind": "test-assertion",
                    "loci": [
                        {
                            "file": "src/lib.rs",
                            "ast_kind": "fn",
                            "ast_path": "Maker::x",
                            "line": 10,
                            "status": "warranted"
                        }
                    ]
                }
            ],
            "sourceMementos": [
                {
                    "file": "src/lib.rs",
                    "sourceFunctionName": "Maker::x",
                    "span": {
                        "start_line": 10,
                        "start_col": 4,
                        "end_line": 12,
                        "end_col": 5
                    },
                    "paramNames": ["self"],
                    "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "template_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                }
            ]
        });
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(!human.contains("contract: <unknown contract>"), "{human}");
        assert!(
            human.contains("contract: rust-test-assertions / test-assertion"),
            "{human}"
        );
        assert!(
            human.contains("complete walk: rust-test-assertions / test-assertion"),
            "{human}"
        );
        assert!(human.contains("src/lib.rs:10 warranted fn"), "{human}");
        assert!(human.contains("contract: rust-source::Maker::x"), "{human}");
        assert!(human.contains("src/lib.rs:10-12 Maker::x(self)"), "{human}");
        assert!(human.contains("out = method:y(self)"), "{human}");
        assert!(
            human.contains("rust-source::Maker::x :: out = method:y(self)"),
            "{human}"
        );
        assert!(!human.contains(":: null"), "{human}");
    }

    #[test]
    fn human_report_renders_inv_contracts_as_observed_facts() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "src/lib.rs::tests::facts_are_inv",
                    "inv": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "const", "value": 42, "sort": {"name": "Int"}},
                            {"kind": "const", "value": 42, "sort": {"name": "Int"}}
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "role": "rust-test-assertions",
                    "universe_kind": "test-assertion",
                    "loci": [
                        {
                            "file": "src/lib.rs",
                            "ast_kind": "test-fn",
                            "ast_path": "facts_are_inv",
                            "line": 10,
                            "status": "warranted"
                        }
                    ]
                }
            ],
            "sourceMementos": []
        });
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(
            human.contains("facts observed:\n  - src/lib.rs::tests::facts_are_inv :: 42 = 42"),
            "{human}"
        );
        assert!(
            !human.contains("contract: src/lib.rs::tests::facts_are_inv\nfacts observed:\n  - not emitted by kit"),
            "{human}"
        );
    }

    #[test]
    fn human_report_renders_assertion_fact_with_source_memento() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "src/lib.rs::tests::enc_asserts",
                    "inv": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "call:enc",
                                "args": [
                                    {"kind": "const", "value": "abc", "sort": {"name": "String"}}
                                ]
                            },
                            {"kind": "const", "value": "def", "sort": {"name": "String"}}
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "role": "rust-test-assertions",
                    "universe_kind": "test-assertion",
                    "loci": [
                        {
                            "file": "src/lib.rs",
                            "ast_kind": "test-fn",
                            "ast_path": "enc_asserts",
                            "line": 12,
                            "status": "warranted"
                        }
                    ]
                }
            ],
            "sourceMementos": [
                {
                    "kind": "source-memento",
                    "file": "src/lib.rs",
                    "sourceFunctionName": "enc_asserts",
                    "span": {"start_line": 12, "end_line": 14},
                    "paramNames": [],
                    "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "template_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                }
            ]
        });
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(
            human.contains(
                "facts observed:\n  - src/lib.rs::tests::enc_asserts :: call:enc(\"abc\") = \"def\" @ src/lib.rs:12-14 enc_asserts() source_cid=blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "{human}"
        );
        assert!(!human.contains("body_text"), "{human}");
        assert!(!human.contains("ast_template"), "{human}");
    }

    #[test]
    fn human_report_renders_generic_assertion_surface_fact_accounting() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "src/lib.rs::tests::emits_fact",
                    "inv": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "const", "value": 2, "sort": {"name": "Int"}},
                            {"kind": "const", "value": 2, "sort": {"name": "Int"}}
                        ]
                    }
                },
                {
                    "kind": "contract",
                    "name": "src/lib.rs::tests::support_only::panic-free::answer",
                    "inv": {
                        "kind": "atomic",
                        "name": "panic-free",
                        "args": [
                            {"kind": "ctor", "name": "call:answer", "args": []}
                        ]
                    }
                }
            ],
            "sourceLedger": {
                "source_loci": 3,
                "source_warranted": 1,
                "source_support": 1,
                "source_refused": 0,
                "source_inactive": 0,
                "source_unresolved": 1
            },
            "sourceAudits": [
                {
                    "role": "vendor-assertion-surface",
                    "universe_kind": "assertion-source",
                    "loci": []
                }
            ],
            "sourceMementos": [],
            "assertionSurfaceAudits": [
                {
                    "kind": "assertion-surface-audit",
                    "surface": "example-assertions",
                    "assertionSource": "src/lib.rs::tests::emits_fact",
                    "file": "src/lib.rs",
                    "line": 10,
                    "status": "facts-emitted",
                    "sourceMemento": {
                        "file": "src/lib.rs",
                        "sourceFunctionName": "emits_fact",
                        "span": {"start_line": 10, "end_line": 12},
                        "paramNames": [],
                        "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    },
                    "facts": [
                        {"contract": "src/lib.rs::tests::emits_fact"}
                    ],
                    "supportFacts": []
                },
                {
                    "kind": "assertion-surface-audit",
                    "surface": "example-assertions",
                    "assertionSource": "src/lib.rs::tests::support_only",
                    "file": "src/lib.rs",
                    "line": 30,
                    "status": "support-only",
                    "reason": "support contracts emitted; no scalar universe emitted by kit",
                    "facts": [],
                    "supportFacts": [
                        {
                            "kind": "support",
                            "contract": "src/lib.rs::tests::support_only::panic-free::answer"
                        }
                    ]
                },
                {
                    "kind": "assertion-surface-audit",
                    "surface": "example-assertions",
                    "assertionSource": "src/lib.rs::tests::no_fact",
                    "file": "src/lib.rs",
                    "line": 20,
                    "status": "no-facts-emitted",
                    "reason": "no liftable scalar assertions",
                    "facts": [],
                    "supportFacts": []
                }
            ]
        });
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);
        let rendered_json = render_report_json(&report, None).expect("json report");
        let parsed: Value = serde_json::from_str(&rendered_json).expect("valid json");

        assert!(
            human.contains("assertion surface accounting: sources=3 facts=1 support=0 no_facts=2"),
            "{human}"
        );
        assert!(human.contains("assertion facts emitted:"), "{human}");
        assert!(
            human.contains("src/lib.rs:10 src/lib.rs::tests::emits_fact facts-emitted facts=1"),
            "{human}"
        );
        assert!(
            human.contains("src/lib.rs::tests::emits_fact :: 2 = 2"),
            "{human}"
        );
        assert!(!human.contains("assertion support emitted:"), "{human}");
        assert!(
            human.contains("assertion sources without facts:"),
            "{human}"
        );
        assert!(
            human.contains(
                "src/lib.rs:30 src/lib.rs::tests::support_only no-facts-emitted facts=0 support=0"
            ),
            "{human}"
        );
        assert!(
            human.contains(
                "src/lib.rs::tests::support_only::panic-free::answer :: panic-free(call:answer())"
            ),
            "{human}"
        );
        assert!(
            human.contains("reason: support contracts emitted; no scalar universe emitted by kit"),
            "{human}"
        );
        assert!(
            human.contains("src/lib.rs:20 src/lib.rs::tests::no_fact no-facts-emitted"),
            "{human}"
        );
        assert!(
            human.contains("reason: no liftable scalar assertions"),
            "{human}"
        );
        assert_eq!(
            parsed["assertionSurfaceAudits"].as_array().unwrap().len(),
            3
        );
    }

    #[test]
    fn assertion_fact_source_owner_comes_from_test_function_not_callee() {
        let name = "method:is_match#euf#c:callresult_method_is_match_a2(c:method:unwrap(c:call:Regex::new(c:method:x(v:src/lib.rs::tests::regex_from_matcher_method_chain::m,s:\"blah\"))),s:\"blah\")::assertion";

        assert_eq!(
            owning_source_function_name(name).as_deref(),
            Some("regex_from_matcher_method_chain")
        );
        assert!(contract_name_matches_source_function(
            name,
            "regex_from_matcher_method_chain"
        ));
        assert!(!contract_name_matches_source_function(name, "Regex::new"));
    }

    #[test]
    fn report_contract_group_key_keeps_plain_rust_test_contracts_distinct() {
        assert_eq!(
            report_contract_group_key("src/lib.rs::tests::first_case"),
            "src/lib.rs::tests::first_case"
        );
        assert_eq!(
            report_contract_group_key("src/lib.rs::tests::second_case"),
            "src/lib.rs::tests::second_case"
        );
        assert_eq!(
            report_contract_group_key("method:x#euf#c:method:x(v:m)::assertion"),
            "method:x#euf#c:method:x(v:m)"
        );
    }

    #[test]
    fn human_report_renders_vendor_conjoin_section() {
        let report = LiftSourceReport {
            ledger: serde_json::json!({
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            }),
            audits: vec![serde_json::json!({
                "role": "rust-test-assertions",
                "universe_kind": "test-assertion",
                "loci": []
            })],
            factory_audits: vec![],
            factory_walk: vec![],
            assertion_surface_audits: vec![],
            source_mementos: vec![],
            contracts: vec![],
            call_edges: vec![],
            vendor_conjoins: vec![VendorConjoinReport {
                call: "call:enc(\"def\")".to_string(),
                local_contract: "src/lib.rs::tests::fresh_vendor_fol_good::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion".to_string(),
                local_fact: "call:enc(\"def\") = \"ghi\"".to_string(),
                bridge_source_symbol: "call:enc".to_string(),
                vendor_contract: "rust-source::enc".to_string(),
                vendor_contract_cid: "blake3-512:vendor".to_string(),
                vendor_proof_cid: Some("blake3-512:proof".to_string()),
                vendor_post: "input = \"def\" ⇒ out = \"ghi\"".to_string(),
                instantiated_post: "\"def\" = \"def\" ⇒ call:enc(\"def\") = \"ghi\""
                    .to_string(),
                vendor_source: Some(VendorSourceResolution::Resolved(
                    "src/lib.rs:1-9 enc(input) source_cid=blake3-512:source".to_string(),
                )),
            }],
            project_root: None,
            source_oracle_routes: Vec::new(),
        };
        let human = render_source_report_human(&report);

        assert!(human.contains("vendor conjoins:"), "{human}");
        assert!(
            human.contains(
                "call: call:enc(\"def\")\n    your contract: src/lib.rs::tests::fresh_vendor_fol_good::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion"
            ),
            "{human}"
        );
        assert!(
            human.contains("your fact: call:enc(\"def\") = \"ghi\""),
            "{human}"
        );
        assert!(
            human.contains(
                "vendor contract: rust-source::enc cid=blake3-512:vendor proof=blake3-512:proof"
            ),
            "{human}"
        );
        assert!(
            human.contains("conjoin here: call:enc(\"def\") = \"ghi\" ∧ (\"def\" = \"def\" ⇒ call:enc(\"def\") = \"ghi\")"),
            "{human}"
        );
        assert!(
            human.contains("vendor source: src/lib.rs:1-9 enc(input) source_cid=blake3-512:source"),
            "{human}"
        );
    }

    #[test]
    fn source_report_reads_vendor_conjoins_from_kit_response() {
        let response = lift_response_with_vendor_conjoin(serde_json::json!({
            "status": "resolved",
            "display": "src/lib.rs:1-9 enc(input) source_cid=blake3-512:source"
        }));
        let report = source_report_from_lift_response(&response, None).expect("source report");

        assert_eq!(report.vendor_conjoins.len(), 1);
        let human = render_source_report_human(&report);
        assert!(human.contains("vendor conjoins:"), "{human}");
        assert!(
            human.contains("vendor source: src/lib.rs:1-9 enc(input) source_cid=blake3-512:source"),
            "{human}"
        );
        assert!(!source_report_has_hard_failures(&report));
    }

    #[test]
    fn absent_vendor_source_is_reported_but_not_hard_failure() {
        let response = lift_response_with_vendor_conjoin(serde_json::json!({
            "status": "absent",
            "reason": "vendor source unavailable for proof blake3-512:proof"
        }));
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(
            human.contains(
                "vendor source: absent - vendor source unavailable for proof blake3-512:proof"
            ),
            "{human}"
        );
        assert!(!source_report_has_hard_failures(&report));
    }

    #[test]
    fn drifted_vendor_source_is_hard_report_failure() {
        let response = lift_response_with_vendor_conjoin(serde_json::json!({
            "status": "drifted",
            "reason": "source CID misaligned for `enc`"
        }));
        let report = source_report_from_lift_response(&response, None).expect("source report");
        let human = render_source_report_human(&report);

        assert!(
            human.contains("vendor source: DRIFTED - source CID misaligned for `enc`"),
            "{human}"
        );
        assert!(source_report_has_hard_failures(&report));
    }

    #[test]
    fn unresolved_referenced_vendor_proof_cid_is_a_report_error() {
        let mut response = lift_response_with_vendor_conjoin(serde_json::json!({
            "status": "absent",
            "reason": "vendor source unavailable"
        }));
        response["vendorConjoins"][0]["vendorProofResolution"] = serde_json::json!({
            "status": "missing",
            "cid": "blake3-512:proof"
        });
        let err = source_report_from_lift_response(&response, None)
            .expect_err("referenced proof CID miss is a kit/protocol panic");

        assert!(
            err.contains("kit referenced proof CID `blake3-512:proof` but did not resolve it"),
            "{err}"
        );
    }

    fn lift_response_with_vendor_conjoin(vendor_source: Value) -> Value {
        serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_refused": 0,
                "source_inactive": 0,
                "unclassified_source": 0
            },
            "sourceAudits": [
                {
                    "role": "rust-test-assertions",
                    "universe_kind": "test-assertion",
                    "loci": []
                }
            ],
            "sourceMementos": [],
            "vendorConjoins": [
                {
                    "call": "call:enc(\"def\")",
                    "localContract": "src/lib.rs::tests::fresh_vendor_fol_good::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion",
                    "localFact": "call:enc(\"def\") = \"ghi\"",
                    "bridgeSourceSymbol": "call:enc",
                    "vendorContract": "rust-source::enc",
                    "vendorContractCid": "blake3-512:vendor",
                    "vendorProofCid": "blake3-512:proof",
                    "vendorProofResolution": {"status": "resolved", "cid": "blake3-512:proof"},
                    "vendorPost": "input = \"def\" ⇒ out = \"ghi\"",
                    "instantiatedPost": "\"def\" = \"def\" ⇒ call:enc(\"def\") = \"ghi\"",
                    "vendorSource": vendor_source
                }
            ]
        })
    }
}
