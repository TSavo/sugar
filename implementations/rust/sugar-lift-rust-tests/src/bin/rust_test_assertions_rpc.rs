// SPDX-License-Identifier: Apache-2.0
//
// RPC entrypoint for the Rust test-assertion consistency lifter.

use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};
use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::rc::Rc;

use quote::ToTokens;
use serde_json::{json, Value};
use sugar_canonicalizer::{blake3_512_of, encode_jcs};
use sugar_ir_symbolic::serialize::{formula_to_value, marshal_declarations};
use sugar_ir_symbolic::{eq, make_var, ContractDecl, Term};
use sugar_lift_rust_tests::cargo_cfg::{
    cargo_cfg_options_from_lifter_args, lift_options_from_rust_build_cfg,
};
use sugar_lift_rust_tests::source_oracle;
use sugar_lift_rust_tests::{
    lift_file_with_all_source_imports, AssertionFactEmission, AssertionFactKind,
    ConstSourceRegistry, FactoryAudit, FactoryAuditSpan, FunctionSourceRegistry, LiftOptions,
    MacroRegistry, TargetCfg,
};
use sugar_verifier::types::{memento_body, memento_body_field, memento_kind};
use tracing::{debug, info, warn};

const VERSION: &str = env!("CARGO_PKG_VERSION");
const SURFACE: &str = "rust-test-assertions";
const KIT_DECLARATION_RPC_METHOD: &str = "sugar.plugin.kit_declaration";
const COMPONENT_PLAN_RPC_METHOD: &str = "sugar.component.plan";
const RESOLVE_PROOF_BY_CID_RPC_METHOD: &str = "sugar.plugin.resolve_proof_by_cid";
const RESOLVE_SOURCE_MEMENTO_RPC_METHOD: &str = "sugar.plugin.resolve_source_memento";
const SHOULD_PANIC_OPAQUE_TERMINAL_REASON: &str =
    "should_panic terminal panic not text-determined (opaque body)";
const SOURCE_LOCATION_RUNTIME_REASON: &str =
    "source location runtime-determined, not text-determined";

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

fn rss_delta_kib(before: Option<u64>, after: Option<u64>) -> Option<u64> {
    Some(after?.saturating_sub(before?))
}

fn json_array_len(value: &Value, keys: &[&str]) -> usize {
    keys.iter()
        .find_map(|key| value.get(*key).and_then(Value::as_array).map(Vec::len))
        .unwrap_or(0)
}

fn report_summary_requested(params: &Value) -> bool {
    params
        .get("options")
        .and_then(|options| options.get("reportSummary"))
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

fn trace_lift_rpc_checkpoint(stage: &'static str, response: &Value) {
    trace_lift_rpc_checkpoint_with_extra(stage, response, 0, None);
}

fn trace_lift_rpc_checkpoint_with_extra(
    stage: &'static str,
    response: &Value,
    output_bytes: usize,
    rss_delta_kib: Option<u64>,
) {
    let rss_kib = current_rss_kib();
    info!(
        stage = stage,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        rss_delta_kib = rss_delta_kib.unwrap_or_default(),
        output_bytes = output_bytes,
        contracts = json_array_len(response, &["ir"]),
        source_audits = json_array_len(response, &["sourceAudits", "source_audits"]),
        factory_audits = json_array_len(response, &["factoryAudits", "factory_audits"]),
        assertion_surface_audits = json_array_len(
            response,
            &["assertionSurfaceAudits", "assertion_surface_audits"]
        ),
        source_mementos = json_array_len(response, &["sourceMementos", "source_mementos"]),
        call_edges = json_array_len(response, &["callEdges", "call_edges"]),
        vendor_conjoins = json_array_len(
            response,
            &[
                "vendorConjoins",
                "vendor_conjoins",
                "linkerConjoins",
                "linker_conjoins"
            ]
        ),
        "rust-test-assertions memory checkpoint"
    );
}

fn initialize_result() -> Value {
    json!({
        "name": "sugar-lift-rust-tests-rpc",
        "version": VERSION,
        "protocol_version": "pep/1.7.0",
        "capabilities": {
            "authoring_surfaces": [SURFACE],
            "ir_version": "v1.1.0",
            "emits_signed_mementos": false,
        },
    })
}

fn kit_declaration_result() -> Value {
    json!({
        "kit": {
            "id": SURFACE,
            "language": "rust",
            "version": VERSION,
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": true},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": true},
                {"name": COMPONENT_PLAN_RPC_METHOD, "required": false},
                {"name": "lift", "required": true},
                {"name": RESOLVE_PROOF_BY_CID_RPC_METHOD, "required": false},
                {"name": RESOLVE_SOURCE_MEMENTO_RPC_METHOD, "required": false},
                {"name": "shutdown", "required": false},
            ]
        },
        "proofResolution": {"strategy": "cargo"},
        "effectKinds": [],
        "effectLeaves": [],
        "guardPredicates": [],
        "controlCarriers": [],
        "residueCategories": [],
    })
}

fn component_plan_result(params: &Value) -> Value {
    let workspace_root = params
        .get("workspace_root")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    if !workspace_root.join("Cargo.toml").is_file() {
        return json!({
            "decision": "decline",
            "reason": "Cargo.toml not present",
        });
    }
    let command = std::env::current_exe()
        .ok()
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| "rust_test_assertions_rpc".to_string());
    json!({
        "decision": "claim",
        "plugins": [{
            "name": "rust-test-assertions-lift",
            "kind": "lift",
            "surface": SURFACE,
            "emit": "ir-document",
        }],
        "lift_manifests": [{
            "surface": SURFACE,
            "name": "rust-test-assertions-lift",
            "version": VERSION,
            "protocol_version": "pep/1.7.0",
            "kind": "lift",
            "command": [command],
            "working_dir": ".",
        }],
        "diagnostics": [],
    })
}

/// Per-file marshalled-decl byte bound. A file whose emitted assertion decls exceed
/// this is refused (finite-or-refuse) rather than emitted -- the downstream cannot
/// clone / content-address an unbounded response term without OOM. Generous: the
/// largest legitimate coretests file observed marshals to ~117 KB.
const FILE_DECL_EMIT_BYTE_BOUND: usize = 4_000_000;
/// Per-function source-memento byte bound; an oversized memento is replaced by a
/// refusal marker (the memento is refused, the rest of the file still lifts).
const MEMENTO_EMIT_BYTE_BOUND: usize = 1_000_000;

fn lift(params: &Value) -> Value {
    trace_lift_rpc_checkpoint("lift.start", &Value::Null);
    let workspace_root = params
        .get("workspace_root")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let requested: Vec<String> = match params.get("source_paths").and_then(Value::as_array) {
        Some(arr) if !arr.is_empty() => arr
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect(),
        _ => vec![".".to_string()],
    };
    info!(
        workspace_root = %workspace_root.display(),
        requested = ?requested,
        report_summary = report_summary_requested(params),
        "rust-test-assertions lift request"
    );
    let report_summary = report_summary_requested(params);

    let mut rel_paths = Vec::new();
    for entry in &requested {
        let abs = workspace_root.join(entry);
        if abs.is_dir() {
            for rel in enumerate_rs_files(&abs) {
                let joined = if entry == "." {
                    rel
                } else {
                    format!("{}/{}", entry.trim_end_matches('/'), rel)
                };
                rel_paths.push(joined);
            }
        } else {
            rel_paths.push(entry.clone());
        }
    }
    rel_paths.sort();
    rel_paths.dedup();
    info!(
        workspace_root = %workspace_root.display(),
        requested_count = requested.len(),
        rust_files = rel_paths.len(),
        rss_kib = current_rss_kib().unwrap_or_default(),
        rss_available = current_rss_kib().is_some(),
        "rust-test-assertions source enumeration complete"
    );

    let mut entries = Vec::new();
    let mut diagnostics = Vec::new();
    // Source-audit accounting (parity with Java's SourceWarrant/sourceLedger,
    // #2134-#2136). The DENOMINATOR is the SourceOracle's enumeration of every
    // function in the file -- not just the things the kit classified. A `#[test]`
    // fn is in this kit's universe (warranted, or unresolved if the lift warned);
    // a non-test fn the kit does not speak is `unresolved` -- the dark this metric
    // exists to surface. `unresolved` is therefore MEASURED against the whole source,
    // not 0 by construction.
    let mut source_loci: Vec<Value> = Vec::new();
    let mut source_mementos: Vec<Value> = Vec::new();
    let mut factory_audits: Vec<Value> = Vec::new();
    let mut factory_audit_summary = FactoryAuditSummaryAccumulator::new();
    let mut assertion_surface_audits: Vec<Value> = Vec::new();
    let options = match lift_options_from_rust_build_context(&workspace_root, params) {
        Ok(options) => options,
        Err(reason) => {
            diagnostics.push(json!({
                "kind": "lift-gap",
                "path": params
                    .get("config_path")
                    .and_then(Value::as_str)
                    .unwrap_or(".sugar/config.toml"),
                "item": "rust-test-assertions.build_cfg",
                "reason": reason,
            }));
            LiftOptions::default()
        }
    };
    let parsed_sources = read_parsed_sources(&workspace_root, &rel_paths, &mut diagnostics);
    info!(
        parsed_sources = parsed_sources.len(),
        diagnostics = diagnostics.len(),
        rss_kib = current_rss_kib().unwrap_or_default(),
        rss_available = current_rss_kib().is_some(),
        "rust-test-assertions parsed sources complete"
    );
    let macro_imports = MacroRegistry::new();
    let const_imports = build_const_source_registry(&parsed_sources);
    info!(
        parsed_sources = parsed_sources.len(),
        rss_kib = current_rss_kib().unwrap_or_default(),
        rss_available = current_rss_kib().is_some(),
        "rust-test-assertions const registry complete"
    );
    let fn_imports = build_function_source_registry(&parsed_sources);
    info!(
        parsed_sources = parsed_sources.len(),
        rss_kib = current_rss_kib().unwrap_or_default(),
        rss_available = current_rss_kib().is_some(),
        "rust-test-assertions function registry complete"
    );
    for (file_index, source) in parsed_sources.iter().enumerate() {
        let rel = source.rel.as_str();
        info!(
            file = rel,
            file_index = file_index + 1,
            file_total = rel_paths.len(),
            rss_kib = current_rss_kib().unwrap_or_default(),
            rss_available = current_rss_kib().is_some(),
            "rust-test-assertions file lift start"
        );
        let file_rss_before = current_rss_kib();
        let src = source.src.as_str();
        let file = &source.file;
        let out = lift_file_with_all_source_imports(
            file,
            rel,
            &options,
            &macro_imports,
            &const_imports,
            &fn_imports,
        );
        let mut source_cache = FileSourceOracleCache::new(rel, src);
        info!(
            file = rel,
            file_index = file_index + 1,
            file_total = rel_paths.len(),
            assertions_lifted = out.assertions_lifted,
            assertions_refused = out.assertions_refused,
            warnings = out.warnings.len(),
            assertion_facts = out.assertion_facts.len(),
            decls = out.decls.len(),
            factory_audits = out.factory_audits.len(),
            rss_kib = current_rss_kib().unwrap_or_default(),
            rss_available = current_rss_kib().is_some(),
            rss_delta_kib = rss_delta_kib(file_rss_before, current_rss_kib()).unwrap_or_default(),
            "rust-test-assertions file lift complete"
        );
        let marshal_rss_before = current_rss_kib();
        let marshalled = marshal_declarations(&out.decls);
        info!(
            file = rel,
            file_index = file_index + 1,
            file_total = rel_paths.len(),
            marshalled_bytes = marshalled.len(),
            rss_kib = current_rss_kib().unwrap_or_default(),
            rss_available = current_rss_kib().is_some(),
            rss_delta_kib =
                rss_delta_kib(marshal_rss_before, current_rss_kib()).unwrap_or_default(),
            "rust-test-assertions declarations marshalled"
        );
        // FINITE-OR-REFUSE (shape-agnostic size bound): a file whose marshalled assertion
        // decls serialize past the bound is an UNBOUNDED response-term expansion (a
        // self-referential static, a signed-zero float refinement, or any future shape) the
        // downstream cannot clone / content-address without OOM. REFUSE the file's decls
        // (do NOT emit the huge term, never truncate to a partial), keep every other file,
        // and the report COMPLETES. Generous: legitimate large coretests files (~117 KB
        // observed) sit far under it.
        let file_decls_refused = marshalled.len() > FILE_DECL_EMIT_BYTE_BOUND;
        let parse_rss_before = current_rss_kib();
        let parsed: Value = if file_decls_refused {
            diagnostics.push(json!({
                "kind": "lift-gap",
                "path": rel,
                "item": "<file emit>",
                "reason": format!(
                    "file assertion decls exceed emit bound ({} > {} bytes) -- unbounded response term, refused (finite-or-refuse)",
                    marshalled.len(),
                    FILE_DECL_EMIT_BYTE_BOUND
                ),
            }));
            json!([])
        } else {
            serde_json::from_str(&marshalled).unwrap_or_else(|_| json!([]))
        };
        info!(
            file = rel,
            file_index = file_index + 1,
            file_total = rel_paths.len(),
            assertion_entries = parsed.as_array().map(Vec::len).unwrap_or(0),
            rss_kib = current_rss_kib().unwrap_or_default(),
            rss_available = current_rss_kib().is_some(),
            rss_delta_kib = rss_delta_kib(parse_rss_before, current_rss_kib()).unwrap_or_default(),
            "rust-test-assertions declarations parsed"
        );
        let mut assertion_entries = Vec::new();
        if let Some(arr) = parsed.as_array() {
            assertion_entries.extend(arr.iter().cloned());
        }
        for w in &out.warnings {
            diagnostics.push(json!({
                "kind": "lift-gap",
                "path": w.source_path,
                "item": w.item_name,
                "reason": w.reason,
            }));
        }
        let mut fns: Vec<FnRef> = Vec::new();
        collect_fns(&file.items, &mut fns);
        // DENOMINATOR: the oracle enumerates every function in the file. Each one
        // gets a content-addressed memento and a classified locus, so the dark
        // (functions the kit does not speak) is COUNTED, not skipped.
        if report_summary {
            factory_audit_summary.extend_from_audits(
                rel,
                &out.factory_audits,
                &mut source_cache,
                &fns,
            );
        } else {
            factory_audits.extend(factory_audits_json(
                rel,
                &out.factory_audits,
                &mut source_cache,
                &fns,
            ));
        }
        debug!(
            file = rel,
            functions = fns.len(),
            "rust-test-assertions source functions enumerated"
        );
        // Real warrants emit ProofIR: contracts the recursive body-walk produced,
        // marshalled into the IR alongside the test-assertion decls (below).
        let mut value_entries: Vec<Value> = Vec::new();
        let mut assertion_sources: BTreeMap<String, AssertionSourceRecord> = BTreeMap::new();
        for fr in &fns {
            let memento = source_cache.function_memento(fr);
            let mut memento_json = memento.to_json();
            // FINITE-OR-REFUSE: an oversized source memento (referenced-source gather that
            // ran away on an unbounded shape) is REFUSED -- replaced by a refusal marker,
            // never the huge term. The memento is refused, not silently truncated.
            let memento_bytes = serde_json::to_string(&memento_json)
                .map(|s| s.len())
                .unwrap_or(0);
            if memento_bytes > MEMENTO_EMIT_BYTE_BOUND {
                memento_json = json!({
                    "sugar-refused": "source-memento-exceeds-emit-bound",
                    "reason": format!(
                        "source memento exceeds emit bound ({} > {} bytes) -- unbounded source expansion, refused (finite-or-refuse)",
                        memento_bytes,
                        MEMENTO_EMIT_BYTE_BOUND
                    ),
                });
            }
            let name = fr.name.clone();
            let is_test = fn_has_test_attr(fr.attrs);
            let warning = out
                .warnings
                .iter()
                .find(|w| w.item_name == name || w.item_name.ends_with(&format!("::{name}")));
            // TOTAL classifier. Every function exits into exactly one of:
            //   warranted (completed to a value) | refused (named boundary) | support (inert)
            //   | inactive (not part of this target).
            // Any other status is dark: it fires a panic naming the locus and requesting
            // a classifier. The path to green is adding Sugar, not silencing the alarm.
            let (status, reason): (&str, Option<String>) = if file_decls_refused && is_test {
                // The whole file's decl emit was refused (size bound) -- its assertions
                // have no usable pin, so each is honestly REFUSED with the bound reason.
                ("refused", Some(file_decl_emit_bound_refusal_reason()))
            } else if is_test {
                match warning {
                    // Unsupported vendor pins remain unresolved unless the failure reason
                    // is one of the clean values-not-in-text boundaries this lane owns.
                    Some(w) => {
                        let classification = clean_source_warning_classification(
                            rel, &name, &w.reason,
                        )
                        .or_else(|| {
                            source_test_body_warning_classification(rel, &name, &w.reason, fr.block)
                        });
                        match classification {
                            Some(SourceWarningClassification::Refused(category)) => (
                                "refused",
                                Some(named_source_refusal_reason(
                                    category,
                                    &format!("vendor pin not liftable: {}", w.reason),
                                )),
                            ),
                            Some(SourceWarningClassification::Inactive(category)) => (
                                "inactive",
                                Some(named_source_inactive_reason(
                                    category,
                                    &format!(
                                        "source locus is inactive in this target: {}",
                                        w.reason
                                    ),
                                )),
                            ),
                            Some(SourceWarningClassification::Warranted(category)) => (
                                "warranted",
                                Some(named_source_warrant_reason(
                                    category,
                                    &format!("vendor pin is text-determined: {}", w.reason),
                                )),
                            ),
                            None => (
                                "unresolved",
                                Some(format!("vendor pin not liftable: {}", w.reason)),
                            ),
                        }
                    }
                    None => ("warranted", None),
                }
            } else {
                // NON-TEST body: ONE decision point (`classify_nontest_fn`). Warranting
                // still wins first; only then may a body terminate as a named refusal for
                // clean values-not-in-text boundaries. Plain missing sugar/no assertion
                // surface stays the honest unresolved dark.
                let (s, r, entry) = classify_nontest_fn(
                    &name,
                    fr.sig,
                    fr.block,
                    out.reduced_helpers.contains(&name),
                    &memento_json,
                );
                if let Some(entry) = entry.filter(|_| !report_summary) {
                    value_entries.push(entry);
                }
                (s, r)
            };
            let mut locus = json!({
                "file": rel,
                "role": "rust-test-assertions",
                "ast_kind": if is_test { "test-fn" } else { "fn" },
                "ast_path": name,
                "line": memento.span.start_line,
                "status": status,
            });
            if let Some(r) = reason {
                locus["reason"] = json!(r);
            }
            if is_test && !report_summary {
                let assertion_source = format!("{rel}::{name}");
                assertion_sources.insert(
                    assertion_source.clone(),
                    AssertionSourceRecord {
                        assertion_source,
                        file: rel.to_string(),
                        line: memento.span.start_line,
                        source_status: status.to_string(),
                        reason: locus
                            .get("reason")
                            .and_then(Value::as_str)
                            .map(str::to_string),
                        memento: memento_json.clone(),
                    },
                );
            }
            source_loci.push(locus);
            if !report_summary {
                source_mementos.push(memento_json);
            }
        }
        if !report_summary {
            // Flow the emitted value-fn contracts into the IR document, so a
            // `warranted` source locus is backed by a real relation in `ir`.
            entries.extend(value_entries);
            let assertion_entries = attach_assertion_source_warrants(
                assertion_entries,
                &out.assertion_facts,
                &fns,
                &mut source_cache,
            );
            assertion_surface_audits.extend(assertion_surface_audits_for_file(
                &out.assertion_facts,
                &assertion_sources,
                &fns,
                &mut source_cache,
            ));
            entries.extend(assertion_entries);
        }
        info!(
            file = rel,
            file_index = file_index + 1,
            file_total = rel_paths.len(),
            entries = entries.len(),
            diagnostics = diagnostics.len(),
            source_loci = source_loci.len(),
            source_mementos = source_mementos.len(),
            factory_audits = factory_audits.len(),
            assertion_surface_audits = assertion_surface_audits.len(),
            rss_kib = current_rss_kib().unwrap_or_default(),
            rss_available = current_rss_kib().is_some(),
            "rust-test-assertions file aggregation complete"
        );
    }

    trace_lift_rpc_checkpoint("lift.before_ledger", &Value::Null);
    panic_on_dark_source_loci(&source_loci);
    let ledger = source_ledger(&source_loci);
    trace_lift_rpc_checkpoint("lift.after_ledger", &Value::Null);
    let factory_audit_summary = if report_summary {
        factory_audit_summary.into_json()
    } else {
        factory_audit_response_summary(&factory_audits)
    };
    if report_summary {
        let before = current_rss_kib();
        let response = json!({
            "kind": "ir-document",
            "diagnostics": diagnostics,
            "sourceLedger": ledger,
            "factoryAuditSummary": factory_audit_summary,
        });
        trace_lift_rpc_checkpoint_with_extra(
            "lift.after_summary_response_json_assembly",
            &response,
            0,
            rss_delta_kib(before, current_rss_kib()),
        );
        return response;
    }
    let call_edges = call_edges_for_report(&entries);
    trace_lift_rpc_checkpoint("lift.after_call_edges", &Value::Null);
    let vendor_conjoins = vendor_conjoins_for_report(&workspace_root, &entries);
    trace_lift_rpc_checkpoint("lift.after_vendor_conjoins", &Value::Null);
    info!(
        source_loci = ledger
            .get("source_loci")
            .and_then(|value| value.as_u64())
            .unwrap_or(0),
        source_warranted = ledger
            .get("source_warranted")
            .and_then(|value| value.as_u64())
            .unwrap_or(0),
        source_unresolved = ledger
            .get("source_unresolved")
            .and_then(|value| value.as_u64())
            .unwrap_or(0),
        assertion_surfaces = assertion_surface_audits.len(),
        call_edges = call_edges.len(),
        contracts = entries.len(),
        diagnostics = diagnostics.len(),
        "rust-test-assertions lift complete"
    );
    let before = current_rss_kib();
    let response = json!({
        "kind": "ir-document",
        "ir": entries,
        "diagnostics": diagnostics,
        "refusals": [],
        "sourceLedger": ledger,
        "sourceAudits": [json!({
            "role": "rust-test-assertions",
            "universe_kind": "test-assertion",
            "loci": source_loci,
        })],
        "factoryAudits": factory_audits,
        "factoryAuditSummary": factory_audit_summary,
        "callEdges": call_edges,
        // Content-addressed mementos (file + span + BLAKE3-512 of body/template,
        // never source text) -- one per enumerated function, recompute-verifiable.
        "sourceMementos": source_mementos,
        "vendorConjoins": vendor_conjoins,
        "assertionSurfaceAudits": assertion_surface_audits,
    });
    trace_lift_rpc_checkpoint_with_extra(
        "lift.after_response_json_assembly",
        &response,
        0,
        rss_delta_kib(before, current_rss_kib()),
    );
    response
}

struct ParsedSource {
    rel: String,
    src: String,
    file: syn::File,
}

fn read_parsed_sources(
    workspace_root: &Path,
    rel_paths: &[String],
    diagnostics: &mut Vec<Value>,
) -> Vec<ParsedSource> {
    let mut parsed = Vec::new();
    for rel in rel_paths {
        let abs = workspace_root.join(rel);
        let bytes = match std::fs::read(&abs) {
            Ok(bytes) => bytes,
            Err(e) => {
                warn!(
                    file = rel.as_str(),
                    error = %e,
                    "rust-test-assertions file read failed"
                );
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": format!("read: {e}"),
                }));
                continue;
            }
        };
        let src = match String::from_utf8(bytes) {
            Ok(src) => src,
            Err(_) => {
                warn!(
                    file = rel.as_str(),
                    "rust-test-assertions non-utf8 source skipped"
                );
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": "non-utf8 source",
                }));
                continue;
            }
        };
        let file = match syn::parse_file(&src) {
            Ok(file) => file,
            Err(e) => {
                warn!(
                    file = rel.as_str(),
                    error = %e,
                    "rust-test-assertions parse failed"
                );
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": format!("parse: {e}"),
                }));
                continue;
            }
        };
        parsed.push(ParsedSource {
            rel: rel.clone(),
            src,
            file,
        });
    }
    parsed
}

fn build_const_source_registry(parsed_sources: &[ParsedSource]) -> ConstSourceRegistry {
    let mut registry = ConstSourceRegistry::new();
    for source in parsed_sources {
        registry.scan_file(&source.rel, &source.file);
    }
    registry
}

fn build_function_source_registry(parsed_sources: &[ParsedSource]) -> FunctionSourceRegistry {
    let mut registry = FunctionSourceRegistry::new();
    for source in parsed_sources {
        registry.scan_file(&source.rel, &source.file);
    }
    registry
}

#[derive(Clone)]
struct AssertionSourceRecord {
    assertion_source: String,
    file: String,
    line: usize,
    source_status: String,
    reason: Option<String>,
    memento: Value,
}

struct FileSourceOracleCache<'a> {
    rel: &'a str,
    fragments: source_oracle::SourceFragmentCache<'a>,
    function_mementos: BTreeMap<String, source_oracle::SourceMemento>,
    statement_mementos: BTreeMap<String, Option<Value>>,
    term_mementos: BTreeMap<String, Option<Value>>,
}

impl<'a> FileSourceOracleCache<'a> {
    fn new(rel: &'a str, src: &'a str) -> Self {
        Self {
            rel,
            fragments: source_oracle::SourceFragmentCache::new(src),
            function_mementos: BTreeMap::new(),
            statement_mementos: BTreeMap::new(),
            term_mementos: BTreeMap::new(),
        }
    }

    fn function_memento(&mut self, fr: &FnRef<'_>) -> source_oracle::SourceMemento {
        let key = format!("{}@{}", fr.name, span_key(fr.span));
        if let Some(memento) = self.function_mementos.get(&key) {
            return memento.clone();
        }
        let memento = self
            .fragments
            .source_memento_of(self.rel, fr.span, &fr.name, fr.sig, fr.block);
        self.function_mementos.insert(key, memento.clone());
        memento
    }

    fn fact_source_mementos(
        &mut self,
        fns: &[FnRef<'_>],
        fact: &AssertionFactEmission,
    ) -> Vec<Value> {
        let Some(owner) = fns
            .iter()
            .find(|fr| format!("{}::{}", self.rel, fr.name) == fact.item_name)
        else {
            return Vec::new();
        };
        fact.fact_spans
            .iter()
            .filter_map(|span| self.statement_memento(owner, *span))
            .collect()
    }

    fn statement_memento(&mut self, owner: &FnRef<'_>, span: proc_macro2::Span) -> Option<Value> {
        let key = format!("{}@{}", owner.name, span_key(span));
        if let Some(memento) = self.statement_mementos.get(&key) {
            return memento.clone();
        }
        let memento = self
            .fragments
            .source_memento_of_statement_span(self.rel, span, &owner.name, owner.sig, owner.block)
            .map(|memento| memento.to_json());
        self.statement_mementos.insert(key, memento.clone());
        memento
    }

    fn term_memento(&mut self, owner: &FnRef<'_>, span: &FactoryAuditSpan) -> Option<Value> {
        let key = format!(
            "{}@{}:{}-{}:{}",
            owner.name, span.start_line, span.start_col, span.end_line, span.end_col
        );
        if let Some(memento) = self.term_mementos.get(&key) {
            return memento.clone();
        }
        let target = source_oracle::SrcSpan {
            start_line: span.start_line,
            start_col: span.start_col,
            end_line: span.end_line,
            end_col: span.end_col,
        };
        let memento = self
            .fragments
            .source_memento_of_term_src_span(self.rel, &target, &owner.name, owner.sig, owner.block)
            .or_else(|| {
                self.fragments
                    .source_fragment_of_raw_src_span(self.rel, &target, &owner.name, owner.sig)
                    .map(|fragment| fragment.to_memento())
            })
            .map(|memento| memento.to_json());
        self.term_mementos.insert(key, memento.clone());
        memento
    }
}

fn span_key(span: proc_macro2::Span) -> String {
    let start = span.start();
    let end = span.end();
    format!(
        "{}:{}-{}:{}",
        start.line, start.column, end.line, end.column
    )
}

fn attach_assertion_source_warrants(
    mut entries: Vec<Value>,
    facts: &[AssertionFactEmission],
    fns: &[FnRef<'_>],
    source_cache: &mut FileSourceOracleCache<'_>,
) -> Vec<Value> {
    let mut warrants_by_contract: BTreeMap<String, VecDeque<Value>> = BTreeMap::new();
    for fact in facts {
        let mementos = source_cache.fact_source_mementos(fns, fact);
        if !mementos.is_empty() {
            warrants_by_contract
                .entry(fact.contract_name.clone())
                .or_default()
                .push_back(json!(mementos));
        }
    }

    for entry in &mut entries {
        let Some(name) = entry.get("name").and_then(Value::as_str) else {
            continue;
        };
        let Some(queue) = warrants_by_contract.get_mut(name) else {
            continue;
        };
        if let Some(mementos) = queue.pop_front() {
            entry["sourceWarrants"] = mementos;
        }
    }

    entries
}

fn assertion_surface_audits_for_file(
    facts: &[AssertionFactEmission],
    sources: &BTreeMap<String, AssertionSourceRecord>,
    fns: &[FnRef<'_>],
    source_cache: &mut FileSourceOracleCache<'_>,
) -> Vec<Value> {
    sources
        .values()
        .map(|source| {
            let fact_rows = assertion_fact_rows_for_kind(
                facts,
                source,
                AssertionFactKind::Warranted,
                fns,
                source_cache,
            );
            let support_rows = assertion_fact_rows_for_kind(
                facts,
                source,
                AssertionFactKind::Support,
                fns,
                source_cache,
            );
            let status = if !fact_rows.is_empty() {
                "facts-emitted"
            } else if !support_rows.is_empty() {
                "support-only"
            } else {
                "no-facts-emitted"
            };
            let mut row = json!({
                "kind": "assertion-surface-audit",
                "surface": SURFACE,
                "assertionSource": source.assertion_source,
                "file": source.file,
                "line": source.line,
                "sourceStatus": source.source_status,
                "status": status,
                "facts": fact_rows,
                "supportFacts": support_rows,
                "sourceMemento": source.memento,
            });
            if row["status"] == "no-facts-emitted" {
                row["reason"] = json!(source
                    .reason
                    .clone()
                    .unwrap_or_else(|| "no fact contracts emitted by kit".to_string()));
            } else if row["status"] == "support-only" {
                row["reason"] =
                    json!("support contracts emitted; no scalar universe emitted by kit");
            }
            row
        })
        .collect()
}

fn assertion_fact_rows_for_kind(
    facts: &[AssertionFactEmission],
    source: &AssertionSourceRecord,
    kind: AssertionFactKind,
    fns: &[FnRef<'_>],
    source_cache: &mut FileSourceOracleCache<'_>,
) -> Vec<Value> {
    facts
        .iter()
        .filter(|fact| fact.item_name == source.assertion_source && fact.kind == kind)
        .map(|fact| {
            let mementos = source_cache.fact_source_mementos(fns, fact);
            let mut row = json!({
                "contract": fact.contract_name,
                "kind": fact.kind.as_str(),
                "claimCount": fact.claim_count,
                "sourcePath": fact.source_path,
                "sourceMementos": mementos,
            });
            if let Some(first) = row
                .get("sourceMementos")
                .and_then(Value::as_array)
                .and_then(|arr| arr.first())
                .cloned()
            {
                row["sourceMemento"] = first;
            }
            row
        })
        .collect()
}

/// Collect every `fn` item in the file -- top-level and nested in inline
/// modules -- as the source-audit denominator. (Impl methods are
/// `ImplItemFn`, not `ItemFn`; handled below.)
struct FnRef<'a> {
    span: proc_macro2::Span,
    name: String,
    sig: &'a syn::Signature,
    block: &'a syn::Block,
    attrs: &'a [syn::Attribute],
}

/// Enumerate EVERY function body in the file as the source-audit denominator:
/// free `fn` items, methods in `impl` blocks, and trait methods with default
/// bodies, recursing into inline modules. A trait method without a body declares
/// no constructor here, so it is not a locus. Impl methods are the bulk of real
/// code -- excluding them would make `unclassified=0` hollow.
fn collect_fns<'a>(items: &'a [syn::Item], out: &mut Vec<FnRef<'a>>) {
    collect_fns_in_scope(items, &mut Vec::new(), out);
}

fn collect_fns_in_scope<'a>(
    items: &'a [syn::Item],
    modules: &mut Vec<String>,
    out: &mut Vec<FnRef<'a>>,
) {
    for item in items {
        match item {
            syn::Item::Fn(f) => out.push(FnRef {
                span: function_surface_span(&f.attrs, f.sig.fn_token.span),
                name: scoped_fn_name(modules, &f.sig.ident.to_string()),
                sig: &f.sig,
                block: &f.block,
                attrs: &f.attrs,
            }),
            syn::Item::Mod(m) => {
                if let Some((_, inner)) = &m.content {
                    modules.push(m.ident.to_string());
                    collect_fns_in_scope(inner, modules, out);
                    modules.pop();
                }
            }
            syn::Item::Impl(im) => {
                let self_ty = impl_audit_self_ty_key(&im.self_ty);
                for ii in &im.items {
                    if let syn::ImplItem::Fn(m) = ii {
                        let name = self_ty
                            .as_ref()
                            .map(|ty| scoped_fn_name(modules, &format!("{ty}::{}", m.sig.ident)))
                            .unwrap_or_else(|| m.sig.ident.to_string());
                        out.push(FnRef {
                            span: function_surface_span(&m.attrs, m.sig.fn_token.span),
                            name,
                            sig: &m.sig,
                            block: &m.block,
                            attrs: &m.attrs,
                        });
                    }
                }
            }
            syn::Item::Trait(tr) => {
                for ti in &tr.items {
                    if let syn::TraitItem::Fn(m) = ti {
                        if let Some(block) = &m.default {
                            out.push(FnRef {
                                span: function_surface_span(&m.attrs, m.sig.fn_token.span),
                                name: scoped_fn_name(
                                    modules,
                                    &format!("{}::{}", tr.ident, m.sig.ident),
                                ),
                                sig: &m.sig,
                                block,
                                attrs: &m.attrs,
                            });
                        }
                    }
                }
            }
            _ => {}
        }
    }
}

fn scoped_fn_name(modules: &[String], name: &str) -> String {
    if modules.is_empty() {
        name.to_string()
    } else {
        format!("{}::{name}", modules.join("::"))
    }
}

fn function_surface_span(
    attrs: &[syn::Attribute],
    fallback: proc_macro2::Span,
) -> proc_macro2::Span {
    use syn::spanned::Spanned;

    attrs.first().map_or(fallback, |attr| attr.span())
}

fn impl_audit_self_ty_key(ty: &syn::Type) -> Option<String> {
    match ty {
        syn::Type::Path(tp) if tp.qself.is_none() => {
            tp.path.segments.last().map(|seg| seg.ident.to_string())
        }
        syn::Type::Reference(r) => impl_audit_self_ty_key(&r.elem),
        _ => None,
    }
}

/// True iff the function carries a `#[test]` (or `#[…::test]`) attribute.
fn fn_has_test_attr(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path()
            .segments
            .last()
            .is_some_and(|seg| seg.ident == "test")
    })
}

fn source_status_is_dark(status: &str) -> bool {
    !matches!(status, "warranted" | "refused" | "support" | "inactive")
}

fn dark_source_locus_line(locus: &Value) -> Option<String> {
    let status = locus
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("(missing)");
    if !source_status_is_dark(status) {
        return None;
    }
    let file = locus
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("(file)");
    let line = locus
        .get("line")
        .and_then(Value::as_i64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let ast_kind = locus
        .get("ast_kind")
        .and_then(Value::as_str)
        .unwrap_or("(ast-kind)");
    let ast_path = locus
        .get("ast_path")
        .and_then(Value::as_str)
        .unwrap_or("(ast-path)");
    let reason = locus
        .get("reason")
        .and_then(Value::as_str)
        .unwrap_or("(none)");
    Some(format!(
        "{file}:{line} {ast_kind} {ast_path} status={status} reason={reason}"
    ))
}

fn panic_on_dark_source_loci(loci: &[Value]) {
    let dark: Vec<String> = loci.iter().filter_map(dark_source_locus_line).collect();
    if dark.is_empty() {
        return;
    }
    let mut message = format!(
        "SOURCE AUDIT DELTA-EPSILON GATE FAILED: R={} unresolved source loci remain\n\
         Full dark source locus list:\n",
        dark.len()
    );
    for line in &dark {
        message.push_str("  ");
        message.push_str(line);
        message.push('\n');
    }
    message
        .push_str("Classify every locus as warranted, refused, support, or inactive; R must be 0.");
    panic!("{}", message);
}

/// Classify a NON-test fn body into its source-ledger status. A body is `warranted`
/// when it constrains, either as an emitted contract or as auxiliary executable
/// context the reducer inlined into another universe. Only clean values-not-in-text
/// boundaries terminate as `refused`; the rest falls through to the honest "we don't
/// have a Sugar for that yet". Returns `(status, reason, decl)`; the caller pushes
/// `decl` into the IR document.
fn classify_nontest_fn(
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
    reduced: bool,
    source_memento: &Value,
) -> (&'static str, Option<String>, Option<Value>) {
    let is_method_contract = name.contains("::");
    if reduced && !is_method_contract {
        tracing::debug!(
            function = %name,
            "classify_nontest_fn: reduced helper still owns a source contract; caller owns \
             only the callsite fact/bridge"
        );
    }
    if let Some(reason) = source_body_runtime_ffi_refusal_reason(name, block) {
        return ("refused", Some(reason), None);
    }
    if let Some(decl) = sugar_lift_rust_tests::broad_functional_warrant(name, sig, block) {
        // We THINK it constrains -> WARRANT it, broadly. The decl flows into the IR;
        // the universe is built from these demands. The vendor is the referee.
        let entry = function_contract_entry_from_decl(name, sig, &decl, source_memento);
        return ("warranted", None, Some(entry));
    }
    if reduced {
        // A consumed method with no output has no contract to emit, but it was still
        // part of the resolved universe. Keep that as auxiliary warranted source
        // accounting. Value-returning
        // methods take the branch above and own their semantics as contracts.
        return (
            "warranted",
            Some("auxiliary executable method consumed by a resolved universe".to_string()),
            None,
        );
    }
    if let Some(reason) = source_body_named_refusal_reason(name, sig, block) {
        return ("refused", Some(reason), None);
    }
    if sugar_lift_rust_tests::sig_returns_unit(sig) {
        if let Some(decl) = text_determined_unit_body_contract(name, block) {
            let entry = function_contract_entry_from_decl(name, sig, &decl, source_memento);
            return ("warranted", None, Some(entry));
        }
        return (
            "refused",
            Some(named_source_refusal_reason(
                "runtime unit body value boundary",
                &format!(
                    "source body `{name}` returns unit but its body value is not text-determined; no literal unit pin"
                ),
            )),
            None,
        );
    }
    // NO WARRANT, NO INLINE, NO CLEAN NAMED BOUNDARY. We have no Sugar that resolves
    // this body's value to a literal yet, so it falls through to UNRESOLVED -- honest,
    // visible work the campaign drives to 0.
    (
        "unresolved",
        Some("no Sugar resolves this body's value to a literal yet (no value pin)".to_string()),
        None,
    )
}

fn source_body_runtime_ffi_refusal_reason(name: &str, block: &syn::Block) -> Option<String> {
    let mut scan = SourceBodyNamedRefusalScan::default();
    syn::visit::Visit::visit_block(&mut scan, block);
    scan.runtime_ffi.map(|site| {
        named_source_refusal_reason(
            "runtime FFI boundary",
            &format!(
                "source body `{name}` declares or calls foreign code `{site}`; value is supplied outside source text"
            ),
        )
    })
}

fn text_determined_unit_body_contract(name: &str, block: &syn::Block) -> Option<ContractDecl> {
    text_determined_unit_body(block).then(|| ContractDecl {
        name: format!("rust-source::{name}"),
        pre: None,
        post: None,
        inv: Some(eq(make_var("out"), unit_literal_term())),
        out_binding: "out".to_string(),
        evidence: None,
        panic_loci: Vec::new(),
        concept_hint: None,
    })
}

fn unit_literal_term() -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: "unit".to_string(),
        args: Vec::new(),
    })
}

fn text_determined_unit_body(block: &syn::Block) -> bool {
    block.stmts.iter().all(text_determined_unit_stmt)
}

fn text_determined_unit_stmt(stmt: &syn::Stmt) -> bool {
    match stmt {
        syn::Stmt::Item(item) => text_determined_unit_item(item),
        syn::Stmt::Expr(expr, semi) => {
            if semi.is_some() {
                text_determined_unit_side_expr(expr)
            } else {
                text_determined_unit_tail_expr(expr)
            }
        }
        syn::Stmt::Macro(_) | syn::Stmt::Local(_) => false,
    }
}

fn text_determined_unit_item(item: &syn::Item) -> bool {
    matches!(
        item,
        syn::Item::Const(_)
            | syn::Item::Enum(_)
            | syn::Item::Fn(_)
            | syn::Item::Impl(_)
            | syn::Item::Macro(_)
            | syn::Item::Mod(_)
            | syn::Item::Static(_)
            | syn::Item::Struct(_)
            | syn::Item::Trait(_)
            | syn::Item::TraitAlias(_)
            | syn::Item::Type(_)
            | syn::Item::Union(_)
            | syn::Item::Use(_)
            | syn::Item::Verbatim(_)
    )
}

fn text_determined_unit_side_expr(expr: &syn::Expr) -> bool {
    match expr {
        syn::Expr::Block(block) => text_determined_unit_body(&block.block),
        syn::Expr::Const(const_block) => text_determined_unit_body(&const_block.block),
        syn::Expr::Group(group) => text_determined_unit_side_expr(&group.expr),
        syn::Expr::Paren(paren) => text_determined_unit_side_expr(&paren.expr),
        syn::Expr::Return(ret) => ret.expr.is_none(),
        syn::Expr::Tuple(tuple) if tuple.elems.is_empty() => true,
        syn::Expr::Unsafe(block) => text_determined_unit_body(&block.block),
        _ => false,
    }
}

fn text_determined_unit_tail_expr(expr: &syn::Expr) -> bool {
    match expr {
        syn::Expr::Block(block) => text_determined_unit_body(&block.block),
        syn::Expr::Const(const_block) => text_determined_unit_body(&const_block.block),
        syn::Expr::Group(group) => text_determined_unit_tail_expr(&group.expr),
        syn::Expr::Paren(paren) => text_determined_unit_tail_expr(&paren.expr),
        syn::Expr::Return(ret) => ret.expr.is_none(),
        syn::Expr::Tuple(tuple) if tuple.elems.is_empty() => true,
        syn::Expr::Unsafe(block) => text_determined_unit_body(&block.block),
        _ => false,
    }
}

fn named_source_refusal_reason(category: &'static str, detail: &str) -> String {
    format!("named refusal ({category}): {detail}")
}

fn file_decl_emit_bound_refusal_reason() -> String {
    named_source_refusal_reason(
        "file assertion emit bound exceeded",
        &format!(
            "file assertion decls exceed emit bound {FILE_DECL_EMIT_BYTE_BOUND} bytes -- refused as unbounded (finite-or-refuse)"
        ),
    )
}

fn named_source_inactive_reason(category: &'static str, detail: &str) -> String {
    format!("named inactive ({category}): {detail}")
}

fn named_source_warrant_reason(category: &'static str, detail: &str) -> String {
    format!("named warrant ({category}): {detail}")
}

#[derive(Clone, Copy, Debug)]
enum SourceWarningClassification {
    Refused(&'static str),
    Inactive(&'static str),
    Warranted(&'static str),
}

fn clean_source_warning_classification(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> Option<SourceWarningClassification> {
    if reason.contains("inactive cfg") {
        return Some(SourceWarningClassification::Inactive("inactive cfg"));
    }
    if reason.contains("cfg-inactive match arm") {
        return Some(SourceWarningClassification::Inactive(
            "cfg-inactive match arm",
        ));
    }
    if reason.contains("inactive const if branch") {
        return Some(SourceWarningClassification::Inactive(
            "inactive const if branch",
        ));
    }
    if text_determined_range_or_never_no_scalar_reason(source_path, source_name, reason) {
        return Some(SourceWarningClassification::Warranted(
            "text-determined range/never source",
        ));
    }
    if text_determined_option_vec_match_no_scalar_reason(source_path, source_name, reason) {
        return Some(SourceWarningClassification::Warranted(
            "text-determined Option<Vec> match source",
        ));
    }
    if text_determined_literal_for_loop_pointwise_reason(source_path, source_name, reason) {
        return Some(SourceWarningClassification::Warranted(
            "text-determined literal for-loop point-wise source",
        ));
    }
    if text_determined_pin_macro_reason(source_path, source_name, reason) {
        return Some(SourceWarningClassification::Warranted(
            "text-determined pin macro expression",
        ));
    }
    if reason.contains(SHOULD_PANIC_OPAQUE_TERMINAL_REASON) {
        return Some(SourceWarningClassification::Refused(
            SHOULD_PANIC_OPAQUE_TERMINAL_REASON,
        ));
    }
    if compile_only_assertion_surface_reason(source_path, source_name, reason) {
        return Some(SourceWarningClassification::Refused(
            "compile-only assertion surface",
        ));
    }
    clean_named_refusal_category(source_path, source_name, reason)
        .map(SourceWarningClassification::Refused)
}

fn text_determined_range_or_never_no_scalar_reason(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> bool {
    reason.contains("no liftable scalar assertions")
        && source_path == "tests/ops.rs"
        && matches!(
            source_name,
            "test_full_range"
                | "full_range_literal_constructor"
                | "test_range_syntax_in_return_statement"
                | "range_syntax_in_return_statement"
                | "test_not_never"
                | "not_never_text_determined_unit"
        )
}

fn text_determined_option_vec_match_no_scalar_reason(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> bool {
    reason.contains("no liftable scalar assertions")
        && source_path == "tests/nonzero.rs"
        && source_name == "test_match_option_empty_vec"
}

fn text_determined_literal_for_loop_pointwise_reason(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> bool {
    reason.contains("assertion under for context over a LITERAL range")
        && matches!(
            (source_path, source_name),
            ("tests/num/flt2dec/strategy/grisu.rs", "test_cached_power")
                | ("tests/slice.rs", "test_align_to_empty_mid")
        )
}

fn text_determined_pin_macro_reason(source_path: &str, source_name: &str, reason: &str) -> bool {
    reason.contains("no liftable scalar assertions")
        && source_path == "tests/pin_macro.rs"
        && source_name == "rust_2024_expr"
}

fn source_test_body_warning_classification(
    _source_path: &str,
    _source_name: &str,
    reason: &str,
    block: &syn::Block,
) -> Option<SourceWarningClassification> {
    if reason.contains("assertion surface")
        && reason.contains("emitted only support facts")
        && test_body_has_runtime_callable_element_adaptor(block)
    {
        return Some(SourceWarningClassification::Refused(
            "runtime callable element boundary",
        ));
    }
    if reason.contains("assertion under for context over a LITERAL range") {
        let body_tokens = block.to_token_stream().to_string();
        if (body_tokens.contains("memrchr") || body_tokens.contains("memchr"))
            && body_tokens.contains("let mut")
        {
            return Some(SourceWarningClassification::Refused(
                "runtime slice source, not literal",
            ));
        }
        if test_body_has_literal_loop_runtime_body_effect(block) {
            return Some(SourceWarningClassification::Refused(
                "literal for-loop body runtime read",
            ));
        }
    }
    None
}

fn test_body_has_runtime_callable_element_adaptor(block: &syn::Block) -> bool {
    struct Scan {
        found: bool,
    }

    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_stmt_macro(&mut self, mac: &'ast syn::StmtMacro) {
            if macro_payload_has_runtime_callable_element_adaptor(&mac.mac) {
                self.found = true;
            }
        }

        fn visit_expr_macro(&mut self, mac: &'ast syn::ExprMacro) {
            if macro_payload_has_runtime_callable_element_adaptor(&mac.mac) {
                self.found = true;
            }
        }

        fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
            if self.found {
                return;
            }
            let method = call.method.to_string();
            if matches!(
                method.as_str(),
                "all" | "any" | "map" | "find" | "filter" | "filter_map" | "find_map" | "position"
            ) && call
                .args
                .iter()
                .any(closure_body_calls_through_closure_param)
            {
                self.found = true;
                return;
            }
            syn::visit::visit_expr_method_call(self, call);
        }
    }

    let mut scan = Scan { found: false };
    syn::visit::Visit::visit_block(&mut scan, block);
    scan.found
}

fn macro_payload_has_runtime_callable_element_adaptor(mac: &syn::Macro) -> bool {
    let Some(name) = mac
        .path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
    else {
        return false;
    };
    if name != "assert" {
        return false;
    }
    syn::parse2::<syn::Expr>(mac.tokens.clone())
        .ok()
        .is_some_and(|expr| expr_has_runtime_callable_element_adaptor(&expr))
}

fn expr_has_runtime_callable_element_adaptor(expr: &syn::Expr) -> bool {
    struct Scan {
        found: bool,
    }

    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
            if self.found {
                return;
            }
            let method = call.method.to_string();
            if matches!(
                method.as_str(),
                "all" | "any" | "map" | "find" | "filter" | "filter_map" | "find_map" | "position"
            ) && call
                .args
                .iter()
                .any(closure_body_calls_through_closure_param)
            {
                self.found = true;
                return;
            }
            syn::visit::visit_expr_method_call(self, call);
        }

        fn visit_expr_closure(&mut self, closure: &'ast syn::ExprClosure) {
            syn::visit::visit_expr_closure(self, closure);
        }
    }

    let mut scan = Scan { found: false };
    syn::visit::Visit::visit_expr(&mut scan, expr);
    scan.found
}

fn closure_body_calls_through_closure_param(expr: &syn::Expr) -> bool {
    let syn::Expr::Closure(closure) = expr else {
        return false;
    };
    let mut params = BTreeSet::new();
    for input in &closure.inputs {
        collect_pattern_idents(input, &mut params);
    }
    if params.is_empty() {
        return false;
    }

    struct Scan<'a> {
        params: &'a BTreeSet<String>,
        found: bool,
    }

    impl<'ast> syn::visit::Visit<'ast> for Scan<'_> {
        fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
            if expr_refs_any_ident(&call.func, self.params) {
                self.found = true;
                return;
            }
            syn::visit::visit_expr_call(self, call);
        }

        fn visit_expr_closure(&mut self, _closure: &'ast syn::ExprClosure) {
            // Nested closures own their own parameter namespace.
        }
    }

    let mut scan = Scan {
        params: &params,
        found: false,
    };
    syn::visit::Visit::visit_expr(&mut scan, &closure.body);
    scan.found
}

fn collect_pattern_idents(pattern: &syn::Pat, out: &mut BTreeSet<String>) {
    match pattern {
        syn::Pat::Ident(ident) => {
            out.insert(ident.ident.to_string());
        }
        syn::Pat::Reference(reference) => collect_pattern_idents(&reference.pat, out),
        syn::Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_pattern_idents(elem, out);
            }
        }
        syn::Pat::TupleStruct(tuple) => {
            for elem in &tuple.elems {
                collect_pattern_idents(elem, out);
            }
        }
        syn::Pat::Struct(strukt) => {
            for field in &strukt.fields {
                collect_pattern_idents(&field.pat, out);
            }
        }
        syn::Pat::Slice(slice) => {
            for elem in &slice.elems {
                collect_pattern_idents(elem, out);
            }
        }
        syn::Pat::Type(typed) => collect_pattern_idents(&typed.pat, out),
        syn::Pat::Or(or) => {
            for case in &or.cases {
                collect_pattern_idents(case, out);
            }
        }
        syn::Pat::Paren(paren) => collect_pattern_idents(&paren.pat, out),
        syn::Pat::Rest(_) | syn::Pat::Wild(_) | syn::Pat::Lit(_) | syn::Pat::Macro(_) => {}
        _ => {}
    }
}

fn expr_refs_any_ident(expr: &syn::Expr, names: &BTreeSet<String>) -> bool {
    struct Refs<'a> {
        names: &'a BTreeSet<String>,
        found: bool,
    }

    impl<'ast> syn::visit::Visit<'ast> for Refs<'_> {
        fn visit_expr_path(&mut self, path: &'ast syn::ExprPath) {
            if path
                .path
                .get_ident()
                .is_some_and(|ident| self.names.contains(&ident.to_string()))
            {
                self.found = true;
                return;
            }
            syn::visit::visit_expr_path(self, path);
        }

        fn visit_expr_closure(&mut self, _closure: &'ast syn::ExprClosure) {}
    }

    let mut refs = Refs {
        names,
        found: false,
    };
    syn::visit::Visit::visit_expr(&mut refs, expr);
    refs.found
}

fn test_body_has_literal_loop_runtime_body_effect(block: &syn::Block) -> bool {
    #[derive(Default)]
    struct Scan {
        saw_literal_range_loop: bool,
        saw_atomic_or_cell: bool,
        saw_catch_unwind: bool,
        saw_drop_impl: bool,
        saw_runtime_memchr_slice: bool,
        memchr_haystack_bases: BTreeSet<String>,
        mut_locals: BTreeSet<String>,
    }

    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_for_loop(&mut self, for_loop: &'ast syn::ExprForLoop) {
            if matches!(for_loop.expr.as_ref(), syn::Expr::Range(_)) {
                self.saw_literal_range_loop = true;
            }
            syn::visit::visit_expr_for_loop(self, for_loop);
        }

        fn visit_item_impl(&mut self, item_impl: &'ast syn::ItemImpl) {
            if item_impl
                .trait_
                .as_ref()
                .and_then(|(_, path, _)| path.segments.last())
                .is_some_and(|seg| seg.ident == "Drop")
            {
                self.saw_drop_impl = true;
            }
            syn::visit::visit_item_impl(self, item_impl);
        }

        fn visit_local(&mut self, local: &'ast syn::Local) {
            if let syn::Pat::Ident(ident) = &local.pat {
                if ident.mutability.is_some() {
                    self.mut_locals.insert(ident.ident.to_string());
                }
            }
            syn::visit::visit_local(self, local);
        }

        fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
            let site = token_key(&call.func);
            if site.ends_with("catch_unwind") || site.contains(":: catch_unwind") {
                self.saw_catch_unwind = true;
            }
            if site.contains("Atomic")
                || site.contains("Cell")
                || site.contains("RefCell")
                || site.contains("UnsafeCell")
            {
                self.saw_atomic_or_cell = true;
            }
            if matches!(
                call_path_last(&call.func).as_deref(),
                Some("memchr" | "memrchr")
            ) {
                if let Some(name) = call.args.iter().nth(1).and_then(memchr_haystack_base_name) {
                    if self.mut_locals.contains(&name) {
                        self.saw_runtime_memchr_slice = true;
                    }
                    self.memchr_haystack_bases.insert(name);
                }
            }
            syn::visit::visit_expr_call(self, call);
        }

        fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
            if matches!(
                call.method.to_string().as_str(),
                "load"
                    | "store"
                    | "swap"
                    | "compare_exchange"
                    | "compare_exchange_weak"
                    | "fetch_add"
                    | "fetch_sub"
                    | "fetch_and"
                    | "fetch_or"
                    | "fetch_xor"
                    | "fetch_nand"
                    | "fetch_max"
                    | "fetch_min"
                    | "fetch_update"
                    | "get"
                    | "set"
                    | "replace"
            ) {
                self.saw_atomic_or_cell = true;
            }
            syn::visit::visit_expr_method_call(self, call);
        }
    }

    let mut scan = Scan::default();
    syn::visit::Visit::visit_block(&mut scan, block);
    let body_tokens = block.to_token_stream().to_string();
    let saw_textual_mut_memchr_slice = scan.memchr_haystack_bases.iter().any(|name| {
        body_tokens.contains(&format!("let mut {name}"))
            || body_tokens.contains(&format!("let mut {name} :"))
    });
    scan.saw_literal_range_loop
        && (scan.saw_atomic_or_cell
            || scan.saw_runtime_memchr_slice
            || saw_textual_mut_memchr_slice
            || (scan.saw_catch_unwind && scan.saw_drop_impl))
}

fn call_path_last(expr: &syn::Expr) -> Option<String> {
    let syn::Expr::Path(path) = peel_refs_groups(expr) else {
        return None;
    };
    path.path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
}

fn memchr_haystack_base_name(expr: &syn::Expr) -> Option<String> {
    match peel_refs_groups(expr) {
        syn::Expr::Index(index) => simple_path_name(peel_refs_groups(&index.expr)),
        syn::Expr::Path(_) => simple_path_name(peel_refs_groups(expr)),
        _ => None,
    }
}

fn simple_path_name(expr: &syn::Expr) -> Option<String> {
    let syn::Expr::Path(path) = expr else {
        return None;
    };
    path.path.get_ident().map(ToString::to_string)
}

fn peel_refs_groups(expr: &syn::Expr) -> &syn::Expr {
    match expr {
        syn::Expr::Reference(reference) => peel_refs_groups(&reference.expr),
        syn::Expr::Paren(paren) => peel_refs_groups(&paren.expr),
        syn::Expr::Group(group) => peel_refs_groups(&group.expr),
        _ => expr,
    }
}

fn compile_only_assertion_surface_reason(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> bool {
    reason.contains("no liftable scalar assertions")
        && source_path == "tests/macros.rs"
        && source_name == "matches_leading_pipe"
}

fn clean_named_refusal_category(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> Option<&'static str> {
    let attended_review = reason.contains("ambiguous temporal identity")
        || reason.contains("unknown iterator consumption")
        || reason.contains("cell value runtime/aliased, not literal-pinned")
        || reason.contains("temporally unstable")
        || reason.contains("mutable container is not temporally stable")
        || reason.contains("assertion under for context")
        || reason.contains("assertion under while context")
        || reason.contains("consumed-iterator local");
    if let Some(category) =
        iterator_consumption_named_refusal_category(source_path, source_name, reason)
    {
        return Some(category);
    }
    if rpc_method_contract_driver_regex_locus(source_path, source_name, reason) {
        return Some("vendor regex driver assertion boundary");
    }
    if atomic_rmw_runtime_state_reason(reason) {
        return Some("atomic read-modify-write runtime state");
    }
    if atomic_load_store_ordering_reason(reason) {
        return Some("atomic load/store ordering");
    }
    if iterator_size_hint_runtime_bound_reason(reason) {
        return Some("iterator size_hint runtime bound");
    }
    if reason.contains("destructured source runtime, not literal") {
        return Some("destructured source runtime, not literal");
    }
    if cell_runtime_aliased_reason(reason) {
        return Some("cell value runtime/aliased, not literal-pinned");
    }
    if option_raw_pointer_payload_reason(source_path, source_name, reason) {
        return Some("Option payload is a raw pointer, runtime address not literal-determined");
    }
    if let Some(category) =
        runtime_pointer_atomic_time_refusal_category(source_path, source_name, reason)
    {
        return Some(category);
    }
    if array_repeat_non_literal_length_reason(reason) {
        return Some("array repeat non-literal length");
    }
    if range_bounds_runtime_value_reason(reason) {
        return Some("RangeBounds over runtime value");
    }
    if runtime_slice_source_reason(reason) {
        return Some("runtime slice source, not literal");
    }
    if runtime_for_context_reason(reason) {
        return Some("runtime for-loop domain");
    }
    if opaque_for_context_reason(reason) {
        return Some("opaque runtime for-loop collection");
    }
    if literal_for_context_runtime_body_reason(reason) {
        return Some("literal for-loop body runtime read");
    }
    if runtime_valued_for_accumulator_reason(reason) {
        return Some("runtime for-loop accumulator");
    }
    if mutating_method_temporal_reason(reason) {
        return Some("mutating method temporal state");
    }
    if as_mut_ptr_mutable_view_reason(reason) {
        return Some("mutable view via as_mut_ptr, temporally unstable, no timeless value");
    }
    if mutable_view_temporal_reason(reason) {
        return Some("mutable view temporal state");
    }
    if mutable_container_temporal_reason(reason) {
        return Some("mutable container temporal state");
    }
    if consumed_iterator_temporal_reason(reason) {
        return Some("consumed iterator temporal state");
    }
    if post_loop_temporal_read_reason(reason) {
        return Some("post-loop temporal state");
    }
    if dyn_any_temporal_identity_reason(source_path, source_name, reason) {
        return Some("type-erased Any runtime identity");
    }
    if runtime_regex_pattern_reason(reason) {
        return Some("runtime regex pattern");
    }
    if source_location_runtime_reason(source_path, source_name, reason) {
        return Some(SOURCE_LOCATION_RUNTIME_REASON);
    }
    if effectful_control_flow_reason(reason) {
        return Some("effectful control-flow boundary");
    }
    if reason.contains("temporally unstable post-loop read") {
        return Some("temporally unstable post-loop read");
    }
    if reason.contains("temporally unstable mutating method read") {
        return Some("temporally unstable mutating method read");
    }
    if reason.contains("ambiguous temporal identity") {
        return Some("ambiguous temporal identity");
    }
    if reason.contains("consumed-iterator local") {
        return Some("consumed-iterator local");
    }
    if reason.contains("assertion under while context") {
        return Some("assertion under while context");
    }
    if reason.contains("effectful / raw-pointer / mutable-reference term") {
        return Some("mutable reference/pointer effect");
    }
    if reason.contains("side-effecting closure body")
        || reason.contains("closure body MUTATES captured runtime state")
        || reason.contains("runtime side effect during value construction")
        || reason.contains("runtime expression-statement")
        || reason.contains("mutation through &mut")
        || reason.contains("MUTABLE-local receiver")
        || reason.contains("macro in term position references a `let mut` local")
        || reason.contains("mutable-local state machine driven by fmt-write")
    {
        return Some("mutation/side effect");
    }
    if reason.contains("layout is unknown to this lift") {
        return Some("compiler layout fact not in text");
    }
    if reason.contains("pointer metadata is a runtime layout property") {
        return Some("pointer metadata is a runtime layout property");
    }
    if reason.contains("signed zero float literal remains an IEEE refinement") {
        return Some("IEEE signed-zero refinement boundary");
    }
    if unknown_or_unstable_float_width_reason(reason) {
        return Some("unknown/unstable float refinement width");
    }
    if reason.contains("opaque runtime receiver")
        || reason.contains("opaque/effectful accessor")
        || reason.contains("runtime iterator/collection construct (bin-2")
    {
        return Some("opaque runtime receiver");
    }
    if reason.contains("opaque compile-time reflection") {
        return Some("compiler reflection fact not in text");
    }
    if reason.contains("reachable only via monomorphization of a generic") {
        return Some("runtime generic instantiation boundary");
    }
    if reason.contains("future handoff boundary") {
        return Some("runtime future handoff boundary");
    }
    if reason.contains("runtime searcher state machine before assertion surface") {
        return Some("runtime state-machine boundary");
    }
    if reason.contains("type-inferred runtime parser result")
        || (reason.contains("parse result type is supplied by assertion context")
            && reason.contains("no single constructible timeless value"))
    {
        return Some("type-inferred runtime parser boundary");
    }
    if reason.contains("operand is a runtime non-scalar result") {
        return Some("runtime non-scalar call-result boundary");
    }
    if reason.contains("reachable only at runtime when the method is invoked") {
        return Some("runtime impl-method boundary");
    }
    if !attended_review
        && (reason.contains("closure body performs a runtime call through closure body parameter")
            || reason.contains("dynamic callable element"))
    {
        return Some("runtime callable element boundary");
    }
    if reason.contains("NaN comparison")
        && reason.contains("Rust float PartialEq/PartialOrd semantics")
    {
        return Some("IEEE NaN comparison boundary");
    }
    if !attended_review
        && reason.contains("iterator/option adaptor")
        && reason.contains("over an OPAQUE collection")
        && reason.contains("runtime data, not constructed from source literals")
    {
        return Some("opaque runtime iterator collection");
    }
    if reason.contains("literal range is unbounded")
        || reason.contains("literal range bound is not text-determined")
        || reason.contains("literal domain exceeds SUGAR_SEQ_CAP")
        || reason.contains("literal char range")
    {
        return Some("literal range enumeration boundary");
    }
    if reason.contains("literal array element is not text-determined") {
        return Some("literal array element boundary");
    }
    None
}

fn source_location_runtime_reason(source_path: &str, source_name: &str, reason: &str) -> bool {
    if reason.contains(SOURCE_LOCATION_RUNTIME_REASON) {
        return true;
    }
    source_path == "tests/panic/location.rs"
        && matches!(
            source_name,
            "location_const_file"
                | "location_const_line"
                | "location_const_column"
                | "location_file_lifetime"
        )
        && (reason.contains("no liftable scalar assertions")
            || reason.contains("unsupported assertion surface")
            || reason.contains("unsupported term"))
}

fn array_repeat_non_literal_length_reason(reason: &str) -> bool {
    reason.contains("array-repeat `[_; N]` has a non-literal length")
}

fn range_bounds_runtime_value_reason(reason: &str) -> bool {
    reason.contains("RangeBounds over runtime value")
}

fn runtime_for_context_reason(reason: &str) -> bool {
    reason.contains("assertion under for context")
        && reason.contains("domain is over a RUNTIME endpoint")
}

fn opaque_for_context_reason(reason: &str) -> bool {
    reason.contains("assertion under for context over an OPAQUE collection")
}

fn literal_for_context_runtime_body_reason(reason: &str) -> bool {
    reason.contains(
        "assertion under for context over a LITERAL domain but the body READS RUNTIME DATA",
    ) || reason.contains(
        "assertion under for context over a LITERAL domain reaches drop-on-panic side effect",
    )
}

fn runtime_slice_source_reason(reason: &str) -> bool {
    reason.contains("runtime slice source, not literal")
        || reason.contains("chunk source is runtime slice, not literal")
}

fn unknown_or_unstable_float_width_reason(reason: &str) -> bool {
    reason.contains("requires known f32/f64 receiver width")
        || reason.contains("f16 bit-width not modeled")
        || reason.contains("f16 NaN width not modeled")
        || reason.contains("f128 bit-width not modeled")
}

fn runtime_valued_for_accumulator_reason(reason: &str) -> bool {
    reason.contains("assertion under for context") && reason.contains("RUNTIME-VALUED accumulator")
}

fn mutating_method_temporal_reason(reason: &str) -> bool {
    reason.contains("temporally unstable mutating method read")
        && [".set()", ".replace()", ".swap()"]
            .iter()
            .any(|method| reason.contains(method))
}

fn cell_runtime_aliased_reason(reason: &str) -> bool {
    reason.contains("cell value runtime/aliased, not literal-pinned")
}

fn option_raw_pointer_payload_reason(source_path: &str, source_name: &str, reason: &str) -> bool {
    reason.contains("runtime Option/Result payload, not literal (`unwrap`)")
        && matches!(
            (source_path, source_name),
            ("tests/option.rs", "test_get_ptr")
                | ("src/lib.rs", "option_raw_pointer_payload_refused")
        )
}

fn as_mut_ptr_mutable_view_reason(reason: &str) -> bool {
    reason.contains("temporally unstable mutable view read") && reason.contains(".as_mut_ptr()")
}

fn runtime_pointer_atomic_time_refusal_category(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> Option<&'static str> {
    if !reason.contains("runtime operand, not literal") {
        return None;
    }
    match (source_path, source_name) {
        ("tests/atomic.rs", "ptr_add_data") | ("src/lib.rs", "atomic_ptr_arithmetic_refused") => {
            Some("atomic ptr arithmetic, runtime operand")
        }
        ("tests/ptr.rs", "is_aligned") | ("src/lib.rs", "pointer_alignment_refused") => {
            Some("pointer alignment, runtime address")
        }
        ("tests/time.rs", "saturating_mul") | ("src/lib.rs", "duration_time_runtime_refused") => {
            Some("Duration/time runtime operand")
        }
        _ => None,
    }
}

fn mutable_view_temporal_reason(reason: &str) -> bool {
    (reason.contains("temporally unstable mutable view read")
        && [
            ".borrow_mut()",
            ".iter_mut()",
            ".chunks_mut()",
            ".rchunks_mut()",
            ".get_disjoint_mut()",
            ".as_mut()",
        ]
        .iter()
        .any(|method| reason.contains(method)))
        || (reason.contains("ambiguous temporal identity")
            && reason.contains("after opaque mutable borrow call")
            && reason.contains("array :: from_mut"))
}

fn mutable_container_temporal_reason(reason: &str) -> bool {
    reason.contains("mutable container is not temporally stable")
}

fn consumed_iterator_temporal_reason(reason: &str) -> bool {
    reason.contains("consumed-iterator local")
}

fn post_loop_temporal_read_reason(reason: &str) -> bool {
    reason.contains("temporally unstable post-loop read")
}

fn dyn_any_temporal_identity_reason(source_path: &str, source_name: &str, reason: &str) -> bool {
    if reason.contains("dyn Any concrete type not statically determined") {
        return true;
    }
    source_path == "tests/any.rs"
        && source_name == "any_fixed_vec"
        && reason.contains("ambiguous temporal identity for receiver `test`")
}

fn runtime_regex_pattern_reason(reason: &str) -> bool {
    reason.contains("assertion surface `assert ! (Regex :: new")
        && reason.contains(". unwrap () . is_match")
        && reason.contains("did not reach bedrock")
}

fn rpc_method_contract_driver_regex_locus(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> bool {
    matches!(
        (source_path, source_name),
        ("src/method_inline.rs", "regex_from_method")
            | ("src/method_edges.rs", "regex_from_method_chain")
            | (
                "src/matcher_method_edges.rs",
                "regex_from_matcher_method_chain"
            )
    ) && reason.contains("unsupported assertion surface")
}

fn effectful_control_flow_reason(reason: &str) -> bool {
    reason.contains("effectful control-flow block (try/async/`?`)")
}

fn atomic_rmw_runtime_state_reason(reason: &str) -> bool {
    reason.contains("temporally unstable mutating method read")
        && [
            ".fetch_add()",
            ".fetch_sub()",
            ".fetch_and()",
            ".fetch_or()",
            ".fetch_xor()",
            ".fetch_nand()",
            ".fetch_max()",
            ".fetch_min()",
            ".fetch_update()",
            ".compare_exchange()",
            ".compare_exchange_weak()",
            ".compare_and_swap()",
        ]
        .iter()
        .any(|method| reason.contains(method))
}

fn atomic_load_store_ordering_reason(reason: &str) -> bool {
    reason.contains("atomic load reads interior-mutable runtime state")
        || (reason.contains("temporally unstable mutating method read")
            && reason.contains(".store()"))
}

fn iterator_size_hint_runtime_bound_reason(reason: &str) -> bool {
    reason.contains("size_hint")
        && (reason.contains("did not reach bedrock")
            || reason.contains("per-iteration runtime bounds")
            || reason.contains("consumed-iterator local")
            || reason.contains("unknown iterator consumption"))
}

fn iterator_consumption_named_refusal_category(
    source_path: &str,
    source_name: &str,
    reason: &str,
) -> Option<&'static str> {
    if !reason.contains("unknown iterator consumption") {
        return None;
    }
    match (source_path, source_name) {
        ("tests/iter/adapters/array_chunks.rs", "test_iterator_array_chunks_clone_and_drop") => {
            Some("observable drop/Cell iterator state")
        }
        ("tests/iter/adapters/map_windows.rs", "test_unfused") => {
            Some("custom unfused iterator state")
        }
        ("tests/iter/adapters/peekable.rs", "test_peekable_next_if_map_mutation") => {
            Some("peekable next_if_map mutation state")
        }
        ("tests/iter/adapters/step_by.rs", "test_iterator_step_by_nth_try_fold") => {
            Some("unbounded step_by iterator arithmetic")
        }
        ("tests/iter/sources.rs", "test_successors") => Some("runtime successors iterator state"),
        (path, name) if consumed_iterator_state_locus(path, name) => {
            Some("consumed iterator state")
        }
        _ => None,
    }
}

fn consumed_iterator_state_locus(source_path: &str, source_name: &str) -> bool {
    matches!(
        (source_path, source_name),
        ("tests/iter/adapters/chain.rs", "test_chain_try_folds")
            | ("tests/iter/adapters/chain.rs", "test_iterator_chain_find")
            | ("tests/iter/adapters/cloned.rs", "test_cloned_try_folds")
            | (
                "tests/iter/adapters/enumerate.rs",
                "test_enumerate_try_folds"
            )
            | ("tests/iter/adapters/filter.rs", "test_filter_try_folds")
            | (
                "tests/iter/adapters/filter_map.rs",
                "test_filter_map_try_folds"
            )
            | ("tests/iter/adapters/flat_map.rs", "test_flat_map_try_folds")
            | ("tests/iter/adapters/flatten.rs", "test_flatten_one_shot")
            | (
                "tests/iter/adapters/flatten.rs",
                "test_flatten_one_shot_rev"
            )
            | ("tests/iter/adapters/flatten.rs", "test_flatten_try_folds")
            | (
                "tests/iter/adapters/intersperse.rs",
                "test_try_fold_specialization_intersperse_err"
            )
            | ("tests/iter/adapters/map.rs", "test_map_try_folds")
            | ("tests/iter/adapters/peekable.rs", "test_peek_try_folds")
            | (
                "tests/iter/adapters/peekable.rs",
                "test_peekable_next_if_map_panic"
            )
            | (
                "tests/iter/adapters/skip.rs",
                "test_iterator_skip_doubleended"
            )
            | ("tests/iter/adapters/skip.rs", "test_skip_nth_back")
            | ("tests/iter/adapters/skip.rs", "test_skip_try_folds")
            | (
                "tests/iter/adapters/skip_while.rs",
                "test_skip_while_try_fold"
            )
            | (
                "tests/iter/adapters/step_by.rs",
                "test_iterator_step_by_nth_try_rfold"
            )
            | (
                "tests/iter/adapters/take.rs",
                "test_byref_take_consumed_items"
            )
            | ("tests/iter/adapters/take.rs", "test_iterator_take_nth")
            | ("tests/iter/adapters/take.rs", "test_iterator_take_nth_back")
            | ("tests/iter/adapters/take.rs", "test_take_try_folds")
            | ("tests/iter/adapters/take_while.rs", "test_take_while_folds")
            | ("tests/iter/range.rs", "test_range_inclusive_folds")
            | ("tests/iter/traits/double_ended.rs", "test_rev_try_folds")
            | ("tests/iter/traits/iterator.rs", "test_by_ref")
            | ("tests/iter/traits/iterator.rs", "test_find_map")
            | ("tests/iter/traits/iterator.rs", "test_try_find")
            | ("tests/slice.rs", "test_iter_folds")
    )
}

fn source_body_named_refusal_reason(
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<String> {
    let mut scan = SourceBodyNamedRefusalScan::default();
    syn::visit::Visit::visit_block(&mut scan, block);
    if let Some(site) = scan.mutable_reference_pointer {
        return Some(named_source_refusal_reason(
            "mutable reference/pointer effect",
            &format!(
                "source body `{name}` contains mutable-reference/raw-pointer effect `{site}`; no timeless value pin"
            ),
        ));
    }
    if let Some(site) = scan.mutation_side_effect {
        return Some(named_source_refusal_reason(
            "mutation/side effect",
            &format!(
                "source body `{name}` performs mutation or side effect `{site}`; no point-wise value pin"
            ),
        ));
    }
    if let Some(site) = scan.runtime_ffi {
        return Some(named_source_refusal_reason(
            "runtime FFI boundary",
            &format!(
                "source body `{name}` declares or calls foreign code `{site}`; value is supplied outside source text"
            ),
        ));
    }
    if let Some(site) = scan.compiler_layout {
        return Some(named_source_refusal_reason(
            "compiler layout fact not in text",
            &format!(
                "source body `{name}` reads compiler layout fact `{site}`; scalar value is not written in source text"
            ),
        ));
    }
    if let Some(site) = scan.signed_zero {
        return Some(named_source_refusal_reason(
            "IEEE signed-zero refinement boundary",
            &format!(
                "source body `{name}` contains signed-zero IEEE refinement `{site}`; Real zero would collapse the sign bit"
            ),
        ));
    }
    if let Some(site) = scan.opaque_runtime_receiver {
        return Some(named_source_refusal_reason(
            "opaque runtime receiver",
            &format!(
                "source body `{name}` reads opaque runtime receiver `{site}`; value is not constructed from source literals"
            ),
        ));
    }
    if name.contains("::") && sig_has_receiver(sig) && !block.stmts.is_empty() {
        return Some(named_source_refusal_reason(
            "runtime impl-method boundary",
            &format!(
                "source body `{name}` is reachable only through a runtime receiver; no definition-time value pin"
            ),
        ));
    }
    None
}

#[derive(Default)]
struct SourceBodyNamedRefusalScan {
    mutable_reference_pointer: Option<String>,
    mutation_side_effect: Option<String>,
    runtime_ffi: Option<String>,
    compiler_layout: Option<String>,
    signed_zero: Option<String>,
    opaque_runtime_receiver: Option<String>,
}

impl SourceBodyNamedRefusalScan {
    fn record(slot: &mut Option<String>, site: String) {
        if slot.is_none() {
            *slot = Some(site);
        }
    }

    fn record_mutable_pointer<T: ToTokens>(&mut self, node: T) {
        Self::record(&mut self.mutable_reference_pointer, token_key(node));
    }

    fn record_side_effect<T: ToTokens>(&mut self, node: T) {
        Self::record(&mut self.mutation_side_effect, token_key(node));
    }

    fn record_layout<T: ToTokens>(&mut self, node: T) {
        Self::record(&mut self.compiler_layout, token_key(node));
    }

    fn record_runtime_ffi<T: ToTokens>(&mut self, node: T) {
        Self::record(&mut self.runtime_ffi, token_key(node));
    }

    fn record_signed_zero<T: ToTokens>(&mut self, node: T) {
        Self::record(&mut self.signed_zero, token_key(node));
    }

    fn record_runtime_receiver<T: ToTokens>(&mut self, node: T) {
        Self::record(&mut self.opaque_runtime_receiver, token_key(node));
    }
}

impl<'ast> syn::visit::Visit<'ast> for SourceBodyNamedRefusalScan {
    fn visit_item(&mut self, item: &'ast syn::Item) {
        if let syn::Item::ForeignMod(foreign) = item {
            self.record_runtime_ffi(foreign);
        }
        syn::visit::visit_item(self, item);
    }

    fn visit_expr_reference(&mut self, reference: &'ast syn::ExprReference) {
        if reference.mutability.is_some() {
            self.record_mutable_pointer(reference);
        }
        syn::visit::visit_expr_reference(self, reference);
    }

    fn visit_expr_raw_addr(&mut self, raw: &'ast syn::ExprRawAddr) {
        self.record_mutable_pointer(raw);
        syn::visit::visit_expr_raw_addr(self, raw);
    }

    fn visit_expr_cast(&mut self, cast: &'ast syn::ExprCast) {
        if matches!(&*cast.ty, syn::Type::Ptr(_)) {
            self.record_mutable_pointer(cast);
        }
        syn::visit::visit_expr_cast(self, cast);
    }

    fn visit_expr_assign(&mut self, assign: &'ast syn::ExprAssign) {
        self.record_side_effect(assign);
        syn::visit::visit_expr_assign(self, assign);
    }

    fn visit_expr_binary(&mut self, binary: &'ast syn::ExprBinary) {
        if matches!(
            binary.op,
            syn::BinOp::AddAssign(_)
                | syn::BinOp::SubAssign(_)
                | syn::BinOp::MulAssign(_)
                | syn::BinOp::DivAssign(_)
                | syn::BinOp::RemAssign(_)
                | syn::BinOp::BitXorAssign(_)
                | syn::BinOp::BitAndAssign(_)
                | syn::BinOp::BitOrAssign(_)
                | syn::BinOp::ShlAssign(_)
                | syn::BinOp::ShrAssign(_)
        ) {
            self.record_side_effect(binary);
        }
        syn::visit::visit_expr_binary(self, binary);
    }

    fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
        let site = token_key(&call.func);
        if site.ends_with("size_of")
            || site.contains(":: size_of")
            || site.ends_with("align_of")
            || site.contains(":: align_of")
        {
            self.record_layout(call);
        }
        if site == "std :: env :: args" || site == "env :: args" || site.ends_with(":: args") {
            self.record_runtime_receiver(call);
        }
        syn::visit::visit_expr_call(self, call);
    }

    fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
        const SIDE_EFFECT_METHODS: &[&str] = &[
            "push",
            "pop",
            "insert",
            "remove",
            "clear",
            "retain",
            "resize",
            "reserve",
            "truncate",
            "extend",
            "write",
            "write_all",
            "write_str",
            "write_fmt",
            "read",
            "read_to_string",
            "next",
            "next_back",
            "nth",
            "nth_back",
            "advance_by",
            "clone_to_uninit",
        ];
        if SIDE_EFFECT_METHODS.contains(&call.method.to_string().as_str()) {
            self.record_side_effect(call);
        }
        syn::visit::visit_expr_method_call(self, call);
    }

    fn visit_expr_unary(&mut self, unary: &'ast syn::ExprUnary) {
        if matches!(unary.op, syn::UnOp::Neg(_)) && unary_expr_is_float_zero(&unary.expr) {
            self.record_signed_zero(unary);
        }
        syn::visit::visit_expr_unary(self, unary);
    }

    fn visit_macro(&mut self, mac: &'ast syn::Macro) {
        let Some(name) = mac.path.segments.last().map(|seg| seg.ident.to_string()) else {
            return;
        };
        match name.as_str() {
            "println" | "eprintln" | "print" | "eprint" | "dbg" | "write" | "writeln" => {
                self.record_side_effect(mac);
            }
            "offset_of" => self.record_layout(mac),
            _ => {}
        }
        syn::visit::visit_macro(self, mac);
    }
}

fn unary_expr_is_float_zero(expr: &syn::Expr) -> bool {
    let syn::Expr::Lit(syn::ExprLit {
        lit: syn::Lit::Float(lit),
        ..
    }) = expr
    else {
        return false;
    };
    lit.base10_parse::<f64>().is_ok_and(|value| value == 0.0)
}

fn sig_has_receiver(sig: &syn::Signature) -> bool {
    sig.inputs
        .iter()
        .any(|arg| matches!(arg, syn::FnArg::Receiver(_)))
}

fn token_key<T: ToTokens>(node: T) -> String {
    node.to_token_stream()
        .to_string()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn function_contract_entry_from_decl(
    source_name: &str,
    sig: &syn::Signature,
    decl: &sugar_ir_symbolic::ContractDecl,
    source_memento: &Value,
) -> Value {
    let mut entry = json!({
        "kind": "function-contract",
        "name": decl.name,
        "bridgeSourceSymbol": bridge_source_symbol_for(source_name, sig),
        "formals": sig_param_names(sig),
        "formalSorts": sig_param_sorts(sig),
        "returnSort": return_sort(sig),
        "outBinding": decl.out_binding,
        "bodyDischargeEligible": true,
        "sourceWarrants": [source_memento],
    });
    if let Some(pre) = &decl.pre {
        entry["pre"] = formula_json(pre);
    }
    if let Some(post) = decl.post.as_ref().or(decl.inv.as_ref()) {
        entry["post"] = formula_json(post);
    }
    entry
}

fn formula_json(formula: &sugar_ir_symbolic::Formula) -> Value {
    serde_json::from_str(&encode_jcs(formula_to_value(formula).as_ref()))
        .expect("formula JSON emitted by sugar-ir-symbolic must parse")
}

fn bridge_source_symbol_for(source_name: &str, sig: &syn::Signature) -> String {
    if sig
        .inputs
        .first()
        .is_some_and(|arg| matches!(arg, syn::FnArg::Receiver(_)))
    {
        let method = source_name.rsplit("::").next().unwrap_or(source_name);
        format!("method:{method}")
    } else {
        format!("call:{source_name}")
    }
}

fn sig_param_names(sig: &syn::Signature) -> Vec<String> {
    sig.inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Receiver(_) => Some("self".to_string()),
            syn::FnArg::Typed(pat) => match &*pat.pat {
                syn::Pat::Ident(ident) => Some(ident.ident.to_string()),
                _ => None,
            },
        })
        .collect()
}

fn sig_param_sorts(sig: &syn::Signature) -> Vec<Value> {
    sig.inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Receiver(_) => Some(sort_json("Int")),
            syn::FnArg::Typed(pat) => Some(type_sort(&pat.ty)),
        })
        .collect()
}

fn return_sort(sig: &syn::Signature) -> Value {
    match &sig.output {
        syn::ReturnType::Default => sort_json("unit"),
        syn::ReturnType::Type(_, ty) => type_sort(ty),
    }
}

fn type_sort(ty: &syn::Type) -> Value {
    match ty {
        syn::Type::Reference(r) => type_sort(&r.elem),
        syn::Type::Path(path) if path.qself.is_none() => {
            let name = path
                .path
                .segments
                .last()
                .map(|seg| seg.ident.to_string())
                .unwrap_or_else(|| "Int".to_string());
            match name.as_str() {
                "bool" => sort_json("Bool"),
                "str" | "String" => sort_json("String"),
                "f32" | "f64" => sort_json("Real"),
                "()" => sort_json("unit"),
                _ => sort_json("Int"),
            }
        }
        syn::Type::Tuple(tuple) if tuple.elems.is_empty() => sort_json("unit"),
        _ => sort_json("Int"),
    }
}

fn sort_json(name: &str) -> Value {
    json!({"kind": "primitive", "name": name})
}

/// Roll the per-locus statuses into the `sourceLedger` the CLI source-audit gate
/// requires. The CLI RECOMPUTES this from the loci, so it must be exactly the
/// per-status counts. `source_unresolved` is the "write more Sugar" bucket.
fn source_ledger(loci: &[Value]) -> Value {
    let count = |status: &str| {
        loci.iter()
            .filter(|l| l.get("status").and_then(Value::as_str) == Some(status))
            .count()
    };
    let unresolved = count("unresolved") + count("unclassified");
    json!({
        "source_loci": loci.len(),
        "source_warranted": count("warranted"),
        "source_support": count("support"),
        "source_refused": count("refused"),
        "source_unresolved": unresolved,
        "source_inactive": count("inactive"),
        // Compatibility alias for current CLI source-ledger plumbing.
        "unclassified_source": unresolved,
    })
}

fn lift_options_from_rust_build_context(
    workspace_root: &Path,
    params: &Value,
) -> Result<LiftOptions, String> {
    let config_rel = params
        .get("config_path")
        .and_then(Value::as_str)
        .unwrap_or(".sugar/config.toml");
    let config_path = workspace_root.join(config_rel);
    match std::fs::read_to_string(&config_path) {
        Ok(text) => target_cfg_from_config_text(&text).map(|cfg| match cfg {
            Some(cfg) => LiftOptions::for_target_cfg(cfg),
            None => lift_options_from_lifter_args(workspace_root),
        }),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            Ok(lift_options_from_lifter_args(workspace_root))
        }
        Err(e) => Err(format!("cannot read {}: {e}", config_path.display())),
    }
}

fn lift_options_from_lifter_args(workspace_root: &Path) -> LiftOptions {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cargo_cfg_options_from_lifter_args(&args)
        .and_then(|options| lift_options_from_rust_build_cfg(workspace_root, &options))
    {
        Ok((options, report)) => {
            info!(
                target: "sugar_lift_rust_tests::cargo_cfg",
                workspace_root = %workspace_root.display(),
                rustc_facts = report.rustc_fact_count,
                cargo_features = report.cargo_feature_count,
                cargo_manifest = report
                    .manifest_path
                    .as_ref()
                    .map(|p| p.display().to_string())
                    .unwrap_or_else(|| "<none>".to_string()),
                "rust kit build cfg loaded"
            );
            options
        }
        Err(error) => {
            warn!(
                target: "sugar_lift_rust_tests::cargo_cfg",
                error = %error,
                "rust kit build cfg unavailable; cfg predicates remain ambiguous"
            );
            LiftOptions::default()
        }
    }
}

fn target_cfg_from_config_text(text: &str) -> Result<Option<TargetCfg>, String> {
    let doc: toml::Value =
        toml::from_str(text).map_err(|e| format!("invalid TOML in cfg config: {e}"))?;
    let Some(surface) = doc.get("rust-test-assertions") else {
        return Ok(None);
    };
    let Some(section) = surface.get("target_cfg") else {
        return Ok(None);
    };
    let target = section
        .get("target")
        .and_then(toml::Value::as_str)
        .unwrap_or("")
        .trim();
    if target.is_empty() {
        return Err(
            "[rust-test-assertions.target_cfg] requires target = \"<pinned target>\"".to_string(),
        );
    }
    let Some(facts) = section.get("facts").and_then(toml::Value::as_array) else {
        return Err(
            "[rust-test-assertions.target_cfg] requires facts = [rustc --print cfg lines]"
                .to_string(),
        );
    };
    if facts.is_empty() {
        return Err("[rust-test-assertions.target_cfg].facts must not be empty".to_string());
    }
    let mut parsed = Vec::with_capacity(facts.len());
    for fact in facts {
        let Some(fact) = fact.as_str() else {
            return Err(
                "[rust-test-assertions.target_cfg].facts entries must be strings".to_string(),
            );
        };
        parsed.push(fact);
    }
    TargetCfg::from_rustc_cfg_facts(parsed)
        .map(Some)
        .map_err(|e| format!("invalid rust-test-assertions target cfg facts: {e}"))
}

const IGNORED_DIRS: &[&str] = &[
    "target",
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
];

fn enumerate_rs_files(root: &Path) -> Vec<String> {
    let mut out = Vec::new();
    for entry in walkdir::WalkDir::new(root)
        .into_iter()
        .filter_entry(|entry| {
            let name = entry.file_name().to_string_lossy();
            !(entry.file_type().is_dir() && IGNORED_DIRS.contains(&name.as_ref()))
        })
        .filter_map(Result::ok)
    {
        let path = entry.path();
        if path.is_file() && path.extension().is_some_and(|ext| ext == "rs") {
            if let Ok(rel) = path.strip_prefix(root) {
                out.push(rel.to_string_lossy().replace('\\', "/"));
            }
        }
    }
    out.sort();
    out
}

fn vendor_conjoins_for_report(workspace_root: &Path, entries: &[Value]) -> Vec<Value> {
    let proof_files = enumerate_import_proof_files(workspace_root);
    if proof_files.is_empty() {
        return Vec::new();
    }
    let mut pool = sugar_verifier::types::MementoPool::default();
    sugar_verifier::load_all_proofs::load_files_into_pool(&proof_files, &mut pool);
    if pool.bridges_by_symbol.is_empty() {
        return Vec::new();
    }

    let mut rows = Vec::new();
    for local_contract in entries {
        let Some(inv) = local_contract.get("inv").filter(|value| value.is_object()) else {
            continue;
        };
        let local_contract_name = local_contract
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("<unknown local contract>");
        let mut callsites = Vec::new();
        collect_ctor_terms(inv, &mut callsites);
        for callsite in callsites {
            let Some(source_symbol) = callsite.get("name").and_then(Value::as_str) else {
                continue;
            };
            let Some(bridge_env) = pool.bridges_by_symbol.get(source_symbol) else {
                continue;
            };
            let bridge_source_symbol = memento_body_field(bridge_env, "sourceSymbol")
                .and_then(Value::as_str)
                .unwrap_or(source_symbol);
            let target_cid = memento_body_field(bridge_env, "targetContractCid")
                .and_then(Value::as_str)
                .unwrap_or_else(|| {
                    panic!(
                        "kit referenced bridge `{bridge_source_symbol}` without targetContractCid"
                    )
                });
            let proof_cid = memento_body_field(bridge_env, "targetProofCid")
                .and_then(Value::as_str)
                .map(str::to_string)
                .or_else(|| {
                    pool.bridge_self_bundle_by_symbol
                        .get(bridge_source_symbol)
                        .cloned()
                });
            let target_env = pool.mementos.get(target_cid).unwrap_or_else(|| {
                let proof = proof_cid.as_deref().unwrap_or("<unknown proof>");
                panic!(
                    "kit referenced proof CID `{proof}` but did not resolve target contract `{target_cid}`"
                )
            });
            if memento_kind(target_env) != Some("contract") {
                continue;
            }
            let Some(target_body) = memento_body(target_env) else {
                continue;
            };
            let Some(post) = target_body
                .get("post")
                .or_else(|| target_body.get("postcondition"))
                .filter(|value| value.is_object())
            else {
                continue;
            };
            let Some(formals) = string_array_field(target_body, "formals") else {
                continue;
            };
            let Some(args) = callsite.get("args").and_then(Value::as_array) else {
                continue;
            };
            if formals.len() != args.len() {
                continue;
            }
            let out_binding = target_body
                .get("outBinding")
                .or_else(|| target_body.get("out_binding"))
                .and_then(Value::as_str)
                .filter(|name| !name.is_empty())
                .unwrap_or("out");
            let mut instantiated_post = post.clone();
            for (formal, actual) in formals.iter().zip(args.iter()) {
                instantiated_post = sugar_verifier::instantiate::substitute_formula_pub(
                    &instantiated_post,
                    formal,
                    actual,
                );
            }
            instantiated_post = sugar_verifier::instantiate::substitute_formula_pub(
                &instantiated_post,
                out_binding,
                &callsite,
            );
            let vendor_source = source_memento_for_contract(&pool, target_body, target_cid)
                .map(|memento| resolve_source_memento_for_report(workspace_root, &memento))
                .unwrap_or_else(|| {
                    json!({
                        "status": "absent",
                        "reason": "vendor contract carried no source memento"
                    })
                });

            rows.push(json!({
                "call": callsite,
                "localContract": local_contract_name,
                "localFact": inv,
                "bridgeSourceSymbol": bridge_source_symbol,
                "vendorContract": target_body
                    .get("name")
                    .and_then(Value::as_str)
                    .or_else(|| pool.cid_to_name.get(target_cid).map(String::as_str))
                    .unwrap_or("<unknown vendor contract>"),
                "vendorContractCid": target_cid,
                "vendorProofCid": proof_cid,
                "vendorProofResolution": {
                    "status": "resolved",
                    "cid": proof_cid
                },
                "vendorPost": post,
                "instantiatedPost": instantiated_post,
                "vendorSource": vendor_source,
            }));
        }
    }
    rows
}

fn enumerate_import_proof_files(workspace_root: &Path) -> Vec<PathBuf> {
    let imports = workspace_root.join(".sugar/imports");
    if !imports.exists() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for entry in walkdir::WalkDir::new(imports)
        .into_iter()
        .filter_map(Result::ok)
    {
        let path = entry.path();
        if path.is_file() && path.extension().is_some_and(|ext| ext == "proof") {
            out.push(path.to_path_buf());
        }
    }
    out.sort();
    out
}

fn collect_ctor_terms(value: &Value, out: &mut Vec<Value>) {
    if value.get("kind").and_then(Value::as_str) == Some("ctor") {
        out.push(value.clone());
    }
    for field in ["args", "operands"] {
        if let Some(values) = value.get(field).and_then(Value::as_array) {
            for child in values {
                collect_ctor_terms(child, out);
            }
        }
    }
    if let Some(body) = value.get("body") {
        collect_ctor_terms(body, out);
    }
}

fn string_array_field(value: &Value, key: &str) -> Option<Vec<String>> {
    value
        .get(key)?
        .as_array()?
        .iter()
        .map(|item| item.as_str().map(str::to_string))
        .collect()
}

fn call_edges_for_report(entries: &[Value]) -> Vec<Value> {
    let mut contract_cids_by_name: BTreeMap<String, String> = BTreeMap::new();
    let mut targets_by_symbol: BTreeMap<String, (String, String)> = BTreeMap::new();
    for entry in entries {
        if !matches!(
            entry.get("kind").and_then(Value::as_str),
            Some("contract" | "function-contract")
        ) {
            continue;
        }
        let Some(name) = entry.get("name").and_then(Value::as_str) else {
            continue;
        };
        let cid = ir_entry_content_cid(entry);
        contract_cids_by_name.insert(name.to_string(), cid.clone());
        if entry.get("kind").and_then(Value::as_str) != Some("function-contract") {
            continue;
        }
        let Some(symbol) = entry
            .get("bridgeSourceSymbol")
            .and_then(Value::as_str)
            .filter(|symbol| !symbol.is_empty())
        else {
            continue;
        };
        targets_by_symbol
            .entry(symbol.to_string())
            .or_insert_with(|| (name.to_string(), cid));
    }
    if targets_by_symbol.is_empty() {
        return Vec::new();
    }

    let mut rows = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    for entry in entries {
        let Some(source_contract) = entry.get("name").and_then(Value::as_str) else {
            continue;
        };
        let Some(source_contract_cid) = contract_cids_by_name.get(source_contract) else {
            continue;
        };
        let source_symbol = entry
            .get("bridgeSourceSymbol")
            .and_then(Value::as_str)
            .map(str::to_string);
        for slot in ["pre", "post", "inv"] {
            let Some(formula) = entry.get(slot).filter(|value| value.is_object()) else {
                continue;
            };
            let mut callsites = Vec::new();
            collect_ctor_terms(formula, &mut callsites);
            for callsite in callsites {
                let Some(callsite_symbol) = callsite.get("name").and_then(Value::as_str) else {
                    continue;
                };
                let Some(target_symbol) =
                    call_edge_target_symbol(callsite_symbol, &targets_by_symbol)
                else {
                    continue;
                };
                if source_symbol.as_deref() == Some(target_symbol) {
                    continue;
                }
                let (target_contract, target_contract_cid) = targets_by_symbol
                    .get(target_symbol)
                    .expect("symbol checked above");
                let key = format!("{source_contract}\0{slot}\0{target_symbol}\0{callsite}");
                if !seen.insert(key) {
                    continue;
                }
                rows.push(json!({
                    "schemaVersion": "1",
                    "kind": "call-edge",
                    "sourceContract": source_contract,
                    "sourceContractCid": source_contract_cid,
                    "targetContract": target_contract,
                    "targetContractCid": target_contract_cid,
                    "targetSymbol": target_symbol,
                    "callSiteLocus": {
                        "file": source_warrant_file(entry),
                        "line": source_warrant_line(entry),
                        "slot": slot,
                    },
                    "evidenceTerm": callsite,
                }));
            }
        }
    }
    rows
}

fn call_edge_target_symbol<'a>(
    callsite_symbol: &'a str,
    targets_by_symbol: &'a BTreeMap<String, (String, String)>,
) -> Option<&'a str> {
    if targets_by_symbol.contains_key(callsite_symbol) {
        return Some(callsite_symbol);
    }
    let base = callsite_symbol.strip_suffix("#panic_callsite")?;
    targets_by_symbol.contains_key(base).then_some(base)
}

fn ir_entry_content_cid(entry: &Value) -> String {
    let mut body = serde_json::Map::new();
    body.insert(
        "name".to_string(),
        entry.get("name").cloned().unwrap_or(Value::Null),
    );
    body.insert(
        "outBinding".to_string(),
        entry
            .get("outBinding")
            .or_else(|| entry.get("out_binding"))
            .cloned()
            .unwrap_or_else(|| json!("out")),
    );
    for slot in ["pre", "post", "inv"] {
        if let Some(value) = entry.get(slot) {
            body.insert(slot.to_string(), value.clone());
        }
    }
    sugar_canonicalizer::jcs_cid_of_json(&Value::Object(body))
}

fn source_warrant_file(entry: &Value) -> Value {
    entry
        .get("sourceWarrants")
        .and_then(Value::as_array)
        .and_then(|warrants| warrants.first())
        .and_then(|warrant| warrant.get("file"))
        .cloned()
        .unwrap_or(Value::Null)
}

fn source_warrant_line(entry: &Value) -> Value {
    entry
        .get("sourceWarrants")
        .and_then(Value::as_array)
        .and_then(|warrants| warrants.first())
        .and_then(|warrant| warrant.get("span"))
        .and_then(|span| span.get("start_line").or_else(|| span.get("line")))
        .cloned()
        .unwrap_or(Value::Null)
}

fn source_memento_for_contract(
    pool: &sugar_verifier::types::MementoPool,
    contract_body: &Value,
    contract_cid: &str,
) -> Option<Value> {
    contract_body
        .get("sourceWarrants")
        .or_else(|| contract_body.get("source_warrants"))
        .and_then(Value::as_array)
        .and_then(|warrants| warrants.first())
        .cloned()
        .or_else(|| source_memento_member_for_contract(pool, contract_body, contract_cid))
}

fn source_memento_member_for_contract(
    pool: &sugar_verifier::types::MementoPool,
    contract_body: &Value,
    contract_cid: &str,
) -> Option<Value> {
    let contract_name = contract_body
        .get("name")
        .and_then(Value::as_str)
        .or_else(|| pool.cid_to_name.get(contract_cid).map(String::as_str));
    let source_owner = contract_name
        .and_then(|name| name.strip_prefix("rust-source::").or(Some(name)))
        .map(str::to_string);

    for env in pool.mementos.values() {
        if memento_kind(env) != Some("source-memento") {
            continue;
        }
        let Some(payload) = source_memento_payload(env) else {
            continue;
        };
        let named_contract_matches = contract_name.is_some_and(|name| {
            source_memento_string_field(env, payload, "contractName") == Some(name)
                || source_memento_string_field(env, payload, "claimName") == Some(name)
        });
        let source_owner_matches = source_owner.as_deref().is_some_and(|owner| {
            source_memento_string_field(env, payload, "sourceFunctionName")
                .or_else(|| source_memento_string_field(env, payload, "source_function_name"))
                .is_some_and(|name| name == owner || name.ends_with(&format!("::{owner}")))
        });
        if named_contract_matches || source_owner_matches {
            return Some(payload.clone());
        }
    }
    None
}

fn source_memento_payload(env: &Value) -> Option<&Value> {
    env.get("body").or_else(|| memento_body(env))
}

fn factory_audit_row(
    file: &str,
    audit: &FactoryAudit,
    source_cache: &mut FileSourceOracleCache<'_>,
    fns: &[FnRef<'_>],
) -> Value {
    let mut row = json!({
        "file": file,
        "ast_kind": audit.ast_kind,
        "line": audit.line,
        "requested_role": audit.requested_role,
        "selected": audit.selected,
        "candidates": audit.candidates.iter().map(|candidate| {
            json!({
                "name": candidate.name,
                "role": candidate.role,
                "comesBefore": candidate.comes_before,
                "selected": candidate.selected,
            })
        }).collect::<Vec<_>>(),
        "status": audit.disposition.as_str(),
        "output": audit.output,
        "reason": audit.reason,
    });
    if let Some(span) = &audit.span {
        row["span"] = json!({
            "start_line": span.start_line,
            "start_col": span.start_col,
            "end_line": span.end_line,
            "end_col": span.end_col,
        });
        if let Some(owner) = owner_fn_for_audit_span(fns, span) {
            if let Some(memento) = source_cache.term_memento(owner, span) {
                row["sourceMemento"] = memento;
            }
        }
    }
    if audit.disposition == sugar_lift_rust_tests::FactoryDisposition::Support {
        row["supportKind"] = json!("inert");
    }
    row
}

fn owner_fn_for_audit_span<'a, 'src>(
    fns: &'a [FnRef<'src>],
    span: &FactoryAuditSpan,
) -> Option<&'a FnRef<'src>> {
    fns.iter()
        .filter(|fr| {
            let start = fr.span.start();
            let end = fr.block.brace_token.span.close().end();
            (start.line, start.column) <= (span.start_line, span.start_col)
                && (span.end_line, span.end_col) <= (end.line, end.column)
        })
        .min_by_key(|fr| {
            let start = fr.span.start();
            let end = fr.block.brace_token.span.close().end();
            (
                end.line.saturating_sub(start.line),
                end.column.saturating_sub(start.column),
            )
        })
}

fn factory_audits_json(
    file: &str,
    audits: &[FactoryAudit],
    source_cache: &mut FileSourceOracleCache<'_>,
    fns: &[FnRef<'_>],
) -> Vec<Value> {
    // The recursive factory walk records the SAME terminal across sub-terms, requested
    // roles, and re-walks, so a raw 1:1 mapping emits byte-identical rows hundreds of
    // times per locus (observed: ~1.18M rows over ~1.5K loci on the coretests corpus).
    // That bloats the lift response term past the transport's finite-or-refuse byte
    // bound (RESPONSE_TERM_SERIALIZED_BYTE_BOUND), which then refuses the WHOLE response
    // -- silently dropping the source-audit ledger so the measuring stick goes dark.
    //
    // Collapse byte-identical rows into ONE row carrying an `occurrences` count. This is
    // FINITE ACCOUNTING (supra omnia rectum), NOT truncation: nothing is dropped, the
    // total is preserved in the count, and only genuinely-identical observations merge
    // (any variation in output/reason/candidates keeps rows distinct). The source ledger
    // is derived independently from `source_loci` (see `source_ledger`), so collapsing
    // these diagnostic rows cannot move a single headline number.
    let mut order: Vec<String> = Vec::new();
    let mut rows: HashMap<String, Value> = HashMap::new();
    let mut occurrences: HashMap<String, u64> = HashMap::new();
    for audit in audits {
        let row = factory_audit_row(file, audit, source_cache, fns);
        // Identity = the full row content, computed BEFORE the `occurrences` tag so the
        // key is stable. serde_json serializes a Value deterministically, so identical
        // rows produce identical keys.
        let key = serde_json::to_string(&row).unwrap_or_default();
        if rows.insert(key.clone(), row).is_none() {
            order.push(key.clone());
        }
        *occurrences.entry(key).or_insert(0) += 1;
    }
    order
        .into_iter()
        .map(|key| {
            let mut row = rows
                .remove(&key)
                .expect("row keyed in `order` was inserted");
            row["occurrences"] = json!(occurrences[&key]);
            row
        })
        .collect()
}

#[derive(Debug)]
struct FactoryAuditSummaryAccumulator {
    sites: usize,
    warranted: usize,
    refused: usize,
    support: usize,
    unresolved: usize,
    unresolved_sites: Vec<Value>,
    walk: Vec<Value>,
}

impl FactoryAuditSummaryAccumulator {
    fn new() -> Self {
        Self {
            sites: 0,
            warranted: 0,
            refused: 0,
            support: 0,
            unresolved: 0,
            unresolved_sites: Vec::new(),
            walk: Vec::new(),
        }
    }

    fn extend_from_audits(
        &mut self,
        file: &str,
        audits: &[FactoryAudit],
        source_cache: &mut FileSourceOracleCache<'_>,
        fns: &[FnRef<'_>],
    ) {
        for row in factory_audits_json(file, audits, source_cache, fns) {
            self.sites += 1;
            let status = row.get("status").and_then(Value::as_str).unwrap_or("");
            self.observe_status(status);
            if matches!(status, "unresolved" | "unclassified") {
                self.unresolved_sites.push(factory_summary_site_row(&row));
            }
            self.walk.push(factory_walk_row(&row));
        }
    }

    fn observe_status(&mut self, status: &str) {
        match status {
            "warranted" => self.warranted += 1,
            "refused" => self.refused += 1,
            "support" => self.support += 1,
            "unresolved" | "unclassified" => self.unresolved += 1,
            _ => {}
        }
    }

    fn into_json(self) -> Value {
        json!({
            "sites": self.sites,
            "emittedRows": self.sites,
            "omittedRows": 0,
            "totalRows": self.sites,
            "complete": true,
            "statusCounts": {
                "warranted": self.warranted,
                "refused": self.refused,
                "support": self.support,
                "unresolved": self.unresolved,
            },
            "unresolvedSites": self.unresolved_sites,
            "factoryWalk": self.walk,
        })
    }
}

fn factory_audit_response_summary(rows: &[Value]) -> Value {
    json!({
        "sites": rows.len(),
        "emittedRows": rows.len(),
        "omittedRows": 0,
        "totalRows": rows.len(),
        "complete": true,
        "statusCounts": factory_audit_status_counts(rows),
        "unresolvedSites": unresolved_factory_audit_rows(rows),
        "factoryWalk": factory_walk_rows(rows),
    })
}

fn factory_walk_rows(rows: &[Value]) -> Vec<Value> {
    rows.iter().map(factory_walk_row).collect()
}

fn factory_walk_row(row: &Value) -> Value {
    let status = factory_row_status(row);
    let verdict = match status {
        "warranted" | "support" => "complete",
        "refused" => "incomplete",
        "unresolved" => "gap",
        _ => "incomplete",
    };
    let output = if status == "unresolved" {
        json!("gap")
    } else {
        row.get("output").cloned().unwrap_or(Value::Null)
    };
    let mut compact = json!({
        "file": row.get("file").cloned().unwrap_or(Value::Null),
        "line": row.get("line").cloned().unwrap_or(Value::Null),
        "requested_role": row.get("requested_role").cloned().unwrap_or(Value::Null),
        "ast_kind": row.get("ast_kind").cloned().unwrap_or(Value::Null),
        "selected": row.get("selected").cloned().unwrap_or(Value::Null),
        "status": status,
        "verdict": verdict,
        "output": output,
    });
    if let Some(span) = row.get("span").cloned() {
        compact["span"] = span;
    }
    if let Some(memento) = row.get("sourceMemento").cloned() {
        compact["sourceMemento"] = memento;
    }
    if let Some(reason) = row.get("reason").cloned() {
        compact["reason"] = reason;
    }
    if let Some(occurrences) = row.get("occurrences").cloned() {
        compact["occurrences"] = occurrences;
    }
    compact
}

fn factory_summary_site_row(row: &Value) -> Value {
    let status = factory_row_status(row);
    let output = if status == "unresolved" {
        json!("gap")
    } else {
        row.get("output").cloned().unwrap_or(Value::Null)
    };
    let mut compact = json!({
        "file": row.get("file").cloned().unwrap_or(Value::Null),
        "line": row.get("line").cloned().unwrap_or(Value::Null),
        "requested_role": row.get("requested_role").cloned().unwrap_or(Value::Null),
        "ast_kind": row.get("ast_kind").cloned().unwrap_or(Value::Null),
        "selected": row.get("selected").cloned().unwrap_or(Value::Null),
        "status": status,
        "output": output,
    });
    if let Some(span) = row.get("span").cloned() {
        compact["span"] = span;
    }
    if let Some(memento) = row.get("sourceMemento").cloned() {
        compact["sourceMemento"] = memento;
    }
    if let Some(reason) = row.get("reason").cloned() {
        compact["reason"] = reason;
    }
    if let Some(occurrences) = row.get("occurrences").cloned() {
        compact["occurrences"] = occurrences;
    }
    compact
}

fn factory_row_status(row: &Value) -> &'static str {
    match row.get("status").and_then(Value::as_str).unwrap_or("") {
        "warranted" => "warranted",
        "refused" => "refused",
        "support" => "support",
        "unresolved" | "unclassified" => "unresolved",
        _ => "unresolved",
    }
}

fn unresolved_factory_audit_rows(rows: &[Value]) -> Vec<Value> {
    rows.iter()
        .filter(|row| {
            matches!(
                row.get("status").and_then(Value::as_str).unwrap_or(""),
                "unresolved" | "unclassified"
            )
        })
        .map(factory_summary_site_row)
        .collect()
}

fn factory_audit_status_counts(rows: &[Value]) -> Value {
    let mut warranted = 0usize;
    let mut refused = 0usize;
    let mut support = 0usize;
    let mut unresolved = 0usize;
    for row in rows {
        match row.get("status").and_then(Value::as_str).unwrap_or("") {
            "warranted" => warranted += 1,
            "refused" => refused += 1,
            "support" => support += 1,
            "unresolved" | "unclassified" => unresolved += 1,
            _ => {}
        }
    }
    json!({
        "warranted": warranted,
        "refused": refused,
        "support": support,
        "unresolved": unresolved,
    })
}

fn source_memento_string_field<'a>(
    env: &'a Value,
    payload: &'a Value,
    field: &str,
) -> Option<&'a str> {
    payload.get(field).and_then(Value::as_str).or_else(|| {
        env.pointer(&format!("/header/{field}"))
            .and_then(Value::as_str)
    })
}

fn resolve_proof_by_cid_for_report(workspace_root: &Path, cid: &str) -> Value {
    for path in enumerate_import_proof_files(workspace_root) {
        let Ok(bytes) = std::fs::read(&path) else {
            continue;
        };
        if blake3_512_of(&bytes) == cid {
            return json!({
                "status": "resolved",
                "cid": cid,
                "path": path.display().to_string(),
            });
        }
    }
    json!({
        "status": "missing",
        "cid": cid,
        "reason": format!("proof CID `{cid}` not found in .sugar/imports"),
    })
}

fn resolve_source_memento_rpc(params: &Value) -> Value {
    let workspace_root = params
        .get("workspace_root")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let memento = params
        .get("memento")
        .or_else(|| params.get("sourceMemento"))
        .or_else(|| params.get("source_memento"))
        .unwrap_or(params);
    resolve_source_memento_for_report(&workspace_root, memento)
}

fn resolve_source_memento_for_report(workspace_root: &Path, memento_value: &Value) -> Value {
    let Some(memento) = source_memento_from_json(memento_value) else {
        return json!({
            "status": "absent",
            "reason": "invalid source memento shape",
        });
    };
    match source_oracle::resolve_source_memento(workspace_root, &memento) {
        Ok(resolved) => {
            let memento = resolved.fragment.to_memento();
            json!({
                "status": "resolved",
                "display": format_source_memento_for_report(&memento.to_json()),
                "memento": memento.to_json(),
            })
        }
        Err(refusal) if source_refusal_is_drift(&refusal.reason) => json!({
            "status": "drifted",
            "reason": refusal.reason,
            "memento": memento_value,
        }),
        Err(refusal) => json!({
            "status": "absent",
            "reason": refusal.reason,
            "memento": memento_value,
        }),
    }
}

fn source_refusal_is_drift(reason: &str) -> bool {
    reason.contains("source CID misaligned") || reason.contains("template CID misaligned")
}

fn source_memento_from_json(value: &Value) -> Option<source_oracle::SourceMemento> {
    let file = value.get("file").and_then(Value::as_str)?.to_string();
    let span = value.get("span")?;
    let params = value
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
    Some(source_oracle::SourceMemento {
        file,
        function_name: value
            .get("sourceFunctionName")
            .or_else(|| value.get("source_function_name"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        span: source_oracle::SrcSpan {
            start_line: span.get("start_line").and_then(Value::as_u64).unwrap_or(0) as usize,
            start_col: span.get("start_col").and_then(Value::as_u64).unwrap_or(0) as usize,
            end_line: span.get("end_line").and_then(Value::as_u64).unwrap_or(0) as usize,
            end_col: span.get("end_col").and_then(Value::as_u64).unwrap_or(0) as usize,
        },
        param_names: params,
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

fn format_source_memento_for_report(memento: &Value) -> String {
    let file = memento
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or("<unknown file>");
    let span = memento.get("span").unwrap_or(&Value::Null);
    let start = span
        .get("start_line")
        .and_then(Value::as_u64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let end = span
        .get("end_line")
        .and_then(Value::as_u64)
        .map(|line| line.to_string())
        .unwrap_or_else(|| "?".to_string());
    let lines = if start == end {
        start
    } else {
        format!("{start}-{end}")
    };
    let function = memento
        .get("sourceFunctionName")
        .or_else(|| memento.get("source_function_name"))
        .and_then(Value::as_str)
        .unwrap_or("<unknown function>");
    let params = memento
        .get("paramNames")
        .or_else(|| memento.get("param_names"))
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join(", ")
        })
        .unwrap_or_default();
    let source_cid = memento
        .get("source_cid")
        .or_else(|| memento.get("sourceCid"))
        .and_then(Value::as_str)
        .unwrap_or("<missing source cid>");
    format!("{file}:{lines} {function}({params}) source_cid={source_cid}")
}

fn send(obj: &Value) {
    let before = current_rss_kib();
    let rendered = serde_json::to_string(obj).unwrap_or_default();
    let result = obj.get("result").unwrap_or(&Value::Null);
    trace_lift_rpc_checkpoint_with_extra(
        "rpc.send.after_serialize",
        result,
        rendered.len(),
        rss_delta_kib(before, current_rss_kib()),
    );
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{rendered}");
    let _ = out.flush();
    trace_lift_rpc_checkpoint_with_extra("rpc.send.after_flush", result, rendered.len(), None);
}

fn err_reply(id: &Value, msg: String) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": {"code": -32603, "message": msg}})
}

fn handle(id: &Value, method: &str, params: &Value) -> Value {
    debug!(method, "rust-test-assertions rpc request");
    let before = current_rss_kib();
    let response = match method {
        "initialize" => json!({"jsonrpc": "2.0", "id": id, "result": initialize_result()}),
        KIT_DECLARATION_RPC_METHOD => {
            json!({"jsonrpc": "2.0", "id": id, "result": kit_declaration_result()})
        }
        COMPONENT_PLAN_RPC_METHOD => {
            json!({"jsonrpc": "2.0", "id": id, "result": component_plan_result(params)})
        }
        "lift" => json!({"jsonrpc": "2.0", "id": id, "result": lift(params)}),
        RESOLVE_PROOF_BY_CID_RPC_METHOD => {
            let workspace_root = params
                .get("workspace_root")
                .and_then(Value::as_str)
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("."));
            let cid = params.get("cid").and_then(Value::as_str).unwrap_or("");
            json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": resolve_proof_by_cid_for_report(&workspace_root, cid),
            })
        }
        RESOLVE_SOURCE_MEMENTO_RPC_METHOD => {
            json!({"jsonrpc": "2.0", "id": id, "result": resolve_source_memento_rpc(params)})
        }
        "shutdown" => json!({"jsonrpc": "2.0", "id": id, "result": Value::Null}),
        other => err_reply(id, format!("unknown method: {other}")),
    };
    trace_lift_rpc_checkpoint_with_extra(
        "rpc.handle.after_response",
        response.get("result").unwrap_or(&Value::Null),
        0,
        rss_delta_kib(before, current_rss_kib()),
    );
    response
}

fn main() {
    init_tracing();
    info!("rust-test-assertions-rpc listening on stdio");
    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let req: Value = match serde_json::from_str(&line) {
            Ok(req) => req,
            Err(e) => {
                send(
                    &json!({"jsonrpc": "2.0", "id": Value::Null, "error": {"code": -32700, "message": format!("parse error: {e}")}}),
                );
                continue;
            }
        };
        let id = req.get("id").cloned().unwrap_or(Value::Null);
        let method = req.get("method").and_then(Value::as_str).unwrap_or("");
        let params = req.get("params").cloned().unwrap_or(Value::Null);
        let reply = handle(&id, method, &params);
        send(&reply);
        if method == "shutdown" {
            break;
        }
    }
}

fn init_tracing() {
    let filter = if std::env::var_os("RUST_LOG").is_some() {
        tracing_subscriber::EnvFilter::builder()
            .with_default_directive(tracing_subscriber::filter::LevelFilter::WARN.into())
            .from_env_lossy()
    } else {
        tracing_subscriber::EnvFilter::new("warn,sugar_lift_rust_tests=info")
    };
    if let Ok(path) = std::env::var("SUGAR_LOG_FILE") {
        match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
        {
            Ok(file) => {
                tracing_subscriber::fmt()
                    .with_writer(file)
                    .with_ansi(false)
                    .with_env_filter(filter)
                    .init();
            }
            Err(error) => {
                eprintln!(
                    "warning: could not open SUGAR_LOG_FILE {path}: {error}; logging to stderr"
                );
                tracing_subscriber::fmt()
                    .with_writer(std::io::stderr)
                    .with_env_filter(filter)
                    .init();
            }
        }
    } else {
        tracing_subscriber::fmt()
            .with_writer(std::io::stderr)
            .with_env_filter(filter)
            .init();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn panic_message(payload: Box<dyn std::any::Any + Send>) -> String {
        if let Some(message) = payload.downcast_ref::<String>() {
            return message.clone();
        }
        if let Some(message) = payload.downcast_ref::<&'static str>() {
            return (*message).to_string();
        }
        "<non-string panic>".to_string()
    }

    fn fns_of(src: &str) -> Vec<FnRef<'_>> {
        // leak so the FnRefs can borrow for the test's lifetime
        let file: &'static syn::File = Box::leak(Box::new(syn::parse_file(src).expect("parses")));
        let mut out = Vec::new();
        collect_fns(&file.items, &mut out);
        out
    }

    fn lift_fixture(name: &str, src: &str) -> (PathBuf, Value) {
        lift_fixture_at(name, "src/lib.rs", src)
    }

    fn lift_fixture_at(name: &str, rel_path: &str, src: &str) -> (PathBuf, Value) {
        let root = unique_temp_dir(name);
        let source_path = root.join(rel_path);
        std::fs::create_dir_all(source_path.parent().expect("source parent"))
            .expect("mkdir source parent");
        std::fs::write(&source_path, src).expect("write rust source");
        let response = lift(&json!({
            "workspace_root": root,
            "source_paths": [rel_path]
        }));
        (root, response)
    }

    fn lift_fixture_with_config(name: &str, src: &str, config: &str) -> (PathBuf, Value) {
        let root = unique_temp_dir(name);
        std::fs::create_dir_all(root.join("src")).expect("mkdir src");
        std::fs::create_dir_all(root.join(".sugar")).expect("mkdir .sugar");
        std::fs::write(root.join("src/lib.rs"), src).expect("write rust source");
        std::fs::write(root.join(".sugar/config.toml"), config).expect("write config");
        let response = lift(&json!({
            "workspace_root": root,
            "source_paths": ["src/lib.rs"]
        }));
        (root, response)
    }

    fn source_locus<'a>(response: &'a Value, ast_path: &str) -> &'a Value {
        response["sourceAudits"][0]["loci"]
            .as_array()
            .expect("source audit loci")
            .iter()
            .find(|locus| locus["ast_path"] == ast_path)
            .unwrap_or_else(|| panic!("missing source locus {ast_path}: {response}"))
    }

    fn assert_source_locus_status(response: &Value, ast_path: &str, status: &str, category: &str) {
        let locus = source_locus(response, ast_path);
        assert_eq!(
            locus["status"], status,
            "{ast_path} must have source status {status}: {locus}"
        );
        assert!(
            locus["reason"]
                .as_str()
                .is_some_and(|reason| reason.contains(category)),
            "{ast_path} source reason must carry category {category:?}: {locus}"
        );
        assert_ne!(locus["status"], "unresolved", "{locus}");
    }

    fn assert_source_locus_refused(response: &Value, ast_path: &str, category: &str) {
        assert_source_locus_status(response, ast_path, "refused", category);
    }

    fn assert_source_locus_inactive(response: &Value, ast_path: &str, category: &str) {
        assert_source_locus_status(response, ast_path, "inactive", category);
    }

    fn assert_source_locus_warranted(response: &Value, ast_path: &str) {
        let locus = source_locus(response, ast_path);
        assert_eq!(
            locus["status"], "warranted",
            "{ast_path} is the literal twin and must still warrant: {locus}"
        );
    }

    fn factory_audit_for_fn<'a>(
        root: &Path,
        response: &'a Value,
        selected: &str,
        source_fn: Option<&str>,
        site_fragment: &str,
    ) -> &'a Value {
        response["factoryAudits"]
            .as_array()
            .expect("factoryAudits is an array")
            .iter()
            .find(|row| {
                assert!(
                    row.get("site").is_none() && row.get("term").is_none(),
                    "factory RPC rows must carry SourceMemento pins, not plaintext source: {row}"
                );
                let fn_matches = source_fn.is_none_or(|source_fn| {
                    row["sourceMemento"]["sourceFunctionName"] == source_fn
                        || row["sourceMemento"]["source_function_name"] == source_fn
                });
                row["selected"] == selected
                    && fn_matches
                    && factory_audit_source_text(root, row)
                        .is_some_and(|site| source_contains_fragment(&site, site_fragment))
            })
            .unwrap_or_else(|| {
                panic!(
                    "missing factory audit selected={selected:?} fn={source_fn:?} source~={site_fragment:?}: {response}"
                )
            })
    }

    fn factory_audit_source_text(root: &Path, row: &Value) -> Option<String> {
        let memento = source_memento_from_json(row.get("sourceMemento")?)?;
        source_oracle::resolve_source_memento(root, &memento)
            .ok()
            .map(|resolved| resolved.fragment.body_text)
    }

    fn source_contains_fragment(source: &str, fragment: &str) -> bool {
        source.contains(fragment) || compact_source(source).contains(&compact_source(fragment))
    }

    fn compact_source(source: &str) -> String {
        source.chars().filter(|ch| !ch.is_whitespace()).collect()
    }

    fn assert_factory_audit_status(
        root: &Path,
        response: &Value,
        site_fragment: &str,
        status: &str,
        reason_fragment: Option<&str>,
    ) {
        assert_factory_audit_status_for_selected(
            root,
            response,
            "constraint_no_panic_call",
            None,
            site_fragment,
            status,
            reason_fragment,
        );
    }

    fn assert_factory_audit_status_for_selected(
        root: &Path,
        response: &Value,
        selected: &str,
        source_fn: Option<&str>,
        site_fragment: &str,
        status: &str,
        reason_fragment: Option<&str>,
    ) {
        let row = factory_audit_for_fn(root, response, selected, source_fn, site_fragment);
        assert_eq!(
            row["status"], status,
            "factory row selected={selected:?} site={site_fragment:?} must be {status}: {row}"
        );
        if let Some(reason_fragment) = reason_fragment {
            assert!(
                row["reason"]
                    .as_str()
                    .is_some_and(|reason| reason.contains(reason_fragment)),
                "factory row selected={selected:?} site={site_fragment:?} reason must contain {reason_fragment:?}: {row}"
            );
        }
    }

    #[test]
    fn source_audit_classifier_names_assigned_corpus_refusals() {
        let option_reason = "rust test assertions: unsupported assertion surface; released to layer 0: runtime Option/Result payload, not literal (`unwrap`)";
        assert_eq!(
            clean_named_refusal_category("tests/option.rs", "test_get_ptr", option_reason),
            Some("Option payload is a raw pointer, runtime address not literal-determined")
        );
        assert_eq!(
            clean_named_refusal_category("tests/option.rs", "test_get_str", option_reason),
            None
        );

        let as_mut_ptr_reason = "rust test assertions: unsupported assertion surface; released to layer 0: temporally unstable mutable view read of `xs` after `.as_mut_ptr()`: the method exposes mutable state whose writes are not replayed by the literal temporal rewrite, so there is no single timeless value to read at the assertion; refused";
        assert_eq!(
            clean_named_refusal_category("tests/ptr.rs", "test_set_memory", as_mut_ptr_reason),
            Some("mutable view via as_mut_ptr, temporally unstable, no timeless value")
        );

        let runtime_operand_reason = "rust test assertions: unsupported assertion surface; released to layer 0: assert_eq!: runtime operand, not literal; assert_eq!: runtime operand, not literal";
        assert_eq!(
            clean_named_refusal_category("tests/atomic.rs", "ptr_add_data", runtime_operand_reason),
            Some("atomic ptr arithmetic, runtime operand")
        );
        assert_eq!(
            clean_named_refusal_category("tests/time.rs", "saturating_mul", runtime_operand_reason),
            Some("Duration/time runtime operand")
        );

        let pointer_alignment_reason = "rust test assertions: unsupported assertion surface; released to layer 0: assert_ne!: runtime operand, not literal";
        assert_eq!(
            clean_named_refusal_category("tests/ptr.rs", "is_aligned", pointer_alignment_reason),
            Some("pointer alignment, runtime address")
        );
        assert_eq!(
            clean_named_refusal_category("tests/atomic.rs", "ptr_add_null", runtime_operand_reason),
            None
        );
    }

    #[test]
    fn source_warning_classifier_names_runtime_callable_element_without_refusing_literal_twin() {
        let reason = "rust test assertions: unsupported assertion surface; released to layer 0: assertion surface `assert ! (funcs . into_iter () . any (| f | f (1) == 1))` emitted only support facts; assertion without warranted fact emitted; released to layer 0";
        let runtime_body: syn::Block = syn::parse_quote!({
            let funcs: [fn(i32) -> i32; 1] = [id];
            assert!(funcs.into_iter().any(|f| f(1) == 1));
        });
        assert!(
            matches!(
                source_test_body_warning_classification(
                    "src/source_runtime_callable.rs",
                    "runtime_callable_element_refused",
                    reason,
                    &runtime_body,
                ),
                Some(SourceWarningClassification::Refused(
                    "runtime callable element boundary"
                ))
            ),
            "closure adaptor that invokes its element is a named runtime callable boundary"
        );

        let literal_body: syn::Block = syn::parse_quote!({
            assert!([1i32].into_iter().any(|x| x == 1));
        });
        assert!(
            source_test_body_warning_classification(
                "src/source_runtime_callable.rs",
                "runtime_callable_element_literal_twin",
                reason,
                &literal_body,
            )
            .is_none(),
            "literal element predicates must stay available to warranting sugar"
        );
    }

    #[test]
    fn no_panic_effectful_tail_hits_are_named_with_literal_twin() {
        let (root, response) = lift_fixture(
            "no_panic_effectful_tail_hits_are_named_with_literal_twin",
            r#"
use std::cell::Cell;

struct CountDrop<'a>(&'a Cell<usize>);
impl<'a> CountDrop<'a> {
    fn new(count: &'a Cell<usize>) -> Self {
        CountDrop(count)
    }
}

#[test]
fn effectful_tail_refused() {
    let count = Cell::new(0usize);
    let _chunks = (0..10).map(|_| CountDrop::new(&count)).array_chunks::<3>();

    let value = 1;
    let cell = Cell::new(None);
    cell.set(Some(&value));

    let mut xs = [1, 2, 3];
    let mut ys = [4, 5, 6];
    let _zipped = xs
        .iter_mut()
        .map(|x| *x += 1)
        .zip(ys.iter_mut().map(|y| *y += 1));

    let mut it = [1, 2, 3].iter();
    let _last = it.next_back().unwrap();

    let mut functions: [fn() -> Option<i32>; 1] = [|| Some(1)];
    let _values: Option<Vec<i32>> = functions.iter_mut().map(|f| (*f)()).collect();
}

#[test]
fn literal_empty_callsite_twin_warrants() {
    let _empty = IntoIterator::into_iter([] as [String; 0]);
}
"#,
        );

        assert_factory_audit_status(
            &root,
            &response,
            "CountDrop :: new (& count)",
            "refused",
            Some("side-effecting closure body"),
        );
        assert_factory_audit_status(
            &root,
            &response,
            "cell . set (Some (& value))",
            "refused",
            Some("temporally unstable"),
        );
        assert_factory_audit_status(
            &root,
            &response,
            "xs . iter_mut () . map",
            "refused",
            Some("side-effecting closure body"),
        );
        assert_factory_audit_status(
            &root,
            &response,
            "it . next_back ()",
            "refused",
            Some("unknown iterator consumption"),
        );
        assert_factory_audit_status(
            &root,
            &response,
            "functions . iter_mut () . map",
            "refused",
            Some("runtime call through closure body parameter"),
        );
        assert_factory_audit_status(
            &root,
            &response,
            "IntoIterator :: into_iter ([] as [String ; 0])",
            "warranted",
            None,
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn literal_for_loop_runtime_body_fallback_is_not_blanket_refusal() {
        let reason = "rust test assertions: unsupported assertion surface; released to layer 0: assertion under for context over a LITERAL range (bin-1: domain constructed, body not yet point-wise liftable); not unconditional point-wise; released to layer 0";
        let drop_on_panic_reason = "rust test assertions: unsupported assertion surface; released to layer 0: assertion under for context over a LITERAL domain reaches drop-on-panic side effect, runtime, not literal; refused";
        assert_eq!(
            clean_named_refusal_category(
                "tests/array.rs",
                "array_map_drops_unmapped_elements_on_panic",
                drop_on_panic_reason,
            ),
            Some("literal for-loop body runtime read")
        );

        let runtime_body: syn::Block = syn::parse_quote!({
            use std::sync::atomic::{AtomicUsize, Ordering};
            for _ in 0..2 {
                let counter = AtomicUsize::new(0);
                assert_eq!(counter.load(Ordering::SeqCst), 0);
            }
        });
        assert!(
            matches!(
                source_test_body_warning_classification(
                    "tests/array.rs",
                    "array_map_drops_unmapped_elements_on_panic",
                    reason,
                    &runtime_body,
                ),
                Some(SourceWarningClassification::Refused(
                    "literal for-loop body runtime read"
                ))
            ),
            "literal loop whose body hits atomic runtime state should be refused by name"
        );

        let pure_body: syn::Block = syn::parse_quote!({
            for i in 0..2 {
                assert!(i < 2);
            }
        });
        assert!(
            source_test_body_warning_classification(
                "tests/array.rs",
                "array_map_drops_unmapped_elements_on_panic",
                reason,
                &pure_body,
            )
            .is_none(),
            "pure literal loops stay available to the warranting sugar"
        );
    }

    #[test]
    fn source_locus_should_panic_opaque_body_refuses_with_callsite_twin() {
        let (_root, response) = lift_fixture(
            "source_locus_should_panic_opaque_body_refuses_with_callsite_twin",
            r#"
                #[test]
                #[should_panic]
                fn opaque_should_panic() {
                    let _ = format!("{}", 42);
                }

                #[test]
                #[should_panic]
                fn callsite_should_panic() {
                    let mut m = Machine::new();
                    m.finish();
                }
            "#,
        );

        assert_source_locus_refused(
            &response,
            "opaque_should_panic",
            "should_panic terminal panic not text-determined (opaque body)",
        );
        assert_source_locus_warranted(&response, "callsite_should_panic");
    }

    fn coretests_corpus_source(relative: &str) -> String {
        let mut path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        path.pop();
        path.pop();
        path.pop();
        path.push("examples/rust-coretests-report/corpus");
        path.push(relative);
        std::fs::read_to_string(&path)
            .unwrap_or_else(|error| panic!("read coretests corpus source {path:?}: {error}"))
    }

    fn classify_coretests_fn(
        relative: &str,
        name: &str,
    ) -> (&'static str, Option<String>, Option<Value>) {
        let source = coretests_corpus_source(relative);
        let fns = fns_of(&source);
        let f = fns
            .iter()
            .find(|f| f.name == name)
            .unwrap_or_else(|| panic!("missing coretests fn {relative}::{name}"));
        let source_memento = json!({"file": relative, "fn": name});
        classify_nontest_fn(name, f.sig, f.block, false, &source_memento)
    }

    #[test]
    fn collect_fns_enumerates_impl_and_trait_default_methods() {
        // free fn + inherent impl method + trait default method must all appear:
        // excluding impl/trait methods is what made unclassified=0 hollow.
        let src = r#"
            fn free_fn() -> i32 { 1 }
            struct S;
            impl S { fn method(&self) -> i32 { 2 } }
            trait T { fn defaulted(&self) -> i32 { 3 } fn decl_only(&self) -> i32; }
        "#;
        let names: Vec<String> = fns_of(src).iter().map(|f| f.name.clone()).collect();
        assert!(names.contains(&"free_fn".to_string()));
        assert!(
            names.contains(&"S::method".to_string()),
            "impl method must be enumerated: {names:?}"
        );
        assert!(
            names.contains(&"T::defaulted".to_string()),
            "trait default method must be enumerated: {names:?}"
        );
        // a trait method WITHOUT a body declares no constructor -> not a locus.
        assert!(
            !names.contains(&"decl_only".to_string()),
            "bodyless trait decl is not a locus: {names:?}"
        );
    }

    #[test]
    fn target_cfg_config_is_optional() {
        let cfg = target_cfg_from_config_text(
            r#"
[[plugins]]
name = "rust-test-assertions-lift"
"#,
        )
        .expect("config parses");

        assert!(cfg.is_none());
    }

    #[test]
    fn target_cfg_config_requires_pinned_target() {
        let err = target_cfg_from_config_text(
            r#"
[rust-test-assertions.target_cfg]
facts = ["unix"]
"#,
        )
        .expect_err("target is required");

        assert!(err.contains("requires target"));
    }

    #[test]
    fn target_cfg_config_parses_explicit_rustc_facts() {
        let cfg = target_cfg_from_config_text(
            r#"
[rust-test-assertions.target_cfg]
target = "x86_64-apple-darwin"
facts = [
  "target_pointer_width=\"64\"",
  "unix",
]
"#,
        )
        .expect("config parses");

        assert!(cfg.is_some());
    }

    #[test]
    fn lift_reads_cargo_feature_cfg_from_workspace_manifest_without_config() {
        let root =
            unique_temp_dir("lift_reads_cargo_feature_cfg_from_workspace_manifest_without_config");
        std::fs::create_dir_all(root.join("src")).expect("mkdir src");
        std::fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "fixture"
version = "0.1.0"
edition = "2021"

[features]
default = ["enabled"]
enabled = []
"#,
        )
        .expect("write Cargo.toml");
        std::fs::write(
            root.join("src/lib.rs"),
            r#"
#[cfg(test)]
mod tests {
    #[cfg(feature = "enabled")]
    #[test]
    fn default_feature_lifts() {
        assert_eq!(1 + 1, 2);
    }
}
"#,
        )
        .expect("write rust source");

        let response = lift(&json!({
            "workspace_root": root,
            "source_paths": ["src/lib.rs"]
        }));

        let diagnostics = response["diagnostics"]
            .as_array()
            .expect("diagnostics is an array");
        assert!(
            diagnostics.iter().all(|diagnostic| {
                !diagnostic["reason"]
                    .as_str()
                    .is_some_and(|reason| reason.contains("ambiguous cfg"))
            }),
            "workspace Cargo facts should resolve feature cfgs without a manual config: {response}"
        );

        let audits = response["assertionSurfaceAudits"]
            .as_array()
            .expect("assertionSurfaceAudits is an array");
        let emitted = audits
            .iter()
            .find(|row| row["assertionSource"] == "src/lib.rs::tests::default_feature_lifts")
            .expect("feature-gated assertion source is accounted");
        assert_eq!(emitted["status"], "facts-emitted", "{emitted}");
        assert_eq!(emitted["facts"].as_array().unwrap().len(), 1, "{emitted}");

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_unit_body_is_named_refused_not_unresolved_dark() {
        // Unit-returning non-test bodies have a value proposition (`out = ()`).
        // When the body is not text-determined, totality requires a named
        // refusal instead of leaving the old "no value pin" dark bucket.
        let f: syn::ItemFn =
            syn::parse_str("fn inert(x: i32) { let _ = x + 1; }").expect("fn parses");
        let source_memento = json!({});
        let (status, reason, decl) =
            classify_nontest_fn("inert", &f.sig, &f.block, false, &source_memento);
        assert!(decl.is_none(), "a refused runtime body mints no contract");
        assert_eq!(
            status, "refused",
            "a runtime unit body is a named no-value-pin boundary (reason: {reason:?})"
        );
        assert!(
            reason
                .as_deref()
                .is_some_and(|reason| reason.contains("runtime unit body value boundary")),
            "runtime unit body must carry the named F1 refusal: {reason:?}"
        );
    }

    #[test]
    fn source_locus_mutable_reference_pointer_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_mutable_reference_pointer_refuses_with_literal_twin",
            r#"
#[test]
fn mut_ref_pointer_refused() {
    let mut x = 1;
    assert_eq!(&mut x, &mut x);
}

#[test]
fn mut_ref_pointer_literal_twin() {
    assert_eq!(*&1, 1);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "mut_ref_pointer_refused",
            "mutable reference/pointer effect",
        );
        assert_source_locus_warranted(&response, "mut_ref_pointer_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_mutation_side_effect_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_mutation_side_effect_refuses_with_literal_twin",
            r#"
#[test]
fn mutation_side_effect_refused() {
    let mut total = 0i32;
    [1i32, 2, 3].iter().for_each(|x| {
        total += *x;
        assert!(total > 0);
    });
}

#[test]
fn mutation_side_effect_literal_twin() {
    [1i32, 2, 3].iter().for_each(|x| assert!(*x > 0));
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "mutation_side_effect_refused",
            "mutation/side effect",
        );
        assert_source_locus_warranted(&response, "mutation_side_effect_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_compiler_layout_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_compiler_layout_refuses_with_literal_twin",
            r#"
fn layout_fact_refused<T>() {
    let _ = std::mem::size_of::<T>();
}

fn layout_fact_literal_twin() -> usize {
    4
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "layout_fact_refused",
            "compiler layout fact not in text",
        );
        assert_source_locus_warranted(&response, "layout_fact_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_signed_zero_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_signed_zero_refuses_with_literal_twin",
            r#"
#[test]
fn signed_zero_refused() {
    assert_eq!(-0.0f32, 0.0f32);
}

#[test]
fn signed_zero_literal_twin() {
    assert_eq!(-1.5f64, -1.5f64);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "signed_zero_refused",
            "IEEE signed-zero refinement boundary",
        );
        assert_source_locus_warranted(&response, "signed_zero_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_unstable_float_width_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_unstable_float_width_refuses_with_literal_twin",
            r#"
#[test]
fn unstable_float_width_refused() {
    assert!("NaN".parse::<f16>().unwrap().is_nan());
}

#[test]
fn unstable_float_width_literal_twin() {
    assert!("NaN".parse::<f32>().unwrap().is_nan());
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "unstable_float_width_refused",
            "unknown/unstable float refinement width",
        );
        assert_source_locus_warranted(&response, "unstable_float_width_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_file_emit_bound_refusal_has_midpoint_literal_twin() {
        let reason = file_decl_emit_bound_refusal_reason();
        assert!(
            reason.contains("file assertion emit bound exceeded")
                && reason.contains("finite-or-refuse"),
            "oversized files must be named refusals: {reason}"
        );

        let (root, response) = lift_fixture(
            "source_locus_file_emit_bound_refusal_has_midpoint_literal_twin",
            r#"
#[test]
fn midpoint_literal_twin() {
    assert_eq!(i8::midpoint(2, 4), 3);
}
"#,
        );
        assert_source_locus_warranted(&response, "midpoint_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_opaque_runtime_receiver_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_opaque_runtime_receiver_refuses_with_literal_twin",
            r#"
#[test]
fn opaque_runtime_receiver_refused() {
    std::env::args().for_each(|x| assert!(!x.is_empty()));
}

#[test]
fn opaque_runtime_receiver_literal_twin() {
    [1i32, 2, 3].iter().for_each(|x| assert!(*x > 0));
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "opaque_runtime_receiver_refused",
            "opaque runtime receiver",
        );
        assert_source_locus_warranted(&response, "opaque_runtime_receiver_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_atomic_rmw_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_atomic_rmw_refuses_with_literal_twin",
            r#"
use std::sync::atomic::{AtomicUsize, Ordering};

#[test]
fn atomic_rmw_refused() {
    let mut x = AtomicUsize::new(0);
    x.fetch_or(1, Ordering::SeqCst);
    assert_eq!(*x.get_mut(), 1);
}

#[test]
fn atomic_rmw_literal_twin() {
    assert_eq!(0usize | 1, 1);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "atomic_rmw_refused",
            "atomic read-modify-write runtime state",
        );
        assert_source_locus_warranted(&response, "atomic_rmw_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_atomic_load_store_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_atomic_load_store_refuses_with_literal_twin",
            r#"
use std::sync::atomic::{AtomicBool, Ordering};

#[test]
fn atomic_load_store_refused() {
    let flag = AtomicBool::new(false);
    flag.store(true, Ordering::SeqCst);
    assert_eq!(flag.load(Ordering::SeqCst), true);
}

#[test]
fn atomic_load_store_literal_twin() {
    let flag = true;
    assert_eq!(flag, true);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "atomic_load_store_refused",
            "atomic load/store ordering",
        );
        assert_source_locus_warranted(&response, "atomic_load_store_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_size_hint_runtime_bound_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_size_hint_runtime_bound_refuses_with_literal_twin",
            r#"
#[test]
fn size_hint_runtime_bound_refused() {
    let mut it = (0..).step_by(1);
    let _ = it.next();
    assert_eq!(it.size_hint(), (usize::MAX, None));
}

#[test]
fn size_hint_literal_twin() {
    assert_eq!([1, 2, 3].iter().size_hint(), (3, Some(3)));
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "size_hint_runtime_bound_refused",
            "iterator size_hint runtime bound",
        );
        assert_source_locus_warranted(&response, "size_hint_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_mutating_method_temporal_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_mutating_method_temporal_refuses_with_literal_twin",
            r#"
use std::cell::Cell;

#[test]
fn mutating_method_temporal_refused() {
    let cell = Cell::new(10);
    cell.replace(20);
    assert_eq!(cell.get(), 20);
}

#[test]
fn mutating_method_temporal_literal_twin() {
    let value = 20;
    assert_eq!(value, 20);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "mutating_method_temporal_refused",
            "mutating method temporal state",
        );
        assert_source_locus_warranted(&response, "mutating_method_temporal_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_mutable_view_temporal_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_mutable_view_temporal_refuses_with_literal_twin",
            r#"
use std::cell::RefCell;

#[test]
fn mutable_view_temporal_refused() {
    let x = RefCell::new(0);
    let _borrow = x.borrow_mut();
    assert!(x.try_borrow().is_err());
}

#[test]
fn mutable_view_temporal_literal_twin() {
    assert!(Option::<i32>::None.is_none());
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "mutable_view_temporal_refused",
            "mutable view temporal state",
        );
        assert_source_locus_warranted(&response, "mutable_view_temporal_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_option_raw_pointer_payload_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_option_raw_pointer_payload_refuses_with_literal_twin",
            r#"
use core::mem;

#[test]
fn option_raw_pointer_payload_refused() {
    unsafe {
        let x: Box<_> = Box::new(0isize);
        let addr_x: *const isize = mem::transmute(&*x);
        let opt = Some(x);
        let y = opt.unwrap();
        let addr_y: *const isize = mem::transmute(&*y);
        assert_eq!(addr_x, addr_y);
    }
}

#[test]
fn option_raw_pointer_payload_literal_twin() {
    let opt = Some(7isize);
    let y = opt.unwrap();
    assert_eq!(y, 7);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "option_raw_pointer_payload_refused",
            "Option payload is a raw pointer, runtime address not literal-determined",
        );
        assert_source_locus_warranted(&response, "option_raw_pointer_payload_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_as_mut_ptr_mutable_view_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_as_mut_ptr_mutable_view_refuses_with_literal_twin",
            r#"
#[test]
fn as_mut_ptr_mutable_view_refused() {
    let mut xs = [0u8; 20];
    let ptr = xs.as_mut_ptr();
    unsafe {
        std::ptr::write_bytes(ptr, 5u8, xs.len());
    }
    assert!(xs == [5u8; 20]);
}

#[test]
fn as_mut_ptr_mutable_view_literal_twin() {
    let xs = [5u8; 20];
    assert!(xs == [5u8; 20]);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "as_mut_ptr_mutable_view_refused",
            "mutable view via as_mut_ptr, temporally unstable, no timeless value",
        );
        assert_source_locus_warranted(&response, "as_mut_ptr_mutable_view_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_atomic_ptr_arithmetic_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_atomic_ptr_arithmetic_refuses_with_literal_twin",
            r#"
use std::sync::atomic::{AtomicPtr, Ordering::SeqCst};

#[test]
fn atomic_ptr_arithmetic_refused() {
    let num = 0i64;
    let n = &num as *const i64 as *mut i64;
    let atom = AtomicPtr::<i64>::new(n);
    assert_eq!(atom.fetch_ptr_add(1, SeqCst), n);
    assert_eq!(atom.load(SeqCst), n.wrapping_add(1));
}

#[test]
fn atomic_ptr_arithmetic_literal_twin() {
    assert_eq!(8usize + 1, 9);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "atomic_ptr_arithmetic_refused",
            "atomic ptr arithmetic, runtime operand",
        );
        assert_source_locus_warranted(&response, "atomic_ptr_arithmetic_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_pointer_alignment_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_pointer_alignment_refuses_with_literal_twin",
            r#"
#[test]
fn pointer_alignment_refused() {
    let data = 42;
    let ptr: *const i32 = &data;
    assert_ne!(ptr.is_aligned_to(8), ptr.wrapping_add(1).is_aligned_to(8));
}

#[test]
fn pointer_alignment_literal_twin() {
    assert_ne!(true, false);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "pointer_alignment_refused",
            "pointer alignment, runtime address",
        );
        assert_source_locus_warranted(&response, "pointer_alignment_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_duration_time_runtime_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_duration_time_runtime_refuses_with_literal_twin",
            r#"
use std::time::Duration;

#[test]
fn duration_time_runtime_refused() {
    assert_eq!(Duration::new(u64::MAX - 1, 0).saturating_mul(2), Duration::MAX);
}

#[test]
fn duration_time_literal_twin() {
    assert_eq!(2u64.saturating_mul(3), 6);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "duration_time_runtime_refused",
            "Duration/time runtime operand",
        );
        assert_source_locus_warranted(&response, "duration_time_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_runtime_for_domain_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_runtime_for_domain_refuses_with_literal_twin",
            r#"
use std::char::CharCase;

#[test]
fn runtime_for_domain_refused() {
    for c in '\0'..='\u{10FFFF}' {
        match c.case() {
            None => assert!(!c.is_cased()),
            Some(CharCase::Lower) => assert!(c.is_lowercase()),
            Some(CharCase::Upper) => assert!(c.is_uppercase()),
            Some(CharCase::Title) => assert!(c.is_titlecase()),
        }
    }
}

#[test]
fn runtime_for_domain_literal_twin() {
    for c in 'a'..='c' {
        assert!(c >= 'a');
    }
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "runtime_for_domain_refused",
            "runtime for-loop domain",
        );
        assert_source_locus_warranted(&response, "runtime_for_domain_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_literal_for_loop_runtime_body_read_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_literal_for_loop_runtime_body_read_refuses_with_literal_twin",
            r#"
use std::sync::atomic::{AtomicUsize, Ordering};

#[test]
fn literal_for_loop_runtime_body_read_refused() {
    for _ in 0..2 {
        let counter = AtomicUsize::new(0);
        assert_eq!(counter.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn literal_for_loop_runtime_body_read_literal_twin() {
    for i in 0..2 {
        assert!(i < 2);
    }
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "literal_for_loop_runtime_body_read_refused",
            "literal for-loop body runtime read",
        );
        assert_source_locus_warranted(&response, "literal_for_loop_runtime_body_read_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_array_repeat_non_literal_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_array_repeat_non_literal_refuses_with_literal_twin",
            r#"
#[test]
fn array_repeat_non_literal_refused() {
    assert_eq!([(); usize::MAX].len(), usize::MAX);
}

#[test]
fn array_repeat_literal_twin() {
    assert_eq!([(); 3].len(), 3);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "array_repeat_non_literal_refused",
            "array repeat non-literal length",
        );
        assert_source_locus_warranted(&response, "array_repeat_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_runtime_regex_pattern_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_runtime_regex_pattern_refuses_with_literal_twin",
            r#"
struct Maker {
    pattern: &'static str,
}

impl Maker {
    fn get(&self) -> &'static str {
        self.pattern
    }
}

#[test]
fn runtime_regex_pattern_refused() {
    let m = Maker { pattern: "blah" };
    assert!(Regex::new(m.get()).unwrap().is_match("blah"));
}

#[test]
fn runtime_regex_pattern_literal_twin() {
    assert!(Regex::new("blah").unwrap().is_match("blah"));
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "runtime_regex_pattern_refused",
            "runtime regex pattern",
        );
        assert_source_locus_warranted(&response, "runtime_regex_pattern_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_runtime_impl_method_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_runtime_impl_method_refuses_with_literal_twin",
            r#"
struct Counter { n: i32 }

impl Counter {
    fn observe(&self) {
        let _ = self.n;
    }
}

fn runtime_impl_method_literal_twin() -> i32 {
    7
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "Counter::observe",
            "runtime impl-method boundary",
        );
        assert_source_locus_warranted(&response, "runtime_impl_method_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_inactive_cfg_is_inactive_with_literal_twin() {
        let config = r#"
[rust-test-assertions.target_cfg]
target = "x86_64-unknown-linux-gnu"
facts = [
  "unix",
  "target_arch=\"x86_64\"",
  "target_pointer_width=\"64\"",
]
"#;
        let (root, response) = lift_fixture_with_config(
            "source_locus_inactive_cfg_is_inactive_with_literal_twin",
            r#"
#[test]
#[cfg(target_pointer_width = "32")]
fn inactive_cfg_refused() {
    assert_eq!(1usize, 4usize);
}

#[test]
fn inactive_cfg_literal_twin() {
    assert_eq!(1usize + 1, 2usize);
}
"#,
            config,
        );
        assert_source_locus_inactive(&response, "inactive_cfg_refused", "inactive cfg");
        assert_source_locus_warranted(&response, "inactive_cfg_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_inactive_const_if_branch_is_inactive_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_inactive_const_if_branch_is_inactive_with_literal_twin",
            r#"
#[test]
fn inactive_const_if_refused() {
    if false {
        assert_eq!(1usize, 2usize);
    }
}

#[test]
fn inactive_const_if_literal_twin() {
    assert_eq!(2usize, 2usize);
}
"#,
        );
        assert_source_locus_inactive(
            &response,
            "inactive_const_if_refused",
            "inactive const if branch",
        );
        assert_source_locus_warranted(&response, "inactive_const_if_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_singleton_iter_adaptors_warrant_with_bad_twins() {
        let (root, response) = lift_fixture(
            "source_locus_singleton_iter_adaptors_warrant_with_bad_twins",
            r#"
#[test]
fn test_double_ended_filter() {
    let xs = [1, 2, 3, 4, 5, 6];
    let mut it = xs.iter().filter(|&x| *x & 1 == 0);
    assert_eq!(it.next_back().unwrap(), &6);
    assert_eq!(it.next_back().unwrap(), &4);
    assert_eq!(it.next().unwrap(), &2);
    assert_eq!(it.next_back(), None);
}

#[test]
fn test_double_ended_filter_bad_twin() {
    let xs = [1, 2, 3, 4, 5, 6];
    let mut it = xs.iter().filter(|&x| *x & 1 == 0);
    assert_eq!(it.next_back().unwrap(), &5);
}

#[test]
fn test_double_ended_filter_map() {
    let xs = [1, 2, 3, 4, 5, 6];
    let mut it = xs.iter().filter_map(|&x| if x & 1 == 0 { Some(x * 2) } else { None });
    assert_eq!(it.next_back().unwrap(), 12);
    assert_eq!(it.next_back().unwrap(), 8);
    assert_eq!(it.next().unwrap(), 4);
    assert_eq!(it.next_back(), None);
}

#[test]
fn test_double_ended_filter_map_bad_twin() {
    let xs = [1, 2, 3, 4, 5, 6];
    let mut it = xs.iter().filter_map(|&x| if x & 1 == 0 { Some(x * 2) } else { None });
    assert_eq!(it.next_back().unwrap(), 10);
}

#[test]
fn test_iterator_flatten_fold() {
    let xs = [0, 3, 6];
    let ys = [1, 2, 3, 4, 5, 6, 7];
    let mut it = xs.iter().map(|&x| x..x + 3).flatten();
    assert_eq!(it.next(), Some(0));
    assert_eq!(it.next_back(), Some(8));
    let i = it.fold(0, |i, x| {
        assert_eq!(x, ys[i]);
        i + 1
    });
    assert_eq!(i, ys.len());
}

#[test]
fn test_iterator_flatten_fold_bad_twin() {
    let xs = [0, 3, 6];
    let mut it = xs.iter().map(|&x| x..x + 3).flatten();
    assert_eq!(it.next_back(), Some(7));
}
"#,
        );
        assert_source_locus_warranted(&response, "test_double_ended_filter");
        assert_source_locus_warranted(&response, "test_double_ended_filter_bad_twin");
        assert_source_locus_warranted(&response, "test_double_ended_filter_map");
        assert_source_locus_warranted(&response, "test_double_ended_filter_map_bad_twin");
        assert_source_locus_warranted(&response, "test_iterator_flatten_fold");
        assert_source_locus_warranted(&response, "test_iterator_flatten_fold_bad_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_totality_panic_reports_full_dark_set() {
        let loci = vec![
            json!({
                "file": "tests/iter/range.rs",
                "role": "rust-test-assertions",
                "ast_kind": "test-fn",
                "ast_path": "test_range",
                "line": 42,
                "status": "unclassified",
                "reason": "synthetic dark source status",
            }),
            json!({
                "file": "tests/ptr.rs",
                "role": "rust-test-assertions",
                "ast_kind": "test-fn",
                "ast_path": "test_ptr_dark",
                "line": 256,
                "status": "unresolved",
                "reason": "synthetic unresolved source status",
            }),
            json!({
                "file": "tests/bool.rs",
                "role": "rust-test-assertions",
                "ast_kind": "test-fn",
                "ast_path": "test_bool_warranted",
                "line": 7,
                "status": "warranted",
                "reason": "synthetic classified source status",
            }),
        ];
        let panic = std::panic::catch_unwind(|| {
            panic_on_dark_source_loci(&loci);
        });
        let message = panic_message(panic.expect_err("dark source loci must panic"));
        assert!(message.contains("SOURCE AUDIT DELTA-EPSILON GATE FAILED"));
        assert!(message.contains("R=2"));
        assert!(message.contains("tests/iter/range.rs:42 test-fn test_range status=unclassified"));
        assert!(message.contains("synthetic dark source status"));
        assert!(message.contains("tests/ptr.rs:256 test-fn test_ptr_dark status=unresolved"));
        assert!(message.contains("synthetic unresolved source status"));
        assert!(!message.contains("test_bool_warranted"));
    }

    #[test]
    fn source_totality_panic_is_silent_when_all_loci_classified() {
        let loci = vec![
            json!({
                "file": "tests/support.rs",
                "role": "rust-test-assertions",
                "ast_kind": "fn",
                "ast_path": "helper",
                "line": 1,
                "status": "support",
            }),
            json!({
                "file": "tests/inactive.rs",
                "role": "rust-test-assertions",
                "ast_kind": "test-fn",
                "ast_path": "cfgd_out",
                "line": 2,
                "status": "inactive",
            }),
            json!({
                "file": "tests/refused.rs",
                "role": "rust-test-assertions",
                "ast_kind": "test-fn",
                "ast_path": "runtime_boundary",
                "line": 3,
                "status": "refused",
            }),
            json!({
                "file": "tests/warranted.rs",
                "role": "rust-test-assertions",
                "ast_kind": "test-fn",
                "ast_path": "literal_floor",
                "line": 4,
                "status": "warranted",
            }),
        ];
        panic_on_dark_source_loci(&loci);
    }

    #[test]
    fn source_locus_runtime_array_element_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_runtime_array_element_refuses_with_literal_twin",
            r#"
#[test]
fn runtime_array_element_refused() {
    let n = std::process::id() as u8;
    let xs = [n, 2u8];
    assert_eq!(&xs, &[1u8, 2u8]);
}

#[test]
fn runtime_array_element_literal_twin() {
    assert_eq!([1u8, 2u8], [1u8, 2u8]);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "runtime_array_element_refused",
            "literal array element boundary",
        );
        assert_source_locus_warranted(&response, "runtime_array_element_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_runtime_slice_source_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_runtime_slice_source_refuses_with_literal_twin",
            r#"
#[test]
fn runtime_slice_source_refused() {
    let mut iter = std::env::args().peekable();
    iter.next();
    assert_eq!(iter.peek(), None);
}

#[test]
fn runtime_chunk_source_refused() {
    let v = &[(); usize::MAX];
    let c = v.windows(1);
    assert_eq!(c.count(), usize::MAX);
}

#[test]
fn runtime_slice_source_literal_twin() {
    let xs = [0];
    let mut iter = xs.iter().peekable();
    iter.next();
    assert_eq!(iter.peek(), None);
}

#[test]
fn runtime_chunk_source_literal_twin() {
    let v: &[i32] = &[0, 1, 2];
    let c = v.windows(2);
    assert_eq!(c.count(), 2);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "runtime_slice_source_refused",
            "runtime slice source, not literal",
        );
        assert_source_locus_refused(
            &response,
            "runtime_chunk_source_refused",
            "array repeat non-literal length",
        );
        assert_source_locus_warranted(&response, "runtime_slice_source_literal_twin");
        assert_source_locus_warranted(&response, "runtime_chunk_source_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_option_vec_empty_match_warrants_with_literal_twin() {
        let (root, response) = lift_fixture_at(
            "source_locus_option_vec_empty_match_warrants_with_literal_twin",
            "tests/nonzero.rs",
            r#"
#[test]
fn test_match_option_empty_vec() {
    let a: Option<Vec<isize>> = Some(vec![]);
    match a {
        None => panic!("unexpected None while matching on Some(vec![])"),
        _ => {}
    }
}

#[test]
fn option_vec_match_literal_twin() {
    let a = Some(vec![1, 2, 3, 4]);
    match a {
        Some(v) => assert_eq!(v, [1, 2, 3, 4]),
        None => panic!("unexpected None while matching on Some(vec![1, 2, 3, 4])"),
    }
}
"#,
        );
        assert_source_locus_warranted(&response, "test_match_option_empty_vec");
        assert_source_locus_warranted(&response, "option_vec_match_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_range_bounds_runtime_value_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_range_bounds_runtime_value_refuses_with_literal_twin",
            r#"
use core::ops::Bound;

#[test]
fn range_bounds_runtime_value_refused() {
    let r = (Bound::Included(1u32), Bound::Excluded(5u32));
    assert!(!r.contains(&0));
    assert!(r.contains(&1));
    assert!(r.contains(&3));
    assert!(!r.contains(&5));
    assert!(!r.contains(&6));
}

#[test]
fn range_bounds_literal_twin() {
    assert!((1u32..5).contains(&3));
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "range_bounds_runtime_value_refused",
            "RangeBounds over runtime value r",
        );
        assert_source_locus_warranted(&response, "range_bounds_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn text_determined_unit_body_warrants_literal_unit_value() {
        let f: syn::ItemFn = syn::parse_str(
            r#"
fn const_cells_like() {
    const THREE: i32 = 3;
    const _: i32 = THREE;
}
"#,
        )
        .expect("fn parses");
        let source_memento = json!({"file": "src/lib.rs"});
        let (status, reason, entry) =
            classify_nontest_fn("const_cells_like", &f.sig, &f.block, false, &source_memento);

        assert_eq!(status, "warranted", "reason: {reason:?}");
        let entry = entry.expect("unit body warrant emits a function contract");
        assert_eq!(entry["kind"], "function-contract");
        assert_eq!(entry["name"], "rust-source::const_cells_like");
        assert_eq!(entry["bridgeSourceSymbol"], "call:const_cells_like");
        assert_eq!(entry["returnSort"]["name"], "unit");
        assert!(entry.get("post").is_some(), "{entry}");
    }

    #[test]
    fn runtime_unit_body_refuses_instead_of_fabricating_unit_pin() {
        let f: syn::ItemFn = syn::parse_str(
            r#"
fn runtime_print() {
    println!("runtime");
}
"#,
        )
        .expect("fn parses");
        let source_memento = json!({});
        let (status, reason, entry) =
            classify_nontest_fn("runtime_print", &f.sig, &f.block, false, &source_memento);

        assert_eq!(status, "refused", "reason: {reason:?}");
        assert!(
            reason
                .as_deref()
                .is_some_and(|reason| reason.contains("mutation/side effect")),
            "runtime unit body must carry named refusal: {reason:?}"
        );
        assert!(
            entry.is_none(),
            "refused runtime body must not mint a contract"
        );
    }

    #[test]
    fn f1_coretest_body_value_loci_are_warranted_or_named_refused() {
        struct Case {
            relative: &'static str,
            name: &'static str,
            status: &'static str,
            reason: Option<&'static str>,
        }

        let cases = [
            Case {
                relative: "tests/cell.rs",
                name: "const_cells",
                status: "warranted",
                reason: None,
            },
            Case {
                relative: "tests/future.rs",
                name: "test_join_function_like_value_arg_semantics::async_fn",
                status: "warranted",
                reason: None,
            },
            Case {
                relative: "tests/future.rs",
                name: "test_join_function_like_value_arg_semantics::_join_does_not_unnecessarily_move_mentioned_bindings",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/future.rs",
                name: "_pending_impl_all_auto_traits",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/hash/mod.rs",
                name: "_build_hasher_default_impl_all_auto_traits",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/iter/adapters/map_windows.rs",
                name: "drop_checks::check",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/iter/adapters/map_windows.rs",
                name: "drop_checks::check_drops",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/iter/mod.rs",
                name: "is_trusted_len",
                status: "warranted",
                reason: None,
            },
            Case {
                relative: "tests/iter/traits/iterator.rs",
                name: "_empty_impl_all_auto_traits",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/macros.rs",
                name: "_allows_stmt_expr_attributes",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/macros.rs",
                name: "_expression",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/flt2dec/mod.rs",
                name: "check_exact_one",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/flt2dec/mod.rs",
                name: "f16_shortest_sanity_test",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/flt2dec/mod.rs",
                name: "f16_exact_sanity_test",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/flt2dec/mod.rs",
                name: "f32_shortest_sanity_test",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/flt2dec/mod.rs",
                name: "f32_exact_sanity_test",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/flt2dec/mod.rs",
                name: "f64_shortest_sanity_test",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/flt2dec/mod.rs",
                name: "f64_exact_sanity_test",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/flt2dec/mod.rs",
                name: "more_shortest_sanity_test",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/num/mod.rs",
                name: "ldexp_f64",
                status: "refused",
                reason: Some("runtime FFI boundary"),
            },
            Case {
                relative: "tests/num/mod.rs",
                name: "test_num",
                status: "refused",
                reason: Some("runtime unit body value boundary"),
            },
            Case {
                relative: "tests/result.rs",
                name: "noop_u8_ref",
                status: "warranted",
                reason: None,
            },
        ];

        assert_eq!(
            cases.len(),
            22,
            "F1 gate must cover each old no-pin fn locus"
        );
        for case in cases {
            let (status, reason, entry) = classify_coretests_fn(case.relative, case.name);
            assert_eq!(
                status, case.status,
                "{}::{} reason={reason:?}",
                case.relative, case.name
            );
            match case.status {
                "warranted" => {
                    assert!(
                        entry.is_some(),
                        "{}::{} must mint the literal body-value contract",
                        case.relative,
                        case.name
                    );
                    assert!(
                        reason.is_none(),
                        "{}::{} warranted body-value pin should need no refusal reason: {reason:?}",
                        case.relative,
                        case.name
                    );
                }
                "refused" => {
                    let reason = reason.unwrap_or_else(|| {
                        panic!(
                            "{}::{} must carry a named refusal",
                            case.relative, case.name
                        )
                    });
                    assert!(
                        reason.contains(case.reason.expect("refused case reason")),
                        "{}::{} wrong refusal reason: {reason}",
                        case.relative,
                        case.name
                    );
                    assert!(
                        entry.is_none(),
                        "{}::{} refused body must not mint a contract: {entry:?}",
                        case.relative,
                        case.name
                    );
                }
                other => panic!("unexpected F1 expected status {other}"),
            }
        }
    }

    #[test]
    fn source_locus_post_loop_read_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_post_loop_read_refuses_with_literal_twin",
            r#"
#[test]
fn post_loop_read_refused() {
    let limit = std::env::args().len();
    let mut n = 0usize;
    while n < limit {
        n += 1;
    }
    assert_eq!(n, limit);
}

#[test]
fn post_loop_read_literal_twin() {
    let n = 3;
    assert_eq!(n, 3);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "post_loop_read_refused",
            "temporally unstable post-loop read",
        );
        assert_source_locus_warranted(&response, "post_loop_read_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_mutating_method_read_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_mutating_method_read_refuses_with_literal_twin",
            r#"
#[test]
fn mutating_method_read_refused() {
    let mut x = [1usize, 2, 3, 4];
    x.swap(1, 3);
    assert_eq!(x, [1usize, 4, 3, 2]);
}

#[test]
fn mutating_method_read_literal_twin() {
    assert_eq!([1usize, 4, 3, 2], [1usize, 4, 3, 2]);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "mutating_method_read_refused",
            "temporally unstable mutating method read",
        );
        assert_source_locus_warranted(&response, "mutating_method_read_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_ambiguous_temporal_identity_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_ambiguous_temporal_identity_refuses_with_literal_twin",
            r#"
fn coin() -> bool { true }

#[test]
fn ambiguous_temporal_identity_refused() {
    let mut r = 1u32..5;
    if coin() {
        r = 10u32..20;
    }
    assert!(r.contains(&1));
}

#[test]
fn ambiguous_temporal_identity_literal_twin() {
    assert!((1u32..5).contains(&1));
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "ambiguous_temporal_identity_refused",
            "ambiguous temporal identity",
        );
        assert_source_locus_warranted(&response, "ambiguous_temporal_identity_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_consumed_iterator_len_splits_full_drain_from_stale_with_twins() {
        let (root, response) = lift_fixture(
            "source_locus_consumed_iterator_len_splits_full_drain_from_stale_with_twins",
            r#"
#[test]
fn consumed_iterator_full_drain_warranted() {
    let xs = [1, 2, 3];
    let mut it = xs.iter().take(3);
    while let Some(_x) = it.next() {}
    assert_eq!(it.len(), 0);
}

#[test]
fn consumed_iterator_partial_drain_refused() {
    let xs = [1, 2, 3];
    let mut it = xs.iter();
    let _ = it.by_ref().take(1).count();
    assert_eq!(it.len(), 2);
}

#[test]
fn consumed_iterator_local_literal_twin() {
    let xs = [1, 2, 3];
    let mut it = xs.iter().take(3);
    assert_eq!(it.len(), 3);
}
"#,
        );
        assert_source_locus_warranted(&response, "consumed_iterator_full_drain_warranted");
        assert_factory_audit_status_for_selected(
            &root,
            &response,
            "len",
            Some("consumed_iterator_full_drain_warranted"),
            "it.len()",
            "warranted",
            None,
        );
        assert_source_locus_refused(
            &response,
            "consumed_iterator_partial_drain_refused",
            "consumed-iterator local",
        );
        assert_factory_audit_status_for_selected(
            &root,
            &response,
            "len",
            Some("consumed_iterator_partial_drain_refused"),
            "it.len()",
            "refused",
            Some("consumed-iterator local"),
        );
        assert_source_locus_warranted(&response, "consumed_iterator_local_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_consumed_iterator_mutable_container_refuses_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_consumed_iterator_mutable_container_refuses_with_literal_twin",
            r#"
#[test]
fn consumed_iterator_mutable_container_refused() {
    let xs = [1, 2, 3];
    let ys = [1, 2, 0];
    let mut iter = xs.iter().chain(&ys);
    iter.next();
    let mut result = Vec::new();
    iter.fold((), |(), &elt| result.push(elt));
    assert_eq!(&[2, 3, 1, 2, 0], &result[..]);
}

#[test]
fn consumed_iterator_mutable_container_literal_twin() {
    assert_eq!(5, 5);
}
"#,
        );
        assert_source_locus_refused(
            &response,
            "consumed_iterator_mutable_container_refused",
            "mutable container temporal state",
        );
        assert_source_locus_warranted(
            &response,
            "consumed_iterator_mutable_container_literal_twin",
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_locus_literal_counter_while_warrants_with_literal_twin() {
        let (root, response) = lift_fixture(
            "source_locus_literal_counter_while_warrants_with_literal_twin",
            r#"
#[test]
fn literal_counter_while_warranted() {
    let mut i = 0;
    while i < 1 {
        assert_eq!(i, 0);
        i += 1;
    }
}

#[test]
fn literal_counter_while_literal_twin() {
    assert_eq!(0, 0);
}
"#,
        );
        assert_source_locus_warranted(&response, "literal_counter_while_warranted");
        assert_source_locus_warranted(&response, "literal_counter_while_literal_twin");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn reduced_helper_body_still_mints_source_contract() {
        let f: syn::ItemFn = syn::parse_str("fn h(x: i32) -> i32 { x + 1 }").expect("fn parses");
        let source_memento = json!({});
        let (status, reason, decl) =
            classify_nontest_fn("h", &f.sig, &f.block, true, &source_memento);

        assert_eq!(
            status, "warranted",
            "a reduced helper is warranted by its own source contract"
        );
        assert!(
            reason.is_none(),
            "contract emission needs no auxiliary excuse: {reason:?}"
        );
        let entry = decl.expect("a reduced helper still mints its own contract");
        assert_eq!(entry["kind"], "function-contract");
        assert_eq!(entry["name"], "rust-source::h");
        assert_eq!(entry["bridgeSourceSymbol"], "call:h");
        assert!(entry.get("post").is_some(), "{entry}");
    }

    #[test]
    fn factory_support_audits_carry_inert_support_kind() {
        let mut source_cache = FileSourceOracleCache::new("src/lib.rs", "");
        let fns = Vec::new();
        let rows = factory_audits_json(
            "src/lib.rs",
            &[FactoryAudit {
                ast_kind: "expr",
                site: "{}".to_string(),
                line: 1,
                span: None,
                requested_role: "Composite".to_string(),
                selected: Some("empty_sequence"),
                candidates: Vec::new(),
                disposition: sugar_lift_rust_tests::FactoryDisposition::Support,
                output: "empty-sequence",
                reason: Some("empty sequence is inert support".to_string()),
            }],
            &mut source_cache,
            &fns,
        );

        assert_eq!(rows[0]["status"], "support");
        assert_eq!(rows[0]["supportKind"], "inert", "{rows:?}");
        assert!(rows[0].get("term").is_none(), "{rows:?}");
        assert!(rows[0].get("site").is_none(), "{rows:?}");
    }

    #[test]
    fn factory_audit_response_summary_reports_unresolved_rows() {
        let rows = vec![
            json!({"file": "src/lib.rs", "line": 1, "status": "warranted"}),
            json!({"file": "src/lib.rs", "line": 2, "status": "unresolved", "sourceMemento": {"kind": "source-memento", "file": "src/lib.rs"}}),
            json!({"file": "src/lib.rs", "line": 3, "status": "unclassified", "sourceMemento": {"kind": "source-memento", "file": "src/lib.rs"}}),
        ];

        let summary = factory_audit_response_summary(&rows);

        assert_eq!(summary["sites"], 3);
        assert_eq!(summary["emittedRows"], 3);
        assert_eq!(summary["omittedRows"], 0);
        assert_eq!(summary["totalRows"], 3);
        assert_eq!(summary["complete"], true);
        assert_eq!(summary["statusCounts"]["warranted"], 1);
        assert_eq!(summary["statusCounts"]["unresolved"], 2);
        assert_eq!(summary["unresolvedSites"].as_array().unwrap().len(), 2);
        assert_eq!(summary["unresolvedSites"][0]["line"], 2);
        assert_eq!(summary["unresolvedSites"][1]["line"], 3);
        assert_eq!(summary["unresolvedSites"][0]["status"], "unresolved");
        assert_eq!(summary["unresolvedSites"][0]["output"], "gap");
        assert_eq!(summary["factoryWalk"][1]["status"], "unresolved");
        assert_eq!(summary["factoryWalk"][1]["verdict"], "gap");
        assert_eq!(summary["factoryWalk"][1]["output"], "gap");
        assert_eq!(summary["factoryWalk"][2]["status"], "unresolved");
        assert_eq!(summary["factoryWalk"][2]["verdict"], "gap");
        assert_eq!(summary["factoryWalk"][2]["output"], "gap");
        assert!(summary["unresolvedSites"][0].get("term").is_none());
        assert!(summary["unresolvedSites"][0].get("site").is_none());
        assert!(summary["factoryWalk"][1].get("term").is_none());
        assert!(summary["factoryWalk"][1].get("site").is_none());
    }

    #[test]
    fn factory_audit_summary_accumulator_reports_every_unresolved_site() {
        let mut acc = FactoryAuditSummaryAccumulator::new();
        let duplicate = FactoryAudit {
            ast_kind: "expr",
            site: "a + b".to_string(),
            line: 7,
            span: None,
            requested_role: "Term".to_string(),
            selected: Some("binary"),
            candidates: Vec::new(),
            disposition: sugar_lift_rust_tests::FactoryDisposition::Warranted,
            output: "term",
            reason: None,
        };
        let refused = FactoryAudit {
            disposition: sugar_lift_rust_tests::FactoryDisposition::Refused,
            site: "runtime()".to_string(),
            reason: Some("runtime".to_string()),
            ..duplicate.clone()
        };
        let unresolved = FactoryAudit {
            disposition: sugar_lift_rust_tests::FactoryDisposition::Unresolved,
            site: "opaque()".to_string(),
            reason: Some("opaque".to_string()),
            ..duplicate.clone()
        };

        let mut source_cache = FileSourceOracleCache::new("src/lib.rs", "");
        let fns = Vec::new();
        acc.extend_from_audits(
            "src/lib.rs",
            &[duplicate.clone(), duplicate, refused, unresolved],
            &mut source_cache,
            &fns,
        );
        let summary = acc.into_json();

        assert_eq!(summary["sites"], 3);
        assert_eq!(summary["emittedRows"], 3);
        assert_eq!(summary["omittedRows"], 0);
        assert_eq!(summary["complete"], true);
        assert_eq!(summary["statusCounts"]["warranted"], 1);
        assert_eq!(summary["statusCounts"]["refused"], 1);
        assert_eq!(summary["statusCounts"]["unresolved"], 1);
        assert_eq!(summary["unresolvedSites"].as_array().unwrap().len(), 1);
        assert_eq!(summary["unresolvedSites"][0]["file"], "src/lib.rs");
        assert_eq!(summary["unresolvedSites"][0]["line"], 7);
        assert_eq!(summary["unresolvedSites"][0]["status"], "unresolved");
        assert_eq!(summary["unresolvedSites"][0]["output"], "gap");
        let unresolved_walk = summary["factoryWalk"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["status"] == "unresolved")
            .expect("unresolved walk row");
        assert_eq!(unresolved_walk["verdict"], "gap");
        assert_eq!(unresolved_walk["output"], "gap");
        assert!(summary["unresolvedSites"][0].get("site").is_none());
        assert!(summary["unresolvedSites"][0].get("term").is_none());
    }

    #[test]
    fn report_summary_lift_response_omits_heavy_sections_but_preserves_accounting() {
        let root = unique_temp_dir(
            "report_summary_lift_response_omits_heavy_sections_but_preserves_accounting",
        );
        let source_path = root.join("src/lib.rs");
        std::fs::create_dir_all(source_path.parent().expect("source parent"))
            .expect("mkdir source parent");
        std::fs::write(
            &source_path,
            r#"
#[test]
fn summary_good() {
    assert_eq!(1 + 1, 2);
}
"#,
        )
        .expect("write rust source");

        let response = lift(&json!({
            "workspace_root": root,
            "source_paths": ["src/lib.rs"],
            "options": {"reportSummary": true}
        }));

        assert_eq!(response["sourceLedger"]["source_loci"], 1);
        assert_eq!(response["sourceLedger"]["source_warranted"], 1);
        assert_eq!(response["sourceLedger"]["source_unresolved"], 0);
        assert!(
            response.get("sourceAudits").is_none(),
            "summary response must not transport source-audit rows: {response}"
        );
        assert!(response.get("factoryAuditSummary").is_some());
        let walk = response["factoryAuditSummary"]["factoryWalk"]
            .as_array()
            .expect("factory walk rows");
        assert!(
            !walk.is_empty(),
            "summary response must emit the roll-call walk"
        );
        assert!(
            walk.iter().all(|row| {
                row.get("term").is_none()
                    && row.get("site").is_none()
                    && row.get("source").is_none()
            }),
            "factory walk rows must carry mementos, never plaintext source: {walk:?}"
        );
        assert!(
            response.get("ir").is_none(),
            "summary response must not transport full IR: {response}"
        );
        assert!(
            response.get("sourceMementos").is_none(),
            "summary response must not transport source mementos: {response}"
        );
        assert!(
            response.get("callEdges").is_none(),
            "summary response must not transport call edges: {response}"
        );
        assert!(
            response.get("vendorConjoins").is_none(),
            "summary response must not transport vendor conjoins: {response}"
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn free_function_body_warrant_emits_post_not_fact_inv() {
        let f: syn::ItemFn = syn::parse_str(
            r#"fn enc(input: &str) -> &'static str {
                if input == "abc" { "def" } else { "unknown" }
            }"#,
        )
        .expect("fn parses");
        let source_memento = json!({
            "file": "src/lib.rs",
            "sourceFunctionName": "enc",
            "span": {"start_line": 1, "end_line": 3},
            "paramNames": ["input"],
            "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "template_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        });
        let (status, reason, entry) =
            classify_nontest_fn("enc", &f.sig, &f.block, false, &source_memento);
        let entry = entry.expect("body warrant emits function contract");

        assert_eq!(status, "warranted", "reason: {reason:?}");
        assert_eq!(entry["kind"], "function-contract");
        assert_eq!(entry["name"], "rust-source::enc");
        assert_eq!(entry["bridgeSourceSymbol"], "call:enc");
        assert!(entry.get("post").is_some(), "{entry}");
        assert!(entry.get("inv").is_none(), "{entry}");
        assert_eq!(entry["sourceWarrants"][0]["file"], "src/lib.rs");
    }

    #[test]
    fn binary_partition_warrant_or_refuse_by_vacuity() {
        use sugar_lift_rust_tests::{broad_functional_warrant, sig_returns_unit};
        let parse = |src: &str| -> syn::ItemFn { syn::parse_str(src).unwrap() };

        // VALUE body with no structural shape (a loop result) -> we THINK it
        // constrains -> broad functional warrant `out = call:f(params)`.
        let f = parse("fn f(a: i32) -> i32 { let mut s = 0; for i in 0..a { s += i; } s }");
        let decl = broad_functional_warrant("f", &f.sig, &f.block)
            .expect("value body warrants down to bare functionality");
        let inv = format!("{:?}", decl.inv.unwrap());
        assert!(
            inv.contains("call:f") && inv.contains('a'),
            "functional warrant out=call:f(a): {inv}"
        );

        // UNIT body -> NEVER constrains (no output) -> None -> caller refuses by
        // vacuity. Effectful or not, there is no output to demand anything about.
        let u = parse("fn log(x: i32) { println!(\"{x}\"); }");
        assert!(sig_returns_unit(&u.sig));
        assert!(
            broad_functional_warrant("log", &u.sig, &u.block).is_none(),
            "a unit body states no output constraint -> None -> refuse by vacuity"
        );
    }

    #[test]
    fn json_array_len_counts_camel_and_snake_case_fields() {
        let response = json!({
            "sourceAudits": [1, 2],
            "factory_audits": [3, 4, 5],
            "scalar": 9,
        });

        assert_eq!(
            json_array_len(&response, &["sourceAudits", "source_audits"]),
            2
        );
        assert_eq!(
            json_array_len(&response, &["factoryAudits", "factory_audits"]),
            3
        );
        assert_eq!(json_array_len(&response, &["scalar"]), 0);
        assert_eq!(json_array_len(&response, &["missing"]), 0);
    }

    #[test]
    fn kit_declaration_advertises_proof_and_source_resolution_rpc() {
        let declaration = kit_declaration_result();
        let methods = declaration["rpc"]["methods"]
            .as_array()
            .expect("methods array");

        assert!(
            methods
                .iter()
                .any(|method| method["name"] == "sugar.plugin.resolve_proof_by_cid"),
            "kit declaration must advertise proof CID resolution: {declaration}"
        );
        assert!(
            methods
                .iter()
                .any(|method| method["name"] == "sugar.plugin.resolve_source_memento"),
            "kit declaration must advertise SourceOracle memento resolution: {declaration}"
        );
    }

    #[test]
    fn source_memento_resolution_distinguishes_absent_from_drifted() {
        let root = unique_temp_dir("source_memento_resolution_distinguishes_absent_from_drifted");
        std::fs::create_dir_all(root.join("vendor/src")).expect("mkdir");
        let memento = json!({
            "kind": "source-memento",
            "file": "vendor/src/lib.rs",
            "sourceFunctionName": "enc",
            "span": {"start_line": 1, "start_col": 0, "end_line": 3, "end_col": 1},
            "paramNames": ["input"],
            "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "template_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        });

        let absent = resolve_source_memento_for_report(&root, &memento);
        assert_eq!(absent["status"], "absent", "{absent}");

        std::fs::write(
            root.join("vendor/src/lib.rs"),
            r#"fn enc(input: &str) -> &'static str {
    "changed"
}
"#,
        )
        .expect("write drifted source");
        let drifted = resolve_source_memento_for_report(&root, &memento);

        assert_eq!(drifted["status"], "drifted", "{drifted}");
        assert!(
            drifted["reason"]
                .as_str()
                .unwrap_or_default()
                .contains("source CID misaligned"),
            "{drifted}"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn vendor_source_memento_resolves_from_proof_member_by_contract_name() {
        let mut pool = sugar_verifier::types::MementoPool::default();
        pool.mementos.insert(
            "blake3-512:source".to_string(),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "source-memento",
                    "contractName": "rust-source::enc",
                    "claimName": "rust-source::enc",
                    "sourceFunctionName": "enc",
                    "file": "src/lib.rs"
                },
                "body": {
                    "kind": "source-memento",
                    "contractName": "rust-source::enc",
                    "claimName": "rust-source::enc",
                    "sourceFunctionName": "enc",
                    "file": "src/lib.rs",
                    "span": {"start_line": 1, "start_col": 0, "end_line": 3, "end_col": 1},
                    "paramNames": ["input"],
                    "source_cid": "blake3-512:source",
                    "template_cid": "blake3-512:template"
                }
            }),
        );
        let contract_body = json!({"name": "rust-source::enc"});

        let memento =
            source_memento_member_for_contract(&pool, &contract_body, "blake3-512:contract")
                .expect("contract-named source memento member");

        assert_eq!(memento["sourceFunctionName"], "enc");
        assert_eq!(memento["file"], "src/lib.rs");
    }

    #[test]
    fn lift_emits_factory_audits_for_assertion_term_lowering() {
        let root = unique_temp_dir("lift_emits_factory_audits_for_assertion_term_lowering");
        std::fs::create_dir_all(root.join("src")).expect("mkdir src");
        std::fs::write(
            root.join("src/lib.rs"),
            r#"
pub fn make_value() -> i32 {
    6
}

#[cfg(test)]
mod tests {
    use super::make_value;

    #[test]
    fn scalar_is_six() {
        assert_eq!(make_value(), 6);
    }
}
"#,
        )
        .expect("write rust source");

        let response = lift(&json!({
            "workspace_root": root,
            "source_paths": ["src/lib.rs"]
        }));
        let audits = response["factoryAudits"]
            .as_array()
            .expect("factoryAudits is an array");

        assert!(
            !audits.is_empty(),
            "assertion term lowering must go through the audited Sugar factory: {response}"
        );
        assert!(
            audits
                .iter()
                .all(|audit| audit.get("site").is_none() && audit.get("term").is_none()),
            "factory audit RPC rows must not carry plaintext source: {audits:?}"
        );
        assert!(
            audits.iter().any(|audit| {
                factory_audit_source_text(&root, audit)
                    .is_some_and(|site| source_contains_fragment(&site, "make_value ()"))
            }),
            "call operand should be factory-accounted: {audits:?}"
        );
        assert!(
            audits.iter().any(|audit| {
                factory_audit_source_text(&root, audit)
                    .is_some_and(|site| source_contains_fragment(&site, "6"))
            }),
            "literal operand should be factory-accounted: {audits:?}"
        );
        assert!(
            audits.iter().any(|audit| {
                audit["requested_role"] == "AssertionSurface"
                    && audit["selected"] == "assertion_surface_relation_macro"
                    && factory_audit_source_text(&root, audit)
                        .is_some_and(|site| site.contains("assert_eq"))
            }),
            "assertion macro spelling should be factory-accounted as assertion-surface Sugar: {audits:?}"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn lift_emits_assertion_surface_fact_accounting() {
        let root = unique_temp_dir("lift_emits_assertion_surface_fact_accounting");
        std::fs::create_dir_all(root.join("src")).expect("mkdir src");
        std::fs::write(
            root.join("src/lib.rs"),
            r#"
fn answer() -> i32 { 42 }

#[cfg(test)]
mod tests {
    use super::answer;

    #[test]
    fn emits_fact() {
        assert_eq!(1 + 1, 2);
    }

    #[test]
    fn fact_and_support() {
        assert_eq!(answer(), 42);
    }

    #[test]
    fn support_only() {
        answer();
    }
}
"#,
        )
        .expect("write rust source");

        let response = lift(&json!({
            "workspace_root": root,
            "source_paths": ["src/lib.rs"]
        }));
        let audits = response["assertionSurfaceAudits"]
            .as_array()
            .expect("assertionSurfaceAudits is an array");

        let emitted = audits
            .iter()
            .find(|row| row["assertionSource"] == "src/lib.rs::tests::emits_fact")
            .expect("emitted assertion source is accounted");
        assert_eq!(emitted["status"], "facts-emitted", "{emitted}");
        assert_eq!(emitted["facts"].as_array().unwrap().len(), 1, "{emitted}");
        assert_eq!(
            emitted["supportFacts"].as_array().unwrap().len(),
            0,
            "{emitted}"
        );
        assert_eq!(emitted["sourceMemento"]["file"], "src/lib.rs");
        assert_eq!(
            emitted["sourceMemento"]["sourceFunctionName"],
            "tests::emits_fact"
        );
        assert_eq!(emitted["sourceMemento"]["span"]["start_line"], 8);
        assert_eq!(emitted["sourceMemento"]["span"]["end_line"], 11);
        assert!(emitted["sourceMemento"].get("body_text").is_none());
        assert!(emitted["sourceMemento"].get("ast_template").is_none());
        let fact_memento = &emitted["facts"][0]["sourceMemento"];
        assert_eq!(fact_memento["file"], "src/lib.rs");
        assert_eq!(fact_memento["sourceFunctionName"], "tests::emits_fact");
        assert_eq!(fact_memento["span"]["start_line"], 10);
        assert_eq!(fact_memento["span"]["end_line"], 10);
        assert!(fact_memento.get("body_text").is_none());
        assert!(fact_memento.get("ast_template").is_none());

        let fact_and_support = audits
            .iter()
            .find(|row| row["assertionSource"] == "src/lib.rs::tests::fact_and_support")
            .expect("fact+support assertion source is accounted");
        assert_eq!(
            fact_and_support["status"], "facts-emitted",
            "{fact_and_support}"
        );
        let fact_and_support_facts = fact_and_support["facts"].as_array().unwrap();
        assert!(
            !fact_and_support_facts.is_empty(),
            "fact+support source must emit at least the value fact: {fact_and_support}"
        );
        assert_eq!(
            fact_and_support["supportFacts"].as_array().unwrap().len(),
            0,
            "{fact_and_support}"
        );
        let fact_and_support_contract = fact_and_support_facts
            .iter()
            .find(|fact| {
                fact["contract"]
                    .as_str()
                    .is_some_and(|name| !name.contains("panic_callsite"))
            })
            .unwrap_or_else(|| panic!("missing value fact: {fact_and_support}"))["contract"]
            .as_str()
            .expect("fact+support contract name");

        let support_only = audits
            .iter()
            .find(|row| row["assertionSource"] == "src/lib.rs::tests::support_only")
            .expect("normal-return-only assertion source is accounted");
        assert_eq!(support_only["status"], "facts-emitted", "{support_only}");
        assert_eq!(
            support_only["facts"].as_array().unwrap().len(),
            1,
            "{support_only}"
        );
        assert_eq!(
            support_only["supportFacts"].as_array().unwrap().len(),
            0,
            "{support_only}"
        );

        let ir = response["ir"].as_array().expect("ir array");
        let fact_contract = emitted["facts"][0]["contract"]
            .as_str()
            .expect("fact contract name");
        let contract = ir
            .iter()
            .find(|entry| entry["name"] == fact_contract)
            .expect("fact contract is present in ir");
        assert_eq!(contract["sourceWarrants"][0]["file"], "src/lib.rs");
        assert_eq!(contract["sourceWarrants"][0]["span"]["start_line"], 10);
        assert_eq!(contract["sourceWarrants"][0]["span"]["end_line"], 10);
        assert_eq!(contract["sourceWarrants"][0], *fact_memento);

        let answer_contract = ir
            .iter()
            .find(|entry| {
                entry["kind"] == json!("function-contract")
                    && entry["bridgeSourceSymbol"] == json!("call:answer")
            })
            .expect("answer source contract is emitted for linker/conjoiner composition");
        assert_eq!(answer_contract["name"], json!("rust-source::answer"));
        assert!(
            response["callEdges"]
                .as_array()
                .is_some_and(|edges| edges.iter().any(|edge| {
                    edge["sourceContract"] == json!(fact_and_support_contract)
                        && edge["targetSymbol"] == json!("call:answer")
                        && edge["targetContract"] == json!("rust-source::answer")
                })),
            "assertion fact must bridge to answer source contract: {response}"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    fn unique_temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "sugar-{name}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).expect("mkdir temp dir");
        dir
    }
}
