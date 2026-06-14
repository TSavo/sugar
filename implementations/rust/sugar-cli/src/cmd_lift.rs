// SPDX-License-Identifier: Apache-2.0
//
// `sugar lift <PROJECT>`: dispatch the configured lift-plugin protocol
// and emit the raw lifted ProofIR response. Minting is a separate composition
// step owned by `sugar mint`.

use std::collections::BTreeMap;
use std::io::Write;
use std::path::PathBuf;

use owo_colors::OwoColorize;
use serde_json::{Map, Value};

use crate::lift_plugin::{self, LiftPluginError, LiftPluginOptions};
use crate::project_config::{read_project_config, read_user_config, ProjectConfig};
use crate::{LiftArgs, EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

pub fn run(args: LiftArgs) -> u8 {
    let project_root = args.project.unwrap_or_else(|| PathBuf::from("."));
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
    let surface = match configured_lift_surface(&project_cfg, &user_cfg) {
        Some(surface) => surface,
        None => {
            eprintln!(
                "{}: no lift surface configured. Set [[plugins]] or [authoring] surface in .sugar/config.toml.",
                "error".red().bold()
            );
            return EXIT_USER_ERROR;
        }
    };

    match lift_plugin::dispatch_lift_path(
        &project_root,
        &surface,
        LiftPluginOptions {
            identify_only: args.identify_only,
            library_bindings: args.library_bindings,
            ..Default::default()
        },
        true,
    ) {
        Ok(session) => {
            let response = session.response();
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
                let report =
                    match source_report_from_lift_response(response, args.contract.as_deref()) {
                        Ok(report) => report,
                        Err(error) => {
                            eprintln!("{}: {error}", "error".red().bold());
                            return EXIT_USER_ERROR;
                        }
                    };
                let rendered = if args.out.json {
                    match render_source_report_json(&report) {
                        Ok(rendered) => rendered,
                        Err(error) => {
                            eprintln!("{}: render lift report: {error}", "error".red().bold());
                            return EXIT_USER_ERROR;
                        }
                    }
                } else {
                    render_source_report_human(&report)
                };
                if let Err(error) = write_output(None, rendered.as_bytes()) {
                    eprintln!("{}: {error}", "error".red().bold());
                    return EXIT_USER_ERROR;
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

fn configured_lift_surface(
    project_cfg: &ProjectConfig,
    user_cfg: &ProjectConfig,
) -> Option<String> {
    if let Some(surface) = project_cfg.surface_for("lift") {
        return Some(surface);
    }

    let lift_plugins = project_cfg
        .plugins
        .iter()
        .filter(|plugin| plugin.is_lift_plugin())
        .collect::<Vec<_>>();
    if lift_plugins.len() == 1 {
        return Some(lift_plugins[0].surface.clone());
    }

    user_cfg.surface_for("lift")
}

#[derive(Debug, Clone, PartialEq)]
struct LiftSourceReport {
    ledger: Value,
    audits: Vec<Value>,
    source_mementos: Vec<Value>,
    contracts: Vec<Value>,
}

const SOURCE_LEDGER_FIELDS: [&str; 7] = [
    "source_loci",
    "source_warranted",
    "source_support",
    "source_refused",
    "source_inactive",
    "source_refuted",
    "unclassified_source",
];

fn source_report_from_lift_response(
    response: &Value,
    contract_filter: Option<&str>,
) -> Result<LiftSourceReport, String> {
    let ledger = response
        .get("sourceLedger")
        .filter(|value| value.is_object())
        .ok_or_else(|| {
            "lift response did not include sourceLedger; the kit must emit source-audit accounting"
                .to_string()
        })?;
    if ledger.get("unclassified_source").is_none() {
        return Err(
            "lift response sourceLedger is missing unclassified_source; cannot measure source coverage"
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

    let filtered_audits: Vec<Value> = audits
        .iter()
        .filter(|audit| {
            contract_filter.is_none_or(|filter| {
                contract_name(audit)
                    .or_else(|| audit.get("role").and_then(Value::as_str))
                    .is_some_and(|name| name.contains(filter))
            })
        })
        .cloned()
        .collect();

    if contract_filter.is_some() && filtered_audits.is_empty() {
        return Err(format!(
            "no source audits matched contract filter `{}`",
            contract_filter.unwrap()
        ));
    }

    let ledger = if contract_filter.is_some() {
        recompute_source_ledger(&filtered_audits)
    } else {
        ledger.clone()
    };
    let contracts = matching_report_contracts(response, contract_filter, &filtered_audits);
    let source_mementos =
        matching_report_source_mementos(response, contract_filter, &filtered_audits)?;

    Ok(LiftSourceReport {
        ledger,
        audits: filtered_audits,
        source_mementos,
        contracts,
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
        return Ok(mementos.clone());
    }

    let audit_bases = audits
        .iter()
        .filter_map(contract_name)
        .map(contract_group_key)
        .collect::<Vec<_>>();
    let filter = contract_filter.unwrap();
    Ok(mementos
        .iter()
        .filter(|memento| {
            let names = [
                memento.get("claimName").and_then(Value::as_str),
                memento.get("contractName").and_then(Value::as_str),
                memento.get("eufName").and_then(Value::as_str),
                memento.get("role").and_then(Value::as_str),
            ];
            names
                .into_iter()
                .flatten()
                .any(|name| name.contains(filter))
                || names.into_iter().flatten().any(|name| {
                    let group = contract_group_key(name);
                    audit_bases.iter().any(|base| base == &group)
                })
        })
        .cloned()
        .collect())
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
    contracts
        .iter()
        .filter(|contract| {
            let Some(name) = contract_value_name(contract) else {
                return false;
            };
            let group = contract_group_key(name);
            contract_filter.is_none_or(|filter| name.contains(filter))
                || audit_bases.iter().any(|base| base == &group)
        })
        .cloned()
        .collect()
}

fn recompute_source_ledger(audits: &[Value]) -> Value {
    let mut ledger = Map::new();
    for field in SOURCE_LEDGER_FIELDS {
        let total = audits
            .iter()
            .map(|audit| {
                audit
                    .get("totals")
                    .and_then(|totals| totals.get(field))
                    .and_then(Value::as_i64)
                    .unwrap_or(0)
            })
            .sum::<i64>();
        ledger.insert(field.to_string(), Value::Number(total.into()));
    }
    Value::Object(ledger)
}

fn render_source_report_json(report: &LiftSourceReport) -> Result<String, serde_json::Error> {
    serde_json::to_string_pretty(&serde_json::json!({
        "kind": "lift-source-report",
        "sourceLedger": report.ledger,
        "sourceAudits": report.audits,
        "sourceMementos": report.source_mementos,
        "contracts": report.contracts,
    }))
    .map(|mut rendered| {
        rendered.push('\n');
        rendered
    })
}

fn render_source_report_human(report: &LiftSourceReport) -> String {
    let mut out = String::new();
    out.push_str(&format!(
        "source audit: {}\n",
        format_counts(&report.ledger)
    ));
    if report.audits.is_empty() {
        out.push_str("no source audits emitted\n");
        return out;
    }

    let mut group_keys = Vec::new();
    for audit in &report.audits {
        let key = contract_name(audit)
            .map(contract_group_key)
            .unwrap_or_else(|| "<unknown contract>".to_string());
        if !group_keys.contains(&key) {
            group_keys.push(key);
        }
    }

    for memento in &report.source_mementos {
        let key = memento_group_key(memento).unwrap_or_else(|| "<unknown contract>".to_string());
        if !group_keys.contains(&key) {
            group_keys.push(key);
        }
    }

    for group_key in group_keys {
        let group_audits = report
            .audits
            .iter()
            .filter(|audit| {
                contract_name(audit)
                    .map(contract_group_key)
                    .is_some_and(|key| key == group_key)
            })
            .collect::<Vec<_>>();
        let group_contracts = report
            .contracts
            .iter()
            .filter(|contract| {
                contract_value_name(contract)
                    .map(contract_group_key)
                    .is_some_and(|key| key == group_key)
            })
            .collect::<Vec<_>>();
        let group_mementos = report
            .source_mementos
            .iter()
            .filter(|memento| memento_group_key(memento).is_some_and(|key| key == group_key))
            .collect::<Vec<_>>();

        let display_name = group_audits
            .first()
            .and_then(|audit| contract_name(audit))
            .or_else(|| {
                group_contracts
                    .first()
                    .and_then(|contract| contract_value_name(contract))
            })
            .unwrap_or("<unknown contract>");
        out.push_str(&format!("\ncontract: {display_name}\n"));

        let fact_mementos = group_mementos
            .iter()
            .filter(|memento| is_fact_source_memento(memento))
            .copied()
            .collect::<Vec<_>>();
        if fact_mementos.is_empty() {
            match assertion_site_for_group(&group_contracts) {
                Some(site) => out.push_str(&format!(
                    "facts observed:\n  - assertion source inferred from contract name: {site}\n"
                )),
                None => out.push_str("facts observed:\n  - not emitted by kit\n"),
            }
        } else {
            out.push_str("facts observed:\n");
            for memento in fact_mementos {
                out.push_str(&format!("  - {}\n", format_fact_memento(memento)));
            }
        }
        out.push_str("warranted digs:\n");
        for audit in &group_audits {
            out.push_str(&format!("  - {}\n", format_source_memento(audit)));
        }
        if !group_contracts.is_empty() {
            let generalized_rows = group_contracts
                .iter()
                .flat_map(|contract| generalized_contract_fol(contract))
                .collect::<Vec<_>>();
            if generalized_rows.is_empty() {
                out.push_str("lifted FOL:\n");
                for contract in &group_contracts {
                    out.push_str(&format!("  - {}\n", format_contract_fol(contract)));
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
            out.push_str(&format!("  dig: {role} / {universe}\n"));
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

    out
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
        if is_support_ast_kind(&locus.ast_kind) {
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

fn is_support_ast_kind(ast_kind: &str) -> bool {
    matches!(
        ast_kind,
        "Import" | "ImportFrom" | "FunctionDef" | "AsyncFunctionDef" | "ClassDef"
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
        "inactive" => 1,
        "support" => 2,
        "refused" => 3,
        "refuted" => 4,
        "unclassified" => 5,
        _ => 6,
    }
}

fn normalized_source_status(status: Option<&str>) -> &str {
    match status {
        Some("warranted") => "warranted",
        Some("inactive") => "inactive",
        Some("support") => "support",
        Some("refused") => "refused",
        Some("refuted") => "refuted",
        _ => "unclassified",
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
    .map(contract_group_key)
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

fn format_counts(value: &Value) -> String {
    format!(
        "loci={} warranted={} inactive={} support={} refused={} refuted={} unclassified={}",
        source_count(value, "source_loci"),
        source_count(value, "source_warranted"),
        source_count(value, "source_inactive"),
        source_count(value, "source_support"),
        source_count(value, "source_refused"),
        source_count(value, "source_refuted"),
        source_count(value, "unclassified_source"),
    )
}

fn source_count(value: &Value, field: &str) -> i64 {
    value.get(field).and_then(Value::as_i64).unwrap_or(0)
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
    name.rsplit_once("::")
        .map(|(base, _)| base)
        .unwrap_or(name)
        .to_string()
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
        return format!("<missing source memento> [{role} / {universe}]");
    };
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
    let function = source
        .get("source_function_name")
        .and_then(Value::as_str)
        .unwrap_or("<unknown function>");
    let params = source
        .get("param_names")
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
    let inv = contract.get("inv").unwrap_or(&Value::Null);
    let rendered = proofir_formula_to_fol_with_instances(inv);
    format!("{name} :: {rendered}")
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
        other => {
            serde_json::to_string(term).unwrap_or_else(|_| format!("<unrenderable {other} term>"))
        }
    }
}

fn format_symbolic_ctor(name: &str, args: &[Value]) -> Option<String> {
    let symbol = match name {
        "bv32.add" | "concept:add" => "+",
        "bv32.sub" | "concept:sub" => "-",
        "bv32.mul" | "concept:mul" => "*",
        "bv32.and" => "&",
        "bv32.or" => "|",
        "bv32.xor" => "⊕",
        "bv32.shl" => "<<",
        "bv32.lshr" => ">>>",
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
                "source_refuted": 0,
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
                        "source_refuted": 0,
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
                        "source_refuted": 0,
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
    fn lift_returns_ok() {
        let args = LiftArgs {
            project: Some(PathBuf::from("/sugar/no/such/lift/project")),
            output: None,
            identify_only: false,
            library_bindings: false,
            report: false,
            contract: None,
            out: OutputFlags::default(),
        };
        assert_eq!(run(args), crate::EXIT_USER_ERROR);
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

        assert_eq!(
            configured_lift_surface(&project_cfg, &ProjectConfig::default()).as_deref(),
            Some("java-test-assertions")
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
    fn human_report_shows_crc_line_606_as_warranted() {
        let report =
            source_report_from_lift_response(&lift_response_with_source_axis(), Some("Crc32"))
                .expect("filtered source report");
        let human = render_source_report_human(&report);

        assert!(human.contains("source audit: loci=29 warranted=15 inactive=13 support=0 refused=1 refuted=0 unclassified=0"));
        assert!(human.contains("commons-codec.PureJavaCrc32::update(byte[],int,int)"));
        assert!(human.contains("facts observed:"));
        assert!(human.contains("CommonsCodecCrc32Test.java:44 testKnownVector() [java.test-fact]"));
        assert!(human.contains("warranted digs:"));
        assert!(human.contains("606 warranted Assignment crc32.slicing-by-8 input fold"));
        assert!(human.contains("lifted FOL:"));
        assert!(human.contains("crc32.eq-walked(3808858755"));
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
                "source_refuted": 0,
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
                        "source_refuted": 0,
                        "unclassified_source": 0
                    },
                    "loci": [
                        {
                            "line": 1,
                            "status": "support",
                            "ast_kind": "Import",
                            "ast_path": "$.module.body[0]"
                        },
                        {
                            "line": 1,
                            "status": "support",
                            "ast_kind": "alias",
                            "ast_path": "$.module.body[0].names[0]"
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
            "source audit: loci=3 warranted=1 inactive=0 support=2 refused=0 refuted=0 unclassified=0"
        ));
        assert!(human.contains(
            "totals: loci=3 warranted=1 inactive=0 support=2 refused=0 refuted=0 unclassified=0"
        ));
        assert!(human.contains("support roots: Import=1"));
        assert!(human.contains("support covered by parent: alias=1"));
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
                "source_refuted": 0,
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
                        "source_refuted": 0,
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
        assert!(human
            .contains("/site-packages/itsdangerous/serializer.py:245 unclassified FunctionDef"));
    }

    #[test]
    fn human_report_shows_compact_package_source_accounting() {
        let response = serde_json::json!({
            "kind": "ir-document",
            "ir": [],
            "sourceLedger": {
                "source_loci": 4,
                "source_warranted": 1,
                "source_support": 1,
                "source_refused": 0,
                "source_inactive": 0,
                "source_refuted": 0,
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
                        "source_loci": 4,
                        "source_warranted": 1,
                        "source_support": 1,
                        "source_refused": 0,
                        "source_inactive": 0,
                        "source_refuted": 0,
                        "unclassified_source": 2
                    },
                    "ast_type_counts": {
                        "warranted": {"Return": 1},
                        "support": {"FunctionDef": 1},
                        "unclassified": {"Assign": 1, "Call": 1}
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
        assert!(human.contains("support: FunctionDef=1"));
        assert!(human.contains("unclassified: Assign=1, Call=1"));
        assert!(human.contains("sample loci:"));
        assert!(human.contains("/site-packages/pandas/core/frame.py:10 unclassified Assign"));
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
                "source_refuted": 0,
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
                        "source_refuted": 0,
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
        assert!(human.contains("    unclassified: Assign=1, Compare=1, If=1, Subscript=1"));
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
                "source_refuted": 0,
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
                        "source_refuted": 0,
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
        assert!(
            human.contains("    unclassified roots: Assign=1, FunctionDef=1, If=1, ImportFrom=1")
        );
        assert!(human.contains("    unclassified constraint roots: Assign=1, If=1"));
        assert!(human.contains("    unclassified constraint children: Compare=1, Subscript=1"));
        assert!(human.contains("    unclassified support roots: FunctionDef=1, ImportFrom=1"));
        assert!(human.contains(
            "    unclassified covered by parent: Compare=1, Name=2, Subscript=1, alias=1, arg=1"
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
                "source_refuted": 0,
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
                        "source_refuted": 0,
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
        let rendered = render_source_report_json(&report).expect("json report");
        let parsed: serde_json::Value = serde_json::from_str(&rendered).expect("valid json");

        assert_eq!(parsed["kind"], "lift-source-report");
        assert_eq!(parsed["sourceLedger"]["source_loci"], 29);
        assert_eq!(parsed["sourceAudits"].as_array().unwrap().len(), 1);
        assert_eq!(parsed["sourceMementos"].as_array().unwrap().len(), 2);
    }
}
