//! Dissolving rust stdlib sugar by throwing it at the compiler.
//!
//! THE STDLIB-SUGAR HANDLER (T 2026-06-14). This is NOT a catch/fallback for things
//! symbolic lifting failed on. It is the first-class, designated handler for ONE
//! category: rust *standard-library sugar* -- the closed, deterministic, total,
//! effect-free computations that are "just how rust is written" (float formatting,
//! char case-mapping, `escape_*`, ...). We deliberately do NOT model these in FOL,
//! because stdlib IS the axiom: a stdlib term is dissolved by EVALUATING it with the
//! same stdlib the kit ships. "Need stdlib to prove stdlib? Yes -- that's the named,
//! pinned TCB; axioms all the way down, then a floor with a name on it." User logic
//! is still modeled and checked; only stdlib sugar is dissolved this way.
//!
//! THE TRICK (T): we already have the compiling code. Don't reconstruct a minimal
//! snippet by hand -- lift the problematic stdlib term (and any *pure local helpers*
//! it calls) verbatim into a throwaway harness, hand it to `rustc`, and run it. The
//! harness CONTAINS stdlib, so stdlib is its own evaluation table -- nothing
//! hand-mapped, nothing to drift. A green run is the dissolution; it is sound because
//! the term is closed + deterministic (so one run is universal) and the toolchain is
//! pinned (so the answer is reproducible / re-walkable).
//!
//! THE HARD BOUNDARY (T, emphatic): this is ONLY for vendor-written STDLIB SUGAR. It
//! is NOT a general "we couldn't model this expression, so let's just run it" cheat.
//! Running an expression to trust its result is the green-tests trap / the EUF
//! tautology in another coat: it trusts the code-under-test. The dividing line is what
//! the vendor WROTE:
//!   * vendor wrote stdlib sugar (`format!`, `.to_lowercase()`, `.count_ones()`) ->
//!     DISSOLVE (stdlib is the axiom; evaluating it grounds in the named TCB).
//!   * vendor wrote logic we are meant to verify -> MODEL + CHECK it; never run-to-trust.
//! A USER function NEVER qualifies, even if closed and pure -- the user's algorithm is
//! precisely the thing under proof; harnessing it would be circular. The eligibility
//! GATE is therefore an ALLOWLIST of stdlib's own pure surface (a carried local helper
//! qualifies only if its body bottoms out, recursively, in stdlib sugar + literals --
//! no user algorithm). This driver must NEVER be invoked on anything the gate has not
//! certified as stdlib sugar.
//!
//! THIRD FENCE -- UNIT-TEST ASSERTIONS ONLY, NEVER GENERALIZATION (T). This applies
//! solely to detected unit-test assertions: a finite set of pinned CONCRETE
//! `(input -> output)` instances. Each is closed, so each is evaluable, and one run is
//! the WHOLE truth for that instance. A GENERALIZATION (`forall x. P(x)`, a free
//! variable) cannot be run -- a single concrete run is only a sample, never a proof of
//! the universal -- so dissolution may NEVER touch it. We discharge exactly the
//! concrete assertion the vendor pinned and never extrapolate to a general property.
//! ("Vendor tests ARE the spec": lift the concrete claim, do not invent a universal.)
//! The gate folds all three fences into one predicate: CLOSED (no free vars) =
//! concrete = unit-test-shaped; a free var (generalization) disqualifies, exactly as a
//! non-stdlib op (user logic) disqualifies.
//!
//! SOUNDNESS BOUNDARY (ours, not stdlib's): the gate decides eligibility; the harness
//! only supplies VALUES. This module is just the driver: given a prelude + a list of
//! gated stdlib-sugar assert statements, compile once, run, and report which held.

use std::io::Write;
use std::path::Path;
use std::process::Command;

use syn::Expr;

/// Method/function names that are NOT value-sugar: pointer/address, time, IO, RNG,
/// concurrency, env/fs, unsafe reinterpretation. An assertion operand naming any of
/// these is rejected (out of the stdlib-VALUE-sugar category, per T's boundaries) even
/// if it happens to evaluate deterministically. Closedness (below) already rejects the
/// common cases (their receivers are runtime locals, not literals); this is a focused
/// backstop for the rare impure-op-on-a-literal.
const IMPURE_NAMES: &[&str] = &[
    "as_ptr", "as_mut_ptr", "addr", "expose_addr", "expose_provenance", "with_addr",
    "from_raw", "into_raw", "transmute", "transmute_copy", "assume_init",
    "now", "elapsed", "duration_since", "instant",
    "read", "write", "read_to_string", "stdin", "stdout", "stderr", "lock",
    "random", "gen", "gen_range", "fill", "next_u32", "next_u64",
    "spawn", "join", "load", "store", "fetch_add", "fetch_sub", "fetch_or",
    "compare_exchange", "swap", "send", "recv", "try_recv",
    "var", "vars", "args", "open", "metadata", "create", "remove_file",
];

/// Certify that every operand of a unit-test assertion is CLOSED STDLIB VALUE SUGAR
/// (fences #1-#3): built only from literals / const-or-ctor paths and stdlib method
/// calls, with NO free variable (generalization), NO call to a user/local function
/// (logic to model), and NO impure op. This is the eligibility gate; only operands it
/// certifies may be handed to the harness driver.
pub fn assert_operands_are_stdlib_sugar(operands: &[&Expr]) -> bool {
    !operands.is_empty() && operands.iter().all(|e| closed_pure_sugar(e))
}

/// A path is an acceptable closed leaf if it is a value constructor / enum variant
/// (`Some`/`Ok`/`Err`/`Ordering::Less`/...) or a SCREAMING_SNAKE associated const
/// (`f64::MAX`, `char::MAX`, `u32::BITS`). A bare lowercase identifier is a free
/// variable or a local binding -> rejected (not closed).
fn is_const_or_ctor_path(p: &syn::Path) -> bool {
    let Some(last) = p.path_last_ident() else {
        return false;
    };
    let s = last;
    // value ctors / enum variants: first char uppercase, rest not screaming-only is fine
    let first_upper = s.chars().next().map(|c| c.is_uppercase()).unwrap_or(false);
    // SCREAMING_SNAKE const: all uppercase / digits / underscore
    let screaming = !s.is_empty()
        && s.chars().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_');
    first_upper || screaming
}

trait PathLastIdent {
    fn path_last_ident(&self) -> Option<String>;
}
impl PathLastIdent for syn::Path {
    fn path_last_ident(&self) -> Option<String> {
        self.segments.last().map(|s| s.ident.to_string())
    }
}

fn closed_pure_sugar(expr: &Expr) -> bool {
    match expr {
        // literals: the pinned leaves.
        Expr::Lit(_) => true,
        // const / ctor / variant path (None, f64::MAX, Ordering::Less); a bare lowercase
        // ident (free var / local) fails is_const_or_ctor_path.
        Expr::Path(p) => is_const_or_ctor_path(&p.path),
        // value constructor / variant call: Some(x), Ok(x), Wrapping(x). The callee must
        // be an uppercase ctor path (NOT a lowercase user/local fn -> fence #1), args pure.
        Expr::Call(c) => {
            let ctor = matches!(c.func.as_ref(), Expr::Path(p) if is_const_or_ctor_path(&p.path));
            ctor && c.args.iter().all(closed_pure_sugar)
        }
        // stdlib method sugar on a closed receiver: 'A'.to_digit(16), "x".to_ascii_uppercase().
        // Receiver + args must be closed-pure; the method name must not be impure.
        Expr::MethodCall(m) => {
            let name = m.method.to_string();
            !IMPURE_NAMES.contains(&name.as_str())
                && closed_pure_sugar(&m.receiver)
                && m.args.iter().all(closed_pure_sugar)
        }
        // format!/concat!/... over pure args is value sugar; reject impure-named macros.
        Expr::Macro(mac) => {
            use syn::parse::Parser;
            use syn::punctuated::Punctuated;
            let name = mac
                .mac
                .path
                .path_last_ident()
                .unwrap_or_default();
            if !matches!(name.as_str(), "format" | "concat" | "stringify" | "vec") {
                return false;
            }
            let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
            match parser.parse2(mac.mac.tokens.clone()) {
                // stringify! takes arbitrary tokens but its result is a literal of the
                // SOURCE text -- pure regardless of args.
                _ if name == "stringify" => true,
                Ok(args) => args.iter().all(closed_pure_sugar),
                Err(_) => false,
            }
        }
        Expr::Unary(u) => closed_pure_sugar(&u.expr),
        Expr::Binary(b) => closed_pure_sugar(&b.left) && closed_pure_sugar(&b.right),
        Expr::Paren(p) => closed_pure_sugar(&p.expr),
        Expr::Group(g) => closed_pure_sugar(&g.expr),
        Expr::Reference(r) => closed_pure_sugar(&r.expr),
        Expr::Array(a) => a.elems.iter().all(closed_pure_sugar),
        Expr::Tuple(t) => t.elems.iter().all(closed_pure_sugar),
        Expr::Cast(c) => closed_pure_sugar(&c.expr),
        Expr::Index(i) => closed_pure_sugar(&i.expr) && closed_pure_sugar(&i.index),
        // everything else (Field, If, Block, Closure, Await, bare local Call, ...) is
        // not certified -> the assertion stays unclassified (safe under-claim).
        _ => false,
    }
}

/// True if any operand subtree performs a stdlib SUGAR operation (a method call or a
/// `format!`/`concat!` macro) -- the operations the symbolic lifter cannot model and
/// therefore leaves unclassified. Requiring this avoids double-counting: a dissolvable
/// candidate is exactly an assert the lifter could not discharge on its own.
fn operands_use_stdlib_op(operands: &[&Expr]) -> bool {
    struct W {
        found: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for W {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            self.found = true;
            syn::visit::visit_expr_method_call(self, m);
        }
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            if let Some(seg) = m.path.segments.last() {
                let n = seg.ident.to_string();
                if matches!(n.as_str(), "format" | "concat") {
                    self.found = true;
                }
            }
            syn::visit::visit_macro(self, m);
        }
    }
    let mut w = W { found: false };
    for e in operands {
        syn::visit::Visit::visit_expr(&mut w, e);
    }
    w.found
}

/// A pure local helper that may be CARRIED into the harness prelude: a thin wrapper
/// whose body is itself stdlib sugar (test plumbing like
/// `fn lower(c: char) -> String { ...; c.to_lowercase().collect() }`), NOT a user
/// algorithm. Its parameters are allowed as leaves (they are bound to closed literals
/// at the call site); every expression in its body must otherwise be stdlib sugar.
/// Single level only: a body that calls another local helper does NOT qualify (skip =
/// safe under-claim). This stays inside fence #1: we are not verifying the helper, we
/// are dissolving the stdlib sugar it wraps -- the helper carries no logic of its own.
/// Recursively decide whether the local helper `name` is CARRYABLE -- plumbing whose
/// body is pure stdlib sugar, where every non-ctor call it makes is to ANOTHER carryable
/// helper (multi-level, with a cycle guard). On success, `name` and all its transitive
/// helper callees are recorded into `deps` (the set to carry into the harness prelude).
/// A helper that is ambiguous (defined more than once), impure, or calls a non-carryable
/// fn disqualifies (-> not carried -> safe under-claim). Bare idents/local lets are fine
/// (a genuinely-free var just fails the harness compile = safe).
fn helper_carryable(
    name: &str,
    fns: &std::collections::BTreeMap<String, Vec<syn::ItemFn>>,
    deps: &mut std::collections::BTreeSet<String>,
    seen: &mut std::collections::BTreeSet<String>,
) -> bool {
    if deps.contains(name) {
        return true; // already validated + recorded
    }
    if !seen.insert(name.to_string()) {
        return false; // cycle -> reject (safe)
    }
    let f = match fns.get(name) {
        Some(d) if d.len() == 1 => &d[0],
        _ => return false, // missing or ambiguous
    };
    // Gather every method name (for the impure check) and every non-ctor call callee.
    struct Collect {
        methods: Vec<String>,
        calls: Vec<String>,
        bad: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for Collect {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            self.methods.push(m.method.to_string());
            syn::visit::visit_expr_method_call(self, m);
        }
        fn visit_expr_call(&mut self, c: &'ast syn::ExprCall) {
            match c.func.as_ref() {
                Expr::Path(p) if is_const_or_ctor_path(&p.path) => {}
                Expr::Path(p) => match p.path.get_ident() {
                    Some(id) => self.calls.push(id.to_string()),
                    None => self.bad = true, // path call we can't resolve (e.g. T::f)
                },
                _ => self.bad = true,
            }
            syn::visit::visit_expr_call(self, c);
        }
    }
    let mut c = Collect {
        methods: Vec::new(),
        calls: Vec::new(),
        bad: false,
    };
    syn::visit::Visit::visit_block(&mut c, &f.block);
    if c.bad || c.methods.iter().any(|m| IMPURE_NAMES.contains(&m.as_str())) {
        return false;
    }
    // every non-ctor callee must itself be carryable (transitively).
    for callee in &c.calls {
        if !helper_carryable(callee, fns, deps, seen) {
            return false;
        }
    }
    deps.insert(name.to_string());
    true
}

/// Walk a file for unit-test assertions that are CLOSED STDLIB VALUE SUGAR (gate) and
/// perform at least one stdlib sugar op the symbolic lifter cannot model. Returns a
/// shared `prelude` (the unique, unambiguous, carryable local helpers any dissolvable
/// assert calls) plus the reconstructed, message-stripped assert statements. Message
/// args are dropped so a message referencing a runtime local cannot break the compile.
pub struct Dissolvable {
    /// Crate-level prelude: the carryable local helper defs the unit's asserts call.
    pub prelude: String,
    /// `main`-level setup: the enclosing fn's `let` bindings the asserts reference
    /// (closed context). A non-closed setup line just fails the unit's compile (safe).
    pub setup: String,
    pub asserts: Vec<String>,
}

pub fn collect_dissolvable(file: &syn::File) -> Vec<Dissolvable> {
    use std::collections::{BTreeMap, BTreeSet};
    // name -> defs (a name defined more than once is ambiguous; never carried).
    let mut fns: BTreeMap<String, Vec<syn::ItemFn>> = BTreeMap::new();
    // every fn in the file, in source order (top-level + nested + in mods); each
    // becomes its own dissolvable unit (its locals in scope, asserts attributed to it).
    let mut all_fns: Vec<syn::ItemFn> = Vec::new();
    struct FnWalk<'a> {
        map: &'a mut BTreeMap<String, Vec<syn::ItemFn>>,
        all: &'a mut Vec<syn::ItemFn>,
    }
    impl<'a, 'ast> syn::visit::Visit<'ast> for FnWalk<'a> {
        fn visit_item_fn(&mut self, f: &'ast syn::ItemFn) {
            self.map.entry(f.sig.ident.to_string()).or_default().push(f.clone());
            self.all.push(f.clone());
            syn::visit::visit_item_fn(self, f);
        }
    }
    syn::visit::Visit::visit_file(
        &mut FnWalk {
            map: &mut fns,
            all: &mut all_fns,
        },
        file,
    );

    let mut units = Vec::new();
    for f in &all_fns {
        // setup = this fn's top-level `let` statements (verbatim); locals = their names.
        let mut setup = String::new();
        let mut locals: BTreeSet<String> = BTreeSet::new();
        for st in &f.block.stmts {
            if let syn::Stmt::Local(local) = st {
                collect_pat_idents(&local.pat, &mut locals);
                setup.push_str(&quote::quote!(#local).to_string());
                setup.push('\n');
            }
        }
        let (asserts, helpers) = collect_block_asserts(&f.block.stmts, &fns, &locals);
        if asserts.is_empty() {
            continue;
        }
        let mut prelude = String::new();
        for name in &helpers {
            if let Some(defs) = fns.get(name) {
                if defs.len() == 1 {
                    prelude.push_str(&quote::quote!(#(#defs)*).to_string());
                    prelude.push('\n');
                }
            }
        }
        units.push(Dissolvable {
            prelude,
            setup,
            asserts,
        });
    }
    units
}

/// Collect the binding idents of a `let` pattern (handles ident, tuple, ref, etc.).
fn collect_pat_idents(pat: &syn::Pat, out: &mut std::collections::BTreeSet<String>) {
    match pat {
        syn::Pat::Ident(i) => {
            out.insert(i.ident.to_string());
            if let Some((_, sub)) = &i.subpat {
                collect_pat_idents(sub, out);
            }
        }
        syn::Pat::Tuple(t) => t.elems.iter().for_each(|e| collect_pat_idents(e, out)),
        syn::Pat::TupleStruct(t) => t.elems.iter().for_each(|e| collect_pat_idents(e, out)),
        syn::Pat::Reference(r) => collect_pat_idents(&r.pat, out),
        syn::Pat::Type(t) => collect_pat_idents(&t.pat, out),
        syn::Pat::Paren(p) => collect_pat_idents(&p.pat, out),
        _ => {}
    }
}

/// Collect the dissolvable asserts in ONE block's statements (not descending into
/// nested fns), gated allowing `locals` (the enclosing fn's `let`-bound names, carried
/// as setup). Returns (assert statements, carryable-helper names referenced).
fn collect_block_asserts(
    stmts: &[syn::Stmt],
    fns: &std::collections::BTreeMap<String, Vec<syn::ItemFn>>,
    locals: &std::collections::BTreeSet<String>,
) -> (Vec<String>, std::collections::BTreeSet<String>) {
    use syn::parse::Parser;
    use syn::punctuated::Punctuated;
    let mut asserts = Vec::new();
    let mut helpers = std::collections::BTreeSet::new();

    // Does `expr` qualify as closed stdlib sugar, allowing (a) calls to UNIQUE carryable
    // local helpers (recorded into `helpers`) and (b) references to `locals` -- the
    // enclosing fn's `let`-bound names, carried into the harness setup (closed context)?
    fn check(
        expr: &Expr,
        fns: &std::collections::BTreeMap<String, Vec<syn::ItemFn>>,
        locals: &std::collections::BTreeSet<String>,
        helpers: &mut std::collections::BTreeSet<String>,
    ) -> bool {
        if let Expr::Call(c) = expr {
            if let Expr::Path(p) = c.func.as_ref() {
                if let Some(id) = p.path.get_ident() {
                    let name = id.to_string();
                    // lowercase call: only OK if it resolves to a carryable local helper
                    // (multi-level: helper_carryable records it + its transitive helper
                    // callees into `helpers` for the prelude).
                    if !is_const_or_ctor_path(&p.path) {
                        let mut seen = std::collections::BTreeSet::new();
                        if helper_carryable(&name, fns, helpers, &mut seen) {
                            return c.args.iter().all(|a| check(a, fns, locals, helpers));
                        }
                        return false;
                    }
                }
            }
        }
        match expr {
            // a reference to a carried local `let` binding is a closed leaf (its value
            // is supplied by the setup block).
            Expr::Path(p) => {
                p.path.get_ident().map(|i| locals.contains(&i.to_string())).unwrap_or(false)
                    || is_const_or_ctor_path(&p.path)
            }
            Expr::Call(c) => {
                let ctor =
                    matches!(c.func.as_ref(), Expr::Path(p) if is_const_or_ctor_path(&p.path));
                ctor && c.args.iter().all(|a| check(a, fns, locals, helpers))
            }
            Expr::MethodCall(m) => {
                !IMPURE_NAMES.contains(&m.method.to_string().as_str())
                    && check(&m.receiver, fns, locals, helpers)
                    && m.args.iter().all(|a| check(a, fns, locals, helpers))
            }
            Expr::Paren(p) => check(&p.expr, fns, locals, helpers),
            Expr::Group(g) => check(&g.expr, fns, locals, helpers),
            Expr::Reference(r) => check(&r.expr, fns, locals, helpers),
            Expr::Unary(u) => check(&u.expr, fns, locals, helpers),
            Expr::Binary(b) => {
                check(&b.left, fns, locals, helpers) && check(&b.right, fns, locals, helpers)
            }
            Expr::Array(a) => a.elems.iter().all(|e| check(e, fns, locals, helpers)),
            Expr::Tuple(t) => t.elems.iter().all(|e| check(e, fns, locals, helpers)),
            Expr::Cast(c) => check(&c.expr, fns, locals, helpers),
            Expr::Index(i) => {
                check(&i.expr, fns, locals, helpers) && check(&i.index, fns, locals, helpers)
            }
            // leaves / macros handled by the plain gate.
            _ => closed_pure_sugar(expr),
        }
    }

    // Rebuild an assert macro with the loop variable token-substituted (loopvar ->
    // value) throughout its token stream, descending into groups. Token-level is
    // simple and fully backstopped: a wrong substitution can only yield a non-green
    // harness -> not dissolved (safe); it can never false-discharge.
    fn subst_macro(m: &syn::Macro, var: &str, value: &Expr) -> Option<syn::Macro> {
        fn replace(
            ts: proc_macro2::TokenStream,
            var: &str,
            val: &proc_macro2::TokenStream,
        ) -> proc_macro2::TokenStream {
            ts.into_iter()
                .flat_map(|tt| -> proc_macro2::TokenStream {
                    match tt {
                        proc_macro2::TokenTree::Ident(id) if id.to_string() == var => val.clone(),
                        proc_macro2::TokenTree::Group(g) => {
                            let inner = replace(g.stream(), var, val);
                            std::iter::once(proc_macro2::TokenTree::Group(
                                proc_macro2::Group::new(g.delimiter(), inner),
                            ))
                            .collect()
                        }
                        other => std::iter::once(other).collect(),
                    }
                })
                .collect()
        }
        let val_tokens = quote::quote!(#value);
        let mut m2 = m.clone();
        m2.tokens = replace(m.tokens.clone(), var, &val_tokens);
        Some(m2)
    }

    // The finite, concrete domain of a `for v in <domain>` loop, as the list of
    // iteration values (each an `Expr`). `None` if the domain is not a finite literal
    // construction (a runtime collection, a non-literal bound, or too large).
    fn for_loop_domain(f: &syn::ExprForLoop) -> Option<Vec<Expr>> {
        const CAP: i64 = 512;
        match &*f.expr {
            Expr::Range(r) => {
                let parse_int = |e: &Expr| -> Option<i64> {
                    match e {
                        Expr::Lit(syn::ExprLit { lit: syn::Lit::Int(i), .. }) => {
                            i.base10_parse::<i64>().ok()
                        }
                        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => match u.expr.as_ref() {
                            Expr::Lit(syn::ExprLit { lit: syn::Lit::Int(i), .. }) => {
                                i.base10_parse::<i64>().ok().map(|n| -n)
                            }
                            _ => None,
                        },
                        _ => None,
                    }
                };
                let start = parse_int(r.start.as_deref()?)?;
                let end = parse_int(r.end.as_deref()?)?;
                let end = if matches!(r.limits, syn::RangeLimits::Closed(_)) { end + 1 } else { end };
                if end < start || end - start > CAP {
                    return None;
                }
                Some(
                    (start..end)
                        .map(|n| syn::parse_str::<Expr>(&n.to_string()).unwrap())
                        .collect(),
                )
            }
            Expr::Array(a) if !a.elems.is_empty() && a.elems.len() as i64 <= CAP => {
                Some(a.elems.iter().cloned().collect())
            }
            _ => None,
        }
    }

    struct W<'a> {
        fns: &'a std::collections::BTreeMap<String, Vec<syn::ItemFn>>,
        locals: &'a std::collections::BTreeSet<String>,
        asserts: &'a mut Vec<String>,
        helpers: &'a mut std::collections::BTreeSet<String>,
    }
    impl<'a> W<'a> {
        // Try one assert macro (already loop-substituted if applicable) as a dissolvable
        // candidate; push it if it gates.
        fn try_assert(&mut self, m: &syn::Macro) {
            W::try_assert_static(m, self.fns, self.locals, self.asserts, self.helpers);
        }
        fn try_assert_static(
            m: &syn::Macro,
            fns: &std::collections::BTreeMap<String, Vec<syn::ItemFn>>,
            locals: &std::collections::BTreeSet<String>,
            asserts: &mut Vec<String>,
            helpers: &mut std::collections::BTreeSet<String>,
        ) {
            let name = m
                .path
                .segments
                .last()
                .map(|s| s.ident.to_string())
                .unwrap_or_default();
            let macro_name = match name.as_str() {
                "assert_eq" | "debug_assert_eq" => Some("assert_eq"),
                "assert_ne" | "debug_assert_ne" => Some("assert_ne"),
                "assert" | "debug_assert" => Some("assert"),
                _ => None,
            };
            if let Some(macro_name) = macro_name {
                let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
                if let Ok(args) = parser.parse2(m.tokens.clone()) {
                    let ops: Vec<&Expr> = args.iter().collect();
                    let value_ops: Vec<&Expr> = if macro_name == "assert" {
                        ops.iter().take(1).copied().collect()
                    } else {
                        ops.iter().take(2).copied().collect()
                    };
                    let enough = value_ops.len() == if macro_name == "assert" { 1 } else { 2 };
                    let mut scratch = std::collections::BTreeSet::new();
                    let all_sugar =
                        enough && value_ops.iter().all(|e| check(e, fns, locals, &mut scratch));
                    let gated =
                        all_sugar && (operands_use_stdlib_op(&value_ops) || !scratch.is_empty());
                    if gated {
                        helpers.extend(scratch);
                        let stmt = if macro_name == "assert" {
                            format!("assert!({})", quote::quote!(#(#value_ops)*))
                        } else {
                            let l = value_ops[0];
                            let r = value_ops[1];
                            format!("{}!({}, {})", macro_name, quote::quote!(#l), quote::quote!(#r))
                        };
                        asserts.push(stmt);
                    }
                }
            }
        }
    }
    impl<'a, 'ast> syn::visit::Visit<'ast> for W<'a> {
        fn visit_expr_for_loop(&mut self, f: &'ast syn::ExprForLoop) {
            // UNROLL a finite literal-domain loop into point assertions: each body
            // assert with the loop variable replaced by each concrete iteration value.
            // This turns a bounded UNIVERSE into points, each then dissolvable. A
            // runtime/non-literal domain falls through to the normal walk (whose
            // free-variable asserts the gate rejects -> stays unclassified, safe).
            if let (syn::Pat::Ident(pi), Some(values)) =
                (f.pat.as_ref(), for_loop_domain(f))
            {
                if pi.subpat.is_none() {
                    let var = pi.ident.to_string();
                    // collect the body's assert macros once.
                    struct Collect {
                        macros: Vec<syn::Macro>,
                    }
                    impl<'b> syn::visit::Visit<'b> for Collect {
                        fn visit_macro(&mut self, m: &'b syn::Macro) {
                            self.macros.push(m.clone());
                            syn::visit::visit_macro(self, m);
                        }
                    }
                    let mut c = Collect { macros: Vec::new() };
                    for st in &f.body.stmts {
                        syn::visit::Visit::visit_stmt(&mut c, st);
                    }
                    for value in &values {
                        for m in &c.macros {
                            // substitute loopvar -> value in the macro's tokens by
                            // re-parsing operands, substituting, and rebuilding a macro.
                            if let Some(subbed) = subst_macro(m, &var, value) {
                                self.try_assert(&subbed);
                            }
                        }
                    }
                    return; // do NOT recurse into the body (avoid free-var versions).
                }
            }
            syn::visit::visit_expr_for_loop(self, f);
        }
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            self.try_assert(m);
            syn::visit::visit_macro(self, m);
        }
        // Do NOT descend into a nested fn item: it is collected as its own unit (with
        // its own `let` context). This keeps each assert attributed to exactly the fn
        // whose locals are in scope for it.
        fn visit_item_fn(&mut self, _f: &'ast syn::ItemFn) {}
    }
    let mut w = W {
        fns,
        locals,
        asserts: &mut asserts,
        helpers: &mut helpers,
    };
    for st in stmts {
        syn::visit::Visit::visit_stmt(&mut w, st);
    }
    (asserts, helpers)
}

/// Walk a file for unit-test assertions that are CLOSED STDLIB VALUE SUGAR (gate) and
/// perform at least one stdlib sugar op the symbolic lifter cannot model. Returns each
/// as a reconstructed, message-stripped assert statement (`assert_eq!(LHS, RHS)` /
/// `assert!(COND)`) ready to drop into a harness. Message args are dropped so a message
/// referencing a runtime local cannot break the harness compile.
pub fn collect_dissolvable_asserts(file: &syn::File) -> Vec<String> {
    use syn::parse::Parser;
    use syn::punctuated::Punctuated;
    struct W {
        out: Vec<String>,
    }
    impl<'ast> syn::visit::Visit<'ast> for W {
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            let name = m
                .path
                .segments
                .last()
                .map(|s| s.ident.to_string())
                .unwrap_or_default();
            let kind = match name.as_str() {
                "assert_eq" | "debug_assert_eq" => Some("assert_eq"),
                "assert_ne" | "debug_assert_ne" => Some("assert_ne"),
                "assert" | "debug_assert" => Some("assert"),
                _ => None,
            };
            if let Some(macro_name) = kind {
                let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
                if let Ok(args) = parser.parse2(m.tokens.clone()) {
                    let ops: Vec<&Expr> = args.iter().collect();
                    let value_ops: Vec<&Expr> = if macro_name == "assert" {
                        ops.iter().take(1).copied().collect()
                    } else {
                        ops.iter().take(2).copied().collect()
                    };
                    let enough = if macro_name == "assert" {
                        value_ops.len() == 1
                    } else {
                        value_ops.len() == 2
                    };
                    if enough
                        && assert_operands_are_stdlib_sugar(&value_ops)
                        && operands_use_stdlib_op(&value_ops)
                    {
                        let stmt = if macro_name == "assert" {
                            format!("assert!({})", quote::quote!(#(#value_ops)*))
                        } else {
                            let l = value_ops[0];
                            let r = value_ops[1];
                            format!("{}!({}, {})", macro_name, quote::quote!(#l), quote::quote!(#r))
                        };
                        self.out.push(stmt);
                    }
                }
            }
            syn::visit::visit_macro(self, m);
        }
    }
    let mut w = W { out: Vec::new() };
    syn::visit::Visit::visit_file(&mut w, file);
    w.out
}

/// Outcome of a harness compile+run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HarnessResult {
    /// The harness compiled and ran; per-assert (by index) whether it held.
    Ran(Vec<bool>),
    /// The harness did not compile -- nothing is dissolved (safe: the asserts stay
    /// unclassified). Carries rustc's stderr (truncated) for diagnostics.
    CompileError(String),
    /// The two determinism runs disagreed -- the term was not deterministic after all,
    /// so NONE of its asserts may be dissolved (every index forced to `false`).
    Nondeterministic,
    /// rustc / the binary could not be invoked (toolchain absent). Caller treats this
    /// like CompileError: dissolve nothing.
    Unavailable(String),
}

/// Compile a harness of `prelude` (imports + pure local helper defs) plus a `main`
/// that runs each statement in `asserts`, printing `OK <i>` iff statement `i` does NOT
/// panic (caught per-assert via `catch_unwind`). Runs TWICE under `rustc` and requires
/// identical results (determinism sanity). `rustc` is the toolchain invocation (e.g.
/// `"rustc"`, or a `rustup run <toolchain> rustc` split handled by the caller via
/// `rustc_args`). `work_dir` must exist and be writable.
pub fn evaluate_asserts(
    prelude: &str,
    setup: &str,
    asserts: &[String],
    rustc: &str,
    rustc_args: &[String],
    edition: &str,
    work_dir: &Path,
) -> HarnessResult {
    if asserts.is_empty() {
        return HarnessResult::Ran(Vec::new());
    }
    let src = build_harness_source(prelude, setup, asserts);
    let src_path = work_dir.join("sugar_closed_eval_probe.rs");
    let bin_path = work_dir.join("sugar_closed_eval_probe_bin");
    if let Err(e) = std::fs::File::create(&src_path).and_then(|mut f| f.write_all(src.as_bytes())) {
        return HarnessResult::Unavailable(format!("write harness: {e}"));
    }

    // Compile.
    let mut cmd = Command::new(rustc);
    cmd.args(rustc_args)
        .arg("--edition")
        .arg(edition)
        .arg("-A")
        .arg("warnings")
        .arg(&src_path)
        .arg("-o")
        .arg(&bin_path);
    let compile = match cmd.output() {
        Ok(o) => o,
        Err(e) => return HarnessResult::Unavailable(format!("invoke rustc: {e}")),
    };
    if !compile.status.success() {
        let mut err = String::from_utf8_lossy(&compile.stderr).to_string();
        err.truncate(2000);
        return HarnessResult::CompileError(err);
    }

    // Run twice for determinism.
    let run1 = match run_and_collect(&bin_path, asserts.len()) {
        Ok(v) => v,
        Err(e) => return HarnessResult::Unavailable(e),
    };
    let run2 = match run_and_collect(&bin_path, asserts.len()) {
        Ok(v) => v,
        Err(e) => return HarnessResult::Unavailable(e),
    };
    if run1 != run2 {
        return HarnessResult::Nondeterministic;
    }
    HarnessResult::Ran(run1)
}

/// Build the harness: prelude, then a `main` that runs each assert under a silenced
/// panic hook and prints `OK <i>` for each that does not panic.
fn build_harness_source(prelude: &str, setup: &str, asserts: &[String]) -> String {
    let mut s = String::new();
    s.push_str(prelude);
    s.push_str("\n#[allow(unused)]\nfn main() {\n");
    // Silence panic output so a deliberately-failing assert does not spam stderr.
    s.push_str("    std::panic::set_hook(Box::new(|_| {}));\n");
    // SETUP: the carried enclosing-fn `let` bindings (closed context the asserts
    // reference, e.g. `let expected = [..];`). A non-closed setup line just fails the
    // compile -> the whole unit dissolves nothing (safe).
    if !setup.trim().is_empty() {
        s.push_str(setup);
        s.push('\n');
    }
    for (i, a) in asserts.iter().enumerate() {
        // Each assert is wrapped so a panic is caught and only the survivors print OK.
        let stmt = a.trim().trim_end_matches(';');
        s.push_str(&format!(
            "    if std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {{ {stmt}; }})).is_ok() {{ println!(\"OK {i}\"); }}\n"
        ));
    }
    s.push_str("}\n");
    s
}

fn run_and_collect(bin: &Path, n: usize) -> Result<Vec<bool>, String> {
    let out = Command::new(bin)
        .output()
        .map_err(|e| format!("run harness: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    let mut held = vec![false; n];
    for line in stdout.lines() {
        if let Some(rest) = line.strip_prefix("OK ") {
            if let Ok(i) = rest.trim().parse::<usize>() {
                if i < n {
                    held[i] = true;
                }
            }
        }
    }
    Ok(held)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rustc_available() -> bool {
        Command::new("rustc")
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }

    fn gate(src: &str) -> bool {
        let e: Expr = syn::parse_str(src).expect("parse");
        assert_operands_are_stdlib_sugar(&[&e])
    }

    #[test]
    fn gate_accepts_closed_stdlib_value_sugar() {
        // direct stdlib method sugar on literals
        assert!(gate("'0'.to_digit(10)"));
        assert!(gate("'A'.to_digit(16)"));
        assert!(gate(r#""url()URL()".to_ascii_uppercase()"#));
        assert!(gate("'A'.to_lowercase().collect::<String>()"));
        // value ctors / variants as RHS expecteds
        assert!(gate("Some(10)"));
        assert!(gate("None"));
        // consts
        assert!(gate("f64::MAX"));
        assert!(gate("u32::BITS"));
        // format! sugar over literals
        assert!(gate(r#"format!("{}", 3.14_f64)"#));
        // literals, refs, byte
        assert!(gate("b'0'"));
        assert!(gate(r#""HİKß""#));
        // arithmetic over literals
        assert!(gate("1.0 / 0.0"));
    }

    #[test]
    fn gate_rejects_non_sugar_the_fences() {
        // FENCE #3 generalization: a free variable (param/local) is not closed.
        assert!(!gate("c"));
        assert!(!gate("c.to_lowercase().collect::<String>()"));
        // FENCE #1 user/local function call (lowercase callee) -> model it, don't run it.
        assert!(!gate("lower('A')"));
        assert!(!gate("my_helper(3, 4)"));
        // impure ops (pointer / time / IO / atomic), even on literals.
        assert!(!gate("'a'.encode_utf8(&mut buf).as_ptr()")); // free `buf` AND as_ptr
        assert!(!gate("Instant::now()")); // ctor-ish path but `now` is impure-named... it's a method-free call
        // field access / arbitrary expr -> not certified.
        assert!(!gate("x.field"));
        assert!(!gate("{ let y = 3; y }"));
    }

    #[test]
    fn collect_carries_a_pure_local_helper() {
        let file: syn::File = syn::parse_str(
            "fn lower(c: char) -> String { c.to_lowercase().collect() }\n\
             #[test] fn t() { assert_eq!(lower('A'), \"a\"); }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        assert!(d.iter().any(|u| u.prelude.contains("fn lower")), "helper carried");
        assert_eq!(d.iter().map(|u| u.asserts.len()).sum::<usize>(), 1, "the helper-wrapped assert is dissolvable");
    }

    #[test]
    fn collect_unrolls_finite_range_loop_into_points() {
        // for i in 0..3 { assert_eq!(i.to_string(), format!("{}", i)); }
        // unrolls to 3 point asserts (i -> 0,1,2), each closed stdlib sugar.
        let file: syn::File = syn::parse_str(
            "#[test] fn t() { for i in 0..3 { assert_eq!(i.to_string(), format!(\"{}\", i)); } }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        let total: usize = d.iter().map(|u| u.asserts.len()).sum();
        assert_eq!(total, 3, "0..3 unrolls to 3 points");
        assert!(
            d.iter().flat_map(|u| &u.asserts).any(|a| a.contains("0 .") || a.contains("0.") || a.contains("0i32")),
            "loop var substituted with concrete values"
        );
    }

    #[test]
    fn collect_carries_local_let_for_loop() {
        // for i in 0..3 over a LOCAL literal array: unroll to 3 points, each referencing
        // `expected[0..2]` -- carried via setup so the harness closes.
        let file: syn::File = syn::parse_str(
            "#[test] fn t() { let expected = [0u32, 1u32, 2u32]; \
             for i in 0..3 { assert_eq!((i as u32).to_string(), expected[i].to_string()); } }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        let total: usize = d.iter().map(|u| u.asserts.len()).sum();
        assert_eq!(total, 3, "0..3 over local array unrolls to 3 carried points");
        assert!(
            d.iter().any(|u| u.setup.contains("let expected")),
            "the local `let expected` array is carried into setup"
        );
    }

    #[test]
    fn collect_does_not_unroll_runtime_domain_loop() {
        // for x in v { ... }: runtime collection, NOT a finite literal domain -> not
        // unrolled; the free-var body assert is rejected by the gate (stays unclassified).
        let file: syn::File = syn::parse_str(
            "#[test] fn t() { let v = make(); for x in v { assert_eq!(x.to_string(), \"1\"); } }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        assert!(d.iter().all(|u| u.asserts.is_empty()), "runtime-domain loop must not unroll");
    }

    #[test]
    fn collect_carries_multilevel_pure_helper() {
        // outer calls inner (both pure stdlib plumbing) -> the WHOLE chain is carried.
        let file: syn::File = syn::parse_str(
            "fn inner(c: char) -> char { c }\n\
             fn outer(c: char) -> String { inner(c).to_lowercase().collect() }\n\
             #[test] fn t() { assert_eq!(outer('A'), \"a\"); }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        assert_eq!(d.iter().map(|u| u.asserts.len()).sum::<usize>(), 1, "multilevel pure helper dissolvable");
        assert!(d.iter().any(|u| u.prelude.contains("fn outer") && u.prelude.contains("fn inner")),
            "both helpers in the chain are carried");
    }

    #[test]
    fn collect_skips_helper_calling_unresolvable_fn() {
        // outer calls a fn we cannot see (external/user logic) -> not carryable -> skipped.
        let file: syn::File = syn::parse_str(
            "fn outer(c: char) -> String { mystery(c).to_lowercase().collect() }\n\
             #[test] fn t() { assert_eq!(outer('A'), \"a\"); }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        assert!(d.iter().all(|u| u.asserts.is_empty()), "helper with unresolvable callee must be skipped (safe)");
    }

    #[test]
    fn harness_dissolves_true_and_refutes_false() {
        // Skip when the toolchain is absent (CI hosts without rustc) -- never fail
        // for an environment reason.
        if !rustc_available() {
            eprintln!("rustc unavailable; skipping harness driver test");
            return;
        }
        let dir = std::env::temp_dir().join("sugar_closed_eval_test");
        let _ = std::fs::create_dir_all(&dir);
        let asserts = vec![
            // closed stdlib sugar: true
            r#"assert_eq!('A'.to_lowercase().collect::<String>(), "a")"#.to_string(),
            // closed stdlib sugar: false (break-the-twin -- must NOT be reported held)
            r#"assert_eq!('A'.to_lowercase().collect::<String>(), "z")"#.to_string(),
            // another true
            r#"assert_eq!(format!("{}", 3.14_f64), "3.14")"#.to_string(),
        ];
        let res = evaluate_asserts("", "", &asserts, "rustc", &[], "2021", &dir);
        match res {
            HarnessResult::Ran(held) => {
                assert_eq!(held, vec![true, false, true], "true/false/true expected");
            }
            other => panic!("expected Ran, got {other:?}"),
        }
    }

    #[test]
    fn harness_carries_a_pure_local_helper() {
        if !rustc_available() {
            eprintln!("rustc unavailable; skipping harness helper test");
            return;
        }
        let dir = std::env::temp_dir().join("sugar_closed_eval_test_helper");
        let _ = std::fs::create_dir_all(&dir);
        let prelude = r#"
fn lower(c: char) -> String {
    let to_lowercase = c.to_lowercase();
    assert_eq!(to_lowercase.len(), to_lowercase.count());
    c.to_lowercase().collect()
}
"#;
        let asserts = vec![
            r#"assert_eq!(lower('A'), "a")"#.to_string(),
            r#"assert_eq!(lower('Σ'), "σ")"#.to_string(),
        ];
        match evaluate_asserts(prelude, "", &asserts, "rustc", &[], "2021", &dir) {
            HarnessResult::Ran(held) => assert_eq!(held, vec![true, true]),
            other => panic!("expected Ran, got {other:?}"),
        }
    }
}
