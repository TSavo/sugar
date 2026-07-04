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
    "as_ptr",
    "as_mut_ptr",
    "addr",
    "expose_addr",
    "expose_provenance",
    "with_addr",
    "from_raw",
    "into_raw",
    "transmute",
    "transmute_copy",
    "assume_init",
    "now",
    "elapsed",
    "duration_since",
    "instant",
    "read",
    "write",
    "read_to_string",
    "stdin",
    "stdout",
    "stderr",
    "lock",
    "random",
    "gen",
    "gen_range",
    "fill",
    "next_u32",
    "next_u64",
    "spawn",
    "join",
    "load",
    "store",
    "fetch_add",
    "fetch_sub",
    "fetch_or",
    "compare_exchange",
    "swap",
    "send",
    "recv",
    "try_recv",
    "var",
    "vars",
    "args",
    "open",
    "metadata",
    "create",
    "remove_file",
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
        && s.chars()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_');
    first_upper || screaming
}

/// A call to a TYPE-ASSOCIATED stdlib function: a path `A::..::func` of >=2 segments
/// whose FIRST segment is a type/enum (starts uppercase) and whose LAST segment is the
/// associated-fn name (e.g. `FormattingOptions::new`, `NonZero::new`, `Ordering::from`).
/// This is stdlib VALUE sugar -- a pure constructor / converter on a stdlib type -- as
/// long as the fn name is not in the impure set. A USER type's associated fn matches the
/// SHAPE, but the harness carries no user type defs, so `MyType::compute()` fails to
/// COMPILE => not dissolved (the harness compile is the backstop, same fence as a
/// lowercase user-fn call). The first segment must be a type-ish name, NOT a lowercase
/// local/module path, so this never admits `mymod::helper()`.
fn is_type_assoc_call_path(p: &syn::Path) -> bool {
    if p.segments.len() < 2 {
        return false;
    }
    let first = p
        .segments
        .first()
        .map(|s| s.ident.to_string())
        .unwrap_or_default();
    let first_type = first
        .chars()
        .next()
        .map(|c| c.is_uppercase())
        .unwrap_or(false);
    let last = p
        .segments
        .last()
        .map(|s| s.ident.to_string())
        .unwrap_or_default();
    first_type && !IMPURE_NAMES.contains(&last.as_str())
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
        // Also a TYPE-associated stdlib fn (`FormattingOptions::new()`, `NonZero::new(..)`):
        // pure value sugar; a user type matches the shape but fails the harness compile.
        Expr::Call(c) => {
            let ctor = matches!(c.func.as_ref(),
                Expr::Path(p) if is_const_or_ctor_path(&p.path) || is_type_assoc_call_path(&p.path));
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
            let name = mac.mac.path.path_last_ident().unwrap_or_default();
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

/// Value-position-aware token substitution: replace every `Ident == var` in `ts` with
/// `val`, EXCEPT when the ident is in name position -- immediately after `.` (a method
/// or field name) or after `::` (a path segment). This stops a loop variable named like
/// a method (`sign`) from rewriting `.sign(..)` into `.None(..)`. Descends into groups.
/// A struct-field name (`Foo { sign: x }`) is rarer in these loops; if it ever mis-subs
/// the result simply fails to parse/compile -> not dissolved (safe under-claim).
fn replace_value_ident(
    ts: proc_macro2::TokenStream,
    var: &str,
    val: &proc_macro2::TokenStream,
) -> proc_macro2::TokenStream {
    use proc_macro2::{Punct, TokenTree};
    let mut out = proc_macro2::TokenStream::new();
    // prev_dot: previous token was a `.`; prev_colon: previous token was a `:` (so a
    // second `:` makes `::`, and an ident right after `::` is a path segment name).
    let mut prev_dot = false;
    let mut prev_colon = false;
    for tt in ts {
        match tt {
            TokenTree::Ident(id) if id.to_string() == var && !prev_dot && !prev_colon => {
                out.extend(val.clone());
                prev_dot = false;
                prev_colon = false;
            }
            TokenTree::Group(g) => {
                let inner = replace_value_ident(g.stream(), var, val);
                out.extend(std::iter::once(TokenTree::Group(proc_macro2::Group::new(
                    g.delimiter(),
                    inner,
                ))));
                prev_dot = false;
                prev_colon = false;
            }
            TokenTree::Punct(ref p) if p.as_char() == '.' => {
                prev_dot = true;
                prev_colon = false;
                out.extend(std::iter::once(TokenTree::Punct(Punct::new(
                    '.',
                    p.spacing(),
                ))));
            }
            TokenTree::Punct(ref p) if p.as_char() == ':' => {
                // A `:` (often part of `::`); mark so the NEXT ident is treated as a path
                // segment name and not substituted.
                prev_colon = true;
                prev_dot = false;
                out.extend(std::iter::once(TokenTree::Punct(Punct::new(
                    ':',
                    p.spacing(),
                ))));
            }
            other => {
                // any other token resets both name-position flags.
                prev_dot = false;
                prev_colon = false;
                out.extend(std::iter::once(other));
            }
        }
    }
    out
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
    /// EXACT-PARTITION tag: this unit's asserts are collected from inside a `while` body,
    /// so the lifter classifies their sites as TERMINAL ("under while context" -- the only
    /// terminal context that holds dissolvable greens). A green here is credited to the
    /// REFUSED (terminal) bucket, not unclassified. Every other unit (top-level asserts,
    /// macro-carry, helper-inlining) is `false` => its greens credit unclassified. This is
    /// what makes the sweep partition exact (credit each green to its real disposition)
    /// rather than a draw-order guess that could fake-zero unclassified.
    pub under_while: bool,
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
            self.map
                .entry(f.sig.ident.to_string())
                .or_default()
                .push(f.clone());
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
        // `let_inits` records each top-level binding's initializer EXPR so a for-loop
        // range bound like `0..v.len()` can be resolved when `v` is a literal-array /
        // slice local of known length (the iterator.rs `for i in 0..v.len()` shape).
        let mut setup = String::new();
        let mut locals: BTreeSet<String> = BTreeSet::new();
        let mut let_inits: std::collections::BTreeMap<String, Expr> =
            std::collections::BTreeMap::new();
        // Carry the fn body's own `use` items (e.g. `use core::fmt::*;`) into the harness
        // `main` so unqualified stdlib paths the asserts reference (`FormattingOptions`,
        // `Sign::Plus`) resolve. A `use` is plumbing, not logic: a wrong/unresolvable use
        // just fails the harness compile => not dissolved (safe under-claim). Emitted
        // BEFORE the `let` setup so the lets may reference the imported names; visible in
        // every nested point block.
        for st in &f.block.stmts {
            if let syn::Stmt::Item(syn::Item::Use(u)) = st {
                setup.push_str(&quote::quote!(#u).to_string());
                setup.push('\n');
            }
        }
        for st in &f.block.stmts {
            if let syn::Stmt::Local(local) = st {
                collect_pat_idents(&local.pat, &mut locals);
                setup.push_str(&quote::quote!(#local).to_string());
                setup.push('\n');
                if let Some(name) = pat_binding_ident(&local.pat) {
                    if let Some(init) = &local.init {
                        if init.diverge.is_none() {
                            let_inits.insert(name, (*init.expr).clone());
                        }
                    }
                }
            }
        }
        // Local `macro_rules!` defs in this fn (carried verbatim into the harness prelude
        // when an invocation with all-closed args is dissolved -- MACRO-CARRY). The
        // vendor's own assertion macro (e.g. `assert_chunks!`) is pure sugar; carrying its
        // def + a closed invocation lets the expansion's stdlib ops be dissolved by
        // evaluation. An unreachable API (e.g. a core-internal import) just fails the
        // harness compile => not dissolved (safe under-claim).
        let mut local_macros: BTreeMap<String, String> = BTreeMap::new();
        for st in &f.block.stmts {
            if let syn::Stmt::Item(syn::Item::Macro(im)) = st {
                if im.mac.path.is_ident("macro_rules") {
                    if let Some(id) = &im.ident {
                        local_macros.insert(id.to_string(), quote::quote!(#im).to_string());
                    }
                }
            }
        }
        let (asserts, helpers, macro_asserts, while_asserts) =
            collect_block_asserts(&f.block.stmts, &fns, &locals, &local_macros, &let_inits);
        // helper-defs prelude, shared by the regular unit and each macro unit.
        let mut helper_prelude = String::new();
        for name in &helpers {
            if let Some(defs) = fns.get(name) {
                if defs.len() == 1 {
                    helper_prelude.push_str(&quote::quote!(#(#defs)*).to_string());
                    helper_prelude.push('\n');
                }
            }
        }
        if !asserts.is_empty() {
            units.push(Dissolvable {
                prelude: helper_prelude.clone(),
                setup: setup.clone(),
                asserts,
                under_while: false,
            });
        }
        // WHILE-body asserts: their own unit, tagged terminal. A green here credits the
        // REFUSED bucket (exact partition), so a while-body closed equality the lifter
        // refused as "under while context" is recovered to discharged -- and a non-green
        // top-level unclassified assert is never drawn down by it (no fake-zero).
        if !while_asserts.is_empty() {
            units.push(Dissolvable {
                prelude: helper_prelude.clone(),
                setup: setup.clone(),
                asserts: while_asserts,
                under_while: true,
            });
        }
        // MACRO-CARRY: each local macro's closed invocations form their OWN unit, with the
        // macro def carried into that unit's prelude (def must precede use). Isolated, so a
        // macro whose expansion needs an unreachable API fails ONLY its own unit and never
        // poisons the fn's regular-assert dissolution.
        for (mname, invs) in macro_asserts {
            if invs.is_empty() {
                continue;
            }
            if let Some(def) = local_macros.get(&mname) {
                let mut prelude = String::new();
                prelude.push_str(def);
                prelude.push('\n');
                prelude.push_str(&helper_prelude);
                units.push(Dissolvable {
                    prelude,
                    setup: setup.clone(),
                    asserts: invs,
                    under_while: false,
                });
            }
        }

        // CALL-SITE ARG-INLINING (fence-bounded). The symbolic lifter counts a
        // non-`#[test]` helper's INTERNAL asserts once per helper as "reachable only via
        // call-site inlining" (free over its params). When this fn calls such a helper
        // with CLOSED literal args (`lower('A')`, `do_test(b'a', &[..])`) and the helper is
        // CARRYABLE (body bottoms out in stdlib sugar + literals, fence #1), we β-reduce:
        // substitute params := the call's closed actuals, then re-run the closed-sugar
        // collector on the substituted body so each INTERNAL assert becomes a CONCRETE
        // point (fence #3) carried into its own harness unit. A green run is the
        // dissolution of that helper's internal asserts at the pinned args; a wrong
        // substitution can only fail to compile/hold => not dissolved (safe under-claim).
        for u in collect_helper_call_inlinings(&f.block.stmts, &fns) {
            units.push(u);
        }
    }
    units
}

/// β-reduce CLOSED-arg calls to CARRYABLE local helpers found anywhere in `stmts`
/// (bare statement calls AND calls in assert/let positions) into dissolvable units: one
/// per distinct (helper, closed-arg-tuple) call site. For each, substitute the helper's
/// params with the call's closed actual tokens, then collect the substituted body's
/// stdlib-sugar asserts (now concrete) plus its `let` context as setup. Skips a helper
/// whose params are not all plain idents, or any call whose args are not all closed
/// stdlib sugar, or any non-unique / non-carryable helper (all = safe under-claim).
fn collect_helper_call_inlinings(
    stmts: &[syn::Stmt],
    fns: &std::collections::BTreeMap<String, Vec<syn::ItemFn>>,
) -> Vec<Dissolvable> {
    use std::collections::BTreeSet;
    // Collect every call expression to a unique-name local fn in this fn's statements.
    struct CallW<'a> {
        calls: Vec<(String, Vec<Expr>)>,
        fns: &'a std::collections::BTreeMap<String, Vec<syn::ItemFn>>,
    }
    impl<'a, 'ast> syn::visit::Visit<'ast> for CallW<'a> {
        fn visit_expr_call(&mut self, c: &'ast syn::ExprCall) {
            if let Expr::Path(p) = c.func.as_ref() {
                if let Some(id) = p.path.get_ident() {
                    let name = id.to_string();
                    if !is_const_or_ctor_path(&p.path) && self.fns.contains_key(&name) {
                        self.calls.push((name, c.args.iter().cloned().collect()));
                    }
                }
            }
            syn::visit::visit_expr_call(self, c);
        }
        // syn::visit does NOT descend into macro token streams (they are opaque), so a
        // helper call inside `assert_eq!(lower('A'), "a")` would be missed. Parse the
        // operands of an assert-shaped macro and visit them for helper calls.
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            use syn::parse::Parser;
            use syn::punctuated::Punctuated;
            let name = m
                .path
                .segments
                .last()
                .map(|s| s.ident.to_string())
                .unwrap_or_default();
            if name.starts_with("assert") || name.starts_with("debug_assert") {
                let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
                if let Ok(args) = parser.parse2(m.tokens.clone()) {
                    for a in &args {
                        syn::visit::Visit::visit_expr(self, a);
                    }
                }
            }
            syn::visit::visit_macro(self, m);
        }
        // Do not descend into nested fn items: their own calls belong to their own unit.
        fn visit_item_fn(&mut self, _f: &'ast syn::ItemFn) {}
    }
    let mut w = CallW {
        calls: Vec::new(),
        fns,
    };
    for st in stmts {
        syn::visit::Visit::visit_stmt(&mut w, st);
    }

    let mut out = Vec::new();
    let mut seen_sites: BTreeSet<String> = BTreeSet::new();
    for (name, args) in &w.calls {
        // The helper must be unique + carryable (fence #1). helper_carryable records the
        // helper and its transitive carryable callees into `deps` (the prelude set).
        let mut deps = BTreeSet::new();
        let mut seen = BTreeSet::new();
        if !helper_carryable(name, fns, &mut deps, &mut seen) {
            continue;
        }
        let def = match fns.get(name) {
            Some(d) if d.len() == 1 => &d[0],
            _ => continue,
        };
        // Every actual must be CLOSED stdlib sugar (fence #1 + #3): a runtime arg
        // disqualifies the call (no construction to pin) -> safe under-claim.
        if !args.iter().all(closed_pure_sugar) {
            continue;
        }
        // Bind plain-ident params := closed actuals; bail on a non-ident pattern or an
        // arity mismatch (we cannot soundly substitute, so skip = safe).
        let params: Vec<String> = match def
            .sig
            .inputs
            .iter()
            .map(|inp| match inp {
                syn::FnArg::Typed(pt) => match pt.pat.as_ref() {
                    syn::Pat::Ident(pi) if pi.subpat.is_none() => Some(pi.ident.to_string()),
                    _ => None,
                },
                syn::FnArg::Receiver(_) => None,
            })
            .collect::<Option<Vec<_>>>()
        {
            Some(p) => p,
            None => continue,
        };
        if params.is_empty() || params.len() != args.len() {
            continue;
        }
        // De-dup identical call sites (same helper, same arg tokens): one point each.
        let site_key = format!(
            "{name}({})",
            args.iter()
                .map(|a| quote::quote!(#a).to_string())
                .collect::<Vec<_>>()
                .join(",")
        );
        if !seen_sites.insert(site_key) {
            continue;
        }
        // Substitute params := actuals throughout the body's token stream.
        let bindings: Vec<(String, proc_macro2::TokenStream)> = params
            .iter()
            .cloned()
            .zip(args.iter().map(|a| quote::quote!(#a)))
            .collect();
        let body_substituted = match substitute_block(&def.block, &bindings) {
            Some(b) => b,
            None => continue,
        };
        // Collect setup (the substituted body's top-level `let`s) + its concrete asserts.
        let mut setup = String::new();
        let mut locals: BTreeSet<String> = BTreeSet::new();
        let mut let_inits: std::collections::BTreeMap<String, Expr> =
            std::collections::BTreeMap::new();
        for st in &body_substituted.stmts {
            if let syn::Stmt::Local(local) = st {
                collect_pat_idents(&local.pat, &mut locals);
                setup.push_str(&quote::quote!(#local).to_string());
                setup.push('\n');
                if let Some(name) = pat_binding_ident(&local.pat) {
                    if let Some(init) = &local.init {
                        if init.diverge.is_none() {
                            let_inits.insert(name, (*init.expr).clone());
                        }
                    }
                }
            }
        }
        let (mut asserts, more_helpers, _macro_asserts, while_asserts) = collect_block_asserts(
            &body_substituted.stmts,
            fns,
            &locals,
            &std::collections::BTreeMap::new(),
            &let_inits,
        );
        // A helper's internal asserts are all "reachable only via call-site inlining"
        // (UNCLASSIFIED) regardless of an in-helper `while`, so fold the while split back
        // in -- their greens correctly credit unclassified (under_while: false below).
        asserts.extend(while_asserts);
        if asserts.is_empty() {
            continue;
        }
        // Prelude: the carryable helper's transitive callees plus any helper the
        // substituted body's asserts reference (e.g. a sibling carryable fn). The helper
        // itself is inlined (β-reduced), so it is removed from the prelude set.
        let mut prelude = String::new();
        let mut prelude_names: BTreeSet<String> = deps.clone();
        prelude_names.extend(more_helpers);
        prelude_names.remove(name);
        for hn in &prelude_names {
            if let Some(defs) = fns.get(hn) {
                if defs.len() == 1 {
                    prelude.push_str(&quote::quote!(#(#defs)*).to_string());
                    prelude.push('\n');
                }
            }
        }
        out.push(Dissolvable {
            prelude,
            setup,
            asserts,
            under_while: false,
        });
    }
    out
}

/// Token-level substitute `param := value` (for each binding) throughout a block,
/// re-parsing the result. Token-level is fully backstopped: a wrong substitution can
/// only yield a body that fails to parse/compile (=> the unit dissolves nothing, safe),
/// never a false-discharge. Returns `None` if the rewritten block does not re-parse.
fn substitute_block(
    block: &syn::Block,
    bindings: &[(String, proc_macro2::TokenStream)],
) -> Option<syn::Block> {
    fn replace_all(
        ts: proc_macro2::TokenStream,
        bindings: &[(String, proc_macro2::TokenStream)],
    ) -> proc_macro2::TokenStream {
        ts.into_iter()
            .flat_map(|tt| -> proc_macro2::TokenStream {
                match tt {
                    proc_macro2::TokenTree::Ident(id) => {
                        let s = id.to_string();
                        match bindings.iter().find(|(p, _)| *p == s) {
                            Some((_, val)) => val.clone(),
                            None => std::iter::once(proc_macro2::TokenTree::Ident(id)).collect(),
                        }
                    }
                    proc_macro2::TokenTree::Group(g) => {
                        let inner = replace_all(g.stream(), bindings);
                        std::iter::once(proc_macro2::TokenTree::Group(proc_macro2::Group::new(
                            g.delimiter(),
                            inner,
                        )))
                        .collect()
                    }
                    other => std::iter::once(other).collect(),
                }
            })
            .collect()
    }
    let body_tokens = {
        let stmts = &block.stmts;
        quote::quote!(#(#stmts)*)
    };
    let replaced = replace_all(body_tokens, bindings);
    // Re-wrap in braces and parse back to a Block.
    let wrapped = quote::quote!({ #replaced });
    syn::parse2::<syn::Block>(wrapped).ok()
}

/// Collect the binding idents of a `let` pattern (handles ident, tuple, ref, etc.).
/// The single bound identifier of a simple binding pattern, unwrapping a type
/// ascription (`let v: &[u32] = ..` -> `Pat::Type(Pat::Ident(v), ty)`) so a typed local
/// is still recognised as a named binding. `None` for tuple/struct/ref/wildcard patterns
/// (no single name to key a `let_inits` entry on).
fn pat_binding_ident(pat: &syn::Pat) -> Option<String> {
    match pat {
        syn::Pat::Ident(pi) if pi.subpat.is_none() => Some(pi.ident.to_string()),
        syn::Pat::Type(t) => pat_binding_ident(&t.pat),
        _ => None,
    }
}

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
    local_macros: &std::collections::BTreeMap<String, String>,
    let_inits: &std::collections::BTreeMap<String, Expr>,
) -> (
    Vec<String>,
    std::collections::BTreeSet<String>,
    std::collections::BTreeMap<String, Vec<String>>,
    Vec<String>,
) {
    use syn::parse::Parser;
    use syn::punctuated::Punctuated;
    let mut asserts = Vec::new();
    let mut helpers = std::collections::BTreeSet::new();
    // macro name -> its closed invocations (each becomes its OWN dissolvable unit).
    let mut macro_asserts: std::collections::BTreeMap<String, Vec<String>> =
        std::collections::BTreeMap::new();
    // Asserts collected from inside a `while` body (lifter disposition = terminal). Kept
    // SEPARATE so the sweep credits their greens to refused, not unclassified (exact
    // partition, no fake-zero).
    let mut while_asserts: Vec<String> = Vec::new();

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
                // A TYPE-associated stdlib fn call (`FormattingOptions::new()`,
                // `NonZero::new(..)`) is value sugar if its args are sugar. Backstopped by
                // the harness compile (a user type is not carried -> fails to compile).
                if is_type_assoc_call_path(&p.path) {
                    return c.args.iter().all(|a| check(a, fns, locals, helpers));
                }
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
                p.path
                    .get_ident()
                    .map(|i| locals.contains(&i.to_string()))
                    .unwrap_or(false)
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

    // Token-substitute `var -> value` throughout an arbitrary statement (used to
    // specialize a loop body to one concrete iteration value). Re-parses the rewritten
    // tokens as a `syn::Stmt`; `None` if the rewrite fails to parse (safe -- the point
    // is simply not built). Same backstop as `subst_macro`: a wrong substitution can
    // only yield a non-parse / non-compile, never a false-discharge.
    fn subst_stmt(stmt: &syn::Stmt, var: &str, value: &Expr) -> Option<syn::Stmt> {
        let val_tokens = quote::quote!(#value);
        let toks = quote::quote!(#stmt);
        let subbed = replace_value_ident(toks, var, &val_tokens);
        syn::parse2::<syn::Stmt>(subbed).ok()
    }

    // The finite, concrete domain of a `for v in <domain>` loop, as the list of
    // iteration values (each an `Expr`). `None` if the domain is not a finite literal
    // construction (a runtime collection, a non-literal bound, or too large).
    fn for_loop_domain(
        f: &syn::ExprForLoop,
        let_inits: &std::collections::BTreeMap<String, Expr>,
    ) -> Option<Vec<Expr>> {
        const CAP: i64 = 512;
        // The literal element count of `<ident>` when it is a top-level local bound to a
        // literal array `[..]` / array-repeat `[x; N]`, optionally behind `&`/`&[..]`
        // slice coercion. None for a runtime collection (opaque) -> the bound stays
        // unresolved -> the loop is left to the bin-2 refusal (safe).
        fn literal_len(
            ident: &str,
            let_inits: &std::collections::BTreeMap<String, Expr>,
        ) -> Option<i64> {
            fn array_len(e: &Expr) -> Option<i64> {
                match e {
                    Expr::Reference(r) => array_len(&r.expr),
                    Expr::Group(g) => array_len(&g.expr),
                    Expr::Paren(p) => array_len(&p.expr),
                    Expr::Array(a) => Some(a.elems.len() as i64),
                    Expr::Repeat(rep) => match rep.len.as_ref() {
                        Expr::Lit(syn::ExprLit {
                            lit: syn::Lit::Int(i),
                            ..
                        }) => i.base10_parse::<i64>().ok(),
                        _ => None,
                    },
                    _ => None,
                }
            }
            array_len(let_inits.get(ident)?)
        }
        match &*f.expr {
            Expr::Range(r) => {
                let parse_int = |e: &Expr| -> Option<i64> {
                    match e {
                        Expr::Lit(syn::ExprLit {
                            lit: syn::Lit::Int(i),
                            ..
                        }) => i.base10_parse::<i64>().ok(),
                        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
                            match u.expr.as_ref() {
                                Expr::Lit(syn::ExprLit {
                                    lit: syn::Lit::Int(i),
                                    ..
                                }) => i.base10_parse::<i64>().ok().map(|n| -n),
                                _ => None,
                            }
                        }
                        // `v.len()` on a literal-array / slice LOCAL of known length.
                        Expr::MethodCall(mc) if mc.method == "len" && mc.args.is_empty() => {
                            let recv = match mc.receiver.as_ref() {
                                Expr::Path(p) => p.path.get_ident().map(|i| i.to_string()),
                                _ => None,
                            }?;
                            literal_len(&recv, let_inits)
                        }
                        _ => None,
                    }
                };
                let start = parse_int(r.start.as_deref()?)?;
                let end = parse_int(r.end.as_deref()?)?;
                let end = if matches!(r.limits, syn::RangeLimits::Closed(_)) {
                    end + 1
                } else {
                    end
                };
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
        local_macros: &'a std::collections::BTreeMap<String, String>,
        macro_asserts: &'a mut std::collections::BTreeMap<String, Vec<String>>,
        let_inits: &'a std::collections::BTreeMap<String, Expr>,
        // Asserts collected while inside a `while` body (terminal disposition).
        while_asserts: &'a mut Vec<String>,
        // Depth of enclosing `while` bodies (>0 ⇒ the current assert is terminal).
        while_depth: usize,
    }
    impl<'a> W<'a> {
        // Try one assert macro (already loop-substituted if applicable) as a dissolvable
        // candidate; push it if it gates.
        fn try_assert(&mut self, m: &syn::Macro) {
            let target = if self.while_depth > 0 {
                &mut *self.while_asserts
            } else {
                &mut *self.asserts
            };
            W::try_assert_static(m, self.fns, self.locals, "", target, self.helpers);
        }
        fn try_assert_static(
            m: &syn::Macro,
            fns: &std::collections::BTreeMap<String, Vec<syn::ItemFn>>,
            locals: &std::collections::BTreeSet<String>,
            // Per-point SETUP prefix (loop-substituted body `let`s / builder stmts that
            // precede this assert in the unrolled iteration). Emitted INSIDE the assert
            // statement as a brace block `{ prefix; assert }` so the carried bindings are
            // in scope and the whole point stays one closed, self-contained unit. Empty
            // for a plain (non-loop) assert -- behaviour is then identical to before.
            prefix: &str,
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
                    let all_sugar = enough
                        && value_ops
                            .iter()
                            .all(|e| check(e, fns, locals, &mut scratch));
                    let gated =
                        all_sugar && (operands_use_stdlib_op(&value_ops) || !scratch.is_empty());
                    if gated {
                        helpers.extend(scratch);
                        let assert_stmt = if macro_name == "assert" {
                            format!("assert!({})", quote::quote!(#(#value_ops)*))
                        } else {
                            let l = value_ops[0];
                            let r = value_ops[1];
                            format!(
                                "{}!({}, {})",
                                macro_name,
                                quote::quote!(#l),
                                quote::quote!(#r)
                            )
                        };
                        // With a per-point prefix (unrolled-iteration `let`s / builder
                        // stmts), wrap the whole point in a brace block so the carried
                        // bindings are in scope: `{ prefix; assert }`. The brace block
                        // is itself the catch_unwind'd statement in the harness, so the
                        // point is closed + self-contained. A non-compiling prefix simply
                        // fails the compile -> not dissolved (safe under-claim).
                        let stmt = if prefix.trim().is_empty() {
                            assert_stmt
                        } else {
                            format!("{{ {prefix} {assert_stmt}; }}")
                        };
                        asserts.push(stmt);
                    }
                }
            }
        }

        // MACRO-CARRY: an invocation of a LOCAL `macro_rules!` (collected in
        // `local_macros`) whose every argument is closed stdlib sugar is dissolved by
        // carrying the macro def into the prelude and evaluating the verbatim invocation.
        // The macro body supplies the stdlib op (its metavars are filled by the closed
        // literal args). Soundness is the same harness compile+run boundary: a body that
        // needs an unreachable API (e.g. a core-internal import) or a non-closed arg
        // simply fails to compile => not dissolved (safe under-claim); the double-run
        // determinism check still guards the run.
        fn try_custom_macro(&mut self, m: &syn::Macro) {
            // Under a `while` body, do NOT collect a custom-macro invocation: leave it
            // refused (terminal) rather than route a whole macro unit into the terminal
            // bucket. Safe under-claim (not dissolved), never a fake-zero.
            if self.while_depth > 0 {
                return;
            }
            let name = m
                .path
                .segments
                .last()
                .map(|s| s.ident.to_string())
                .unwrap_or_default();
            if name == "macro_rules" || !self.local_macros.contains_key(&name) {
                return;
            }
            let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
            let args = match parser.parse2(m.tokens.clone()) {
                Ok(a) => a,
                Err(_) => return,
            };
            if args.is_empty() {
                return;
            }
            let mut scratch = std::collections::BTreeSet::new();
            if !args
                .iter()
                .all(|a| check(a, self.fns, self.locals, &mut scratch))
            {
                return;
            }
            self.helpers.extend(scratch);
            // Into a SEPARATE per-macro unit (not the fn's regular-assert unit) so a macro
            // whose def/expansion fails to compile can never poison the regular asserts.
            self.macro_asserts
                .entry(name.clone())
                .or_default()
                .push(format!("{}!({})", name, m.tokens));
        }
    }
    impl<'a> W<'a> {
        // Recursively UNROLL a finite literal-domain `for` loop into closed point
        // assertions. For each iteration value, the loop body is token-substituted
        // (loopvar -> value), then walked statement-by-statement:
        //   * a non-assert, non-loop statement (a body `let` or a builder/expr stmt)
        //     is GATED as closed stdlib sugar referencing the in-scope locals, then
        //     CARRIED into the per-point `prefix` (verbatim, substituted) -- its
        //     bindings are added to `scope` so a later assert may reference them.
        //   * a NESTED `for` over a literal domain recurses, carrying the accumulated
        //     prefix + scope (the fmt `for sign .. for alternate .. { let opts; assert }`
        //     shape).
        //   * an assert macro is emitted as `{ prefix; assert }` -- a self-contained
        //     closed point -- via the prefix-carrying `try_assert_static`.
        // A non-literal / runtime / opaque domain (`for x in v` with `v` not a known
        // literal local of known length) yields no domain -> nothing is unrolled; the
        // loop is left to the bin-2 refusal (safe). Backstop: every point is closed +
        // GATED, and the harness compile+run is the final fence -- a wrong substitution
        // or a non-sugar carried stmt can only fail to compile => not dissolved.
        fn unroll_loop(
            &mut self,
            f: &syn::ExprForLoop,
            prefix: &str,
            scope: &std::collections::BTreeSet<String>,
        ) {
            // Bound total emitted points per top-level loop site (nested literal domains
            // multiply); keep it finite and cheap. A loop that would exceed the cap is
            // left unrolled-only-partially is NOT acceptable (it would under/over claim
            // unpredictably), so we refuse the whole loop above the cap (safe).
            const POINT_CAP: usize = 4096;
            let var = match f.pat.as_ref() {
                syn::Pat::Ident(pi) if pi.subpat.is_none() => pi.ident.to_string(),
                _ => return,
            };
            let values = match for_loop_domain(f, self.let_inits) {
                Some(v) if !v.is_empty() && v.len() <= POINT_CAP => v,
                _ => return,
            };
            for value in &values {
                // Substitute loopvar -> value across the WHOLE body, then walk the
                // substituted statements building this iteration's prefix + scope.
                let mut iter_prefix = String::from(prefix);
                let mut iter_scope = scope.clone();
                // Pre-scan: gate fails on a non-sugar carried stmt -> drop the whole
                // iteration (do not emit a partial point).
                let mut ok = true;
                let mut pending: Vec<syn::Stmt> = Vec::new();
                for st in &f.body.stmts {
                    match subst_stmt(st, &var, value) {
                        Some(s) => pending.push(s),
                        None => {
                            ok = false;
                            break;
                        }
                    }
                }
                if !ok {
                    continue;
                }
                self.walk_unrolled_stmts(&pending, &mut iter_prefix, &mut iter_scope);
            }
        }

        // Walk the (already loop-substituted) statements of one unrolled iteration,
        // accumulating carried prefix + in-scope local names and emitting each closed
        // assert as a point. Nested literal loops recurse.
        fn walk_unrolled_stmts(
            &mut self,
            stmts: &[syn::Stmt],
            prefix: &mut String,
            scope: &mut std::collections::BTreeSet<String>,
        ) {
            for st in stmts {
                match st {
                    // A nested literal-domain loop: recurse with the prefix/scope so far.
                    syn::Stmt::Expr(Expr::ForLoop(inner), _) => {
                        let snap = scope.clone();
                        self.unroll_loop(inner, prefix, &snap);
                    }
                    // A body `let`: gate its initializer as closed sugar over in-scope
                    // locals, carry it verbatim, and bring its bindings into scope.
                    syn::Stmt::Local(local) => {
                        if let Some(init) = &local.init {
                            let mut scratch = std::collections::BTreeSet::new();
                            let ok = init.diverge.is_none()
                                && check(&init.expr, self.fns, scope, &mut scratch);
                            if ok {
                                self.helpers.extend(scratch);
                                collect_pat_idents(&local.pat, scope);
                                prefix.push_str(&quote::quote!(#local).to_string());
                                prefix.push(' ');
                            } else {
                                // a non-sugar / diverging initializer: stop carrying this
                                // iteration (a later assert that needs the binding cannot
                                // close -> safe under-claim).
                                return;
                            }
                        }
                    }
                    // An assert macro: emit `{ prefix; assert }` as one closed point.
                    syn::Stmt::Macro(sm) => {
                        let name = sm
                            .mac
                            .path
                            .segments
                            .last()
                            .map(|s| s.ident.to_string())
                            .unwrap_or_default();
                        if name.starts_with("assert") || name.starts_with("debug_assert") {
                            let target = if self.while_depth > 0 {
                                &mut *self.while_asserts
                            } else {
                                &mut *self.asserts
                            };
                            W::try_assert_static(
                                &sm.mac,
                                self.fns,
                                scope,
                                prefix,
                                target,
                                self.helpers,
                            );
                            self.try_custom_macro_prefixed(&sm.mac, scope, prefix);
                        }
                        // a non-assert statement macro (e.g. `println!`) is ignored.
                    }
                    syn::Stmt::Expr(Expr::Macro(em), _) => {
                        let name = em
                            .mac
                            .path
                            .segments
                            .last()
                            .map(|s| s.ident.to_string())
                            .unwrap_or_default();
                        if name.starts_with("assert") || name.starts_with("debug_assert") {
                            let target = if self.while_depth > 0 {
                                &mut *self.while_asserts
                            } else {
                                &mut *self.asserts
                            };
                            W::try_assert_static(
                                &em.mac,
                                self.fns,
                                scope,
                                prefix,
                                target,
                                self.helpers,
                            );
                            self.try_custom_macro_prefixed(&em.mac, scope, prefix);
                        }
                    }
                    // A bare expression statement (a builder mutation like
                    // `opts.sign(sign).alternate(alternate);`): gate it as a stdlib-sugar
                    // method chain over in-scope locals, then carry it verbatim so a
                    // following assert observes its effect.
                    syn::Stmt::Expr(e, _) => {
                        let mut scratch = std::collections::BTreeSet::new();
                        let okk = check(e, self.fns, scope, &mut scratch);
                        if okk {
                            self.helpers.extend(scratch);
                            prefix.push_str(&quote::quote!(#e).to_string());
                            prefix.push_str("; ");
                        } else {
                            // a non-sugar effecting statement we cannot certify: stop (a
                            // later assert may depend on it) -- safe under-claim.
                            return;
                        }
                    }
                    syn::Stmt::Item(_) => {}
                }
            }
        }

        // The prefixed analogue of `try_custom_macro` for an unrolled point: a local
        // `macro_rules!` invocation with closed args, emitted with the carried prefix.
        fn try_custom_macro_prefixed(
            &mut self,
            m: &syn::Macro,
            scope: &std::collections::BTreeSet<String>,
            prefix: &str,
        ) {
            // Under a `while` body, skip (leave refused) -- see try_custom_macro.
            if self.while_depth > 0 {
                return;
            }
            let name = m
                .path
                .segments
                .last()
                .map(|s| s.ident.to_string())
                .unwrap_or_default();
            if name == "macro_rules" || !self.local_macros.contains_key(&name) {
                return;
            }
            let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
            let args = match parser.parse2(m.tokens.clone()) {
                Ok(a) => a,
                Err(_) => return,
            };
            if args.is_empty() {
                return;
            }
            let mut scratch = std::collections::BTreeSet::new();
            if !args.iter().all(|a| check(a, self.fns, scope, &mut scratch)) {
                return;
            }
            self.helpers.extend(scratch);
            let inv = format!("{}!({})", name, m.tokens);
            let stmt = if prefix.trim().is_empty() {
                inv
            } else {
                format!("{{ {prefix} {inv}; }}")
            };
            self.macro_asserts.entry(name).or_default().push(stmt);
        }
    }
    impl<'a, 'ast> syn::visit::Visit<'ast> for W<'a> {
        fn visit_expr_for_loop(&mut self, f: &'ast syn::ExprForLoop) {
            // UNROLL a finite literal-domain loop into closed point assertions (carrying
            // the body's own `let`s / builder stmts per iteration, recursing into nested
            // literal loops). A runtime/non-literal domain produces no points.
            let is_literal_domain = matches!(
                f.pat.as_ref(),
                syn::Pat::Ident(pi) if pi.subpat.is_none()
            ) && for_loop_domain(f, self.let_inits).is_some();
            if is_literal_domain {
                // Fully handled by the unroll; do NOT descend (that would re-collect the
                // free-loop-variable body asserts, which would fail the gate anyway but
                // also miss the per-point carry).
                self.unroll_loop(f, "", self.locals);
                return;
            }
            // A runtime/non-literal domain: fall through to the normal walk so a closed
            // (loop-var-independent) assert or a NESTED literal loop inside is still
            // found. The free-variable body asserts the gate rejects stay unclassified.
            syn::visit::visit_expr_for_loop(self, f);
        }
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            self.try_assert(m);
            self.try_custom_macro(m);
            syn::visit::visit_macro(self, m);
        }
        // A `while` (incl. `while let`) body: its asserts run 0..n times under runtime
        // loop control, so the lifter classifies them TERMINAL ("under while context").
        // Bump the depth so asserts collected within route to `while_asserts` (credited to
        // the terminal bucket), keeping the dissolution partition exact.
        fn visit_expr_while(&mut self, w: &'ast syn::ExprWhile) {
            self.while_depth += 1;
            syn::visit::visit_expr_while(self, w);
            self.while_depth -= 1;
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
        local_macros,
        macro_asserts: &mut macro_asserts,
        let_inits,
        while_asserts: &mut while_asserts,
        while_depth: 0,
    };
    for st in stmts {
        syn::visit::Visit::visit_stmt(&mut w, st);
    }
    (asserts, helpers, macro_asserts, while_asserts)
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
                            format!(
                                "{}!({}, {})",
                                macro_name,
                                quote::quote!(#l),
                                quote::quote!(#r)
                            )
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
    // UNIQUE per-harness filenames (hash of the source). The dissolve dir is a single
    // REUSED temp dir and every unit used to compile to the SAME `..._probe_bin`; in a
    // sequential sweep, unit N runs that binary and unit N+1's `rustc -o` overwrites the
    // same path — if N's executable is not yet released the OS returns ETXTBSY ("text
    // file busy"), a spurious compile failure => under-claim. Unique names per (closed)
    // harness source remove that cross-unit overwrite race deterministically (and let
    // concurrent sweeps coexist). Identical source reuses the same name, which is fine.
    let tag = {
        use std::hash::{Hash, Hasher};
        let mut h = std::collections::hash_map::DefaultHasher::new();
        src.hash(&mut h);
        format!("{:016x}", h.finish())
    };
    let src_path = work_dir.join(format!("sugar_closed_eval_{tag}.rs"));
    let bin_path = work_dir.join(format!("sugar_closed_eval_{tag}_bin"));
    let n = asserts.len();

    let run = || -> HarnessResult {
        if let Err(e) =
            std::fs::File::create(&src_path).and_then(|mut f| f.write_all(src.as_bytes()))
        {
            return HarnessResult::Unavailable(format!("write harness: {e}"));
        }

        // Compile, with a small retry that absorbs transient/environmental failures
        // (rustup/rustc I/O contention, residual ETXTBSY, linker hiccups under sustained
        // load). SOUND: a genuine front-end error carries an `error[E####]` code and
        // reproduces identically, so it is returned immediately and NEVER retried (a
        // broken harness stays a CompileError => not dissolved). Only diagnostic-free /
        // non-front-end failures are retried. A successful compile of the EXACT harness
        // source is ground truth, and the double-run check below still guards the run, so
        // retry can only recover a true dissolvable — never manufacture a false-discharge.
        // Worst case a real failure is retried a few times then still fails (safe).
        const COMPILE_TRIES: usize = 3;
        let mut last_err = String::new();
        let mut last_was_invoke = false;
        let mut compiled = false;
        for attempt in 0..COMPILE_TRIES {
            let mut cmd = Command::new(rustc);
            cmd.args(rustc_args)
                .arg("--edition")
                .arg(edition)
                .arg("-A")
                .arg("warnings")
                .arg(&src_path)
                .arg("-o")
                .arg(&bin_path);
            match cmd.output() {
                Ok(o) if o.status.success() => {
                    compiled = true;
                    break;
                }
                Ok(o) => {
                    let mut err = String::from_utf8_lossy(&o.stderr).to_string();
                    err.truncate(2000);
                    if err.contains("error[E") {
                        return HarnessResult::CompileError(err);
                    }
                    last_err = err;
                    last_was_invoke = false;
                }
                Err(e) => {
                    last_err = format!("invoke rustc: {e}");
                    last_was_invoke = true;
                }
            }
            if attempt + 1 < COMPILE_TRIES {
                std::thread::sleep(std::time::Duration::from_millis(120));
            }
        }
        if !compiled {
            return if last_was_invoke {
                HarnessResult::Unavailable(last_err)
            } else {
                HarnessResult::CompileError(last_err)
            };
        }

        // Run twice for determinism.
        let run1 = match run_and_collect(&bin_path, n) {
            Ok(v) => v,
            Err(e) => return HarnessResult::Unavailable(e),
        };
        let run2 = match run_and_collect(&bin_path, n) {
            Ok(v) => v,
            Err(e) => return HarnessResult::Unavailable(e),
        };
        if run1 != run2 {
            return HarnessResult::Nondeterministic;
        }
        HarnessResult::Ran(run1)
    };

    let result = run();
    // Best-effort cleanup: names are unique per unit, so removing them cannot disturb any
    // other unit, and it keeps the reused dissolve dir bounded across a full sweep.
    let _ = std::fs::remove_file(&src_path);
    let _ = std::fs::remove_file(&bin_path);
    result
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
    fn while_body_green_tagged_terminal_top_level_stays_unclassified() {
        // EXACT-PARTITION discrimination (the whole point): a closed assert inside a
        // `while` body is collected into an `under_while` unit (terminal disposition);
        // a top-level closed assert into a non-`under_while` unit (unclassified). The sweep
        // then credits a while-body green to REFUSED and a top-level green to UNCLASSIFIED.
        // Because the two are NEVER conflated, a non-green unclassified sibling can never be
        // drawn down by a while-body green -- no fake-zero of unclassified.
        let file: syn::File = syn::parse_str(
            "#[test] fn t() {\n\
                assert_eq!('A'.to_lowercase().to_string(), \"a\");\n\
                while [1u8].iter().next().is_some() {\n\
                    assert_eq!('B'.to_lowercase().to_string(), \"b\");\n\
                    break;\n\
                }\n\
            }\n",
        )
        .unwrap();
        let units = collect_dissolvable(&file);
        let in_while = |n: &str| {
            units
                .iter()
                .any(|u| u.under_while && u.asserts.iter().any(|a| a.contains(n)))
        };
        let in_top = |n: &str| {
            units
                .iter()
                .any(|u| !u.under_while && u.asserts.iter().any(|a| a.contains(n)))
        };
        // the while-body 'B'->"b" assert: tagged terminal, and NOT in any unclassified unit.
        assert!(
            in_while("\"b\""),
            "while-body closed assert must be tagged terminal (under_while)"
        );
        assert!(
            !in_top("\"b\""),
            "while-body assert must NOT land in an unclassified unit"
        );
        // the top-level 'A'->"a" assert: unclassified, and NOT tagged terminal.
        assert!(
            in_top("\"a\""),
            "top-level closed assert must be unclassified (not under_while)"
        );
        assert!(
            !in_while("\"a\""),
            "top-level assert must NOT be tagged terminal"
        );
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
        assert!(
            d.iter().any(|u| u.prelude.contains("fn lower")),
            "helper carried"
        );
        assert_eq!(
            d.iter().map(|u| u.asserts.len()).sum::<usize>(),
            1,
            "the helper-wrapped assert is dissolvable"
        );
    }

    #[test]
    fn collect_carries_local_macro_with_closed_args() {
        // MACRO-CARRY: a LOCAL macro_rules! invoked with CLOSED literal/sugar args is
        // carried (def -> prelude) and the verbatim invocation becomes one dissolvable unit
        // (the assert_chunks!/assert_almost_eq! shape).
        let file: syn::File = syn::parse_str(
            "#[test] fn t() {\n             macro_rules! ae { ($a:expr, $b:expr) => {{ assert_eq!($a, $b); }}; }\n             ae!('A'.to_lowercase().to_string(), \"a\");\n             }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        assert!(
            d.iter()
                .any(|u| u.prelude.contains("macro_rules ! ae")
                    || u.prelude.contains("macro_rules! ae")),
            "macro def carried into prelude"
        );
        assert!(
            d.iter()
                .flat_map(|u| &u.asserts)
                .any(|a| a.starts_with("ae !") || a.starts_with("ae!")),
            "closed macro invocation collected as a dissolvable unit"
        );
    }

    #[test]
    fn collect_rejects_local_macro_with_free_arg() {
        // TWIN: the SAME macro invoked with a FREE variable arg (`c`, not a let-local, not
        // a literal) is NOT closed (fence #3) -> not collected. (Even if it slipped past,
        // the free var would fail the harness compile => not dissolved; this asserts the
        // gate refuses it up front.)
        let file: syn::File = syn::parse_str(
            "#[test] fn t() {\n             macro_rules! ae { ($a:expr, $b:expr) => {{ assert_eq!($a, $b); }}; }\n             ae!(c, \"a\");\n             }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        assert!(
            d.iter()
                .flat_map(|u| &u.asserts)
                .all(|a| !a.starts_with("ae !") && !a.starts_with("ae!")),
            "free-arg macro invocation is NOT dissolved"
        );
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
            d.iter()
                .flat_map(|u| &u.asserts)
                .any(|a| a.contains("0 .") || a.contains("0.") || a.contains("0i32")),
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
        assert_eq!(
            total, 3,
            "0..3 over local array unrolls to 3 carried points"
        );
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
        assert!(
            d.iter().all(|u| u.asserts.is_empty()),
            "runtime-domain loop must not unroll"
        );
    }

    #[test]
    fn collect_carries_body_let_in_unrolled_loop() {
        // BIN-1 BODY-LET CARRY: a `for i in 0..3` whose body defines its OWN `let` that a
        // following assert references. Each unrolled point must carry the (substituted)
        // body `let` so the point is closed: `{ let s = i.to_string(); assert!(...) }`.
        let file: syn::File = syn::parse_str(
            "#[test] fn t() { for i in 0..3 { let s = (i as u32).to_string(); \
             assert_eq!(s.len(), 1); } }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        let total: usize = d.iter().map(|u| u.asserts.len()).sum();
        assert_eq!(
            total, 3,
            "0..3 with a body `let` unrolls to 3 closed points"
        );
        assert!(
            d.iter()
                .flat_map(|u| &u.asserts)
                .all(|a| a.contains("let s =")),
            "each unrolled point carries the body `let` into a brace block: {:?}",
            d.iter().map(|u| &u.asserts).collect::<Vec<_>>()
        );
        // the loop var is concretely substituted (no free `i` remains).
        assert!(
            d.iter()
                .flat_map(|u| &u.asserts)
                .all(|a| !a.contains("(i as u32)")),
            "loop var i is substituted to a concrete value in every point"
        );
    }

    #[test]
    fn collect_resolves_len_bound_over_literal_local() {
        // `for i in 0..v.len()` where `v` is a LITERAL array LOCAL of known length:
        // the bound `v.len()` resolves to 3, so the loop unrolls to 3 points. The body
        // assert references the carried `v` and the substituted `i`.
        let file: syn::File = syn::parse_str(
            "#[test] fn t() { let v: &[u32] = &[10u32, 20u32, 30u32]; \
             for i in 0..v.len() { assert_eq!(v[i].to_string(), v[i].to_string()); } }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        let total: usize = d.iter().map(|u| u.asserts.len()).sum();
        assert_eq!(
            total, 3,
            "0..v.len() over a 3-element literal local unrolls to 3 points"
        );
    }

    #[test]
    fn collect_unrolls_nested_literal_loops_with_builder() {
        // The fmt `formatting_options_flags` shape (compressed): NESTED literal-array
        // loops, a body `let` + a builder MUTATION statement, then asserts that observe
        // the mutated builder. Each point carries the use, the let, and the (substituted)
        // builder stmt. The loop-var `sign`/`alternate` must NOT rewrite the method names
        // `.sign(..)`/`.alternate(..)` (value-position-aware substitution).
        let file: syn::File = syn::parse_str(
            "#[test] fn t() {\n             use core::fmt::*;\n             for sign in [None, Some(Sign::Plus)] {\n               for alternate in [true, false] {\n                 let mut o = FormattingOptions::new();\n                 o.sign(sign).alternate(alternate);\n                 assert_eq!(o.get_sign(), sign);\n                 assert_eq!(o.get_alternate(), alternate);\n               }\n             }\n           }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        let total: usize = d.iter().map(|u| u.asserts.len()).sum();
        // 2 (sign) * 2 (alternate) * 2 (asserts) = 8 closed points.
        assert_eq!(total, 8, "nested 2x2 literal loops x 2 asserts = 8 points");
        // value-position-aware: the method `.sign(` is preserved, never rewritten to a
        // value; the ARGUMENT `sign` is substituted to a concrete enum value.
        assert!(
            d.iter()
                .flat_map(|u| &u.asserts)
                .all(|a| a.contains(". sign (") || a.contains(".sign(")),
            "the method name `.sign(` is preserved (not corrupted by value subst): {:?}",
            d.iter().map(|u| &u.asserts).collect::<Vec<_>>()
        );
        assert!(
            d.iter()
                .flat_map(|u| &u.asserts)
                .all(|a| !a.contains("sign (sign)") && !a.contains("sign(sign)")),
            "the loop-var argument is substituted (no free `sign` remains in the builder)"
        );
        // the body `let` + builder mutation are carried into each point block.
        assert!(
            d.iter()
                .flat_map(|u| &u.asserts)
                .all(|a| a.contains("FormattingOptions :: new")
                    || a.contains("FormattingOptions::new")),
            "the body `let` constructor is carried into every point"
        );
    }

    #[test]
    fn collect_does_not_unroll_len_bound_over_runtime_local() {
        // DISCRIMINATION: `for i in 0..v.len()` where `v` is a RUNTIME value (not a
        // literal array of known length) -> the bound does NOT resolve -> no unroll ->
        // the free-var body assert is rejected by the gate (stays unclassified). This is
        // the bin-2 membrane: runtime data, not constructed from source literals.
        let file: syn::File = syn::parse_str(
            "#[test] fn t() { let v = make(); \
             for i in 0..v.len() { assert_eq!(v[i].to_string(), \"x\"); } }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        assert!(
            d.iter().all(|u| u.asserts.is_empty()),
            "a len()-bound over a RUNTIME local must NOT unroll (bin-2 stays refused): {:?}",
            d.iter().map(|u| &u.asserts).collect::<Vec<_>>()
        );
    }

    #[test]
    fn collect_does_not_unroll_nested_runtime_loop() {
        // DISCRIMINATION: a NESTED loop whose inner domain is a runtime collection does
        // not unroll the inner body (no finite construction). The outer literal loop
        // produces no closed points because the inner asserts are free over the runtime
        // element -> safe under-claim.
        let file: syn::File = syn::parse_str(
            "#[test] fn t() { let data = make(); \
             for k in [0u32, 1u32] { for x in data.iter() { assert_eq!(x.to_string(), k.to_string()); } } }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        assert!(
            d.iter().all(|u| u.asserts.is_empty()),
            "a nested runtime-domain loop must not unroll: {:?}",
            d.iter().map(|u| &u.asserts).collect::<Vec<_>>()
        );
    }

    #[test]
    fn value_aware_subst_preserves_method_and_path_names() {
        // The value-position-aware substitution must replace `sign` ONLY as a value, not
        // as a method name (`.sign(`) or a path segment. Direct check of the rewriter.
        let e: Expr = syn::parse_str("o.sign(sign).foo(Sign::sign)").unwrap();
        let toks: proc_macro2::TokenStream = quote::quote!(#e);
        let val: proc_macro2::TokenStream = quote::quote!(VALUE);
        let out = replace_value_ident(toks, "sign", &val).to_string();
        // method name `.sign(` preserved; the bare value `sign` arg replaced; the path
        // segment `Sign::sign` preserved.
        assert!(
            out.contains("sign (VALUE)") || out.contains("sign(VALUE)"),
            "value arg replaced: {out}"
        );
        assert!(
            !out.contains("VALUE (VALUE)"),
            "method name `.sign` NOT replaced: {out}"
        );
        assert!(
            out.contains("Sign :: sign") || out.contains("Sign::sign"),
            "path segment preserved: {out}"
        );
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
        assert_eq!(
            d.iter().map(|u| u.asserts.len()).sum::<usize>(),
            1,
            "multilevel pure helper dissolvable"
        );
        assert!(
            d.iter()
                .any(|u| u.prelude.contains("fn outer") && u.prelude.contains("fn inner")),
            "both helpers in the chain are carried"
        );
    }

    #[test]
    fn callsite_inlines_helper_internal_asserts_at_literal_args() {
        // A non-#[test] helper with INTERNAL asserts over its param `c`, called with a
        // char literal. β-reduce (c := 'A') so the internal assert becomes a CONCRETE
        // point dissolvable on its own (the bucket the symbolic lifter leaves as
        // "reachable only via call-site inlining").
        let file: syn::File = syn::parse_str(
            "#[test] fn t() {\n             fn lower(c: char) -> String {\n               let lo = c.to_lowercase();\n               assert_eq!(lo.clone().count(), c.to_lowercase().count());\n               c.to_lowercase().collect()\n             }\n             assert_eq!(lower(\'A\'), \"a\");\n             }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        // The helper's INTERNAL assert is carried as a concrete point (c := 'A'): a unit
        // whose asserts reference the substituted body (`'A'.to_lowercase()`), NOT a free `c`.
        let inlined = d.iter().any(|u| {
            u.asserts.iter().any(|a| a.contains("count"))
                && !u.asserts.iter().any(|a| a.contains("c ."))
        });
        assert!(
            inlined,
            "helper internal assert should inline at the literal arg: {:?}",
            d.iter().map(|u| &u.asserts).collect::<Vec<_>>()
        );
    }

    #[test]
    fn callsite_does_not_inline_helper_with_runtime_arg() {
        // DISCRIMINATION: the same helper called with a RUNTIME arg (`x`, a free local
        // not a literal) is NOT closed -> no construction to pin -> not inlined (safe).
        let file: syn::File = syn::parse_str(
            "#[test] fn t() {\n             fn lower(c: char) -> String {\n               assert_eq!(c.to_lowercase().count(), c.to_lowercase().count());\n               c.to_lowercase().collect()\n             }\n             let x = make();\n             let _ = lower(x);\n             }\n",
        )
        .unwrap();
        let d = collect_dissolvable(&file);
        // No unit carries the helper's internal `count` assert (its arg is runtime `x`).
        assert!(
            d.iter()
                .all(|u| !u.asserts.iter().any(|a| a.contains("count"))),
            "a runtime-arg call must not inline the helper body: {:?}",
            d.iter().map(|u| &u.asserts).collect::<Vec<_>>()
        );
    }

    #[test]
    fn callsite_does_not_inline_impure_or_unresolvable_helper() {
        // DISCRIMINATION #1: an IMPURE helper body (`now()`-class op) is not carryable.
        let impure: syn::File = syn::parse_str(
            "#[test] fn t() {\n             fn h(c: char) -> u32 {\n               assert_eq!(c.to_digit(10).unwrap(), Instant::now().elapsed().as_secs() as u32);\n               0\n             }\n             let _ = h(\'1\');\n             }\n",
        )
        .unwrap();
        let di = collect_dissolvable(&impure);
        assert!(
            di.iter().all(|u| u.asserts.is_empty()),
            "impure helper must not inline: {:?}",
            di.iter().map(|u| &u.asserts).collect::<Vec<_>>()
        );
        // DISCRIMINATION #2: a helper whose body calls an UNRESOLVABLE fn (user logic
        // we cannot see) is not carryable -> not inlined.
        let unres: syn::File = syn::parse_str(
            "#[test] fn t() {\n             fn h(c: char) -> u32 {\n               assert_eq!(mystery(c), 1u32);\n               0\n             }\n             let _ = h(\'1\');\n             }\n",
        )
        .unwrap();
        let du = collect_dissolvable(&unres);
        assert!(
            du.iter().all(|u| u.asserts.is_empty()),
            "unresolvable-callee helper must not inline: {:?}",
            du.iter().map(|u| &u.asserts).collect::<Vec<_>>()
        );
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
        assert!(
            d.iter().all(|u| u.asserts.is_empty()),
            "helper with unresolvable callee must be skipped (safe)"
        );
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
