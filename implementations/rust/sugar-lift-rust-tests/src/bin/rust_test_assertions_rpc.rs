// SPDX-License-Identifier: Apache-2.0
//
// RPC entrypoint for the Rust test-assertion consistency lifter.

use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use sugar_ir_symbolic::serialize::marshal_declarations;
use sugar_lift_rust_tests::source_oracle;
use sugar_lift_rust_tests::{lift_file_with_options, LiftOptions, TargetCfg};

const VERSION: &str = env!("CARGO_PKG_VERSION");
const SURFACE: &str = "rust-test-assertions";
const KIT_DECLARATION_RPC_METHOD: &str = "sugar.plugin.kit_declaration";

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
    // fn is in this kit's universe (warranted, or refused if the lift warned);
    // a non-test fn the kit does not speak is `unclassified` -- the dark this
    // metric exists to surface. `unclassified` is therefore MEASURED against the
    // whole source, not 0 by construction.
    let mut source_loci: Vec<Value> = Vec::new();
    let mut source_mementos: Vec<Value> = Vec::new();
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
        if let Some(arr) = parsed.as_array() {
            entries.extend(arr.iter().cloned());
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
        let mut fns: Vec<FnRef> = Vec::new();
        collect_fns(&file.items, &mut fns);
        // Real warrants emit ProofIR: contracts the recursive body-walk produced,
        // marshalled into the IR alongside the test-assertion decls (below).
        let mut value_decls: Vec<sugar_ir_symbolic::ContractDecl> = Vec::new();
        // Oracle slice: unclassified method-call bodies queued for the RA daemon's
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
            // TOTAL classifier. Every function exits into exactly one status, and
            // `unclassified` is the HONEST dark -- a body the kit has not yet
            // classified, the residual the campaign drives to 0 by real
            // classification work. It is NOT a fall-through to avoid: forcing the
            // catch-all to `refused` so `unclassified=0` is a FAKE ZERO -- it
            // launders the dark into a verdict it never earned. `refused` is a
            // CONSIDERED no (false-pass risk), here only the test-assertion lifter
            // declining an assertion it understands. `unclassified=0` is the GOAL,
            // earned by classifying -- never structural.
            let (status, reason): (&str, Option<String>) = if is_test {
                match warning {
                    // NEW DOCTRINE: the lifter COULDN'T LIFT this vendor assertion
                    // (unsupported assert / no liftable scalar / ambiguous cfg) ->
                    // there is no usable pin to check, so it is SILENT, not refused.
                    // `refused` is reserved for an UNSAT certificate -- a vendor
                    // assertion we DID lift that contradicts (itself or the body).
                    // A can't-lift is a coverage gap (named in the reason), never a
                    // contradiction verdict.
                    Some(w) => ("silent", Some(format!("vendor pin not liftable: {}", w.reason))),
                    None => ("warranted", None),
                }
            } else if let Some(decl) =
                sugar_lift_rust_tests::broad_functional_warrant(&name, fr.sig, fr.block)
            {
                // We THINK it constrains -> WARRANT it, broadly. Either a structural
                // lift (strong teeth) or the dumb functional fallback
                // `out = call:NAME(params)` (out is a deterministic function of the
                // inputs -- weak teeth, but a real vendor DEMAND). Safe to be dumb:
                // the vendor is the referee. A bogus broad warrant finds no pin
                // (harmless) or goes all-UNSAT and self-retracts; only a SAT
                // licenses it, and only then are its UNSATs vendor findings. The
                // decl flows into the IR; the universe is built from these demands.
                value_decls.push(decl);
                ("warranted", None)
            } else if out.reduced_helpers.contains(&name) {
                // a non-test fn the reducer inlined to discharge a test: it backs
                // a warrant, so it is `support`.
                ("support", None)
            } else {
                // It NEVER constrains: a unit-returning body has no output to
                // demand anything about. REFUSED BY VACUITY -- "adds no constraint"
                // -- the reason names the effect if one is present (IO / mutation /
                // panic / `?`), else bare vacuity. This is the EASY, EXPECTED half
                // of refused (the analysis half is the UNSAT-vs-vendor certificate,
                // wired at the body<->pin seam). There is no swamp left: every body
                // is warranted (constrains) or refused (never constrains / UNSAT).
                let reason = effect_refusal(fr.block).unwrap_or_else(|| {
                    "vacuity: no output to constrain (unit return states no demand)".to_string()
                });
                ("refused", Some(reason))
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
            if status == "unclassified" {
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
        let value_marshalled = marshal_declarations(&value_decls);
        if let Ok(Value::Array(arr)) = serde_json::from_str::<Value>(&value_marshalled) {
            entries.extend(arr);
        }
        // Oracle slice: ask the resident RA daemon (sugar-linkerd) to resolve the
        // receiver/param mutability of each queued method-call position. A method
        // call that is `&mut self` / takes a `&mut` param is the provable
        // "mutation through &mut" effect -> reclassify the body REFUSED. An
        // unreachable/cold daemon yields no resolutions -> every body stays
        // unclassified (the conservative refuse-floor); the oracle never warrants
        // here (RefClean does not rule out IO/panic the signature can't show).
        oracle_reclassify_mutating(&workspace_root, rel, &oracle_pending, &mut source_loci);
    }

    let ledger = source_ledger(&source_loci);
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
        // Content-addressed mementos (file + span + BLAKE3-512 of body/template,
        // never source text) -- one per enumerated function, recompute-verifiable.
        "sourceMementos": source_mementos,
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
                for ii in &im.items {
                    if let syn::ImplItem::Fn(m) = ii {
                        out.push(FnRef {
                            span: m.span(),
                            name: m.sig.ident.to_string(),
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
                                name: m.sig.ident.to_string(),
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

/// True iff the function carries a `#[test]` (or `#[…::test]`) attribute.
fn fn_has_test_attr(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path()
            .segments
            .last()
            .is_some_and(|seg| seg.ident == "test")
    })
}

/// Scan an unclassified body for the dominant blocker, so every `unclassified`
/// locus carries a NAMED, CATEGORIZED note of WHICH construct the walker doesn't
/// speak yet -- the IO membrane (bin-2, the named floor) split from drainable
/// bin-1 (loop / `?` / method-call / macro). This is a diagnostic, not a verdict.
#[derive(Default)]
struct BlockerScan {
    io: Option<String>,
    has_loop: bool,
    has_try: bool,
    has_method: bool,
    macro_name: Option<String>,
    has_assign: bool,
    has_mut_borrow: bool,
    has_compound_assign: bool,
    panic_macro: Option<String>,
    panic_method: Option<String>,
}

impl<'ast> syn::visit::Visit<'ast> for BlockerScan {
    fn visit_expr_for_loop(&mut self, n: &'ast syn::ExprForLoop) {
        self.has_loop = true;
        syn::visit::visit_expr_for_loop(self, n);
    }
    fn visit_expr_while(&mut self, n: &'ast syn::ExprWhile) {
        self.has_loop = true;
        syn::visit::visit_expr_while(self, n);
    }
    fn visit_expr_loop(&mut self, n: &'ast syn::ExprLoop) {
        self.has_loop = true;
        syn::visit::visit_expr_loop(self, n);
    }
    fn visit_expr_try(&mut self, n: &'ast syn::ExprTry) {
        self.has_try = true;
        syn::visit::visit_expr_try(self, n);
    }
    fn visit_expr_assign(&mut self, n: &'ast syn::ExprAssign) {
        self.has_assign = true;
        syn::visit::visit_expr_assign(self, n);
    }
    fn visit_expr_reference(&mut self, n: &'ast syn::ExprReference) {
        if n.mutability.is_some() {
            self.has_mut_borrow = true;
        }
        syn::visit::visit_expr_reference(self, n);
    }
    fn visit_expr_binary(&mut self, n: &'ast syn::ExprBinary) {
        use syn::BinOp::*;
        if matches!(
            n.op,
            AddAssign(_)
                | SubAssign(_)
                | MulAssign(_)
                | DivAssign(_)
                | RemAssign(_)
                | BitXorAssign(_)
                | BitAndAssign(_)
                | BitOrAssign(_)
                | ShlAssign(_)
                | ShrAssign(_)
        ) {
            self.has_compound_assign = true;
        }
        syn::visit::visit_expr_binary(self, n);
    }
    fn visit_expr_method_call(&mut self, n: &'ast syn::ExprMethodCall) {
        self.has_method = true;
        if self.panic_method.is_none() {
            let m = n.method.to_string();
            if matches!(
                m.as_str(),
                "unwrap" | "expect" | "unwrap_unchecked" | "unwrap_err" | "expect_err"
            ) {
                self.panic_method = Some(m);
            }
        }
        syn::visit::visit_expr_method_call(self, n);
    }
    fn visit_expr_call(&mut self, n: &'ast syn::ExprCall) {
        if self.io.is_none() {
            if let syn::Expr::Path(p) = &*n.func {
                let path = p
                    .path
                    .segments
                    .iter()
                    .map(|s| s.ident.to_string())
                    .collect::<Vec<_>>()
                    .join("::");
                if is_io_path(&path) {
                    self.io = Some(format!("call `{path}`"));
                }
            }
        }
        syn::visit::visit_expr_call(self, n);
    }
    fn visit_macro(&mut self, m: &'ast syn::Macro) {
        let name = m
            .path
            .segments
            .last()
            .map(|s| s.ident.to_string())
            .unwrap_or_default();
        if self.io.is_none()
            && matches!(
                name.as_str(),
                "println" | "print" | "eprintln" | "eprint" | "write" | "writeln"
            )
        {
            self.io = Some(format!("macro `{name}!`"));
        }
        if self.panic_macro.is_none()
            && matches!(
                name.as_str(),
                "panic"
                    | "unreachable"
                    | "unimplemented"
                    | "todo"
                    | "assert"
                    | "assert_eq"
                    | "assert_ne"
                    | "debug_assert"
                    | "debug_assert_eq"
                    | "debug_assert_ne"
                    | "const_panic"
                    | "const_assert"
                    | "assert_unsafe_precondition"
            )
        {
            self.panic_macro = Some(name.clone());
        }
        if self.macro_name.is_none() {
            self.macro_name = Some(name);
        }
        syn::visit::visit_macro(self, m);
    }
}

/// The EASY half of refused: a body with NO liftable constraint that is provably
/// effectful (IO membrane / mutation via `&mut`/assignment / panic-divergence /
/// `?` short-circuit) is out of the consistency domain -> refused BY NAME. This
/// runs AFTER try-warrant (emit_value_contract), never as a pre-gate: a volatile
/// body that still lifts a constraint is warranted and judged by the vendor, not
/// pre-refused. An undetermined body (opaque call / macro / multi-statement)
/// returns None -> it stays unclassified or silent (we have not PROVEN an effect).
/// The HARD half of refused -- a lifted constraint that goes UNSAT against a
/// vendor pin -- is minted separately (where the analysis lives).
fn effect_refusal(block: &syn::Block) -> Option<String> {
    let mut s = BlockerScan::default();
    syn::visit::Visit::visit_block(&mut s, block);
    if let Some(io) = s.io {
        return Some(format!("IO membrane (effect): {io}"));
    }
    if s.has_assign || s.has_compound_assign || s.has_mut_borrow {
        return Some("mutation (effect): assignment / `&mut` borrow".to_string());
    }
    if let Some(m) = s.panic_macro {
        return Some(format!("panic/divergence (effect): `{m}!`"));
    }
    if let Some(m) = s.panic_method {
        return Some(format!("panic/divergence (effect): `.{m}()`"));
    }
    if s.has_try {
        return Some("panic/divergence (effect): `?` short-circuit".to_string());
    }
    None
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

/// Oracle slice: resolve the queued unclassified method-call bodies against the
/// resident RA daemon and reclassify any body with a `&mut self` / `&mut`-param
/// (Mutating) method call to `refused` "mutation through &mut". Sound + safe: an
/// unreachable/cold daemon returns no resolutions -> a conservative no-op (every
/// body stays unclassified). Never WARRANTS here -- `RefClean` does not prove the
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
                locus["status"] = json!("refused");
                locus["reason"] = json!("mutation through &mut (oracle)");
            }
        }
    }
}

fn is_io_path(path: &str) -> bool {
    [
        "fs::",
        "io::",
        "net::",
        "process::",
        "time::Instant",
        "time::SystemTime",
        "File",
        "stdin",
        "stdout",
        "stderr",
        "thread::spawn",
        "thread::sleep",
    ]
    .iter()
    .any(|m| path.contains(m))
}

/// Roll the per-locus statuses into the `sourceLedger` the CLI source-audit gate
/// requires. The CLI RECOMPUTES this from the loci, so it must be exactly the
/// per-status counts. `unclassified_source` is the silent-drop measure: every
/// locus the kit emits carries a classified status, so a non-zero count here
/// means a source locus escaped accounting -- the thing `silent = 0` forbids.
fn source_ledger(loci: &[Value]) -> Value {
    let count = |status: &str| {
        loci.iter()
            .filter(|l| l.get("status").and_then(Value::as_str) == Some(status))
            .count()
    };
    json!({
        "source_loci": loci.len(),
        "source_warranted": count("warranted"),
        "source_support": count("support"),
        "source_refused": count("refused"),
        // SILENT (new doctrine): a body with no output to constrain (unit return)
        // and no vendor pin -- nothing to lift, nothing to check. Partitioned out
        // of `unclassified` so the residual is only value bodies the lifter cannot
        // read yet, NOT effect-only operations parked on a floor.
        "source_silent": count("silent"),
        "source_inactive": count("inactive"),
        "source_refuted": count("refuted"),
        "unclassified_source": count("unclassified"),
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
            names.contains(&"method".to_string()),
            "impl method must be enumerated: {names:?}"
        );
        assert!(
            names.contains(&"defaulted".to_string()),
            "trait default method must be enumerated: {names:?}"
        );
        // a trait method WITHOUT a body declares no constructor -> not a locus.
        assert!(
            !names.contains(&"decl_only".to_string()),
            "bodyless trait decl is not a locus: {names:?}"
        );
    }

    fn block_of(src: &str) -> syn::Block {
        let f: syn::ItemFn = syn::parse_str(src).expect("fn parses");
        *f.block
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
    fn effect_refusal_is_the_easy_half_of_refused() {
        // The EASY half of refused: provably effectful bodies, refused by name.
        // (Runs AFTER try-warrant in the classifier -- a body that lifts a
        // constraint is warranted regardless; this only catches no-constraint
        // effectful bodies.) The HARD half (UNSAT vs a vendor pin) is minted
        // elsewhere -- where the analysis lives.
        assert!(effect_refusal(&block_of("fn f() { println!(\"x\"); }"))
            .is_some_and(|r| r.contains("IO membrane")));
        assert!(effect_refusal(&block_of("fn f(x: &mut i32) { *x = 1; }"))
            .is_some_and(|r| r.contains("mutation")));
        assert!(effect_refusal(&block_of("fn f() -> i32 { panic!(\"no\") }"))
            .is_some_and(|r| r.contains("panic/divergence")));
        assert!(effect_refusal(&block_of("fn f(r: Result<i32, ()>) -> i32 { r? }"))
            .is_some_and(|r| r.contains("divergence") && r.contains('?')));
        // Undetermined (no proven effect) -> None: stays unclassified/silent,
        // never refused on a guess. The EUF warrant handles a bare call upstream.
        assert!(effect_refusal(&block_of("fn f(v: Vec<u8>) -> usize { v.len() }")).is_none());
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
        assert!(inv.contains("call:f") && inv.contains('a'), "functional warrant out=call:f(a): {inv}");

        // UNIT body -> NEVER constrains (no output) -> None -> caller refuses by
        // vacuity. Effectful or not, there is no output to demand anything about.
        let u = parse("fn log(x: i32) { println!(\"{x}\"); }");
        assert!(sig_returns_unit(&u.sig));
        assert!(
            broad_functional_warrant("log", &u.sig, &u.block).is_none(),
            "a unit body states no output constraint -> None -> refuse by vacuity"
        );
    }
}
