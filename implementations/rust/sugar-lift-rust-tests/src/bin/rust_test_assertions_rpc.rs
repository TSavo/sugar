// SPDX-License-Identifier: Apache-2.0
//
// RPC entrypoint for the Rust test-assertion consistency lifter.

use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use sugar_canonicalizer::{blake3_512_of, encode_jcs};
use sugar_ir_symbolic::serialize::{formula_to_value, marshal_declarations};
use sugar_lift_rust_tests::source_oracle;
use sugar_lift_rust_tests::{lift_file_with_options, FactoryAudit, LiftOptions, TargetCfg};
use sugar_verifier::types::{memento_body, memento_body_field, memento_kind};

const VERSION: &str = env!("CARGO_PKG_VERSION");
const SURFACE: &str = "rust-test-assertions";
const KIT_DECLARATION_RPC_METHOD: &str = "sugar.plugin.kit_declaration";
const RESOLVE_PROOF_BY_CID_RPC_METHOD: &str = "sugar.plugin.resolve_proof_by_cid";
const RESOLVE_SOURCE_MEMENTO_RPC_METHOD: &str = "sugar.plugin.resolve_source_memento";

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

fn lift(params: &Value) -> Value {
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
    let options = match lift_options_from_config(&workspace_root, params) {
        Ok(options) => options,
        Err(reason) => {
            diagnostics.push(json!({
                "kind": "lift-gap",
                "path": params
                    .get("config_path")
                    .and_then(Value::as_str)
                    .unwrap_or(".sugar/config.toml"),
                "item": "rust-test-assertions.target_cfg",
                "reason": reason,
            }));
            LiftOptions::default()
        }
    };
    for rel in &rel_paths {
        let abs = workspace_root.join(rel);
        let bytes = match std::fs::read(&abs) {
            Ok(bytes) => bytes,
            Err(e) => {
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": format!("read: {e}"),
                }));
                continue;
            }
        };
        let src = match std::str::from_utf8(&bytes) {
            Ok(src) => src,
            Err(_) => {
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": "non-utf8 source",
                }));
                continue;
            }
        };
        let file = match syn::parse_file(src) {
            Ok(file) => file,
            Err(e) => {
                diagnostics.push(json!({
                    "kind": "lift-gap",
                    "path": rel,
                    "reason": format!("parse: {e}"),
                }));
                continue;
            }
        };
        let out = lift_file_with_options(&file, rel, &options);
        let marshalled = marshal_declarations(&out.decls);
        let parsed: Value = serde_json::from_str(&marshalled).unwrap_or_else(|_| json!([]));
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
        // DENOMINATOR: the oracle enumerates every function in the file. Each one
        // gets a content-addressed memento and a classified locus, so the dark
        // (functions the kit does not speak) is COUNTED, not skipped.
        factory_audits.extend(factory_audits_json(rel, &out.factory_audits));
        let mut fns: Vec<FnRef> = Vec::new();
        collect_fns(&file.items, &mut fns);
        // Real warrants emit ProofIR: contracts the recursive body-walk produced,
        // marshalled into the IR alongside the test-assertion decls (below).
        let mut value_entries: Vec<Value> = Vec::new();
        // Oracle slice: unresolved method-call bodies queued for the RA daemon's
        // receiver/param-mutability verdict. (source_loci index, LSP positions).
        let mut oracle_pending: Vec<(usize, Vec<(u32, u32)>)> = Vec::new();
        for fr in fns {
            let memento =
                source_oracle::source_memento_of(rel, src, fr.span, &fr.name, fr.sig, fr.block);
            let name = fr.name.clone();
            let is_test = fn_has_test_attr(fr.attrs);
            let warning = out
                .warnings
                .iter()
                .find(|w| w.item_name == name || w.item_name.ends_with(&format!("::{name}")));
            // TOTAL classifier. Every function exits into exactly one status by
            // RESOLVING (build Sugar + desugar), NEVER by scanning. `refused` is
            // IMPOSSIBLE here by design: the walk never DECLINES (that is the sin), and
            // the only "no" is an UNSAT certificate (`refuted`) minted at the body<->pin
            // seam where the analysis lives. A body that does not resolve to a value
            // falls through to `unresolved` -- the HONEST dark, "we don't have a Sugar
            // for that yet", the residual the campaign drives to 0 by real classification
            // work. (Laundering the dark into a verdict it never earned -- forcing the
            // catch-all so `unresolved=0` looks done -- is the FAKE ZERO; the honest
            // move is the opposite: let the dark be visible.)
            let (status, reason): (&str, Option<String>) = if is_test {
                match warning {
                    // NEW DOCTRINE: the lifter COULDN'T LIFT this vendor assertion
                    // (unsupported assert / no liftable scalar / ambiguous cfg) ->
                    // there is no usable pin to check, so it is UNRESOLVED, not refused.
                    // `refused` is reserved for an UNSAT certificate -- a vendor
                    // assertion we DID lift that contradicts (itself or the body).
                    // A can't-lift is a coverage gap (named in the reason), never a
                    // contradiction verdict.
                    Some(w) => (
                        "unresolved",
                        Some(format!("vendor pin not liftable: {}", w.reason)),
                    ),
                    None => ("warranted", None),
                }
            } else {
                // NON-TEST body: ONE decision point (`classify_nontest_fn`) so the law
                // "`refused` is impossible" is enforced and tested in one place. The walk
                // never DECLINES: a body is `support` (inlined universe member),
                // `warranted` (constrains -> decl flows into the IR), or falls through to
                // the honest "we don't have a Sugar for that yet" -- never a `refused`
                // verdict it didn't earn.
                let (s, r, entry) = classify_nontest_fn(
                    &name,
                    fr.sig,
                    fr.block,
                    out.reduced_helpers.contains(&name),
                    &memento.to_json(),
                );
                if let Some(entry) = entry {
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
            if status == "unresolved" {
                let positions = method_call_positions(fr.block);
                if !positions.is_empty() {
                    oracle_pending.push((source_loci.len(), positions));
                }
            }
            source_loci.push(locus);
            source_mementos.push(memento.to_json());
        }
        // Flow the emitted value-fn contracts into the IR document, so a
        // `warranted` source locus is backed by a real relation in `ir`.
        entries.extend(value_entries);
        entries.extend(assertion_entries);
        // Oracle slice: ask the resident RA daemon (sugar-linkerd) to resolve the
        // receiver/param mutability of each queued method-call position. A method
        // call that is `&mut self` / takes a `&mut` param is the provable
        // "mutation through &mut" effect -> SHARPEN the unresolved locus's reason. An
        // unreachable/cold daemon yields no resolutions -> every body stays
        // unresolved (the conservative refuse-floor); the oracle never warrants
        // here (RefClean does not rule out IO/panic the signature can't show).
        oracle_reclassify_mutating(&workspace_root, rel, &oracle_pending, &mut source_loci);
    }

    let ledger = source_ledger(&source_loci);
    let vendor_conjoins = vendor_conjoins_for_report(&workspace_root, &entries);
    json!({
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
        // Content-addressed mementos (file + span + BLAKE3-512 of body/template,
        // never source text) -- one per enumerated function, recompute-verifiable.
        "sourceMementos": source_mementos,
        "vendorConjoins": vendor_conjoins,
    })
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
    use syn::spanned::Spanned;
    for item in items {
        match item {
            syn::Item::Fn(f) => out.push(FnRef {
                span: f.span(),
                name: f.sig.ident.to_string(),
                sig: &f.sig,
                block: &f.block,
                attrs: &f.attrs,
            }),
            syn::Item::Mod(m) => {
                if let Some((_, inner)) = &m.content {
                    collect_fns(inner, out);
                }
            }
            syn::Item::Impl(im) => {
                let self_ty = impl_audit_self_ty_key(&im.self_ty);
                for ii in &im.items {
                    if let syn::ImplItem::Fn(m) = ii {
                        let name = self_ty
                            .as_ref()
                            .map(|ty| format!("{ty}::{}", m.sig.ident))
                            .unwrap_or_else(|| m.sig.ident.to_string());
                        out.push(FnRef {
                            span: m.span(),
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
                                span: m.span(),
                                name: format!("{}::{}", tr.ident, m.sig.ident),
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

/// Classify a NON-test fn body into its source-ledger status -- the SINGLE decision
/// point, so the design law "`refused` is impossible" lives (and is tested) in ONE
/// place. A body is `support` (the reducer inlined it as a universe member),
/// `warranted` (it constrains -> the returned decl flows into the IR), or it falls
/// through to the honest "we don't have a Sugar for that yet". Returns
/// `(status, reason, decl)`; the caller pushes `decl` into the IR document.
fn classify_nontest_fn(
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
    reduced: bool,
    source_memento: &Value,
) -> (&'static str, Option<String>, Option<Value>) {
    let is_method_contract = name.contains("::");
    if reduced && !is_method_contract {
        // A non-test fn the reducer INLINED to discharge a test (a bare-statement R7
        // inline, an arg-position inline, OR -- capability #1 -- a TERM-POSITION
        // value-call peel that grounded `h(2)` to `+(2,1)`). It backs a warrant as a
        // UNIVERSE member, so it is `support`. CHECKED BEFORE `broad_functional_warrant`
        // (which returns Some for ANY value-returning body): a fully-inlined value
        // helper must NOT also be minted as its OWN standalone `out=call:h` contract --
        // that re-introduces the opaque `call:h` symbol the peel just killed.
        return ("support", None, None);
    }
    if let Some(decl) = sugar_lift_rust_tests::broad_functional_warrant(name, sig, block) {
        // We THINK it constrains -> WARRANT it, broadly. The decl flows into the IR;
        // the universe is built from these demands. The vendor is the referee.
        let entry = function_contract_entry_from_decl(name, sig, &decl, source_memento);
        return ("warranted", None, Some(entry));
    }
    if reduced {
        // A consumed method with no output has no contract to emit, but it was still
        // part of the resolved universe. Keep that support-only. Value-returning
        // methods take the branch above and own their semantics as contracts.
        return ("support", None, None);
    }
    // NO WARRANT, NO INLINE -- and we do NOT SCAN. Declining is the sin, and a
    // syntactic scan for effects is the same sin in disguise: it can't tell
    // `[1..5].iter().next()` -> `1` from a real side effect (only RESOLVING the term
    // can). A side effect surfaces ONLY at term resolution, as a `Hit`, when the body
    // is actually reduced -- never from a pre-scan here. So: we have no Sugar that
    // resolves this body's value to a literal yet, and it falls through to UNRESOLVED
    // -- "we don't have a Sugar for that yet" = honest, visible work the campaign
    // drives to 0. `refused` is reserved for named source/effect boundaries and UNSAT
    // certificates, never for a static decline.
    (
        "unresolved",
        Some("no Sugar resolves this body's value to a literal yet (no value pin)".to_string()),
        None,
    )
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

/// LSP-coordinate positions (0-based line, 0-based col) of every method-call
/// ident in a body -- the positions the RA oracle resolves to receiver/param
/// mutability. proc-macro2 spans are 1-based line / 0-based column, so the line
/// is decremented to LSP space.
#[derive(Default)]
struct MethodCallPositions(Vec<(u32, u32)>);

impl<'ast> syn::visit::Visit<'ast> for MethodCallPositions {
    fn visit_expr_method_call(&mut self, n: &'ast syn::ExprMethodCall) {
        let s = n.method.span().start();
        if s.line >= 1 {
            self.0.push(((s.line - 1) as u32, s.column as u32));
        }
        syn::visit::visit_expr_method_call(self, n);
    }
}

fn method_call_positions(block: &syn::Block) -> Vec<(u32, u32)> {
    let mut v = MethodCallPositions::default();
    syn::visit::Visit::visit_block(&mut v, block);
    v.0
}

/// Oracle slice: resolve the queued unresolved method-call bodies against the
/// resident RA daemon and reclassify any body with a `&mut self` / `&mut`-param
/// (Mutating) method call -> SHARPEN the `unresolved` locus reason "mutation through &mut". Sound + safe: an
/// unreachable/cold daemon returns no resolutions -> a conservative no-op (every
/// body stays unresolved). Never WARRANTS here -- `RefClean` does not prove the
/// body free of IO/panic the signature can't reveal.
fn oracle_reclassify_mutating(
    workspace_root: &Path,
    rel: &str,
    pending: &[(usize, Vec<(u32, u32)>)],
    source_loci: &mut [Value],
) {
    if pending.is_empty() {
        return;
    }
    // OFF by default: resolve_receiver_crates can SPAWN the daemon (-> RA index,
    // the heavy/Mac-cooking path), so the oracle pass only runs when explicitly
    // enabled (the supervised run, on a box with a warm RA host). Default builds,
    // CI, and local measurements stay a pure no-op.
    if std::env::var("SUGAR_SOURCE_AUDIT_ORACLE").as_deref() != Ok("1") {
        return;
    }
    use sugar_walk::ra_daemon_client::{resolve_receiver_crates, DaemonQuery};
    let abs = workspace_root.join(rel).to_string_lossy().to_string();
    let mut queries = Vec::new();
    for (_, positions) in pending {
        for &(line, col) in positions {
            queries.push(DaemonQuery {
                file: abs.clone(),
                line,
                col,
            });
        }
    }
    let batch = resolve_receiver_crates(workspace_root, &queries);
    if batch.resolutions.is_empty() {
        return; // daemon down/cold/not-ready -> conservative no-op
    }
    for (idx, positions) in pending {
        let mutating = positions.iter().any(|&(line, col)| {
            batch
                .resolutions
                .get(&(abs.clone(), line, col))
                .is_some_and(|r| r.effect == "mutating")
        });
        if mutating {
            if let Some(locus) = source_loci.get_mut(*idx) {
                // A PROVEN `&mut` mutation is a real effect signal, but this side
                // door does not own a Sugar proof. The locus stays `unresolved`;
                // the oracle only SHARPENS its reason to name the observed boundary.
                locus["status"] = json!("unresolved");
                locus["reason"] =
                    json!("mutation through &mut (oracle): proven effect, no value pin");
            }
        }
    }
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
        "source_refuted": count("refuted"),
        // Compatibility alias for current CLI source-ledger plumbing.
        "unclassified_source": unresolved,
    })
}

fn lift_options_from_config(workspace_root: &Path, params: &Value) -> Result<LiftOptions, String> {
    let config_rel = params
        .get("config_path")
        .and_then(Value::as_str)
        .unwrap_or(".sugar/config.toml");
    let config_path = workspace_root.join(config_rel);
    match std::fs::read_to_string(&config_path) {
        Ok(text) => target_cfg_from_config_text(&text).map(|cfg| match cfg {
            Some(cfg) => LiftOptions::for_target_cfg(cfg),
            None => LiftOptions::default(),
        }),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(LiftOptions::default()),
        Err(e) => Err(format!("cannot read {}: {e}", config_path.display())),
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

fn factory_audits_json(file: &str, audits: &[FactoryAudit]) -> Vec<Value> {
    audits
        .iter()
        .map(|audit| {
            json!({
                "file": file,
                "ast_kind": audit.ast_kind,
                "site": audit.site,
                "line": audit.line,
                "requested_role": audit.requested_role,
                "selected": audit.selected,
                "candidates": audit.candidates.iter().map(|candidate| {
                    json!({
                        "name": candidate.name,
                        "role": candidate.role,
                        "priority": candidate.priority,
                        "selected": candidate.selected,
                    })
                }).collect::<Vec<_>>(),
                "status": audit.disposition.as_str(),
                "output": audit.output,
                "reason": audit.reason,
            })
        })
        .collect()
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
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{}", serde_json::to_string(obj).unwrap_or_default());
    let _ = out.flush();
}

fn err_reply(id: &Value, msg: String) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": {"code": -32603, "message": msg}})
}

fn handle(id: &Value, method: &str, params: &Value) -> Value {
    match method {
        "initialize" => json!({"jsonrpc": "2.0", "id": id, "result": initialize_result()}),
        KIT_DECLARATION_RPC_METHOD => {
            json!({"jsonrpc": "2.0", "id": id, "result": kit_declaration_result()})
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
    }
}

fn main() {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn fns_of(src: &str) -> Vec<FnRef<'_>> {
        // leak so the FnRefs can borrow for the test's lifetime
        let file: &'static syn::File = Box::leak(Box::new(syn::parse_file(src).expect("parses")));
        let mut out = Vec::new();
        collect_fns(&file.items, &mut out);
        out
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
    fn unwarrantable_body_falls_through_to_unresolved_no_sugar_yet() {
        // DESIGN LAW: a non-test body the kit cannot warrant or inline is not
        // "considered and declined" -- it falls through to "we don't have a Sugar
        // for that yet" (`unresolved`), the honest, VISIBLE work.
        let f: syn::ItemFn =
            syn::parse_str("fn log(x: i32) { println!(\"{x}\"); }").expect("fn parses");
        let source_memento = json!({});
        let (status, reason, decl) =
            classify_nontest_fn("log", &f.sig, &f.block, false, &source_memento);
        assert!(decl.is_none(), "an un-warrantable body mints no contract");
        assert_ne!(
            status, "refused",
            "`refused` must be earned by a named boundary"
        );
        assert_eq!(
            status, "unresolved",
            "an un-warrantable body falls through to 'no Sugar yet' (reason: {reason:?})"
        );
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
            audits.iter().any(|audit| audit["site"] == "make_value ()"),
            "call operand should be factory-accounted: {audits:?}"
        );
        assert!(
            audits.iter().any(|audit| audit["site"] == "6"),
            "literal operand should be factory-accounted: {audits:?}"
        );
        assert!(
            audits.iter().any(|audit| {
                audit["requested_role"] == "Constraint"
                    && audit["site"]
                        .as_str()
                        .is_some_and(|site| site.contains("assert_eq"))
            }),
            "assertion macro spelling should be factory-accounted as a constraint Sugar: {audits:?}"
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
