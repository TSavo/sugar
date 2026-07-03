// SPDX-License-Identifier: MIT OR Apache-2.0
//
// lift.rs — build predicates from Rust source.
//
// Recognizes the patterns that paper 07 reads as "every if-statement is
// a contract": `if cond { panic!() }`, `assert!(cond)`, `debug_assert!(cond)`.
// Each such pattern contributes a leaf precondition the function's body
// is implicitly demanding from its caller.
//
// MVP scope:
//   - if-then-panic: `if cond { panic!(...) }` → ¬cond holds for the
//     non-panic continuation, so the function's effective precondition
//     accumulates ¬cond.
//   - assert! family: `assert!(cond)` → cond holds afterward (and the
//     caller must have established cond up to here).
//   - Binary comparisons `<`, `≤`, `>`, `≥`, `==`, `!=` lift to the
//     corresponding `AtomicPredicateName`.
//   - Compound `&&` lifts to `IrFormula::And`; `||` to `IrFormula::Or`;
//     `!cond` to `IrFormula::Not`.
//
// Out of scope (later commits on #368):
//   - if-then-else with non-panic else (introduces conditional
//     strengthening, not a flat precondition).
//   - match arms.
//   - early-return patterns beyond `panic!`.
//   - postcondition lifting from `return` expressions.

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::rc::Rc;

use libsugar::panic_freedom;
use proc_macro2::{Delimiter, TokenStream, TokenTree};
use sugar_floor_algebra::{
    guard_exit, Desugared, PredicateValue, PredicateValueFloorAccept,
    RequiredPredicateValueVisitor, SymbolicValue,
};
use sugar_ir_symbolic::Term as AlgebraTerm;
use sugar_ir_types::{IrFormula, IrTerm, LetBinding};
use syn::spanned::Spanned;
use syn::visit::{self, Visit};
use syn::{
    BinOp, Expr, ExprBinary, ExprIf, ExprMacro, ExprUnary, FnArg, GenericArgument, ItemFn, Lit,
    Local, Macro, Pat, PathArguments, ReturnType, Stmt, StmtMacro, Type, UnOp,
};
use tracing::debug;

use crate::term_boundary::{
    formula_to_legacy_guard_term, lower_ir, lower_ir_formula, raise_guarded_return_ir, raise_ir,
    raise_ir_formula,
};
use crate::wp::{free_vars_formula, free_vars_term, Wp};

// ---- LiftCtx: scope-tracked name resolution ----
//
// The shadow AST is the structural witness of the source. Per Sir's
// "shadow AST pays rent" directive (#368), the lifter consults a
// scope walker mirroring the shadow tree's structure when emitting IR
// variable references. Each closure binder receives a globally-unique
// id within the formula; references inside the closure body resolve
// to that unique id; references outside (free variables) keep their
// surface name. The result is that lifted IR is in barendregt form
// for closure binders by construction — capture is impossible at the
// lift layer for those binders. The capture-avoiding substitution in
// `wp.rs` is the belt-and-suspenders second line.
//
// The binder counter is per-formula. Two structurally identical
// inputs produce structurally identical IR (deterministic for content
// addressing).
#[derive(Clone)]
struct LiftCtx {
    next_binder_id: u32,
    /// Stack of frames; each frame holds (surface_name, unique_name) pairs
    /// in declaration order. Innermost frame shadows outer frames.
    scope: Vec<Vec<(String, String)>>,
    local_value_kinds: BTreeMap<String, ValueKind>,
    return_facts: FunctionReturnFacts,
    assertion_guard_facts: Vec<TrackedGuardFact>,
    len_eq_one_facts: Vec<LenEqOneFact>,
    mutable_roots: HashSet<String>,
    pure_free_guard_rules: Vec<PureFreeGuardRule>,
}

impl LiftCtx {
    fn new() -> Self {
        Self::with_return_facts(FunctionReturnFacts::default())
    }

    fn with_return_facts(return_facts: FunctionReturnFacts) -> Self {
        Self::with_return_facts_and_pure_free_guards(return_facts, Vec::new())
    }

    fn with_return_facts_and_pure_free_guards(
        return_facts: FunctionReturnFacts,
        pure_free_guard_rules: Vec<PureFreeGuardRule>,
    ) -> Self {
        Self {
            next_binder_id: 0,
            scope: Vec::new(),
            local_value_kinds: BTreeMap::new(),
            return_facts,
            assertion_guard_facts: Vec::new(),
            len_eq_one_facts: Vec::new(),
            mutable_roots: HashSet::new(),
            pure_free_guard_rules,
        }
    }

    fn push_frame(&mut self) {
        self.scope.push(Vec::new());
    }

    fn pop_frame(&mut self) {
        self.scope.pop();
    }

    /// Bind `base` in the innermost frame to a fresh unique name; return
    /// the unique name. Caller must have pushed at least one frame.
    fn bind(&mut self, base: &str) -> String {
        let id = self.next_binder_id;
        self.next_binder_id += 1;
        let unique = format!("{}#{}", base, id);
        self.scope
            .last_mut()
            .expect("LiftCtx::bind without push_frame")
            .push((base.to_string(), unique.clone()));
        unique
    }

    /// Resolve a surface name to its unique form. If not bound in any
    /// frame, the name is free in this formula and returned unchanged.
    fn resolve(&self, base: &str) -> String {
        for frame in self.scope.iter().rev() {
            for (b, u) in frame.iter().rev() {
                if b == base {
                    return u.clone();
                }
            }
        }
        base.to_string()
    }

    fn invalidate_root(&mut self, root: &str) {
        self.local_value_kinds.remove(root);
        self.assertion_guard_facts.retain(|fact| fact.root != root);
        self.len_eq_one_facts.retain(|fact| fact.root != root);
    }
}

#[derive(Clone, Debug, Default)]
pub struct FunctionReturnFacts {
    direct_string: HashSet<String>,
    result_string: HashSet<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PureFreeGuardRule {
    pub callee: String,
    pub post_predicate: String,
    pub source_line: Option<usize>,
    pub allow_line_less_match: bool,
}

#[derive(Clone, Debug)]
struct StatementPureFreeGuardFact {
    callee: String,
    args: Vec<Expr>,
    arg_roots: BTreeSet<String>,
    post_predicate: String,
}

#[derive(Clone, Debug, Default)]
struct StatementGuardFacts {
    pure_free: Vec<StatementPureFreeGuardFact>,
    resolved: Vec<StatementResolvedGuardFact>,
    keyset_snapshots: BTreeMap<String, KeysetMapSource>,
}

#[derive(Clone, Debug)]
struct StatementResolvedGuardFact {
    receiver_key: String,
    guard: IrFormula,
    roots: BTreeSet<String>,
}

#[derive(Clone, Debug)]
struct KeysetMapSource {
    map_root: String,
    map_term: IrTerm,
    roots: BTreeSet<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum ValueKind {
    String,
    Number,
    Bool,
    JsonObject(BTreeMap<String, ValueKind>),
    Unknown,
}

#[derive(Clone, Debug)]
struct TrackedGuardFact {
    root: String,
    receiver_key: String,
    guard_head: String,
    guard: IrFormula,
}

#[derive(Clone, Debug)]
struct LenEqOneFact {
    root: String,
    receiver_key: String,
}

/// Collect only EXPLICIT signature facts from a Rust file. This is a
/// refuse-floor data source for json! construction tracking: the kit trusts
/// `fn f(...) -> String` and `fn g(...) -> Result<String, _>` declarations,
/// but never infers return kinds from function bodies in this slice.
pub fn collect_explicit_function_return_facts(file: &syn::File) -> FunctionReturnFacts {
    let mut facts = FunctionReturnFacts::default();
    for item in &file.items {
        let syn::Item::Fn(item_fn) = item else {
            continue;
        };
        let name = item_fn.sig.ident.to_string();
        match explicit_return_kind(&item_fn.sig.output) {
            Some(ExplicitReturnKind::String) => {
                facts.direct_string.insert(name);
            }
            Some(ExplicitReturnKind::ResultString) => {
                facts.result_string.insert(name);
            }
            None => {}
        }
    }
    facts
}

#[derive(Copy, Clone, Debug, PartialEq, Eq)]
enum ExplicitReturnKind {
    String,
    ResultString,
}

fn explicit_return_kind(output: &ReturnType) -> Option<ExplicitReturnKind> {
    let ReturnType::Type(_, ty) = output else {
        return None;
    };
    if type_is_string(ty) {
        return Some(ExplicitReturnKind::String);
    }
    if type_is_result_string(ty) {
        return Some(ExplicitReturnKind::ResultString);
    }
    None
}

fn type_is_string(ty: &Type) -> bool {
    let Type::Path(type_path) = ty else {
        return false;
    };
    let Some(seg) = type_path.path.segments.last() else {
        return false;
    };
    seg.ident == "String"
}

fn type_is_result_string(ty: &Type) -> bool {
    let Type::Path(type_path) = ty else {
        return false;
    };
    let Some(seg) = type_path.path.segments.last() else {
        return false;
    };
    if seg.ident != "Result" {
        return false;
    }
    let PathArguments::AngleBracketed(args) = &seg.arguments else {
        return false;
    };
    let Some(GenericArgument::Type(first)) = args.args.first() else {
        return false;
    };
    type_is_string(first)
}

/// Lift the implicit precondition from a function body. Walks every
/// statement and conjoins the contribution of each pattern recognized.
///
/// Returns `Wp(true)` if no patterns are recognized — this means the
/// function makes no demands on its caller (a vacuous precondition).
pub fn lift_function_precondition(item_fn: &ItemFn) -> Wp {
    let mut ctx = LiftCtx::new();
    let mut accum: Vec<IrFormula> = Vec::new();
    for stmt in &item_fn.block.stmts {
        if let Some(predicate) = lift_stmt_contribution(stmt, &mut ctx) {
            accum.push(predicate);
        }
    }
    Wp(simplify_conjunction(accum))
}

/// Lift the implicit postcondition from a function body. Returns the
/// conjunction of predicates DERIVED from the body's structure that
/// hold at every reachable return point.
///
/// Derivation sources:
///   - if-then-panic: ¬cond holds for the non-panic continuation
///     (Sir's "every if is a free post; every else is the contraposition").
///   - assert!(c): c holds afterward.
///   - Trailing return expression: derives `result = <expr>` where
///     <expr> is lifted to an IrTerm and named-result equates with it.
///
/// This is real derivation: facts the substrate produces from the
/// body's structure that did not appear as explicit annotations. The
/// postcondition is the conjunction of every such derived fact.
pub fn lift_function_postcondition(item_fn: &ItemFn) -> Wp {
    lift_function_postcondition_with_return_facts(item_fn, &FunctionReturnFacts::default())
}

pub fn lift_function_postcondition_with_return_facts(
    item_fn: &ItemFn,
    return_facts: &FunctionReturnFacts,
) -> Wp {
    lift_function_postcondition_with_return_facts_and_pure_free_guards(item_fn, return_facts, &[])
}

pub fn lift_function_postcondition_with_return_facts_and_pure_free_guards(
    item_fn: &ItemFn,
    return_facts: &FunctionReturnFacts,
    pure_free_guard_rules: &[PureFreeGuardRule],
) -> Wp {
    let mut ctx = LiftCtx::with_return_facts_and_pure_free_guards(
        return_facts.clone(),
        pure_free_guard_rules.to_vec(),
    );

    // 1. Collect entry-assertion contributions, but track which names are
    //    subsequently shadowed by `let` bindings. An entry assertion
    //    `assert!(x >= 5)` that is followed LATER by `let x = 0` is UNSOUND to
    //    copy into the postcondition: after `let x = 0` the name `x` means
    //    something else. Drop any entry assertion whose free variables are
    //    shadowed by a `let` at a LATER position in the body.
    //
    //    Algorithm: walk statements in order, collecting (formula, position)
    //    pairs for assertions. Then for each assertion, collect names bound by
    //    `let` statements that come AFTER the assertion's index, and filter out
    //    assertions whose free variables overlap those later-bound names.
    let stmts = &item_fn.block.stmts;
    let mut entry_assertions: Vec<(IrFormula, usize)> = Vec::new();
    for (i, stmt) in stmts.iter().enumerate() {
        if let Some(predicate) = lift_stmt_contribution(stmt, &mut ctx) {
            entry_assertions.push((predicate, i));
        }
    }

    // Keep only assertions whose free variables are NOT shadowed by a LATER
    // `let` binding. A `let` that precedes the assertion is fine (it introduces
    // the name the assertion references); only later rebindings are unsound.
    let mut accum: Vec<IrFormula> = entry_assertions
        .into_iter()
        .filter(|(formula, assert_idx)| {
            let free = free_vars_formula(formula);
            // Collect names bound by `let` statements at positions AFTER this assertion.
            let mut later_bound: HashSet<String> = HashSet::new();
            for stmt in stmts.iter().skip(assert_idx + 1) {
                collect_let_bound_names(stmt, &mut later_bound);
            }
            // Keep this assertion only if none of its free vars are rebound later.
            free.is_disjoint(&later_bound)
        })
        .map(|(formula, _)| formula)
        .collect();

    seed_param_value_kinds(item_fn, &mut ctx);
    seed_mutable_param_roots(item_fn, &mut ctx);
    collect_assertion_guard_facts(stmts, &mut ctx);
    collect_local_value_facts(stmts, &mut ctx);
    accum.extend(collect_statement_guarded_panic_effects(stmts, &mut ctx));

    // 2. Trailing-expression derivation: if the function body ends with
    //    an expression statement (no trailing semicolon), that
    //    expression is the function's return value. Derive
    //    `result = <lifted expression>` and add to the postcondition.
    if let Some(Stmt::Expr(e, None)) = stmts.last() {
        if let Some(term) = lift_tail_expr_to_result_term(e, &mut ctx) {
            // A reformat that introduces a local (`let n = x; n*2`) leaves the
            // tail term referencing the local name (`n*2`), which would leak a
            // free variable `n` and move the behavior identity away from the
            // inline form (`x*2`). Re-attach the leading immutable `let`
            // bindings as a faithful `IrTerm::Let` over the result term: the
            // kit emits the data (the let with surface names), and the CLI
            // canonicalizer inlines the pure let at CID/discharge time, so the
            // two surface shapes share one behavior identity. (z3 also lowers
            // `(let ...)` natively, so the stored faithful form discharges.)
            let term = wrap_leading_lets(&stmts[..stmts.len() - 1], term, &mut ctx);
            let result_var = IrTerm::Var {
                name: "result".to_string(),
            };
            accum.push(IrFormula::Atomic {
                name: "=".to_string(),
                args: vec![result_var, term],
            });
        }
    }

    // 3. Explicit `return expr;` tails. If the body has an explicit
    //    `return <expr>;` statement, derive `result = <lifted expr>`. The
    //    leading `let`s that dominate the return (the statements before it) are
    //    re-attached too, so `let n = x; return n*2;` does not leak `n` any more
    //    than the trailing-expression form does.
    for (i, stmt) in stmts.iter().enumerate() {
        if let Some(formula) = lift_return_stmt_postcondition(&stmts[..i], stmt, &mut ctx) {
            accum.push(formula);
        }
    }

    Wp(simplify_conjunction(accum))
}

/// A ctor head the lifter emits for an opaque / effectful operation, whose value
/// is NOT a referentially-transparent function of its arguments: a method call
/// (`it.next()` advances an iterator), a channel/mutex conduit, an opaque macro,
/// the `?` short-circuit. Inlining a `let` whose initializer contains one of
/// these would DUPLICATE the effect (`let n = it.next(); n + n` is one advance
/// doubled, not two advances), so such bindings must never be wrapped/inlined.
fn is_impure_ctor_head(name: &str) -> bool {
    name.starts_with("method:")
        || name.starts_with("channel:")
        || name.starts_with("mutex:")
        || name.starts_with("macro:")
        || name.starts_with("call:")
        || name == "?"
}

/// Is `t` a pure value term -- safe to inline (duplicate) because its value is a
/// referentially-transparent function of its free variables? Vars and consts are
/// pure; a ctor is pure iff its head is not opaque/effectful and all its args are
/// pure. Lambdas and nested lets are conservatively treated as not-inlinable.
fn is_pure_value_term(t: &IrTerm) -> bool {
    match t {
        IrTerm::Var { .. } | IrTerm::Const { .. } => true,
        IrTerm::Ctor { name, args } => {
            !is_impure_ctor_head(name) && args.iter().all(is_pure_value_term)
        }
        IrTerm::Lambda { .. } | IrTerm::Let { .. } => false,
    }
}

/// Re-attach the function's leading immutable `let` bindings to the derived
/// result `body` term as a faithful [`IrTerm::Let`], so a reformat that
/// introduces a local emits the same behavior identity as the inline form.
///
/// ARCHITECTURE: the kit emits DATA, the CLI computes over it. We do NOT
/// pre-resolve or inline here -- we emit the `let` with the source's surface
/// names and let the CLI canonicalizer (`canonicalize_formula`) inline the pure
/// let at CID/discharge time. z3 lowers `(let ...)` natively, so the stored
/// faithful form still discharges reflexively against the body's own.
///
/// Only immutable bindings whose initializer lifts to a pure term are captured,
/// in source order. Bindings the result never references (transitively) are
/// dropped, so a function whose tail does not touch a leading local is
/// byte-unchanged.
///
/// SOUNDNESS bounds (correctness over coverage):
///   * SHADOWING IS REFUSED. If any name is bound more than once across the
///     prefix `let`s, we bail and leave the term untouched. A later rebinding
///     (`let mut n = ..`, an unliftable `let n = io()`, or even a pure
///     `let n = n+1`) means the tail's `n` no longer denotes the first
///     binding; wrapping anyway would assert a FALSE behavior identity. Bailing
///     keeps the leaked free var (the pre-fix behavior) -- honest, never wrong.
///   * NESTED, not parallel. We emit one single-binding `Let` per captured
///     binding, nested in source order: `let a in (let b in body)`. SMT-LIB
///     `let` is PARALLEL (binding RHSs see the OUTER scope), so a single
///     multi-binding `(let ((a x)(b (+ a 1))) ..)` would leave `b`'s `a` free.
///     Nesting gives the sequential semantics the canonicalizer and
///     `free_vars_term` already assume.
fn wrap_leading_lets(prefix: &[Stmt], body: IrTerm, ctx: &mut LiftCtx) -> IrTerm {
    // `prefix` is the run of statements before the result-producing position (a
    // trailing tail expression, or an explicit `return`); the lets it holds
    // dominate that result.
    // Refuse on ANY shadowing: collect every name bound by a prefix `let`
    // (regardless of mutability/liftability) and bail if one repeats.
    let mut seen: HashSet<String> = HashSet::new();
    for stmt in prefix {
        if let Stmt::Local(local) = stmt {
            let mut names = HashSet::new();
            collect_pat_names(&local.pat, &mut names);
            for name in names {
                if !seen.insert(name) {
                    return body; // a name is rebound later -> not a pure let chain
                }
            }
        }
    }
    // Names are now distinct. Collect (name, value-term) for immutable, liftable
    // lets in source order; a later binding may reference an earlier one.
    let mut bindings: Vec<LetBinding> = Vec::new();
    for stmt in prefix {
        let Stmt::Local(local) = stmt else { continue };
        let Some((name, mutable)) = local_binding_ident(local) else {
            continue;
        };
        if mutable {
            continue;
        }
        let Some(init) = local.init.as_ref() else {
            continue;
        };
        let Some(value) = lift_expr_to_term_inner(&init.expr, ctx) else {
            continue;
        };
        // IMPURITY GUARD: only capture a `let` whose initializer is a pure value
        // term. An effectful/opaque init (a `method:` call, a channel/mutex
        // conduit, ...) must stay an un-inlined local -- abstracted to a free
        // variable -- so canonicalization never duplicates the effect and never
        // identifies `let n = it.next(); n + n` (one advance) with
        // `it.next() + it.next()` (two advances).
        if !is_pure_value_term(&value) {
            continue;
        }
        bindings.push(LetBinding {
            name,
            bound_term: value,
        });
    }
    if bindings.is_empty() {
        return body;
    }
    // Keep only bindings the result references (transitive, backward fixpoint),
    // so an unrelated leading `let` does not change the emitted term. Remove the
    // bound name as the walk crosses its binding (it is bound from here down),
    // then add its initializer's free vars.
    let mut needed: HashSet<String> = free_vars_term(&body);
    let mut kept_rev: Vec<LetBinding> = Vec::new();
    for b in bindings.into_iter().rev() {
        if needed.remove(&b.name) {
            needed.extend(free_vars_term(&b.bound_term));
            kept_rev.push(b);
        }
    }
    if kept_rev.is_empty() {
        return body;
    }
    // Emit NESTED single-binding lets. `kept_rev` is innermost-first (we walked
    // the prefix in reverse), so wrapping in this order yields source-order
    // nesting: `let a in (let b in body)`.
    let mut wrapped = body;
    for b in kept_rev {
        wrapped = IrTerm::Let {
            bindings: vec![b],
            body: Box::new(wrapped),
        };
    }
    wrapped
}

fn lift_tail_expr_to_result_term(expr: &Expr, ctx: &mut LiftCtx) -> Option<IrTerm> {
    match expr {
        Expr::If(if_expr) => lift_tail_if_to_ite_term(if_expr, ctx),
        _ => lift_expr_to_term_inner(expr, ctx),
    }
}

fn lift_tail_if_to_ite_term(if_expr: &ExprIf, ctx: &mut LiftCtx) -> Option<IrTerm> {
    // The condition lifts as a boolean TERM. Prefer the structured
    // predicate lift (it normalizes comparisons / De Morgan); fall back to
    // lifting the condition directly as a term (`path.is_absolute()` ->
    // `method:is_absolute(path)`), so a method-call or other non-whitelist
    // boolean condition no longer collapses the whole `ite`. The cond term
    // is uninterpreted; the `ite` still discharges reflexively.
    let cond_formula = lift_predicate_inner(&if_expr.cond, ctx);
    let cond_term = match cond_formula.clone().and_then(formula_to_legacy_guard_term) {
        Some(t) => t,
        None => lift_expr_to_term_inner(&if_expr.cond, ctx)?,
    };
    // The then-branch value is the block's TAIL expression (last
    // expr-statement), not necessarily a single-statement block: a
    // branch may run `let x = ...; x`. Leading statements do not change
    // the returned value term.
    let then_expr = block_tail_expr(&if_expr.then_branch)?;
    let then_len_guard = {
        let mut guard_ctx = ctx.clone();
        len_eq_one_branch_guard_formula(&if_expr.cond, then_expr, &mut guard_ctx)
    };
    let then_term = lift_expr_to_term_inner(then_expr, ctx)?;
    let else_term = match if_expr.else_branch.as_ref() {
        Some((_, else_expr)) => {
            // `else if ...` nests another `if`; `else { ... }` is a block.
            // Both reduce through `lift_expr_to_term_inner` (the `If`/`Block`
            // arms), so stmt-bearing else blocks and else-if chains work.
            lift_expr_to_term_inner(else_expr, ctx)?
        }
        None => {
            // if-without-else in value position: the implicit else value is
            // `()`. Model it as an opaque nullary ctor; encoded as an
            // uninterpreted constant by the verifier, so the synthesized
            // `ite` still discharges reflexively against the body's own.
            IrTerm::Ctor {
                name: "unit".to_string(),
                args: vec![],
            }
        }
    };
    // PANIC-FREEDOM guard resolution lives HERE, in the Rust kit. The kit is
    // the only layer ALLOWED to know that `is_some`'s complement is `is_none`,
    // that `is_ok`'s is `is_err`, etc. -- this is Rust-std semantics, exactly
    // as JUnit lives in the Java emitter. The then-branch is dominated by the
    // POSITIVE guard predicate; the else-branch by its COMPLEMENT. We wrap each
    // branch value in `cf_guarded(<resolved-predicate-term>, <value>)` so the
    // language-blind verifier can thread the already-resolved atom into its
    // path condition without recognizing a single Rust predicate name.
    let then_term =
        guarded_return_for_branch(cond_formula.as_ref(), false, then_term, then_len_guard);
    let else_term = guarded_return_for_branch(cond_formula.as_ref(), true, else_term, None);
    Some(cf_ite_via_symbolic_value_boundary(
        cond_term, then_term, else_term,
    ))
}

fn cf_ite_via_symbolic_value_boundary(
    cond: IrTerm,
    then_term: IrTerm,
    else_term: IrTerm,
) -> IrTerm {
    // `cf_ite`, not the SMT builtin `ite`: a synthesized control-flow value
    // over uninterpreted Int-sorted operands. Using the builtin `ite` makes z3
    // demand a Bool guard and Bool/typed branches, which an uninterpreted guard
    // term (`match_guard(..)` : Int) does not satisfy -- a sort-mismatch error
    // that fails the reflexive discharge. As a fresh uninterpreted symbol,
    // congruence closes `cf_ite(g,a,b) == cf_ite(g,a,b)` regardless of operand
    // sorts.
    let symbolic = SymbolicValue::new(Rc::new(AlgebraTerm::Ctor {
        name: panic_freedom::CF_ITE.to_string(),
        args: vec![lower_ir(&cond), lower_ir(&then_term), lower_ir(&else_term)],
    }));
    raise_ir(&symbolic.into_term())
}

/// The closed set of boolean-predicate guards whose POSITIVE form is a
/// panic-freedom obligation a Rust-std partial demands, plus each one's
/// COMPLEMENT. This table is Rust-std semantics and is ALLOWED to live in the
/// Rust kit (the lifter) -- it is the kit's job to know that the else-branch of
/// `if opt.is_some()` is governed by `is_none`. The verifier never sees these
/// names; it only threads whatever resolved atom the kit emits on a branch.
///
/// Returns the guard-predicate HEAD that governs `branch` (then = positive,
/// else = complement), or `None` when the condition head is not a recognized
/// unary boolean predicate (a comparison `cf_lt`, a non-predicate method,
/// `cf_and`, ...). `None` means: emit no guard wrapper -> the branch carries no
/// usable fact -> a partial inside it stays honestly undecidable. `!is_empty`
/// also returns `None`: its complement establishes no partial's pre.
///
/// NAME NORMALIZATION (load-bearing for discharge). A caller's condition
/// `opt.is_some()` lifts to the method-call ctor `method:is_some` (see
/// `Expr::MethodCall` -> `format!("method:{}", ..)`), but the PARTIAL's own
/// precondition was lifted from `assert!(opt.is_some())` to the BARE predicate
/// `is_some` (the `assert!` lifter produces bare heads). For the syntactic
/// discharge `guard => pre` to hold, the guard atom this kit emits must use the
/// SAME bare head as the partial's pre. So we strip a `method:` prefix on the
/// condition head and emit the bare predicate name. The verifier never sees
/// this normalization -- it only threads the resolved bare atom.
fn branch_guard_head(cond_head: &str, else_branch: bool) -> Option<&'static str> {
    let head = match cond_head.strip_prefix("method:") {
        Some(method_head) => method_head,
        None => cond_head,
    };
    match (head, else_branch) {
        (panic_freedom::IS_SOME, false) | (panic_freedom::IS_NONE, true) => {
            Some(panic_freedom::IS_SOME)
        }
        (panic_freedom::IS_NONE, false) | (panic_freedom::IS_SOME, true) => {
            Some(panic_freedom::IS_NONE)
        }
        (panic_freedom::IS_OK, false) | (panic_freedom::IS_ERR, true) => Some(panic_freedom::IS_OK),
        (panic_freedom::IS_ERR, false) | (panic_freedom::IS_OK, true) => {
            Some(panic_freedom::IS_ERR)
        }
        ("is_empty", false) => Some("is_empty"),
        // `!is_empty` (else of `if c.is_empty()`) establishes no partial pre.
        ("is_empty", true) => None,
        (other_head, other_branch) => {
            // sugar-audit: not-mine(unrecognized guard predicates deliberately carry no branch fact)
            let _ = (other_head, other_branch);
            None
        }
    }
}

/// Wrap a branch value in `cf_guarded(<resolved-guard-term>, <value>)` when the
/// dominating condition is a recognized unary boolean predicate. The guard term
/// reuses the condition's argument terms (the receiver the predicate is about),
/// so the carried atom (`is_some(x)`) names the SAME term the partial's `pre`
/// is instantiated over -- the only way the syntactic discharge can match.
///
/// SOUNDNESS: only a recognized head is wrapped. An unrecognized condition
/// (comparison, method, conjunction) leaves the branch value UNCHANGED, so it
/// carries no fact and a partial inside it stays undecidable. The else-branch
/// receives the COMPLEMENT predicate, which never establishes the positive
/// `pre`. No path wraps a branch with a guard that would over-prove. Leaving
/// the value unchanged when no guard applies also keeps every non-guarded
/// `cf_ite` byte-identical to before this change (CID stability / reflexive
/// discharge unperturbed).
fn guarded_return_for_branch(
    cond_formula: Option<&IrFormula>,
    else_branch: bool,
    value: IrTerm,
    prioritized_guard: Option<IrFormula>,
) -> IrTerm {
    let mut guards = Vec::new();
    if let Some(guard) = prioritized_guard {
        guards.push(lower_ir_formula(&guard));
        return raise_guarded_return_ir(guard_exit(
            Desugared::StmtReturn(lower_ir(&value)),
            &guards,
            "sugar-walk.branch-guard",
        ));
    }
    let Some(IrFormula::Atomic { name, args }) = cond_formula else {
        return value;
    };
    let head = name.as_str();
    let Some(resolved_head) = branch_guard_head(head, else_branch) else {
        return value;
    };
    let guard = IrFormula::Atomic {
        name: resolved_head.to_string(),
        args: args.clone(),
    };
    guards.push(lower_ir_formula(&guard));
    raise_guarded_return_ir(guard_exit(
        Desugared::StmtReturn(lower_ir(&value)),
        &guards,
        "sugar-walk.branch-guard",
    ))
}

fn len_eq_one_branch_guard_formula(
    cond_expr: &Expr,
    branch_expr: &Expr,
    ctx: &mut LiftCtx,
) -> Option<IrFormula> {
    let receiver_key = len_eq_one_receiver_key_expr(cond_expr, ctx)?;
    let next_receiver = find_next_partial_receiver_expr(branch_expr, &receiver_key, ctx)?;
    Some(IrFormula::Atomic {
        name: panic_freedom::IS_SOME.to_string(),
        args: vec![next_receiver],
    })
}

fn len_eq_one_receiver_key_expr(expr: &Expr, ctx: &mut LiftCtx) -> Option<String> {
    let Expr::Binary(binary) = expr else {
        return None;
    };
    if !matches!(binary.op, BinOp::Eq(_)) {
        return None;
    }
    let receiver = if expr_is_const_one(&binary.right) {
        len_receiver_expr_term(&binary.left, ctx)?
    } else if expr_is_const_one(&binary.left) {
        len_receiver_expr_term(&binary.right, ctx)?
    } else {
        return None;
    };
    term_key(&receiver)
}

fn find_next_partial_receiver_expr(
    expr: &Expr,
    collection_receiver_key: &str,
    ctx: &mut LiftCtx,
) -> Option<IrTerm> {
    let mut collector = PartialReceiverCollector::default();
    collector.visit_expr(expr);
    for receiver in collector.receivers {
        if next_into_iter_receiver_key_expr(&receiver, ctx).as_deref()
            == Some(collection_receiver_key)
        {
            return lift_expr_to_term_inner(&receiver, ctx);
        }
    }
    None
}

/// Fold a value-position `match` into a right-nested `ite` chain keyed
/// by each arm's recognized guard predicate. Arm `i` with pattern-guard
/// `g_i` and value `v_i` becomes `ite(g_i, v_i, <rest>)`; the final arm
/// is the chain's tail (no guard needed). A pattern we cannot turn into
/// a boolean guard is modeled with an opaque `match_arm` guard term so
/// the chain still forms; the resulting term is uninterpreted but
/// discharges reflexively against the body's own identical match.
fn lift_match_to_ite_term(match_expr: &syn::ExprMatch, ctx: &mut LiftCtx) -> Option<IrTerm> {
    let scrutinee = lift_expr_to_term_inner(&match_expr.expr, ctx)?;
    let arms = &match_expr.arms;
    if arms.is_empty() {
        return None;
    }
    // Build from the last arm backwards.
    let mut acc: Option<IrTerm> = None;
    for (idx, arm) in arms.iter().enumerate().rev() {
        let value = lift_expr_to_term_inner(&arm.body, ctx)?;
        let is_last = idx == arms.len() - 1;
        acc = Some(if is_last && acc.is_none() {
            // Final arm: the fall-through value of the chain.
            value
        } else {
            // A guard predicate keyed by this arm's pattern against the
            // scrutinee. We do not interpret the pattern; we name an
            // opaque `match_guard(scrutinee, <pattern-hash>)` boolean. The
            // verifier encodes it as an uninterpreted predicate symbol.
            let pat_hash = opaque_token_hash(&arm.pat);
            let guard = IrTerm::Ctor {
                name: "match_guard".to_string(),
                args: vec![
                    scrutinee.clone(),
                    IrTerm::Var {
                        name: format!("#pat:{pat_hash}"),
                    },
                ],
            };
            cf_ite_via_symbolic_value_boundary(
                guard,
                value,
                acc.expect("non-final arm has an accumulator"),
            )
        });
    }
    acc
}

/// Lift a macro invocation (`json!{...}`, `format!(...)`, `vec![...]`,
/// ...) to an OPAQUE uninterpreted term keyed by the macro's name plus a
/// deterministic hash of its token stream. Two identical macro calls
/// (same name, same tokens) produce the SAME term, so a body returning
/// `Ok(json!({...}))` and a post derived from that same body yield
/// `Ok(macro:json!#<h>) == Ok(macro:json!#<h>)`, which discharges by
/// reflexivity. A DIFFERENT macro call hashes differently and does not
/// spuriously unify. The argument tokens are not lifted (a macro body is
/// not Rust expression grammar); the hash is the whole content.
fn lift_macro_to_opaque_term(mac: &Macro) -> IrTerm {
    let name = mac
        .path
        .segments
        .last()
        .map(|s| s.ident.to_string())
        .unwrap_or_else(|| "macro".to_string());
    let tok_hash = opaque_token_hash(&mac.tokens);
    IrTerm::Ctor {
        name: format!("macro:{name}#{tok_hash}"),
        args: vec![],
    }
}

/// Deterministic short hash of any `ToTokens` node (a macro's token
/// stream, a match pattern, ...). Stable across runs: the token stream
/// renders to a canonical string and is blake3-hashed; the first 16 hex
/// chars key the opaque term. Determinism matters because the SAME
/// surface node must encode to the SAME symbol on both sides of the
/// reflexive equality.
fn opaque_token_hash<T: quote::ToTokens>(node: &T) -> String {
    let rendered = node.to_token_stream().to_string();
    let full = sugar_canonicalizer::blake3_512_hex(rendered.as_bytes());
    // `blake3_512_hex` returns a `blake3-512:<hex>` prefixed string; take
    // the hex tail and keep it short for readable terms.
    let hex = match full.rsplit_once(':') {
        Some((_, hex)) => hex,
        None => full.as_str(),
    };
    hex.chars().take(16).collect()
}

/// The block's value expression: its trailing expr-statement (no
/// semicolon). Unlike `block_single_tail_expr` this tolerates LEADING
/// statements (`let x = ...; x`), because they do not change the value
/// the block evaluates to. Returns `None` for a block whose last
/// statement is not a tail expression (e.g. ends in a `;` -> unit value).
fn block_tail_expr(block: &syn::Block) -> Option<&Expr> {
    let Some(Stmt::Expr(expr, None)) = block.stmts.last() else {
        return None;
    };
    Some(expr)
}

/// Collect all names bound by `let` patterns at the top level of a statement.
/// Used for the shadowing check in `lift_function_postcondition`.
fn collect_let_bound_names(stmt: &Stmt, out: &mut HashSet<String>) {
    if let Stmt::Local(Local { pat, .. }) = stmt {
        collect_pat_names(pat, out);
    }
}

/// Recursively collect all bound names from a pattern.
fn collect_pat_names(pat: &Pat, out: &mut HashSet<String>) {
    match pat {
        Pat::Ident(p) => {
            out.insert(p.ident.to_string());
            if let Some((_, subpat)) = &p.subpat {
                collect_pat_names(subpat, out);
            }
        }
        Pat::Type(pt) => collect_pat_names(&pt.pat, out),
        Pat::Reference(r) => collect_pat_names(&r.pat, out),
        Pat::Paren(p) => collect_pat_names(&p.pat, out),
        Pat::Tuple(t) => {
            for sub in &t.elems {
                collect_pat_names(sub, out);
            }
        }
        Pat::TupleStruct(ts) => {
            for sub in &ts.elems {
                collect_pat_names(sub, out);
            }
        }
        Pat::Struct(s) => {
            for field in &s.fields {
                collect_pat_names(&field.pat, out);
            }
        }
        Pat::Slice(s) => {
            for sub in &s.elems {
                collect_pat_names(sub, out);
            }
        }
        Pat::Const(_)
        | Pat::Lit(_)
        | Pat::Path(_)
        | Pat::Range(_)
        | Pat::Rest(_)
        | Pat::Wild(_) => {}
        Pat::Macro(_) | Pat::Verbatim(_) => {
            panic!("sugar-walk pattern name collector refused opaque syn::Pat variant")
        }
        other => {
            let _ = other;
            panic!("sugar-walk pattern name collector refused unknown syn::Pat variant")
        }
    }
}

fn pat_contains_mut_ident(pat: &Pat) -> bool {
    match pat {
        Pat::Ident(ident) => ident.mutability.is_some(),
        Pat::Type(typed) => pat_contains_mut_ident(&typed.pat),
        Pat::Reference(reference) => pat_contains_mut_ident(&reference.pat),
        Pat::Paren(paren) => pat_contains_mut_ident(&paren.pat),
        Pat::Tuple(tuple) => tuple.elems.iter().any(pat_contains_mut_ident),
        Pat::TupleStruct(tuple) => tuple.elems.iter().any(pat_contains_mut_ident),
        Pat::Struct(strukt) => strukt
            .fields
            .iter()
            .any(|field| pat_contains_mut_ident(&field.pat)),
        Pat::Slice(slice) => slice.elems.iter().any(pat_contains_mut_ident),
        Pat::Or(or) => or.cases.iter().any(pat_contains_mut_ident),
        _ => false,
    }
}

fn seed_mutable_param_roots(item_fn: &ItemFn, ctx: &mut LiftCtx) {
    for input in &item_fn.sig.inputs {
        let FnArg::Typed(arg) = input else {
            continue;
        };
        let Pat::Ident(ident) = &*arg.pat else {
            continue;
        };
        if ident.mutability.is_some() {
            ctx.mutable_roots.insert(ident.ident.to_string());
        }
    }
}

fn seed_param_value_kinds(item_fn: &ItemFn, ctx: &mut LiftCtx) {
    for input in &item_fn.sig.inputs {
        let FnArg::Typed(arg) = input else {
            continue;
        };
        let Pat::Ident(ident) = &*arg.pat else {
            continue;
        };
        if ident.mutability.is_some() {
            continue;
        }
        if type_is_string(&arg.ty) {
            ctx.local_value_kinds
                .insert(ident.ident.to_string(), ValueKind::String);
        }
    }
}

/// Track top-level facts established by `assert!` for later panic partials.
///
/// SOUNDNESS / refuse-floor: the propagation is same-function, top-level, and
/// same-receiver only. Branch-local asserts are not scanned; mutations or
/// shadowing invalidate a fact immediately. Mutable roots are refused because
/// this slice does not model aliasing or mutation.
fn collect_assertion_guard_facts(stmts: &[Stmt], ctx: &mut LiftCtx) {
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => {
                let mut names = HashSet::new();
                collect_pat_names(&local.pat, &mut names);
                let local_mutable = match local_binding_ident(local) {
                    Some((_, mutable)) => mutable,
                    None => pat_contains_mut_ident(&local.pat),
                };
                for name in names {
                    ctx.invalidate_root(&name);
                    if local_mutable {
                        ctx.mutable_roots.insert(name);
                    }
                }
            }
            Stmt::Macro(StmtMacro { mac, .. }) => {
                collect_assert_macro_guard_fact(mac, ctx);
            }
            Stmt::Expr(Expr::Macro(ExprMacro { mac, .. }), _) => {
                collect_assert_macro_guard_fact(mac, ctx);
            }
            Stmt::Expr(expr, _) => invalidate_assignment_targets(expr, ctx),
            Stmt::Item(_) => {}
        }
    }
}

fn collect_assert_macro_guard_fact(mac: &Macro, ctx: &mut LiftCtx) {
    let Some(first) = assert_macro_condition(mac) else {
        return;
    };
    if let Some(fact) = tracked_direct_guard_fact(&first, ctx) {
        ctx.assertion_guard_facts.push(fact);
        return;
    }
    if let Some(fact) = tracked_len_eq_one_fact(&first, ctx) {
        ctx.len_eq_one_facts.push(fact);
    }
}

fn assert_macro_condition(mac: &Macro) -> Option<Expr> {
    let seg = mac.path.segments.last()?;
    if seg.ident != "assert" {
        return None;
    }
    let parsed_cond = match syn::parse2::<Expr>(first_macro_arg_tokens(mac.tokens.clone())) {
        Ok(expr) => expr,
        Err(err) => panic!("{err}"),
    };
    // Keep the prior tuple fallback for already-parenthesized conditions.
    match parsed_cond {
        Expr::Tuple(t) => t.elems.first().cloned(),
        other => Some(other),
    }
}

fn first_macro_arg_tokens(tokens: TokenStream) -> TokenStream {
    let mut first = TokenStream::new();
    for token in tokens {
        if matches!(&token, TokenTree::Punct(punct) if punct.as_char() == ',') {
            break;
        }
        first.extend(std::iter::once(token));
    }
    first
}

fn tracked_direct_guard_fact(expr: &Expr, ctx: &mut LiftCtx) -> Option<TrackedGuardFact> {
    let Expr::MethodCall(method_call) = expr else {
        return None;
    };
    if !method_call.args.is_empty() {
        return None;
    }
    let guard_head = method_call.method.to_string();
    if !matches!(
        guard_head.as_str(),
        panic_freedom::IS_SOME | panic_freedom::IS_OK | panic_freedom::IS_ERR
    ) {
        return None;
    }
    let root = expr_root_ident(&method_call.receiver)?;
    if ctx.mutable_roots.contains(&root) {
        return None;
    }
    let receiver = lift_expr_to_term_inner(&method_call.receiver, ctx)?;
    let receiver_key = term_key(&receiver)?;
    let guard = IrFormula::Atomic {
        name: guard_head.clone(),
        args: vec![receiver],
    };
    Some(TrackedGuardFact {
        root,
        receiver_key,
        guard_head,
        guard,
    })
}

fn tracked_len_eq_one_fact(expr: &Expr, ctx: &mut LiftCtx) -> Option<LenEqOneFact> {
    let receiver = len_eq_one_receiver_expr_term(expr, ctx)?;
    let root = len_receiver_root_from_eq_expr(expr)?;
    if ctx.mutable_roots.contains(&root) {
        return None;
    }
    Some(LenEqOneFact {
        root,
        receiver_key: term_key(&receiver)?,
    })
}

fn len_eq_one_receiver_expr_term(expr: &Expr, ctx: &mut LiftCtx) -> Option<IrTerm> {
    let Expr::Binary(binary) = expr else {
        return None;
    };
    if !matches!(binary.op, BinOp::Eq(_)) {
        return None;
    }
    if expr_is_const_one(&binary.right) {
        len_receiver_expr_term(&binary.left, ctx)
    } else if expr_is_const_one(&binary.left) {
        len_receiver_expr_term(&binary.right, ctx)
    } else {
        None
    }
}

fn len_receiver_expr_term(expr: &Expr, ctx: &mut LiftCtx) -> Option<IrTerm> {
    let Expr::MethodCall(method_call) = expr else {
        return None;
    };
    if method_call.method != "len" || !method_call.args.is_empty() {
        return None;
    }
    lift_expr_to_term_inner(&method_call.receiver, ctx)
}

fn expr_is_const_one(expr: &Expr) -> bool {
    let Expr::Lit(lit) = expr else {
        return false;
    };
    let Lit::Int(value) = &lit.lit else {
        return false;
    };
    matches!(value.base10_parse::<i64>(), Ok(1))
}

fn len_receiver_root_from_eq_expr(expr: &Expr) -> Option<String> {
    let Expr::Binary(binary) = expr else {
        return None;
    };
    len_receiver_root_expr(&binary.left).or_else(|| len_receiver_root_expr(&binary.right))
}

fn len_receiver_root_expr(expr: &Expr) -> Option<String> {
    match expr {
        Expr::MethodCall(method_call)
            if method_call.method == "len" && method_call.args.is_empty() =>
        {
            expr_root_ident(&method_call.receiver)
        }
        Expr::Paren(paren) => len_receiver_root_expr(&paren.expr),
        Expr::Group(group) => len_receiver_root_expr(&group.expr),
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::Field(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Index(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::MethodCall(_)
        | Expr::Path(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Reference(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        Expr::Verbatim(_) => {
            panic!("sugar-walk len receiver classifier refused uninterpreted verbatim expression")
        }
        other => {
            let _ = other;
            panic!("sugar-walk len receiver classifier refused unknown syn::Expr variant")
        }
    }
}

fn expr_root_ident(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) => path.path.segments.last().map(|seg| seg.ident.to_string()),
        Expr::Reference(reference) => expr_root_ident(&reference.expr),
        Expr::Paren(paren) => expr_root_ident(&paren.expr),
        Expr::Cast(cast) => expr_root_ident(&cast.expr),
        Expr::Field(field) => expr_root_ident(&field.base),
        Expr::Group(group) => expr_root_ident(&group.expr),
        Expr::Index(index) => expr_root_ident(&index.expr),
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::MethodCall(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        Expr::Verbatim(_) => {
            panic!(
                "sugar-walk root identifier classifier refused uninterpreted verbatim expression"
            )
        }
        other => {
            let _ = other;
            panic!("sugar-walk root identifier classifier refused unknown syn::Expr variant")
        }
    }
}

fn term_key(term: &IrTerm) -> Option<String> {
    match serde_json::to_string(term) {
        Ok(key) => Some(key),
        Err(err) => panic!("sugar-walk refused unserializable IR term key: {err}"),
    }
}

/// Track local json! construction facts for this function body.
///
/// SOUNDNESS / refuse-floor: this is a Rust-kit-only analysis and must bless
/// only facts proven by explicit local construction. Any uncertainty (mutable
/// binding, assignment to a tracked value, non-literal json! macro, opaque call,
/// or divergent shape we do not model) becomes `Unknown`; `Unknown` never emits
/// `cf_guarded`, so the panic site stays honestly undecidable. In particular,
/// `let mut x = json!(...); x["k"] = ...` is refused in this slice rather than
/// tracked.
fn collect_local_value_facts(stmts: &[Stmt], ctx: &mut LiftCtx) {
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => collect_local_binding_value_fact(local, ctx),
            Stmt::Expr(expr, _) => invalidate_assignment_targets(expr, ctx),
            Stmt::Macro(_) | Stmt::Item(_) => {}
        }
    }
}

fn collect_local_binding_value_fact(local: &Local, ctx: &mut LiftCtx) {
    let Some((name, mutable)) = local_binding_ident(local) else {
        let mut names = HashSet::new();
        collect_pat_names(&local.pat, &mut names);
        for name in names {
            ctx.local_value_kinds.remove(&name);
        }
        return;
    };
    if mutable {
        ctx.local_value_kinds.remove(&name);
        return;
    }
    let kind = local
        .init
        .as_ref()
        .map(|init| infer_value_kind(&init.expr, ctx));
    let kind = match kind {
        Some(kind) => kind,
        None => ValueKind::Unknown,
    };
    ctx.local_value_kinds.insert(name, kind);
}

fn local_binding_ident(local: &Local) -> Option<(String, bool)> {
    local_binding_ident_for_pat(&local.pat)
}

fn local_binding_ident_for_pat(pat: &Pat) -> Option<(String, bool)> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => {
            Some((ident.ident.to_string(), ident.mutability.is_some()))
        }
        Pat::Ident(_) => None,
        Pat::Paren(paren) => local_binding_ident_for_pat(&paren.pat),
        Pat::Reference(reference) => local_binding_ident_for_pat(&reference.pat),
        Pat::Type(typed) => local_binding_ident_for_pat(&typed.pat),
        Pat::Const(_)
        | Pat::Lit(_)
        | Pat::Macro(_)
        | Pat::Or(_)
        | Pat::Path(_)
        | Pat::Range(_)
        | Pat::Rest(_)
        | Pat::Slice(_)
        | Pat::Struct(_)
        | Pat::Tuple(_)
        | Pat::TupleStruct(_)
        | Pat::Verbatim(_)
        | Pat::Wild(_) => None,
        other => {
            let _ = other;
            panic!("sugar-walk local binding classifier refused unknown syn::Pat variant")
        }
    }
}

fn invalidate_assignment_targets(expr: &Expr, ctx: &mut LiftCtx) {
    let mut roots = BTreeSet::new();
    collect_assignment_target_roots_in_expr(expr, &mut roots);
    for root in roots {
        ctx.invalidate_root(&root);
    }
}

fn collect_assignment_target_roots_in_expr(expr: &Expr, roots: &mut BTreeSet<String>) {
    match expr {
        Expr::Assign(assign) => {
            collect_assignment_roots_lift(&assign.left, roots);
            collect_assignment_target_roots_in_expr(&assign.right, roots);
        }
        Expr::Binary(binary) => {
            if binop_is_assignment_lift(&binary.op) {
                collect_assignment_roots_lift(&binary.left, roots);
            } else {
                collect_assignment_target_roots_in_expr(&binary.left, roots);
            }
            collect_assignment_target_roots_in_expr(&binary.right, roots);
        }
        Expr::Array(array) => {
            for elem in &array.elems {
                collect_assignment_target_roots_in_expr(elem, roots);
            }
        }
        Expr::Async(async_expr) => {
            collect_assignment_target_roots_in_stmts(&async_expr.block.stmts, roots)
        }
        Expr::Await(await_expr) => collect_assignment_target_roots_in_expr(&await_expr.base, roots),
        Expr::Block(block) => collect_assignment_target_roots_in_stmts(&block.block.stmts, roots),
        Expr::Break(break_expr) => {
            if let Some(expr) = &break_expr.expr {
                collect_assignment_target_roots_in_expr(expr, roots);
            }
        }
        Expr::Call(call) => {
            collect_assignment_target_roots_in_expr(&call.func, roots);
            for arg in &call.args {
                collect_assignment_target_roots_in_expr(arg, roots);
            }
        }
        Expr::Cast(cast) => collect_assignment_target_roots_in_expr(&cast.expr, roots),
        Expr::Closure(_) => {}
        Expr::Const(const_expr) => {
            collect_assignment_target_roots_in_stmts(&const_expr.block.stmts, roots)
        }
        Expr::Field(field) => collect_assignment_target_roots_in_expr(&field.base, roots),
        Expr::ForLoop(for_loop) => {
            collect_assignment_target_roots_in_expr(&for_loop.expr, roots);
            collect_assignment_target_roots_in_stmts(&for_loop.body.stmts, roots);
        }
        Expr::Group(group) => collect_assignment_target_roots_in_expr(&group.expr, roots),
        Expr::If(if_expr) => {
            collect_assignment_target_roots_in_expr(&if_expr.cond, roots);
            collect_assignment_target_roots_in_stmts(&if_expr.then_branch.stmts, roots);
            if let Some((_, else_expr)) = &if_expr.else_branch {
                collect_assignment_target_roots_in_expr(else_expr, roots);
            }
        }
        Expr::Index(index) => {
            collect_assignment_target_roots_in_expr(&index.expr, roots);
            collect_assignment_target_roots_in_expr(&index.index, roots);
        }
        Expr::Let(let_expr) => collect_assignment_target_roots_in_expr(&let_expr.expr, roots),
        Expr::Loop(loop_expr) => {
            collect_assignment_target_roots_in_stmts(&loop_expr.body.stmts, roots)
        }
        Expr::Match(match_expr) => {
            collect_assignment_target_roots_in_expr(&match_expr.expr, roots);
            for arm in &match_expr.arms {
                if let Some((_, guard)) = &arm.guard {
                    collect_assignment_target_roots_in_expr(guard, roots);
                }
                collect_assignment_target_roots_in_expr(&arm.body, roots);
            }
        }
        Expr::MethodCall(method) => {
            collect_assignment_target_roots_in_expr(&method.receiver, roots);
            for arg in &method.args {
                collect_assignment_target_roots_in_expr(arg, roots);
            }
        }
        Expr::Paren(paren) => collect_assignment_target_roots_in_expr(&paren.expr, roots),
        Expr::Range(range) => {
            if let Some(start) = &range.start {
                collect_assignment_target_roots_in_expr(start, roots);
            }
            if let Some(end) = &range.end {
                collect_assignment_target_roots_in_expr(end, roots);
            }
        }
        Expr::RawAddr(raw_addr) => collect_assignment_target_roots_in_expr(&raw_addr.expr, roots),
        Expr::Reference(reference) => {
            if reference.mutability.is_some() {
                collect_assignment_roots_lift(&reference.expr, roots);
            }
            collect_assignment_target_roots_in_expr(&reference.expr, roots);
        }
        Expr::Repeat(repeat) => {
            collect_assignment_target_roots_in_expr(&repeat.expr, roots);
            collect_assignment_target_roots_in_expr(&repeat.len, roots);
        }
        Expr::Return(return_expr) => {
            if let Some(expr) = &return_expr.expr {
                collect_assignment_target_roots_in_expr(expr, roots);
            }
        }
        Expr::Struct(struct_expr) => {
            for field in &struct_expr.fields {
                collect_assignment_target_roots_in_expr(&field.expr, roots);
            }
            if let Some(rest) = &struct_expr.rest {
                collect_assignment_target_roots_in_expr(rest, roots);
            }
        }
        Expr::Try(try_expr) => collect_assignment_target_roots_in_expr(&try_expr.expr, roots),
        Expr::TryBlock(try_block) => {
            collect_assignment_target_roots_in_stmts(&try_block.block.stmts, roots)
        }
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_assignment_target_roots_in_expr(elem, roots);
            }
        }
        Expr::Unary(unary) => collect_assignment_target_roots_in_expr(&unary.expr, roots),
        Expr::Unsafe(unsafe_expr) => {
            collect_assignment_target_roots_in_stmts(&unsafe_expr.block.stmts, roots)
        }
        Expr::While(while_expr) => {
            collect_assignment_target_roots_in_expr(&while_expr.cond, roots);
            collect_assignment_target_roots_in_stmts(&while_expr.body.stmts, roots);
        }
        Expr::Yield(yield_expr) => {
            if let Some(expr) = &yield_expr.expr {
                collect_assignment_target_roots_in_expr(expr, roots);
            }
        }
        Expr::Continue(_) | Expr::Infer(_) | Expr::Lit(_) | Expr::Path(_) => {}
        Expr::Macro(expr_macro) if assignment_target_macro_has_no_roots(&expr_macro.mac) => {}
        Expr::Macro(_) | Expr::Verbatim(_) => {
            panic!("sugar-walk assignment target collector refused opaque syn::Expr variant")
        }
        other => {
            let _ = other;
            panic!("sugar-walk assignment target collector refused unknown syn::Expr variant")
        }
    }
}

fn collect_assignment_target_roots_in_stmts(stmts: &[Stmt], roots: &mut BTreeSet<String>) {
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => {
                if let Some(init) = &local.init {
                    collect_assignment_target_roots_in_expr(&init.expr, roots);
                }
            }
            Stmt::Expr(expr, _) => collect_assignment_target_roots_in_expr(expr, roots),
            Stmt::Item(_) => {}
            Stmt::Macro(stmt_macro) if assignment_target_macro_has_no_roots(&stmt_macro.mac) => {}
            Stmt::Macro(_) => {
                panic!("sugar-walk assignment target collector refused opaque statement macro")
            }
        }
    }
}

fn assignment_target_macro_has_no_roots(mac: &Macro) -> bool {
    match macro_leaf_name(mac).as_deref() {
        Some(
            "assert" | "debug_assert" | "debug_assert_eq" | "debug_assert_ne" | "eprintln"
            | "format" | "json" | "panic" | "println" | "vec",
        ) => true,
        Some(other) => {
            let _ = other;
            false
        }
        None => false,
    }
}

fn infer_value_kind(expr: &Expr, ctx: &LiftCtx) -> ValueKind {
    match expr {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Str(_) => ValueKind::String,
            Lit::Int(_) | Lit::Float(_) => ValueKind::Number,
            Lit::Bool(_) => ValueKind::Bool,
            _ => ValueKind::Unknown,
        },
        Expr::Path(path) => match path.path.segments.last() {
            Some(seg) => match ctx.local_value_kinds.get(&seg.ident.to_string()) {
                Some(kind) => kind.clone(),
                None => ValueKind::Unknown,
            },
            None => ValueKind::Unknown,
        },
        Expr::Paren(paren) => infer_value_kind(&paren.expr, ctx),
        Expr::Reference(reference) => infer_value_kind(&reference.expr, ctx),
        Expr::Group(group) => infer_value_kind(&group.expr, ctx),
        Expr::MethodCall(method) => {
            let method_name = method.method.to_string();
            match method_name.as_str() {
                "to_string" => ValueKind::String,
                "clone" if method.args.is_empty() => infer_value_kind(&method.receiver, ctx),
                _ => ValueKind::Unknown,
            }
        }
        Expr::Call(call) => {
            let Some(callee) = call_callee_name(call) else {
                return ValueKind::Unknown;
            };
            if ctx.return_facts.direct_string.contains(&callee) {
                ValueKind::String
            } else {
                // A bare call to `fn f() -> Result<String, _>` is not a string;
                // only `f()?` produces the inner String in this slice.
                ValueKind::Unknown
            }
        }
        Expr::Try(try_expr) => {
            if let Expr::Call(call) = &*try_expr.expr {
                if let Some(callee) = call_callee_name(call) {
                    if ctx.return_facts.result_string.contains(&callee) {
                        return ValueKind::String;
                    }
                }
            }
            ValueKind::Unknown
        }
        Expr::Index(index) => infer_indexed_json_value_kind(index, ctx),
        Expr::Macro(expr_macro) => infer_macro_value_kind(&expr_macro.mac, ctx),
        _ => ValueKind::Unknown,
    }
}

fn call_callee_name(call: &syn::ExprCall) -> Option<String> {
    let Expr::Path(path) = &*call.func else {
        return None;
    };
    path.path.segments.last().map(|seg| seg.ident.to_string())
}

fn infer_indexed_json_value_kind(index: &syn::ExprIndex, ctx: &LiftCtx) -> ValueKind {
    let ValueKind::JsonObject(fields) = infer_value_kind(&index.expr, ctx) else {
        return ValueKind::Unknown;
    };
    let Some(key) = expr_string_literal(&index.index) else {
        return ValueKind::Unknown;
    };
    match fields.get(&key) {
        Some(kind) => kind.clone(),
        None => ValueKind::Unknown,
    }
}

fn expr_string_literal(expr: &Expr) -> Option<String> {
    if let Expr::Lit(lit) = expr {
        return lit_string_literal(&lit.lit);
    }
    if let Expr::Paren(paren) = expr {
        return expr_string_literal(&paren.expr);
    }
    if let Expr::Group(group) = expr {
        return expr_string_literal(&group.expr);
    }
    if matches!(expr, Expr::Verbatim(_)) {
        panic!("sugar-walk string literal classifier refused uninterpreted verbatim expression");
    }
    if known_non_string_literal_expr(expr) {
        return None;
    }
    panic!("sugar-walk string literal classifier refused unknown syn::Expr variant")
}

fn lit_string_literal(lit: &Lit) -> Option<String> {
    if let Lit::Str(s) = lit {
        return Some(s.value());
    }
    if known_non_string_lit(lit) {
        return None;
    }
    panic!("sugar-walk string literal classifier refused unknown syn::Lit variant")
}

fn known_non_string_lit(lit: &Lit) -> bool {
    matches!(
        lit,
        Lit::Bool(_)
            | Lit::Byte(_)
            | Lit::ByteStr(_)
            | Lit::CStr(_)
            | Lit::Char(_)
            | Lit::Float(_)
            | Lit::Int(_)
            | Lit::Verbatim(_)
    )
}

fn known_non_string_literal_expr(expr: &Expr) -> bool {
    matches!(
        expr,
        Expr::Array(_)
            | Expr::Assign(_)
            | Expr::Async(_)
            | Expr::Await(_)
            | Expr::Binary(_)
            | Expr::Block(_)
            | Expr::Break(_)
            | Expr::Call(_)
            | Expr::Cast(_)
            | Expr::Closure(_)
            | Expr::Const(_)
            | Expr::Continue(_)
            | Expr::Field(_)
            | Expr::ForLoop(_)
            | Expr::If(_)
            | Expr::Index(_)
            | Expr::Infer(_)
            | Expr::Let(_)
            | Expr::Loop(_)
            | Expr::Macro(_)
            | Expr::Match(_)
            | Expr::MethodCall(_)
            | Expr::Path(_)
            | Expr::Range(_)
            | Expr::RawAddr(_)
            | Expr::Reference(_)
            | Expr::Repeat(_)
            | Expr::Return(_)
            | Expr::Struct(_)
            | Expr::Try(_)
            | Expr::TryBlock(_)
            | Expr::Tuple(_)
            | Expr::Unary(_)
            | Expr::Unsafe(_)
            | Expr::While(_)
            | Expr::Yield(_)
    )
}

fn infer_macro_value_kind(mac: &Macro, ctx: &LiftCtx) -> ValueKind {
    match macro_leaf_name(mac).as_deref() {
        Some("format") => ValueKind::String,
        Some("json") => match parse_json_object_macro(mac, ctx) {
            Some(fields) => ValueKind::JsonObject(fields),
            None => ValueKind::Unknown,
        },
        _ => ValueKind::Unknown,
    }
}

fn macro_leaf_name(mac: &Macro) -> Option<String> {
    mac.path.segments.last().map(|seg| seg.ident.to_string())
}

fn parse_json_object_macro(mac: &Macro, ctx: &LiftCtx) -> Option<BTreeMap<String, ValueKind>> {
    let mut iter = mac.tokens.clone().into_iter();
    let Some(TokenTree::Group(group)) = iter.next() else {
        return None;
    };
    if group.delimiter() != Delimiter::Brace || iter.next().is_some() {
        return None;
    }
    parse_json_object_tokens(group.stream(), ctx)
}

fn parse_json_object_tokens(
    tokens: TokenStream,
    ctx: &LiftCtx,
) -> Option<BTreeMap<String, ValueKind>> {
    let mut fields = BTreeMap::new();
    let mut iter = tokens.into_iter().peekable();
    while let Some(token) = iter.next() {
        if is_comma(&token) {
            continue;
        }
        let key = token_string_literal(&token)?;
        let Some(colon) = iter.next() else {
            return None;
        };
        if !is_colon(&colon) {
            return None;
        }
        let mut value_tokens = TokenStream::new();
        while let Some(next) = iter.peek() {
            if is_comma(next) {
                iter.next();
                break;
            }
            let next = iter.next().expect("peeked token exists");
            value_tokens.extend(std::iter::once(next));
        }
        if value_tokens.is_empty() {
            return None;
        }
        fields.insert(key, infer_json_value_tokens(value_tokens, ctx));
    }
    Some(fields)
}

fn infer_json_value_tokens(tokens: TokenStream, ctx: &LiftCtx) -> ValueKind {
    let mut iter = tokens.clone().into_iter();
    if let Some(TokenTree::Group(group)) = iter.next() {
        if group.delimiter() == Delimiter::Brace && iter.next().is_none() {
            return match parse_json_object_tokens(group.stream(), ctx) {
                Some(fields) => ValueKind::JsonObject(fields),
                None => ValueKind::Unknown,
            };
        }
    }
    match syn::parse2::<Expr>(tokens) {
        Ok(expr) => infer_value_kind(&expr, ctx),
        Err(_) => ValueKind::Unknown,
    }
}

fn token_string_literal(token: &TokenTree) -> Option<String> {
    let TokenTree::Literal(lit) = token else {
        return None;
    };
    let Ok(parsed) = syn::parse_str::<Lit>(&lit.to_string()) else {
        return None;
    };
    lit_string_literal(&parsed)
}

fn is_comma(token: &TokenTree) -> bool {
    matches!(token, TokenTree::Punct(p) if p.as_char() == ',')
}

fn is_colon(token: &TokenTree) -> bool {
    matches!(token, TokenTree::Punct(p) if p.as_char() == ':')
}

fn receiver_as_str_is_known_json_string(receiver: &Expr, ctx: &LiftCtx) -> bool {
    let Expr::MethodCall(method) = receiver else {
        return false;
    };
    method.method == "as_str"
        && method.args.is_empty()
        && matches!(infer_value_kind(&method.receiver, ctx), ValueKind::String)
}

fn guarded_value_for_known_option_unwrap(receiver: IrTerm, value: IrTerm) -> IrTerm {
    guarded_value_from_formula(
        IrFormula::Atomic {
            name: panic_freedom::IS_SOME.to_string(),
            args: vec![receiver],
        },
        value,
    )
}

fn guarded_value_from_formula(guard: IrFormula, value: IrTerm) -> IrTerm {
    raise_guarded_return_ir(guard_exit(
        Desugared::StmtReturn(lower_ir(&value)),
        &[lower_ir_formula(&guard)],
        "sugar-walk.branch-guard",
    ))
}

fn assertion_guard_for_partial(
    method: &syn::Ident,
    receiver_expr: &Expr,
    receiver_term: &IrTerm,
    ctx: &mut LiftCtx,
) -> Option<IrFormula> {
    let method = method.to_string();
    let receiver_key = term_key(receiver_term)?;
    for fact in &ctx.assertion_guard_facts {
        if fact.receiver_key != receiver_key {
            continue;
        }
        match (method.as_str(), fact.guard_head.as_str()) {
            ("unwrap" | "expect", panic_freedom::IS_SOME | panic_freedom::IS_OK) => {
                return Some(fact.guard.clone())
            }
            ("unwrap_err", panic_freedom::IS_ERR) => return Some(fact.guard.clone()),
            (other_method, other_guard) => {
                // sugar-audit: not-mine(non-matching partial/guard pairs must not discharge)
                let _ = (other_method, other_guard);
            }
        }
    }
    let next_receiver_key = next_into_iter_receiver_key_expr(receiver_expr, ctx);
    if matches!(method.as_str(), "unwrap" | "expect")
        && ctx
            .len_eq_one_facts
            .iter()
            .any(|fact| next_receiver_key.as_ref() == Some(&fact.receiver_key))
    {
        return Some(IrFormula::Atomic {
            name: panic_freedom::IS_SOME.to_string(),
            args: vec![receiver_term.clone()],
        });
    }
    None
}

fn next_into_iter_receiver_key_expr(expr: &Expr, ctx: &mut LiftCtx) -> Option<String> {
    let Expr::MethodCall(next_call) = expr else {
        return None;
    };
    if next_call.method != "next" || !next_call.args.is_empty() {
        return None;
    }
    let Expr::MethodCall(into_iter_call) = &*next_call.receiver else {
        return None;
    };
    if into_iter_call.method != "into_iter" || !into_iter_call.args.is_empty() {
        return None;
    }
    let receiver = lift_expr_to_term_inner(&into_iter_call.receiver, ctx)?;
    term_key(&receiver)
}

#[derive(Default)]
struct PartialReceiverCollector {
    receivers: Vec<Expr>,
}

impl<'ast> Visit<'ast> for PartialReceiverCollector {
    fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
        let method = node.method.to_string();
        if matches!(method.as_str(), "unwrap" | "expect") && node.args.is_empty() {
            self.receivers.push((*node.receiver).clone());
        }
        visit::visit_expr_method_call(self, node);
    }
}

fn collect_statement_guarded_panic_effects(stmts: &[Stmt], ctx: &mut LiftCtx) -> Vec<IrFormula> {
    let mut guard_facts = StatementGuardFacts::default();
    let mut out = Vec::new();
    collect_guarded_panic_effects_in_stmts(stmts, ctx, &mut guard_facts, &mut out);
    out
}

fn collect_guarded_panic_effects_in_stmts(
    stmts: &[Stmt],
    ctx: &mut LiftCtx,
    guard_facts: &mut StatementGuardFacts,
    out: &mut Vec<IrFormula>,
) {
    for stmt in stmts {
        collect_guarded_panic_effects_in_stmt(stmt, ctx, guard_facts, out);
    }
}

fn collect_guarded_panic_effects_in_stmt(
    stmt: &Stmt,
    ctx: &mut LiftCtx,
    guard_facts: &mut StatementGuardFacts,
    out: &mut Vec<IrFormula>,
) {
    match stmt {
        Stmt::Local(local) => {
            if let Some(init) = &local.init {
                collect_guarded_panic_effects_in_expr(&init.expr, ctx, guard_facts, out);
                invalidate_statement_guard_facts_for_expr_effects(&init.expr, guard_facts);
            }
            invalidate_statement_guard_facts_for_pat(&local.pat, guard_facts);
            if let Some((root, source)) = keyset_snapshot_for_local(local, ctx) {
                guard_facts.keyset_snapshots.insert(root, source);
            }
        }
        Stmt::Expr(expr, _) => {
            collect_guarded_panic_effects_in_expr(expr, ctx, guard_facts, out);
            invalidate_statement_guard_facts_for_expr_effects(expr, guard_facts);
        }
        Stmt::Macro(_) | Stmt::Item(_) => {}
    }
}

fn collect_guarded_panic_effects_in_expr(
    expr: &Expr,
    ctx: &mut LiftCtx,
    guard_facts: &mut StatementGuardFacts,
    out: &mut Vec<IrFormula>,
) {
    match expr {
        Expr::If(if_expr) => {
            collect_guarded_panic_effects_in_expr(&if_expr.cond, ctx, guard_facts, out);
            invalidate_statement_guard_facts_for_expr_effects(&if_expr.cond, guard_facts);
            let saved_guard_facts = guard_facts.clone();
            let mut branch_guard_facts = Vec::new();
            if expr_effect_mutation_roots(&if_expr.cond).is_empty() {
                collect_statement_pure_free_guard_facts(
                    &if_expr.cond,
                    ctx,
                    &mut branch_guard_facts,
                );
            } else {
                debug!(
                    "lift_function_postcondition: refusing pure-free statement guard facts from mutating if condition"
                );
            }
            guard_facts.pure_free.extend(branch_guard_facts);
            collect_guarded_panic_effects_in_stmts(
                &if_expr.then_branch.stmts,
                ctx,
                guard_facts,
                out,
            );
            *guard_facts = saved_guard_facts;
            if let Some((_, else_expr)) = &if_expr.else_branch {
                collect_guarded_panic_effects_in_expr(else_expr, ctx, guard_facts, out);
            }
        }
        Expr::While(while_expr) => {
            collect_guarded_panic_effects_in_expr(&while_expr.cond, ctx, guard_facts, out);
            invalidate_statement_guard_facts_for_expr_effects(&while_expr.cond, guard_facts);
            let saved_guard_facts = guard_facts.clone();
            collect_guarded_panic_effects_in_stmts(&while_expr.body.stmts, ctx, guard_facts, out);
            *guard_facts = saved_guard_facts;
        }
        Expr::ForLoop(for_loop) => {
            collect_guarded_panic_effects_in_expr(&for_loop.expr, ctx, guard_facts, out);
            invalidate_statement_guard_facts_for_expr_effects(&for_loop.expr, guard_facts);
            let saved_guard_facts = guard_facts.clone();
            ctx.push_frame();
            bind_pat_idents_lift(&for_loop.pat, ctx);
            guard_facts.resolved.extend(keyset_guard_facts_for_for_loop(
                for_loop,
                ctx,
                &saved_guard_facts.keyset_snapshots,
            ));
            collect_guarded_panic_effects_in_stmts(&for_loop.body.stmts, ctx, guard_facts, out);
            ctx.pop_frame();
            *guard_facts = saved_guard_facts;
        }
        Expr::Block(block) => {
            collect_guarded_panic_effects_in_stmts(&block.block.stmts, ctx, guard_facts, out);
        }
        Expr::Unsafe(unsafe_expr) => {
            collect_guarded_panic_effects_in_stmts(&unsafe_expr.block.stmts, ctx, guard_facts, out);
        }
        Expr::TryBlock(try_block) => {
            collect_guarded_panic_effects_in_stmts(&try_block.block.stmts, ctx, guard_facts, out);
        }
        Expr::Assign(assign) => {
            collect_guarded_panic_effects_in_child_expr(&assign.left, ctx, guard_facts, out);
            collect_guarded_panic_effects_in_child_expr(&assign.right, ctx, guard_facts, out);
            let roots = statement_expr_assignment_roots(&assign.left);
            invalidate_statement_guard_facts_for_roots(&roots, guard_facts);
        }
        Expr::Binary(binary) => {
            collect_guarded_panic_effects_in_child_expr(&binary.left, ctx, guard_facts, out);
            collect_guarded_panic_effects_in_child_expr(&binary.right, ctx, guard_facts, out);
            if binop_is_assignment_lift(&binary.op) {
                let roots = statement_expr_assignment_roots(&binary.left);
                invalidate_statement_guard_facts_for_roots(&roots, guard_facts);
            }
        }
        Expr::Call(call) => {
            collect_guarded_panic_effects_in_child_expr(&call.func, ctx, guard_facts, out);
            for arg in &call.args {
                collect_guarded_panic_effects_in_child_expr(arg, ctx, guard_facts, out);
            }
        }
        Expr::Match(match_expr) => {
            collect_guarded_panic_effects_in_child_expr(&match_expr.expr, ctx, guard_facts, out);
            let saved_guard_facts = guard_facts.clone();
            for arm in &match_expr.arms {
                let mut arm_guard_facts = saved_guard_facts.clone();
                ctx.push_frame();
                bind_pat_idents_lift(&arm.pat, ctx);
                invalidate_statement_guard_facts_for_pat(&arm.pat, &mut arm_guard_facts);
                if let Some((_, guard)) = &arm.guard {
                    collect_guarded_panic_effects_in_child_expr(
                        guard,
                        ctx,
                        &mut arm_guard_facts,
                        out,
                    );
                }
                collect_guarded_panic_effects_in_expr(&arm.body, ctx, &mut arm_guard_facts, out);
                ctx.pop_frame();
            }
            *guard_facts = saved_guard_facts;
        }
        Expr::MethodCall(method) => {
            if let Some(formula) =
                statement_guarded_panic_effect_for_method(method, ctx, guard_facts)
            {
                out.push(formula);
            }
            collect_guarded_panic_effects_in_child_expr(&method.receiver, ctx, guard_facts, out);
            for arg in &method.args {
                collect_guarded_panic_effects_in_child_expr(arg, ctx, guard_facts, out);
            }
        }
        Expr::Paren(paren) => {
            collect_guarded_panic_effects_in_expr(&paren.expr, ctx, guard_facts, out)
        }
        Expr::Group(group) => {
            collect_guarded_panic_effects_in_expr(&group.expr, ctx, guard_facts, out)
        }
        Expr::Reference(reference) => {
            collect_guarded_panic_effects_in_expr(&reference.expr, ctx, guard_facts, out)
        }
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_guarded_panic_effects_in_child_expr(elem, ctx, guard_facts, out);
            }
        }
        Expr::Array(array) => {
            for elem in &array.elems {
                collect_guarded_panic_effects_in_child_expr(elem, ctx, guard_facts, out);
            }
        }
        Expr::Repeat(repeat) => {
            collect_guarded_panic_effects_in_child_expr(&repeat.expr, ctx, guard_facts, out);
            collect_guarded_panic_effects_in_child_expr(&repeat.len, ctx, guard_facts, out);
        }
        Expr::Range(range) => {
            if let Some(start) = &range.start {
                collect_guarded_panic_effects_in_child_expr(start, ctx, guard_facts, out);
            }
            if let Some(end) = &range.end {
                collect_guarded_panic_effects_in_child_expr(end, ctx, guard_facts, out);
            }
        }
        Expr::Cast(cast) => {
            collect_guarded_panic_effects_in_expr(&cast.expr, ctx, guard_facts, out)
        }
        Expr::Field(field) => {
            collect_guarded_panic_effects_in_expr(&field.base, ctx, guard_facts, out)
        }
        Expr::Index(index) => {
            collect_guarded_panic_effects_in_child_expr(&index.expr, ctx, guard_facts, out);
            collect_guarded_panic_effects_in_child_expr(&index.index, ctx, guard_facts, out);
        }
        Expr::Await(await_expr) => match await_expr.base.as_ref() {
            Expr::Async(async_expr) => {
                collect_guarded_panic_effects_in_stmts(
                    &async_expr.block.stmts,
                    ctx,
                    guard_facts,
                    out,
                );
            }
            base => collect_guarded_panic_effects_in_child_expr(base, ctx, guard_facts, out),
        },
        Expr::Break(break_expr) => {
            if let Some(expr) = &break_expr.expr {
                collect_guarded_panic_effects_in_child_expr(expr, ctx, guard_facts, out);
            }
        }
        Expr::Const(const_expr) => {
            collect_guarded_panic_effects_in_stmts(&const_expr.block.stmts, ctx, guard_facts, out);
        }
        Expr::Let(let_expr) => {
            collect_guarded_panic_effects_in_child_expr(&let_expr.expr, ctx, guard_facts, out);
            invalidate_statement_guard_facts_for_pat(&let_expr.pat, guard_facts);
        }
        Expr::RawAddr(raw_addr) => {
            collect_guarded_panic_effects_in_expr(&raw_addr.expr, ctx, guard_facts, out)
        }
        Expr::Return(return_expr) => {
            if let Some(expr) = &return_expr.expr {
                collect_guarded_panic_effects_in_child_expr(expr, ctx, guard_facts, out);
            }
        }
        Expr::Struct(struct_expr) => {
            for field in &struct_expr.fields {
                collect_guarded_panic_effects_in_child_expr(&field.expr, ctx, guard_facts, out);
            }
            if let Some(rest) = &struct_expr.rest {
                collect_guarded_panic_effects_in_child_expr(rest, ctx, guard_facts, out);
            }
        }
        Expr::Try(try_expr) => {
            collect_guarded_panic_effects_in_child_expr(&try_expr.expr, ctx, guard_facts, out);
        }
        Expr::Unary(unary) => {
            collect_guarded_panic_effects_in_expr(&unary.expr, ctx, guard_facts, out)
        }
        Expr::Yield(yield_expr) => {
            if let Some(expr) = &yield_expr.expr {
                collect_guarded_panic_effects_in_child_expr(expr, ctx, guard_facts, out);
            }
        }
        // Closure and async block bodies are delayed work, not immediate effects
        // of evaluating the expression that creates them. Expression macros are
        // opaque to this unwrap/expect guard collector; if they expand to
        // panics, the precondition panic collector owns those explicit patterns.
        Expr::Async(_)
        | Expr::Closure(_)
        | Expr::Continue(_)
        | Expr::Infer(_)
        | Expr::Lit(_)
        | Expr::Macro(_)
        | Expr::Path(_) => {}
        Expr::Verbatim(_) => {
            panic!("sugar-walk guarded panic collector refused uninterpreted verbatim expression")
        }
        _ => panic!("sugar-walk guarded panic collector refused unknown syn::Expr variant"),
    }
}

fn collect_guarded_panic_effects_in_child_expr(
    expr: &Expr,
    ctx: &mut LiftCtx,
    guard_facts: &mut StatementGuardFacts,
    out: &mut Vec<IrFormula>,
) {
    collect_guarded_panic_effects_in_expr(expr, ctx, guard_facts, out);
    invalidate_statement_guard_facts_for_expr_effects(expr, guard_facts);
}

fn collect_statement_pure_free_guard_facts(
    expr: &Expr,
    ctx: &mut LiftCtx,
    facts: &mut Vec<StatementPureFreeGuardFact>,
) {
    match expr {
        Expr::Binary(binary) if matches!(binary.op, BinOp::And(_)) => {
            collect_statement_pure_free_guard_facts(&binary.left, ctx, facts);
            collect_statement_pure_free_guard_facts(&binary.right, ctx, facts);
        }
        Expr::MethodCall(method) => {
            if let Some(fact) = statement_pure_free_guard_fact_for_is_some(method, ctx) {
                facts.push(fact);
            }
        }
        Expr::Paren(paren) => collect_statement_pure_free_guard_facts(&paren.expr, ctx, facts),
        Expr::Group(group) => collect_statement_pure_free_guard_facts(&group.expr, ctx, facts),
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::Field(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Index(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::Path(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Reference(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::While(_)
        | Expr::Yield(_) => {}
        Expr::Verbatim(_) => {
            panic!("sugar-walk pure-free guard collector refused uninterpreted verbatim expression")
        }
        other => {
            let _ = other;
            panic!("sugar-walk pure-free guard collector refused unknown syn::Expr variant")
        }
    }
}

fn statement_pure_free_guard_fact_for_is_some(
    node: &syn::ExprMethodCall,
    ctx: &mut LiftCtx,
) -> Option<StatementPureFreeGuardFact> {
    if node.method != panic_freedom::IS_SOME || !node.args.is_empty() {
        return None;
    }
    let call = expr_as_call_lift(&node.receiver)?;
    let callee = call_callee_name(call)?;
    let call_line = call.func.span().start().line;
    let rule = ctx.pure_free_guard_rules.iter().find(|rule| {
        rule.callee == callee
            && rule.post_predicate == panic_freedom::IS_SOME
            && match rule.source_line {
                Some(line) => line == call_line,
                None => rule.allow_line_less_match,
            }
    })?;
    let args = call.args.iter().cloned().collect::<Vec<_>>();
    if !args.iter().all(pure_free_guard_arg_is_stable) {
        debug!(
            callee = %callee,
            line = call_line,
            "lift_function_postcondition: refusing manifest pure-free guard fact because an arg expression is not stable"
        );
        return None;
    }
    debug!(
        callee = %callee,
        line = call_line,
        args = args.len(),
        "lift_function_postcondition: accepted manifest pure-free statement guard fact"
    );
    Some(StatementPureFreeGuardFact {
        callee: rule.callee.clone(),
        args: args.clone(),
        arg_roots: expr_roots_for_lift_args(&args),
        post_predicate: rule.post_predicate.clone(),
    })
}

fn statement_guarded_panic_effect_for_method(
    method: &syn::ExprMethodCall,
    ctx: &mut LiftCtx,
    guard_facts: &StatementGuardFacts,
) -> Option<IrFormula> {
    let panic_leaf = method.method.to_string();
    let valid_panic_call = match panic_leaf.as_str() {
        "unwrap" => method.args.is_empty(),
        "expect" => true,
        _ => false,
    };
    if !valid_panic_call {
        return None;
    }
    if let Some(formula) =
        resolved_statement_guarded_panic_effect_for_method(method, ctx, guard_facts)
    {
        return Some(formula);
    }
    let call = expr_as_call_lift(&method.receiver)?;
    let callee = call_callee_name(call)?;
    let args = call.args.iter().cloned().collect::<Vec<_>>();
    if !args.iter().all(pure_free_guard_arg_is_stable) {
        debug!(
            callee = %callee,
            method = %panic_leaf,
            "lift_function_postcondition: refusing pure-free statement panic carrier because receiver args are not stable"
        );
        return None;
    }
    let fact = guard_facts
        .pure_free
        .iter()
        .rev()
        .find(|fact| fact.callee == callee && expr_vecs_ast_equal_lift(&fact.args, &args))?;
    let receiver = lift_expr_to_term_inner(&method.receiver, ctx)?;
    let mut method_args = vec![receiver.clone()];
    for arg in &method.args {
        method_args.push(lift_expr_to_term_inner(arg, ctx)?);
    }
    let value = IrTerm::Ctor {
        name: format!("method:{}", method.method),
        args: method_args,
    };
    let guarded = guarded_value_from_formula(
        IrFormula::Atomic {
            name: fact.post_predicate.clone(),
            args: vec![receiver],
        },
        value,
    );
    debug!(
        callee = %callee,
        method = %panic_leaf,
        "lift_function_postcondition: emitting content-bearing guarded panic-effect carrier"
    );
    Some(IrFormula::Atomic {
        name: "panic_effect".to_string(),
        args: vec![guarded],
    })
}

fn resolved_statement_guarded_panic_effect_for_method(
    method: &syn::ExprMethodCall,
    ctx: &mut LiftCtx,
    guard_facts: &StatementGuardFacts,
) -> Option<IrFormula> {
    let receiver = lift_expr_to_term_inner(&method.receiver, ctx)?;
    let receiver_key = term_key(&receiver)?;
    let fact = guard_facts
        .resolved
        .iter()
        .rev()
        .find(|fact| fact.receiver_key == receiver_key)?;
    let mut method_args = vec![receiver];
    for arg in &method.args {
        method_args.push(lift_expr_to_term_inner(arg, ctx)?);
    }
    let value = IrTerm::Ctor {
        name: format!("method:{}", method.method),
        args: method_args,
    };
    let guarded = guarded_value_from_formula(fact.guard.clone(), value);
    debug!(
        method = %method.method,
        "lift_function_postcondition: emitting resolved guarded panic-effect carrier"
    );
    Some(IrFormula::Atomic {
        name: "panic_effect".to_string(),
        args: vec![guarded],
    })
}

fn keyset_snapshot_for_local(
    local: &Local,
    ctx: &mut LiftCtx,
) -> Option<(String, KeysetMapSource)> {
    let root = local_pat_single_ident(&local.pat)?;
    let init = &local.init.as_ref()?.expr;
    let collect = expr_as_method_call_lift(init)?;
    let typed_as_btreeset = pat_type_mentions_ident(&local.pat, "BTreeSet")
        || method_turbofish_mentions_ident(collect, "BTreeSet");
    if !typed_as_btreeset {
        return None;
    }
    let mut source = keyset_source_from_keys_collect(init, ctx)?;
    source.roots.insert(root.clone());
    Some((root, source))
}

fn keyset_source_from_keys_collect(expr: &Expr, ctx: &mut LiftCtx) -> Option<KeysetMapSource> {
    let collect = expr_as_method_call_lift(expr)?;
    if collect.method != "collect" || !collect.args.is_empty() {
        return None;
    }
    let keys_receiver = match expr_as_method_call_lift(&collect.receiver) {
        Some(cloned) if cloned.method == "cloned" && cloned.args.is_empty() => &cloned.receiver,
        _ => &collect.receiver,
    };
    let keys = expr_as_method_call_lift(keys_receiver)?;
    if keys.method != "keys" || !keys.args.is_empty() {
        return None;
    }
    keyset_source_from_map_expr(&keys.receiver, ctx)
}

fn keyset_guard_facts_for_for_loop(
    for_loop: &syn::ExprForLoop,
    ctx: &mut LiftCtx,
    snapshots: &BTreeMap<String, KeysetMapSource>,
) -> Vec<StatementResolvedGuardFact> {
    keyset_guard_facts_for_iterable(&for_loop.expr, &for_loop.pat, ctx, snapshots)
}

fn keyset_guard_facts_for_iterable(
    iterable: &Expr,
    pat: &Pat,
    ctx: &mut LiftCtx,
    snapshots: &BTreeMap<String, KeysetMapSource>,
) -> Vec<StatementResolvedGuardFact> {
    if let Some(method) = expr_as_method_call_lift(iterable) {
        let name = method.method.to_string();
        match name.as_str() {
            "keys" if method.args.is_empty() => {
                return keyset_direct_key_guard_facts(
                    pat,
                    &[keyset_source_from_map_expr(&method.receiver, ctx)],
                    ctx,
                );
            }
            "iter" if method.args.is_empty() => {
                if let Some(snapshot) = keyset_snapshot_source_for_expr(&method.receiver, snapshots)
                {
                    return keyset_direct_key_guard_facts(pat, &[Some(snapshot)], ctx);
                }
                return keyset_tuple_key_guard_facts(
                    pat,
                    &[keyset_source_from_map_expr(&method.receiver, ctx)],
                    ctx,
                );
            }
            "difference" if method.args.len() == 1 => {
                let Some(right_arg) = method.args.first() else {
                    return Vec::new();
                };
                let left = keyset_snapshot_source_for_expr(&method.receiver, snapshots);
                let right = keyset_snapshot_source_for_expr(right_arg, snapshots);
                if left.is_some() && right.is_some() {
                    return keyset_direct_key_guard_facts(pat, &[left], ctx);
                }
                return Vec::new();
            }
            "intersection" if method.args.len() == 1 => {
                let Some(right_arg) = method.args.first() else {
                    return Vec::new();
                };
                let left = keyset_snapshot_source_for_expr(&method.receiver, snapshots);
                let right = keyset_snapshot_source_for_expr(right_arg, snapshots);
                if left.is_some() && right.is_some() {
                    return keyset_direct_key_guard_facts(pat, &[left, right], ctx);
                }
                return Vec::new();
            }
            _ => return Vec::new(),
        }
    }

    if let Some(source) = keyset_source_from_borrowed_map_expr(iterable, ctx) {
        return keyset_tuple_key_guard_facts(pat, &[Some(source)], ctx);
    }

    Vec::new()
}

fn keyset_direct_key_guard_facts(
    pat: &Pat,
    sources: &[Option<KeysetMapSource>],
    ctx: &mut LiftCtx,
) -> Vec<StatementResolvedGuardFact> {
    let Some((key_root, key_term)) = direct_key_term_for_pat(pat, ctx) else {
        return Vec::new();
    };
    sources
        .iter()
        .filter_map(|source| {
            keyset_guard_fact_for_source(source.as_ref()?, &key_root, key_term.clone())
        })
        .collect()
}

fn keyset_tuple_key_guard_facts(
    pat: &Pat,
    sources: &[Option<KeysetMapSource>],
    ctx: &mut LiftCtx,
) -> Vec<StatementResolvedGuardFact> {
    let Some((key_root, key_term)) = tuple_key_term_for_pat(pat, ctx) else {
        return Vec::new();
    };
    sources
        .iter()
        .filter_map(|source| {
            keyset_guard_fact_for_source(source.as_ref()?, &key_root, key_term.clone())
        })
        .collect()
}

fn keyset_guard_fact_for_source(
    source: &KeysetMapSource,
    key_root: &str,
    key_term: IrTerm,
) -> Option<StatementResolvedGuardFact> {
    let receiver = IrTerm::Ctor {
        name: "method:get".to_string(),
        args: vec![source.map_term.clone(), key_term],
    };
    let receiver_key = term_key(&receiver)?;
    let guard = IrFormula::Atomic {
        name: panic_freedom::IS_SOME.to_string(),
        args: vec![receiver],
    };
    let mut roots = source.roots.clone();
    roots.insert(source.map_root.clone());
    roots.insert(key_root.to_string());
    Some(StatementResolvedGuardFact {
        receiver_key,
        guard,
        roots,
    })
}

fn keyset_source_from_map_expr(expr: &Expr, ctx: &mut LiftCtx) -> Option<KeysetMapSource> {
    let map_root = expr_root_ident(expr)?;
    let map_term = lift_expr_to_term_inner(expr, ctx)?;
    let mut roots = expr_roots_for_lift_args(&[expr.clone()]);
    roots.insert(map_root.clone());
    Some(KeysetMapSource {
        map_root,
        map_term,
        roots,
    })
}

fn keyset_source_from_borrowed_map_expr(expr: &Expr, ctx: &mut LiftCtx) -> Option<KeysetMapSource> {
    match expr {
        Expr::Reference(reference) if reference.mutability.is_none() => {
            keyset_source_from_map_expr(&reference.expr, ctx)
        }
        Expr::Paren(paren) => keyset_source_from_borrowed_map_expr(&paren.expr, ctx),
        Expr::Group(group) => keyset_source_from_borrowed_map_expr(&group.expr, ctx),
        Expr::Reference(_) => None,
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::Field(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Index(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::MethodCall(_)
        | Expr::Path(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        Expr::Verbatim(_) => {
            panic!("sugar-walk keyset source classifier refused uninterpreted verbatim expression")
        }
        other => {
            let _ = other;
            panic!("sugar-walk keyset source classifier refused unknown syn::Expr variant")
        }
    }
}

fn keyset_snapshot_source_for_expr(
    expr: &Expr,
    snapshots: &BTreeMap<String, KeysetMapSource>,
) -> Option<KeysetMapSource> {
    let root = expr_root_ident(expr)?;
    snapshots.get(&root).cloned()
}

fn direct_key_term_for_pat(pat: &Pat, ctx: &LiftCtx) -> Option<(String, IrTerm)> {
    let root = pat_single_ident(pat)?;
    Some((root.clone(), crate::wp::var(ctx.resolve(&root))))
}

fn tuple_key_term_for_pat(pat: &Pat, ctx: &LiftCtx) -> Option<(String, IrTerm)> {
    let root = tuple_first_pat_ident(pat)?;
    Some((root.clone(), crate::wp::var(ctx.resolve(&root))))
}

fn local_pat_single_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => Some(ident.ident.to_string()),
        Pat::Ident(_) => None,
        Pat::Paren(paren) => local_pat_single_ident(&paren.pat),
        Pat::Reference(reference) => local_pat_single_ident(&reference.pat),
        Pat::Type(typed) => local_pat_single_ident(&typed.pat),
        Pat::Const(_)
        | Pat::Lit(_)
        | Pat::Macro(_)
        | Pat::Or(_)
        | Pat::Path(_)
        | Pat::Range(_)
        | Pat::Rest(_)
        | Pat::Slice(_)
        | Pat::Struct(_)
        | Pat::Tuple(_)
        | Pat::TupleStruct(_)
        | Pat::Verbatim(_)
        | Pat::Wild(_) => None,
        other => {
            let _ = other;
            panic!("sugar-walk local single-pattern classifier refused unknown syn::Pat variant")
        }
    }
}

fn pat_single_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => Some(ident.ident.to_string()),
        Pat::Ident(_) => None,
        Pat::Paren(paren) => pat_single_ident(&paren.pat),
        Pat::Reference(reference) => pat_single_ident(&reference.pat),
        Pat::Type(typed) => pat_single_ident(&typed.pat),
        Pat::Const(_)
        | Pat::Lit(_)
        | Pat::Macro(_)
        | Pat::Or(_)
        | Pat::Path(_)
        | Pat::Range(_)
        | Pat::Rest(_)
        | Pat::Slice(_)
        | Pat::Struct(_)
        | Pat::Tuple(_)
        | Pat::TupleStruct(_)
        | Pat::Verbatim(_)
        | Pat::Wild(_) => None,
        other => {
            let _ = other;
            panic!("sugar-walk single-pattern classifier refused unknown syn::Pat variant")
        }
    }
}

fn tuple_first_pat_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Tuple(tuple) => tuple.elems.first().and_then(pat_single_ident),
        Pat::Paren(paren) => tuple_first_pat_ident(&paren.pat),
        Pat::Reference(reference) => tuple_first_pat_ident(&reference.pat),
        Pat::Type(typed) => tuple_first_pat_ident(&typed.pat),
        Pat::Const(_)
        | Pat::Ident(_)
        | Pat::Lit(_)
        | Pat::Macro(_)
        | Pat::Or(_)
        | Pat::Path(_)
        | Pat::Range(_)
        | Pat::Rest(_)
        | Pat::Slice(_)
        | Pat::Struct(_)
        | Pat::TupleStruct(_)
        | Pat::Verbatim(_)
        | Pat::Wild(_) => None,
        other => {
            let _ = other;
            panic!("sugar-walk tuple-pattern classifier refused unknown syn::Pat variant")
        }
    }
}

fn pat_type_mentions_ident(pat: &Pat, needle: &str) -> bool {
    match pat {
        Pat::Paren(paren) => pat_type_mentions_ident(&paren.pat, needle),
        Pat::Reference(reference) => pat_type_mentions_ident(&reference.pat, needle),
        Pat::Type(typed) => type_mentions_ident(&typed.ty, needle),
        _ => false,
    }
}

fn type_mentions_ident(ty: &Type, needle: &str) -> bool {
    match ty {
        Type::Path(path) => path.path.segments.iter().any(|segment| {
            segment.ident == needle || path_arguments_mentions_ident(&segment.arguments, needle)
        }),
        Type::Reference(reference) => type_mentions_ident(&reference.elem, needle),
        Type::Group(group) => type_mentions_ident(&group.elem, needle),
        Type::Paren(paren) => type_mentions_ident(&paren.elem, needle),
        Type::Tuple(tuple) => tuple
            .elems
            .iter()
            .any(|elem| type_mentions_ident(elem, needle)),
        _ => false,
    }
}

fn path_arguments_mentions_ident(args: &PathArguments, needle: &str) -> bool {
    match args {
        PathArguments::AngleBracketed(args) => args.args.iter().any(|arg| match arg {
            GenericArgument::Type(ty) => type_mentions_ident(ty, needle),
            _ => false,
        }),
        PathArguments::Parenthesized(args) => {
            args.inputs.iter().any(|ty| type_mentions_ident(ty, needle))
                || matches!(&args.output, ReturnType::Type(_, ty) if type_mentions_ident(ty, needle))
        }
        PathArguments::None => false,
    }
}

fn method_turbofish_mentions_ident(method: &syn::ExprMethodCall, needle: &str) -> bool {
    let Some(args) = method.turbofish.as_ref() else {
        return false;
    };
    args.args.iter().any(|arg| match arg {
        GenericArgument::Type(ty) => type_mentions_ident(ty, needle),
        _ => false,
    })
}

fn expr_as_method_call_lift(expr: &Expr) -> Option<&syn::ExprMethodCall> {
    match expr {
        Expr::MethodCall(method) => Some(method),
        Expr::Paren(paren) => expr_as_method_call_lift(&paren.expr),
        Expr::Group(group) => expr_as_method_call_lift(&group.expr),
        Expr::Reference(reference) if reference.mutability.is_none() => {
            expr_as_method_call_lift(&reference.expr)
        }
        Expr::Reference(_) => None,
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::Field(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Index(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::Path(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        Expr::Verbatim(_) => {
            panic!("sugar-walk method-call classifier refused uninterpreted verbatim expression")
        }
        other => {
            let _ = other;
            panic!("sugar-walk method-call classifier refused unknown syn::Expr variant")
        }
    }
}

fn invalidate_statement_guard_facts_for_expr_effects(
    expr: &Expr,
    guard_facts: &mut StatementGuardFacts,
) {
    let roots = expr_effect_mutation_roots(expr);
    invalidate_statement_guard_facts_for_roots(&roots, guard_facts);
}

fn invalidate_statement_guard_facts_for_roots(
    roots: &BTreeSet<String>,
    guard_facts: &mut StatementGuardFacts,
) {
    if roots.is_empty() {
        return;
    }
    let pure_free_before = guard_facts.pure_free.len();
    guard_facts
        .pure_free
        .retain(|fact| fact.arg_roots.is_disjoint(roots));
    let resolved_before = guard_facts.resolved.len();
    guard_facts
        .resolved
        .retain(|fact| fact.roots.is_disjoint(roots));
    let snapshots_before = guard_facts.keyset_snapshots.len();
    guard_facts
        .keyset_snapshots
        .retain(|_, source| source.roots.is_disjoint(roots));
    let removed = pure_free_before.saturating_sub(guard_facts.pure_free.len())
        + resolved_before.saturating_sub(guard_facts.resolved.len())
        + snapshots_before.saturating_sub(guard_facts.keyset_snapshots.len());
    if removed > 0 {
        debug!(
            roots = ?roots,
            removed,
            "lift_function_postcondition: invalidated statement guard facts"
        );
    }
}

fn invalidate_statement_guard_facts_for_pat(pat: &Pat, guard_facts: &mut StatementGuardFacts) {
    let roots = pat_bound_idents_lift(pat);
    invalidate_statement_guard_facts_for_roots(&roots, guard_facts);
}

fn expr_as_call_lift(expr: &Expr) -> Option<&syn::ExprCall> {
    match expr {
        Expr::Call(call) => Some(call),
        Expr::Paren(paren) => expr_as_call_lift(&paren.expr),
        Expr::Group(group) => expr_as_call_lift(&group.expr),
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::Field(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Index(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::MethodCall(_)
        | Expr::Path(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Reference(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        Expr::Verbatim(_) => {
            panic!("sugar-walk call classifier refused uninterpreted verbatim expression")
        }
        other => {
            let _ = other;
            panic!("sugar-walk call classifier refused unknown syn::Expr variant")
        }
    }
}

fn expr_vecs_ast_equal_lift(left: &[Expr], right: &[Expr]) -> bool {
    left.len() == right.len() && left.iter().zip(right).all(|(left, right)| left == right)
}

pub fn pure_free_guard_arg_is_stable(expr: &Expr) -> bool {
    pure_free_guard_expr_is_pure_read(expr)
}

pub fn pure_free_guard_expr_effect_roots(expr: &Expr) -> BTreeSet<String> {
    expr_effect_mutation_roots(expr)
}

fn pure_free_guard_expr_is_pure_read(expr: &Expr) -> bool {
    match expr {
        Expr::Array(array) => array.elems.iter().all(pure_free_guard_expr_is_pure_read),
        Expr::Binary(binary) => {
            !binop_is_assignment_lift(&binary.op)
                && pure_free_guard_expr_is_pure_read(&binary.left)
                && pure_free_guard_expr_is_pure_read(&binary.right)
        }
        Expr::Cast(cast) => pure_free_guard_expr_is_pure_read(&cast.expr),
        Expr::Field(field) => pure_free_guard_expr_is_pure_read(&field.base),
        Expr::Group(group) => pure_free_guard_expr_is_pure_read(&group.expr),
        Expr::Index(index) => {
            pure_free_guard_expr_is_pure_read(&index.expr)
                && pure_free_guard_expr_is_pure_read(&index.index)
        }
        Expr::Lit(_) | Expr::Path(_) => true,
        Expr::MethodCall(method) => pure_free_guard_method_is_pure_read(method),
        Expr::Paren(paren) => pure_free_guard_expr_is_pure_read(&paren.expr),
        Expr::Reference(reference) => {
            reference.mutability.is_none() && pure_free_guard_expr_is_pure_read(&reference.expr)
        }
        Expr::Tuple(tuple) => tuple.elems.iter().all(pure_free_guard_expr_is_pure_read),
        Expr::Unary(unary) => pure_free_guard_expr_is_pure_read(&unary.expr),
        _ => false,
    }
}

fn pure_free_guard_method_is_pure_read(method: &syn::ExprMethodCall) -> bool {
    let name = method.method.to_string();
    let args_pure = method.args.iter().all(pure_free_guard_expr_is_pure_read);
    let receiver_pure = pure_free_guard_expr_is_pure_read(&method.receiver);
    receiver_pure
        && args_pure
        && match name.as_str() {
            "cloned" | "iter" | "keys" | "len" | "is_empty" | "is_some" | "is_none" => {
                method.args.is_empty()
            }
            "difference" | "intersection" | "union" => method.args.len() == 1,
            "get" => method.args.len() == 1,
            _ => false,
        }
}

fn expr_roots_for_lift_args(args: &[Expr]) -> BTreeSet<String> {
    let mut roots = BTreeSet::new();
    for arg in args {
        collect_expr_roots_lift(arg, &mut roots);
    }
    roots
}

fn collect_expr_roots_lift(expr: &Expr, roots: &mut BTreeSet<String>) {
    match expr {
        Expr::Path(path) if path.path.segments.len() == 1 => {
            if let Some(segment) = path.path.segments.first() {
                roots.insert(segment.ident.to_string());
            }
        }
        Expr::Path(_) => {}
        Expr::Assign(assign) => {
            collect_expr_roots_lift(&assign.left, roots);
            collect_expr_roots_lift(&assign.right, roots);
        }
        Expr::Array(array) => {
            for elem in &array.elems {
                collect_expr_roots_lift(elem, roots);
            }
        }
        Expr::Async(async_expr) => collect_stmt_roots_lift(&async_expr.block.stmts, roots),
        Expr::Await(await_expr) => collect_expr_roots_lift(&await_expr.base, roots),
        Expr::Binary(binary) => {
            collect_expr_roots_lift(&binary.left, roots);
            collect_expr_roots_lift(&binary.right, roots);
        }
        Expr::Block(block) => collect_stmt_roots_lift(&block.block.stmts, roots),
        Expr::Break(break_expr) => {
            if let Some(expr) = &break_expr.expr {
                collect_expr_roots_lift(expr, roots);
            }
        }
        Expr::Call(call) => {
            collect_expr_roots_lift(&call.func, roots);
            for arg in &call.args {
                collect_expr_roots_lift(arg, roots);
            }
        }
        Expr::Cast(cast) => collect_expr_roots_lift(&cast.expr, roots),
        Expr::Closure(closure) => collect_expr_roots_lift(&closure.body, roots),
        Expr::Const(const_expr) => collect_stmt_roots_lift(&const_expr.block.stmts, roots),
        Expr::Field(field) => collect_expr_roots_lift(&field.base, roots),
        Expr::ForLoop(for_loop) => {
            collect_expr_roots_lift(&for_loop.expr, roots);
            collect_stmt_roots_lift(&for_loop.body.stmts, roots);
        }
        Expr::Group(group) => collect_expr_roots_lift(&group.expr, roots),
        Expr::If(if_expr) => {
            collect_expr_roots_lift(&if_expr.cond, roots);
            collect_stmt_roots_lift(&if_expr.then_branch.stmts, roots);
            if let Some((_, else_expr)) = &if_expr.else_branch {
                collect_expr_roots_lift(else_expr, roots);
            }
        }
        Expr::Index(index) => {
            collect_expr_roots_lift(&index.expr, roots);
            collect_expr_roots_lift(&index.index, roots);
        }
        Expr::Let(let_expr) => collect_expr_roots_lift(&let_expr.expr, roots),
        Expr::Loop(loop_expr) => collect_stmt_roots_lift(&loop_expr.body.stmts, roots),
        Expr::Match(match_expr) => {
            collect_expr_roots_lift(&match_expr.expr, roots);
            for arm in &match_expr.arms {
                if let Some((_, guard)) = &arm.guard {
                    collect_expr_roots_lift(guard, roots);
                }
                collect_expr_roots_lift(&arm.body, roots);
            }
        }
        Expr::MethodCall(method) => {
            collect_expr_roots_lift(&method.receiver, roots);
            for arg in &method.args {
                collect_expr_roots_lift(arg, roots);
            }
        }
        Expr::Paren(paren) => collect_expr_roots_lift(&paren.expr, roots),
        Expr::Range(range) => {
            if let Some(start) = &range.start {
                collect_expr_roots_lift(start, roots);
            }
            if let Some(end) = &range.end {
                collect_expr_roots_lift(end, roots);
            }
        }
        Expr::RawAddr(raw_addr) => collect_expr_roots_lift(&raw_addr.expr, roots),
        Expr::Reference(reference) => collect_expr_roots_lift(&reference.expr, roots),
        Expr::Repeat(repeat) => {
            collect_expr_roots_lift(&repeat.expr, roots);
            collect_expr_roots_lift(&repeat.len, roots);
        }
        Expr::Return(return_expr) => {
            if let Some(expr) = &return_expr.expr {
                collect_expr_roots_lift(expr, roots);
            }
        }
        Expr::Struct(struct_expr) => {
            for field in &struct_expr.fields {
                collect_expr_roots_lift(&field.expr, roots);
            }
            if let Some(rest) = &struct_expr.rest {
                collect_expr_roots_lift(rest, roots);
            }
        }
        Expr::Try(try_expr) => collect_expr_roots_lift(&try_expr.expr, roots),
        Expr::TryBlock(try_block) => collect_stmt_roots_lift(&try_block.block.stmts, roots),
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_expr_roots_lift(elem, roots);
            }
        }
        Expr::Unary(unary) => collect_expr_roots_lift(&unary.expr, roots),
        Expr::Unsafe(unsafe_expr) => collect_stmt_roots_lift(&unsafe_expr.block.stmts, roots),
        Expr::While(while_expr) => {
            collect_expr_roots_lift(&while_expr.cond, roots);
            collect_stmt_roots_lift(&while_expr.body.stmts, roots);
        }
        Expr::Yield(yield_expr) => {
            if let Some(expr) = &yield_expr.expr {
                collect_expr_roots_lift(expr, roots);
            }
        }
        Expr::Continue(_) | Expr::Infer(_) | Expr::Lit(_) => {}
        Expr::Macro(_) | Expr::Verbatim(_) => {
            panic!("sugar-walk expression root collector refused opaque syn::Expr variant")
        }
        other => {
            let _ = other;
            panic!("sugar-walk expression root collector refused unknown syn::Expr variant")
        }
    }
}

fn collect_stmt_roots_lift(stmts: &[Stmt], roots: &mut BTreeSet<String>) {
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => {
                if let Some(init) = &local.init {
                    collect_expr_roots_lift(&init.expr, roots);
                }
            }
            Stmt::Expr(expr, _) => collect_expr_roots_lift(expr, roots),
            Stmt::Item(_) => {}
            Stmt::Macro(_) => {
                panic!("sugar-walk expression root collector refused opaque statement macro")
            }
        }
    }
}

fn expr_effect_mutation_roots(expr: &Expr) -> BTreeSet<String> {
    let mut roots = BTreeSet::new();
    collect_expr_effect_mutation_roots(expr, &mut roots);
    roots
}

struct ExprEffectMutationRootCollector<'a> {
    roots: &'a mut BTreeSet<String>,
}

impl<'ast> Visit<'ast> for ExprEffectMutationRootCollector<'_> {
    fn visit_expr_assign(&mut self, node: &'ast syn::ExprAssign) {
        collect_assignment_roots_lift(&node.left, self.roots);
        visit::visit_expr_assign(self, node);
    }

    fn visit_expr_binary(&mut self, node: &'ast syn::ExprBinary) {
        if binop_is_assignment_lift(&node.op) {
            collect_assignment_roots_lift(&node.left, self.roots);
        }
        visit::visit_expr_binary(self, node);
    }

    fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
        if !pure_free_guard_method_is_pure_read(node)
            && !matches!(
                node.method.to_string().as_str(),
                "unwrap" | "expect" | "unwrap_err"
            )
        {
            if let Some(root) = expr_root_ident(&node.receiver) {
                self.roots.insert(root);
            }
        }
        visit::visit_expr_method_call(self, node);
    }

    fn visit_expr_reference(&mut self, node: &'ast syn::ExprReference) {
        if node.mutability.is_some() {
            if let Some(root) = expr_root_ident(&node.expr) {
                self.roots.insert(root);
            }
        }
        visit::visit_expr_reference(self, node);
    }
}

fn collect_expr_effect_mutation_roots(expr: &Expr, roots: &mut BTreeSet<String>) {
    ExprEffectMutationRootCollector { roots }.visit_expr(expr);
}

fn statement_expr_assignment_roots(expr: &Expr) -> BTreeSet<String> {
    let mut roots = BTreeSet::new();
    collect_assignment_roots_lift(expr, &mut roots);
    roots
}

fn collect_assignment_roots_lift(expr: &Expr, roots: &mut BTreeSet<String>) {
    match expr {
        Expr::Path(path) if path.path.segments.len() == 1 => {
            if let Some(segment) = path.path.segments.first() {
                roots.insert(segment.ident.to_string());
            }
        }
        Expr::Path(_) => {}
        Expr::Field(field) => collect_assignment_roots_lift(&field.base, roots),
        Expr::Group(group) => collect_assignment_roots_lift(&group.expr, roots),
        Expr::Index(index) => collect_assignment_roots_lift(&index.expr, roots),
        Expr::Paren(paren) => collect_assignment_roots_lift(&paren.expr, roots),
        Expr::Reference(reference) => collect_assignment_roots_lift(&reference.expr, roots),
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_assignment_roots_lift(elem, roots);
            }
        }
        Expr::Unary(unary) if matches!(unary.op, syn::UnOp::Deref(_)) => {
            collect_assignment_roots_lift(&unary.expr, roots)
        }
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::MethodCall(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::While(_)
        | Expr::Yield(_) => {}
        Expr::Verbatim(_) => {
            panic!("sugar-walk assignment root collector refused uninterpreted verbatim expression")
        }
        other => {
            let _ = other;
            panic!("sugar-walk assignment root collector refused unknown syn::Expr variant")
        }
    }
}

fn binop_is_assignment_lift(op: &BinOp) -> bool {
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

fn pat_bound_idents_lift(pat: &Pat) -> BTreeSet<String> {
    let mut roots = BTreeSet::new();
    collect_pat_bound_idents_lift(pat, &mut roots);
    roots
}

fn collect_pat_bound_idents_lift(pat: &Pat, roots: &mut BTreeSet<String>) {
    match pat {
        Pat::Ident(ident) => {
            roots.insert(ident.ident.to_string());
            if let Some((_, subpat)) = &ident.subpat {
                collect_pat_bound_idents_lift(subpat, roots);
            }
        }
        Pat::Or(or) => {
            for case in &or.cases {
                collect_pat_bound_idents_lift(case, roots);
            }
        }
        Pat::Paren(paren) => collect_pat_bound_idents_lift(&paren.pat, roots),
        Pat::Reference(reference) => collect_pat_bound_idents_lift(&reference.pat, roots),
        Pat::Slice(slice) => {
            for elem in &slice.elems {
                collect_pat_bound_idents_lift(elem, roots);
            }
        }
        Pat::Struct(strukt) => {
            for field in &strukt.fields {
                collect_pat_bound_idents_lift(&field.pat, roots);
            }
        }
        Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_pat_bound_idents_lift(elem, roots);
            }
        }
        Pat::TupleStruct(tuple) => {
            for elem in &tuple.elems {
                collect_pat_bound_idents_lift(elem, roots);
            }
        }
        Pat::Type(typed) => collect_pat_bound_idents_lift(&typed.pat, roots),
        Pat::Const(_)
        | Pat::Lit(_)
        | Pat::Path(_)
        | Pat::Range(_)
        | Pat::Rest(_)
        | Pat::Wild(_) => {}
        Pat::Macro(_) | Pat::Verbatim(_) => {
            panic!("sugar-walk pattern binding collector refused opaque syn::Pat variant")
        }
        other => {
            let _ = other;
            panic!("sugar-walk pattern binding collector refused unknown syn::Pat variant")
        }
    }
}

fn bind_pat_idents_lift(pat: &Pat, ctx: &mut LiftCtx) {
    match pat {
        Pat::Ident(ident) => {
            ctx.bind(&ident.ident.to_string());
            if let Some((_, subpat)) = &ident.subpat {
                bind_pat_idents_lift(subpat, ctx);
            }
        }
        Pat::Or(or) => {
            for case in &or.cases {
                bind_pat_idents_lift(case, ctx);
            }
        }
        Pat::Paren(paren) => bind_pat_idents_lift(&paren.pat, ctx),
        Pat::Reference(reference) => bind_pat_idents_lift(&reference.pat, ctx),
        Pat::Slice(slice) => {
            for elem in &slice.elems {
                bind_pat_idents_lift(elem, ctx);
            }
        }
        Pat::Struct(strukt) => {
            for field in &strukt.fields {
                bind_pat_idents_lift(&field.pat, ctx);
            }
        }
        Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                bind_pat_idents_lift(elem, ctx);
            }
        }
        Pat::TupleStruct(tuple) => {
            for elem in &tuple.elems {
                bind_pat_idents_lift(elem, ctx);
            }
        }
        Pat::Type(typed) => bind_pat_idents_lift(&typed.pat, ctx),
        Pat::Const(_)
        | Pat::Lit(_)
        | Pat::Path(_)
        | Pat::Range(_)
        | Pat::Rest(_)
        | Pat::Wild(_) => {}
        Pat::Macro(_) | Pat::Verbatim(_) => {
            panic!("sugar-walk pattern binder refused opaque syn::Pat variant")
        }
        other => {
            let _ = other;
            panic!("sugar-walk pattern binder refused unknown syn::Pat variant")
        }
    }
}

/// If a statement is an explicit `return <expr>;`, derive
/// `result = <lifted expr>`. Returns None for other statement kinds. `prefix`
/// is the run of statements before this one, whose leading `let`s are
/// re-attached to the result term (so `let n = x; return n*2;` does not leak the
/// local `n`, exactly as the trailing-expression form does not).
fn lift_return_stmt_postcondition(
    prefix: &[Stmt],
    stmt: &Stmt,
    ctx: &mut LiftCtx,
) -> Option<IrFormula> {
    let expr = match stmt {
        Stmt::Expr(e, Some(_)) => e, // Expr with trailing semicolon
        _ => return None,
    };
    if let Expr::Return(ret) = expr {
        if let Some(inner) = &ret.expr {
            if let Some(term) = lift_expr_to_term_inner(inner, ctx) {
                let term = wrap_leading_lets(prefix, term, ctx);
                let result_var = IrTerm::Var {
                    name: "result".to_string(),
                };
                return Some(IrFormula::Atomic {
                    name: "=".to_string(),
                    args: vec![result_var, term],
                });
            }
        }
    }
    None
}

/// What does this single statement contribute to the function's
/// implicit precondition? Returns None for statements that don't lift
/// (let-bindings, plain expressions, etc.).
fn lift_stmt_contribution(stmt: &Stmt, ctx: &mut LiftCtx) -> Option<IrFormula> {
    match stmt {
        Stmt::Expr(e, _) => lift_expr_contribution(e, ctx),
        // `assert!(c);` at statement position parses to Stmt::Macro
        // (with optional trailing semicolon), not Stmt::Expr(Expr::Macro).
        Stmt::Macro(StmtMacro { mac, .. }) => lift_macro_contribution(mac, ctx),
        Stmt::Item(_) | Stmt::Local(_) => None,
    }
}

/// Recognize and lift macro contributions at statement or expression
/// position. Used by both `Stmt::Macro` and `Expr::Macro` paths.
fn lift_macro_contribution(mac: &Macro, ctx: &mut LiftCtx) -> Option<IrFormula> {
    let seg = mac.path.segments.last()?;
    let name = seg.ident.to_string();
    match name.as_str() {
        "assert" => {
            let first = assert_macro_condition(mac)?;
            lift_predicate_inner(&first, ctx)
        }
        // debug_assert! is compiled out in release builds. Lifting its
        // predicate as a real contract would misrepresent what holds in
        // release mode. Skip it entirely.
        "debug_assert" | "debug_assert_eq" | "debug_assert_ne" => None,
        other => {
            // sugar-audit: not-mine(only assert! contributes a checked precondition)
            let _ = other;
            None
        }
    }
}

fn lift_expr_contribution(expr: &Expr, ctx: &mut LiftCtx) -> Option<IrFormula> {
    // if-then-panic pattern: `if cond { panic!() }` lifts to ¬cond.
    if let Expr::If(ExprIf {
        cond,
        then_branch,
        else_branch,
        ..
    }) = expr
    {
        if else_branch.is_none() && block_only_panics(then_branch) {
            let cond_formula = lift_predicate_inner(cond, ctx)?;
            return Some(negate(cond_formula));
        }
    }
    // assert!()-shaped macros sometimes parse as Expr::Macro (e.g. when
    // they're the trailing tail expression of a block).
    if let Expr::Macro(ExprMacro { mac, .. }) = expr {
        if let Some(formula) = lift_macro_contribution(mac, ctx) {
            return Some(formula);
        }
    }
    None
}

/// Lift an arbitrary Rust predicate-shaped expression to `IrFormula`.
/// Returns None for shapes the MVP does not yet handle.
pub fn lift_predicate(expr: &Expr) -> Option<IrFormula> {
    let mut ctx = LiftCtx::new();
    lift_predicate_inner(expr, &mut ctx)
}

fn lift_predicate_inner(expr: &Expr, ctx: &mut LiftCtx) -> Option<IrFormula> {
    lift_predicate_value_inner(expr, ctx).map(predicate_value_to_ir_formula)
}

/// Predicate-position boundary seam. A bool-sorted `IrTerm` is data; a
/// `PredicateValue` is an assertion-position formula. Python carries this as
/// `floor/predicate_value.py` beside `floor/bool_value.py`; Rust routes the
/// same distinction through the shared closed visitor and converts only at the
/// `IrTerm` boundary.
fn require_predicate_value_floor(floor: Desugared, owner: &str) -> PredicateValue {
    floor.accept_predicate_value_floor(RequiredPredicateValueVisitor { owner })
}

fn predicate_value_from_ir_formula(formula: IrFormula) -> PredicateValue {
    require_predicate_value_floor(
        Desugared::PredicateValue(PredicateValue::new(lower_ir_formula(&formula))),
        "sugar-walk.predicate",
    )
}

fn predicate_value_to_ir_formula(predicate: PredicateValue) -> IrFormula {
    raise_ir_formula(predicate.formula())
}

fn lift_predicate_value_inner(expr: &Expr, ctx: &mut LiftCtx) -> Option<PredicateValue> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: Lit::Bool(value),
            ..
        }) => Some(predicate_value_from_ir_formula(bool_term_predicate(
            bool_const_term(value.value),
        ))),
        Expr::Binary(ExprBinary {
            left, op, right, ..
        }) => match op {
            BinOp::And(_) => {
                let l = predicate_value_to_ir_formula(lift_predicate_value_inner(left, ctx)?);
                let r = predicate_value_to_ir_formula(lift_predicate_value_inner(right, ctx)?);
                Some(predicate_value_from_ir_formula(IrFormula::And {
                    operands: vec![l, r],
                }))
            }
            BinOp::Or(_) => {
                let l = predicate_value_to_ir_formula(lift_predicate_value_inner(left, ctx)?);
                let r = predicate_value_to_ir_formula(lift_predicate_value_inner(right, ctx)?);
                Some(predicate_value_from_ir_formula(IrFormula::Or {
                    operands: vec![l, r],
                }))
            }
            _ => {
                // Comparison: lift both sides as terms, pick the IR predicate name.
                let name = bin_op_to_predicate_name(op)?;
                let l_term = lift_expr_to_term_inner(left, ctx)?;
                let r_term = lift_expr_to_term_inner(right, ctx)?;
                Some(predicate_value_from_ir_formula(IrFormula::Atomic {
                    name: name.to_string(),
                    args: vec![l_term, r_term],
                }))
            }
        },
        Expr::Unary(ExprUnary {
            op: UnOp::Not(_),
            expr,
            ..
        }) => {
            let inner = predicate_value_to_ir_formula(lift_predicate_value_inner(expr, ctx)?);
            // Apply De Morgan / double-negation via the negate helper,
            // so `!(x >= 10)` lifts to `x < 10`, not `¬(x ≥ 10)`.
            Some(predicate_value_from_ir_formula(negate(inner)))
        }
        Expr::Paren(p) => lift_predicate_value_inner(&p.expr, ctx),
        Expr::Group(g) => lift_predicate_value_inner(&g.expr, ctx),
        // Zero-argument method calls that return bool: `.is_some()`, `.is_none()`,
        // `.is_empty()`, `.is_err()`, `.is_ok()`. These are common predicate shapes
        // in Rust and appear naturally in source-level defensive guards.
        // Each lifts to `IrFormula::Atomic { name: "is_some" (or similar), args: [recv] }`.
        Expr::MethodCall(syn::ExprMethodCall {
            receiver,
            method,
            args,
            ..
        }) if args.is_empty() => {
            let method_name = method.to_string();
            let is_bool_predicate = matches!(
                method_name.as_str(),
                panic_freedom::IS_SOME
                    | panic_freedom::IS_NONE
                    | "is_empty"
                    | panic_freedom::IS_ERR
                    | panic_freedom::IS_OK
            );
            if is_bool_predicate {
                let recv_term = lift_expr_to_term_inner(receiver, ctx)?;
                Some(predicate_value_from_ir_formula(IrFormula::Atomic {
                    name: method_name,
                    args: vec![recv_term],
                }))
            } else {
                None
            }
        }
        Expr::Path(_)
        | Expr::Field(_)
        | Expr::Index(_)
        | Expr::Call(_)
        | Expr::MethodCall(_)
        | Expr::Block(_)
        | Expr::If(_)
        | Expr::Match(_)
        | Expr::Try(_)
        | Expr::Macro(_)
        | Expr::Reference(_)
        | Expr::Cast(_)
        | Expr::Unsafe(_)
        | Expr::Const(_) => lift_bool_term_predicate_value(expr, ctx),
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Break(_)
        | Expr::Closure(_)
        | Expr::Continue(_)
        | Expr::ForLoop(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Verbatim(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        Expr::Unary(_) => None,
        _ => panic!("sugar-walk predicate classifier refused unknown syn::Expr variant"),
    }
}

fn bool_const_term(value: bool) -> IrTerm {
    IrTerm::Const {
        value: serde_json::Value::Bool(value),
        sort: sugar_ir_types::Sort::Primitive {
            name: "Bool".to_string(),
        },
    }
}

fn bool_term_predicate(term: IrTerm) -> IrFormula {
    IrFormula::Atomic {
        name: "=".to_string(),
        args: vec![term, bool_const_term(true)],
    }
}

fn lift_bool_term_predicate(expr: &Expr, ctx: &mut LiftCtx) -> Option<IrFormula> {
    lift_expr_to_term_inner(expr, ctx).map(bool_term_predicate)
}

fn lift_bool_term_predicate_value(expr: &Expr, ctx: &mut LiftCtx) -> Option<PredicateValue> {
    lift_bool_term_predicate(expr, ctx).map(predicate_value_from_ir_formula)
}

/// Lift a Rust expression to a canonical `IrTerm`. Supported shapes:
///   - Integer literal: `IrTerm::Const { value: <num>, sort: Int }`.
///   - Bool literal: `IrTerm::Const { value: <bool>, sort: Bool }`.
///   - Bare identifier: `IrTerm::Var { name: <ident> }`.
///   - Parenthesized expression: recurses on the inner expression.
///   - Reference (`&x`, `&mut x`): unwraps; for substrate purposes
///     a borrow is the value's identity (substitution-equivalent).
///   - Cast (`x as u32`): unwraps to the inner term (the IR's Sort
///     captures type changes; the term-level lift ignores casts).
///   - Field access (`s.f`): `Ctor("field", [s_term, "f"])`.
///   - Index (`a[i]`): `Ctor("index", [a_term, i_term])`.
///   - Method call (`x.foo(args)`): `Ctor("method:foo", [x, ...args])`.
///   - Range (`a..b`, `a..=b`): `Ctor("range", [a, b])` /
///     `Ctor("range_incl", [a, b])`.
///   - Tuple (`(a, b, c)`): `Ctor("tuple", [a, b, c])`.
///   - Unary negation (`-x`), bitwise not (`!x` on integers):
///     `Ctor("neg" / "bit-not", [...])`.
///   - Binary arithmetic (`+`, `-`, `*`, `/`, `%`, `&`, `|`, `^`,
///     `<<`, `>>`): lifts to `Ctor(<op>, [lhs, rhs])`.
///
/// Anything else returns None.
pub fn lift_expr_to_term(expr: &Expr) -> Option<IrTerm> {
    let mut ctx = LiftCtx::new();
    lift_expr_to_term_inner(expr, &mut ctx)
}

pub fn collect_panic_loci_json(item_fn: &ItemFn, rel_path: &str) -> Vec<serde_json::Value> {
    struct PanicLocusVisitor {
        rel_path: String,
        ctx: LiftCtx,
        out: Vec<serde_json::Value>,
    }

    impl<'ast> Visit<'ast> for PanicLocusVisitor {
        fn visit_expr_for_loop(&mut self, node: &'ast syn::ExprForLoop) {
            self.visit_expr(&node.expr);
            self.ctx.push_frame();
            bind_pat_idents_lift(&node.pat, &mut self.ctx);
            self.visit_block(&node.body);
            self.ctx.pop_frame();
        }

        fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
            let leaf = node.method.to_string();
            if is_panic_leaf_method_lift(&leaf) {
                let mut occurrence_ctx = self.ctx.clone();
                if let Some(recv) = lift_expr_to_term_inner(&node.receiver, &mut occurrence_ctx) {
                    if let Ok(arg_term) = serde_json::to_value(&recv) {
                        let receiver_start = node.receiver.span().start();
                        let panic_start = node.method.span().start();
                        let mut locus = serde_json::json!({
                            "argTerm": arg_term,
                            "file": self.rel_path,
                            "line": panic_start.line,
                            "col": panic_start.column,
                            "receiverLine": receiver_start.line,
                            "receiverCol": receiver_start.column,
                            "panicLine": panic_start.line,
                            "panicCol": panic_start.column,
                            "callee": format!("method:{}", leaf),
                        });
                        if let Some((producer_symbol, producer_line, producer_col)) =
                            receiver_producer_callsite_lift(&node.receiver)
                        {
                            locus["producerSymbol"] = serde_json::json!(producer_symbol);
                            locus["producerLine"] = serde_json::json!(producer_line);
                            locus["producerCol"] = serde_json::json!(producer_col);
                        }
                        self.out.push(locus);
                    }
                }
            }
            visit::visit_expr_method_call(self, node);
        }
    }

    let mut visitor = PanicLocusVisitor {
        rel_path: rel_path.to_string(),
        ctx: LiftCtx::new(),
        out: Vec::new(),
    };
    visitor.visit_item_fn(item_fn);
    visitor.out
}

fn is_panic_leaf_method_lift(leaf: &str) -> bool {
    matches!(leaf, "unwrap" | "expect" | "unwrap_err")
}

fn receiver_producer_callsite_lift(receiver: &Expr) -> Option<(String, usize, usize)> {
    if let Expr::MethodCall(method) = receiver {
        let start = method.method.span().start();
        return Some((
            format!("method:{}", method.method),
            start.line,
            start.column,
        ));
    }
    if let Expr::Call(call) = receiver {
        let callee = associated_call_path_leaf_lift(&call.func)?;
        let start = call.func.span().start();
        return Some((callee, start.line, start.column));
    }
    if let Expr::Paren(paren) = receiver {
        return receiver_producer_callsite_lift(&paren.expr);
    }
    if let Expr::Group(group) = receiver {
        return receiver_producer_callsite_lift(&group.expr);
    }
    if let Expr::Reference(reference) = receiver {
        return receiver_producer_callsite_lift(&reference.expr);
    }
    if matches!(receiver, Expr::Verbatim(_)) {
        panic!("sugar-walk receiver producer classifier refused uninterpreted verbatim expression");
    }
    if known_non_receiver_producer_expr(receiver) {
        return None;
    }
    panic!("sugar-walk receiver producer classifier refused unknown syn::Expr variant")
}

fn known_non_receiver_producer_expr(expr: &Expr) -> bool {
    matches!(
        expr,
        Expr::Array(_)
            | Expr::Assign(_)
            | Expr::Async(_)
            | Expr::Await(_)
            | Expr::Binary(_)
            | Expr::Block(_)
            | Expr::Break(_)
            | Expr::Cast(_)
            | Expr::Closure(_)
            | Expr::Const(_)
            | Expr::Continue(_)
            | Expr::Field(_)
            | Expr::ForLoop(_)
            | Expr::If(_)
            | Expr::Index(_)
            | Expr::Infer(_)
            | Expr::Let(_)
            | Expr::Lit(_)
            | Expr::Loop(_)
            | Expr::Macro(_)
            | Expr::Match(_)
            | Expr::Path(_)
            | Expr::Range(_)
            | Expr::RawAddr(_)
            | Expr::Repeat(_)
            | Expr::Return(_)
            | Expr::Struct(_)
            | Expr::Try(_)
            | Expr::TryBlock(_)
            | Expr::Tuple(_)
            | Expr::Unary(_)
            | Expr::Unsafe(_)
            | Expr::While(_)
            | Expr::Yield(_)
    )
}

fn associated_call_path_leaf_lift(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = expr else {
        return None;
    };
    if path.path.segments.len() < 2 {
        return None;
    }
    path.path.segments.last().map(|seg| seg.ident.to_string())
}

fn lift_expr_to_term_inner(expr: &Expr, ctx: &mut LiftCtx) -> Option<IrTerm> {
    match expr {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Int(n) => match n.base10_parse::<i64>() {
                Ok(v) => Some(crate::wp::const_int(v)),
                Err(_) => None,
            },
            Lit::Bool(b) => Some(IrTerm::Const {
                value: serde_json::Value::Bool(b.value),
                sort: sugar_ir_types::Sort::Primitive {
                    name: "Bool".to_string(),
                },
            }),
            // A byte literal `b'0'` is its ASCII codepoint; lift as an int
            // const so byte-arithmetic tails (`byte - b'0'`) and byte match
            // arms lift instead of collapsing the whole term to None.
            Lit::Byte(b) => Some(crate::wp::const_int(b.value() as i64)),
            // A char literal `'a'` is its Unicode scalar value.
            Lit::Char(c) => Some(crate::wp::const_int(c.value() as i64)),
            // A string literal lifts to a String const so string-returning
            // tails (`"const"`) carry a real term.
            Lit::Str(s) => Some(IrTerm::Const {
                value: serde_json::Value::String(s.value()),
                sort: sugar_ir_types::Sort::Primitive {
                    name: "String".to_string(),
                },
            }),
            Lit::Float(_) | Lit::ByteStr(_) | Lit::CStr(_) | Lit::Verbatim(_) => {
                // #3017 item 2 owns the broader sort-neutral scalar floor; this
                // term lifter does not invent a carrier for unmodeled literals.
                None
            }
            _ => panic!("sugar-walk term classifier refused unknown syn::Lit variant"),
        },
        Expr::Path(syn::ExprPath { path, .. }) => {
            let seg = path.segments.last()?;
            // Resolve through the scope stack: bound names map to their
            // unique forms; free variables keep their surface name.
            Some(crate::wp::var(ctx.resolve(&seg.ident.to_string())))
        }
        Expr::Paren(p) => lift_expr_to_term_inner(&p.expr, ctx),
        Expr::Reference(r) => lift_expr_to_term_inner(&r.expr, ctx),
        Expr::Cast(c) => lift_expr_to_term_inner(&c.expr, ctx),
        Expr::Field(f) => {
            let base = lift_expr_to_term_inner(&f.base, ctx)?;
            let name = match &f.member {
                syn::Member::Named(id) => id.to_string(),
                syn::Member::Unnamed(idx) => idx.index.to_string(),
            };
            Some(IrTerm::Ctor {
                name: "field".to_string(),
                args: vec![
                    base,
                    IrTerm::Var {
                        name: format!(".{}", name),
                    },
                ],
            })
        }
        Expr::Index(i) => {
            let arr = lift_expr_to_term_inner(&i.expr, ctx)?;
            let idx = lift_expr_to_term_inner(&i.index, ctx)?;
            Some(IrTerm::Ctor {
                name: "index".to_string(),
                args: vec![arr, idx],
            })
        }
        Expr::MethodCall(m) => {
            let receiver = lift_expr_to_term_inner(&m.receiver, ctx)?;
            let mut args = vec![receiver.clone()];
            for a in &m.args {
                let lifted = lift_expr_to_term_inner(a, ctx)?;
                args.push(lifted);
            }
            let method_name = if m.method == "recv" && m.args.is_empty() {
                expr_root_ident(&m.receiver)
                    .map(|rx| format!("channel:recv:{rx}"))
                    .unwrap_or_else(|| format!("method:{}", m.method))
            } else if m.method == "lock" && m.args.is_empty() {
                expr_root_ident(&m.receiver)
                    .map(|mutex| format!("mutex:guard:{mutex}"))
                    .unwrap_or_else(|| format!("method:{}", m.method))
            } else {
                format!("method:{}", m.method)
            };
            let value = IrTerm::Ctor {
                name: method_name,
                args,
            };
            if let Some(guard) = assertion_guard_for_partial(&m.method, &m.receiver, &receiver, ctx)
            {
                return Some(guarded_value_from_formula(guard, value));
            }
            if m.method == "unwrap"
                && m.args.is_empty()
                && receiver_as_str_is_known_json_string(&m.receiver, ctx)
            {
                return Some(guarded_value_for_known_option_unwrap(receiver, value));
            }
            Some(value)
        }
        Expr::Range(r) => {
            let start = match &r.start {
                Some(e) => lift_expr_to_term_inner(e, ctx)?,
                None => crate::wp::var("_"),
            };
            let end = match &r.end {
                Some(e) => lift_expr_to_term_inner(e, ctx)?,
                None => crate::wp::var("_"),
            };
            let name = match r.limits {
                syn::RangeLimits::HalfOpen(_) => "range",
                syn::RangeLimits::Closed(_) => "range_incl",
            };
            Some(IrTerm::Ctor {
                name: name.to_string(),
                args: vec![start, end],
            })
        }
        Expr::Tuple(t) => {
            let mut args = Vec::with_capacity(t.elems.len());
            for e in &t.elems {
                args.push(lift_expr_to_term_inner(e, ctx)?);
            }
            Some(IrTerm::Ctor {
                name: "tuple".to_string(),
                args,
            })
        }
        Expr::Array(a) => {
            let mut args = Vec::with_capacity(a.elems.len());
            for e in &a.elems {
                args.push(lift_expr_to_term_inner(e, ctx)?);
            }
            Some(IrTerm::Ctor {
                name: "array".to_string(),
                args,
            })
        }
        Expr::Repeat(r) => {
            let elem = lift_expr_to_term_inner(&r.expr, ctx)?;
            let count = lift_expr_to_term_inner(&r.len, ctx)?;
            Some(IrTerm::Ctor {
                name: "array_repeat".to_string(),
                args: vec![elem, count],
            })
        }
        Expr::Closure(c) => {
            // `|x| body` lifts to IrTerm::Lambda. Multi-arg closures
            // collapse into nested lambdas (right-associative). Each
            // closure parameter is bound in a fresh scope frame and
            // assigned a globally-unique id by the LiftCtx; references
            // to that name inside the closure body resolve to the
            // unique form. The shadow AST's structural traversal owns
            // this name resolution.
            ctx.push_frame();
            let mut unique_names: Vec<String> = Vec::with_capacity(c.inputs.len());
            for (idx, input) in c.inputs.iter().enumerate() {
                // A closure param's binding NAME. Ident/typed-ident keep
                // their name. A wildcard `_` or a destructuring pattern
                // (`|(a, _)| ..`, common in `.map`/`.unwrap_or_else`) binds
                // a synthetic positional placeholder so the closure lifts
                // to a lambda instead of collapsing the whole tail to None.
                // The body references to a destructured name resolve as
                // free vars (not the placeholder), which is fine under the
                // reflexive encoding: the lambda term is uninterpreted and
                // discharges against the body's own identical lambda.
                let base = match input {
                    syn::Pat::Ident(p) => p.ident.to_string(),
                    syn::Pat::Type(pt) => match &*pt.pat {
                        syn::Pat::Ident(p) => p.ident.to_string(),
                        _ => format!("_closure_arg{idx}"),
                    },
                    _ => format!("_closure_arg{idx}"),
                };
                unique_names.push(ctx.bind(&base));
            }
            let body_lifted = lift_expr_to_term_inner(&c.body, ctx);
            ctx.pop_frame();
            let body = body_lifted?;
            let mut term = body;
            for unique in unique_names.into_iter().rev() {
                term = IrTerm::Lambda {
                    param_name: unique,
                    param_sort: sugar_ir_types::Sort::Primitive {
                        name: "Int".to_string(),
                    },
                    body: Box::new(term),
                };
            }
            Some(term)
        }
        Expr::Await(a) => {
            let base = lift_expr_to_term_inner(&a.base, ctx)?;
            Some(IrTerm::Ctor {
                name: "await".to_string(),
                args: vec![base],
            })
        }
        Expr::Async(a) => {
            // `async { body }` produces a Future. The substrate sees
            // through to the body's eventual value: lift the trailing
            // expression of the block.
            if let Some(syn::Stmt::Expr(e, None)) = a.block.stmts.last() {
                lift_expr_to_term_inner(e, ctx)
            } else {
                None
            }
        }
        Expr::Call(call) => {
            // Plain function call `f(args)`. Lift to a ctor named by the
            // callee's bare symbol (the last path segment) so the call tree
            // SURVIVES into the contract formula. This is the keystone: the
            // ctor name matches the callee's auto-minted bridge `sourceSymbol`,
            // so `enumerate_callsites` finds the seam, `resolve_target` pulls
            // the callee's precondition, and the runner discharges
            // `producer_post -> callee_pre`. Without this arm the call tree
            // vanished and the postcondition collapsed to a vacuous `true` --
            // the missing edge was invisible to the solver. Mirrors the
            // `Expr::MethodCall` arm. Language-blind once emitted: the catch
            // lives in the verifier, below the source language.
            let Expr::Path(syn::ExprPath { path, .. }) = &*call.func else {
                // Calls through a non-path callee (closure value, fn pointer
                // in a local, etc.) have no stable bridge symbol to name.
                return None;
            };
            let callee = path.segments.last()?.ident.to_string();
            let mut args = Vec::with_capacity(call.args.len());
            for a in &call.args {
                args.push(lift_expr_to_term_inner(a, ctx)?);
            }
            Some(IrTerm::Ctor { name: callee, args })
        }
        Expr::If(if_expr) => {
            // A value-position `if`. Reuse the tail-if synthesis (it folds
            // `if c { a } else { b }` into `ite(c, a, b)`, and now also
            // handles if-without-else and stmt-bearing branch blocks).
            lift_tail_if_to_ite_term(if_expr, ctx)
        }
        Expr::Match(match_expr) => {
            // A value-position `match`. Fold it into a right-nested `ite`
            // chain keyed by each arm's recognized guard predicate. Every
            // arm value lifts (often to an uninterpreted ctor term), so the
            // whole match becomes one term that discharges reflexively when
            // it equals the body's own match. See `lift_match_to_ite_term`.
            lift_match_to_ite_term(match_expr, ctx)
        }
        Expr::Block(block_expr) => {
            // A block expression `{ ...; tail }` lifts to the lift of its
            // trailing expression (the block's value). For the compiler-forced
            // pattern `{ let x = value; x }`, substitute the immediately
            // preceding immutable binding into the tail so the returned value
            // term survives without broader data-flow analysis.
            if let Some(term) = lift_immediate_block_result_binding(&block_expr.block.stmts, ctx) {
                return Some(term);
            }
            let tail = block_expr.block.stmts.last()?;
            match tail {
                Stmt::Expr(e, None) => lift_expr_to_term_inner(e, ctx),
                Stmt::Expr(_, Some(_)) | Stmt::Local(_) | Stmt::Item(_) | Stmt::Macro(_) => None,
            }
        }
        Expr::Try(t) => {
            // The `?` operator: `e?` evaluates `e` and unwraps its `Ok`
            // (or short-circuits on `Err`). For the returned-value term we
            // model it as an opaque unary `?` applied to the lifted inner
            // expression. Encoded as an uninterpreted function symbol by the
            // verifier, so `?(e) == ?(e)` discharges reflexively. Without
            // this arm any tail containing `?` collapsed the whole term to
            // None (mechanism (ii) in the body-discharge diagnostic).
            let inner = lift_expr_to_term_inner(&t.expr, ctx)?;
            Some(IrTerm::Ctor {
                name: "?".to_string(),
                args: vec![inner],
            })
        }
        Expr::Macro(m) => Some(lift_macro_to_opaque_term(&m.mac)),
        Expr::Struct(s) => {
            // A struct literal `Name { f: v, g: w, .. }`. Lift to a ctor
            // named by the struct path with the field VALUES as args. To
            // make the term canonical (independent of source field order)
            // the fields are sorted by name; the field names ride along as
            // opaque `#field:<name>` markers so two literals with the same
            // names+values produce the same term (reflexive) and differing
            // ones do not. A `..rest` base, if present, is appended as its
            // lifted term. Without this arm `Ok(Report { .. })` collapsed
            // the whole tail to None.
            let name = s
                .path
                .segments
                .last()
                .map(|seg| seg.ident.to_string())
                .unwrap_or_else(|| "struct".to_string());
            let mut fields: Vec<(&syn::Member, &Expr)> =
                s.fields.iter().map(|f| (&f.member, &f.expr)).collect();
            fields.sort_by_key(|(m, _)| match m {
                syn::Member::Named(id) => id.to_string(),
                syn::Member::Unnamed(idx) => format!("{}", idx.index),
            });
            let mut args = Vec::with_capacity(fields.len() * 2 + 1);
            for (member, value) in fields {
                let fname = match member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                args.push(IrTerm::Var {
                    name: format!("#field:{fname}"),
                });
                args.push(lift_expr_to_term_inner(value, ctx)?);
            }
            if let Some(rest) = &s.rest {
                args.push(lift_expr_to_term_inner(rest, ctx)?);
            }
            Some(IrTerm::Ctor { name, args })
        }
        Expr::Binary(ExprBinary {
            left, op, right, ..
        }) => {
            let op_name = match op {
                BinOp::Add(_) => "+",
                BinOp::Sub(_) => "-",
                BinOp::Mul(_) => "*",
                BinOp::Div(_) => "/",
                BinOp::Rem(_) => "%",
                BinOp::BitAnd(_) => "&",
                BinOp::BitOr(_) => "|",
                BinOp::BitXor(_) => "^",
                BinOp::Shl(_) => "<<",
                BinOp::Shr(_) => ">>",
                // Boolean / relational operators in VALUE position (a
                // function returning `bool`, e.g. `!x.is_absolute() && ..`,
                // or `a == b`). Lift to a `cf_`-prefixed UNINTERPRETED head
                // (NOT the SMT builtins `and`/`or`/`=`/`<`): a builtin
                // demands Bool operands and a Bool result, but these sit
                // over uninterpreted Int-sorted value terms, so the builtin
                // raises a sort mismatch and the reflexive discharge fails.
                // As fresh uninterpreted symbols they discharge by
                // congruence: `cf_and(a,b) == cf_and(a,b)`. (Builtin
                // arithmetic comes from a different, substantive path and is
                // untouched.)
                BinOp::And(_) => "cf_and",
                BinOp::Or(_) => "cf_or",
                BinOp::Eq(_) => "cf_eq",
                BinOp::Ne(_) => "cf_ne",
                BinOp::Lt(_) => "cf_lt",
                BinOp::Le(_) => "cf_le",
                BinOp::Gt(_) => "cf_gt",
                BinOp::Ge(_) => "cf_ge",
                op if binop_is_assignment_lift(op) => return None,
                _ => panic!("sugar-walk term classifier refused unknown syn::BinOp variant"),
            };
            let l = lift_expr_to_term_inner(left, ctx)?;
            let r = lift_expr_to_term_inner(right, ctx)?;
            Some(IrTerm::Ctor {
                name: op_name.to_string(),
                args: vec![l, r],
            })
        }
        Expr::Unary(ExprUnary { op, expr, .. }) => {
            let inner = lift_expr_to_term_inner(expr, ctx)?;
            let name = match op {
                UnOp::Neg(_) => {
                    if let IrTerm::Const { value, sort } = &inner {
                        if let Some(n) = value.as_i64() {
                            return Some(IrTerm::Const {
                                value: serde_json::json!(-n),
                                sort: sort.clone(),
                            });
                        }
                    }
                    "neg"
                }
                UnOp::Not(_) => "bit-not",
                UnOp::Deref(_) => return Some(inner), // *x is x for substitution
                _ => panic!("sugar-walk term classifier refused unknown syn::UnOp variant"),
            };
            Some(IrTerm::Ctor {
                name: name.to_string(),
                args: vec![inner],
            })
        }
        Expr::Group(group) => lift_expr_to_term_inner(&group.expr, ctx),
        Expr::Unsafe(unsafe_expr) => {
            block_tail_expr(&unsafe_expr.block).and_then(|tail| lift_expr_to_term_inner(tail, ctx))
        }
        Expr::Const(const_expr) => {
            block_tail_expr(&const_expr.block).and_then(|tail| lift_expr_to_term_inner(tail, ctx))
        }
        Expr::Assign(_)
        | Expr::Break(_)
        | Expr::Continue(_)
        | Expr::ForLoop(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Loop(_)
        | Expr::RawAddr(_)
        | Expr::Return(_)
        | Expr::TryBlock(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        Expr::Verbatim(_) => {
            panic!("sugar-walk term classifier refused uninterpreted verbatim expression")
        }
        _ => panic!("sugar-walk term classifier refused unknown syn::Expr variant"),
    }
}

fn lift_immediate_block_result_binding(stmts: &[Stmt], ctx: &mut LiftCtx) -> Option<IrTerm> {
    let [prefix @ .., Stmt::Expr(Expr::Path(tail), None)] = stmts else {
        return None;
    };
    let tail_name = tail.path.get_ident()?.to_string();
    let Stmt::Local(local) = prefix.last()? else {
        return None;
    };
    let (bound_name, mutable) = local_binding_ident(local)?;
    if mutable || bound_name != tail_name {
        return None;
    }
    let init = &local.init.as_ref()?.expr;
    lift_expr_to_term_inner(init, ctx)
}

fn bin_op_to_predicate_name(op: &BinOp) -> Option<&'static str> {
    match op {
        BinOp::Eq(_) => Some("="),
        BinOp::Ne(_) => Some("≠"),
        BinOp::Lt(_) => Some("<"),
        BinOp::Le(_) => Some("≤"),
        BinOp::Gt(_) => Some(">"),
        BinOp::Ge(_) => Some("≥"),
        BinOp::Add(_)
        | BinOp::AddAssign(_)
        | BinOp::And(_)
        | BinOp::BitAnd(_)
        | BinOp::BitAndAssign(_)
        | BinOp::BitOr(_)
        | BinOp::BitOrAssign(_)
        | BinOp::BitXor(_)
        | BinOp::BitXorAssign(_)
        | BinOp::Div(_)
        | BinOp::DivAssign(_)
        | BinOp::Mul(_)
        | BinOp::MulAssign(_)
        | BinOp::Or(_)
        | BinOp::Rem(_)
        | BinOp::RemAssign(_)
        | BinOp::Shl(_)
        | BinOp::ShlAssign(_)
        | BinOp::Shr(_)
        | BinOp::ShrAssign(_)
        | BinOp::Sub(_)
        | BinOp::SubAssign(_) => None,
        other => {
            let _ = other;
            panic!("sugar-walk predicate operator classifier refused unknown syn::BinOp variant")
        }
    }
}

fn block_only_panics(block: &syn::Block) -> bool {
    if block.stmts.len() != 1 {
        return false;
    }
    let stmt = &block.stmts[0];
    let mac: &Macro = match stmt {
        Stmt::Expr(Expr::Macro(ExprMacro { mac, .. }), _) => mac,
        Stmt::Macro(StmtMacro { mac, .. }) => mac,
        _ => return false,
    };
    let Some(segment) = mac.path.segments.last() else {
        return false;
    };
    segment.ident == "panic"
}

fn negate(f: IrFormula) -> IrFormula {
    // Comparison flips: `if x < 10 panic` lifts to `x ≥ 10`, not `¬(x < 10)`.
    if let IrFormula::Atomic { name, args } = &f {
        let flipped = match name.as_str() {
            "<" => Some("≥"),
            "≤" => Some(">"),
            ">" => Some("≤"),
            "≥" => Some("<"),
            "=" => Some("≠"),
            "≠" => Some("="),
            other => {
                // sugar-audit: not-mine(non-comparison predicates negate as explicit Not nodes)
                let _ = other;
                None
            }
        };
        if let Some(new_name) = flipped {
            return IrFormula::Atomic {
                name: new_name.to_string(),
                args: args.clone(),
            };
        }
    }
    // De Morgan's laws: push negation inward.
    //   ¬(a ∧ b) → ¬a ∨ ¬b
    //   ¬(a ∨ b) → ¬a ∧ ¬b
    // Sir's "every else is the contraposition" — when the lifter
    // produces the contraposition of `a && b` for an if-then-panic,
    // the result is `¬a ∨ ¬b`, not the harder-to-discharge `¬(a ∧ b)`.
    match f {
        IrFormula::And { operands } => IrFormula::Or {
            operands: operands.into_iter().map(negate).collect(),
        },
        IrFormula::Or { operands } => IrFormula::And {
            operands: operands.into_iter().map(negate).collect(),
        },
        IrFormula::Not { mut operands } if operands.len() == 1 => {
            // Double-negation elimination: ¬¬a → a.
            operands.pop().unwrap()
        }
        other => IrFormula::Not {
            operands: vec![other],
        },
    }
}

fn simplify_conjunction(parts: Vec<IrFormula>) -> IrFormula {
    if parts.is_empty() {
        IrFormula::Atomic {
            name: "true".to_string(),
            args: vec![],
        }
    } else if parts.len() == 1 {
        parts.into_iter().next().unwrap()
    } else {
        IrFormula::And { operands: parts }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wp::{atomic_ge, atomic_true, const_int, var};

    fn parse_fn(src: &str) -> ItemFn {
        let file: syn::File = syn::parse_str(src).expect("parses");
        file.items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) => Some(f),
                other => {
                    // sugar-audit: not-mine(test helper searches one top-level free function)
                    let _ = other;
                    None
                }
            })
            .expect("function present")
    }

    #[test]
    fn lifts_if_then_panic_as_negated_condition() {
        let item_fn = parse_fn(
            r#"
            fn f(x: u32) -> u32 {
                if x < 10 {
                    panic!("x must be >= 10");
                }
                x * 2
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        // ¬(x < 10) simplifies to x ≥ 10 via negate's comparison flip.
        assert_eq!(
            pre.as_formula(),
            atomic_ge(var("x"), const_int(10)).as_formula()
        );
    }

    #[test]
    fn lifts_assert_macro_as_predicate() {
        let item_fn = parse_fn(
            r#"
            fn g(x: u32) -> u32 {
                assert!(x >= 5);
                x * 3
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        assert_eq!(
            pre.as_formula(),
            atomic_ge(var("x"), const_int(5)).as_formula()
        );
    }

    #[test]
    fn lifts_assert_macro_with_message_as_predicate() {
        let item_fn = parse_fn(
            r#"
            fn to_digit(radix: u32) {
                assert!(
                    radix >= 2 && radix <= 36,
                    "to_digit: invalid radix -- radix must be in the range 2 to 36 inclusive"
                );
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        let json = serde_json::to_string(pre.as_formula()).unwrap();
        assert!(
            json.contains("\"and\""),
            "pre should be a conjunction: {json}"
        );
        assert!(
            json.contains("\"≥\"") && json.contains("\"≤\""),
            "pre should contain radix bounds: {json}"
        );
        assert!(
            json.contains("\"radix\""),
            "pre should mention radix: {json}"
        );
    }

    #[test]
    fn empty_body_lifts_to_vacuous_true() {
        let item_fn = parse_fn(r#"fn h() {}"#);
        let pre = lift_function_precondition(&item_fn);
        assert_eq!(pre.as_formula(), atomic_true().as_formula());
    }

    #[test]
    fn function_without_preconditions_lifts_to_true() {
        let item_fn = parse_fn(
            r#"
            fn k(x: u32) -> u32 {
                x + 1
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        assert_eq!(pre.as_formula(), atomic_true().as_formula());
    }

    #[test]
    fn multiple_assertions_conjoin() {
        let item_fn = parse_fn(
            r#"
            fn m(x: u32, y: u32) -> u32 {
                assert!(x >= 1);
                assert!(y >= 2);
                x + y
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        let expected = IrFormula::And {
            operands: vec![
                atomic_ge(var("x"), const_int(1)).into_formula(),
                atomic_ge(var("y"), const_int(2)).into_formula(),
            ],
        };
        assert_eq!(pre.as_formula(), &expected);
    }

    #[test]
    fn postcondition_derives_return_value_relation() {
        // f's body: `if x < 10 panic; x * 2`.
        // Derived post: `(x ≥ 10) ∧ (result = x * 2)`.
        // The first conjunct is the contraposition lifted from the
        // if-then-panic. The second is derived from the trailing
        // return expression `x * 2`.
        let item_fn = parse_fn(
            r#"
            fn f(x: u32) -> u32 {
                if x < 10 { panic!(); }
                x * 2
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn);
        let json = serde_json::to_string(post.as_formula()).unwrap();
        assert!(
            json.contains("\"≥\""),
            "post should include x ≥ 10: {}",
            json
        );
        // The return-value derivation: result = x * 2.
        assert!(
            json.contains("\"result\""),
            "post should include `result` variable: {}",
            json
        );
        assert!(
            json.contains("\"*\""),
            "post should include the multiplication ctor: {}",
            json
        );
    }

    #[test]
    fn binary_ops_lift_to_ctor_terms() {
        // `x + 5` lifts to Ctor("+", [Var("x"), Const(5)]).
        let item_fn = parse_fn(
            r#"
            fn k(x: u32) -> u32 {
                x + 5
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn);
        let json = serde_json::to_string(post.as_formula()).unwrap();
        assert!(
            json.contains("\"+\""),
            "post should encode the + ctor: {}",
            json
        );
        assert!(json.contains("\"x\""));
    }

    #[test]
    fn tokio_mpsc_recv_lifts_as_receiver_specific_channel_conduit() {
        let expr: Expr = syn::parse_str("rx.recv().await.unwrap()").unwrap();
        let term = lift_expr_to_term(&expr).unwrap();
        let json = serde_json::to_value(&term).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "kind": "ctor",
                "name": "method:unwrap",
                "args": [{
                    "kind": "ctor",
                    "name": "await",
                    "args": [{
                        "kind": "ctor",
                        "name": "channel:recv:rx",
                        "args": [{"kind": "var", "name": "rx"}]
                    }]
                }]
            })
        );
    }

    #[test]
    fn tokio_mutex_lock_lifts_as_receiver_specific_guard_conduit() {
        let expr: Expr = syn::parse_str("*m.lock().await").unwrap();
        let term = lift_expr_to_term(&expr).unwrap();
        let json = serde_json::to_value(&term).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "kind": "ctor",
                "name": "await",
                "args": [{
                    "kind": "ctor",
                    "name": "mutex:guard:m",
                    "args": [{"kind": "var", "name": "m"}]
                }]
            })
        );
    }

    #[test]
    fn block_result_binding_preserves_mutex_guard_conduit_term() {
        let expr: Expr = syn::parse_str("{ let x = consumer(*m.lock().await); x }").unwrap();
        let term = lift_expr_to_term(&expr).unwrap();
        let json = serde_json::to_value(&term).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "kind": "ctor",
                "name": "consumer",
                "args": [{
                    "kind": "ctor",
                    "name": "await",
                    "args": [{
                        "kind": "ctor",
                        "name": "mutex:guard:m",
                        "args": [{"kind": "var", "name": "m"}]
                    }]
                }]
            })
        );
    }

    #[test]
    fn postcondition_for_tail_if_expression_is_branch_sensitive() {
        let item_fn = parse_fn(
            r#"
            fn foo(x: i32) -> i32 {
                if x == 0 { -22 } else { x }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let expected = IrFormula::Atomic {
            name: "=".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "result".to_string(),
                },
                IrTerm::Ctor {
                    // Synthesized control-flow heads are `cf_`-prefixed
                    // (uninterpreted), not the SMT builtins `ite`/`=`, so
                    // they encode over uninterpreted operands without a
                    // sort mismatch and discharge reflexively.
                    name: panic_freedom::CF_ITE.to_string(),
                    args: vec![
                        IrTerm::Ctor {
                            name: "cf_eq".to_string(),
                            args: vec![var("x"), const_int(0)],
                        },
                        const_int(-22),
                        var("x"),
                    ],
                },
            ],
        };
        assert_eq!(post, expected);
    }

    #[test]
    fn lifts_or_condition_with_de_morgan() {
        // `if x < 10 || y < 5 panic` lifts to ¬(x<10 ∨ y<5)
        // which simplifies via De Morgan to (x≥10 ∧ y≥5).
        let item_fn = parse_fn(
            r#"
            fn h(x: u32, y: u32) -> u32 {
                if x < 10 || y < 5 {
                    panic!();
                }
                x * y
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        let json = serde_json::to_string(pre.as_formula()).unwrap();
        // Expect an `and` of two `≥` atoms (De Morgan applied + comparison flips).
        assert!(
            json.contains("\"and\""),
            "pre should be a conjunction: {}",
            json
        );
        assert!(
            json.contains("\"≥\""),
            "pre should contain ≥ atoms: {}",
            json
        );
        assert!(json.contains("\"x\"") && json.contains("\"y\""));
    }

    #[test]
    fn lifts_and_condition_with_de_morgan() {
        // `if x < 10 && y < 5 panic` lifts to ¬(x<10 ∧ y<5)
        // which is (x≥10 ∨ y≥5).
        let item_fn = parse_fn(
            r#"
            fn h(x: u32, y: u32) -> u32 {
                if x < 10 && y < 5 {
                    panic!();
                }
                x + y
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        let json = serde_json::to_string(pre.as_formula()).unwrap();
        // Expect an `or` of two `≥` atoms.
        assert!(
            json.contains("\"or\""),
            "pre should be a disjunction: {}",
            json
        );
        assert!(
            json.contains("\"≥\""),
            "pre should contain ≥ atoms: {}",
            json
        );
    }

    #[test]
    fn double_negation_eliminated() {
        // `if !(x >= 10) panic` is equivalent to `if x < 10 panic`.
        // The lifter should produce `x ≥ 10` (not `¬¬(x ≥ 10)`).
        let item_fn = parse_fn(
            r#"
            fn n(x: u32) -> u32 {
                if !(x >= 10) {
                    panic!();
                }
                x * 2
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        let json = serde_json::to_string(pre.as_formula()).unwrap();
        // The atomic ≥ should appear directly, with no `not` wrapper.
        assert!(
            json.contains("\"≥\""),
            "pre should contain ≥ atom: {}",
            json
        );
        assert!(
            !json.contains("\"not\""),
            "pre should NOT contain a `not` wrapper (double negation eliminated): {}",
            json
        );
    }

    // ---- shadow-AST scope tracking ----

    #[test]
    fn lift_closure_assigns_unique_param_id() {
        // |x| x  ->  Lambda { x#0, body: Var x#0 }
        let expr: Expr = syn::parse_str("|x| x").unwrap();
        let term = lift_expr_to_term(&expr).unwrap();
        match term {
            IrTerm::Lambda {
                param_name, body, ..
            } => {
                assert!(
                    param_name.starts_with("x#"),
                    "expected x#N, got {}",
                    param_name
                );
                match *body {
                    IrTerm::Var { name } => assert_eq!(
                        name, param_name,
                        "body's `x` must resolve to the closure's unique id"
                    ),
                    other => panic!("expected Var, got {:?}", other),
                }
            }
            other => panic!("expected Lambda, got {:?}", other),
        }
    }

    #[test]
    fn lift_nested_closures_get_distinct_ids() {
        // |x| |x| x  ->  the inner `x` shadows the outer; the inner's
        // unique id is what the body resolves to.
        let expr: Expr = syn::parse_str("|x| |x| x").unwrap();
        let term = lift_expr_to_term(&expr).unwrap();
        match term {
            IrTerm::Lambda {
                param_name: outer,
                body,
                ..
            } => match *body {
                IrTerm::Lambda {
                    param_name: inner,
                    body: inner_body,
                    ..
                } => {
                    assert_ne!(outer, inner, "outer and inner ids must differ");
                    assert!(outer.starts_with("x#"));
                    assert!(inner.starts_with("x#"));
                    match *inner_body {
                        IrTerm::Var { name } => {
                            assert_eq!(name, inner, "innermost binding wins");
                        }
                        other => panic!("expected Var, got {:?}", other),
                    }
                }
                other => panic!("expected nested Lambda, got {:?}", other),
            },
            other => panic!("expected Lambda, got {:?}", other),
        }
    }

    #[test]
    fn lift_free_variable_keeps_original_name() {
        // Bare `y` lifts to Var("y") — y is free in this context.
        let expr: Expr = syn::parse_str("y").unwrap();
        let term = lift_expr_to_term(&expr).unwrap();
        match term {
            IrTerm::Var { name } => {
                assert_eq!(name, "y", "free variable keeps surface name");
            }
            other => panic!("expected Var, got {:?}", other),
        }
    }

    #[test]
    fn lift_closure_does_not_capture_outer_reference() {
        // |x| (x + y)  -- inside the closure, x is bound, y is free.
        let expr: Expr = syn::parse_str("|x| x + y").unwrap();
        let term = lift_expr_to_term(&expr).unwrap();
        match term {
            IrTerm::Lambda {
                param_name, body, ..
            } => {
                assert!(param_name.starts_with("x#"));
                let json = serde_json::to_string(&body).unwrap();
                // Body should reference the unique x#N for x and bare "y" for y.
                assert!(
                    json.contains(&format!("\"{}\"", param_name)),
                    "body should reference the unique x: {}",
                    json
                );
                assert!(
                    json.contains("\"y\""),
                    "body should reference free y unchanged: {}",
                    json
                );
            }
            other => panic!("expected Lambda, got {:?}", other),
        }
    }

    #[test]
    fn lift_function_with_closure_keeps_formal_unscoped() {
        // fn f(x) { let _ = |x| x; x }
        // The trailing `x` is the function's formal — should be plain "x".
        // The closure's body `x` is the closure's param — should be "x#N".
        let item_fn = parse_fn(
            r#"
            fn f(x: u32) -> u32 {
                let _ = |x: u32| x;
                x
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn);
        let json = serde_json::to_string(post.as_formula()).unwrap();
        // The trailing-expression derivation gives `result = x` (plain x).
        assert!(
            json.contains("\"result\""),
            "post should derive result = x: {}",
            json
        );
        // The plain "x" formal (not "x#N") should appear.
        assert!(
            json.contains("\"x\""),
            "post should reference the formal x: {}",
            json
        );
    }

    // ---- bug-fix regression tests ----

    #[test]
    fn call_expr_body_lifts_call_tree_into_postcondition() {
        // A function whose body is a nested call must derive a post that
        // CONTAINS the call tree as ctor terms. Otherwise the callees are
        // invisible to `enumerate_callsites` and the missing-edge seam can
        // never be discharged (it was the false-green hole: this collapsed to
        // a vacuous `true` because `Expr::Call` had no lift arm).
        let item_fn = parse_fn(
            r#"
            fn address_of(value: i64) -> i64 {
                content_address(serialize(value))
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn);
        let json = serde_json::to_string(post.as_formula()).unwrap();
        assert!(
            json.contains("\"result\""),
            "post must derive result = <body>: {json}"
        );
        assert!(
            json.contains("content_address"),
            "post must contain the outer call ctor `content_address`: {json}"
        );
        assert!(
            json.contains("serialize"),
            "post must contain the nested call ctor `serialize`: {json}"
        );
    }

    #[test]
    fn debug_assert_not_lifted_to_postcondition() {
        // Bug #5: `debug_assert!` is compiled out in release builds.
        // It must NOT contribute to the postcondition.
        let item_fn = parse_fn(
            r#"
            fn f(x: u32) -> u32 {
                debug_assert!(x >= 5);
                x * 2
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn);
        let json = serde_json::to_string(post.as_formula()).unwrap();
        // The postcondition should NOT include the debug_assert predicate.
        // It should only have the trailing-expression derivation.
        assert!(
            !json.contains("\"≥\""),
            "debug_assert! must NOT appear in postcondition: {}",
            json
        );
        // The trailing `x * 2` should still derive a result postcondition.
        assert!(
            json.contains("\"result\""),
            "postcondition should still include result = x * 2: {}",
            json
        );
    }

    #[test]
    fn assert_shadowed_by_later_let_dropped_from_postcondition() {
        // Bug #6: `assert!(x >= 5); let x = 0; x` — the assert refers to
        // the original `x`, but `let x = 0` rebinds `x` afterward.
        // The assert is UNSOUND in the postcondition and must be dropped.
        let item_fn = parse_fn(
            r#"
            fn f(x: u32) -> u32 {
                assert!(x >= 5);
                let x = 0u32;
                x
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn);
        let json = serde_json::to_string(post.as_formula()).unwrap();
        // The original assert!(x >= 5) is unsound after let x = 0.
        // It must NOT appear in the postcondition.
        assert!(
            !json.contains("\"≥\""),
            "shadowed assert! must NOT appear in postcondition: {}",
            json
        );
    }

    #[test]
    fn assert_not_shadowed_stays_in_postcondition() {
        // Bug #6 complementary: when no later `let` shadows the assert's
        // free variables, the assert correctly stays in the postcondition.
        let item_fn = parse_fn(
            r#"
            fn f(x: u32, y: u32) -> u32 {
                assert!(x >= 5);
                let z = 0u32;   // shadows `z`, not `x`
                x + y
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn);
        let json = serde_json::to_string(post.as_formula()).unwrap();
        // `x` is NOT rebound; the assert should remain.
        assert!(
            json.contains("\"≥\""),
            "non-shadowed assert! should remain in postcondition: {}",
            json
        );
    }

    #[test]
    fn explicit_return_derives_result_postcondition() {
        // Bug #7: `fn f() -> i32 { return x + 1; }` must derive
        // `result = x + 1` in the postcondition.
        let item_fn = parse_fn(
            r#"
            fn f(x: i32) -> i32 {
                return x + 1;
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn);
        let json = serde_json::to_string(post.as_formula()).unwrap();
        assert!(
            json.contains("\"result\""),
            "explicit return expr must derive result = ...: {}",
            json
        );
        assert!(
            json.contains("\"+\""),
            "explicit return expr must include the + ctor: {}",
            json
        );
        assert!(
            json.contains("\"x\""),
            "explicit return expr must reference x: {}",
            json
        );
    }

    #[test]
    fn lifts_is_none_method_call_as_atomic_predicate() {
        // `if x.is_none() { panic!() }` lifts to is_none(x) at the
        // precondition (via the if-then-panic path: ¬panic_cond = ¬is_none(x)).
        // This is the shape source-level defensive guards use.
        let item_fn = parse_fn(
            r#"
            fn caller(x: Option<i32>) {
                if x.is_none() { panic!("not_null: x must be Some"); }
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        let json = serde_json::to_string(pre.as_formula()).unwrap();
        // The if-then-panic lifts ¬is_none(x) as the precondition.
        // The JSON should contain "is_none" to confirm the method-call lift fired.
        assert!(
            json.contains("is_none"),
            "if x.is_none() panic must lift is_none to precondition: {}",
            json
        );
    }

    #[test]
    fn lifts_is_some_method_call_as_atomic_predicate() {
        // `if !x.is_some() { panic!() }` (double-negation via De Morgan)
        // should also lift correctly.
        let item_fn = parse_fn(
            r#"
            fn caller(x: Option<i32>) {
                if !x.is_some() { panic!("not_null: x must be Some"); }
            }
        "#,
        );
        let pre = lift_function_precondition(&item_fn);
        let json = serde_json::to_string(pre.as_formula()).unwrap();
        assert!(
            json.contains("is_some"),
            "if !x.is_some() panic must lift is_some to precondition: {}",
            json
        );
    }

    #[test]
    fn predicate_value_boundary_distinguishes_predicate_from_data_bool_term() {
        let data_bool = bool_const_term(true);
        let predicate = predicate_value_from_ir_formula(bool_term_predicate(data_bool.clone()));
        let predicate_wire = raise_ir_formula(predicate.formula());

        assert_ne!(
            serde_json::to_value(&data_bool).unwrap(),
            serde_json::to_value(&predicate_wire).unwrap(),
            "BoolValue-as-term and PredicateValue must stay different wire positions"
        );
        assert!(
            matches!(data_bool, IrTerm::Const { .. }),
            "data-position bool stays a term"
        );
        assert!(
            matches!(predicate_wire, IrFormula::Atomic { name, .. } if name == "="),
            "predicate-position bool becomes an assertion formula"
        );
    }

    #[test]
    fn predicate_value_boundary_refuses_raw_term_as_predicate() {
        let refusal = std::panic::catch_unwind(|| {
            let raw_bool = Desugared::Term(lower_ir(&bool_const_term(true)));
            let _ = require_predicate_value_floor(raw_bool, "predicate boundary twin");
        });
        let Err(payload) = refusal else {
            panic!("raw bool term silently crossed the PredicateValue boundary");
        };
        let message = payload
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| payload.downcast_ref::<&str>().map(|msg| (*msg).to_string()))
            .unwrap_or_else(|| "<non-string panic payload>".to_string());
        assert!(
            message.contains(
                "predicate boundary twin completed Term floor where a PredicateValue floor was required"
            ),
            "raw term refusal should name the PredicateValue floor seam: {message}"
        );
    }

    /// The post's `result == <value>` equation, or None if the body has
    /// no result term (genuinely unit-returning).
    fn result_equation_of(item_fn: &ItemFn) -> Option<IrTerm> {
        let post = lift_function_postcondition(item_fn);
        libsugar::wp::find_result_equation(post.as_formula(), "result")
    }

    #[test]
    fn ok_struct_literal_tail_lifts_a_result_equation() {
        // `Ok(Report { code: 0 })` formerly collapsed to None (the struct
        // literal child had no lift arm). The new `Expr::Struct` arm lifts
        // it; the whole tail becomes `Ok(Report(...))`, a `result ==` post
        // that discharges reflexively.
        let item_fn = parse_fn(
            r#"
            fn make() -> Result<Report, ()> {
                Ok(Report { code: 0 })
            }
        "#,
        );
        let eq = result_equation_of(&item_fn);
        assert!(
            eq.is_some(),
            "Ok(StructLiteral{{..}}) tail must synthesize a result equation"
        );
        let json = serde_json::to_string(&eq.unwrap()).unwrap();
        assert!(
            json.contains("Ok"),
            "result term must carry the Ok ctor: {json}"
        );
        assert!(
            json.contains("Report"),
            "result term must carry the struct ctor: {json}"
        );
    }

    #[test]
    fn pathbuf_from_format_macro_tail_lifts_a_result_equation() {
        // `PathBuf::from(format!("{}", x))`: a call whose argument is a
        // `format!` macro. The macro arm encodes it as an opaque
        // `macro:format#<hash>` ctor instead of collapsing the whole tail
        // to None (diagnostic mechanism (ii)).
        let item_fn = parse_fn(
            r#"
            fn p(x: i64) -> String {
                from(format!("{}", x))
            }
        "#,
        );
        let eq = result_equation_of(&item_fn);
        assert!(
            eq.is_some(),
            "call wrapping a format! macro must synthesize a result equation"
        );
        let json = serde_json::to_string(&eq.unwrap()).unwrap();
        assert!(
            json.contains("macro:format#"),
            "the format! macro must lift to an opaque keyed ctor: {json}"
        );
    }

    #[test]
    fn match_tail_lifts_to_ite_chain_result_equation() {
        // A value-position `match` now folds to an `ite` chain rather than
        // collapsing to None (diagnostic mechanism (i)).
        let item_fn = parse_fn(
            r#"
            fn classify(x: i64) -> i64 {
                match x {
                    0 => zero(),
                    _ => other(),
                }
            }
        "#,
        );
        let eq = result_equation_of(&item_fn);
        assert!(eq.is_some(), "match tail must synthesize a result equation");
        let json = serde_json::to_string(&eq.unwrap()).unwrap();
        assert!(
            json.contains("cf_ite"),
            "match must lift to a cf_ite chain: {json}"
        );
    }

    #[test]
    fn try_operator_tail_lifts_a_result_equation() {
        // `serialize(x)?` (the `?` operator) formerly collapsed the tail.
        let item_fn = parse_fn(
            r#"
            fn t(x: i64) -> Result<i64, ()> {
                Ok(serialize(x)?)
            }
        "#,
        );
        let eq = result_equation_of(&item_fn);
        assert!(
            eq.is_some(),
            "tail containing `?` must synthesize a result equation"
        );
        let json = serde_json::to_string(&eq.unwrap()).unwrap();
        assert!(
            json.contains("\"?\""),
            "`?` must lift to an opaque `?` ctor: {json}"
        );
    }

    #[test]
    fn macro_token_hash_is_deterministic_and_distinguishing() {
        // The SAME macro call (same name + tokens) lifts to the SAME term
        // (so reflexive equality holds); a DIFFERENT call lifts to a
        // different term (so distinct calls do not spuriously unify).
        let a1: syn::Macro = syn::parse_quote!(format!("{}", x));
        let a2: syn::Macro = syn::parse_quote!(format!("{}", x));
        let b: syn::Macro = syn::parse_quote!(format!("{}", y));
        let ta = lift_macro_to_opaque_term(&a1);
        let ta2 = lift_macro_to_opaque_term(&a2);
        let tb = lift_macro_to_opaque_term(&b);
        assert_eq!(
            ta, ta2,
            "identical macro calls must lift to the same opaque term"
        );
        assert_ne!(
            ta, tb,
            "different macro calls must lift to different opaque terms"
        );
    }

    // ---- PANIC-FREEDOM guard resolution lives in the Rust kit ----
    //
    // The complement table (`is_some` <-> `is_none`, `is_ok` <-> `is_err`,
    // `is_empty`) was RELOCATED here from the verifier so the verifier stays
    // language-blind. These tests pin the Rust-std semantics: the then-branch
    // carries the POSITIVE predicate, the else-branch the COMPLEMENT, and an
    // unrecognized guard wraps NOTHING (fail-safe).

    #[test]
    fn branch_guard_head_then_is_positive_else_is_complement() {
        // The full complement table, both branches.
        assert_eq!(branch_guard_head("is_some", false), Some("is_some"));
        assert_eq!(branch_guard_head("is_some", true), Some("is_none"));
        assert_eq!(branch_guard_head("is_none", false), Some("is_none"));
        assert_eq!(branch_guard_head("is_none", true), Some("is_some"));
        assert_eq!(branch_guard_head("is_ok", false), Some("is_ok"));
        assert_eq!(branch_guard_head("is_ok", true), Some("is_err"));
        assert_eq!(branch_guard_head("is_err", false), Some("is_err"));
        assert_eq!(branch_guard_head("is_err", true), Some("is_ok"));
        assert_eq!(branch_guard_head("is_empty", false), Some("is_empty"));
        // The method-call form `opt.is_some()` lifts to `method:is_some`; it must
        // normalize to the bare `is_some` that the partial's pre uses, or the
        // syntactic discharge `guard => pre` never matches.
        assert_eq!(branch_guard_head("method:is_some", false), Some("is_some"));
        assert_eq!(branch_guard_head("method:is_some", true), Some("is_none"));
        assert_eq!(branch_guard_head("method:is_ok", false), Some("is_ok"));
        assert_eq!(branch_guard_head("method:is_err", true), Some("is_ok"));
    }

    #[test]
    fn branch_guard_head_refuses_unrecognized_and_negated_is_empty() {
        // `!is_empty` establishes no partial's pre -> no guard.
        assert_eq!(branch_guard_head("is_empty", true), None);
        // Comparisons / conjunctions / method guards are not partial-pre
        // predicates -> no guard, so a partial inside stays undecidable.
        assert_eq!(branch_guard_head("cf_lt", false), None);
        assert_eq!(branch_guard_head("cf_and", false), None);
        assert_eq!(branch_guard_head("match_guard", false), None);
        assert_eq!(branch_guard_head("method:is_absolute", false), None);
    }

    #[test]
    fn guarded_return_for_branch_then_carries_positive_else_carries_complement() {
        // Condition `is_some(x)`. The then-branch must wrap to
        // cf_guarded(is_some(x), value); the else-branch to
        // cf_guarded(is_none(x), value) -- the kit-computed complement.
        let recv = IrTerm::Var { name: "x".into() };
        let cond = IrFormula::Atomic {
            name: "is_some".into(),
            args: vec![recv.clone()],
        };
        let val = || IrTerm::Var { name: "v".into() };

        let then_t = guarded_return_for_branch(Some(&cond), false, val(), None);
        let else_t = guarded_return_for_branch(Some(&cond), true, val(), None);

        match &then_t {
            IrTerm::Ctor { name, args } => {
                assert_eq!(name, "cf_guarded");
                match &args[0] {
                    IrTerm::Ctor { name, args } => {
                        assert_eq!(
                            name, "is_some",
                            "then-branch carries the POSITIVE predicate"
                        );
                        assert_eq!(args, &vec![recv.clone()], "guard names the receiver term");
                    }
                    other => panic!("then guard not a ctor: {other:?}"),
                }
            }
            other => panic!("then not cf_guarded: {other:?}"),
        }
        match &else_t {
            IrTerm::Ctor { name, args } => {
                assert_eq!(name, "cf_guarded");
                match &args[0] {
                    IrTerm::Ctor { name, .. } => assert_eq!(
                        name, "is_none",
                        "else-branch carries the COMPLEMENT (the trap: never is_some)"
                    ),
                    other => panic!("else guard not a ctor: {other:?}"),
                }
            }
            other => panic!("else not cf_guarded: {other:?}"),
        }
    }

    #[test]
    fn guarded_return_for_branch_unrecognized_condition_wraps_nothing() {
        // A comparison condition (`cf_lt(...)`) is not a partial-pre predicate:
        // the branch value passes through UNCHANGED (no cf_guarded), so a
        // partial inside it stays undecidable and the cf_ite is byte-stable.
        let cond = IrFormula::Atomic {
            name: "cf_lt".into(),
            args: vec![IrTerm::Var { name: "x".into() }, const_int(10)],
        };
        let val = IrTerm::Var { name: "v".into() };
        let wrapped = guarded_return_for_branch(Some(&cond), false, val.clone(), None);
        assert_eq!(wrapped, val, "unrecognized guard must wrap nothing");
        // A method-call condition likewise.
        let mcond = IrFormula::Atomic {
            name: "method:is_absolute".into(),
            args: vec![IrTerm::Var { name: "p".into() }],
        };
        assert_eq!(
            guarded_return_for_branch(Some(&mcond), true, val.clone(), None),
            val,
            "a method guard must wrap nothing"
        );
    }

    #[test]
    fn cf_ite_via_symbolic_value_refuses_unlowerable_condition_sort() {
        // The boundary conversion is the totality obligation for this slice:
        // a condition with no algebra image must fail loudly, not silently drop
        // its guard and over-claim branch facts.
        let cond = IrTerm::Const {
            value: serde_json::json!(0),
            sort: sugar_ir_types::Sort::Function {
                args: vec![sugar_ir_types::Sort::Primitive { name: "Int".into() }],
                ret: Box::new(sugar_ir_types::Sort::Primitive {
                    name: "Bool".into(),
                }),
            },
        };
        let value = IrTerm::Var { name: "v".into() };

        let refusal = std::panic::catch_unwind(|| {
            cf_ite_via_symbolic_value_boundary(cond, value.clone(), value)
        });
        let Err(payload) = refusal else {
            panic!("Function-sort condition silently crossed the term boundary");
        };
        let message = payload
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| payload.downcast_ref::<&str>().map(|msg| (*msg).to_string()))
            .unwrap_or_else(|| "<non-string panic payload>".to_string());
        assert!(
            message.contains("not supported in symbolic Sort wrapper"),
            "Function-sort refusal should name the term boundary seam: {message}"
        );
    }

    #[test]
    fn guarded_return_for_branch_refuses_unlowerable_value_sort() {
        // The branch value crosses the same boundary before guard composition;
        // if it has no algebra image, the route must fail loudly instead of
        // fabricating a guarded fact for an unrepresentable value.
        let cond = IrFormula::Atomic {
            name: "is_some".into(),
            args: vec![IrTerm::Var { name: "x".into() }],
        };
        let value = IrTerm::Const {
            value: serde_json::json!(0),
            sort: sugar_ir_types::Sort::Function {
                args: vec![sugar_ir_types::Sort::Primitive { name: "Int".into() }],
                ret: Box::new(sugar_ir_types::Sort::Primitive {
                    name: "Bool".into(),
                }),
            },
        };

        let refusal =
            std::panic::catch_unwind(|| guarded_return_for_branch(Some(&cond), false, value, None));
        let Err(payload) = refusal else {
            panic!("Function-sort value silently crossed the term boundary");
        };
        let message = payload
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| payload.downcast_ref::<&str>().map(|msg| (*msg).to_string()))
            .unwrap_or_else(|| "<non-string panic payload>".to_string());
        assert!(
            message.contains("not supported in symbolic Sort wrapper"),
            "Function-sort refusal should name the term boundary seam: {message}"
        );
    }

    #[test]
    fn cf_ite_via_symbolic_value_preserves_sort_neutral_wire_shape() {
        let cond = IrTerm::Ctor {
            name: "match_guard".into(),
            args: vec![var("scrutinee"), var("#pat:abcd")],
        };
        let then_term = var("then_value");
        let else_term = IrTerm::Ctor {
            name: "opaque_else".into(),
            args: vec![var("else_value")],
        };

        let term =
            cf_ite_via_symbolic_value_boundary(cond.clone(), then_term.clone(), else_term.clone());

        assert_eq!(
            term,
            IrTerm::Ctor {
                name: panic_freedom::CF_ITE.to_string(),
                args: vec![cond, then_term, else_term],
            },
            "SymbolicValue boundary route must preserve the old cf_ite congruence carrier"
        );
    }

    #[test]
    fn cf_ite_via_symbolic_value_refuses_unlowerable_operand() {
        let unlowerable = IrTerm::Const {
            value: serde_json::json!(0),
            sort: sugar_ir_types::Sort::Function {
                args: vec![sugar_ir_types::Sort::Primitive { name: "Int".into() }],
                ret: Box::new(sugar_ir_types::Sort::Primitive {
                    name: "Bool".into(),
                }),
            },
        };

        let refusal = std::panic::catch_unwind(|| {
            cf_ite_via_symbolic_value_boundary(var("guard"), unlowerable, var("fallback"))
        });
        let Err(payload) = refusal else {
            panic!("Function-sort cf_ite operand silently crossed the term boundary");
        };
        let message = payload
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| payload.downcast_ref::<&str>().map(|msg| (*msg).to_string()))
            .unwrap_or_else(|| "<non-string panic payload>".to_string());
        assert!(
            message.contains("not supported in symbolic Sort wrapper"),
            "Function-sort refusal should name the term boundary seam: {message}"
        );
    }

    #[test]
    fn tail_if_without_else_keeps_unit_else_through_symbolic_value() {
        let item_fn = parse_fn(
            r#"
            fn f(x: bool) -> i64 {
                if x {
                    1
                }
            }
        "#,
        );

        let eq = result_equation_of(&item_fn).expect("if-tail must synthesize a result equation");
        let IrTerm::Ctor { name, args } = eq else {
            panic!("if-tail did not synthesize cf_ite");
        };
        assert_eq!(name, panic_freedom::CF_ITE);
        let Some(IrTerm::Ctor { name, args }) = args.get(2) else {
            panic!("implicit else branch should be the unit ctor");
        };
        assert_eq!(name, "unit");
        assert!(args.is_empty(), "unit must stay nullary");
    }

    #[test]
    fn if_is_some_lifts_then_to_cf_guarded_is_some_else_to_is_none() {
        // End-to-end through the tail-if lifter: an `if opt.is_some()` produces
        // a cf_ite whose then-branch is cf_guarded(is_some(opt), ..) and whose
        // else-branch is cf_guarded(is_none(opt), ..).
        let item_fn = parse_fn(
            r#"
            fn f(opt: Option<i64>) -> i64 {
                if opt.is_some() {
                    opt.unwrap()
                } else {
                    0
                }
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("if-tail must synthesize a result equation");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(json.contains("cf_ite"), "must lift to a cf_ite: {json}");
        assert!(
            !json.contains("concept:panic-freedom.choice"),
            "Rust v1 emission must keep the old choice carrier: {json}"
        );
        assert!(
            json.contains("cf_guarded"),
            "guarded branches must carry cf_guarded wrappers: {json}"
        );
        assert!(
            !json.contains("concept:panic-freedom.guard"),
            "Rust v1 emission must keep the old cf_guarded carrier: {json}"
        );
        assert!(
            json.contains("is_some"),
            "then-branch guard is is_some: {json}"
        );
        assert!(
            json.contains(panic_freedom::METHOD_UNWRAP),
            "Rust v1 emission must keep the old unwrap leaf token: {json}"
        );
        assert!(
            !json.contains("concept:panic-freedom.leaf.unwrap"),
            "Rust v1 emission must not write the leaf concept alias: {json}"
        );
        assert!(
            !json.contains("concept:panic-freedom.option.some"),
            "Rust v1 emission must keep the old option predicate: {json}"
        );
        assert!(
            json.contains("is_none"),
            "else-branch guard is the complement is_none: {json}"
        );
        assert!(
            !json.contains("concept:panic-freedom.option.none"),
            "Rust v1 emission must keep the old option complement: {json}"
        );
    }

    #[test]
    fn assert_is_some_guards_later_option_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(x: Option<i64>) -> i64 {
                assert!(x.is_some());
                x.unwrap()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "assert!(x.is_some()) must guard the later unwrap: {json}"
        );
        assert!(
            json.contains("is_some"),
            "guard must carry the option precondition: {json}"
        );
    }

    #[test]
    fn assert_is_ok_guards_later_result_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(r: Result<i64, String>) -> i64 {
                assert!(r.is_ok());
                r.unwrap()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "assert!(r.is_ok()) must guard the later unwrap: {json}"
        );
        assert!(
            json.contains("is_ok"),
            "guard must carry the result precondition: {json}"
        );
        assert!(
            json.contains(panic_freedom::METHOD_UNWRAP),
            "Rust v1 writer must keep emitting the old unwrap leaf token: {json}"
        );
        assert!(
            !json.contains("concept:panic-freedom.leaf.unwrap"),
            "Rust v1 writer must not emit the unwrap leaf concept alias: {json}"
        );
        assert!(
            !json.contains("concept:panic-freedom.result.ok"),
            "Rust v1 writer must keep emitting the old result predicate token: {json}"
        );
    }

    #[test]
    fn assert_is_ok_guards_later_result_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(r: Result<i64, String>) -> i64 {
                assert!(r.is_ok());
                r.expect("present")
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("expect must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "assert!(r.is_ok()) must guard the later expect: {json}"
        );
        assert!(
            json.contains("is_ok"),
            "guard must carry the result precondition: {json}"
        );
        assert!(
            json.contains(panic_freedom::METHOD_EXPECT),
            "Rust v1 writer must keep emitting the old expect leaf token: {json}"
        );
        assert!(
            !json.contains("concept:panic-freedom.leaf.expect"),
            "Rust v1 writer must not emit the expect leaf concept alias: {json}"
        );
        assert!(
            !json.contains("concept:panic-freedom.result.ok"),
            "Rust v1 writer must keep emitting the old result predicate token: {json}"
        );
    }

    #[test]
    fn line_less_pure_free_guard_rule_does_not_guard_later_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(x: i64) -> i64 {
                if helper(x).is_some() {
                    helper(x).unwrap()
                } else {
                    0
                }
            }
        "#,
        );
        let rule = PureFreeGuardRule {
            callee: "helper".to_string(),
            post_predicate: panic_freedom::IS_SOME.to_string(),
            source_line: None,
            allow_line_less_match: false,
        };
        let post = lift_function_postcondition_with_return_facts_and_pure_free_guards(
            &item_fn,
            &FunctionReturnFacts::default(),
            &[rule],
        )
        .into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("panic_effect"),
            "a guard rule with no source line must not match every helper(x) callsite: {json}"
        );
    }

    #[test]
    fn match_arm_guarded_panic_effect_is_collected() {
        let item_fn = parse_fn(
            r#"
            fn f(map: BTreeMap<String, String>, choose: bool) {
                for key in map.keys() {
                    match choose {
                        true => {
                            map.get(key).expect("present");
                        }
                        false => {}
                    }
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "guarded panic effect in a match arm must not be silently dropped: {json}"
        );
        assert!(
            json.contains("is_some"),
            "match-arm guard must carry the keyset membership proof: {json}"
        );
    }

    #[test]
    fn len_eq_one_guards_into_iter_next_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(values: Vec<i64>) -> i64 {
                assert!(values.len() == 1);
                values.into_iter().next().unwrap()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "len == 1 must guard into_iter().next().unwrap(): {json}"
        );
        assert!(
            json.contains("is_some"),
            "guard must prove next() returns Some: {json}"
        );
        assert!(
            json.contains("method:next"),
            "guard must name the same next() receiver term: {json}"
        );
    }

    #[test]
    fn keyset_keys_iteration_guards_map_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(map: BTreeMap<String, String>) {
                for key in map.keys() {
                    map.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "map.keys() must guard get(key).expect(): {json}"
        );
        assert!(
            json.contains("is_some") && json.contains("method:get"),
            "guard must prove the same map.get(key) is Some: {json}"
        );
    }

    #[test]
    fn keyset_map_iter_guards_map_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(map: BTreeMap<String, String>) {
                for (key, _) in map.iter() {
                    map.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "map.iter() key binding must guard get(key).expect(): {json}"
        );
        assert!(
            json.contains("is_some") && json.contains("method:get"),
            "guard must prove the same map.get(key) is Some: {json}"
        );
    }

    #[test]
    fn keyset_difference_guards_left_map_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(left: BTreeMap<String, String>, right: BTreeMap<String, String>) {
                let left_keys: BTreeSet<String> = left.keys().cloned().collect();
                let right_keys: BTreeSet<String> = right.keys().cloned().collect();
                for key in left_keys.difference(&right_keys) {
                    left.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "left_keys.difference(right_keys) must guard left.get(key): {json}"
        );
        assert!(
            json.contains("is_some") && json.contains("method:get"),
            "guard must prove the same left.get(key) is Some: {json}"
        );
    }

    #[test]
    fn keyset_intersection_guards_both_map_get_expects() {
        let item_fn = parse_fn(
            r#"
            fn f(left: BTreeMap<String, String>, right: BTreeMap<String, String>) {
                let left_keys: BTreeSet<String> = left.keys().cloned().collect();
                let right_keys: BTreeSet<String> = right.keys().cloned().collect();
                for key in left_keys.intersection(&right_keys) {
                    left.get(key).expect("present");
                    right.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        let guarded_count = json.matches("cf_guarded").count();
        assert!(
            guarded_count >= 2,
            "intersection must guard both left.get(key) and right.get(key): {json}"
        );
        assert!(
            json.contains("is_some") && json.contains("method:get"),
            "guards must prove the get receivers are Some: {json}"
        );
    }

    #[test]
    fn keyset_reused_loop_key_names_are_scoped_in_post_and_panic_loci() {
        let item_fn = parse_fn(
            r#"
            fn f(left: BTreeMap<String, String>, right: BTreeMap<String, String>) {
                for key in left.keys() {
                    left.get(key).expect("present");
                }
                for key in right.keys() {
                    right.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let post_json = serde_json::to_string(&post).unwrap();
        assert!(
            post_json.contains("key#0") && post_json.contains("key#1"),
            "guarded post must preserve distinct loop binders: {post_json}"
        );
        let loci = collect_panic_loci_json(&item_fn, "src/lib.rs");
        assert_eq!(loci.len(), 2, "expected two panic loci: {loci:#?}");
        let key_names = loci
            .iter()
            .map(|locus| {
                locus["argTerm"]["args"][1]["name"]
                    .as_str()
                    .expect("second get arg is key var")
                    .to_string()
            })
            .collect::<BTreeSet<_>>();
        assert_eq!(
            key_names,
            BTreeSet::from(["key#0".to_string(), "key#1".to_string()]),
            "panic loci must use the same scoped loop binders as the post: {loci:#?}"
        );
    }

    #[test]
    fn keyset_wrong_map_does_not_guard_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(left: BTreeMap<String, String>, other: BTreeMap<String, String>) {
                for key in left.keys() {
                    other.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "key provenance from left must not guard other.get(key): {json}"
        );
    }

    #[test]
    fn keyset_difference_reversed_polarity_does_not_guard_right_map_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(left: BTreeMap<String, String>, right: BTreeMap<String, String>) {
                let left_keys: BTreeSet<String> = left.keys().cloned().collect();
                let right_keys: BTreeSet<String> = right.keys().cloned().collect();
                for key in left_keys.difference(&right_keys) {
                    right.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "left minus right must not prove key membership in right: {json}"
        );
    }

    #[test]
    fn keyset_intersection_third_map_does_not_guard_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(
                left: BTreeMap<String, String>,
                right: BTreeMap<String, String>,
                third: BTreeMap<String, String>,
            ) {
                let left_keys: BTreeSet<String> = left.keys().cloned().collect();
                let right_keys: BTreeSet<String> = right.keys().cloned().collect();
                for key in left_keys.intersection(&right_keys) {
                    third.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "intersection must not prove membership in an unrelated map: {json}"
        );
    }

    #[test]
    fn keyset_mutation_between_does_not_guard_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(mut map: BTreeMap<String, String>) {
                for key in map.keys() {
                    map.clear();
                    map.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "mutation between key binding and get must invalidate membership: {json}"
        );
    }

    #[test]
    fn keyset_key_removed_between_does_not_guard_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(mut map: BTreeMap<String, String>) {
                for key in map.keys() {
                    map.remove(key);
                    map.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "removing the current key must invalidate membership: {json}"
        );
    }

    #[test]
    fn keyset_opaque_key_does_not_guard_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(map: BTreeMap<String, String>) {
                for key in map.keys() {
                    map.get(opaque_key()).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "keyset fact must apply only to the bound key expression: {json}"
        );
    }

    #[test]
    fn keyset_opaque_source_does_not_guard_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(map: BTreeMap<String, String>) {
                let keys: BTreeSet<String> = build_keys();
                for key in keys.iter() {
                    map.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "opaque keyset source must not prove map membership: {json}"
        );
    }

    #[test]
    fn keyset_transformed_key_does_not_guard_get_expect() {
        let item_fn = parse_fn(
            r#"
            fn f(map: BTreeMap<String, String>) {
                for key in map.keys() {
                    map.get(key.to_string()).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "transformed keys must not inherit the bound key membership fact: {json}"
        );
    }

    #[test]
    fn keyset_unmodeled_op_default_refuses_get_expect_guard() {
        let item_fn = parse_fn(
            r#"
            fn f(left: BTreeMap<String, String>, right: BTreeMap<String, String>) {
                let left_keys: BTreeSet<String> = left.keys().cloned().collect();
                let right_keys: BTreeSet<String> = right.keys().cloned().collect();
                for key in left_keys.union(&right_keys) {
                    left.get(key).expect("present");
                }
            }
        "#,
        );
        let post = lift_function_postcondition(&item_fn).into_formula();
        let json = serde_json::to_string(&post).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "unmodeled keyset ops must default-refuse instead of guessing: {json}"
        );
    }

    #[test]
    fn if_len_eq_one_guards_then_branch_into_iter_next_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(values: Vec<i64>) -> Option<i64> {
                if values.len() == 1 {
                    Some(values.into_iter().next().unwrap())
                } else {
                    None
                }
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("if-tail must synthesize a result equation");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(json.contains("cf_ite"), "must lift to a cf_ite: {json}");
        assert!(
            json.contains("cf_guarded"),
            "positive len == 1 branch must guard next().unwrap(): {json}"
        );
        assert!(
            json.contains("is_some"),
            "guard must prove next() returns Some: {json}"
        );
        assert!(
            json.contains("method:next"),
            "guard must name the next() receiver term: {json}"
        );
    }

    #[test]
    fn if_len_eq_one_wrong_collection_does_not_guard_next_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(a: Vec<i64>, b: Vec<i64>) -> Option<i64> {
                if a.len() == 1 {
                    Some(b.into_iter().next().unwrap())
                } else {
                    None
                }
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("if-tail must synthesize a result equation");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "len fact for a must not guard b.into_iter().next().unwrap(): {json}"
        );
    }

    #[test]
    fn if_compound_len_eq_one_condition_does_not_guard_next_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(values: Vec<i64>, ready: bool) -> Option<i64> {
                if values.len() == 1 && ready {
                    Some(values.into_iter().next().unwrap())
                } else {
                    None
                }
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("if-tail must synthesize a result equation");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "compound conditions are outside the audited len==1 shape: {json}"
        );
    }

    #[test]
    fn if_len_not_one_does_not_guard_next_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(values: Vec<i64>) -> Option<i64> {
                if values.len() != 0 {
                    Some(values.into_iter().next().unwrap())
                } else {
                    None
                }
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("if-tail must synthesize a result equation");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "len != 0 does not establish the exact len==1 iterator fact: {json}"
        );
    }

    #[test]
    fn no_assert_does_not_guard_option_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(x: Option<i64>) -> i64 {
                x.unwrap()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "unguarded unwrap must remain honestly undecidable: {json}"
        );
    }

    #[test]
    fn unrelated_assert_does_not_guard_option_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(x: Option<i64>, ready: bool) -> i64 {
                assert!(ready);
                x.unwrap()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "unrelated assert must not guard x.unwrap(): {json}"
        );
    }

    #[test]
    fn different_receiver_assert_does_not_guard_option_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(x: Option<i64>, y: Option<i64>) -> i64 {
                assert!(y.is_some());
                x.unwrap()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "assert about y must not guard x.unwrap(): {json}"
        );
    }

    #[test]
    fn mutation_after_assert_does_not_guard_option_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(mut x: Option<i64>) -> i64 {
                assert!(x.is_some());
                x = None;
                x.unwrap()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "mutation after assert must invalidate the guard fact: {json}"
        );
    }

    #[test]
    fn branch_local_assert_does_not_guard_outer_unwrap() {
        let item_fn = parse_fn(
            r#"
            fn f(x: Option<i64>, cond: bool) -> i64 {
                if cond {
                    assert!(x.is_some());
                }
                x.unwrap()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "branch-local assert must not guard an outer unwrap: {json}"
        );
    }

    #[test]
    fn json_string_field_unwrap_carries_is_some_guard_fact() {
        let item_fn = parse_fn(
            r#"
            fn f(from_catalog_cid: String) -> String {
                let body = json!({
                    "fromCatalogCid": from_catalog_cid
                });
                let payload = json!({
                    "fromCatalogCid": body["fromCatalogCid"].clone()
                });
                payload["fromCatalogCid"].as_str().unwrap().to_string()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("json unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            json.contains("cf_guarded"),
            "json string construction must carry an opaque guard fact: {json}"
        );
        assert!(
            json.contains("is_some"),
            "json string construction must prove as_str() is Some: {json}"
        );
        assert!(
            json.contains("fromCatalogCid"),
            "guard must name the same indexed JSON field: {json}"
        );
    }

    #[test]
    fn dynamic_json_construction_does_not_carry_guard_fact() {
        let item_fn = parse_fn(
            r#"
            fn f() -> String {
                let payload = make_payload();
                payload["value"].as_str().unwrap().to_string()
            }
        "#,
        );
        let eq = result_equation_of(&item_fn).expect("dynamic unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "opaque dynamic construction must stay honestly unguarded: {json}"
        );
    }

    #[test]
    fn numeric_json_field_does_not_carry_string_guard_fact() {
        let item_fn = parse_fn(
            r#"
            fn f() -> String {
                let payload = json!({
                    "value": 7
                });
                payload["value"].as_str().unwrap().to_string()
            }
        "#,
        );
        let eq =
            result_equation_of(&item_fn).expect("wrong-type unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "numeric JSON fields must not prove as_str() is Some: {json}"
        );
    }

    #[test]
    fn mutable_json_binding_does_not_carry_guard_fact() {
        let item_fn = parse_fn(
            r#"
            fn f() -> String {
                let mut payload = json!({
                    "value": "ok"
                });
                payload["value"].as_str().unwrap().to_string()
            }
        "#,
        );
        let eq =
            result_equation_of(&item_fn).expect("mutable JSON unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "mutable JSON construction must stay honestly unguarded: {json}"
        );
    }

    #[test]
    fn match_assignment_invalidates_json_guard_fact() {
        let item_fn = parse_fn(
            r#"
            fn f(flag: bool) -> String {
                let mut payload = json!({
                    "value": "ok"
                });
                match flag {
                    true => {
                        payload["value"] = json!(7);
                    }
                    false => {}
                }
                payload["value"].as_str().unwrap().to_string()
            }
        "#,
        );
        let eq =
            result_equation_of(&item_fn).expect("match-mutated unwrap must remain in result term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "match assignment must invalidate stale JSON field facts: {json}"
        );
    }

    #[test]
    fn unknown_json_field_propagation_does_not_carry_guard_fact() {
        let item_fn = parse_fn(
            r#"
            fn f() -> String {
                let body = json!({
                    "value": opaque()
                });
                let payload = json!({
                    "value": body["value"].clone()
                });
                payload["value"].as_str().unwrap().to_string()
            }
        "#,
        );
        let eq =
            result_equation_of(&item_fn).expect("unknown propagated unwrap must remain in term");
        let json = serde_json::to_string(&eq).unwrap();
        assert!(
            !json.contains("cf_guarded"),
            "unknown field kind must remain unknown through clone propagation: {json}"
        );
    }

    /// THE reformat-canonicality bug. `fn double(x){ let n = x; n*2 }` used to
    /// leak the local name `n` into the post (`result = n*2`, free `n`), moving
    /// the behavior identity away from the inline form `x*2`. The fix: emit the
    /// leading `let` as a faithful `IrTerm::Let` (the kit emits data), which the
    /// CLI canonicalizer inlines so both surface shapes share one identity.
    #[test]
    fn leading_let_reformat_shares_behavior_identity() {
        use sugar_ir_types::canonicalize_property;

        let inline =
            lift_function_postcondition(&parse_fn(r#"fn double(x: i64) -> i64 { x * 2 }"#))
                .into_formula();
        let reformat = lift_function_postcondition(&parse_fn(
            r#"fn double(x: i64) -> i64 { let n = x; n * 2 }"#,
        ))
        .into_formula();

        // The kit emits the let FAITHFULLY (no pre-resolution): the result
        // term is an `IrTerm::Let`, not a leaked free `n`.
        let rhs = libsugar::wp::find_result_equation(&reformat, "result")
            .expect("reformat has a result equation");
        assert!(
            matches!(rhs, IrTerm::Let { .. }),
            "leading let must be emitted as a faithful IrTerm::Let, got {rhs:?}"
        );

        // The CLI canonicalizer inlines the pure let: inline and reformat share
        // ONE behavior identity.
        let ci = canonicalize_property(&inline, &["x".to_string()], "result");
        let cr = canonicalize_property(&reformat, &["x".to_string()], "result");
        assert_eq!(
            ci, cr,
            "inline x*2 and let-reformat must canonicalize to the same behavior"
        );

        // A genuine behavior change (x*3) must NOT be identified with x*2.
        let changed = lift_function_postcondition(&parse_fn(
            r#"fn double(x: i64) -> i64 { let n = x; n * 3 }"#,
        ))
        .into_formula();
        let cc = canonicalize_property(&changed, &["x".to_string()], "result");
        assert_ne!(
            ci, cc,
            "a real behavior change (x*3) must not share x*2's identity"
        );
    }

    /// An unrelated leading `let` the tail never touches must NOT change the
    /// emitted term: `fn f(x){ let _k = 99; x*2 }` still emits a bare `x*2`.
    #[test]
    fn unreferenced_leading_let_is_not_wrapped() {
        let post =
            lift_function_postcondition(&parse_fn(r#"fn f(x: i64) -> i64 { let k = 99; x * 2 }"#))
                .into_formula();
        let rhs =
            libsugar::wp::find_result_equation(&post, "result").expect("has a result equation");
        assert!(
            !matches!(rhs, IrTerm::Let { .. }),
            "an unreferenced leading let must not wrap the result term, got {rhs:?}"
        );
    }

    /// Explicit `return` gets the same leading-let reattachment as the trailing
    /// expression form: `let n = x; return n*2;` must NOT leak `n`.
    #[test]
    fn explicit_return_reformat_shares_behavior_identity() {
        use sugar_ir_types::canonicalize_property;
        let inline =
            lift_function_postcondition(&parse_fn(r#"fn double(x: i64) -> i64 { x * 2 }"#))
                .into_formula();
        let ret = lift_function_postcondition(&parse_fn(
            r#"fn double(x: i64) -> i64 { let n = x; return n * 2; }"#,
        ))
        .into_formula();
        let rhs = libsugar::wp::find_result_equation(&ret, "result")
            .expect("return has a result equation");
        assert!(
            matches!(rhs, IrTerm::Let { .. }),
            "explicit return must reattach the leading let, got {rhs:?}"
        );
        assert_eq!(
            canonicalize_property(&inline, &["x".to_string()], "result"),
            canonicalize_property(&ret, &["x".to_string()], "result"),
            "`let n=x; return n*2` must share x*2's behavior identity"
        );
    }

    /// Chained leading lets emit NESTED single-binding lets (not one
    /// multi-binding let): SMT-LIB `let` is parallel, so `(let ((a x)(b (+ a 1)))
    /// ..)` would leave `b`'s `a` free. Nesting keeps sequential semantics, and
    /// the chained locals inline away to a behavior over the parameter alone.
    #[test]
    fn chained_leading_lets_emit_nested_single_binding_lets() {
        let post = lift_function_postcondition(&parse_fn(
            r#"fn f(x: i64) -> i64 { let a = x; let b = a + 1; b * 2 }"#,
        ))
        .into_formula();
        let rhs =
            libsugar::wp::find_result_equation(&post, "result").expect("has a result equation");
        let IrTerm::Let { bindings, body } = &rhs else {
            panic!("expected an outer let, got {rhs:?}");
        };
        assert_eq!(
            bindings.len(),
            1,
            "must be single-binding nested lets, not a parallel multi-binding let"
        );
        assert_eq!(bindings[0].name, "a");
        assert!(
            matches!(&*body.clone(), IrTerm::Let { .. }),
            "inner term must be another single-binding let, got {body:?}"
        );
        // After canonicalization the chained locals are gone: behavior is over x.
        let canon = sugar_ir_types::canonicalize_formula(&post);
        let fv = free_vars_formula(&canon);
        assert!(
            !fv.contains("a") && !fv.contains("b"),
            "chained locals must inline away, free vars were {fv:?}"
        );
    }

    /// A later MUTABLE binding that shadows an earlier immutable one must NOT be
    /// wrapped: `let n=x; let mut n=x+1; n*2` returns (x+1)*2, and binding the
    /// tail's `n` to the first `let n=x` would assert a FALSE identity with x*2.
    #[test]
    fn mutable_shadow_is_refused_no_false_identity() {
        use sugar_ir_types::canonicalize_property;
        let inline = lift_function_postcondition(&parse_fn(r#"fn f(x: i64) -> i64 { x * 2 }"#))
            .into_formula();
        let shadow = lift_function_postcondition(&parse_fn(
            r#"fn f(x: i64) -> i64 { let n = x; let mut n = x + 1; n * 2 }"#,
        ))
        .into_formula();
        let rhs =
            libsugar::wp::find_result_equation(&shadow, "result").expect("has a result equation");
        assert!(
            !matches!(rhs, IrTerm::Let { .. }),
            "a mutable shadow must bail (no wrap), got {rhs:?}"
        );
        assert_ne!(
            canonicalize_property(&inline, &["x".to_string()], "result"),
            canonicalize_property(&shadow, &["x".to_string()], "result"),
            "the (x+1)*2 mutable-shadow body must NOT share x*2's identity"
        );
    }

    /// A rebound (shadowed) name bails entirely: `let x=0; let x=input; x*2`
    /// has a dead first binding; we refuse to wrap rather than keep it.
    #[test]
    fn liftable_shadow_is_refused() {
        let post = lift_function_postcondition(&parse_fn(
            r#"fn f(input: i64) -> i64 { let x = 0; let x = input; x * 2 }"#,
        ))
        .into_formula();
        let rhs =
            libsugar::wp::find_result_equation(&post, "result").expect("has a result equation");
        assert!(
            !matches!(rhs, IrTerm::Let { .. }),
            "a rebound/shadowed name must bail, got {rhs:?}"
        );
    }

    // --- impure-let discrimination (3 per the per-variant discipline) ---

    /// STRUCTURAL: a `let` whose initializer is an effectful/opaque call
    /// (`it.next()` -> `method:next`) is NOT captured -- the result term is left
    /// referencing the free local, not an `IrTerm::Let`. Inlining it would
    /// duplicate the effect.
    #[test]
    fn impure_let_init_is_not_wrapped() {
        let post = lift_function_postcondition(&parse_fn(
            r#"fn f(it: &mut It) -> i64 { let n = it.next(); n + 1 }"#,
        ))
        .into_formula();
        let rhs =
            libsugar::wp::find_result_equation(&post, "result").expect("has a result equation");
        assert!(
            !matches!(rhs, IrTerm::Let { .. }),
            "an effectful (method-call) let init must not be wrapped, got {rhs:?}"
        );
    }

    /// DISCRIMINATION (the soundness keystone): binding an effectful call ONCE
    /// and using it twice (`let n = it.next(); n + n` -- one advance, doubled)
    /// must NOT share a behavior identity with calling it twice
    /// (`it.next() + it.next()` -- two advances). The impurity guard keeps the
    /// call abstracted to a free local rather than inlining it into both
    /// positions.
    #[test]
    fn impure_let_used_twice_is_not_identified_with_double_eval() {
        use sugar_ir_types::canonicalize_property;
        let bound_once = lift_function_postcondition(&parse_fn(
            r#"fn f(it: &mut It) -> i64 { let n = it.next(); n + n }"#,
        ))
        .into_formula();
        let called_twice = lift_function_postcondition(&parse_fn(
            r#"fn f(it: &mut It) -> i64 { it.next() + it.next() }"#,
        ))
        .into_formula();
        assert_ne!(
            canonicalize_property(&bound_once, &["it".to_string()], "result"),
            canonicalize_property(&called_twice, &["it".to_string()], "result"),
            "one effectful call bound and used twice must NOT equal two effectful calls"
        );
    }

    /// POSITIVE (the guard does not over-refuse): a PURE init that is used twice
    /// (`let n = x + 1; n * n`) is still wrapped and still shares its identity
    /// with the inline form `(x+1) * (x+1)` -- pure terms are freely duplicable.
    #[test]
    fn pure_let_used_twice_is_still_identified() {
        use sugar_ir_types::canonicalize_property;
        let bound = lift_function_postcondition(&parse_fn(
            r#"fn f(x: i64) -> i64 { let n = x + 1; n * n }"#,
        ))
        .into_formula();
        let inline =
            lift_function_postcondition(&parse_fn(r#"fn f(x: i64) -> i64 { (x + 1) * (x + 1) }"#))
                .into_formula();
        let rhs =
            libsugar::wp::find_result_equation(&bound, "result").expect("has a result equation");
        assert!(
            matches!(rhs, IrTerm::Let { .. }),
            "a pure let init must still be wrapped, got {rhs:?}"
        );
        assert_eq!(
            canonicalize_property(&bound, &["x".to_string()], "result"),
            canonicalize_property(&inline, &["x".to_string()], "result"),
            "a pure let used twice must share the inline form's identity"
        );
    }
}
