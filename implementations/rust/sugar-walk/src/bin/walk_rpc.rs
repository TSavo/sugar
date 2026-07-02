// SPDX-License-Identifier: Apache-2.0
//
// `sugar-walk-rpc`: minimal JSON-RPC 2.0 server over stdio. Each line
// of stdin is one JSON-RPC request; each response is one line of JSON
// on stdout. Methods:
//
//   walk.lift_pre        { src, fn_name }            → IrFormula
//   walk.lift_post       { src, fn_name }            → IrFormula
//   walk.contract        { src, fn_name, file? }     → FunctionContractMemento
//   walk.term            { src, fn_name, source? }   → rust algebra term JSON
//   walk.shadow_source   { src, callee, caller }     → { cid, slots, arrivals_total, bundle_cid }
//   walk.proof_ir        { src, callee, caller }     → { cid, bytes_b64, length }
//
// All requests must include `jsonrpc: "2.0"` and an `id`. Errors return
// JSON-RPC error objects.
//
// This makes the substrate's wire-format gap closed end-to-end: any
// program that speaks line-delimited JSON-RPC can drive sugar-walk
// and pull back proof.ir bytes ready for the substrate's lift / mint /
// linker pipeline.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};

use base64::Engine;
use libsugar::canonical::local_op_cid as canonical_local_op_cid;
use libsugar::panic_freedom;
use quote::ToTokens;
use serde_json::{json, Value};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_claim_envelope::{
    body_discharge_policy_from_object, body_discharge_policy_from_object_with_default,
    BodyDischargePolicyWarning, KIT_DECLARATION_RPC_METHOD,
};
use sugar_ir_types::{EvidenceMemento, IrFormula, IrTerm, SourceKind};
use sugar_lift_contracts::lift_file_with_docstring_evidence;
use sugar_walk::emit::{rust_function_term_json_for_file, shadow_proof_ir_cid, shadow_to_proof_ir};
use sugar_walk::source_oracle::{
    block_inner_source, block_to_ast_template, resolve_source_memento,
    source_memento_of_named_item_fn, source_memento_of_statement_span, source_memento_of_term_span,
    SourceMemento, SrcSpan,
};
use sugar_walk::{
    build_function_contract_with_file_and_post_override, build_shadow_source,
    collect_explicit_function_return_facts, lift_function_postcondition_with_return_facts,
    lift_function_postcondition_with_return_facts_and_pure_free_guards, lift_function_precondition,
    pure_free_guard_arg_is_stable, pure_free_guard_expr_effect_roots, CalleeContract,
    PureFreeGuardRule,
};
use syn::spanned::Spanned;
use tracing::{debug, info, trace, warn};

const COMPONENT_PLAN_RPC_METHOD: &str = "sugar.component.plan";

// Tier 2b native semantic oracle (spec 2026-05-30-callee-resolution-tiers §2.T2b).
// The RA LSP client now lives in the `sugar_walk::ra_oracle` library module so
// BOTH this per-mint binary AND the resident `sugar-linkerd` daemon import the
// same framing/quiescence/resolve logic with no copy-paste. This binary no longer
// COLD-SPAWNS rust-analyzer per mint; it asks the warm resident daemon via
// `resolveReceiverCrate` (see `resolve_method_calls_via_oracle`). The oracle is
// opt-in (SUGAR_RESOLVE_ORACLE=rust-analyzer) and refuses (leaves
// callee_crate = None) when the daemon is unreachable or cannot reach readiness,
// so the fast path and CI are unaffected. The RA LSP client itself lives in
// `sugar_walk::ra_oracle` and is imported by the daemon, not this binary.

// The daemon client lives alongside this binary (std-only, synchronous NDJSON).
#[path = "../ra_daemon_client.rs"]
mod ra_daemon_client;

const SORT_BOOL_CID: &str = "blake3-512:0ee13bf3fd6b7ecfbee72dfbfc18a7c0ea7f1663de6cca43cefb36f5b4c03665452646094a7c296e819e75d683c6ce4821f3d7db3c3c78ae97f2d4e3451d2074";
const SORT_BYTES_CID: &str = "blake3-512:7116ef6e62e6739b213a8394f975a53c771b89f08c36d27143827acfcfebc0e39e5b82c530be668c3cfd5ec6966ccaa42930b37fdb1f4ac25652a970be10fb6b";
const SORT_FLOAT_CID: &str = "blake3-512:b979e70c4d5e53d9bdf13d6f08330be3c5b0714b8c770d69bbd05946b86c36df5274be8145a2683cc29c278155c9c1ee65b6897913524eecb9e4c89c71862f57";
const SORT_INT_CID: &str = "blake3-512:30ffc51350121a7172f3e4064a33c45bbd345756979fccff6875cd2ab33e4964d098a99df80cfbdf1ec1a0738c5ac3476f0ff8f75589ea511d1acd82c74ecd58";
const SORT_STRING_CID: &str = "blake3-512:be8721d24849feb74c4721520bdba02d352a94f49253a627cd509127472aa1c47cbe99cb705cac4159b5365abcce0c9aaa4901fe67630827deb6be1f9daeea10";

static CONCEPT_OP_CIDS: OnceLock<std::sync::Mutex<BTreeMap<String, &'static str>>> =
    OnceLock::new();

fn log_body_discharge_policy_warnings(
    context: &str,
    contract: &str,
    warnings: &[BodyDischargePolicyWarning],
) {
    for warning in warnings {
        match warning {
            BodyDischargePolicyWarning::Disagreement {
                legacy_eligible,
                legacy_reason,
                policy_eligible,
                policy_reason,
            } => warn!(
                context = %context,
                contract = %contract,
                legacy_eligible = *legacy_eligible,
                legacy_reason = ?legacy_reason,
                policy_eligible = *policy_eligible,
                policy_reason = ?policy_reason,
                "body-discharge-disagreement: dischargePolicy/bodyDischarge* disagree; using legacy bodyDischarge*"
            ),
            BodyDischargePolicyWarning::Malformed { reason } => warn!(
                context = %context,
                contract = %contract,
                reason = %reason,
                "body-discharge-malformed: ignoring malformed dischargePolicy"
            ),
        }
    }
}

fn formal_actuals_for_binding(binding: &Value, actual_terms: Option<&[Value]>) -> Option<Value> {
    let formals = binding.get("formals")?.as_array()?;
    if formals.is_empty() {
        return Some(json!({}));
    }
    let actual_terms = actual_terms?;
    if actual_terms.len() != formals.len() {
        return None;
    }
    let mut out = serde_json::Map::new();
    for (formal, actual) in formals.iter().zip(actual_terms.iter()) {
        let name = formal.as_str()?.trim();
        if name.is_empty() {
            return None;
        }
        out.insert(name.to_string(), actual.clone());
    }
    Some(Value::Object(out))
}

fn callsite_with_formal_actuals(
    file: &str,
    line: usize,
    col: usize,
    panic_site: bool,
    formal_actuals: Option<Value>,
) -> Value {
    let mut callsite = json!({
        "file": file,
        "start_line": line,
        "start_col": col,
        "panicSite": panic_site,
    });
    if let Some(formal_actuals) = formal_actuals {
        callsite["formalActuals"] = formal_actuals;
    }
    callsite
}

fn main() -> io::Result<()> {
    // Logs go to stderr only; stdout is the JSON-RPC channel and must stay
    // byte-clean. Default level: warn. Set RUST_LOG to override:
    //   RUST_LOG=info  -> phase summaries
    //   RUST_LOG=debug -> per-callsite decisions, per-RPC method
    //   RUST_LOG=sugar_walk::ra_oracle=trace -> every RA LSP query
    // Note: ra_oracle now lives in the sugar_walk library, so its event
    // target is sugar_walk::ra_oracle.
    init_tracing();
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    info!("sugar-walk-rpc listening on stdio (JSON-RPC 2.0, line-delimited)");
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let response = handle_line(&line);
        let response_str = serde_json::to_string(&response).unwrap_or_else(|e| {
            json!({"jsonrpc": "2.0", "error": {"code": -32603, "message": e.to_string()}})
                .to_string()
        });
        writeln!(stdout, "{}", response_str)?;
        stdout.flush()?;
    }
    Ok(())
}

fn init_tracing() {
    let filter = tracing_subscriber::EnvFilter::builder()
        .with_default_directive(tracing_subscriber::filter::LevelFilter::WARN.into())
        .from_env_lossy();
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

fn handle_line(line: &str) -> Value {
    let req: Value = match serde_json::from_str(line) {
        Ok(v) => v,
        Err(e) => {
            return json!({
                "jsonrpc": "2.0",
                "error": { "code": -32700, "message": format!("parse error: {}", e) },
                "id": Value::Null,
            });
        }
    };
    let id = match req.get("id") {
        Some(id) => id.clone(),
        None => Value::Null,
    };
    let Some(method) = req.get("method").and_then(|m| m.as_str()) else {
        return json!({
            "jsonrpc": "2.0",
            "error": { "code": -32600, "message": "invalid request: missing string `method`" },
            "id": id,
        });
    };
    let params = match req.get("params") {
        Some(params) => params.clone(),
        None => json!({}),
    };

    let result = match method {
        // Bind-IR lift surface (PEP 1.7.0 `kind = "lift"` over the legacy-retained
        // `initialize`/`lift`/`shutdown` JSON-RPC shape per
        // `2026-04-30-lift-plugin-protocol.md`). cmd_bind dispatches Verb 1 here.
        "initialize" => Ok(initialize_result()),
        "lift" => bind_lift(&params),
        "shutdown" => Ok(Value::Null),
        KIT_DECLARATION_RPC_METHOD => Ok(kit_declaration_result()),
        COMPONENT_PLAN_RPC_METHOD => Ok(component_plan_result(&params)),
        // Recognizer foundation (#81, #82) per protocol §4.2.5. The lift
        // binary handles this too because it already owns the syn AST
        // machinery that recognize needs — same kit, same language.
        "sugar.plugin.recognize" => recognize(&params),
        "sugar.plugin.resolve_source_memento" => resolve_source_memento_rpc(&params),
        // Materialize (#1359, rust mirror of the python bind_rpc materializer).
        // Finds `#[sugar::boundary(library, call)]` stubs in the consumer
        // source, asks the SOURCE ORACLE to resolve each bound vendor function's
        // REAL body from on-disk source (CID-verified against the
        // SourceMemento the vendor sugar-lift minted), and rewrites the stub
        // body in place. On a CID-misalign (source drift) the oracle REFUSES and
        // the site is reported `outcome:"refused"` with NO write. Same kit, same
        // syn AST machinery, same source-oracle family as lift/recognize.
        // Implication lifter (#97). For every call expression in every
        // function body in the supplied source files, emit a kind:bridge
        // memento that links the call site (sourceSymbol = callee ident)
        // to a contract resolved by ctor-name index over the supplied
        // contract_bindings. Same kit, same AST walker; new memento kind.
        // This is the structural callsite obligation pass: the verb that
        // says "this call expression exists, an obligation forms here,
        // here is the contract it pins to."
        "sugar.plugin.lift_implications" => lift_implications(&params),
        // Walk-internal RPC (substrate-private; not part of any plugin protocol).
        "walk.lift_pre" => lift_pre(&params),
        "walk.lift_post" => lift_post(&params),
        "walk.contract" => contract(&params),
        "walk.term" => term(&params),
        "walk.shadow_source" => shadow_source(&params),
        "walk.proof_ir" => proof_ir(&params),
        _ => Err(format!("unknown method: {}", method)),
    };

    match result {
        Ok(value) => json!({
            "jsonrpc": "2.0",
            "result": value,
            "id": id,
        }),
        Err(message) => json!({
            "jsonrpc": "2.0",
            "error": { "code": -32602, "message": message },
            "id": id,
        }),
    }
}

fn resolve_source_memento_rpc(params: &Value) -> Result<Value, String> {
    let workspace_root = params
        .get("workspace_root")
        .and_then(Value::as_str)
        .ok_or("missing `workspace_root`")?;
    let memento_value = params
        .get("sourceMemento")
        .or_else(|| params.get("source_memento"))
        .ok_or("missing `sourceMemento`")?;
    let memento = source_memento_from_json_value(memento_value)?;
    let resolved = resolve_source_memento(Path::new(workspace_root), &memento)
        .map_err(|refusal| refusal.reason)?;
    Ok(json!({
        "file": memento.file,
        "span": {
            "start_line": memento.span.start_line,
            "start_col": memento.span.start_col,
            "end_line": memento.span.end_line,
            "end_col": memento.span.end_col,
        },
        "source": resolved.fragment.body_text.trim(),
        "bodyText": resolved.fragment.body_text.trim(),
        "sourceLines": source_lines_for_memento(Path::new(workspace_root), &memento),
    }))
}

fn source_lines_for_memento(workspace_root: &Path, memento: &SourceMemento) -> Value {
    let Ok(source) = std::fs::read_to_string(workspace_root.join(&memento.file)) else {
        return Value::Array(Vec::new());
    };
    let lines = source.lines().collect::<Vec<_>>();
    let Some(start) = memento.span.start_line.checked_sub(1) else {
        return Value::Array(Vec::new());
    };
    let end = memento.span.end_line.max(memento.span.start_line);
    let Some(selected) = lines.get(start..end) else {
        return Value::Array(Vec::new());
    };
    Value::Array(
        selected
            .iter()
            .enumerate()
            .map(|(offset, source)| {
                json!({
                    "line": start + offset + 1,
                    "source": source.trim_end(),
                })
            })
            .collect(),
    )
}

fn json_field_or_null(value: &Value, key: &str) -> Value {
    match value.get(key) {
        Some(field) => field.clone(),
        None => Value::Null,
    }
}

fn json_any_field_or_null(value: &Value, keys: &[&str]) -> Value {
    for key in keys {
        if let Some(field) = value.get(*key) {
            return field.clone();
        }
    }
    Value::Null
}

fn relative_display_path(path: &Path, root: &Path) -> String {
    let display_path = match path.strip_prefix(root) {
        Ok(rel) => rel,
        Err(_) => path,
    };
    display_path.display().to_string().replace('\\', "/")
}

fn path_has_rs_extension(path: &Path) -> bool {
    path.extension().is_some_and(|x| x == "rs")
}

fn source_memento_from_json_value(value: &Value) -> Result<SourceMemento, String> {
    let file = value
        .get("file")
        .and_then(Value::as_str)
        .ok_or("invalid `sourceMemento` shape: missing `file`")?
        .to_string();
    let span = value
        .get("span")
        .ok_or("invalid `sourceMemento` shape: missing `span`")?;
    let param_names = match value
        .get("paramNames")
        .or_else(|| value.get("param_names"))
        .and_then(Value::as_array)
    {
        Some(values) => values
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect(),
        None => Vec::new(),
    };
    let function_name = match value
        .get("sourceFunctionName")
        .or_else(|| value.get("source_function_name"))
        .and_then(Value::as_str)
    {
        Some(name) => name.to_string(),
        None => String::new(),
    };
    let source_cid = value
        .get("source_cid")
        .or_else(|| value.get("sourceCid"))
        .and_then(Value::as_str)
        .filter(|cid| !cid.is_empty())
        .ok_or("invalid `sourceMemento` shape: missing non-empty `source_cid`")?
        .to_string();
    let template_cid = value
        .get("template_cid")
        .or_else(|| value.get("templateCid"))
        .and_then(Value::as_str)
        .filter(|cid| !cid.is_empty())
        .ok_or("invalid `sourceMemento` shape: missing non-empty `template_cid`")?
        .to_string();
    Ok(SourceMemento {
        file,
        function_name,
        span: SrcSpan {
            start_line: span
                .get("start_line")
                .and_then(Value::as_u64)
                .ok_or("invalid `sourceMemento` shape: missing `span.start_line`")?
                as usize,
            start_col: span
                .get("start_col")
                .and_then(Value::as_u64)
                .ok_or("invalid `sourceMemento` shape: missing `span.start_col`")?
                as usize,
            end_line: span
                .get("end_line")
                .and_then(Value::as_u64)
                .ok_or("invalid `sourceMemento` shape: missing `span.end_line`")?
                as usize,
            end_col: span
                .get("end_col")
                .and_then(Value::as_u64)
                .ok_or("invalid `sourceMemento` shape: missing `span.end_col`")?
                as usize,
        },
        param_names,
        source_cid,
        template_cid,
    })
}

/// Recognizer foundation (#81, #82) per protocol §4.2.5.
///
/// Walk user source files, compute their function bodies' identifier-
/// canonical AST templates with the same `block_to_ast_template` the
/// sugar lifter uses, and match by `template_cid` against the request's
/// kit-resolved sugar binding templates. An exact CID match means the
/// user's function body IS the shim's sugar body (modulo whitespace +
/// alpha-equivalence on params) — tier `exact`. Tiers `structural`,
/// `probable`, `refused` are reserved for follow-up tier-2/3 work.
///
/// The kit owns the AST machinery; the substrate sees only the tag set.
/// This is the language-blind invariant: the substrate sends project source
/// paths and collects tags opaquely; only the kit reads Rust package proofs
/// and syn shapes.
fn recognize(params: &Value) -> Result<Value, String> {
    let project_root = params
        .get("project_root")
        .and_then(|v| v.as_str())
        .ok_or("missing `project_root`")?;
    let project_root = std::path::PathBuf::from(project_root);

    let source_paths: Vec<String> = params
        .get("source_paths")
        .and_then(|v| v.as_array())
        .ok_or("missing `source_paths` array")?
        .iter()
        .filter_map(|v| v.as_str().map(|s| s.to_string()))
        .collect();

    // Index bindings by template_cid for O(1) lookup. The kit reads the
    // template_cid the lifter emitted; `binding_templates` remains accepted for
    // older direct kit tests, but the CLI does not send it. Real template
    // authority comes from proof catalogs the Rust kit resolves itself.
    let mut bindings_by_cid: HashMap<String, RecognizeBindingTemplate> = HashMap::new();
    if let Some(binding_templates) = params.get("binding_templates").and_then(|v| v.as_array()) {
        for binding in binding_templates {
            if let Some(cid) = binding.get("template_cid").and_then(|v| v.as_str()) {
                bindings_by_cid.insert(
                    cid.to_string(),
                    RecognizeBindingTemplate {
                        body: binding.clone(),
                        target_proof_cid: binding
                            .get("target_proof_cid")
                            .and_then(Value::as_str)
                            .map(str::to_string),
                    },
                );
            }
        }
    }
    for binding in load_binding_templates_for_project(&project_root)? {
        if let Some(cid) = binding.body.get("template_cid").and_then(|v| v.as_str()) {
            bindings_by_cid.insert(cid.to_string(), binding);
        }
    }

    let mut tags: Vec<Value> = Vec::new();

    for rel_path in &source_paths {
        let full_path = project_root.join(rel_path);
        let src = match std::fs::read_to_string(&full_path) {
            Ok(s) => s,
            Err(_) => continue, // missing files are not errors at the recognize layer
        };
        let file = match syn::parse_file(&src) {
            Ok(f) => f,
            Err(_) => continue, // unparseable files cannot host AST recognition
        };

        recognize_walk_items(&file.items, rel_path, &bindings_by_cid, &mut tags);
    }

    Ok(json!({ "tags": tags }))
}

/// Recursively visit items + nested modules, collecting recognize tags.
fn recognize_walk_items(
    items: &[syn::Item],
    rel_path: &str,
    bindings_by_cid: &HashMap<String, RecognizeBindingTemplate>,
    tags: &mut Vec<Value>,
) {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                if let Some(tag) = recognize_match_item_fn(item_fn, rel_path, bindings_by_cid) {
                    tags.push(tag);
                }
            }
            syn::Item::Mod(item_mod) => {
                if let Some((_, ref nested)) = item_mod.content {
                    recognize_walk_items(nested, rel_path, bindings_by_cid, tags);
                }
            }
            // sugar-audit: not-mine(recognize tags are minted only from functions inside inline modules)
            _ => {}
        }
    }
}

/// Compute the candidate's identifier-canonical AST template and look it
/// up in `bindings_by_cid`. Returns a tag JSON if matched at tier `exact`.
fn recognize_match_item_fn(
    item_fn: &syn::ItemFn,
    rel_path: &str,
    bindings_by_cid: &HashMap<String, RecognizeBindingTemplate>,
) -> Option<Value> {
    let param_names: Vec<String> = item_fn
        .sig
        .inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Typed(pat_ty) => match &*pat_ty.pat {
                syn::Pat::Ident(pid) => Some(pid.ident.to_string()),
                _ => None,
            },
            syn::FnArg::Receiver(_) => None,
        })
        .collect();

    let candidate_template = block_to_ast_template(&item_fn.block, &param_names);
    let candidate_cid = blake3_512_of(candidate_template.to_string().as_bytes());

    let binding = bindings_by_cid.get(&candidate_cid)?;
    let body = &binding.body;

    let start = item_fn.sig.fn_token.span.start();
    let end = item_fn.block.brace_token.span.close().end();

    let param_bindings: Vec<Value> = param_names
        .iter()
        .enumerate()
        .map(|(i, n)| {
            json!({
                "index": i + 1,
                "source_text": n,
            })
        })
        .collect();

    Some(json!({
        "file": rel_path,
        "span": {
            "start_line": start.line,
            "start_col": start.column,
            "end_line": end.line,
            "end_col": end.column,
        },
        "function_name": item_fn.sig.ident.to_string(),
        "op_cid": json_field_or_null(body, "op_cid"),
        "library_tag": json_field_or_null(body, "library_tag"),
        "template_cid": candidate_cid,
        "contract_cid": json_field_or_null(body, "contract_cid"),
        "target_proof_cid": match &binding.target_proof_cid {
            Some(cid) => Value::String(cid.clone()),
            None => json_field_or_null(body, "target_proof_cid"),
        },
        "match_tier": "exact",
        "param_bindings": param_bindings,
    }))
}

#[derive(Debug, Clone)]
struct RecognizeBindingTemplate {
    body: Value,
    target_proof_cid: Option<String>,
}

fn load_binding_templates_for_project(
    project_root: &Path,
) -> Result<Vec<RecognizeBindingTemplate>, String> {
    let proof_paths = resolve_recognizer_proof_paths(project_root)?;
    let mut bindings = Vec::new();
    for path in proof_paths {
        bindings.extend(binding_templates_from_proof(&path)?);
    }
    Ok(bindings)
}

fn binding_templates_from_proof(path: &Path) -> Result<Vec<RecognizeBindingTemplate>, String> {
    let bytes = std::fs::read(path)
        .map_err(|error| format!("read Rust recognizer proof {}: {error}", path.display()))?;
    let proof_cid = blake3_512_of(&bytes);
    let graph = sugar_proof_envelope::ProofGraph::read(&bytes)
        .map_err(|error| format!("decode Rust recognizer proof {}: {error}", path.display()))?;

    let mut bindings = Vec::new();
    for view in graph.members_view() {
        let Ok(parsed) = serde_json::from_slice::<Value>(view.bytes()) else {
            continue;
        };
        let body = match parsed.get("body") {
            Some(body) => body,
            None => &parsed,
        };
        if let Some(binding) = binding_template_from_sugar_entry(body, Some(proof_cid.clone())) {
            bindings.push(binding);
        }
    }
    Ok(bindings)
}

fn rust_vendor_contract_bindings_from_proofs(project_root: &Path) -> Result<Vec<Value>, String> {
    let proof_paths = resolve_recognizer_proof_paths(project_root)?;
    let mut bindings = Vec::new();
    for path in proof_paths {
        bindings.extend(rust_vendor_contract_bindings_from_proof(&path)?);
    }
    Ok(bindings)
}

fn rust_vendor_contract_bindings_from_proof(path: &Path) -> Result<Vec<Value>, String> {
    let bytes = std::fs::read(path)
        .map_err(|error| format!("read Rust vendor proof {}: {error}", path.display()))?;
    let proof_cid = blake3_512_of(&bytes);
    let graph = sugar_proof_envelope::ProofGraph::read(&bytes)
        .map_err(|error| format!("decode Rust vendor proof {}: {error}", path.display()))?;

    let mut parsed_members: Vec<RustVendorProofMember> = Vec::new();
    for view in graph.members_view() {
        parsed_members.push(RustVendorProofMember::from_view(view));
    }

    // First pass: collect bridge members that map a source symbol to a target contract CID.
    // A bridge qualifies when it has no callsite (pure symbol-level bridge), points from
    // sourceLayer="source" to targetLayer="kit", and carries non-empty sourceSymbol /
    // targetContractCid values.  Member::from_value is STRICT — any Err (missing required
    // field, bad CID format, unknown kind) is treated as "not a qualifying bridge" and the
    // member is skipped, matching the old stringly None path exactly.
    let mut bridge_source_by_target: HashMap<String, String> = HashMap::new();
    for member in &parsed_members {
        let bridge = match sugar_proof_envelope::Member::from_value(&member.json) {
            Ok(sugar_proof_envelope::Member::Bridge(b)) => b,
            _ => continue,
        };
        if bridge.callsite.is_some() {
            continue;
        }
        if bridge.source_layer.as_deref() != Some("source") {
            continue;
        }
        if bridge.target_layer.as_deref() != Some("kit") {
            continue;
        }
        // sourceSymbol is a required String in BridgeMember; preserve the old empty filter.
        if bridge.source_symbol.trim().is_empty() {
            continue;
        }
        // targetContractCid is a required MementoCid; the blake3-512: prefix check already
        // rejected empty/malformed CIDs during from_value, but keep an explicit guard to
        // match the old filter(|s| !s.trim().is_empty()) exactly.
        let target_cid = bridge.target_contract_cid.as_str();
        if target_cid.trim().is_empty() {
            continue;
        }
        bridge_source_by_target
            .entry(target_cid.to_string())
            .or_insert_with(|| bridge.source_symbol.clone());
    }

    // Second pass: collect contract members that have a matching bridge.
    //
    // Rust-minted graph-backed contracts carry `name` plus `bodyCid`; older
    // importer code promised a `name`/`contractName` fallback but accidentally
    // asked the typed member parser to require both. Keep the importer strict
    // about kind/body-backed shape, but accept the Rust minter's canonical
    // `name` spelling so dependency proofs can be indexed.
    let mut bindings = Vec::new();
    for member in parsed_members {
        let member_cid = member.cid.clone();
        let Some(bridge_source_symbol) = bridge_source_by_target.get(&member_cid).cloned() else {
            continue;
        };
        let contract = match rust_vendor_contract_binding_member(&member) {
            Ok(Some(contract)) => contract,
            Ok(None) => continue,
            Err(error) => {
                return Err(format!(
                    "rust vendor proof {proof_cid} contract member {member_cid}: {error}"
                ));
            }
        };
        let RustVendorContractBindingMember {
            name,
            formals,
            formal_sorts,
            has_pre,
            has_post,
            library,
            body_discharge_eligible,
            body_discharge_refusal_reason,
            discharge_policy,
        } = contract;
        let formals_value = Value::Array(formals.into_iter().map(Value::String).collect());
        if !has_pre && !has_post {
            continue;
        }

        let body_discharge_eligible = match body_discharge_eligible {
            Some(value) => Value::Bool(value),
            None => Value::Null,
        };
        let body_discharge_refusal_reason = match body_discharge_refusal_reason {
            Some(value) => Value::String(value),
            None => Value::Null,
        };
        let discharge_policy = match discharge_policy {
            Some(value) => value,
            None => Value::Null,
        };
        let library = match library {
            Some(library) => Value::String(library),
            None => Value::Null,
        };
        let body_policy_input = json!({
            "bodyDischargeEligible": body_discharge_eligible,
            "bodyDischargeRefusalReason": body_discharge_refusal_reason,
            "dischargePolicy": discharge_policy,
        });
        let body_policy = body_discharge_policy_from_object(&body_policy_input);
        log_body_discharge_policy_warnings(
            "walk-rust-vendor-proof-contract-binding",
            &name,
            &body_policy.warnings,
        );
        let body_bearing = (has_pre || has_post) && body_policy.body_discharge_eligible;

        let mut binding = json!({
            "name": name,
            "contract_cid": member_cid,
            "body_bearing": body_bearing,
            "has_pre": has_pre,
            "has_post": has_post,
            "bodyDischargeEligible": body_policy.body_discharge_eligible,
            "bodyDischargeRefusalReason": body_policy.body_discharge_refusal_reason,
            "bridgeSourceSymbol": bridge_source_symbol,
            "target_proof_cid": proof_cid,
            "formals": formals_value,
            "library": library,
        });
        if let Some(formal_sorts) = formal_sorts {
            binding["formalSorts"] = Value::Array(formal_sorts);
        }
        bindings.push(binding);
    }

    Ok(bindings)
}

struct RustVendorContractBindingMember {
    name: String,
    formals: Vec<String>,
    formal_sorts: Option<Vec<Value>>,
    has_pre: bool,
    has_post: bool,
    library: Option<String>,
    body_discharge_eligible: Option<bool>,
    body_discharge_refusal_reason: Option<String>,
    discharge_policy: Option<Value>,
}

struct RustVendorProofMember {
    cid: String,
    kind: Option<String>,
    body_cid: Option<String>,
    json: Value,
}

impl RustVendorProofMember {
    fn from_view(view: sugar_proof_envelope::MemberView<'_>) -> Self {
        Self {
            cid: view.cid().as_str().to_string(),
            kind: view.kind(),
            body_cid: view.body_cid(),
            json: view.json(),
        }
    }

    fn body_cid(&self) -> Option<&str> {
        self.body_cid
            .as_deref()
            .or_else(|| self.field("bodyCid").and_then(Value::as_str))
    }

    fn field(&self, field: &str) -> Option<&Value> {
        sugar_proof_envelope::member_field(&self.json, field)
    }
}

fn rust_vendor_contract_binding_member(
    member: &RustVendorProofMember,
) -> Result<Option<RustVendorContractBindingMember>, String> {
    if member.kind.as_deref() != Some("contract") {
        return Ok(None);
    }
    // Graph-backed Rust contracts prove the body map exists by carrying bodyCid.
    if member.body_cid().is_none() {
        return Ok(None);
    }
    let Some(name) = member
        .field("name")
        .or_else(|| member.field("contractName"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(str::to_string)
    else {
        return Ok(None);
    };
    let Some(formals_value) = member.field("formals") else {
        return Ok(None);
    };
    let formals =
        serde_json::from_value::<Vec<String>>(formals_value.clone()).map_err(|error| {
            format!("contract member `{name}` has invalid `formals` array: {error}")
        })?;
    let formal_sorts = match member.field("formalSorts") {
        Some(value) => Some(serde_json::from_value::<Vec<Value>>(value.clone()).map_err(
            |error| format!("contract member `{name}` has invalid `formalSorts` array: {error}"),
        )?),
        None => None,
    };
    let has_pre = member.field("pre").is_some_and(has_nontrivial_pre_json)
        || member
            .field("preHash")
            .and_then(Value::as_str)
            .is_some_and(|hash| !hash.trim().is_empty());
    let has_post = member.field("post").is_some()
        || member
            .field("postHash")
            .and_then(Value::as_str)
            .is_some_and(|hash| !hash.trim().is_empty());
    Ok(Some(RustVendorContractBindingMember {
        name,
        formals,
        formal_sorts,
        has_pre,
        has_post,
        library: member
            .field("library")
            .and_then(Value::as_str)
            .map(str::to_string),
        body_discharge_eligible: member
            .field("bodyDischargeEligible")
            .and_then(Value::as_bool),
        body_discharge_refusal_reason: member
            .field("bodyDischargeRefusalReason")
            .and_then(Value::as_str)
            .map(str::to_string),
        discharge_policy: member.field("dischargePolicy").cloned(),
    }))
}

fn binding_template_from_sugar_entry(
    entry: &Value,
    target_proof_cid: Option<String>,
) -> Option<RecognizeBindingTemplate> {
    if entry.get("kind").and_then(Value::as_str) != Some("library-sugar-binding-entry") {
        return None;
    }
    let op_cid = entry
        .get("op_cid")
        .or_else(|| entry.get("opCid"))
        .and_then(Value::as_str)?;
    let library_tag = json_any_field_or_null(entry, &["target_library_tag", "library_tag"]);
    let body_source = entry.get("body_source")?;
    let template_cid = body_source
        .get("template_cid")
        .and_then(Value::as_str)
        .map(str::to_string)?;
    let param_names = body_source
        .get("param_names")
        .or_else(|| entry.get("param_names"))
        .cloned()
        .unwrap_or_else(|| Value::Array(Vec::new()));

    let mut body = json!({
        "op_cid": op_cid,
        "library_tag": library_tag,
        "template_cid": template_cid,
        "param_names": param_names,
        "contract_cid": json_field_or_null(entry, "contract_cid"),
    });
    if let Some(cid) = &target_proof_cid {
        body["target_proof_cid"] = Value::String(cid.clone());
    }

    Some(RecognizeBindingTemplate {
        body,
        target_proof_cid,
    })
}

fn resolve_recognizer_proof_paths(project_root: &Path) -> Result<Vec<PathBuf>, String> {
    let mut proof_paths = BTreeSet::new();
    collect_recognizer_proof_files(
        &project_root.join(".sugar").join("imports"),
        &mut proof_paths,
    );
    for path in resolve_cargo_dependency_proof_paths(project_root)? {
        proof_paths.insert(path);
    }
    Ok(proof_paths.into_iter().collect())
}

fn resolve_cargo_dependency_proof_paths(project_root: &Path) -> Result<Vec<PathBuf>, String> {
    let manifest_path = project_root.join("Cargo.toml");
    if !manifest_path.is_file() {
        return Ok(Vec::new());
    }

    let output = std::process::Command::new("cargo")
        .arg("metadata")
        .arg("--format-version")
        .arg("1")
        .arg("--manifest-path")
        .arg(&manifest_path)
        .current_dir(project_root)
        .output()
        .map_err(|error| format!("spawn cargo metadata: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "cargo metadata failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let metadata: Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("parse cargo metadata JSON: {error}"))?;

    let workspace_members = match metadata.get("workspace_members").and_then(Value::as_array) {
        Some(members) => members
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect::<BTreeSet<_>>(),
        None => return Err("cargo metadata missing `workspace_members` array".to_string()),
    };
    let reachable = match metadata
        .get("resolve")
        .and_then(|resolve| resolve.get("nodes"))
        .and_then(Value::as_array)
    {
        Some(nodes) => nodes
            .iter()
            .filter_map(|node| node.get("id").and_then(Value::as_str))
            .map(str::to_string)
            .collect::<BTreeSet<_>>(),
        None => return Err("cargo metadata missing `resolve.nodes` array".to_string()),
    };

    let mut proof_paths = BTreeSet::new();
    let Some(packages) = metadata.get("packages").and_then(Value::as_array) else {
        return Ok(Vec::new());
    };
    for package in packages {
        let Some(package_id) = package.get("id").and_then(Value::as_str) else {
            continue;
        };
        if workspace_members.contains(package_id) {
            continue;
        }
        if !reachable.is_empty() && !reachable.contains(package_id) {
            continue;
        }
        let Some(manifest_path) = package.get("manifest_path").and_then(Value::as_str) else {
            continue;
        };
        let Some(package_dir) = Path::new(manifest_path).parent() else {
            continue;
        };
        collect_recognizer_proof_files(package_dir, &mut proof_paths);
    }

    Ok(proof_paths.into_iter().collect())
}

fn collect_recognizer_proof_files(root: &Path, proof_paths: &mut BTreeSet<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let file_name = match path.file_name().and_then(|s| s.to_str()) {
            Some(file_name) => file_name,
            None => "",
        };
        if path.is_dir() {
            match file_name {
                ".git" | "target" | "node_modules" | "vendor" => continue,
                _ => collect_recognizer_proof_files(&path, proof_paths),
            }
            continue;
        }
        if path.extension().and_then(|s| s.to_str()) == Some("proof") {
            proof_paths.insert(path);
        }
    }
}

// ---------------------------------------------------------------------------
// Implication lifter (#97).
//
// The substrate has three lift surfaces:
//
//   1. The sugar lifter (rust-bind, above) walks #[sugar::sugar] /
//      #[sugar::boundary] annotations and emits bind-IR entries plus
//      identity-ctor sibling contracts at the sugar definitions. That
//      surface NAMES the vendor contract.
//
//   2. The test lifter (sugar-lift-rust-tests) walks #[test] / panic /
//      early-return shapes and emits one contract per asserted callsite,
//      named "<callee>@<file>:<line>:<col>". That surface DERIVES contracts
//      from observed asserts and pins them to the production-code call site
//      the assertion witnessed.
//
//   3. THIS LIFTER walks production code (no test-runner involvement, no
//      sugar annotation requirement). For every Expr::Call and
//      Expr::MethodCall in every function body, it emits a kind:bridge
//      memento that pins the call site by sourceSymbol = callee identifier
//      to a contract supplied via `contract_bindings`. The implication
//      forms STRUCTURALLY: the AST already contains the call expression;
//      the lifter just makes it explicit as a substrate-named callsite
//      anchor that enumerate_callsites can find via pool.bridges_by_symbol.
//
// Without this lifter, the verifier's enumerate_callsites stage walks the
// loaded contracts looking for ctor refs whose names hit pool.bridges_by_symbol,
// finds zero hits when the project has no vendor-shim recognize pass, and
// reports "no callsites". The bind-lift surface and the test surface emit
// contracts; this surface emits the bridges that turn those contracts into
// enumerable callsites.

#[derive(Debug, Clone)]
struct CallSite {
    /// The bare callee leaf: last path segment for `Expr::Call`, method ident
    /// for `Expr::MethodCall`.
    callee: String,
    /// The target contract lookup key for this callee. Usually identical to
    /// `callee`, but carries generic arguments for monomorphized calls
    /// (`foo::<i64>`) so different instantiations cannot collapse into one
    /// target binding. This never becomes the bridge `sourceSymbol`; the source
    /// symbol must stay aligned with the ctor name lifted from the caller body.
    contract_callee: String,
    /// The crate the callee resolves to (Tier-1 qualification). `Some("std")`,
    /// `Some("libsugar")`, etc. for a path or use-resolved free function;
    /// `None` when it could not be resolved syntactically (a method call whose
    /// receiver type is unknown, or a bare call with no matching `use`). A
    /// `None` here is treated as the current crate by the matcher, which keeps
    /// intra-crate bare calls resolving as before; a `Some(other)` is what
    /// distinguishes a cross-crate callee from a same-named local one.
    callee_crate: Option<String>,
    /// `true` for an `Expr::MethodCall` (`x.method()`), `false` for an
    /// `Expr::Call` (free function / associated function). Only method calls
    /// whose `callee_crate` stayed `None` after Tier 2a are eligible for the
    /// Tier 2b semantic-oracle fallback; a `None` on a free call is a glob
    /// import and must keep its current-crate fallback, never the oracle.
    is_method: bool,
    /// The disambiguated callee leaf for a panic-relevant call, when the Tier-2b
    /// oracle resolved the receiver TYPE (not just the crate). For `x.unwrap()`
    /// on an `Option`, this is `Some("option_unwrap")`: the rust-std shim's
    /// disambiguated partial whose REAL precondition (`opt.is_some()`) the call
    /// site must discharge to be proven panic-free. `None` when the receiver type
    /// was not resolved or the `(type, leaf)` pair is not a known panic partial;
    /// the matcher then keys on the bare `callee` exactly as before (additive,
    /// never regressing the total-wrapper bridges). The bridge's `sourceSymbol`
    /// STAYS the bare `callee` (that is the ctor name in the lifted caller body);
    /// only the TARGET binding selected changes to the disambiguated partial.
    disambiguated_callee: Option<String>,
    /// Optional target crate for `disambiguated_callee`. Panic partials usually
    /// live in the resolved receiver crate (`std`), but serde_json per-type
    /// totality contracts live in the crate that owns the blessed type
    /// (`libsugar`, a consumer crate, etc.), not in serde_json itself.
    disambiguated_crate: Option<String>,
    /// Some call syntaxes are real callsites, but not yet bridgeable to a
    /// stable contract key. Keep them in the census as explicit lift gaps
    /// rather than silently dropping them or guessing a bridge target.
    unsupported_reason: Option<&'static str>,
    /// Concrete callsite actuals in target-signature order as resolved by this
    /// Rust kit: free calls carry call arguments, methods carry receiver first
    /// followed by explicit arguments. The verifier treats the resulting
    /// `formalActuals` map as opaque data and never infers Rust call syntax.
    actual_terms: Option<Vec<Value>>,
    /// Producer contract name for the enclosing Rust function or impl method,
    /// using the same naming convention as `function_contract_lift`.
    caller_contract_name: Option<String>,
    file: String,
    line: usize,
    col: usize,
}

#[derive(Debug, Clone)]
struct TrackedChannelConduit {
    tx: String,
    rx: String,
    producer: Option<String>,
    ambiguous: bool,
    escaped: bool,
    recv_sites: Vec<(usize, usize)>,
}

#[derive(Debug, Clone)]
struct TrackedMutexConduit {
    mutex: String,
    producer: Option<String>,
    escaped: bool,
    lock_sites: BTreeSet<(usize, usize)>,
    allowed_lock_sites: BTreeSet<(usize, usize)>,
}

fn channel_recv_source_symbol(rx: &str) -> String {
    format!("channel:recv:{rx}")
}

fn mutex_guard_source_symbol(mutex: &str) -> String {
    format!("mutex:guard:{mutex}")
}

fn collect_tokio_mpsc_channel_conduit_callsites(file: &syn::File, rel_path: &str) -> Vec<CallSite> {
    use syn::visit::Visit;

    struct V<'a> {
        rel_path: &'a str,
        channels: Vec<TrackedChannelConduit>,
    }

    impl<'a> V<'a> {
        fn channel_by_tx_mut(&mut self, tx: &str) -> Option<&mut TrackedChannelConduit> {
            self.channels.iter_mut().find(|channel| channel.tx == tx)
        }

        fn channel_by_rx_mut(&mut self, rx: &str) -> Option<&mut TrackedChannelConduit> {
            self.channels.iter_mut().find(|channel| channel.rx == rx)
        }

        fn endpoint_names(&self) -> BTreeSet<String> {
            self.channels
                .iter()
                .flat_map(|channel| [channel.tx.clone(), channel.rx.clone()])
                .collect()
        }

        fn mark_escaped_if_endpoint_is_used_opaquely(&mut self, expr: &syn::Expr) {
            let endpoints = self.endpoint_names();
            if endpoints.is_empty() {
                return;
            }
            for name in expr_ident_roots(expr) {
                if endpoints.contains(&name) {
                    for channel in &mut self.channels {
                        if channel.tx == name || channel.rx == name {
                            channel.escaped = true;
                        }
                    }
                }
            }
        }

        fn into_callsites(self) -> Vec<CallSite> {
            let mut out = Vec::new();
            for channel in self.channels {
                if channel.escaped || channel.ambiguous {
                    continue;
                }
                let Some(producer) = channel.producer else {
                    continue;
                };
                for (line, col) in channel.recv_sites {
                    out.push(CallSite {
                        callee: channel_recv_source_symbol(&channel.rx),
                        contract_callee: producer.clone(),
                        callee_crate: None,
                        is_method: false,
                        disambiguated_callee: None,
                        disambiguated_crate: None,
                        unsupported_reason: None,
                        actual_terms: None,
                        caller_contract_name: None,
                        file: self.rel_path.to_string(),
                        line,
                        col,
                    });
                }
            }
            out
        }
    }

    impl<'ast, 'a> Visit<'ast> for V<'a> {
        fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
            let saved = std::mem::take(&mut self.channels);
            syn::visit::visit_item_fn(self, node);
            let current = std::mem::take(&mut self.channels);
            self.channels = saved;
            self.channels.extend(current);
        }

        fn visit_local(&mut self, node: &'ast syn::Local) {
            if let Some((tx, rx)) = tokio_mpsc_channel_binding(node) {
                self.channels.push(TrackedChannelConduit {
                    tx,
                    rx,
                    producer: None,
                    ambiguous: false,
                    escaped: false,
                    recv_sites: Vec::new(),
                });
                syn::visit::visit_local(self, node);
                return;
            }

            let endpoints = self.endpoint_names();
            for bound in pat_bound_idents(&node.pat) {
                if endpoints.contains(&bound) {
                    for channel in &mut self.channels {
                        if channel.tx == bound || channel.rx == bound {
                            channel.escaped = true;
                        }
                    }
                }
            }
            if let Some(init) = &node.init {
                let uses_endpoint = expr_ident_roots(&init.expr)
                    .iter()
                    .any(|name| endpoints.contains(name));
                let allowed_recv = self
                    .channels
                    .iter()
                    .any(|channel| expr_is_channel_recv_chain(&init.expr, &channel.rx));
                if uses_endpoint && !allowed_recv {
                    self.mark_escaped_if_endpoint_is_used_opaquely(&init.expr);
                }
            }
            syn::visit::visit_local(self, node);
        }

        fn visit_expr_call(&mut self, node: &'ast syn::ExprCall) {
            for arg in &node.args {
                let allowed_recv = self
                    .channels
                    .iter()
                    .any(|channel| expr_is_channel_recv_chain(arg, &channel.rx));
                if !allowed_recv {
                    self.mark_escaped_if_endpoint_is_used_opaquely(arg);
                }
            }
            syn::visit::visit_expr_call(self, node);
        }

        fn visit_expr_assign(&mut self, node: &'ast syn::ExprAssign) {
            let roots = expr_assignment_roots(&node.left);
            for channel in &mut self.channels {
                if roots.contains(&channel.tx) || roots.contains(&channel.rx) {
                    channel.escaped = true;
                }
            }
            syn::visit::visit_expr_assign(self, node);
        }

        fn visit_expr_binary(&mut self, node: &'ast syn::ExprBinary) {
            if binop_is_assignment(&node.op) {
                let roots = expr_assignment_roots(&node.left);
                for channel in &mut self.channels {
                    if roots.contains(&channel.tx) || roots.contains(&channel.rx) {
                        channel.escaped = true;
                    }
                }
            }
            syn::visit::visit_expr_binary(self, node);
        }

        fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
            if let Some(tx) = expr_bare_ident_name(&node.receiver) {
                if let Some(channel) = self.channel_by_tx_mut(&tx) {
                    if node.method == "send" && node.args.len() == 1 {
                        let producer = node
                            .args
                            .first()
                            .and_then(channel_send_payload_zero_arg_producer);
                        match (&channel.producer, producer) {
                            (None, Some(producer)) => channel.producer = Some(producer),
                            (Some(existing), Some(producer)) if existing == &producer => {}
                            _ => channel.ambiguous = true,
                        }
                    } else {
                        channel.escaped = true;
                    }
                }
            }
            if let Some(rx) = expr_bare_ident_name(&node.receiver) {
                if let Some(channel) = self.channel_by_rx_mut(&rx) {
                    if node.method == "recv" && node.args.is_empty() {
                        let start = node.method.span().start();
                        channel.recv_sites.push((start.line, start.column));
                    } else {
                        channel.escaped = true;
                    }
                }
            }
            syn::visit::visit_expr_method_call(self, node);
        }
    }

    let mut visitor = V {
        rel_path,
        channels: Vec::new(),
    };
    visitor.visit_file(file);
    visitor.into_callsites()
}

fn collect_tokio_mutex_guard_conduit_callsites(file: &syn::File, rel_path: &str) -> Vec<CallSite> {
    use syn::visit::Visit;

    struct V<'a> {
        rel_path: &'a str,
        mutexes: Vec<TrackedMutexConduit>,
    }

    impl<'a> V<'a> {
        fn mutex_by_name_mut(&mut self, name: &str) -> Option<&mut TrackedMutexConduit> {
            self.mutexes.iter_mut().find(|mutex| mutex.mutex == name)
        }

        fn mutex_names(&self) -> BTreeSet<String> {
            self.mutexes
                .iter()
                .map(|mutex| mutex.mutex.clone())
                .collect()
        }

        fn mark_escaped_if_mutex_is_used_opaquely(&mut self, expr: &syn::Expr) {
            let mutexes = self.mutex_names();
            if mutexes.is_empty() {
                return;
            }
            for name in expr_ident_roots(expr) {
                if mutexes.contains(&name) {
                    if let Some(mutex) = self.mutex_by_name_mut(&name) {
                        mutex.escaped = true;
                    }
                }
            }
        }

        fn mark_allowed_mutex_guard_arg(&mut self, expr: &syn::Expr) -> bool {
            let mut matched = false;
            for mutex in &mut self.mutexes {
                if let Some(site) = mutex_guard_access_lock_site(expr, &mutex.mutex) {
                    mutex.allowed_lock_sites.insert(site);
                    matched = true;
                }
            }
            matched
        }

        fn into_callsites(self) -> Vec<CallSite> {
            let mut out = Vec::new();
            for mutex in self.mutexes {
                if mutex.escaped || mutex.lock_sites != mutex.allowed_lock_sites {
                    continue;
                }
                let Some(producer) = mutex.producer else {
                    continue;
                };
                for (line, col) in mutex.lock_sites {
                    out.push(CallSite {
                        callee: mutex_guard_source_symbol(&mutex.mutex),
                        contract_callee: producer.clone(),
                        callee_crate: None,
                        is_method: false,
                        disambiguated_callee: None,
                        disambiguated_crate: None,
                        unsupported_reason: None,
                        actual_terms: None,
                        caller_contract_name: None,
                        file: self.rel_path.to_string(),
                        line,
                        col,
                    });
                }
            }
            out
        }
    }

    impl<'ast, 'a> Visit<'ast> for V<'a> {
        fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
            let saved = std::mem::take(&mut self.mutexes);
            syn::visit::visit_item_fn(self, node);
            let current = std::mem::take(&mut self.mutexes);
            self.mutexes = saved;
            self.mutexes.extend(current);
        }

        fn visit_local(&mut self, node: &'ast syn::Local) {
            if let Some((mutex, producer)) = tokio_mutex_binding(node) {
                self.mutexes.push(TrackedMutexConduit {
                    mutex,
                    producer,
                    escaped: false,
                    lock_sites: BTreeSet::new(),
                    allowed_lock_sites: BTreeSet::new(),
                });
                syn::visit::visit_local(self, node);
                return;
            }

            let mutex_names = self.mutex_names();
            for bound in pat_bound_idents(&node.pat) {
                if mutex_names.contains(&bound) {
                    if let Some(mutex) = self.mutex_by_name_mut(&bound) {
                        mutex.escaped = true;
                    }
                }
            }
            if let Some(init) = &node.init {
                let uses_mutex = expr_ident_roots(&init.expr)
                    .iter()
                    .any(|name| mutex_names.contains(name));
                if uses_mutex && expr_as_call(&init.expr).is_none() {
                    self.mark_escaped_if_mutex_is_used_opaquely(&init.expr);
                }
            }
            syn::visit::visit_local(self, node);
        }

        fn visit_expr_call(&mut self, node: &'ast syn::ExprCall) {
            for arg in &node.args {
                if !self.mark_allowed_mutex_guard_arg(arg) {
                    self.mark_escaped_if_mutex_is_used_opaquely(arg);
                }
            }
            syn::visit::visit_expr_call(self, node);
        }

        fn visit_expr_assign(&mut self, node: &'ast syn::ExprAssign) {
            let roots = expr_assignment_roots(&node.left);
            for mutex in &mut self.mutexes {
                if roots.contains(&mutex.mutex) {
                    mutex.escaped = true;
                }
            }
            syn::visit::visit_expr_assign(self, node);
        }

        fn visit_expr_binary(&mut self, node: &'ast syn::ExprBinary) {
            if binop_is_assignment(&node.op) {
                let roots = expr_assignment_roots(&node.left);
                for mutex in &mut self.mutexes {
                    if roots.contains(&mutex.mutex) {
                        mutex.escaped = true;
                    }
                }
            }
            syn::visit::visit_expr_binary(self, node);
        }

        fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
            if let Some(mutex_name) = expr_bare_ident_name(&node.receiver) {
                if let Some(mutex) = self.mutex_by_name_mut(&mutex_name) {
                    if node.method == "lock" && node.args.is_empty() {
                        let start = node.method.span().start();
                        mutex.lock_sites.insert((start.line, start.column));
                    } else {
                        mutex.escaped = true;
                    }
                }
            }
            syn::visit::visit_expr_method_call(self, node);
        }
    }

    let mut visitor = V {
        rel_path,
        mutexes: Vec::new(),
    };
    visitor.visit_file(file);
    visitor.into_callsites()
}

fn tokio_mpsc_channel_binding(local: &syn::Local) -> Option<(String, String)> {
    let init = local.init.as_ref()?;
    if !expr_is_tokio_mpsc_channel_call(&init.expr) {
        return None;
    }
    let syn::Pat::Tuple(tuple) = &local.pat else {
        return None;
    };
    if tuple.elems.len() != 2 {
        return None;
    }
    let tx = pat_single_ident(tuple.elems.first()?)?;
    let rx = pat_single_ident(tuple.elems.iter().nth(1)?)?;
    Some((tx, rx))
}

fn tokio_mutex_binding(local: &syn::Local) -> Option<(String, Option<String>)> {
    let init = local.init.as_ref()?;
    let producer = tokio_mutex_new_producer(&init.expr)?;
    let mutex = pat_single_ident(&local.pat)?;
    Some((mutex, producer))
}

fn pat_single_ident(pat: &syn::Pat) -> Option<String> {
    match pat {
        syn::Pat::Ident(ident) => Some(ident.ident.to_string()),
        syn::Pat::Type(typed) => pat_single_ident(&typed.pat),
        _ => None,
    }
}

fn expr_is_tokio_mpsc_channel_call(expr: &syn::Expr) -> bool {
    let syn::Expr::Call(call) = expr else {
        return false;
    };
    let syn::Expr::Path(path) = &*call.func else {
        return false;
    };
    let segments = path
        .path
        .segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect::<Vec<_>>();
    segments.last().is_some_and(|leaf| leaf == "channel")
        && segments.iter().any(|segment| segment == "mpsc")
}

fn tokio_mutex_new_producer(expr: &syn::Expr) -> Option<Option<String>> {
    let syn::Expr::Call(call) = expr else {
        return None;
    };
    let syn::Expr::Path(path) = &*call.func else {
        return None;
    };
    let segments = path
        .path
        .segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect::<Vec<_>>();
    if segments.last().is_some_and(|leaf| leaf == "new")
        && segments.iter().any(|segment| segment == "Mutex")
        && call.args.len() == 1
    {
        Some(
            call.args
                .first()
                .and_then(channel_send_payload_zero_arg_producer),
        )
    } else {
        None
    }
}

fn channel_send_payload_zero_arg_producer(expr: &syn::Expr) -> Option<String> {
    match expr {
        syn::Expr::Await(await_expr) => channel_send_payload_zero_arg_producer(&await_expr.base),
        syn::Expr::Paren(paren) => channel_send_payload_zero_arg_producer(&paren.expr),
        syn::Expr::Group(group) => channel_send_payload_zero_arg_producer(&group.expr),
        syn::Expr::Reference(reference) => channel_send_payload_zero_arg_producer(&reference.expr),
        syn::Expr::Call(call) if call.args.is_empty() => {
            let syn::Expr::Path(path) = &*call.func else {
                return None;
            };
            path.path
                .segments
                .last()
                .map(|segment| segment.ident.to_string())
        }
        _ => None,
    }
}

fn mutex_guard_access_lock_site(expr: &syn::Expr, mutex: &str) -> Option<(usize, usize)> {
    match expr {
        syn::Expr::Unary(unary) => match unary.op {
            syn::UnOp::Deref(_) => mutex_lock_site(&unary.expr, mutex),
            _ => None,
        },
        syn::Expr::Paren(paren) => mutex_guard_access_lock_site(&paren.expr, mutex),
        syn::Expr::Group(group) => mutex_guard_access_lock_site(&group.expr, mutex),
        syn::Expr::Reference(reference) => mutex_guard_access_lock_site(&reference.expr, mutex),
        _ => None,
    }
}

fn mutex_lock_site(expr: &syn::Expr, mutex: &str) -> Option<(usize, usize)> {
    match expr {
        syn::Expr::Await(await_expr) => mutex_lock_site(&await_expr.base, mutex),
        syn::Expr::Paren(paren) => mutex_lock_site(&paren.expr, mutex),
        syn::Expr::Group(group) => mutex_lock_site(&group.expr, mutex),
        syn::Expr::Reference(reference) => mutex_lock_site(&reference.expr, mutex),
        syn::Expr::MethodCall(method) if method.method == "lock" && method.args.is_empty() => {
            if expr_bare_ident_name(&method.receiver).as_deref() == Some(mutex) {
                let start = method.method.span().start();
                Some((start.line, start.column))
            } else {
                None
            }
        }
        _ => None,
    }
}

fn expr_is_channel_recv_chain(expr: &syn::Expr, rx: &str) -> bool {
    match expr {
        syn::Expr::MethodCall(method)
            if (method.method == "unwrap" || method.method == "expect") =>
        {
            expr_is_channel_recv_chain(&method.receiver, rx)
        }
        syn::Expr::Await(await_expr) => expr_is_channel_recv_chain(&await_expr.base, rx),
        syn::Expr::Paren(paren) => expr_is_channel_recv_chain(&paren.expr, rx),
        syn::Expr::Group(group) => expr_is_channel_recv_chain(&group.expr, rx),
        syn::Expr::Reference(reference) => expr_is_channel_recv_chain(&reference.expr, rx),
        syn::Expr::MethodCall(method) if method.method == "recv" && method.args.is_empty() => {
            expr_bare_ident_name(&method.receiver).as_deref() == Some(rx)
        }
        _ => false,
    }
}

fn expr_ident_roots(expr: &syn::Expr) -> BTreeSet<String> {
    let mut roots = BTreeSet::new();
    struct V<'a> {
        roots: &'a mut BTreeSet<String>,
    }
    impl<'ast, 'a> syn::visit::Visit<'ast> for V<'a> {
        fn visit_expr_path(&mut self, node: &'ast syn::ExprPath) {
            if node.path.segments.len() == 1 {
                self.roots.insert(node.path.segments[0].ident.to_string());
            }
            syn::visit::visit_expr_path(self, node);
        }
    }
    syn::visit::Visit::visit_expr(&mut V { roots: &mut roots }, expr);
    roots
}

#[derive(Debug, Clone, Copy, Default)]
struct OracleObservation {
    requested: bool,
    reachable: bool,
    ready: bool,
    attempted: u64,
    resolved: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct TypeIdentity {
    krate: String,
    head: String,
}

#[derive(Debug, Clone, Default)]
struct InfallibleSerializeManifest {
    rules: Vec<InfallibleSerializeRule>,
    by_key: HashMap<(String, String, String), usize>,
}

#[derive(Debug, Clone)]
struct InfallibleSerializeRule {
    function: String,
    type_id: TypeIdentity,
    contract: String,
    reason: String,
}

impl InfallibleSerializeManifest {
    fn load(workspace_root: &Path) -> Result<Self, String> {
        let path = workspace_root
            .join(".sugar")
            .join("contracts")
            .join("infallible_serialize.toml");
        if !path.is_file() {
            return Ok(Self::default());
        }
        // Side metadata/config: this file does not enter proof CIDs directly.
        // The synthetic contract entries emitted from it do enter the normal
        // mint path, so changing a blessed entry intentionally changes the
        // corresponding contract bytes and CID.
        let raw =
            std::fs::read_to_string(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
        let value: toml::Value =
            toml::from_str(&raw).map_err(|e| format!("parse {}: {e}", path.display()))?;
        let table = value
            .as_table()
            .ok_or_else(|| format!("{} must be a TOML table", path.display()))?;
        let Some(serde_json_value) = table.get("serde_json") else {
            return Ok(Self::default());
        };
        let entries = serde_json_value.as_array().ok_or_else(|| {
            format!(
                "{} field `serde_json` must be an array of tables (`[[serde_json]]`)",
                path.display()
            )
        })?;

        let mut manifest = Self::default();
        for (idx, entry) in entries.iter().enumerate() {
            let table = entry.as_table().ok_or_else(|| {
                format!(
                    "{} `serde_json[{idx}]` must be a table, got {}",
                    path.display(),
                    toml_value_type(entry)
                )
            })?;
            let function = required_toml_string(&path, idx, table, "function")?;
            if !matches!(
                function.as_str(),
                "to_value" | "to_string" | "to_string_pretty"
            ) {
                return Err(format!(
                    "{} `serde_json[{idx}].function` must be one of to_value, to_string, to_string_pretty",
                    path.display()
                ));
            }
            let type_crate =
                normalize_crate_root(&required_toml_string(&path, idx, table, "type_crate")?);
            let type_name = required_toml_string(&path, idx, table, "type_name")?;
            let contract = required_toml_string(&path, idx, table, "contract")?;
            let reason = required_toml_string(&path, idx, table, "reason")?;
            let key = (function.clone(), type_crate.clone(), type_name.clone());
            if manifest.by_key.contains_key(&key) {
                return Err(format!(
                    "{} duplicate serde_json infallible entry for function `{}`, type `{}`::{}`",
                    path.display(),
                    function,
                    type_crate,
                    type_name
                ));
            }
            let rule = InfallibleSerializeRule {
                function,
                type_id: TypeIdentity {
                    krate: type_crate,
                    head: type_name,
                },
                contract,
                reason,
            };
            manifest.by_key.insert(key, manifest.rules.len());
            manifest.rules.push(rule);
        }
        Ok(manifest)
    }

    fn is_empty(&self) -> bool {
        self.rules.is_empty()
    }

    fn contract_for(&self, function: &str, type_id: &TypeIdentity) -> Option<&str> {
        let key = (
            function.to_string(),
            type_id.krate.clone(),
            type_id.head.clone(),
        );
        self.by_key
            .get(&key)
            .and_then(|idx| self.rules.get(*idx))
            .map(|rule| rule.contract.as_str())
    }
}

#[derive(Debug, Clone, Default)]
struct FunctionPostconditionsManifest {
    rules: Vec<FunctionPostconditionRule>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum FunctionPostconditionCallKind {
    Associated,
    Free,
    Method,
}

#[derive(Debug, Clone)]
enum FunctionPostconditionArg0 {
    FormatRepeat {
        format_literal: String,
        repeat_literal: String,
        repeat_count: u64,
    },
    Path(String),
}

#[derive(Debug, Clone)]
struct FunctionPostconditionRule {
    call_kind: FunctionPostconditionCallKind,
    callee_crate: String,
    type_path: Option<String>,
    receiver_path: Option<String>,
    callee: String,
    pure: bool,
    source_file: Option<String>,
    source_line: Option<usize>,
    arg0: Option<FunctionPostconditionArg0>,
    contract: String,
    post_predicate: String,
    reason: String,
}

#[derive(Debug, Clone)]
struct PureFreeCallGuardFact {
    callee: String,
    args: Vec<syn::Expr>,
    arg_roots: BTreeSet<String>,
    post_predicate: String,
}

#[derive(Debug, Clone, Default)]
struct ResidueManifest {
    annotations: Vec<PanicSiteAnnotationDiagnostic>,
}

#[derive(Debug, Clone)]
struct PanicSiteAnnotationDiagnostic {
    file: String,
    line: usize,
    callee: String,
    status: &'static str,
    category: String,
    tier_to_close: String,
    reason: String,
}

impl ResidueManifest {
    fn load(workspace_root: &Path) -> Result<Self, String> {
        let path = workspace_root.join(".sugar").join("residue.toml");
        if !path.is_file() {
            return Ok(Self::default());
        }
        let raw =
            std::fs::read_to_string(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
        let value: toml::Value =
            toml::from_str(&raw).map_err(|e| format!("parse {}: {e}", path.display()))?;
        let table = value
            .as_table()
            .ok_or_else(|| format!("{} must be a TOML table", path.display()))?;

        let mut annotations = Vec::new();
        let mut seen = BTreeSet::new();
        Self::read_section(
            &path,
            table,
            "residue",
            "residue",
            &mut annotations,
            &mut seen,
        )?;
        Self::read_section(
            &path,
            table,
            "tier_to_close",
            "unproven",
            &mut annotations,
            &mut seen,
        )?;

        Ok(Self { annotations })
    }

    fn read_section(
        path: &Path,
        table: &toml::map::Map<String, toml::Value>,
        section: &str,
        status: &'static str,
        annotations: &mut Vec<PanicSiteAnnotationDiagnostic>,
        seen: &mut BTreeSet<(String, usize, String)>,
    ) -> Result<(), String> {
        let Some(entries_value) = table.get(section) else {
            return Ok(());
        };
        let entries = entries_value.as_array().ok_or_else(|| {
            format!(
                "{} field `{section}` must be an array of tables (`[[{section}]]`)",
                path.display()
            )
        })?;

        for (idx, entry) in entries.iter().enumerate() {
            let context = format!("{section}[{idx}]");
            let table = entry.as_table().ok_or_else(|| {
                format!(
                    "{} `{context}` must be a table, got {}",
                    path.display(),
                    toml_value_type(entry)
                )
            })?;
            let file = required_toml_string_for(path, &context, table, "file")?;
            let line = required_toml_u64_for(path, &context, table, "line")? as usize;
            let callee = required_toml_string_for(path, &context, table, "callee")?;
            let category = required_toml_string_for(path, &context, table, "category")?;
            let tier_to_close = required_toml_string_for(path, &context, table, "tier_to_close")?;
            let reason = required_toml_string_for(path, &context, table, "reason")?;
            let key = (file.clone(), line, callee.clone());
            if !seen.insert(key) {
                return Err(format!(
                    "duplicate panic-site annotation for {}:{} {} in {}",
                    file,
                    line,
                    callee,
                    path.display()
                ));
            }
            annotations.push(PanicSiteAnnotationDiagnostic {
                file,
                line,
                callee,
                status,
                category,
                tier_to_close,
                reason,
            });
        }

        Ok(())
    }

    fn is_empty(&self) -> bool {
        self.annotations.is_empty()
    }

    fn into_diagnostics(self) -> Vec<Value> {
        self.annotations
            .into_iter()
            .map(PanicSiteAnnotationDiagnostic::into_diagnostic)
            .collect()
    }
}

impl PanicSiteAnnotationDiagnostic {
    fn into_diagnostic(self) -> Value {
        json!({
            "kind": "panic-site-annotation",
            "file": self.file,
            "line": self.line,
            "callee": self.callee,
            "status": self.status,
            "category": self.category,
            "tierToClose": self.tier_to_close,
            "reason": self.reason,
        })
    }
}

impl FunctionPostconditionsManifest {
    fn load(workspace_root: &Path) -> Result<Self, String> {
        let path = workspace_root
            .join(".sugar")
            .join("contracts")
            .join("function_postconditions.toml");
        if !path.is_file() {
            return Ok(Self::default());
        }
        let raw =
            std::fs::read_to_string(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
        let value: toml::Value =
            toml::from_str(&raw).map_err(|e| format!("parse {}: {e}", path.display()))?;
        let table = value
            .as_table()
            .ok_or_else(|| format!("{} must be a TOML table", path.display()))?;
        let Some(functions_value) = table.get("functions") else {
            return Ok(Self::default());
        };
        let entries = functions_value.as_array().ok_or_else(|| {
            format!(
                "{} field `functions` must be an array of tables (`[[functions]]`)",
                path.display()
            )
        })?;

        let mut manifest = Self::default();
        let mut seen_contracts = BTreeSet::new();
        for (idx, entry) in entries.iter().enumerate() {
            let context = format!("functions[{idx}]");
            let table = entry.as_table().ok_or_else(|| {
                format!(
                    "{} `{context}` must be a table, got {}",
                    path.display(),
                    toml_value_type(entry)
                )
            })?;
            let call_kind =
                match required_toml_string_for(&path, &context, table, "call_kind")?.as_str() {
                    "associated" => FunctionPostconditionCallKind::Associated,
                    "free" => FunctionPostconditionCallKind::Free,
                    "method" => FunctionPostconditionCallKind::Method,
                    other => {
                        return Err(format!(
                        "{} `{context}.call_kind` must be `associated`, `free`, or `method`, got `{other}`",
                        path.display()
                    ))
                    }
                };
            let callee_crate = normalize_crate_root(&required_toml_string_for(
                &path,
                &context,
                table,
                "callee_crate",
            )?);
            let callee = required_toml_string_for(&path, &context, table, "callee")?;
            let contract = required_toml_string_for(&path, &context, table, "contract")?;
            let post_predicate =
                required_toml_string_for(&path, &context, table, "post_predicate")?;
            let reason = required_toml_string_for(&path, &context, table, "reason")?;
            let pure = match table
                .get("pure")
                .map(|value| {
                    value.as_bool().ok_or_else(|| {
                        format!(
                            "{} `{context}.pure` must be a boolean, got {}",
                            path.display(),
                            toml_value_type(value)
                        )
                    })
                })
                .transpose()?
            {
                Some(pure) => pure,
                None => false,
            };
            let source_file = table
                .get("source_file")
                .and_then(toml::Value::as_str)
                .map(ToString::to_string);
            let source_line = table
                .get("source_line")
                .map(|_| required_toml_u64_for(&path, &context, table, "source_line"))
                .transpose()?
                .map(|line| line as usize);
            if source_file.is_some() != source_line.is_some() {
                return Err(format!(
                    "{} `{context}` must set `source_file` and `source_line` together",
                    path.display()
                ));
            }
            if !seen_contracts.insert(contract.clone()) {
                return Err(format!(
                    "{} duplicate function postcondition contract `{contract}`",
                    path.display()
                ));
            }

            let (type_path, receiver_path, arg0) = match call_kind {
                FunctionPostconditionCallKind::Associated => {
                    let type_path = required_toml_string_for(&path, &context, table, "type_path")?;
                    let arg0 = if let Some(arg0_path) =
                        table.get("arg0_path").and_then(toml::Value::as_str)
                    {
                        FunctionPostconditionArg0::Path(arg0_path.to_string())
                    } else {
                        let format_literal = required_toml_string_for(
                            &path,
                            &context,
                            table,
                            "arg0_format_literal",
                        )?;
                        let repeat_literal = required_toml_string_for(
                            &path,
                            &context,
                            table,
                            "arg0_repeat_literal",
                        )?;
                        let repeat_count =
                            required_toml_u64_for(&path, &context, table, "arg0_repeat_count")?;
                        FunctionPostconditionArg0::FormatRepeat {
                            format_literal,
                            repeat_literal,
                            repeat_count,
                        }
                    };
                    (Some(type_path), None, Some(arg0))
                }
                FunctionPostconditionCallKind::Free => {
                    if !pure {
                        return Err(format!(
                            "{} `{context}` with `call_kind = \"free\"` must set `pure = true`",
                            path.display()
                        ));
                    }
                    if table.contains_key("type_path")
                        || table.contains_key("receiver_path")
                        || table.contains_key("arg0_path")
                        || table.contains_key("arg0_format_literal")
                        || table.contains_key("arg0_repeat_literal")
                        || table.contains_key("arg0_repeat_count")
                    {
                        return Err(format!(
                            "{} `{context}` with `call_kind = \"free\"` is guard-only and must not set type/receiver/arg0 match fields",
                            path.display()
                        ));
                    }
                    (None, None, None)
                }
                FunctionPostconditionCallKind::Method => {
                    let receiver_path =
                        required_toml_string_for(&path, &context, table, "receiver_path")?;
                    let arg0_path = required_toml_string_for(&path, &context, table, "arg0_path")?;
                    (
                        None,
                        Some(receiver_path),
                        Some(FunctionPostconditionArg0::Path(arg0_path)),
                    )
                }
            };

            manifest.rules.push(FunctionPostconditionRule {
                call_kind,
                callee_crate,
                type_path,
                receiver_path,
                callee,
                pure,
                source_file,
                source_line,
                arg0,
                contract,
                post_predicate,
                reason,
            });
        }
        Ok(manifest)
    }

    fn is_empty(&self) -> bool {
        self.rules.is_empty()
    }

    fn rule_for_associated_call(
        &self,
        func: &syn::Expr,
        args: &syn::punctuated::Punctuated<syn::Expr, syn::Token![,]>,
        current_crate: &str,
        source_file: &str,
        source_line: usize,
    ) -> Option<&FunctionPostconditionRule> {
        let (type_path, callee) = associated_call_path_and_leaf(func)?;
        self.rules.iter().find_map(|rule| {
            if rule.call_kind != FunctionPostconditionCallKind::Associated {
                return None;
            }
            if rule.callee_crate != current_crate || rule.callee != callee {
                return None;
            }
            if rule.type_path.as_deref() != Some(type_path.as_str()) {
                return None;
            }
            if !function_postcondition_source_matches(rule, source_file, source_line) {
                return None;
            }
            let arg0 = only_call_arg(args)?;
            let rule_arg0 = rule.arg0.as_ref()?;
            match rule_arg0 {
                FunctionPostconditionArg0::FormatRepeat {
                    format_literal,
                    repeat_literal,
                    repeat_count,
                } => {
                    if !expr_matches_format_repeat(
                        arg0,
                        format_literal,
                        repeat_literal,
                        *repeat_count,
                    ) {
                        return None;
                    }
                }
                FunctionPostconditionArg0::Path(expected_arg) => {
                    if expr_path_text(arg0).as_deref() != Some(expected_arg.as_str()) {
                        return None;
                    }
                }
            }
            Some(rule)
        })
    }

    fn rule_for_free_pure_call(
        &self,
        func: &syn::Expr,
        use_map: &HashMap<String, String>,
        current_crate: &str,
        source_file: &str,
        source_line: usize,
        local_free_functions: &BTreeSet<String>,
    ) -> Option<&FunctionPostconditionRule> {
        let (callee, callee_crate, _) = call_expr_callee(func, use_map, current_crate)?;
        let resolved_crate = callee_crate.unwrap_or_else(|| current_crate.to_string());
        if resolved_crate != current_crate || !local_free_functions.contains(&callee) {
            return None;
        }
        self.rules.iter().find_map(|rule| {
            if rule.call_kind != FunctionPostconditionCallKind::Free || !rule.pure {
                return None;
            }
            if rule.callee_crate != current_crate || rule.callee != callee {
                return None;
            }
            if !function_postcondition_source_matches(rule, source_file, source_line) {
                return None;
            }
            if panic_stem_for_post_predicate(&rule.post_predicate).is_none() {
                return None;
            }
            Some(rule)
        })
    }

    fn target_for_associated_call(
        &self,
        func: &syn::Expr,
        args: &syn::punctuated::Punctuated<syn::Expr, syn::Token![,]>,
        current_crate: &str,
        source_file: &str,
        source_line: usize,
    ) -> Option<(String, String)> {
        self.rule_for_associated_call(func, args, current_crate, source_file, source_line)
            .map(|rule| (current_crate.to_string(), rule.contract.clone()))
    }

    fn rule_for_method_call(
        &self,
        node: &syn::ExprMethodCall,
        current_crate: &str,
        source_file: &str,
        source_line: usize,
        stability_block: Option<&syn::Block>,
        param_names: &BTreeSet<String>,
    ) -> Option<&FunctionPostconditionRule> {
        let callee = node.method.to_string();
        self.rules.iter().find_map(|rule| {
            if rule.call_kind != FunctionPostconditionCallKind::Method {
                return None;
            }
            if rule.callee_crate != current_crate || rule.callee != callee {
                return None;
            }
            if expr_path_text(&node.receiver) != rule.receiver_path {
                return None;
            }
            if !function_postcondition_source_matches(rule, source_file, source_line) {
                return None;
            }
            if let Some(block) = stability_block {
                if !method_postcondition_receiver_is_stable(node, block, param_names) {
                    return None;
                }
            }
            let rule_arg0 = rule.arg0.as_ref()?;
            let arg0 = only_call_arg(&node.args)?;
            match rule_arg0 {
                FunctionPostconditionArg0::Path(expected_arg) => {
                    if expr_path_text(arg0).as_deref() != Some(expected_arg.as_str()) {
                        return None;
                    }
                }
                FunctionPostconditionArg0::FormatRepeat { .. } => return None,
            }
            Some(rule)
        })
    }

    fn target_for_method_call(
        &self,
        node: &syn::ExprMethodCall,
        current_crate: &str,
        source_file: &str,
        source_line: usize,
        stability_block: &syn::Block,
        param_names: &BTreeSet<String>,
    ) -> Option<(String, String)> {
        self.rule_for_method_call(
            node,
            current_crate,
            source_file,
            source_line,
            Some(stability_block),
            param_names,
        )
        .map(|rule| (current_crate.to_string(), rule.contract.clone()))
    }

    fn panic_partial_for_receiver(
        &self,
        receiver: &syn::Expr,
        current_crate: &str,
        source_file: &str,
        panic_leaf: &str,
        stability_block: &syn::Block,
        param_names: &BTreeSet<String>,
    ) -> Option<(String, String)> {
        let rule = match receiver {
            syn::Expr::Call(call) => {
                let start = call.func.span().start();
                self.rule_for_associated_call(
                    &call.func,
                    &call.args,
                    current_crate,
                    source_file,
                    start.line,
                )
            }
            syn::Expr::MethodCall(method) => {
                let start = method.method.span().start();
                self.rule_for_method_call(
                    method,
                    current_crate,
                    source_file,
                    start.line,
                    Some(stability_block),
                    param_names,
                )
            }
            syn::Expr::Paren(paren) => {
                return self.panic_partial_for_receiver(
                    &paren.expr,
                    current_crate,
                    source_file,
                    panic_leaf,
                    stability_block,
                    param_names,
                );
            }
            syn::Expr::Group(group) => {
                return self.panic_partial_for_receiver(
                    &group.expr,
                    current_crate,
                    source_file,
                    panic_leaf,
                    stability_block,
                    param_names,
                );
            }
            syn::Expr::Reference(reference) => {
                return self.panic_partial_for_receiver(
                    &reference.expr,
                    current_crate,
                    source_file,
                    panic_leaf,
                    stability_block,
                    param_names,
                );
            }
            _ => None,
        }?;
        let stem = panic_stem_for_post_predicate(&rule.post_predicate)?;
        disambiguated_partial_leaf(stem, panic_leaf).map(|leaf| ("std".to_string(), leaf))
    }
}

fn function_postcondition_source_matches(
    rule: &FunctionPostconditionRule,
    source_file: &str,
    source_line: usize,
) -> bool {
    match (rule.source_file.as_deref(), rule.source_line) {
        (Some(expected_file), Some(expected_line)) => {
            expected_file == source_file && expected_line == source_line
        }
        (None, None) => true,
        _ => false,
    }
}

fn panic_stem_for_post_predicate(predicate: &str) -> Option<&'static str> {
    match predicate {
        panic_freedom::IS_OK => Some("result"),
        panic_freedom::IS_SOME => Some("option"),
        _ => None,
    }
}

fn toml_value_type(value: &toml::Value) -> &'static str {
    match value {
        toml::Value::String(_) => "string",
        toml::Value::Integer(_) => "integer",
        toml::Value::Float(_) => "float",
        toml::Value::Boolean(_) => "boolean",
        toml::Value::Datetime(_) => "datetime",
        toml::Value::Array(_) => "array",
        toml::Value::Table(_) => "table",
    }
}

fn required_toml_string(
    path: &Path,
    idx: usize,
    table: &toml::map::Map<String, toml::Value>,
    field: &str,
) -> Result<String, String> {
    required_toml_string_for(path, &format!("serde_json[{idx}]"), table, field)
}

fn required_toml_string_for(
    path: &Path,
    context: &str,
    table: &toml::map::Map<String, toml::Value>,
    field: &str,
) -> Result<String, String> {
    let value = table.get(field).ok_or_else(|| {
        format!(
            "{} `{context}` missing required string field `{field}`",
            path.display()
        )
    })?;
    value
        .as_str()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .ok_or_else(|| {
            format!(
                "{} `{context}.{field}` must be a non-empty string, got {}",
                path.display(),
                toml_value_type(value)
            )
        })
}

fn required_toml_u64_for(
    path: &Path,
    context: &str,
    table: &toml::map::Map<String, toml::Value>,
    field: &str,
) -> Result<u64, String> {
    let value = table.get(field).ok_or_else(|| {
        format!(
            "{} `{context}` missing required integer field `{field}`",
            path.display()
        )
    })?;
    let raw = value.as_integer().ok_or_else(|| {
        format!(
            "{} `{context}.{field}` must be a non-negative integer, got {}",
            path.display(),
            toml_value_type(value)
        )
    })?;
    u64::try_from(raw).map_err(|_| {
        format!(
            "{} `{context}.{field}` must be a non-negative integer, got {raw}",
            path.display()
        )
    })
}

/// Map of `leaf ident -> crate root` for the `use` imports in one file.
/// `use libsugar::core::{address, cid_of_value}` yields
/// `{address: libsugar, cid_of_value: libsugar}`. `crate`/`self`/`super`
/// roots map to `"crate"` (the current crate). Lets a bare call `address(x)`
/// recover that it is `libsugar::address`, robust to internal re-exports
/// because only the ROOT (not the full module path) is needed to disambiguate.
fn build_use_crate_map(file: &syn::File) -> HashMap<String, String> {
    let mut map = HashMap::new();
    for item in &file.items {
        if let syn::Item::Use(item_use) = item {
            collect_use_tree(&item_use.tree, None, &mut map);
        }
    }
    map
}

/// Walk a `use` tree, threading the crate root (first path segment) down to
/// each imported leaf. `root` is `None` until the first `Path` segment fixes it.
fn collect_use_tree(tree: &syn::UseTree, root: Option<&str>, map: &mut HashMap<String, String>) {
    match tree {
        syn::UseTree::Path(p) => {
            let seg = p.ident.to_string();
            // The crate root is the FIRST segment. `crate`/`self`/`super`
            // normalize to the current crate.
            let next_root = root.map(|r| r.to_string()).unwrap_or_else(|| {
                if seg == "self" || seg == "super" || seg == "crate" {
                    "crate".to_string()
                } else {
                    seg.clone()
                }
            });
            collect_use_tree(&p.tree, Some(&next_root), map);
        }
        syn::UseTree::Name(n) => {
            if let Some(r) = root {
                map.insert(n.ident.to_string(), r.to_string());
            }
        }
        syn::UseTree::Rename(r) => {
            // `use a::b as c`: the in-scope name is `c`, still rooted at `root`.
            let rt = root
                .map(str::to_string)
                .unwrap_or_else(|| r.ident.to_string());
            map.insert(r.rename.to_string(), rt);
        }
        syn::UseTree::Group(g) => {
            for item in &g.items {
                collect_use_tree(item, root, map);
            }
        }
        syn::UseTree::Glob(_) => {
            // A glob import (`use foo::*`) brings unknown leaves; we cannot map
            // individual names, so callees relying on it stay unresolved (None)
            // and fall back to the current crate. Honest under-approximation.
        }
    }
}

fn resolve_path_root_crate(
    root: &str,
    use_map: &HashMap<String, String>,
    current_crate: &str,
) -> String {
    if root == "crate" || root == "self" || root == "super" {
        current_crate.to_string()
    } else if let Some(mapped) = use_map.get(root) {
        if mapped == "crate" {
            current_crate.to_string()
        } else {
            normalize_crate_root(mapped)
        }
    } else {
        normalize_crate_root(root)
    }
}

fn type_crate_for(
    ty: &syn::Type,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<String> {
    let syn::Type::Path(tp) = ty else {
        return None;
    };
    let segs: Vec<String> = tp
        .path
        .segments
        .iter()
        .map(|s| s.ident.to_string())
        .collect();
    let first = segs.first()?;
    if segs.len() >= 2 {
        Some(resolve_path_root_crate(first, use_map, current_crate))
    } else {
        use_map
            .get(first)
            .map(|root| resolve_path_root_crate(root, use_map, current_crate))
            .or_else(|| {
                if !current_crate.is_empty() && local_type_names.contains(first) {
                    Some(current_crate.to_string())
                } else if is_std_prelude_panic_type(first) {
                    Some("std".to_string())
                } else {
                    None
                }
            })
    }
}

fn is_std_prelude_panic_type(name: &str) -> bool {
    matches!(name, "Option" | "Result")
}

fn collect_local_type_names(file: &syn::File) -> BTreeSet<String> {
    let mut names = BTreeSet::new();
    collect_local_type_names_in_items(&file.items, &mut names);
    names
}

fn collect_local_type_names_in_items(items: &[syn::Item], names: &mut BTreeSet<String>) {
    for item in items {
        match item {
            syn::Item::Struct(item) => {
                names.insert(item.ident.to_string());
            }
            syn::Item::Enum(item) => {
                names.insert(item.ident.to_string());
            }
            syn::Item::Union(item) => {
                names.insert(item.ident.to_string());
            }
            syn::Item::Type(item) => {
                names.insert(item.ident.to_string());
            }
            syn::Item::Mod(item_mod) => {
                if let Some((_, ref nested)) = item_mod.content {
                    collect_local_type_names_in_items(nested, names);
                }
            }
            // sugar-audit: not-mine(local type name index only records type declarations and inline modules)
            _ => {}
        }
    }
}

#[derive(Debug, Clone, Default)]
struct EnumVariantTypeMap {
    variants: HashMap<(String, String), VariantFieldTypes>,
}

#[derive(Debug, Clone, Default)]
struct StructFieldTypeMap {
    fields: HashMap<(String, String, String), FieldTypeIdentity>,
}

#[derive(Debug, Clone)]
struct FieldTypeIdentity {
    type_id: TypeIdentity,
    option_inner: Option<TypeIdentity>,
}

#[derive(Debug, Clone)]
enum VariantFieldTypes {
    Named(HashMap<String, TypeIdentity>),
    Unnamed(Vec<TypeIdentity>),
    Unit,
}

fn collect_enum_variant_type_map(
    file: &syn::File,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> EnumVariantTypeMap {
    let mut map = EnumVariantTypeMap::default();
    collect_enum_variant_type_map_in_items(
        &file.items,
        use_map,
        local_type_names,
        current_crate,
        &mut map,
    );
    map
}

fn collect_struct_field_type_map(
    file: &syn::File,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> StructFieldTypeMap {
    let mut map = StructFieldTypeMap::default();
    collect_struct_field_type_map_in_items(
        &file.items,
        use_map,
        local_type_names,
        current_crate,
        &mut map,
    );
    map
}

fn collect_struct_field_type_map_in_items(
    items: &[syn::Item],
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
    out: &mut StructFieldTypeMap,
) {
    for item in items {
        match item {
            syn::Item::Struct(item_struct) => {
                let struct_type = TypeIdentity {
                    krate: current_crate.to_string(),
                    head: item_struct.ident.to_string(),
                };
                let syn::Fields::Named(named) = &item_struct.fields else {
                    continue;
                };
                for field in &named.named {
                    let Some(ident) = field.ident.as_ref() else {
                        continue;
                    };
                    let Some(field_type) = field_type_identity_for(
                        strip_reference_type(&field.ty),
                        use_map,
                        local_type_names,
                        current_crate,
                    ) else {
                        continue;
                    };
                    out.fields.insert(
                        (
                            struct_type.krate.clone(),
                            struct_type.head.clone(),
                            ident.to_string(),
                        ),
                        field_type,
                    );
                }
            }
            syn::Item::Mod(item_mod) => {
                if let Some((_, ref nested)) = item_mod.content {
                    collect_struct_field_type_map_in_items(
                        nested,
                        use_map,
                        local_type_names,
                        current_crate,
                        out,
                    );
                }
            }
            // sugar-audit: not-mine(struct field map only records struct declarations and inline modules)
            _ => {}
        }
    }
}

fn field_type_identity_for(
    ty: &syn::Type,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<FieldTypeIdentity> {
    Some(FieldTypeIdentity {
        type_id: type_identity_for(ty, use_map, local_type_names, current_crate)?,
        option_inner: option_inner_type_identity_for(ty, use_map, local_type_names, current_crate),
    })
}

fn option_inner_type_identity_for(
    ty: &syn::Type,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<TypeIdentity> {
    let syn::Type::Path(path) = ty else {
        return None;
    };
    let segment = path.path.segments.last()?;
    if segment.ident != "Option" {
        return None;
    }
    let syn::PathArguments::AngleBracketed(args) = &segment.arguments else {
        return None;
    };
    let syn::GenericArgument::Type(inner_ty) = args.args.first()? else {
        return None;
    };
    type_identity_for(
        strip_reference_type(inner_ty),
        use_map,
        local_type_names,
        current_crate,
    )
}

fn collect_enum_variant_type_map_in_items(
    items: &[syn::Item],
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
    out: &mut EnumVariantTypeMap,
) {
    for item in items {
        match item {
            syn::Item::Enum(item_enum) => {
                let enum_name = item_enum.ident.to_string();
                for variant in &item_enum.variants {
                    let variant_name = variant.ident.to_string();
                    let fields = match &variant.fields {
                        syn::Fields::Named(named) => {
                            let mut fields = HashMap::new();
                            for field in &named.named {
                                let Some(ident) = field.ident.as_ref() else {
                                    continue;
                                };
                                if let Some(type_id) = type_identity_for(
                                    strip_reference_type(&field.ty),
                                    use_map,
                                    local_type_names,
                                    current_crate,
                                ) {
                                    fields.insert(ident.to_string(), type_id);
                                }
                            }
                            VariantFieldTypes::Named(fields)
                        }
                        syn::Fields::Unnamed(unnamed) => {
                            let fields = unnamed
                                .unnamed
                                .iter()
                                .filter_map(|field| {
                                    type_identity_for(
                                        strip_reference_type(&field.ty),
                                        use_map,
                                        local_type_names,
                                        current_crate,
                                    )
                                })
                                .collect();
                            VariantFieldTypes::Unnamed(fields)
                        }
                        syn::Fields::Unit => VariantFieldTypes::Unit,
                    };
                    out.variants
                        .insert((enum_name.clone(), variant_name), fields);
                }
            }
            syn::Item::Mod(item_mod) => {
                if let Some((_, ref nested)) = item_mod.content {
                    collect_enum_variant_type_map_in_items(
                        nested,
                        use_map,
                        local_type_names,
                        current_crate,
                        out,
                    );
                }
            }
            // sugar-audit: not-mine(enum variant map only records enum declarations and inline modules)
            _ => {}
        }
    }
}

fn bind_pattern_type_id(
    pat: &syn::Pat,
    scrutinee_type: &TypeIdentity,
    enum_variant_types: &EnumVariantTypeMap,
    local_types: &mut HashMap<String, String>,
    value_types: &mut HashMap<String, TypeIdentity>,
) {
    match pat {
        syn::Pat::Ident(ident) => {
            bind_value_type(
                &ident.ident.to_string(),
                scrutinee_type.clone(),
                local_types,
                value_types,
            );
            if let Some((_at, subpat)) = &ident.subpat {
                bind_pattern_type_id(
                    subpat,
                    scrutinee_type,
                    enum_variant_types,
                    local_types,
                    value_types,
                );
            }
        }
        syn::Pat::Reference(reference) => {
            bind_pattern_type_id(
                &reference.pat,
                scrutinee_type,
                enum_variant_types,
                local_types,
                value_types,
            );
        }
        syn::Pat::Struct(pat_struct) => {
            let Some(variant_name) = pat_struct
                .path
                .segments
                .last()
                .map(|seg| seg.ident.to_string())
            else {
                return;
            };
            let enum_name = pat_struct
                .path
                .segments
                .iter()
                .rev()
                .nth(1)
                .map(|seg| seg.ident.to_string())
                .unwrap_or_else(|| scrutinee_type.head.clone());
            let Some(VariantFieldTypes::Named(fields)) =
                enum_variant_types.variants.get(&(enum_name, variant_name))
            else {
                return;
            };
            for field in &pat_struct.fields {
                let field_name = field.member.to_token_stream().to_string();
                let Some(type_id) = fields.get(&field_name).cloned() else {
                    continue;
                };
                bind_pattern_type_id(
                    &field.pat,
                    &type_id,
                    enum_variant_types,
                    local_types,
                    value_types,
                );
            }
        }
        syn::Pat::TupleStruct(tuple_struct) => {
            let Some(variant_name) = tuple_struct
                .path
                .segments
                .last()
                .map(|seg| seg.ident.to_string())
            else {
                return;
            };
            let enum_name = tuple_struct
                .path
                .segments
                .iter()
                .rev()
                .nth(1)
                .map(|seg| seg.ident.to_string())
                .unwrap_or_else(|| scrutinee_type.head.clone());
            let Some(VariantFieldTypes::Unnamed(fields)) =
                enum_variant_types.variants.get(&(enum_name, variant_name))
            else {
                return;
            };
            for (subpat, type_id) in tuple_struct.elems.iter().zip(fields.iter()) {
                bind_pattern_type_id(
                    subpat,
                    type_id,
                    enum_variant_types,
                    local_types,
                    value_types,
                );
            }
        }
        syn::Pat::Or(or_pat) => {
            for case in &or_pat.cases {
                bind_pattern_type_id(
                    case,
                    scrutinee_type,
                    enum_variant_types,
                    local_types,
                    value_types,
                );
            }
        }
        syn::Pat::Paren(paren) => bind_pattern_type_id(
            &paren.pat,
            scrutinee_type,
            enum_variant_types,
            local_types,
            value_types,
        ),
        syn::Pat::Type(typed) => bind_pattern_type_id(
            &typed.pat,
            scrutinee_type,
            enum_variant_types,
            local_types,
            value_types,
        ),
        // sugar-audit: not-mine(non-binding or schema-needed pattern forms cannot receive a sound value type here)
        _ => {}
    }
}

fn bind_option_pattern_type_id(
    pat: &syn::Pat,
    inner_type: &TypeIdentity,
    local_types: &mut HashMap<String, String>,
    value_types: &mut HashMap<String, TypeIdentity>,
) {
    match pat {
        syn::Pat::TupleStruct(tuple_struct) => {
            let is_some_tuple = match tuple_struct.path.segments.last() {
                Some(segment) => segment.ident == "Some",
                None => false,
            };
            if is_some_tuple && tuple_struct.elems.len() == 1 {
                if let Some(inner_pat) = tuple_struct.elems.first() {
                    bind_pattern_type_id_direct(inner_pat, inner_type, local_types, value_types);
                }
            }
        }
        syn::Pat::Reference(reference) => {
            bind_option_pattern_type_id(&reference.pat, inner_type, local_types, value_types);
        }
        syn::Pat::Paren(paren) => {
            bind_option_pattern_type_id(&paren.pat, inner_type, local_types, value_types);
        }
        syn::Pat::Or(or_pat) => {
            for case in &or_pat.cases {
                bind_option_pattern_type_id(case, inner_type, local_types, value_types);
            }
        }
        syn::Pat::Type(typed) => {
            bind_option_pattern_type_id(&typed.pat, inner_type, local_types, value_types);
        }
        // sugar-audit: not-mine(option inner typing is only sound for Some-like destructuring)
        _ => {}
    }
}

fn bind_pattern_type_id_direct(
    pat: &syn::Pat,
    type_id: &TypeIdentity,
    local_types: &mut HashMap<String, String>,
    value_types: &mut HashMap<String, TypeIdentity>,
) {
    match pat {
        syn::Pat::Ident(ident) => {
            bind_value_type(
                &ident.ident.to_string(),
                type_id.clone(),
                local_types,
                value_types,
            );
            if let Some((_at, subpat)) = &ident.subpat {
                bind_pattern_type_id_direct(subpat, type_id, local_types, value_types);
            }
        }
        syn::Pat::Reference(reference) => {
            bind_pattern_type_id_direct(&reference.pat, type_id, local_types, value_types);
        }
        syn::Pat::Or(or_pat) => {
            for case in &or_pat.cases {
                bind_pattern_type_id_direct(case, type_id, local_types, value_types);
            }
        }
        syn::Pat::Paren(paren) => {
            bind_pattern_type_id_direct(&paren.pat, type_id, local_types, value_types);
        }
        syn::Pat::Type(typed) => {
            bind_pattern_type_id_direct(&typed.pat, type_id, local_types, value_types);
        }
        // sugar-audit: not-mine(direct type binding cannot assign field element types without a schema)
        _ => {}
    }
}

fn bind_value_type(
    name: &str,
    type_id: TypeIdentity,
    local_types: &mut HashMap<String, String>,
    value_types: &mut HashMap<String, TypeIdentity>,
) {
    local_types.insert(name.to_string(), type_id.krate.clone());
    value_types.insert(name.to_string(), type_id);
}

fn function_return_crates(
    file: &syn::File,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> HashMap<String, String> {
    let mut returns = HashMap::new();
    collect_function_return_crates_in_items(
        &file.items,
        use_map,
        local_type_names,
        current_crate,
        &mut returns,
    );
    returns
}

fn collect_function_return_crates_in_items(
    items: &[syn::Item],
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
    returns: &mut HashMap<String, String>,
) {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                if let Some(krate) = return_type_crate(
                    &item_fn.sig.output,
                    use_map,
                    local_type_names,
                    current_crate,
                ) {
                    returns.insert(item_fn.sig.ident.to_string(), krate);
                }
            }
            syn::Item::Impl(item_impl) => {
                for impl_item in &item_impl.items {
                    if let syn::ImplItem::Fn(method) = impl_item {
                        if let Some(krate) = return_type_crate(
                            &method.sig.output,
                            use_map,
                            local_type_names,
                            current_crate,
                        ) {
                            returns.insert(method.sig.ident.to_string(), krate);
                        }
                    }
                }
            }
            syn::Item::Mod(item_mod) => {
                if let Some((_, ref nested)) = item_mod.content {
                    collect_function_return_crates_in_items(
                        nested,
                        use_map,
                        local_type_names,
                        current_crate,
                        returns,
                    );
                }
            }
            // sugar-audit: not-mine(return-crate index only records functions, methods, and inline modules)
            _ => {}
        }
    }
}

fn return_type_crate(
    output: &syn::ReturnType,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<String> {
    let syn::ReturnType::Type(_, ty) = output else {
        return None;
    };
    type_crate_for(ty, use_map, local_type_names, current_crate)
}

/// Recursively collect every call expression in every function body inside
/// `file`. Each entry carries the bare callee leaf, the crate it resolves to
/// (via the file's `use` map / path qualification), and the source position.
fn collect_callsites_in_items(
    items: &[syn::Item],
    in_test_context: bool,
    rel_path: &str,
    use_map: &HashMap<String, String>,
    fn_return_crates: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    local_free_functions: &BTreeSet<String>,
    current_crate: &str,
    enum_variant_types: &EnumVariantTypeMap,
    struct_field_types: &StructFieldTypeMap,
    infallible_serialize: &InfallibleSerializeManifest,
    function_postconditions: &FunctionPostconditionsManifest,
    out: &mut Vec<CallSite>,
) {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                if in_test_context || is_rust_test_fn(item_fn) {
                    continue;
                }
                let param_type_map =
                    build_param_type_map(&item_fn.sig, use_map, local_type_names, current_crate);
                let param_names = build_param_name_set(&item_fn.sig);
                let caller_contract_name = item_fn.sig.ident.to_string();
                collect_callsites_in_block(
                    &item_fn.block,
                    rel_path,
                    use_map,
                    fn_return_crates,
                    local_type_names,
                    local_free_functions,
                    current_crate,
                    enum_variant_types,
                    struct_field_types,
                    infallible_serialize,
                    function_postconditions,
                    &param_type_map,
                    &param_names,
                    Some(caller_contract_name.as_str()),
                    out,
                );
            }
            syn::Item::Impl(item_impl) => {
                if in_test_context || attrs_include_cfg_test(&item_impl.attrs) {
                    continue;
                }
                for impl_item in &item_impl.items {
                    if let syn::ImplItem::Fn(method) = impl_item {
                        let item_fn = item_fn_from_impl_method(method);
                        if is_rust_test_fn(&item_fn) {
                            continue;
                        }
                        let param_type_map = build_param_type_map(
                            &method.sig,
                            use_map,
                            local_type_names,
                            current_crate,
                        );
                        let param_names = build_param_name_set(&method.sig);
                        let caller_contract_name = if is_liftable_impl_method(item_impl, method) {
                            impl_function_qualifier(item_impl)
                                .map(|qualifier| format!("{qualifier}::{}", method.sig.ident))
                        } else {
                            None
                        };
                        collect_callsites_in_block(
                            &method.block,
                            rel_path,
                            use_map,
                            fn_return_crates,
                            local_type_names,
                            local_free_functions,
                            current_crate,
                            enum_variant_types,
                            struct_field_types,
                            infallible_serialize,
                            function_postconditions,
                            &param_type_map,
                            &param_names,
                            caller_contract_name.as_deref(),
                            out,
                        );
                    }
                }
            }
            syn::Item::Mod(item_mod) => {
                if let Some((_, ref nested)) = item_mod.content {
                    let nested_test_context =
                        in_test_context || attrs_include_cfg_test(&item_mod.attrs);
                    collect_callsites_in_items(
                        nested,
                        nested_test_context,
                        rel_path,
                        use_map,
                        fn_return_crates,
                        local_type_names,
                        local_free_functions,
                        current_crate,
                        enum_variant_types,
                        struct_field_types,
                        infallible_serialize,
                        function_postconditions,
                        out,
                    );
                }
            }
            // sugar-audit: not-mine(callsite collection only descends through callable bodies and inline modules)
            _ => {}
        }
    }
}

fn lift_call_actual_term(expr: &syn::Expr) -> Option<Value> {
    let term = sugar_walk::lift::lift_expr_to_term(expr)?;
    match serde_json::to_value(term) {
        Ok(value) => Some(value),
        Err(err) => panic!("sugar-walk refused unserializable lifted call actual term: {err}"),
    }
}

fn stable_local_actual_term(term: &Value) -> bool {
    term.get("kind").and_then(Value::as_str) == Some("const")
}

fn collect_callsites_in_block(
    block: &syn::Block,
    rel_path: &str,
    use_map: &HashMap<String, String>,
    fn_return_crates: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    local_free_functions: &BTreeSet<String>,
    current_crate: &str,
    enum_variant_types: &EnumVariantTypeMap,
    struct_field_types: &StructFieldTypeMap,
    infallible_serialize: &InfallibleSerializeManifest,
    function_postconditions: &FunctionPostconditionsManifest,
    // Phase-2 Tier D-lib: param name -> concrete type identity for syntactic
    // serde_json arg-type disambiguation. Built from the enclosing function's
    // declared parameter types; empty when called outside a fn.
    param_type_map: &HashMap<String, TypeIdentity>,
    param_names: &BTreeSet<String>,
    caller_contract_name: Option<&str>,
    out: &mut Vec<CallSite>,
) {
    use syn::visit::Visit;
    struct V<'a> {
        rel_path: &'a str,
        use_map: &'a HashMap<String, String>,
        fn_return_crates: &'a HashMap<String, String>,
        local_type_names: &'a BTreeSet<String>,
        local_free_functions: &'a BTreeSet<String>,
        current_crate: &'a str,
        local_types: HashMap<String, String>,
        value_types: HashMap<String, TypeIdentity>,
        local_terms: HashMap<String, Value>,
        enum_variant_types: &'a EnumVariantTypeMap,
        struct_field_types: &'a StructFieldTypeMap,
        infallible_serialize: &'a InfallibleSerializeManifest,
        function_postconditions: &'a FunctionPostconditionsManifest,
        param_type_map: &'a HashMap<String, TypeIdentity>,
        param_names: &'a BTreeSet<String>,
        caller_contract_name: Option<String>,
        stability_block: &'a syn::Block,
        pure_free_guard_facts: Vec<PureFreeCallGuardFact>,
        out: &'a mut Vec<CallSite>,
    }
    impl<'a> V<'a> {
        fn value_type(&self, name: &str) -> Option<&TypeIdentity> {
            self.value_types
                .get(name)
                .or_else(|| self.param_type_map.get(name))
        }

        fn actual_term_for_expr(&self, expr: &syn::Expr) -> Option<Value> {
            if let Some(name) = expr_bare_ident_name(expr) {
                if let Some(term) = self.local_terms.get(&name) {
                    return Some(term.clone());
                }
            }
            lift_call_actual_term(expr)
        }

        fn stable_local_term_for_expr(&self, expr: &syn::Expr) -> Option<Value> {
            let term = self.actual_term_for_expr(expr)?;
            stable_local_actual_term(&term).then_some(term)
        }

        fn expr_type_identity(&self, expr: &syn::Expr) -> Option<TypeIdentity> {
            match expr {
                syn::Expr::Path(path) if path.path.segments.len() == 1 => path
                    .path
                    .segments
                    .first()
                    .and_then(|segment| self.value_type(&segment.ident.to_string()).cloned()),
                syn::Expr::Field(field) => {
                    let receiver = self.expr_type_identity(&field.base)?;
                    let field_name = match &field.member {
                        syn::Member::Named(ident) => ident.to_string(),
                        syn::Member::Unnamed(_) => return None,
                    };
                    self.struct_field_types
                        .fields
                        .get(&(receiver.krate, receiver.head, field_name))
                        .map(|field| field.type_id.clone())
                }
                syn::Expr::Reference(reference) => self.expr_type_identity(&reference.expr),
                syn::Expr::Paren(paren) => self.expr_type_identity(&paren.expr),
                syn::Expr::Group(group) => self.expr_type_identity(&group.expr),
                _ => None,
            }
        }

        fn expr_option_inner_type_identity(&self, expr: &syn::Expr) -> Option<TypeIdentity> {
            match expr {
                syn::Expr::Field(field) => {
                    let receiver = self.expr_type_identity(&field.base)?;
                    let field_name = match &field.member {
                        syn::Member::Named(ident) => ident.to_string(),
                        syn::Member::Unnamed(_) => return None,
                    };
                    self.struct_field_types
                        .fields
                        .get(&(receiver.krate, receiver.head, field_name))
                        .and_then(|field| field.option_inner.clone())
                }
                syn::Expr::Reference(reference) => {
                    self.expr_option_inner_type_identity(&reference.expr)
                }
                syn::Expr::Paren(paren) => self.expr_option_inner_type_identity(&paren.expr),
                syn::Expr::Group(group) => self.expr_option_inner_type_identity(&group.expr),
                _ => None,
            }
        }

        fn serde_json_panic_partial_for_receiver(
            &self,
            receiver: &syn::Expr,
            panic_leaf: &str,
        ) -> Option<(String, String)> {
            match receiver {
                syn::Expr::Call(call) => {
                    let (producer, producer_crate, _) =
                        call_expr_callee(&call.func, self.use_map, self.current_crate)?;
                    if !needs_arg_type_resolution(producer_crate.as_deref(), &producer) {
                        return None;
                    }
                    let arg = call.args.first()?;
                    let type_id = self.expr_type_identity(arg)?;
                    self.infallible_serialize
                        .contract_for(&producer, &type_id)?;
                    disambiguated_partial_leaf("result", panic_leaf)
                        .map(|leaf| ("std".to_string(), leaf))
                }
                syn::Expr::Paren(paren) => {
                    self.serde_json_panic_partial_for_receiver(&paren.expr, panic_leaf)
                }
                syn::Expr::Group(group) => {
                    self.serde_json_panic_partial_for_receiver(&group.expr, panic_leaf)
                }
                syn::Expr::Reference(reference) => {
                    self.serde_json_panic_partial_for_receiver(&reference.expr, panic_leaf)
                }
                _ => None,
            }
        }

        fn pure_free_guard_fact_for_is_some(
            &self,
            node: &syn::ExprMethodCall,
        ) -> Option<PureFreeCallGuardFact> {
            if node.method != "is_some" || !node.args.is_empty() {
                return None;
            }
            let call = expr_as_call(&node.receiver)?;
            let start = call.func.span().start();
            let rule = self.function_postconditions.rule_for_free_pure_call(
                &call.func,
                self.use_map,
                self.current_crate,
                self.rel_path,
                start.line,
                self.local_free_functions,
            )?;
            if rule.post_predicate != panic_freedom::IS_SOME {
                return None;
            }
            let args = call.args.iter().cloned().collect::<Vec<_>>();
            if !args.iter().all(pure_free_guard_arg_is_stable) {
                debug!(
                    callee = %rule.callee,
                    line = start.line,
                    "lift_implications: refusing manifest pure-free guard fact because an arg expression is not stable"
                );
                return None;
            }
            Some(PureFreeCallGuardFact {
                callee: rule.callee.clone(),
                arg_roots: expr_roots_for_args(&args),
                args,
                post_predicate: rule.post_predicate.clone(),
            })
        }

        fn collect_pure_free_guard_facts(
            &self,
            expr: &syn::Expr,
            facts: &mut Vec<PureFreeCallGuardFact>,
        ) {
            match expr {
                syn::Expr::Binary(binary) if matches!(binary.op, syn::BinOp::And(_)) => {
                    self.collect_pure_free_guard_facts(&binary.left, facts);
                    self.collect_pure_free_guard_facts(&binary.right, facts);
                }
                syn::Expr::MethodCall(method) => {
                    if let Some(fact) = self.pure_free_guard_fact_for_is_some(method) {
                        facts.push(fact);
                    }
                }
                syn::Expr::Paren(paren) => self.collect_pure_free_guard_facts(&paren.expr, facts),
                syn::Expr::Group(group) => self.collect_pure_free_guard_facts(&group.expr, facts),
                // sugar-audit: not-mine(pure-free guard facts are only && chains of is_some method calls)
                _ => {}
            }
        }

        fn pure_free_guarded_panic_partial_for_receiver(
            &self,
            receiver: &syn::Expr,
            panic_leaf: &str,
        ) -> Option<(String, String)> {
            let call = expr_as_call(receiver)?;
            let (callee, callee_crate, _) =
                call_expr_callee(&call.func, self.use_map, self.current_crate)?;
            let resolved_crate = callee_crate.unwrap_or_else(|| self.current_crate.to_string());
            if resolved_crate != self.current_crate
                || !self.local_free_functions.contains(&callee)
                || self
                    .function_postconditions
                    .rule_for_free_pure_call(
                        &call.func,
                        self.use_map,
                        self.current_crate,
                        self.rel_path,
                        call.func.span().start().line,
                        self.local_free_functions,
                    )
                    .is_none()
            {
                return None;
            }
            let args = call.args.iter().cloned().collect::<Vec<_>>();
            if !args.iter().all(pure_free_guard_arg_is_stable) {
                debug!(
                    callee = %callee,
                    "lift_implications: refusing manifest pure-free panic partial because receiver args are not stable"
                );
                return None;
            }
            let fact = self
                .pure_free_guard_facts
                .iter()
                .rev()
                .find(|fact| fact.callee == callee && expr_vecs_ast_equal(&fact.args, &args))?;
            let stem = panic_stem_for_post_predicate(&fact.post_predicate)?;
            disambiguated_partial_leaf(stem, panic_leaf).map(|leaf| ("std".to_string(), leaf))
        }

        fn invalidate_pure_free_guard_facts_for_roots(&mut self, roots: &BTreeSet<String>) {
            if roots.is_empty() {
                return;
            }
            self.pure_free_guard_facts
                .retain(|fact| fact.arg_roots.is_disjoint(roots));
            for root in roots {
                self.local_terms.remove(root);
            }
        }

        fn invalidate_pure_free_guard_facts_for_expr_effects(&mut self, expr: &syn::Expr) {
            let roots = pure_free_guard_expr_effect_roots(expr);
            self.invalidate_pure_free_guard_facts_for_roots(&roots);
        }

        fn invalidate_pure_free_guard_facts_for_pat(&mut self, pat: &syn::Pat) {
            let roots = pat_bound_idents(pat);
            self.invalidate_pure_free_guard_facts_for_roots(&roots);
        }
    }
    impl<'ast, 'a> Visit<'ast> for V<'a> {
        // Let-binding inference mutates these maps while traversing a block.
        // Bracket block traversal so nested blocks, if/loop bodies, and
        // closures cannot leak inferred bindings into later outer callsites.
        // Match/if-let pattern binders keep their narrower save/restore below.
        fn visit_block(&mut self, node: &'ast syn::Block) {
            let saved_local_types = self.local_types.clone();
            let saved_value_types = self.value_types.clone();
            let saved_local_terms = self.local_terms.clone();
            syn::visit::visit_block(self, node);
            self.local_types = saved_local_types;
            self.value_types = saved_value_types;
            self.local_terms = saved_local_terms;
        }

        fn visit_expr_call(&mut self, node: &'ast syn::ExprCall) {
            if let Some((callee, callee_crate, contract_callee)) =
                call_expr_callee(&node.func, self.use_map, self.current_crate)
            {
                let start = node.func.span().start();
                // Phase-2 Tier D-lib: syntactic arg-type disambiguation for
                // serde_json::{to_value,to_string,to_string_pretty}. The
                // manifest is per-crate Rust-kit config; the CLI/verifier never
                // read it. Concrete type identity must be available from a
                // conservative source position, otherwise we refuse to guess.
                let disambiguated_target =
                    if needs_arg_type_resolution(callee_crate.as_deref(), &callee) {
                        node.args.first().and_then(|a| {
                            let type_id = self.expr_type_identity(a)?;
                            disambiguated_serde_json_totality_target(
                                &callee,
                                &type_id,
                                self.infallible_serialize,
                                self.current_crate,
                            )
                        })
                    } else {
                        None
                    };
                let disambiguated_target = disambiguated_target.or_else(|| {
                    self.function_postconditions.target_for_associated_call(
                        &node.func,
                        &node.args,
                        self.current_crate,
                        self.rel_path,
                        start.line,
                    )
                });
                self.out.push(CallSite {
                    callee,
                    contract_callee,
                    callee_crate,
                    is_method: false,
                    disambiguated_callee: disambiguated_target
                        .as_ref()
                        .map(|(_, leaf)| leaf.clone()),
                    disambiguated_crate: disambiguated_target.map(|(krate, _)| krate),
                    unsupported_reason: None,
                    actual_terms: node
                        .args
                        .iter()
                        .map(|arg| self.actual_term_for_expr(arg))
                        .collect::<Option<Vec<_>>>(),
                    caller_contract_name: self.caller_contract_name.clone(),
                    file: self.rel_path.to_string(),
                    line: start.line,
                    col: start.column,
                });
            } else if is_closure_expr(&node.func) {
                let start = node.func.span().start();
                self.out.push(CallSite {
                    callee: "<closure>".to_string(),
                    contract_callee: "<closure>".to_string(),
                    callee_crate: None,
                    is_method: false,
                    disambiguated_callee: None,
                    disambiguated_crate: None,
                    unsupported_reason: Some("unsupported-closure-invocation"),
                    actual_terms: None,
                    caller_contract_name: self.caller_contract_name.clone(),
                    file: self.rel_path.to_string(),
                    line: start.line,
                    col: start.column,
                });
            } else {
                let start = node.func.span().start();
                self.out.push(CallSite {
                    callee: "<dynamic>".to_string(),
                    contract_callee: "<dynamic>".to_string(),
                    callee_crate: None,
                    is_method: false,
                    disambiguated_callee: None,
                    disambiguated_crate: None,
                    unsupported_reason: Some("unsupported-dynamic-callee"),
                    actual_terms: None,
                    caller_contract_name: self.caller_contract_name.clone(),
                    file: self.rel_path.to_string(),
                    line: start.line,
                    col: start.column,
                });
            }
            syn::visit::visit_expr_call(self, node);
            self.invalidate_pure_free_guard_facts_for_expr_effects(&syn::Expr::Call(node.clone()));
        }
        fn visit_expr_macro(&mut self, node: &'ast syn::ExprMacro) {
            self.out.push(unsupported_macro_callsite(
                &node.mac,
                self.rel_path,
                self.caller_contract_name.as_deref(),
            ));
            syn::visit::visit_expr_macro(self, node);
        }
        fn visit_stmt_macro(&mut self, node: &'ast syn::StmtMacro) {
            self.out.push(unsupported_macro_callsite(
                &node.mac,
                self.rel_path,
                self.caller_contract_name.as_deref(),
            ));
            syn::visit::visit_stmt_macro(self, node);
        }
        fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
            let callee = node.method.to_string();
            let contract_callee = callee_with_angle_args(&callee, node.turbofish.as_ref());
            let start = node.method.span().start();
            let syntactic_panic_target = expr_bare_ident_name(&node.receiver)
                .and_then(|name| self.value_type(&name).cloned())
                .and_then(|type_id| {
                    if type_id.krate != "std" {
                        return None;
                    }
                    let stem = type_id.head.to_ascii_lowercase();
                    disambiguated_partial_leaf(&stem, &callee).map(|leaf| ("std".to_string(), leaf))
                });
            let manifest_panic_target = syntactic_panic_target
                .as_ref()
                .is_none()
                .then(|| {
                    if is_panic_leaf(&callee) {
                        self.pure_free_guarded_panic_partial_for_receiver(&node.receiver, &callee)
                            .or_else(|| {
                                self.serde_json_panic_partial_for_receiver(&node.receiver, &callee)
                            })
                            .or_else(|| {
                                self.function_postconditions.panic_partial_for_receiver(
                                    &node.receiver,
                                    self.current_crate,
                                    self.rel_path,
                                    &callee,
                                    self.stability_block,
                                    self.param_names,
                                )
                            })
                    } else {
                        None
                    }
                })
                .flatten();
            let callee_crate = syntactic_panic_target
                .as_ref()
                .map(|(krate, _)| krate.clone())
                .or_else(|| {
                    receiver_crate_for_expr(
                        &node.receiver,
                        &self.local_types,
                        self.use_map,
                        self.fn_return_crates,
                        self.local_type_names,
                        self.current_crate,
                    )
                });
            let function_postcondition_target = syntactic_panic_target
                .as_ref()
                .is_none()
                .then(|| {
                    self.function_postconditions.target_for_method_call(
                        node,
                        self.current_crate,
                        self.rel_path,
                        start.line,
                        self.stability_block,
                        self.param_names,
                    )
                })
                .flatten();
            let actual_terms = self
                .actual_term_for_expr(&node.receiver)
                .and_then(|receiver| {
                    let mut actuals = vec![receiver];
                    for arg in &node.args {
                        actuals.push(self.actual_term_for_expr(arg)?);
                    }
                    Some(actuals)
                });
            self.out.push(CallSite {
                callee,
                contract_callee,
                callee_crate,
                is_method: true,
                disambiguated_callee: syntactic_panic_target
                    .as_ref()
                    .map(|(_, leaf)| leaf.clone())
                    .or_else(|| manifest_panic_target.as_ref().map(|(_, leaf)| leaf.clone()))
                    .or_else(|| {
                        function_postcondition_target
                            .as_ref()
                            .map(|(_, leaf)| leaf.clone())
                    }),
                disambiguated_crate: syntactic_panic_target
                    .map(|(krate, _)| krate)
                    .or_else(|| manifest_panic_target.map(|(krate, _)| krate))
                    .or_else(|| function_postcondition_target.map(|(krate, _)| krate)),
                unsupported_reason: None,
                actual_terms,
                caller_contract_name: self.caller_contract_name.clone(),
                file: self.rel_path.to_string(),
                line: start.line,
                col: start.column,
            });
            syn::visit::visit_expr_method_call(self, node);
            self.invalidate_pure_free_guard_facts_for_expr_effects(&syn::Expr::MethodCall(
                node.clone(),
            ));
        }
        fn visit_expr_match(&mut self, node: &'ast syn::ExprMatch) {
            self.visit_expr(&node.expr);
            let scrutinee_type = self.expr_type_identity(&node.expr);
            let option_inner_type = self.expr_option_inner_type_identity(&node.expr);
            for arm in &node.arms {
                let saved_local_types = self.local_types.clone();
                let saved_value_types = self.value_types.clone();
                let saved_local_terms = self.local_terms.clone();
                if let Some(inner_type) = option_inner_type.as_ref() {
                    bind_option_pattern_type_id(
                        &arm.pat,
                        inner_type,
                        &mut self.local_types,
                        &mut self.value_types,
                    );
                } else if let Some(type_id) = scrutinee_type.as_ref() {
                    bind_pattern_type_id(
                        &arm.pat,
                        type_id,
                        self.enum_variant_types,
                        &mut self.local_types,
                        &mut self.value_types,
                    );
                }
                if let Some((_if_token, guard)) = &arm.guard {
                    self.visit_expr(guard);
                }
                self.visit_expr(&arm.body);
                self.local_types = saved_local_types;
                self.value_types = saved_value_types;
                self.local_terms = saved_local_terms;
            }
        }
        fn visit_expr_if(&mut self, node: &'ast syn::ExprIf) {
            if let syn::Expr::Let(expr_let) = &*node.cond {
                self.visit_expr(&expr_let.expr);
                let saved_local_types = self.local_types.clone();
                let saved_value_types = self.value_types.clone();
                let saved_local_terms = self.local_terms.clone();
                if let Some(inner_type) = self.expr_option_inner_type_identity(&expr_let.expr) {
                    bind_option_pattern_type_id(
                        &expr_let.pat,
                        &inner_type,
                        &mut self.local_types,
                        &mut self.value_types,
                    );
                }
                self.visit_block(&node.then_branch);
                self.local_types = saved_local_types;
                self.value_types = saved_value_types;
                self.local_terms = saved_local_terms;
                if let Some((_else_token, else_branch)) = &node.else_branch {
                    self.visit_expr(else_branch);
                }
                return;
            }

            self.visit_expr(&node.cond);
            let saved_guard_facts = self.pure_free_guard_facts.clone();
            let mut guard_facts = Vec::new();
            if pure_free_guard_expr_effect_roots(&node.cond).is_empty() {
                self.collect_pure_free_guard_facts(&node.cond, &mut guard_facts);
            } else {
                debug!(
                    "lift_implications: refusing manifest pure-free guard facts from mutating if condition"
                );
            }
            self.pure_free_guard_facts.extend(guard_facts);
            self.visit_block(&node.then_branch);
            self.pure_free_guard_facts = saved_guard_facts;
            if let Some((_else_token, else_branch)) = &node.else_branch {
                self.visit_expr(else_branch);
            }
        }
        fn visit_expr_index(&mut self, node: &'ast syn::ExprIndex) {
            // `v[i]` is a PANIC site: indexing out of bounds panics. The term
            // lift represents it as `Ctor("index", [v, i])`, so the call leaf is
            // `index` (matching that ctor name as the bridge sourceSymbol). The
            // rust-std shim publishes no index-bounds partial yet, so this
            // resolves to no contract and is reported as an HONEST unproven
            // panic-site (refuse-floor), making `v[i]` visible in the
            // panic-freedom census instead of silently absent. The locus points
            // at the indexed expression start (`v` in `v[i]`), where the term's
            // arg0 (the receiver the bounds obligation is about) lives.
            let start = node.expr.span().start();
            self.out.push(CallSite {
                callee: "index".to_string(),
                contract_callee: "index".to_string(),
                // Receiver-defining crate is not syntactically known; the index
                // op itself is std. Leave None so it is treated like a method
                // call for the matcher's current-crate fallback / lift-gap.
                callee_crate: None,
                is_method: false,
                disambiguated_callee: None,
                disambiguated_crate: None,
                unsupported_reason: None,
                actual_terms: None,
                caller_contract_name: self.caller_contract_name.clone(),
                file: self.rel_path.to_string(),
                line: start.line,
                col: start.column,
            });
            syn::visit::visit_expr_index(self, node);
        }
        fn visit_expr_assign(&mut self, node: &'ast syn::ExprAssign) {
            syn::visit::visit_expr_assign(self, node);
            let roots = expr_assignment_roots(&node.left);
            self.invalidate_pure_free_guard_facts_for_roots(&roots);
        }
        fn visit_expr_binary(&mut self, node: &'ast syn::ExprBinary) {
            syn::visit::visit_expr_binary(self, node);
            if binop_is_assignment(&node.op) {
                let roots = expr_assignment_roots(&node.left);
                self.invalidate_pure_free_guard_facts_for_roots(&roots);
            }
        }
        fn visit_local(&mut self, node: &'ast syn::Local) {
            let explicit_type = pat_type_identity(
                &node.pat,
                self.use_map,
                self.local_type_names,
                self.current_crate,
            );
            let mut inferred_type = None;
            let inferred_crate = node.init.as_ref().and_then(|init| {
                self.visit_expr(&init.expr);
                inferred_type = expr_constructed_type_identity(
                    &init.expr,
                    self.use_map,
                    self.local_type_names,
                    self.current_crate,
                );
                inferred_type
                    .as_ref()
                    .map(|type_id| type_id.krate.clone())
                    .or_else(|| {
                        expr_return_crate(
                            &init.expr,
                            self.use_map,
                            self.fn_return_crates,
                            self.local_type_names,
                            self.current_crate,
                        )
                    })
            });
            let local_term = node
                .init
                .as_ref()
                .and_then(|init| self.stable_local_term_for_expr(&init.expr));
            self.invalidate_pure_free_guard_facts_for_pat(&node.pat);
            for name in pat_bound_idents(&node.pat) {
                self.local_terms.remove(&name);
            }
            let local_type = explicit_type.clone().or(inferred_type);
            if let (Some(name), Some(krate)) = (
                pat_ident_name(&node.pat),
                local_type
                    .as_ref()
                    .map(|type_id| type_id.krate.clone())
                    .or(inferred_crate),
            ) {
                self.local_types.insert(name.clone(), krate);
            }
            if let (Some(name), Some(type_id)) = (pat_ident_name(&node.pat), local_type) {
                self.value_types.insert(name, type_id);
            }
            if let (Some(name), Some(term)) = (pat_immutable_ident_name(&node.pat), local_term) {
                self.local_terms.insert(name, term);
            }
        }
    }
    let mut v = V {
        rel_path,
        use_map,
        fn_return_crates,
        local_type_names,
        local_free_functions,
        current_crate,
        local_types: param_type_map
            .iter()
            .map(|(name, type_id)| (name.clone(), type_id.krate.clone()))
            .collect(),
        value_types: param_type_map.clone(),
        local_terms: HashMap::new(),
        enum_variant_types,
        struct_field_types,
        infallible_serialize,
        function_postconditions,
        param_type_map,
        param_names,
        caller_contract_name: caller_contract_name.map(str::to_string),
        stability_block: block,
        pure_free_guard_facts: Vec::new(),
        out,
    };
    v.visit_block(block);
}

fn unsupported_macro_callsite(
    mac: &syn::Macro,
    rel_path: &str,
    caller_contract_name: Option<&str>,
) -> CallSite {
    let callee = mac
        .path
        .segments
        .last()
        .map(|seg| format!("{}!", seg.ident))
        .unwrap_or_else(|| "<macro>!".to_string());
    let start = mac.path.span().start();
    CallSite {
        callee,
        contract_callee: mac
            .path
            .segments
            .last()
            .map(path_segment_contract_leaf)
            .map(|leaf| format!("{leaf}!"))
            .unwrap_or_else(|| "<macro>!".to_string()),
        callee_crate: None,
        is_method: false,
        disambiguated_callee: None,
        disambiguated_crate: None,
        unsupported_reason: Some("unsupported-macro-callsite"),
        actual_terms: None,
        caller_contract_name: caller_contract_name.map(str::to_string),
        file: rel_path.to_string(),
        line: start.line,
        col: start.column,
    }
}

fn path_segment_contract_leaf(segment: &syn::PathSegment) -> String {
    callee_with_path_args(&segment.ident.to_string(), &segment.arguments)
}

fn callee_with_path_args(leaf: &str, args: &syn::PathArguments) -> String {
    match args {
        syn::PathArguments::AngleBracketed(angle_args) => {
            callee_with_angle_args(leaf, Some(angle_args))
        }
        _ => leaf.to_string(),
    }
}

fn callee_with_angle_args(
    leaf: &str,
    args: Option<&syn::AngleBracketedGenericArguments>,
) -> String {
    let Some(args) = args else {
        return leaf.to_string();
    };
    if args.args.is_empty() {
        return leaf.to_string();
    }
    let rendered_args = args
        .args
        .iter()
        .map(|arg| {
            arg.to_token_stream()
                .to_string()
                .chars()
                .filter(|ch| !ch.is_whitespace())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join(",");
    format!("{leaf}::<{rendered_args}>")
}

fn is_closure_expr(expr: &syn::Expr) -> bool {
    match expr {
        syn::Expr::Closure(_) => true,
        syn::Expr::Paren(paren) => is_closure_expr(&paren.expr),
        syn::Expr::Group(group) => is_closure_expr(&group.expr),
        _ => false,
    }
}

fn pat_ident_name(pat: &syn::Pat) -> Option<String> {
    match pat {
        syn::Pat::Ident(ident) => Some(ident.ident.to_string()),
        syn::Pat::Type(pat_type) => pat_ident_name(&pat_type.pat),
        _ => None,
    }
}

fn pat_immutable_ident_name(pat: &syn::Pat) -> Option<String> {
    match pat {
        syn::Pat::Ident(ident) if ident.mutability.is_none() && ident.subpat.is_none() => {
            Some(ident.ident.to_string())
        }
        syn::Pat::Type(pat_type) => pat_immutable_ident_name(&pat_type.pat),
        _ => None,
    }
}

fn pat_type_identity(
    pat: &syn::Pat,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<TypeIdentity> {
    match pat {
        syn::Pat::Type(pat_type) => type_identity_for(
            strip_reference_type(&pat_type.ty),
            use_map,
            local_type_names,
            current_crate,
        ),
        _ => None,
    }
}

fn receiver_crate_for_expr(
    expr: &syn::Expr,
    local_types: &HashMap<String, String>,
    use_map: &HashMap<String, String>,
    fn_return_crates: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<String> {
    match expr {
        syn::Expr::Path(path) if path.path.segments.len() == 1 => path
            .path
            .segments
            .first()
            .and_then(|seg| local_types.get(&seg.ident.to_string()).cloned()),
        syn::Expr::Paren(paren) => receiver_crate_for_expr(
            &paren.expr,
            local_types,
            use_map,
            fn_return_crates,
            local_type_names,
            current_crate,
        ),
        _ => expr_return_crate(
            expr,
            use_map,
            fn_return_crates,
            local_type_names,
            current_crate,
        ),
    }
}

fn expr_return_crate(
    expr: &syn::Expr,
    use_map: &HashMap<String, String>,
    fn_return_crates: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<String> {
    match expr {
        syn::Expr::Call(call) => {
            if let Some(krate) =
                associated_type_crate_for_call(&call.func, use_map, local_type_names, current_crate)
            {
                return Some(krate);
            }
            let (leaf, _, _) = call_expr_callee(&call.func, use_map, current_crate)?;
            fn_return_crates.get(&leaf).cloned()
        }
        syn::Expr::Paren(paren) => expr_return_crate(
            &paren.expr,
            use_map,
            fn_return_crates,
            local_type_names,
            current_crate,
        ),
        _ => None,
    }
}

fn associated_type_crate_for_call(
    func: &syn::Expr,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<String> {
    let syn::Expr::Path(path) = func else {
        return None;
    };
    if path.path.segments.len() < 2 {
        return None;
    }
    let root = path.path.segments.first()?.ident.to_string();
    use_map
        .get(&root)
        .map(|mapped| resolve_path_root_crate(mapped, use_map, current_crate))
        .or_else(|| {
            if !current_crate.is_empty() && local_type_names.contains(&root) {
                Some(current_crate.to_string())
            } else {
                None
            }
        })
}

/// Extract the callee leaf AND its resolved crate from an `Expr::Call`'s
/// `func`. The leaf is the last path segment (the natural ctor name the
/// contract lifters use); the crate is recovered as follows:
///   - a multi-segment path `a::b::fn` is rooted at `a` (an extern crate),
///     unless `a` is `crate`/`self`/`super`, in which case it is the current
///     crate;
///   - a single-segment path `fn` is looked up in the file `use` map; a hit
///     gives its crate root, a miss defaults to the current crate.
/// Returns None for callees that are not simple paths (closures, macro
/// expansions, dynamic dispatch).
fn call_expr_callee(
    expr: &syn::Expr,
    use_map: &HashMap<String, String>,
    current_crate: &str,
) -> Option<(String, Option<String>, String)> {
    match expr {
        syn::Expr::Path(p) => {
            let segs: Vec<String> = p
                .path
                .segments
                .iter()
                .map(|s| s.ident.to_string())
                .collect();
            let leaf_segment = p.path.segments.last()?;
            let leaf = leaf_segment.ident.to_string();
            let contract_leaf = path_segment_contract_leaf(leaf_segment);
            let krate = if segs.len() >= 2 {
                let root = &segs[0];
                Some(resolve_path_root_crate(root, use_map, current_crate))
            } else {
                // Bare call: resolve via the file's `use` map.
                use_map.get(&leaf).map(|r| {
                    if r == "crate" {
                        current_crate.to_string()
                    } else {
                        normalize_crate_root(r)
                    }
                })
            };
            Some((leaf, krate, contract_leaf))
        }
        syn::Expr::Paren(p) => call_expr_callee(&p.expr, use_map, current_crate),
        _ => None,
    }
}

fn associated_call_path_and_leaf(expr: &syn::Expr) -> Option<(String, String)> {
    let syn::Expr::Path(path) = expr else {
        return None;
    };
    if path.path.segments.len() < 2 {
        return None;
    }
    let callee = path.path.segments.last()?.ident.to_string();
    let type_path = path
        .path
        .segments
        .iter()
        .take(path.path.segments.len() - 1)
        .map(|seg| seg.ident.to_string())
        .collect::<Vec<_>>()
        .join("::");
    Some((type_path, callee))
}

fn only_call_arg<T, P>(args: &syn::punctuated::Punctuated<T, P>) -> Option<&T> {
    if args.len() == 1 {
        args.first()
    } else {
        None
    }
}

fn expr_as_call(expr: &syn::Expr) -> Option<&syn::ExprCall> {
    match expr {
        syn::Expr::Call(call) => Some(call),
        syn::Expr::Paren(paren) => expr_as_call(&paren.expr),
        syn::Expr::Group(group) => expr_as_call(&group.expr),
        _ => None,
    }
}

fn expr_vecs_ast_equal(left: &[syn::Expr], right: &[syn::Expr]) -> bool {
    left.len() == right.len() && left.iter().zip(right).all(|(left, right)| left == right)
}

fn expr_roots_for_args(args: &[syn::Expr]) -> BTreeSet<String> {
    let mut roots = BTreeSet::new();
    for arg in args {
        collect_expr_roots(arg, &mut roots);
    }
    roots
}

fn collect_expr_roots(expr: &syn::Expr, roots: &mut BTreeSet<String>) {
    match expr {
        syn::Expr::Path(path) if path.path.segments.len() == 1 => {
            if let Some(segment) = path.path.segments.first() {
                roots.insert(segment.ident.to_string());
            }
        }
        syn::Expr::Array(array) => {
            for elem in &array.elems {
                collect_expr_roots(elem, roots);
            }
        }
        syn::Expr::Binary(binary) => {
            collect_expr_roots(&binary.left, roots);
            collect_expr_roots(&binary.right, roots);
        }
        syn::Expr::Call(call) => {
            collect_expr_roots(&call.func, roots);
            for arg in &call.args {
                collect_expr_roots(arg, roots);
            }
        }
        syn::Expr::Cast(cast) => collect_expr_roots(&cast.expr, roots),
        syn::Expr::Field(field) => collect_expr_roots(&field.base, roots),
        syn::Expr::Group(group) => collect_expr_roots(&group.expr, roots),
        syn::Expr::Index(index) => {
            collect_expr_roots(&index.expr, roots);
            collect_expr_roots(&index.index, roots);
        }
        syn::Expr::MethodCall(method) => {
            collect_expr_roots(&method.receiver, roots);
            for arg in &method.args {
                collect_expr_roots(arg, roots);
            }
        }
        syn::Expr::Paren(paren) => collect_expr_roots(&paren.expr, roots),
        syn::Expr::Reference(reference) => collect_expr_roots(&reference.expr, roots),
        syn::Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_expr_roots(elem, roots);
            }
        }
        syn::Expr::Unary(unary) => collect_expr_roots(&unary.expr, roots),
        // sugar-audit: not-mine(root extraction tracks pure expression containers that can feed stable guard args)
        _ => {}
    }
}

fn expr_assignment_roots(expr: &syn::Expr) -> BTreeSet<String> {
    let mut roots = BTreeSet::new();
    collect_assignment_roots(expr, &mut roots);
    roots
}

fn collect_assignment_roots(expr: &syn::Expr, roots: &mut BTreeSet<String>) {
    match expr {
        syn::Expr::Path(path) if path.path.segments.len() == 1 => {
            if let Some(segment) = path.path.segments.first() {
                roots.insert(segment.ident.to_string());
            }
        }
        syn::Expr::Field(field) => collect_assignment_roots(&field.base, roots),
        syn::Expr::Group(group) => collect_assignment_roots(&group.expr, roots),
        syn::Expr::Index(index) => collect_assignment_roots(&index.expr, roots),
        syn::Expr::Paren(paren) => collect_assignment_roots(&paren.expr, roots),
        syn::Expr::Reference(reference) => collect_assignment_roots(&reference.expr, roots),
        // sugar-audit: not-mine(assignment roots only exist on assignable path-field-index projections)
        _ => {}
    }
}

fn binop_is_assignment(op: &syn::BinOp) -> bool {
    matches!(
        op,
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
    )
}

fn pat_bound_idents(pat: &syn::Pat) -> BTreeSet<String> {
    let mut roots = BTreeSet::new();
    collect_pat_bound_idents(pat, &mut roots);
    roots
}

fn collect_pat_bound_idents(pat: &syn::Pat, roots: &mut BTreeSet<String>) {
    match pat {
        syn::Pat::Ident(ident) => {
            roots.insert(ident.ident.to_string());
        }
        syn::Pat::Or(or) => {
            for case in &or.cases {
                collect_pat_bound_idents(case, roots);
            }
        }
        syn::Pat::Paren(paren) => collect_pat_bound_idents(&paren.pat, roots),
        syn::Pat::Reference(reference) => collect_pat_bound_idents(&reference.pat, roots),
        syn::Pat::Slice(slice) => {
            for elem in &slice.elems {
                collect_pat_bound_idents(elem, roots);
            }
        }
        syn::Pat::Struct(strukt) => {
            for field in &strukt.fields {
                collect_pat_bound_idents(&field.pat, roots);
            }
        }
        syn::Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_pat_bound_idents(elem, roots);
            }
        }
        syn::Pat::TupleStruct(tuple) => {
            for elem in &tuple.elems {
                collect_pat_bound_idents(elem, roots);
            }
        }
        syn::Pat::Type(typed) => collect_pat_bound_idents(&typed.pat, roots),
        // sugar-audit: not-mine(non-binding pattern forms do not introduce local roots)
        _ => {}
    }
}

fn expr_path_text(expr: &syn::Expr) -> Option<String> {
    match expr {
        syn::Expr::Path(path) => Some(
            path.path
                .segments
                .iter()
                .map(|seg| seg.ident.to_string())
                .collect::<Vec<_>>()
                .join("::"),
        ),
        syn::Expr::Reference(reference) => expr_path_text(&reference.expr),
        syn::Expr::Paren(paren) => expr_path_text(&paren.expr),
        syn::Expr::Group(group) => expr_path_text(&group.expr),
        _ => None,
    }
}

fn expr_matches_format_repeat(
    expr: &syn::Expr,
    format_literal: &str,
    repeat_literal: &str,
    repeat_count: u64,
) -> bool {
    use syn::parse::Parser;

    let syn::Expr::Macro(expr_macro) = expr else {
        return false;
    };
    let Some(macro_tail) = expr_macro.mac.path.segments.last() else {
        return false;
    };
    if macro_tail.ident != "format" {
        return false;
    }
    let parser = syn::punctuated::Punctuated::<syn::Expr, syn::Token![,]>::parse_terminated;
    let Ok(args) = parser.parse2(expr_macro.mac.tokens.clone()) else {
        return false;
    };
    if args.len() != 2 {
        return false;
    }
    let Some(syn::Expr::Lit(format_arg)) = args.first() else {
        return false;
    };
    let syn::Lit::Str(format_str) = &format_arg.lit else {
        return false;
    };
    if format_str.value() != format_literal {
        return false;
    }
    let Some(syn::Expr::MethodCall(repeat_call)) = args.iter().nth(1) else {
        return false;
    };
    if repeat_call.method != "repeat" || repeat_call.args.len() != 1 {
        return false;
    }
    let syn::Expr::Lit(receiver) = repeat_call.receiver.as_ref() else {
        return false;
    };
    let syn::Lit::Str(receiver_str) = &receiver.lit else {
        return false;
    };
    if receiver_str.value() != repeat_literal {
        return false;
    }
    let Some(syn::Expr::Lit(count_arg)) = repeat_call.args.first() else {
        return false;
    };
    let syn::Lit::Int(count_int) = &count_arg.lit else {
        return false;
    };
    match count_int.base10_parse::<u64>() {
        Ok(count) => count == repeat_count,
        Err(_) => false,
    }
}

/// Crate roots in source use `_`-free hyphenless identifiers; a Cargo package
/// `sugar-cli` is referenced in code as `sugar_cli`. Normalize to the
/// underscore form so call-site roots and the Cargo-derived current crate name
/// compare equal.
fn normalize_crate_root(root: &str) -> String {
    root.replace('-', "_")
}

/// Read the `[package].name` of the crate rooted at `dir` (its `Cargo.toml`),
/// normalized to the underscore identifier form used in source. Returns None
/// when there is no readable package manifest.
fn crate_name_for(dir: &Path) -> Option<String> {
    // Line-scan the manifest rather than pull in a TOML parser: we only need
    // `[package].name`. Robust to the standard `name = "..."` form.
    // sugar-audit: default-ok(crate root probing treats an unreadable Cargo.toml as absence, not proof evidence)
    let manifest = std::fs::read_to_string(dir.join("Cargo.toml")).ok()?;
    let mut in_package = false;
    for line in manifest.lines() {
        let t = line.trim();
        if t.starts_with('[') {
            in_package = t == "[package]";
            continue;
        }
        if in_package {
            if let Some(rest) = t.strip_prefix("name") {
                if let Some(rest) = rest.trim_start().strip_prefix('=') {
                    let v = rest.trim().trim_matches('"').trim_matches('\'');
                    if !v.is_empty() {
                        return Some(normalize_crate_root(v));
                    }
                }
            }
        }
    }
    None
}

/// Read the RAW `[package].name` of the crate rooted at `dir` (its
/// `Cargo.toml`), WITHOUT the `-`→`_` normalization `crate_name_for` applies.
///
/// The derived `library-sugar-binding-entry` stamps this as its
/// `target_library_tag`, and the materialize verb matches a boundary stub by
/// `(target_library_tag, source_function_name) == (library, call)` with a RAW
/// `==` (no normalization on either side). The consumer's
/// `#[sugar::boundary(library = "rust-boundary-vendor", ...)]` carries the
/// crate name verbatim (hyphens intact), so the tag we derive must too, or the
/// match silently misses. (The DERIVED symbol the verb synthesizes is
/// `format!("{library}.{call}")` — `rust-boundary-vendor.reverse_chars` — built
/// from the boundary attr, not from this entry, so the separator is the verb's
/// concern, not ours.)
fn crate_name_raw_for(dir: &Path) -> Option<String> {
    // sugar-audit: default-ok(raw crate tag probing treats an unreadable Cargo.toml as absence, not proof evidence)
    let manifest = std::fs::read_to_string(dir.join("Cargo.toml")).ok()?;
    let mut in_package = false;
    for line in manifest.lines() {
        let t = line.trim();
        if t.starts_with('[') {
            in_package = t == "[package]";
            continue;
        }
        if in_package {
            if let Some(rest) = t.strip_prefix("name") {
                if let Some(rest) = rest.trim_start().strip_prefix('=') {
                    let v = rest.trim().trim_matches('"').trim_matches('\'');
                    if !v.is_empty() {
                        return Some(v.to_string());
                    }
                }
            }
        }
    }
    None
}

/// JSON-RPC handler for `sugar.plugin.lift_implications`.
///
/// Request params:
///   {
///     "workspace_root": "/abs/path",
///     "source_paths":   ["src/lib.rs", "src/cmd_mint.rs", ...],
///     "contract_bindings": [
///       { "name": "<callee>@<file>:<line>:<col>", "contract_cid": "blake3-512:..." },
///       ...
///     ]
///   }
///
/// Response (PEP 1.7.0 `kind = "ir-document"`):
///   {
///     "kind": "ir-document",
///     "ir":   [ <bridge memento>, ... ],
///     "diagnostics": [ <lift-gap>, ... ]
///   }
///
/// Each `bridge` memento pins exactly one call site to exactly one
/// contract. Call sites that find no matching binding emit a `lift-gap`
/// diagnostic and skip the bridge — substrate-honesty over silently
/// producing the wrong edge.
///
/// Map a `(receiver_type_stem, bare_method_leaf)` to the rust-std shim's
/// DISAMBIGUATED partial-wrapper leaf, or `None` when the pair is not a known
/// panic partial.
///
/// This is the panic-freedom enabler. A bare `unwrap` names neither
/// `Option::unwrap` nor `Result::unwrap`; the receiver type (from the Tier-2b
/// oracle's `textDocument/definition` file stem) disambiguates which shim
/// partial -- and therefore which REAL precondition -- the call site must
/// discharge to be proven panic-free:
///   (`option`, `unwrap`)     -> `option_unwrap`     (pre: `opt.is_some()`)
///   (`result`, `unwrap`)     -> `result_unwrap`     (pre: `result.is_ok()`)
///   (`option`, `expect`)     -> `option_expect`     (pre: `opt.is_some()`)
///   (`result`, `expect`)     -> `result_expect`     (pre: `result.is_ok()`)
///   (`result`, `unwrap_err`) -> `result_unwrap_err` (pre: `result.is_err()`)
///
/// The returned leaf is the shim partial's CONTRACT NAME, which is exactly the
/// key the binding index uses (`(library, leaf)`), so the matcher can select the
/// partial's contract as the bridge target. This table is a documented coupling
/// to the rust-std shim's partial function names (examples/sugar-shim-rust-std);
/// it is deliberately SMALL and explicit (the panic set), not a generic rule.
/// `unwrap_or`/`get` etc. are TOTAL (no panic), so they are intentionally absent
/// and fall through to the bare-leaf key (their existing total-wrapper bridges
/// are unaffected). Anything not in this table -> `None` -> bare-leaf key
/// (additive; the refuse-floor and the existing bridges are preserved).
/// True iff this free call needs arg-type resolution.
/// The set is deliberately narrow: only the serde_json totality wrappers.
/// A non-Value arg to `serde_json::to_string` must NOT be disambiguated
/// (it stays `to_string` -> no-contract-for-callee -> honestly undecidable).
fn needs_arg_type_resolution(callee_crate: Option<&str>, callee: &str) -> bool {
    callee_crate == Some("serde_json")
        && matches!(callee, "to_value" | "to_string" | "to_string_pretty")
}

fn disambiguated_serde_json_totality_target(
    callee: &str,
    type_id: &TypeIdentity,
    manifest: &InfallibleSerializeManifest,
    current_crate: &str,
) -> Option<(String, String)> {
    // `type_crate` is the argument type's crate identity, used only for
    // matching. The synthetic totality contract is published by the current
    // project proof, so the bridge targets `current_crate`.
    manifest
        .contract_for(callee, type_id)
        .map(|contract| (current_crate.to_string(), contract.to_string()))
        .or_else(|| {
            // Backwards-compatible Rust-kit semantics for the serde_json shim's
            // existing Value totality contracts. This stays in the kit: the
            // CLI/verifier still see only opaque contract names over RPC.
            if type_id.krate == "serde_json" && type_id.head == "Value" {
                Some((
                    "serde_json".to_string(),
                    match callee {
                        "to_string" => "serde_json_to_string_value",
                        "to_string_pretty" => "serde_json_to_string_pretty_value",
                        _ => return None,
                    }
                    .to_string(),
                ))
            } else {
                None
            }
        })
}

/// Extract the bare identifier name from an expression, stripping leading
/// `&`/`&mut` references. Used to look up a call argument's name in the
/// enclosing function's parameter type map.
///
/// Returns `Some(name)` for `v`, `&v`, `&mut v` where the ident is bare.
/// Returns `None` for non-ident expressions (method calls, literals, etc.).
fn expr_bare_ident_name(expr: &syn::Expr) -> Option<String> {
    match expr {
        syn::Expr::Path(p) if p.path.segments.len() == 1 => {
            Some(p.path.segments[0].ident.to_string())
        }
        syn::Expr::Reference(r) => expr_bare_ident_name(&r.expr),
        _ => None,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct MethodCallOccurrence {
    method: String,
    line: usize,
    column: usize,
    end_line: usize,
    end_column: usize,
}

#[derive(Debug, Default)]
struct MethodPostconditionStability {
    local_bindings: HashMap<String, usize>,
    effect_roots: BTreeSet<String>,
}

fn method_call_occurrence(node: &syn::ExprMethodCall) -> MethodCallOccurrence {
    let start = node.method.span().start();
    let end = node.span().end();
    MethodCallOccurrence {
        method: node.method.to_string(),
        line: start.line,
        column: start.column,
        end_line: end.line,
        end_column: end.column,
    }
}

fn source_position_after_method_call(
    line: usize,
    column: usize,
    candidate: &MethodCallOccurrence,
) -> bool {
    line > candidate.end_line || (line == candidate.end_line && column >= candidate.end_column)
}

fn method_postcondition_receiver_is_stable(
    node: &syn::ExprMethodCall,
    block: &syn::Block,
    param_names: &BTreeSet<String>,
) -> bool {
    let Some(root) = expr_bare_ident_name(&node.receiver) else {
        return false;
    };
    let occurrence = method_call_occurrence(node);
    let stability = method_postcondition_stability_for_block(block, &occurrence);
    if stability.effect_roots.contains(&root) {
        return false;
    }
    let binding_count = match stability.local_bindings.get(&root) {
        Some(count) => *count,
        None => 0,
    } + usize::from(param_names.contains(&root));
    binding_count <= 1
}

fn method_postcondition_stability_for_block(
    block: &syn::Block,
    candidate: &MethodCallOccurrence,
) -> MethodPostconditionStability {
    struct V<'a> {
        candidate: &'a MethodCallOccurrence,
        stability: MethodPostconditionStability,
    }

    impl<'ast, 'a> syn::visit::Visit<'ast> for V<'a> {
        fn visit_local(&mut self, node: &'ast syn::Local) {
            let start = node.span().start();
            if source_position_after_method_call(start.line, start.column, self.candidate) {
                return;
            }
            for root in pat_bound_idents(&node.pat) {
                *self.stability.local_bindings.entry(root).or_default() += 1;
            }
            syn::visit::visit_local(self, node);
        }

        fn visit_expr_assign(&mut self, node: &'ast syn::ExprAssign) {
            let start = node.span().start();
            if source_position_after_method_call(start.line, start.column, self.candidate) {
                return;
            }
            self.stability
                .effect_roots
                .extend(expr_assignment_roots(&node.left));
            syn::visit::visit_expr_assign(self, node);
        }

        fn visit_expr_binary(&mut self, node: &'ast syn::ExprBinary) {
            let start = node.span().start();
            if source_position_after_method_call(start.line, start.column, self.candidate) {
                return;
            }
            if binop_is_assignment(&node.op) {
                self.stability
                    .effect_roots
                    .extend(expr_assignment_roots(&node.left));
            }
            syn::visit::visit_expr_binary(self, node);
        }

        fn visit_expr_reference(&mut self, node: &'ast syn::ExprReference) {
            let start = node.span().start();
            if source_position_after_method_call(start.line, start.column, self.candidate) {
                return;
            }
            if node.mutability.is_some() {
                if let Some(root) = expr_bare_ident_name(&node.expr) {
                    self.stability.effect_roots.insert(root);
                }
            }
            syn::visit::visit_expr_reference(self, node);
        }

        fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
            let start = node.span().start();
            if source_position_after_method_call(start.line, start.column, self.candidate) {
                return;
            }
            let occurrence = method_call_occurrence(node);
            if &occurrence != self.candidate && !method_postcondition_method_is_pure_read(node) {
                if let Some(root) = expr_bare_ident_name(&node.receiver) {
                    self.stability.effect_roots.insert(root);
                }
            }
            syn::visit::visit_expr_method_call(self, node);
        }
    }

    let mut visitor = V {
        candidate,
        stability: MethodPostconditionStability::default(),
    };
    syn::visit::Visit::visit_block(&mut visitor, block);
    visitor.stability
}

fn method_postcondition_method_is_pure_read(node: &syn::ExprMethodCall) -> bool {
    let receiver_pure = method_postcondition_expr_is_pure_read(&node.receiver);
    let args_pure = node.args.iter().all(method_postcondition_expr_is_pure_read);
    if !receiver_pure || !args_pure {
        return false;
    }
    match node.method.to_string().as_str() {
        "cid" | "is_empty" | "is_none" | "is_some" | "len" => node.args.is_empty(),
        "get" | "starts_with" | "strip_prefix" => node.args.len() == 1,
        _ => false,
    }
}

fn method_postcondition_expr_is_pure_read(expr: &syn::Expr) -> bool {
    match expr {
        syn::Expr::Array(array) => array
            .elems
            .iter()
            .all(method_postcondition_expr_is_pure_read),
        syn::Expr::Field(field) => method_postcondition_expr_is_pure_read(&field.base),
        syn::Expr::Group(group) => method_postcondition_expr_is_pure_read(&group.expr),
        syn::Expr::Index(index) => {
            method_postcondition_expr_is_pure_read(&index.expr)
                && method_postcondition_expr_is_pure_read(&index.index)
        }
        syn::Expr::Lit(_) | syn::Expr::Path(_) => true,
        syn::Expr::MethodCall(method) => method_postcondition_method_is_pure_read(method),
        syn::Expr::Paren(paren) => method_postcondition_expr_is_pure_read(&paren.expr),
        syn::Expr::Reference(reference) if reference.mutability.is_none() => {
            method_postcondition_expr_is_pure_read(&reference.expr)
        }
        syn::Expr::Tuple(tuple) => tuple
            .elems
            .iter()
            .all(method_postcondition_expr_is_pure_read),
        _ => false,
    }
}

fn build_param_name_set(sig: &syn::Signature) -> BTreeSet<String> {
    let mut names = BTreeSet::new();
    for input in &sig.inputs {
        let syn::FnArg::Typed(pt) = input else {
            continue;
        };
        names.extend(pat_bound_idents(&pt.pat));
    }
    names
}

/// Build a map from parameter name to `(crate, type_head)` for the given
/// function signature. Used for syntactic serde_json::Value arg-type
/// disambiguation without needing the oracle.
///
/// For `fn f(v: &serde_json::Value)`, returns `{"v" -> ("serde_json", "Value")}`.
/// For `fn f(v: &Value)` with `use serde_json::Value` in scope, same result.
/// For `fn g(s: &MyStruct)`, returns `{"s" -> ("current_crate", "MyStruct")}`.
/// Non-typed patterns (e.g. destructured) are skipped.
fn build_param_type_map(
    sig: &syn::Signature,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> HashMap<String, TypeIdentity> {
    let mut map = HashMap::new();
    for input in &sig.inputs {
        let syn::FnArg::Typed(pt) = input else {
            continue; // skip `self`
        };
        let syn::Pat::Ident(pi) = &*pt.pat else {
            continue; // skip destructured patterns
        };
        let name = pi.ident.to_string();
        let ty = &*pt.ty;
        // Strip outer & / &mut
        let inner_ty = strip_reference_type(ty);
        // Extract the type's (crate, head)
        if let Some(type_id) = type_identity_for(inner_ty, use_map, local_type_names, current_crate)
        {
            map.insert(name, type_id);
        }
    }
    map
}

/// For a type path, return `(crate, type_head)`. Uses `type_crate_for` for the
/// crate and extracts the last path segment for the head.
///
/// Returns `None` for non-path types or when the crate cannot be determined.
fn type_identity_for(
    ty: &syn::Type,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<TypeIdentity> {
    let syn::Type::Path(tp) = ty else {
        return None;
    };
    let head = tp.path.segments.last()?.ident.to_string();
    let krate = type_crate_for(ty, use_map, local_type_names, current_crate)?;
    Some(TypeIdentity { krate, head })
}

fn expr_constructed_type_identity(
    expr: &syn::Expr,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<TypeIdentity> {
    match expr {
        syn::Expr::Struct(expr_struct) => {
            type_identity_for_path(&expr_struct.path, use_map, local_type_names, current_crate)
        }
        syn::Expr::Paren(paren) => {
            expr_constructed_type_identity(&paren.expr, use_map, local_type_names, current_crate)
        }
        syn::Expr::Group(group) => {
            expr_constructed_type_identity(&group.expr, use_map, local_type_names, current_crate)
        }
        _ => None,
    }
}

fn type_identity_for_path(
    path: &syn::Path,
    use_map: &HashMap<String, String>,
    local_type_names: &BTreeSet<String>,
    current_crate: &str,
) -> Option<TypeIdentity> {
    let head = path.segments.last()?.ident.to_string();
    let segs: Vec<String> = path
        .segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect();
    let krate = if segs.len() >= 2 {
        resolve_path_root_crate(segs.first()?, use_map, current_crate)
    } else {
        use_map
            .get(&head)
            .map(|root| resolve_path_root_crate(root, use_map, current_crate))
            .or_else(|| {
                if !current_crate.is_empty() && local_type_names.contains(&head) {
                    Some(current_crate.to_string())
                } else if is_std_prelude_panic_type(&head) {
                    Some("std".to_string())
                } else {
                    None
                }
            })?
    };
    Some(TypeIdentity { krate, head })
}

fn strip_reference_type(ty: &syn::Type) -> &syn::Type {
    match ty {
        syn::Type::Reference(r) => strip_reference_type(&r.elem),
        other => other,
    }
}

fn disambiguated_partial_leaf(type_stem: &str, leaf: &str) -> Option<String> {
    let partial = match (type_stem, leaf) {
        ("option", "unwrap") => "option_unwrap",
        ("result", "unwrap") => "result_unwrap",
        ("option", "expect") => "option_expect",
        ("result", "expect") => "result_expect",
        ("result", "unwrap_err") => "result_unwrap_err",
        _ => return None,
    };
    Some(partial.to_string())
}

/// Is `leaf` a PANIC method whose safety depends on a precondition? These bare
/// leaves must NEVER bridge to a bare `(crate, leaf)` contract: such a shell has
/// no precondition, so the bridge would vacuous-pass and falsely assert the site
/// cannot panic. A panic leaf either reaches its type-disambiguated partial
/// (whose pre IS the panic obligation) or REFUSES (honest unproven). This is the
/// panic-site half of the refuse-floor. The set mirrors the `(type, leaf)` pairs
/// in `disambiguated_partial_leaf`; `get`/`unwrap_or` are TOTAL (return Option /
/// a default, never panic) and are intentionally NOT panic leaves.
fn is_panic_leaf(leaf: &str) -> bool {
    matches!(leaf, "unwrap" | "expect" | "unwrap_err")
}

/// PANIC-LOCUS PRESERVATION (#1745): collect the source loci of every panic-leaf
/// method call (`x.unwrap()` / `.expect()` / `.unwrap_err()`) in a function body,
/// keyed by the LIFTED argument term so the verifier can attribute a per-symbol
/// `method:unwrap` obligation back to ITS OWN receiver producer call site.
///
/// The problem this closes: a panic-leaf call lifts to the abstract ctor
/// `method:unwrap` with NO source span (the IR term is span-free by design). Two
/// functions both calling `.unwrap()` therefore produce two `method:unwrap`
/// obligations that the verifier's per-symbol bridge index (`bridges_by_symbol`,
/// last-writer-wins) collapses to a single call-site line. The line is the call
/// OCCURRENCE's provenance, and each occurrence lives in exactly one function's
/// contract, so we record it HERE, scoped to this contract.
///
/// Key = the lifted argument term (the unwrap RECEIVER, e.g. `to_string(v)`),
/// produced by the SAME `lift_expr_to_term` the post lift uses, so it is
/// byte-identical to the `method:unwrap` ctor's first arg as it appears in the
/// contract `post`. enumerate matches an occurrence to its locus by this term
/// (NOT by positional order, which is fragile across two distinct walks). A
/// receiver that does not lift (returns None) records no locus: the occurrence
/// then carries no line and stays honestly undecidable (fail-safe, never the
/// collapsed line).
///
/// The `line`/`col` fields name the panic leaf's method-token span, so the
/// verifier can resolve the panic partial bridge at the exact panic site. The
/// receiver producer's bridge coordinates ride separately as
/// `producerLine`/`producerCol`/`producerSymbol`; a split-line
/// `GrammarOpRegistry\n  .cid(..)\n  .expect(..)` needs all three coordinates
/// because the receiver expression, producer call, and panic leaf can start on
/// three different source lines. The verifier treats these as opaque provenance.
fn collect_panic_loci(item_fn: &syn::ItemFn, rel_path: &str) -> Vec<Value> {
    sugar_walk::lift::collect_panic_loci_json(item_fn, rel_path)
}

/// Tier 2b (§2.T2b): for the still-unresolved method calls in `callsites`
/// (`is_method && callee_crate.is_none()`), consult the rust-analyzer semantic
/// oracle in one warm session and stamp the resolved (normalized) crate. Free
/// calls left `None` by Tier 1 are NOT sent to the oracle: those are glob
/// imports whose current-crate fallback is intended. The oracle refuses
/// (leaves `None`) when disabled or unavailable, so this is a pure upgrade over
/// Tier 2a with no behavior change when off.
fn resolve_method_calls_via_oracle(
    workspace_root: &Path,
    callsites: &mut [(CallSite, PathBuf)],
) -> OracleObservation {
    use ra_daemon_client::DaemonQuery;

    // Opt-in stays identical to the cold path: a mint with the oracle off must
    // never spawn or contact the daemon's RA host. When off we leave every
    // unresolved method call to the syntactic tiers (Tier 1/2a) and return.
    let raw_oracle_env = match std::env::var("SUGAR_RESOLVE_ORACLE") {
        Ok(value) => value,
        Err(_) => String::new(),
    };
    let oracle_on = raw_oracle_env == "rust-analyzer";
    let total_method_calls = callsites.iter().filter(|(cs, _)| cs.is_method).count();
    info!(
        oracle_env = %raw_oracle_env,
        oracle_on,
        total_callsites = callsites.len(),
        total_method_calls,
        linkerd_bin = %std::env::var("SUGAR_LINKERD_BIN").unwrap_or_else(|_| "<unset>".into()),
        linkerd_socket = %std::env::var("SUGAR_LINKERD_SOCKET").unwrap_or_else(|_| "<unset>".into()),
        "ORACLE: resolve_method_calls_via_oracle ENTER"
    );
    let mut observation = OracleObservation {
        requested: oracle_on,
        ..OracleObservation::default()
    };
    if !oracle_on {
        info!(oracle_env = %raw_oracle_env, "ORACLE: OFF (SUGAR_RESOLVE_ORACLE != rust-analyzer); leaving method calls to Tier 1/2a -- NO daemon, NO disambiguation");
        return observation;
    }

    // Gather the eligible positions. proc-macro2 spans are 1-based line /
    // 0-based column; LSP wants 0-based line, 0-based char. The method ident's
    // span start already points at the ident (not the dot), so the column maps
    // directly. A line of 0 should never occur for a real call; guard anyway.
    let mut queries: Vec<DaemonQuery> = Vec::new();
    for (cs, full_path) in callsites.iter() {
        if !cs.is_method {
            continue;
        }
        let is_candidate = cs.callee_crate.is_none() && cs.line >= 1;
        info!(
            callee = %cs.callee,
            callee_crate = ?cs.callee_crate,
            disambiguated_callee = ?cs.disambiguated_callee,
            is_panic_leaf = is_panic_leaf(&cs.callee),
            file = %full_path.display(),
            line = cs.line,
            col = cs.col,
            is_candidate,
            "ORACLE: method-call gate -- is_candidate={is_candidate} (candidate iff callee_crate==None). callee_crate already set => oracle SKIPS this site"
        );
        if is_candidate {
            queries.push(DaemonQuery {
                file: full_path.to_string_lossy().into_owned(),
                line: (cs.line - 1) as u32,
                col: cs.col as u32,
            });
        }
    }
    let total_queries = queries.len();
    observation.attempted = total_queries as u64;
    if queries.is_empty() {
        info!(
            total_method_calls,
            "ORACLE: ZERO candidate queries (every method call already had callee_crate set syntactically) -- daemon will NOT be spawned, NO disambiguation will occur"
        );
        return observation;
    }
    info!(
        count = total_queries,
        "ORACLE: asking resident daemon (sugar-linkerd) to resolve {total_queries} method calls -- spawning/indexing daemon now"
    );
    // The resident warm rust-analyzer indexes the workspace ONCE inside the
    // daemon and is reused across mints, fronted by a content-addressed cache.
    // The daemon client waits on linkerd's readiness signal before resolving,
    // so a cold proof mint does not bake a partially-indexed answer into proof.
    let batch = ra_daemon_client::resolve_receiver_crates(workspace_root, &queries);
    observation.reachable = batch.reachable;
    observation.ready = batch.ready;
    let resolved = batch.resolutions;
    let resolved_count = resolved.len();
    observation.resolved = resolved_count as u64;
    let unavailable_count = total_queries - resolved_count;
    if resolved.is_empty() {
        debug!(
            total = total_queries,
            "oracle: daemon resolved nothing (cold/not-ready or all refused); \
             leaving method calls to Tier 1/2a"
        );
        return observation;
    }
    for (cs, full_path) in callsites.iter_mut() {
        if cs.is_method && cs.callee_crate.is_none() && cs.line >= 1 {
            let key = (
                full_path.to_string_lossy().into_owned(),
                (cs.line - 1) as u32,
                cs.col as u32,
            );
            if let Some(res) = resolved.get(&key) {
                // Disambiguate the panic partial from the receiver TYPE stem: an
                // `unwrap` on `Option` (stem `option`) must discharge against the
                // shim's `option_unwrap` (pre `opt.is_some()`), not the ambiguous
                // bare `unwrap`. When the type was not disambiguable, leave the
                // disambiguated leaf None and key on the bare callee as before.
                let disambiguated = res
                    .type_stem
                    .as_deref()
                    .and_then(|stem| disambiguated_partial_leaf(stem, &cs.callee));
                debug!(
                    callee = %cs.callee,
                    resolved_crate = %res.krate,
                    type_stem = ?res.type_stem,
                    disambiguated = ?disambiguated,
                    file = %full_path.display(),
                    line = cs.line,
                    "oracle resolved method call (resident daemon)"
                );
                cs.callee_crate = Some(res.krate.clone());
                cs.disambiguated_crate = disambiguated.as_ref().map(|_| res.krate.clone());
                cs.disambiguated_callee = disambiguated;
            } else {
                debug!(
                    callee = %cs.callee,
                    file = %full_path.display(),
                    line = cs.line,
                    "oracle refused: no resolution for method call"
                );
            }
        }
    }
    info!(
        resolved = resolved_count,
        total = total_queries,
        unavailable = unavailable_count,
        "oracle resolved {}/{} method calls via resident daemon ({} refused/unavailable)",
        resolved_count,
        total_queries,
        unavailable_count
    );
    observation
}

fn binding_has_pre(binding: &Value) -> bool {
    binding
        .get("has_pre")
        .or_else(|| binding.get("hasPre"))
        .and_then(|v| v.as_bool())
        .unwrap_or_else(|| binding.get("pre").is_some_and(has_nontrivial_pre_json))
}

fn has_nontrivial_pre_json(pre: &Value) -> bool {
    if pre.is_null() {
        return false;
    }
    !(pre.get("kind").and_then(|v| v.as_str()) == Some("atomic")
        && pre.get("name").and_then(|v| v.as_str()) == Some("true"))
}

fn binding_has_post(binding: &Value) -> bool {
    binding
        .get("has_post")
        .or_else(|| binding.get("hasPost"))
        .and_then(|v| v.as_bool())
        .unwrap_or_else(|| binding.get("post").is_some() || binding.get("postHash").is_some())
}

fn binding_is_body_bearing(binding: &Value) -> bool {
    match binding.get("body_bearing").and_then(|v| v.as_bool()) {
        Some(body_bearing) => body_bearing,
        None => false,
    }
}

fn binding_contract_name(binding: &Value) -> Option<&str> {
    binding
        .get("name")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|name| !name.is_empty())
}

fn binding_is_imported_contract(binding: &Value) -> bool {
    binding
        .get("target_proof_cid")
        .and_then(Value::as_str)
        .is_some_and(|cid| !cid.trim().is_empty())
}

fn binding_rank(binding: &Value) -> u8 {
    if binding_has_pre(binding) {
        2
    } else if binding_is_body_bearing(binding) {
        1
    } else {
        0
    }
}

fn rust_binding_key_leaves(name_leaf: &str, binding: &Value) -> Vec<String> {
    let mut leaves = Vec::new();
    push_rust_binding_key_leaf(&mut leaves, name_leaf);
    let Some(alias) = binding
        .get("bridgeSourceSymbol")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
    else {
        return leaves;
    };

    push_rust_binding_key_leaf(&mut leaves, alias);
    if let Some(method_leaf) = alias.strip_prefix("method:") {
        push_rust_binding_key_leaf(&mut leaves, method_leaf);
    }
    if let Some(call_leaf) = alias.strip_prefix("call:") {
        push_rust_binding_key_leaf(&mut leaves, call_leaf);
        if let Some(last) = call_leaf.rsplit("::").next() {
            push_rust_binding_key_leaf(&mut leaves, last);
        }
    }
    leaves
}

fn push_rust_binding_key_leaf(leaves: &mut Vec<String>, leaf: &str) {
    let leaf = leaf.trim();
    if leaf.is_empty() {
        return;
    }
    if !leaves.iter().any(|existing| existing == leaf) {
        leaves.push(leaf.to_string());
    }
}

// ---------------------------------------------------------------------------
// Source Oracle + materialize (#1359). The rust mirror of the python kit's
// `source_oracle.py` + `bind_rpc.py::materialize_impl`. The `.proof` carries a
// SourceMemento (locus + source_cid/template_cid, no inline body); the
// oracle reconstructs the body from on-disk source IFF it recomputes to the
// pinned CIDs, else REFUSES. Exact-or-refuse, no silent loss.
// ---------------------------------------------------------------------------

/// A vendor sugar binding the materializer can fill a boundary stub from: the
/// `(library_tag, source_function_name)` key + the SourceMemento needed to
/// resolve its body.
struct VendorBinding {
    library_tag: String,
    source_function_name: String,
    memento: SourceMemento,
}

/// Collect VendorBindings from the FROZEN vendor `.proof`s resolved for the
/// project (the same proof sources `recognize` uses: `.sugar/imports/` +
/// cargo-dependency proofs). The pin is frozen at mint time; the oracle later
/// resolves it against LIVE vendor disk, so drift (frozen pin != live recompute)
/// is detectable. This is the by-reference contract: re-lifting live source
/// could never detect drift (the pin would track disk by construction).
///
/// Mirrors python `_vendor_proof_binding_templates` + `_resolve_via_source_oracle`.
/// Materialize pulls the SourceMemento (locus + pins) and resolves the body via
/// the oracle; recognize only needs the pinned `template_cid`.
fn vendor_bindings_from_proofs(project_root: &Path) -> Result<Vec<VendorBinding>, String> {
    let proof_paths = resolve_recognizer_proof_paths(project_root)?;
    let mut bindings = Vec::new();
    for path in proof_paths {
        let bytes = match std::fs::read(&path) {
            Ok(b) => b,
            Err(_) => continue,
        };
        let Ok(graph) = sugar_proof_envelope::ProofGraph::read(&bytes) else {
            continue;
        };
        for view in graph.members_view() {
            let Ok(parsed) = serde_json::from_slice::<Value>(view.bytes()) else {
                continue;
            };
            let body = match parsed.get("body") {
                Some(body) => body,
                None => &parsed,
            };
            if body.get("kind").and_then(Value::as_str) != Some("library-sugar-binding-entry") {
                continue;
            }
            let Some(library_tag) = body
                .get("target_library_tag")
                .or_else(|| body.get("library_tag"))
                .and_then(Value::as_str)
                .filter(|tag| !tag.is_empty())
            else {
                return Err(format!(
                    "vendor proof `{}` library-sugar-binding-entry missing target_library_tag",
                    path.display()
                ));
            };
            let Some(source_function_name) = body
                .get("source_function_name")
                .and_then(Value::as_str)
                .filter(|name| !name.is_empty())
            else {
                return Err(format!(
                    "vendor proof `{}` library-sugar-binding-entry missing source_function_name",
                    path.display()
                ));
            };
            let Some(body_source) = body.get("body_source") else {
                continue;
            };
            let Some(memento) = SourceMemento::from_body_source(
                Some(source_function_name.to_string()),
                body_source,
            ) else {
                continue;
            };
            bindings.push(VendorBinding {
                library_tag: library_tag.to_string(),
                source_function_name: source_function_name.to_string(),
                memento,
            });
        }
    }
    Ok(bindings)
}

fn lift_implications(params: &Value) -> Result<Value, String> {
    use std::collections::HashMap;

    let workspace_root = params
        .get("workspace_root")
        .and_then(|v| v.as_str())
        .ok_or("missing `workspace_root`")?;
    let workspace_root = std::path::PathBuf::from(workspace_root);

    let source_paths: Vec<String> = params
        .get("source_paths")
        .and_then(|v| v.as_array())
        .ok_or("missing `source_paths` array")?
        .iter()
        .filter_map(|v| v.as_str().map(|s| s.to_string()))
        .collect();

    let mut contract_bindings: Vec<Value> =
        match params.get("contract_bindings").and_then(|v| v.as_array()) {
            Some(bindings) => bindings.clone(),
            None => Vec::new(),
        };
    let supplied_contract_bindings = contract_bindings.len();
    let vendor_contract_bindings = rust_vendor_contract_bindings_from_proofs(&workspace_root)?;
    let vendor_contract_binding_count = vendor_contract_bindings.len();
    contract_bindings.extend(vendor_contract_bindings);

    let span = tracing::info_span!(
        "lift_implications",
        workspace = %workspace_root.display(),
        source_files = source_paths.len(),
        contract_bindings = contract_bindings.len(),
    );
    let _enter = span.enter();

    info!(
        source_files = source_paths.len(),
        supplied_contract_bindings = supplied_contract_bindings,
        vendor_contract_bindings = vendor_contract_binding_count,
        contract_bindings = contract_bindings.len(),
        workspace = %workspace_root.display(),
        "lift_implications: starting callsite collection"
    );

    trace!(
        source_paths = ?source_paths,
        "lift_implications: source file list"
    );

    // The crate currently being lifted. Producer contracts and intra-crate
    // call sites resolve to this; a dependency call site resolves to its own
    // crate. Reading it from the project Cargo.toml is what lets the matcher
    // tell this crate's `foo` from a same-named dependency `foo` (Tier 1).
    let current_crate = match crate_name_for(&workspace_root) {
        Some(name) => name,
        None => String::new(),
    };
    debug!(current_crate = %current_crate, "lift_implications: resolved current crate");
    let infallible_serialize = InfallibleSerializeManifest::load(&workspace_root)?;
    if !infallible_serialize.is_empty() {
        info!(
            entries = infallible_serialize.rules.len(),
            "lift_implications: loaded infallible serde_json manifest"
        );
    }
    let function_postconditions = FunctionPostconditionsManifest::load(&workspace_root)?;
    if !function_postconditions.is_empty() {
        info!(
            entries = function_postconditions.rules.len(),
            "lift_implications: loaded function postconditions manifest"
        );
    }
    let residue_manifest = ResidueManifest::load(&workspace_root)?;
    if !residue_manifest.is_empty() {
        info!(
            entries = residue_manifest.annotations.len(),
            "lift_implications: loaded panic-site residue manifest"
        );
    }

    // Index contracts by (crate, leaf), not bare leaf. The leaf is the substring
    // before the first '@' in the contract `name` (`<callee>@<file>:<line>:<col>`
    // for test contracts, a bare `<fn>` for function-contracts). The crate is
    // the binding's `library` field (stamped by the lifter that produced it);
    // a binding with no `library` is treated as this crate (a producer
    // contract). Keying by (crate, leaf) is what stops a bare callee from
    // resolving to a same-named contract in the WRONG crate -- the cross-crate
    // ambiguity that forced same-name dependency contracts to be dropped at
    // mint. Within one key the body-bearing binding wins over an inv-only
    // witness (a bridge to the body-bearing target is dischargeable; a bridge
    // to the `inv` witness vacuous-passes); among same-tier bindings the first
    // wins (stable). Body-discharge-ineligible bindings are indexed separately
    // so the diagnostic distinguishes "known callee, not a real obligation"
    // from "no contract exists for this callee".
    let mut contracts_by_key: HashMap<(String, String), &Value> = HashMap::new();
    let mut ineligible_by_key: HashMap<(String, String), &Value> = HashMap::new();
    let mut same_bundle_bindings_by_name: HashMap<String, &Value> = HashMap::new();
    for binding in &contract_bindings {
        if let Some(name) = binding_contract_name(binding) {
            if !binding_is_imported_contract(binding) {
                same_bundle_bindings_by_name
                    .entry(name.to_string())
                    .or_insert(binding);
            }
            let leaf = match name.split_once('@') {
                Some((leaf, _)) => leaf,
                None => name,
            }
            .trim()
            .to_string();
            if leaf.is_empty() {
                continue;
            }
            let key_leaves = rust_binding_key_leaves(&leaf, binding);
            let body_policy = body_discharge_policy_from_object(binding);
            log_body_discharge_policy_warnings(
                "walk-lift-implication-contract-binding",
                name,
                &body_policy.warnings,
            );
            let body_discharge_eligible = body_policy.body_discharge_eligible;
            let library = binding
                .get("library")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(normalize_crate_root)
                .unwrap_or_else(|| current_crate.clone());
            let keys = key_leaves
                .into_iter()
                .map(|leaf| (library.clone(), leaf))
                .collect::<Vec<_>>();
            if !body_discharge_eligible {
                for key in keys {
                    ineligible_by_key.insert(key, binding);
                }
                continue;
            }
            for key in keys {
                match contracts_by_key.get(&key) {
                    None => {
                        contracts_by_key.insert(key, binding);
                    }
                    Some(existing) => {
                        // Upgrade to the most dischargeable binding; never
                        // downgrade. For panic partials, a pre-bearing contract is
                        // the only shape that can prove the site cannot panic.
                        if binding_rank(binding) > binding_rank(existing) {
                            contracts_by_key.insert(key, binding);
                        }
                    }
                }
            }
        }
    }

    let mut entries: Vec<Value> = Vec::new();
    let mut implications: Vec<Value> = Vec::new();
    let mut seen_implications: BTreeSet<String> = BTreeSet::new();
    let mut diagnostics: Vec<Value> = Vec::new();
    diagnostics.extend(residue_manifest.into_diagnostics());

    // Collect every call site across every file FIRST, carrying each one's
    // absolute path. The Tier-1/2a crate is set during collection; the Tier-2b
    // oracle (if enabled) then resolves the still-unresolved method calls in one
    // warm rust-analyzer session, before the matcher runs. Collecting up front is
    // what lets the oracle be spawned + indexed exactly once per lift run rather
    // than once per call site.
    let mut all_callsites: Vec<(CallSite, PathBuf)> = Vec::new();
    for (rel_path, full_path) in resolve_rs_source_files(&workspace_root, &source_paths) {
        let src = match std::fs::read_to_string(&full_path) {
            Ok(s) => s,
            Err(_) => continue, // missing files are not lift errors here
        };
        let file = match syn::parse_file(&src) {
            Ok(f) => f,
            Err(_) => continue, // unparseable files cannot host implication lifting
        };

        let use_map = build_use_crate_map(&file);
        let local_type_names = collect_local_type_names(&file);
        let local_free_functions = collect_local_free_function_names(&file);
        let enum_variant_types =
            collect_enum_variant_type_map(&file, &use_map, &local_type_names, &current_crate);
        let struct_field_types =
            collect_struct_field_type_map(&file, &use_map, &local_type_names, &current_crate);
        let fn_return_crates =
            function_return_crates(&file, &use_map, &local_type_names, &current_crate);
        let mut callsites: Vec<CallSite> = Vec::new();
        collect_callsites_in_items(
            &file.items,
            false,
            &rel_path,
            &use_map,
            &fn_return_crates,
            &local_type_names,
            &local_free_functions,
            &current_crate,
            &enum_variant_types,
            &struct_field_types,
            &infallible_serialize,
            &function_postconditions,
            &mut callsites,
        );
        callsites.extend(collect_tokio_mpsc_channel_conduit_callsites(
            &file, &rel_path,
        ));
        callsites.extend(collect_tokio_mutex_guard_conduit_callsites(
            &file, &rel_path,
        ));
        let file_callsite_count = callsites.len();
        if file_callsite_count > 0 {
            debug!(
                file = %rel_path,
                callsites = file_callsite_count,
                "lift_implications: collected callsites from file"
            );
        }
        for cs in callsites {
            all_callsites.push((cs, full_path.clone()));
        }
    }

    info!(
        total_callsites = all_callsites.len(),
        "lift_implications: callsite collection complete"
    );

    // Tier 2b (§2.T2b): for method calls Tier 2a could not resolve
    // (`callee_crate == None` AND `is_method`), ask rust-analyzer which crate
    // the receiver's method resolves into, and stamp the normalized crate. The
    // oracle is opt-in and refuses when unavailable; a refusal leaves the crate
    // `None`, which the matcher below treats exactly as before (current-crate
    // fallback / lift-gap). Tier 1/2a are untouched: only None-on-method sites
    // are sent to the oracle, so the fast path is never slowed by it.
    let oracle_observation = resolve_method_calls_via_oracle(&workspace_root, &mut all_callsites);

    {
        for (cs, _full_path) in all_callsites {
            if let Some(reason) = cs.unsupported_reason {
                debug!(
                    callee = %cs.callee,
                    reason = %reason,
                    file = %cs.file,
                    line = cs.line,
                    "lift-gap: unsupported implication callee shape"
                );
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "category": "implication-callee",
                    "reason": reason,
                    "callee": cs.callee,
                    "file": cs.file,
                    "line": cs.line,
                    "col": cs.col,
                }));
                continue;
            }
            // Resolve the call site to a (crate, leaf) key. An unresolved crate
            // (None: a method call, or a glob-imported bare call) defaults to
            // the current crate, preserving the prior intra-crate behavior; a
            // resolved cross-crate callee keys into that dependency's contracts.
            let resolved_crate = cs
                .callee_crate
                .clone()
                .unwrap_or_else(|| current_crate.clone());
            // CONVERGENCE resolution: receiver-type disambiguation (af65) picks
            // the right TARGET; the panic-leaf refuse-floor (af65) forbids a bare
            // vacuous shell on a panic site; Fix B (#1696, HEAD) keeps every
            // non-panic ineligible callsite ENUMERATED (bridged, never silently
            // dropped). The three compose because the panic vs total split gates
            // Fix B's ineligible-bridge structurally: an ineligible bare shell is
            // bridged only for TOTAL leaves; a panic leaf never reaches
            // `ineligible_by_key` (which is keyed on the bare `(std, unwrap)` no-pre
            // shell) and so can never vacuous-pass a "cannot panic" claim.
            //
            // PANIC-FREEDOM keying: when the Tier-2b oracle disambiguated the
            // receiver type, prefer the shim's disambiguated partial leaf
            // (`option_unwrap`), whose contract carries the REAL precondition
            // (`opt.is_some()`). Discharging that pre at the call site is the
            // proof the site cannot panic. The bridge's `sourceSymbol` stays the
            // bare `cs.callee` (the ctor name in the lifted caller body); only the
            // TARGET binding changes.
            let key = (resolved_crate.clone(), cs.contract_callee.clone());
            let disambig_key = cs.disambiguated_callee.as_ref().map(|leaf| {
                let dkey = (
                    cs.disambiguated_crate
                        .clone()
                        .unwrap_or_else(|| resolved_crate.clone()),
                    leaf.clone(),
                );
                dkey
            });
            let is_panic = is_panic_leaf(&cs.callee);
            let raw_disambig_binding = disambig_key
                .as_ref()
                .and_then(|dkey| contracts_by_key.get(dkey).copied());
            let raw_disambig_binding_has_pre = match raw_disambig_binding {
                Some(binding) => binding_has_pre(binding),
                None => false,
            };
            let disambig_binding = match (is_panic, raw_disambig_binding) {
                (true, Some(binding)) if binding_has_pre(binding) => Some(binding),
                (true, _) => None,
                (false, binding) => binding,
            };
            let disambig_ineligible = disambig_key
                .as_ref()
                .and_then(|dkey| ineligible_by_key.get(dkey).copied());
            if is_panic {
                info!(
                    callee = %cs.callee,
                    resolved_crate = %resolved_crate,
                    disambiguated_callee = ?cs.disambiguated_callee,
                    disambig_binding_found = raw_disambig_binding.is_some(),
                    disambig_binding_has_pre = raw_disambig_binding_has_pre,
                    lookup_key = ?disambig_key,
                    file = %cs.file,
                    line = cs.line,
                    "PANIC-EMIT: panic-leaf site decision -- bridges to disambiguated pre-bearing partial iff found, else REFUSES (panic-site-unproven)"
                );
            }
            // A value-producing select (NOT a let-else): the total-leaf branch must
            // be able to YIELD the ineligible binding for Fix B, which a let-else
            // `else` block (it must diverge) structurally cannot do.
            let binding = if is_panic {
                // PANIC-LEAF refuse-floor: disambiguate-or-refuse. The bare
                // `(std, unwrap)` shell carries no precondition, so bridging to it
                // would produce a VACUOUS pass on a panic site -- a false "this
                // cannot panic" claim, the worst refuse-floor breach. The ONLY
                // acceptable target is the type-disambiguated partial (whose pre IS
                // the panic-freedom obligation). No bare fall-through, no
                // ineligible fall-through; an unresolved panic site REFUSES.
                match disambig_binding {
                    Some(b) => b,
                    None => {
                        debug!(
                            callee = %cs.callee,
                            crate_ = %key.0,
                            disambiguated = ?cs.disambiguated_callee,
                            file = %cs.file,
                            line = cs.line,
                            "lift-gap: panic site unproven (receiver type unresolved or partial absent); \
                             refusing rather than bridging a bare vacuous unwrap"
                        );
                        diagnostics.push(json!({
                            "kind": "lift-gap",
                            "reason": "panic-site-unproven",
                            "detail": "receiver type did not resolve to a known panic partial; \
                                       a bare unwrap/expect would vacuous-pass, so the site is \
                                       reported as unproven (cannot show it does not panic)",
                            "callee": cs.callee,
                            "calleeCrate": key.0,
                            "file": cs.file,
                            "line": cs.line,
                            "col": cs.col,
                            "panicSite": true,
                        }));
                        continue;
                    }
                }
            } else {
                // TOTAL leaf: disambiguated partial -> bare eligible -> Fix B
                // ineligible bridge -> refuse. Fix B (#1696): a call site that
                // matched ANY known contract MUST be emitted as a bridge, never
                // silently dropped. An INELIGIBLE callee (its self-derived post has
                // no result equation) is bridged anyway; at verification the bridge
                // routes to the honesty boundary, so the obligation is honestly
                // surfaced instead of vanishing unseen. Only a callee with NO
                // contract at all has nothing to bridge to.
                match disambig_binding
                    .or(disambig_ineligible)
                    .or_else(|| contracts_by_key.get(&key).copied())
                {
                    Some(b) => b,
                    None => match ineligible_by_key.get(&key) {
                        Some(ineligible) => {
                            debug!(
                                callee = %cs.callee,
                                crate_ = %key.0,
                                file = %cs.file,
                                line = cs.line,
                                "lift-note: body-discharge-ineligible callee (bridged anyway, not dropped)"
                            );
                            // An INFORMATIONAL note, not a `lift-gap`: the call site
                            // IS bridged (below), so it is not a gap. We surface the
                            // body-discharge ineligibility for observability but no
                            // obligation vanishes.
                            diagnostics.push(json!({
                                "kind": "lift-note",
                                "reason": "body-discharge-ineligible-bridged",
                                "detail": body_discharge_policy_from_object(ineligible)
                                    .body_discharge_refusal_reason
                                    .unwrap_or_else(|| "callee contract is not body-discharge eligible; bridged anyway".to_string()),
                                "callee": cs.callee,
                                "calleeCrate": key.0,
                                "file": cs.file,
                                "line": cs.line,
                                "col": cs.col,
                            }));
                            // Do NOT `continue`: fall through and bridge to the
                            // ineligible callee's contract. The honesty boundary at
                            // verification handles it.
                            *ineligible
                        }
                        None => {
                            debug!(
                                callee = %cs.callee,
                                crate_ = %key.0,
                                file = %cs.file,
                                line = cs.line,
                                "lift-gap: no contract for callee"
                            );
                            diagnostics.push(json!({
                                "kind": "lift-gap",
                                "reason": "no-contract-for-callee",
                                "callee": cs.callee,
                                "calleeCrate": key.0,
                                "file": cs.file,
                                "line": cs.line,
                                "col": cs.col,
                            }));
                            continue;
                        }
                    },
                }
            };
            let Some(target_cid) = binding
                .get("contract_cid")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
            else {
                debug!(
                    callee = %cs.callee,
                    file = %cs.file,
                    line = cs.line,
                    "lift-gap: binding missing contract_cid"
                );
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "reason": "binding-missing-contract-cid",
                    "callee": cs.callee,
                    "file": cs.file,
                    "line": cs.line,
                    "col": cs.col,
                }));
                continue;
            };
            debug!(
                callee = %cs.callee,
                crate_ = %key.0,
                target_cid = %target_cid,
                file = %cs.file,
                line = cs.line,
                "lift_implications: emitting bridge for callsite"
            );
            // Forward pin: a binding harvested from a dependency proof carries
            // `target_proof_cid` (that proof's bundle CID); stamp it on the
            // bridge so the verifier enforces ConsequentBundlePinned against
            // the dependency bundle. An intra-crate binding has none -> the
            // field is omitted and the verifier enforces same-bundle
            // co-membership (self-pinned). This is the only path; there is no
            // unpinned bridge.
            //
            // method: SEAM. The bridge `sourceSymbol` is the verifier's lookup
            // key (`bridges_by_symbol.get(<ctor name>)`), so it MUST be the
            // exact ctor name the call appears as in a lifted fn-contract body.
            // A method call `x.unwrap()` lifts to ctor `method:unwrap` (see
            // `lift.rs` `Expr::MethodCall` -> `format!("method:{}", m.method)`),
            // while a free call `foo()` lifts to the bare `foo`. Keying the
            // bridge on the bare leaf for a method call made
            // `bridges_by_symbol.get("method:unwrap")` MISS, so the panic bridge
            // never enumerated. Emit `method:<leaf>` for method callsites; the
            // verifier matches by this opaque key, with no `method:` stripping or
            // Rust-method set on the verifier side. Target selection above is
            // unchanged: it correctly keys `contracts_by_key` on the bare leaf.
            let source_symbol = if cs.is_method {
                format!("method:{}", cs.callee)
            } else {
                cs.callee.clone()
            };
            let formal_actuals = formal_actuals_for_binding(binding, cs.actual_terms.as_deref());
            let mut bridge = json!({
                "kind": "bridge",
                "name": format!(
                    "intra-body:rust:{}@{}:{}:{}",
                    source_symbol, cs.file, cs.line, cs.col
                ),
                "schemaVersion": "1",
                "sourceContractCid": target_cid,
                "sourceLayer": "rust",
                "sourceSymbol": source_symbol,
                "target": { "cid": target_cid, "kind": "contract" },
                "targetContractCid": target_cid,
                "targetLayer": "rust-tests",
                "callsite": callsite_with_formal_actuals(
                    &cs.file,
                    cs.line,
                    cs.col,
                    is_panic,
                    formal_actuals,
                ),
            });
            if let Some(tpc) = binding
                .get("target_proof_cid")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
            {
                bridge["targetProofCid"] = json!(tpc);
            }
            if binding_has_pre(binding) && !binding_is_imported_contract(binding) {
                if let (Some(caller_name), Some(callee_name)) = (
                    cs.caller_contract_name.as_deref(),
                    binding_contract_name(binding),
                ) {
                    if same_bundle_bindings_by_name
                        .get(caller_name)
                        .is_some_and(|caller_binding| binding_has_post(caller_binding))
                    {
                        let implication_name = format!(
                            "rust-call-pre:{caller_name}->{callee_name}@{}:{}:{}",
                            cs.file, cs.line, cs.col
                        );
                        if seen_implications.insert(implication_name.clone()) {
                            implications.push(json!({
                                "name": implication_name,
                                "antecedent": caller_name,
                                "antecedentSlot": "post",
                                "consequent": callee_name,
                                "consequentSlot": "pre",
                                "prover": "rust-implications",
                            }));
                        }
                    }
                }
            }
            entries.push(bridge);
        }
    }

    let bridge_count = entries.len();
    let gap_count = diagnostics
        .iter()
        .filter(|d| d.get("kind").and_then(|v| v.as_str()) == Some("lift-gap"))
        .count();
    // Break the lift-gaps down by reason so the gap between callsites and
    // emitted bridges is legible: "why did 3000 method calls yield 30 bridges?"
    // is answered here (no-matching-contract / unresolved-receiver / closure /
    // macro / binding-missing-contract-cid ...), not left as a bare count.
    let mut gap_by_reason: std::collections::BTreeMap<&str, usize> =
        std::collections::BTreeMap::new();
    for d in &diagnostics {
        if d.get("kind").and_then(|v| v.as_str()) == Some("lift-gap") {
            let reason = match d.get("reason").and_then(|v| v.as_str()) {
                Some(reason) => reason,
                None => "unspecified",
            };
            *gap_by_reason.entry(reason).or_insert(0) += 1;
        }
    }
    let gap_breakdown = gap_by_reason
        .iter()
        .map(|(r, n)| format!("{r}={n}"))
        .collect::<Vec<_>>()
        .join(", ");
    info!(
        bridges_emitted = bridge_count,
        lift_gaps = gap_count,
        gap_breakdown = %gap_breakdown,
        "lift_implications: complete -> {} bridges emitted, {} lift-gaps [{}]",
        bridge_count,
        gap_count,
        gap_breakdown
    );
    // LOUD: a call site that matched a known contract but was dropped as
    // body-discharge-ineligible is the worst failure mode in this pipeline. It
    // is not bridged, not discharged, and not refused: it simply disappears from
    // verification, so an obligation we KNOW exists is silently suppressed. That
    // is exactly the regression that made self-application collapse from 1305 to
    // 582 call sites without a single warning. It must scream.
    let swallowed = match gap_by_reason.get("body-discharge-ineligible") {
        Some(swallowed) => *swallowed,
        None => 0,
    };
    if swallowed > 0 {
        // INVARIANT VIOLATION (Fix B): a call site that matched a known
        // contract was dropped. After Fix B this must be 0 -- ineligible
        // callees are now bridged (recorded as `lift-note`/
        // `body-discharge-ineligible-bridged`), not dropped. If this fires,
        // a new drop path was introduced; it must scream.
        warn!(
            swallowed_callsites = swallowed,
            "lift_implications: {} call sites had a MATCHING contract but were DROPPED as body-discharge-ineligible -> Fix B invariant VIOLATED (these must be bridged, not dropped)",
            swallowed
        );
    } else {
        // Observability: how many ineligible-but-bridged callsites Fix B
        // rescued from the old silent-drop path.
        let bridged_ineligible = diagnostics
            .iter()
            .filter(|d| {
                d.get("reason").and_then(|v| v.as_str())
                    == Some("body-discharge-ineligible-bridged")
            })
            .count();
        info!(
            swallowed_callsites = 0,
            bridged_ineligible_callsites = bridged_ineligible,
            "lift_implications: 0 swallowed call sites (Fix B); {} body-discharge-ineligible call sites bridged to the honesty boundary instead of dropped",
            bridged_ineligible
        );
    }

    let mut response = json!({
        "kind": "ir-document",
        "ir": entries,
        "diagnostics": diagnostics,
        "bridges_emitted": bridge_count as u64,
        "lift_gaps": gap_count as u64,
        "oracle_requested": oracle_observation.requested,
        "oracle_reachable": oracle_observation.reachable,
        "oracle_ready": oracle_observation.ready,
        "receivers_attempted": oracle_observation.attempted,
        "receivers_resolved": oracle_observation.resolved,
    });
    if !implications.is_empty() {
        response["implications"] = json!(implications);
    }
    Ok(response)
}

fn lift_pre(params: &Value) -> Result<Value, String> {
    let src = params
        .get("src")
        .and_then(|v| v.as_str())
        .ok_or("missing `src`")?;
    let fn_name = params
        .get("fn_name")
        .and_then(|v| v.as_str())
        .ok_or("missing `fn_name`")?;
    let item = parse_fn(src, fn_name)?;
    let pre = lift_function_precondition(&item);
    serde_json::to_value(pre.as_formula()).map_err(|e| e.to_string())
}

fn lift_post(params: &Value) -> Result<Value, String> {
    let src = params
        .get("src")
        .and_then(|v| v.as_str())
        .ok_or("missing `src`")?;
    let fn_name = params
        .get("fn_name")
        .and_then(|v| v.as_str())
        .ok_or("missing `fn_name`")?;
    let file: syn::File = syn::parse_str(src).map_err(|e| format!("parse error: {}", e))?;
    let return_facts = collect_explicit_function_return_facts(&file);
    let item = file
        .items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == fn_name => Some(f),
            _ => None,
        })
        .ok_or_else(|| format!("function `{}` not found", fn_name))?;
    let post = lift_function_postcondition_with_return_facts(&item, &return_facts);
    serde_json::to_value(post.as_formula()).map_err(|e| e.to_string())
}

fn contract(params: &Value) -> Result<Value, String> {
    let src = params
        .get("src")
        .and_then(|v| v.as_str())
        .ok_or("missing `src`")?;
    let fn_name = params
        .get("fn_name")
        .and_then(|v| v.as_str())
        .ok_or("missing `fn_name`")?;
    let file = params.get("file").and_then(|v| v.as_str());
    let parsed: syn::File = syn::parse_str(src).map_err(|e| format!("parse error: {}", e))?;
    let return_facts = collect_explicit_function_return_facts(&parsed);
    let item = parsed
        .items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == fn_name => Some(f),
            _ => None,
        })
        .ok_or_else(|| format!("function `{}` not found", fn_name))?;
    let post = lift_function_postcondition_with_return_facts(&item, &return_facts).into_formula();
    let contract =
        build_function_contract_with_file_and_post_override(&item, None, file, Some(post));
    serde_json::from_slice(&contract.canonical_bytes).map_err(|e| e.to_string())
}

fn term(params: &Value) -> Result<Value, String> {
    let src = params
        .get("src")
        .and_then(|v| v.as_str())
        .ok_or("missing `src`")?;
    let fn_name = params
        .get("fn_name")
        .and_then(|v| v.as_str())
        .ok_or("missing `fn_name`")?;
    let source = params
        .get("source")
        .and_then(|v| v.as_str())
        .ok_or("missing `source`")?;
    let file: syn::File = syn::parse_str(src).map_err(|e| format!("parse error: {}", e))?;
    let bytes = rust_function_term_json_for_file(&file, fn_name, source)?;
    serde_json::from_slice(&bytes).map_err(|e| e.to_string())
}

fn shadow_source(params: &Value) -> Result<Value, String> {
    let (s, _bytes) = build_bundle(params)?;
    Ok(json!({
        "cid": s.cid,
        "fn_name": s.fn_name,
        "slots": s.slots.len(),
        "arrivals_total": s.slots.iter().map(|sl| sl.arrivals.len()).sum::<usize>(),
        "bundle_cid": shadow_proof_ir_cid(&s),
    }))
}

fn proof_ir(params: &Value) -> Result<Value, String> {
    let (s, _bytes) = build_bundle(params)?;
    let bytes = shadow_to_proof_ir(&s);
    let cid = shadow_proof_ir_cid(&s);
    let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
    Ok(json!({
        "cid": cid,
        "bytes_b64": b64,
        "length": bytes.len(),
        "shadow_source_cid": s.cid,
    }))
}

fn build_bundle(params: &Value) -> Result<(sugar_walk::ShadowSource, Vec<u8>), String> {
    let src = params
        .get("src")
        .and_then(|v| v.as_str())
        .ok_or("missing `src`")?;
    let callee_name = params
        .get("callee")
        .and_then(|v| v.as_str())
        .ok_or("missing `callee`")?;
    let caller_name = params
        .get("caller")
        .and_then(|v| v.as_str())
        .ok_or("missing `caller`")?;
    let callee_fn = parse_fn(src, callee_name)?;
    let caller_fn = parse_fn(src, caller_name)?;
    let pre = lift_function_precondition(&callee_fn);
    let formal_params = all_param_names(&callee_fn);
    let s = build_shadow_source(
        &caller_fn,
        &[CalleeContract {
            callee_name: callee_name.to_string(),
            formal_params,
            precondition: pre,
        }],
    );
    Ok((s, Vec::new()))
}

fn parse_fn(src: &str, name: &str) -> Result<syn::ItemFn, String> {
    let file: syn::File = syn::parse_str(src).map_err(|e| format!("parse error: {}", e))?;
    file.items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == name => Some(f),
            _ => None,
        })
        .ok_or_else(|| format!("function `{}` not found", name))
}

fn all_param_names(item_fn: &syn::ItemFn) -> Vec<String> {
    // Must return length == arity. Non-Ident patterns get a stable placeholder.
    item_fn
        .sig
        .inputs
        .iter()
        .enumerate()
        .map(|(i, arg)| match arg {
            syn::FnArg::Receiver(_) => "__self".to_string(),
            syn::FnArg::Typed(pt) => match &*pt.pat {
                syn::Pat::Ident(p) => p.ident.to_string(),
                _ => format!("__arg{}", i),
            },
        })
        .collect()
}

// ============================================================================
// Bind-IR lift surface (PEP 1.7.0 kind = "lift")
//
// Implements the legacy-retained `initialize` / `lift` / `shutdown` JSON-RPC
// shape from `2026-04-30-lift-plugin-protocol.md`, returning bind-lift entries
// per `2026-05-13-bind-ir-lift-result.md`. cmd_bind dispatches Verb 1 (Lift)
// to this surface so the bind pipeline carries zero language knowledge in
// the CLI core.
// ============================================================================

fn initialize_result() -> Value {
    json!({
        "name": "sugar-walk-rpc",
        "version": env!("CARGO_PKG_VERSION"),
            "protocol_version": "pep/1.7.0",
            "capabilities": {
                "authoring_surfaces": ["rust", "rust-bind", "rust-walk-contracts"],
            "ir_version": "bind-ir/2.0.0",
            "emits_signed_mementos": false,
            // CONSUMER SURFACES (kit-declared, so `doctor` stays language-blind):
            // these surfaces MUST run a specific RPC method in the `consumer`
            // phase or they silently degrade to the default `lift` producer and
            // their pass never runs (the manifest method/phase footgun that cost
            // five investigations on 2026-05-31). `doctor` cross-checks each
            // kit manifest against this so the omission is a loud check, not a
            // silent empty-set attestation.
            "consumer_surfaces": {
                "rust-implications": {
                    "method": "sugar.plugin.lift_implications",
                    "phase": "consumer"
                }
            }
        }
    })
}

fn kit_declaration_result() -> Value {
    json!({
        "kit": {
            "id": "sugar-walk-rpc",
            "language": "rust",
            "version": env!("CARGO_PKG_VERSION")
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": true},
                {"name": "lift", "required": true},
                {"name": "shutdown", "required": true},
                {"name": "sugar.plugin.recognize", "required": false},
                {"name": "sugar.plugin.lift_implications", "required": false},
                {"name": COMPONENT_PLAN_RPC_METHOD, "required": false},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": false}
            ]
        },
        "proofResolution": {
            "strategy": "cargo"
        },
        "residueCategories": []
    })
}

fn component_plan_result(params: &Value) -> Value {
    let workspace_root = params
        .get("workspace_root")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let Some(vendor_root) = claimed_base64_vendor_root(params, &workspace_root) else {
        return json!({
            "decision": "decline",
            "reason": "no base64 0.22.1 vendor source candidate",
        });
    };
    let command = match std::env::current_exe() {
        Ok(path) => path.display().to_string(),
        Err(err) => {
            return json!({
                "decision": "decline",
                "reason": format!("could not determine sugar-walk-rpc executable: {err}"),
            });
        }
    };
    let vendor_manifest_path = format!("{vendor_root}/Cargo.toml");
    let Some(vendor_manifest_item) = forensic_items(params)
        .into_iter()
        .find(|item| {
            item.get("path").and_then(Value::as_str) == Some(vendor_manifest_path.as_str())
        })
        .and_then(|item| item.get("id").and_then(Value::as_str))
        .map(str::to_string)
    else {
        return json!({
            "decision": "decline",
            "reason": format!("missing base64 0.22.1 vendor Cargo.toml forensic item `{vendor_manifest_path}`"),
        });
    };

    json!({
        "decision": "claim",
        "claims": [
            {
                "item": vendor_manifest_item,
                "role": "contract-producer",
                "surface": "rust-fn-contracts",
            },
            {
                "item": "file:Cargo.toml",
                "role": "implication-consumer",
                "surface": "rust-implications",
            }
        ],
        "plugins": [
            {
                "name": "rust-fn-contracts-lift",
                "kind": "lift",
                "surface": "rust-fn-contracts",
                "emit": "ir-document",
                "workspace_override": vendor_root,
            },
            {
                "name": "rust-implications-lift",
                "kind": "lift",
                "surface": "rust-implications",
            }
        ],
        "lift_manifests": [
            {
                "surface": "rust-fn-contracts",
                "name": "rust-fn-contracts-lift",
                "version": env!("CARGO_PKG_VERSION"),
                "protocol_version": "pep/1.7.0",
                "kind": "lift",
                "command": [command, "--rpc"],
                "working_dir": ".",
            },
            {
                "surface": "rust-implications",
                "name": "rust-implications-lift",
                "version": env!("CARGO_PKG_VERSION"),
                "protocol_version": "pep/1.7.0",
                "kind": "lift",
                "command": [command, "--rpc"],
                "working_dir": ".",
                "method": "sugar.plugin.lift_implications",
                "phase": "consumer",
            }
        ],
        "diagnostics": [],
    })
}

fn claimed_base64_vendor_root(params: &Value, workspace_root: &Path) -> Option<String> {
    for item in forensic_items(params) {
        let path = item.get("path").and_then(Value::as_str)?;
        let language = item
            .get("language_hint")
            .or_else(|| item.get("languageHint"))
            .and_then(Value::as_str);
        if language != Some("rust") {
            continue;
        }
        if path == "vendor/base64-0.22.1/Cargo.toml" {
            return Some("vendor/base64-0.22.1".to_string());
        }
    }
    if workspace_root
        .join("vendor/base64-0.22.1/Cargo.toml")
        .is_file()
    {
        return Some("vendor/base64-0.22.1".to_string());
    }
    None
}

fn forensic_items(params: &Value) -> Vec<&Value> {
    match params
        .get("project_forensics")
        .or_else(|| params.get("projectForensics"))
        .and_then(|value| value.get("items"))
        .or_else(|| {
            params
                .get("workspace_evidence")
                .or_else(|| params.get("workspaceEvidence"))
                .and_then(|value| value.get("items"))
        })
        .and_then(Value::as_array)
    {
        Some(items) => items.iter().collect(),
        None => Vec::new(),
    }
}

fn bind_lift(params: &Value) -> Result<Value, String> {
    if lift_emit_mode(params) == Some("ir-document") {
        return function_contract_lift(params);
    }

    let workspace_root = params
        .get("workspace_root")
        .and_then(|v| v.as_str())
        .ok_or("missing `workspace_root`")?;
    let source_paths: Vec<String> = params
        .get("source_paths")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_else(|| vec![".".to_string()]);

    let root = PathBuf::from(workspace_root);
    let mut entries: Vec<Value> = Vec::new();
    let mut diagnostics: Vec<Value> = Vec::new();
    // Derive-from-source: in the `library-bindings` layer, EVERY module-level
    // `pub fn` that carries NO `#[sugar::sugar]` attribute is ALSO sugar —
    // the tag is gone, the binding is DERIVED from the crate name + fn name
    // (`<crate>::f` -> tag=`<crate>`, symbol=`<crate>.f`). This is the rust
    // mirror of python's universal lift (`_library_binding_entry_for_function`,
    // `binding_origin: "derived"`): write a function, it's sugar — zero code
    // changes, no `#[sugar::sugar]` required. Gated to `library-bindings`
    // exactly like python (`layer == "library-bindings"`) so the general
    // contract path (`all`) is untouched and not flooded. The explicit-tag
    // path below stays unconditional (it already works).
    let derive_library_bindings = params
        .get("options")
        .and_then(|options| options.get("layer"))
        .and_then(Value::as_str)
        == Some("library-bindings");
    // The crate the derived tag names: the RAW `[package].name` (hyphens
    // intact) so it matches a consumer's `#[sugar::boundary(library = ...)]`
    // verbatim under the materialize verb's raw `==`.
    let derived_crate_tag = if derive_library_bindings {
        crate_name_raw_for(&root)
    } else {
        None
    };

    let scan_roots: Vec<PathBuf> = if source_paths.is_empty() {
        vec![root.clone()]
    } else {
        source_paths
            .iter()
            .map(|p| {
                let candidate = root.join(p);
                if candidate.is_dir() {
                    candidate
                } else {
                    root.clone()
                }
            })
            .collect()
    };

    let mut visited: std::collections::BTreeSet<PathBuf> = Default::default();
    for scan_root in &scan_roots {
        let src_dir = scan_root.join("src");
        let walk_root: &Path = if src_dir.is_dir() {
            &src_dir
        } else {
            scan_root.as_path()
        };
        collect_rs_files(walk_root, &mut visited);
        // Also include top-level *.rs files when scan_root != walk_root.
        if walk_root != scan_root.as_path() {
            collect_rs_files_shallow(scan_root.as_path(), &mut visited);
        }
    }

    for path in &visited {
        let src = match std::fs::read_to_string(path) {
            Ok(s) => s,
            Err(e) => {
                diagnostics.push(diagnostic(
                    "read-error",
                    path.display().to_string(),
                    e.to_string(),
                ));
                continue;
            }
        };
        let file = match syn::parse_file(&src) {
            Ok(f) => f,
            Err(e) => {
                diagnostics.push(diagnostic(
                    "parse-error",
                    path.display().to_string(),
                    e.to_string(),
                ));
                continue;
            }
        };
        let rel = relative_display_path(path, &root);
        let witnesses_by_symbol =
            contract_witnesses_by_function_symbol(&file, &rel, src.as_bytes());

        for target in collect_bind_lift_targets_with_source(&file, &src) {
            let item_fn = &target.item_fn;
            let fn_name = &target.fn_name;
            let comment_shapes = comment_shapes_for_fn_source(&src, &target.source_name);
            let comment_count = comment_shapes.len();
            let base_term_shape = term_shape_for_fn(item_fn);
            let base_has_operator = !is_non_operation_shape(&base_term_shape);
            let term_shape = term_shape_with_comments(base_term_shape, comment_shapes);
            let term_shape_cid = blake3_512_of(encode_jcs(&term_shape).as_bytes());
            let operand_bindings = operand_bindings_for_fn_with_comment_prefix(
                item_fn,
                comment_count,
                base_has_operator,
            );
            let param_names = fn_param_names(item_fn);
            let param_types = sugar_param_types(item_fn);
            let original_param_types = sugar_original_param_types(item_fn);
            let return_type = sugar_return_type(item_fn);
            let generic_params = sugar_generic_params(item_fn);
            let visibility = match &item_fn.vis {
                syn::Visibility::Public(_) => "pub",
                syn::Visibility::Restricted(_) => "pub(crate)",
                syn::Visibility::Inherited => "",
            };
            let function_symbol = format!("{fn_name}@{rel}");
            let fallback_function_symbol = format!("{}@{rel}", target.source_name);
            let witnesses = match witnesses_by_symbol
                .get(&function_symbol)
                .or_else(|| witnesses_by_symbol.get(&fallback_function_symbol))
            {
                Some(witnesses) => witnesses.clone(),
                None => Vec::new(),
            };

            let doc_lines = sugar_doc_lines(item_fn);
            // #1075/A9 federation invariant: the bind-lift-entry is a
            // CID-bearing surface (it is embedded verbatim as arg[0] of the
            // federated `concept:bind-result` payload and feeds NamedTerm via
            // `bind_term_document`). Declared source signature types MUST NOT
            // ride here, or typed-Rust and untyped-Python bind to DIFFERENT
            // CIDs and seam-4 federation byte-identity breaks (regression
            // 48b343a43). The Java boundary emitter genuinely needs these
            // types to realize the interface signature, so they travel on the
            // CID-INVISIBLE realize sidecar (`realize_*`, stripped by
            // `strip_realize_sidecar_from_lift_term` before hashing) — the
            // same channel #1448 already uses for the sugar/realizer path.
            let mut entry = json!({
                "kind": "bind-lift-entry",
                "param_names": param_names,
                "realize_param_types": param_types,
                "realize_original_param_types": original_param_types,
                "realize_return_type": return_type,
                "generic_params": generic_params,
                "visibility": visibility,
                "term_shape": cvalue_to_json(&term_shape),
                "term_shape_cid": term_shape_cid,
                "operand_bindings": operand_bindings,
                "source_function_name": target.source_name,
                "witnesses": witnesses,
                "doc_lines": doc_lines,
            });
            if let Some(concept_annotation) = &target.concept_annotation {
                entry["concept_annotation"] = json!(concept_annotation);
            }
            entries.push(entry);
        }

        for sugar_target in collect_sugar_targets(&file, &src) {
            let SugarTarget {
                op,
                library,
                version,
                loss,
                observed_dimension,
                item_fn,
                totality_result_ok,
            } = sugar_target;
            let op_cid = canonical_local_op_cid(&op)
                .map_err(|e| format!("derive op cid for sugar binding `{op}`: {e}"))?;
            let param_names = fn_param_names(&item_fn);
            let param_types = sugar_param_types(&item_fn);
            let original_param_types = sugar_original_param_types(&item_fn);
            let generic_params = sugar_generic_params(&item_fn);
            let return_type = sugar_return_type(&item_fn);
            let term_shape = term_shape_for_fn(&item_fn);
            let term_shape_cid = blake3_512_of(encode_jcs(&term_shape).as_bytes());
            let operand_bindings = operand_bindings_for_fn(&item_fn);
            let sig_shape = CValue::object([
                (
                    "param_names",
                    CValue::array(
                        param_names
                            .iter()
                            .map(|name| CValue::string(name.clone()))
                            .collect(),
                    ),
                ),
                (
                    "param_types",
                    CValue::array(
                        param_types
                            .iter()
                            .map(|param_type| CValue::string(param_type.clone()))
                            .collect(),
                    ),
                ),
                ("return_type", CValue::string(return_type.clone())),
            ]);
            let signature_shape_cid = blake3_512_of(encode_jcs(&sig_shape).as_bytes());

            // #1361 chunk 2 part B / #1355: emit concept-hub sort CIDs for
            // each parameter type. The rust kit's @sugar lift translates
            // its source syntax to substrate-canonical sort identities AT
            // the kit/substrate boundary. Parallel to other source-lifter
            // boundary emissions.
            // Kit-internal sort labels (rust:Int, rust:Str, ...) stay inside
            // the rust kit; only concept-hub CIDs cross to substrate. Empty
            // string in a slot signals "kit has no morphism for this type" —
            // substrate-honest gap signal for downstream refusal.
            let mut parametric_sort_expansions: Vec<
                libsugar::core::source_aliases::ParametricSortExpansion,
            > = Vec::new();
            let param_sort_cids: Vec<String> = param_types
                .iter()
                .map(|t| {
                    match rust_source_type_to_concept_hub_sort_cid(
                        t,
                        &mut parametric_sort_expansions,
                    ) {
                        Some(cid) => cid,
                        None => String::new(),
                    }
                })
                .collect();
            let return_sort_cid = match rust_source_type_to_concept_hub_sort_cid(
                &return_type,
                &mut parametric_sort_expansions,
            ) {
                Some(cid) => cid,
                None => String::new(),
            };
            let doc_lines_sb = sugar_doc_lines(&item_fn);
            let mut entry = json!({
                "kind": "library-sugar-binding-entry",
                "target_language": "rust",
                "target_library_tag": library,
                "op_cid": op_cid,
                "source_function_name": item_fn.sig.ident.to_string(),
                "visibility": match &item_fn.vis {
                    syn::Visibility::Public(_) => "pub",
                    syn::Visibility::Restricted(_) => "pub(crate)",
                    syn::Visibility::Inherited => "",
                },
                "generic_params": generic_params,
                "original_param_types": original_param_types,
                "param_names": param_names,
                "param_types": param_types,
                "param_sort_cids": param_sort_cids,
                "return_type": return_type,
                "return_sort_cid": return_sort_cid,
                "term_shape": cvalue_to_json(&term_shape),
                "term_shape_cid": term_shape_cid,
                "operand_bindings": operand_bindings,
                "signature_shape_cid": signature_shape_cid,
                "loss_record_contribution": {
                    "form": "literal",
                    "value": { "entries": loss },
                },
                "body_source": sugar_body_source(&rel, &src, &item_fn),
                "doc_lines": doc_lines_sb,
            });
            // #1369: parametric content-addressing — emit expansions for any
            // composite CIDs the signature contains. Realize plugin reads
            // these to decompose composite CIDs into (constructor, args)
            // for parameterized morphism dispatch.
            if !parametric_sort_expansions.is_empty() {
                entry["parametric_sort_expansions"] =
                    serde_json::to_value(&parametric_sort_expansions).unwrap_or_else(|_| json!([]));
            }
            if let Some(observed) = observed_dimension {
                entry["observed_dimension"] = json!(observed);
            }
            // #1357: surface the optional version pin on the
            // binding entry so downstream materialize dispatch (#1359) can
            // narrow by them. Absent on the annotation → absent in the
            // emitted JSON (NOT empty strings — null/missing is the substrate
            // signal for "this axis floats").
            if let Some(v) = version {
                entry["library_version"] = json!(v);
            }
            entries.push(entry);

            // #1580: emit a SIBLING `contract` decl per
            // `#[sugar::sugar(...)]` annotation. cmd_mint mints
            // this as a regular (non-body-bearing) contract memento.
            // The post is normally the trivial identity ctor —
            // `function_name(<vars>)` — which makes the verifier's
            // enumerate_callsites find a callsite at this ctor name.
            //
            // TOTALITY EXCEPTION (Phase-2 Tier D-lib): when the sugar
            // annotation carries `totality = "result_ok"` and the
            // return type is Result, the post is the AXIOM `is_ok(result)`.
            // This is one exact singleton shape callee_post_guard_fact accepts.
            // With this post, bridges emitted by the recognize lane discharge
            // the downstream `.unwrap()` as panic-safe. Sound: only functions
            // explicitly marked totality get this post; inference from arg
            // types is rejected (refuse-floor).
            let fn_name = item_fn.sig.ident.to_string();
            let post = if totality_result_ok {
                // Singleton totality post: is_ok(result).
                // Shape: {"kind":"atomic","name":"is_ok","args":[{"kind":"var","name":"result"}]}
                json!({
                    "kind": "atomic",
                    "name": panic_freedom::IS_OK,
                    "args": [{ "kind": "var", "name": "result" }],
                })
            } else {
                let arg_terms: Vec<Value> = param_names
                    .iter()
                    .map(|name| json!({ "kind": "var", "name": name }))
                    .collect();
                json!({
                    "kind": "atomic",
                    "args": [{
                        "kind": "ctor",
                        "name": fn_name,
                        "args": arg_terms,
                    }],
                })
            };
            entries.push(json!({
                "kind": "contract",
                "name": fn_name,
                "post": post,
                "outBinding": "out",
            }));
        }

        // Derive-from-source lane (mirrors python's universal lift). Anything is
        // liftable sugar: when the `library-bindings` layer is active and the
        // crate has a readable `[package].name`, every MODULE-LEVEL `fn` (ANY
        // visibility) with NO `#[sugar::sugar]` and NO `#[sugar::boundary]`
        // attribute ALSO emits a `library-sugar-binding-entry` —
        // `binding_origin: "derived"`, `target_library_tag = <crate>`,
        // `symbol = <crate>.<fn>`, carrying the SAME SourceMemento
        // (`sugar_body_source`) the tagged path emits. The body source CIDs are
        // byte-identical to the tagged path for the same fn (same locus, same
        // hashing), so the Source Oracle resolves a derived binding exactly as it
        // does a tagged one. We reuse the tagged path's entry builder; only the
        // symbol/tag/origin provenance differs (path-derived vs attribute-
        // derived). Visibility is NOT a gate. Only structural skips remain: a
        // still-tagged fn (emitted above), a `#[sugar::boundary]` consumer
        // stub, and test fns. Impl methods + nested-module fns are the next
        // increment of "anything" (a structural walk, not an access rule). No
        // no name-keyed identity is emitted, so `recognize` (which requires a
        // pinned op CID) keeps the
        // project's own functions out of its published match-template set; the
        // derived binding is materialize-only, exactly like python's derived
        // path.
        if let Some(crate_tag) = &derived_crate_tag {
            for item in &file.items {
                let syn::Item::Fn(item_fn) = item else {
                    continue;
                };
                // Anything is liftable sugar: visibility is NOT a gate. A
                // crate-private fn is as derivable as a `pub` one — its body is
                // real source the oracle resolves and CID-verifies just the
                // same. The only skips below are structural, not access-level.
                // The tag is OPTIONAL, not removed: a fn that still carries
                // `#[sugar::sugar]` is emitted by the tagged path above —
                // skip it here so we never double-emit.
                if extract_sugar_attr(item_fn).is_some() {
                    continue;
                }
                // Tests are not a vendored surface.
                if is_rust_test_fn(item_fn) {
                    continue;
                }

                let fn_name = item_fn.sig.ident.to_string();
                let symbol = format!("{crate_tag}.{fn_name}");
                let op_cid = canonical_local_op_cid(&symbol)
                    .map_err(|err| format!("failed to derive op_cid for `{symbol}`: {err}"))?;
                let param_names = fn_param_names(item_fn);
                let param_types = sugar_param_types(item_fn);
                let original_param_types = sugar_original_param_types(item_fn);
                let generic_params = sugar_generic_params(item_fn);
                let return_type = sugar_return_type(item_fn);
                let term_shape = term_shape_for_fn(item_fn);
                let term_shape_cid = blake3_512_of(encode_jcs(&term_shape).as_bytes());
                let operand_bindings = operand_bindings_for_fn(item_fn);
                let sig_shape = CValue::object([
                    (
                        "param_names",
                        CValue::array(
                            param_names
                                .iter()
                                .map(|name| CValue::string(name.clone()))
                                .collect(),
                        ),
                    ),
                    (
                        "param_types",
                        CValue::array(
                            param_types
                                .iter()
                                .map(|param_type| CValue::string(param_type.clone()))
                                .collect(),
                        ),
                    ),
                    ("return_type", CValue::string(return_type.clone())),
                ]);
                let signature_shape_cid = blake3_512_of(encode_jcs(&sig_shape).as_bytes());
                let mut parametric_sort_expansions: Vec<
                    libsugar::core::source_aliases::ParametricSortExpansion,
                > = Vec::new();
                let param_sort_cids: Vec<String> = param_types
                    .iter()
                    .map(|t| {
                        match rust_source_type_to_concept_hub_sort_cid(
                            t,
                            &mut parametric_sort_expansions,
                        ) {
                            Some(cid) => cid,
                            None => String::new(),
                        }
                    })
                    .collect();
                let return_sort_cid = match rust_source_type_to_concept_hub_sort_cid(
                    &return_type,
                    &mut parametric_sort_expansions,
                ) {
                    Some(cid) => cid,
                    None => String::new(),
                };
                let doc_lines = sugar_doc_lines(item_fn);
                let mut entry = json!({
                    "kind": "library-sugar-binding-entry",
                    "target_language": "rust",
                    "target_library_tag": crate_tag,
                    "symbol": symbol,
                    "op_cid": op_cid,
                    "binding_origin": "derived",
                    "source_function_name": fn_name,
                    "visibility": match &item_fn.vis {
                        syn::Visibility::Public(_) => "pub",
                        _ => "private",
                    },
                    "generic_params": generic_params,
                    "original_param_types": original_param_types,
                    "param_names": param_names,
                    "param_types": param_types,
                    "param_sort_cids": param_sort_cids,
                    "return_type": return_type,
                    "return_sort_cid": return_sort_cid,
                    "term_shape": cvalue_to_json(&term_shape),
                    "term_shape_cid": term_shape_cid,
                    "operand_bindings": operand_bindings,
                    "signature_shape_cid": signature_shape_cid,
                    "loss_record_contribution": {
                        "form": "literal",
                        "value": { "entries": Vec::<String>::new() },
                    },
                    "body_source": sugar_body_source(&rel, &src, item_fn),
                    "doc_lines": doc_lines,
                });
                if !parametric_sort_expansions.is_empty() {
                    entry["parametric_sort_expansions"] =
                        serde_json::to_value(&parametric_sort_expansions)
                            .unwrap_or_else(|_| json!([]));
                }
                entries.push(entry);
            }
        }

        // Module-level item declarations: const, static, struct, enum,
        // trait. Each becomes its own substrate IR entry so the target
        // plugin can emit native equivalents (java class+interface+
        // constants from rust mod-level items, no hand-written code).
        use quote::ToTokens;
        for item in &file.items {
            // const X: T = value;
            if let syn::Item::Const(c) = item {
                let name = c.ident.to_string();
                let ty = c.ty.to_token_stream().to_string().replace(' ', "");
                let value = c.expr.to_token_stream().to_string();
                let visibility = match &c.vis {
                    syn::Visibility::Public(_) => "pub",
                    syn::Visibility::Restricted(_) => "pub(crate)",
                    syn::Visibility::Inherited => "",
                };
                entries.push(json!({
                    "kind": "const-decl",
                    "name": name,
                    "type": ty,
                    "value": value,
                    "visibility": visibility,
                }));
            }
            // struct X { field: T, ... }
            if let syn::Item::Struct(s) = item {
                let name = s.ident.to_string();
                let visibility = match &s.vis {
                    syn::Visibility::Public(_) => "pub",
                    syn::Visibility::Restricted(_) => "pub(crate)",
                    syn::Visibility::Inherited => "",
                };
                let mut fields: Vec<Value> = Vec::new();
                if let syn::Fields::Named(named) = &s.fields {
                    for f in &named.named {
                        let Some(ident) = f.ident.as_ref() else {
                            continue;
                        };
                        let fname = ident.to_string();
                        let fty = f.ty.to_token_stream().to_string().replace(' ', "");
                        fields.push(json!({"name": fname, "type": fty}));
                    }
                }
                entries.push(json!({
                    "kind": "struct-decl",
                    "name": name,
                    "visibility": visibility,
                    "fields": fields,
                }));
            }
            // enum X { Variant1(T), Variant2 }
            if let syn::Item::Enum(e) = item {
                let name = e.ident.to_string();
                let visibility = match &e.vis {
                    syn::Visibility::Public(_) => "pub",
                    syn::Visibility::Restricted(_) => "pub(crate)",
                    syn::Visibility::Inherited => "",
                };
                let mut variants: Vec<Value> = Vec::new();
                for v in &e.variants {
                    let vname = v.ident.to_string();
                    let mut payload_types: Vec<String> = Vec::new();
                    match &v.fields {
                        syn::Fields::Unnamed(unn) => {
                            for f in &unn.unnamed {
                                payload_types
                                    .push(f.ty.to_token_stream().to_string().replace(' ', ""));
                            }
                        }
                        syn::Fields::Named(_) => {
                            // struct-style variant; skip detail for now (named-fields
                            // variant data is future work — pull as a struct with the
                            // variant's name).
                        }
                        syn::Fields::Unit => {}
                    }
                    variants.push(json!({
                        "name": vname,
                        "payload_types": payload_types,
                    }));
                }
                entries.push(json!({
                    "kind": "enum-decl",
                    "name": name,
                    "visibility": visibility,
                    "variants": variants,
                }));
            }
            // Original trait-decl handling kept below — fall through.
            if let syn::Item::Trait(t) = item {
                let trait_name = t.ident.to_string();
                let visibility = match &t.vis {
                    syn::Visibility::Public(_) => "pub",
                    syn::Visibility::Restricted(_) => "pub(crate)",
                    syn::Visibility::Inherited => "",
                };
                let mut methods: Vec<Value> = Vec::new();
                for trait_item in &t.items {
                    if let syn::TraitItem::Fn(m) = trait_item {
                        let name = m.sig.ident.to_string();
                        let return_type = match &m.sig.output {
                            syn::ReturnType::Default => "()".to_string(),
                            syn::ReturnType::Type(_, ty) => {
                                ty.to_token_stream().to_string().replace(' ', "")
                            }
                        };
                        let mut param_names: Vec<String> = Vec::new();
                        let mut param_types: Vec<String> = Vec::new();
                        for input in &m.sig.inputs {
                            match input {
                                syn::FnArg::Receiver(_) => {
                                    // Skip `&self` / `&mut self` — java interface methods are implicit.
                                }
                                syn::FnArg::Typed(pt) => {
                                    if let syn::Pat::Ident(pi) = &*pt.pat {
                                        param_names.push(pi.ident.to_string());
                                    } else {
                                        param_names.push(pt.pat.to_token_stream().to_string());
                                    }
                                    param_types
                                        .push(pt.ty.to_token_stream().to_string().replace(' ', ""));
                                }
                            }
                        }
                        methods.push(json!({
                            "name": name,
                            "param_names": param_names,
                            "param_types": param_types,
                            "return_type": return_type,
                        }));
                    }
                }
                entries.push(json!({
                    "kind": "trait-decl",
                    "name": trait_name,
                    "visibility": visibility,
                    "methods": methods,
                }));
            }
        }
    }

    Ok(json!({
        "kind": "ir-document",
        "ir": entries,
        "diagnostics": diagnostics,
    }))
}

fn lift_emit_mode(params: &Value) -> Option<&str> {
    params
        .get("options")
        .and_then(|options| options.get("emit"))
        .and_then(|value| value.as_str())
}

fn function_contract_lift(params: &Value) -> Result<Value, String> {
    let workspace_root = params
        .get("workspace_root")
        .and_then(|v| v.as_str())
        .ok_or("missing `workspace_root`")?;
    let source_paths: Vec<String> = params
        .get("source_paths")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_else(|| vec![".".to_string()]);

    let root = PathBuf::from(workspace_root);
    // The crate these contracts belong to (Tier 1): the Cargo package name of
    // the project being lifted, normalized. Stamped onto every contract so a
    // consumer that vendors this proof can key a call site by (crate, leaf).
    // Single-crate self-application projects (the only ones minted today) have
    // one package per workspace_root; a true multi-crate workspace would need
    // per-scan-root names, noted as a limitation.
    let current_crate = crate_name_for(&root).ok_or_else(|| {
        format!(
            "function_contract_lift: missing Cargo package name for workspace root `{}`",
            root.display()
        )
    })?;
    let infallible_serialize = InfallibleSerializeManifest::load(&root)?;
    let function_postconditions = FunctionPostconditionsManifest::load(&root)?;
    let mut entries: Vec<Value> = Vec::new();
    let mut diagnostics: Vec<Value> = Vec::new();
    let mut source_loci: Vec<Value> = Vec::new();
    let mut source_mementos: Vec<Value> = Vec::new();
    let mut factory_walk: Vec<Value> = Vec::new();
    let mut visited: std::collections::BTreeSet<PathBuf> = Default::default();

    for scan_root in lift_scan_roots(&root, &source_paths) {
        let src_dir = scan_root.join("src");
        let walk_root: &Path = if src_dir.is_dir() {
            &src_dir
        } else {
            scan_root.as_path()
        };
        collect_rs_files(walk_root, &mut visited);
        if walk_root != scan_root.as_path() {
            collect_rs_files_shallow(scan_root.as_path(), &mut visited);
        }
    }

    for path in &visited {
        let src = match std::fs::read_to_string(path) {
            Ok(s) => s,
            Err(e) => {
                diagnostics.push(diagnostic(
                    "read-error",
                    path.display().to_string(),
                    e.to_string(),
                ));
                continue;
            }
        };
        let file = match syn::parse_file(&src) {
            Ok(f) => f,
            Err(e) => {
                diagnostics.push(diagnostic(
                    "parse-error",
                    path.display().to_string(),
                    e.to_string(),
                ));
                continue;
            }
        };
        let rel = relative_display_path(path, &root);
        let return_facts = collect_explicit_function_return_facts(&file);
        let local_free_functions = collect_local_free_function_names(&file);
        let pure_free_guard_rules = pure_free_guard_rules_for_function_post_lift(
            &function_postconditions,
            &current_crate,
            rel.as_str(),
            &local_free_functions,
        );

        for target in collect_function_contract_targets(&file) {
            // Phase-2 Tier D-lib: when a sugar function carries `totality =
            // "result_ok"`, the minted post is the AXIOM `is_ok(result)`
            // rather than the body-derived reflexive post. The axiom flows
            // into canonical_bytes and CID via the override path so the
            // contract is self-consistent. This is the ONLY totality
            // mechanism; inference from types is unsound (a non-Value Result
            // may be fallible). The gate is explicit opt-in in the attribute.
            // Singleton totality post: is_ok(result).
            // Shape: {"kind":"atomic","name":"is_ok","args":[{"kind":"var","name":"result"}]}
            // Matches the exact shape callee_post_guard_fact requires (body_discharge.rs).
            let post_formula = if target.totality_result_ok {
                IrFormula::Atomic {
                    name: panic_freedom::IS_OK.to_string(),
                    args: vec![IrTerm::Var {
                        name: "result".to_string(),
                    }],
                }
            } else {
                lift_function_postcondition_with_return_facts_and_pure_free_guards(
                    &target.item_fn,
                    &return_facts,
                    &pure_free_guard_rules,
                )
                .into_formula()
            };
            if !target.totality_result_ok {
                factory_walk.extend(function_contract_body_factory_walk_rows(
                    rel.as_str(),
                    &src,
                    &target,
                    &post_formula,
                ));
            }
            let contract = build_function_contract_with_file_and_post_override(
                &target.item_fn,
                None,
                Some(rel.as_str()),
                Some(post_formula),
            );
            // Totality-axiom contracts are body-discharge-INELIGIBLE (no
            // result equation, by design: the post is an axiom, not derived
            // from the body). Mark with a distinct reason so the loud
            // diagnostic does not fire for expected ineligibility.
            let (body_discharge_eligible, refusal_reason) = if target.totality_result_ok {
                (false, Some("totality-axiom".to_string()))
            } else {
                body_discharge_eligibility(&contract.post, &contract.formals)
            };
            let mut entry: Value =
                serde_json::from_slice(&contract.canonical_bytes).map_err(|e| e.to_string())?;
            entry["name"] = json!(target.fn_name.clone());
            entry["fn_name"] = json!(target.fn_name.clone());
            entry["contract_cid"] = json!(contract.cid.clone());
            entry["bridgeSourceSymbol"] = json!(target.source_name.clone());
            entry["bodyDischargeEligible"] = json!(body_discharge_eligible);
            if let Some(reason) = refusal_reason {
                entry["bodyDischargeRefusalReason"] = json!(reason.clone());
                // Suppress the loud body-discharge-gap diagnostic for the
                // totality-axiom case: ineligibility is expected and sound.
                if !target.totality_result_ok {
                    diagnostics.push(json!({
                        "kind": "body-discharge-gap",
                        "reason": reason,
                        "function": target.fn_name,
                        "file": rel,
                    }));
                }
            }
            if !current_crate.is_empty() {
                entry["library"] = json!(current_crate.clone());
            }
            // PANIC-LOCUS PRESERVATION (#1745): each panic-leaf call in this
            // function's body (e.g. `x.unwrap()`) is an abstract ctor term in
            // `post` with NO source span -- two functions calling `.unwrap()`
            // both lift to the bare ctor `method:unwrap`, and the verifier's
            // per-symbol bridge index collapses their distinct call-site lines
            // to one (last-writer-wins). The line is the call OCCURRENCE's
            // provenance, and the occurrence lives in THIS function's contract,
            // so carry it here, scoped to this contract, keyed by the lifted
            // argument term so enumerate can match a specific occurrence (not by
            // fragile positional order). Emitted OUTSIDE the contract content CID
            // (added after `canonical_bytes`, like `name`/`fn_name`): the locus
            // is developer-facing provenance, not part of what is proven.
            let panic_loci = collect_panic_loci(&target.item_fn, rel.as_str());
            if !panic_loci.is_empty() {
                entry["panicLoci"] = json!(panic_loci);
            }
            let source_memento = source_memento_of_named_item_fn(
                rel.as_str(),
                &src,
                &target.fn_name,
                &target.item_fn,
            )
            .to_json();
            entry["sourceWarrants"] = json!([source_memento.clone()]);
            source_loci.push(function_contract_source_locus(
                rel.as_str(),
                &target,
                &source_memento,
            )?);
            source_mementos.push(source_memento);
            entries.push(entry);
        }
    }

    emit_infallible_serialize_contracts(&infallible_serialize, &current_crate, &mut entries)?;
    emit_function_postcondition_contracts(&function_postconditions, &current_crate, &mut entries)?;
    emit_builtin_std_panic_partial_contracts(&mut entries);

    // Producer-side visibility. This surface emits the contracts that the
    // implication matcher later bridges into; a collapse here (e.g. a soundness
    // gate flipping most contracts to body-discharge-ineligible) was previously
    // INVISIBLE because nothing logged the eligible-vs-ineligible split. Log it
    // loudly: N fn-contracts, M body-discharge-eligible, and the refusal reasons
    // (which ctors the body-discharge spine cannot yet encode) broken down, so a
    // future regression of this size is loud, not silent.
    let total_fnc = entries.len();
    let eligible = entries
        .iter()
        .filter(|e| {
            body_discharge_policy_from_object_with_default(e, false).body_discharge_eligible
        })
        .count();
    let mut refusal_by_reason: std::collections::BTreeMap<String, usize> =
        std::collections::BTreeMap::new();
    for e in &entries {
        let body_policy = body_discharge_policy_from_object_with_default(e, false);
        if !body_policy.body_discharge_eligible {
            if let Some(reason) = body_policy.body_discharge_refusal_reason {
                *refusal_by_reason.entry(reason).or_insert(0) += 1;
            }
        }
    }
    let refusal_breakdown = refusal_by_reason
        .iter()
        .map(|(r, n)| format!("{r}={n}"))
        .collect::<Vec<_>>()
        .join(", ");
    let ineligible = total_fnc - eligible;
    // LOUD by design. If the body-discharge gate refuses the MAJORITY of a
    // crate's production contracts, that is either a genuine property of the
    // code or a regression in the gate/encoding (e.g. #1696 flipping 309/310 to
    // ineligible). Either way it caps how much the substrate can ever discharge,
    // so it must not hide in a DEBUG line. WARN with the ctor breakdown that
    // names exactly what the body-discharge spine cannot encode.
    if total_fnc > 0 && ineligible * 2 > total_fnc {
        warn!(
            fn_contracts = total_fnc,
            body_discharge_eligible = eligible,
            body_discharge_ineligible = ineligible,
            "function_contract_lift: ONLY {}/{} fn-contracts are body-discharge-eligible; {} are REFUSED by the body-discharge spine and cap self-discharge [unencodable post terms: {}]",
            eligible,
            total_fnc,
            ineligible,
            refusal_breakdown
        );
    } else {
        info!(
            fn_contracts = total_fnc,
            body_discharge_eligible = eligible,
            body_discharge_ineligible = ineligible,
            "function_contract_lift: {} fn-contracts ({} body-discharge-eligible, {} ineligible) [refusals: {}]",
            total_fnc,
            eligible,
            ineligible,
            refusal_breakdown
        );
    }

    let source_ledger = source_ledger_for_loci(&source_loci);
    let factory_audit_summary = factory_audit_summary_from_walk(&factory_walk);
    Ok(json!({
        "kind": "ir-document",
        "ir": entries,
        "diagnostics": diagnostics,
        "refusals": [],
        "factoryAuditSummary": factory_audit_summary,
        "sourceLedger": source_ledger.clone(),
        "sourceAudits": [json!({
            "role": "rust-fn-contracts",
            "universe_kind": "function-contract",
            "totals": source_ledger,
            "loci": source_loci,
        })],
        "sourceMementos": source_mementos,
    }))
}

fn function_contract_body_factory_walk_rows(
    rel: &str,
    src: &str,
    target: &FunctionContractLiftTarget,
    post_formula: &IrFormula,
) -> Vec<Value> {
    let projection_sites = function_contract_body_projection_sites(rel, src, target);
    if projection_sites.is_empty() {
        return Vec::new();
    }

    function_contract_body_projection_formulas(post_formula)
        .into_iter()
        .enumerate()
        .filter_map(|(idx, formula)| {
            let site = projection_site_for_formula(&formula, &projection_sites)
                .or_else(|| projection_sites.get(idx))
                .or_else(|| projection_sites.last())?;
            let memento = &site.memento;
            Some(json!({
                "file": rel,
                "line": memento.span.start_line,
                "requested_role": "FunctionBodyConstraint",
                "ast_kind": "stmt",
                "selected": "function_contract_body_post",
                "status": "warranted",
                "verdict": "complete",
                "output": "constraints",
                "sourceMemento": memento.to_json(),
                "emittedFormula": serde_json::to_value(&formula)
                    .expect("IrFormula should serialize for factory walk"),
            }))
        })
        .collect()
}

struct FunctionContractBodyProjectionSite {
    memento: SourceMemento,
    bound_name: Option<String>,
    result_position: bool,
}

fn function_contract_body_projection_sites(
    rel: &str,
    src: &str,
    target: &FunctionContractLiftTarget,
) -> Vec<FunctionContractBodyProjectionSite> {
    let stmts = &target.item_fn.block.stmts;
    stmts
        .iter()
        .enumerate()
        .filter_map(|(idx, stmt)| {
            let result_position = statement_produces_result(stmt, idx, stmts.len());
            let memento =
                function_contract_projection_site_memento(rel, src, target, stmt, result_position)?;
            Some(FunctionContractBodyProjectionSite {
                memento,
                bound_name: statement_bound_name(stmt),
                result_position,
            })
        })
        .collect()
}

fn function_contract_projection_site_memento(
    rel: &str,
    src: &str,
    target: &FunctionContractLiftTarget,
    stmt: &syn::Stmt,
    result_position: bool,
) -> Option<SourceMemento> {
    if result_position {
        if let syn::Stmt::Expr(expr, _) = stmt {
            if let Some(memento) = source_memento_of_term_span(
                rel,
                src,
                expr.span(),
                &target.fn_name,
                &target.item_fn.sig,
                &target.item_fn.block,
            ) {
                return Some(memento);
            }
        }
    }
    source_memento_of_statement_span(
        rel,
        src,
        stmt.span(),
        &target.fn_name,
        &target.item_fn.sig,
        &target.item_fn.block,
    )
}

fn projection_site_for_formula<'a>(
    formula: &IrFormula,
    sites: &'a [FunctionContractBodyProjectionSite],
) -> Option<&'a FunctionContractBodyProjectionSite> {
    match formula_lhs_var_name(formula) {
        Some("result") => sites.iter().find(|site| site.result_position),
        Some(lhs) => sites
            .iter()
            .find(|site| site.bound_name.as_deref() == Some(lhs)),
        None => None,
    }
}

fn formula_lhs_var_name(formula: &IrFormula) -> Option<&str> {
    let IrFormula::Atomic { name, args } = formula else {
        return None;
    };
    if name != "=" {
        return None;
    }
    let Some(IrTerm::Var { name }) = args.first() else {
        return None;
    };
    Some(name.as_str())
}

fn statement_bound_name(stmt: &syn::Stmt) -> Option<String> {
    let syn::Stmt::Local(local) = stmt else {
        return None;
    };
    local_binding_ident_name(local)
}

fn local_binding_ident_name(local: &syn::Local) -> Option<String> {
    match &local.pat {
        syn::Pat::Ident(ident) => Some(ident.ident.to_string()),
        syn::Pat::Type(typed) => match &*typed.pat {
            syn::Pat::Ident(ident) => Some(ident.ident.to_string()),
            _ => None,
        },
        _ => None,
    }
}

fn statement_produces_result(stmt: &syn::Stmt, idx: usize, total: usize) -> bool {
    match stmt {
        syn::Stmt::Expr(syn::Expr::Return(_), _) => true,
        syn::Stmt::Expr(_, None) => idx + 1 == total,
        _ => false,
    }
}

fn function_contract_body_projection_formulas(post_formula: &IrFormula) -> Vec<IrFormula> {
    let mut formulas = Vec::new();
    push_function_contract_body_projection_formula(post_formula, &mut formulas);
    formulas
}

fn push_function_contract_body_projection_formula(formula: &IrFormula, out: &mut Vec<IrFormula>) {
    match formula {
        IrFormula::And { operands } => {
            for operand in operands {
                push_function_contract_body_projection_formula(operand, out);
            }
        }
        IrFormula::Atomic { name, args } if name == "=" && args.len() == 2 => {
            push_result_term_projection_formulas(args[0].clone(), &args[1], out);
        }
        _ => out.push(formula.clone()),
    }
}

fn push_result_term_projection_formulas(lhs: IrTerm, rhs: &IrTerm, out: &mut Vec<IrFormula>) {
    match rhs {
        IrTerm::Let { bindings, body } => {
            for binding in bindings {
                out.push(IrFormula::Atomic {
                    name: "=".to_string(),
                    args: vec![
                        IrTerm::Var {
                            name: binding.name.clone(),
                        },
                        binding.bound_term.clone(),
                    ],
                });
            }
            push_result_term_projection_formulas(lhs, body, out);
        }
        _ => out.push(IrFormula::Atomic {
            name: "=".to_string(),
            args: vec![lhs, rhs.clone()],
        }),
    }
}

fn factory_audit_summary_from_walk(factory_walk: &[Value]) -> Value {
    let warranted = factory_walk
        .iter()
        .filter(|row| row.get("status").and_then(Value::as_str) == Some("warranted"))
        .count();
    json!({
        "sites": factory_walk.len(),
        "emittedRows": factory_walk.len(),
        "omittedRows": 0,
        "totalRows": factory_walk.len(),
        "complete": true,
        "statusCounts": {
            "warranted": warranted,
            "refused": 0,
            "support": 0,
            "unresolved": 0,
        },
        "unresolvedSites": [],
        "factoryWalk": factory_walk,
    })
}

fn function_contract_source_locus(
    rel: &str,
    target: &FunctionContractLiftTarget,
    source_memento: &Value,
) -> Result<Value, String> {
    let span = source_memento
        .get("span")
        .ok_or("function contract source memento missing `span`")?;
    let line = span
        .get("start_line")
        .and_then(Value::as_u64)
        .ok_or("function contract source memento missing `span.start_line`")?;
    let col = span
        .get("start_col")
        .and_then(Value::as_u64)
        .ok_or("function contract source memento missing `span.start_col`")?;
    let source_cid = source_memento
        .get("source_cid")
        .cloned()
        .ok_or("function contract source memento missing `source_cid`")?;
    Ok(json!({
        "file": rel,
        "role": "rust-fn-contracts",
        "universe_kind": "function-contract",
        "ast_kind": if target.fn_name.contains("::") { "method" } else { "fn" },
        "ast_path": target.fn_name.clone(),
        "sourceFunctionName": target.fn_name.clone(),
        "line": line,
        "col": col,
        "source_cid": source_cid,
        "status": "warranted",
    }))
}

fn source_ledger_for_loci(loci: &[Value]) -> Value {
    let count = |status: &str| {
        loci.iter()
            .filter(|locus| locus.get("status").and_then(Value::as_str) == Some(status))
            .count()
    };
    json!({
        "source_loci": loci.len(),
        "source_warranted": count("warranted"),
        "source_support": count("support"),
        "source_refused": count("refused"),
        "source_inactive": count("inactive"),
        "source_refuted": count("refuted"),
        "unclassified_source": count("unclassified"),
    })
}

fn emit_infallible_serialize_contracts(
    manifest: &InfallibleSerializeManifest,
    current_crate: &str,
    entries: &mut Vec<Value>,
) -> Result<(), String> {
    if manifest.is_empty() {
        return Ok(());
    }
    if current_crate.is_empty() {
        return Err(
            "infallible_serialize.toml requires a Cargo package name for type_crate matching"
                .to_string(),
        );
    }
    for rule in &manifest.rules {
        debug!(
            function = %rule.function,
            type_crate = %rule.type_id.krate,
            type_name = %rule.type_id.head,
            contract_library = %current_crate,
            contract = %rule.contract,
            reason = %rule.reason,
            "function_contract_lift: emitting project-local infallible serde_json totality contract"
        );
        entries.push(json!({
            "kind": "contract",
            "name": rule.contract,
            "post": singleton_result_post_json(panic_freedom::IS_OK),
            "outBinding": "out",
            "bodyDischargeEligible": false,
            "bodyDischargeRefusalReason": "totality-axiom",
            "library": current_crate,
        }));
    }
    Ok(())
}

fn emit_function_postcondition_contracts(
    manifest: &FunctionPostconditionsManifest,
    current_crate: &str,
    entries: &mut Vec<Value>,
) -> Result<(), String> {
    if manifest.is_empty() {
        return Ok(());
    }
    if current_crate.is_empty() {
        return Err(
            "function_postconditions.toml requires a Cargo package name for contract emission"
                .to_string(),
        );
    }
    for rule in &manifest.rules {
        if rule.call_kind == FunctionPostconditionCallKind::Free {
            debug!(
                callee_crate = %rule.callee_crate,
                callee = %rule.callee,
                contract = %rule.contract,
                post_predicate = %rule.post_predicate,
                reason = %rule.reason,
                "function_contract_lift: skipping guard-only pure free-function declaration"
            );
            continue;
        }
        debug!(
            call_kind = ?rule.call_kind,
            callee_crate = %rule.callee_crate,
            callee = %rule.callee,
            contract_library = %current_crate,
            contract = %rule.contract,
            post_predicate = %rule.post_predicate,
            reason = %rule.reason,
            "function_contract_lift: emitting project-local function postcondition contract"
        );
        entries.push(json!({
            "kind": "contract",
            "name": rule.contract,
            "post": singleton_result_post_json(&rule.post_predicate),
            "outBinding": "out",
            "bodyDischargeEligible": false,
            "bodyDischargeRefusalReason": "totality-axiom",
            "library": current_crate,
        }));
    }
    Ok(())
}

fn emit_builtin_std_panic_partial_contracts(entries: &mut Vec<Value>) {
    for partial in [
        StdPanicPartial {
            name: "option_unwrap@std/src/option.rs:1:1",
            predicate: panic_freedom::IS_SOME,
            sort: "Option",
        },
        StdPanicPartial {
            name: "option_expect@std/src/option.rs:1:1",
            predicate: panic_freedom::IS_SOME,
            sort: "Option",
        },
        StdPanicPartial {
            name: "result_unwrap@std/src/result.rs:1:1",
            predicate: panic_freedom::IS_OK,
            sort: "Result",
        },
        StdPanicPartial {
            name: "result_expect@std/src/result.rs:1:1",
            predicate: panic_freedom::IS_OK,
            sort: "Result",
        },
        StdPanicPartial {
            name: "result_unwrap_err@std/src/result.rs:1:1",
            predicate: panic_freedom::IS_ERR,
            sort: "Result",
        },
    ] {
        entries.push(json!({
            "kind": "function-contract",
            "name": partial.name,
            "fn_name": partial.name,
            "formals": ["receiver"],
            "formalSorts": [{"kind": "primitive", "name": partial.sort}],
            "outBinding": "out",
            "pre": {
                "kind": "atomic",
                "name": partial.predicate,
                "args": [{"kind": "var", "name": "receiver"}],
            },
            "bodyDischargeEligible": true,
            "library": "std",
        }));
    }
}

struct StdPanicPartial {
    name: &'static str,
    predicate: &'static str,
    sort: &'static str,
}

fn pure_free_guard_rules_for_function_post_lift(
    manifest: &FunctionPostconditionsManifest,
    current_crate: &str,
    source_file: &str,
    local_free_functions: &BTreeSet<String>,
) -> Vec<PureFreeGuardRule> {
    manifest
        .rules
        .iter()
        .filter_map(|rule| {
            if rule.call_kind != FunctionPostconditionCallKind::Free || !rule.pure {
                return None;
            }
            if rule.callee_crate != current_crate || !local_free_functions.contains(&rule.callee) {
                debug!(
                    callee_crate = %rule.callee_crate,
                    callee = %rule.callee,
                    current_crate = %current_crate,
                    source_file = %source_file,
                    "function_contract_lift: refusing pure-free post-lift guard rule outside current crate/local function set"
                );
                return None;
            }
            if rule.source_file.as_deref().is_some_and(|file| file != source_file) {
                return None;
            }
            if panic_stem_for_post_predicate(&rule.post_predicate).is_none() {
                debug!(
                    callee = %rule.callee,
                    post_predicate = %rule.post_predicate,
                    "function_contract_lift: refusing pure-free post-lift guard rule with unsupported panic predicate"
                );
                return None;
            }
            debug!(
                callee = %rule.callee,
                post_predicate = %rule.post_predicate,
                source_file = %source_file,
                source_line = ?rule.source_line,
                "function_contract_lift: enabling pure-free post-lift guard rule"
            );
            Some(PureFreeGuardRule {
                callee: rule.callee.clone(),
                post_predicate: rule.post_predicate.clone(),
                source_line: rule.source_line,
                allow_line_less_match: true,
            })
        })
        .collect()
}

fn singleton_result_post_json(predicate: &str) -> Value {
    json!({
        "kind": "atomic",
        "name": predicate,
        "args": [{ "kind": "var", "name": "result" }],
    })
}

fn body_discharge_eligibility(post: &IrFormula, formals: &[String]) -> (bool, Option<String>) {
    // A function's self-derived post is `result == <body tail term>`.
    // Eligibility now hinges on ONE thing: does that result equation
    // exist? If it does, the post is dischargeable by REFLEXIVITY: the
    // verifier's SMT lowering encodes every term head (enum/struct ctors
    // like `Ok`/`Err`/`Some`/`tuple`, function/method calls, field
    // projections, `format!`/`json!`/`vec!` macro terms, `ite` from
    // `match`/`if`) as an uninterpreted function symbol, so `result ==
    // f(x)` against a body returning `f(x)` lowers to `f(x) == f(x)` and
    // discharges under any interpretation of `f`. The old whitelist
    // (`+ - * ... and or not`) is obsolete: it refused 309/310 contracts
    // here and caused their call sites to be silently dropped. The only
    // remaining refusal is the honest one: a genuinely unit-returning
    // function has NO result term, so there is nothing to discharge.
    //
    // SOUNDNESS: this is NOT "always eligible -> always pass". The
    // reflexive encoding only proves `T == T`. If a lifter bug ever
    // emits `result == Ok(x)` for a body that returns `Err(x)`, the
    // obligation `Ok(x) == Err(x)` does NOT discharge (z3 refutes it); the
    // claim stays undecidable. Widening eligibility here cannot launder a
    // false post past the solver; it only stops dropping call sites whose
    // obligation the verifier can now honestly encode.
    if libsugar::wp::find_result_equation(post, "result").is_none() {
        return (false, Some("missing-result-equation".to_string()));
    }
    let _ = formals;
    (true, None)
}

fn lift_scan_roots(root: &Path, source_paths: &[String]) -> Vec<PathBuf> {
    if source_paths.is_empty() {
        return vec![root.to_path_buf()];
    }
    source_paths
        .iter()
        .map(|p| {
            let candidate = root.join(p);
            if candidate.is_dir() {
                candidate
            } else {
                root.to_path_buf()
            }
        })
        .collect()
}

fn diagnostic(kind: &str, path: String, detail: String) -> Value {
    json!({
        "kind": kind,
        "path": path,
        "detail": detail,
    })
}

#[derive(Debug, Clone)]
struct BindLiftTarget {
    fn_name: String,
    source_name: String,
    concept_annotation: Option<String>,
    item_fn: syn::ItemFn,
}

#[derive(Debug, Clone)]
struct FunctionContractLiftTarget {
    fn_name: String,
    source_name: String,
    item_fn: syn::ItemFn,
    /// True when the function carries `#[sugar::sugar(totality = "result_ok", ...)]`.
    /// When set, the minted post is the AXIOM `is_ok(result)` (NOT body-derived).
    /// Sound only for wrapper functions whose return type is always Ok by type invariants
    /// (e.g. serde_json::to_string(&Value) is total). Gate: explicit opt-in only.
    totality_result_ok: bool,
}

#[derive(Debug, Clone)]
struct SugarTarget {
    op: String,
    library: String,
    /// #1357: per-#1355, the @sugar annotation may carry a `version`
    /// pin (e.g. "0.39.0"). It floats when absent.
    version: Option<String>,
    loss: Vec<String>,
    observed_dimension: Option<String>,
    item_fn: syn::ItemFn,
    /// Phase-2 Tier D-lib: when `totality = "result_ok"` in the sugar attr
    /// AND the return type is Result, the emitted sibling `kind=contract`
    /// carries post = `is_ok(result)` instead of the identity ctor post.
    totality_result_ok: bool,
}

fn collect_bind_lift_targets_with_source(file: &syn::File, source: &str) -> Vec<BindLiftTarget> {
    let mut targets = Vec::new();
    collect_bind_lift_targets_in_items(&file.items, source, &mut targets);
    targets
}

fn collect_function_contract_targets(file: &syn::File) -> Vec<FunctionContractLiftTarget> {
    let mut targets = Vec::new();
    collect_function_contract_targets_in_items(&file.items, false, &mut targets);
    targets
}

fn collect_local_free_function_names(file: &syn::File) -> BTreeSet<String> {
    let mut names = BTreeSet::new();
    collect_local_free_function_names_in_items(&file.items, false, &mut names);
    names
}

fn collect_local_free_function_names_in_items(
    items: &[syn::Item],
    in_test_context: bool,
    names: &mut BTreeSet<String>,
) {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                if in_test_context || is_rust_test_fn(item_fn) {
                    continue;
                }
                names.insert(item_fn.sig.ident.to_string());
            }
            syn::Item::Mod(module) => {
                let nested_test_context = in_test_context || attrs_include_cfg_test(&module.attrs);
                if let Some((_, nested_items)) = &module.content {
                    collect_local_free_function_names_in_items(
                        nested_items,
                        nested_test_context,
                        names,
                    );
                }
            }
            // sugar-audit: not-mine(local free-function index records only non-test free functions and inline modules)
            _ => {}
        }
    }
}

fn collect_function_contract_targets_in_items(
    items: &[syn::Item],
    in_test_context: bool,
    targets: &mut Vec<FunctionContractLiftTarget>,
) {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                if in_test_context || is_rust_test_fn(item_fn) {
                    continue;
                }
                let fn_name = item_fn.sig.ident.to_string();
                let totality_result_ok = sugar_declares_totality_result_ok(item_fn);
                targets.push(FunctionContractLiftTarget {
                    source_name: fn_name.clone(),
                    fn_name,
                    item_fn: item_fn.clone(),
                    totality_result_ok,
                });
            }
            syn::Item::Impl(impl_block) => {
                if in_test_context || attrs_include_cfg_test(&impl_block.attrs) {
                    continue;
                }
                let Some(qualifier) = impl_function_qualifier(impl_block) else {
                    continue;
                };
                for impl_item in &impl_block.items {
                    let syn::ImplItem::Fn(method) = impl_item else {
                        continue;
                    };
                    let item_fn = item_fn_from_impl_method(method);
                    if !is_liftable_impl_method(impl_block, method) || is_rust_test_fn(&item_fn) {
                        continue;
                    }
                    let source_name = method.sig.ident.to_string();
                    let totality_result_ok = sugar_declares_totality_result_ok(&item_fn);
                    targets.push(FunctionContractLiftTarget {
                        fn_name: format!("{qualifier}::{source_name}"),
                        source_name,
                        item_fn,
                        totality_result_ok,
                    });
                }
            }
            syn::Item::Mod(module) => {
                let nested_test_context = in_test_context || attrs_include_cfg_test(&module.attrs);
                if let Some((_, nested_items)) = &module.content {
                    collect_function_contract_targets_in_items(
                        nested_items,
                        nested_test_context,
                        targets,
                    );
                }
            }
            // sugar-audit: not-mine(function contract targets are functions, liftable methods, and inline modules)
            _ => {}
        }
    }
}

fn is_rust_test_fn(item_fn: &syn::ItemFn) -> bool {
    item_fn.attrs.iter().any(|attr| {
        let path = attr
            .path()
            .segments
            .iter()
            .map(|segment| segment.ident.to_string())
            .collect::<Vec<_>>()
            .join("::");
        matches!(path.as_str(), "test" | "tokio::test" | "async_std::test")
            || is_cfg_test_attr(attr)
    })
}

fn attrs_include_cfg_test(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(is_cfg_test_attr)
}

fn is_cfg_test_attr(attr: &syn::Attribute) -> bool {
    let syn::Meta::List(meta) = &attr.meta else {
        return false;
    };
    attr.path().is_ident("cfg") && meta.tokens.to_string().trim() == "test"
}

fn collect_bind_lift_targets_in_items(
    items: &[syn::Item],
    source: &str,
    targets: &mut Vec<BindLiftTarget>,
) {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                let fn_name = item_fn.sig.ident.to_string();
                targets.push(BindLiftTarget {
                    source_name: fn_name.clone(),
                    fn_name,
                    concept_annotation: concept_annotation_for_fn(source, item_fn),
                    item_fn: item_fn.clone(),
                });
            }
            syn::Item::Impl(impl_block) => {
                let Some(qualifier) = impl_function_qualifier(impl_block) else {
                    continue;
                };
                for impl_item in &impl_block.items {
                    let syn::ImplItem::Fn(method) = impl_item else {
                        continue;
                    };
                    if !is_liftable_impl_method(impl_block, method) {
                        continue;
                    }
                    let source_name = method.sig.ident.to_string();
                    let item_fn = item_fn_from_impl_method(method);
                    targets.push(BindLiftTarget {
                        fn_name: format!("{qualifier}::{source_name}"),
                        source_name,
                        concept_annotation: concept_annotation_for_fn(source, &item_fn),
                        item_fn,
                    });
                }
            }
            syn::Item::Mod(module) => {
                if let Some((_, nested_items)) = &module.content {
                    collect_bind_lift_targets_in_items(nested_items, source, targets);
                }
            }
            // sugar-audit: not-mine(bind lift targets are functions, liftable methods, and inline modules)
            _ => {}
        }
    }
}

fn collect_sugar_targets(file: &syn::File, _src: &str) -> Vec<SugarTarget> {
    let mut targets = Vec::new();
    collect_sugar_targets_in_items(&file.items, &mut targets);
    targets
}

fn collect_sugar_targets_in_items(items: &[syn::Item], targets: &mut Vec<SugarTarget>) {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                if let Some(parsed) = extract_sugar_attr(item_fn) {
                    let totality_result_ok = parsed.totality.as_deref() == Some("result_ok")
                        && is_result_type_fn(item_fn);
                    targets.push(SugarTarget {
                        op: parsed.op,
                        library: parsed.library,
                        version: parsed.version,
                        loss: parsed.loss,
                        observed_dimension: parsed.observed_dimension,
                        item_fn: item_fn.clone(),
                        totality_result_ok,
                    });
                }
            }
            syn::Item::Mod(module) => {
                if let Some((_, nested_items)) = &module.content {
                    collect_sugar_targets_in_items(nested_items, targets);
                }
            }
            // sugar-audit: not-mine(sugar targets are annotated functions inside inline modules)
            _ => {}
        }
    }
}

#[derive(Debug, Clone, Default)]
struct SugarAttrParsed {
    op: String,
    library: String,
    /// #1357: optional `version` named arg (e.g. "0.39.0"). Absent ↔ floating.
    version: Option<String>,
    loss: Vec<String>,
    observed_dimension: Option<String>,
    /// Phase-2 Tier D-lib: when `totality = "result_ok"`, the minted contract
    /// post is the AXIOM `is_ok(result)` rather than the body-derived reflexive
    /// post. Only valid on functions whose return type is always Ok by type
    /// invariants (e.g. serde_json::to_string(&Value)). Must be explicitly set;
    /// never inferred.
    totality: Option<String>,
}

/// True iff the function carries `#[sugar::sugar(totality = "result_ok", ...)]`.
///
/// This is the ONLY gate for the totality post override: the attribute must be
/// present AND the return type must be Result. Never infer from the type alone;
/// explicit opt-in is required to prevent inadvertent totality labels on
/// fallible functions that happen to take `&Value` arguments.
fn sugar_declares_totality_result_ok(item_fn: &syn::ItemFn) -> bool {
    let Some(parsed) = extract_sugar_attr(item_fn) else {
        return false;
    };
    // Require explicit totality = "result_ok" in the attribute.
    if parsed.totality.as_deref() != Some("result_ok") {
        return false;
    }
    // Require a Result return type. A totality label on a non-Result return
    // makes no sense and is rejected loudly here rather than silently mislabeling.
    is_result_type_fn(item_fn)
}

/// True iff a syn Type is `Result<...>` (bare or path-qualified).
fn is_result_type(ty: &syn::Type) -> bool {
    let syn::Type::Path(tp) = ty else {
        return false;
    };
    match tp.path.segments.last() {
        Some(seg) => seg.ident == "Result",
        None => false,
    }
}

/// True iff an ItemFn has a `Result<...>` return type.
fn is_result_type_fn(item_fn: &syn::ItemFn) -> bool {
    matches!(
        &item_fn.sig.output,
        syn::ReturnType::Type(_, ty) if is_result_type(ty)
    )
}

fn extract_sugar_attr(item_fn: &syn::ItemFn) -> Option<SugarAttrParsed> {
    for attr in &item_fn.attrs {
        let path = attr.path();
        let segments: Vec<_> = path.segments.iter().collect();
        if segments.len() == 2 && segments[0].ident == "sugar" && segments[1].ident == "sugar" {
            if let Ok(meta_list) = attr.meta.require_list() {
                let args = parse_attr_named_args(&meta_list.tokens);
                let Some(op) = args.string("op") else {
                    continue;
                };
                let Some(library) = args.string("library") else {
                    continue;
                };
                if !op.is_empty() && !library.is_empty() {
                    return Some(SugarAttrParsed {
                        op,
                        library,
                        version: args.string("version"),
                        loss: args.string_array("loss"),
                        observed_dimension: args.string("observed_dimension"),
                        totality: args.string("totality"),
                    });
                }
            }
        }
    }
    None
}

#[derive(Debug, Default)]
struct ParsedAttrArgs {
    strings: std::collections::BTreeMap<String, String>,
    string_arrays: std::collections::BTreeMap<String, Vec<String>>,
}

impl ParsedAttrArgs {
    fn string(&self, key: &str) -> Option<String> {
        self.strings.get(key).cloned()
    }

    fn string_array(&self, key: &str) -> Vec<String> {
        match self.string_arrays.get(key) {
            Some(values) => values.clone(),
            None => Vec::new(),
        }
    }
}

fn parse_attr_named_args(tokens: &proc_macro2::TokenStream) -> ParsedAttrArgs {
    let mut out = ParsedAttrArgs::default();
    let tokens: Vec<_> = tokens.clone().into_iter().collect();
    let mut i = 0;
    while i < tokens.len() {
        let key = match &tokens[i] {
            proc_macro2::TokenTree::Ident(ident) => ident.to_string(),
            _ => {
                i += 1;
                continue;
            }
        };
        let is_eq = matches!(tokens.get(i + 1), Some(proc_macro2::TokenTree::Punct(p)) if p.as_char() == '=');
        if !is_eq {
            i += 1;
            continue;
        }
        match tokens.get(i + 2) {
            Some(proc_macro2::TokenTree::Literal(lit)) => {
                if let Some(unquoted) = unquote_string_literal(&lit.to_string()) {
                    out.strings.insert(key, unquoted);
                }
                i += 3;
            }
            Some(proc_macro2::TokenTree::Group(group))
                if group.delimiter() == proc_macro2::Delimiter::Bracket =>
            {
                let entries: Vec<String> = group
                    .stream()
                    .into_iter()
                    .filter_map(|tt| match tt {
                        proc_macro2::TokenTree::Literal(lit) => {
                            unquote_string_literal(&lit.to_string())
                        }
                        _ => None,
                    })
                    .collect();
                out.string_arrays.insert(key, entries);
                i += 3;
            }
            _ => {
                i += 1;
                continue;
            }
        }
        if let Some(proc_macro2::TokenTree::Punct(p)) = tokens.get(i) {
            if p.as_char() == ',' {
                i += 1;
            }
        }
    }
    out
}

fn unquote_string_literal(raw: &str) -> Option<String> {
    if raw.starts_with('"') && raw.ends_with('"') && raw.len() >= 2 {
        Some(raw[1..raw.len() - 1].to_string())
    } else {
        None
    }
}

fn concept_annotation_for_fn(source: &str, item_fn: &syn::ItemFn) -> Option<String> {
    if source.trim().is_empty() {
        return None;
    }
    let fn_line = item_fn.sig.fn_token.span.start().line;
    concept_annotation_before_line(source, fn_line)
}

fn concept_annotation_before_line(source: &str, fn_line: usize) -> Option<String> {
    if fn_line <= 1 {
        return None;
    }
    let lines = source.lines().collect::<Vec<_>>();
    let mut idx = fn_line.checked_sub(2)?;
    loop {
        let trimmed = lines.get(idx)?.trim();
        if trimmed.is_empty() {
            return None;
        }
        if trimmed.starts_with("#[") {
            if idx == 0 {
                return None;
            }
            idx -= 1;
            continue;
        }
        if let Some(comment_body) = rust_line_comment_body(trimmed) {
            if let Some(name) = parse_concept_comment_body(comment_body) {
                return Some(name);
            }
            if idx == 0 {
                return None;
            }
            idx -= 1;
            continue;
        }
        return None;
    }
}

fn rust_line_comment_body(trimmed: &str) -> Option<&str> {
    trimmed
        .strip_prefix("///")
        .or_else(|| trimmed.strip_prefix("//"))
        .map(str::trim_start)
}

fn parse_concept_comment_body(body: &str) -> Option<String> {
    let raw = body.strip_prefix("concept:")?.trim();
    let token = raw.split_whitespace().next()?;
    let bare = match token.strip_prefix("concept:") {
        Some(bare) => bare,
        None => token,
    };
    if bare.is_empty() {
        None
    } else {
        Some(bare.to_string())
    }
}

fn is_liftable_impl_method(impl_block: &syn::ItemImpl, method: &syn::ImplItemFn) -> bool {
    impl_block.trait_.is_some() || matches!(method.vis, syn::Visibility::Public(_))
}

fn impl_function_qualifier(impl_block: &syn::ItemImpl) -> Option<String> {
    let self_ty = rust_symbol_surface(&impl_block.self_ty);
    if self_ty.is_empty() {
        return None;
    }
    match &impl_block.trait_ {
        Some((_, trait_path, _)) => {
            let trait_name = rust_symbol_surface(trait_path);
            if trait_name.is_empty() {
                Some(self_ty)
            } else {
                Some(format!("<{self_ty} as {trait_name}>"))
            }
        }
        None => Some(self_ty),
    }
}

fn item_fn_from_impl_method(method: &syn::ImplItemFn) -> syn::ItemFn {
    syn::ItemFn {
        attrs: method.attrs.clone(),
        vis: method.vis.clone(),
        sig: method.sig.clone(),
        block: Box::new(method.block.clone()),
    }
}

fn rust_symbol_surface(node: &impl quote::ToTokens) -> String {
    normalize_rust_symbol(&node.to_token_stream().to_string())
}

fn normalize_rust_symbol(raw: &str) -> String {
    let mut s = normalize_ws(raw);
    for (from, to) in [
        (" :: ", "::"),
        (" < ", "<"),
        (" >", ">"),
        (" <", "<"),
        (" ,", ","),
        (" & ", "&"),
        (" * ", "*"),
    ] {
        s = s.replace(from, to);
    }
    s
}

fn contract_witnesses_by_function_symbol(
    file: &syn::File,
    rel: &str,
    source_bytes: &[u8],
) -> BTreeMap<String, Vec<Value>> {
    let mut by_symbol: BTreeMap<String, Vec<(String, Value)>> = BTreeMap::new();
    for evidence in lift_file_with_docstring_evidence(file, rel, source_bytes)
        .evidences
        .into_iter()
    {
        let Some(symbol) = evidence_function_symbol(&evidence) else {
            continue;
        };
        let Some(witness) = bind_contract_witness_from_evidence(&evidence) else {
            continue;
        };
        by_symbol
            .entry(symbol.to_string())
            .or_default()
            .push((evidence.cid.clone(), witness));
    }

    by_symbol
        .into_iter()
        .map(|(symbol, mut witnesses)| {
            witnesses.sort_by(|a, b| a.0.cmp(&b.0));
            (
                symbol,
                witnesses.into_iter().map(|(_, witness)| witness).collect(),
            )
        })
        .collect()
}

fn evidence_function_symbol(evidence: &EvidenceMemento) -> Option<&str> {
    evidence
        .extension_fields
        .get("function_symbol")
        .and_then(|value| value.as_str())
}

fn bind_contract_witness_from_evidence(evidence: &EvidenceMemento) -> Option<Value> {
    let role = evidence_role(evidence)?;
    let source_kind: String = evidence.source_kind.clone().into();
    let predicate = match serde_json::to_value(&evidence.predicate) {
        Ok(predicate) => predicate,
        Err(err) => panic!("sugar-walk refused unserializable evidence predicate: {err}"),
    };
    let predicate_text = evidence
        .extension_fields
        .get("raw_text")
        .and_then(|value| value.as_str())
        .map(str::to_string)
        .unwrap_or_else(|| ir_formula_to_text(&evidence.predicate));
    let mut extension_fields = evidence.extension_fields.clone();
    extension_fields.remove("role");

    Some(json!({
        "role": role,
        "predicate": predicate,
        "predicate_text": predicate_text,
        "source_kind": source_kind,
        "confidence_basis_points": evidence.confidence_basis_points,
        "extension_fields": extension_fields,
    }))
}

fn evidence_role(evidence: &EvidenceMemento) -> Option<String> {
    if let Some(role) = evidence
        .extension_fields
        .get("role")
        .and_then(|value| value.as_str())
        .filter(|role| !role.trim().is_empty())
    {
        return Some(role.trim().to_string());
    }

    match &evidence.source_kind {
        SourceKind::Docstring => evidence
            .extension_fields
            .get("pattern_kind")
            .and_then(|value| value.as_str())
            .and_then(|pattern_kind| match pattern_kind {
                "requires" | "arguments_must_be" => Some("pre".to_string()),
                "returns_if" => Some("post".to_string()),
                "panics_if" => Some("panic".to_string()),
                _ => None,
            }),
        SourceKind::TypeSignature => evidence
            .extension_fields
            .get("signature_position")
            .and_then(|value| value.as_str())
            .map(|position| {
                if position == "return" {
                    "post".to_string()
                } else {
                    "pre".to_string()
                }
            }),
        _ => None,
    }
}

fn ir_formula_to_text(formula: &IrFormula) -> String {
    match formula {
        IrFormula::Atomic { name, args } if args.is_empty() => name.clone(),
        IrFormula::Atomic { name, args } => {
            let args = args
                .iter()
                .map(ir_term_to_text)
                .collect::<Vec<_>>()
                .join(", ");
            format!("{name}({args})")
        }
        IrFormula::And { operands } => join_formula_operands(operands, " && "),
        IrFormula::Or { operands } => join_formula_operands(operands, " || "),
        IrFormula::Not { operands } => {
            let inner = join_formula_operands(operands, ", ");
            format!("!({inner})")
        }
        IrFormula::Implies { operands } => join_formula_operands(operands, " -> "),
        IrFormula::Forall { name, body, .. } => {
            format!("forall {name}. {}", ir_formula_to_text(body))
        }
        IrFormula::Exists { name, body, .. } => {
            format!("exists {name}. {}", ir_formula_to_text(body))
        }
        IrFormula::Choice { var_name, body, .. } => {
            format!("choice {var_name}. {}", ir_formula_to_text(body))
        }
        IrFormula::Substitute { target, var, term } => {
            format!(
                "{}[{} := {}]",
                ir_formula_to_text(target),
                var,
                ir_term_to_text(term)
            )
        }
        IrFormula::Apply { r#fn, args } => {
            let args = args
                .iter()
                .map(ir_formula_to_text)
                .collect::<Vec<_>>()
                .join(", ");
            format!("{}({args})", r#fn)
        }
        IrFormula::DivergenceBetween { source, target } => format!(
            "divergence_between({}, {})",
            ir_formula_to_text(source),
            ir_formula_to_text(target)
        ),
    }
}

fn join_formula_operands(operands: &[IrFormula], separator: &str) -> String {
    operands
        .iter()
        .map(|operand| format!("({})", ir_formula_to_text(operand)))
        .collect::<Vec<_>>()
        .join(separator)
}

fn ir_term_to_text(term: &IrTerm) -> String {
    match term {
        IrTerm::Var { name } => name.clone(),
        // Human-readable compatibility text for predicate_text only. The
        // authoritative predicate remains the structured IrFormula above.
        IrTerm::Const { value, .. } => match value {
            Value::String(s) => format!("{s:?}"),
            _ => value.to_string(),
        },
        IrTerm::Ctor { name, args } => {
            let args = args
                .iter()
                .map(ir_term_to_text)
                .collect::<Vec<_>>()
                .join(", ");
            format!("{name}({args})")
        }
        IrTerm::Lambda {
            param_name, body, ..
        } => {
            format!("lambda {param_name}. {}", ir_term_to_text(body))
        }
        IrTerm::Let { bindings, body } => {
            let bindings = bindings
                .iter()
                .map(|binding| {
                    format!(
                        "{} = {}",
                        binding.name,
                        ir_term_to_text(&binding.bound_term)
                    )
                })
                .collect::<Vec<_>>()
                .join(", ");
            format!("let {bindings} in {}", ir_term_to_text(body))
        }
    }
}

fn resolve_rs_source_files(
    workspace_root: &Path,
    source_paths: &[String],
) -> Vec<(String, PathBuf)> {
    let mut visited: std::collections::BTreeSet<PathBuf> = Default::default();
    let scan_roots: Vec<PathBuf> = if source_paths.is_empty() {
        vec![workspace_root.to_path_buf()]
    } else {
        source_paths
            .iter()
            .map(|p| workspace_root.join(p))
            .collect()
    };
    for scan_root in &scan_roots {
        if scan_root.is_file() {
            if path_has_rs_extension(scan_root) {
                visited.insert(scan_root.clone());
            }
            continue;
        }
        if !scan_root.is_dir() {
            continue;
        }
        let src_dir = scan_root.join("src");
        let walk_root: &Path = if src_dir.is_dir() {
            &src_dir
        } else {
            scan_root
        };
        collect_rs_files(walk_root, &mut visited);
        if walk_root != scan_root.as_path() {
            collect_rs_files_shallow(scan_root, &mut visited);
        }
    }
    visited
        .into_iter()
        .map(|abs| {
            let rel_path = match abs.strip_prefix(workspace_root) {
                Ok(rel) => rel,
                Err(_) => abs.as_path(),
            };
            let rel = rel_path.to_string_lossy().to_string();
            (rel, abs)
        })
        .collect()
}

fn collect_rs_files(dir: &Path, visited: &mut std::collections::BTreeSet<PathBuf>) {
    if !dir.is_dir() {
        return;
    }
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_rs_files(&path, visited);
        } else if path_has_rs_extension(&path) {
            visited.insert(path);
        }
    }
}

fn collect_rs_files_shallow(dir: &Path, visited: &mut std::collections::BTreeSet<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_file() && path_has_rs_extension(&path) {
            visited.insert(path);
        }
    }
}

fn fn_param_names(item_fn: &syn::ItemFn) -> Vec<String> {
    let mut names = Vec::new();
    for (i, arg) in item_fn.sig.inputs.iter().enumerate() {
        match arg {
            syn::FnArg::Receiver(_) => {
                names.push("__self".to_string());
            }
            syn::FnArg::Typed(pt) => {
                let name = match &*pt.pat {
                    syn::Pat::Ident(p) => p.ident.to_string(),
                    _ => format!("__arg{}", i),
                };
                names.push(name);
            }
        }
    }
    names
}

/// Catalog-driven rust-source-syntax → concept-hub sort CID (#1370).
///
/// NO hardcoded source-token names. Reads kit-source-alias mementos via
/// libsugar::core::source_aliases::load_kit_source_aliases("rust") and
/// dispatches via the recursive resolver. Parametric types emit composite
/// CIDs computed via content-addressing; expansions are accumulated for
/// realize-side dispatch.
fn rust_source_type_to_concept_hub_sort_cid(
    rust_type: &str,
    expansions: &mut Vec<libsugar::core::source_aliases::ParametricSortExpansion>,
) -> Option<String> {
    let aliases = RUST_ALIASES
        .get_or_init(|| libsugar::core::source_aliases::load_kit_source_aliases("rust"));
    libsugar::core::source_aliases::rust_type_to_sort_cid(rust_type, aliases, expansions)
}

static RUST_ALIASES: OnceLock<
    std::collections::BTreeMap<String, libsugar::core::source_aliases::KitSourceAliasEntry>,
> = OnceLock::new();

fn sugar_param_types(item_fn: &syn::ItemFn) -> Vec<String> {
    // Build a map from type-parameter ident to its FIRST trait bound.
    // For `fn f<A: AdapterLifter>(a: A)`, the param_type for `a` is
    // emitted as "AdapterLifter" so the lower side has the right
    // method-resolution target instead of the erased Object.
    let mut bounds: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    for gp in &item_fn.sig.generics.params {
        if let syn::GenericParam::Type(tp) = gp {
            let name = tp.ident.to_string();
            for b in &tp.bounds {
                if let syn::TypeParamBound::Trait(tb) = b {
                    if let Some(last) = tb.path.segments.last() {
                        bounds.insert(name.clone(), last.ident.to_string());
                        break;
                    }
                }
            }
        }
    }
    item_fn
        .sig
        .inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Typed(pat_type) => {
                let raw = sugar_type_surface(&pat_type.ty);
                // Strip `&` / `&mut ` prefix for the bound lookup, then
                // re-apply for non-bound types.
                let stripped = raw
                    .trim_start_matches("&mut")
                    .trim_start_matches("&")
                    .trim()
                    .to_string();
                if let Some(bound) = bounds.get(&stripped) {
                    Some(bound.clone())
                } else {
                    Some(raw)
                }
            }
            _ => None,
        })
        .collect()
}

fn sugar_return_type(item_fn: &syn::ItemFn) -> String {
    match &item_fn.sig.output {
        syn::ReturnType::Default => "()".to_string(),
        syn::ReturnType::Type(_, ty) => sugar_type_surface(ty),
    }
}

/// Original param types as written in source (no trait-bound substitution).
/// Preserves generic-param references like `&A` so realize can emit the
/// signature byte-identical. param_types (above) carries the substituted
/// form for body-template matching.
fn sugar_original_param_types(item_fn: &syn::ItemFn) -> Vec<String> {
    item_fn
        .sig
        .inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Typed(pat_type) => Some(sugar_type_surface(&pat_type.ty)),
            _ => None,
        })
        .collect()
}

/// Generic parameter declarations as a single string suitable for
/// inserting between `fn name` and `(`. Empty if no generics.
/// Example: `<A: AdapterLifter, T>`.
fn sugar_generic_params(item_fn: &syn::ItemFn) -> String {
    use quote::ToTokens;
    if item_fn.sig.generics.params.is_empty() {
        String::new()
    } else {
        item_fn.sig.generics.to_token_stream().to_string()
    }
}

/// #1391 follow-on: extract the `///` doc-comment lines that appear
/// AFTER the `#[sugar::sugar(...)]` attribute on a fn (syn surfaces
/// these as `#[doc = "..."]` attributes interleaved with sugar). Doc
/// comments BEFORE the sugar attribute belong to the rust source-level
/// concept declaration block (a different surface that measure_fn skips)
/// and are NOT round-tripped through the cycle's body channel.
///
/// Returns the doc body lines (without the `/// ` prefix and without
/// `\n`), preserving source order. Empty when the function has no
/// post-sugar docs.
fn sugar_doc_lines(item_fn: &syn::ItemFn) -> Vec<String> {
    let mut out = Vec::new();
    let mut seen_sugar = false;
    for attr in &item_fn.attrs {
        let path = attr.path();
        // Detect the `#[sugar::sugar(...)]` attribute by its two-segment
        // path.
        let segs: Vec<_> = path.segments.iter().collect();
        if segs.len() == 2 && segs[0].ident == "sugar" && segs[1].ident == "sugar" {
            seen_sugar = true;
            continue;
        }
        if !path.is_ident("doc") {
            continue;
        }
        if !seen_sugar {
            // Doc BEFORE sugar — belongs to the rust-source concept block;
            // skip for the cycle's emit (the block precedes the cycle's
            // function-level surface).
            continue;
        }
        if let syn::Meta::NameValue(nv) = &attr.meta {
            if let syn::Expr::Lit(elit) = &nv.value {
                if let syn::Lit::Str(s) = &elit.lit {
                    out.push(s.value());
                }
            }
        }
    }
    out
}

fn sugar_type_surface(ty: &syn::Type) -> String {
    use quote::ToTokens;
    ty.to_token_stream().to_string().replace(' ', "")
}

/// Emit the Rust SourceMemento shape: locus + pins only. Source and AST content
/// stay in source files; proofs carry `file`, `span`, `source_cid`,
/// `template_cid`, and `param_names`.
fn sugar_body_source(rel: &str, src: &str, item_fn: &syn::ItemFn) -> Value {
    source_memento_of_named_item_fn(rel, src, &item_fn.sig.ident.to_string(), item_fn)
        .to_body_source_json()
}

fn normalize_ws(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut prev_ws = false;
    for c in s.chars() {
        if c.is_whitespace() {
            if !prev_ws && !out.is_empty() {
                out.push(' ');
            }
            prev_ws = true;
        } else {
            out.push(c);
            prev_ws = false;
        }
    }
    out.trim().to_string()
}

fn comment_shapes_for_fn_source(src: &str, fn_name: &str) -> Vec<Arc<CValue>> {
    let Some(body) = function_body_source(src, fn_name) else {
        return Vec::new();
    };
    comment_surfaces_in_source(&body)
        .into_iter()
        .filter_map(|surface| comment_shape(&surface))
        .collect()
}

fn comment_shape(surface: &str) -> Option<Arc<CValue>> {
    let op_cid = local_op_cid("comment")?;
    Some(CValue::object([
        (
            "args",
            CValue::array(vec![CValue::object([
                ("kind", CValue::string("literal")),
                ("value", CValue::string(surface.to_string())),
            ])]),
        ),
        ("op_cid", CValue::string(op_cid.to_string())),
    ]))
}

fn function_body_source(src: &str, fn_name: &str) -> Option<String> {
    let file = match syn::parse_file(src) {
        Ok(file) => file,
        Err(err) => {
            panic!("sugar-walk refused unparsable Rust source while extracting body for `{fn_name}`: {err}")
        }
    };
    let item_fn = find_item_fn_by_name(&file.items, fn_name)?;
    block_inner_source(src, &item_fn.block).map(str::to_string)
}

fn find_item_fn_by_name<'a>(items: &'a [syn::Item], fn_name: &str) -> Option<&'a syn::ItemFn> {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) if item_fn.sig.ident == fn_name => return Some(item_fn),
            syn::Item::Mod(item_mod) => {
                if let Some((_, nested_items)) = &item_mod.content {
                    if let Some(item_fn) = find_item_fn_by_name(nested_items, fn_name) {
                        return Some(item_fn);
                    }
                }
            }
            // sugar-audit: not-mine(body source lookup only searches functions in inline modules)
            _ => {}
        }
    }
    None
}

fn comment_surfaces_in_source(src: &str) -> Vec<String> {
    let bytes = src.as_bytes();
    let mut surfaces = Vec::new();
    let mut i = 0usize;
    while i < bytes.len() {
        match bytes[i] {
            b'"' => i = skip_quoted(bytes, i, b'"'),
            b'\'' => i = skip_quoted(bytes, i, b'\''),
            b'/' if bytes.get(i + 1) == Some(&b'/') => {
                let end = line_comment_end(bytes, i);
                if let Some(surface) = src.get(i..end).map(str::trim_end) {
                    if !is_sugar_comment_carrier(surface) {
                        surfaces.push(surface.to_string());
                    }
                }
                i = end;
            }
            b'/' if bytes.get(i + 1) == Some(&b'*') => {
                let end = block_comment_end(bytes, i);
                if let Some(surface) = src.get(i..end).map(str::trim) {
                    if !is_sugar_comment_carrier(surface) {
                        surfaces.push(surface.to_string());
                    }
                }
                i = end;
            }
            _ => i += 1,
        }
    }
    surfaces
}

fn is_sugar_comment_carrier(surface: &str) -> bool {
    let mut payload = surface.trim();
    if let Some(rest) = payload.strip_prefix("//") {
        payload = rest.trim();
    } else if payload.starts_with("/*") && payload.ends_with("*/") {
        payload = payload[2..payload.len() - 2].trim();
    }
    [
        "sugar:concept:",
        "sugar:concept-payload-cid:",
        "sugar-concept:",
        "sugar-concept-payload-cid:",
        "sugar-contract:",
        "sugar-contract-payload-cid:",
    ]
    .iter()
    .any(|prefix| payload.starts_with(prefix))
}

fn skip_quoted(bytes: &[u8], start: usize, quote: u8) -> usize {
    let mut i = start + 1;
    while i < bytes.len() {
        if bytes[i] == b'\\' {
            i = (i + 2).min(bytes.len());
        } else if bytes[i] == quote {
            return i + 1;
        } else {
            i += 1;
        }
    }
    bytes.len()
}

fn line_comment_end(bytes: &[u8], start: usize) -> usize {
    let mut i = start + 2;
    while i < bytes.len() && bytes[i] != b'\n' {
        i += 1;
    }
    i
}

fn block_comment_end(bytes: &[u8], start: usize) -> usize {
    let mut i = start + 2;
    while i + 1 < bytes.len() {
        if bytes[i] == b'*' && bytes[i + 1] == b'/' {
            return i + 2;
        }
        i += 1;
    }
    bytes.len()
}

fn term_shape_for_fn(item_fn: &syn::ItemFn) -> Arc<CValue> {
    let ctx = ShapeContext::for_fn(item_fn);
    shape_of_block(&item_fn.block, &ctx)
}

fn term_shape_with_comments(
    base_term_shape: Arc<CValue>,
    mut comment_shapes: Vec<Arc<CValue>>,
) -> Arc<CValue> {
    if !is_non_operation_shape(&base_term_shape) {
        comment_shapes.push(base_term_shape);
    }
    collapse_operation_shapes(comment_shapes)
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct OperandBinding {
    position: Vec<usize>,
    symbol: String,
}

#[derive(Debug, Clone, Default)]
struct BindingResult {
    has_operator: bool,
    bindings: Vec<OperandBinding>,
}

fn operand_bindings_for_fn(item_fn: &syn::ItemFn) -> Vec<Value> {
    let ctx = ShapeContext::for_fn(item_fn);
    let mut bindings = bindings_of_block(&item_fn.block, &ctx).bindings;
    bindings.sort_by(|left, right| left.position.cmp(&right.position));
    bindings
        .into_iter()
        .map(|binding| {
            json!({
                "position": binding.position,
                "symbol": binding.symbol,
            })
        })
        .collect()
}

fn operand_bindings_for_fn_with_comment_prefix(
    item_fn: &syn::ItemFn,
    comment_count: usize,
    base_has_operator: bool,
) -> Vec<Value> {
    let mut bindings = operand_bindings_for_fn(item_fn);
    if comment_count == 0 || !base_has_operator {
        return bindings;
    }
    for binding in &mut bindings {
        if let Some(position) = binding.get_mut("position").and_then(Value::as_array_mut) {
            position.insert(0, json!(comment_count));
        }
    }
    bindings
}

fn bindings_of_block(block: &syn::Block, ctx: &ShapeContext) -> BindingResult {
    let mut block_ctx = ctx.clone();
    let mut groups = Vec::new();
    for stmt in &block.stmts {
        let result = bindings_of_stmt(stmt, &block_ctx);
        if result.has_operator {
            groups.push(result.bindings);
        }
        update_context_from_stmt(stmt, &mut block_ctx);
    }
    collapse_binding_groups(groups)
}

fn collapse_binding_groups(groups: Vec<Vec<OperandBinding>>) -> BindingResult {
    match groups.len() {
        0 => BindingResult::default(),
        1 => BindingResult {
            has_operator: true,
            bindings: match groups.into_iter().next() {
                Some(bindings) => bindings,
                None => Vec::new(),
            },
        },
        _ => {
            let bindings = groups
                .into_iter()
                .enumerate()
                .flat_map(|(index, group)| prefix_bindings(group, index))
                .collect();
            BindingResult {
                has_operator: true,
                bindings,
            }
        }
    }
}

fn bindings_of_stmt(stmt: &syn::Stmt, ctx: &ShapeContext) -> BindingResult {
    match stmt {
        syn::Stmt::Expr(e, _) => bindings_of_expr(e, ctx),
        syn::Stmt::Local(local) => {
            let Some(init) = local.init.as_ref() else {
                return BindingResult::default();
            };
            // `let _ = X;` mirrors shape_of_stmt: args = [wildcard_literal,
            // init_shape]. No operand binding for the literal slot.
            if matches!(&local.pat, syn::Pat::Wild(_)) {
                return operation_binding_result(vec![
                    BindingResult::default(),
                    bindings_of_expr(&init.expr, ctx),
                ]);
            }
            let Some(symbol) = local_binding_symbol(local) else {
                return bindings_of_expr(&init.expr, ctx);
            };
            operation_binding_result(vec![
                binding_result_for_symbol(symbol),
                bindings_of_expr(&init.expr, ctx),
            ])
        }
        _ => BindingResult::default(),
    }
}

fn bindings_of_expr(expr: &syn::Expr, ctx: &ShapeContext) -> BindingResult {
    match expr {
        // Structural control flow — thread bindings through each substrate
        // operator's argument layout to match shape_of_expr's emission.
        // Without this, references inside condition/body lose their
        // operand_binding entries and downstream address resolution can't
        // see them at the expected positions.
        syn::Expr::If(e) => {
            let cond = bindings_of_expr(&e.cond, ctx);
            let then_branch = bindings_of_block(&e.then_branch, ctx);
            let else_branch = match &e.else_branch {
                Some((_, else_expr)) => bindings_of_expr(else_expr, ctx),
                None => BindingResult {
                    has_operator: true,
                    bindings: Vec::new(),
                },
            };
            operation_binding_result(vec![cond, then_branch, else_branch])
        }
        syn::Expr::While(e) => {
            // Match the shape side's treatment of `while let` — emit
            // [empty_var_slot, value_bindings, body_bindings] so the
            // arities align with concept:while-let.
            if let syn::Expr::Let(let_expr) = &*e.cond {
                let value_bindings = bindings_of_expr(&let_expr.expr, ctx);
                let body = bindings_of_block(&e.body, ctx);
                return operation_binding_result(vec![
                    BindingResult::default(),
                    value_bindings,
                    body,
                ]);
            }
            let cond = bindings_of_expr(&e.cond, ctx);
            let body = bindings_of_block(&e.body, ctx);
            operation_binding_result(vec![cond, body])
        }
        syn::Expr::ForLoop(e) => {
            // concept:for-each(var, iterable, body); var is a symbol leaf (no binding slot).
            let iterable = bindings_of_expr(&e.expr, ctx);
            let body = bindings_of_block(&e.body, ctx);
            operation_binding_result(vec![BindingResult::default(), iterable, body])
        }
        syn::Expr::Loop(e) => {
            // concept:while(true_literal_leaf, body)
            let body = bindings_of_block(&e.body, ctx);
            operation_binding_result(vec![BindingResult::default(), body])
        }
        syn::Expr::Match(e) => {
            // concept:match(scrutinee, arm1, arm2, ...)
            // Each arm: concept:match-arm(pattern_leaf, body) — pattern is leaf, body has bindings.
            let mut args = vec![bindings_of_expr(&e.expr, ctx)];
            for arm in &e.arms {
                let body_bindings = bindings_of_expr(&arm.body, ctx);
                args.push(operation_binding_result(vec![
                    BindingResult::default(),
                    body_bindings,
                ]));
            }
            operation_binding_result(args)
        }
        syn::Expr::Cast(c) => {
            // concept:cast(value, type_leaf)
            operation_binding_result(vec![
                bindings_of_expr(&c.expr, ctx),
                BindingResult::default(),
            ])
        }
        syn::Expr::Index(idx) => {
            // concept:index(receiver, index)
            operation_binding_result(vec![
                bindings_of_expr(&idx.expr, ctx),
                bindings_of_expr(&idx.index, ctx),
            ])
        }
        syn::Expr::Field(f) => {
            // concept:field(receiver, field_leaf)
            operation_binding_result(vec![
                bindings_of_expr(&f.base, ctx),
                BindingResult::default(),
            ])
        }
        syn::Expr::Return(e) => {
            let args = match e.expr.as_ref() {
                Some(expr) => vec![bindings_of_expr(expr, ctx)],
                None => Vec::new(),
            };
            operation_binding_result(args)
        }
        syn::Expr::Break(e) => {
            let args = match e.expr.as_ref() {
                Some(expr) => vec![bindings_of_expr(expr, ctx)],
                None => Vec::new(),
            };
            operation_binding_result(args)
        }
        syn::Expr::Continue(_) => BindingResult {
            has_operator: true,
            bindings: Vec::new(),
        },
        syn::Expr::Assign(e) => operation_binding_result(vec![
            bindings_of_expr(&e.left, ctx),
            bindings_of_expr(&e.right, ctx),
        ]),
        syn::Expr::Binary(e) => {
            if binary_operator_name(&e.op).is_none() {
                return BindingResult::default();
            }
            operation_binding_result(vec![
                bindings_of_expr(&e.left, ctx),
                bindings_of_expr(&e.right, ctx),
            ])
        }
        syn::Expr::Unary(e) => {
            if unary_operator_name(&e.op, expr_sort(&e.expr, ctx)).is_none() {
                return BindingResult::default();
            }
            operation_binding_result(vec![bindings_of_expr(&e.expr, ctx)])
        }
        syn::Expr::Call(e) => {
            // Callee path leaf is at args[0] (no operand binding — it's an
            // inline identifier, not a parameter symbol). Call arguments
            // are at args[1..], matching the shape_of_expr layout below.
            let mut args = vec![BindingResult::default()]; // slot for callee leaf
            args.extend(e.args.iter().map(|arg| bindings_of_expr(arg, ctx)));
            operation_binding_result(args)
        }
        syn::Expr::MethodCall(e) => {
            // Receiver is at args[0]. Method ident leaf is at args[1] (no
            // operand binding). Call arguments are at args[2..], matching
            // the shape_of_expr layout below.
            let mut args = vec![
                bindings_of_expr(&e.receiver, ctx),
                BindingResult::default(), // slot for method ident leaf
            ];
            args.extend(e.args.iter().map(|arg| bindings_of_expr(arg, ctx)));
            operation_binding_result(args)
        }
        // concept:array-repeat: args[0]=elem bindings, args[1]=len (no symbol).
        syn::Expr::Repeat(e) => operation_binding_result(vec![
            bindings_of_expr(&e.expr, ctx),
            BindingResult::default(), // len is a leaf, no operand binding slot
        ]),
        // concept:ref: args[0]=inner bindings, args[1]=mutability leaf (no symbol).
        syn::Expr::Reference(e) => operation_binding_result(vec![
            bindings_of_expr(&e.expr, ctx),
            BindingResult::default(), // mutability leaf, no operand binding slot
        ]),
        // Expr::Macro is lifted as a concept:literal source_text leaf — no
        // inner operand bindings to thread through.
        syn::Expr::Macro(_) => BindingResult::default(),
        // concept:closure: args[0]=body bindings, args[1..]=param literal slots
        // (no operand bindings — they're concept:literal source_text leaves).
        // Closure-introduced param symbols flow through the existing
        // Expr::Path -> operand_symbol path when referenced in the body;
        // that's the McCarthy address resolution.
        syn::Expr::Closure(e) => {
            let mut arg_bindings = vec![bindings_of_expr(&e.body, ctx)];
            for _ in &e.inputs {
                arg_bindings.push(BindingResult::default());
            }
            operation_binding_result(arg_bindings)
        }
        syn::Expr::Block(b) => bindings_of_block(&b.block, ctx),
        syn::Expr::Paren(e) => bindings_of_expr(&e.expr, ctx),
        syn::Expr::Group(e) => bindings_of_expr(&e.expr, ctx),
        _ => {
            // Single-identifier path → only emit a binding when the
            // identifier is a KNOWN scoped name (function param / local).
            // Free identifiers (None, Some, Vec::new, etc.) fall through
            // to the structural kind:"symbol" leaf in shape_of_expr —
            // emitting a binding for them shadowed the leaf at use site
            // because realize checks operand_bindings BEFORE kind:symbol.
            if let Some(symbol) = operand_symbol(expr) {
                // Use scoped_names (all in-scope identifiers) instead of
                // ctx.vars (only sort-inferred). Params/locals of non-modeled
                // types (refs, String, custom) belong in scope but aren't
                // in vars — without scoped_names they were treated as free
                // symbols and lost their operand_binding.
                if ctx.scoped_names.contains(&symbol) {
                    return binding_result_for_symbol(symbol);
                }
            }
            BindingResult::default()
        }
    }
}

fn binding_result_for_symbol(symbol: String) -> BindingResult {
    BindingResult {
        has_operator: false,
        bindings: vec![OperandBinding {
            position: Vec::new(),
            symbol,
        }],
    }
}

fn operation_binding_result(args: Vec<BindingResult>) -> BindingResult {
    let bindings = args
        .into_iter()
        .enumerate()
        .flat_map(|(index, arg)| prefix_bindings(arg.bindings, index))
        .collect();
    BindingResult {
        has_operator: true,
        bindings,
    }
}

fn prefix_bindings(bindings: Vec<OperandBinding>, prefix: usize) -> Vec<OperandBinding> {
    bindings
        .into_iter()
        .map(|mut binding| {
            binding.position.insert(0, prefix);
            binding
        })
        .collect()
}

fn operand_symbol(expr: &syn::Expr) -> Option<String> {
    match expr {
        syn::Expr::Path(path) => path.path.get_ident().map(|ident| ident.to_string()),
        syn::Expr::Lit(lit) => literal_symbol(&lit.lit),
        _ => None,
    }
}

fn literal_symbol(lit: &syn::Lit) -> Option<String> {
    match lit {
        syn::Lit::Bool(value) => Some(value.value().to_string()),
        syn::Lit::Int(value) => Some(value.to_string()),
        syn::Lit::Str(value) => Some(format!("{:?}", value.value())),
        _ => None,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ShapeSort {
    Bool,
    Int,
    Unit,
}

#[derive(Debug, Clone, Default)]
struct ShapeContext {
    /// Identifier → inferred sort. Only populated when the type is in
    /// ShapeSort's modeled set (Int/Float/Bool/String/Bytes/...). Used
    /// for sort-aware lifts (e.g. binary op result-sort inference).
    vars: BTreeMap<String, ShapeSort>,
    /// All scoped identifiers, regardless of whether their type is sort-
    /// inferable. Distinct from `vars` because params/locals with non-
    /// modeled types (refs, String, custom types) belong in scope but
    /// not in `vars`. Used by bindings_of_expr to distinguish scoped
    /// identifiers (emit operand_binding) from free identifiers
    /// (None/Some/path leaves — let kind:"symbol" handle them).
    scoped_names: BTreeSet<String>,
}

impl ShapeContext {
    fn for_fn(item_fn: &syn::ItemFn) -> Self {
        let mut ctx = Self::default();
        for arg in &item_fn.sig.inputs {
            let syn::FnArg::Typed(pat_type) = arg else {
                continue;
            };
            let syn::Pat::Ident(ident) = &*pat_type.pat else {
                continue;
            };
            ctx.set_local(ident.ident.to_string(), sort_from_type(&pat_type.ty));
        }
        ctx
    }

    fn set_local(&mut self, name: String, sort: Option<ShapeSort>) {
        // Always track the name in scope, even when sort isn't inferable —
        // bindings_of_expr needs this to recognize the name as scoped.
        self.scoped_names.insert(name.clone());
        if let Some(sort) = sort {
            self.vars.insert(name, sort);
        } else {
            self.vars.remove(&name);
        }
    }
}

fn shape_of_block(block: &syn::Block, ctx: &ShapeContext) -> Arc<CValue> {
    let mut block_ctx = ctx.clone();
    let mut shapes = Vec::with_capacity(block.stmts.len());
    // #1391 follow-on: blank-line carrier for substrate-symmetric
    // round-trip. When the source has a blank line between two
    // statements, emit a concept:blank-line marker so the lower side
    // (java) can carry it through and rust realize can re-emit the
    // blank line. Detection: stmt end line vs next stmt start line
    // is > 1 (i.e. at least one blank line between them).
    let mut prev_end_line: Option<usize> = None;
    for stmt in &block.stmts {
        let span = stmt.span();
        let start_line = span.start().line;
        if let Some(prev) = prev_end_line {
            if start_line > prev + 1 {
                // One concept:blank-line marker per gap, regardless of
                // how many blank lines (rustfmt normalizes multi-blank
                // to single).
                shapes.push(gamma_operation("concept:blank-line", Vec::new()));
            }
        }
        prev_end_line = Some(span.end().line);
        shapes.push(shape_of_stmt(stmt, &block_ctx));
        update_context_from_stmt(stmt, &mut block_ctx);
    }
    collapse_operation_shapes(shapes)
}

fn update_context_from_stmt(stmt: &syn::Stmt, ctx: &mut ShapeContext) {
    let syn::Stmt::Local(local) = stmt else {
        return;
    };
    if let Some((name, sort)) = local_binding_sort(local, ctx) {
        ctx.set_local(name, sort);
    }
}

fn local_binding_symbol(local: &syn::Local) -> Option<String> {
    match &local.pat {
        syn::Pat::Ident(ident) => Some(ident.ident.to_string()),
        syn::Pat::Type(pat_type) => {
            let syn::Pat::Ident(ident) = &*pat_type.pat else {
                return None;
            };
            Some(ident.ident.to_string())
        }
        _ => None,
    }
}

fn local_binding_is_mut(local: &syn::Local) -> bool {
    match &local.pat {
        syn::Pat::Ident(ident) => ident.mutability.is_some(),
        syn::Pat::Type(pat_type) => {
            let syn::Pat::Ident(ident) = &*pat_type.pat else {
                return false;
            };
            ident.mutability.is_some()
        }
        _ => false,
    }
}

fn local_binding_sort(
    local: &syn::Local,
    ctx: &ShapeContext,
) -> Option<(String, Option<ShapeSort>)> {
    let inferred = local
        .init
        .as_ref()
        .and_then(|init| expr_sort(&init.expr, ctx));
    match &local.pat {
        syn::Pat::Ident(ident) => Some((ident.ident.to_string(), inferred)),
        syn::Pat::Type(pat_type) => {
            let syn::Pat::Ident(ident) = &*pat_type.pat else {
                return None;
            };
            Some((
                ident.ident.to_string(),
                sort_from_type(&pat_type.ty).or(inferred),
            ))
        }
        _ => None,
    }
}

fn shape_of_stmt(stmt: &syn::Stmt, ctx: &ShapeContext) -> Arc<CValue> {
    match stmt {
        syn::Stmt::Expr(e, _) => shape_of_expr(e, ctx),
        // Function-local item declaration: `const X: T = expr;`, `static X`,
        // inner `fn`, etc. First-class concept:item-decl carrying the
        // verbatim source. Realize-side emits it back into the function body.
        // (Full structural lift of items is future work — preserving source
        // verbatim is the minimal byte-identical surface.)
        syn::Stmt::Item(item) => {
            use quote::ToTokens;
            let source = item.to_token_stream().to_string();
            gamma_operation(
                "concept:item-decl",
                vec![CValue::object([
                    ("kind", CValue::string("symbol")),
                    ("text", CValue::string(source)),
                ])],
            )
        }
        syn::Stmt::Local(local) => {
            let Some(init) = local.init.as_ref() else {
                return non_operation_shape();
            };
            // `let _ = X;` — Pat::Wild discard binding. Target is a symbol
            // leaf "_" (substrate-canonical name; same shape walk_rpc uses
            // for other named bindings). The realize side detects "_" and
            // emits the wildcard form. No source_text — the underscore IS
            // the substrate name, not a kit-specific source token.
            if matches!(&local.pat, syn::Pat::Wild(_)) {
                let target_leaf = CValue::object([
                    ("kind", CValue::string("symbol")),
                    ("text", CValue::string("_")),
                ]);
                return gamma_operation(
                    "concept:assign",
                    vec![target_leaf, shape_of_expr(&init.expr, ctx)],
                );
            }
            // Struct destructuring: `let TypeName { field1, field2 } = expr`
            // → first-class concept:destructure-struct(value, type_leaf,
            //   field1_name_leaf, ..., fieldN_name_leaf).
            // Realize-side: rust emits the source's destructure pattern;
            // java/etc emit field-by-field getter calls.
            if let syn::Pat::Struct(struct_pat) = &local.pat {
                use quote::ToTokens;
                let type_text = struct_pat.path.to_token_stream().to_string();
                let mut args: Vec<Arc<CValue>> = Vec::new();
                args.push(shape_of_expr(&init.expr, ctx));
                args.push(CValue::object([
                    ("kind", CValue::string("type")),
                    ("text", CValue::string(type_text)),
                ]));
                for field in &struct_pat.fields {
                    let field_name = match &field.member {
                        syn::Member::Named(ident) => ident.to_string(),
                        syn::Member::Unnamed(idx) => idx.index.to_string(),
                    };
                    let binding_name = match &*field.pat {
                        syn::Pat::Ident(pi) => pi.ident.to_string(),
                        _ => field_name.clone(),
                    };
                    args.push(CValue::object([
                        ("kind", CValue::string("symbol")),
                        ("text", CValue::string(binding_name)),
                        ("field_name", CValue::string(field_name)),
                    ]));
                }
                return gamma_operation("concept:destructure-struct", args);
            }
            // Tuple destructuring: `let (a, b, c) = expr` — first-class
            // concept:destructure-tuple(value, name1, name2, name3, ...).
            // Realize-side translates to `let (a, b, c) = expr` (rust-native)
            // OR to a temp + indexed assigns (java/etc).
            if let syn::Pat::Tuple(tuple_pat) = &local.pat {
                let mut name_leaves: Vec<Arc<CValue>> = Vec::new();
                for elem in &tuple_pat.elems {
                    let name = match elem {
                        syn::Pat::Ident(pi) => pi.ident.to_string(),
                        syn::Pat::Wild(_) => "_".to_string(),
                        other => {
                            use quote::ToTokens;
                            other.to_token_stream().to_string()
                        }
                    };
                    name_leaves.push(CValue::object([
                        ("kind", CValue::string("symbol")),
                        ("text", CValue::string(name)),
                    ]));
                }
                if !name_leaves.is_empty() {
                    let mut args = vec![shape_of_expr(&init.expr, ctx)];
                    args.extend(name_leaves);
                    return gamma_operation("concept:destructure-tuple", args);
                }
            }
            if let Some(binding_name) = local_binding_symbol(local) {
                // Substrate-honest let-binding: the binding NAME is data,
                // emit it as a kind:"symbol" leaf in the target slot.
                // (Previously emitted as non_operation_shape {} relying on
                // operand_bindings position-resolution — fragile because
                // for nested lets in loop / conditional bodies, the bindings
                // collector doesn't always thread the binding name to the
                // expected position.)
                // args[0] = target (symbol leaf with binding name)
                // args[1] = value expression
                // args[2] = mutability flag leaf when `let mut`, omitted otherwise
                // Preserve explicit `: Type` annotation when present.
                // Stored on the symbol leaf as `let_type` so the lower side
                // can emit `let X: Type = value` byte-identical with source.
                let explicit_type = if let syn::Pat::Type(pat_type) = &local.pat {
                    use quote::ToTokens;
                    Some(pat_type.ty.to_token_stream().to_string())
                } else {
                    None
                };
                let target_leaf = if let Some(ty) = explicit_type {
                    CValue::object([
                        ("kind", CValue::string("symbol")),
                        ("text", CValue::string(binding_name)),
                        ("let_type", CValue::string(ty)),
                    ])
                } else {
                    CValue::object([
                        ("kind", CValue::string("symbol")),
                        ("text", CValue::string(binding_name)),
                    ])
                };
                let mut assign_args = vec![target_leaf, shape_of_expr(&init.expr, ctx)];
                if local_binding_is_mut(local) {
                    // Emit a concept:literal boolean true as the mutability flag.
                    let Some(op_cid) = local_op_cid("literal") else {
                        return non_operation_shape();
                    };
                    assign_args.push(CValue::object([
                        ("args", CValue::array(Vec::new())),
                        ("op_cid", CValue::string(op_cid)),
                        ("sort", CValue::string(SORT_BOOL_CID)),
                        ("value", CValue::boolean(true)),
                    ]));
                }
                return gamma_operation("concept:assign", assign_args);
            }
            shape_of_expr(&init.expr, ctx)
        }
        _ => non_operation_shape(),
    }
}

fn shape_of_expr(expr: &syn::Expr, ctx: &ShapeContext) -> Arc<CValue> {
    match expr {
        // Structural control-flow lifts (source_text fallback removed):
        // - if/else → concept:conditional(cond, then, else)
        // - while → concept:while(cond, body)
        // - for x in iter → concept:for-each(var, iterable, body)
        // - loop → concept:while(true, body)  (decomposed via existing primitives)
        syn::Expr::If(e) => {
            // Detect `if let PATTERN = EXPR { body }` — rust models this
            // as ExprIf with cond = Expr::Let(pat, expr). Re-encode as
            //   { let var = EXPR; if var != null { body } else { else } }
            // using existing catalog concepts.
            if let syn::Expr::Let(let_expr) = &*e.cond {
                // First-class concept:if-let(pattern_leaf, expr, then, else).
                // Pattern text preserved so lower emits the source idiom.
                use quote::ToTokens;
                let pattern_text = let_expr.pat.to_token_stream().to_string();
                let pattern_leaf = CValue::object([
                    ("kind", CValue::string("symbol")),
                    ("text", CValue::string(pattern_text)),
                ]);
                let value = shape_of_expr(&let_expr.expr, ctx);
                let then_shape = shape_of_block(&e.then_branch, ctx);
                let else_shape = match &e.else_branch {
                    Some((_, expr)) => shape_of_expr(expr, ctx),
                    None => gamma_operation("concept:skip", Vec::new()),
                };
                return gamma_operation(
                    "concept:if-let",
                    vec![pattern_leaf, value, then_shape, else_shape],
                );
            }
            let cond = shape_of_expr(&e.cond, ctx);
            let then_shape = shape_of_block(&e.then_branch, ctx);
            let else_shape = match &e.else_branch {
                Some((_, expr)) => shape_of_expr(expr, ctx),
                None => gamma_operation("concept:skip", Vec::new()),
            };
            gamma_operation("concept:conditional", vec![cond, then_shape, else_shape])
        }
        syn::Expr::While(e) => {
            // Detect `while let PATTERN = EXPR { body }` — rust models this
            // as ExprWhile with cond = Expr::Let(pat, expr). The pattern
            // binds a variable that's in scope inside body. Lift as
            // concept:while-let(var_leaf, expr, body) so the lower side
            // can emit `while ((var = expr) != null) { body }` or the
            // equivalent in each target.
            if let syn::Expr::Let(let_expr) = &*e.cond {
                // First-class concept:while-let(pattern_leaf, expr, body).
                // The pattern's full text is preserved (e.g. `Some(line)`)
                // so the lower side can emit the original `while let
                // PATTERN = EXPR { body }` byte-identical with source.
                // Synthetic decomposition into while-true + assign + break
                // is a target-side translation, not a substrate concept.
                use quote::ToTokens;
                let pattern_text = let_expr.pat.to_token_stream().to_string();
                let pattern_leaf = CValue::object([
                    ("kind", CValue::string("symbol")),
                    ("text", CValue::string(pattern_text)),
                ]);
                let value = shape_of_expr(&let_expr.expr, ctx);
                let body = shape_of_block(&e.body, ctx);
                return gamma_operation("concept:while-let", vec![pattern_leaf, value, body]);
            }
            let cond = shape_of_expr(&e.cond, ctx);
            let body = shape_of_block(&e.body, ctx);
            gamma_operation("concept:while", vec![cond, body])
        }
        syn::Expr::ForLoop(e) => {
            // `for pat in expr { body }` — concept:for-each(var, iterable, body).
            // The pattern is captured as a leaf binding by name (full pattern
            // destructuring resolution is follow-up; matches walk_rpc's
            // existing pattern-as-leaf convention).
            let var = match &*e.pat {
                syn::Pat::Ident(p) => {
                    // Preserve `for mut x in ...` mutability marker.
                    let mut fields = vec![
                        ("kind", CValue::string("symbol")),
                        ("text", CValue::string(p.ident.to_string())),
                    ];
                    if p.mutability.is_some() {
                        fields.push(("mut", CValue::boolean(true)));
                    }
                    CValue::object(fields)
                }
                other => {
                    use quote::ToTokens;
                    CValue::object([
                        ("kind", CValue::string("symbol")),
                        ("text", CValue::string(other.to_token_stream().to_string())),
                    ])
                }
            };
            let iterable = shape_of_expr(&e.expr, ctx);
            let body = shape_of_block(&e.body, ctx);
            gamma_operation("concept:for-each", vec![var, iterable, body])
        }
        syn::Expr::Loop(e) => {
            // `loop { body }` ≡ `while true { body }` — decompose via concept:literal(true).
            let true_lit = {
                let Some(op_cid) = local_op_cid("literal") else {
                    return non_operation_shape();
                };
                CValue::object([
                    ("args", CValue::array(Vec::new())),
                    ("op_cid", CValue::string(op_cid)),
                    ("sort", CValue::string(SORT_BOOL_CID)),
                    ("value", CValue::boolean(true)),
                ])
            };
            let body = shape_of_block(&e.body, ctx);
            gamma_operation("concept:while", vec![true_lit, body])
        }
        syn::Expr::Return(e) => {
            let args = match e.expr.as_ref() {
                Some(expr) => vec![shape_of_expr(expr, ctx)],
                None => Vec::new(),
            };
            gamma_operation("concept:return", args)
        }
        // `(a, b, c)` — rust tuple literal. No first-class tuple concept
        // in the catalog; encode as concept:call with synthetic path leaf
        // `__sugar_tuple_new`. The lower side detects this name and
        // emits target-appropriate tuple constructor (e.g. Object[] in java).
        syn::Expr::Tuple(e) => {
            let callee = CValue::object([
                ("kind", CValue::string("path")),
                ("text", CValue::string("__sugar_tuple_new")),
            ]);
            let mut args = vec![callee];
            for elem in &e.elems {
                args.push(shape_of_expr(elem, ctx));
            }
            gamma_operation("concept:call", args)
        }
        syn::Expr::Break(e) => {
            let args = match e.expr.as_ref() {
                Some(expr) => vec![shape_of_expr(expr, ctx)],
                None => Vec::new(),
            };
            gamma_operation("concept:break", args)
        }
        syn::Expr::Continue(_) => gamma_operation("concept:continue", Vec::new()),
        syn::Expr::Assign(e) => gamma_operation(
            "concept:assign",
            vec![shape_of_expr(&e.left, ctx), shape_of_expr(&e.right, ctx)],
        ),
        syn::Expr::Binary(e) => {
            let Some(operator) = binary_operator_name(&e.op) else {
                return non_operation_shape();
            };
            gamma_operation(
                operator,
                vec![shape_of_expr(&e.left, ctx), shape_of_expr(&e.right, ctx)],
            )
        }
        syn::Expr::Unary(e) => {
            let Some(operator) = unary_operator_name(&e.op, expr_sort(&e.expr, ctx)) else {
                return non_operation_shape();
            };
            gamma_operation(operator, vec![shape_of_expr(&e.expr, ctx)])
        }
        syn::Expr::Call(e) => {
            // Extract callee path text from `func`. Only Expr::Path callees are
            // recognized; anything else (closures, parens, etc.) falls through to
            // non_operation_shape so we never fabricate a callee.
            let callee_text = if let syn::Expr::Path(path_expr) = &*e.func {
                path_expr
                    .path
                    .segments
                    .iter()
                    .map(|seg| seg.ident.to_string())
                    .collect::<Vec<_>>()
                    .join("::")
            } else {
                return non_operation_shape();
            };
            // args[0]: callee path leaf (kind:"path", text:"blake3::Hasher::new")
            // args[1..]: call arguments, matching bindings_of_expr layout above.
            let callee_leaf = CValue::object([
                ("kind", CValue::string("path")),
                ("text", CValue::string(callee_text)),
            ]);
            let mut args = vec![callee_leaf];
            args.extend(e.args.iter().map(|arg| shape_of_expr(arg, ctx)));
            gamma_operation("concept:call", args)
        }
        syn::Expr::MethodCall(e) => {
            // catalog-driven abstraction recognition (#1391): when the
            // method+arity matches a catalog'd realization, emit the
            // abstraction operator directly instead of concept:call wrapping
            // a method:<name> leaf. Both sides do the same; the cycle
            // collapses to the abstraction at the substrate seam.
            let m_name = e.method.to_string();
            // args[0]: receiver shape, matching bindings_of_expr layout above.
            // args[1]: canonical method leaf (kind:"method",
            // name:"<name>", arity:<n>, op_cid:<derived>).
            // The CID is determined by structure — no minting required.
            // args[2..]: call arguments.
            let method_leaf = method_operator_leaf(&m_name, e.args.len());
            let mut args = vec![shape_of_expr(&e.receiver, ctx), method_leaf];
            args.extend(e.args.iter().map(|arg| shape_of_expr(arg, ctx)));
            gamma_operation("concept:call", args)
        }
        syn::Expr::Lit(lit) => literal_shape(&lit.lit),
        // `expr?` — rust's Try operator. First-class concept:try(inner)
        // preserves the source form for byte-identical rust round-trip;
        // target plugins translate to language-appropriate unwrap (java
        // gets .try_unwrap() via the method-concept catalog mapping).
        syn::Expr::Try(e) => {
            let inner = shape_of_expr(&e.expr, ctx);
            gamma_operation("concept:try", vec![inner])
        }
        // [elem; count] syntax — emitted as concept:array-repeat with args [elem, len].
        syn::Expr::Repeat(e) => gamma_operation(
            "concept:array-repeat",
            vec![shape_of_expr(&e.expr, ctx), shape_of_expr(&e.len, ctx)],
        ),
        // &expr and &mut expr — emitted as concept:ref with args [inner, mutability_leaf].
        // mutability_leaf: {kind:"mutability", text:"mut"} or {kind:"mutability", text:""}.
        syn::Expr::Reference(e) => {
            let mut_text = if e.mutability.is_some() { "mut" } else { "" };
            let mut_leaf = CValue::object([
                ("kind", CValue::string("mutability")),
                ("text", CValue::string(mut_text)),
            ]);
            gamma_operation("concept:ref", vec![shape_of_expr(&e.expr, ctx), mut_leaf])
        }
        // Structural match: concept:match(scrutinee, arm1, arm2, ...).
        // Each arm is concept:match-arm(pattern, body). Pattern is a
        // symbol leaf carrying the textual form (full pattern decomposition
        // to concept:literal-pattern / concept:constructor-pattern / etc.
        // is follow-up substrate-mint work; for now patterns live as
        // symbol-leaf substrate names with kit-side pattern parsing).
        syn::Expr::Match(e) => {
            use quote::ToTokens;
            let mut args = vec![shape_of_expr(&e.expr, ctx)];
            for arm in &e.arms {
                let mut pattern_text = arm.pat.to_token_stream().to_string();
                // Carry the guard inline in the pattern text so the
                // realize side reconstructs `Pattern if Cond => Body`.
                // Storing it in the pattern leaf keeps the substrate
                // shape stable (no new concept-arity yet); future work
                // can split guard into its own structural slot.
                if let Some((_, guard)) = &arm.guard {
                    pattern_text.push_str(" if ");
                    pattern_text.push_str(&guard.to_token_stream().to_string());
                }
                let pattern_leaf = CValue::object([
                    ("kind", CValue::string("symbol")),
                    ("text", CValue::string(pattern_text)),
                ]);
                let body = shape_of_expr(&arm.body, ctx);
                args.push(gamma_operation(
                    "concept:match-arm",
                    vec![pattern_leaf, body],
                ));
            }
            gamma_operation("concept:match", args)
        }
        // Macro invocation: `writeln!(handle, "{}", line)` and similar.
        // concept:macro-call(path, args...) — path is symbol leaf for the
        // macro name; args are the tokens as a single symbol leaf
        // (structural decomposition of macro tokens to substrate primitives
        // is follow-up; macros are syntactic — their structure isn't
        // semantically meaningful until the macro expands).
        syn::Expr::Macro(e) => {
            use quote::ToTokens;
            let path = e.mac.path.to_token_stream().to_string().replace(' ', "");
            let path_leaf = CValue::object([
                ("kind", CValue::string("symbol")),
                ("text", CValue::string(path)),
            ]);
            let tokens = e.mac.tokens.to_string();
            let formatted = format_macro_tokens(&tokens);
            let args_leaf = CValue::object([
                ("kind", CValue::string("symbol")),
                ("text", CValue::string(formatted)),
            ]);
            gamma_operation("concept:macro-call", vec![path_leaf, args_leaf])
        }
        // |param1, param2, ...| body — emitted as concept:closure with
        // args = [body_shape, param1_literal, param2_literal, ...]. Body
        // at args[0], param-name literals at args[1..]. No new substrate
        // concept:closure (already in catalog as abstraction). Param names
        // are symbol leaves — substrate-canonical names, NOT source text.
        // The realize side spells each per its own convention.
        //
        // Closure-introduced bindings flow through the existing
        // Expr::Path -> operand_symbol path at use site (McCarthy address
        // resolution); we do NOT pre-bind closure params here.
        syn::Expr::Closure(e) => {
            let mut closure_args: Vec<Arc<CValue>> = Vec::new();
            // Record source form choice: block-body vs expression-body.
            // `|e| { ... }` is Expr::Block (block-form); `|e| expr` is
            // any other expression. The lower side uses this to emit
            // byte-identical surface — block form lets rustfmt split
            // long lines, expression form keeps them inline.
            let is_block_body = matches!(&*e.body, syn::Expr::Block(_));
            let body_shape = shape_of_expr(&e.body, ctx);
            // Attach closure_block_body marker on a wrapper. Cloning the
            // inner object's fields and re-wrapping is simpler than
            // get_mut-and-mutate (Arc has multiple refs in the IR tree).
            let body_shape = if is_block_body {
                let cloned = (*body_shape).clone();
                match cloned {
                    CValue::Object(mut fields) => {
                        // CValue::Object is Vec<(String, Arc<Value>)>
                        let val: Arc<CValue> = CValue::boolean(true);
                        fields.push(("closure_block_body".to_string(), val));
                        Arc::new(CValue::Object(fields))
                    }
                    other => Arc::new(other),
                }
            } else {
                body_shape
            };
            closure_args.push(body_shape);
            for input in &e.inputs {
                let syn::Pat::Ident(pat) = input else {
                    return non_operation_shape();
                };
                closure_args.push(CValue::object([
                    ("kind", CValue::string("symbol")),
                    ("text", CValue::string(pat.ident.to_string())),
                ]));
            }
            gamma_operation("concept:closure", closure_args)
        }
        syn::Expr::Block(b) => shape_of_block(&b.block, ctx),
        syn::Expr::Paren(e) => shape_of_expr(&e.expr, ctx),
        syn::Expr::Group(e) => shape_of_expr(&e.expr, ctx),
        // Cast: `value as TargetType` → concept:cast(value_shape, type_symbol_leaf).
        syn::Expr::Cast(c) => {
            use quote::ToTokens;
            let value = shape_of_expr(&c.expr, ctx);
            let type_text = c.ty.to_token_stream().to_string().replace(' ', "");
            let type_leaf = CValue::object([
                ("kind", CValue::string("symbol")),
                ("text", CValue::string(type_text)),
            ]);
            gamma_operation("concept:cast", vec![value, type_leaf])
        }
        // Indexed access: `receiver[index]` → concept:index(receiver, index).
        syn::Expr::Index(idx) => {
            let receiver = shape_of_expr(&idx.expr, ctx);
            let index = shape_of_expr(&idx.index, ctx);
            gamma_operation("concept:index", vec![receiver, index])
        }
        // Field access: `receiver.field` (and `receiver.0` tuple field) →
        // concept:field(receiver_shape, field_symbol_leaf).
        syn::Expr::Field(f) => {
            let receiver = shape_of_expr(&f.base, ctx);
            let field_text = match &f.member {
                syn::Member::Named(ident) => ident.to_string(),
                syn::Member::Unnamed(idx) => idx.index.to_string(),
            };
            let field_leaf = CValue::object([
                ("kind", CValue::string("symbol")),
                ("text", CValue::string(field_text)),
            ]);
            gamma_operation("concept:field", vec![receiver, field_leaf])
        }
        // Free path identifier (e.g. None, Some, Vec::new, Ordering::Less).
        // Emit as substrate-canonical symbol leaf so deeper consumers (match
        // arm bodies, conditional branches) can lower them without depending
        // on operand_bindings position threading.
        //
        // Note: parameter references ALSO go through Expr::Path. Those are
        // handled at use site by the realize binary's operand_bindings
        // lookup (term_shape_leaf_expression checks operand_bindings.get(
        // position) BEFORE checking kind=symbol). So this symbol-leaf
        // emission is the FALLBACK for free identifiers not bound as params.
        syn::Expr::Path(path) => {
            use quote::ToTokens;
            let text = path.to_token_stream().to_string().replace(' ', "");
            // #1075 federation: operand NAMES are sugar — the term_shape is
            // structural identity, so `f(x)=x*2` and `f(y)=y*2` MUST share a
            // term_shape. A scoped param/local reference therefore emits an
            // EMPTY structural leaf `{}`; its symbol travels on the CID-invisible
            // operand_bindings sidecar (same position, see bindings_of_expr's
            // matching scoped_names check). This makes the rust term_shape
            // byte-identical to the python lifter's empty-leaf + operand_bindings
            // form (seam-4 federation). Discharge is unaffected: the realize
            // binary's term_shape_leaf_expression checks operand_bindings.get(
            // position) BEFORE kind=symbol, so it never read these leaves for
            // scoped names. FREE identifiers (None, Some, Vec::new, enum paths)
            // are NOT operands — they keep their symbol leaf so deeper consumers
            // can lower them without operand_bindings position threading.
            if ctx.scoped_names.contains(&text) {
                non_operation_shape()
            } else {
                CValue::object([
                    ("kind", CValue::string("symbol")),
                    ("text", CValue::string(text)),
                ])
            }
        }
        _ => non_operation_shape(),
    }
}

fn expr_sort(expr: &syn::Expr, ctx: &ShapeContext) -> Option<ShapeSort> {
    match expr {
        syn::Expr::Lit(lit) => match &lit.lit {
            syn::Lit::Bool(_) => Some(ShapeSort::Bool),
            syn::Lit::Int(_) => Some(ShapeSort::Int),
            syn::Lit::Byte(_) | syn::Lit::Char(_) => Some(ShapeSort::Int),
            syn::Lit::Float(_)
            | syn::Lit::Str(_)
            | syn::Lit::ByteStr(_)
            | syn::Lit::CStr(_)
            | syn::Lit::Verbatim(_) => {
                // #3017 item 2 owns richer scalar floors; ShapeSort only proves
                // the current Unit/Bool/Int subset.
                None
            }
            _ => panic!("sugar-walk RPC expr_sort refused unknown syn::Lit variant"),
        },
        syn::Expr::Path(path) => path
            .path
            .get_ident()
            .and_then(|ident| ctx.vars.get(&ident.to_string()).copied()),
        syn::Expr::Paren(paren) => expr_sort(&paren.expr, ctx),
        syn::Expr::Group(group) => expr_sort(&group.expr, ctx),
        syn::Expr::Block(block) => {
            block_tail_expr(&block.block).and_then(|expr| expr_sort(expr, ctx))
        }
        syn::Expr::Unary(unary) => match &unary.op {
            syn::UnOp::Neg(_) => {
                (expr_sort(&unary.expr, ctx) == Some(ShapeSort::Int)).then_some(ShapeSort::Int)
            }
            syn::UnOp::Not(_) => match expr_sort(&unary.expr, ctx) {
                Some(ShapeSort::Bool) => Some(ShapeSort::Bool),
                Some(ShapeSort::Int) => Some(ShapeSort::Int),
                Some(ShapeSort::Unit) | None => {
                    // #3017 item 8 owns the predicate-vs-raw-term split that
                    // would let unknown `!x` classify without guessing.
                    None
                }
            },
            syn::UnOp::Deref(_) => expr_sort(&unary.expr, ctx),
            _ => panic!("sugar-walk RPC expr_sort refused unknown syn::UnOp variant"),
        },
        syn::Expr::Binary(binary) => binary_result_sort(binary, ctx),
        syn::Expr::Array(_)
        | syn::Expr::Assign(_)
        | syn::Expr::Async(_)
        | syn::Expr::Await(_)
        | syn::Expr::Break(_)
        | syn::Expr::Call(_)
        | syn::Expr::Cast(_)
        | syn::Expr::Closure(_)
        | syn::Expr::Const(_)
        | syn::Expr::Continue(_)
        | syn::Expr::Field(_)
        | syn::Expr::ForLoop(_)
        | syn::Expr::If(_)
        | syn::Expr::Index(_)
        | syn::Expr::Infer(_)
        | syn::Expr::Let(_)
        | syn::Expr::Loop(_)
        | syn::Expr::Macro(_)
        | syn::Expr::Match(_)
        | syn::Expr::MethodCall(_)
        | syn::Expr::Range(_)
        | syn::Expr::RawAddr(_)
        | syn::Expr::Reference(_)
        | syn::Expr::Repeat(_)
        | syn::Expr::Return(_)
        | syn::Expr::Struct(_)
        | syn::Expr::Try(_)
        | syn::Expr::TryBlock(_)
        | syn::Expr::Tuple(_)
        | syn::Expr::Unsafe(_)
        | syn::Expr::Verbatim(_)
        | syn::Expr::While(_)
        | syn::Expr::Yield(_) => None,
        _ => panic!("sugar-walk RPC expr_sort refused unknown syn::Expr variant"),
    }
}

fn block_tail_expr(block: &syn::Block) -> Option<&syn::Expr> {
    match block.stmts.last()? {
        syn::Stmt::Expr(expr, None) => Some(expr),
        _ => None,
    }
}

fn binary_result_sort(binary: &syn::ExprBinary, ctx: &ShapeContext) -> Option<ShapeSort> {
    match &binary.op {
        syn::BinOp::Add(_)
        | syn::BinOp::Sub(_)
        | syn::BinOp::Mul(_)
        | syn::BinOp::Div(_)
        | syn::BinOp::Rem(_)
        | syn::BinOp::BitAnd(_)
        | syn::BinOp::BitOr(_)
        | syn::BinOp::BitXor(_)
        | syn::BinOp::Shl(_)
        | syn::BinOp::Shr(_) => {
            operands_have_sort(&binary.left, &binary.right, ctx, ShapeSort::Int)
                .then_some(ShapeSort::Int)
        }
        syn::BinOp::Eq(_)
        | syn::BinOp::Ne(_)
        | syn::BinOp::Lt(_)
        | syn::BinOp::Le(_)
        | syn::BinOp::Gt(_)
        | syn::BinOp::Ge(_) => operands_have_sort(&binary.left, &binary.right, ctx, ShapeSort::Int)
            .then_some(ShapeSort::Bool),
        syn::BinOp::And(_) | syn::BinOp::Or(_) => {
            operands_have_sort(&binary.left, &binary.right, ctx, ShapeSort::Bool)
                .then_some(ShapeSort::Bool)
        }
        syn::BinOp::AddAssign(_)
        | syn::BinOp::SubAssign(_)
        | syn::BinOp::MulAssign(_)
        | syn::BinOp::DivAssign(_)
        | syn::BinOp::RemAssign(_)
        | syn::BinOp::BitXorAssign(_)
        | syn::BinOp::BitAndAssign(_)
        | syn::BinOp::BitOrAssign(_)
        | syn::BinOp::ShlAssign(_)
        | syn::BinOp::ShrAssign(_) => Some(ShapeSort::Unit),
        _ => panic!("sugar-walk RPC binary_result_sort refused unknown syn::BinOp variant"),
    }
}

fn operands_have_sort(
    left: &syn::Expr,
    right: &syn::Expr,
    ctx: &ShapeContext,
    sort: ShapeSort,
) -> bool {
    expr_sort(left, ctx) == Some(sort) && expr_sort(right, ctx) == Some(sort)
}

fn sort_from_type(ty: &syn::Type) -> Option<ShapeSort> {
    match ty {
        syn::Type::Path(path) if path.qself.is_none() => {
            let ident = path.path.segments.last()?.ident.to_string();
            sort_from_type_name(&ident)
        }
        syn::Type::Paren(paren) => sort_from_type(&paren.elem),
        syn::Type::Group(group) => sort_from_type(&group.elem),
        syn::Type::Tuple(tuple) if tuple.elems.is_empty() => Some(ShapeSort::Unit),
        syn::Type::Path(_)
        | syn::Type::Array(_)
        | syn::Type::BareFn(_)
        | syn::Type::ImplTrait(_)
        | syn::Type::Infer(_)
        | syn::Type::Macro(_)
        | syn::Type::Never(_)
        | syn::Type::Ptr(_)
        | syn::Type::Reference(_)
        | syn::Type::Slice(_)
        | syn::Type::TraitObject(_)
        | syn::Type::Tuple(_)
        | syn::Type::Verbatim(_) => {
            // #3017 item 2 keeps non-primitive and sort-neutral values out of
            // this scalar classifier; shape_of_expr carries concept structure.
            None
        }
        _ => panic!("sugar-walk RPC sort_from_type refused unknown syn::Type variant"),
    }
}

fn sort_from_type_name(name: &str) -> Option<ShapeSort> {
    match name {
        "bool" => Some(ShapeSort::Bool),
        "i8" | "i16" | "i32" | "i64" | "i128" | "isize" | "u8" | "u16" | "u32" | "u64" | "u128"
        | "usize" => Some(ShapeSort::Int),
        _ => None,
    }
}

fn collapse_operation_shapes(shapes: impl IntoIterator<Item = Arc<CValue>>) -> Arc<CValue> {
    let operations = shapes
        .into_iter()
        .filter(|shape| !is_non_operation_shape(shape))
        .collect::<Vec<_>>();
    match operations.as_slice() {
        [] => non_operation_shape(),
        [only] => only.clone(),
        _ => gamma_operation("concept:seq", operations),
    }
}

fn binary_operator_name(op: &syn::BinOp) -> Option<&'static str> {
    match op {
        syn::BinOp::Add(_) | syn::BinOp::AddAssign(_) => Some("concept:add"),
        syn::BinOp::Sub(_) | syn::BinOp::SubAssign(_) => Some("concept:sub"),
        syn::BinOp::Mul(_) | syn::BinOp::MulAssign(_) => Some("concept:mul"),
        syn::BinOp::Div(_) | syn::BinOp::DivAssign(_) => Some("concept:div"),
        syn::BinOp::Rem(_) | syn::BinOp::RemAssign(_) => Some("concept:mod"),
        syn::BinOp::BitAnd(_) | syn::BinOp::BitAndAssign(_) => Some("concept:bitand"),
        syn::BinOp::BitOr(_) | syn::BinOp::BitOrAssign(_) => Some("concept:bitor"),
        syn::BinOp::BitXor(_) | syn::BinOp::BitXorAssign(_) => Some("concept:bitxor"),
        syn::BinOp::Shl(_) | syn::BinOp::ShlAssign(_) => Some("concept:shl"),
        syn::BinOp::Shr(_) | syn::BinOp::ShrAssign(_) => Some("concept:shr"),
        syn::BinOp::Eq(_) => Some("concept:eq"),
        syn::BinOp::Ne(_) => Some("concept:ne"),
        syn::BinOp::Lt(_) => Some("concept:lt"),
        syn::BinOp::Le(_) => Some("concept:le"),
        syn::BinOp::Gt(_) => Some("concept:gt"),
        syn::BinOp::Ge(_) => Some("concept:ge"),
        syn::BinOp::And(_) => Some("concept:and"),
        syn::BinOp::Or(_) => Some("concept:or"),
        _ => None,
    }
}

fn unary_operator_name(op: &syn::UnOp, operand_sort: Option<ShapeSort>) -> Option<&'static str> {
    match op {
        syn::UnOp::Deref(_) => Some("concept:deref"),
        syn::UnOp::Not(_) => match operand_sort {
            Some(ShapeSort::Int) => Some("concept:bitnot"),
            _ => Some("concept:not"),
        },
        syn::UnOp::Neg(_) => Some("concept:neg"),
        _ => None,
    }
}

/// Canonical-spacing format for proc_macro2::TokenStream::to_string() output.
/// The default TokenStream renderer emits space-separated tokens (e.g.
/// `handle , "{}" , line`). Apply minimal normalization to match common
/// Rust source conventions: drop spaces before `,` and around `(` `)` `[`
/// `]` and `;`. This is byte-correct for the macro forms the L0 shims use.
fn format_macro_tokens(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut prev_was_space = false;
    let chars: Vec<char> = s.chars().collect();
    for (i, &c) in chars.iter().enumerate() {
        if c == ' ' {
            // Look at the next non-space character: if it's `,` `(` `)` `[` `]` `;` `.`
            // or we just emitted `(` `[` `.`, drop this space.
            let next_non_space = chars.iter().skip(i + 1).find(|&&c| c != ' ');
            let prev = out.chars().last();
            let skip = matches!(next_non_space, Some(',' | ')' | ']' | ';' | '.'))
                || matches!(prev, Some('(' | '[' | '.'));
            if !skip {
                if !prev_was_space {
                    out.push(' ');
                }
                prev_was_space = true;
            }
        } else {
            out.push(c);
            prev_was_space = false;
        }
    }
    out.trim().to_string()
}

/// Build a substrate-canonical method leaf.
///
/// A method's identity comes from its STRUCTURE — the canonical shape
/// is `{kind:"method-operator", name:"<name>", arity:<n>}`, and its
/// op_cid is `blake3_512(JCS(that))`. No catalog minting required:
/// the structure IS the identity. Any source language emitting a
/// method with the same (name, arity) gets the same CID automatically.
///
/// The leaf also keeps `text` for readers that consume source spelling.
fn method_operator_leaf(method_name: &str, arity: usize) -> Arc<CValue> {
    // Canonical content-addressable shape (no text/legacy fields,
    // no op_cid yet — those are derived/auxiliary).
    let canonical = CValue::object([
        ("arity", CValue::integer(arity as i128)),
        ("kind", CValue::string("method-operator")),
        ("name", CValue::string(method_name.to_string())),
    ]);
    let op_cid = blake3_512_of(encode_jcs(&canonical).as_bytes());
    // Emitted leaf includes op_cid (self-describing) AND keeps text/
    // kind="method" for backwards compatibility with existing readers
    // (e.g. the java realize plugin's pattern-match on "kind":"method").
    CValue::object([
        ("arity", CValue::integer(arity as i128)),
        ("kind", CValue::string("method")),
        ("name", CValue::string(method_name.to_string())),
        ("op_cid", CValue::string(op_cid.to_string())),
        ("text", CValue::string(method_name.to_string())),
    ])
}

fn gamma_operation(operator: &str, args: Vec<Arc<CValue>>) -> Arc<CValue> {
    let op_cid = match local_op_cid(operator) {
        Some(cid) => cid.to_string(),
        None => {
            // Unknown local operator label: derive a deterministic CID from
            // the label bytes rather than guessing a body template.
            blake3_512_of(operator.as_bytes())
        }
    };
    CValue::object([
        ("args", CValue::array(args)),
        ("op_cid", CValue::string(op_cid)),
    ])
}

fn literal_shape(lit: &syn::Lit) -> Arc<CValue> {
    match lit {
        syn::Lit::Bool(value) => {
            concept_literal_shape(CValue::boolean(value.value()), SORT_BOOL_CID)
        }
        syn::Lit::Int(value) => {
            // Substrate-canonical literal: (sort=concept:Int, value=N, integer_width=W).
            // The kit's realize side reconstructs source spelling from these
            // — no source_text side channel. integer_width covers width
            // refinements (u8/i32/usize/etc.) so the spelling is fully
            // derivable from (value + width).
            let decoded = match value.base10_parse::<i128>() {
                Ok(decoded) => decoded,
                Err(err) => {
                    panic!("sugar-walk refused integer literal outside canonical i128 floor: {err}")
                }
            };
            let Some(op_cid) = local_op_cid("literal") else {
                return non_operation_shape();
            };
            let suffix = value.suffix();
            let integer_width = if suffix.is_empty() {
                "inferred".to_string()
            } else {
                suffix.to_string()
            };
            // Preserve source radix (hex, oct, bin) so realize reproduces
            // `0x0F` not `15`. base10_digits gives "15" for any radix; we
            // peek at the original token text for the prefix.
            let token_text = value.to_string();
            let radix = if token_text.starts_with("0x") || token_text.starts_with("0X") {
                "hex"
            } else if token_text.starts_with("0o") || token_text.starts_with("0O") {
                "oct"
            } else if token_text.starts_with("0b") || token_text.starts_with("0B") {
                "bin"
            } else {
                "dec"
            };
            CValue::object([
                ("args", CValue::array(Vec::new())),
                ("op_cid", CValue::string(op_cid)),
                ("sort", CValue::string(SORT_INT_CID)),
                ("value", CValue::integer(decoded)),
                ("integer_width", CValue::string(integer_width)),
                ("radix", CValue::string(radix)),
            ])
        }
        syn::Lit::Float(value) => {
            concept_literal_shape(CValue::string(value.base10_digits()), SORT_FLOAT_CID)
        }
        syn::Lit::Str(value) => {
            // Substrate-canonical: sort + value (the decoded string).
            // Source-form escape choices (`"\\\""` vs `"\""`) are kit
            // presentation, not substrate state.
            let Some(op_cid) = local_op_cid("literal") else {
                return non_operation_shape();
            };
            CValue::object([
                ("args", CValue::array(Vec::new())),
                ("op_cid", CValue::string(op_cid)),
                ("sort", CValue::string(SORT_STRING_CID)),
                ("value", CValue::string(value.value())),
            ])
        }
        syn::Lit::ByteStr(value) => {
            concept_literal_shape(byte_array_value(value.value()), SORT_BYTES_CID)
        }
        syn::Lit::CStr(value) => concept_literal_shape(
            byte_array_value(value.value().as_bytes_with_nul().to_vec()),
            SORT_BYTES_CID,
        ),
        syn::Lit::Byte(value) => {
            concept_literal_shape(CValue::integer(i128::from(value.value())), SORT_INT_CID)
        }
        // Substrate-canonical char: sort + value (the actual character as a
        // single-char string). Source spelling (`'a'` vs `'\u{61}'`) is kit
        // presentation; the substrate carries semantic identity only.
        syn::Lit::Char(value) => {
            let Some(op_cid) = local_op_cid("literal") else {
                return non_operation_shape();
            };
            CValue::object([
                ("args", CValue::array(Vec::new())),
                ("op_cid", CValue::string(op_cid)),
                ("sort", CValue::string(SORT_STRING_CID)),
                ("value", CValue::string(value.value().to_string())),
            ])
        }
        syn::Lit::Verbatim(_) => non_operation_shape(),
        // syn::Lit is #[non_exhaustive]; future variants refuse the lift
        // until the substrate adds an explicit shape claim for them.
        _ => non_operation_shape(),
    }
}

fn concept_literal_shape(value: Arc<CValue>, sort_cid: &str) -> Arc<CValue> {
    let Some(op_cid) = local_op_cid("literal") else {
        return non_operation_shape();
    };
    CValue::object([
        ("args", CValue::array(Vec::new())),
        ("op_cid", CValue::string(op_cid.to_string())),
        ("sort", CValue::string(sort_cid.to_string())),
        ("value", value),
    ])
}

fn byte_array_value(bytes: Vec<u8>) -> Arc<CValue> {
    CValue::array(
        bytes
            .into_iter()
            .map(|byte| CValue::integer(i128::from(byte)))
            .collect(),
    )
}

fn local_op_cid(operator: &str) -> Option<&'static str> {
    let cache = CONCEPT_OP_CIDS.get_or_init(|| std::sync::Mutex::new(BTreeMap::new()));
    let mut cids = match cache.lock() {
        Ok(cids) => cids,
        Err(err) => panic!("sugar-walk concept op CID cache lock poisoned: {err}"),
    };
    if let Some(cid) = cids.get(operator) {
        return Some(*cid);
    }
    let cid = match canonical_local_op_cid(operator) {
        Ok(cid) => cid,
        Err(err) => {
            panic!("sugar-walk refused local op CID canonicalization for `{operator}`: {err}")
        }
    };
    let cid = Box::leak(cid.into_boxed_str()) as &'static str;
    cids.insert(operator.to_string(), cid);
    Some(cid)
}

fn is_non_operation_shape(shape: &CValue) -> bool {
    encode_jcs(shape) == "{}"
}

fn non_operation_shape() -> Arc<CValue> {
    CValue::object(Vec::<(&str, Arc<CValue>)>::new())
}

/// Render a canonicalizer `Value` as `serde_json::Value` for the RPC response.
fn cvalue_to_json(v: &CValue) -> Value {
    let s = encode_jcs(v);
    match serde_json::from_str(&s) {
        Ok(value) => value,
        Err(err) => panic!("canonicalizer emitted non-JSON JCS: {err}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use libsugar::core::{bind_result_payload, bind_term_document, BindOptions, Term};
    use std::collections::BTreeSet;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};
    use sugar_claim_envelope::{
        mint_bridge, mint_contract_with_body_cid, Authoring, MintBridgeArgs, MintContractArgs,
    };
    use sugar_ir_types::Sort;
    use sugar_proof_envelope::{
        build_proof_envelope, ed25519_pubkey_string, proof_filename, AtomMemento, BridgeMemento,
        ClaimContractMemento, ContractBody, ContractMementoRef, Ed25519Seed, FlatAtom,
        LibrarySugarBindingMemento, ProofEnvelopeInput, ProofGraph,
    };

    // ---- Source Oracle + materialize (#1359) --------------------------------

    /// Mint a SourceMemento for `fn_name` in `src`, then return
    /// (project_root, memento). Mirrors what the producer (`sugar_body_source`)
    /// emits + what the proof loader hands `resolve_source_memento`.
    fn mint_memento_for(dir: &Path, fn_name: &str, src: &str) -> SourceMemento {
        let file_rel = "src/lib.rs";
        fs::create_dir_all(dir.join("src")).unwrap();
        fs::write(dir.join(file_rel), src).unwrap();
        let parsed = syn::parse_file(src).unwrap();
        let item_fn = parsed
            .items
            .iter()
            .find_map(|it| match it {
                syn::Item::Fn(f) if f.sig.ident == fn_name => Some(f),
                _ => None,
            })
            .unwrap();
        let body_source = sugar_body_source(file_rel, src, item_fn);
        // body_source carries only the locus + pins.
        SourceMemento::from_body_source(Some(fn_name.to_string()), &body_source).unwrap()
    }

    fn unique_tmp(tag: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!(
            "pk-oracle-{tag}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&p).unwrap();
        p
    }

    #[test]
    fn source_oracle_resolves_matching_source_to_body() {
        let dir = unique_tmp("match");
        let src = "#[sugar::sugar(op = \"c\", library = \"l\")]\npub fn rev(s: &str) -> String {\n    s.chars().rev().collect()\n}\n";
        let memento = mint_memento_for(&dir, "rev", src);
        // Clean disk == the pin: the oracle returns the body.
        let resolved = resolve_source_memento(&dir, &memento).expect("clean resolve");
        assert_eq!(resolved.body_text(), "s.chars().rev().collect()");
        assert_eq!(resolved.source_cid, memento.source_cid);
        assert_eq!(resolved.template_cid, memento.template_cid);
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn resolve_source_memento_rpc_returns_source_from_workspace_root() {
        let dir = unique_tmp("resolve-rpc");
        let src = "pub fn encoded_len(bytes_len: usize) -> usize {\n    let rem = bytes_len % 3;\n    rem + 1\n}\n";
        let memento = mint_memento_for(&dir, "encoded_len", src);

        let resolved = resolve_source_memento_rpc(&json!({
            "workspace_root": dir.to_string_lossy(),
            "sourceMemento": memento.to_json(),
        }))
        .expect("resolve source memento rpc");

        assert_eq!(resolved["file"], "src/lib.rs");
        assert_eq!(resolved["source"], "let rem = bytes_len % 3;\n    rem + 1");
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn resolve_source_memento_rpc_refuses_unpinned_memento() {
        let dir = unique_tmp("resolve-rpc-unpinned");
        let src = "pub fn encoded_len(bytes_len: usize) -> usize {\n    bytes_len + 1\n}\n";
        let memento = mint_memento_for(&dir, "encoded_len", src);
        let mut unpinned = memento.to_json();
        unpinned
            .as_object_mut()
            .expect("source memento object")
            .remove("source_cid");
        unpinned
            .as_object_mut()
            .expect("source memento object")
            .remove("template_cid");

        let err = resolve_source_memento_rpc(&json!({
            "workspace_root": dir.to_string_lossy(),
            "sourceMemento": unpinned,
        }))
        .expect_err("source memento without CIDs must not resolve unchecked");

        assert!(
            err.contains("source_cid") || err.contains("template_cid"),
            "unexpected error: {err}"
        );
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn source_oracle_refuses_on_body_drift() {
        let dir = unique_tmp("drift");
        let src = "#[sugar::sugar(op = \"c\", library = \"l\")]\npub fn rev(s: &str) -> String {\n    s.chars().rev().collect()\n}\n";
        let memento = mint_memento_for(&dir, "rev", src);
        // Tamper the body AFTER minting the pin: same behavior, different bytes.
        let tampered = "#[sugar::sugar(op = \"c\", library = \"l\")]\npub fn rev(s: &str) -> String {\n    let v: Vec<char> = s.chars().rev().collect();\n    v.into_iter().collect()\n}\n";
        fs::write(dir.join("src/lib.rs"), tampered).unwrap();
        let err = resolve_source_memento(&dir, &memento).expect_err("drift must refuse");
        assert!(
            err.reason.contains("source CID misaligned"),
            "expected source_cid refusal, got: {}",
            err.reason
        );
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn source_oracle_param_rename_keeps_template_cid_but_drifts_source_cid() {
        // Renaming a PARAM (not a local) leaves the AST template stable —
        // `block_to_ast_template` canonicalizes params to positional `param_ref`
        // holes — so template_cid is unchanged. But the body TEXT changes
        // (`s` -> `input`), so source_cid drifts. The oracle therefore refuses
        // on the source_cid axis, demonstrating the producer's canonicalization
        // is exactly what the oracle recomputes.
        let dir = unique_tmp("rename");
        let src = "#[sugar::sugar(op = \"c\", library = \"l\")]\npub fn rev(s: &str) -> String {\n    s.chars().rev().collect()\n}\n";
        let memento = mint_memento_for(&dir, "rev", src);

        // Re-mint a memento from the param-renamed body to read its pins.
        let renamed = "#[sugar::sugar(op = \"c\", library = \"l\")]\npub fn rev(input: &str) -> String {\n    input.chars().rev().collect()\n}\n";
        let dir2 = unique_tmp("rename2");
        let renamed_memento = mint_memento_for(&dir2, "rev", renamed);
        // template_cid is STABLE across the param rename (alpha-equivalence).
        assert_eq!(
            memento.template_cid, renamed_memento.template_cid,
            "param rename must leave template_cid stable"
        );
        // source_cid DIFFERS (body text changed).
        assert_ne!(
            memento.source_cid, renamed_memento.source_cid,
            "param rename must drift source_cid"
        );

        // Resolving the ORIGINAL pin against the renamed disk refuses on source_cid.
        fs::write(dir.join("src/lib.rs"), renamed).unwrap();
        let err = resolve_source_memento(&dir, &memento).expect_err("rename must refuse");
        assert!(
            err.reason.contains("source CID misaligned"),
            "got: {}",
            err.reason
        );
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&dir).ok();
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&dir2).ok();
    }

    #[test]
    fn source_oracle_same_locus_replacement_reports_name_and_source_drift() {
        let dir = unique_tmp("replacement");
        let src = "#[sugar::sugar(op = \"c\", library = \"l\")]\npub fn rev(s: &str) -> String {\n    s.chars().rev().collect()\n}\n";
        let memento = mint_memento_for(&dir, "rev", src);
        // Same locus, different function. That is a name axis change plus source
        // drift, not "gone": the oracle can still see the replacement.
        fs::write(dir.join("src/lib.rs"), "pub fn other() -> u32 { 0 }\n").unwrap();
        let err = resolve_source_memento(&dir, &memento).expect_err("replacement must refuse");
        assert!(
            err.reason.contains("source name changed"),
            "same-locus replacement must name the name axis, got: {}",
            err.reason
        );
        assert!(
            err.reason.contains("source CID misaligned"),
            "replacement must still name the byte/source axis, got: {}",
            err.reason
        );
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn source_oracle_refuses_when_function_absent() {
        let dir = unique_tmp("absent");
        let src = "#[sugar::sugar(op = \"c\", library = \"l\")]\npub fn rev(s: &str) -> String {\n    s.chars().rev().collect()\n}\n";
        let memento = mint_memento_for(&dir, "rev", src);
        // Gone means no function exists at the pinned name or locus.
        fs::write(dir.join("src/lib.rs"), "pub struct Other;\n").unwrap();
        let err = resolve_source_memento(&dir, &memento).expect_err("absent fn must refuse");
        assert!(err.reason.contains("not found"), "got: {}", err.reason);
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn sugar_body_source_is_one_shape_without_inline_body_or_template() {
        let src = "#[sugar::sugar(op = \"c\", library = \"l\")]\npub fn rev(s: &str) -> String {\n    s.chars().rev().collect()\n}\n";
        let parsed = syn::parse_file(src).unwrap();
        let item_fn = parsed
            .items
            .iter()
            .find_map(|it| match it {
                syn::Item::Fn(f) => Some(f),
                _ => None,
            })
            .unwrap();
        let body_source = sugar_body_source("src/lib.rs", src, item_fn);
        let keys: BTreeSet<&str> = body_source
            .as_object()
            .expect("body_source object")
            .keys()
            .map(String::as_str)
            .collect();
        assert_eq!(
            keys,
            BTreeSet::from(["file", "span", "source_cid", "template_cid", "param_names"]),
            "SourceMemento is one shape: no inline body, no inline AST"
        );
        assert_eq!(
            body_source["source_cid"],
            blake3_512_of("s.chars().rev().collect()".as_bytes())
        );
        let param_names = vec!["s".to_string()];
        let expected_template = block_to_ast_template(&item_fn.block, &param_names);
        assert_eq!(
            body_source["template_cid"],
            blake3_512_of(expected_template.to_string().as_bytes())
        );
        assert!(body_source.get("span").is_some());
    }

    fn panic_loci_for_first_fn(src: &str) -> Vec<Value> {
        let file = syn::parse_file(src).expect("source parses");
        let item_fn = file
            .items
            .iter()
            .find_map(|item| match item {
                syn::Item::Fn(item_fn) => Some(item_fn),
                _ => None,
            })
            .expect("fixture has a function");
        collect_panic_loci(item_fn, "src/lib.rs")
    }

    fn assert_single_panic_locus_lines(
        src: &str,
        expected_producer_line: u64,
        expected_panic_line: u64,
    ) {
        let loci = panic_loci_for_first_fn(src);
        assert_eq!(loci.len(), 1, "expected one panic locus: {loci:?}");
        assert_eq!(loci[0]["file"], "src/lib.rs");
        assert_eq!(loci[0]["callee"], "method:unwrap");
        assert_eq!(
            loci[0]["line"].as_u64(),
            Some(expected_panic_line),
            "panic locus line must be the panic leaf line; producer provenance rides producerLine: {loci:?}"
        );
        assert_eq!(
            loci[0]["panicLine"].as_u64(),
            Some(expected_panic_line),
            "panicLine must preserve the unwrap leaf line for diagnostics: {loci:?}"
        );
        assert_eq!(
            loci[0]["producerLine"].as_u64(),
            Some(expected_producer_line),
            "producerLine must key the receiver producer bridge independently from the panic leaf: {loci:?}"
        );
    }

    #[test]
    fn collect_panic_loci_uses_receiver_line_for_single_line_unwrap() {
        let src = r#"pub fn one_line(v: &serde_json::Value) -> String {
    serde_json::to_string(v).unwrap()
}
"#;
        assert_single_panic_locus_lines(src, 2, 2);
    }

    #[test]
    fn collect_panic_loci_uses_receiver_line_for_two_line_unwrap() {
        let src = r#"pub fn two_line(v: &serde_json::Value) -> String {
    serde_json::to_string(v)
        .unwrap()
}
"#;
        assert_single_panic_locus_lines(src, 2, 3);
    }

    #[test]
    fn collect_panic_loci_uses_receiver_start_line_for_spanning_unwrap() {
        let src = r#"pub fn spanning(v: &serde_json::Value) -> String {
    serde_json::to_string(
        v,
    )
    .unwrap()
}
"#;
        assert_single_panic_locus_lines(src, 2, 5);
    }

    #[test]
    fn collect_panic_loci_splits_receiver_start_from_method_producer_line() {
        let src = r#"pub struct GrammarOpRegistry;
const CONCEPT_BIND_RESULT: &str = "concept:bind-result";

pub fn split_method_chain() -> Cid {
    GrammarOpRegistry
        .cid(CONCEPT_BIND_RESULT)
        .unwrap()
}
"#;
        let loci = panic_loci_for_first_fn(src);
        assert_eq!(loci.len(), 1, "expected one panic locus: {loci:?}");
        assert_eq!(loci[0]["line"].as_u64(), Some(7), "{loci:?}");
        assert_eq!(loci[0]["panicLine"].as_u64(), Some(7), "{loci:?}");
        assert_eq!(loci[0]["producerLine"].as_u64(), Some(6), "{loci:?}");
        assert_eq!(loci[0]["producerSymbol"], "method:cid", "{loci:?}");
    }

    #[test]
    fn disambiguated_partial_leaf_maps_panic_set() {
        // The four panic partials with REAL preconditions.
        assert_eq!(
            disambiguated_partial_leaf("option", "unwrap").as_deref(),
            Some("option_unwrap")
        );
        assert_eq!(
            disambiguated_partial_leaf("result", "unwrap").as_deref(),
            Some("result_unwrap")
        );
        assert_eq!(
            disambiguated_partial_leaf("option", "expect").as_deref(),
            Some("option_expect")
        );
        assert_eq!(
            disambiguated_partial_leaf("result", "expect").as_deref(),
            Some("result_expect")
        );
        assert_eq!(
            disambiguated_partial_leaf("result", "unwrap_err").as_deref(),
            Some("result_unwrap_err")
        );
    }

    #[test]
    fn disambiguated_partial_leaf_refuses_non_panic_and_mismatched() {
        // TOTAL methods are not in the table: they fall through to the bare leaf,
        // preserving their existing total-wrapper bridges.
        assert_eq!(disambiguated_partial_leaf("option", "unwrap_or"), None);
        assert_eq!(disambiguated_partial_leaf("slice", "get"), None);
        assert_eq!(disambiguated_partial_leaf("str", "len"), None);
        // A panic leaf on the WRONG type head is refused (no guess): `unwrap_err`
        // is a Result method, not Option.
        assert_eq!(disambiguated_partial_leaf("option", "unwrap_err"), None);
        // Unknown stem -> refuse.
        assert_eq!(disambiguated_partial_leaf("mystery", "unwrap"), None);
    }

    #[test]
    fn bind_lift_erases_signature_types_from_bind_ir_entries() {
        let root = temp_workspace("bind_lift_type_erasure");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn add(left: i64, right: i64) -> i64 {
    left + right
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entries = out["ir"].as_array().expect("ir array");
        let entry = entries.first().expect("add entry");
        assert_no_forbidden_bind_lift_entry_fields(entry);
        assert_eq!(entry["param_names"], json!(["left", "right"]));
        // Federation invariant (#1075/A9): the bind-lift-entry is CID-bearing
        // (embedded as arg[0] of the federated concept:bind-result payload and
        // feeding NamedTerm), so declared signature types must NOT appear on it
        // under the bare keys — typed-Rust would otherwise bind to a different
        // CID than untyped-Python and seam-4 byte-identity would break.
        assert!(
            entry.get("param_types").is_none(),
            "bare param_types must not ride the CID-bearing bind-lift-entry"
        );
        assert!(
            entry.get("return_type").is_none(),
            "bare return_type must not ride the CID-bearing bind-lift-entry"
        );
        assert!(
            entry.get("original_param_types").is_none(),
            "bare original_param_types must not ride the CID-bearing bind-lift-entry"
        );
        // The types are not LOST: they travel on the CID-invisible realize
        // sidecar (stripped before hashing by strip_realize_sidecar_from_lift_term)
        // so the Java boundary emitter can still realize the interface signature.
        assert_eq!(
            entry["realize_param_types"],
            json!(["i64", "i64"]),
            "signature types must be carried on the CID-invisible realize sidecar"
        );
        assert_eq!(
            entry["realize_return_type"],
            json!("i64"),
            "return type must be carried on the CID-invisible realize sidecar"
        );
        assert!(
            entry["witnesses"]
                .as_array()
                .expect("witnesses array")
                .iter()
                .all(|witness| witness["source_kind"] != "type-signature"),
            "signature type evidence must not cross the bind lift boundary"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bind_lift_marries_docstring_evidence_as_witnesses() {
        assert_eq!(
            initialize_result()["capabilities"]["ir_version"],
            "bind-ir/2.0.0",
            "the Rust kit must advertise the current bind IR schema"
        );

        let root = temp_workspace("bind_lift_witnesses");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
/// Requires amount > 0
/// Returns Some(...) if amount > 0
/// Panics if amount == 0
pub fn wrap_positive(amount: usize) -> Option<usize> {
    Some(amount)
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entries = out["ir"].as_array().expect("ir array");
        let entry = entries.first().expect("wrap_positive entry");
        assert_no_forbidden_bind_lift_entry_fields(entry);
        let witnesses = entry["witnesses"].as_array().expect("witnesses array");

        assert!(
            witnesses.iter().any(|w| w["source_kind"] == "docstring"
                && w["role"] == "pre"
                && w["extension_fields"]["pattern_kind"] == "requires"),
            "expected Requires docstring evidence to be married as a pre witness: {witnesses:#?}"
        );
        assert!(
            witnesses.iter().any(|w| w["source_kind"] == "docstring"
                && w["role"] == "post"
                && w["extension_fields"]["pattern_kind"] == "returns_if"),
            "expected Returns docstring evidence to be married as a post witness: {witnesses:#?}"
        );
        assert!(
            witnesses.iter().any(|w| w["source_kind"] == "docstring"
                && w["role"] == "panic"
                && w["extension_fields"]["pattern_kind"] == "panics_if"),
            "expected Panics docstring evidence to be preserved under the panic role: {witnesses:#?}"
        );
        assert!(
            witnesses
                .iter()
                .all(|w| w["source_kind"] != "type-signature"),
            "type-signature witnesses must not cross the bind lift boundary: {witnesses:#?}"
        );
        assert!(
            witnesses.iter().all(|w| {
                match w["extension_fields"].as_object() {
                    Some(fields) => !fields.contains_key("role"),
                    None => false,
                }
            }),
            "bind witness wire entries must keep role top-level only: {witnesses:#?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn kit_declaration_result_is_valid_without_concept_vocabulary() {
        let declaration: sugar_claim_envelope::KitDeclaration =
            serde_json::from_value(kit_declaration_result()).expect("kit declaration shape");

        declaration.validate().expect("valid kit declaration");
        assert_eq!(declaration.kit.id, "sugar-walk-rpc");
        assert_eq!(declaration.kit.language, "rust");
    }

    #[test]
    fn sugar_attr_annotated_fn_emits_library_sugar_binding_entry() {
        let root = temp_workspace("sugar_positive");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src = r#"
#[sugar::sugar(op = "http-request", library = "reqwest")]
async fn fetch_status(url: String) -> i64 {
    0
}
"#;
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(
            sugar.len(),
            1,
            "expected exactly one sugar entry, got: {sugar:?}"
        );
        let e = &sugar[0];
        assert_eq!(e["kind"], "library-sugar-binding-entry");
        assert_eq!(e["target_language"], "rust");
        assert_eq!(e["target_library_tag"], "reqwest");
        assert_eq!(
            e["op_cid"],
            local_op_cid("http-request").expect("http-request op cid")
        );
        assert_eq!(e["source_function_name"], "fetch_status");
        assert!(
            e["signature_shape_cid"]
                .as_str()
                .expect("signature cid")
                .starts_with("blake3-512:"),
            "bad sig cid"
        );
        assert!(
            e["body_source"]["source_cid"]
                .as_str()
                .expect("source cid")
                .starts_with("blake3-512:"),
            "bad source cid"
        );
        // The body-source span is attribute-inclusive: it starts at the function's
        // first attribute line, not the `fn`/`async fn` line. Here the leading `\n`
        // is line 1, the attribute is line 2, the `async fn` is line 3 -- so the
        // surface starts at line 2. Pinning the attribute in the source fragment is
        // deliberate: a rust attribute edit that changes behavior (cfg/repr/derive/
        // inline/...) also moves source_cid, so it is caught as source drift rather
        // than left dark. source_oracle.rs's `source_memento_of_named_item_fn` test
        // pins the same attribute-inclusive semantics.
        assert_eq!(e["body_source"]["span"]["start_line"], 2);
        assert_eq!(e["loss_record_contribution"]["form"], "literal");
        assert_eq!(e["loss_record_contribution"]["value"]["entries"], json!([]));
        assert!(
            e.get("signature_shape").is_none(),
            "must not emit full signature_shape doc"
        );
        assert!(
            e["body_source"].get("locator").is_none(),
            "must use span not locator"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn untagged_pub_fn_derives_library_sugar_binding_entry_in_library_bindings_layer() {
        // The relapse-killer: a PLAIN `pub fn` with NO `#[sugar::sugar]`
        // attribute must ALSO emit a `library-sugar-binding-entry` when the
        // `library-bindings` layer is active — the tag is gone; the binding is
        // DERIVED from the crate name + fn name. Mirror of python's universal
        // lift. The `target_library_tag` is the RAW crate name (hyphens intact)
        // so it matches a consumer's `#[sugar::boundary(library = ...)]`.
        let root = temp_workspace("derive_positive");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            "[package]\nname = \"rust-boundary-vendor\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
        )
        .expect("write Cargo.toml");
        let src = "pub fn reverse_chars(s: &str) -> String {\n    s.chars().rev().collect()\n}\n";
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
            "options": { "layer": "library-bindings" },
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let derived: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(
            derived.len(),
            1,
            "expected exactly one derived sugar entry, got: {derived:?}"
        );
        let e = &derived[0];
        assert_eq!(e["target_language"], "rust");
        assert_eq!(
            e["target_library_tag"], "rust-boundary-vendor",
            "derived tag must be the RAW crate name (hyphens intact)"
        );
        assert_eq!(e["symbol"], "rust-boundary-vendor.reverse_chars");
        assert_eq!(e["binding_origin"], "derived");
        assert_eq!(e["source_function_name"], "reverse_chars");
        assert_eq!(
            e["op_cid"],
            json!(canonical_local_op_cid("rust-boundary-vendor.reverse_chars").unwrap())
        );
        assert!(
            e["body_source"]["source_cid"]
                .as_str()
                .expect("source cid")
                .starts_with("blake3-512:"),
            "bad source cid"
        );
        assert!(
            e["body_source"]["span"]["start_line"].is_number(),
            "derived body_source must carry a locus span"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn untagged_pub_fn_does_not_derive_in_general_all_layer() {
        // Membrane: the derived path is GATED to `library-bindings`. A plain
        // `pub fn` lifted in the default (no-layer / `all`) path must NOT emit a
        // derived binding — else every general lift floods spurious entries.
        let root = temp_workspace("derive_negative");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            "[package]\nname = \"rust-boundary-vendor\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
        )
        .expect("write Cargo.toml");
        let src = "pub fn reverse_chars(s: &str) -> String {\n    s.chars().rev().collect()\n}\n";
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let derived: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert!(
            derived.is_empty(),
            "no-layer lift must NOT derive sugar bindings, got: {derived:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn sugar_body_source_uses_rust_block_span_for_source_cid_without_storing_body() {
        let src = r####"
#[sugar::sugar(op = "http-request", library = "reqwest")]
async fn render(url: String) -> String {
    let normal = "}";
    let raw = r###"raw } braces { stay"###;
    // comment with } before the real block end
    let macro_value = format!("literal }} and {}", url);
    let nested = {
        let inner = "{";
        inner.len()
    };
    let future = async {
        let block = unsafe { normal.len() + raw.len() };
        block + nested
    };
    format!("{normal}:{raw}:{macro_value}:{}", future.await)
}
"####;
        let entry = single_sugar_entry_for_source("sugar_body_span_braces", src);
        let expected = r####"let normal = "}";
    let raw = r###"raw } braces { stay"###;
    // comment with } before the real block end
    let macro_value = format!("literal }} and {}", url);
    let nested = {
        let inner = "{";
        inner.len()
    };
    let future = async {
        let block = unsafe { normal.len() + raw.len() };
        block + nested
    };
    format!("{normal}:{raw}:{macro_value}:{}", future.await)"####;

        assert_eq!(
            entry["body_source"]["source_cid"],
            blake3_512_of(expected.as_bytes())
        );
        assert!(entry["body_source"].get("body_text").is_none());
    }

    #[test]
    fn sugar_body_source_uses_byte_offsets_for_unicode_source_cid_without_storing_body() {
        let src = r#"
#[sugar::sugar(op = "unicode", library = "unicode-lib")]
pub fn snowman() -> &'static str { "☃ } still body" }
"#;
        let entry = single_sugar_entry_for_source("sugar_body_unicode_byte_offsets", src);
        let expected = r#""☃ } still body""#;

        assert_eq!(
            entry["body_source"]["source_cid"],
            blake3_512_of(expected.as_bytes())
        );
        assert!(entry["body_source"].get("body_text").is_none());
    }

    #[test]
    fn sugar_body_source_canonicalizes_trimmed_body_for_source_cid_without_storing_body() {
        let src_a = r#"
#[sugar::sugar(op = "canonical-body", library = "test-lib")]
pub fn canonical_body() -> i64 {

    41 + 1

}
"#;
        let src_b = r#"
#[sugar::sugar(op = "canonical-body", library = "test-lib")]
pub fn canonical_body() -> i64 {    41 + 1    }
"#;

        let entry_a = single_sugar_entry_for_source("sugar_body_canonical_a", src_a);
        let entry_b = single_sugar_entry_for_source("sugar_body_canonical_b", src_b);
        let body_source_a = &entry_a["body_source"];
        let body_source_b = &entry_b["body_source"];

        assert_eq!(body_source_a["source_cid"], body_source_b["source_cid"]);
        assert_eq!(
            body_source_a["source_cid"],
            blake3_512_of("41 + 1".as_bytes())
        );
        assert!(body_source_a.get("body_text").is_none());
        assert!(body_source_b.get("body_text").is_none());
    }

    // ---------------------------------------------------------------------
    // Recognizer foundation (#81 / #82): source-pass computes source/template
    // pins for the one-shape SourceMemento. The proof carries only CIDs; the
    // recognizer recomputes candidate template_cid from user source and matches
    // by content-address equality.
    // ---------------------------------------------------------------------

    #[test]
    fn sugar_body_source_emits_template_cid_without_storing_template() {
        let src = r##"
#[sugar::sugar(op = "json-parse", library = "serde_json")]
pub fn json_parse(s: &str) -> i64 {
    serde_json::from_str(s)
}
"##;
        let entry = single_sugar_entry_for_source("sugar_template_cid_basic", src);
        let parsed = syn::parse_file(src).unwrap();
        let item_fn = parsed
            .items
            .iter()
            .find_map(|it| match it {
                syn::Item::Fn(f) => Some(f),
                _ => None,
            })
            .unwrap();
        let param_names = vec!["s".to_string()];
        let template = block_to_ast_template(&item_fn.block, &param_names);
        assert_eq!(template["kind"], "block");
        let stmts = template["stmts"].as_array().expect("stmts array");
        assert_eq!(stmts.len(), 1, "one statement in body");
        let stmt = &stmts[0];
        assert_eq!(stmt["kind"], "expr_stmt");
        let call = &stmt["expr"];
        assert_eq!(call["kind"], "call");
        assert_eq!(call["func"]["kind"], "path");
        assert_eq!(call["func"]["segments"], json!(["serde_json", "from_str"]));
        // Param `s` canonicalized to $1.
        let args = call["args"].as_array().expect("args array");
        assert_eq!(args.len(), 1);
        assert_eq!(args[0]["kind"], "param_ref");
        assert_eq!(args[0]["index"], 1);
        assert_eq!(
            entry["body_source"]["template_cid"],
            blake3_512_of(template.to_string().as_bytes())
        );
        assert!(entry["body_source"].get("ast_template").is_none());
    }

    #[test]
    fn sugar_body_template_canonicalizes_multiple_params_positionally() {
        let src = r##"
#[sugar::sugar(op = "sql-execute", library = "rusqlite")]
pub fn execute(conn: &i64, sql: &str, args: &i64) -> i64 {
    conn.execute(sql, args)
}
"##;
        let entry = single_sugar_entry_for_source("sugar_template_cid_params", src);
        let parsed = syn::parse_file(src).unwrap();
        let item_fn = parsed
            .items
            .iter()
            .find_map(|it| match it {
                syn::Item::Fn(f) => Some(f),
                _ => None,
            })
            .unwrap();
        let param_names = vec!["conn".to_string(), "sql".to_string(), "args".to_string()];
        let template = block_to_ast_template(&item_fn.block, &param_names);
        let stmt = &template["stmts"][0];
        let mc = &stmt["expr"];
        assert_eq!(mc["kind"], "method_call");
        // Receiver is param #1 (conn).
        assert_eq!(mc["receiver"]["kind"], "param_ref");
        assert_eq!(mc["receiver"]["index"], 1);
        assert_eq!(mc["method"], "execute");
        // Args are $2 (sql) and $3 (args).
        let mc_args = mc["args"].as_array().expect("mc args");
        assert_eq!(mc_args.len(), 2);
        assert_eq!(mc_args[0]["kind"], "param_ref");
        assert_eq!(mc_args[0]["index"], 2);
        assert_eq!(mc_args[1]["kind"], "param_ref");
        assert_eq!(mc_args[1]["index"], 3);
        assert_eq!(
            entry["body_source"]["template_cid"],
            blake3_512_of(template.to_string().as_bytes())
        );
        assert!(entry["body_source"].get("ast_template").is_none());
    }

    #[test]
    fn sugar_body_template_cid_is_stable_under_param_renaming() {
        // Canonical templates with $1/$2 must be byte-identical for two
        // sugar functions that differ only in their parameter names.
        let src_a = r##"
#[sugar::sugar(op = "noop", library = "ka")]
pub fn op(x: &i64, y: &i64) -> i64 {
    x.add(y)
}
"##;
        let src_b = r##"
#[sugar::sugar(op = "noop", library = "kb")]
pub fn op(alpha: &i64, beta: &i64) -> i64 {
    alpha.add(beta)
}
"##;
        let entry_a = single_sugar_entry_for_source("sugar_template_cid_alpha_a", src_a);
        let entry_b = single_sugar_entry_for_source("sugar_template_cid_alpha_b", src_b);
        assert_eq!(
            entry_a["body_source"]["template_cid"], entry_b["body_source"]["template_cid"],
            "template_cid must match across alpha-equivalent sugars"
        );
        assert_ne!(
            entry_a["body_source"]["source_cid"],
            entry_b["body_source"]["source_cid"]
        );
        assert!(entry_a["body_source"].get("body_text").is_none());
        assert!(entry_b["body_source"].get("body_text").is_none());
        assert!(entry_a["body_source"].get("ast_template").is_none());
        assert!(entry_b["body_source"].get("ast_template").is_none());
    }

    // ---------------------------------------------------------------------
    // Recognizer foundation Phase C (#81, #82, #86): the sugar.plugin.recognize
    // RPC handler. Walks user source, matches function bodies' identifier-
    // canonical templates against supplied binding_templates by template_cid,
    // emits tier-`exact` tags for matches. Tier-1 = exact-cid match.
    // ---------------------------------------------------------------------

    #[test]
    fn recognize_emits_exact_tag_for_alpha_equivalent_user_function() {
        // The shim's sugar (what would land in the .proof envelope):
        let sugar_src = r##"
#[sugar::sugar(op = "json-parse", library = "sugar-shim-serde-json-rust")]
pub fn json_parse(s: &str) -> i64 {
    serde_json::from_str(s)
}
"##;
        let sugar_entry = single_sugar_entry_for_source("recognize_sugar_src", sugar_src);
        let binding_template = json!({
            "op_cid": sugar_entry["op_cid"],
            "library_tag": sugar_entry["target_library_tag"],
            "template_cid": sugar_entry["body_source"]["template_cid"],
            "param_names": sugar_entry["body_source"]["param_names"],
            "contract_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        });

        // The user's function — alpha-equivalent (different param name).
        let user_src = r##"
pub fn json_parse(input: &str) -> Result<serde_json::Value, String> {
    serde_json::from_str(input)
}
"##;
        let root = temp_workspace("recognize_user_src");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let user_rel = "src/lib.rs";
        fs::write(root.join(user_rel), user_src).expect("write user source");

        let resp = recognize(&json!({
            "project_root": root.to_string_lossy(),
            "source_paths": [user_rel],
            "binding_templates": [binding_template],
        }))
        .expect("recognize should succeed");

        let tags = resp["tags"].as_array().expect("tags array");
        assert_eq!(tags.len(), 1, "alpha-equivalent body must match: {tags:?}");
        let tag = &tags[0];
        assert_eq!(
            tag["op_cid"],
            local_op_cid("json-parse").expect("json op cid")
        );
        assert_eq!(tag["library_tag"], "sugar-shim-serde-json-rust");
        assert_eq!(tag["match_tier"], "exact");
        assert_eq!(tag["file"], user_rel);
        // param_bindings reflects the USER's spelling (input), not the sugar's (s).
        let bindings = tag["param_bindings"].as_array().expect("param_bindings");
        assert_eq!(bindings.len(), 1);
        assert_eq!(bindings[0]["index"], 1);
        assert_eq!(bindings[0]["source_text"], "input");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recognize_loads_binding_templates_from_imported_proofs() {
        let sugar_src = r##"
#[sugar::sugar(op = "json-parse", library = "sugar-shim-serde-json-rust")]
pub fn json_parse(s: &str) -> i64 {
    serde_json::from_str(s)
}
"##;
        let sugar_entry = single_sugar_entry_for_source("recognize_imported_sugar", sugar_src);
        let contract_cid = "blake3-512:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";

        let user_src = r##"
pub fn json_parse(input: &str) -> Result<serde_json::Value, String> {
    serde_json::from_str(input)
}
"##;
        let root = temp_workspace("recognize_imported_user");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let user_rel = "src/lib.rs";
        fs::write(root.join(user_rel), user_src).expect("write user source");

        let proof_cid = write_sugar_binding_proof(
            &root.join(".sugar").join("imports"),
            sugar_entry,
            contract_cid,
            "@test/rust-recognize-imported-shim",
        );

        let resp = recognize(&json!({
            "project_root": root.to_string_lossy(),
            "source_paths": [user_rel],
        }))
        .expect("recognize should succeed");

        let tags = resp["tags"].as_array().expect("tags array");
        assert_eq!(
            tags.len(),
            1,
            "Rust recognizer must self-resolve imported sugar binding proofs without CLI binding_templates: {tags:?}"
        );
        let tag = &tags[0];
        assert_eq!(
            tag["op_cid"],
            local_op_cid("json-parse").expect("json op cid")
        );
        assert_eq!(tag["library_tag"], "sugar-shim-serde-json-rust");
        assert_eq!(tag["contract_cid"], contract_cid);
        assert_eq!(tag["target_proof_cid"], proof_cid);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recognize_matches_template_cid_only_imported_proof() {
        let sugar_src = r##"
#[sugar::sugar(op = "json-parse", library = "sugar-shim-serde-json-rust")]
pub fn json_parse(s: &str) -> i64 {
    serde_json::from_str(s)
}
"##;
        let mut sugar_entry =
            single_sugar_entry_for_source("recognize_template_cid_only_sugar", sugar_src);
        let contract_cid = "blake3-512:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
        let body_source = sugar_entry["body_source"]
            .as_object_mut()
            .expect("body_source object");
        assert!(body_source.get("template_cid").is_some());
        assert!(body_source.get("body_text").is_none());
        assert!(body_source.get("ast_template").is_none());

        let user_src = r##"
pub fn json_parse(input: &str) -> Result<serde_json::Value, String> {
    serde_json::from_str(input)
}
"##;
        let root = temp_workspace("recognize_template_cid_only_user");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let user_rel = "src/lib.rs";
        fs::write(root.join(user_rel), user_src).expect("write user source");

        let proof_cid = write_sugar_binding_proof(
            &root.join(".sugar").join("imports"),
            sugar_entry,
            contract_cid,
            "@test/rust-recognize-template-cid-only-shim",
        );

        let resp = recognize(&json!({
            "project_root": root.to_string_lossy(),
            "source_paths": [user_rel],
        }))
        .expect("recognize should succeed");

        let tags = resp["tags"].as_array().expect("tags array");
        assert_eq!(
            tags.len(),
            1,
            "Rust recognizer must match imported sugar proofs by pinned template_cid alone: {tags:?}"
        );
        let tag = &tags[0];
        assert_eq!(
            tag["op_cid"],
            local_op_cid("json-parse").expect("json op cid")
        );
        assert_eq!(tag["library_tag"], "sugar-shim-serde-json-rust");
        assert_eq!(tag["contract_cid"], contract_cid);
        assert_eq!(tag["target_proof_cid"], proof_cid);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recognize_loads_binding_templates_from_cargo_dependency_proofs() {
        let sugar_src = r##"
#[sugar::sugar(op = "json-parse", library = "sugar-shim-serde-json-rust")]
pub fn json_parse(s: &str) -> i64 {
    serde_json::from_str(s)
}
"##;
        let sugar_entry = single_sugar_entry_for_source("recognize_cargo_sugar", sugar_src);
        let contract_cid = "blake3-512:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff";

        let root = temp_workspace("recognize_cargo_dependency");
        let project = root.join("project");
        let dep = root.join("recognize-shim");
        fs::create_dir_all(project.join("src")).expect("create project src");
        fs::create_dir_all(dep.join("src")).expect("create dep src");
        fs::write(
            project.join("Cargo.toml"),
            r#"[package]
name = "recognize-user"
version = "0.1.0"
edition = "2021"

[dependencies]
recognize-shim = { path = "../recognize-shim" }
"#,
        )
        .expect("write project Cargo.toml");
        fs::write(
            dep.join("Cargo.toml"),
            r#"[package]
name = "recognize-shim"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write dep Cargo.toml");
        fs::write(dep.join("src").join("lib.rs"), "pub fn marker() {}\n").expect("write dep src");
        let user_rel = "src/lib.rs";
        fs::write(
            project.join(user_rel),
            r##"
pub fn json_parse(input: &str) -> Result<serde_json::Value, String> {
    serde_json::from_str(input)
}
"##,
        )
        .expect("write user source");
        let proof_cid = write_sugar_binding_proof(
            &dep,
            sugar_entry,
            contract_cid,
            "@test/rust-recognize-cargo-shim",
        );

        let resp = recognize(&json!({
            "project_root": project.to_string_lossy(),
            "source_paths": [user_rel],
        }))
        .expect("recognize should succeed");

        let tags = resp["tags"].as_array().expect("tags array");
        assert_eq!(
            tags.len(),
            1,
            "Rust recognizer must resolve package proof templates through Cargo metadata: {tags:?}"
        );
        let tag = &tags[0];
        assert_eq!(
            tag["op_cid"],
            local_op_cid("json-parse").expect("json op cid")
        );
        assert_eq!(tag["contract_cid"], contract_cid);
        assert_eq!(tag["target_proof_cid"], proof_cid);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recognize_returns_empty_tags_for_non_matching_source() {
        let sugar_src = r##"
#[sugar::sugar(op = "json-parse", library = "sugar-shim-serde-json-rust")]
pub fn json_parse(s: &str) -> i64 {
    serde_json::from_str(s)
}
"##;
        let sugar_entry = single_sugar_entry_for_source("recognize_neg_sugar", sugar_src);
        let binding_template = json!({
            "op_cid": sugar_entry["op_cid"],
            "library_tag": sugar_entry["target_library_tag"],
            "template_cid": sugar_entry["body_source"]["template_cid"],
            "contract_cid": "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        });

        // User's function is structurally DIFFERENT — calls a different function.
        let user_src = r##"
pub fn json_parse(s: &str) -> i64 {
    completely_different_function(s)
}
"##;
        let root = temp_workspace("recognize_neg_user");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let user_rel = "src/lib.rs";
        fs::write(root.join(user_rel), user_src).expect("write user source");

        let resp = recognize(&json!({
            "project_root": root.to_string_lossy(),
            "source_paths": [user_rel],
            "binding_templates": [binding_template],
        }))
        .expect("recognize should succeed");

        let tags = resp["tags"].as_array().expect("tags array");
        assert!(
            tags.is_empty(),
            "non-matching source must produce no tags: {tags:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recognize_routes_multiple_bindings_per_call_site_pool() {
        // Two binding templates (json + sql shapes). User source contains
        // one match for each. Recognize emits two tags.
        let json_sugar = r##"
#[sugar::sugar(op = "json-parse", library = "json-lib")]
pub fn json_parse(s: &str) -> i64 {
    serde_json::from_str(s)
}
"##;
        let sql_sugar = r##"
#[sugar::sugar(op = "sql-execute", library = "sql-lib")]
pub fn sql_execute(conn: &i64, sql: &str, args: &i64) -> i64 {
    conn.execute(sql, args)
}
"##;
        let json_entry = single_sugar_entry_for_source("recognize_multi_json", json_sugar);
        let sql_entry = single_sugar_entry_for_source("recognize_multi_sql", sql_sugar);
        let bindings = json!([
            {
                "op_cid": json_entry["op_cid"],
                "library_tag": json_entry["target_library_tag"],
                "template_cid": json_entry["body_source"]["template_cid"],
                "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            },
            {
                "op_cid": sql_entry["op_cid"],
                "library_tag": sql_entry["target_library_tag"],
                "template_cid": sql_entry["body_source"]["template_cid"],
                "contract_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            }
        ]);

        let user_src = r##"
pub fn json_parse(input: &str) -> i64 {
    serde_json::from_str(input)
}

pub fn sql_execute(c: &i64, q: &str, p: &i64) -> i64 {
    c.execute(q, p)
}
"##;
        let root = temp_workspace("recognize_multi_user");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let user_rel = "src/lib.rs";
        fs::write(root.join(user_rel), user_src).expect("write user source");

        let resp = recognize(&json!({
            "project_root": root.to_string_lossy(),
            "source_paths": [user_rel],
            "binding_templates": bindings,
        }))
        .expect("recognize");

        let tags = resp["tags"].as_array().expect("tags array");
        assert_eq!(tags.len(), 2, "expected 2 tags (json + sql): {tags:?}");
        let op_cids: Vec<&str> = tags.iter().filter_map(|t| t["op_cid"].as_str()).collect();
        assert!(op_cids.contains(&local_op_cid("json-parse").expect("json op cid")));
        assert!(op_cids.contains(&local_op_cid("sql-execute").expect("sql op cid")));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn sugar_body_emits_param_names_list_for_recognize_binding() {
        // The recognize side needs the original param names to bind the
        // template's $N markers back to the user's actual variables at
        // tag emission time. The lifter exposes them as a separate field.
        let src = r##"
#[sugar::sugar(op = "sql-query-row", library = "rusqlite")]
pub fn query_row(conn: &i64, sql: &str, params: &i64, mapper: &i64) -> i64 {
    conn.query_row(sql, params, mapper)
}
"##;
        let entry = single_sugar_entry_for_source("sugar_template_cid_paramnames", src);
        let names = entry["body_source"]["param_names"]
            .as_array()
            .expect("param_names array");
        assert_eq!(names.len(), 4);
        assert_eq!(names[0], "conn");
        assert_eq!(names[1], "sql");
        assert_eq!(names[2], "params");
        assert_eq!(names[3], "mapper");
    }

    // ---------------------------------------------------------------------
    // #1357 / #1355: version axis on @sugar / @boundary annotations
    // ---------------------------------------------------------------------

    #[test]
    fn sugar_attr_with_family_and_version_emits_into_binding_entry() {
        let root = temp_workspace("sugar_family_version");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src = r#"
#[sugar::sugar(
    op = "sql-query",
    library = "rusqlite",
    version = "0.39.0",
)]
pub fn query(conn: &i64, sql: &str) -> i64 {
    0
}
"#;
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(sugar.len(), 1, "expected one sugar entry, got: {sugar:?}");
        let e = &sugar[0];
        assert_eq!(e["target_library_tag"], "rusqlite");
        assert_eq!(e["library_version"], "0.39.0");
        assert_eq!(
            e["op_cid"],
            local_op_cid("sql-query").expect("sql-query op cid")
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn sugar_attr_without_family_or_version_omits_those_fields() {
        // Back-compat: existing shims without version annotations must
        // still mint, with the new fields simply absent (NOT empty strings).
        let root = temp_workspace("sugar_no_family_version");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src = r#"
#[sugar::sugar(op = "http-request", library = "reqwest")]
async fn fetch_status(url: String) -> i64 {
    0
}
"#;
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let e = ir
            .iter()
            .find(|e| e["kind"] == "library-sugar-binding-entry")
            .expect("sugar entry");
        assert!(
            e.get("library_version").is_none() || e["library_version"].is_null(),
            "library_version must not be emitted when absent on annotation"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn unannotated_fn_produces_zero_sugar_entries() {
        let root = temp_workspace("sugar_discrim");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src = r#"
fn plain_fn(x: i64) -> i64 {
    x + 1
}
"#;
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(
            sugar.len(),
            0,
            "unannotated fn must produce zero sugar entries"
        );
        let bind: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "bind-lift-entry")
            .collect();
        assert_eq!(
            bind.len(),
            1,
            "regular bind-lift-entry must still be emitted"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn two_sugar_annotated_fns_produce_two_entries() {
        let root = temp_workspace("sugar_multi");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src = r#"
#[sugar::sugar(op = "http-request", library = "reqwest")]
fn fetch_one(url: String) -> i64 {
    0
}

#[sugar::sugar(op = "sql-query", library = "rusqlite")]
fn query_db(sql: String) -> String {
    String::new()
}
"#;
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(
            sugar.len(),
            2,
            "two annotated fns must produce two sugar entries"
        );
        let op_cids: Vec<_> = sugar
            .iter()
            .map(|e| e["op_cid"].as_str().expect("op cid"))
            .collect();
        assert!(
            op_cids.contains(&local_op_cid("http-request").expect("http op cid")),
            "{op_cids:?}"
        );
        assert!(
            op_cids.contains(&local_op_cid("sql-query").expect("sql op cid")),
            "{op_cids:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn malformed_sugar_attr_missing_concept_or_library_produces_zero_entries() {
        let root = temp_workspace("sugar_malformed");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src_missing_lib = r#"
#[sugar::sugar(op = "http-request")]
fn missing_lib(url: String) -> i64 { 0 }
"#;
        fs::write(src_dir.join("lib.rs"), src_missing_lib).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(
            sugar.len(),
            0,
            "missing library must produce zero sugar entries"
        );

        let src_missing_concept = r#"
#[sugar::sugar(library = "reqwest")]
fn missing_concept(url: String) -> i64 { 0 }
"#;
        fs::write(src_dir.join("lib.rs"), src_missing_concept).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(
            sugar.len(),
            0,
            "missing concept must produce zero sugar entries"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn term_shape_simple_add_is_canonical_gamma_literal() {
        let shape = term_shape_json(
            r#"
pub fn add(x: i64, y: i64) -> i64 {
    x + y
}
"#,
        );
        let add_cid = local_op_cid("add").expect("concept:add cid");

        // Substrate-canonical shape (#1075 federation): operand NAMES are
        // sugar, so scoped param/local references lift as EMPTY structural
        // leaves {}. The names travel on the CID-invisible operand_bindings
        // sidecar (verified separately below), making the rust term_shape
        // byte-identical to the python lifter's empty-leaf form so the same
        // algebra federates cross-language. f(x)=x+y and f(a)=a+b share this
        // shape. (Earlier the names rode the leaf, which made the shape
        // name-dependent and broke seam-4 byte-identity.)
        assert_eq!(
            shape,
            json!({
                "args": [
                    {},
                    {},
                ],
                "op_cid": add_cid
            })
        );

        // Names-are-sugar: the operand symbols are recovered from the
        // operand_bindings sidecar (CID-invisible), not the leaves.
        let out = bind_lift(&{
            let root = temp_workspace("term_shape_add_bindings");
            let src_dir = root.join("src");
            fs::create_dir_all(&src_dir).expect("create src dir");
            fs::write(
                src_dir.join("lib.rs"),
                "pub fn add(x: i64, y: i64) -> i64 {\n    x + y\n}\n",
            )
            .expect("write source");
            let params = json!({
                "workspace_root": root.to_string_lossy(),
                "source_paths": ["."]
            });
            // leak the temp dir path via params; cleaned by OS temp reaper
            params
        })
        .expect("bind lift should succeed");
        let entry = out["ir"].as_array().expect("ir").first().expect("entry");
        let bindings = entry["operand_bindings"]
            .as_array()
            .expect("operand_bindings array");
        let symbols: Vec<&str> = bindings
            .iter()
            .filter_map(|b| b["symbol"].as_str())
            .collect();
        assert!(
            symbols.contains(&"x") && symbols.contains(&"y"),
            "operand symbols x,y must live on the operand_bindings sidecar, not the leaves: {bindings:#?}"
        );
    }

    // ---------------------------------------------------------------------
    // #1363 / #1355: integer-width metadata on concept:literal shapes
    // ---------------------------------------------------------------------

    #[test]
    fn integer_literal_with_u8_suffix_emits_integer_width_u8() {
        let shape = term_shape_json(
            r#"
pub fn first() -> i64 {
    let x = 0u8;
    1
}
"#,
        );
        let json_text = serde_json::to_string(&shape).expect("shape stringifies");
        assert!(
            json_text.contains("\"integer_width\":\"u8\""),
            "u8-suffixed literal must carry integer_width=u8: {json_text}"
        );
    }

    #[test]
    fn integer_literal_with_i32_suffix_emits_integer_width_i32() {
        let shape = term_shape_json(
            r#"
pub fn first() -> i64 {
    let x = 5i32;
    1
}
"#,
        );
        let json_text = serde_json::to_string(&shape).expect("shape stringifies");
        assert!(
            json_text.contains("\"integer_width\":\"i32\""),
            "i32-suffixed literal must carry integer_width=i32: {json_text}"
        );
    }

    #[test]
    fn integer_literal_without_suffix_emits_integer_width_inferred() {
        let shape = term_shape_json(
            r#"
pub fn first() -> i64 {
    let x = 42;
    1
}
"#,
        );
        let json_text = serde_json::to_string(&shape).expect("shape stringifies");
        assert!(
            json_text.contains("\"integer_width\":\"inferred\""),
            "unsuffixed literal must mark inferred: {json_text}"
        );
    }

    #[test]
    fn term_shape_rust_char_literal_lifts_as_concept_literal_with_value() {
        // Substrate-canonical char literal shape: (sort=concept:String CID,
        // value=<char as string>). Source-form spelling ('a' vs '\u{61}')
        // is kit presentation; substrate carries semantic identity only.
        // (2026-05-21: source_text dropped from substrate channel; the rust
        // realize binary re-spells via literal_term_with_width.)
        let shape = term_shape_json(
            r#"
pub fn first() -> char {
    'a'
}
"#,
        );
        assert_eq!(
            shape.get("op_cid").and_then(|v| v.as_str()),
            local_op_cid("literal"),
            "Char literal must lift as concept:literal: {shape}"
        );
        assert_eq!(
            shape.get("value").and_then(|v| v.as_str()),
            Some("a"),
            "char value must carry semantic identity (the actual character)"
        );
        assert!(
            shape.get("source_text").is_none(),
            "source_text must not appear in substrate channel: {shape}"
        );
    }

    #[test]
    fn bind_lift_emits_operand_binding_sidecar_with_integer_positions() {
        let root = temp_workspace("bind_lift_operand_binding_sidecar");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn add(x: i64, y: i64) -> i64 {
    x + y
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entries = out["ir"].as_array().expect("ir array");
        let entry = entries.first().expect("add entry");
        assert_no_forbidden_bind_lift_entry_fields(entry);
        assert_eq!(entry["source_function_name"], json!("add"));
        assert_eq!(
            entry["operand_bindings"],
            json!([
                {"position": [0], "symbol": "x"},
                {"position": [1], "symbol": "y"},
            ])
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bind_lift_line_comments_as_concept_comment_terms() {
        let root = temp_workspace("bind_lift_line_comments");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn commented(value: i64) -> i64 {
    // first line comment
    let next = value + 1;
    // second line comment
    // third line comment
    next
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entry = out["ir"]
            .as_array()
            .expect("ir array")
            .first()
            .expect("entry");
        assert_eq!(
            comment_surfaces(&entry["term_shape"]),
            vec![
                "// first line comment".to_string(),
                "// second line comment".to_string(),
                "// third line comment".to_string(),
            ]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bind_lift_excludes_concept_carrier_line_comments() {
        let root = temp_workspace("bind_lift_comment_carriers");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn commented(value: i64) -> i64 {
    // sugar:concept:skip
    // sugar-concept: {}
    // sugar-concept-payload-cid: blake3-512:dead
    // ordinary line comment
    value
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entry = out["ir"]
            .as_array()
            .expect("ir array")
            .first()
            .expect("entry");
        assert_eq!(
            comment_surfaces(&entry["term_shape"]),
            vec!["// ordinary line comment".to_string()]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bind_lift_block_comments_as_concept_comment_terms() {
        let root = temp_workspace("bind_lift_block_comments");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn commented(value: i64) -> i64 {
    /* first block comment */
    let next = value + 1;
    /* second
       block comment */
    /* third block comment */
    next
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entry = out["ir"]
            .as_array()
            .expect("ir array")
            .first()
            .expect("entry");
        assert_eq!(
            comment_surfaces(&entry["term_shape"]),
            vec![
                "/* first block comment */".to_string(),
                "/* second\n       block comment */".to_string(),
                "/* third block comment */".to_string(),
            ]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bind_lift_ignores_comment_markers_inside_strings() {
        let root = temp_workspace("bind_lift_comment_string_markers");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn commented() -> &'static str {
    let text = "// not a comment /* still not a comment */";
    /* actual block */
    // actual line
    text
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entry = out["ir"]
            .as_array()
            .expect("ir array")
            .first()
            .expect("entry");
        assert_eq!(
            comment_surfaces(&entry["term_shape"]),
            vec![
                "/* actual block */".to_string(),
                "// actual line".to_string()
            ]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn term_shape_let_binding_preserves_assignment_boundary() {
        let shape = term_shape_json(
            r#"
pub fn add_via_let(a: i64, b: i64) -> i64 {
    let q = a + b;
    q
}
"#,
        );
        let assign_cid = local_op_cid("assign").expect("assign cid");
        let add_cid = local_op_cid("add").expect("add cid");

        // Substrate-canonical shape (#1075 federation):
        // - assign TARGET is kind:symbol "q" — a let-binding NAME is structural
        //   data (it declares a new name), so it stays in the shape.
        // - SCOPED operand references (a, b) are EMPTY leaves {} — operand NAMES
        //   are sugar, recovered from operand_bindings so the shape is
        //   name-independent and federates cross-language.
        // - The tail expression `q` is a bare scoped-variable return: it is now
        //   an empty {} non-operation leaf and is dropped by
        //   collapse_operation_shapes, so the body collapses from
        //   seq([assign, q]) to just the assign. This is a CONSEQUENCE of
        //   names-are-sugar: `{ let q = a+b; q }` and `{ let z = a+b; z }` carry
        //   the same computation and now share a term_shape. The value-return
        //   flows via operand_bindings; discharge (#1441 5/5) and the rust/go
        //   production bridges round-trip unaffected.
        assert_eq!(
            shape,
            json!({
                "args": [
                    {"kind": "symbol", "text": "q"},
                    {
                        "args": [
                            {},
                            {},
                        ],
                        "op_cid": add_cid
                    }
                ],
                "op_cid": assign_cid
            })
        );
        assert_no_forbidden_term_shape_fields(&shape);
    }

    #[test]
    fn term_shape_top_level_operator_differs_from_let_assignment_boundary() {
        let top_level = term_shape_json(
            r#"
pub fn f(a: i64, b: i64) -> i64 {
    a + b
}
"#,
        );
        let let_rhs = term_shape_json(
            r#"
pub fn f(a: i64, b: i64) -> i64 {
    let q = a + b;
    q
}
"#,
        );

        assert_ne!(top_level, let_rhs);
        assert_eq!(
            top_level["op_cid"],
            json!(local_op_cid("add").expect("add cid")),
            "top-level tail expression remains an add shape"
        );
        // #1075 federation: `{ let q = a+b; q }` lifts as concept:assign(q, add).
        // The trailing bare scoped-variable return `q` is now an empty {}
        // non-operation leaf (operand NAMES are sugar), so collapse_operation_shapes
        // drops it and the seq([assign, q]) collapses to the assign alone. The
        // assignment boundary is still structurally distinct from a top-level
        // operator (assign != add), which is what this test guards.
        assert_eq!(
            let_rhs["op_cid"],
            json!(local_op_cid("assign").expect("assign cid")),
            "let+bare-tail-return body collapses to the concept:assign for the let-binding"
        );
        assert_eq!(
            let_rhs["args"][0],
            json!({"kind": "symbol", "text": "q"}),
            "assign's first child is the let-binding NAME leaf (structural, not sugar)"
        );
        assert_no_forbidden_term_shape_fields(&top_level);
        assert_no_forbidden_term_shape_fields(&let_rhs);
    }

    #[test]
    fn term_shape_explicit_return_preserves_return_boundary() {
        let shape = term_shape_json(
            r#"
pub fn f(a: i64) -> i64 {
    return a;
}
"#,
        );

        assert_eq!(
            shape["op_cid"],
            json!(local_op_cid("return").expect("return cid"))
        );
        assert_no_forbidden_term_shape_fields(&shape);
    }

    #[test]
    fn safe_divide_then_double_emits_gamma_without_unnamed_concepts() {
        let shape = term_shape_json(
            r#"
pub fn safe_divide_then_double(num: i64, denom: i64) -> i64 {
    if denom == 0 {
        -1
    } else {
        let q = num / denom;
        if q < 0 { -1 } else { q * 2 }
    }
}
"#,
        );

        // Substrate-canonical (2026-05-21): Expr::If lifts structurally
        // as concept:conditional(cond, then, else). No more
        // concept:literal source_text fallback — source strings don't
        // belong in the substrate channel. The structural shape carries
        // identity; each kit re-spells from concept-hub identities.
        assert_no_forbidden_term_shape_fields(&shape);
        assert_eq!(
            shape.get("op_cid").and_then(|v| v.as_str()),
            local_op_cid("conditional"),
            "if-as-tail-expression lifts as concept:conditional: {shape:#?}"
        );
        // Collect every op_cid in the tree — verify the structural
        // shape carries the expected operator chain (eq for the equality
        // check, conditional for nested if, div for /, lt for <, etc.).
        let mut op_cids = Vec::new();
        collect_op_cids(&shape, &mut op_cids);
        for expected in [
            "concept:conditional",
            "concept:eq",
            "concept:div",
            "concept:lt",
        ] {
            let expected_cid = local_op_cid(expected).expect("expected op cid");
            assert!(
                op_cids.contains(&expected_cid.to_string()),
                "expected operator {expected} in shape op_cids: {op_cids:?}\nshape: {shape:#?}"
            );
        }
        assert!(
            !serde_json::to_string(&shape)
                .expect("shape stringifies")
                .contains("UNNAMED-CONCEPT"),
            "shape must not contain unnamed concept wrappers: {shape:#?}"
        );
        // Substrate-honest invariant: no source_text leaves anywhere.
        let json_text = serde_json::to_string(&shape).expect("shape stringifies");
        assert!(
            !json_text.contains("\"source_text\""),
            "substrate channel must not carry source_text: {json_text}"
        );
    }

    #[test]
    fn bind_lift_output_strips_source_locations_from_term_shape_and_lines() {
        let root = temp_workspace("bind_lift_source_location_strip");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn add(x: i64, y: i64) -> i64 {
    x + y
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entries = out["ir"].as_array().expect("ir array");
        let entry = entries.first().expect("add entry");
        assert_no_forbidden_bind_lift_entry_fields(entry);
        assert!(
            entry.get("fn_line").is_none(),
            "bind payload must not carry function source lines: {entry:#?}"
        );
        assert!(
            entry.get("file").is_none() || entry["file"] == "",
            "bind payload must not carry source paths: {entry:#?}"
        );
        assert_no_forbidden_term_shape_fields(&entry["term_shape"]);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bind_lift_relifts_edited_concept_comment_into_named_substrate_binding() {
        let root = temp_workspace("bind_lift_concept_comment_lifecycle");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
// concept: my-thing
pub fn shaped(x: i64) -> i64 {
    (x * 7) + 3
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entries = out["ir"].as_array().expect("ir array");
        let entry = entries.first().expect("shaped entry");
        assert_eq!(entry["concept_annotation"], "my-thing");

        let named = bind_term_document(&out, &BindOptions::default())
            .expect("bind term document builds from relifted source");
        assert!(named.terms[0].op_cid.starts_with("blake3-512:"));

        let original_term = Term::Const {
            value: out,
            sort: primitive_sort("LiftPluginResponse"),
        };
        let payload = bind_result_payload(original_term, &named).expect("bind payload builds");
        let payload_bytes =
            libsugar::canonical::serializable_jcs(&payload).expect("payload canonicalizes");
        assert!(
            !payload_bytes.contains("concept_annotation"),
            "bind payload must not retain lift-side annotation scaffolding: {payload_bytes}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bind_lift_concept_comment_survives_adjacent_attrs_and_metadata_comments() {
        let root = temp_workspace("bind_lift_concept_comment_attrs");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
// concept: attr-backed-name
// substrate-origin: annotation-lift
#[cfg_attr(any(), requires(x > 0))]
pub fn shaped(x: i64) -> i64 {
    x
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entries = out["ir"].as_array().expect("ir array");
        let entry = entries.first().expect("shaped entry");
        assert_eq!(entry["concept_annotation"], "attr-backed-name");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bind_lift_discrimination_ignores_concept_comment_separated_by_blank_line() {
        let entry = single_entry_for_source(
            "concept_comment_blank_line",
            r#"
// concept: too-far-away

pub fn shaped(x: i64) -> i64 {
    x
}
"#,
        );

        assert!(
            entry.get("concept_annotation").is_none(),
            "blank-separated concept comment must not bind: {entry:#?}"
        );
    }

    #[test]
    fn bind_lift_discrimination_ignores_inline_trailing_concept_comment() {
        let entry = single_entry_for_source(
            "concept_comment_inline",
            r#"
pub fn shaped(x: i64) -> i64 { // concept: inline-name
    x
}
"#,
        );

        assert!(
            entry.get("concept_annotation").is_none(),
            "inline trailing concept comment must not bind: {entry:#?}"
        );
    }

    #[test]
    fn bind_lift_discrimination_ignores_empty_concept_comment() {
        let entry = single_entry_for_source(
            "concept_comment_empty",
            r#"
// concept:
pub fn shaped(x: i64) -> i64 {
    x
}
"#,
        );

        assert!(
            entry.get("concept_annotation").is_none(),
            "empty concept comment must not bind: {entry:#?}"
        );
    }

    #[test]
    fn bind_lift_contract_attrs_do_not_enter_hashed_bind_payload() {
        let root = temp_workspace("bind_lift_contract_attrs_payload");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
#[cfg_attr(any(), requires(x > 0))]
pub fn positive_id(x: i64) -> i64 {
    x
}
"#,
        )
        .expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entries = out["ir"].as_array().expect("ir array");
        assert_eq!(entries.len(), 1);
        assert_no_forbidden_bind_lift_entry_fields(&entries[0]);

        let original_term = Term::Const {
            value: out,
            sort: primitive_sort("LiftPluginResponse"),
        };
        let named = bind_term_document(
            match &original_term {
                Term::Const { value, .. } => value,
                _ => unreachable!("test constructs const term"),
            },
            &BindOptions::default(),
        )
        .expect("bind term document builds");
        let payload = bind_result_payload(original_term, &named).expect("bind payload builds");
        let payload_bytes =
            libsugar::canonical::serializable_jcs(&payload).expect("payload canonicalizes");

        // Bind no longer emits transport gap records, so `fn_name` must not appear
        // anywhere in the hashed bind payload. Walk the JSON tree and forbid it
        // (empty allow-list).
        for forbidden in [
            "attr_pre",
            "attr_post",
            "concept_annotation",
            "operand_bindings",
            "source_function_name",
        ] {
            assert!(
                !payload_bytes.contains(forbidden),
                "bind payload hashed bytes contain forbidden field `{forbidden}`: {payload_bytes}"
            );
        }
        let payload_json: Value =
            serde_json::from_str(&payload_bytes).expect("payload bytes parse back to JSON");
        assert_no_fn_name_outside_gap_records(&payload_json, &[]);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn unary_not_disambiguates_bool_logical_and_integer_bitwise() {
        let logical_shape = term_shape_json(
            r#"
pub fn logical_not() -> bool {
    !true
}
"#,
        );
        let bitwise_shape = term_shape_json(
            r#"
pub fn bitwise_not() -> i64 {
    !0i64
}
"#,
        );

        assert_eq!(
            logical_shape["op_cid"],
            local_op_cid("not").expect("logical not cid")
        );
        assert_eq!(
            bitwise_shape["op_cid"],
            local_op_cid("bitnot").expect("bitnot cid")
        );
        assert_ne!(
            logical_shape["op_cid"], bitwise_shape["op_cid"],
            "logical not and bitwise not must resolve to distinct concept atoms"
        );
        assert_no_forbidden_term_shape_fields(&logical_shape);
        assert_no_forbidden_term_shape_fields(&bitwise_shape);
    }

    #[test]
    fn bind_lift_includes_public_impl_methods_from_canonicalizer_value() {
        let root = temp_workspace("bind_lift_impl_methods");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("value.rs"),
            include_str!("../../../sugar-canonicalizer/src/value.rs"),
        )
        .expect("write value.rs fixture");
        let file = syn::parse_file(include_str!("../../../sugar-canonicalizer/src/value.rs"))
            .expect("value fixture parses");
        let target_names = collect_bind_lift_targets_with_source(&file, "")
            .into_iter()
            .map(|target| target.fn_name)
            .collect::<Vec<_>>();

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");

        let entries = out["ir"].as_array().expect("ir array");
        for entry in entries {
            assert_no_forbidden_bind_lift_entry_fields(entry);
        }

        for expected in [
            "Value::kind",
            "Value::null",
            "Value::boolean",
            "Value::integer",
            "Value::string",
            "Value::array",
            "Value::object",
        ] {
            assert!(
                target_names.iter().any(|name| name == expected),
                "missing impl method target {expected}; got {target_names:?}"
            );
        }
        assert!(
            entries.len() >= 7,
            "expected at least seven bind lift entries from value.rs impl methods, got {}",
            entries.len()
        );

        let _ = fs::remove_dir_all(root);
    }

    fn term_shape_json(src: &str) -> Value {
        let file = syn::parse_file(src).expect("fixture parses");
        let item_fn = file
            .items
            .iter()
            .find_map(|item| {
                if let syn::Item::Fn(item_fn) = item {
                    Some(item_fn)
                } else {
                    None
                }
            })
            .expect("fixture contains function");
        cvalue_to_json(&term_shape_for_fn(item_fn))
    }

    fn comment_surfaces(value: &Value) -> Vec<String> {
        let mut surfaces = Vec::new();
        collect_comment_surfaces(value, &mut surfaces);
        surfaces
    }

    fn collect_comment_surfaces(value: &Value, surfaces: &mut Vec<String>) {
        match value {
            Value::Object(object) => {
                if object.get("op_cid").and_then(Value::as_str) == local_op_cid("comment") {
                    if let Some(surface) = object
                        .get("args")
                        .and_then(Value::as_array)
                        .and_then(|args| args.first())
                        .and_then(|arg| arg.get("value"))
                        .and_then(Value::as_str)
                    {
                        surfaces.push(surface.to_string());
                    }
                }
                for child in object.values() {
                    collect_comment_surfaces(child, surfaces);
                }
            }
            Value::Array(items) => {
                for child in items {
                    collect_comment_surfaces(child, surfaces);
                }
            }
            // sugar-audit: not-mine(test comment-surface walker only descends JSON object and array nodes)
            _ => {}
        }
    }

    fn assert_no_forbidden_term_shape_fields(value: &Value) {
        match value {
            Value::Object(object) => {
                // `kind` is legitimately used as a leaf-disambiguator (path/
                // method/mutability/symbol/literal) and is NOT forbidden;
                // remaining forbiddens are lift-side annotations and source
                // locations that have no place in the substrate channel.
                for forbidden in [
                    "op",
                    "file",
                    "line",
                    "column",
                    "fn_line",
                    "concept_annotation",
                    "attr_pre",
                    "attr_post",
                    "concept_citations",
                ] {
                    assert!(
                        !object.contains_key(forbidden),
                        "term_shape contains forbidden field `{forbidden}` in {value:#?}"
                    );
                }
                for child in object.values() {
                    assert_no_forbidden_term_shape_fields(child);
                }
            }
            Value::Array(values) => {
                for child in values {
                    assert_no_forbidden_term_shape_fields(child);
                }
            }
            // sugar-audit: not-mine(test forbidden-field assertion only descends JSON object and array nodes)
            _ => {}
        }
    }

    fn collect_op_cids(value: &Value, out: &mut Vec<String>) {
        match value {
            Value::Object(object) => {
                if let Some(op_cid) = object.get("op_cid").and_then(Value::as_str) {
                    out.push(op_cid.to_string());
                }
                for child in object.values() {
                    collect_op_cids(child, out);
                }
            }
            Value::Array(values) => {
                for child in values {
                    collect_op_cids(child, out);
                }
            }
            // sugar-audit: not-mine(test op_cid collector only descends JSON object and array nodes)
            _ => {}
        }
    }

    fn assert_no_forbidden_bind_lift_entry_fields(value: &Value) {
        let object = value.as_object().expect("bind entry object");
        for forbidden in ["attr_pre", "attr_post", "concept_annotation", "fn_name"] {
            assert!(
                !object.contains_key(forbidden),
                "bind lift entry contains forbidden field `{forbidden}` in {value:#?}"
            );
        }
    }

    fn assert_no_fn_name_outside_gap_records(value: &Value, path: &[&str]) {
        let under_gap_records = path.iter().any(|segment| *segment == "gapRecords");
        match value {
            Value::Object(map) => {
                if !under_gap_records {
                    assert!(
                        !map.contains_key("fn_name"),
                        "bind payload contains forbidden `fn_name` outside gap-record context at path {path:?}: {value:#?}"
                    );
                }
                for (key, child) in map {
                    let mut next_path: Vec<&str> = path.to_vec();
                    next_path.push(key.as_str());
                    assert_no_fn_name_outside_gap_records(child, &next_path);
                }
            }
            Value::Array(items) => {
                for child in items {
                    assert_no_fn_name_outside_gap_records(child, path);
                }
            }
            // sugar-audit: not-mine(test fn_name assertion only descends JSON object and array nodes)
            _ => {}
        }
    }

    fn primitive_sort(name: &str) -> Sort {
        Sort::Primitive {
            name: name.to_string(),
        }
    }

    fn temp_workspace(name: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!("{name}_{nanos}"));
        fs::create_dir_all(&root).expect("create temp workspace");
        root
    }

    fn write_cargo_package(root: &Path, name: &str) {
        fs::write(
            root.join("Cargo.toml"),
            format!(
                r#"
[package]
name = "{name}"
version = "0.1.0"
edition = "2021"
"#
            ),
        )
        .expect("write Cargo.toml");
    }

    #[test]
    fn component_plan_claims_base64_vendor_contracts_and_implications() {
        let root = temp_workspace("component_plan_base64_vendor");
        fs::write(
            root.join("Cargo.toml"),
            "[package]\nname='base64-showcase-good'\nversion='0.1.0'\n",
        )
        .expect("write project Cargo.toml");
        let vendor = root.join("vendor/base64-0.22.1/src");
        fs::create_dir_all(&vendor).expect("create vendor src");
        fs::write(
            root.join("vendor/base64-0.22.1/Cargo.toml"),
            "[package]\nname='base64'\nversion='0.22.1'\n",
        )
        .expect("write vendor Cargo.toml");
        fs::write(vendor.join("encode.rs"), "pub fn encoded_len() {}\n")
            .expect("write vendor source");

        let response = component_plan_result(&json!({
            "workspace_root": root.to_string_lossy(),
            "project_forensics": {
                "items": [
                    {
                        "id": "file:Cargo.toml",
                        "kind": "package-manifest",
                        "path": "Cargo.toml",
                        "language_hint": "rust",
                        "reason": "Cargo package manifest"
                    },
                    {
                        "id": "file:vendor/base64-0.22.1/Cargo.toml",
                        "kind": "package-manifest",
                        "path": "vendor/base64-0.22.1/Cargo.toml",
                        "language_hint": "rust",
                        "reason": "Cargo package manifest"
                    },
                    {
                        "id": "file:vendor/base64-0.22.1/src/encode.rs",
                        "kind": "source-file",
                        "path": "vendor/base64-0.22.1/src/encode.rs",
                        "language_hint": "rust",
                        "reason": "rust source file"
                    }
                ]
            }
        }));

        assert_eq!(response["decision"].as_str(), Some("claim"));
        let plugins = response["plugins"].as_array().expect("plugins");
        let fn_contracts = plugins
            .iter()
            .find(|plugin| plugin["surface"] == "rust-fn-contracts")
            .expect("rust-fn-contracts plugin");
        assert_eq!(
            fn_contracts["workspace_override"].as_str(),
            Some("vendor/base64-0.22.1")
        );
        assert!(plugins
            .iter()
            .any(|plugin| plugin["surface"] == "rust-implications"));
        let manifests = response["lift_manifests"].as_array().expect("manifests");
        let implications = manifests
            .iter()
            .find(|manifest| manifest["surface"] == "rust-implications")
            .expect("rust-implications manifest");
        assert_eq!(
            implications["method"].as_str(),
            Some("sugar.plugin.lift_implications")
        );
        assert_eq!(implications["phase"].as_str(), Some("consumer"));
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn component_plan_refuses_missing_base64_vendor_manifest_forensic_item() {
        let root = temp_workspace("component_plan_missing_base64_manifest_item");
        fs::write(
            root.join("Cargo.toml"),
            "[package]\nname='base64-showcase-good'\nversion='0.1.0'\n",
        )
        .expect("write project Cargo.toml");
        let vendor = root.join("vendor/base64-0.22.1/src");
        fs::create_dir_all(&vendor).expect("create vendor src");
        fs::write(
            root.join("vendor/base64-0.22.1/Cargo.toml"),
            "[package]\nname='base64'\nversion='0.22.1'\n",
        )
        .expect("write vendor Cargo.toml");
        fs::write(vendor.join("encode.rs"), "pub fn encoded_len() {}\n")
            .expect("write vendor source");

        let response = component_plan_result(&json!({
            "workspace_root": root.to_string_lossy(),
            "project_forensics": {
                "items": [
                    {
                        "id": "file:Cargo.toml",
                        "kind": "package-manifest",
                        "path": "Cargo.toml",
                        "language_hint": "rust",
                        "reason": "Cargo package manifest"
                    },
                    {
                        "id": "file:vendor/base64-0.22.1/src/encode.rs",
                        "kind": "source-file",
                        "path": "vendor/base64-0.22.1/src/encode.rs",
                        "language_hint": "rust",
                        "reason": "rust source file"
                    }
                ]
            }
        }));

        assert_eq!(response["decision"].as_str(), Some("decline"));
        assert!(
            response["reason"]
                .as_str()
                .is_some_and(|reason| reason.contains("vendor Cargo.toml forensic item")),
            "unexpected response: {response:#}"
        );
        // sugar-audit: default-ok(test tempdir cleanup is best-effort after assertions)
        fs::remove_dir_all(&root).ok();
    }

    fn write_infallible_serialize_manifest(root: &Path, body: &str) {
        let contracts_dir = root.join(".sugar").join("contracts");
        fs::create_dir_all(&contracts_dir).expect("create contracts dir");
        fs::write(contracts_dir.join("infallible_serialize.toml"), body)
            .expect("write infallible serialize manifest");
    }

    fn write_function_postconditions_manifest(root: &Path, body: &str) {
        let contracts_dir = root.join(".sugar").join("contracts");
        fs::create_dir_all(&contracts_dir).expect("create contracts dir");
        fs::write(contracts_dir.join("function_postconditions.toml"), body)
            .expect("write function postconditions manifest");
    }

    fn source_line_containing(src: &str, needle: &str) -> usize {
        src.lines()
            .position(|line| line.contains(needle))
            .unwrap_or_else(|| panic!("missing source line containing `{needle}`"))
            + 1
    }

    fn manifest_to_value_hit_count(temp_name: &str, src: &str, type_name: &str) -> usize {
        let root = temp_workspace(temp_name);
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_infallible_serialize_manifest(
            &root,
            &format!(
                r#"
[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "{type_name}"
contract = "serde_json_to_value__scope_probe"
reason = "scope discipline probe"
"#,
            ),
        );

        let expected_cid = "blake3-512:abababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababab";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [{
                "name": "serde_json_to_value__scope_probe",
                "library": "consumer_crate",
                "contract_cid": expected_cid,
                "bodyDischargeEligible": false,
                "bodyDischargeRefusalReason": "totality-axiom"
            }],
        }))
        .expect("lift_implications");

        let count = resp["ir"]
            .as_array()
            .expect("ir array")
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "to_value")
            .filter(|entry| entry["targetContractCid"] == expected_cid)
            .count();
        let _ = fs::remove_dir_all(root);
        count
    }

    fn write_residue_manifest(root: &Path, body: &str) {
        let sugar_dir = root.join(".sugar");
        fs::create_dir_all(&sugar_dir).expect("create .sugar dir");
        fs::write(sugar_dir.join("residue.toml"), body).expect("write residue manifest");
    }

    fn write_sugar_binding_proof(
        proof_dir: &Path,
        mut sugar_entry: Value,
        contract_cid: &str,
        proof_name: &str,
    ) -> String {
        sugar_entry["contract_cid"] = Value::String(contract_cid.to_string());
        let member = json!({
            "body": sugar_entry,
            "header": {"kind": "library-sugar-binding-entry"},
        });
        let member_bytes = serde_json::to_vec(&member).expect("member json");
        let member_cid = blake3_512_of(&member_bytes);
        let memento = LibrarySugarBindingMemento::new(member_bytes);
        assert_eq!(memento.cid().as_str(), member_cid);
        let mut graph = ProofGraph::new();
        graph.push_library_sugar_binding(memento);
        let signer_seed: Ed25519Seed = [0x91; 32];
        let proof = build_proof_envelope(&ProofEnvelopeInput {
            name: proof_name.to_string(),
            version: "0.1.0".to_string(),
            binary_cid: None,
            metadata: None,
            graph,
            signer_cid: ed25519_pubkey_string(&signer_seed),
            signer_seed,
            declared_at: "2026-05-31T00:00:00.000Z".to_string(),
        });
        fs::create_dir_all(proof_dir).expect("create proof dir");
        fs::write(proof_dir.join(proof_filename(&proof.cid)), &proof.bytes).expect("write proof");
        proof.cid
    }

    fn register_test_contract_body_graph(
        proof_graph: &mut ProofGraph,
        pre: Option<&Arc<CValue>>,
        post: Option<&Arc<CValue>>,
        inv: Option<&Arc<CValue>>,
    ) -> ContractBody {
        let mut slots: Vec<(&'static str, AtomMemento)> = Vec::new();
        if let Some(formula) = pre {
            slots.push((
                "pre",
                proof_graph.register_atom(FlatAtom::new(formula.clone())),
            ));
        }
        if let Some(formula) = post {
            slots.push((
                "post",
                proof_graph.register_atom(FlatAtom::new(formula.clone())),
            ));
        }
        if let Some(formula) = inv {
            slots.push((
                "inv",
                proof_graph.register_atom(FlatAtom::new(formula.clone())),
            ));
        }
        assert!(
            !slots.is_empty(),
            "contract body graph requires at least one formula slot"
        );
        let slot_refs = slots
            .iter()
            .map(|(slot, atom)| (*slot, atom))
            .collect::<Vec<_>>();
        proof_graph.register_body(ContractBody::from_slots(slot_refs))
    }

    fn write_rust_vendor_function_contract_proof(
        proof_dir: &Path,
        contract_name: &str,
        library: &str,
        source_symbol: &str,
        formals: Value,
    ) -> (String, String) {
        let signer_seed: Ed25519Seed = [0x92; 32];
        let formals_vec: Vec<String> = match formals.as_array() {
            Some(values) => values
                .iter()
                .filter_map(|value| value.as_str().map(str::to_string))
                .collect(),
            None => Vec::new(),
        };
        let args = MintContractArgs {
            evidence_term: None,
            contract_name: contract_name.to_string(),
            pre: None,
            post: Some(CValue::object([
                ("kind", CValue::string("atomic")),
                ("name", CValue::string("=")),
                (
                    "args",
                    CValue::array(vec![
                        CValue::object([
                            ("kind", CValue::string("var")),
                            ("name", CValue::string("out")),
                        ]),
                        CValue::object([
                            ("kind", CValue::string("ctor")),
                            ("name", CValue::string("vendor:pattern")),
                            ("args", CValue::array(Vec::new())),
                        ]),
                    ]),
                ),
            ])),
            inv: None,
            out_binding: "out".to_string(),
            produced_by: "walk-rpc-test".to_string(),
            produced_at: "2026-06-18T00:00:00.000Z".to_string(),
            input_cids: Vec::new(),
            authoring: Authoring::KitAuthor {
                author: "walk-rpc-test".to_string(),
                note: None,
            },
            signer_seed,
            formals: formals_vec,
            emit_empty_formals: formals.as_array().is_some(),
            formal_sorts: vec![CValue::object([
                ("kind", CValue::string("primitive")),
                ("name", CValue::string("String")),
            ])],
            library: Some(library.to_string()),
            body_discharge_eligible: true,
            body_discharge_refusal_reason: None,
            panic_loci: Vec::new(),
            class_shapes: Vec::new(),
            source_warrants: Vec::new(),
        };
        let mut graph = ProofGraph::new();
        let body = register_test_contract_body_graph(
            &mut graph,
            args.pre.as_ref(),
            args.post.as_ref(),
            args.inv.as_ref(),
        );
        let contract = mint_contract_with_body_cid(&args, Some(body.cid().as_str()))
            .expect("mint vendor function contract");
        let contract_cid = contract.cid.clone();
        let contract_memento = ClaimContractMemento::new(contract.canonical_bytes);
        assert_eq!(contract_memento.cid().as_str(), contract_cid);

        let bridge = mint_bridge(&MintBridgeArgs {
            produced_by: "walk-rpc-test".to_string(),
            produced_at: "2026-06-18T00:00:00.000Z".to_string(),
            source_symbol: source_symbol.to_string(),
            source_layer: "source".to_string(),
            target_contract: ContractMementoRef::new(contract_cid.clone()),
            target_layer: "kit".to_string(),
            ir_arg_sorts: Vec::new(),
            ir_return_sort: String::new(),
            notes: "test self-pinned Rust vendor function bridge".to_string(),
            signer_seed,
            target_proof_cid: None,
            callsite: None,
        });
        let bridge_cid = bridge.cid.clone();
        let bridge_memento = BridgeMemento::new(bridge.canonical_bytes);
        assert_eq!(bridge_memento.cid().as_str(), bridge_cid);

        graph.push_claim_contract(contract_memento);
        graph.push_bridge(bridge_memento);
        let proof = build_proof_envelope(&ProofEnvelopeInput {
            name: "rust-vendor-function-contract".to_string(),
            version: "0.1.0".to_string(),
            binary_cid: None,
            metadata: None,
            graph,
            signer_cid: ed25519_pubkey_string(&signer_seed),
            signer_seed,
            declared_at: "2026-06-18T00:00:00.000Z".to_string(),
        });
        fs::create_dir_all(proof_dir).expect("create proof dir");
        fs::write(proof_dir.join(proof_filename(&proof.cid)), &proof.bytes).expect("write proof");
        (proof.cid, contract_cid)
    }

    fn single_entry_for_source(name: &str, source: &str) -> Value {
        let root = temp_workspace(name);
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(src_dir.join("lib.rs"), source).expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");
        let entry = out["ir"]
            .as_array()
            .expect("ir array")
            .first()
            .expect("single entry")
            .clone();
        let _ = fs::remove_dir_all(root);
        entry
    }

    fn single_sugar_entry_for_source(name: &str, source: &str) -> Value {
        let root = temp_workspace(name);
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(src_dir.join("lib.rs"), source).expect("write source");

        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("bind lift should succeed");
        let entry = out["ir"]
            .as_array()
            .expect("ir array")
            .iter()
            .find(|entry| entry["kind"] == "library-sugar-binding-entry")
            .expect("single sugar entry")
            .clone();
        let _ = fs::remove_dir_all(root);
        entry
    }

    #[test]
    fn rust_lifter_parse_refusal_does_not_fire_read_error_variant() {
        let dir = rust_lifter_parse_refusal_workspace("discrim");

        let result = bind_lift(&json!({
            "workspace_root": dir,
            "source_paths": ["."]
        }))
        .expect("bind lift returns document");

        assert_eq!(result["diagnostics"][0]["kind"], "parse-error");
        assert!(result["diagnostics"]
            .as_array()
            .expect("diagnostics array")
            .iter()
            .all(|item| item["kind"] != "read-error"));
    }

    fn rust_lifter_parse_refusal_workspace(label: &str) -> PathBuf {
        let unique = format!(
            "sugar-walk-parse-refusal-{}-{}",
            label,
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        );
        let dir = std::env::temp_dir().join(unique);
        std::fs::create_dir_all(dir.join("src")).expect("create src");
        std::fs::write(dir.join("src/lib.rs"), "fn broken(").expect("write source");
        dir
    }

    // ---- substrate-honest precursor wire tests (loss, observed_dimension, refusal-memento) ----

    #[test]
    fn sugar_attr_loss_array_populates_loss_record_entries() {
        let root = temp_workspace("sugar_loss_array");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src = r#"
#[sugar::sugar(
    op = "sql-query",
    library = "rusqlite",
    loss = ["sync-vs-async", "row-cardinality"],
)]
fn query(conn: String, sql: String) -> i64 { 0 }
"#;
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(sugar.len(), 1, "expected one sugar entry");
        assert_eq!(
            sugar[0]["loss_record_contribution"]["value"]["entries"],
            json!(["sync-vs-async", "row-cardinality"])
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn sugar_attr_without_loss_still_emits_empty_entries() {
        let root = temp_workspace("sugar_no_loss");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src = r#"
#[sugar::sugar(op = "sql-query", library = "rusqlite")]
fn query(conn: String, sql: String) -> i64 { 0 }
"#;
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(sugar.len(), 1);
        assert_eq!(
            sugar[0]["loss_record_contribution"]["value"]["entries"],
            json!([])
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn sugar_attr_observed_dimension_propagates_to_entry() {
        let root = temp_workspace("sugar_observed_dim");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let src = r#"
#[sugar::sugar(
    op = "contract-observation",
    library = "rusqlite",
    observed_dimension = "autocommit-mode",
)]
fn is_autocommit(conn: String) -> bool { false }
"#;
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let out = bind_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("bind lift should succeed");
        let ir = out["ir"].as_array().expect("ir array");
        let sugar: Vec<_> = ir
            .iter()
            .filter(|e| e["kind"] == "library-sugar-binding-entry")
            .collect();
        assert_eq!(sugar.len(), 1);
        assert_eq!(sugar[0]["observed_dimension"], "autocommit-mode");

        let _ = fs::remove_dir_all(root);
    }

    // -----------------------------------------------------------------
    // Implication lifter (#97). Walks production-code function bodies
    // and emits one kind:bridge memento per Expr::Call / Expr::MethodCall
    // call site, looked up against the supplied contract_bindings by
    // ctor-name index over the contract name's "<callee>@..." prefix.
    // -----------------------------------------------------------------

    #[test]
    fn lift_implications_emits_bridge_per_call_expression_matched_by_callee_name() {
        let src = r##"
pub fn caller(input: &str) -> i64 {
    let parsed = parse_input(input);
    parsed.normalize_value()
}
"##;
        let root = temp_workspace("lift_implications_basic");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            { "name": "parse_input@src/lib.rs:5:8",
              "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
            { "name": "normalize_value@src/lib.rs:12:8",
              "contract_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        assert_eq!(resp["kind"], "ir-document");
        let ir = resp["ir"].as_array().expect("ir array");
        assert_eq!(
            ir.len(),
            2,
            "expected one bridge per call expression (parse_input + normalize_value), got: {ir:?}"
        );

        // Free function call -> kind:bridge with sourceSymbol = parse_input.
        let parse = ir
            .iter()
            .find(|e| e["sourceSymbol"] == "parse_input")
            .expect("parse_input bridge");
        assert_eq!(parse["kind"], "bridge");
        assert_eq!(parse["sourceLayer"], "rust");
        assert_eq!(parse["targetLayer"], "rust-tests");
        assert_eq!(
            parse["targetContractCid"],
            "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        );
        assert_eq!(parse["target"]["cid"], parse["targetContractCid"]);
        assert!(parse["name"]
            .as_str()
            .unwrap()
            .starts_with("intra-body:rust:parse_input@"));

        // Method call -> sourceSymbol = `method:<ident>` (matching the lifted
        // method-call ctor name), NOT the receiver and NOT the bare leaf.
        let norm = ir
            .iter()
            .find(|e| e["sourceSymbol"] == "method:normalize_value")
            .expect("method:normalize_value bridge");
        assert_eq!(norm["kind"], "bridge");
        assert_eq!(
            norm["targetContractCid"],
            "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_same_bundle_pre_implication_for_caller_to_callee() {
        let src = r##"
pub fn callee(x: i64) -> i64 {
    x
}

pub fn caller(x: i64) -> i64 {
    callee(x)
}
"##;
        let root = temp_workspace("lift_implications_same_bundle_implication");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            {
                "name": "caller",
                "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "body_bearing": true,
                "has_post": true
            },
            {
                "name": "callee",
                "contract_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "body_bearing": true,
                "has_pre": true,
                "formals": ["x"]
            }
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let bridge = ir
            .iter()
            .find(|entry| entry["sourceSymbol"] == "callee")
            .unwrap_or_else(|| panic!("callee bridge missing: {resp:#?}"));
        assert_eq!(
            bridge["targetContractCid"],
            "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        );

        let implications = resp["implications"]
            .as_array()
            .unwrap_or_else(|| panic!("implications missing: {resp:#?}"));
        assert_eq!(
            implications.len(),
            1,
            "expected one caller.post => callee.pre implication, got {implications:#?}"
        );
        let implication = &implications[0];
        assert_eq!(implication["antecedent"], "caller");
        assert_eq!(implication["antecedentSlot"], "post");
        assert_eq!(implication["consequent"], "callee");
        assert_eq!(implication["consequentSlot"], "pre");
        assert_eq!(implication["prover"], "rust-implications");
        assert!(implication["name"]
            .as_str()
            .expect("implication name")
            .contains("caller->callee@src/lib.rs:"));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_does_not_emit_pre_implication_without_caller_post() {
        let src = r##"
pub fn callee(x: i64) -> i64 {
    x
}

pub fn caller(x: i64) -> i64 {
    callee(x)
}
"##;
        let root = temp_workspace("lift_implications_requires_caller_post");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            {
                "name": "caller",
                "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "body_bearing": true,
                "has_pre": true
            },
            {
                "name": "callee",
                "contract_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "body_bearing": true,
                "has_pre": true,
                "formals": ["x"]
            }
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        assert!(
            resp["implications"].is_null(),
            "caller without post slot must stay bridge-only: {resp:#?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_uses_bridge_source_symbol_for_impl_method_contracts() {
        let src = r##"
pub struct Digitish;

impl Digitish {
    pub fn to_digit(&self, radix: u32) -> u32 {
        assert!(radix >= 2 && radix <= 36, "radix out of range");
        radix
    }
}

pub fn caller(value: Digitish) -> u32 {
    value.to_digit(1)
}
"##;
        let root = temp_workspace("lift_implications_impl_method_bridge_source_symbol");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let producer = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
        }))
        .expect("function contract lift");
        let contract_bindings = producer["ir"].as_array().expect("producer ir array");
        let target = contract_bindings
            .iter()
            .find(|entry| entry["name"] == "Digitish::to_digit")
            .expect("impl method contract should be lifted");
        assert_eq!(target["bridgeSourceSymbol"], "to_digit");

        let consumer = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift implications");
        let ir = consumer["ir"].as_array().expect("consumer ir array");
        let bridge = ir
            .iter()
            .find(|entry| entry["sourceSymbol"] == "method:to_digit")
            .unwrap_or_else(|| panic!("method:to_digit bridge missing: {consumer:#?}"));
        assert_eq!(bridge["targetContractCid"], target["contract_cid"]);
        assert_eq!(
            bridge["callsite"]["formalActuals"]["radix"],
            json!({"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 1})
        );
        assert_eq!(bridge["callsite"]["formalActuals"]["self"]["kind"], "var");
        assert_eq!(bridge["callsite"]["formalActuals"]["self"]["name"], "value");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_loads_method_contracts_from_imported_rust_proofs() {
        let src = r##"
use match_crate::Match;

pub fn user_unit_test_subject(m: Match) -> &'static str {
    m.pattern()
}
"##;
        let root = temp_workspace("lift_implications_imported_rust_proof_method_contract");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let (proof_cid, contract_cid) = write_rust_vendor_function_contract_proof(
            &root.join(".sugar").join("imports"),
            "rust-source::Match::pattern",
            "match_crate",
            "method:pattern",
            json!(["self"]),
        );
        let imported = rust_vendor_contract_bindings_from_proofs(&root)
            .expect("import generated Rust vendor proof");
        assert_eq!(
            imported.len(),
            1,
            "generated Rust vendor proof should import one binding: {imported:#?}"
        );

        let consumer = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [],
        }))
        .expect("lift implications");
        let ir = consumer["ir"].as_array().expect("consumer ir array");
        let bridge = ir
            .iter()
            .find(|entry| entry["sourceSymbol"] == "method:pattern")
            .unwrap_or_else(|| panic!("method:pattern bridge missing: {consumer:#?}"));

        assert_eq!(bridge["targetContractCid"], contract_cid);
        assert_eq!(bridge["targetProofCid"], proof_cid);
        assert_eq!(bridge["callsite"]["formalActuals"]["self"]["kind"], "var");
        assert_eq!(bridge["callsite"]["formalActuals"]["self"]["name"], "m");
        assert!(
            consumer["implications"].is_null(),
            "imported proof contracts should stay bridge-only; got {consumer:#?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_resolves_stable_local_receiver_in_formal_actuals() {
        let src = r##"
pub fn caller() -> Option<u32> {
    let ch = 'a';
    ch.to_digit(16)
}
"##;
        let root = temp_workspace("lift_implications_stable_local_receiver_formal_actuals");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_cid = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        let contract_bindings = json!([
            {
                "name": "char::to_digit",
                "contract_cid": contract_cid,
                "bridgeSourceSymbol": "to_digit",
                "formals": ["self", "radix"],
                "body_bearing": true,
                "has_pre": true,
                "bodyDischargeEligible": true,
            }
        ]);

        let consumer = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift implications");
        let ir = consumer["ir"].as_array().expect("consumer ir array");
        let bridge = ir
            .iter()
            .find(|entry| entry["sourceSymbol"] == "method:to_digit")
            .unwrap_or_else(|| panic!("method:to_digit bridge missing: {consumer:#?}"));
        assert_eq!(bridge["targetContractCid"], contract_cid);
        assert_eq!(
            bridge["callsite"]["formalActuals"]["self"],
            json!({"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 97})
        );
        assert_eq!(
            bridge["callsite"]["formalActuals"]["radix"],
            json!({"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 16})
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn formal_actuals_for_binding_refuses_arity_mismatch() {
        let binding = json!({
            "formals": ["self", "radix"],
        });
        let actuals = vec![json!({"kind": "var", "name": "value"})];
        assert_eq!(formal_actuals_for_binding(&binding, Some(&actuals)), None);
    }

    #[test]
    fn lift_implications_harvests_producer_call_inside_await_seam() {
        let src = r##"
pub async fn producer() -> i64 {
    6
}

pub async fn caller() -> i64 {
    producer().await
}
"##;
        let root = temp_workspace("lift_implications_await_producer");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            { "name": "producer@src/lib.rs:2:4",
              "contract_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let producer = ir
            .iter()
            .find(|e| e["sourceSymbol"] == "producer")
            .expect("producer bridge under await seam");
        assert_eq!(producer["kind"], "bridge");
        assert_eq!(
            producer["targetContractCid"],
            "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_channel_conduit_bridge_from_send_to_recv() {
        let src = r##"
pub async fn producer() -> i64 {
    6
}

pub fn consumer(x: i64) -> i64 {
    assert!(x == 6);
    6
}

pub async fn edge() -> i64 {
    let (tx, mut rx) = tokio::sync::mpsc::channel::<i64>(1);
    tx.send(producer().await).await.unwrap();
    let value = rx.recv().await.unwrap();
    consumer(value)
}
"##;
        let root = temp_workspace("lift_implications_channel_conduit");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            { "name": "producer@src/lib.rs:2:4",
              "contract_cid": "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" },
            { "name": "consumer@src/lib.rs:6:4",
              "contract_cid": "blake3-512:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let channel = ir
            .iter()
            .find(|e| e["sourceSymbol"] == "channel:recv:rx")
            .expect("channel recv conduit bridge");
        assert_eq!(channel["kind"], "bridge");
        assert_eq!(
            channel["targetContractCid"],
            "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_channel_conduit_bridge_for_direct_recv_consumer_arg() {
        let src = r##"
pub async fn producer() -> i64 {
    6
}

pub fn consumer(x: i64) -> i64 {
    assert!(x == 6);
    6
}

pub async fn edge() -> i64 {
    let (tx, mut rx) = tokio::sync::mpsc::channel::<i64>(1);
    tx.send(producer().await).await.expect("send");
    consumer(rx.recv().await.expect("recv"))
}
"##;
        let root = temp_workspace("lift_implications_channel_direct_recv_arg");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                { "name": "producer@src/lib.rs:2:4",
                  "contract_cid": "blake3-512:444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444" },
                { "name": "consumer@src/lib.rs:6:4",
                  "contract_cid": "blake3-512:555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555" }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let channel = ir
            .iter()
            .find(|e| e["sourceSymbol"] == "channel:recv:rx")
            .expect("channel recv conduit bridge");
        assert_eq!(
            channel["targetContractCid"],
            "blake3-512:444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_refuses_channel_conduit_when_sends_have_multiple_producers() {
        let src = r##"
pub async fn producer_six() -> i64 {
    6
}

pub async fn producer_five() -> i64 {
    5
}

pub fn consumer(x: i64) -> i64 {
    assert!(x == 6);
    6
}

pub async fn edge(flag: bool) -> i64 {
    let (tx, mut rx) = tokio::sync::mpsc::channel::<i64>(2);
    if flag {
        tx.send(producer_six().await).await.unwrap();
    } else {
        tx.send(producer_five().await).await.unwrap();
    }
    let value = rx.recv().await.unwrap();
    consumer(value)
}
"##;
        let root = temp_workspace("lift_implications_channel_ambiguous_sends");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                { "name": "producer_six@src/lib.rs:2:4",
                  "contract_cid": "blake3-512:111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111" },
                { "name": "producer_five@src/lib.rs:6:4",
                  "contract_cid": "blake3-512:222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222" },
                { "name": "consumer@src/lib.rs:10:4",
                  "contract_cid": "blake3-512:333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333" }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            !ir.iter()
                .any(|entry| entry["sourceSymbol"] == "channel:recv:rx"),
            "ambiguous sends must not produce a channel conduit bridge"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_mutex_guard_conduit_bridge_from_protected_value() {
        let src = r##"
pub async fn producer() -> i64 {
    6
}

pub fn consumer(x: i64) -> i64 {
    assert!(x == 6);
    6
}

pub async fn edge() -> i64 {
    let m = tokio::sync::Mutex::new(producer().await);
    {
        let x = consumer(*m.lock().await);
        x
    }
}
"##;
        let root = temp_workspace("lift_implications_mutex_guard_conduit");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                { "name": "producer@src/lib.rs:2:4",
                  "contract_cid": "blake3-512:666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666" },
                { "name": "consumer@src/lib.rs:6:4",
                  "contract_cid": "blake3-512:777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777" }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let mutex = ir
            .iter()
            .find(|e| e["sourceSymbol"] == "mutex:guard:m")
            .expect("mutex guard conduit bridge");
        assert_eq!(mutex["kind"], "bridge");
        assert_eq!(
            mutex["targetContractCid"],
            "blake3-512:666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_refuses_mutex_guard_conduit_when_protected_value_is_ambiguous() {
        let src = r##"
pub async fn producer_six() -> i64 {
    6
}

pub async fn producer_five() -> i64 {
    5
}

pub fn consumer(x: i64) -> i64 {
    assert!(x == 6);
    6
}

pub async fn edge(flag: bool) -> i64 {
    let m = tokio::sync::Mutex::new(if flag {
        producer_six().await
    } else {
        producer_five().await
    });
    {
        let x = consumer(*m.lock().await);
        x
    }
}
"##;
        let root = temp_workspace("lift_implications_mutex_ambiguous_protected_value");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                { "name": "producer_six@src/lib.rs:2:4",
                  "contract_cid": "blake3-512:888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888" },
                { "name": "producer_five@src/lib.rs:6:4",
                  "contract_cid": "blake3-512:999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999" },
                { "name": "consumer@src/lib.rs:10:4",
                  "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            !ir.iter()
                .any(|entry| entry["sourceSymbol"] == "mutex:guard:m"),
            "ambiguous protected values must not produce a mutex guard conduit bridge"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_residue_manifest_annotations() {
        let root = temp_workspace("lift_implications_residue_annotations");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), "pub fn f() {}\n").expect("write source");
        write_residue_manifest(
            &root,
            r#"
[[residue]]
file = "src/kit_dispatch.rs"
line = 106
callee = "expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "Mutex::lock returns Err only when another thread panicked while holding the lock; assuming lock totality would be unsound."

[[tier_to_close]]
file = "src/kit_dispatch.rs"
line = 2416
callee = "expect"
category = "D-lib"
tier_to_close = "generic fixture tier"
reason = "synthetic fixture reason."
"#,
        );

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [],
        }))
        .expect("lift_implications");
        let diagnostics = resp["diagnostics"].as_array().expect("diagnostics");
        let annotations: Vec<&Value> = diagnostics
            .iter()
            .filter(|diagnostic| diagnostic["kind"] == "panic-site-annotation")
            .collect();
        let effect_annotations: Vec<&Value> = diagnostics
            .iter()
            .filter(|diagnostic| diagnostic["kind"] == "effect-site-annotation")
            .collect();

        assert_eq!(
            annotations.len(),
            2,
            "expected manifest annotations: {diagnostics:#?}"
        );
        assert!(
            effect_annotations.is_empty(),
            "writer-stability: Rust kit must not emit effect-site-annotation diagnostics in the reader-only slice: {diagnostics:#?}"
        );
        assert_eq!(annotations[0]["status"], "residue");
        assert_eq!(annotations[0]["category"], "lock_poisoning_residue");
        assert_eq!(annotations[0]["tierToClose"], "irreducible");
        assert_eq!(annotations[1]["status"], "unproven");
        assert_eq!(annotations[1]["category"], "D-lib");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_rejects_duplicate_residue_manifest_sites() {
        let root = temp_workspace("lift_implications_residue_duplicate");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), "pub fn f() {}\n").expect("write source");
        write_residue_manifest(
            &root,
            r#"
[[residue]]
file = "src/kit_dispatch.rs"
line = 106
callee = "expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "first"

[[tier_to_close]]
file = "src/kit_dispatch.rs"
line = 106
callee = "expect"
category = "D-lib"
tier_to_close = "future tier"
reason = "second"
"#,
        );

        let err = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [],
        }))
        .expect_err("duplicate residue manifest sites must fail closed");
        assert!(
            err.contains("duplicate panic-site annotation"),
            "unexpected error: {err}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_rejects_residue_manifest_missing_tier_to_close() {
        let root = temp_workspace("lift_implications_residue_missing_tier");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), "pub fn f() {}\n").expect("write source");
        write_residue_manifest(
            &root,
            r#"
[[residue]]
file = "src/kit_dispatch.rs"
line = 106
callee = "expect"
category = "lock_poisoning_residue"
reason = "missing tier"
"#,
        );

        let err = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [],
        }))
        .expect_err("missing tier_to_close must fail closed");
        assert!(err.contains("tier_to_close"), "unexpected error: {err}");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_skips_cfg_test_callsites() {
        let src = r##"
pub fn production() -> i64 {
    parse_input("1")
}

#[cfg(test)]
mod tests {
    #[test]
    fn unit_test() {
        parse_input("2").unwrap();
    }
}
"##;
        let root = temp_workspace("lift_implications_skip_tests");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            { "name": "parse_input@src/lib.rs:1:1",
              "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
            { "name": "unwrap@src/lib.rs:1:1",
              "contract_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert_eq!(ir.len(), 1, "only production callsites are bridged: {ir:?}");
        assert_eq!(ir[0]["sourceSymbol"], "parse_input");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_stamps_library_from_cargo_package_name() {
        let root = temp_workspace("function_contract_library_stamp");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "sugar-cli"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn identity(value: i64) -> i64 {
    value
}
"#,
        )
        .expect("write source");

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");

        let entries = resp["ir"].as_array().expect("ir array");
        let entry = entries
            .iter()
            .find(|entry| entry["name"] == "identity")
            .expect("identity function contract");
        assert_eq!(entry["library"], "sugar_cli");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_refuses_missing_cargo_package_name() {
        let root = temp_workspace("function_contract_missing_package_name");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn identity(value: i64) -> i64 {
    value
}
"#,
        )
        .expect("write source");

        let err = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect_err("missing Cargo package name must refuse before emitting contracts");

        assert!(
            err.contains("Cargo package name"),
            "unexpected error: {err}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_publishes_builtin_std_panic_partials() {
        let root = temp_workspace("function_contract_builtin_std_partials");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "std-partial-consumer"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn identity(value: i64) -> i64 {
    value
}
"#,
        )
        .expect("write source");

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");

        let entries = resp["ir"].as_array().expect("ir array");
        for (name, predicate) in [
            ("option_unwrap@std/src/option.rs:1:1", "is_some"),
            ("option_expect@std/src/option.rs:1:1", "is_some"),
            ("result_unwrap@std/src/result.rs:1:1", "is_ok"),
            ("result_expect@std/src/result.rs:1:1", "is_ok"),
            ("result_unwrap_err@std/src/result.rs:1:1", "is_err"),
        ] {
            let entry = entries
                .iter()
                .find(|entry| entry["name"] == name)
                .unwrap_or_else(|| panic!("missing builtin std partial `{name}`: {entries:?}"));
            assert_eq!(entry["kind"], "function-contract");
            assert_eq!(entry["library"], "std");
            assert_eq!(entry["bodyDischargeEligible"], true);
            assert_eq!(
                entry["pre"],
                json!({
                    "kind": "atomic",
                    "name": predicate,
                    "args": [{"kind": "var", "name": "receiver"}]
                })
            );
            assert_eq!(entry["formals"], json!(["receiver"]));
        }

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_emits_source_oracle_mementos_without_source_text() {
        let root = temp_workspace("function_contract_source_mementos");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "source-memento-demo"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn callee(x: i64) -> i64 {
    x + 1
}

pub struct Thing;

impl Thing {
    pub fn method(&self, x: i64) -> i64 {
        callee(x)
    }
}
"#,
        )
        .expect("write source");

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");

        assert_eq!(resp["sourceLedger"]["source_loci"], json!(2));
        assert_eq!(resp["sourceLedger"]["source_warranted"], json!(2));
        assert_eq!(resp["sourceLedger"]["unclassified_source"], json!(0));
        let audits = resp["sourceAudits"].as_array().expect("source audits");
        assert_eq!(audits.len(), 1);
        assert_eq!(audits[0]["role"], "rust-fn-contracts");
        assert_eq!(audits[0]["universe_kind"], "function-contract");
        let loci = audits[0]["loci"].as_array().expect("audit loci");
        assert_eq!(loci.len(), 2);
        assert!(loci.iter().all(|locus| locus["status"] == "warranted"));

        let mementos = resp["sourceMementos"].as_array().expect("source mementos");
        assert_eq!(mementos.len(), 2);
        let names: BTreeSet<String> = mementos
            .iter()
            .map(|memento| {
                memento["sourceFunctionName"]
                    .as_str()
                    .expect("source function name")
                    .to_string()
            })
            .collect();
        assert_eq!(
            names,
            BTreeSet::from(["Thing::method".to_string(), "callee".to_string()])
        );
        for memento in mementos {
            assert_eq!(memento["file"], "src/lib.rs");
            assert!(memento["source_cid"]
                .as_str()
                .is_some_and(|cid| !cid.is_empty()));
            assert!(memento["template_cid"]
                .as_str()
                .is_some_and(|cid| !cid.is_empty()));
            assert!(memento.get("source").is_none(), "must not emit source text");
            assert!(
                memento.get("body_text").is_none(),
                "must not emit body text"
            );
            assert!(
                memento.get("ast_template").is_none(),
                "must not emit AST template text"
            );
        }

        let entries = resp["ir"].as_array().expect("ir array");
        for name in ["callee", "Thing::method"] {
            let entry = entries
                .iter()
                .find(|entry| entry["name"] == name)
                .unwrap_or_else(|| panic!("missing contract {name}: {entries:?}"));
            let warrants = entry["sourceWarrants"]
                .as_array()
                .expect("contract source warrants");
            assert_eq!(warrants.len(), 1);
            assert_eq!(warrants[0]["sourceFunctionName"], name);
            assert!(warrants[0]["source_cid"]
                .as_str()
                .is_some_and(|cid| !cid.is_empty()));
        }

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_projects_body_post_through_factory_walk_rows() {
        let root = temp_workspace("function_contract_factory_walk_projection");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "factory-walk-demo"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn encoded_len(bytes_len: usize) -> usize {
    let rem = bytes_len % 3;
    rem + 1
}
"#,
        )
        .expect("write source");

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");

        let factory_walk = resp["factoryAuditSummary"]["factoryWalk"]
            .as_array()
            .expect("function contracts must emit factory walk rows");
        let encoded_rows = factory_walk
            .iter()
            .filter(|row| row["sourceMemento"]["sourceFunctionName"] == "encoded_len")
            .collect::<Vec<_>>();
        assert!(
            encoded_rows.len() >= 2,
            "encoded_len should project let binding and result rows: {factory_walk:#?}"
        );
        assert!(
            encoded_rows.iter().all(|row| row["status"] == "warranted"
                && row["verdict"] == "complete"
                && row["output"] == "constraints"),
            "factory walk rows should be complete warranted constraints: {encoded_rows:#?}"
        );
        assert!(
            encoded_rows.iter().all(|row| row.get("source").is_none()
                && row.get("term").is_none()
                && row.get("site").is_none()),
            "factory walk rows must carry memento pins, not plaintext source/term/site: {encoded_rows:#?}"
        );
        assert!(
            encoded_rows
                .iter()
                .all(|row| row.get("emittedFormula").is_some()),
            "each projected row must name the emitted formula: {encoded_rows:#?}"
        );
        assert!(
            encoded_rows.iter().any(|row| {
                row["sourceMemento"]["span"]["start_line"] == json!(3)
                    && row["emittedFormula"]["kind"] == "atomic"
                    && row["emittedFormula"]["name"] == "="
                    && row["emittedFormula"]["args"][0]["kind"] == "var"
                    && row["emittedFormula"]["args"][0]["name"] == "rem"
            }),
            "let binding line should emit rem = bytes_len % 3: {encoded_rows:#?}"
        );
        assert!(
            encoded_rows.iter().any(|row| {
                row["sourceMemento"]["span"]["start_line"] == json!(4)
                    && row["emittedFormula"]["kind"] == "atomic"
                    && row["emittedFormula"]["name"] == "="
                    && row["emittedFormula"]["args"][0]["kind"] == "var"
                    && row["emittedFormula"]["args"][0]["name"] == "result"
            }),
            "tail line should emit result = tail expression: {encoded_rows:#?}"
        );
        assert_eq!(
            resp["factoryAuditSummary"]["emittedRows"],
            json!(factory_walk.len())
        );
        assert_eq!(
            resp["factoryAuditSummary"]["statusCounts"]["warranted"],
            json!(factory_walk.len())
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_factory_walk_pins_residual_result_to_result_statement() {
        let root = temp_workspace("function_contract_factory_walk_result_pin");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "factory-walk-result-pin-demo"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let source = r#"
pub fn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {
    let rem = bytes_len % 3;
    let complete_input_chunks = bytes_len / 3;
    let complete_chunk_output =
        if let Some(complete_chunk_output) = complete_input_chunks.checked_mul(4) {
            complete_chunk_output
        } else {
            return None;
        };
    if rem > 0 {
        if padding {
            complete_chunk_output.checked_add(4)
        } else {
            let encoded_rem = match rem {
                1 => 2,
                _ => 3,
            };
            complete_chunk_output.checked_add(encoded_rem)
        }
    } else {
        Some(complete_chunk_output)
    }
}
"#;
        fs::write(src_dir.join("lib.rs"), source).expect("write source");
        let rem_line = source
            .lines()
            .position(|line| line.contains("let rem ="))
            .expect("rem line")
            + 1;
        let result_line = source
            .lines()
            .position(|line| line.contains("if rem > 0"))
            .expect("result line")
            + 1;
        let unrelated_let_line = source
            .lines()
            .position(|line| line.contains("let complete_input_chunks"))
            .expect("unrelated let line")
            + 1;

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");

        let factory_walk = resp["factoryAuditSummary"]["factoryWalk"]
            .as_array()
            .expect("function contracts must emit factory walk rows");
        let encoded_rows = factory_walk
            .iter()
            .filter(|row| row["sourceMemento"]["sourceFunctionName"] == "encoded_len")
            .collect::<Vec<_>>();
        assert!(
            encoded_rows.iter().any(|row| {
                row["sourceMemento"]["span"]["start_line"] == json!(rem_line)
                    && row["emittedFormula"]["args"][0]["name"] == "rem"
            }),
            "rem binding should stay pinned to its own let line: {encoded_rows:#?}"
        );
        assert!(
            encoded_rows.iter().any(|row| {
                row["sourceMemento"]["span"]["start_line"] == json!(result_line)
                    && row["emittedFormula"]["args"][0]["name"] == "result"
            }),
            "residual result formula should pin to the result-producing statement: {encoded_rows:#?}"
        );
        let result_row = encoded_rows
            .iter()
            .find(|row| {
                row["sourceMemento"]["span"]["start_line"] == json!(result_line)
                    && row["emittedFormula"]["args"][0]["name"] == "result"
            })
            .expect("result row");
        let result_memento = SourceMemento::from_body_source(
            Some("encoded_len".to_string()),
            &json!({
                "file": result_row["sourceMemento"]["file"].clone(),
                "span": result_row["sourceMemento"]["span"].clone(),
                "param_names": result_row["sourceMemento"]["param_names"].clone(),
                "source_cid": result_row["sourceMemento"]["source_cid"].clone(),
                "template_cid": result_row["sourceMemento"]["template_cid"].clone(),
            }),
        )
        .expect("result source memento");
        let resolved = resolve_source_memento(&root, &result_memento)
            .expect("result source memento should resolve to its source line");
        assert!(
            resolved.fragment.body_text.contains("if rem > 0"),
            "result row should resolve to the result-producing source: {resolved:#?}"
        );
        assert!(
            !encoded_rows.iter().any(|row| {
                row["sourceMemento"]["span"]["start_line"] == json!(unrelated_let_line)
                    && row["emittedFormula"]["args"][0]["name"] == "result"
            }),
            "residual result formula must not drift onto an unrelated middle let: {encoded_rows:#?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_emits_infallible_serialize_contracts_from_manifest() {
        let root = temp_workspace("function_contract_infallible_serialize");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn identity(value: i64) -> i64 {
    value
}
"#,
        )
        .expect("write source");
        write_infallible_serialize_manifest(
            &root,
            r#"
[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "SerializableRecord"
contract = "serde_json_to_value__serializable_record"
reason = "derive Serialize over serde_json-infallible fields"

[[serde_json]]
function = "to_string"
type_crate = "consumer_crate"
type_name = "Sort"
contract = "serde_json_to_string__sort"
reason = "derive Serialize over serde_json-infallible fields"
"#,
        );

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");

        let entries = resp["ir"].as_array().expect("ir array");
        let by_name = |name: &str| -> &Value {
            entries
                .iter()
                .find(|entry| entry["name"] == name)
                .unwrap_or_else(|| panic!("missing synthetic contract `{name}`: {entries:?}"))
        };
        let to_value = by_name("serde_json_to_value__serializable_record");
        assert_eq!(to_value["kind"], "contract");
        assert_eq!(to_value["library"], "consumer_crate");
        assert_eq!(to_value["outBinding"], "out");
        assert_eq!(to_value["bodyDischargeEligible"], false);
        assert_eq!(to_value["bodyDischargeRefusalReason"], "totality-axiom");
        assert_eq!(
            to_value["post"],
            json!({
                "kind": "atomic",
                "name": "is_ok",
                "args": [{ "kind": "var", "name": "result" }]
            })
        );
        assert_eq!(
            by_name("serde_json_to_string__sort")["post"],
            to_value["post"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_refuses_malformed_infallible_serialize_manifest() {
        let cases = [
            ("string", r#"serde_json = "not an array""#),
            ("number", r#"serde_json = 7"#),
            (
                "object",
                r#"
[serde_json]
function = "to_value"
type_crate = "consumer_crate"
type_name = "SerializableRecord"
contract = "serde_json_to_value__serializable_record"
reason = "derive Serialize over serde_json-infallible fields"
"#,
            ),
            (
                "missing-field",
                r#"
[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "SerializableRecord"
reason = "derive Serialize over serde_json-infallible fields"
"#,
            ),
        ];

        for (name, manifest) in cases {
            let root = temp_workspace(&format!("infallible_serialize_bad_{name}"));
            let src_dir = root.join("src");
            fs::create_dir_all(&src_dir).expect("create src dir");
            fs::write(
                root.join("Cargo.toml"),
                r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
            )
            .expect("write Cargo.toml");
            fs::write(
                src_dir.join("lib.rs"),
                r#"
pub fn identity(value: i64) -> i64 {
    value
}
"#,
            )
            .expect("write source");
            write_infallible_serialize_manifest(&root, manifest);

            let err = function_contract_lift(&json!({
                "workspace_root": root.to_string_lossy(),
                "source_paths": ["."]
            }))
            .expect_err("malformed infallible serialize manifest must refuse loudly");
            assert!(
                err.contains("infallible_serialize.toml"),
                "error should name the manifest path for case {name}: {err}"
            );
            let _ = fs::remove_dir_all(root);
        }
    }

    #[test]
    fn function_contract_lift_emits_function_postconditions_from_manifest() {
        let root = temp_workspace("function_contract_dfn_postconditions");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn identity(value: i64) -> i64 {
    value
}
"#,
        )
        .expect("write source");
        write_function_postconditions_manifest(
            &root,
            r#"
[[functions]]
call_kind = "associated"
callee_crate = "consumer_crate"
type_path = "Cid"
callee = "parse"
arg0_format_literal = "blake3-512:{}"
arg0_repeat_literal = "0"
arg0_repeat_count = 128
contract = "cid_parse__zero_digest"
post_predicate = "is_ok"
reason = "format!(\"blake3-512:{}\", \"0\".repeat(128)) is a valid blake3-512 CID"

[[functions]]
call_kind = "method"
callee_crate = "consumer_crate"
receiver_path = "GrammarOpRegistry"
callee = "cid"
arg0_path = "CONCEPT_BIND_RESULT"
contract = "op_name_catalog_cid__concept_bind_result"
post_predicate = "is_some"
reason = "grammar_op_shape(CONCEPT_BIND_RESULT) has a fixed primitive arm and json_cid returns a valid CID"
"#,
        );

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");

        let entries = resp["ir"].as_array().expect("ir array");
        let by_name = |name: &str| -> &Value {
            entries
                .iter()
                .find(|entry| entry["name"] == name)
                .unwrap_or_else(|| panic!("missing synthetic D-fn contract `{name}`: {entries:?}"))
        };

        let parse = by_name("cid_parse__zero_digest");
        assert_eq!(parse["kind"], "contract");
        assert_eq!(parse["library"], "consumer_crate");
        assert_eq!(parse["bodyDischargeEligible"], false);
        assert_eq!(parse["bodyDischargeRefusalReason"], "totality-axiom");
        assert_eq!(
            parse["post"],
            json!({
                "kind": "atomic",
                "name": "is_ok",
                "args": [{ "kind": "var", "name": "result" }]
            })
        );

        let cid = by_name("op_name_catalog_cid__concept_bind_result");
        assert_eq!(cid["kind"], "contract");
        assert_eq!(cid["library"], "consumer_crate");
        assert_eq!(cid["bodyDischargeEligible"], false);
        assert_eq!(cid["bodyDischargeRefusalReason"], "totality-axiom");
        assert_eq!(
            cid["post"],
            json!({
                "kind": "atomic",
                "name": "is_some",
                "args": [{ "kind": "var", "name": "result" }]
            })
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_does_not_emit_guard_only_free_pure_postcondition() {
        let root = temp_workspace("function_contract_free_pure_guard_only");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        fs::write(
            src_dir.join("lib.rs"),
            r#"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}
"#,
        )
        .expect("write source");
        write_function_postconditions_manifest(
            &root,
            r#"
[[functions]]
call_kind = "free"
callee_crate = "consumer_crate"
callee = "pure_fn"
pure = true
contract = "pure_fn__guard_only"
post_predicate = "is_some"
reason = "purity lets a dominating is_some guard transfer to an identical repeated call; it is not a global postcondition"
"#,
        );

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");

        let entries = resp["ir"].as_array().expect("ir array");
        assert!(
            entries
                .iter()
                .all(|entry| entry["name"] != "pure_fn__guard_only"),
            "free pure rules are guard-transfer declarations, not unconditional function postconditions: {entries:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    fn function_contract_entry_for_free_pure_fixture(
        temp_name: &str,
        src: &str,
        target_name: &str,
        manifest: Option<String>,
    ) -> Value {
        let root = temp_workspace(temp_name);
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        if let Some(manifest) = manifest {
            write_function_postconditions_manifest(&root, &manifest);
        }

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."]
        }))
        .expect("function contract lift");
        let entries = resp["ir"].as_array().expect("ir array");
        let target = entries
            .iter()
            .find(|entry| entry["name"] == target_name)
            .unwrap_or_else(|| panic!("missing `{target_name}` contract: {entries:?}"));
        let target = target.clone();

        let _ = fs::remove_dir_all(root);
        target
    }

    fn function_contract_post_for_free_pure_fixture(
        temp_name: &str,
        src: &str,
        target_name: &str,
        manifest: Option<String>,
    ) -> String {
        let target =
            function_contract_entry_for_free_pure_fixture(temp_name, src, target_name, manifest);
        let post = serde_json::to_string(&target["post"]).expect("post stringifies");
        post
    }

    fn assert_post_has_guarded_pure_free_unwrap(post: &str) {
        assert!(
            post.contains("cf_guarded"),
            "statement-position pure free guard must emit a content-bearing cf_guarded carrier: {post}"
        );
        assert!(
            post.contains("is_some"),
            "guard carrier must establish the Option precondition: {post}"
        );
        assert!(
            post.contains("pure_fn"),
            "guard and unwrap receiver must name the manifest pure function: {post}"
        );
        assert!(
            post.contains("method:unwrap"),
            "guard carrier must contain the panic leaf term the verifier enumerates: {post}"
        );
    }

    fn assert_post_has_guarded_pure_free_expect(post: &str) {
        assert!(
            post.contains("cf_guarded"),
            "statement-position pure free guard must emit a content-bearing cf_guarded carrier: {post}"
        );
        assert!(
            post.contains("is_some"),
            "guard carrier must establish the Option precondition: {post}"
        );
        assert!(
            post.contains("pure_fn"),
            "guard and expect receiver must name the manifest pure function: {post}"
        );
        assert!(
            post.contains("method:expect"),
            "guard carrier must contain the expect panic leaf term the verifier enumerates: {post}"
        );
    }

    fn assert_post_has_no_guarded_effect(post: &str) {
        assert!(
            !post.contains("cf_guarded"),
            "refused guard-transfer shape must not emit a cf_guarded proof carrier: {post}"
        );
    }

    fn count_ctor_name(value: &Value, target: &str) -> usize {
        match value {
            Value::Object(map) => {
                let here = (map.get("kind").and_then(Value::as_str) == Some("ctor")
                    && map.get("name").and_then(Value::as_str) == Some(target))
                    as usize;
                here + map
                    .values()
                    .map(|child| count_ctor_name(child, target))
                    .sum::<usize>()
            }
            Value::Array(items) => items
                .iter()
                .map(|child| count_ctor_name(child, target))
                .sum(),
            _ => 0,
        }
    }

    #[test]
    fn function_contract_lift_carries_manifest_pure_free_guard_for_statement_unwrap() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn guarded(line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_guard_positive",
            src,
            "guarded",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_guarded_pure_free_unwrap(&post);
    }

    #[test]
    fn function_contract_lift_carries_manifest_pure_free_guard_for_statement_expect() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn guarded(line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let declared = pure_fn(line).expect("present");
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_guard_expect_positive",
            src,
            "guarded",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_guarded_pure_free_expect(&post);
    }

    #[test]
    fn function_contract_lift_emits_one_formula_occurrence_for_guarded_panic_carrier() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn guarded(line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let entry = function_contract_entry_for_free_pure_fixture(
            "function_contract_free_pure_statement_single_formula_carrier",
            src,
            "guarded",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_eq!(
            count_ctor_name(&entry["post"], "method:unwrap"),
            1,
            "formula-backed guarded panic carrier must emit exactly one unwrap occurrence; verifier dedup must not mask kit double-emission: {}",
            entry["post"]
        );
    }

    #[test]
    fn function_contract_lift_carries_manifest_pure_free_guard_through_len_condition() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn guarded(lines: &[&str], idx: usize, consumed: usize) -> Option<&str> {
    if idx + consumed < lines.len() && pure_fn(lines[idx + consumed]).is_some() {
        let declared = pure_fn(lines[idx + consumed]).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_len_condition",
            src,
            "guarded",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_guarded_pure_free_unwrap(&post);
    }

    #[test]
    fn function_contract_lift_carries_manifest_pure_free_guard_inside_while_body() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn guarded(lines: &[&str]) -> Option<&str> {
    let mut idx = 0usize;
    while idx < lines.len() {
        let consumed = 1usize;
        if idx + consumed < lines.len() && pure_fn(lines[idx + consumed]).is_some() {
            let declared = pure_fn(lines[idx + consumed]).unwrap();
            return Some(declared);
        }
        idx += 1;
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_loop_guard",
            src,
            "guarded",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_guarded_pure_free_unwrap(&post);
    }

    #[test]
    fn function_contract_lift_carries_manifest_pure_free_guard_through_len_read_before_unwrap() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn guarded(lines: &[&str], idx: usize) -> Option<&str> {
    if pure_fn(lines[idx]).is_some() {
        let _line_count = lines.len();
        let declared = pure_fn(lines[idx]).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_len_read",
            src,
            "guarded",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_guarded_pure_free_unwrap(&post);
    }

    #[test]
    fn function_contract_lift_does_not_leak_pure_free_guard_outside_then_branch() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn scope_leak(line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
    }
    let declared = pure_fn(line).unwrap();
    Some(declared)
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_scope_leak",
            src,
            "scope_leak",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_with_wrong_polarity() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn wrong_polarity(line: &str) -> Option<&str> {
    if pure_fn(line).is_none() {
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_wrong_polarity",
            src,
            "wrong_polarity",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_from_disjunction() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn disjunction(line: &str, flag: bool) -> Option<&str> {
    if flag || pure_fn(line).is_some() {
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_disjunction",
            src,
            "disjunction",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_in_else_branch() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn else_branch(line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
    } else {
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_else_branch",
            src,
            "else_branch",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_after_arg_reassignment() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn reassigned(mut line: &str, other: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        line = other;
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_reassigned",
            src,
            "reassigned",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_after_method_mutation() {
        let src = r##"
pub struct Slot(String);

impl Slot {
    pub fn mutate(&mut self) {}
}

pub fn pure_fn(_slot: &Slot) -> Option<&str> {
    None
}

pub fn method_mutation(mut slot: Slot) -> Option<&str> {
    if pure_fn(&slot).is_some() {
        slot.mutate();
        let declared = pure_fn(&slot).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_method_mutation",
            src,
            "method_mutation",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_after_mut_borrow_call() {
        let src = r##"
pub fn take_mut(_line: &mut &str) {}

pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn mut_borrow(mut line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        take_mut(&mut line);
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_mut_borrow",
            src,
            "mut_borrow",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_after_same_expression_mut_borrow() {
        let src = r##"
pub fn take_mut(_line: &mut &str) {}

pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn same_expression_mut_borrow(mut line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let pair = (take_mut(&mut line), pure_fn(line).unwrap());
        return Some(pair.1);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_same_expression_mut_borrow",
            src,
            "same_expression_mut_borrow",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_expect_after_same_expression_mut_borrow() {
        let src = r##"
pub fn take_mut(_line: &mut &str) {}

pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn same_expression_expect_mut_borrow(mut line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let pair = (take_mut(&mut line), pure_fn(line).expect("present"));
        return Some(pair.1);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_same_expression_expect_mut_borrow",
            src,
            "same_expression_expect_mut_borrow",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_after_call_callee_mutation() {
        let src = r##"
pub fn take_mut(_line: &mut &str) {}

pub fn consume(value: &str) -> &str {
    value
}

pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn call_callee_mutates(mut line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let declared = ({ take_mut(&mut line); consume })(pure_fn(line).unwrap());
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_call_callee_mutates",
            src,
            "call_callee_mutates",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_after_uncollected_struct_mutation() {
        let src = r##"
pub struct Holder<'a> {
    pub value: &'a str,
}

pub fn take_mut(_line: &mut &str) {}

pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn struct_literal_mutates(mut line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let pair = (Holder { value: { take_mut(&mut line); "" } }, pure_fn(line).unwrap());
        return Some(pair.1);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_struct_literal_mutates",
            src,
            "struct_literal_mutates",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_with_non_stable_arg_expression() {
        let src = r##"
pub fn pure_fn(_line: Option<&str>) -> Option<&str> {
    None
}

pub fn non_stable_arg(mut iter: std::vec::IntoIter<&str>) -> Option<&str> {
    if pure_fn(iter.next()).is_some() {
        let declared = pure_fn(iter.next()).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_non_stable_arg",
            src,
            "non_stable_arg",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_for_different_function() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn other_fn(_line: &str) -> Option<&str> {
    None
}

pub fn different_function(line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let declared = other_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_different_function",
            src,
            "different_function",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_for_different_args() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn different_args(left: &str, right: &str) -> Option<&str> {
    if pure_fn(left).is_some() {
        let declared = pure_fn(right).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_different_args",
            src,
            "different_args",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_unregistered_pure_free_guard() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    None
}

pub fn unregistered(line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_unregistered",
            src,
            "unregistered",
            None,
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn function_contract_lift_refuses_pure_free_guard_without_local_definition() {
        let src = r##"
pub fn missing_definition(line: &str) -> Option<&str> {
    if pure_fn(line).is_some() {
        let declared = pure_fn(line).unwrap();
        return Some(declared);
    }
    None
}
"##;

        let post = function_contract_post_for_free_pure_fixture(
            "function_contract_free_pure_statement_missing_definition",
            src,
            "missing_definition",
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_post_has_no_guarded_effect(&post);
    }

    #[test]
    fn lift_implications_disambiguates_blessed_concrete_param_from_manifest_alias() {
        let src = r##"
use serde_json as sj;

pub struct SerializableRecord;

pub fn caller(realized: &SerializableRecord) {
    sj::to_value(realized).unwrap();
}
"##;
        let root = temp_workspace("lift_implications_infallible_param");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_infallible_serialize_manifest(
            &root,
            r#"
[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "SerializableRecord"
contract = "serde_json_to_value__serializable_record"
reason = "derive Serialize over serde_json-infallible fields"
"#,
        );

        let expected_cid = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "serde_json_to_value__serializable_record",
                    "library": "consumer_crate",
                    "contract_cid": expected_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let bridge = ir
            .iter()
            .find(|entry| entry["sourceSymbol"] == "to_value")
            .expect("aliased serde_json::to_value bridge for blessed concrete type");
        assert_eq!(bridge["targetContractCid"], expected_cid);
        assert_eq!(bridge["callsite"]["start_line"], 7);
        assert_eq!(bridge["callsite"]["panicSite"], false);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_disambiguates_function_postcondition_shapes_from_manifest() {
        let src = r##"
pub struct Cid;
pub struct GrammarOpRegistry;

const CONCEPT_BIND_RESULT: &str = "concept:bind-result";
const CONCEPT_SEQ: &str = "concept:seq";

impl Cid {
    pub fn parse(_value: String) -> Result<Cid, ()> {
        panic!()
    }
}

impl GrammarOpRegistry {
    pub fn cid(&self, _name: &str) -> Option<Cid> {
        panic!()
    }
}

pub fn parse_zero_digest() -> Cid {
    Cid::parse(format!("blake3-512:{}", "0".repeat(128))).expect("sentinel cid is valid")
}

pub fn parse_other_digest() -> Cid {
    Cid::parse(format!("blake3-512:{}", "1".repeat(128))).expect("not audited")
}

pub fn parse_wrong_count() -> Cid {
    Cid::parse(format!("blake3-512:{}", "0".repeat(64))).expect("not audited")
}

pub fn parse_wrong_prefix() -> Cid {
    Cid::parse(format!("blake3-256:{}", "0".repeat(128))).expect("not audited")
}

pub fn parse_unknown_predicate() -> Cid {
    Cid::parse(format!("blake3-512:{}", "2".repeat(128))).expect("audited producer, unknown panic predicate")
}

pub fn parse_variable(value: String) -> Cid {
    Cid::parse(value).expect("not audited")
}

pub fn catalog_bind_result() -> Cid {
    GrammarOpRegistry.cid(CONCEPT_BIND_RESULT).expect("concept:bind-result is primitive")
}

pub fn catalog_other_name() -> Cid {
    GrammarOpRegistry.cid(CONCEPT_SEQ).expect("not audited")
}
"##;
        let root = temp_workspace("lift_implications_dfn_postconditions");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_function_postconditions_manifest(
            &root,
            r#"
[[functions]]
call_kind = "associated"
callee_crate = "consumer_crate"
type_path = "Cid"
callee = "parse"
arg0_format_literal = "blake3-512:{}"
arg0_repeat_literal = "0"
arg0_repeat_count = 128
contract = "cid_parse__zero_digest"
post_predicate = "is_ok"
reason = "format!(\"blake3-512:{}\", \"0\".repeat(128)) is a valid blake3-512 CID"

[[functions]]
call_kind = "associated"
callee_crate = "consumer_crate"
type_path = "Cid"
callee = "parse"
arg0_format_literal = "blake3-512:{}"
arg0_repeat_literal = "2"
arg0_repeat_count = 128
contract = "cid_parse__unknown_predicate"
post_predicate = "is_canonical"
reason = "recognized producer with an unknown singleton predicate must not imply a std panic partial"

[[functions]]
call_kind = "method"
callee_crate = "consumer_crate"
receiver_path = "GrammarOpRegistry"
callee = "cid"
arg0_path = "CONCEPT_BIND_RESULT"
contract = "op_name_catalog_cid__concept_bind_result"
post_predicate = "is_some"
reason = "grammar_op_shape(CONCEPT_BIND_RESULT) has a fixed primitive arm and json_cid returns a valid CID"
"#,
        );

        let parse_cid = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let catalog_cid = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let unknown_predicate_cid = "blake3-512:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
        let result_expect_cid = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
        let option_expect_cid = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "cid_parse__zero_digest",
                    "library": "consumer_crate",
                    "contract_cid": parse_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                },
                {
                    "name": "cid_parse__unknown_predicate",
                    "library": "consumer_crate",
                    "contract_cid": unknown_predicate_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                },
                {
                    "name": "op_name_catalog_cid__concept_bind_result",
                    "library": "consumer_crate",
                    "contract_cid": catalog_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                },
                {
                    "name": "result_expect@std/src/result.rs:2:1",
                    "library": "std",
                    "contract_cid": result_expect_cid,
                    "body_bearing": true,
                    "has_pre": true
                },
                {
                    "name": "option_expect@std/src/option.rs:2:1",
                    "library": "std",
                    "contract_cid": option_expect_cid,
                    "body_bearing": true,
                    "has_pre": true
                }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let parse_hits: Vec<&Value> = ir
            .iter()
            .filter(|entry| {
                entry["sourceSymbol"] == "parse" && entry["targetContractCid"] == parse_cid
            })
            .collect();
        assert_eq!(
            parse_hits.len(),
            1,
            "only the exact audited Cid::parse(format!(\"blake3-512:{{}}\", \"0\".repeat(128))) shape may bridge to the parse totality contract; wrong literal/count/prefix and variables must refuse: {ir:?}"
        );

        let unknown_predicate_hits: Vec<&Value> = ir
            .iter()
            .filter(|entry| {
                entry["sourceSymbol"] == "parse"
                    && entry["targetContractCid"] == unknown_predicate_cid
            })
            .collect();
        assert_eq!(
            unknown_predicate_hits.len(),
            1,
            "the unknown-predicate manifest entry should still emit its producer bridge, proving the later panic refusal is predicate-gated rather than recognizer failure: {ir:?}"
        );

        let catalog_hits: Vec<&Value> = ir
            .iter()
            .filter(|entry| {
                entry["sourceSymbol"] == "method:cid" && entry["targetContractCid"] == catalog_cid
            })
            .collect();
        assert_eq!(
            catalog_hits.len(),
            1,
            "only GrammarOpRegistry.cid(CONCEPT_BIND_RESULT) may bridge to the catalog totality contract: {ir:?}"
        );

        let panic_targets: Vec<&str> = ir
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "method:expect")
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect();
        assert_eq!(
            panic_targets,
            vec![result_expect_cid, option_expect_cid],
            "manifest-audited receiver calls must route their panic leaf to the matching std partial; unaudited receiver shapes must still refuse: {ir:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_disambiguates_constructor_locals_for_infallible_serde_manifest() {
        let src = r##"
use serde_json as sj;

pub struct BridgeHeaderV14 {
    name: String,
}

pub struct Other {
    name: String,
}

macro_rules! make_header {
    () => {
        BridgeHeaderV14 {
            name: "macro".to_string(),
        }
    };
}

pub fn audited_constructor() {
    let header = BridgeHeaderV14 {
        name: "ok".to_string(),
    };
    sj::to_value(header).unwrap();
}

pub fn explicit_type_wins() {
    let header: Other = BridgeHeaderV14 {
        name: "wrong".to_string(),
    }.into();
    sj::to_value(header).unwrap();
}

pub fn macro_constructor_does_not_bind() {
    let header = make_header!();
    sj::to_value(header).unwrap();
}
"##;
        let root = temp_workspace("lift_implications_constructor_local_type");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_infallible_serialize_manifest(
            &root,
            r#"
[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "BridgeHeaderV14"
contract = "serde_json_to_value__bridge_header_v14"
reason = "BridgeHeaderV14 derives Serialize over serde_json-infallible fields"
"#,
        );

        let expected_cid = "blake3-512:abababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababab";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [{
                "name": "serde_json_to_value__bridge_header_v14",
                "library": "consumer_crate",
                "contract_cid": expected_cid,
                "bodyDischargeEligible": false,
                "bodyDischargeRefusalReason": "totality-axiom"
            }],
        }))
        .expect("lift_implications");

        let hits: Vec<&Value> = resp["ir"]
            .as_array()
            .expect("ir array")
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "to_value")
            .filter(|entry| entry["targetContractCid"] == expected_cid)
            .collect();
        assert_eq!(
            hits.len(),
            1,
            "only the direct local struct constructor should bind to the manifest type; explicit-type and macro locals must not borrow it: {resp:#?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_disambiguates_option_field_match_bindings_for_infallible_serde_manifest() {
        let src = r##"
use serde_json as sj;

pub struct Claim {
    witness: Option<Witness>,
    other: Option<Other>,
}

pub struct Witness {
    value: String,
}

pub struct Other {
    value: String,
}

pub fn audited_option_field(claim: &Claim) {
    match &claim.witness {
        Some(witness) => {
            sj::to_value(witness).unwrap();
        }
        None => {}
    }
}

pub fn audited_option_field_if_let(claim: &Claim) {
    if let Some(witness) = &claim.witness {
        sj::to_value(witness).unwrap();
    }
}

pub fn shadowed_binding_does_not_remain_typed(claim: &Claim) {
    match &claim.witness {
        Some(witness) => {
            let witness = Other {
                value: "shadow".to_string(),
            };
            sj::to_value(witness).unwrap();
        }
        None => {}
    }
}

pub fn method_receiver_does_not_bind(claim: &Claim) {
    match claim.witness.as_ref() {
        Some(witness) => {
            sj::to_value(witness).unwrap();
        }
        None => {}
    }
}

pub fn if_let_method_receiver_does_not_bind(claim: &Claim) {
    if let Some(witness) = claim.witness.as_ref() {
        sj::to_value(witness).unwrap();
    }
}

pub fn wrong_field_does_not_bind(claim: &Claim) {
    match &claim.other {
        Some(witness) => {
            sj::to_value(witness).unwrap();
        }
        None => {}
    }
}
"##;
        let root = temp_workspace("lift_implications_option_field_bindings");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_infallible_serialize_manifest(
            &root,
            r#"
[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "Witness"
contract = "serde_json_to_value__witness"
reason = "Witness derives Serialize over serde_json-infallible fields"
"#,
        );

        let expected_cid = "blake3-512:bcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbc";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [{
                "name": "serde_json_to_value__witness",
                "library": "consumer_crate",
                "contract_cid": expected_cid,
                "bodyDischargeEligible": false,
                "bodyDischargeRefusalReason": "totality-axiom"
            }],
        }))
        .expect("lift_implications");

        let hits: Vec<&Value> = resp["ir"]
            .as_array()
            .expect("ir array")
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "to_value")
            .filter(|entry| entry["targetContractCid"] == expected_cid)
            .collect();
        assert_eq!(
            hits.len(),
            2,
            "only direct Option field patterns over &claim.witness should bind witness to Witness; shadowed, method-derived, and wrong-field bindings must not borrow it: {resp:#?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn constructor_local_type_does_not_escape_nested_block_scope() {
        let src = r##"
use serde_json as sj;

pub struct BridgeHeaderV14 {
    name: String,
}

pub struct Other {
    name: String,
}

pub fn block_scope(header: Other) {
    {
        let header = BridgeHeaderV14 {
            name: "inner".to_string(),
        };
        drop(header);
    }
    sj::to_value(header).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("constructor_scope_nested_block", src, "BridgeHeaderV14"),
            0,
            "constructor-local type inferred inside a nested block must not type the post-block binding"
        );
    }

    #[test]
    fn constructor_local_type_does_not_escape_match_arm_scope() {
        let src = r##"
use serde_json as sj;

pub struct BridgeHeaderV14 {
    name: String,
}

pub struct Other {
    name: String,
}

pub fn match_scope(header: Other, flag: bool) {
    match flag {
        true => {
            let header = BridgeHeaderV14 {
                name: "inner".to_string(),
            };
            drop(header);
        }
        false => {}
    }
    sj::to_value(header).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("constructor_scope_match_arm", src, "BridgeHeaderV14"),
            0,
            "constructor-local type inferred inside a match arm must not type the post-match binding"
        );
    }

    #[test]
    fn constructor_local_type_does_not_escape_if_branch_scope() {
        let src = r##"
use serde_json as sj;

pub struct BridgeHeaderV14 {
    name: String,
}

pub struct Other {
    name: String,
}

pub fn if_scope(header: Other, flag: bool) {
    if flag {
        let header = BridgeHeaderV14 {
            name: "inner".to_string(),
        };
        drop(header);
    }
    sj::to_value(header).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("constructor_scope_if_branch", src, "BridgeHeaderV14"),
            0,
            "constructor-local type inferred inside an if branch must not type the post-if binding"
        );
    }

    #[test]
    fn constructor_local_type_does_not_escape_loop_body_scope() {
        let src = r##"
use serde_json as sj;

pub struct BridgeHeaderV14 {
    name: String,
}

pub struct Other {
    name: String,
}

pub fn loop_scope(header: Other) {
    loop {
        let header = BridgeHeaderV14 {
            name: "inner".to_string(),
        };
        drop(header);
        break;
    }
    sj::to_value(header).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("constructor_scope_loop_body", src, "BridgeHeaderV14"),
            0,
            "constructor-local type inferred inside a loop body must not type the post-loop binding"
        );
    }

    #[test]
    fn constructor_local_type_does_not_escape_closure_body_scope() {
        let src = r##"
use serde_json as sj;

pub struct BridgeHeaderV14 {
    name: String,
}

pub struct Other {
    name: String,
}

pub fn closure_scope(header: Other) {
    let _f = || {
        let header = BridgeHeaderV14 {
            name: "inner".to_string(),
        };
        drop(header);
    };
    sj::to_value(header).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("constructor_scope_closure_body", src, "BridgeHeaderV14"),
            0,
            "constructor-local type inferred inside a closure body must not type the post-closure binding"
        );
    }

    #[test]
    fn option_field_binding_does_not_escape_if_let_scope() {
        let src = r##"
use serde_json as sj;

pub struct Claim {
    witness: Option<Witness>,
}

pub struct Witness {
    value: String,
}

pub struct Other {
    value: String,
}

pub fn if_let_scope(claim: &Claim, witness: Other) {
    if let Some(witness) = &claim.witness {
        drop(witness);
    }
    sj::to_value(witness).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("option_scope_if_let", src, "Witness"),
            0,
            "Option field binding inside if-let must not type the post-if binding"
        );
    }

    #[test]
    fn option_field_binding_does_not_escape_match_scope() {
        let src = r##"
use serde_json as sj;

pub struct Claim {
    witness: Option<Witness>,
}

pub struct Witness {
    value: String,
}

pub struct Other {
    value: String,
}

pub fn match_scope(claim: &Claim, witness: Other) {
    match &claim.witness {
        Some(witness) => {
            drop(witness);
        }
        None => {}
    }
    sj::to_value(witness).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("option_scope_match", src, "Witness"),
            0,
            "Option field binding inside match must not type the post-match binding"
        );
    }

    #[test]
    fn option_field_binding_does_not_escape_nested_block_scope() {
        let src = r##"
use serde_json as sj;

pub struct Claim {
    witness: Option<Witness>,
}

pub struct Witness {
    value: String,
}

pub struct Other {
    value: String,
}

pub fn block_scope(claim: &Claim, witness: Other) {
    {
        if let Some(witness) = &claim.witness {
            drop(witness);
        }
    }
    sj::to_value(witness).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("option_scope_nested_block", src, "Witness"),
            0,
            "Option field binding inside a nested block must not type the post-block binding"
        );
    }

    #[test]
    fn option_field_binding_does_not_escape_loop_body_scope() {
        let src = r##"
use serde_json as sj;

pub struct Claim {
    witness: Option<Witness>,
}

pub struct Witness {
    value: String,
}

pub struct Other {
    value: String,
}

pub fn loop_scope(claim: &Claim, witness: Other) {
    loop {
        if let Some(witness) = &claim.witness {
            drop(witness);
        }
        break;
    }
    sj::to_value(witness).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("option_scope_loop_body", src, "Witness"),
            0,
            "Option field binding inside a loop body must not type the post-loop binding"
        );
    }

    #[test]
    fn option_field_binding_does_not_escape_closure_body_scope() {
        let src = r##"
use serde_json as sj;

pub struct Claim {
    witness: Option<Witness>,
}

pub struct Witness {
    value: String,
}

pub struct Other {
    value: String,
}

pub fn closure_scope(claim: &Claim, witness: Other) {
    let _f = || {
        if let Some(witness) = &claim.witness {
            drop(witness);
        }
    };
    sj::to_value(witness).unwrap();
}
"##;
        assert_eq!(
            manifest_to_value_hit_count("option_scope_closure_body", src, "Witness"),
            0,
            "Option field binding inside a closure body must not type the post-closure binding"
        );
    }

    #[test]
    fn lift_implications_matches_function_postconditions_by_arg0_path_without_fuzzy_borrowing() {
        let src = r##"
pub mod canonical {
    pub fn json_jcs(_value: &serde_json::Value) -> Result<String, String> {
        panic!()
    }
}

pub mod other {
    pub fn json_jcs(_value: &serde_json::Value) -> Result<String, String> {
        panic!()
    }
}

pub fn audited(value: serde_json::Value, other_value: serde_json::Value) {
    crate::canonical::json_jcs(&value).expect("audited value canonicalizes");
    crate::canonical::json_jcs(&other_value).expect("wrong arg");
    crate::other::json_jcs(&value).expect("wrong function path");
}

pub fn same_shape_later(value: serde_json::Value) {
    crate::canonical::json_jcs(&value).expect("same shape, wrong source site");
}
"##;
        let root = temp_workspace("lift_implications_arg0_path_postconditions");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        let audited_line = source_line_containing(src, "audited value canonicalizes");
        write_function_postconditions_manifest(
            &root,
            &format!(
                r#"
[[functions]]
call_kind = "associated"
callee_crate = "consumer_crate"
type_path = "crate::canonical"
callee = "json_jcs"
source_file = "src/lib.rs"
source_line = {audited_line}
arg0_path = "value"
contract = "canonical_json_jcs__audited_value"
post_predicate = "is_ok"
reason = "The audited value is known to contain only canonicalizable JSON primitives"
"#,
            ),
        );

        let post_cid = "blake3-512:cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd";
        let result_expect_cid = "blake3-512:dededededededededededededededededededededededededededededededededededededededededededededededededededededededededededededededededede";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "canonical_json_jcs__audited_value",
                    "library": "consumer_crate",
                    "contract_cid": post_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                },
                {
                    "name": "result_expect@std/src/result.rs:2:1",
                    "library": "std",
                    "contract_cid": result_expect_cid,
                    "body_bearing": true,
                    "has_pre": true
                }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let post_hits: Vec<&Value> = ir
            .iter()
            .filter(|entry| {
                entry["sourceSymbol"] == "json_jcs" && entry["targetContractCid"] == post_cid
            })
            .collect();
        assert_eq!(
            post_hits.len(),
            1,
            "only crate::canonical::json_jcs(&value) may bridge to the audited postcondition: {resp:#?}"
        );
        let panic_targets: Vec<&str> = ir
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "method:expect")
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect();
        assert_eq!(
            panic_targets,
            vec![result_expect_cid],
            "only the audited receiver should route its expect panic leaf through result_expect: {resp:#?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    fn lift_method_postcondition_fixture(temp_name: &str, src: &str) -> (Value, String) {
        let root = temp_workspace(temp_name);
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        let audited_line = source_line_containing(src, "audited prefix");
        write_function_postconditions_manifest(
            &root,
            &format!(
                r#"
[[functions]]
call_kind = "method"
callee_crate = "consumer_crate"
receiver_path = "digest"
callee = "strip_prefix"
source_file = "src/lib.rs"
source_line = {audited_line}
arg0_path = "prefix"
contract = "digest_strip_prefix__audited"
post_predicate = "is_some"
reason = "audited digest prefix"
"#,
            ),
        );

        let option_expect_cid = "blake3-512:abababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababab";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "option_expect@std/src/option.rs:2:1",
                    "library": "std",
                    "contract_cid": option_expect_cid,
                    "body_bearing": true,
                    "has_pre": true
                }
            ],
        }))
        .expect("lift_implications");

        let _ = fs::remove_dir_all(root);
        (resp, option_expect_cid.to_string())
    }

    fn method_expect_targets(resp: &Value) -> Vec<&str> {
        let ir = resp["ir"].as_array().expect("ir array");
        ir.iter()
            .filter(|entry| entry["sourceSymbol"] == "method:expect")
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect()
    }

    #[test]
    fn lift_implications_refuses_method_postcondition_after_receiver_reassignment() {
        let src = r##"
pub fn audited(mut digest: String, prefix: &str, other: String) {
    digest = other;
    digest.strip_prefix(prefix).expect("audited prefix");
}
"##;
        let (resp, _) = lift_method_postcondition_fixture(
            "lift_implications_method_postcondition_reassign",
            src,
        );
        let panic_targets = method_expect_targets(&resp);
        assert!(
            panic_targets.is_empty(),
            "a source-line-gated method postcondition must refuse after receiver reassignment: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_routes_method_postcondition_before_later_receiver_reassignment() {
        let src = r##"
pub fn audited(mut digest: String, prefix: &str, other: String) {
    digest.strip_prefix(prefix).expect("audited prefix");
    digest = other;
}
"##;
        let (resp, option_expect_cid) = lift_method_postcondition_fixture(
            "lift_implications_method_postcondition_post_reassign",
            src,
        );
        let panic_targets = method_expect_targets(&resp);
        assert_eq!(
            panic_targets,
            vec![option_expect_cid.as_str()],
            "later receiver reassignment must not invalidate an already-audited method call: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_method_postcondition_after_same_expression_mut_borrow() {
        let src = r##"
fn touch(_digest: &mut String) -> bool {
    true
}

pub fn audited(mut digest: String, prefix: &str) {
    if touch(&mut digest) && digest.strip_prefix(prefix).expect("audited prefix").is_empty() {
    }
}
"##;
        let (resp, _) = lift_method_postcondition_fixture(
            "lift_implications_method_postcondition_same_expression_mut_borrow",
            src,
        );
        let panic_targets = method_expect_targets(&resp);
        assert!(
            panic_targets.is_empty(),
            "a same-expression mut-borrow before the audited call must keep the method postcondition refused: {resp:#?}"
        );
    }

    fn free_pure_option_manifest(callee: &str) -> String {
        format!(
            r#"
[[functions]]
call_kind = "free"
callee_crate = "consumer_crate"
callee = "{callee}"
pure = true
contract = "manifest_pure_option_contract"
post_predicate = "is_some"
reason = "manifest-declared pure free Option producer may share an identical-call is_some guard"
"#,
        )
    }

    fn lift_implications_for_free_pure_fixture(
        temp_name: &str,
        src: &str,
        manifest: Option<String>,
    ) -> Value {
        let root = temp_workspace(temp_name);
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        if let Some(manifest) = manifest {
            write_function_postconditions_manifest(&root, &manifest);
        }

        let option_unwrap_cid = "blake3-512:abababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababab";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "manifest_pure_option_contract",
                    "library": "consumer_crate",
                    "contract_cid": "blake3-512:cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                },
                {
                    "name": "option_unwrap@std/src/option.rs:2:1",
                    "library": "std",
                    "contract_cid": option_unwrap_cid,
                    "body_bearing": true,
                    "has_pre": true
                }
            ],
        }))
        .expect("lift_implications");

        let _ = fs::remove_dir_all(root);
        resp
    }

    fn method_unwrap_targets(resp: &Value) -> Vec<&str> {
        resp["ir"]
            .as_array()
            .expect("ir array")
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "method:unwrap")
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect()
    }

    #[test]
    fn lift_implications_routes_manifest_pure_free_call_guarded_unwrap() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn guarded(line: &str) -> &str {
    if pure_fn(line).is_some() {
        pure_fn(line).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_positive",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_eq!(
            method_unwrap_targets(&resp),
            vec!["blake3-512:abababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababab"],
            "manifest-pure identical repeated call under is_some guard must route to std option_unwrap: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_routes_manifest_pure_free_call_with_ast_normalized_whitespace() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn guarded(line: &str) -> &str {
    if pure_fn(line).is_some() {
        pure_fn( line ).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_ast_normalized_whitespace",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_eq!(
            method_unwrap_targets(&resp),
            vec!["blake3-512:abababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababab"],
            "manifest-pure repeated call matching must normalize AST whitespace without semantic equivalence: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_without_guard() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn unguarded(line: &str) -> &str {
    pure_fn(line).unwrap()
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_unguarded",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "manifest-pure free call must not route without a dominating is_some guard: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_from_disjunction() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn disjunction(line: &str, flag: bool) -> &str {
    if flag || pure_fn(line).is_some() {
        pure_fn(line).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_disjunction",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "manifest-pure free call under || must not route because disjunction does not dominate the unwrap: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_with_different_arg() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn different_arg(left: &str, right: &str) -> &str {
    if pure_fn(left).is_some() {
        pure_fn(right).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_different_arg",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "guarded pure free call must require exact syntactic arg equality: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_with_different_function() {
        let src = r##"
pub fn pure_fn_a(_line: &str) -> Option<&str> {
    panic!()
}

pub fn pure_fn_b(_line: &str) -> Option<&str> {
    panic!()
}

pub fn different_function(line: &str) -> &str {
    if pure_fn_a(line).is_some() {
        pure_fn_b(line).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_different_function",
            src,
            Some(free_pure_option_manifest("pure_fn_a")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "guarded pure free call must require the same callee as the guard: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_after_mutation() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn mutated(mut line: &str, replacement: &str) -> &str {
    if pure_fn(line).is_some() {
        line = replacement;
        pure_fn(line).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_after_mutation",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "guarded pure free call must refuse when a receiver arg root mutates between guard and unwrap: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_after_compound_assignment() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn mutated(mut idx: usize, lines: &[&str]) -> &str {
    if pure_fn(lines[idx]).is_some() {
        idx += 1;
        pure_fn(lines[idx]).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_after_compound_assignment",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "guarded pure free call must refuse when a receiver arg root is compound-assigned between guard and unwrap: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_routes_manifest_pure_free_call_after_len_read() {
        let src = r##"
pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn guarded(lines: &[&str], idx: usize) -> &str {
    if pure_fn(lines[idx]).is_some() {
        let _line_count = lines.len();
        pure_fn(lines[idx]).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_after_len_read",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert_eq!(
            method_unwrap_targets(&resp),
            vec!["blake3-512:abababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababab"],
            "whitelisted shared-read methods like len must not invalidate the guarded pure-free fact: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_after_unknown_method_on_arg_root() {
        let src = r##"
pub struct Slot(String);

impl Slot {
    pub fn touch(&self) {}
}

pub fn pure_fn(_slot: &Slot) -> Option<&str> {
    panic!()
}

pub fn guarded(slot: Slot) -> &str {
    if pure_fn(&slot).is_some() {
        slot.touch();
        pure_fn(&slot).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_after_unknown_method",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "unknown methods on a guarded arg root must invalidate the pure-free fact by default: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_after_mut_borrow() {
        let src = r##"
pub fn take_mut(_line: &mut &str) {}

pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn guarded(mut line: &str) -> &str {
    if pure_fn(line).is_some() {
        take_mut(&mut line);
        pure_fn(line).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_after_mut_borrow",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "mutable borrows of a guarded arg root must invalidate the pure-free fact: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_when_condition_mutates_arg() {
        let src = r##"
pub fn take_mut(_line: &mut &str) -> bool {
    true
}

pub fn pure_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn condition_mutates(mut line: &str) -> &str {
    if pure_fn(line).is_some() && take_mut(&mut line) {
        pure_fn(line).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_condition_mutates_arg",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "mutating a guarded arg inside the same if condition must not leave a stale pure-free route: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_with_non_stable_arg_expression() {
        let src = r##"
pub fn pure_fn(_line: Option<&str>) -> Option<&str> {
    panic!()
}

pub fn non_stable_arg(mut iter: std::vec::IntoIter<&str>) -> &str {
    if pure_fn(iter.next()).is_some() {
        pure_fn(iter.next()).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_non_stable_arg",
            src,
            Some(free_pure_option_manifest("pure_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "guarded pure free call must refuse when the identical arg expression can evaluate differently: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_unregistered_free_call_guarded_unwrap() {
        let src = r##"
pub fn random_fn(_line: &str) -> Option<&str> {
    panic!()
}

pub fn unregistered(line: &str) -> &str {
    if random_fn(line).is_some() {
        random_fn(line).unwrap()
    } else {
        ""
    }
}
"##;

        let resp =
            lift_implications_for_free_pure_fixture("free_pure_guard_unregistered", src, None);

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "unregistered free function must not borrow manifest-pure routing: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_refuses_manifest_pure_free_call_without_local_function_definition() {
        let src = r##"
pub fn missing_definition(line: &str) -> &str {
    if missing_fn(line).is_some() {
        missing_fn(line).unwrap()
    } else {
        ""
    }
}
"##;

        let resp = lift_implications_for_free_pure_fixture(
            "free_pure_guard_missing_definition",
            src,
            Some(free_pure_option_manifest("missing_fn")),
        );

        assert!(
            method_unwrap_targets(&resp).is_empty(),
            "manifest-pure routing must require the free function to resolve in the lifted crate: {resp:#?}"
        );
    }

    #[test]
    fn lift_implications_disambiguates_blessed_match_bindings_from_manifest() {
        let src = r##"
pub enum Dialect {
    Rust,
}

pub enum Sort {
    Primitive,
    Function,
}

pub enum Term {
    Unit,
}

pub enum Input {
    Source { dialect: Dialect, bytes: Vec<u8> },
    Term(Term),
}

pub fn caller(input: &Input) {
    match input {
        Input::Source { dialect, bytes: _ } => {
            serde_json::to_value(dialect).unwrap();
        }
        Input::Term(term) => {
            serde_json::to_value(term).unwrap();
        }
    }
}

pub fn sort_name(sort: &Sort) {
    match sort {
        Sort::Primitive => {}
        other => {
            serde_json::to_string(other).unwrap();
        }
    }
}
"##;
        let root = temp_workspace("lift_implications_infallible_match_bindings");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_infallible_serialize_manifest(
            &root,
            r#"
[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "Dialect"
contract = "serde_json_to_value__dialect"
reason = "derive Serialize over serde_json-infallible fields"

[[serde_json]]
function = "to_string"
type_crate = "consumer_crate"
type_name = "Sort"
contract = "serde_json_to_string__sort"
reason = "derive Serialize over serde_json-infallible fields"

[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "Term"
contract = "serde_json_to_value__term"
reason = "derive Serialize over serde_json-infallible fields"
"#,
        );

        let dialect_cid = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let term_cid = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
        let sort_cid = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "serde_json_to_value__dialect",
                    "library": "consumer_crate",
                    "contract_cid": dialect_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                },
                {
                    "name": "serde_json_to_string__sort",
                    "library": "consumer_crate",
                    "contract_cid": sort_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                },
                {
                    "name": "serde_json_to_value__term",
                    "library": "consumer_crate",
                    "contract_cid": term_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                }
            ],
        }))
        .expect("lift_implications");

        let to_value_targets: Vec<&str> = resp["ir"]
            .as_array()
            .expect("ir array")
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "to_value")
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect();
        assert_eq!(to_value_targets, vec![dialect_cid, term_cid]);
        let to_string_targets: Vec<&str> = resp["ir"]
            .as_array()
            .expect("ir array")
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "to_string")
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect();
        assert_eq!(to_string_targets, vec![sort_cid]);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn infallible_serialize_manifest_matches_external_type_but_emits_current_crate_contract() {
        let src = r##"
use dep_crate::Sort;

pub fn sort_name(sort: &Sort) {
    match sort {
        other => {
            serde_json::to_string(other).unwrap();
        }
    }
}
"##;
        let root = temp_workspace("infallible_serialize_external_type");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_infallible_serialize_manifest(
            &root,
            r#"
[[serde_json]]
function = "to_string"
type_crate = "dep_crate"
type_name = "Sort"
contract = "serde_json_to_string__dep_sort"
reason = "project-local totality axiom for dependency Sort serialization"
"#,
        );

        let producer = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel]
        }))
        .expect("function contract lift accepts external type match identity");
        let entries = producer["ir"].as_array().expect("producer ir array");
        let contract = entries
            .iter()
            .find(|entry| entry["name"] == "serde_json_to_string__dep_sort")
            .expect("synthetic external-type totality contract");
        assert_eq!(contract["library"], "consumer_crate");
        assert_eq!(contract["bodyDischargeEligible"], false);
        assert_eq!(contract["bodyDischargeRefusalReason"], "totality-axiom");

        let sort_cid = "blake3-512:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
        let consumer = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "serde_json_to_string__dep_sort",
                    "library": "consumer_crate",
                    "contract_cid": sort_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                }
            ],
        }))
        .expect("lift implications");
        let bridge = consumer["ir"]
            .as_array()
            .expect("consumer ir array")
            .iter()
            .find(|entry| entry["sourceSymbol"] == "to_string")
            .expect("serde_json::to_string bridge for external type identity");
        assert_eq!(bridge["targetContractCid"], sort_cid);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_routes_external_to_value_expect_for_line_broken_receiver() {
        let src = r##"
use dep_crate::{IrFormula, IrTerm};

pub fn formula_to_canonical(f: &IrFormula, g: &IrTerm) {
    let serde =
        serde_json::to_value(f).expect("IrFormula serializes");
    serde_json::to_value(g).expect("wrong arg type");
    serde_json::to_string(f).expect("wrong serde function");
    let through_var = serde_json::to_value(f);
    through_var.expect("non-immediate receiver");
    drop(serde);
}
"##;
        let root = temp_workspace("lift_implications_external_to_value_expect");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_infallible_serialize_manifest(
            &root,
            r#"
[[serde_json]]
function = "to_value"
type_crate = "dep_crate"
type_name = "IrFormula"
contract = "serde_json_to_value__ir_formula"
reason = "project-local totality axiom for dependency IrFormula serialization"
"#,
        );

        let producer_cid = "blake3-512:abababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababab";
        let result_expect_cid = "blake3-512:babababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababababa";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "serde_json_to_value__ir_formula",
                    "library": "consumer_crate",
                    "contract_cid": producer_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                },
                {
                    "name": "result_expect@std/src/result.rs:2:1",
                    "library": "std",
                    "contract_cid": result_expect_cid,
                    "body_bearing": true,
                    "has_pre": true
                }
            ],
        }))
        .expect("lift implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let producer_hits: Vec<&Value> = ir
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "to_value")
            .filter(|entry| entry["targetContractCid"] == producer_cid)
            .collect();
        assert_eq!(
            producer_hits.len(),
            2,
            "both direct serde_json::to_value(f) producer calls should bridge to the external IrFormula totality contract; wrong arg type and wrong serde function must not: {resp:#?}"
        );
        let panic_targets: Vec<&str> = ir
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "method:expect")
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect();
        assert_eq!(
            panic_targets,
            vec![result_expect_cid],
            "only the immediate serde_json::to_value(f).expect(...) receiver should route through Result::expect; wrong arg type, wrong serde function, and through-var receiver must not: {resp:#?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_disambiguates_explicit_local_json_value_to_string() {
        let src = r##"
use serde_json::{json, Value};

pub fn dispatch() {
    let req: Value = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.invoke",
    });
    serde_json::to_string(&req).expect("serialize request");
}
"##;
        let root = temp_workspace("lift_implications_explicit_local_json_value_to_string");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let value_cid = "blake3-512:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "serde_json_to_string_value",
                    "library": "serde_json",
                    "contract_cid": value_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                }
            ],
        }))
        .expect("lift implications");

        let bridge = resp["ir"]
            .as_array()
            .expect("consumer ir array")
            .iter()
            .find(|entry| entry["sourceSymbol"] == "to_string")
            .expect("serde_json::to_string bridge for explicit local Value");
        assert_eq!(bridge["targetContractCid"], value_cid);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_refuses_unregistered_concrete_and_generic_bound_manifest_hits() {
        let src = r##"
pub struct SerializableRecord;
pub struct Unregistered;

pub fn unregistered(value: &Unregistered) {
    serde_json::to_value(value).unwrap();
}

pub fn generic<T: serde::Serialize>(value: &T) {
    serde_json::to_value(value).unwrap();
}

pub fn wrong_method(value: &SerializableRecord) {
    value.to_string();
}
"##;
        let root = temp_workspace("lift_implications_infallible_refuse_floor");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");
        write_infallible_serialize_manifest(
            &root,
            r#"
[[serde_json]]
function = "to_value"
type_crate = "consumer_crate"
type_name = "SerializableRecord"
contract = "serde_json_to_value__serializable_record"
reason = "derive Serialize over serde_json-infallible fields"
"#,
        );

        let forbidden_cid = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                {
                    "name": "serde_json_to_value__serializable_record",
                    "library": "consumer_crate",
                    "contract_cid": forbidden_cid,
                    "bodyDischargeEligible": false,
                    "bodyDischargeRefusalReason": "totality-axiom"
                }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            !ir.iter()
                .any(|entry| entry["targetContractCid"] == forbidden_cid),
            "unregistered concrete and generic-bound receivers must not borrow the blessed type's totality contract: {ir:?}"
        );
        let gaps: Vec<&Value> = resp["diagnostics"]
            .as_array()
            .expect("diagnostics array")
            .iter()
            .filter(|entry| {
                entry["kind"] == "lift-gap"
                    && entry["reason"] == "no-contract-for-callee"
                    && entry["callee"] == "to_value"
            })
            .collect();
        assert_eq!(
            gaps.len(),
            2,
            "both refused to_value calls should stay as honest no-contract gaps: {gaps:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_resolves_annotated_method_receiver_to_type_crate() {
        let src = r##"
use dep_crate::Widget;

pub fn make_widget() -> Widget {
    panic!()
}

pub fn caller() {
    let widget: Widget = make_widget();
    widget.run();
}
"##;
        let root = temp_workspace("lift_implications_typed_receiver");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let current_run = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let dep_run = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let contract_bindings = json!([
            { "name": "make_widget@src/lib.rs:4:1",
              "library": "consumer_crate",
              "contract_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" },
            { "name": "run@src/lib.rs:10:5",
              "library": "consumer_crate",
              "contract_cid": current_run },
            { "name": "run@dep/src/lib.rs:10:5",
              "library": "dep_crate",
              "contract_cid": dep_run },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        // Method call `widget.run()` -> sourceSymbol = `method:run` (the lifted
        // ctor name); target still resolves on the bare leaf to the dep crate.
        let run = ir
            .iter()
            .find(|entry| entry["sourceSymbol"] == "method:run")
            .expect("method:run bridge");
        assert_eq!(run["targetContractCid"], dep_run);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_resolves_inferred_method_receivers_to_type_crate() {
        let src = r##"
use dep_crate::Widget;

pub fn make_widget() -> Widget {
    panic!()
}

pub fn caller() {
    let from_return = make_widget();
    from_return.run();

    let from_ctor = Widget::new();
    from_ctor.run();
}
"##;
        let root = temp_workspace("lift_implications_inferred_receiver");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let current_run = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let dep_run = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let contract_bindings = json!([
            { "name": "make_widget@src/lib.rs:4:1",
              "library": "consumer_crate",
              "contract_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" },
            { "name": "new@dep/src/lib.rs:3:1",
              "library": "dep_crate",
              "contract_cid": "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" },
            { "name": "run@src/lib.rs:10:5",
              "library": "consumer_crate",
              "contract_cid": current_run },
            { "name": "run@dep/src/lib.rs:10:5",
              "library": "dep_crate",
              "contract_cid": dep_run },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        // Both are method calls (`from_return.run()`, `from_ctor.run()`) ->
        // sourceSymbol = `method:run`; targets resolve on the bare leaf.
        let run_targets: Vec<&str> = ir
            .iter()
            .filter(|entry| entry["sourceSymbol"] == "method:run")
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect();
        assert_eq!(run_targets, vec![dep_run, dep_run]);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_disambiguates_prelude_option_result_panic_partials() {
        let src = r##"
pub fn option_case<T>(opt: Option<T>) -> T {
    opt.unwrap()
}

pub fn result_case<T, E: std::fmt::Debug>(result: Result<T, E>, msg: &str) -> T {
    if result.is_ok() {
        result.expect(msg)
    } else {
        result.unwrap()
    }
}

pub fn option_expect_case<T>(opt: Option<T>, msg: &str) -> T {
    opt.expect(msg)
}
"##;
        let root = temp_workspace("lift_implications_prelude_panic_partials");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let option_unwrap_no_pre =
            "blake3-512:111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
        let result_unwrap_no_pre =
            "blake3-512:222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222";
        let result_expect_no_pre =
            "blake3-512:333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333";
        let option_expect_no_pre =
            "blake3-512:444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444";
        let option_unwrap =
            "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let result_unwrap =
            "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let result_expect =
            "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
        let option_expect =
            "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        let contract_bindings = json!([
            { "name": "option_unwrap@std/src/option.rs:1:1",
              "library": "std",
              "contract_cid": option_unwrap_no_pre,
              "body_bearing": true,
              "has_pre": false },
            { "name": "option_unwrap@std/src/option.rs:2:1",
              "library": "std",
              "contract_cid": option_unwrap,
              "body_bearing": true,
              "has_pre": true },
            { "name": "result_unwrap@std/src/result.rs:1:1",
              "library": "std",
              "contract_cid": result_unwrap_no_pre,
              "body_bearing": true,
              "has_pre": false },
            { "name": "result_unwrap@std/src/result.rs:2:1",
              "library": "std",
              "contract_cid": result_unwrap,
              "body_bearing": true,
              "has_pre": true },
            { "name": "result_expect@std/src/result.rs:1:1",
              "library": "std",
              "contract_cid": result_expect_no_pre,
              "body_bearing": true,
              "has_pre": false },
            { "name": "result_expect@std/src/result.rs:2:1",
              "library": "std",
              "contract_cid": result_expect,
              "body_bearing": true,
              "has_pre": true },
            { "name": "option_expect@std/src/option.rs:1:1",
              "library": "std",
              "contract_cid": option_expect_no_pre,
              "body_bearing": true,
              "has_pre": false },
            { "name": "option_expect@std/src/option.rs:2:1",
              "library": "std",
              "contract_cid": option_expect,
              "body_bearing": true,
              "has_pre": true },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let panic_targets: Vec<&str> = ir
            .iter()
            .filter(|entry| {
                entry["sourceSymbol"] == "method:unwrap" || entry["sourceSymbol"] == "method:expect"
            })
            .filter_map(|entry| entry["targetContractCid"].as_str())
            .collect();
        assert_eq!(
            panic_targets,
            vec![option_unwrap, result_expect, result_unwrap, option_expect],
            "prelude Option/Result panic leaves must bridge to the std partials, not refuse or pick the current crate: {ir:?}"
        );
        assert!(
            resp["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .all(|diagnostic| diagnostic["reason"] != "panic-site-unproven"),
            "prelude Option/Result panic leaves should not emit panic-site-unproven: {:#?}",
            resp["diagnostics"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_refuses_prelude_panic_partial_without_pre_bearing_contract() {
        let src = r##"
pub fn option_case<T>(opt: Option<T>) -> T {
    opt.unwrap()
}
"##;
        let root = temp_workspace("lift_implications_panic_partial_requires_pre");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let no_pre =
            "blake3-512:111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
        let contract_bindings = json!([
            { "name": "option_unwrap@std/src/option.rs:1:1",
              "library": "std",
              "contract_cid": no_pre,
              "body_bearing": true,
              "pre": { "kind": "atomic", "name": "true", "args": [] } },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            !ir.iter()
                .any(|entry| entry["sourceSymbol"] == "method:unwrap"),
            "panic partials must refuse rather than bridge to a no-pre duplicate: {ir:?}"
        );
        assert!(
            resp["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .any(|diagnostic| diagnostic["reason"] == "panic-site-unproven"),
            "no-pre panic partial should stay as an honest panic-site-unproven gap: {:#?}",
            resp["diagnostics"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_refuses_prelude_panic_partial_with_only_ineligible_totality() {
        let src = r##"
pub fn option_case<T>(opt: Option<T>) -> T {
    opt.unwrap()
}
"##;
        let root = temp_workspace("lift_implications_panic_partial_refuses_ineligible_totality");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let ineligible =
            "blake3-512:222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222";
        let contract_bindings = json!([
            { "name": "option_unwrap@std/src/option.rs:1:1",
              "library": "std",
              "contract_cid": ineligible,
              "bodyDischargeEligible": false,
              "bodyDischargeRefusalReason": "totality-axiom" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            !ir.iter()
                .any(|entry| entry["sourceSymbol"] == "method:unwrap"),
            "panic partials must not fall through to ineligible totality bindings: {ir:?}"
        );
        assert!(
            resp["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .any(|diagnostic| diagnostic["reason"] == "panic-site-unproven"),
            "ineligible totality-only panic partial should stay as an honest panic-site-unproven gap: {:#?}",
            resp["diagnostics"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_refuses_local_option_shadow_as_std_panic_partial() {
        let src = r##"
mod local {
    pub struct Option<T>(pub T);

    impl<T> Option<T> {
        pub fn unwrap(self) -> T {
            self.0
        }
    }
}

pub fn local_case<T>(opt: local::Option<T>) -> T {
    opt.unwrap()
}
"##;
        let root = temp_workspace("lift_implications_local_option_shadow");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            { "name": "option_unwrap@std/src/option.rs:1:1",
              "library": "std",
              "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            !ir.iter()
                .any(|entry| entry["sourceSymbol"] == "method:unwrap"),
            "local Option shadow must not bridge to std option_unwrap: {ir:?}"
        );
        assert!(
            resp["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .any(|diagnostic| diagnostic["reason"] == "panic-site-unproven"),
            "local Option shadow should refuse as an unresolved panic site: {:#?}",
            resp["diagnostics"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_refuses_generic_trait_receiver_as_std_panic_partial() {
        let src = r##"
pub trait MaybeUnwrap {
    type Output;
    fn unwrap(self) -> Self::Output;
}

pub fn generic_case<T: MaybeUnwrap>(value: T) -> T::Output {
    value.unwrap()
}
"##;
        let root = temp_workspace("lift_implications_generic_trait_unwrap");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            { "name": "option_unwrap@std/src/option.rs:1:1",
              "library": "std",
              "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            !ir.iter()
                .any(|entry| entry["sourceSymbol"] == "method:unwrap"),
            "generic trait unwrap must not bridge to std option_unwrap: {ir:?}"
        );
        assert!(
            resp["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .any(|diagnostic| diagnostic["reason"] == "panic-site-unproven"),
            "generic trait unwrap should refuse as unresolved: {:#?}",
            resp["diagnostics"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_refuses_option_type_alias_without_canonical_type_resolution() {
        let src = r##"
type MyOption<T> = std::option::Option<T>;

pub fn alias_case<T>(opt: MyOption<T>) -> T {
    opt.unwrap()
}
"##;
        let root = temp_workspace("lift_implications_option_alias_refuse");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(
            root.join("Cargo.toml"),
            r#"
[package]
name = "consumer-crate"
version = "0.1.0"
edition = "2021"
"#,
        )
        .expect("write Cargo.toml");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            { "name": "option_unwrap@std/src/option.rs:1:1",
              "library": "std",
              "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            !ir.iter().any(|entry| entry["sourceSymbol"] == "method:unwrap"),
            "type aliases are refused in this syntactic prelude slice until canonical type resolution is available: {ir:?}"
        );
        assert!(
            resp["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .any(|diagnostic| diagnostic["reason"] == "panic-site-unproven"),
            "type alias should refuse rather than guessing std Option: {:#?}",
            resp["diagnostics"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_scans_src_when_source_path_is_project_root() {
        let src = r##"
pub fn caller(input: &str) -> i64 {
    parse_input(input)
}
"##;
        let root = temp_workspace("lift_implications_project_root");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(src_dir.join("lib.rs"), src).expect("write source");

        let contract_bindings = json!([
            { "name": "parse_input@src/lib.rs:5:8",
              "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            ir.iter()
                .any(|entry| entry["sourceSymbol"] == "parse_input"),
            "mint sends source_paths=[\".\"], so implication lift must scan src/: {ir:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rpc_dispatches_sugar_plugin_lift_implications_method() {
        let src = r##"
pub fn caller(input: &str) -> i64 {
    parse_input(input)
}
"##;
        let root = temp_workspace("lift_implications_rpc_method");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(src_dir.join("lib.rs"), src).expect("write source");

        let response = handle_line(&json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "sugar.plugin.lift_implications",
            "params": {
                "workspace_root": root.to_string_lossy(),
                "source_paths": ["."],
                "contract_bindings": [{
                    "name": "parse_input@src/lib.rs:5:8",
                    "contract_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                }],
            }
        }).to_string());

        assert!(
            response.get("error").is_none(),
            "RPC method table must expose sugar.plugin.lift_implications: {response}"
        );
        let ir = response["result"]["ir"].as_array().expect("ir array");
        assert!(
            ir.iter()
                .any(|entry| entry["sourceSymbol"] == "parse_input"),
            "RPC implication route should return bridge IR: {response}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_lift_gap_for_unmatched_callee() {
        let src = r##"
pub fn caller() -> i64 {
    completely_unknown_function(0)
}
"##;
        let root = temp_workspace("lift_implications_gap");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(ir.is_empty(), "no bridges should be emitted: {ir:?}");
        let diags = resp["diagnostics"].as_array().expect("diagnostics array");
        assert_eq!(
            diags.len(),
            1,
            "one lift-gap for the unmatched call: {diags:?}"
        );
        assert_eq!(diags[0]["kind"], "lift-gap");
        assert_eq!(diags[0]["reason"], "no-contract-for-callee");
        assert_eq!(diags[0]["callee"], "completely_unknown_function");
        assert!(resp["oracle_requested"].is_boolean());
        assert_eq!(resp["oracle_reachable"], false);
        assert_eq!(resp["oracle_ready"], false);
        assert_eq!(resp["receivers_attempted"], 0);
        assert_eq!(resp["receivers_resolved"], 0);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_lift_gap_for_macro_callsites() {
        let src = r##"
pub fn caller() {
    println!("hello");
}
"##;
        let root = temp_workspace("lift_implications_macro_gap");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            ir.is_empty(),
            "macro calls should not mint guessed bridges: {ir:?}"
        );
        let diags = resp["diagnostics"].as_array().expect("diagnostics array");
        assert_eq!(diags.len(), 1, "one lift-gap for the macro call: {diags:?}");
        assert_eq!(diags[0]["kind"], "lift-gap");
        assert_eq!(diags[0]["reason"], "unsupported-macro-callsite");
        assert_eq!(diags[0]["callee"], "println!");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_lift_gap_for_closure_invocations() {
        let src = r##"
pub fn caller() -> i64 {
    (|x: i64| x + 1)(41)
}
"##;
        let root = temp_workspace("lift_implications_closure_gap");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            ir.is_empty(),
            "closure invocations should not mint guessed bridges: {ir:?}"
        );
        let diags = resp["diagnostics"].as_array().expect("diagnostics array");
        assert_eq!(
            diags.len(),
            1,
            "one lift-gap for the closure invocation: {diags:?}"
        );
        assert_eq!(diags[0]["kind"], "lift-gap");
        assert_eq!(diags[0]["reason"], "unsupported-closure-invocation");
        assert_eq!(diags[0]["callee"], "<closure>");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_emits_lift_gap_for_dynamic_callee_invocations() {
        let src = r##"
pub fn caller() -> i64 {
    (if true { add_one } else { add_two })(41)
}
"##;
        let root = temp_workspace("lift_implications_dynamic_callee_gap");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert!(
            ir.is_empty(),
            "dynamic callees should not mint guessed bridges: {ir:?}"
        );
        let diags = resp["diagnostics"].as_array().expect("diagnostics array");
        assert_eq!(
            diags.len(),
            1,
            "one lift-gap for the dynamic callee invocation: {diags:?}"
        );
        assert_eq!(diags[0]["kind"], "lift-gap");
        assert_eq!(diags[0]["reason"], "unsupported-dynamic-callee");
        assert_eq!(diags[0]["callee"], "<dynamic>");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_uses_last_path_segment_as_callee_name() {
        // `serde_json::from_str(s)` lowers to a callsite with
        // sourceSymbol = "from_str" (the LAST segment), which matches
        // how the test lifter names contracts: `from_str@...`.
        let src = r##"
pub fn caller(s: &str) -> serde_json::Value {
    serde_json::from_str(s).unwrap()
}
"##;
        let root = temp_workspace("lift_implications_path");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let contract_bindings = json!([
            { "name": "from_str@src/foreign.rs:42:8",
              "library": "serde_json",
              "contract_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" },
            { "name": "unwrap@somewhere.rs:1:1",
              "contract_cid": "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" },
        ]);

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": contract_bindings,
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        let symbols: Vec<&str> = ir
            .iter()
            .filter_map(|e| e["sourceSymbol"].as_str())
            .collect();
        // Free function call `serde_json::from_str(s)` -> bare last segment as
        // sourceSymbol (this is what this test pins: last-path-segment naming).
        assert!(
            symbols.contains(&"from_str"),
            "expected from_str (last path segment, free call) in: {symbols:?}"
        );
        // The trailing `.unwrap()` is a method call AND a PANIC leaf. With the
        // oracle off (no receiver-type disambiguation) the panic refuse-floor
        // refuses to bridge it -- bridging the bare `(std, unwrap)` shell would
        // vacuous-pass a "cannot panic" claim. So NO unwrap bridge is emitted,
        // under either the bare key or the `method:` key. (Pre-existing: this
        // refusal predates the method: seam; the seam only governs the
        // sourceSymbol of bridges that ARE emitted, e.g. a non-panic method
        // call -> `method:<leaf>`.)
        assert!(
            !symbols.iter().any(|s| *s == "unwrap" || *s == "method:unwrap"),
            "the panic-leaf unwrap must NOT bridge without disambiguation (refuse-floor): {symbols:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_uses_generic_args_for_target_contract_key() {
        let src = r##"
pub fn caller(x: i64) -> i64 {
    identity::<i64>(x)
}
"##;
        let root = temp_workspace("lift_implications_generic_key");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        let rel = "src/lib.rs";
        fs::write(root.join(rel), src).expect("write source");

        let expected_cid = "blake3-512:111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
        let wrong_cid = "blake3-512:222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222";
        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": [rel],
            "contract_bindings": [
                { "name": "identity::<String>@src/lib.rs:10:4", "contract_cid": wrong_cid },
                { "name": "identity::<i64>@src/lib.rs:20:4", "contract_cid": expected_cid }
            ],
        }))
        .expect("lift_implications");

        let ir = resp["ir"].as_array().expect("ir array");
        assert_eq!(ir.len(), 1, "generic call should emit one bridge: {ir:?}");
        assert_eq!(
            ir[0]["sourceSymbol"], "identity",
            "sourceSymbol must stay the bare ctor name lifted from the caller body"
        );
        assert_eq!(
            ir[0]["targetContractCid"], expected_cid,
            "target selection must use the concrete generic argument key"
        );
        let diags = resp["diagnostics"].as_array().expect("diagnostics array");
        assert!(
            diags.is_empty(),
            "matched generic call should not gap: {diags:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn lift_implications_treats_discharge_policy_refused_binding_as_ineligible() {
        let src = r##"
pub fn blocked(x: i64) -> i64 {
    x
}

pub fn caller(x: i64) -> i64 {
    blocked(x)
}
"##;
        let root = temp_workspace("lift_implications_discharge_policy_refused");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        fs::write(src_dir.join("lib.rs"), src).expect("write source");
        let target_cid = "blake3-512:111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";

        let resp = lift_implications(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
            "contract_bindings": [{
                "name": "blocked",
                "contract_cid": target_cid,
                "dischargePolicy": {
                    "bodyReduction": {
                        "status": "refused",
                        "reason": "totality-axiom"
                    }
                }
            }]
        }))
        .expect("lift implications");

        let diagnostics = resp["diagnostics"].as_array().expect("diagnostics array");
        assert!(
            diagnostics.iter().any(|diag| {
                diag["kind"] == "lift-note"
                    && diag["reason"] == "body-discharge-ineligible-bridged"
                    && diag["detail"] == "totality-axiom"
            }),
            "new dischargePolicy refused binding must be surfaced as ineligible: {diagnostics:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_marks_value_returning_contracts_reflexively_eligible() {
        // Post-#1696 reflexive policy: any function with a result equation
        // (`result == <body term>`) is body-discharge ELIGIBLE, because the
        // verifier encodes every term head (field projection, `Ok`/`Err`
        // ctors, calls, ...) as an uninterpreted function symbol and
        // discharges `f(x) == f(x)` by reflexivity. The ONLY ineligible
        // case is a genuinely unit-returning function: no result term, so
        // nothing to discharge. The old whitelist (arithmetic only) is
        // gone.
        let src = r##"
pub struct ExitReport {
    pub code: i64,
}

pub fn double(x: i64) -> i64 {
    x * 2
}

pub fn report_exit_code(report: ExitReport) -> i64 {
    report.code
}

pub fn wrap_ok(x: i64) -> Result<i64, ()> {
    Ok(x)
}

pub fn record_only(report: ExitReport) {
    let _ = report.code;
}
"##;
        let root = temp_workspace("function_contract_body_discharge_eligibility");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        write_cargo_package(&root, "function-contract-body-discharge-eligibility");
        fs::write(src_dir.join("lib.rs"), src).expect("write source");

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("function contract lift");

        let ir = resp["ir"].as_array().expect("ir array");
        let by_name = |name: &str| -> &Value {
            ir.iter()
                .find(|entry| entry["name"] == name)
                .unwrap_or_else(|| panic!("missing lifted function contract `{name}`: {ir:?}"))
        };

        assert_eq!(
            by_name("double")["bodyDischargeEligible"],
            true,
            "plain arithmetic body is reflexively eligible"
        );
        assert_eq!(
            by_name("report_exit_code")["bodyDischargeEligible"],
            true,
            "field projection is reflexively eligible: `field(report, .code) == field(report, .code)`"
        );
        assert_eq!(
            by_name("wrap_ok")["bodyDischargeEligible"],
            true,
            "Result::Ok construction is reflexively eligible: `Ok(x) == Ok(x)`"
        );
        assert_eq!(
            by_name("record_only")["bodyDischargeEligible"],
            false,
            "a genuinely unit-returning function has no result equation; it is honestly ineligible"
        );
        let diagnostics = resp["diagnostics"].as_array().expect("diagnostics array");
        assert!(
            diagnostics
                .iter()
                .any(|diag| diag["kind"] == "body-discharge-gap"
                    && diag["function"] == "record_only"),
            "the unit-returning ineligible contract must surface a precise kit diagnostic: {diagnostics:?}"
        );
        assert!(
            !diagnostics
                .iter()
                .any(|diag| diag["kind"] == "body-discharge-gap"
                    && (diag["function"] == "report_exit_code" || diag["function"] == "wrap_ok")),
            "value-returning contracts must NOT surface a body-discharge gap under the reflexive policy: {diagnostics:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn function_contract_lift_uses_explicit_result_string_signature_for_json_guards() {
        let src = r##"
use serde_json::json;

pub fn jcs_cid(value: &serde_json::Value) -> Result<String, String> {
    Ok(value.to_string())
}

pub fn mint(from: serde_json::Value) -> Result<String, String> {
    let from_catalog_cid = jcs_cid(&from)?;
    let body = json!({
        "fromCatalogCid": from_catalog_cid
    });
    let payload = json!({
        "fromCatalogCid": body["fromCatalogCid"].clone()
    });
    Ok(payload["fromCatalogCid"].as_str().unwrap().to_string())
}
"##;
        let root = temp_workspace("function_contract_json_guard_signature");
        let src_dir = root.join("src");
        fs::create_dir_all(&src_dir).expect("create src dir");
        write_cargo_package(&root, "function-contract-json-guard-signature");
        fs::write(src_dir.join("lib.rs"), src).expect("write source");

        let resp = function_contract_lift(&json!({
            "workspace_root": root.to_string_lossy(),
            "source_paths": ["."],
        }))
        .expect("function contract lift");

        let ir = resp["ir"].as_array().expect("ir array");
        let mint = ir
            .iter()
            .find(|entry| entry["name"] == "mint")
            .unwrap_or_else(|| panic!("missing mint contract: {ir:?}"));
        let post = serde_json::to_string(&mint["post"]).expect("post stringifies");
        assert!(
            post.contains("cf_guarded"),
            "explicit Result<String, _> signature must feed json guard facts: {post}"
        );
        assert!(
            post.contains("is_some"),
            "guard fact must prove as_str() is Some: {post}"
        );

        let _ = fs::remove_dir_all(root);
    }
}
