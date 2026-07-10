// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar lift <PROJECT>`: dispatch the configured lift-plugin protocol
// and emit the raw lifted ProofIR response. Minting is a separate composition
// step owned by `sugar mint`.

use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use owo_colors::OwoColorize;
use serde_json::{Map, Value};

use sugar_claim_envelope::contract_cid_of_ir_decl;
use sugar_proof_envelope::Member;
use sugar_verifier::MemberKind;

use crate::component_plan::{self, ComponentPlan, ComponentPlanOptions, PlanIntent};
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
    let component_plan_options = ComponentPlanOptions {
        allow_failed_components: args.allow_failed_components,
    };
    if args.report {
        let graph_plugins = match lift_report_graph_plugins(
            &project_root,
            &project_cfg,
            &user_cfg,
            component_plan_options,
        ) {
            Ok(graph_plugins) => graph_plugins,
            Err(error) => {
                eprintln!("{}: {error}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        };
        if graph_plugins.len() > 1 {
            return run_configured_lift_report_graph(&args, &project_root, &graph_plugins);
        }
        if graph_plugins.len() == 1 {
            return run_configured_lift_report_response(&args, &project_root, &graph_plugins);
        }
    }
    let resolved_surface = match configured_or_planned_lift_surface(
        &project_root,
        &project_cfg,
        &user_cfg,
        args.report,
        component_plan_options,
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
            let projection = session.response_projection();
            let response = match projection.response_value() {
                Ok(response) => response,
                Err(error) => {
                    eprintln!("{}: {error}", "error".red().bold());
                    return EXIT_VERIFY_FAIL;
                }
            };
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
                        component_plan_options,
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
                    match cmd_prove::build_prove_report_with_options(
                        &project_root,
                        &args.z3,
                        &prove_with,
                        component_plan_options,
                    ) {
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
        Err(LiftPluginError::Diagnostic(error)) => {
            eprintln!("{}: {error}", "error".red().bold());
            EXIT_VERIFY_FAIL
        }
    }
}

fn lift_report_graph_plugins(
    project_root: &Path,
    project_cfg: &ProjectConfig,
    user_cfg: &ProjectConfig,
    options: ComponentPlanOptions,
) -> Result<Vec<PluginEntry>, String> {
    let configured = project_cfg
        .plugins
        .iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .filter(|plugin| {
            plugin.emit.as_deref() == Some("ir-document")
                || lift_plugin::surface_phase(project_root, &plugin.surface) == "consumer"
        })
        .cloned()
        .collect::<Vec<_>>();
    if !configured.is_empty() {
        return Ok(configured);
    }
    if project_cfg
        .surface_for("lift")
        .or_else(|| user_cfg.surface_for("lift"))
        .is_some()
    {
        return Ok(Vec::new());
    }
    let component_plan =
        component_plan::plan_workspace_with_options(project_root, PlanIntent::Lift, options);
    check_component_plan_errors(&component_plan)?;
    if options.allow_failed_components {
        emit_component_plan_warnings(&component_plan);
    }
    Ok(component_plan
        .plugins
        .into_iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .filter(|plugin| {
            plugin.emit.as_deref() == Some("ir-document")
                || lift_plugin::surface_phase(project_root, &plugin.surface) == "consumer"
        })
        .collect())
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
    options: ComponentPlanOptions,
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

    let component_plan =
        component_plan::plan_workspace_with_options(project_root, PlanIntent::Lift, options);
    check_component_plan_errors(&component_plan)?;
    if options.allow_failed_components {
        emit_component_plan_warnings(&component_plan);
    }
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
    component_plan_options: ComponentPlanOptions,
) -> Result<Vec<String>, String> {
    let mut with = configured_with.to_vec();
    if !needs_lift_report_auto_mint(project_root, true) {
        tracing::info!(
            project = %project_root.display(),
            "lift-report-prove: existing .proof input found; skipping auto-mint"
        );
        return Ok(with);
    }

    let plugins = lift_report_mint_plugins(
        project_root,
        project_cfg,
        user_cfg,
        resolved_surface,
        component_plan_options,
    )?;
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
    if !args.report_summary {
        let proof_file = match cmd_mint::mint_lift_plugins_for_report(
            project_root,
            plugins,
            &out_dir,
            args.library_bindings,
        ) {
            Ok(Some(proof_file)) => proof_file,
            Ok(None) => {
                eprintln!(
                    "{}: configured lift report did not mint a proof file",
                    "error".red().bold()
                );
                return EXIT_USER_ERROR;
            }
            Err(error) => {
                eprintln!("{}: {error}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        };
        trace_lift_report_checkpoint("before_source_report_from_proof");
        let mut report =
            match source_report_from_proof_files(&[proof_file.clone()], args.contract.as_deref()) {
                Ok(report) => report,
                Err(error) => {
                    eprintln!("{}: {error}", "error".red().bold());
                    return EXIT_USER_ERROR;
                }
            };
        report.project_root = Some(project_root.to_path_buf());
        report.source_oracle_routes =
            source_oracle_routes_from_plan_mementos(&report.plan_mementos);
        // Rebase file paths in source mementos and contract sourceWarrants
        // using workspace_override from plan mementos.  In the proof path
        // (dispatch_multi) the lifter output is minted as-is; the
        // dispatch_report_lift_plugin path applies prefix_workspace_override_source_files
        // inline, so the proof already has rebased paths there.  Here we apply
        // the same prefix so the two paths agree on the file names in the report.
        rebase_proof_source_file_paths(&mut report);
        enrich_report_source_mementos_from_oracles(&mut report);
        trace_lift_source_report("after_source_report_from_proof", &report);

        let prove_with = if args.prove {
            let mut with = args.with.clone();
            with.push(absolute_path(&out_dir).display().to_string());
            with
        } else {
            Vec::new()
        };
        let prove_report = if args.prove {
            trace_lift_report_checkpoint("before_build_prove_report");
            match cmd_prove::build_prove_report_with_options(
                project_root,
                &args.z3,
                &prove_with,
                ComponentPlanOptions {
                    allow_failed_components: args.allow_failed_components,
                },
            ) {
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
        return if hard_failure {
            EXIT_VERIFY_FAIL
        } else {
            EXIT_OK
        };
    }

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
        match cmd_prove::build_prove_report_with_options(
            project_root,
            &args.z3,
            &prove_with,
            ComponentPlanOptions {
                allow_failed_components: args.allow_failed_components,
            },
        ) {
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

fn run_configured_lift_report_response(
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
    trace_lift_report_response("after_configured_lift_report_response", &response);
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
        match cmd_prove::build_prove_report_with_options(
            project_root,
            &args.z3,
            &prove_with,
            ComponentPlanOptions {
                allow_failed_components: args.allow_failed_components,
            },
        ) {
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
    options: ComponentPlanOptions,
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
        let component_plan =
            component_plan::plan_workspace_with_options(project_root, PlanIntent::Lift, options);
        check_component_plan_errors(&component_plan)?;
        if options.allow_failed_components {
            emit_component_plan_warnings(&component_plan);
        }
        let component_plugins = component_plan
            .plugins
            .iter()
            .filter(|plugin| plugin.is_lift_plugin())
            .cloned()
            .collect::<Vec<_>>();
        if !component_plugins.is_empty() {
            return Ok(component_plugins);
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
        role: None,
    }
}

fn source_oracle_routes_from_plan_mementos(plan_mementos: &[Value]) -> Vec<SourceOracleRoute> {
    let mut routes = Vec::new();
    let mut seen = BTreeSet::new();
    for plan_body in plan_mementos.iter().filter_map(plan_body_from_memento) {
        for atom in plan_atoms_from_body(plan_body) {
            let Some(surface) = atom.get("surface").and_then(Value::as_str) else {
                continue;
            };
            let workspace_override = atom
                .get("workspaceOverride")
                .or_else(|| atom.get("workspace_override"))
                .and_then(Value::as_str)
                .filter(|workspace| !workspace.is_empty())
                .map(str::to_string);
            let role = atom
                .get("role")
                .and_then(Value::as_str)
                .filter(|role| !role.is_empty())
                .map(str::to_string);
            if matches!(
                role.as_deref(),
                Some("factory-report" | "proofir-compiler" | "witness-oracle")
            ) {
                continue;
            }
            let key = (
                surface.to_string(),
                workspace_override.clone().unwrap_or_default(),
                role.clone().unwrap_or_default(),
            );
            if seen.insert(key) {
                routes.push(SourceOracleRoute {
                    surface: surface.to_string(),
                    workspace_override,
                    role,
                });
            }
        }
    }
    routes
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
    diagnostics: Vec<Value>,
    source_mementos: Vec<Value>,
    plan_mementos: Vec<Value>,
    contracts: Vec<Value>,
    call_edges: Vec<Value>,
    vendor_conjoins: Vec<VendorConjoinReport>,
    project_root: Option<PathBuf>,
    source_oracle_routes: Vec<SourceOracleRoute>,
    /// #4013 dual-axis lift coverage (majority assertions / minority bodies).
    /// Carried through from the kit's liftCoverage field; independent AST
    /// census lives inside the kit, not re-computed here.
    lift_coverage: Option<Value>,
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
    role: Option<String>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct FactoryAccountingSummary {
    sites: usize,
    warranted: usize,
    incomplete: usize,
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
    "source_boundary",
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
    if let Some(refused) = response.get("sugar-bound-exceeded").and_then(Value::as_str) {
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
        incomplete: status_count(status_counts, "incomplete"),
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
    // finite-or-refuse byte bound swapped the whole response for a `sugar-bound-exceeded`
    // marker) carries no sourceLedger. Surface THAT as a loud, named hard-error -- not
    // the generic "missing sourceLedger" (which reads like a kit bug and hides the real
    // cause), and never a silent empty headline. A blind aggregate ledger cannot catch a
    // false discharge, so a clipped/over-bound response MUST fail visibly, naming the clip.
    if let Some(refused) = response.get("sugar-bound-exceeded").and_then(Value::as_str) {
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
    let mut call_edges = matching_report_call_edges(response, contract_filter, &filtered_audits);
    call_edges.extend(matching_report_implication_edges(
        response,
        contract_filter,
        &filtered_audits,
    ));
    trace_lift_collection_checkpoint("source_report.call_edges", call_edges.len());
    let source_mementos =
        matching_report_source_mementos(response, contract_filter, &filtered_audits)?;
    trace_lift_collection_checkpoint("source_report.source_mementos", source_mementos.len());
    let plan_mementos = response
        .get("planMementos")
        .or_else(|| response.get("plan_mementos"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    trace_lift_collection_checkpoint("source_report.plan_mementos", plan_mementos.len());
    let vendor_conjoins = vendor_conjoins_from_lift_response(response, contract_filter)?;
    trace_lift_collection_checkpoint("source_report.vendor_conjoins", vendor_conjoins.len());
    let mut diagnostics = response
        .get("diagnostics")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    trace_lift_collection_checkpoint("source_report.diagnostics", diagnostics.len());
    if let Some(condition) =
        no_vendor_test_corpus_condition(&ledger, &assertion_surface_audits, &contracts)
    {
        diagnostics.push(condition);
    }

    let lift_coverage = response
        .get("liftCoverage")
        .or_else(|| response.get("lift_coverage"))
        .cloned();

    Ok(LiftSourceReport {
        ledger,
        audits: filtered_audits,
        factory_audits,
        factory_walk,
        assertion_surface_audits,
        diagnostics,
        source_mementos,
        plan_mementos,
        contracts,
        call_edges,
        vendor_conjoins,
        project_root: None,
        source_oracle_routes: Vec::new(),
        lift_coverage,
    })
}

fn source_report_from_proof_files(
    proof_files: &[PathBuf],
    contract_filter: Option<&str>,
) -> Result<LiftSourceReport, String> {
    let mut pool = sugar_verifier::types::MementoPool::default();
    sugar_verifier::load_all_proofs::load_files_into_pool(proof_files, &mut pool);
    if !pool.load_errors.is_empty() {
        return Err(format!(
            "proof report load errors: {}",
            pool.load_errors
                .iter()
                .map(|error| format!("{}: {}", error.proof_path, error.reason))
                .collect::<Vec<_>>()
                .join("; ")
        ));
    }
    Ok(source_report_from_proof_pool(&pool, contract_filter))
}

fn source_report_from_proof_pool(
    pool: &sugar_verifier::types::MementoPool,
    contract_filter: Option<&str>,
) -> LiftSourceReport {
    let mut contracts = Vec::new();
    let mut contract_names_by_cid = BTreeMap::new();
    for (cid, member) in pool.contract_members() {
        let mut contract = proof_contract_value(pool, cid, member);
        if let Some(name) = contract_value_name(&contract) {
            contract_names_by_cid.insert(cid.clone(), name.to_string());
        }
        if contract_filter.is_some_and(|filter| !proof_contract_matches_filter(&contract, filter)) {
            continue;
        }
        if let Some(object) = contract.as_object_mut() {
            object.insert("proofMemberCid".to_string(), Value::String(cid.to_string()));
        }
        contracts.push(contract);
    }
    // Bridge members (e.g. consumer-lifted "dig:<sourceSymbol>") are also
    // surfaced as contracts so they appear in the report's contracts list.
    // Bridge envelopes carry `sourceSymbol` in the header, not `name`; the
    // report convention is "dig:<sourceSymbol>" per the consumer IR naming.
    for (cid, member) in pool.bridge_members() {
        let source_symbol = match member.field("sourceSymbol").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s,
            _ => continue,
        };
        let bridge_name = format!("dig:{source_symbol}");
        let mut contract = serde_json::json!({
            "kind": "contract",
            "name": bridge_name,
            "contractCid": cid,
        });
        contract_names_by_cid.insert(cid.clone(), bridge_name.clone());
        if contract_filter.is_some_and(|filter| !proof_contract_matches_filter(&contract, filter)) {
            continue;
        }
        if let Some(object) = contract.as_object_mut() {
            object.insert("proofMemberCid".to_string(), Value::String(cid.to_string()));
        }
        contracts.push(contract);
    }

    let mut source_mementos = Vec::new();
    for (_, member) in pool.source_memento_members() {
        let Some(body) = member.body() else {
            continue;
        };
        if contract_filter.is_some_and(|filter| !proof_source_memento_matches_filter(body, filter))
        {
            continue;
        }
        source_mementos.push(body.clone());
    }

    let mut factory_walk = Vec::new();
    for (_, member) in pool.members_by_kind(MemberKind::FactoryWalkMemento) {
        let Some(body) = member.body() else {
            continue;
        };
        if contract_filter.is_some_and(|filter| !factory_audit_matches_filter(body, filter)) {
            continue;
        }
        factory_walk.push(normalize_factory_gap_walk_row(body.clone()));
    }

    let mut assertion_surface_audits = Vec::new();
    for (_, member) in pool.members_by_kind(MemberKind::AssertionSurfaceMemento) {
        let Some(body) = member.body() else {
            continue;
        };
        if contract_filter
            .is_some_and(|filter| !assertion_surface_audit_matches_filter(body, filter))
        {
            continue;
        }
        assertion_surface_audits.push(normalize_assertion_surface_audit(body.clone()));
    }

    let mut plan_mementos = Vec::new();
    for (_, member) in pool.plan_memento_members() {
        if let Some(plan) = proof_plan_memento_with_atoms(pool, member) {
            plan_mementos.push(plan);
        }
    }

    let mut call_edges = proof_implication_call_edges(pool, &contract_names_by_cid);
    call_edges.extend(proof_callsite_precondition_edges(pool));
    let mut call_edges = call_edges
        .into_iter()
        .filter(|edge| {
            contract_filter.is_none_or(|filter| call_edge_matches_filter(edge, filter, &[]))
        })
        .collect::<Vec<_>>();
    let implication_count = pool.member_count_by_kind(MemberKind::Implication);
    let witness_count = pool.member_count_by_kind(MemberKind::WitnessMemento);
    if implication_count > 0 && call_edges.is_empty() {
        call_edges.push(serde_json::json!({
            "sourceContract": "proof-members",
            "targetSymbol": "implication",
            "targetContract": format!("{implication_count} implication memento(s) pinned in proof")
        }));
    }
    if witness_count > 0 {
        call_edges.push(serde_json::json!({
            "sourceContract": "proof-members",
            "targetSymbol": "witness",
            "targetContract": format!("{witness_count} witness memento(s) pinned in proof")
        }));
    }

    // Reconstruct sourceWarrants for each contract from source mementos
    // that were minted as separate pool entries (from ir[*].sourceWarrants).
    // Those entries carry contractName in their header/body (set by mint_source_memento
    // when given a default_contract_name). Top-level sourceMementos[] entries do not
    // have contractName and are excluded here.
    let mut source_warrants_map: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for (_, member) in pool.source_memento_members() {
        let Some(contract_name) = member.field("contractName").and_then(Value::as_str) else {
            continue;
        };
        let Some(body) = member.body() else {
            continue;
        };
        source_warrants_map
            .entry(contract_name.to_string())
            .or_default()
            .push(body.clone());
    }
    for contract in &mut contracts {
        if let Some(name) = contract_value_name(contract) {
            if let Some(warrants) = source_warrants_map.get(name) {
                if let Some(obj) = contract.as_object_mut() {
                    obj.insert("sourceWarrants".to_string(), Value::Array(warrants.clone()));
                }
            }
        }
    }

    let source_loci = source_mementos.len() as i64;
    LiftSourceReport {
        ledger: serde_json::json!({
            "source_loci": source_loci,
            "source_warranted": source_loci,
            "source_support": 0,
            "source_boundary": 0,
            "source_inactive": 0,
            "source_unresolved": 0,
        }),
        audits: Vec::new(),
        factory_audits: Vec::new(),
        factory_walk,
        assertion_surface_audits,
        diagnostics: Vec::new(),
        source_mementos,
        plan_mementos,
        contracts,
        call_edges,
        vendor_conjoins: Vec::new(),
        project_root: None,
        source_oracle_routes: Vec::new(),
        lift_coverage: None,
    }
}

fn proof_implication_call_edges(
    pool: &sugar_verifier::types::MementoPool,
    contract_names_by_cid: &BTreeMap<sugar_verifier::MementoCid, String>,
) -> Vec<Value> {
    pool.implication_members()
        .filter_map(|(_, member)| proof_implication_call_edge(member, contract_names_by_cid))
        .collect()
}

fn contract_name_for_cid(
    contract_names_by_cid: &BTreeMap<sugar_verifier::MementoCid, String>,
    cid: &str,
) -> Option<String> {
    sugar_verifier::MementoCid::try_parse(cid.to_string())
        .ok()
        .and_then(|cid| contract_names_by_cid.get(&cid).cloned())
}

fn proof_implication_call_edge(
    member: &sugar_verifier::StoredMember,
    contract_names_by_cid: &BTreeMap<sugar_verifier::MementoCid, String>,
) -> Option<Value> {
    let antecedent_cid = member.field("antecedentCid").and_then(|v| v.as_str())?;
    let consequent_cid = member.field("consequentCid").and_then(|v| v.as_str())?;
    let source = contract_name_for_cid(contract_names_by_cid, antecedent_cid)
        .unwrap_or_else(|| antecedent_cid.to_string());
    let target = contract_name_for_cid(contract_names_by_cid, consequent_cid)
        .unwrap_or_else(|| consequent_cid.to_string());
    let source_slot = member
        .field("antecedentSlot")
        .and_then(|v| v.as_str())
        .unwrap_or("post");
    let target_slot = member
        .field("consequentSlot")
        .and_then(|v| v.as_str())
        .unwrap_or("pre");
    let mut edge = serde_json::json!({
        "kind": "implication",
        "sourceContract": source,
        "sourceSlot": source_slot,
        "targetSymbol": target,
        "targetContract": target,
        "targetSlot": target_slot,
        "sourceContractCid": antecedent_cid,
        "targetContractCid": consequent_cid,
    });
    for field in ["prover", "proofWitness", "smtLibInput"] {
        if let Some(value) = member.field(field).cloned() {
            edge[field] = value;
        }
    }
    Some(edge)
}

fn proof_callsite_precondition_edges(pool: &sugar_verifier::types::MementoPool) -> Vec<Value> {
    let mut edges = Vec::new();
    let mut seen = BTreeSet::new();
    for callsite in sugar_verifier::enumerate_callsites::run(pool) {
        let source = callsite_producer_contract_name(&callsite)
            .unwrap_or_else(|| callsite.property_name.clone());
        let postcondition = proof_contract_slot_formula_by_name(pool, &source, "post");
        if callsite.bridge_target_cid.is_none() {
            let mut edge = serde_json::json!({
                "kind": "callsite-precondition-unresolved",
                "sourceContract": source,
                "sourceSlot": "post",
                "targetSymbol": callsite.bridge_ir_name.clone(),
                "targetContract": callsite.bridge_ir_name.clone(),
                "targetSlot": "pre",
                "callerContract": callsite.property_name.clone(),
                "callerContractCid": callsite.property_cid.clone(),
                "precondition": format!(
                    "unresolved: NoBridgeTarget: callsite {} has no targetContractCid",
                    callsite.bridge_ir_name
                ),
            });
            if let Some(postcondition) = postcondition {
                edge["postcondition"] = postcondition;
            }
            if let Some(file) = callsite.file.as_ref() {
                edge["file"] = Value::String(file.clone());
            }
            if let Some(line) = callsite.line {
                edge["line"] = serde_json::json!(line);
            }
            let formatted = format_dependency_edge(&edge);
            if seen.insert(formatted) {
                edges.push(edge);
            }
            continue;
        }
        let resolved = match sugar_verifier::resolve_target::run(&callsite, pool) {
            Ok(resolved) => resolved,
            Err(error) => {
                let mut edge = serde_json::json!({
                    "kind": "callsite-precondition-unresolved",
                    "sourceContract": source,
                    "sourceSlot": "post",
                    "targetSymbol": callsite.bridge_ir_name.clone(),
                    "targetContract": callsite.bridge_ir_name.clone(),
                    "targetSlot": "pre",
                    "callerContract": callsite.property_name.clone(),
                    "callerContractCid": callsite.property_cid.clone(),
                    "precondition": format!("unresolved: {error}"),
                });
                if let Some(postcondition) = postcondition {
                    edge["postcondition"] = postcondition;
                }
                if let Some(file) = callsite.file.as_ref() {
                    edge["file"] = Value::String(file.clone());
                }
                if let Some(line) = callsite.line {
                    edge["line"] = serde_json::json!(line);
                }
                let formatted = format_dependency_edge(&edge);
                if seen.insert(formatted) {
                    edges.push(edge);
                }
                continue;
            }
        };
        if resolved.ir_formula.is_none() {
            continue;
        }
        let actual_terms = callsite_actual_terms_for_report(&callsite);
        let Ok(obligation) = sugar_verifier::instantiate::run_specialized(
            &resolved,
            &actual_terms,
            callsite.formal_actuals.as_ref(),
        ) else {
            continue;
        };
        let precondition = sugar_verifier::instantiate::strip_outer_forall(&obligation.ir_formula);
        let target = sugar_verifier::MementoCid::try_parse(resolved.cid.clone())
            .ok()
            .and_then(|cid| pool.cid_to_name.get(&cid).cloned())
            .unwrap_or_else(|| callsite.bridge_ir_name.clone());
        let mut edge = serde_json::json!({
            "kind": "callsite-precondition",
            "sourceContract": source,
            "sourceSlot": "post",
            "targetSymbol": callsite.bridge_ir_name,
            "targetContract": target,
            "targetSlot": "pre",
            "targetContractCid": resolved.cid,
            "callerContract": callsite.property_name,
            "callerContractCid": callsite.property_cid,
            "precondition": precondition,
        });
        if let Some(postcondition) = postcondition {
            edge["postcondition"] = postcondition;
        }
        if let Some(file) = callsite.file {
            edge["file"] = Value::String(file);
        }
        if let Some(line) = callsite.line {
            edge["line"] = serde_json::json!(line);
        }
        let formatted = format_dependency_edge(&edge);
        if seen.insert(formatted) {
            edges.push(edge);
        }
    }
    edges
}

fn callsite_actual_terms_for_report(callsite: &sugar_verifier::types::CallSite) -> Vec<Value> {
    if !callsite.arg_terms.is_empty() {
        return callsite.arg_terms.clone();
    }
    callsite.arg_term.iter().cloned().collect()
}

fn callsite_producer_contract_name(callsite: &sugar_verifier::types::CallSite) -> Option<String> {
    callsite
        .arg_term
        .as_ref()
        .and_then(producer_contract_name_from_term)
}

fn producer_contract_name_from_term(term: &Value) -> Option<String> {
    if term.get("kind").and_then(Value::as_str) != Some("ctor") {
        return None;
    }
    let name = term.get("name").and_then(Value::as_str)?;
    let name = name.strip_prefix("call:").unwrap_or(name);
    let name = name.strip_suffix("#panic_callsite").unwrap_or(name);
    if name.is_empty() {
        None
    } else {
        Some(name.to_string())
    }
}

fn proof_contract_slot_formula_by_name(
    pool: &sugar_verifier::types::MementoPool,
    name: &str,
    slot: &str,
) -> Option<Value> {
    let cid = pool.name_to_cid.get(name)?;
    let body = pool.contract_body_by_cid(cid)?;
    body.get(slot).cloned()
}

/// Apply the workspace_override prefix to `file` fields in source mementos
/// and contract sourceWarrants loaded from a proof pool.  The proof path
/// (dispatch_multi / mint_input_multi) mints source mementos with the raw
/// relative paths returned by the lifter; dispatch_report_lift_plugin applies
/// prefix_workspace_override_source_files inline before minting, so rebased
/// paths already live in the proof there.  Here we close the gap so both
/// paths emit the same file names in the JSON report.
fn rebase_proof_source_file_paths(report: &mut LiftSourceReport) {
    let routes = report.source_oracle_routes.clone();
    if routes.is_empty() {
        return;
    }
    for memento in &mut report.source_mementos {
        if let Some(prefix) = best_workspace_override_prefix_for_memento(memento, &routes) {
            rebase_proof_file_fields(memento, &prefix);
        }
    }
    for contract in &mut report.contracts {
        // Walk into sourceWarrants inside each contract and rebase their file
        // fields; the contract object itself does not carry a top-level "file".
        if let Some(warrants) = contract
            .get_mut("sourceWarrants")
            .and_then(Value::as_array_mut)
        {
            for warrant in warrants.iter_mut() {
                if let Some(prefix) = best_workspace_override_prefix_for_memento(warrant, &routes) {
                    rebase_proof_file_fields(warrant, &prefix);
                }
            }
        }
    }
}

fn best_workspace_override_prefix_for_memento(
    memento: &Value,
    routes: &[SourceOracleRoute],
) -> Option<String> {
    for route in source_oracle_route_attempt_order(routes, memento) {
        if let Some(prefix) = normalized_workspace_prefix(route.workspace_override.as_deref()) {
            return Some(prefix);
        }
    }
    None
}

fn rebase_proof_file_fields(value: &mut Value, prefix: &str) {
    match value {
        Value::Object(object) => {
            if let Some(Value::String(file)) = object.get_mut("file") {
                let normalized = file.replace('\\', "/");
                let relative = normalized.trim_start_matches("./");
                if !normalized.trim().is_empty()
                    && !Path::new(&normalized).is_absolute()
                    && relative != prefix
                    && !relative.starts_with(&format!("{prefix}/"))
                {
                    *file = format!("{prefix}/{relative}");
                }
            }
            for child in object.values_mut() {
                rebase_proof_file_fields(child, prefix);
            }
        }
        Value::Array(items) => {
            for item in items {
                rebase_proof_file_fields(item, prefix);
            }
        }
        _ => {}
    }
}

fn enrich_report_source_mementos_from_oracles(report: &mut LiftSourceReport) {
    let Some(project_root) = report.project_root.clone() else {
        return;
    };
    let routes = report.source_oracle_routes.clone();
    for memento in &mut report.source_mementos {
        enrich_source_memento_value_from_oracle(&project_root, &routes, memento);
    }
    for row in &mut report.factory_walk {
        if let Some(memento) = row.get_mut("sourceMemento") {
            enrich_source_memento_value_from_oracle(&project_root, &routes, memento);
        }
    }
}

fn enrich_source_memento_value_from_oracle(
    project_root: &Path,
    routes: &[SourceOracleRoute],
    memento: &mut Value,
) {
    let resolution = resolve_report_source_memento_via_plan_routes(project_root, routes, memento);
    if let Some(object) = memento.as_object_mut() {
        object.insert("sourceOracle".to_string(), resolution);
    }
}

fn resolve_report_source_memento_via_plan_routes(
    project_root: &Path,
    routes: &[SourceOracleRoute],
    memento_value: &Value,
) -> Value {
    let ordered_routes = source_oracle_route_attempt_order(routes, memento_value);
    if let Some(lines) = visual_lines_from_project_file(Some(project_root), memento_value) {
        let mut resolution = serde_json::json!({
            "status": "resolved",
            "sourceLines": source_oracle_lines_json(Some(&lines)),
            "display": "source present",
        });
        if let Some(route) = ordered_routes.first() {
            if let Some(object) = resolution.as_object_mut() {
                object.insert("surface".to_string(), Value::String(route.surface.clone()));
                object.insert(
                    "role".to_string(),
                    route.role.clone().map(Value::String).unwrap_or(Value::Null),
                );
                object.insert(
                    "workspaceOverride".to_string(),
                    route
                        .workspace_override
                        .clone()
                        .map(Value::String)
                        .unwrap_or(Value::Null),
                );
            }
        }
        return resolution;
    }
    let attempts = ordered_routes
        .into_iter()
        .map(|route| {
            source_oracle_attempt_json(route, Some(format_source_not_present(memento_value)))
        })
        .collect::<Vec<_>>();
    serde_json::json!({
        "status": "absent",
        "display": format_source_not_present(memento_value),
        "attempts": attempts,
    })
}

fn source_oracle_route_attempt_order<'a>(
    routes: &'a [SourceOracleRoute],
    memento: &Value,
) -> Vec<&'a SourceOracleRoute> {
    let mut ordered = routes.iter().collect::<Vec<_>>();
    ordered.sort_by_key(|route| source_oracle_route_priority(route, memento));
    ordered
}

fn source_oracle_route_priority(route: &SourceOracleRoute, memento: &Value) -> usize {
    let role = route.role.as_deref().unwrap_or_default();
    let memento_role = memento
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let contract_name = memento
        .get("contractName")
        .or_else(|| memento.get("contract_name"))
        .and_then(Value::as_str)
        .unwrap_or_default();
    if !memento_role.is_empty()
        && (memento_role == role
            || (memento_role.contains("test") && role == "unit-test-assertions")
            || (memento_role.contains("contract") && role == "body-universes"))
    {
        return 0;
    }
    if contract_name.contains("test") && role == "unit-test-assertions" {
        return 1;
    }
    if role == "body-universes" {
        return 2;
    }
    if role == "unit-test-assertions" {
        return 3;
    }
    4
}

fn source_oracle_attempt_json(route: &SourceOracleRoute, reason: Option<String>) -> Value {
    serde_json::json!({
        "surface": route.surface.clone(),
        "role": route.role.clone(),
        "workspaceOverride": route.workspace_override.clone(),
        "reason": reason.unwrap_or_else(|| "source oracle did not resolve this memento".to_string()),
    })
}

fn proof_contract_value(
    pool: &sugar_verifier::types::MementoPool,
    cid: &sugar_verifier::MementoCid,
    member: &sugar_verifier::StoredMember,
) -> Value {
    let name = member
        .field("contractName")
        .or_else(|| member.field("name"))
        .and_then(|v| v.as_str())
        .unwrap_or("<unknown contract>");
    let mut contract = serde_json::json!({
        "kind": "contract",
        "name": name,
        "contractCid": cid,
    });
    if let Some(body) = pool.contract_body_for_member(member) {
        for slot in ["pre", "post", "inv"] {
            if let Some(formula) = body.get(slot) {
                contract[slot] = formula.clone();
            }
        }
    }
    contract
}

fn proof_contract_matches_filter(contract: &Value, filter: &str) -> bool {
    contract_value_name(contract).is_some_and(|name| name.contains(filter))
        || serde_json::to_string(contract)
            .ok()
            .is_some_and(|text| text.contains(filter))
}

fn proof_source_memento_matches_filter(source: &Value, filter: &str) -> bool {
    [
        "claimName",
        "claim_name",
        "contractName",
        "contract_name",
        "sourceFunctionName",
        "source_function_name",
        "file",
        "role",
    ]
    .into_iter()
    .any(|field| {
        source
            .get(field)
            .and_then(Value::as_str)
            .is_some_and(|value| value.contains(filter))
    })
}

fn proof_plan_memento_with_atoms(
    pool: &sugar_verifier::types::MementoPool,
    envelope: &sugar_verifier::StoredMember,
) -> Option<Value> {
    let mut body = envelope.body()?.clone();
    let refs = body
        .get("planAtoms")
        .or_else(|| body.get("plan_atoms"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if refs.is_empty() {
        return Some(body);
    }
    let mut resolved_atoms = Vec::new();
    let mut unresolved_refs = Vec::new();
    for atom_ref in refs {
        let Some(atom_cid) = atom_ref.get("atomCid").and_then(Value::as_str) else {
            unresolved_refs.push(atom_ref);
            continue;
        };
        let Some(bytes) = pool.atoms.get(atom_cid) else {
            unresolved_refs.push(atom_ref);
            continue;
        };
        match serde_json::from_slice::<Value>(bytes) {
            Ok(atom) => resolved_atoms.push(atom),
            Err(_) => unresolved_refs.push(atom_ref),
        }
    }
    if let Some(object) = body.as_object_mut() {
        object.insert("planAtoms".to_string(), Value::Array(resolved_atoms));
        if !unresolved_refs.is_empty() {
            object.insert(
                "unresolvedPlanAtoms".to_string(),
                Value::Array(unresolved_refs),
            );
        }
    }
    Some(body)
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

fn matching_report_implication_edges(
    response: &Value,
    contract_filter: Option<&str>,
    audits: &[Value],
) -> Vec<Value> {
    let Some(implications) = response.get("implications").and_then(Value::as_array) else {
        return Vec::new();
    };
    let audit_bases = audits
        .iter()
        .filter_map(contract_name)
        .map(contract_group_key)
        .collect::<Vec<_>>();
    clone_matching_report_values(
        "matching_report_implication_edges",
        implications,
        |implication| {
            let edge = implication_edge_from_row(implication);
            contract_filter
                .is_none_or(|filter| call_edge_matches_filter(&edge, filter, &audit_bases))
        },
        |row| implication_edge_from_row(&row),
    )
}

fn implication_edge_from_row(row: &Value) -> Value {
    let source = report_text_field(row, &["antecedent", "sourceContract", "source_contract"])
        .unwrap_or_else(|| "<unknown antecedent>".to_string());
    let source_slot = report_text_field(
        row,
        &[
            "antecedentSlot",
            "antecedent_slot",
            "sourceSlot",
            "source_slot",
        ],
    )
    .unwrap_or_else(|| "post".to_string());
    let target = report_text_field(row, &["consequent", "targetContract", "target_contract"])
        .unwrap_or_else(|| "<unknown consequent>".to_string());
    let target_slot = report_text_field(
        row,
        &[
            "consequentSlot",
            "consequent_slot",
            "targetSlot",
            "target_slot",
        ],
    )
    .unwrap_or_else(|| "pre".to_string());
    let target_symbol = report_text_field(row, &["targetSymbol", "target_symbol"])
        .unwrap_or_else(|| target.clone());
    let mut edge = serde_json::json!({
        "kind": "implication",
        "sourceContract": source,
        "sourceSlot": source_slot,
        "targetSymbol": target_symbol,
        "targetContract": target,
        "targetSlot": target_slot,
    });
    for (from, to) in [
        ("name", "name"),
        ("prover", "prover"),
        ("proofWitness", "proofWitness"),
        ("proof_witness", "proofWitness"),
    ] {
        if let Some(value) = row.get(from).cloned() {
            edge[to] = value;
        }
    }
    edge
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
        || row
            .get("sourceMemento")
            .is_some_and(|memento| proof_source_memento_matches_filter(memento, filter))
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
    let mut value = serde_json::json!({
        "kind": "lift-source-report",
        "sourceLedger": report.ledger,
        "sourceAudits": report.audits,
        "factoryAudits": report.factory_audits,
        "factoryWalk": report.factory_walk,
        "assertionSurfaceAudits": report.assertion_surface_audits,
        "diagnostics": report.diagnostics,
        "sourceMementos": report.source_mementos,
        "planMementos": report.plan_mementos,
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
    });
    if let Some(assembly_plan) = assembly_plan_json_value(report) {
        value["assemblyPlan"] = assembly_plan;
    }
    // #4013 dual-axis coverage (majority assertions / minority bodies).
    if let Some(coverage) = &report.lift_coverage {
        value["liftCoverage"] = coverage.clone();
    }
    value
}

fn render_report_json(
    report: &LiftSourceReport,
    prove_report: Option<&sugar_verifier::Report>,
) -> Result<String, serde_json::Error> {
    let value = if let Some(prove_report) = prove_report {
        let mut prove_json = report_fmt::report_to_json(prove_report);
        render_source_partition(
            &mut prove_json,
            prove_report,
            report.project_root.as_deref(),
        );
        serde_json::json!({
            "kind": "lift-prove-report",
            "lift": source_report_json_value(report),
            "prove": prove_json,
        })
    } else {
        source_report_json_value(report)
    };
    serde_json::to_string_pretty(&value).map(|mut rendered| {
        rendered.push('\n');
        rendered
    })
}

/// Render `lineAccounting` and `lineAccountingPartition` from per-file
/// `SourcePartition`s (see `source_partition` module docs). The partition is
/// the single source of truth: `lineAccounting` entries and the partition
/// totals both project from it, and a file whose tiling is not total surfaces
/// its residue as a LOUD, named construction failure -- never a silent skip.
/// `report_fmt` cannot do this itself: it has no source-file access, so it
/// emits only the row-derived warrant/effect claims, which this overwrites
/// with the tiled result once source is in hand.
fn render_source_partition(
    prove_json: &mut Value,
    prove_report: &sugar_verifier::Report,
    project_root: Option<&Path>,
) {
    let Some(project_root) = project_root else {
        return;
    };
    let (entries, partitions) =
        crate::source_partition::build_line_accounting(prove_report, project_root);
    prove_json["lineAccounting"] = Value::Array(entries);
    prove_json["lineAccountingPartition"] = Value::Array(partitions);
}

fn render_report_summary_json(summary: &LiftReportSummary) -> Result<String, serde_json::Error> {
    let source_unresolved = source_unresolved_count(&summary.ledger);
    let source_accounting = serde_json::json!({
        "loci": source_count(&summary.ledger, "source_loci"),
        "warranted": source_count(&summary.ledger, "source_warranted"),
        "inactive": source_count(&summary.ledger, "source_inactive"),
        "support": source_count(&summary.ledger, "source_support"),
        "boundary": source_count(&summary.ledger, "source_boundary"),
        "unresolved": source_unresolved,
    });
    let value = serde_json::json!({
        "kind": "lift-source-report-summary",
        "sourceAccounting": source_accounting,
        "factoryAccounting": {
            "sites": summary.factory.sites,
            "warranted": summary.factory.warranted,
            "incomplete": summary.factory.incomplete,
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
        "source accounting: loci={} warranted={} inactive={} support={} boundary={} unresolved={}\n",
        source_count(&summary.ledger, "source_loci"),
        source_count(&summary.ledger, "source_warranted"),
        source_count(&summary.ledger, "source_inactive"),
        source_count(&summary.ledger, "source_support"),
        source_count(&summary.ledger, "source_boundary"),
        source_unresolved,
    ));
    if summary.factory.sites > 0 {
        out.push_str(&format!(
            "factory accounting: sites={} warranted={} incomplete={} support={} unresolved={}\n",
            summary.factory.sites,
            summary.factory.warranted,
            summary.factory.incomplete,
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
    Plain,
    Green,
    Red,
}

struct VisualFactoryWalkRow {
    context: String,
    source: String,
    label: String,
    tone: VisualTone,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct VisualRedGrounds {
    kind: &'static str,
    file: String,
    line: u64,
    col: u64,
    reason: String,
}

impl VisualRedGrounds {
    fn own_label(&self, here: bool) -> String {
        let here = if here { " HERE" } else { "" };
        format!("RED{here} {}: {}", self.kind, self.reason)
    }

    fn inherited_label(&self) -> String {
        format!(
            "RED via {} at {}:{}:{}: {}",
            self.kind, self.file, self.line, self.col, self.reason
        )
    }
}

#[derive(Clone, Copy)]
struct VisualSourceLookup<'a> {
    project_root: Option<&'a Path>,
}

struct VisualBoundaryRow {
    context: String,
    sort_key: (u64, u64, u64, u64),
    source: String,
    label: String,
    grounds: VisualRedGrounds,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum UniverseVisualMode {
    Fact,
    BodyComplete,
    BodyIncomplete,
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
    };
    let rows = visual_factory_walk_rows(&report.factory_walk, source_lookup);
    let mut out = String::new();
    out.push_str(&render_report_plan_roll_call(report));
    out.push_str(&render_universe_visual_report(report, source_lookup));
    if !out.is_empty() && !out.ends_with('\n') {
        out.push('\n');
    }
    out.push_str("factory visual:\n");
    if rows.is_empty() {
        out.push_str("  <no factory walk emitted>\n");
    } else {
        let mut current_context = String::new();
        for row in rows {
            if row.context != current_context {
                current_context = row.context.clone();
                out.push_str(&format!("  contract {current_context}\n"));
            }
            render_visual_source_annotation(&mut out, &row.source, row.tone, &row.label);
        }
    }
    if !report.call_edges.is_empty() {
        out.push_str("call edges observed:\n");
        for edge in &report.call_edges {
            out.push_str(&format!("  - {}\n", format_call_edge(edge)));
        }
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
        let fact_universe = contract_inv_is_observed_fact(contract);
        let warrants = contract_visual_warrants(report, contract);
        let context = warrants
            .first()
            .map(|warrant| source_memento_context_key(warrant));
        let incomplete_boundary = context.as_deref().and_then(|context| {
            boundaries
                .iter()
                .find(|boundary| boundary.context == context)
        });
        let mode = if fact_universe {
            UniverseVisualMode::Fact
        } else if incomplete_boundary.is_some() {
            UniverseVisualMode::BodyIncomplete
        } else {
            UniverseVisualMode::BodyComplete
        };
        out.push_str(&format!("  universe {name}\n"));
        match mode {
            UniverseVisualMode::BodyIncomplete => {
                let reason = incomplete_boundary
                    .map(|boundary| boundary.grounds.reason.as_str())
                    .unwrap_or("effect");
                out.push_str(&format!("    incomplete: {reason}\n"));
            }
            UniverseVisualMode::Fact | UniverseVisualMode::BodyComplete => {
                out.push_str(&format!(
                    "    FOL: {}\n",
                    format_contract_visual_fol(contract)
                ));
            }
        }
        if mode == UniverseVisualMode::BodyComplete {
            render_visual_forensic_context(&mut out, report, contract);
        }
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
            mode,
        );
    }
    out
}

fn render_visual_forensic_context(out: &mut String, report: &LiftSourceReport, contract: &Value) {
    let contracts = [contract];
    let warranting_facts = warranting_fact_rows_for_contracts(report, &contracts);
    let downstream_edges = downstream_call_edges_for_contracts(&report.call_edges, &contracts);
    if warranting_facts.is_empty() && downstream_edges.is_empty() {
        return;
    }
    if !warranting_facts.is_empty() {
        out.push_str("    walk warranted by observed facts:\n");
        for fact in warranting_facts.iter().take(8) {
            out.push_str(&format!("      - {}\n", fact.row));
        }
        if warranting_facts.len() > 8 {
            out.push_str(&format!(
                "      - (+{} more observed facts using this universe)\n",
                warranting_facts.len() - 8
            ));
        }
    }
    out.push_str("    callsite preconditions depending on this post:\n");
    if downstream_edges.is_empty() {
        out.push_str("      - no precondition implication mementos observed in this proof\n");
    } else {
        for edge in &downstream_edges {
            out.push_str(&format!("      - {}\n", format_dependency_edge(edge)));
        }
    }
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
    mode: UniverseVisualMode,
) {
    let context = warrants
        .first()
        .map(|warrant| source_memento_context_key(warrant))
        .unwrap_or_else(|| "<unknown>".to_string());
    let factory_predicates = if mode == UniverseVisualMode::BodyIncomplete {
        Vec::new()
    } else {
        universe_factory_predicate_rows(factory_walk, source_lookup, &context)
    };
    if let Some(source_walk) = universe_source_walk_lines(source_lookup, warrants) {
        render_universe_source_walk(
            out,
            &source_walk,
            boundaries,
            &context,
            source_lookup,
            warrants,
            predicates,
            &factory_predicates,
            mode,
        );
        return;
    }

    let mut items = Vec::new();
    if mode == UniverseVisualMode::BodyIncomplete {
        for boundary in boundaries
            .iter()
            .filter(|boundary| boundary.context == context)
        {
            items.push(UniverseVisualItem::Boundary(boundary));
        }
    }
    if mode == UniverseVisualMode::BodyIncomplete {
        // Red body universes are effect traces, not proof traces.
    } else if factory_predicates.is_empty() {
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

    let mut red: Option<VisualRedGrounds> = None;
    for item in items {
        match item {
            UniverseVisualItem::Boundary(boundary) => {
                red = Some(boundary.grounds.clone());
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
                let (tone, annotation) = match mode {
                    UniverseVisualMode::Fact => (VisualTone::Plain, format!("FACT ⊢ {predicate}")),
                    UniverseVisualMode::BodyComplete | UniverseVisualMode::BodyIncomplete => {
                        let tone = if red.is_some() {
                            VisualTone::Red
                        } else {
                            VisualTone::Green
                        };
                        let status = if red.is_some() { "RED" } else { "GREEN" };
                        let annotation = if let Some(grounds) = red.as_ref() {
                            grounds.inherited_label()
                        } else {
                            format!("{status} ⊢ {predicate}")
                        };
                        (tone, annotation)
                    }
                };
                render_visual_source_annotation(out, &source, tone, &annotation);
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct VisualSourceWalkLine {
    line: u64,
    source: String,
}

fn render_universe_source_walk(
    out: &mut String,
    source_walk: &[VisualSourceWalkLine],
    boundaries: &[VisualBoundaryRow],
    context: &str,
    source_lookup: VisualSourceLookup<'_>,
    warrants: &[&Value],
    predicates: &[String],
    factory_predicates: &[UniverseFactoryPredicateRow],
    mode: UniverseVisualMode,
) {
    let mut predicate_by_line: BTreeMap<u64, Vec<String>> = BTreeMap::new();
    if mode == UniverseVisualMode::BodyIncomplete {
        // Incomplete body universes emit no predicates anywhere.
    } else if factory_predicates.is_empty() {
        for (index, warrant) in warrants.iter().enumerate() {
            let line = warrant
                .get("span")
                .map(source_span_sort_key)
                .unwrap_or_default()
                .0;
            if line == 0 {
                continue;
            }
            let predicate = predicates
                .get(index)
                .cloned()
                .unwrap_or_else(|| "<predicate unavailable>".to_string());
            predicate_by_line.entry(line).or_default().push(predicate);
        }
    } else {
        for predicate in factory_predicates {
            let line = predicate.sort_key.0;
            if line == 0 {
                continue;
            }
            predicate_by_line
                .entry(line)
                .or_default()
                .push(predicate.predicate.clone());
        }
    }

    let mut boundary_by_line: BTreeMap<u64, Vec<&VisualBoundaryRow>> = BTreeMap::new();
    if mode == UniverseVisualMode::BodyIncomplete {
        for boundary in boundaries
            .iter()
            .filter(|boundary| boundary.context == context)
        {
            let line = boundary.sort_key.0;
            if line == 0 {
                continue;
            }
            boundary_by_line.entry(line).or_default().push(boundary);
        }
    }

    let mut red: Option<VisualRedGrounds> = None;
    let mut rendered_lines = BTreeSet::new();
    for line in source_walk {
        rendered_lines.insert(line.line);
        if mode == UniverseVisualMode::BodyIncomplete {
            if let Some(boundary_rows) = boundary_by_line.get(&line.line) {
                if let Some(boundary) = boundary_rows.first() {
                    red = Some(boundary.grounds.clone());
                    render_visual_source_annotation(
                        out,
                        &line.source,
                        VisualTone::Red,
                        &boundary.label,
                    );
                    continue;
                }
            }
        }
        match mode {
            UniverseVisualMode::Fact => {
                let annotation = predicate_by_line
                    .get(&line.line)
                    .map(|predicates| format!("FACT ⊢ {}", predicates.join(" ∧ ")))
                    .unwrap_or_default();
                render_visual_source_annotation(out, &line.source, VisualTone::Plain, &annotation);
                continue;
            }
            UniverseVisualMode::BodyComplete | UniverseVisualMode::BodyIncomplete => {}
        }
        if let Some(boundary_rows) = boundary_by_line.get(&line.line) {
            if let Some(boundary) = boundary_rows.first() {
                red = Some(boundary.grounds.clone());
                render_visual_source_annotation(
                    out,
                    &line.source,
                    VisualTone::Red,
                    &boundary.label,
                );
                continue;
            }
        }
        let tone = if red.is_some() {
            VisualTone::Red
        } else {
            VisualTone::Green
        };
        let status = if red.is_some() { "RED" } else { "GREEN" };
        let annotation = if let Some(grounds) = red.as_ref() {
            grounds.inherited_label()
        } else if let Some(predicates) = predicate_by_line.get(&line.line) {
            format!("{status} ⊢ {}", predicates.join(" ∧ "))
        } else {
            status.to_string()
        };
        render_visual_source_annotation(out, &line.source, tone, &annotation);
    }

    for predicate in factory_predicates
        .iter()
        .filter(|predicate| !rendered_lines.contains(&predicate.sort_key.0))
    {
        let (tone, annotation) = if mode == UniverseVisualMode::Fact {
            (VisualTone::Plain, format!("FACT ⊢ {}", predicate.predicate))
        } else {
            (
                VisualTone::Green,
                format!("GREEN ⊢ {}", predicate.predicate),
            )
        };
        render_visual_source_annotation(out, &predicate.source, tone, &annotation);
    }

    if factory_predicates.is_empty() && mode != UniverseVisualMode::BodyIncomplete {
        for (index, warrant) in warrants.iter().enumerate() {
            let line = warrant
                .get("span")
                .map(source_span_sort_key)
                .unwrap_or_default()
                .0;
            if rendered_lines.contains(&line) {
                continue;
            }
            let predicate = predicates
                .get(index)
                .cloned()
                .unwrap_or_else(|| "<predicate unavailable>".to_string());
            let (tone, annotation) = if mode == UniverseVisualMode::Fact {
                (VisualTone::Plain, format!("FACT ⊢ {predicate}"))
            } else {
                (VisualTone::Green, format!("GREEN ⊢ {predicate}"))
            };
            render_visual_source_annotation(
                out,
                &resolve_source_memento_visual_source(source_lookup, warrant),
                tone,
                &annotation,
            );
        }
    }
}

fn universe_source_walk_lines(
    source_lookup: VisualSourceLookup<'_>,
    warrants: &[&Value],
) -> Option<Vec<VisualSourceWalkLine>> {
    let warrant = warrants.iter().copied().max_by_key(|warrant| {
        warrant
            .get("span")
            .map(source_span_sort_key)
            .map(|(start_line, _, end_line, _)| end_line.saturating_sub(start_line))
            .unwrap_or(0)
    })?;
    resolve_source_memento_visual_lines(source_lookup, warrant).ok()
}

fn resolve_source_memento_visual_lines(
    source_lookup: VisualSourceLookup<'_>,
    memento_value: &Value,
) -> Result<Vec<VisualSourceWalkLine>, String> {
    if let Some(resolution) = source_oracle_resolution_from_report_memento(memento_value) {
        if let Some(lines) = resolution.lines.clone() {
            return Ok(lines);
        }
        if let Some(source) = resolution.source.as_deref() {
            return visual_lines_from_source_text(memento_value, source)
                .ok_or_else(|| "source oracle text did not map to source lines".to_string());
        }
        return Err(resolution.display_source_or_absent(memento_value));
    }
    if let Some(lines) = visual_lines_from_project_file(source_lookup.project_root, memento_value) {
        return Ok(lines);
    }
    Err(format_source_not_present(memento_value))
}

fn visual_lines_from_project_file(
    project_root: Option<&Path>,
    memento_value: &Value,
) -> Option<Vec<VisualSourceWalkLine>> {
    let project_root = project_root?;
    let memento = source_memento_from_report_json(memento_value)?;
    let path = if Path::new(&memento.file).is_absolute() {
        PathBuf::from(&memento.file)
    } else {
        project_root.join(&memento.file)
    };
    let source = std::fs::read_to_string(path).ok()?;
    visual_lines_from_source_file_text(memento_value, &source)
}

fn visual_lines_from_source_file_text(
    memento_value: &Value,
    source: &str,
) -> Option<Vec<VisualSourceWalkLine>> {
    let span = memento_value.get("span")?;
    let start_line = span.get("start_line").and_then(Value::as_u64).unwrap_or(1);
    let end_line = span
        .get("end_line")
        .and_then(Value::as_u64)
        .unwrap_or(start_line)
        .max(start_line);
    let lines = source.lines().collect::<Vec<_>>();
    let start = start_line.checked_sub(1)? as usize;
    let end = end_line.min(lines.len() as u64) as usize;
    let selected = lines.get(start..end)?;
    let rendered = selected
        .iter()
        .enumerate()
        .map(|(offset, source)| VisualSourceWalkLine {
            line: start_line + offset as u64,
            source: source.to_string(),
        })
        .collect::<Vec<_>>();
    (!rendered.is_empty()).then_some(rendered)
}

fn visual_lines_from_source_text(
    memento_value: &Value,
    source: &str,
) -> Option<Vec<VisualSourceWalkLine>> {
    let start_line = memento_value
        .get("span")
        .and_then(|span| span.get("start_line"))
        .and_then(Value::as_u64)
        .unwrap_or(1);
    let lines = source
        .lines()
        .enumerate()
        .map(|(index, source)| VisualSourceWalkLine {
            line: start_line + index as u64,
            source: source.to_string(),
        })
        .collect::<Vec<_>>();
    (!lines.is_empty()).then_some(lines)
}

fn render_visual_source_annotation(
    out: &mut String,
    source: &str,
    tone: VisualTone,
    annotation: &str,
) {
    let first = source.lines().next().unwrap_or("");
    if annotation.is_empty() {
        out.push_str(&format!("    {}\n", ansi_paint(first, tone)));
        return;
    }
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
        let grounds = visual_red_grounds_from_factory_row(row, raw_verdict, memento);
        let label = grounds.own_label(here);
        rows.push(VisualBoundaryRow {
            context,
            sort_key: memento
                .get("span")
                .map(source_span_sort_key)
                .unwrap_or_default(),
            source: resolve_source_memento_visual_source(source_lookup, memento),
            label,
            grounds,
        });
    }
    rows
}

fn visual_red_grounds_from_factory_row(
    row: &Value,
    raw_verdict: &str,
    memento: &Value,
) -> VisualRedGrounds {
    let kind = if raw_verdict == "gap" {
        "gap"
    } else {
        "effect"
    };
    let reason = row
        .get("reason")
        .and_then(Value::as_str)
        .filter(|reason| !reason.trim().is_empty())
        .unwrap_or_else(|| panic_groundless_red_row(row, raw_verdict, memento));
    let (file, line, col) = visual_red_blame(row, memento);
    VisualRedGrounds {
        kind,
        file,
        line,
        col,
        reason: reason.to_string(),
    }
}

fn panic_groundless_red_row(row: &Value, raw_verdict: &str, memento: &Value) -> ! {
    let status = row
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("<missing>");
    let selected = row
        .get("selected")
        .and_then(Value::as_str)
        .unwrap_or("<none>");
    let ast_kind = row
        .get("ast_kind")
        .or_else(|| row.get("astKind"))
        .and_then(Value::as_str)
        .unwrap_or("<unknown>");
    let requested_role = row
        .get("requested_role")
        .or_else(|| row.get("requestedRole"))
        .and_then(Value::as_str)
        .unwrap_or("<unknown>");
    let (file, line, col) = visual_red_blame(row, memento);
    panic!(
        "red verdict carries no grounds; the ledger lost the dragon: \
         owner=sugar-cli.visual status={status} verdict={raw_verdict} \
         requested_role={requested_role} ast_kind={ast_kind} selected={selected} \
         blame={file}:{line}:{col} replacement=thread the own gap/effect reason \
         or inherited contamination provenance into this red row before rendering"
    );
}

fn visual_red_blame(row: &Value, memento: &Value) -> (String, u64, u64) {
    let file = memento
        .get("file")
        .and_then(Value::as_str)
        .or_else(|| row.get("file").and_then(Value::as_str))
        .unwrap_or("<unknown>")
        .to_string();
    let line = memento
        .get("span")
        .and_then(|span| span.get("start_line"))
        .and_then(Value::as_u64)
        .or_else(|| row.get("line").and_then(Value::as_u64))
        .unwrap_or(0);
    let col = memento
        .get("span")
        .and_then(|span| span.get("start_col"))
        .and_then(Value::as_u64)
        .unwrap_or(0);
    (file, line, col)
}

fn visual_factory_walk_rows(
    factory_walk: &[Value],
    source_lookup: VisualSourceLookup<'_>,
) -> Vec<VisualFactoryWalkRow> {
    let mut red_seen: BTreeMap<String, VisualRedGrounds> = BTreeMap::new();
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
        let (tone, label) = if raw_verdict == "complete" {
            let predicate = row
                .get("emittedFormula")
                .or_else(|| row.get("emitted_formula"))
                .or_else(|| row.get("formula"))
                .map(proofir_formula_to_fol_with_instances);
            if let Some(grounds) = red_seen.get(&context) {
                (VisualTone::Red, grounds.inherited_label())
            } else {
                (
                    VisualTone::Green,
                    predicate
                        .map(|predicate| format!("GREEN ⊢ {predicate}"))
                        .unwrap_or_else(|| "GREEN".to_string()),
                )
            }
        } else if raw_verdict == "gap" {
            let grounds = visual_red_grounds_from_factory_row(
                row,
                raw_verdict,
                row.get("sourceMemento").unwrap_or(&Value::Null),
            );
            let here = !red_seen.contains_key(&context);
            red_seen
                .entry(context.clone())
                .or_insert_with(|| grounds.clone());
            (VisualTone::Red, grounds.own_label(here))
        } else {
            let grounds = visual_red_grounds_from_factory_row(
                row,
                raw_verdict,
                row.get("sourceMemento").unwrap_or(&Value::Null),
            );
            let here = !red_seen.contains_key(&context);
            red_seen
                .entry(context.clone())
                .or_insert_with(|| grounds.clone());
            (VisualTone::Red, grounds.own_label(here))
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
    if matches!(tone, VisualTone::Plain) {
        return source.to_string();
    }
    let color = match tone {
        VisualTone::Plain => unreachable!("plain tone returned before ANSI selection"),
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
    if let Some(resolution) = source_oracle_resolution_from_report_memento(memento_value) {
        return resolution.display_source_or_absent(memento_value);
    }
    if let Some(lines) = visual_lines_from_project_file(source_lookup.project_root, memento_value) {
        return lines
            .iter()
            .map(|line| line.source.as_str())
            .collect::<Vec<_>>()
            .join("\n");
    }
    if source_memento_from_report_json(memento_value).is_none() {
        return "<source memento invalid>".to_string();
    }
    format_source_not_present(memento_value)
}

fn source_oracle_resolution_from_report_memento(
    memento_value: &Value,
) -> Option<SourceOracleResolution> {
    let oracle = memento_value.get("sourceOracle")?;
    Some(SourceOracleResolution {
        status: oracle
            .get("status")
            .and_then(Value::as_str)
            .filter(|status| !status.is_empty())
            .map(str::to_string),
        source: oracle
            .get("source")
            .and_then(Value::as_str)
            .filter(|source| !source.trim().is_empty())
            .map(str::to_string),
        lines: source_oracle_lines_from_value(oracle),
        display: oracle
            .get("display")
            .and_then(Value::as_str)
            .filter(|display| !display.trim().is_empty())
            .map(str::to_string),
        reason: oracle
            .get("reason")
            .and_then(Value::as_str)
            .filter(|reason| !reason.trim().is_empty())
            .map(str::to_string),
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SourceOracleResolution {
    status: Option<String>,
    source: Option<String>,
    lines: Option<Vec<VisualSourceWalkLine>>,
    display: Option<String>,
    reason: Option<String>,
}

impl SourceOracleResolution {
    fn display_source_or_absent(&self, memento: &Value) -> String {
        if let Some(lines) = self.lines.as_deref() {
            return lines
                .iter()
                .map(|line| line.source.as_str())
                .collect::<Vec<_>>()
                .join("\n");
        }
        if let Some(source) = self.source.as_deref() {
            return source.to_string();
        }
        self.display
            .clone()
            .unwrap_or_else(|| format_source_not_present(memento))
    }
}

fn source_oracle_lines_from_value(value: &Value) -> Option<Vec<VisualSourceWalkLine>> {
    let lines = value
        .get("sourceLines")
        .or_else(|| value.get("source_lines"))?
        .as_array()?;
    let parsed = lines
        .iter()
        .filter_map(|line| {
            let number = line
                .get("line")
                .or_else(|| line.get("lineNumber"))
                .or_else(|| line.get("line_number"))
                .and_then(Value::as_u64)?;
            let source = line
                .get("source")
                .or_else(|| line.get("text"))
                .and_then(Value::as_str)?;
            Some(VisualSourceWalkLine {
                line: number,
                source: source.to_string(),
            })
        })
        .collect::<Vec<_>>();
    (!parsed.is_empty()).then_some(parsed)
}

fn source_oracle_lines_json(lines: Option<&[VisualSourceWalkLine]>) -> Value {
    lines
        .map(|lines| {
            Value::Array(
                lines
                    .iter()
                    .map(|line| {
                        serde_json::json!({
                            "line": line.line,
                            "source": line.source,
                        })
                    })
                    .collect(),
            )
        })
        .unwrap_or(Value::Null)
}

#[cfg(test)]
struct RoutedSourceMemento {
    workspace_root: PathBuf,
    memento: Value,
}

#[cfg(test)]
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
        memento,
    })
}

#[cfg(test)]
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
        [route] if normalized_workspace_prefix(route.workspace_override.as_deref()).is_none() => {
            Some((route, normalized_file))
        }
        [route] if normalized_workspace_prefix(route.workspace_override.as_deref()).is_some() => {
            Some((route, normalized_file))
        }
        _ => None,
    }
}

#[cfg(test)]
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

#[cfg(test)]
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

fn contract_visual_warrants<'a>(
    report: &'a LiftSourceReport,
    contract: &'a Value,
) -> Vec<&'a Value> {
    if let Some(name) = contract_value_name(contract) {
        if let Some(memento) = source_memento_for_contract(report, name) {
            if contract_inv_is_observed_fact(contract) {
                return vec![fuller_source_memento_for_report(report, memento).unwrap_or(memento)];
            }
            return vec![memento];
        }
    }
    contract_source_warrants(contract)
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

fn resolve_factory_walk_term(_project_root: Option<&Path>, row: &Value) -> String {
    let Some(memento_value) = row.get("sourceMemento") else {
        return "<source memento absent>".to_string();
    };
    if let Some(resolution) = source_oracle_resolution_from_report_memento(memento_value) {
        return resolution.display_source_or_absent(memento_value);
    }
    if source_memento_from_report_json(memento_value).is_none() {
        return "<source memento invalid>".to_string();
    }
    format_source_not_present(memento_value)
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

fn render_report_plan_roll_call(report: &LiftSourceReport) -> String {
    let Some(plan_body) = report.plan_mementos.iter().find_map(plan_body_from_memento) else {
        return String::new();
    };
    let sections = report_section_counts(report);
    let mut out = String::new();
    let source = plan_body
        .pointer("/planning/source")
        .and_then(Value::as_str)
        .unwrap_or("component-plan");
    out.push_str(&format!("plan: {source}\n"));
    out.push_str("This report was assembled with the use of:\n");
    let plan_atoms = plan_atoms_from_body(plan_body);
    if plan_atoms.is_empty() {
        out.push_str("  - plan memento: pinned, but PlanAtom details are available only by resolving catalog atoms\n");
    } else {
        for atom in plan_atoms {
            out.push_str(&format!("  - {}\n", format_plan_atom_roll_call(atom)));
        }
    }
    out.push_str(&format!(
        "report sections: unit test facts={}, body universes={}, factory report={}, call edges total={}, call edges resolved={}, call edges dangling={}, implications={}, vendor conjoins={}, source mementos={}\n",
        sections.unit_test_facts,
        sections.body_universes,
        sections.factory_report,
        sections.call_edges_total,
        sections.call_edges_resolved,
        sections.call_edges_dangling,
        sections.implications,
        sections.vendor_conjoins,
        sections.source_mementos,
    ));
    out
}

fn assembly_plan_json_value(report: &LiftSourceReport) -> Option<Value> {
    let plan_body = report
        .plan_mementos
        .iter()
        .find_map(plan_body_from_memento)?;
    let sections = report_section_counts(report);
    Some(serde_json::json!({
        "source": plan_body
            .pointer("/planning/source")
            .and_then(Value::as_str)
            .unwrap_or("component-plan"),
        "planMementos": report.plan_mementos.len(),
        "planAtoms": plan_body
            .get("planAtoms")
            .or_else(|| plan_body.get("plan_atoms"))
            .cloned()
            .unwrap_or_else(|| Value::Array(Vec::new())),
        "expectedOutputCids": plan_body
            .get("expectedOutputCids")
            .or_else(|| plan_body.get("expected_output_cids"))
            .cloned()
            .unwrap_or_else(|| Value::Array(Vec::new())),
        "reportSections": {
            "unitTestFacts": sections.unit_test_facts,
            "bodyUniverses": sections.body_universes,
            "factoryReport": sections.factory_report,
            "callEdgesTotal": sections.call_edges_total,
            "callEdgesResolved": sections.call_edges_resolved,
            "callEdgesDangling": sections.call_edges_dangling,
            "implications": sections.implications,
            "vendorConjoins": sections.vendor_conjoins,
            "sourceMementos": sections.source_mementos,
        },
    }))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ReportSectionCounts {
    unit_test_facts: usize,
    body_universes: usize,
    factory_report: usize,
    call_edges_total: usize,
    call_edges_resolved: usize,
    call_edges_dangling: usize,
    implications: usize,
    vendor_conjoins: usize,
    source_mementos: usize,
}

fn report_section_counts(report: &LiftSourceReport) -> ReportSectionCounts {
    let call_edges_total = report
        .call_edges
        .iter()
        .filter(|edge| report_call_edge_kind(edge) == Some("call-edge"))
        .count();
    let call_edges_resolved = report
        .call_edges
        .iter()
        .filter(|edge| {
            report_call_edge_kind(edge) == Some("call-edge")
                && report_call_edge_target_cid(edge).is_some()
        })
        .count();
    let implications = report
        .call_edges
        .iter()
        .filter(|edge| report_call_edge_kind(edge) == Some("implication"))
        .count();
    ReportSectionCounts {
        unit_test_facts: report_unit_test_fact_count(report),
        body_universes: report.contracts.len(),
        factory_report: report.factory_audits.len() + report.factory_walk.len(),
        call_edges_total,
        call_edges_resolved,
        call_edges_dangling: call_edges_total.saturating_sub(call_edges_resolved),
        implications,
        vendor_conjoins: report.vendor_conjoins.len(),
        source_mementos: report.source_mementos.len(),
    }
}

fn report_call_edge_kind(edge: &Value) -> Option<&str> {
    edge.get("kind").and_then(Value::as_str)
}

fn report_call_edge_target_cid(edge: &Value) -> Option<&str> {
    edge.get("targetContractCid")
        .or_else(|| edge.get("target_contract_cid"))
        .and_then(Value::as_str)
        .filter(|cid| !cid.is_empty())
}

fn plan_body_from_memento(value: &Value) -> Option<&Value> {
    if matches!(Member::from_value(value), Ok(Member::PlanMemento(_))) {
        return value.get("body");
    }
    if value.get("kind").and_then(Value::as_str) == Some("component-plan") {
        return Some(value);
    }
    value
        .get("planMemento")
        .or_else(|| value.get("plan_memento"))
        .filter(|body| body.get("kind").and_then(Value::as_str) == Some("component-plan"))
}

fn plan_atoms_from_body(body: &Value) -> Vec<&Value> {
    body.get("planAtoms")
        .or_else(|| body.get("plan_atoms"))
        .and_then(Value::as_array)
        .map(|atoms| {
            atoms
                .iter()
                .filter(|atom| atom.get("kind").and_then(Value::as_str) == Some("plan-atom"))
                .collect()
        })
        .unwrap_or_default()
}

fn format_plan_atom_roll_call(atom: &Value) -> String {
    let role = atom
        .get("role")
        .and_then(Value::as_str)
        .map(plan_role_label)
        .unwrap_or("component");
    let participation = atom
        .get("participation")
        .and_then(Value::as_str)
        .filter(|participation| *participation != "executed")
        .map(|participation| format!(" ({participation})"))
        .unwrap_or_default();
    let name = atom
        .get("pluginName")
        .or_else(|| atom.get("manifestName"))
        .or_else(|| atom.get("surface"))
        .and_then(Value::as_str)
        .unwrap_or("<unknown>");
    let version = atom
        .get("version")
        .and_then(Value::as_str)
        .filter(|version| !version.is_empty())
        .map(|version| format!(" v{version}"))
        .unwrap_or_default();
    let binary_cid = atom
        .pointer("/binary/cid")
        .and_then(Value::as_str)
        .map(short_cid)
        .map(|cid| format!(" bin {cid}"))
        .unwrap_or_default();
    let workspace = atom
        .get("workspaceOverride")
        .and_then(Value::as_str)
        .filter(|workspace| !workspace.is_empty())
        .map(|workspace| format!(" workspace {workspace}"))
        .unwrap_or_default();
    format!("{role}{participation}: {name}{version}{binary_cid}{workspace}")
}

fn plan_role_label(role: &str) -> &'static str {
    match role {
        "unit-test-assertions" => "unit test assertions",
        "body-universes" => "body universes",
        "implications" => "implications",
        "factory-report" => "factory report",
        "witness-oracle" => "witness oracle",
        "proofir-compiler" => "ProofIR compiler",
        "source-oracle" => "source oracle",
        _ => "component",
    }
}

fn short_cid(cid: &str) -> String {
    if let Some(rest) = sugar_canonicalizer::cid_hex(cid) {
        let short: String = rest.chars().take(12).collect();
        return format!("blake3-512:{short}");
    }
    cid.to_string()
}

/// #3766 named terminal: THE ONE DOOR TEST is a raw `git clone <vendor>; sugar
/// lift`, and a vendor tree with real source but no test corpus checked out
/// (or a corpus the kit could not locate) must never read as exit-0-empty.
/// This is a lift-side TYPED CONDITION -- not `refus*` vocabulary, which is
/// reserved for the verifier's decision-space (see #3632) -- so it names the
/// missing-corpus shape distinctly: `"kind": "no-vendor-test-corpus"`. It
/// fires only when the workspace actually carried real source loci (an empty
/// tree is a different, prior condition) yet zero vendor assertions were
/// observed as facts.
fn no_vendor_test_corpus_condition(
    ledger: &Value,
    assertion_surface_audits: &[Value],
    contracts: &[Value],
) -> Option<Value> {
    let source_loci = source_count(ledger, "source_loci");
    if source_loci <= 0 {
        // No source at all is a prior, differently-named condition; this
        // terminal is specifically "source present, tests absent".
        return None;
    }
    let audit_facts = assertion_surface_audits
        .iter()
        .map(assertion_surface_fact_count)
        .sum::<usize>();
    let contract_facts = contracts
        .iter()
        .filter(|contract| contract_inv_is_observed_fact(contract))
        .count();
    if audit_facts.max(contract_facts) > 0 {
        return None;
    }
    Some(serde_json::json!({
        "kind": "no-vendor-test-corpus",
        "level": "error",
        "message": format!(
            "no vendor test corpus in workspace: {source_loci} source loci lifted but zero vendor test assertions were observed as facts. This tree either lacks its test suite (a bare `pip install`/wheel checkout, or a source clone missing the tests/ directory) or the kit could not locate one. Vendor tests ARE the spec; clone the vendor source WITH its test corpus (`git clone <vendor>` at the release tag, not just the installed package) and re-run."
        ),
    }))
}

fn report_unit_test_fact_count(report: &LiftSourceReport) -> usize {
    let audit_facts = report
        .assertion_surface_audits
        .iter()
        .map(assertion_surface_fact_count)
        .sum::<usize>();
    let contract_facts = report
        .contracts
        .iter()
        .filter(|contract| contract_inv_is_observed_fact(contract))
        .count();
    audit_facts.max(contract_facts)
}

/// Human render of #4013 dual-axis lift coverage (majority / minority diverge).
fn render_lift_coverage_human(coverage: &Value) -> String {
    let mut out = String::new();
    let totals = coverage.get("totals").cloned().unwrap_or(Value::Null);
    let majority = coverage.get("majority").cloned().unwrap_or(Value::Null);
    let minority = coverage.get("minority").cloned().unwrap_or(Value::Null);
    let maj_stated = totals
        .get("majority_stated")
        .and_then(Value::as_u64)
        .or_else(|| majority.get("stated").and_then(Value::as_u64))
        .unwrap_or(0);
    let maj_accounted = totals
        .get("majority_accounted")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let maj_silent = totals
        .get("majority_silently_unaccounted")
        .and_then(Value::as_u64)
        .or_else(|| majority.get("silently_unaccounted").and_then(Value::as_u64))
        .unwrap_or(0);
    let min_present = totals
        .get("minority_present")
        .and_then(Value::as_u64)
        .or_else(|| minority.get("present").and_then(Value::as_u64))
        .unwrap_or(0);
    let min_dug = totals
        .get("minority_dug")
        .and_then(Value::as_u64)
        .or_else(|| minority.get("dug").and_then(Value::as_u64))
        .unwrap_or(0);
    let min_un = totals
        .get("minority_un_asserted")
        .and_then(Value::as_u64)
        .or_else(|| minority.get("un_asserted").and_then(Value::as_u64))
        .unwrap_or(0);
    out.push_str(&format!(
        "lift coverage (majority assertions): stated={maj_stated} accounted={maj_accounted} silently_unaccounted={maj_silent}\n"
    ));
    if maj_silent > 0 {
        out.push_str("  MAJORITY SILENT RESIDUE (RED — lifter walked past these asserts):\n");
        if let Some(silent) = majority.get("silent_loci").and_then(Value::as_array) {
            for locus in silent.iter().take(32) {
                let file = locus.get("file").and_then(Value::as_str).unwrap_or("?");
                let line = locus.get("line").and_then(Value::as_u64).unwrap_or(0);
                let preview = locus.get("preview").and_then(Value::as_str).unwrap_or("");
                out.push_str(&format!("    - {file}:{line}  {preview}\n"));
            }
            if silent.len() > 32 {
                out.push_str(&format!("    (+{} more)\n", silent.len() - 32));
            }
        }
    }
    out.push_str(&format!(
        "lift coverage (minority bodies): present={min_present} dug={min_dug} un_asserted={min_un}  [scope report — not a red gate]\n"
    ));
    if min_un > 0 {
        out.push_str("  minority un-asserted bodies (no claim targets these — visible scope):\n");
        if let Some(un) = minority.get("un_asserted_loci").and_then(Value::as_array) {
            for locus in un.iter().take(16) {
                let file = locus.get("file").and_then(Value::as_str).unwrap_or("?");
                let line = locus.get("line").and_then(Value::as_u64).unwrap_or(0);
                let name = locus.get("qualname").or_else(|| locus.get("name")).and_then(Value::as_str).unwrap_or("?");
                out.push_str(&format!("    - {file}:{line}  {name}\n"));
            }
            if un.len() > 16 {
                out.push_str(&format!("    (+{} more)\n", un.len() - 16));
            }
        }
    }
    out
}

fn render_source_report_human(report: &LiftSourceReport) -> String {
    trace_lift_source_report("render_source_report_human.start", report);
    let mut out = String::new();
    out.push_str(&render_report_plan_roll_call(report));
    for diagnostic in &report.diagnostics {
        if diagnostic.get("kind").and_then(Value::as_str) == Some("no-vendor-test-corpus") {
            if let Some(message) = diagnostic.get("message").and_then(Value::as_str) {
                out.push_str(&format!(
                    "NAMED CONDITION [no-vendor-test-corpus]: {message}\n"
                ));
            }
        }
    }
    out.push_str(&format!(
        "source audit: {}\n",
        format_counts(&report.ledger)
    ));
    if let Some(coverage) = &report.lift_coverage {
        out.push_str(&render_lift_coverage_human(coverage));
    }
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
    if report.audits.is_empty() && report.contracts.is_empty() && report.source_mementos.is_empty()
    {
        out.push_str("no source audits emitted\n");
        trace_lift_render_checkpoint("render_source_report_human.end", out.len());
        return out;
    }
    if report.audits.is_empty() {
        out.push_str("no source audits emitted\n");
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
        let body_contracts = group_contracts
            .iter()
            .copied()
            .filter(|contract| !contract_inv_is_observed_fact(contract))
            .collect::<Vec<_>>();
        let case_warranting_facts = if body_contracts.is_empty() {
            Vec::new()
        } else {
            warranting_fact_rows_for_contracts(report, &body_contracts)
        };
        let case_downstream_edges = if body_contracts.is_empty() {
            Vec::new()
        } else {
            downstream_call_edges_for_contracts(&report.call_edges, &body_contracts)
        };
        let forensic_case = !body_contracts.is_empty()
            && (!case_warranting_facts.is_empty() || !case_downstream_edges.is_empty());
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
                push_source_resolution_lines(&mut out, memento);
            }
            for fact in &asserted_fact_rows {
                out.push_str(&format!("  - {}\n", fact.row));
                if let Some(source) = fact.source.as_ref() {
                    let render_source =
                        fuller_source_memento_for_report(report, source).unwrap_or(source);
                    let annotations = fact.source_annotations(source_start_line(source));
                    push_source_resolution_lines_with_annotations(
                        &mut out,
                        render_source,
                        &annotations,
                    );
                }
            }
        }
        if forensic_case {
            let universe_rows = body_contracts
                .iter()
                .filter_map(|contract| format_contract_universe_fol(contract))
                .collect::<Vec<_>>();
            if !universe_rows.is_empty() {
                out.push_str("universe under investigation:\n");
                for row in universe_rows {
                    out.push_str(&format!("  - {row}\n"));
                }
            }
            if !case_warranting_facts.is_empty() {
                out.push_str("walk warranted by observed facts:\n");
                let displayed = case_warranting_facts.iter().take(8).collect::<Vec<_>>();
                for fact in displayed {
                    out.push_str(&format!("  - {}\n", fact.row));
                }
                if case_warranting_facts.len() > 8 {
                    out.push_str(&format!(
                        "  - (+{} more observed facts using this universe)\n",
                        case_warranting_facts.len() - 8
                    ));
                }
                out.push_str("known callers of this function:\n");
                for fact in &case_warranting_facts {
                    out.push_str(&format!("  - {}\n", fact.row));
                }
            }
            out.push_str("callsite preconditions depending on this post:\n");
            if case_downstream_edges.is_empty() {
                out.push_str("  - no precondition implication mementos observed in this proof\n");
            } else {
                for edge in &case_downstream_edges {
                    out.push_str(&format!("  - {}\n", format_dependency_edge(edge)));
                }
            }
        }
        let warranted_mementos = group_mementos
            .iter()
            .filter(|memento| !is_fact_source_memento(memento))
            .filter(|memento| {
                !asserted_fact_rows.iter().any(|fact| {
                    fact.source
                        .as_ref()
                        .is_some_and(|source| source == **memento)
                })
            })
            .collect::<Vec<_>>();
        if !warranted_mementos.is_empty() || !group_audits.is_empty() {
            if forensic_case {
                out.push_str("source walk evidence:\n");
            }
            out.push_str("warranted complete walks:\n");
            for memento in warranted_mementos {
                out.push_str(&format!("  - {}\n", format_source_memento_value(memento)));
                let fact_annotations = asserted_fact_rows
                    .iter()
                    .filter(|fact| fact.source.is_none())
                    .filter_map(|fact| fact.source_annotation(source_start_line(memento)))
                    .collect::<Vec<_>>();
                let render_source = if fact_annotations.is_empty() {
                    *memento
                } else {
                    fuller_source_memento_for_report(report, memento).unwrap_or(memento)
                };
                let annotations = if fact_annotations.is_empty() {
                    universe_source_annotations(
                        report,
                        &group_contracts,
                        render_source,
                        source_start_line(render_source),
                    )
                } else {
                    fact_annotations
                };
                push_source_resolution_lines_with_annotations(
                    &mut out,
                    render_source,
                    &annotations,
                );
            }
            for audit in &group_audits {
                out.push_str(&format!("  - {}\n", format_source_memento(audit)));
            }
        }

        if !group_contracts.is_empty() && !forensic_case {
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

fn warranting_fact_rows_for_contracts(
    report: &LiftSourceReport,
    contracts: &[&Value],
) -> Vec<ReportFactRow> {
    let tokens = contract_dependency_tokens_for_contracts(contracts);
    if tokens.is_empty() {
        return Vec::new();
    }
    let mut seen = BTreeSet::new();
    let facts = report
        .contracts
        .iter()
        .filter(|contract| contract_inv_is_observed_fact(contract))
        .filter_map(|contract| format_contract_asserted_fact(report, contract))
        .filter(|fact| fact_row_mentions_any_token(fact, &tokens))
        .filter(|fact| seen.insert(fact.row.clone()))
        .collect::<Vec<_>>();
    let source_backed = facts
        .iter()
        .filter(|fact| fact.source.is_some())
        .cloned()
        .collect::<Vec<_>>();
    let preferred = if source_backed.is_empty() {
        facts
    } else {
        source_backed
    };
    let non_internal = preferred
        .iter()
        .filter(|fact| !fact.row.contains("method:unwrap#panic_callsite"))
        .cloned()
        .collect::<Vec<_>>();
    if non_internal.is_empty() {
        preferred
    } else {
        non_internal
    }
}

fn contract_dependency_tokens_for_contracts(contracts: &[&Value]) -> Vec<String> {
    let mut tokens = BTreeSet::new();
    for contract in contracts {
        if let Some(name) = contract_value_name(contract) {
            for token in contract_dependency_tokens(name) {
                tokens.insert(token);
            }
        }
    }
    tokens.into_iter().collect()
}

fn contract_dependency_tokens(name: &str) -> Vec<String> {
    let mut tokens = BTreeSet::new();
    push_contract_dependency_token(&mut tokens, name);
    if let Some(owner) = owning_source_function_name(name) {
        push_contract_dependency_token(&mut tokens, &owner);
    }
    if let Some(stripped) = name.strip_prefix("rust-source::") {
        push_contract_dependency_token(&mut tokens, stripped);
    }
    let base = name.split('#').next().unwrap_or(name);
    push_contract_dependency_token(&mut tokens, base);
    if let Some(last) = base.rsplit("::").next() {
        if !(last == "callable" && base.ends_with("::callable")) {
            push_contract_dependency_token(&mut tokens, last);
        }
    }
    if let Some(method) = base.strip_prefix("method:") {
        push_contract_dependency_token(&mut tokens, method);
    }
    if let Some(call) = base.strip_prefix("call:") {
        push_contract_dependency_token(&mut tokens, call);
    }
    tokens.into_iter().collect()
}

fn push_contract_dependency_token(tokens: &mut BTreeSet<String>, token: &str) {
    let token = token.trim();
    if token.len() >= 3 && token != "<unknown contract>" {
        tokens.insert(token.to_string());
    }
}

fn fact_row_mentions_any_token(fact: &ReportFactRow, tokens: &[String]) -> bool {
    tokens.iter().any(|token| {
        fact.row.contains(&format!("call:{token}"))
            || fact.row.contains(&format!("method:{token}"))
            || fact.row.contains(&format!("{token}#"))
            || fact.row.contains(&format!("::{token}"))
            || fact.row.contains(&format!("{token}("))
            || (token.contains("::") && fact.row.contains(token))
    })
}

fn downstream_call_edges_for_contracts(edges: &[Value], contracts: &[&Value]) -> Vec<Value> {
    let mut out = Vec::new();
    let mut seen = BTreeSet::new();
    for edge in edges {
        let Some(source) =
            report_text_field(edge, &["sourceContract", "source_contract", "antecedent"])
        else {
            continue;
        };
        if !contracts
            .iter()
            .filter_map(|contract| contract_value_name(contract))
            .any(|name| edge_source_matches_contract(&source, name))
        {
            continue;
        }
        let formatted = format_dependency_edge(edge);
        if seen.insert(formatted) {
            out.push(edge.clone());
        }
    }
    out
}

fn edge_source_matches_contract(edge_source: &str, contract_name: &str) -> bool {
    if edge_source == contract_name
        || report_contract_group_key(edge_source) == report_contract_group_key(contract_name)
    {
        return true;
    }
    contract_dependency_tokens(contract_name)
        .iter()
        .any(|token| edge_source == token || edge_source.ends_with(&format!("::{token}")))
}

fn format_dependency_edge(edge: &Value) -> String {
    let source = report_text_field(edge, &["sourceContract", "source_contract", "antecedent"])
        .unwrap_or_else(|| "<unknown source contract>".to_string());
    let source_slot = report_text_field(
        edge,
        &[
            "sourceSlot",
            "source_slot",
            "antecedentSlot",
            "antecedent_slot",
        ],
    )
    .unwrap_or_else(|| "post".to_string());
    let target = report_text_field(edge, &["targetContract", "target_contract", "consequent"])
        .unwrap_or_else(|| "<unknown target contract>".to_string());
    let target_slot = report_text_field(
        edge,
        &[
            "targetSlot",
            "target_slot",
            "consequentSlot",
            "consequent_slot",
        ],
    )
    .unwrap_or_else(|| "pre".to_string());
    let target_symbol = report_text_field(edge, &["targetSymbol", "target_symbol"])
        .unwrap_or_else(|| target.clone());
    let mut row = format!("{source}.{source_slot}");
    if let Some(postcondition) = report_text_field(
        edge,
        &[
            "postcondition",
            "sourcePostcondition",
            "source_postcondition",
        ],
    ) {
        row.push_str(&format!(" [post: {postcondition}]"));
    }
    row.push_str(&format!(" -> {target}.{target_slot}"));
    if !target_symbol.is_empty() && target_symbol != "<unknown target symbol>" {
        row.push_str(&format!(" via {target_symbol}"));
    }
    if let Some(precondition) = report_text_field(
        edge,
        &[
            "precondition",
            "specializedPrecondition",
            "specialized_precondition",
        ],
    ) {
        row.push_str(&format!(" [pre: {precondition}]"));
    }
    if let Some(prover) = report_text_field(edge, &["prover"]) {
        row.push_str(&format!(" ({prover})"));
    }
    row
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
        || report.diagnostics.iter().any(|diagnostic| {
            diagnostic.get("kind").and_then(Value::as_str) == Some("no-vendor-test-corpus")
        })
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
        "boundary" => 1,
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
        // Generic rust-lifter boundary, plus the python factory-walk kit's
        // typed-effect family (#3632 batch 6): all are a named lift-side
        // boundary, not a verifier refusal. Collapsed to one display bucket.
        Some("boundary")
        | Some("raise-effect")
        | Some("runtime-effect")
        | Some("coverage-gap")
        | Some("factory-gap")
        | Some("dig-boundary")
        | Some("absent")
        | Some("drifted") => "boundary",
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
                        .map(|fact| fact.row)
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
        "loci={} warranted={} inactive={} support={} boundary={} unresolved={}",
        source_count(value, "source_loci"),
        source_count(value, "source_warranted"),
        source_count(value, "source_inactive"),
        source_count(value, "source_support"),
        source_count(value, "source_boundary"),
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
        "factory accounting: sites={} warranted={} incomplete={} support={} unresolved={}\n",
        factory_audits.len(),
        counts.get("warranted").copied().unwrap_or(0),
        counts.get("boundary").copied().unwrap_or(0),
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

    for status in ["unresolved", "boundary", "support", "warranted"] {
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
        let heading = if status == "boundary" {
            "factory boundaries"
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
        "boundary" => 1,
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
                == "boundary"
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
    contract
        .get("name")
        .or_else(|| contract.get("fnName"))
        .or_else(|| contract.get("fn_name"))
        .and_then(Value::as_str)
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

#[derive(Debug, Clone, PartialEq, Eq)]
struct ReportSourceAnnotation {
    line: u64,
    label: String,
}

#[derive(Debug, Clone, PartialEq)]
struct ReportFactRow {
    row: String,
    source: Option<Value>,
    predicate: String,
    annotation_line: Option<u64>,
}

impl ReportFactRow {
    fn source_annotation(&self, fallback_line: Option<u64>) -> Option<ReportSourceAnnotation> {
        let line = self.annotation_line.or(fallback_line)?;
        Some(ReportSourceAnnotation {
            line,
            label: format!("FACT ⊢ {}", self.predicate),
        })
    }

    fn source_annotations(&self, fallback_line: Option<u64>) -> Vec<ReportSourceAnnotation> {
        self.source_annotation(fallback_line).into_iter().collect()
    }
}

fn format_source_resolution_line_with_annotations(
    source: &Value,
    annotations: &[ReportSourceAnnotation],
) -> String {
    let Some(oracle) = source.get("sourceOracle") else {
        return format_source_not_present(source);
    };
    let status = oracle
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("absent");
    if status == "resolved" {
        if let Some(lines) = source_oracle_lines_from_value(oracle) {
            let text = render_source_oracle_lines_with_annotations(&lines, annotations);
            return format!("source present:\n{}", indent_block(text.trim_end(), 6));
        }
        if let Some(text) = oracle.get("source").and_then(Value::as_str) {
            return format!("source present:\n{}", indent_block(text.trim(), 6));
        }
        if let Some(display) = oracle.get("display").and_then(Value::as_str) {
            return format!("source present: {display}");
        }
    }
    oracle
        .get("display")
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| format_source_not_present(source))
}

fn render_source_oracle_lines_with_annotations(
    lines: &[VisualSourceWalkLine],
    annotations: &[ReportSourceAnnotation],
) -> String {
    lines
        .iter()
        .map(|line| {
            let labels = annotations
                .iter()
                .filter(|annotation| annotation.line == line.line)
                .map(|annotation| annotation.label.as_str())
                .collect::<Vec<_>>();
            if labels.is_empty() {
                line.source.clone()
            } else {
                format!("{}  {}", line.source, labels.join(" ; "))
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn push_source_resolution_lines(out: &mut String, source: &Value) {
    push_source_resolution_lines_with_annotations(out, source, &[]);
}

fn push_source_resolution_lines_with_annotations(
    out: &mut String,
    source: &Value,
    annotations: &[ReportSourceAnnotation],
) {
    for line in format_source_resolution_line_with_annotations(source, annotations).lines() {
        out.push_str("    ");
        out.push_str(line);
        out.push('\n');
    }
}

fn indent_block(text: &str, spaces: usize) -> String {
    let prefix = " ".repeat(spaces);
    text.lines()
        .map(|line| format!("{prefix}{line}"))
        .collect::<Vec<_>>()
        .join("\n")
}

fn format_source_not_present(source: &Value) -> String {
    let file = source
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown file>");
    let span = source.get("span");
    let line = span
        .and_then(|span| span.get("start_line"))
        .and_then(Value::as_i64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let col = span
        .and_then(|span| span.get("start_col"))
        .and_then(Value::as_i64)
        .map(|col| col.to_string())
        .unwrap_or_else(|| "?".to_string());
    let cid = source
        .get("source_cid")
        .or_else(|| source.get("sourceCid"))
        .and_then(Value::as_str)
        .unwrap_or("<missing source cid>");
    format!("source not present, file {file} line {line} col {col} cid {cid}")
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

fn format_contract_asserted_fact(
    report: &LiftSourceReport,
    contract: &Value,
) -> Option<ReportFactRow> {
    if !contract_inv_is_observed_fact(contract) {
        return None;
    }
    let name = contract_value_name(contract).unwrap_or("<unknown contract>");
    let rendered = contract
        .get("inv")
        .map(proofir_formula_to_fol_with_instances)?;
    let mut row = format!("{name} :: {rendered}");
    let source = contract_source_warrant(contract)
        .or_else(|| fact_source_memento_for_contract(report, name))
        .cloned();
    if let Some(source) = source.as_ref() {
        row.push_str(" @ ");
        row.push_str(&format_fact_source_memento_ref(source));
    } else if let Some(locus) = source_locus_for_contract(report, name) {
        row.push_str(" @ ");
        row.push_str(&format_fact_source_locus_ref(locus));
    }
    let annotation_line = source.as_ref().and_then(source_start_line);
    Some(ReportFactRow {
        row,
        source,
        predicate: rendered,
        annotation_line,
    })
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

fn source_start_line(source: &Value) -> Option<u64> {
    source
        .get("span")
        .and_then(|span| span.get("start_line"))
        .and_then(Value::as_u64)
}

fn source_end_line(source: &Value) -> Option<u64> {
    source
        .get("span")
        .and_then(|span| span.get("end_line"))
        .and_then(Value::as_u64)
}

fn source_file(source: &Value) -> Option<&str> {
    source.get("file").and_then(Value::as_str)
}

fn fuller_source_memento_for_report<'a>(
    report: &'a LiftSourceReport,
    source: &Value,
) -> Option<&'a Value> {
    let file = source_file(source)?;
    let function = source_function_name(source)?;
    let start = source_start_line(source).unwrap_or(0);
    let end = source_end_line(source).unwrap_or(start);
    report
        .source_mementos
        .iter()
        .filter(|candidate| source_file(candidate) == Some(file))
        .filter(|candidate| source_function_name(candidate) == Some(function))
        .filter(|candidate| {
            let candidate_start = source_start_line(candidate).unwrap_or(u64::MAX);
            let candidate_end = source_end_line(candidate).unwrap_or(candidate_start);
            candidate_start <= start && candidate_end >= end
        })
        .max_by_key(|candidate| {
            let candidate_start = source_start_line(candidate).unwrap_or(0);
            let candidate_end = source_end_line(candidate).unwrap_or(candidate_start);
            candidate_end.saturating_sub(candidate_start)
        })
}

fn universe_source_annotations(
    report: &LiftSourceReport,
    contracts: &[&Value],
    source: &Value,
    fallback_line: Option<u64>,
) -> Vec<ReportSourceAnnotation> {
    let body_contracts = contracts
        .iter()
        .copied()
        .filter(|contract| !contract_inv_is_observed_fact(contract))
        .collect::<Vec<_>>();
    if body_contracts.is_empty() {
        return Vec::new();
    }
    let context = source_memento_context_key(source);
    if factory_walk_context_has_incomplete_boundary(&report.factory_walk, &context) {
        return Vec::new();
    }
    let factory_annotations = universe_factory_source_annotations(&report.factory_walk, &context);
    if !factory_annotations.is_empty() {
        return factory_annotations;
    }
    let Some(line) = fallback_line else {
        return Vec::new();
    };
    body_contracts
        .iter()
        .flat_map(|contract| contract_predicate_rows(contract))
        .map(|predicate| ReportSourceAnnotation {
            line,
            label: format!("UNIVERSE ⊢ {predicate}"),
        })
        .collect()
}

fn universe_factory_source_annotations(
    factory_walk: &[Value],
    context: &str,
) -> Vec<ReportSourceAnnotation> {
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
            if row
                .get("verdict")
                .and_then(Value::as_str)
                .is_some_and(|verdict| verdict != "complete")
            {
                return None;
            }
            let line = memento
                .get("span")
                .map(source_span_sort_key)
                .unwrap_or_default()
                .0;
            if line == 0 {
                return None;
            }
            let formula = row
                .get("emittedFormula")
                .or_else(|| row.get("emitted_formula"))
                .or_else(|| row.get("formula"))?;
            Some(ReportSourceAnnotation {
                line,
                label: format!(
                    "UNIVERSE ⊢ {}",
                    proofir_formula_to_fol_with_instances(formula)
                ),
            })
        })
        .collect()
}

fn factory_walk_context_has_incomplete_boundary(factory_walk: &[Value], context: &str) -> bool {
    factory_walk.iter().any(|row| {
        let Some(memento) = row.get("sourceMemento") else {
            return false;
        };
        if source_memento_context_key(memento) != context {
            return false;
        }
        let status = normalized_source_status(row.get("status").and_then(Value::as_str));
        let verdict = if status == "unresolved" {
            "gap"
        } else {
            row.get("verdict")
                .and_then(Value::as_str)
                .unwrap_or("incomplete")
        };
        verdict != "complete"
    })
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

fn fact_source_memento_for_contract<'a>(
    report: &'a LiftSourceReport,
    contract_name: &str,
) -> Option<&'a Value> {
    if let Some(exact) = report
        .source_mementos
        .iter()
        .filter(|memento| source_memento_names_contract(memento, contract_name))
        .min_by_key(|memento| source_memento_span_width(memento))
    {
        return Some(exact);
    }

    let owner = owning_source_function_name(contract_name);
    if let Some(owner) = owner.as_deref() {
        if let Some(memento) = report
            .source_mementos
            .iter()
            .filter(|memento| {
                source_function_name(memento)
                    .is_some_and(|name| source_function_name_matches_owner(name, owner))
            })
            .min_by_key(|memento| source_memento_span_width(memento))
        {
            return Some(memento);
        }
    }

    report
        .source_mementos
        .iter()
        .filter(|memento| {
            source_function_name(memento)
                .is_some_and(|name| contract_name_matches_source_function(contract_name, name))
        })
        .min_by_key(|memento| source_memento_span_width(memento))
}

fn source_memento_names_contract(memento: &Value, contract_name: &str) -> bool {
    ["contractName", "contract_name", "claimName", "claim_name"]
        .into_iter()
        .any(|field| {
            memento
                .get(field)
                .and_then(Value::as_str)
                .is_some_and(|value| value == contract_name)
        })
}

fn source_memento_span_width(memento: &Value) -> (u64, u64) {
    let start = source_start_line(memento).unwrap_or(u64::MAX);
    let end = source_end_line(memento).unwrap_or(start);
    (end.saturating_sub(start), start)
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

// ProofIR -> FOL renderer family lives in sugar-verifier (moved 2026-07-07,
// part of #3774): the daemon's proveConsistency RPC and this CLI binary
// call the SAME renderer, never a second copy. Re-export so every existing
// unqualified call site in this file (and its test module) keeps compiling.
pub(crate) use sugar_verifier::fol_render::*;

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
    use sugar_verifier::{CallSite, MementoCid, ObligationVerdict, Report, ReportRow};
    use syn::spanned::Spanned;

    fn test_memento_cid(label: &str) -> MementoCid {
        MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(label.as_bytes()))
            .expect("test CID must parse")
    }

    fn insert_unanchored_test_member(
        pool: &mut sugar_verifier::types::MementoPool,
        cid: MementoCid,
        envelope: serde_json::Value,
    ) {
        if matches!(
            sugar_proof_envelope::member_kind(&envelope),
            Ok(MemberKind::Contract)
        ) {
            if let Some(name) = sugar_proof_envelope::member_field(&envelope, "contractName")
                .or_else(|| sugar_proof_envelope::member_field(&envelope, "name"))
                .and_then(|v| v.as_str())
                .map(str::to_string)
            {
                pool.cid_to_name.insert(cid.clone(), name.clone());
                pool.name_to_cid.insert(name.clone(), cid.clone());
                if let Some(body_cid) = sugar_proof_envelope::member_field(&envelope, "bodyCid")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty())
                    .and_then(|raw| {
                        sugar_verifier::ContractBodyCid::try_parse(raw.to_string()).ok()
                    })
                {
                    pool.name_to_body_cid.insert(name, body_cid);
                }
            }
        }
        let member = sugar_verifier::StoredMember::from_envelope(cid.clone(), &envelope)
            .expect("test member must parse");
        pool.mementos.insert(cid, member);
    }

    fn minimal_source_report() -> LiftSourceReport {
        LiftSourceReport {
            ledger: serde_json::json!({
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_boundary": 0,
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
            diagnostics: vec![],
            source_mementos: vec![],
            plan_mementos: vec![],
            contracts: vec![],
            call_edges: vec![],
            vendor_conjoins: vec![],
            project_root: None,
            source_oracle_routes: Vec::new(),
            lift_coverage: None,
        }
    }

    fn stamp_source_oracles(value: &mut Value, source_text: &str) {
        match value {
            Value::Object(object) => {
                let is_source_memento = object.contains_key("file") && object.contains_key("span");
                if is_source_memento && !object.contains_key("sourceOracle") {
                    if let Some(lines) = source_lines_json_for_memento_object(object, source_text) {
                        object.insert(
                            "sourceOracle".to_string(),
                            serde_json::json!({
                                "status": "resolved",
                                "sourceLines": lines,
                                "display": "source present",
                            }),
                        );
                    }
                }
                for child in object.values_mut() {
                    stamp_source_oracles(child, source_text);
                }
            }
            Value::Array(values) => {
                for child in values {
                    stamp_source_oracles(child, source_text);
                }
            }
            _ => {}
        }
    }

    fn source_lines_json_for_memento_object(
        object: &Map<String, Value>,
        source_text: &str,
    ) -> Option<Value> {
        let span = object.get("span")?;
        let start_line = span.get("start_line").and_then(Value::as_u64)? as usize;
        let end_line = span
            .get("end_line")
            .and_then(Value::as_u64)
            .unwrap_or(start_line as u64) as usize;
        let lines = source_text.lines().collect::<Vec<_>>();
        let start = start_line.checked_sub(1)?;
        let selected = lines.get(start..end_line.max(start_line))?;
        Some(Value::Array(
            selected
                .iter()
                .enumerate()
                .map(|(offset, source)| {
                    serde_json::json!({
                        "line": start_line + offset,
                        "source": source.trim_end(),
                    })
                })
                .collect(),
        ))
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
            status: ObligationVerdict::Discharged,
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
                "source_boundary": 22,
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
                        "source_boundary": 21,
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
                        "source_boundary": 1,
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
            allow_failed_components: false,
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
            ComponentPlanOptions::default(),
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
        assert_eq!(report.ledger["source_boundary"], 1);
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
        // bound swaps the whole response for a `sugar-bound-exceeded` marker, the source-audit
        // gate must fail LOUDLY naming the clip -- never the generic "missing sourceLedger"
        // (which hides the cause and reads like a kit bug) and never a silent empty
        // headline. A blind aggregate ledger cannot catch a false discharge.
        let refused = serde_json::json!({
            "sugar-bound-exceeded": "response-term-exceeds-byte-bound",
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
            "source audit: loci=29 warranted=15 inactive=13 support=0 boundary=1 unresolved=0"
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
                "source_boundary": 0,
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
                        "source_boundary": 0,
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
            "source audit: loci=3 warranted=1 inactive=0 support=2 boundary=0 unresolved=0"
        ));
        assert!(human
            .contains("totals: loci=3 warranted=1 inactive=0 support=2 boundary=0 unresolved=0"));
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
                "source_boundary": 0,
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
                        "source_boundary": 0,
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
            "source audit: loci=1 warranted=0 inactive=0 support=0 boundary=0 unresolved=1"
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
                "source_boundary": 0,
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
                "source_boundary": 0,
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
                        "source_boundary": 0,
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
                "source_boundary": 0,
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
                        "source_boundary": 0,
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
            "source audit: loci=5 warranted=1 inactive=0 support=1 boundary=0 unresolved=3"
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
                "source_boundary": 0,
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
                        "source_boundary": 0,
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
                "source_boundary": 0,
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
                        "source_boundary": 0,
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
            "∀ x:Int. (x ≥ 0 ∧ x < 10) ⇒ encode(x) = \"baz\""
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
            "str.eq-bv-blocks(encodeBase64String(\"foo\"), base64.blocks(input=[102, 111, 111], chars=[((bits >>> 18) & 63)], table=\"ABC+/\"))"
        );
    }

    #[test]
    fn proofir_fol_printer_summarizes_general_bv_blocks_payloads() {
        let formula = serde_json::json!({
            "kind": "atomic",
            "name": "str.eq-bv-blocks",
            "args": [
                {"kind": "var", "name": "out"},
                {"kind": "var", "name": "value"},
                {
                    "kind": "const",
                    "value": "{\"per_char\":[{\"args\":[{\"kind\":\"var\",\"name\":\"byte_value_0\"},{\"kind\":\"const\",\"sort\":{\"kind\":\"primitive\",\"name\":\"Int\"},\"value\":15}],\"kind\":\"ctor\",\"name\":\"bv32.and\"}],\"table\":[65,66,67],\"vars\":[\"byte_value_0\"]}",
                    "sort": {"kind": "primitive", "name": "String"}
                }
            ]
        });

        let rendered = proofir_formula_to_fol(&formula);

        assert_eq!(
            rendered,
            "str.eq-bv-blocks(out, base64.blocks(input=value, chars=[(byte_value_0 & 15)], table=\"ABC\"))"
        );
        assert!(
            !rendered.contains("\"per_char\"") && !rendered.contains("\"kind\""),
            "general encoder visual FOL must not leak serialized payload JSON: {rendered}"
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
                "source_boundary": 0,
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
                        "source_boundary": 0,
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
        assert!(human.contains("encodeBase64String(bytes(b0, b1, b2))"));
        assert!(human.contains("instantiated FOL:"));
        assert!(human.contains(
            "b0=102, b1=111, b2=111 ⊢ str.eq-bv-blocks(encodeBase64String(\"foo\")"
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
    fn full_report_renders_plan_roll_call_first() {
        let mut report = minimal_source_report();
        report.assertion_surface_audits = vec![serde_json::json!({
            "contract": "src/lib.rs::tests::encode_base64_len",
            "facts": ["call:encodeBase64(bytes) = out"]
        })];
        report.factory_audits = vec![serde_json::json!({"kind": "factory-audit"})];
        report.factory_walk = vec![serde_json::json!({
            "kind": "factory-walk",
            "status": "warranted",
            "verdict": "complete"
        })];
        report.contracts = vec![serde_json::json!({
            "kind": "contract",
            "name": "encode_len",
            "post": {"kind": "atomic", "name": "=", "args": [{"kind": "var", "name": "out"}, {"kind": "var", "name": "expected"}]}
        })];
        report.call_edges = vec![serde_json::json!({
            "sourceContract": "src/lib.rs::tests::encode_base64_len",
            "targetSymbol": "encode_len",
            "targetContract": "encode_len"
        })];
        report.source_mementos = vec![serde_json::json!({
            "kind": "source-memento",
            "role": "rust-source-universe",
            "contractName": "encode_len",
            "file": "vendor/base64-0.22.1/src/encode.rs"
        })];
        report.plan_mementos = vec![serde_json::json!({
            "kind": "component-plan",
            "schemaVersion": "1",
            "workspaceRoot": "/workspace",
            "planning": {"source": "component-discovery"},
            "expectedOutputCids": [format!("blake3-512:{}", "a".repeat(128))],
            "planAtoms": [
                {
                    "kind": "plan-atom",
                    "schemaVersion": "1",
                    "atomKind": "lifter-binary",
                    "role": "unit-test-assertions",
                    "surface": "rust-test-assertions",
                    "pluginName": "rust-test-assertions-lift",
                    "version": "0.1.0",
                    "binary": {"path": "/bin/rust_test_assertions_rpc", "cid": format!("blake3-512:{}", "b".repeat(128))}
                },
                {
                    "kind": "plan-atom",
                    "schemaVersion": "1",
                    "atomKind": "lifter-binary",
                    "role": "body-universes",
                    "surface": "rust-fn-contracts",
                    "pluginName": "rust-fn-contracts-lift",
                    "version": "0.1.0",
                    "workspaceOverride": "vendor/base64-0.22.1",
                    "binary": {"path": "/bin/sugar-walk-rpc", "cid": format!("blake3-512:{}", "c".repeat(128))}
                },
                {
                    "kind": "plan-atom",
                    "schemaVersion": "1",
                    "atomKind": "lifter-binary",
                    "role": "implications",
                    "surface": "rust-implications",
                    "pluginName": "rust-implications-lift",
                    "version": "0.1.0",
                    "binary": {"path": "/bin/sugar-walk-rpc", "cid": format!("blake3-512:{}", "c".repeat(128))}
                },
                {
                    "kind": "plan-atom",
                    "schemaVersion": "1",
                    "atomKind": "lifter-binary",
                    "role": "witness-oracle",
                    "surface": "rust-cargo-test-witness",
                    "pluginName": "rust-cargo-test-witness-lift",
                    "version": "0.1.0",
                    "binary": {"path": "/bin/witness_rpc", "cid": format!("blake3-512:{}", "d".repeat(128))}
                }
            ]
        })];

        let human = render_source_report_human(&report);
        assert!(
            human.starts_with(
                "plan: component-discovery\nThis report was assembled with the use of:\n"
            ),
            "{human}"
        );
        assert!(
            human.contains("unit test assertions: rust-test-assertions-lift"),
            "{human}"
        );
        assert!(
            human.contains("body universes: rust-fn-contracts-lift"),
            "{human}"
        );
        assert!(
            human.contains("implications: rust-implications-lift"),
            "{human}"
        );
        assert!(
            human.contains("witness oracle: rust-cargo-test-witness-lift"),
            "{human}"
        );
        assert!(human.contains("bin blake3-512:"), "{human}");
        assert!(human.contains("report sections: unit test facts=1, body universes=1, factory report=2, call edges total=0, call edges resolved=0, call edges dangling=0, implications=0, vendor conjoins=0, source mementos=1"), "{human}");

        let rendered_json = render_report_json(&report, None).expect("json report");
        let parsed: serde_json::Value = serde_json::from_str(&rendered_json).expect("valid json");
        assert_eq!(parsed["assemblyPlan"]["source"], "component-discovery");
        assert_eq!(parsed["assemblyPlan"]["reportSections"]["bodyUniverses"], 1);
        assert_eq!(
            parsed["assemblyPlan"]["reportSections"]["callEdgesTotal"],
            0
        );
        assert_eq!(parsed["assemblyPlan"]["reportSections"]["implications"], 0);
        assert_eq!(
            parsed["assemblyPlan"]["planAtoms"][1]["workspaceOverride"],
            "vendor/base64-0.22.1"
        );

        let visual = render_report_visual(&report, None);
        assert!(
            visual.starts_with(
                "plan: component-discovery\nThis report was assembled with the use of:\n"
            ),
            "{visual}"
        );
        assert!(
            visual.contains("unit test assertions: rust-test-assertions-lift"),
            "{visual}"
        );
        assert!(visual.contains("universe visual:"), "{visual}");
    }

    #[test]
    fn proof_only_report_renders_contract_source_and_predicates_without_audits() {
        let mut report = minimal_source_report();
        report.audits = Vec::new();
        report.contracts = vec![serde_json::json!({
            "kind": "contract",
            "name": "encode_len",
            "post": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "out"},
                    {"kind": "ctor", "name": "+", "args": [
                        {"kind": "var", "name": "n"},
                        {"kind": "const", "value": 1, "sort": {"name": "Int"}}
                    ]}
                ]
            }
        })];
        report.source_mementos = vec![serde_json::json!({
            "kind": "source-memento",
            "contractName": "encode_len",
            "file": "src/lib.rs",
            "span": {"start_line": 7, "start_col": 4, "end_line": 9, "end_col": 5},
            "sourceFunctionName": "encode_len",
            "paramNames": ["n"],
            "source_cid": format!("blake3-512:{}", "e".repeat(128)),
            "template_cid": format!("blake3-512:{}", "f".repeat(128)),
        })];

        let human = render_source_report_human(&report);

        assert!(human.contains("no source audits emitted"), "{human}");
        assert!(human.contains("contract: encode_len"), "{human}");
        assert!(human.contains("encode_len :: out = (n + 1)"), "{human}");
        assert!(
            human.contains("source not present, file src/lib.rs line 7 col 4 cid blake3-512:"),
            "{human}"
        );
    }

    #[test]
    fn proof_only_report_rehydrates_implication_edges_as_downstream_dependencies() {
        let mut pool = sugar_verifier::types::MementoPool::default();
        let antecedent_cid = test_memento_cid("antecedent");
        let consequent_cid = test_memento_cid("consequent");
        let implication_cid = test_memento_cid("implication");
        insert_unanchored_test_member(
            &mut pool,
            antecedent_cid.clone(),
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "encoded_len"
                },
                "body": {},
                "schemaVersion": "1"
            }),
        );
        insert_unanchored_test_member(
            &mut pool,
            consequent_cid.clone(),
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "method:checked_add"
                },
                "body": {},
                "schemaVersion": "1"
            }),
        );
        insert_unanchored_test_member(
            &mut pool,
            implication_cid,
            serde_json::json!({
                "header": {
                    "kind": "implication",
                    "antecedentCid": antecedent_cid.to_string(),
                    "consequentCid": consequent_cid.to_string(),
                    "antecedentSlot": "post",
                    "consequentSlot": "pre"
                },
                "metadata": {
                    "prover": "rust-implications",
                    "proofWitness": "rust-call-pre:encoded_len->method:checked_add@src/encode.rs:110:26"
                },
                "schemaVersion": "1"
            }),
        );

        let report = source_report_from_proof_pool(&pool, None);

        assert_eq!(report.call_edges.len(), 1);
        assert_eq!(
            format_dependency_edge(&report.call_edges[0]),
            "encoded_len.post -> method:checked_add.pre via method:checked_add (rust-implications)"
        );
    }

    #[test]
    fn proof_only_forensic_report_lists_known_callers_when_implications_are_absent() {
        let mut pool = sugar_verifier::types::MementoPool::default();
        let encoded_len_cid = test_memento_cid("encoded_len_contract");
        let observed_fact_cid = test_memento_cid("observed_fact");
        let bridge_cid = test_memento_cid("bridge");
        insert_unanchored_test_member(
            &mut pool,
            encoded_len_cid.clone(),
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "encoded_len"
                },
                "body": {
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "ctor", "name": "Some", "args": [{"kind": "var", "name": "complete_chunk_output"}]}
                        ]
                    }
                },
                "schemaVersion": "1"
            }),
        );
        insert_unanchored_test_member(
            &mut pool,
            observed_fact_cid,
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "src/lib.rs::tests::test_encoded_len_unpadded_2_exact_row::encoded_len::assertion"
                },
                "body": {
                    "inv": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "const", "value": 3, "sort": {"name": "Int"}},
                            {"kind": "ctor", "name": "call:encoded_len", "args": [
                                {"kind": "const", "value": 2, "sort": {"name": "Int"}},
                                {"kind": "const", "value": false, "sort": {"name": "Bool"}}
                            ]}
                        ]
                    }
                },
                "schemaVersion": "1"
            }),
        );
        insert_unanchored_test_member(
            &mut pool,
            bridge_cid,
            serde_json::json!({
                "header": {
                    "kind": "bridge",
                    "sourceSymbol": "encoded_len",
                    "sourceLayer": "source",
                    "targetContractCid": encoded_len_cid.to_string(),
                    "targetLayer": "kit"
                },
                "schemaVersion": "1"
            }),
        );

        let report = source_report_from_proof_pool(&pool, Some("encoded_len"));
        let human = render_source_report_human(&report);

        assert!(
            human.contains("  - no precondition implication mementos observed in this proof"),
            "{human}"
        );
        assert!(human.contains("known callers of this function:"), "{human}");
        assert!(
            human.contains("src/lib.rs::tests::test_encoded_len_unpadded_2_exact_row::encoded_len::assertion :: 3 = encoded_len(2, false)"),
            "{human}"
        );
    }

    #[test]
    fn proof_only_forensic_report_reconstructs_callsite_preconditions_from_pool() {
        let mut pool = sugar_verifier::types::MementoPool::default();
        let bundle_cid = test_memento_cid("test_bundle");
        let callee_cid = test_memento_cid("callee_contract");
        let unwrap_cid = test_memento_cid("unwrap_contract");
        let bridge_cid = test_memento_cid("unwrap_bridge");
        let caller_fact_cid = test_memento_cid("caller_fact");

        insert_unanchored_test_member(
            &mut pool,
            callee_cid.clone(),
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "callee"
                },
                "body": {
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "ctor", "name": "Some", "args": [{"kind": "var", "name": "value"}]}
                        ]
                    }
                },
                "schemaVersion": "1"
            }),
        );
        insert_unanchored_test_member(
            &mut pool,
            caller_fact_cid.clone(),
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "src/lib.rs::tests::test_callee_unwrap::callee::assertion"
                },
                "body": {
                    "inv": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "ctor", "name": "method:unwrap", "args": [
                                {"kind": "ctor", "name": "call:callee", "args": [
                                    {"kind": "const", "value": 7, "sort": {"name": "Int"}}
                                ]}
                            ]},
                            {"kind": "const", "value": 11, "sort": {"name": "Int"}}
                        ]
                    }
                },
                "schemaVersion": "1"
            }),
        );
        insert_unanchored_test_member(
            &mut pool,
            unwrap_cid.clone(),
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "method:unwrap"
                },
                "body": {
                    "formals": ["opt"],
                    "formalSorts": [{"kind": "primitive", "name": "Any"}],
                    "pre": {
                        "kind": "atomic",
                        "name": "is_some",
                        "args": [{"kind": "var", "name": "opt"}]
                    }
                },
                "schemaVersion": "1"
            }),
        );
        let bridge = serde_json::json!({
            "header": {
                "kind": "bridge",
                "sourceSymbol": "method:unwrap",
                "sourceLayer": "rust-tests",
                "targetContractCid": unwrap_cid.to_string(),
                "targetLayer": "rust-core"
            },
            "schemaVersion": "1"
        });
        insert_unanchored_test_member(&mut pool, bridge_cid.clone(), bridge.clone());
        pool.bridges_by_symbol
            .insert("method:unwrap".to_string(), bridge_cid.clone());
        pool.bridge_self_bundle_by_symbol
            .insert("method:unwrap".to_string(), bundle_cid.clone());
        pool.bundle_members.entry(bundle_cid).or_default().extend([
            callee_cid,
            unwrap_cid,
            bridge_cid,
            caller_fact_cid,
        ]);

        let report = source_report_from_proof_pool(&pool, Some("callee"));
        let human = render_source_report_human(&report);

        assert!(
            human.contains("callsite preconditions depending on this post:\n  - callee.post [post: result = Some(value)] -> method:unwrap.pre via method:unwrap [pre: is_some(callee(7))]"),
            "{human}"
        );
    }

    #[test]
    fn proof_only_forensic_report_lists_unresolved_callsite_precondition_targets() {
        let mut pool = sugar_verifier::types::MementoPool::default();
        let callee_cid = test_memento_cid("callee_contract");
        let caller_fact_cid = test_memento_cid("caller_fact");
        let bridge_cid = test_memento_cid("unresolved_method_unwrap_bridge");
        insert_unanchored_test_member(
            &mut pool,
            callee_cid,
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "callee"
                },
                "body": {
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "ctor", "name": "Some", "args": [{"kind": "var", "name": "value"}]}
                        ]
                    }
                },
                "schemaVersion": "1"
            }),
        );
        insert_unanchored_test_member(
            &mut pool,
            caller_fact_cid,
            serde_json::json!({
                "header": {
                    "kind": "contract",
                    "contractName": "src/lib.rs::tests::test_callee_unwrap::callee::assertion"
                },
                "body": {
                    "inv": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "ctor", "name": "method:unwrap", "args": [
                                {"kind": "ctor", "name": "call:callee", "args": [
                                    {"kind": "const", "value": 7, "sort": {"name": "Int"}}
                                ]}
                            ]},
                            {"kind": "const", "value": 11, "sort": {"name": "Int"}}
                        ]
                    }
                },
                "schemaVersion": "1"
            }),
        );
        let bridge = serde_json::json!({
            "header": {
                "kind": "bridge",
                "sourceSymbol": "method:unwrap",
                "sourceLayer": "rust-tests",
                "targetLayer": "rust-core"
            },
            "schemaVersion": "1"
        });
        insert_unanchored_test_member(&mut pool, bridge_cid.clone(), bridge.clone());
        pool.insert_bridge_by_symbol("method:unwrap", bridge_cid, bridge);

        let report = source_report_from_proof_pool(&pool, Some("callee"));
        let human = render_source_report_human(&report);

        assert!(
            human.contains("callsite preconditions depending on this post:\n  - callee.post [post: result = Some(value)] -> method:unwrap.pre via method:unwrap [pre: unresolved: NoBridgeTarget: callsite method:unwrap has no targetContractCid]"),
            "{human}"
        );
    }

    #[test]
    fn human_report_renders_full_unit_test_from_source_oracle_with_fact_inline() {
        let mut report = minimal_source_report();
        report.audits = Vec::new();
        report.contracts = vec![serde_json::json!({
            "kind": "contract",
            "name": "src/lib.rs::tests::test_encoded_len_unpadded_2_exact_row::encoded_len#panic_callsite#euf#c:callresult_encoded_len_panic_callsite_a2(i:2,b:false)::assertion",
            "inv": {
                "kind": "not",
                "operands": [{
                    "kind": "atomic",
                    "name": "panic",
                    "args": [{
                        "kind": "ctor",
                        "name": "call:encoded_len#panic_callsite",
                        "args": [
                            {"kind": "const", "value": 2, "sort": {"name": "Int"}},
                            {"kind": "const", "value": false, "sort": {"name": "Bool"}}
                        ]
                    }]
                }]
            }
        })];
        let assertion_source = serde_json::json!({
            "kind": "source-memento",
            "contractName": "src/lib.rs::tests::test_encoded_len_unpadded_2_exact_row::encoded_len#panic_callsite#euf#c:callresult_encoded_len_panic_callsite_a2(i:2,b:false)::assertion",
            "file": "src/lib.rs",
            "span": {"start_line": 24, "start_col": 4, "end_line": 24, "end_col": 56},
            "sourceFunctionName": "tests::test_encoded_len_unpadded_2_exact_row",
            "paramNames": [],
            "source_cid": format!("blake3-512:{}", "c".repeat(128)),
            "template_cid": format!("blake3-512:{}", "d".repeat(128)),
            "sourceOracle": {
                "status": "resolved",
                "source": "assert_eq!(3, encoded_len(2, false).unwrap());",
                "sourceLines": [
                    {"line": 24, "source": "    assert_eq!(3, encoded_len(2, false).unwrap());"}
                ]
            }
        });
        report.source_mementos = vec![
            serde_json::json!({
                "kind": "source-memento",
                "contractName": "rust-source::tests::test_encoded_len_unpadded_2_exact_row",
                "file": "src/lib.rs",
                "span": {"start_line": 20, "start_col": 0, "end_line": 25, "end_col": 1},
                "sourceFunctionName": "tests::test_encoded_len_unpadded_2_exact_row",
                "paramNames": [],
                "source_cid": format!("blake3-512:{}", "a".repeat(128)),
                "template_cid": format!("blake3-512:{}", "b".repeat(128)),
                "sourceOracle": {
                    "status": "resolved",
                    "source": "assert_eq!(3, encoded_len(2, false).unwrap());",
                    "sourceLines": [
                        {"line": 20, "source": "#[test]"},
                        {"line": 21, "source": "fn test_encoded_len_unpadded_2_exact_row() {"},
                        {"line": 22, "source": "    // Vendor source: base64 0.22.1 tests/encode.rs::encoded_len_unpadded."},
                        {"line": 23, "source": "    // Exact row: encoded_len(2, false) == Some(3)."},
                        {"line": 24, "source": "    assert_eq!(3, encoded_len(2, false).unwrap());"},
                        {"line": 25, "source": "}"}
                    ]
                }
            }),
            assertion_source,
        ];

        let human = render_source_report_human(&report);

        assert!(
            human.contains(
                "    assert_eq!(3, encoded_len(2, false).unwrap());  FACT ⊢ ¬panic(encoded_len#panic_callsite(2, false))"
            ),
            "{human}"
        );
        assert!(
            human.contains("fn test_encoded_len_unpadded_2_exact_row() {"),
            "{human}"
        );
        assert!(human.contains("#[test]"), "{human}");
        assert!(
            !human.contains(
                "source present:\n          assert_eq!(3, encoded_len(2, false).unwrap());\n"
            ),
            "{human}"
        );
        assert!(
            !human.contains("#[test]  FACT ⊢"),
            "FACT must stay on the assertion line, not the test attribute:\n{human}"
        );
    }

    #[test]
    fn human_report_renders_full_body_source_from_source_oracle_with_universe_inline() {
        let mut report = minimal_source_report();
        report.audits = Vec::new();
        report.contracts = vec![
            serde_json::json!({
                "kind": "contract",
                "name": "encoded_len",
                "post": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [
                        {"kind": "var", "name": "result"},
                        {"kind": "ctor", "name": "Some", "args": [{"kind": "var", "name": "complete_chunk_output"}]}
                    ]
                }
            }),
            serde_json::json!({
                "kind": "contract",
                "name": "src/lib.rs::tests::test_encoded_len_unpadded_2_exact_row::encoded_len#panic_callsite#euf#c:callresult_encoded_len_panic_callsite_a2(i:2,b:false)::assertion",
                "inv": {
                    "kind": "not",
                    "operands": [{
                        "kind": "atomic",
                        "name": "panic",
                        "args": [{
                            "kind": "ctor",
                            "name": "call:encoded_len#panic_callsite",
                            "args": [
                                {"kind": "const", "value": 2, "sort": {"name": "Int"}},
                                {"kind": "const", "value": false, "sort": {"name": "Bool"}}
                            ]
                        }]
                    }]
                }
            }),
        ];
        let source_memento = serde_json::json!({
            "kind": "source-memento",
            "contractName": "encoded_len",
            "file": "src/encode.rs",
            "span": {"start_line": 92, "start_col": 4, "end_line": 92, "end_col": 29},
            "sourceFunctionName": "encoded_len",
            "paramNames": ["bytes_len", "padding"],
            "source_cid": format!("blake3-512:{}", "e".repeat(128)),
            "template_cid": format!("blake3-512:{}", "f".repeat(128)),
            "sourceOracle": {
                "status": "resolved",
                "source": "let rem = bytes_len % 3;",
                "sourceLines": [
                    {"line": 92, "source": "    let rem = bytes_len % 3;"}
                ]
            }
        });
        report.source_mementos = vec![serde_json::json!({
            "kind": "source-memento",
            "contractName": "encoded_len",
            "file": "src/encode.rs",
            "span": {"start_line": 90, "start_col": 0, "end_line": 96, "end_col": 1},
            "sourceFunctionName": "encoded_len",
            "paramNames": ["bytes_len", "padding"],
            "source_cid": format!("blake3-512:{}", "c".repeat(128)),
            "template_cid": format!("blake3-512:{}", "d".repeat(128)),
            "sourceOracle": {
                "status": "resolved",
                "source": "let rem = bytes_len % 3;",
                "sourceLines": [
                    {"line": 90, "source": "/// Calculate the base64 encoded length for a given input length."},
                    {"line": 91, "source": "pub const fn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {"},
                    {"line": 92, "source": "    let rem = bytes_len % 3;"},
                    {"line": 93, "source": "    let complete_input_chunks = bytes_len / 3;"},
                    {"line": 94, "source": "    Some(complete_chunk_output)"},
                    {"line": 95, "source": "}"}
                ]
            }
        })];
        report.factory_walk = vec![serde_json::json!({
            "file": "src/encode.rs",
            "line": 92,
            "requested_role": "FunctionBodyConstraint",
            "ast_kind": "stmt",
            "selected": "function_contract_body_post",
            "status": "warranted",
            "verdict": "complete",
            "output": "constraints",
            "sourceMemento": source_memento,
            "emittedFormula": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "result"},
                    {"kind": "ctor", "name": "Some", "args": [{"kind": "var", "name": "complete_chunk_output"}]}
                ]
            }
        })];
        report.call_edges = vec![serde_json::json!({
            "kind": "implication",
            "name": "rust-call-pre:encoded_len->method:checked_add@src/encode.rs:110:26",
            "sourceContract": "encoded_len",
            "sourceSlot": "post",
            "targetSymbol": "method:checked_add",
            "targetContract": "method:checked_add",
            "targetSlot": "pre",
            "prover": "rust-implications"
        })];

        let human = render_source_report_human(&report);

        assert!(
            human.contains(
                "universe under investigation:\n  - encoded_len :: result = Some(complete_chunk_output)"
            ),
            "{human}"
        );
        assert!(
            human.contains(
                "walk warranted by observed facts:\n  - src/lib.rs::tests::test_encoded_len_unpadded_2_exact_row::encoded_len#panic_callsite#euf#c:callresult_encoded_len_panic_callsite_a2(i:2,b:false)::assertion :: ¬panic(encoded_len#panic_callsite(2, false))"
            ),
            "{human}"
        );
        assert!(
            human.contains(
                "callsite preconditions depending on this post:\n  - encoded_len.post -> method:checked_add.pre via method:checked_add"
            ),
            "{human}"
        );
        let universe_index = human
            .find("universe under investigation:")
            .expect("universe section");
        let source_index = human.find("source walk evidence:").expect("source section");
        assert!(
            universe_index < source_index,
            "the body universe should be read before the source walk:\n{human}"
        );
        assert!(
            human.contains(
                "    let rem = bytes_len % 3;  UNIVERSE ⊢ result = Some(complete_chunk_output)"
            ),
            "{human}"
        );
        assert!(
            !human.contains(
                "/// Calculate the base64 encoded length for a given input length.  UNIVERSE ⊢"
            ),
            "{human}"
        );
        assert!(
            human.contains(
                "pub const fn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {"
            ),
            "{human}"
        );
        assert!(!human.contains("lifted FOL:"), "{human}");
        assert!(
            !human.contains("source present:\n          let rem = bytes_len % 3;\n"),
            "{human}"
        );

        let visual = render_report_visual(&report, None);
        assert!(
            visual.contains(
                "    walk warranted by observed facts:\n      - src/lib.rs::tests::test_encoded_len_unpadded_2_exact_row::encoded_len#panic_callsite#euf#c:callresult_encoded_len_panic_callsite_a2(i:2,b:false)::assertion :: ¬panic(encoded_len#panic_callsite(2, false))"
            ),
            "{visual}"
        );
        assert!(
            visual.contains(
                "    callsite preconditions depending on this post:\n      - encoded_len.post -> method:checked_add.pre via method:checked_add"
            ),
            "{visual}"
        );
    }

    #[test]
    fn proof_only_report_rehydrates_factory_walk_rows_for_visual_warrants() {
        let mut pool = sugar_verifier::types::MementoPool::default();
        let contract = serde_json::json!({
            "header": {
                "kind": "contract",
                "contractName": "encoded_len"
            },
            "body": {
                "post": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [
                        {"kind": "var", "name": "result"},
                        {"kind": "ctor", "name": "Some", "args": [{"kind": "var", "name": "complete_chunk_output"}]}
                    ]
                }
            },
            "schemaVersion": "1"
        });
        insert_unanchored_test_member(
            &mut pool,
            test_memento_cid("factory-walk-contract"),
            contract,
        );
        insert_unanchored_test_member(
            &mut pool,
            test_memento_cid("factory-walk-source"),
            serde_json::json!({
                "header": {"kind": "source-memento"},
                "body": {
                    "kind": "source-memento",
                    "contractName": "encoded_len",
                    "file": "src/encode.rs",
                    "span": {"start_line": 90, "start_col": 0, "end_line": 96, "end_col": 1},
                    "sourceFunctionName": "encoded_len",
                    "source_cid": format!("blake3-512:{}", "a".repeat(128)),
                    "template_cid": format!("blake3-512:{}", "b".repeat(128)),
                    "sourceOracle": {
                        "status": "resolved",
                        "sourceLines": [
                            {"line": 90, "source": "/// Calculate the base64 encoded length for a given input length."},
                            {"line": 91, "source": "pub const fn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {"},
                            {"line": 92, "source": "    let rem = bytes_len % 3;"},
                            {"line": 93, "source": "    let complete_input_chunks = bytes_len / 3;"},
                            {"line": 94, "source": "    Some(complete_chunk_output)"},
                            {"line": 95, "source": "}"}
                        ]
                    }
                },
                "schemaVersion": "1"
            }),
        );
        insert_unanchored_test_member(
            &mut pool,
            test_memento_cid("factory-walk-row"),
            serde_json::json!({
                "header": {"kind": "factory-walk-memento"},
                "body": {
                    "kind": "factory-walk-row",
                    "file": "src/encode.rs",
                    "line": 92,
                    "requested_role": "FunctionBodyConstraint",
                    "ast_kind": "stmt",
                    "selected": "function_contract_body_post",
                    "status": "warranted",
                    "verdict": "complete",
                    "output": "constraints",
                    "sourceMemento": {
                        "kind": "source-memento",
                        "file": "src/encode.rs",
                        "span": {"start_line": 92, "start_col": 4, "end_line": 92, "end_col": 29},
                        "sourceFunctionName": "encoded_len",
                        "source_cid": format!("blake3-512:{}", "a".repeat(128)),
                        "template_cid": format!("blake3-512:{}", "b".repeat(128)),
                        "sourceOracle": {
                            "status": "resolved",
                            "sourceLines": [
                                {"line": 92, "source": "    let rem = bytes_len % 3;"}
                            ]
                        }
                    },
                    "emittedFormula": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "ctor", "name": "Some", "args": [{"kind": "var", "name": "complete_chunk_output"}]}
                        ]
                    }
                },
                "schemaVersion": "1"
            }),
        );

        let report = source_report_from_proof_pool(&pool, Some("encoded_len"));

        assert_eq!(report.factory_walk.len(), 1);
        assert_eq!(
            report.factory_walk[0]
                .pointer("/sourceMemento/span/start_line")
                .and_then(Value::as_u64),
            Some(92)
        );
        let visual = render_visual_source_report(&report);
        assert!(
            visual.contains("\u{1b}[32m    let rem = bytes_len % 3;\u{1b}[0m  GREEN ⊢ result = Some(complete_chunk_output)"),
            "{visual}"
        );
        assert!(
            !visual.contains(
                "Calculate the base64 encoded length for a given input length.\u{1b}[0m  GREEN ⊢"
            ),
            "{visual}"
        );
    }

    #[test]
    fn proof_plan_routes_source_oracle_absence_to_pinned_memento_line() {
        let root = tempfile::tempdir().expect("tempdir");
        let mut report = minimal_source_report();
        report.audits = Vec::new();
        report.project_root = Some(root.path().to_path_buf());
        report.plan_mementos = vec![serde_json::json!({
            "kind": "component-plan",
            "schemaVersion": "1",
            "planning": {"source": "component-discovery"},
            "planAtoms": [{
                "kind": "plan-atom",
                "schemaVersion": "1",
                "atomKind": "lifter-binary",
                "role": "body-universes",
                "surface": "rust-fn-contracts",
                "pluginName": "rust-fn-contracts-lift",
                "binary": {"path": "/bin/sugar-walk-rpc"}
            }]
        })];
        report.source_oracle_routes =
            source_oracle_routes_from_plan_mementos(&report.plan_mementos);
        report.source_mementos = vec![serde_json::json!({
            "kind": "source-memento",
            "contractName": "encode_len",
            "file": "src/lib.rs",
            "span": {"start_line": 11, "start_col": 8, "end_line": 12, "end_col": 1},
            "sourceFunctionName": "encode_len",
            "source_cid": format!("blake3-512:{}", "a".repeat(128)),
            "template_cid": format!("blake3-512:{}", "b".repeat(128)),
        })];

        enrich_report_source_mementos_from_oracles(&mut report);

        let oracle = &report.source_mementos[0]["sourceOracle"];
        assert_eq!(oracle["status"], "absent");
        assert_eq!(
            oracle["display"],
            format!(
                "source not present, file src/lib.rs line 11 col 8 cid blake3-512:{}",
                "a".repeat(128)
            )
        );
        assert_eq!(oracle["attempts"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn visual_report_without_source_shows_pinned_absence_and_predicate() {
        let mut report = minimal_source_report();
        report.audits = Vec::new();
        report.contracts = vec![serde_json::json!({
            "kind": "contract",
            "name": "encode_len",
            "post": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "out"},
                    {"kind": "var", "name": "expected"}
                ]
            }
        })];
        report.source_mementos = vec![serde_json::json!({
            "kind": "source-memento",
            "contractName": "encode_len",
            "file": "src/lib.rs",
            "span": {"start_line": 21, "start_col": 2, "end_line": 22, "end_col": 1},
            "sourceFunctionName": "encode_len",
            "source_cid": format!("blake3-512:{}", "c".repeat(128)),
            "template_cid": format!("blake3-512:{}", "d".repeat(128)),
            "sourceOracle": {
                "status": "absent",
                "display": format!("source not present, file src/lib.rs line 21 col 2 cid blake3-512:{}", "c".repeat(128))
            }
        })];

        let visual = render_report_visual(&report, None);

        assert!(visual.contains("universe visual:"), "{visual}");
        assert!(visual.contains("  universe encode_len"), "{visual}");
        assert!(
            visual.contains("FOL: encode_len ⊢ out = expected"),
            "{visual}"
        );
        assert!(
            visual.contains("source not present, file src/lib.rs line 21 col 2 cid blake3-512:"),
            "{visual}"
        );
        assert!(visual.contains("GREEN ⊢ out = expected"), "{visual}");
    }

    #[test]
    fn visual_report_panics_on_red_factory_row_without_grounds() {
        let mut report = minimal_source_report();
        report.factory_walk = vec![serde_json::json!({
            "file": "src/lib.rs",
            "line": 7,
            "requested_role": "Term",
            "ast_kind": "Call",
            "selected": "CallSugar",
            "status": "boundary",
            "verdict": "incomplete",
            "output": "effect",
            "sourceMemento": {
                "kind": "source-memento",
                "file": "src/lib.rs",
                "span": {
                    "start_line": 7,
                    "start_col": 12,
                    "end_line": 7,
                    "end_col": 24
                }
            }
        })];

        let panic = std::panic::catch_unwind(|| render_visual_source_report(&report))
            .expect_err("groundless red rows must halt visual rendering");
        let message = panic
            .downcast_ref::<String>()
            .map(String::as_str)
            .or_else(|| panic.downcast_ref::<&str>().copied())
            .unwrap_or("<non-string panic>");
        assert!(
            message.contains("red verdict carries no grounds; the ledger lost the dragon"),
            "{message}"
        );
        assert!(message.contains("blame=src/lib.rs:7:12"), "{message}");
    }

    #[test]
    fn visual_report_consumes_completed_report_without_render_time_source_oracle_dispatch() {
        let root = tempfile::tempdir().expect("tempdir");
        let marker = root.path().join("render-time-source-oracle-invoked");
        let script = root.path().join("source-oracle.sh");
        std::fs::write(
            &script,
            format!(
                r#"#!/bin/sh
printf invoked > "{}"
printf '%s\n' '{{"jsonrpc":"2.0","id":1,"result":{{"status":"resolved","sourceLines":[{{"line":1,"source":"fn from_plugin() {{}}"}}],"display":"source present"}}}}'
"#,
                marker.display()
            ),
        )
        .expect("write source oracle script");
        let manifest_dir = root.path().join(".sugar/lift/rust-test-assertions");
        std::fs::create_dir_all(&manifest_dir).expect("mkdir manifest dir");
        std::fs::write(
            manifest_dir.join("manifest.toml"),
            format!(
                "name = \"rust-test-assertions\"\ncommand = [\"sh\", \"{}\"]\n",
                script
                    .to_string_lossy()
                    .replace('\\', "\\\\")
                    .replace('"', "\\\"")
            ),
        )
        .expect("write manifest");

        let mut report = minimal_source_report();
        report.audits = Vec::new();
        report.project_root = Some(root.path().to_path_buf());
        report.source_oracle_routes = vec![SourceOracleRoute {
            surface: "rust-test-assertions".to_string(),
            workspace_override: None,
            role: Some("unit-test-assertions".to_string()),
        }];
        report.contracts = vec![serde_json::json!({
            "kind": "contract",
            "name": "encode_len",
            "post": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "out"},
                    {"kind": "var", "name": "expected"}
                ]
            },
            "sourceWarrants": [{
                "kind": "source-memento",
                "contractName": "encode_len",
                "file": "src/lib.rs",
                "span": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 16},
                "sourceFunctionName": "encode_len",
                "source_cid": format!("blake3-512:{}", "e".repeat(128)),
                "template_cid": format!("blake3-512:{}", "f".repeat(128))
            }]
        })];

        let visual = render_report_visual(&report, None);

        assert!(
            !marker.exists(),
            "visual rendering must consume the completed report, not re-dispatch the lift/source plugin:\n{visual}"
        );
        assert!(
            visual.contains("source not present, file src/lib.rs line 1 col 0 cid blake3-512:"),
            "{visual}"
        );
        assert!(
            !visual.contains("fn from_plugin"),
            "rendered source came from the planted source oracle, not the completed report:\n{visual}"
        );
    }

    #[test]
    fn visual_report_does_not_warrant_callable_universe_from_callable_builtin_fact() {
        let mut report = minimal_source_report();
        report.audits = Vec::new();
        report.contracts = vec![
            serde_json::json!({
                "kind": "function-contract",
                "name": "test_scalarbuffer::_as_dict::callable",
                "outBinding": "out",
                "post": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [
                        {"kind": "var", "name": "out"},
                        {"kind": "ctor", "name": "python:dict", "args": []}
                    ]
                },
                "sourceWarrants": [{
                    "kind": "source-memento",
                    "contractName": "test_scalarbuffer::_as_dict::callable",
                    "file": "_core/tests/test_scalarbuffer.py",
                    "span": {"start_line": 17, "start_col": 4, "end_line": 18, "end_col": 72},
                    "sourceFunctionName": "_as_dict",
                    "source_cid": format!("blake3-512:{}", "a".repeat(128)),
                    "template_cid": format!("blake3-512:{}", "b".repeat(128))
                }]
            }),
            serde_json::json!({
                "kind": "contract",
                "name": "test_indexing::test_flatiter_method_signatures::assert:1698:4::assertion",
                "inv": {
                    "kind": "atomic",
                    "name": "py.truthy",
                    "args": [{
                        "kind": "ctor",
                        "name": "call:callable",
                        "args": [{"kind": "var", "name": "method"}]
                    }]
                },
                "sourceWarrants": [{
                    "kind": "source-memento",
                    "contractName": "test_indexing::test_flatiter_method_signatures::assert:1698:4::assertion",
                    "file": "_core/tests/test_indexing.py",
                    "span": {"start_line": 1698, "start_col": 4, "end_line": 1698, "end_col": 27},
                    "sourceFunctionName": "test_flatiter_method_signatures",
                    "source_cid": format!("blake3-512:{}", "c".repeat(128)),
                    "template_cid": format!("blake3-512:{}", "d".repeat(128))
                }]
            }),
        ];

        let visual = render_visual_source_report(&report);
        let section = visual
            .split("  universe test_scalarbuffer::_as_dict::callable\n")
            .nth(1)
            .expect("as_dict universe")
            .split("\n  universe ")
            .next()
            .expect("as_dict section");

        assert!(
            !section.contains("walk warranted by observed facts:"),
            "the `::callable` contract marker must not attach unrelated call:callable facts:\n{visual}"
        );
        assert!(
            !section.contains("callable(method)"),
            "callable builtin facts are not _as_dict callsite evidence:\n{visual}"
        );
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
        let foo_source = std::fs::read_to_string(source_dir.join("foo.rs")).expect("read source");
        let source: syn::File = syn::parse_file(&foo_source).expect("parse source");
        let syn::Item::Fn(item) = &source.items[0] else {
            panic!("expected function");
        };
        let syn::Stmt::Local(first) = &item.block.stmts[0] else {
            panic!("expected first let");
        };
        let syn::Stmt::Local(second) = &item.block.stmts[1] else {
            panic!("expected second let");
        };
        // to_json_stamped stamps sourceOracle.source so resolve_factory_walk_term
        // can resolve the term text without an RPC oracle round-trip.
        let first_memento = sugar_walk::source_oracle::source_memento_of_term_span(
            "tests/foo.rs",
            &foo_source,
            first.init.as_ref().expect("first init").expr.span(),
            "sample",
            &item.sig,
            &item.block,
        )
        .expect("first term memento")
        .to_json_stamped(&foo_source);
        let second_memento = sugar_walk::source_oracle::source_memento_of_term_span(
            "tests/foo.rs",
            &foo_source,
            second.init.as_ref().expect("second init").expr.span(),
            "sample",
            &item.sig,
            &item.block,
        )
        .expect("second term memento")
        .to_json_stamped(&foo_source);
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
                "source_boundary": 1,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAuditSummary": {
                "emittedRows": 5,
                "statusCounts": {
                    "warranted": 3,
                    "incomplete": 1,
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
            "source accounting: loci=2 warranted=1 inactive=0 support=0 boundary=1 unresolved=0"
        ));
        assert!(human.contains(
            "factory accounting: sites=5 warranted=3 incomplete=1 support=0 unresolved=1"
        ));
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
                "source_boundary": 1,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 4,
                "statusCounts": {
                    "warranted": 3,
                    "incomplete": 1,
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
                        "status": "boundary",
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
                        "status": "boundary",
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
                incomplete: 2,
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
                    "status": "boundary",
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
                    "status": "boundary",
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
        let mut response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 0,
                "source_inactive": 0,
                "source_support": 0,
                "source_boundary": 1,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 4,
                "statusCounts": {
                    "warranted": 3,
                    "incomplete": 1,
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
                        "status": "boundary",
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
        stamp_source_oracles(&mut response, &source_text);
        let mut report = source_report_from_lift_response(&response, None).expect("source report");
        report.project_root = Some(root.path().to_path_buf());

        let visual = render_visual_source_report(&report);

        assert!(
            visual.contains("\u{1b}[32m    let x = 1;\u{1b}[0m  GREEN"),
            "{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32m    let y = 2;\u{1b}[0m  GREEN"),
            "{visual}"
        );
        assert!(
            visual.contains(
                "\u{1b}[31m    let z = runtime();\u{1b}[0m  RED HERE effect: runtime boundary: pointer identity"
            ),
            "{visual}"
        );
        assert!(
            visual.contains("\u{1b}[31m    let a = 10;\u{1b}[0m  RED via effect at src/lib.rs:5:12: runtime boundary: pointer identity"),
            "{visual}"
        );
        assert!(
            !visual.contains("    let a = 10;\u{1b}[0m  RED HERE"),
            "{visual}"
        );
    }

    #[test]
    fn visual_report_lists_observed_call_edges() {
        let mut report = minimal_source_report();
        report.call_edges = vec![serde_json::json!({
            "kind": "call-edge",
            "schemaVersion": "1",
            "sourceContract": "test_external::test_sqrt::assert:5:4::assertion",
            "targetSymbol": "call:math.sqrt",
            "targetContract": null,
            "targetContractCid": null,
            "callSiteLocus": {
                "file": "test_external.py",
                "line": 5,
                "column": 27
            }
        })];

        let visual = render_visual_source_report(&report);

        assert!(visual.contains("call edges observed:"), "{visual}");
        assert!(
            visual.contains(
                "test_external::test_sqrt::assert:5:4::assertion -> call:math.sqrt -> null cid=null @ test_external.py:5 ?"
            ),
            "{visual}"
        );
    }

    #[test]
    fn visual_report_shows_whole_unit_test_with_inv_inline_at_assertion() {
        let root = tempfile::tempdir().expect("tempdir");
        let source_dir = root.path().join("src");
        std::fs::create_dir_all(&source_dir).expect("mkdir source dir");
        std::fs::write(
            source_dir.join("lib.rs"),
            r#"
#[test]
fn sample() {
    let setup = 1;
    assert_eq!(setup, 1);
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
        let function_memento = sugar_walk::source_oracle::source_memento_of_named_item_fn(
            "src/lib.rs",
            &source_text,
            "sample",
            item,
        )
        .to_json();
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
        let first_assert = memento_for_stmt(1);
        let second_assert = memento_for_stmt(2);
        let first_formula = serde_json::json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "setup"},
                {"kind": "const", "value": 1, "sort": {"name": "Int"}}
            ]
        });
        let second_formula = serde_json::json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "const", "value": 10, "sort": {"name": "Int"}},
                {"kind": "const", "value": 10, "sort": {"name": "Int"}}
            ]
        });
        let mut response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "contract",
                    "name": "src/lib.rs::tests::sample",
                    "outBinding": "out",
                    "inv": {
                        "kind": "and",
                        "operands": [
                            first_formula.clone(),
                            second_formula.clone()
                        ]
                    },
                    "sourceWarrants": [
                        first_assert.clone(),
                        second_assert.clone()
                    ]
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_inactive": 0,
                "source_support": 0,
                "source_boundary": 0,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [function_memento],
            "factoryAuditSummary": {
                "emittedRows": 2,
                "statusCounts": {
                    "warranted": 2,
                    "incomplete": 0,
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
                        "sourceMemento": first_assert,
                        "emittedFormula": first_formula
                    },
                    {
                        "file": "src/lib.rs",
                        "line": 5,
                        "requested_role": "AssertionSurface",
                        "ast_kind": "expr",
                        "selected": "assertion_surface_relation_macro",
                        "status": "warranted",
                        "verdict": "complete",
                        "output": "constraints",
                        "sourceMemento": second_assert,
                        "emittedFormula": second_formula
                    }
                ]
            }
        });
        stamp_source_oracles(&mut response, &source_text);
        let mut report = source_report_from_lift_response(&response, None).expect("source report");
        report.project_root = Some(root.path().to_path_buf());

        let visual = render_visual_source_report(&report);

        assert!(visual.contains("universe visual:"), "{visual}");
        assert!(
            visual.contains("  universe src/lib.rs::tests::sample"),
            "{visual}"
        );
        assert!(
            visual.contains("    FOL: src/lib.rs::tests::sample ⊢ setup = 1 ∧ 10 = 10"),
            "{visual}"
        );
        assert!(
            visual.contains("    fn sample() {"),
            "unit-test visual must walk the whole test function:\n{visual}"
        );
        assert!(
            visual.contains("        let setup = 1;"),
            "unit-test setup lines remain visible without predicates:\n{visual}"
        );
        assert!(
            visual.contains("        assert_eq!(setup, 1);  FACT ⊢ setup = 1"),
            "unit-test invariant must be pinned inline at its assertion:\n{visual}"
        );
        assert!(
            visual.contains("        assert_eq!(10, 10);  FACT ⊢ 10 = 10"),
            "unit-test invariant must be pinned inline at its assertion:\n{visual}"
        );
        assert!(
            visual.contains("    }"),
            "unit-test visual must walk through the closing brace:\n{visual}"
        );
        let universe_visual = visual.split("factory visual:").next().unwrap_or(&visual);
        assert!(
            !universe_visual.contains("GREEN") && !universe_visual.contains("RED"),
            "unit-test fact view must not use body green/red status:\n{visual}"
        );
    }

    #[test]
    fn visual_report_shows_incomplete_function_body_as_effect_trace_without_predicates() {
        let root = tempfile::tempdir().expect("tempdir");
        let source_dir = root.path().join("src");
        std::fs::create_dir_all(&source_dir).expect("mkdir source dir");
        std::fs::write(
            source_dir.join("lib.rs"),
            r#"
fn encode_with_padding(input: &[u8], output: &mut [u8], engine: &Engine) {
    debug_assert_eq!(1, 1);
    let b64_bytes_written = engine.internal_encode(input, output);
    let padding_bytes = 0;
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
            "encode_with_padding",
            item,
        )
        .to_json();
        let effect_site = sugar_walk::source_oracle::source_memento_of_statement_span(
            "src/lib.rs",
            &source_text,
            item.block.stmts[1].span(),
            "encode_with_padding",
            &item.sig,
            &item.block,
        )
        .expect("effect statement memento")
        .to_json();
        let mut response = serde_json::json!({
            "kind": "ir-document",
            "ir": [
                {
                    "kind": "function-contract",
                    "name": "encode_with_padding",
                    "outBinding": "result",
                    "post": {"kind": "atomic", "name": "true", "args": []},
                    "sourceWarrants": [function_memento]
                }
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_inactive": 0,
                "source_support": 0,
                "source_boundary": 0,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 0,
                    "incomplete": 1,
                    "support": 0,
                    "unresolved": 0
                },
                "unresolvedSites": [],
                "factoryWalk": [
                    {
                        "file": "src/lib.rs",
                        "line": 4,
                        "requested_role": "FunctionBodyConstraint",
                        "ast_kind": "stmt",
                        "selected": "function_body_runtime_call",
                        "status": "boundary",
                        "verdict": "incomplete",
                        "output": "effect",
                        "reason": "runtime boundary: internal_encode writes output",
                        "sourceMemento": effect_site
                    }
                ]
            }
        });
        stamp_source_oracles(&mut response, &source_text);
        let mut report = source_report_from_lift_response(&response, None).expect("source report");
        report.project_root = Some(root.path().to_path_buf());

        let visual = render_visual_source_report(&report);
        let universe_visual = visual.split("factory visual:").next().unwrap_or(&visual);

        assert!(
            universe_visual.contains("  universe encode_with_padding"),
            "{visual}"
        );
        assert!(
            universe_visual
                .contains("    incomplete: runtime boundary: internal_encode writes output"),
            "red function universes must report the effect instead of a theorem:\n{visual}"
        );
        assert!(
            !universe_visual.contains("FOL: encode_with_padding ⊢"),
            "incomplete function universes must not render a FOL predicate:\n{visual}"
        );
        assert!(
            !universe_visual.contains("⊢"),
            "incomplete function universes emit no predicates anywhere:\n{visual}"
        );
        assert!(
            universe_visual.contains("\u{1b}[32mfn encode_with_padding(input: &[u8], output: &mut [u8], engine: &Engine) {\u{1b}[0m  GREEN"),
            "function body visual must walk the whole source before the effect:\n{visual}"
        );
        assert!(
            universe_visual.contains("\u{1b}[32m    debug_assert_eq!(1, 1);\u{1b}[0m  GREEN"),
            "pre-effect body lines are green but predicate-free:\n{visual}"
        );
        assert!(
            universe_visual.contains(
                "\u{1b}[31m    let b64_bytes_written = engine.internal_encode(input, output);\u{1b}[0m  RED HERE effect: runtime boundary: internal_encode writes output"
            ),
            "first incomplete factory effect is the RED HERE line:\n{visual}"
        );
        assert!(
            universe_visual.contains("\u{1b}[31m    let padding_bytes = 0;\u{1b}[0m  RED via effect at src/lib.rs:4:4: runtime boundary: internal_encode writes output"),
            "after the effect, later source remains red and unknowable:\n{visual}"
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
        let mut response = serde_json::json!({
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
                "source_boundary": 0,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 2,
                "statusCounts": {
                    "warranted": 2,
                    "incomplete": 0,
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
        stamp_source_oracles(&mut response, &source_text);
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
        let universe_visual = visual.split("factory visual:").next().unwrap_or(&visual);
        assert!(
            universe_visual.contains("\u{1b}[32mfn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {\u{1b}[0m  GREEN"),
            "function universe projection must walk the whole function source:\n{visual}"
        );
        assert!(
            universe_visual.contains(
                "\u{1b}[32m    let rem = bytes_len % 3;\u{1b}[0m  GREEN ⊢ rem = (bytes_len % 3)"
            ),
            "factory-emitted predicates must stay pinned to their source statement lines:\n{visual}"
        );
        assert!(
            universe_visual.contains(
                "\u{1b}[32m    let encoded_rem = rem + 1;\u{1b}[0m  GREEN ⊢ encoded_rem = (rem + 1)"
            ),
            "factory-emitted predicates must stay pinned to their source statement lines:\n{visual}"
        );
        assert!(
            universe_visual.contains("\u{1b}[32m    Some(encoded_rem)\u{1b}[0m  GREEN"),
            "function universe projection must include source lines with no emitted predicate:\n{visual}"
        );
        assert!(
            universe_visual.contains("\u{1b}[32m}\u{1b}[0m  GREEN"),
            "function universe projection must walk through the closing brace:\n{visual}"
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
        let mut response = serde_json::json!({
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
                "source_boundary": 0,
                "source_unresolved": 0
            },
            "sourceAudits": [],
            "factoryAudits": [],
            "sourceMementos": [],
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 1,
                    "incomplete": 0,
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
        stamp_source_oracles(&mut response, &source_text);
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
            visual.contains("\u{1b}[32mfn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {\u{1b}[0m  GREEN"),
            "universe visual must walk the whole warranted function source from its signature:\n{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32m    if rem > 0 {\u{1b}[0m  GREEN ⊢ result = if rem > 0 then Some(4) else Some(0)"),
            "the predicate emitted by the whole if expression should land on the if line:\n{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32m        if padding {\u{1b}[0m  GREEN"),
            "universe visual must keep walking nested source lines even when they emit no predicate:\n{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32m            Some(4)\u{1b}[0m  GREEN"),
            "universe visual must show branch source, not only predicate-bearing rows:\n{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32m        } else {\u{1b}[0m  GREEN"),
            "universe visual must preserve else lines in the source walk:\n{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32m        Some(0)\u{1b}[0m  GREEN"),
            "universe visual must show the else branch source:\n{visual}"
        );
        assert!(
            visual.contains("\u{1b}[32m}\u{1b}[0m  GREEN"),
            "universe visual must walk through the closing brace of the warranted function:\n{visual}"
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
            role: Some("body-universes".to_string()),
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
    fn visual_source_oracle_route_accepts_single_project_route_without_override() {
        let root = tempfile::tempdir().expect("tempdir");
        let route = SourceOracleRoute {
            surface: "python".to_string(),
            workspace_override: None,
            role: Some("source-lifter".to_string()),
        };
        let memento = serde_json::json!({
            "file": "test_array_map.py",
            "sourceFunctionName": "test_array_map_sugar",
            "span": {"start_line": 1, "start_col": 0, "end_line": 2, "end_col": 54},
            "source_cid": "blake3-512:source",
            "template_cid": "blake3-512:template"
        });

        let routed = routed_source_memento(root.path(), &[route], &memento)
            .expect("single project source oracle route should own local files");

        assert_eq!(routed.memento["file"], "test_array_map.py");
        assert_eq!(routed.workspace_root, root.path().canonicalize().unwrap());
    }

    #[test]
    fn visual_source_oracle_route_keeps_local_files_out_of_vendor_override() {
        let root = tempfile::tempdir().expect("tempdir");
        let routes = [
            SourceOracleRoute {
                surface: "rust-test-assertions".to_string(),
                workspace_override: None,
                role: Some("unit-test-assertions".to_string()),
            },
            SourceOracleRoute {
                surface: "rust-fn-contracts".to_string(),
                workspace_override: Some("vendor/base64-0.22.1".to_string()),
                role: Some("body-universes".to_string()),
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
                "source_boundary": 0,
                "source_unresolved": 0
            },
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 1,
                    "incomplete": 0,
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
                "source_boundary": 0,
                "source_unresolved": 1
            },
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 0,
                    "incomplete": 0,
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
                "source_boundary": 0,
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
                    "incomplete": 0,
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
                "source_boundary": 0,
                "source_unresolved": 0
            },
            "factoryAuditSummary": {
                "emittedRows": 1,
                "statusCounts": {
                    "warranted": 0,
                    "incomplete": 0,
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
                "source_boundary": 0,
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
                "source_boundary": 0,
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
                "source_boundary": 0,
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
                        "source_boundary": 0,
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
                "source_boundary": 0,
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
                "source_boundary": 0,
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
                "source_boundary": 0,
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
                "source_boundary": 0,
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
                "facts observed:\n  - src/lib.rs::tests::enc_asserts :: enc(\"abc\") = \"def\" @ src/lib.rs:12-14 enc_asserts() source_cid=blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
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
                "source_boundary": 0,
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
                "src/lib.rs::tests::support_only::panic-free::answer :: panic-free(answer())"
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
                "source_boundary": 0,
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
            diagnostics: vec![],
            source_mementos: vec![],
            plan_mementos: vec![],
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
            lift_coverage: None,
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
    fn zero_test_assertions_over_real_source_is_a_named_hard_failure() {
        // #3766: a lifted tree with real source but zero vendor test
        // assertions must never read as exit-0-empty. This is the discharge
        // discrimination test: positive (source + assertions => quiet),
        // negative (source, no assertions => loud named condition), and
        // structural (no source at all => a different, prior condition, not
        // this one).
        let condition =
            no_vendor_test_corpus_condition(&serde_json::json!({ "source_loci": 42 }), &[], &[]);
        let condition = condition.expect("zero-assertion source tree must name the condition");
        assert_eq!(condition["kind"], "no-vendor-test-corpus");
        assert!(condition["message"]
            .as_str()
            .unwrap()
            .contains("no vendor test corpus in workspace"));
    }

    #[test]
    fn source_with_test_assertions_carries_no_named_terminal() {
        let contracts = vec![serde_json::json!({
            "name": "test_mod::tests::test_thing::assert:1:1::assertion"
        })];
        let condition = no_vendor_test_corpus_condition(
            &serde_json::json!({ "source_loci": 42 }),
            &[],
            &contracts,
        );
        assert!(
            condition.is_none(),
            "a workspace with observed test facts must not carry the empty-corpus terminal"
        );
    }

    #[test]
    fn empty_workspace_does_not_claim_the_no_test_corpus_terminal() {
        // Zero source loci is a prior, different condition (nothing was
        // lifted at all); it must not masquerade as "tests are missing".
        let condition =
            no_vendor_test_corpus_condition(&serde_json::json!({ "source_loci": 0 }), &[], &[]);
        assert!(condition.is_none());
    }

    #[test]
    fn no_vendor_test_corpus_condition_is_a_hard_report_failure() {
        let mut report = minimal_source_report();
        report.ledger = serde_json::json!({ "source_loci": 42, "source_unresolved": 0 });
        report.diagnostics =
            vec![no_vendor_test_corpus_condition(&report.ledger, &[], &[]).expect("condition")];
        assert!(source_report_has_hard_failures(&report));
        let human = render_source_report_human(&report);
        assert!(
            human.contains("NAMED CONDITION [no-vendor-test-corpus]"),
            "{human}"
        );
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
            // A real local test assertion backs the vendor conjoin below (its
            // name matches `localContract`); this keeps the fixture honest
            // against the #3766 no-vendor-test-corpus terminal, which these
            // tests are not exercising -- they exercise vendor conjoin
            // resolution instead.
            "ir": [
                {"name": "src/lib.rs::tests::fresh_vendor_fol_good::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion"}
            ],
            "sourceLedger": {
                "source_loci": 1,
                "source_warranted": 1,
                "source_support": 0,
                "source_boundary": 0,
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
