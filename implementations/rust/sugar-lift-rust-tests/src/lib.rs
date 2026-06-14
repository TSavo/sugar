// SPDX-License-Identifier: Apache-2.0
//
// sugar-lift-rust-tests
//
// Rust parity for sugar-lift-py-tests' assertion-consistency path:
// recognize scalar assertions inside #[test] functions and emit inv-only
// ContractDecls. The verifier's existing consistency pass checks those closed
// invariants with raw SAT: SAT => consistent/discharged; UNSAT => refused.

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fmt;
use std::rc::Rc;

mod macro_expand;

use quote::ToTokens;
use sugar_ir_symbolic::{
    and_, atomic_, eq, forall, gt, gte, implies, lt, lte, make_var, ne, not_, num, or_, real_const,
    str_const, ConstValue, ContractDecl, Formula, Sort, Term,
};
use syn::parse::{Parse, ParseStream, Parser};
use syn::punctuated::Punctuated;
use syn::{BinOp, Expr, ExprLit, Item, Lit, Pat, Stmt, Token, Type, UnOp};

#[derive(Debug, Clone)]
pub struct LiftWarning {
    pub source_path: String,
    pub item_name: String,
    pub reason: String,
}

#[derive(Debug, Default)]
pub struct AdapterOutput {
    pub decls: Vec<ContractDecl>,
    pub warnings: Vec<LiftWarning>,
    pub seen: usize,
    pub lifted: usize,
    /// Assertion-macro invocations the collector reached and lifted to at least
    /// one FOL atom (counted at macro granularity, not atom granularity).
    pub assertions_lifted: usize,
    /// Assertion-macro invocations the collector reached but refused, each with
    /// a named reason (the loudly-bounded-lossy outcome).
    pub assertions_refused: usize,
    /// Every individual refusal reason, ungrouped, for the delta histogram.
    pub skip_reasons: Vec<String>,
    /// Names of non-test helper fns that were successfully reduced (inlined) by
    /// the reducer at least once. Used to avoid double-counting: asserts in these
    /// fns are already credited under assertions_lifted and must not also appear
    /// in assertions_refused.
    pub(crate) reduced_helpers: HashSet<String>,
}

#[derive(Debug, Clone, Default)]
pub struct LiftOptions {
    pub target_cfg: Option<TargetCfg>,
}

impl LiftOptions {
    pub fn for_target_cfg(target_cfg: TargetCfg) -> Self {
        Self {
            target_cfg: Some(target_cfg),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct TargetCfg {
    facts: BTreeMap<String, BTreeSet<Option<String>>>,
}

impl TargetCfg {
    pub fn from_rustc_cfg_facts<I, S>(facts: I) -> Result<Self, String>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let mut out = Self::default();
        for raw in facts {
            out.insert_rustc_cfg_fact(raw.as_ref())?;
        }
        Ok(out)
    }

    pub fn from_rustc_cfg_text(text: &str) -> Result<Self, String> {
        Self::from_rustc_cfg_facts(text.lines())
    }

    fn insert_rustc_cfg_fact(&mut self, raw: &str) -> Result<(), String> {
        let fact = raw.trim();
        if fact.is_empty() {
            return Ok(());
        }
        let (key, value) = if let Some(eq) = fact.find('=') {
            let key = fact[..eq].trim();
            let value = parse_rustc_cfg_quoted_value(fact[eq + 1..].trim())?;
            (key, Some(value))
        } else {
            (fact, None)
        };
        if key.is_empty() {
            return Err(format!("empty cfg key in `{fact}`"));
        }
        self.facts.entry(key.to_string()).or_default().insert(value);
        Ok(())
    }

    fn contains_name(&self, name: &str) -> bool {
        self.facts
            .get(name)
            .is_some_and(|values| values.contains(&None))
    }

    fn contains_key_value(&self, key: &str, value: &str) -> bool {
        self.facts
            .get(key)
            .is_some_and(|values| values.contains(&Some(value.to_string())))
    }
}

fn parse_rustc_cfg_quoted_value(raw: &str) -> Result<String, String> {
    let lit = syn::parse_str::<syn::LitStr>(raw)
        .map_err(|e| format!("cfg value must be a quoted Rust string `{raw}`: {e}"))?;
    Ok(lit.value())
}

pub fn lift_file(file: &syn::File, source_path: &str) -> AdapterOutput {
    lift_file_with_options(file, source_path, &LiftOptions::default())
}

pub fn lift_file_with_options(
    file: &syn::File,
    source_path: &str,
    options: &LiftOptions,
) -> AdapterOutput {
    let empty = MacroRegistry::new();
    lift_file_with_macro_imports(file, source_path, options, &empty)
}

/// Lift a file with an external macro registry in scope. The registry carries
/// `macro_rules!` definitions gathered from the rest of the crate and its
/// dependency SOURCE (we operate exclusively on source, never on a binary or an
/// opaque macro we refuse to read). Any macro the lifter expands is expanded
/// from a definition we hold.
pub fn lift_file_with_macro_imports(
    file: &syn::File,
    source_path: &str,
    options: &LiftOptions,
    imported_macros: &MacroRegistry,
) -> AdapterOutput {
    let mut out = AdapterOutput::default();
    let mut modules = Vec::new();
    let reducer = ReductionCtx::from_items_with_imports(&file.items, imported_macros);
    // Pass 1: walk test fns (and modules). Populates assertions_lifted, reduced_helpers.
    walk_items(
        &file.items,
        source_path,
        &mut modules,
        options,
        &reducer,
        &mut out,
    );
    // Pass 2: walk non-test fns. Emit named refusals for asserts in helper fns
    // that were NOT already credited via reducer inlining in Pass 1.
    walk_non_test_fns(
        &file.items,
        source_path,
        &mut Vec::new(),
        &out.reduced_helpers.clone(),
        &reducer,
        options,
        &mut out,
    );
    out
}

fn walk_items<'a>(
    items: &[Item],
    source_path: &str,
    modules: &mut Vec<String>,
    options: &LiftOptions,
    reducer: &ReductionCtx<'a>,
    out: &mut AdapterOutput,
) {
    for item in items {
        match item {
            Item::Fn(f) => {
                if has_test_attr(&f.attrs) {
                    visit_test_fn(f, source_path, modules, options, reducer, out);
                }
                // Non-test fns are handled in the second pass (walk_non_test_fns).
            }
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    let module_name = scoped_test_name(source_path, modules, &m.ident.to_string());
                    match cfg_eval_for_attrs(&m.attrs, options) {
                        CfgEval::Active => {}
                        CfgEval::Inactive(reason) => {
                            account_skipped_module(
                                items,
                                &module_name,
                                "inactive",
                                &reason,
                                source_path,
                                out,
                            );
                            continue;
                        }
                        CfgEval::Ambiguous(reason) => {
                            account_skipped_module(
                                items,
                                &module_name,
                                "ambiguous",
                                &reason,
                                source_path,
                                out,
                            );
                            continue;
                        }
                    }
                    modules.push(m.ident.to_string());
                    walk_items(items, source_path, modules, options, reducer, out);
                    modules.pop();
                }
            }
            _ => {}
        }
    }
}

/// Walk items for Pass 2 (non-test fns). Emits named refusals for asserts in
/// non-test fns that were NOT already credited via reducer inlining (Pass 1).
fn walk_non_test_fns(
    items: &[Item],
    source_path: &str,
    modules: &mut Vec<String>,
    reduced_helpers: &HashSet<String>,
    reducer: &ReductionCtx<'_>,
    options: &LiftOptions,
    out: &mut AdapterOutput,
) {
    for item in items {
        match item {
            Item::Fn(f) => {
                if !has_test_attr(&f.attrs) {
                    visit_non_test_fn(f, source_path, modules, reduced_helpers, out);
                }
            }
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    // A cfg-skipped module was fully accounted in pass 1; do not
                    // recurse here or its non-test asserts would be double-counted.
                    if !matches!(cfg_eval_for_attrs(&m.attrs, options), CfgEval::Active) {
                        continue;
                    }
                    modules.push(m.ident.to_string());
                    walk_non_test_fns(
                        items,
                        source_path,
                        modules,
                        reduced_helpers,
                        reducer,
                        options,
                        out,
                    );
                    modules.pop();
                }
            }
            // Item-level macro invocation (e.g. `assert_value!(...)` at module
            // scope). Account assert-named invocations: walk into the definition
            // if it is in-source, otherwise refuse by name. One invocation is one
            // unit, matching the assertion-macro denominator.
            Item::Macro(m) => {
                if let Some(seg) = m.mac.path.segments.last() {
                    let mname = seg.ident.to_string();
                    if mname.starts_with("assert") || mname.starts_with("debug_assert") {
                        let reason = match try_macro_expansion_entries(
                            &m.mac.path,
                            &m.mac.tokens,
                            reducer,
                            "item",
                            options,
                            &mut FloatWidthScope::new(),
                            0,
                        ) {
                            Some(Ok(_)) => format!(
                                "item-level macro `{mname}`: assertion content lifts only inside a test fn; released to layer 0"
                            ),
                            Some(Err(e)) => e,
                            None => format!(
                                "item-level assert macro `{mname}`: definition not visible; released to layer 0"
                            ),
                        };
                        out.assertions_refused += 1;
                        out.skip_reasons.push(reason.clone());
                        out.warnings.push(LiftWarning {
                            source_path: source_path.to_string(),
                            item_name: scoped_test_name(source_path, modules, &mname),
                            reason: format!(
                                "rust test assertions: unsupported assertion surface; released to layer 0: {reason}"
                            ),
                        });
                    }
                }
            }
            // Asserts inside impl method bodies (e.g. an Iterator impl on a test
            // helper struct) are reachable only when the method runs, with the
            // receiver's runtime state. Refuse them so they are not silent.
            Item::Impl(imp) => {
                for impl_item in &imp.items {
                    if let syn::ImplItem::Fn(method) = impl_item {
                        let method_name = method.sig.ident.to_string();
                        let count = count_asserts_in_stmts(&method.block.stmts);
                        if count == 0 {
                            continue;
                        }
                        let reason = format!(
                            "assertion in impl method {method_name}: reachable only when the method runs; released to layer 0"
                        );
                        for _ in 0..count {
                            out.assertions_refused += 1;
                            out.skip_reasons.push(reason.clone());
                        }
                        out.warnings.push(LiftWarning {
                            source_path: source_path.to_string(),
                            item_name: scoped_test_name(source_path, modules, &method_name),
                            reason: format!(
                                "rust test assertions: unsupported assertion surface; released to layer 0: {reason}"
                            ),
                        });
                    }
                }
            }
            // Item-level const/static initializers can hold compile-time asserts
            // (e.g. `const _: () = assert!(S(1) == S(1));`). Count and refuse them
            // so they are accounted, not silently dropped.
            Item::Const(c) => {
                refuse_item_assertions(&c.expr, "const-item", source_path, modules, out);
            }
            Item::Static(s) => {
                refuse_item_assertions(&s.expr, "static-item", source_path, modules, out);
            }
            _ => {}
        }
    }
}

/// Emit named refusals for every assert macro in a non-`#[test]` fn.
/// These assertions are only reachable via call-site inlining and depend on
/// the fn's parameters: lifting them as unconditional facts would be a false-pass.
/// Skips the fn if it was already successfully reduced by a test fn (Pass 1),
/// because those asserts are already in assertions_lifted.
fn visit_non_test_fn(
    f: &syn::ItemFn,
    source_path: &str,
    modules: &[String],
    reduced_helpers: &HashSet<String>,
    out: &mut AdapterOutput,
) {
    let fn_name = f.sig.ident.to_string();
    // If the reducer successfully inlined this fn's body during Pass 1, its
    // asserts are already in assertions_lifted. Do not double-count.
    if reduced_helpers.contains(&fn_name) {
        return;
    }
    let scoped_name = scoped_test_name(source_path, modules, &fn_name);
    let count = count_asserts_in_stmts(&f.block.stmts);
    if count == 0 {
        return;
    }
    let reason = format!(
        "assertion in non-#[test] item {fn_name}: reachable only via call-site inlining; released to layer 0"
    );
    for _ in 0..count {
        out.assertions_refused += 1;
        out.skip_reasons.push(reason.clone());
    }
    out.warnings.push(LiftWarning {
        source_path: source_path.to_string(),
        item_name: scoped_name,
        reason: format!(
            "rust test assertions: unsupported assertion surface; released to layer 0: {reason}"
        ),
    });
}

fn visit_test_fn(
    f: &syn::ItemFn,
    source_path: &str,
    modules: &[String],
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    out: &mut AdapterOutput,
) {
    let test_name = scoped_test_name(source_path, modules, &f.sig.ident.to_string());
    match cfg_eval_for_attrs(&f.attrs, options) {
        CfgEval::Active => {}
        CfgEval::Inactive(reason) => {
            // Refuse every assert in the fn body so they are not silent drops.
            let assert_count = count_asserts_in_stmts(&f.block.stmts);
            let skip_reason = format!("inactive cfg on test fn; skipped: {reason}");
            for _ in 0..assert_count {
                out.assertions_refused += 1;
                out.skip_reasons.push(skip_reason.clone());
            }
            out.warnings.push(LiftWarning {
                source_path: source_path.to_string(),
                item_name: test_name,
                reason: format!("rust test assertions: inactive cfg; skipped test: {reason}"),
            });
            return;
        }
        CfgEval::Ambiguous(reason) => {
            // Refuse every assert in the fn body so they are not silent drops.
            let assert_count = count_asserts_in_stmts(&f.block.stmts);
            let skip_reason = format!("ambiguous cfg on test fn; skipped: {reason}");
            for _ in 0..assert_count {
                out.assertions_refused += 1;
                out.skip_reasons.push(skip_reason.clone());
            }
            out.warnings.push(LiftWarning {
                source_path: source_path.to_string(),
                item_name: test_name,
                reason: format!("rust test assertions: ambiguous cfg; skipped test: {reason}"),
            });
            return;
        }
    }
    out.seen += 1;

    let mut entries = Vec::new();
    let mut skipped = Vec::new();
    let mut float_widths = FloatWidthScope::new();
    let mut macros_lifted = 0usize;
    collect_assertion_entries(
        &f.block.stmts,
        &test_name,
        options,
        reducer,
        &mut float_widths,
        &mut entries,
        &mut skipped,
        &mut macros_lifted,
        &mut out.reduced_helpers,
        0,
    );
    out.assertions_lifted += macros_lifted;
    out.assertions_refused += skipped.len();
    out.skip_reasons.extend(skipped.iter().cloned());

    // Totality safety net: every assert macro textually present in this test fn
    // body must be accounted for (lifted or refused). The syntactic count is the
    // ground truth; if the structured walk enumerated fewer (an assert in an AST
    // position no arm handles), refuse the remainder by name so nothing is
    // silently dropped. When helper inlining makes accounted exceed the textual
    // count, the gap is zero and no refusal is added.
    let textual_total = count_asserts_in_stmts(&f.block.stmts);
    let accounted = macros_lifted + skipped.len();
    if textual_total > accounted {
        let gap = textual_total - accounted;
        let reason =
            "assertion in an unenumerated statement position within the test fn; released to layer 0"
                .to_string();
        for _ in 0..gap {
            out.assertions_refused += 1;
            out.skip_reasons.push(reason.clone());
        }
        out.warnings.push(LiftWarning {
            source_path: source_path.to_string(),
            item_name: test_name.clone(),
            reason: format!(
                "rust test assertions: {gap} assertion(s) in unenumerated positions; released to layer 0"
            ),
        });
    }

    if !skipped.is_empty() {
        out.warnings.push(LiftWarning {
            source_path: source_path.to_string(),
            item_name: test_name.clone(),
            reason: format!(
                "rust test assertions: unsupported assertion surface; released to layer 0: {}",
                skipped.join("; ")
            ),
        });
    }

    if entries.is_empty() {
        out.warnings.push(LiftWarning {
            source_path: source_path.to_string(),
            item_name: test_name,
            reason: "rust test assertions: no liftable scalar assertions".to_string(),
        });
        return;
    }

    for (name, atoms) in group_assertions(entries, &test_name) {
        out.decls.push(ContractDecl {
            name,
            pre: None,
            post: None,
            inv: Some(and_(atoms)),
            out_binding: "out".to_string(),
            evidence: None,
            panic_loci: Vec::new(),
            concept_hint: None,
        });
    }
    out.lifted += 1;
}

fn has_test_attr(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path()
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "test")
    })
}

fn scoped_test_name(source_path: &str, modules: &[String], fn_name: &str) -> String {
    if modules.is_empty() {
        format!("{source_path}::{fn_name}")
    } else {
        format!("{source_path}::{}::{fn_name}", modules.join("::"))
    }
}

struct AssertionEntry {
    name: Option<String>,
    atom: Rc<Formula>,
}

struct ReductionCtx<'a> {
    functions: BTreeMap<String, &'a syn::ItemFn>,
    ambiguous_functions: BTreeSet<String>,
    /// In-source `macro_rules!` definitions, by name, parsed into rules. These
    /// are what lets the lifter walk into a macro's definition and expand it,
    /// the same way it walks into a function. A name defined more than once is
    /// ambiguous and not expanded.
    macros: BTreeMap<String, std::rc::Rc<Vec<macro_expand::MacroRule>>>,
    ambiguous_macros: BTreeSet<String>,
    /// macro_rules! gathered from the rest of the crate and its dependency
    /// SOURCE. In-file definitions take precedence; this is the fallback so a
    /// macro defined in another file or crate (whose source we hold) is still
    /// expanded from its definition rather than treated as opaque.
    imported: MacroRegistry,
}

impl<'a> ReductionCtx<'a> {
    fn from_items(items: &'a [Item]) -> Self {
        Self::from_items_with_imports(items, &MacroRegistry::new())
    }

    fn from_items_with_imports(items: &'a [Item], imported: &MacroRegistry) -> Self {
        let mut ctx = Self {
            functions: BTreeMap::new(),
            ambiguous_functions: BTreeSet::new(),
            macros: BTreeMap::new(),
            ambiguous_macros: BTreeSet::new(),
            imported: imported.clone(),
        };
        ctx.collect_items(items);
        ctx
    }

    fn collect_items(&mut self, items: &'a [Item]) {
        for item in items {
            match item {
                Item::Fn(f) if !has_test_attr(&f.attrs) => self.insert_function(f),
                Item::Macro(m) if m.mac.path.is_ident("macro_rules") => {
                    if let Some(ident) = &m.ident {
                        self.insert_macro(&ident.to_string(), m.mac.tokens.clone());
                    }
                }
                Item::Mod(m) => {
                    if let Some((_, items)) = &m.content {
                        self.collect_items(items);
                    }
                }
                _ => {}
            }
        }
    }

    fn insert_function(&mut self, f: &'a syn::ItemFn) {
        let name = f.sig.ident.to_string();
        if self.ambiguous_functions.contains(&name) {
            return;
        }
        if self.functions.insert(name.clone(), f).is_some() {
            self.functions.remove(&name);
            self.ambiguous_functions.insert(name);
        }
    }

    fn insert_macro(&mut self, name: &str, tokens: proc_macro2::TokenStream) {
        if self.ambiguous_macros.contains(name) {
            return;
        }
        // A macro whose rules we cannot even parse is not a usable definition;
        // skip it (the caller falls back to refusal).
        let Ok(rules) = macro_expand::parse_rules(tokens) else {
            return;
        };
        if self
            .macros
            .insert(name.to_string(), std::rc::Rc::new(rules))
            .is_some()
        {
            self.macros.remove(name);
            self.ambiguous_macros.insert(name.to_string());
        }
    }

    fn function(&self, name: &str) -> Result<Option<&'a syn::ItemFn>, String> {
        if self.ambiguous_functions.contains(name) {
            return Err(format!(
                "assertion helper `{name}` is ambiguous in visible source"
            ));
        }
        Ok(self.functions.get(name).copied())
    }

    /// Look up a `macro_rules!` definition by name for expansion: in-file first
    /// (most specific), then the imported source-graph registry.
    fn macro_rules(&self, name: &str) -> Option<std::rc::Rc<Vec<macro_expand::MacroRule>>> {
        if self.ambiguous_macros.contains(name) {
            return None;
        }
        if let Some(rules) = self.macros.get(name) {
            return Some(rules.clone());
        }
        self.imported.lookup(name)
    }
}

/// A registry of `macro_rules!` definitions gathered from source: the crate
/// under analysis plus its dependency source trees. Our guarantee extends
/// exactly as far as the source we hold; a macro absent here is out of scope
/// (a named refusal), and the remedy is to add its source, never to reason
/// about a binary.
#[derive(Default, Clone)]
pub struct MacroRegistry {
    macros: BTreeMap<String, std::rc::Rc<Vec<macro_expand::MacroRule>>>,
    ambiguous: BTreeSet<String>,
}

impl MacroRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Ingest every `macro_rules!` definition in a parsed source file (recursing
    /// into inline modules). A name defined inconsistently across sources is
    /// marked ambiguous and not expanded.
    pub fn scan_file(&mut self, file: &syn::File) {
        self.scan_items(&file.items);
    }

    /// Parse source text and ingest its macro definitions. Unparseable source is
    /// skipped (it contributes no definitions).
    pub fn scan_source(&mut self, src: &str) {
        if let Ok(file) = syn::parse_file(src) {
            self.scan_file(&file);
        }
    }

    fn scan_items(&mut self, items: &[Item]) {
        for item in items {
            match item {
                Item::Macro(m) if m.mac.path.is_ident("macro_rules") => {
                    if let Some(ident) = &m.ident {
                        self.insert(&ident.to_string(), m.mac.tokens.clone());
                    }
                }
                Item::Mod(m) => {
                    if let Some((_, items)) = &m.content {
                        self.scan_items(items);
                    }
                }
                _ => {}
            }
        }
    }

    fn insert(&mut self, name: &str, tokens: proc_macro2::TokenStream) {
        if self.ambiguous.contains(name) {
            return;
        }
        let Ok(rules) = macro_expand::parse_rules(tokens) else {
            return;
        };
        match self.macros.get(name) {
            // Re-seeing a byte-identical definition (the same crate scanned
            // twice) is fine; a genuinely different one is ambiguous.
            Some(existing)
                if macro_expand::rules_signature(existing)
                    == macro_expand::rules_signature(&rules) => {}
            Some(_) => {
                self.macros.remove(name);
                self.ambiguous.insert(name.to_string());
            }
            None => {
                self.macros
                    .insert(name.to_string(), std::rc::Rc::new(rules));
            }
        }
    }

    fn lookup(&self, name: &str) -> Option<std::rc::Rc<Vec<macro_expand::MacroRule>>> {
        if self.ambiguous.contains(name) {
            return None;
        }
        self.macros.get(name).cloned()
    }

    /// Number of distinct macro definitions held (for reporting).
    pub fn len(&self) -> usize {
        self.macros.len()
    }

    pub fn is_empty(&self) -> bool {
        self.macros.is_empty()
    }
}

const MAX_ASSERTION_REDUCTION_DEPTH: usize = 8;

/// Bound on nested macro_rules expansion (a macro whose body invokes another
/// in-source macro). Prevents runaway expansion; assertion macros nest shallowly.
const MAX_MACRO_EXPANSION_DEPTH: usize = 16;

/// Walk into an in-source `macro_rules!` definition and reduce its expansion.
/// Returns:
///   - `None` if `path` is not an in-source macro we learned (caller falls back).
///   - `Some(Ok(entries))` if expansion produced at least one liftable atom.
///   - `Some(Err(reason))` if it expanded to no FOL content, the matcher was
///     unsupported, no rule matched, or depth was exceeded. The macro is one
///     accounting unit: one source invocation yields one outcome.
#[allow(clippy::too_many_arguments)]
fn try_macro_expansion_entries(
    path: &syn::Path,
    tokens: &proc_macro2::TokenStream,
    reducer: &ReductionCtx<'_>,
    local_scope: &str,
    options: &LiftOptions,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
) -> Option<Result<Vec<AssertionEntry>, String>> {
    let name = path.segments.last()?.ident.to_string();
    let rules = reducer.macro_rules(&name)?;
    if macro_depth >= MAX_MACRO_EXPANSION_DEPTH {
        return Some(Err(format!(
            "macro `{name}`: expansion depth exceeded; released to layer 0"
        )));
    }
    let expanded = match macro_expand::expand(&rules, tokens.clone()) {
        Ok(ts) => ts,
        Err(e) => return Some(Err(format!("macro `{name}`: {e}; released to layer 0"))),
    };
    // Re-parse the expansion as a statement block, then reduce it like any body.
    let block: syn::Block = match syn::parse2(quote::quote! { { #expanded } }) {
        Ok(b) => b,
        Err(_) => {
            return Some(Err(format!(
                "macro `{name}`: expansion did not parse as statements; released to layer 0"
            )))
        }
    };
    let mut temp_entries = Vec::new();
    let mut temp_skipped = Vec::new();
    let mut temp_lifted = 0usize;
    let mut temp_helpers = HashSet::new();
    collect_assertion_entries(
        &block.stmts,
        local_scope,
        options,
        reducer,
        float_widths,
        &mut temp_entries,
        &mut temp_skipped,
        &mut temp_lifted,
        &mut temp_helpers,
        macro_depth + 1,
    );
    if temp_entries.is_empty() {
        Some(Err(format!(
            "macro `{name}`: expansion yielded no liftable assertion (type-level or effectful body); released to layer 0"
        )))
    } else {
        Some(Ok(temp_entries))
    }
}

type ExprBindings = BTreeMap<String, Expr>;

#[derive(Debug, Clone, Default)]
struct TemporalPlan {
    versioned: BTreeSet<String>,
    /// Locals bound with `let mut` anywhere in the scope. Rust's `mut` keyword
    /// is the mutability oracle: a non-mut local cannot be reassigned,
    /// &mut-borrowed, index-assigned, or have an &mut-self method called on it,
    /// so it is provably temporally stable. A `mut` local is conservatively
    /// treated as unstable (it may be mutated in a way the syntactic tracker
    /// cannot follow, e.g. `xs[i] = v` or `xs.push(..)`).
    mut_locals: BTreeSet<String>,
}

#[derive(Debug, Clone)]
struct TemporalScope {
    local_scope: String,
    plan: TemporalPlan,
    versions: BTreeMap<String, usize>,
    ambiguous: BTreeSet<String>,
}

impl TemporalScope {
    fn new(local_scope: &str, plan: TemporalPlan) -> Self {
        Self {
            local_scope: local_scope.to_string(),
            plan,
            versions: BTreeMap::new(),
            ambiguous: BTreeSet::new(),
        }
    }

    fn local_scope(&self) -> &str {
        &self.local_scope
    }

    /// Whether `name` is a `let mut` local in this scope (conservatively
    /// unstable). A non-mut local is provably immutable and stable.
    fn is_mut_local(&self, name: &str) -> bool {
        self.plan.mut_locals.contains(name)
    }

    fn define_local(&mut self, name: &str) {
        if self.plan.versioned.contains(name) {
            let next = self.versions.get(name).copied().unwrap_or(0) + 1;
            self.versions.insert(name.to_string(), next);
            self.ambiguous.remove(name);
        }
    }

    fn mark_ambiguous(&mut self, name: &str) {
        if self.plan.versioned.contains(name) {
            self.ambiguous.insert(name.to_string());
        }
    }

    fn path_name(&self, path: &syn::Path) -> Result<String, String> {
        let name = path_to_name(path);
        if !is_unqualified_local_name(&name) || !self.plan.versioned.contains(&name) {
            return Ok(name);
        }
        if self.ambiguous.contains(&name) {
            return Err(format!(
                "ambiguous temporal identity for receiver `{name}`; skipped assertion"
            ));
        }
        match self.versions.get(&name).copied() {
            Some(version) => Ok(format!("{name}@def{version}")),
            None => Ok(name),
        }
    }
}

fn group_assertions(
    entries: Vec<AssertionEntry>,
    fallback_name: &str,
) -> Vec<(String, Vec<Rc<Formula>>)> {
    // Each entry joins the obligation named by its callsite (or the fn
    // fallback). A lifted loop is a named `<test>::loop::<var>` memento with its
    // own obligation here, mirroring the Python layer-2 lifter. Whether a
    // universal refutes a sibling point-claim is answered ONCE in the shared
    // consistency engine (which treats forall invariants as ambient), not in
    // this per-language lifter.
    let mut groups: Vec<(String, Vec<Rc<Formula>>)> = Vec::new();
    for entry in entries {
        let name = entry.name.unwrap_or_else(|| fallback_name.to_string());
        if let Some((_, atoms)) = groups
            .iter_mut()
            .find(|(group_name, _)| group_name == &name)
        {
            atoms.push(entry.atom);
        } else {
            groups.push((name, vec![entry.atom]));
        }
    }
    groups
}

/// Count assert macros reachable anywhere inside a statement list, including
/// nested in control flow, closures, and blocks. Used to produce named refusals
/// for asserts that cannot be unconditionally lifted.
/// Exhaustively counts assert-family macro invocations anywhere in a subtree,
/// using the same syn visitor the sweep uses as its denominator. Counting must
/// match that denominator exactly, otherwise the totality safety net cannot
/// detect an assert in an AST position the structured walk does not enumerate.
#[derive(Default)]
struct NestedAssertCounter {
    total: usize,
}

impl<'ast> syn::visit::Visit<'ast> for NestedAssertCounter {
    fn visit_macro(&mut self, m: &'ast syn::Macro) {
        if is_assert_macro_path(&m.path) {
            self.total += 1;
        }
        syn::visit::visit_macro(self, m);
    }
}

fn count_asserts_in_stmts(stmts: &[Stmt]) -> usize {
    let mut counter = NestedAssertCounter::default();
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut counter, stmt);
    }
    counter.total
}

/// Exhaustively count assert-family macros across a set of items (a whole
/// module subtree). Used to account a cfg-skipped module per assertion so the
/// walk logs a reason for every assert it drops, leaving no silent drop.
fn count_asserts_in_items(items: &[Item]) -> usize {
    let mut counter = NestedAssertCounter::default();
    for item in items {
        syn::visit::Visit::visit_item(&mut counter, item);
    }
    counter.total
}

/// A cfg-gated module (e.g. `#[cfg(all(test, target_has_atomic = "64"))]`) whose
/// predicate we cannot resolve is skipped, but every assertion inside it must
/// still be accounted: refuse one per assert with the cfg reason so nothing is
/// silently dropped. The remedy to discharge them is to resolve the cfg (feed
/// the build configuration), not to ignore them.
fn account_skipped_module(
    items: &[Item],
    module_name: &str,
    kind: &str,
    reason: &str,
    source_path: &str,
    out: &mut AdapterOutput,
) {
    let count = count_asserts_in_items(items);
    let skip = format!("{kind} cfg on module; skipped: {reason}");
    for _ in 0..count {
        out.assertions_refused += 1;
        out.skip_reasons.push(skip.clone());
    }
    out.warnings.push(LiftWarning {
        source_path: source_path.to_string(),
        item_name: module_name.to_string(),
        reason: format!("rust test assertions: {kind} cfg; skipped module: {reason}"),
    });
}

fn count_asserts_in_expr(expr: &Expr) -> usize {
    let mut counter = NestedAssertCounter::default();
    syn::visit::Visit::visit_expr(&mut counter, expr);
    counter.total
}

fn is_assert_macro_path(path: &syn::Path) -> bool {
    if let Some(seg) = path.segments.last() {
        // The lifter treats any macro whose name starts with assert / debug_assert
        // as an assertion (the standard six plus stdlib custom macros like
        // assert_all!, assert_none!, assert_eq_const_safe!). The nested-assert
        // counter must use the same universe as the sweep denominator so the
        // discharged + refused + silent reconciliation is exact.
        let name = seg.ident.to_string();
        name.starts_with("assert") || name.starts_with("debug_assert")
    } else {
        false
    }
}

/// If an expression is an UNCONDITIONALLY-evaluated block, return its statements
/// so the collector can recurse and lift the asserts inside (the per-fn safety
/// net still accounts anything not reached, so this never reintroduces a silent
/// drop). Sound contexts:
///   - a plain value block `{ .. }` and `unsafe { .. }` (evaluated once here)
///   - `rt.block_on(async { .. })`: block_on drives the future to completion
///     synchronously, so its top-level statements run exactly once. The async /
///     await is the ordering we drop; the assertions inside still hold.
/// A bare `async { .. }`, a closure, or a spawned future is NOT unconditional
/// (it may never run, or runs per-iteration) and is not returned here.
/// If `expr` is a call to the std intrinsic `const_eval_select((), ct, rt)`,
/// return the runtime branch fn name (the third argument, an ident). At run
/// time the intrinsic calls that fn, so its body is reached.
fn const_eval_select_runtime_target(expr: &Expr) -> Option<String> {
    let call = match expr {
        Expr::Call(c) => c,
        Expr::Paren(p) => return const_eval_select_runtime_target(&p.expr),
        Expr::Group(g) => return const_eval_select_runtime_target(&g.expr),
        _ => return None,
    };
    let Expr::Path(p) = &*call.func else {
        return None;
    };
    if p.path.segments.last()?.ident != "const_eval_select" {
        return None;
    }
    // The runtime fn is the last argument; accept the common 3-arg form.
    match call.args.last()? {
        Expr::Path(rt) => rt.path.get_ident().map(|i| i.to_string()),
        _ => None,
    }
}

/// All inner-fn names selected as a const_eval_select runtime branch in a block.
fn const_eval_select_runtime_targets(stmts: &[Stmt]) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for stmt in stmts {
        if let Stmt::Expr(e, _) = stmt {
            if let Some(name) = const_eval_select_runtime_target(e) {
                out.insert(name);
            }
        }
    }
    out
}

/// True if a block of statements mutates anything: an assignment / compound
/// assignment, a `let mut` binding, or a `&mut` borrow. A loop whose body
/// mutates is not a clean universal over the loop variable, so it is gutter.
fn loop_body_mutates(stmts: &[Stmt]) -> bool {
    #[derive(Default)]
    struct MutScan {
        mutates: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for MutScan {
        fn visit_expr_assign(&mut self, _: &'ast syn::ExprAssign) {
            self.mutates = true;
        }
        fn visit_expr_binary(&mut self, b: &'ast syn::ExprBinary) {
            if matches!(
                b.op,
                BinOp::AddAssign(_)
                    | BinOp::SubAssign(_)
                    | BinOp::MulAssign(_)
                    | BinOp::DivAssign(_)
                    | BinOp::RemAssign(_)
                    | BinOp::BitXorAssign(_)
                    | BinOp::BitAndAssign(_)
                    | BinOp::BitOrAssign(_)
                    | BinOp::ShlAssign(_)
                    | BinOp::ShrAssign(_)
            ) {
                self.mutates = true;
            }
            syn::visit::visit_expr_binary(self, b);
        }
        fn visit_expr_reference(&mut self, r: &'ast syn::ExprReference) {
            if r.mutability.is_some() {
                self.mutates = true;
            }
            syn::visit::visit_expr_reference(self, r);
        }
        fn visit_pat_ident(&mut self, p: &'ast syn::PatIdent) {
            if p.mutability.is_some() {
                self.mutates = true;
            }
            syn::visit::visit_pat_ident(self, p);
        }
    }
    let mut scan = MutScan::default();
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut scan, stmt);
    }
    scan.mutates
}

/// Substitute every free occurrence of the variable `name` in a term with
/// `repl`. Used to bind a loop variable to a quantifier's bound variable.
fn subst_var_in_term(term: &Rc<Term>, name: &str, repl: &Rc<Term>) -> Rc<Term> {
    match term.as_ref() {
        Term::Var { name: n } if n == name => repl.clone(),
        Term::Ctor { name: cname, args } => Rc::new(Term::Ctor {
            name: cname.clone(),
            args: args
                .iter()
                .map(|a| subst_var_in_term(a, name, repl))
                .collect(),
        }),
        _ => term.clone(),
    }
}

/// Substitute `name` with `repl` throughout a formula (respecting quantifier
/// shadowing: a nested quantifier binding the same name is left untouched).
fn subst_var_in_formula(formula: &Rc<Formula>, name: &str, repl: &Rc<Term>) -> Rc<Formula> {
    match formula.as_ref() {
        Formula::Atomic { name: rel, args } => Rc::new(Formula::Atomic {
            name: rel.clone(),
            args: args
                .iter()
                .map(|a| subst_var_in_term(a, name, repl))
                .collect(),
        }),
        Formula::Connective { kind, operands } => Rc::new(Formula::Connective {
            kind: kind.clone(),
            operands: operands
                .iter()
                .map(|f| subst_var_in_formula(f, name, repl))
                .collect(),
        }),
        Formula::Quantifier {
            kind,
            name: bound,
            sort,
            body,
        } => {
            let new_body = if bound == name {
                body.clone()
            } else {
                subst_var_in_formula(body, name, repl)
            };
            Rc::new(Formula::Quantifier {
                kind: kind.clone(),
                name: bound.clone(),
                sort: sort.clone(),
                body: new_body,
            })
        }
        _ => formula.clone(),
    }
}

/// Read a `for <ident> in <range> { body }` loop as the bounded universal it
/// literally states: forall x. (range_guard(x) => body(x)). The range is
/// transcribed letter for letter (start..end / start..=end); the body is lifted
/// through the normal collector, so a body that does not compute to a truth
/// value (effectful, mutated accumulator, conditional) is gutter (None here,
/// refused by the caller). Returns the quantified formula and the number of
/// body assert macros it accounts for, or None to refuse the loop.
#[allow(clippy::too_many_arguments)]
fn try_lift_for_loop_forall(
    f: &syn::ExprForLoop,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
) -> Option<(Rc<Formula>, usize, String)> {
    // The loop variable must be a plain ident (the bound variable).
    let var = match &*f.pat {
        Pat::Ident(p) if p.subpat.is_none() => p.ident.to_string(),
        _ => return None,
    };
    // The iterator domain must be a FINITE CONSTRUCTION: a closed integer range
    // `a..b` (transcribed as a forall guard) or a literal array `[e0, e1, ...]`
    // (unrolled over its constructed element terms). A runtime collection
    // (`for x in v`) is NOT constructed from source literals -- it is left to the
    // for-context refusal (named bin-2 by `for_iter_domain`).
    enum ForDomain {
        Range {
            start: Rc<Term>,
            end: Rc<Term>,
            inclusive: bool,
        },
        Array(Vec<Rc<Term>>),
    }
    let domain = match &*f.expr {
        Expr::Range(range) => {
            let (Some(start_expr), Some(end_expr)) = (&range.start, &range.end) else {
                return None;
            };
            ForDomain::Range {
                start: translate_term_in_scope(start_expr, scope).ok()?,
                end: translate_term_in_scope(end_expr, scope).ok()?,
                inclusive: matches!(range.limits, syn::RangeLimits::Closed(_)),
            }
        }
        Expr::Array(arr) => {
            // An empty array means the loop never runs -> nothing is asserted
            // (vacuously). Leave it to the refusal path rather than emit a vacuous
            // `true`. Each element must translate, or the domain is not fully
            // constructed and we refuse.
            if arr.elems.is_empty() {
                return None;
            }
            let mut elems = Vec::with_capacity(arr.elems.len());
            for e in &arr.elems {
                elems.push(translate_term_in_scope(e, scope).ok()?);
            }
            ForDomain::Array(elems)
        }
        _ => return None,
    };

    // Lift the body through the normal collector. Truth-table-or-gutter: every
    // body assert must lift cleanly (none refused, none missing) or we refuse
    // the whole loop.
    let n_body = count_asserts_in_stmts(&f.body.stmts);
    if n_body == 0 {
        return None;
    }
    // Purity gate: the body must not mutate anything. An assignment, a `let mut`,
    // or a `&mut` borrow means a value varies across iterations independently of
    // the loop variable (e.g. an accumulator `count = count + 1`), so a single
    // universal over x would be a false claim. Gutter such loops -- the
    // single-iteration view can look stable when it is not.
    if loop_body_mutates(&f.body.stmts) {
        return None;
    }
    let mut body_entries = Vec::new();
    let mut body_skipped = Vec::new();
    let mut body_lifted = 0usize;
    let mut body_helpers = HashSet::new();
    collect_assertion_entries(
        &f.body.stmts,
        scope.local_scope(),
        options,
        reducer,
        float_widths,
        &mut body_entries,
        &mut body_skipped,
        &mut body_lifted,
        &mut body_helpers,
        macro_depth,
    );
    if !body_skipped.is_empty() || body_entries.len() != n_body {
        return None;
    }
    let body_conj = and_(body_entries.iter().map(|e| e.atom.clone()).collect());

    let quantified = match domain {
        // forall x:Int. ( start <= x (< | <=) end ) => body[var := x]
        ForDomain::Range {
            start,
            end,
            inclusive,
        } => {
            let bound_var = var.clone();
            forall(Sort::int(), move |x| {
                let lower = lte(start.clone(), x.clone());
                let upper = if inclusive {
                    lte(x.clone(), end.clone())
                } else {
                    lt(x.clone(), end.clone())
                };
                let guard = and_(vec![lower, upper]);
                let body = subst_var_in_formula(&body_conj, &bound_var, &x);
                implies(guard, body)
            })
        }
        // `for x in [e0, e1, ...]` is exactly the FINITE conjunction
        // body[x:=e0] ∧ body[x:=e1] ∧ ... -- a complete unroll over the constructed
        // element terms, every instance concrete (full point-wise teeth). This is
        // the construction axiom directly: the domain is allocated at formation, so
        // `∀x ∈ {e_i}. body` IS the finite conjunction, no quantifier needed.
        ForDomain::Array(elems) => {
            let instances = elems
                .iter()
                .map(|e| subst_var_in_formula(&body_conj, &var, e))
                .collect();
            and_(instances)
        }
    };
    Some((quantified, n_body, var))
}

fn unconditional_block_stmts(expr: &Expr) -> Option<&[Stmt]> {
    match expr {
        Expr::Block(b) => Some(&b.block.stmts),
        Expr::Unsafe(u) => Some(&u.block.stmts),
        Expr::Paren(p) => unconditional_block_stmts(&p.expr),
        Expr::Group(g) => unconditional_block_stmts(&g.expr),
        Expr::MethodCall(c) if c.method == "block_on" && c.args.len() == 1 => match &c.args[0] {
            Expr::Async(a) => Some(&a.block.stmts),
            other => unconditional_block_stmts(other),
        },
        _ => None,
    }
}

#[allow(clippy::too_many_arguments)]
fn collect_assertion_entries(
    stmts: &[Stmt],
    local_scope: &str,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    entries: &mut Vec<AssertionEntry>,
    skipped: &mut Vec<String>,
    macros_lifted: &mut usize,
    reduced_helpers: &mut HashSet<String>,
    macro_depth: usize,
) {
    let temporal_plan = temporal_plan_for_stmts(stmts);
    let mut temporal_scope = TemporalScope::new(local_scope, temporal_plan);
    // const_eval_select((), compiletime, runtime) is a std intrinsic that, at
    // run time, calls its runtime fn. Find such calls in this block and the
    // inner fns they select, so the runtime branch is inlined (its asserts
    // lift) instead of refused as an unreachable inner fn.
    let runtime_targets = const_eval_select_runtime_targets(stmts);
    let local_fns: BTreeMap<String, &syn::ItemFn> = stmts
        .iter()
        .filter_map(|s| match s {
            Stmt::Item(Item::Fn(f)) => Some((f.sig.ident.to_string(), f)),
            _ => None,
        })
        .collect();
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => {
                update_float_width_scope_for_pat(&local.pat, float_widths);
                if let Some(init) = &local.init {
                    // If the initializer is an unconditional block (a plain block
                    // or a block_on(async {..})), recurse and lift its asserts;
                    // the per-fn safety net accounts anything not reached, so no
                    // silent drop. Otherwise the asserts (closures, conditionals)
                    // are not top-level point-wise: refuse them.
                    if let Some(stmts) = unconditional_block_stmts(&init.expr) {
                        collect_assertion_entries(
                            stmts,
                            local_scope,
                            options,
                            reducer,
                            float_widths,
                            entries,
                            skipped,
                            macros_lifted,
                            reduced_helpers,
                            macro_depth,
                        );
                    } else {
                        let mut count = count_asserts_in_expr(&init.expr);
                        if let Some((_, diverge)) = &init.diverge {
                            count += count_asserts_in_expr(diverge);
                        }
                        for _ in 0..count {
                            skipped.push(
                                "assertion inside a let-initializer expression: not a top-level point-wise assertion; released to layer 0"
                                    .to_string(),
                            );
                        }
                    }
                }
            }
            Stmt::Macro(m) => match cfg_eval_for_attrs(&m.attrs, options) {
                CfgEval::Active => {
                    // Known assertion macros are lowered by their tuned arm
                    // first. If no arm lifts it, walk into the definition: when
                    // we hold the macro's source, expand it and reduce the
                    // expansion. One source macro is one accounting unit.
                    let before_e = entries.len();
                    let before_s = skipped.len();
                    collect_macro(
                        &m.mac.path,
                        m.mac.tokens.clone(),
                        &temporal_scope,
                        &*float_widths,
                        options,
                        entries,
                        skipped,
                    );
                    if entries.len() > before_e {
                        *macros_lifted += 1;
                    } else {
                        match try_macro_expansion_entries(
                            &m.mac.path,
                            &m.mac.tokens,
                            reducer,
                            local_scope,
                            options,
                            float_widths,
                            macro_depth,
                        ) {
                            Some(Ok(es)) => {
                                skipped.truncate(before_s);
                                if !es.is_empty() {
                                    *macros_lifted += 1;
                                }
                                entries.extend(es);
                            }
                            Some(Err(reason)) => {
                                skipped.truncate(before_s);
                                // Account a refusal only for assertion macros. A
                                // non-assertion macro (task_local!, pin!, ...)
                                // that does not expand to FOL is not an assertion
                                // and is ignored, not refused.
                                if is_assert_macro_path(&m.mac.path) {
                                    skipped.push(reason);
                                }
                            }
                            None => {}
                        }
                    }
                }
                CfgEval::Inactive(reason) => {
                    skipped.push(format!("inactive cfg on assertion; skipped: {reason}"));
                }
                CfgEval::Ambiguous(reason) => {
                    skipped.push(format!("ambiguous cfg on assertion; skipped: {reason}"));
                }
            },
            Stmt::Expr(Expr::Macro(m), _) => match cfg_eval_for_attrs(&m.attrs, options) {
                CfgEval::Active => {
                    // Known assertion macros are lowered by their tuned arm
                    // first. If no arm lifts it, walk into the definition: when
                    // we hold the macro's source, expand it and reduce the
                    // expansion. One source macro is one accounting unit.
                    let before_e = entries.len();
                    let before_s = skipped.len();
                    collect_macro(
                        &m.mac.path,
                        m.mac.tokens.clone(),
                        &temporal_scope,
                        &*float_widths,
                        options,
                        entries,
                        skipped,
                    );
                    if entries.len() > before_e {
                        *macros_lifted += 1;
                    } else {
                        match try_macro_expansion_entries(
                            &m.mac.path,
                            &m.mac.tokens,
                            reducer,
                            local_scope,
                            options,
                            float_widths,
                            macro_depth,
                        ) {
                            Some(Ok(es)) => {
                                skipped.truncate(before_s);
                                if !es.is_empty() {
                                    *macros_lifted += 1;
                                }
                                entries.extend(es);
                            }
                            Some(Err(reason)) => {
                                skipped.truncate(before_s);
                                // Account a refusal only for assertion macros. A
                                // non-assertion macro (task_local!, pin!, ...)
                                // that does not expand to FOL is not an assertion
                                // and is ignored, not refused.
                                if is_assert_macro_path(&m.mac.path) {
                                    skipped.push(reason);
                                }
                            }
                            None => {}
                        }
                    }
                }
                CfgEval::Inactive(reason) => {
                    skipped.push(format!("inactive cfg on assertion; skipped: {reason}"));
                }
                CfgEval::Ambiguous(reason) => {
                    skipped.push(format!("ambiguous cfg on assertion; skipped: {reason}"));
                }
            },
            Stmt::Expr(expr, _) if assertion_call_name(expr).is_some() => {
                match reduce_assertion_expr(
                    expr,
                    reducer,
                    &temporal_scope,
                    &*float_widths,
                    options,
                    MAX_ASSERTION_REDUCTION_DEPTH,
                    reduced_helpers,
                ) {
                    Ok(reduced_entries) => {
                        if !reduced_entries.is_empty() {
                            *macros_lifted += 1;
                        }
                        entries.extend(reduced_entries);
                    }
                    Err(reason) => skipped.push(reason),
                }
            }
            // Unconditional plain block: recurse and lift normally.
            Stmt::Expr(Expr::Block(b), _) => {
                collect_assertion_entries(
                    &b.block.stmts,
                    local_scope,
                    options,
                    reducer,
                    float_widths,
                    entries,
                    skipped,
                    macros_lifted,
                    reduced_helpers,
                    macro_depth,
                );
            }
            // Unconditional unsafe block: recurse and lift normally.
            Stmt::Expr(Expr::Unsafe(u), _) => {
                collect_assertion_entries(
                    &u.block.stmts,
                    local_scope,
                    options,
                    reducer,
                    float_widths,
                    entries,
                    skipped,
                    macros_lifted,
                    reduced_helpers,
                    macro_depth,
                );
            }
            // Control-flow contexts: asserts are conditional or parametric; refuse.
            Stmt::Expr(Expr::ForLoop(f), _) => {
                // A bounded loop is the universal it states: read the range as a
                // guard and lift forall x. (guard => body). If the body does not
                // wholly compute to truth values, gutter the loop (refuse).
                if let Some((quantified, n, var)) = try_lift_for_loop_forall(
                    f,
                    &temporal_scope,
                    options,
                    reducer,
                    float_widths,
                    macro_depth,
                ) {
                    // Name the loop memento `<test>::loop::<var>`, mirroring the
                    // Python reference (layer2.py PATTERN 1). A named universal is
                    // federatable and the engine conjoins it ambiently.
                    entries.push(AssertionEntry {
                        name: Some(format!("{}::loop::{}", temporal_scope.local_scope(), var)),
                        atom: quantified,
                    });
                    *macros_lifted += n;
                } else {
                    // Provenance for the bin-1/bin-2 sort: a refused for-loop is
                    // either over a CONSTRUCTED domain (literal range/array -- the
                    // forall lift exists, so the refusal is body-side) or over an
                    // OPAQUE collection (RUNTIME data, bin-2). For a literal domain
                    // the refusal is body-side -- but the BODY itself may assert over
                    // OPAQUE runtime data (e.g. `assert_eq!(some_call().get(k), ..)`),
                    // which is bin-2 EVEN WITH a literal domain: the iterated values
                    // are literals, but the ASSERTED values are runtime. So re-run the
                    // body collector and read its own refusal reasons: if any body
                    // assert refused over OPAQUE data, the loop is bin-2; otherwise it
                    // is a genuine missing-constructor bin-1 (let-SSA / format! / ...).
                    let domain = for_iter_domain(&f.expr);
                    let count = count_asserts_in_stmts(&f.body.stmts);
                    let tag = if domain.contains("LITERAL") {
                        let mut be = Vec::new();
                        let mut bs = Vec::new();
                        let mut bl = 0usize;
                        let mut bh = HashSet::new();
                        collect_assertion_entries(
                            &f.body.stmts,
                            temporal_scope.local_scope(),
                            options,
                            reducer,
                            float_widths,
                            &mut be,
                            &mut bs,
                            &mut bl,
                            &mut bh,
                            macro_depth,
                        );
                        let body_over_opaque = bs.iter().any(|r| {
                            r.contains("OPAQUE")
                                || r.contains("ambiguous temporal identity")
                                || r.contains("mutable container")
                        });
                        if body_over_opaque {
                            "a LITERAL array but with a body assertion over OPAQUE runtime data"
                                .to_string()
                        } else {
                            domain.to_string()
                        }
                    } else {
                        domain.to_string()
                    };
                    for _ in 0..count {
                        skipped.push(format!(
                            "assertion under for context over {tag}; \
                             not unconditional point-wise; released to layer 0"
                        ));
                    }
                }
            }
            Stmt::Expr(Expr::While(w), _) => {
                let body_count = count_asserts_in_stmts(&w.body.stmts);
                let cond_count = count_asserts_in_expr(&w.cond);
                let total = body_count + cond_count;
                for _ in 0..total {
                    skipped.push(
                        "assertion under while context: not unconditional point-wise; released to layer 0"
                            .to_string(),
                    );
                }
            }
            Stmt::Expr(Expr::Loop(l), _) => {
                refuse_nested_asserts_in_stmts(&l.body.stmts, "loop", skipped);
            }
            Stmt::Expr(Expr::If(i), _) => {
                // Panic locus: `if let PAT = e { .. } else { panic!() }` asserts
                // e matches PAT. Lift it; otherwise refuse the conditional.
                if let Some(entry) = panic_locus_if_entry(i, &temporal_scope) {
                    entries.push(entry);
                    *macros_lifted += 1;
                } else {
                    let count = count_asserts_in_stmts(&i.then_branch.stmts)
                        + i.else_branch
                            .as_ref()
                            .map_or(0, |(_, e)| count_asserts_in_expr(e));
                    for _ in 0..count {
                        skipped.push(
                            "assertion under if context: not unconditional point-wise; released to layer 0"
                                .to_string(),
                        );
                    }
                }
            }
            Stmt::Expr(Expr::Match(m), _) => {
                // Panic locus: a match whose every arm but one diverges asserts
                // the scrutinee matches the surviving arm. Lift it; otherwise
                // refuse the conditional.
                if let Some(entry) = panic_locus_match_entry(m, &temporal_scope) {
                    entries.push(entry);
                    *macros_lifted += 1;
                } else {
                    let count: usize = m.arms.iter().map(|a| count_asserts_in_expr(&a.body)).sum();
                    for _ in 0..count {
                        skipped.push(
                            "assertion under match context: not unconditional point-wise; released to layer 0"
                                .to_string(),
                        );
                    }
                }
            }
            Stmt::Expr(Expr::Closure(c), _) => {
                let count = count_asserts_in_expr(&c.body);
                for _ in 0..count {
                    skipped.push(
                        "assertion under closure context: not unconditional point-wise; released to layer 0"
                            .to_string(),
                    );
                }
            }
            // Unconditional const block: recurse and lift normally.
            // const { ... } is always evaluated; lifting its asserts is sound.
            Stmt::Expr(Expr::Const(c), _) => {
                collect_assertion_entries(
                    &c.block.stmts,
                    local_scope,
                    options,
                    reducer,
                    float_widths,
                    entries,
                    skipped,
                    macros_lifted,
                    reduced_helpers,
                    macro_depth,
                );
            }
            // Inner fn definitions inside a test fn: their asserts are only
            // reachable via a call inside the test body; refuse them.
            Stmt::Item(syn::Item::Fn(inner_fn)) => {
                let fn_name = inner_fn.sig.ident.to_string();
                // An inner fn selected as the runtime branch of const_eval_select
                // is reached at run time; it is inlined where the call appears,
                // so do not refuse it here (that would double-count).
                if runtime_targets.contains(&fn_name) {
                    continue;
                }
                let count = count_asserts_in_stmts(&inner_fn.block.stmts);
                for _ in 0..count {
                    skipped.push(format!(
                        "assertion in non-#[test] item {fn_name}: reachable only via call-site inlining; released to layer 0"
                    ));
                }
            }
            // Totality fallback: any other statement shape (a bare method-call
            // statement with a closure argument, an expression statement we do
            // not lift, etc.) may still contain nested asserts. Count and refuse
            // them so nothing is silently dropped. count_asserts_in_stmts only
            // runs here for statements no specific arm matched, so there is no
            // double counting.
            other => {
                // A bare expression statement that is an unconditional block
                // (e.g. `rt.block_on(async { .. })`) runs once: recurse and lift
                // its asserts. The per-fn safety net accounts anything not
                // reached, so no silent drop. Otherwise refuse.
                let recursed = if let Stmt::Expr(e, _) = other {
                    // const_eval_select((), compiletime, runtime): inline the
                    // runtime branch (the fn called at run time).
                    let select_target = const_eval_select_runtime_target(e)
                        .filter(|name| local_fns.contains_key(name));
                    if let Some(name) = select_target {
                        collect_assertion_entries(
                            &local_fns[&name].block.stmts,
                            local_scope,
                            options,
                            reducer,
                            float_widths,
                            entries,
                            skipped,
                            macros_lifted,
                            reduced_helpers,
                            macro_depth,
                        );
                        true
                    } else if let Some(stmts) = unconditional_block_stmts(e) {
                        collect_assertion_entries(
                            stmts,
                            local_scope,
                            options,
                            reducer,
                            float_widths,
                            entries,
                            skipped,
                            macros_lifted,
                            reduced_helpers,
                            macro_depth,
                        );
                        true
                    } else {
                        false
                    }
                } else {
                    false
                };
                if !recursed {
                    let count = count_asserts_in_stmts(std::slice::from_ref(other));
                    for _ in 0..count {
                        skipped.push(
                            "assertion nested in an unlifted expression statement: not a top-level point-wise assertion; released to layer 0"
                                .to_string(),
                        );
                    }
                }
            }
        }
        advance_temporal_scope_for_stmt(stmt, &mut temporal_scope);
    }
}

/// Classify a refused for-loop's iterator domain for the bin-1 / bin-2 sort.
/// `try_lift_for_loop_forall` already lifts a closed-range loop as a `forall`, so
/// a loop that reaches the refusal is one it could NOT lift:
///   - a literal range `a..b` / `a..=b` or a literal array `[..]`: the domain IS
///     a finite construction (the forall lift exists) -- the refusal is body-side
///     (mutation, or a body assert that did not lift). This is **bin-1**, drainable
///     by teaching the body, NOT by inventing a domain.
///   - anything else (`for x in coll`, `for x in v.iter()`, a field, a call): the
///     loop ranges over a collection whose ELEMENTS are runtime data, not
///     constructed from source literals. No finite construction to walk -> **bin-2**.
fn for_iter_domain(expr: &Expr) -> &'static str {
    match expr {
        Expr::Range(r) if r.start.is_some() && r.end.is_some() => {
            "a LITERAL range (bin-1: domain constructed, body not yet point-wise liftable)"
        }
        Expr::Array(_) | Expr::Repeat(_) => {
            "a LITERAL array (bin-1: domain constructed, body not yet point-wise liftable)"
        }
        Expr::Reference(r) => for_iter_domain(&r.expr),
        Expr::Paren(p) => for_iter_domain(&p.expr),
        Expr::Group(g) => for_iter_domain(&g.expr),
        _ => "an OPAQUE collection (bin-2: runtime data, not constructed from source literals)",
    }
}

/// If `expr` is a CLOSURE-BEARING iterator/Option adaptor -- a quantifier
/// (`.all`/`.any`) or a transform/search (`.map`/`.find`/`.filter`/...) -- return a
/// provenance-named refusal (literal-collection -> bin-1, opaque -> bin-2), reusing
/// `for_iter_domain` on the underlying collection. The closure predicate ranges over
/// the receiver's ELEMENTS, which are runtime data when the receiver is opaque; the
/// provenance makes that bin-2 PROVEN rather than presumed from the bare `|x|` shape.
/// Returns None for any non-adaptor call (handled by the ordinary term path).
fn closure_adaptor_refusal(expr: &Expr) -> Option<String> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    let is_adaptor = matches!(
        method.as_str(),
        "all" | "any" | "map" | "find" | "filter" | "filter_map" | "find_map" | "position"
    );
    if !is_adaptor {
        return None;
    }
    // At least one closure argument (the predicate / transform). A `.map(path_fn)`
    // with a function path (not a closure) is left to the ordinary term path.
    if !call.args.iter().any(|a| matches!(a, Expr::Closure(_))) {
        return None;
    }
    let collection = iter_adaptor_base(&call.receiver);
    let domain = for_iter_domain(collection);
    Some(format!(
        "iterator/option adaptor `.{method}(|..| ..)` over {domain}; not yet lifted; \
         released to layer 0"
    ))
}

/// Strip a trailing element-producing adaptor (`.iter()`, `.into_iter()`,
/// `.iter_mut()`, `.chars()`, `.bytes()`, `.keys()`, `.values()`) to reveal the
/// underlying collection expression, so its literal/opaque provenance can be read.
fn iter_adaptor_base(expr: &Expr) -> &Expr {
    if let Expr::MethodCall(c) = expr {
        if c.args.is_empty()
            && matches!(
                c.method.to_string().as_str(),
                "iter" | "into_iter" | "iter_mut" | "chars" | "bytes" | "keys" | "values"
            )
        {
            return iter_adaptor_base(&c.receiver);
        }
    }
    expr
}

fn refuse_nested_asserts_in_stmts(stmts: &[Stmt], context: &str, skipped: &mut Vec<String>) {
    let count = count_asserts_in_stmts(stmts);
    for _ in 0..count {
        skipped.push(format!(
            "assertion under {context} context: not unconditional point-wise; released to layer 0"
        ));
    }
}

/// Account for assert macros inside an item-level const/static initializer by
/// emitting one named refusal per assert. Keeps the totality invariant for
/// compile-time asserts written as `const _: () = assert!(...)`.
fn refuse_item_assertions(
    expr: &Expr,
    kind: &str,
    source_path: &str,
    modules: &[String],
    out: &mut AdapterOutput,
) {
    let count = count_asserts_in_expr(expr);
    if count == 0 {
        return;
    }
    let reason = format!("{kind} assertion: compile-time const/static assert; released to layer 0");
    for _ in 0..count {
        out.assertions_refused += 1;
        out.skip_reasons.push(reason.clone());
    }
    out.warnings.push(LiftWarning {
        source_path: source_path.to_string(),
        item_name: scoped_test_name(source_path, modules, kind),
        reason: format!(
            "rust test assertions: unsupported assertion surface; released to layer 0: {reason}"
        ),
    });
}

fn temporal_plan_for_stmts(stmts: &[Stmt]) -> TemporalPlan {
    let mut definitions = BTreeMap::<String, usize>::new();
    let mut ambiguous = BTreeSet::<String>::new();
    let mut mut_locals = BTreeSet::<String>::new();
    for stmt in stmts {
        for name in deterministic_definition_names(stmt) {
            *definitions.entry(name).or_insert(0) += 1;
        }
        for name in ambiguous_boundary_names_in_stmt(stmt) {
            ambiguous.insert(name);
        }
        collect_mut_binding_names_in_stmt(stmt, &mut mut_locals);
    }
    let versioned = definitions
        .into_iter()
        .filter_map(|(name, count)| (count > 1 || ambiguous.contains(&name)).then_some(name))
        .collect();
    TemporalPlan {
        versioned,
        mut_locals,
    }
}

/// Collect `let mut <name>` binding names in a statement (recursing into nested
/// blocks/control-flow). These are the conservatively-unstable locals.
fn collect_mut_binding_names_in_stmt(stmt: &Stmt, out: &mut BTreeSet<String>) {
    if let Stmt::Local(local) = stmt {
        collect_mut_pat_idents(&local.pat, out);
    }
}

fn collect_mut_pat_idents(pat: &Pat, out: &mut BTreeSet<String>) {
    match pat {
        Pat::Ident(ident) => {
            if ident.mutability.is_some() {
                out.insert(ident.ident.to_string());
            }
            if let Some((_, sub)) = &ident.subpat {
                collect_mut_pat_idents(sub, out);
            }
        }
        Pat::Reference(r) => collect_mut_pat_idents(&r.pat, out),
        Pat::Tuple(t) => t.elems.iter().for_each(|e| collect_mut_pat_idents(e, out)),
        Pat::TupleStruct(t) => t.elems.iter().for_each(|e| collect_mut_pat_idents(e, out)),
        Pat::Paren(p) => collect_mut_pat_idents(&p.pat, out),
        Pat::Type(t) => collect_mut_pat_idents(&t.pat, out),
        _ => {}
    }
}

fn advance_temporal_scope_for_stmt(stmt: &Stmt, scope: &mut TemporalScope) {
    for name in deterministic_definition_names(stmt) {
        scope.define_local(&name);
    }
    for name in ambiguous_boundary_names_in_stmt(stmt) {
        scope.mark_ambiguous(&name);
    }
}

fn deterministic_definition_names(stmt: &Stmt) -> Vec<String> {
    let mut out = BTreeSet::new();
    match stmt {
        Stmt::Local(local) if local.init.is_some() => {
            for name in pat_idents(&local.pat) {
                out.insert(name);
            }
        }
        Stmt::Expr(expr, _) if !is_temporal_control_flow_expr(expr) => {
            if let Some(name) = deterministic_assignment_name(expr) {
                out.insert(name);
            }
            collect_method_receiver_names(expr, &mut out);
        }
        _ => {}
    }
    out.into_iter().collect()
}

fn deterministic_assignment_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Assign(assign) => simple_path_name(&assign.left),
        Expr::Binary(binary) if is_assignment_binop(&binary.op) => simple_path_name(&binary.left),
        Expr::Paren(paren) => deterministic_assignment_name(&paren.expr),
        Expr::Group(group) => deterministic_assignment_name(&group.expr),
        _ => None,
    }
}

fn ambiguous_boundary_names_in_stmt(stmt: &Stmt) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    match stmt {
        Stmt::Local(local) => {
            if let Some(init) = &local.init {
                collect_reference_alias_names_in_expr(&init.expr, &mut out);
            }
        }
        Stmt::Expr(expr, _) => {
            collect_reference_alias_names_in_expr(expr, &mut out);
            collect_ambiguous_control_flow_names_in_expr(expr, &mut out);
        }
        _ => {}
    }
    out
}

fn collect_ambiguous_control_flow_names_in_expr(expr: &Expr, out: &mut BTreeSet<String>) {
    match expr {
        Expr::If(expr_if) => {
            collect_ambiguous_boundary_names_in_block(&expr_if.then_branch, out);
            if let Some((_, else_branch)) = &expr_if.else_branch {
                collect_ambiguous_names_in_expr(else_branch, out);
            }
        }
        Expr::ForLoop(expr_for) => collect_ambiguous_boundary_names_in_block(&expr_for.body, out),
        Expr::Loop(expr_loop) => collect_ambiguous_boundary_names_in_block(&expr_loop.body, out),
        Expr::While(expr_while) => collect_ambiguous_boundary_names_in_block(&expr_while.body, out),
        Expr::Match(expr_match) => {
            for arm in &expr_match.arms {
                collect_ambiguous_names_in_expr(&arm.body, out);
            }
        }
        Expr::Block(expr_block) => {
            collect_ambiguous_boundary_names_in_block(&expr_block.block, out)
        }
        _ => {}
    }
}

fn collect_ambiguous_boundary_names_in_block(block: &syn::Block, out: &mut BTreeSet<String>) {
    for stmt in &block.stmts {
        match stmt {
            Stmt::Local(local) if local.init.is_some() => {
                for name in pat_idents(&local.pat) {
                    out.insert(name);
                }
                if let Some(init) = &local.init {
                    collect_reference_alias_names_in_expr(&init.expr, out);
                }
            }
            Stmt::Expr(expr, _) => collect_ambiguous_names_in_expr(expr, out),
            _ => {}
        }
    }
}

fn collect_ambiguous_names_in_expr(expr: &Expr, out: &mut BTreeSet<String>) {
    if let Some(name) = deterministic_assignment_name(expr) {
        out.insert(name);
        return;
    }
    collect_reference_alias_names_in_expr(expr, out);
    collect_method_receiver_names(expr, out);
    match expr {
        Expr::Block(expr_block) => {
            collect_ambiguous_boundary_names_in_block(&expr_block.block, out)
        }
        Expr::If(expr_if) => {
            collect_ambiguous_boundary_names_in_block(&expr_if.then_branch, out);
            if let Some((_, else_branch)) = &expr_if.else_branch {
                collect_ambiguous_names_in_expr(else_branch, out);
            }
        }
        Expr::ForLoop(expr_for) => collect_ambiguous_boundary_names_in_block(&expr_for.body, out),
        Expr::Loop(expr_loop) => collect_ambiguous_boundary_names_in_block(&expr_loop.body, out),
        Expr::While(expr_while) => collect_ambiguous_boundary_names_in_block(&expr_while.body, out),
        Expr::Match(expr_match) => {
            for arm in &expr_match.arms {
                collect_ambiguous_names_in_expr(&arm.body, out);
            }
        }
        Expr::Paren(paren) => collect_ambiguous_names_in_expr(&paren.expr, out),
        Expr::Group(group) => collect_ambiguous_names_in_expr(&group.expr, out),
        _ => {}
    }
}

fn collect_reference_alias_names_in_expr(expr: &Expr, out: &mut BTreeSet<String>) {
    match expr {
        Expr::Reference(reference) => {
            if let Some(name) = simple_path_name(&reference.expr) {
                out.insert(name);
            } else {
                collect_reference_alias_names_in_expr(&reference.expr, out);
            }
        }
        Expr::MethodCall(call) => {
            collect_reference_alias_names_in_expr(&call.receiver, out);
            for arg in &call.args {
                collect_reference_alias_names_in_expr(arg, out);
            }
        }
        Expr::Call(call) => {
            collect_reference_alias_names_in_expr(&call.func, out);
            for arg in &call.args {
                collect_reference_alias_names_in_expr(arg, out);
            }
        }
        Expr::Await(await_expr) => collect_reference_alias_names_in_expr(&await_expr.base, out),
        Expr::Cast(cast) => collect_reference_alias_names_in_expr(&cast.expr, out),
        Expr::Field(field) => collect_reference_alias_names_in_expr(&field.base, out),
        Expr::Binary(binary) => {
            collect_reference_alias_names_in_expr(&binary.left, out);
            collect_reference_alias_names_in_expr(&binary.right, out);
        }
        Expr::Array(array) => {
            for elem in &array.elems {
                collect_reference_alias_names_in_expr(elem, out);
            }
        }
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_reference_alias_names_in_expr(elem, out);
            }
        }
        Expr::Range(range) => {
            if let Some(start) = &range.start {
                collect_reference_alias_names_in_expr(start, out);
            }
            if let Some(end) = &range.end {
                collect_reference_alias_names_in_expr(end, out);
            }
        }
        Expr::Assign(assign) => {
            collect_reference_alias_names_in_expr(&assign.left, out);
            collect_reference_alias_names_in_expr(&assign.right, out);
        }
        Expr::Paren(paren) => collect_reference_alias_names_in_expr(&paren.expr, out),
        Expr::Group(group) => collect_reference_alias_names_in_expr(&group.expr, out),
        _ => {}
    }
}

fn pat_idents(pat: &Pat) -> Vec<String> {
    let mut out = Vec::new();
    collect_pat_idents(pat, &mut out);
    out
}

fn collect_pat_idents(pat: &Pat, out: &mut Vec<String>) {
    match pat {
        Pat::Ident(ident) => out.push(ident.ident.to_string()),
        Pat::Reference(reference) => collect_pat_idents(&reference.pat, out),
        Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_pat_idents(elem, out);
            }
        }
        Pat::TupleStruct(tuple) => {
            for elem in &tuple.elems {
                collect_pat_idents(elem, out);
            }
        }
        Pat::Struct(strukt) => {
            for field in &strukt.fields {
                collect_pat_idents(&field.pat, out);
            }
        }
        Pat::Slice(slice) => {
            for elem in &slice.elems {
                collect_pat_idents(elem, out);
            }
        }
        Pat::Or(or_pat) => {
            for case in &or_pat.cases {
                collect_pat_idents(case, out);
            }
        }
        Pat::Paren(paren) => collect_pat_idents(&paren.pat, out),
        Pat::Type(ty) => collect_pat_idents(&ty.pat, out),
        _ => {}
    }
}

fn simple_path_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) if path.qself.is_none() => {
            path.path.get_ident().map(|ident| ident.to_string())
        }
        Expr::Paren(paren) => simple_path_name(&paren.expr),
        Expr::Group(group) => simple_path_name(&group.expr),
        _ => None,
    }
}

fn is_temporal_control_flow_expr(expr: &Expr) -> bool {
    matches!(
        expr,
        Expr::If(_) | Expr::ForLoop(_) | Expr::Loop(_) | Expr::While(_) | Expr::Match(_)
    )
}

fn collect_method_receiver_names(expr: &Expr, out: &mut BTreeSet<String>) {
    match expr {
        Expr::MethodCall(call) => {
            if let Some(name) = simple_path_name(&call.receiver) {
                out.insert(name);
            } else {
                collect_method_receiver_names(&call.receiver, out);
            }
            for arg in &call.args {
                collect_method_receiver_names(arg, out);
            }
        }
        Expr::Call(call) => {
            for arg in &call.args {
                collect_method_receiver_names(arg, out);
            }
        }
        Expr::Await(await_expr) => collect_method_receiver_names(&await_expr.base, out),
        Expr::Reference(reference) => collect_method_receiver_names(&reference.expr, out),
        Expr::Cast(cast) => collect_method_receiver_names(&cast.expr, out),
        Expr::Field(field) => collect_method_receiver_names(&field.base, out),
        Expr::Binary(binary) => {
            collect_method_receiver_names(&binary.left, out);
            collect_method_receiver_names(&binary.right, out);
        }
        Expr::Array(array) => {
            for elem in &array.elems {
                collect_method_receiver_names(elem, out);
            }
        }
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_method_receiver_names(elem, out);
            }
        }
        Expr::Range(range) => {
            if let Some(start) = &range.start {
                collect_method_receiver_names(start, out);
            }
            if let Some(end) = &range.end {
                collect_method_receiver_names(end, out);
            }
        }
        Expr::Paren(paren) => collect_method_receiver_names(&paren.expr, out),
        Expr::Group(group) => collect_method_receiver_names(&group.expr, out),
        _ => {}
    }
}

fn is_assignment_binop(op: &BinOp) -> bool {
    matches!(
        op,
        BinOp::AddAssign(_)
            | BinOp::SubAssign(_)
            | BinOp::MulAssign(_)
            | BinOp::DivAssign(_)
            | BinOp::RemAssign(_)
            | BinOp::BitXorAssign(_)
            | BinOp::BitAndAssign(_)
            | BinOp::BitOrAssign(_)
            | BinOp::ShlAssign(_)
            | BinOp::ShrAssign(_)
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum CfgEval {
    Active,
    Inactive(String),
    Ambiguous(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum CfgPredicate {
    Name(String),
    KeyValue(String, String),
    All(Vec<CfgPredicate>),
    Any(Vec<CfgPredicate>),
    Not(Box<CfgPredicate>),
}

impl Parse for CfgPredicate {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let path: syn::Path = input.parse()?;
        let name = path_to_name(&path);
        if input.peek(Token![=]) {
            let _: Token![=] = input.parse()?;
            let value: syn::LitStr = input.parse()?;
            return Ok(CfgPredicate::KeyValue(name, value.value()));
        }
        if input.peek(syn::token::Paren) {
            let content;
            syn::parenthesized!(content in input);
            let args = Punctuated::<CfgPredicate, Token![,]>::parse_terminated(&content)?
                .into_iter()
                .collect::<Vec<_>>();
            return match name.as_str() {
                "all" => Ok(CfgPredicate::All(args)),
                "any" => Ok(CfgPredicate::Any(args)),
                "not" if args.len() == 1 => Ok(CfgPredicate::Not(Box::new(
                    args.into_iter().next().unwrap(),
                ))),
                "not" => Err(syn::Error::new_spanned(
                    path,
                    "cfg not(...) expects exactly one predicate",
                )),
                _ => Err(syn::Error::new_spanned(
                    path,
                    "unsupported cfg predicate function",
                )),
            };
        }
        Ok(CfgPredicate::Name(name))
    }
}

impl fmt::Display for CfgPredicate {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CfgPredicate::Name(name) => f.write_str(name),
            CfgPredicate::KeyValue(key, value) => write!(f, "{key} = {value:?}"),
            CfgPredicate::All(predicates) => write!(
                f,
                "all({})",
                predicates
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            CfgPredicate::Any(predicates) => write!(
                f,
                "any({})",
                predicates
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            CfgPredicate::Not(predicate) => write!(f, "not({predicate})"),
        }
    }
}

fn cfg_eval_for_attrs(attrs: &[syn::Attribute], options: &LiftOptions) -> CfgEval {
    let mut saw_cfg = false;
    for attr in attrs {
        if !attr.path().is_ident("cfg") {
            continue;
        }
        saw_cfg = true;
        let predicate = match attr.parse_args::<CfgPredicate>() {
            Ok(predicate) => predicate,
            Err(e) => {
                return CfgEval::Ambiguous(format!(
                    "cannot parse cfg `{}`: {e}",
                    attr.to_token_stream()
                ));
            }
        };
        match cfg_eval_predicate(&predicate, options.target_cfg.as_ref()) {
            CfgEval::Active => {}
            CfgEval::Inactive(reason) => return CfgEval::Inactive(reason),
            CfgEval::Ambiguous(reason) => return CfgEval::Ambiguous(reason),
        }
    }
    if saw_cfg {
        CfgEval::Active
    } else {
        CfgEval::Active
    }
}

fn cfg_eval_predicate(predicate: &CfgPredicate, target_cfg: Option<&TargetCfg>) -> CfgEval {
    match predicate {
        CfgPredicate::Name(name) => {
            if name == "test" {
                return CfgEval::Active;
            }
            let Some(target_cfg) = target_cfg else {
                return CfgEval::Ambiguous(format!(
                    "no explicit target cfg facts for `{predicate}`"
                ));
            };
            if target_cfg.contains_name(name) {
                CfgEval::Active
            } else {
                CfgEval::Inactive(predicate.to_string())
            }
        }
        CfgPredicate::KeyValue(key, value) => {
            let Some(target_cfg) = target_cfg else {
                return CfgEval::Ambiguous(format!(
                    "no explicit target cfg facts for `{predicate}`"
                ));
            };
            if target_cfg.contains_key_value(key, value) {
                CfgEval::Active
            } else {
                CfgEval::Inactive(predicate.to_string())
            }
        }
        CfgPredicate::All(predicates) => {
            let mut ambiguous = None;
            for child in predicates {
                match cfg_eval_predicate(child, target_cfg) {
                    CfgEval::Active => {}
                    CfgEval::Inactive(reason) => return CfgEval::Inactive(reason),
                    CfgEval::Ambiguous(reason) => {
                        ambiguous.get_or_insert(reason);
                    }
                }
            }
            if let Some(reason) = ambiguous {
                CfgEval::Ambiguous(reason)
            } else {
                CfgEval::Active
            }
        }
        CfgPredicate::Any(predicates) => {
            let mut inactive = Vec::new();
            let mut ambiguous = None;
            for child in predicates {
                match cfg_eval_predicate(child, target_cfg) {
                    CfgEval::Active => return CfgEval::Active,
                    CfgEval::Inactive(reason) => inactive.push(reason),
                    CfgEval::Ambiguous(reason) => {
                        ambiguous.get_or_insert(reason);
                    }
                }
            }
            if let Some(reason) = ambiguous {
                CfgEval::Ambiguous(reason)
            } else {
                CfgEval::Inactive(format!("any inactive: {}", inactive.join("; ")))
            }
        }
        CfgPredicate::Not(child) => match cfg_eval_predicate(child, target_cfg) {
            CfgEval::Active => CfgEval::Inactive(predicate.to_string()),
            CfgEval::Inactive(_) => CfgEval::Active,
            CfgEval::Ambiguous(reason) => CfgEval::Ambiguous(reason),
        },
    }
}

fn assertion_call_name(expr: &Expr) -> Option<String> {
    let Expr::Call(call) = expr else {
        return None;
    };
    let name = simple_call_name(call)?;
    name.starts_with("assert").then_some(name)
}

fn simple_call_name(call: &syn::ExprCall) -> Option<String> {
    let Expr::Path(path) = call.func.as_ref() else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.get_ident().map(|ident| ident.to_string())
}

fn reduce_assertion_expr(
    expr: &Expr,
    reducer: &ReductionCtx<'_>,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
    depth: usize,
    reduced_helpers: &mut HashSet<String>,
) -> Result<Vec<AssertionEntry>, String> {
    if depth == 0 {
        return Err(format!(
            "assertion reduction depth exhausted at `{}`; skipped assertion",
            token_key(expr)
        ));
    }
    match expr {
        Expr::Call(call) => {
            // Base lowerer: ptr::eq / core::ptr::eq / std::ptr::eq is a primitive
            // expression reducer. Dispatch it directly so helper bodies that call
            // assert!(ptr::eq(a, b)) reduce through this path rather than requiring
            // the dedicated translate_pointer_eq_assertion pre-filter arm.
            let callee = expr_head_key(&call.func);
            if matches!(
                callee.as_str(),
                "core::ptr::eq" | "ptr::eq" | "std::ptr::eq"
            ) {
                return translate_pointer_eq_assertion(expr, scope)?
                    .ok_or_else(|| {
                        format!(
                            "ptr::eq call did not lower to an assertion at `{}`",
                            token_key(expr)
                        )
                    })
                    .map(|entry| vec![entry]);
            }
            let name = simple_call_name(call).ok_or_else(|| {
                format!(
                    "assertion call is not a simple visible helper `{}`",
                    token_key(expr)
                )
            })?;
            if !name.starts_with("assert") {
                return Err(format!(
                    "non-assertion helper call `{name}` is not reducible"
                ));
            }
            let helper = reducer.function(&name)?.ok_or_else(|| {
                format!("assertion helper `{name}` has no visible source; skipped assertion")
            })?;
            match cfg_eval_for_attrs(&helper.attrs, options) {
                CfgEval::Active => {}
                CfgEval::Inactive(reason) => {
                    return Err(format!(
                        "assertion helper `{name}` inactive cfg; skipped: {reason}"
                    ));
                }
                CfgEval::Ambiguous(reason) => {
                    return Err(format!(
                        "assertion helper `{name}` ambiguous cfg; skipped: {reason}"
                    ));
                }
            }
            let params = helper_param_names(helper)?;
            if params.len() != call.args.len() {
                return Err(format!(
                    "assertion helper `{name}` arity mismatch: expected {}, got {}",
                    params.len(),
                    call.args.len()
                ));
            }
            let mut bindings = ExprBindings::new();
            for (param, arg) in params.into_iter().zip(call.args.iter()) {
                bindings.insert(param, arg.clone());
            }
            let result = reduce_assertion_stmts(
                &helper.block.stmts,
                &bindings,
                reducer,
                scope,
                float_widths,
                options,
                depth - 1,
                reduced_helpers,
            )
            .map_err(|e| format!("{name}: {e}"));
            // Record the helper fn name as successfully reduced so Pass 2
            // does not also emit refusals for its asserts (which are already
            // in assertions_lifted).
            if result.is_ok() {
                reduced_helpers.insert(name);
            }
            result
        }
        Expr::Paren(paren) => reduce_assertion_expr(
            &paren.expr,
            reducer,
            scope,
            float_widths,
            options,
            depth,
            reduced_helpers,
        ),
        Expr::Group(group) => reduce_assertion_expr(
            &group.expr,
            reducer,
            scope,
            float_widths,
            options,
            depth,
            reduced_helpers,
        ),
        other => Err(format!(
            "assertion expression is not structurally reducible `{}`",
            token_key(other)
        )),
    }
}

fn reduce_assertion_stmts(
    stmts: &[Stmt],
    bindings: &ExprBindings,
    reducer: &ReductionCtx<'_>,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
    depth: usize,
    reduced_helpers: &mut HashSet<String>,
) -> Result<Vec<AssertionEntry>, String> {
    let mut entries = Vec::new();
    for stmt in stmts {
        match stmt {
            Stmt::Macro(m) => {
                entries.extend(assertions_from_macro_with_bindings(
                    &m.mac.path,
                    m.mac.tokens.clone(),
                    scope,
                    float_widths,
                    options,
                    bindings,
                )?);
            }
            Stmt::Expr(Expr::Macro(m), _) => {
                entries.extend(assertions_from_macro_with_bindings(
                    &m.mac.path,
                    m.mac.tokens.clone(),
                    scope,
                    float_widths,
                    options,
                    bindings,
                )?);
            }
            Stmt::Expr(expr, _) => {
                let expr = substitute_expr(expr, bindings);
                entries.extend(reduce_assertion_expr(
                    &expr,
                    reducer,
                    scope,
                    float_widths,
                    options,
                    depth,
                    reduced_helpers,
                )?);
            }
            other => {
                return Err(format!(
                    "helper body is not a static assertion reduction `{}`",
                    token_key(other)
                ));
            }
        }
    }
    if entries.is_empty() {
        return Err("helper body reduced to no FOL assertions".to_string());
    }
    Ok(entries)
}

fn helper_param_names(f: &syn::ItemFn) -> Result<Vec<String>, String> {
    let mut params = Vec::new();
    for input in &f.sig.inputs {
        let syn::FnArg::Typed(pat_type) = input else {
            return Err(
                "assertion helper methods with self receivers are not reducible".to_string(),
            );
        };
        let name = simple_pat_name(&pat_type.pat).ok_or_else(|| {
            format!(
                "assertion helper `{}` has non-simple parameter `{}`",
                f.sig.ident,
                token_key(&pat_type.pat)
            )
        })?;
        params.push(name);
    }
    Ok(params)
}

fn simple_pat_name(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => Some(ident.ident.to_string()),
        Pat::Type(pat_type) => simple_pat_name(&pat_type.pat),
        Pat::Paren(paren) => simple_pat_name(&paren.pat),
        _ => None,
    }
}

fn collect_macro(
    path: &syn::Path,
    tokens: proc_macro2::TokenStream,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
    entries: &mut Vec<AssertionEntry>,
    skipped: &mut Vec<String>,
) {
    match assertions_from_macro(path, tokens, scope, float_widths, options) {
        Ok(macro_entries) => entries.extend(macro_entries),
        Err(reason) => skipped.push(reason),
    }
}

fn lower_assert_eq(
    lhs_expr: &Expr,
    rhs_expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<AssertionEntry, String> {
    // Intercept infinity-constant equality before falling through to the
    // Real-equality path. f32/f64 infinity is not a Real value; IEEE exactness
    // gives the sound conjunction instead.
    if let Some(entry) = translate_infinity_eq_assertion(lhs_expr, rhs_expr, scope, float_widths)? {
        return Ok(entry);
    }
    let lhs = translate_assertion_term_in_scope(lhs_expr, scope)?;
    let rhs = translate_assertion_term_in_scope(rhs_expr, scope)?;
    Ok(assertion_entry_from_eq(lhs, rhs, scope))
}

fn lower_assert_ne(
    lhs_expr: &Expr,
    rhs_expr: &Expr,
    scope: &TemporalScope,
) -> Result<AssertionEntry, String> {
    // assert_ne!(a, b) is sugar for assert!(a != b): route through the same
    // relation path so the lifted atom is byte-identical to `a != b`.
    let lhs = translate_assertion_term_in_scope(lhs_expr, scope)?;
    let rhs = translate_assertion_term_in_scope(rhs_expr, scope)?;
    Ok(assertion_entry_from_relation(
        lhs,
        rhs,
        RelationOp::Ne,
        scope,
    ))
}

fn lower_assert_condition(
    expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<AssertionEntry, String> {
    translate_bool_assertion(expr, scope, float_widths)
}

fn substitute_exprs(exprs: &[Expr], bindings: &ExprBindings) -> Vec<Expr> {
    exprs
        .iter()
        .map(|expr| substitute_expr(expr, bindings))
        .collect()
}

fn substitute_expr(expr: &Expr, bindings: &ExprBindings) -> Expr {
    match expr {
        Expr::Path(path) if path.qself.is_none() => {
            if let Some(ident) = path.path.get_ident() {
                if let Some(bound) = bindings.get(&ident.to_string()) {
                    return bound.clone();
                }
            }
            expr.clone()
        }
        Expr::Paren(paren) => {
            let mut out = paren.clone();
            out.expr = Box::new(substitute_expr(&paren.expr, bindings));
            Expr::Paren(out)
        }
        Expr::Group(group) => {
            let mut out = group.clone();
            out.expr = Box::new(substitute_expr(&group.expr, bindings));
            Expr::Group(out)
        }
        Expr::Binary(binary) => {
            let mut out = binary.clone();
            out.left = Box::new(substitute_expr(&binary.left, bindings));
            out.right = Box::new(substitute_expr(&binary.right, bindings));
            Expr::Binary(out)
        }
        Expr::Unary(unary) => {
            let mut out = unary.clone();
            out.expr = Box::new(substitute_expr(&unary.expr, bindings));
            Expr::Unary(out)
        }
        Expr::Call(call) => {
            let mut out = call.clone();
            out.func = Box::new(substitute_expr(&call.func, bindings));
            out.args = call
                .args
                .iter()
                .map(|arg| substitute_expr(arg, bindings))
                .collect();
            Expr::Call(out)
        }
        Expr::MethodCall(call) => {
            let mut out = call.clone();
            out.receiver = Box::new(substitute_expr(&call.receiver, bindings));
            out.args = call
                .args
                .iter()
                .map(|arg| substitute_expr(arg, bindings))
                .collect();
            Expr::MethodCall(out)
        }
        Expr::Await(await_expr) => {
            let mut out = await_expr.clone();
            out.base = Box::new(substitute_expr(&await_expr.base, bindings));
            Expr::Await(out)
        }
        Expr::Reference(reference) => {
            let mut out = reference.clone();
            out.expr = Box::new(substitute_expr(&reference.expr, bindings));
            Expr::Reference(out)
        }
        Expr::Field(field) => {
            let mut out = field.clone();
            out.base = Box::new(substitute_expr(&field.base, bindings));
            Expr::Field(out)
        }
        Expr::Cast(cast) => {
            let mut out = cast.clone();
            out.expr = Box::new(substitute_expr(&cast.expr, bindings));
            Expr::Cast(out)
        }
        Expr::Array(array) => {
            let mut out = array.clone();
            out.elems = array
                .elems
                .iter()
                .map(|elem| substitute_expr(elem, bindings))
                .collect();
            Expr::Array(out)
        }
        Expr::Tuple(tuple) => {
            let mut out = tuple.clone();
            out.elems = tuple
                .elems
                .iter()
                .map(|elem| substitute_expr(elem, bindings))
                .collect();
            Expr::Tuple(out)
        }
        _ => expr.clone(),
    }
}

fn assertions_from_macro(
    path: &syn::Path,
    tokens: proc_macro2::TokenStream,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
) -> Result<Vec<AssertionEntry>, String> {
    let bindings = ExprBindings::new();
    assertions_from_macro_with_bindings(path, tokens, scope, float_widths, options, &bindings)
}

fn assertions_from_macro_with_bindings(
    path: &syn::Path,
    tokens: proc_macro2::TokenStream,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
    bindings: &ExprBindings,
) -> Result<Vec<AssertionEntry>, String> {
    let Some(name) = path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
    else {
        return Ok(Vec::new());
    };
    match name.as_str() {
        "assert_eq" => {
            let args = parse_macro_args(tokens).map_err(|e| format!("assert_eq!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            if exprs.len() < 2 {
                return Err("assert_eq!: expected at least 2 arguments".to_string());
            }
            lower_assert_eq(&exprs[0], &exprs[1], scope, float_widths)
                .map(|entry| vec![entry])
                .map_err(|e| format!("assert_eq!: {e}"))
        }
        "assert" => {
            let args = parse_macro_args(tokens).map_err(|e| format!("assert!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            let Some(first) = exprs.first() else {
                return Err("assert!: expected a condition".to_string());
            };
            lower_assert_condition(first, scope, float_widths)
                .map(|entry| vec![entry])
                .map_err(|e| format!("assert!: {e}"))
        }
        "assert_ne" => {
            let args = parse_macro_args(tokens).map_err(|e| format!("assert_ne!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            if exprs.len() < 2 {
                return Err("assert_ne!: expected at least 2 arguments".to_string());
            }
            lower_assert_ne(&exprs[0], &exprs[1], scope)
                .map(|entry| vec![entry])
                .map_err(|e| format!("assert_ne!: {e}"))
        }
        "assert_all" | "assert_none" => {
            let args = parse_macro_args(tokens).map_err(|e| format!("{name}!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            assertion_entries_from_ascii_macro(name.as_str(), &exprs)
        }
        // debug_assert*(a, b) is cfg(debug_assertions)-gated sugar: the CLAIM is
        // identical to the non-debug twin, but it is only asserted when
        // debug_assertions is Active (i.e. debug/test builds). In the witnessed test
        // profile (cargo test) debug_assertions is always on, so if the supplied
        // target_cfg confirms it Active we lift the same atom as the twin. If
        // debug_assertions is NOT confirmed Active we refuse -- overclaiming on a
        // macro that compiles out in release would be a falsePass.
        "debug_assert_eq" => {
            match cfg_eval_predicate(
                &CfgPredicate::Name("debug_assertions".to_string()),
                options.target_cfg.as_ref(),
            ) {
                CfgEval::Active => {}
                CfgEval::Inactive(reason) => {
                    return Err(format!(
                        "debug_assert_eq!: cfg(debug_assertions) not active; skipped: {reason}"
                    ));
                }
                CfgEval::Ambiguous(reason) => {
                    return Err(format!(
                        "debug_assert_eq!: cfg(debug_assertions) ambiguous; skipped: {reason}"
                    ));
                }
            }
            let args = parse_macro_args(tokens).map_err(|e| format!("debug_assert_eq!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            if exprs.len() < 2 {
                return Err("debug_assert_eq!: expected at least 2 arguments".to_string());
            }
            lower_assert_eq(&exprs[0], &exprs[1], scope, float_widths)
                .map(|entry| vec![entry])
                .map_err(|e| format!("debug_assert_eq!: {e}"))
        }
        "debug_assert" => {
            match cfg_eval_predicate(
                &CfgPredicate::Name("debug_assertions".to_string()),
                options.target_cfg.as_ref(),
            ) {
                CfgEval::Active => {}
                CfgEval::Inactive(reason) => {
                    return Err(format!(
                        "debug_assert!: cfg(debug_assertions) not active; skipped: {reason}"
                    ));
                }
                CfgEval::Ambiguous(reason) => {
                    return Err(format!(
                        "debug_assert!: cfg(debug_assertions) ambiguous; skipped: {reason}"
                    ));
                }
            }
            let args = parse_macro_args(tokens).map_err(|e| format!("debug_assert!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            let Some(first) = exprs.first() else {
                return Err("debug_assert!: expected a condition".to_string());
            };
            lower_assert_condition(first, scope, float_widths)
                .map(|entry| vec![entry])
                .map_err(|e| format!("debug_assert!: {e}"))
        }
        "debug_assert_ne" => {
            match cfg_eval_predicate(
                &CfgPredicate::Name("debug_assertions".to_string()),
                options.target_cfg.as_ref(),
            ) {
                CfgEval::Active => {}
                CfgEval::Inactive(reason) => {
                    return Err(format!(
                        "debug_assert_ne!: cfg(debug_assertions) not active; skipped: {reason}"
                    ));
                }
                CfgEval::Ambiguous(reason) => {
                    return Err(format!(
                        "debug_assert_ne!: cfg(debug_assertions) ambiguous; skipped: {reason}"
                    ));
                }
            }
            let args = parse_macro_args(tokens).map_err(|e| format!("debug_assert_ne!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            if exprs.len() < 2 {
                return Err("debug_assert_ne!: expected at least 2 arguments".to_string());
            }
            lower_assert_ne(&exprs[0], &exprs[1], scope)
                .map(|entry| vec![entry])
                .map_err(|e| format!("debug_assert_ne!: {e}"))
        }
        // The hardcoded per-macro arms for assert_eq_const_safe!,
        // assert_almost_eq!, assert_float_result_bits_eq!, assert_chunks!, and
        // assert_range_eq! were removed. Those were a hardcoded vocabulary --
        // the sin. The macro_rules expander now walks into each macro's real
        // definition (from source, in-crate or a dependency) and reduces the
        // expansion: a clean equality discharges, a tolerance/iteration/effectful
        // body becomes a named refusal derived from the actual body. The
        // collector tries the expander when no tuned arm lifts a macro.
        other if other.starts_with("assert") || other.starts_with("debug_assert") => {
            Err(format!("{other}!: unsupported assertion macro"))
        }
        _ => Ok(Vec::new()),
    }
}

// Parser for assert_eq_const_safe!($t:ty: $left:expr, $right:expr).
//
// The macro prefixes the two value expressions with a type annotation and a
// colon: `u8: left, right`. Standard parse_macro_args (comma-only) cannot
// split this because the colon is not a comma. We consume the Type and the
// colon token explicitly, then collect the remaining expressions normally.
struct ConstSafeMacroArgs {
    exprs: Vec<Expr>,
}

impl Parse for ConstSafeMacroArgs {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        // Consume the leading type argument ($t:ty) and the colon separator.
        let _ty: Type = input.parse()?;
        let _colon: Token![:] = input.parse()?;
        // The rest is a comma-separated list of expressions.
        let exprs = Punctuated::<Expr, Token![,]>::parse_terminated(input)?
            .into_iter()
            .collect();
        Ok(Self { exprs })
    }
}

fn parse_const_safe_macro_args(
    tokens: proc_macro2::TokenStream,
) -> syn::Result<ConstSafeMacroArgs> {
    syn::parse2(tokens)
}

fn assertion_entries_from_ascii_macro(
    macro_name: &str,
    exprs: &[Expr],
) -> Result<Vec<AssertionEntry>, String> {
    if exprs.len() < 2 {
        return Err(format!(
            "{macro_name}!: expected predicate name and at least one literal source"
        ));
    }
    let predicate = ascii_macro_predicate_name(&exprs[0]).ok_or_else(|| {
        format!(
            "{macro_name}!: expected a simple ASCII predicate name, got `{}`",
            token_key(&exprs[0])
        )
    })?;
    let negate = macro_name == "assert_none";
    let mut entries = Vec::new();
    for source in &exprs[1..] {
        let value = literal_string_value(source).ok_or_else(|| {
            format!(
                "{macro_name}!: expected string literal source, got `{}`",
                token_key(source)
            )
        })?;
        for ch in value.chars() {
            let atom = ascii_char_class_atom(&predicate, str_const(ch.to_string()))
                .ok_or_else(|| unsupported_ascii_macro_predicate(&predicate))?;
            entries.push(AssertionEntry {
                name: None,
                atom: if negate { not_(atom) } else { atom },
            });
        }
        for byte in value.as_bytes() {
            let atom = ascii_byte_class_atom(&predicate, num(i64::from(*byte)))
                .ok_or_else(|| unsupported_ascii_macro_predicate(&predicate))?;
            entries.push(AssertionEntry {
                name: None,
                atom: if negate { not_(atom) } else { atom },
            });
        }
    }
    Ok(entries)
}

fn ascii_macro_predicate_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) => path.path.get_ident().map(|ident| ident.to_string()),
        Expr::Paren(paren) => ascii_macro_predicate_name(&paren.expr),
        Expr::Group(group) => ascii_macro_predicate_name(&group.expr),
        _ => None,
    }
}

fn unsupported_ascii_macro_predicate(predicate: &str) -> String {
    if predicate == "is_alphabetic" {
        "unicode char predicate is_alphabetic is not lifted; z3 string theory has no Rust Unicode Alphabetic database"
            .to_string()
    } else {
        format!("unsupported bounded ASCII macro predicate `{predicate}`")
    }
}

struct MacroArgs {
    exprs: Vec<Expr>,
}

impl Parse for MacroArgs {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let exprs = Punctuated::<Expr, Token![,]>::parse_terminated(input)?
            .into_iter()
            .collect();
        Ok(Self { exprs })
    }
}

fn parse_macro_args(tokens: proc_macro2::TokenStream) -> syn::Result<MacroArgs> {
    syn::parse2(tokens)
}

fn translate_bool_assertion(
    expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<AssertionEntry, String> {
    if let Some(entry) = translate_pointer_eq_assertion(expr, scope)? {
        return Ok(entry);
    }
    if let Some(entry) = translate_string_predicate_assertion(expr, scope)? {
        return Ok(entry);
    }
    if let Some(entry) = translate_literal_iterator_assertion(expr, scope.local_scope())? {
        return Ok(entry);
    }
    if let Some(entry) = translate_float_refinement_assertion(expr, scope, float_widths)? {
        return Ok(entry);
    }
    if let Some(entry) = translate_matches_assertion(expr, scope)? {
        return Ok(entry);
    }
    match expr {
        Expr::Binary(binary) => translate_binary_bool_assertion(binary, scope, float_widths),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => {
            if let Some(entry) = translate_string_predicate_assertion(&unary.expr, scope)? {
                return Ok(AssertionEntry {
                    name: entry.name,
                    atom: not_(entry.atom),
                });
            }
            if let Some(entry) =
                translate_float_refinement_assertion(&unary.expr, scope, float_widths)?
            {
                return Ok(AssertionEntry {
                    name: entry.name,
                    atom: not_(entry.atom),
                });
            }
            // `!matches!(x, Type::Variant)` — negate the discriminant atom. This
            // MUST run before the opaque-term fallback below, which would lower a
            // `matches!` macro to an unconstrained `macro:...` Var equated to false
            // (a vacuous lift with no teeth) rather than the real discriminant.
            if let Some(entry) = translate_matches_assertion(&unary.expr, scope)? {
                return Ok(AssertionEntry {
                    name: entry.name,
                    atom: not_(entry.atom),
                });
            }
            if let Ok(term) = translate_term_in_scope(&unary.expr, scope) {
                Ok(assertion_entry_from_eq(term, bool_const(false), scope))
            } else {
                let entry = translate_bool_assertion(&unary.expr, scope, float_widths)?;
                Ok(AssertionEntry {
                    name: entry.name,
                    atom: not_(entry.atom),
                })
            }
        }
        Expr::Path(_) => {
            // A bare boolean place `assert!(flag)` asserts the boolean is true:
            // lift `flag == true`. `assert!` requires a bool operand, so this is
            // type-safe WITHOUT type info; it is teethed, not vacuous -- a sibling
            // `assert!(!flag)` over the same place is `flag==true ∧ flag==false`,
            // UNSAT. (A `Field` place like `assert!(x.flag)` is already handled by
            // the call/method/field arm below.)
            let term = translate_term_in_scope(expr, scope)?;
            Ok(assertion_entry_from_eq(term, bool_const(true), scope))
        }
        Expr::Call(_) | Expr::MethodCall(_) | Expr::Await(_) | Expr::Field(_) => {
            // `<coll>.all(|x| ..)` / `.any(|x| ..)` is an iterator quantifier
            // (∀ / ∃ over the receiver's elements). We do not yet LIFT it, but we
            // pay the provenance debt: name whether the collection is a finite
            // CONSTRUCTION (literal -> bin-1, drainable by unroll) or RUNTIME data
            // (opaque -> bin-2, the membrane), so the bin sort is structural rather
            // than presumed from the bare `|x|` shape.
            if let Some(reason) = closure_adaptor_refusal(expr) {
                return Err(reason);
            }
            let term = translate_term_in_scope(expr, scope)?;
            if is_refinement_predicate_term(term.as_ref()) {
                return Err(format!(
                    "refinement predicate remains out of this exact-value slice `{}`",
                    token_key(expr)
                ));
            }
            Ok(assertion_entry_from_eq(term, bool_const(true), scope))
        }
        Expr::Paren(paren) => translate_bool_assertion(&paren.expr, scope, float_widths),
        Expr::Group(group) => translate_bool_assertion(&group.expr, scope, float_widths),
        other => Err(format!(
            "only scalar equality is liftable, got `{}`",
            token_key(other)
        )),
    }
}

fn translate_float_refinement_assertion(
    expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<Option<AssertionEntry>, String> {
    match expr {
        Expr::MethodCall(call) => {
            let method = call.method.to_string();
            if !is_liftable_float_refinement_method(&method) {
                return Ok(None);
            }
            if !call.args.is_empty() {
                return Err(format!(
                    "float refinement predicate takes no arguments `{}`",
                    token_key(expr)
                ));
            }
            let Some(width) = float_refinement_receiver_width(&call.receiver, float_widths) else {
                return Err(format!(
                    "float refinement predicate `{method}` requires known f32/f64 receiver width `{}`",
                    token_key(expr)
                ));
            };
            let receiver = translate_term_in_scope(&call.receiver, scope)?;
            let name = callsite_assertion_name(receiver.as_ref(), scope.local_scope());
            Ok(Some(AssertionEntry {
                name,
                atom: atomic_(format!("float.{width}.{method}"), vec![receiver]),
            }))
        }
        Expr::Paren(paren) => {
            translate_float_refinement_assertion(&paren.expr, scope, float_widths)
        }
        Expr::Group(group) => {
            translate_float_refinement_assertion(&group.expr, scope, float_widths)
        }
        _ => Ok(None),
    }
}

fn is_liftable_float_refinement_method(method: &str) -> bool {
    matches!(
        method,
        "is_nan"
            | "is_infinite"
            | "is_finite"
            | "is_normal"
            | "is_sign_positive"
            | "is_sign_negative"
    )
}

/// If `expr` is exactly `f32::INFINITY`, `f64::INFINITY`, `f32::NEG_INFINITY`,
/// or `f64::NEG_INFINITY` (a two-segment path with no generics), returns
/// `(width, is_positive)`. Any other expression returns `None`.
///
/// This is the ONLY trigger for the infinity-equality conjunction path.
/// Finite float literals (`1.5f64`) and all other expressions return `None`
/// and stay on the existing Real-equality path unchanged.
fn infinity_constant_kind(expr: &Expr) -> Option<(&'static str, bool)> {
    let path = match expr {
        Expr::Path(p) if p.qself.is_none() => &p.path,
        Expr::Paren(paren) => return infinity_constant_kind(&paren.expr),
        Expr::Group(group) => return infinity_constant_kind(&group.expr),
        _ => return None,
    };
    // Must be exactly two path segments with no arguments: `f32::INFINITY`.
    let segs: Vec<_> = path.segments.iter().collect();
    if segs.len() != 2 {
        return None;
    }
    // Both segments must have no generic arguments.
    for seg in &segs {
        if !matches!(seg.arguments, syn::PathArguments::None) {
            return None;
        }
    }
    let type_seg = segs[0].ident.to_string();
    let const_seg = segs[1].ident.to_string();
    let width: &'static str = match type_seg.as_str() {
        "f32" => "f32",
        "f64" => "f64",
        _ => return None,
    };
    let is_positive = match const_seg.as_str() {
        "INFINITY" => true,
        "NEG_INFINITY" => false,
        _ => return None,
    };
    Some((width, is_positive))
}

/// Attempt to lift `lhs == rhs` (or `rhs == lhs`) where exactly one operand is
/// an infinity constant path, as the sound predicate conjunction:
///
///   `f64::INFINITY`  => `and(float.f64.is_infinite(expr), float.f64.is_sign_positive(expr))`
///   `f64::NEG_INFINITY` => `and(float.f64.is_infinite(expr), float.f64.is_sign_negative(expr))`
///
/// Width is taken from the constant operand. The non-constant operand becomes
/// the receiver term.
///
/// Returns `Ok(None)` if neither operand is an infinity constant (caller falls
/// through to the existing path). Returns `Err` only if the constant was
/// detected but the receiver term translation fails.
fn translate_infinity_eq_assertion(
    lhs: &Expr,
    rhs: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<Option<AssertionEntry>, String> {
    let (width, is_positive, receiver_expr) =
        match (infinity_constant_kind(lhs), infinity_constant_kind(rhs)) {
            (Some((w, pos)), _) => (w, pos, rhs),
            (None, Some((w, pos))) => (w, pos, lhs),
            (None, None) => return Ok(None),
        };

    // The receiver must have a known width to avoid lifting a wrong claim.
    // We accept the width from the constant side if the receiver has no
    // conflicting annotation (soundness: we know the constant's type so the
    // equality is between same-type values in valid Rust).
    // We still check: if the receiver has a conflicting width annotation,
    // refuse rather than guess.
    if let Some(receiver_width) = float_refinement_receiver_width(receiver_expr, float_widths) {
        if receiver_width != width {
            return Err(format!(
                "infinity equality: receiver width `{receiver_width}` conflicts with constant width `{width}` in `{}`",
                token_key(receiver_expr)
            ));
        }
    }
    // Width is determined by the constant. Translate the receiver as a term.
    let receiver = translate_term_in_scope(receiver_expr, scope).map_err(|e| {
        format!(
            "infinity equality: receiver term translation failed for `{}`: {e}",
            token_key(receiver_expr)
        )
    })?;

    let name = callsite_assertion_name(receiver.as_ref(), scope.local_scope());
    let sign_pred = if is_positive {
        "is_sign_positive"
    } else {
        "is_sign_negative"
    };
    let atom = and_(vec![
        atomic_(format!("float.{width}.is_infinite"), vec![receiver.clone()]),
        atomic_(format!("float.{width}.{sign_pred}"), vec![receiver]),
    ]);
    Ok(Some(AssertionEntry { name, atom }))
}

type FloatWidthScope = BTreeMap<String, &'static str>;

fn update_float_width_scope_for_pat(pat: &Pat, out: &mut FloatWidthScope) {
    remove_float_width_idents(pat, out);
    match pat {
        Pat::Type(pat_type) => {
            if let Some(width) = float_width_from_type(&pat_type.ty) {
                collect_float_width_ident_pat(&pat_type.pat, width, out);
            }
        }
        Pat::Paren(paren) => update_float_width_scope_for_pat(&paren.pat, out),
        _ => {}
    }
}

fn remove_float_width_idents(pat: &Pat, out: &mut FloatWidthScope) {
    match pat {
        Pat::Ident(ident) => {
            out.remove(&ident.ident.to_string());
            if let Some((_, subpat)) = &ident.subpat {
                remove_float_width_idents(subpat, out);
            }
        }
        Pat::Or(or) => {
            for case in &or.cases {
                remove_float_width_idents(case, out);
            }
        }
        Pat::Paren(paren) => remove_float_width_idents(&paren.pat, out),
        Pat::Reference(reference) => remove_float_width_idents(&reference.pat, out),
        Pat::Slice(slice) => {
            for elem in &slice.elems {
                remove_float_width_idents(elem, out);
            }
        }
        Pat::Struct(pat_struct) => {
            for field in &pat_struct.fields {
                remove_float_width_idents(&field.pat, out);
            }
        }
        Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                remove_float_width_idents(elem, out);
            }
        }
        Pat::TupleStruct(tuple_struct) => {
            for elem in &tuple_struct.elems {
                remove_float_width_idents(elem, out);
            }
        }
        Pat::Type(pat_type) => remove_float_width_idents(&pat_type.pat, out),
        _ => {}
    }
}

fn collect_float_width_ident_pat(pat: &Pat, width: &'static str, out: &mut FloatWidthScope) {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => {
            out.insert(ident.ident.to_string(), width);
        }
        Pat::Paren(paren) => collect_float_width_ident_pat(&paren.pat, width, out),
        _ => {}
    }
}

fn float_width_from_type(ty: &Type) -> Option<&'static str> {
    match ty {
        Type::Path(path) => float_width_from_path(&path.path),
        Type::Paren(paren) => float_width_from_type(&paren.elem),
        Type::Group(group) => float_width_from_type(&group.elem),
        _ => None,
    }
}

fn float_refinement_receiver_width(
    expr: &Expr,
    float_widths: &FloatWidthScope,
) -> Option<&'static str> {
    match expr {
        Expr::MethodCall(call) => float_width_from_method_name(&call.method.to_string())
            .or_else(|| float_width_from_method_turbofish(call))
            .or_else(|| {
                if call.method == "unwrap" {
                    float_refinement_receiver_width(&call.receiver, float_widths)
                } else {
                    None
                }
            }),
        Expr::Path(path) => {
            let name = path_to_name(&path.path);
            float_widths
                .get(&name)
                .copied()
                .or_else(|| float_width_from_path(&path.path))
        }
        Expr::Lit(ExprLit {
            lit: Lit::Float(lit),
            ..
        }) => float_width_from_suffix(lit.suffix()),
        Expr::Paren(paren) => float_refinement_receiver_width(&paren.expr, float_widths),
        Expr::Group(group) => float_refinement_receiver_width(&group.expr, float_widths),
        _ => None,
    }
}

fn float_width_from_method_turbofish(call: &syn::ExprMethodCall) -> Option<&'static str> {
    if call.method != "parse" {
        return None;
    }
    let args = call.turbofish.as_ref()?;
    float_width_from_angle_args(args)
}

fn float_width_from_angle_args(args: &syn::AngleBracketedGenericArguments) -> Option<&'static str> {
    if args.args.len() != 1 {
        return None;
    }
    let Some(syn::GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    float_width_from_type(ty)
}

fn float_width_from_method_name(method: &str) -> Option<&'static str> {
    if method.ends_with("_f32") {
        Some("f32")
    } else if method.ends_with("_f64") {
        Some("f64")
    } else {
        None
    }
}

fn float_width_from_path(path: &syn::Path) -> Option<&'static str> {
    for segment in &path.segments {
        match segment.ident.to_string().as_str() {
            "f32" => return Some("f32"),
            "f64" => return Some("f64"),
            _ => {}
        }
    }
    None
}

fn float_width_from_suffix(suffix: &str) -> Option<&'static str> {
    match suffix {
        "f32" => Some("f32"),
        "f64" => Some("f64"),
        _ => None,
    }
}

fn translate_pointer_eq_assertion(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Option<AssertionEntry>, String> {
    match expr {
        Expr::Paren(paren) => translate_pointer_eq_assertion(&paren.expr, scope),
        Expr::Group(group) => translate_pointer_eq_assertion(&group.expr, scope),
        Expr::Call(call) => {
            let callee = expr_head_key(&call.func);
            if !matches!(
                callee.as_str(),
                "core::ptr::eq" | "ptr::eq" | "std::ptr::eq"
            ) {
                return Ok(None);
            }
            if call.args.len() != 2 {
                return Err("ptr::eq expects two arguments".to_string());
            }
            let mut args = Vec::new();
            for arg in &call.args {
                args.push(translate_pointer_identity_term(arg, scope)?);
            }
            let term = Rc::new(Term::Ctor {
                name: format!("call:{callee}"),
                args,
            });
            Ok(Some(assertion_entry_from_eq(term, bool_const(true), scope)))
        }
        _ => Ok(None),
    }
}

fn translate_pointer_identity_term(expr: &Expr, scope: &TemporalScope) -> Result<Rc<Term>, String> {
    match expr {
        Expr::Reference(reference) if reference.mutability.is_none() => Ok(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![translate_pointer_identity_term(&reference.expr, scope)?],
        })),
        Expr::Index(index) => Ok(Rc::new(Term::Ctor {
            name: "index".to_string(),
            args: vec![
                translate_pointer_identity_term(&index.expr, scope)?,
                translate_pointer_identity_term(&index.index, scope)?,
            ],
        })),
        Expr::Paren(paren) => translate_pointer_identity_term(&paren.expr, scope),
        Expr::Group(group) => translate_pointer_identity_term(&group.expr, scope),
        other => translate_term_in_scope(other, scope),
    }
}

fn translate_binary_bool_assertion(
    binary: &syn::ExprBinary,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<AssertionEntry, String> {
    match &binary.op {
        BinOp::And(_) | BinOp::Or(_) => {
            let left = translate_bool_assertion(&binary.left, scope, float_widths)?;
            let right = translate_bool_assertion(&binary.right, scope, float_widths)?;
            let name = common_assertion_name(&left.name, &right.name);
            let atom = if matches!(binary.op, BinOp::And(_)) {
                and_(vec![left.atom, right.atom])
            } else {
                or_(vec![left.atom, right.atom])
            };
            Ok(AssertionEntry { name, atom })
        }
        BinOp::Eq(_) | BinOp::Ne(_) | BinOp::Lt(_) | BinOp::Le(_) | BinOp::Gt(_) | BinOp::Ge(_) => {
            // For == only: intercept infinity-constant equality before the
            // Real-equality path. != and ordered comparisons fall through unchanged.
            if matches!(binary.op, BinOp::Eq(_)) {
                if let Some(entry) = translate_infinity_eq_assertion(
                    &binary.left,
                    &binary.right,
                    scope,
                    float_widths,
                )? {
                    return Ok(entry);
                }
            }
            let op = relation_from_binop(&binary.op)
                .expect("comparison op matched but did not map to relation");
            let lhs = translate_assertion_term_in_scope(&binary.left, scope)?;
            let rhs = translate_assertion_term_in_scope(&binary.right, scope)?;
            Ok(assertion_entry_from_relation(lhs, rhs, op, scope))
        }
        _ => Err(format!(
            "only scalar comparison/connective assertions are liftable, got `{}`",
            token_key(binary)
        )),
    }
}

fn common_assertion_name(left: &Option<String>, right: &Option<String>) -> Option<String> {
    match (left, right) {
        (Some(left), Some(right)) if left == right => Some(left.clone()),
        _ => None,
    }
}

fn assertion_entry_from_eq(lhs: Rc<Term>, rhs: Rc<Term>, scope: &TemporalScope) -> AssertionEntry {
    assertion_entry_from_relation(lhs, rhs, RelationOp::Eq, scope)
}

/// An expression that diverges: its value is never produced because control
/// panics/aborts/returns. As a match or if arm, it is the panic locus -- the
/// test passing proves control did NOT reach it.
fn expr_diverges(expr: &Expr) -> bool {
    match expr {
        Expr::Macro(m) => m.mac.path.segments.last().is_some_and(|s| {
            matches!(
                s.ident.to_string().as_str(),
                "panic" | "unreachable" | "todo" | "unimplemented"
            )
        }),
        Expr::Block(b) => b.block.stmts.last().is_some_and(stmt_diverges),
        Expr::Unsafe(u) => u.block.stmts.last().is_some_and(stmt_diverges),
        Expr::Return(_) => true,
        Expr::Paren(p) => expr_diverges(&p.expr),
        Expr::Group(g) => expr_diverges(&g.expr),
        Expr::Call(c) => {
            if let Expr::Path(p) = &*c.func {
                let last = p.path.segments.last().map(|s| s.ident.to_string());
                matches!(last.as_deref(), Some("exit") | Some("abort"))
                    && p.path.segments.iter().any(|s| s.ident == "process")
            } else {
                false
            }
        }
        _ => false,
    }
}

fn stmt_diverges(s: &Stmt) -> bool {
    match s {
        Stmt::Expr(e, _) => expr_diverges(e),
        Stmt::Macro(m) => m.mac.path.segments.last().is_some_and(|seg| {
            matches!(
                seg.ident.to_string().as_str(),
                "panic" | "unreachable" | "todo" | "unimplemented"
            )
        }),
        _ => false,
    }
}

fn path_to_variant_string(p: &syn::Path) -> String {
    p.segments
        .iter()
        .map(|s| s.ident.to_string())
        .collect::<Vec<_>>()
        .join("::")
}

/// The variant a surviving match/if-let arm pattern identifies, as a tag string.
fn pattern_variant_path(pat: &syn::Pat) -> Option<String> {
    match pat {
        syn::Pat::TupleStruct(ts) => Some(path_to_variant_string(&ts.path)),
        syn::Pat::Path(p) => Some(path_to_variant_string(&p.path)),
        syn::Pat::Struct(s) => Some(path_to_variant_string(&s.path)),
        syn::Pat::Ident(id) if id.subpat.is_none() => Some(id.ident.to_string()),
        syn::Pat::Reference(r) => pattern_variant_path(&r.pat),
        _ => None,
    }
}

/// Lift `assert!(matches!(subject, Type::Variant ...))` as a variant-discriminant
/// assertion: `variant_of(subject) == "variant::<Type::Variant>"` -- the SAME
/// construction-semantics atom panic-locus lifting emits (`panic_locus_entry`),
/// with the same teeth (two variants are distinct string constants, so claiming
/// both is UNSAT).
///
/// SOUND SCOPE: `matches!(x, P)` is exactly `match x { P => true, _ => false }`,
/// so a passing `assert!(matches!(x, P [if g]))` means x matched P (and, if
/// present, the guard g held) -- the discriminant `variant_of(x) == "variant::P"`
/// is therefore IMPLIED. We lift only that (weaker, always-implied) discriminant
/// fact, so both value-binding subpatterns (`V { f }`, `V(inner)`) AND a trailing
/// GUARD (`P if g`) are fine: the lifted obligation is implied either way, and
/// dropping g loses only refutation power, never soundness. (This differs from
/// `panic_locus_match_entry`, which refuses guards: a `match` has multiple arms,
/// the same pattern can recur with different guards, and which arm a value reaches
/// is genuinely guard-dependent -- the single-pattern `matches!` macro has no such
/// ambiguity.) We REFUSE BY NAME only the shapes where the discriminant itself is
/// NOT unambiguous:
///   - an or-pattern (`A | B`): a disjunction is not a single discriminant;
///   - a binding / wildcard / single-segment path: a lowercase `foo` is a
///     catch-all binding (always matches), and a bare `Foo` is ambiguous between
///     a unit variant and an associated const -- not an unambiguous `Type::Variant`.
fn translate_matches_assertion(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Option<AssertionEntry>, String> {
    let Expr::Macro(m) = expr else {
        return Ok(None);
    };
    if !m.mac.path.is_ident("matches") {
        return Ok(None);
    }
    // Parse `subject , pattern (if guard)?` from the macro token stream.
    let parser = |input: ParseStream| -> syn::Result<(Expr, syn::Pat)> {
        let subject: Expr = input.parse()?;
        input.parse::<Token![,]>()?;
        let pat = syn::Pat::parse_multi_with_leading_vert(input)?;
        // A trailing `if <guard>` is consumed but NOT modeled: for the ASSERTED
        // direction, `matches!(x, V if g)` true ⟹ x matches V AND g, so the
        // discriminant `variant_of(x) == "variant::V"` is IMPLIED regardless of g.
        // Lifting the discriminant and dropping the guard is therefore SOUND (a
        // weaker, always-implied fact); not modeling g loses only refutation power,
        // never soundness -- the same tradeoff `collect_ambient_foralls` makes.
        let _ = input.parse::<proc_macro2::TokenStream>();
        Ok((subject, pat))
    };
    let (subject, pat) = match Parser::parse2(parser, m.mac.tokens.clone()) {
        Ok(v) => v,
        // Not the `matches!(expr, pat)` shape we lift; fall through to the
        // ordinary boolean-assertion paths (which will name their own refusal).
        Err(_) => return Ok(None),
    };
    let Some(variant) = strict_variant_path(&pat) else {
        // NESTED WRAPPER: `matches!(x, Some(Inner::V))` / `Ok(..)` / `Err(..)`.
        // The single-segment wrapper is a known prelude variant (so `variant_of(x)
        // == "variant::Some"` is unambiguous), and its inner pattern -- when a
        // qualified variant -- pins the payload's discriminant via the payload
        // accessor. This is the meaningful claim (`Some(Widen)` vs `Some(Halt)`),
        // so we lift the conjunction, not just the trivial outer `Some`.
        if let Some((wrapper, inner)) = wrapped_variant(&pat) {
            return Ok(wrapped_variant_entry(
                &subject,
                &wrapper,
                inner.as_deref(),
                scope,
            ));
        }
        return Err(format!(
            "matches! pattern is not an unambiguous qualified variant \
             (binding/wildcard/single-segment/or-pattern); refused by name: `{}`",
            token_key(expr)
        ));
    };
    match panic_locus_entry(&subject, &variant, scope) {
        Some(entry) => Ok(Some(entry)),
        None => Err(format!(
            "matches! subject is not a liftable term: `{}`",
            token_key(&subject)
        )),
    }
}

/// A nested known-wrapper pattern `Some(P)` / `Ok(P)` / `Err(P)`: returns the
/// single-segment wrapper variant name and the inner variant IF the inner pattern
/// is itself a qualified `Type::Variant` (else `None` -- a `Some(_)` / `Some(x)`
/// still pins the OUTER wrapper, but carries no inner discriminant). The wrapper
/// must be one of the prelude tuple variants whose single-segment name is
/// unambiguously a variant, not a const/binding.
fn wrapped_variant(pat: &syn::Pat) -> Option<(String, Option<String>)> {
    match pat {
        syn::Pat::Reference(r) => wrapped_variant(&r.pat),
        syn::Pat::TupleStruct(ts) if ts.path.segments.len() == 1 && ts.elems.len() == 1 => {
            let wrapper = ts.path.segments[0].ident.to_string();
            if !matches!(wrapper.as_str(), "Some" | "Ok" | "Err") {
                return None;
            }
            Some((wrapper, strict_variant_path(&ts.elems[0])))
        }
        _ => None,
    }
}

/// Build the nested-wrapper discriminant entry:
///   `variant_of(subject) == "variant::<wrapper>"`  (always), AND
///   `variant_of(payload:<wrapper>(subject)) == "variant::<inner>"`  (if inner is
///   a qualified variant).
/// The payload accessor `payload:<wrapper>(subject)` is an uninterpreted Ctor; by
/// congruence, two claims about the same subject's payload share it, so asserting
/// two distinct inner variants is UNSAT (the teeth). The contract NAME keys on the
/// subject (via the outer entry), so siblings about the same subject conjoin.
fn wrapped_variant_entry(
    subject: &Expr,
    wrapper: &str,
    inner: Option<&str>,
    scope: &TemporalScope,
) -> Option<AssertionEntry> {
    let subject_term = translate_term_in_scope(subject, scope).ok()?;
    let outer_lhs = Rc::new(Term::Ctor {
        name: "variant_of".to_string(),
        args: vec![subject_term.clone()],
    });
    let outer = assertion_entry_from_eq(outer_lhs, str_const(format!("variant::{wrapper}")), scope);
    let Some(inner_variant) = inner else {
        // `Some(_)` / `Some(x)`: only the outer wrapper is pinned.
        return Some(outer);
    };
    let payload = Rc::new(Term::Ctor {
        name: format!("payload:{wrapper}"),
        args: vec![subject_term],
    });
    let inner_lhs = Rc::new(Term::Ctor {
        name: "variant_of".to_string(),
        args: vec![payload],
    });
    let inner_atom = assertion_entry_from_eq(
        inner_lhs,
        str_const(format!("variant::{inner_variant}")),
        scope,
    )
    .atom;
    Some(AssertionEntry {
        name: outer.name,
        atom: and_(vec![outer.atom, inner_atom]),
    })
}

/// Strict variant-path extraction for `matches!` discriminant lifting: a
/// QUALIFIED `Type::Variant` (>= 2 path segments) as a unit, tuple-struct, or
/// struct pattern, or such a pattern behind a `&`. Returns None for bindings,
/// wildcards, single-segment paths, and or-patterns -- the caller refuses those
/// by name. Stricter than `pattern_variant_path` (which accepts bare `Pat::Ident`
/// bindings and single-segment paths, sound only in its panic-locus call site).
fn strict_variant_path(pat: &syn::Pat) -> Option<String> {
    fn qualified(path: &syn::Path) -> Option<String> {
        (path.segments.len() >= 2).then(|| path_to_variant_string(path))
    }
    match pat {
        syn::Pat::TupleStruct(ts) => qualified(&ts.path),
        syn::Pat::Struct(s) => qualified(&s.path),
        syn::Pat::Path(p) => qualified(&p.path),
        syn::Pat::Reference(r) => strict_variant_path(&r.pat),
        _ => None,
    }
}

/// Build the panic-locus atom: `variant_of(subject) == "variant::<tag>"`. The
/// tag is a string literal, so two different variants of the same subject are
/// distinct constants -- asserting both is UNSAT (the teeth).
fn panic_locus_entry(
    subject: &Expr,
    variant: &str,
    scope: &TemporalScope,
) -> Option<AssertionEntry> {
    let subject_term = translate_term_in_scope(subject, scope).ok()?;
    let variant_of = Rc::new(Term::Ctor {
        name: "variant_of".to_string(),
        args: vec![subject_term],
    });
    Some(assertion_entry_from_eq(
        variant_of,
        str_const(format!("variant::{variant}")),
        scope,
    ))
}

/// Panic-locus lifting for a `match`: if every arm but one diverges (panics),
/// the test passing proves the scrutinee matches the surviving arm's pattern.
fn panic_locus_match_entry(m: &syn::ExprMatch, scope: &TemporalScope) -> Option<AssertionEntry> {
    if m.arms.len() < 2 {
        return None;
    }
    let mut surviving = Vec::new();
    let mut diverging = 0usize;
    for arm in &m.arms {
        if arm.guard.is_some() {
            return None; // a guard changes which values reach the arm
        }
        if expr_diverges(&arm.body) {
            diverging += 1;
        } else {
            surviving.push(arm);
        }
    }
    if diverging == 0 || surviving.len() != 1 {
        return None;
    }
    let variant = pattern_variant_path(&surviving[0].pat)?;
    panic_locus_entry(&m.expr, &variant, scope)
}

/// Panic-locus lifting for `if let PAT = SUBJ { .. } else { panic!() }`.
fn panic_locus_if_entry(i: &syn::ExprIf, scope: &TemporalScope) -> Option<AssertionEntry> {
    let Expr::Let(cond) = &*i.cond else {
        return None;
    };
    let (_, else_expr) = i.else_branch.as_ref()?;
    if !expr_diverges(else_expr) {
        return None;
    }
    let variant = pattern_variant_path(&cond.pat)?;
    panic_locus_entry(&cond.expr, &variant, scope)
}

#[derive(Clone, Copy)]
enum RelationOp {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl RelationOp {
    fn operator_call_name(self) -> &'static str {
        match self {
            RelationOp::Eq | RelationOp::Ne => "eq",
            RelationOp::Lt => "lt",
            RelationOp::Le => "le",
            RelationOp::Gt => "gt",
            RelationOp::Ge => "ge",
        }
    }

    fn operator_asserted_result(self) -> bool {
        !matches!(self, RelationOp::Ne)
    }
}

fn relation_from_binop(op: &BinOp) -> Option<RelationOp> {
    match op {
        BinOp::Eq(_) => Some(RelationOp::Eq),
        BinOp::Ne(_) => Some(RelationOp::Ne),
        BinOp::Lt(_) => Some(RelationOp::Lt),
        BinOp::Le(_) => Some(RelationOp::Le),
        BinOp::Gt(_) => Some(RelationOp::Gt),
        BinOp::Ge(_) => Some(RelationOp::Ge),
        _ => None,
    }
}

fn translate_string_predicate_assertion(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Option<AssertionEntry>, String> {
    match expr {
        Expr::Paren(paren) => translate_string_predicate_assertion(&paren.expr, scope),
        Expr::Group(group) => translate_string_predicate_assertion(&group.expr, scope),
        Expr::MethodCall(call) => {
            let method = call.method.to_string();
            match method.as_str() {
                "contains" => {
                    let Some(receiver) = string_or_char_literal_term(&call.receiver) else {
                        return Ok(None);
                    };
                    if call.args.len() != 1 {
                        return Err("string contains predicate expects one literal pattern".to_string());
                    }
                    let Some(pattern) = string_or_char_literal_term(&call.args[0]) else {
                        return Err(format!(
                            "string contains predicate needs a string/char literal pattern, got `{}`",
                            token_key(&call.args[0])
                        ));
                    };
                    let name = method_call_assertion_name(
                        "contains",
                        vec![receiver.clone(), pattern.clone()],
                        scope.local_scope(),
                    );
                    Ok(Some(AssertionEntry {
                        name,
                        atom: atomic_("contains", vec![receiver, pattern]),
                    }))
                }
                "starts_with" | "ends_with" => {
                    // The receiver is type-guaranteed a string (`starts_with` /
                    // `ends_with` exist only on str/String), so translate it as a
                    // TERM -- literal OR opaque (e.g. `cid.starts_with("blake3-512:")`
                    // where `cid` is a computed value). No type info needed; the
                    // method's existence proves stringness. The PATTERN must still be
                    // a literal (the known prefix/suffix). `prefix-of(pattern, recv)`
                    // is the faithful FOL, teethed against a contradicting claim.
                    let Ok(receiver) = translate_term_in_scope(&call.receiver, scope) else {
                        return Ok(None);
                    };
                    if call.args.len() != 1 {
                        return Err(format!("{method} predicate expects one literal pattern"));
                    }
                    let Some(pattern) = string_or_char_literal_term(&call.args[0]) else {
                        return Err(format!(
                            "{method} predicate needs a string/char literal pattern, got `{}`",
                            token_key(&call.args[0])
                        ));
                    };
                    let name = method_call_assertion_name(
                        method.as_str(),
                        vec![receiver.clone(), pattern.clone()],
                        scope.local_scope(),
                    );
                    let atom_name = if method == "starts_with" {
                        "prefix-of"
                    } else {
                        "suffix-of"
                    };
                    Ok(Some(AssertionEntry {
                        name,
                        atom: atomic_(atom_name, vec![pattern, receiver]),
                    }))
                }
                "is_ascii" => {
                    if !call.args.is_empty() {
                        return Err("is_ascii predicate expects no arguments".to_string());
                    }
                    if let Some(receiver) = string_or_char_literal_term(&call.receiver) {
                        let name = method_call_assertion_name(
                            "is_ascii",
                            vec![receiver.clone()],
                            scope.local_scope(),
                        );
                        return Ok(Some(AssertionEntry {
                            name,
                            atom: atomic_("str.is_ascii", vec![receiver]),
                        }));
                    }
                    let Some(bytes) = literal_byte_string_value(&call.receiver) else {
                        return Ok(None);
                    };
                    let atoms = bytes
                        .into_iter()
                        .map(|b| byte_is_ascii_formula(num(i64::from(b))))
                        .collect::<Vec<_>>();
                    let atom = if atoms.is_empty() {
                        eq(bool_const(true), bool_const(true))
                    } else {
                        and_(atoms)
                    };
                    Ok(Some(AssertionEntry { name: None, atom }))
                }
                "is_ascii_alphabetic" => {
                    let Some(receiver) = char_literal_term(&call.receiver) else {
                        return Ok(None);
                    };
                    if !call.args.is_empty() {
                        return Err("is_ascii_alphabetic predicate expects no arguments".to_string());
                    }
                    let name = method_call_assertion_name(
                        "is_ascii_alphabetic",
                        vec![receiver.clone()],
                        scope.local_scope(),
                    );
                    Ok(Some(AssertionEntry {
                        name,
                        atom: atomic_("str.is_ascii_alphabetic", vec![receiver]),
                    }))
                }
                "is_ascii_digit" => {
                    ascii_char_class_assertion(call, scope.local_scope(), "str.is_ascii_digit")
                }
                "is_ascii_alphanumeric" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_alphanumeric",
                ),
                "is_ascii_octdigit" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_octdigit",
                ),
                "is_ascii_lowercase" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_lowercase",
                ),
                "is_ascii_uppercase" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_uppercase",
                ),
                "is_ascii_hexdigit" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_hexdigit",
                ),
                "is_ascii_punctuation" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_punctuation",
                ),
                "is_ascii_graphic" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_graphic",
                ),
                "is_ascii_whitespace" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_whitespace",
                ),
                "is_ascii_control" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_control",
                ),
                "is_alphabetic" if char_literal_term(&call.receiver).is_some() => Err(
                    "unicode char predicate is_alphabetic is not lifted; z3 string theory has no Rust Unicode Alphabetic database"
                        .to_string(),
                ),
                _ => Ok(None),
            }
        }
        _ => Ok(None),
    }
}

fn ascii_char_class_assertion(
    call: &syn::ExprMethodCall,
    local_scope: &str,
    atom_name: &str,
) -> Result<Option<AssertionEntry>, String> {
    let Some(receiver) = char_literal_term(&call.receiver) else {
        return Ok(None);
    };
    if !call.args.is_empty() {
        return Err(format!("{} predicate expects no arguments", call.method));
    }
    let method = call.method.to_string();
    let name = method_call_assertion_name(method.as_str(), vec![receiver.clone()], local_scope);
    Ok(Some(AssertionEntry {
        name,
        atom: atomic_(atom_name, vec![receiver]),
    }))
}

fn translate_literal_iterator_assertion(
    expr: &Expr,
    _local_scope: &str,
) -> Result<Option<AssertionEntry>, String> {
    let Expr::MethodCall(call) = expr else {
        return Ok(None);
    };
    let method = call.method.to_string();
    if !matches!(method.as_str(), "all" | "any") {
        return Ok(None);
    }
    if call.args.len() != 1 {
        return Err(format!("{method} predicate expects one closure"));
    }
    let Some(closure) = call.args.first().and_then(|expr| match expr {
        Expr::Closure(closure) => Some(closure),
        _ => None,
    }) else {
        return Ok(None);
    };
    if closure.inputs.len() != 1 {
        return Err(format!("{method} predicate expects one closure parameter"));
    }
    let param_name = closure
        .inputs
        .first()
        .and_then(|pat| match pat {
            syn::Pat::Ident(ident) => Some(ident.ident.to_string()),
            _ => None,
        })
        .ok_or_else(|| format!("{method} predicate requires a simple identifier parameter"))?;

    let Some((iter_kind, elements)) = literal_iterator_elements(&call.receiver)? else {
        return Ok(None);
    };
    let mut atoms = Vec::new();
    for element in elements {
        atoms.push(iterator_element_predicate_atom(
            closure.body.as_ref(),
            &param_name,
            element,
            iter_kind,
        )?);
    }
    let atom = if method == "all" {
        if atoms.is_empty() {
            eq(bool_const(true), bool_const(true))
        } else {
            and_(atoms)
        }
    } else if atoms.is_empty() {
        eq(bool_const(true), bool_const(false))
    } else {
        or_(atoms)
    };
    Ok(Some(AssertionEntry { name: None, atom }))
}

#[derive(Clone, Copy)]
enum IteratorKind {
    Chars,
    Bytes,
}

fn iterator_element_predicate_atom(
    body: &Expr,
    param_name: &str,
    element: Rc<Term>,
    iter_kind: IteratorKind,
) -> Result<Rc<Formula>, String> {
    let Expr::MethodCall(call) = body else {
        return Err(format!(
            "iterator closure body must be a simple method call, got `{}`",
            token_key(body)
        ));
    };
    if !call.args.is_empty() {
        return Err(format!(
            "iterator closure predicate `{}` expects no arguments",
            call.method
        ));
    }
    if !matches_param_receiver(&call.receiver, param_name) {
        return Err(format!(
            "iterator closure predicate must read its bound parameter `{param_name}`"
        ));
    }
    let method = call.method.to_string();
    match iter_kind {
        IteratorKind::Chars => ascii_char_class_atom(&method, element).ok_or_else(|| {
            if method == "is_alphabetic" {
                "unicode char predicate is_alphabetic is not lifted; z3 string theory has no Rust Unicode Alphabetic database"
                    .to_string()
            } else {
                format!("unsupported char iterator predicate `{method}`")
            }
        }),
        IteratorKind::Bytes => ascii_byte_class_atom(&method, element)
            .ok_or_else(|| format!("unsupported byte iterator predicate `{method}`")),
    }
}

fn ascii_char_class_atom(method: &str, receiver: Rc<Term>) -> Option<Rc<Formula>> {
    let atom_name = match method {
        "is_ascii" => "str.is_ascii",
        "is_ascii_alphabetic" => "str.is_ascii_alphabetic",
        "is_ascii_alphanumeric" => "str.is_ascii_alphanumeric",
        "is_ascii_digit" => "str.is_ascii_digit",
        "is_ascii_octdigit" => "str.is_ascii_octdigit",
        "is_ascii_lowercase" => "str.is_ascii_lowercase",
        "is_ascii_uppercase" => "str.is_ascii_uppercase",
        "is_ascii_hexdigit" => "str.is_ascii_hexdigit",
        "is_ascii_punctuation" => "str.is_ascii_punctuation",
        "is_ascii_graphic" => "str.is_ascii_graphic",
        "is_ascii_whitespace" => "str.is_ascii_whitespace",
        "is_ascii_control" => "str.is_ascii_control",
        _ => return None,
    };
    Some(atomic_(atom_name, vec![receiver]))
}

fn ascii_byte_class_atom(method: &str, byte: Rc<Term>) -> Option<Rc<Formula>> {
    match method {
        "is_ascii" => Some(byte_is_ascii_formula(byte)),
        "is_ascii_alphabetic" => Some(or_(vec![
            byte_range(byte.clone(), b'A', b'Z'),
            byte_range(byte, b'a', b'z'),
        ])),
        "is_ascii_alphanumeric" => Some(or_(vec![
            byte_range(byte.clone(), b'A', b'Z'),
            byte_range(byte.clone(), b'a', b'z'),
            byte_range(byte, b'0', b'9'),
        ])),
        "is_ascii_digit" => Some(byte_range(byte, b'0', b'9')),
        "is_ascii_octdigit" => Some(byte_range(byte, b'0', b'7')),
        "is_ascii_lowercase" => Some(byte_range(byte, b'a', b'z')),
        "is_ascii_uppercase" => Some(byte_range(byte, b'A', b'Z')),
        "is_ascii_hexdigit" => Some(or_(vec![
            byte_range(byte.clone(), b'0', b'9'),
            byte_range(byte.clone(), b'A', b'F'),
            byte_range(byte, b'a', b'f'),
        ])),
        "is_ascii_punctuation" => Some(or_(vec![
            byte_range(byte.clone(), b'!', b'/'),
            byte_range(byte.clone(), b':', b'@'),
            byte_range(byte.clone(), b'[', b'`'),
            byte_range(byte, b'{', b'~'),
        ])),
        "is_ascii_graphic" => Some(byte_range(byte, b'!', b'~')),
        "is_ascii_whitespace" => Some(or_(vec![
            eq(byte.clone(), num(i64::from(b' '))),
            eq(byte.clone(), num(9)),
            eq(byte.clone(), num(10)),
            eq(byte.clone(), num(12)),
            eq(byte, num(13)),
        ])),
        "is_ascii_control" => Some(or_(vec![
            byte_range(byte.clone(), 0u8, 31u8),
            eq(byte, num(127)),
        ])),
        _ => None,
    }
}

fn byte_is_ascii_formula(byte: Rc<Term>) -> Rc<Formula> {
    and_(vec![gte(byte.clone(), num(0)), lte(byte, num(127))])
}

fn byte_range(byte: Rc<Term>, low: u8, high: u8) -> Rc<Formula> {
    and_(vec![
        gte(byte.clone(), num(i64::from(low))),
        lte(byte, num(i64::from(high))),
    ])
}

fn literal_iterator_elements(expr: &Expr) -> Result<Option<(IteratorKind, Vec<Rc<Term>>)>, String> {
    match expr {
        Expr::MethodCall(call) if call.args.is_empty() && call.method == "chars" => {
            let Some(value) = literal_string_value(&call.receiver) else {
                return Ok(None);
            };
            let elements = value
                .chars()
                .map(|ch| str_const(ch.to_string()))
                .collect::<Vec<_>>();
            Ok(Some((IteratorKind::Chars, elements)))
        }
        Expr::MethodCall(call) if call.args.is_empty() && call.method == "iter" => {
            let Some(bytes) = literal_byte_string_value(&call.receiver) else {
                return Ok(None);
            };
            let elements = bytes.into_iter().map(|b| num(i64::from(b))).collect();
            Ok(Some((IteratorKind::Bytes, elements)))
        }
        Expr::Paren(paren) => literal_iterator_elements(&paren.expr),
        Expr::Group(group) => literal_iterator_elements(&group.expr),
        _ => Ok(None),
    }
}

fn literal_string_value(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value()),
        Expr::Paren(paren) => literal_string_value(&paren.expr),
        Expr::Group(group) => literal_string_value(&group.expr),
        _ => None,
    }
}

fn literal_byte_string_value(expr: &Expr) -> Option<Vec<u8>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::ByteStr(bytes),
            ..
        }) => Some(bytes.value()),
        Expr::Paren(paren) => literal_byte_string_value(&paren.expr),
        Expr::Group(group) => literal_byte_string_value(&group.expr),
        _ => None,
    }
}

fn matches_param_receiver(expr: &Expr, param_name: &str) -> bool {
    match expr {
        Expr::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|segment| segment.ident == param_name),
        Expr::Paren(paren) => matches_param_receiver(&paren.expr, param_name),
        Expr::Group(group) => matches_param_receiver(&group.expr, param_name),
        _ => false,
    }
}

fn method_call_assertion_name(
    method: &str,
    args: Vec<Rc<Term>>,
    local_scope: &str,
) -> Option<String> {
    let term = Term::Ctor {
        name: format!("method:{method}"),
        args,
    };
    callsite_assertion_name(&term, local_scope)
}

fn assertion_entry_from_relation(
    lhs: Rc<Term>,
    rhs: Rc<Term>,
    op: RelationOp,
    scope: &TemporalScope,
) -> AssertionEntry {
    if let Some(tag) =
        constructor_operator_tag(lhs.as_ref()).or_else(|| constructor_operator_tag(rhs.as_ref()))
    {
        return AssertionEntry {
            name: None,
            atom: constructor_operator_atom(lhs, rhs, op, &tag),
        };
    }

    let name = if is_ground_value(lhs.as_ref()) {
        callsite_assertion_name(rhs.as_ref(), scope.local_scope())
    } else if is_ground_value(rhs.as_ref()) {
        callsite_assertion_name(lhs.as_ref(), scope.local_scope())
    } else {
        None
    };
    let atom = match op {
        RelationOp::Eq => eq(lhs, rhs),
        RelationOp::Ne => ne(lhs, rhs),
        RelationOp::Lt => lt(lhs, rhs),
        RelationOp::Le => lte(lhs, rhs),
        RelationOp::Gt => gt(lhs, rhs),
        RelationOp::Ge => gte(lhs, rhs),
    };
    AssertionEntry { name, atom }
}

fn constructor_operator_atom(
    lhs: Rc<Term>,
    rhs: Rc<Term>,
    op: RelationOp,
    tag: &str,
) -> Rc<Formula> {
    // Federated operator-dispatch shape: user-type operators are method calls,
    // so ==/!= lift as equality over the canonical eq call result, and
    // order operators lift as their own canonical call results. Java .equals
    // and Python __eq__ must mirror this byte-for-byte for the same TypeKey.
    let operator_call = Rc::new(Term::Ctor {
        name: format!("call:{}:{tag}", op.operator_call_name()),
        args: vec![lhs, rhs],
    });
    eq(operator_call, bool_const(op.operator_asserted_result()))
}

fn constructor_operator_tag(term: &Term) -> Option<String> {
    let Term::Ctor { name, .. } = term else {
        return None;
    };
    let callee = name.strip_prefix("call:")?;
    let final_segment = callee.rsplit("::").next().unwrap_or(callee);
    final_segment
        .chars()
        .next()
        .is_some_and(|ch| ch.is_ascii_uppercase())
        .then(|| callee.to_string())
}

fn is_ground_value(term: &Term) -> bool {
    match term {
        Term::Const { .. } => true,
        Term::Var { name } if name.starts_with("literal:") => true,
        Term::Ctor { name, args } if is_ground_value_ctor(name) => {
            args.iter().all(|arg| is_ground_value(arg))
        }
        _ => false,
    }
}

fn is_ground_value_ctor(name: &str) -> bool {
    matches!(
        name,
        "+" | "-"
            | "*"
            | "int-div"
            | "int-rem"
            | "bit-and"
            | "bit-or"
            | "bit-xor"
            | "shift-left"
            | "shift-right"
            | "bit-not"
            | "ref"
            | "range"
            | "range_incl"
    )
}

fn bool_const(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(value),
        sort: sugar_ir_symbolic::Sort::bool(),
    })
}

fn callsite_assertion_name(term: &Term, local_scope: &str) -> Option<String> {
    let Term::Ctor { name, .. } = term else {
        return None;
    };
    if is_location_keyed_call_result(name) {
        return None;
    }
    let callee = callsite_callee_name(name)?;
    Some(format!(
        "{callee}#euf#{}::assertion",
        canonical_callsite_sig(term, local_scope)
    ))
}

fn is_location_keyed_call_result(name: &str) -> bool {
    matches!(
        name,
        "call:core::ptr::eq" | "call:ptr::eq" | "call:std::ptr::eq"
    )
}

fn canonical_callsite_sig(term: &Term, local_scope: &str) -> String {
    let Term::Ctor { name, args } = term else {
        return term_key(term);
    };
    let Some(callee) = callsite_callee_name(name) else {
        return term_key(term);
    };
    let head = call_result_head(callee, args.len());
    let inner = args
        .iter()
        .map(|arg| {
            if callee.starts_with("method:") {
                canonical_method_arg_sig(arg, local_scope)
            } else {
                canonical_term_sig(arg)
            }
        })
        .collect::<Vec<_>>()
        .join(",");
    format!("c:{head}({inner})")
}

fn callsite_callee_name(name: &str) -> Option<&str> {
    if name == "str.len" {
        return Some("method:len");
    }
    name.strip_prefix("call:")
        .or_else(|| name.starts_with("method:").then_some(name))
}

fn call_result_head(callee: &str, arity: usize) -> String {
    let safe = callee
        .chars()
        .map(|ch| {
            if ch.is_ascii() && ch.is_ascii_alphanumeric() {
                ch
            } else {
                '_'
            }
        })
        .collect::<String>();
    format!("callresult_{safe}_a{arity}")
}

fn canonical_term_sig(term: &Term) -> String {
    match term {
        Term::Var { name } => format!("v:{name}"),
        Term::Const { value, .. } => match value {
            ConstValue::Int(value) => format!("i:{value}"),
            ConstValue::Real(value) => format!("r:{value}"),
            ConstValue::String(value) => format!("s:{value:?}"),
            ConstValue::Bool(value) => format!("b:{value}"),
        },
        Term::Ctor { name, args } => {
            let inner = args
                .iter()
                .map(|arg| canonical_term_sig(arg))
                .collect::<Vec<_>>()
                .join(",");
            format!("c:{name}({inner})")
        }
        _ => term_key(term),
    }
}

fn canonical_method_arg_sig(term: &Term, local_scope: &str) -> String {
    match term {
        Term::Var { name } if name.starts_with("literal:") => format!("v:{name}"),
        Term::Var { name } if is_unqualified_local_name(name) => {
            format!("v:{local_scope}::{name}")
        }
        Term::Var { name } => format!("v:{name}"),
        Term::Const { value, .. } => match value {
            ConstValue::Int(value) => format!("i:{value}"),
            ConstValue::Real(value) => format!("r:{value}"),
            ConstValue::String(value) => format!("s:{value:?}"),
            ConstValue::Bool(value) => format!("b:{value}"),
        },
        Term::Ctor { name, args } => {
            let inner = args
                .iter()
                .map(|arg| canonical_method_arg_sig(arg, local_scope))
                .collect::<Vec<_>>()
                .join(",");
            format!("c:{name}({inner})")
        }
        _ => term_key(term),
    }
}

fn is_unqualified_local_name(name: &str) -> bool {
    !name.contains("::")
}

fn is_refinement_predicate_term(term: &Term) -> bool {
    matches!(
        term,
        Term::Ctor { name, .. }
            if matches!(
                name.as_str(),
                "method:is_nan"
                    | "method:is_finite"
                    | "method:is_infinite"
                    | "method:is_normal"
                    | "method:is_subnormal"
                    | "method:is_sign_positive"
                    | "method:is_sign_negative"
            )
    )
}

fn term_key(term: &Term) -> String {
    format!("{term:?}")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn translate_term_in_scope(expr: &Expr, scope: &TemporalScope) -> Result<Rc<Term>, String> {
    match expr {
        Expr::Lit(lit) => translate_lit(lit),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            if let Some(value) = const_int(&unary.expr) {
                return Ok(num(-value));
            }
            if let Some(value) = const_float(&unary.expr)? {
                if real_literal_is_zero(&value) {
                    return Err(format!(
                        "signed zero float literal remains an IEEE refinement `{}`",
                        token_key(expr)
                    ));
                }
                return Ok(real_const(format!("-{value}")));
            }
            Err(format!(
                "unsupported negative literal `{}`",
                token_key(expr)
            ))
        }
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => Ok(Rc::new(Term::Ctor {
            name: "bit-not".to_string(),
            args: vec![translate_term_in_scope(&unary.expr, scope)?],
        })),
        // Dereference: *p is a function of the pointer/reference term, the same
        // EUF shape as the immutable-reference arm below. `*a == *b` reasons
        // structurally and a contradiction over one dereferenced term is UNSAT.
        Expr::Unary(unary) if matches!(unary.op, UnOp::Deref(_)) => Ok(Rc::new(Term::Ctor {
            name: "deref".to_string(),
            args: vec![translate_term_in_scope(&unary.expr, scope)?],
        })),
        Expr::Path(path) if path.path.is_ident("None") => Ok(Rc::new(Term::Ctor {
            name: "call:None".to_string(),
            args: Vec::new(),
        })),
        Expr::Path(path) => Ok(make_var(scope.path_name(&path.path)?)),
        Expr::Call(call) => {
            if let Some(term) = type_id_of_call_term(&call.func, call.args.len())? {
                return Ok(term);
            }
            let mut args = Vec::new();
            for arg in &call.args {
                args.push(translate_term_in_scope(arg, scope)?);
            }
            Ok(Rc::new(Term::Ctor {
                name: format!("call:{}", expr_head_key(&call.func)),
                args,
            }))
        }
        Expr::Array(array) => {
            literal_aggregate_term_in_scope("Array", array.elems.iter(), expr, scope)
        }
        Expr::Tuple(tuple) => {
            literal_aggregate_term_in_scope("Tuple", tuple.elems.iter(), expr, scope)
        }
        Expr::Repeat(repeat) => {
            // `[elem; N]` is an N-element array constructor. With a LITERAL count it
            // is EXACTLY the N-fold explicit array `[elem, elem, ...]`, the same value
            // and (by construction) the same aggregate term -- so `[0xab; 3]` and
            // `[0xab, 0xab, 0xab]` are congruent, and two different repeats are
            // distinct terms (the teeth). A non-literal count is not a finite
            // construction from the written literal, so it is REFUSED BY NAME; an
            // element that does not translate propagates its own named Err.
            let Some(count) = repeat_count_literal(&repeat.len) else {
                return Err(format!(
                    "array-repeat `[_; N]` has a non-literal length -- not a finite \
                     construction from the literal; refused by name: `{}`",
                    token_key(expr)
                ));
            };
            // Bound the expansion so a pathological literal length cannot blow up the
            // term; an over-bound repeat is named, not silently truncated.
            const MAX_REPEAT: usize = 4096;
            if count > MAX_REPEAT {
                return Err(format!(
                    "array-repeat length {count} exceeds the {MAX_REPEAT}-element \
                     expansion bound; refused by name: `{}`",
                    token_key(expr)
                ));
            }
            let elem_refs = std::iter::repeat(&*repeat.expr).take(count);
            literal_aggregate_term_in_scope("Array", elem_refs, expr, scope)
        }
        Expr::Struct(s) => {
            // A struct / enum-struct literal `Path { f: v, ... }` is a constructor.
            // Lift it to a Ctor keyed by the path, with one `field:<name>` sub-ctor
            // per field. Fields are SORTED BY NAME so the term is canonical (source
            // field order is irrelevant: `V { a, b }` and `V { b, a }` are the same
            // value -> the same term) while field names stay significant
            // (`V { a: x }` != `V { b: x }`). Two distinct literals are distinct
            // Ctors -> asserting equality with the wrong one is UNSAT (the teeth).
            //
            // A functional-update `..rest` means the value is NOT fully pinned from
            // the literal, so it is refused by name (not silently approximated).
            // A field value that does not translate propagates its own named Err.
            if s.rest.is_some() {
                return Err(format!(
                    "struct literal with `..rest` is not fully pinned from the literal: `{}`",
                    token_key(expr)
                ));
            }
            let mut fields: Vec<(String, Rc<Term>)> = Vec::new();
            for fv in &s.fields {
                let fname = match &fv.member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                fields.push((fname, translate_term_in_scope(&fv.expr, scope)?));
            }
            fields.sort_by(|a, b| a.0.cmp(&b.0));
            let args = fields
                .into_iter()
                .map(|(fname, term)| {
                    Rc::new(Term::Ctor {
                        name: format!("field:{fname}"),
                        args: vec![term],
                    })
                })
                .collect();
            Ok(Rc::new(Term::Ctor {
                name: format!("struct:{}", path_to_variant_string(&s.path)),
                args,
            }))
        }
        Expr::MethodCall(call) => {
            // A closure-bearing iterator/Option adaptor in TERM position (e.g.
            // `assert_eq!(opt.map(|v| ..), x)`) refuses with the collection
            // provenance, not a bare "unsupported term `|v|`" -- so the bin sort is
            // PROVEN (opaque receiver -> bin-2), not presumed. Same rigor the
            // bool-assertion path already applies to `.all`/`.any`.
            if let Some(reason) = closure_adaptor_refusal(expr) {
                return Err(reason);
            }
            let mut args = vec![translate_term_in_scope(&call.receiver, scope)?];
            for arg in &call.args {
                args.push(translate_term_in_scope(arg, scope)?);
            }
            let method = match &call.turbofish {
                Some(args) => format!("{}{}", call.method, angle_args_key(args)),
                None => call.method.to_string(),
            };
            Ok(Rc::new(Term::Ctor {
                name: format!("method:{method}"),
                args,
            }))
        }
        Expr::Await(await_expr) => Ok(Rc::new(Term::Ctor {
            name: "await".to_string(),
            args: vec![translate_term_in_scope(&await_expr.base, scope)?],
        })),
        // Only the immutable borrow is a stable term. `&mut x` stays residual:
        // a mutable referent can change between observations (temporal identity),
        // so coalescing two `&mut x` terms would be unsound. See the
        // mutable_reference_pointer_eq_stays_residual guard test.
        Expr::Reference(reference) if reference.mutability.is_none() => Ok(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![translate_term_in_scope(&reference.expr, scope)?],
        })),
        Expr::Cast(cast) => {
            if is_shared_dyn_any_type(&cast.ty) {
                return Ok(Rc::new(Term::Ctor {
                    name: format!("cast:{}", type_key(&cast.ty)),
                    args: vec![translate_term_in_scope(&cast.expr, scope)?],
                }));
            }
            if let Some(cast_type) = integer_scalar_cast_type_key(&cast.ty) {
                return Ok(Rc::new(Term::Ctor {
                    name: format!("cast:{cast_type}"),
                    args: vec![translate_term_in_scope(&cast.expr, scope)?],
                }));
            }
            Err(format!("unsupported term `{}`", token_key(expr)))
        }
        Expr::Range(range) => {
            let start = match &range.start {
                Some(expr) => translate_term_in_scope(expr, scope)?,
                None => make_var("_"),
            };
            let end = match &range.end {
                Some(expr) => translate_term_in_scope(expr, scope)?,
                None => make_var("_"),
            };
            let name = match range.limits {
                syn::RangeLimits::HalfOpen(_) => "range",
                syn::RangeLimits::Closed(_) => "range_incl",
            };
            Ok(Rc::new(Term::Ctor {
                name: name.to_string(),
                args: vec![start, end],
            }))
        }
        Expr::Field(field) => Ok(Rc::new(Term::Ctor {
            name: format!("field:{}", token_key(&field.member)),
            args: vec![translate_term_in_scope(&field.base, scope)?],
        })),
        Expr::Index(index) => {
            if let Some(term) = const_index_term_in_scope(index, scope)? {
                return Ok(term);
            }
            // General a[i] is the IR term index(a, i). Sound iff the container is
            // temporally stable. The `mut` oracle (L4) decides: a non-`mut` local
            // is provably immutable, so index(a, i) is a stable term; a `mut`
            // local may be index-assigned or method-mutated in ways the tracker
            // cannot follow, so it stays residual. Non-local containers (a call
            // result, a field) translate through their own EUF terms.
            if let Some(name) = simple_path_name(&index.expr) {
                if scope.is_mut_local(&name) {
                    return Err(format!(
                        "unsupported term `{}`: mutable container is not temporally stable",
                        token_key(expr)
                    ));
                }
            }
            let container = translate_term_in_scope(&index.expr, scope)?;
            let idx = translate_term_in_scope(&index.index, scope)?;
            Ok(Rc::new(Term::Ctor {
                name: "index".to_string(),
                args: vec![container, idx],
            }))
        }
        Expr::Binary(binary) => {
            let Some(op) = term_binop_name(&binary.op) else {
                return Err(format!("unsupported term operator `{}`", token_key(expr)));
            };
            Ok(Rc::new(Term::Ctor {
                name: op.to_string(),
                args: vec![
                    translate_term_in_scope(&binary.left, scope)?,
                    translate_term_in_scope(&binary.right, scope)?,
                ],
            }))
        }
        Expr::Paren(paren) => translate_term_in_scope(&paren.expr, scope),
        Expr::Group(group) => translate_term_in_scope(&group.expr, scope),
        // A macro invocation in term position (format!, vec!, offset_of!, ...)
        // is desugared to an uninterpreted function term keyed by its canonical
        // source tokens. Identical macro calls map to the same term (congruence),
        // so a contradiction like `format!(a) == "p" && format!(a) == "q"` stays
        // UNSAT; distinct calls map to distinct terms. The witness re-run proves
        // the actual runtime value; consistency only checks non-contradiction.
        Expr::Macro(_) => Ok(make_var(format!("macro:{}", token_key(expr)))),
        other => Err(format!("unsupported term `{}`", token_key(other))),
    }
}

fn const_index_term_in_scope(
    index: &syn::ExprIndex,
    scope: &TemporalScope,
) -> Result<Option<Rc<Term>>, String> {
    let Some(index_value) = const_int(&index.index) else {
        return Ok(None);
    };
    let Some(base_name) = const_index_base_name(&index.expr, scope)? else {
        return Ok(None);
    };
    Ok(Some(Rc::new(Term::Ctor {
        name: "index".to_string(),
        args: vec![make_var(base_name), num(index_value)],
    })))
}

fn const_index_base_name(expr: &Expr, scope: &TemporalScope) -> Result<Option<String>, String> {
    match expr {
        Expr::Path(path) if path.qself.is_none() && is_const_like_path(&path.path) => {
            scope.path_name(&path.path).map(Some)
        }
        Expr::Paren(paren) => const_index_base_name(&paren.expr, scope),
        Expr::Group(group) => const_index_base_name(&group.expr, scope),
        _ => Ok(None),
    }
}

fn is_const_like_path(path: &syn::Path) -> bool {
    let Some(final_segment) = path.segments.last() else {
        return false;
    };
    let ident = final_segment.ident.to_string();
    ident.chars().any(|ch| ch.is_ascii_uppercase())
        && ident
            .chars()
            .all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_')
}

fn translate_assertion_term_in_scope(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Rc<Term>, String> {
    match expr {
        Expr::Const(const_block) => {
            let term =
                translate_expression_only_block_in_scope(&const_block.block, "const", scope)?;
            Ok(scope_const_block_locals(term, scope.local_scope()))
        }
        Expr::Path(path) if path.path.is_ident("None") => Ok(Rc::new(Term::Ctor {
            name: "call:None".to_string(),
            args: Vec::new(),
        })),
        Expr::Paren(paren) => translate_assertion_term_in_scope(&paren.expr, scope),
        Expr::Group(group) => translate_assertion_term_in_scope(&group.expr, scope),
        _ => translate_term_in_scope(expr, scope),
    }
}

fn scope_const_block_locals(term: Rc<Term>, local_scope: &str) -> Rc<Term> {
    match term.as_ref() {
        Term::Var { name } if should_scope_const_block_var(name) => {
            make_var(format!("{local_scope}::{name}"))
        }
        Term::Ctor { name, args } => Rc::new(Term::Ctor {
            name: name.clone(),
            args: args
                .iter()
                .map(|arg| scope_const_block_locals(arg.clone(), local_scope))
                .collect(),
        }),
        _ => term,
    }
}

fn should_scope_const_block_var(name: &str) -> bool {
    is_unqualified_local_name(name) && name != "_" && !name.starts_with("literal:")
}

fn translate_expression_only_block_in_scope(
    block: &syn::Block,
    label: &str,
    scope: &TemporalScope,
) -> Result<Rc<Term>, String> {
    match block.stmts.as_slice() {
        [Stmt::Expr(expr, None)] => {
            if let Some(nested_const) = find_const_expr(expr) {
                return Err(format!("unsupported term `{}`", token_key(nested_const)));
            }
            translate_term_in_scope(expr, scope)
        }
        _ => Err(format!(
            "{label} block is not an expression-only term `{}`",
            token_key(block)
        )),
    }
}

fn find_const_expr(expr: &Expr) -> Option<&Expr> {
    match expr {
        Expr::Const(_) => Some(expr),
        Expr::Unary(unary) => find_const_expr(&unary.expr),
        Expr::Call(call) => call
            .args
            .iter()
            .find_map(find_const_expr)
            .or_else(|| find_const_expr(&call.func)),
        Expr::Array(array) => array.elems.iter().find_map(find_const_expr),
        Expr::Tuple(tuple) => tuple.elems.iter().find_map(find_const_expr),
        Expr::MethodCall(call) => {
            find_const_expr(&call.receiver).or_else(|| call.args.iter().find_map(find_const_expr))
        }
        Expr::Await(await_expr) => find_const_expr(&await_expr.base),
        Expr::Reference(reference) => find_const_expr(&reference.expr),
        Expr::Cast(cast) => find_const_expr(&cast.expr),
        Expr::Range(range) => range
            .start
            .as_deref()
            .and_then(find_const_expr)
            .or_else(|| range.end.as_deref().and_then(find_const_expr)),
        Expr::Field(field) => find_const_expr(&field.base),
        Expr::Binary(binary) => {
            find_const_expr(&binary.left).or_else(|| find_const_expr(&binary.right))
        }
        Expr::Paren(paren) => find_const_expr(&paren.expr),
        Expr::Group(group) => find_const_expr(&group.expr),
        _ => None,
    }
}

/// The length of an array-repeat `[elem; N]` as a `usize`, iff `N` is a plain
/// integer literal (the only finitely-constructible case). A `const`/path length
/// (`[0; LEN]`) returns None and is refused by name upstream.
fn repeat_count_literal(len: &Expr) -> Option<usize> {
    match len {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<usize>().ok(),
        Expr::Paren(p) => repeat_count_literal(&p.expr),
        Expr::Group(g) => repeat_count_literal(&g.expr),
        _ => None,
    }
}

fn literal_aggregate_term_in_scope<'a>(
    kind: &str,
    elems: impl Iterator<Item = &'a Expr>,
    source: &Expr,
    scope: &TemporalScope,
) -> Result<Rc<Term>, String> {
    let _ = source;
    let mut args = Vec::new();
    let mut all_literal = true;
    for elem in elems {
        // Each element is translated through the same sound term path. An
        // element that cannot be translated (e.g. a &mut borrow) propagates its
        // refusal via `?`, so the aggregate is only built from accountable terms.
        let term = translate_term_in_scope(elem, scope)?;
        if !is_literal_identity_term(term.as_ref()) {
            all_literal = false;
        }
        args.push(term);
    }
    let inner = args
        .iter()
        .map(|arg| canonical_term_sig(arg))
        .collect::<Vec<_>>()
        .join(",");
    // All-literal aggregates keep the literal: key (byte-identical to before).
    // Aggregates with non-literal elements are an uninterpreted constructor over
    // their element terms (agg:), congruence-keyed so contradictions are caught.
    let prefix = if all_literal { "literal" } else { "agg" };
    Ok(make_var(format!("{prefix}:{kind}({inner})")))
}

fn is_literal_identity_term(term: &Term) -> bool {
    match term {
        Term::Const { .. } => true,
        Term::Var { name } => name.starts_with("literal:"),
        Term::Ctor { name, args } if constructor_operator_tag(term).is_some() => {
            name.starts_with("call:") && args.iter().all(|arg| is_literal_identity_term(arg))
        }
        _ => false,
    }
}

fn type_id_of_call_term(func: &Expr, arg_len: usize) -> Result<Option<Rc<Term>>, String> {
    if arg_len != 0 {
        return Ok(None);
    }
    let Expr::Path(path) = func else {
        return Ok(None);
    };
    if !is_type_id_of_path(&path.path) {
        return Ok(None);
    }
    let Some(last) = path.path.segments.last() else {
        return Ok(None);
    };
    let syn::PathArguments::AngleBracketed(args) = &last.arguments else {
        return Err("TypeId::of requires exactly one type argument".to_string());
    };
    if args.args.len() != 1 {
        return Err("TypeId::of requires exactly one type argument".to_string());
    }
    let Some(syn::GenericArgument::Type(ty)) = args.args.first() else {
        return Err("TypeId::of requires a type argument".to_string());
    };
    Ok(Some(Rc::new(Term::Ctor {
        name: format!("type_id::{}", type_key(ty)),
        args: Vec::new(),
    })))
}

fn is_type_id_of_path(path: &syn::Path) -> bool {
    let segments = path.segments.iter().collect::<Vec<_>>();
    matches!(
        segments.as_slice(),
        [.., type_id, of]
            if type_id.ident == "TypeId" && of.ident == "of"
    )
}

fn is_shared_dyn_any_type(ty: &syn::Type) -> bool {
    let syn::Type::Reference(reference) = ty else {
        return false;
    };
    if reference.mutability.is_some() {
        return false;
    }
    let syn::Type::TraitObject(trait_object) = reference.elem.as_ref() else {
        return false;
    };
    trait_object.bounds.iter().any(|bound| {
        let syn::TypeParamBound::Trait(trait_bound) = bound else {
            return false;
        };
        trait_bound
            .path
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "Any")
    })
}

fn integer_scalar_cast_type_key(ty: &syn::Type) -> Option<&'static str> {
    let syn::Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() != 1 {
        return None;
    }
    let segment = path.path.segments.first()?;
    if !matches!(segment.arguments, syn::PathArguments::None) {
        return None;
    }
    match segment.ident.to_string().as_str() {
        "i8" => Some("i8"),
        "i16" => Some("i16"),
        "i32" => Some("i32"),
        "i64" => Some("i64"),
        "i128" => Some("i128"),
        "isize" => Some("isize"),
        "u8" => Some("u8"),
        "u16" => Some("u16"),
        "u32" => Some("u32"),
        "u64" => Some("u64"),
        "u128" => Some("u128"),
        "usize" => Some("usize"),
        _ => None,
    }
}

fn translate_lit(lit: &ExprLit) -> Result<Rc<Term>, String> {
    match &lit.lit {
        Lit::Int(i) => parse_int_lit(i).map(num),
        Lit::Float(f) => canonical_float_literal(f).map(real_const),
        Lit::Str(s) => Ok(str_const(s.value())),
        Lit::Char(c) => Ok(str_const(c.value().to_string())),
        Lit::Bool(b) => Ok(bool_const(b.value)),
        Lit::ByteStr(bs) => Ok(bytes_literal_term_from_bytes(&bs.value())),
        other => Err(format!(
            "only integer/string/char/finite decimal float scalar constants are liftable, got `{}`",
            token_key(other)
        )),
    }
}

/// Encode a byte slice as a lower-hex string: each byte as exactly two hex
/// digits, concatenated.  No external crate dependency required.
fn bytes_to_hex(bytes: &[u8]) -> String {
    bytes
        .iter()
        .flat_map(|b| {
            let hi = (b >> 4) & 0xf;
            let lo = b & 0xf;
            [
                char::from_digit(u32::from(hi), 16).unwrap_or('0'),
                char::from_digit(u32::from(lo), 16).unwrap_or('0'),
            ]
        })
        .collect()
}

/// Produce an opaque content-keyed term for a byte-string literal.
///
/// The term is `Term::Var { name: "literal:bytes(<hex>)" }` where `<hex>` is
/// the lower-hex encoding of the byte content.  This mirrors the
/// `literal_aggregate_term_in_scope` convention: the `literal:` prefix marks
/// the var as a ground identity value throughout the lifter.
///
/// Soundness: identical byte sequences produce identical names (congruence);
/// distinct byte sequences produce distinct names, so any conjunction that
/// equates a single call result to two different byte literals is
/// internally contradictory and will be flagged UNSAT by the solver.
fn bytes_literal_term_from_bytes(bytes: &[u8]) -> Rc<Term> {
    make_var(format!("literal:bytes({})", bytes_to_hex(bytes)))
}

/// Extract a byte-string literal from `expr` as an opaque content-keyed
/// Term::Var, if `expr` is exactly a `b"..."` literal (or a parenthesised /
/// grouped wrapper around one).  Returns `None` for all other expression
/// shapes.
fn bytes_literal_term(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::ByteStr(bs),
            ..
        }) => Some(bytes_literal_term_from_bytes(&bs.value())),
        Expr::Paren(paren) => bytes_literal_term(&paren.expr),
        Expr::Group(group) => bytes_literal_term(&group.expr),
        _ => None,
    }
}

fn parse_int_lit(lit: &syn::LitInt) -> Result<i64, String> {
    let mut text = lit.to_string();
    let suffix = lit.suffix();
    if !suffix.is_empty() && text.ends_with(suffix) {
        text.truncate(text.len() - suffix.len());
    }
    let text = text.replace('_', "");
    let (radix, digits) =
        if let Some(rest) = text.strip_prefix("0x").or_else(|| text.strip_prefix("0X")) {
            (16, rest)
        } else if let Some(rest) = text.strip_prefix("0o").or_else(|| text.strip_prefix("0O")) {
            (8, rest)
        } else if let Some(rest) = text.strip_prefix("0b").or_else(|| text.strip_prefix("0B")) {
            (2, rest)
        } else {
            (10, text.as_str())
        };
    i64::from_str_radix(digits, radix).map_err(|e| format!("int literal `{}`: {e}", lit))
}

fn string_or_char_literal_term(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(str_const(s.value())),
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(str_const(c.value().to_string())),
        Expr::Paren(paren) => string_or_char_literal_term(&paren.expr),
        Expr::Group(group) => string_or_char_literal_term(&group.expr),
        _ => None,
    }
}

fn char_literal_term(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(str_const(c.value().to_string())),
        Expr::Paren(paren) => char_literal_term(&paren.expr),
        Expr::Group(group) => char_literal_term(&group.expr),
        _ => None,
    }
}

fn canonical_float_literal(lit: &syn::LitFloat) -> Result<String, String> {
    let digits = lit.base10_digits().replace('_', "");
    if digits.is_empty() {
        return Err("empty float literal".to_string());
    }
    if digits.contains('e') || digits.contains('E') {
        return normalize_decimal_exponent_literal(&digits).map_err(|e| {
            format!(
                "float literal with exponent is not exact decimal syntax `{}`: {e}",
                lit.to_token_stream()
            )
        });
    }
    Ok(digits)
}

fn normalize_decimal_exponent_literal(text: &str) -> Result<String, String> {
    let lower = text.to_ascii_lowercase();
    let (mantissa, exponent) = lower
        .split_once('e')
        .ok_or_else(|| "missing exponent marker".to_string())?;
    if exponent.contains('e') {
        return Err("multiple exponent markers".to_string());
    }
    let exponent: i64 = exponent
        .parse()
        .map_err(|e| format!("invalid exponent: {e}"))?;
    if exponent.unsigned_abs() > 10_000 {
        return Err("exponent is too large to normalize safely".to_string());
    }

    let mut digits = String::new();
    let mut fractional_digits = 0i64;
    let mut seen_dot = false;
    for ch in mantissa.chars() {
        match ch {
            '.' if !seen_dot => seen_dot = true,
            '.' => return Err("multiple decimal points".to_string()),
            ch if ch.is_ascii_digit() => {
                digits.push(ch);
                if seen_dot {
                    fractional_digits += 1;
                }
            }
            _ => return Err(format!("invalid mantissa character `{ch}`")),
        }
    }
    if digits.is_empty() {
        return Err("empty mantissa".to_string());
    }

    let scale = fractional_digits - exponent;
    if scale <= 0 {
        let zeros = usize::try_from(-scale).map_err(|_| "invalid exponent scale".to_string())?;
        digits.extend(std::iter::repeat_n('0', zeros));
        return Ok(normalize_integer_digits(&digits));
    }

    let scale = usize::try_from(scale).map_err(|_| "invalid exponent scale".to_string())?;
    if digits.len() <= scale {
        let zeros = scale - digits.len();
        let mut out = String::from("0.");
        out.extend(std::iter::repeat_n('0', zeros));
        out.push_str(&digits);
        return Ok(normalize_decimal_digits(&out));
    }

    let split = digits.len() - scale;
    let mut out = digits[..split].to_string();
    out.push('.');
    out.push_str(&digits[split..]);
    Ok(normalize_decimal_digits(&out))
}

fn normalize_integer_digits(text: &str) -> String {
    let trimmed = text.trim_start_matches('0');
    if trimmed.is_empty() {
        "0".to_string()
    } else {
        trimmed.to_string()
    }
}

fn normalize_decimal_digits(text: &str) -> String {
    let (int_part, frac_part) = text
        .split_once('.')
        .expect("normalizer calls this only for decimal text");
    let int_part = normalize_integer_digits(int_part);
    let frac_part = frac_part.trim_end_matches('0');
    if frac_part.is_empty() {
        int_part
    } else {
        format!("{int_part}.{frac_part}")
    }
}

fn const_float(expr: &Expr) -> Result<Option<String>, String> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Float(lit),
            ..
        }) => Ok(Some(canonical_float_literal(lit)?)),
        Expr::Paren(paren) => const_float(&paren.expr),
        Expr::Group(group) => const_float(&group.expr),
        _ => Ok(None),
    }
}

fn real_literal_is_zero(text: &str) -> bool {
    let text = text.strip_prefix('-').unwrap_or(text);
    let mut saw_digit = false;
    for ch in text.chars() {
        if ch == '.' {
            continue;
        }
        saw_digit = true;
        if ch != '0' {
            return false;
        }
    }
    saw_digit
}

fn const_int(expr: &Expr) -> Option<i64> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => parse_int_lit(i).ok(),
        Expr::Paren(paren) => const_int(&paren.expr),
        Expr::Group(group) => const_int(&group.expr),
        _ => None,
    }
}

fn term_binop_name(op: &BinOp) -> Option<&'static str> {
    match op {
        BinOp::Add(_) => Some("+"),
        BinOp::Sub(_) => Some("-"),
        BinOp::Mul(_) => Some("*"),
        BinOp::Div(_) => Some("int-div"),
        BinOp::Rem(_) => Some("int-rem"),
        BinOp::BitAnd(_) => Some("bit-and"),
        BinOp::BitOr(_) => Some("bit-or"),
        BinOp::BitXor(_) => Some("bit-xor"),
        BinOp::Shl(_) => Some("shift-left"),
        BinOp::Shr(_) => Some("shift-right"),
        _ => None,
    }
}

fn expr_head_key(expr: &Expr) -> String {
    match expr {
        Expr::Path(path) => path_to_name(&path.path),
        Expr::Paren(paren) => expr_head_key(&paren.expr),
        Expr::Group(group) => expr_head_key(&group.expr),
        other => token_key(other),
    }
}

fn path_to_name(path: &syn::Path) -> String {
    path.segments
        .iter()
        .map(|segment| {
            let mut name = segment.ident.to_string();
            name.push_str(&path_arguments_key(&segment.arguments));
            name
        })
        .collect::<Vec<_>>()
        .join("::")
}

fn path_arguments_key(arguments: &syn::PathArguments) -> String {
    match arguments {
        syn::PathArguments::None => String::new(),
        syn::PathArguments::AngleBracketed(args) => angle_args_key(args),
        syn::PathArguments::Parenthesized(args) => token_key(args),
    }
}

fn angle_args_key(args: &syn::AngleBracketedGenericArguments) -> String {
    let inner = args
        .args
        .iter()
        .map(generic_arg_key)
        .collect::<Vec<_>>()
        .join(",");
    format!("::<{inner}>")
}

fn generic_arg_key(arg: &syn::GenericArgument) -> String {
    match arg {
        syn::GenericArgument::Type(ty) => type_key(ty),
        syn::GenericArgument::Const(expr) => format!("const:{}", token_key(expr)),
        syn::GenericArgument::Lifetime(lifetime) => format!("'{}", lifetime.ident),
        syn::GenericArgument::AssocType(assoc) => {
            format!("{}={}", assoc.ident, type_key(&assoc.ty))
        }
        syn::GenericArgument::AssocConst(assoc) => {
            format!("{}=const:{}", assoc.ident, token_key(&assoc.value))
        }
        syn::GenericArgument::Constraint(constraint) => token_key(constraint),
        _ => token_key(arg),
    }
}

fn type_key(ty: &syn::Type) -> String {
    match ty {
        syn::Type::Path(path) => path_to_name(&path.path),
        syn::Type::Reference(reference) => {
            let mut out = String::from("&");
            if let Some(lifetime) = &reference.lifetime {
                out.push('\'');
                out.push_str(&lifetime.ident.to_string());
                out.push(' ');
            }
            if reference.mutability.is_some() {
                out.push_str("mut ");
            }
            out.push_str(&type_key(&reference.elem));
            out
        }
        syn::Type::Tuple(tuple) => {
            let inner = tuple
                .elems
                .iter()
                .map(type_key)
                .collect::<Vec<_>>()
                .join(",");
            format!("({inner})")
        }
        syn::Type::Array(array) => {
            format!("[{};{}]", type_key(&array.elem), token_key(&array.len))
        }
        syn::Type::Slice(slice) => format!("[{}]", type_key(&slice.elem)),
        syn::Type::TraitObject(trait_object) => {
            let bounds = trait_object
                .bounds
                .iter()
                .map(|bound| match bound {
                    syn::TypeParamBound::Trait(trait_bound) => path_to_name(&trait_bound.path),
                    syn::TypeParamBound::Lifetime(lifetime) => format!("'{}", lifetime.ident),
                    _ => token_key(bound),
                })
                .collect::<Vec<_>>()
                .join("+");
            format!("dyn {bounds}")
        }
        _ => token_key(ty),
    }
}

fn token_key<T: ToTokens>(node: T) -> String {
    node.to_token_stream()
        .to_string()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}
