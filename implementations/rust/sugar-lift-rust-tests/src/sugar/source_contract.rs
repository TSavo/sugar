// SPDX-License-Identifier: Apache-2.0
//
// Source-contract emission Sugar: compose source-backed function contracts from
// existing term, bool, and constraint floors. The crate root re-exports the
// public entrypoints; this module owns the source-value semantic reduction.

use std::collections::BTreeSet;
use std::rc::Rc;

use sugar_ir_symbolic::{
    and_, atomic_, eq, gte, implies, lt, lte, make_var, not_, num, or_, str_const, ContractDecl,
    Formula, Term,
};
use syn::parse::ParseStream;
use syn::{BinOp, Expr, ExprLit, Item, Lit, Pat, Stmt, Token, UnOp};

use crate::sugar::block_sugar::block_stmt_to_formula;
use crate::sugar::catalog::build_stmt_role;
use crate::sugar::claim::SugarRole;
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    bool_const, parse_int_lit, path_to_variant_string, source_assertion_entries_in_stmts,
    subst_var_in_formula, subst_var_in_term, sugar_ctx_with_factory_audits,
    temporal_plan_for_stmts, translate_term_in_scope, Desugared, FloatWidthScope, LiftOptions,
    Outcome, ReductionCtx, TemporalScope,
};

// ── Source-audit value-contract emission ────────────────────────────────────
// A source warrant is REAL only if the kit EMITS the ProofIR contract for the
// body -- a syntactic "looks generalizable" flag with no emitted relation is a
// hollow warrant. `emit_value_contract` walks a value-function body into a
// closed consistency `ContractDecl`, mirroring the Python source kit's
// `_lift_function` (walk body -> term/formula, wrap as `return_value = body`) in
// the rust kit's inv-only form (`out` is the return value). It reuses the SAME
// term/formula atoms the test-assertion path already compiles to Z3 -- no new
// semantic path. Returns None when the body is not (yet) emittable; the caller
// then leaves the function UNCLASSIFIED (the honest dark), never warranted.
//
// Slice 1 -- the character-classification predicate shape (`is_ascii_*` family):
// a bool-returning body that reduces to `matches!(<scalar>, <pattern>)` (and
// `&&`/`||`/`!` trees thereof). The pattern is walked -- not the function name
// (names are sugar) -- into a range/equality membership formula, the same shape
// `ascii_byte_class_atom` proves. The contract is the biconditional
// `out <-> membership` (encoded with `implies`/`and`, since the compiler has no
// `iff`).
pub fn emit_value_contract(name: &str, block: &syn::Block) -> Option<ContractDecl> {
    let plan = temporal_plan_for_stmts(&block.stmts, &BTreeSet::new());
    let scope = TemporalScope::new("rust-source", plan);
    block_inv(block, &scope).map(|inv| source_value_contract(name, inv))
}

fn emit_source_assertion_contract(name: &str, block: &syn::Block) -> Option<ContractDecl> {
    let plan = temporal_plan_for_stmts(&block.stmts, &BTreeSet::new());
    let scope = TemporalScope::new("rust-source", plan);
    let options = LiftOptions::default();
    let items: Vec<Item> = Vec::new();
    let reducer = ReductionCtx::from_items(&items);
    let entries = source_assertion_entries_in_stmts(&block.stmts, &scope, &options, &reducer, None);
    if entries.is_empty() {
        return None;
    }
    Some(source_value_contract(
        name,
        and_(entries.into_iter().map(|entry| entry.entry.atom).collect()),
    ))
}

fn emit_callable_param_precondition_contract(
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<ContractDecl> {
    let param_names = sig_param_name_set(sig);
    if param_names.is_empty() {
        return None;
    }
    let plan = temporal_plan_for_stmts(&block.stmts, &BTreeSet::new());
    let scope = TemporalScope::new("rust-source", plan);
    let mut visitor = CallableParamPreconditionVisitor {
        param_names: &param_names,
        scope: &scope,
        atoms: Vec::new(),
    };
    syn::visit::Visit::visit_block(&mut visitor, block);
    if visitor.atoms.is_empty() {
        return None;
    }
    let mut decl = source_value_contract(name, atomic_("true", Vec::new()));
    decl.inv = None;
    decl.pre = Some(and_(visitor.atoms));
    Some(decl)
}

struct CallableParamPreconditionVisitor<'a> {
    param_names: &'a BTreeSet<String>,
    scope: &'a TemporalScope,
    atoms: Vec<Rc<Formula>>,
}

impl CallableParamPreconditionVisitor<'_> {
    fn callable_param_name(&self, expr: &Expr) -> Option<String> {
        match expr {
            Expr::Path(path) if path.qself.is_none() => path
                .path
                .segments
                .last()
                .map(|segment| segment.ident.to_string())
                .filter(|name| self.param_names.contains(name)),
            Expr::Paren(paren) => self.callable_param_name(&paren.expr),
            Expr::Group(group) => self.callable_param_name(&group.expr),
            _ => None,
        }
    }

    fn callsite_precondition(&self, call: &syn::ExprCall) -> Option<Rc<Formula>> {
        let name = self.callable_param_name(&call.func)?;
        let mut args = Vec::with_capacity(call.args.len());
        for arg in &call.args {
            args.push(translate_term_in_scope(arg, self.scope).ok()?);
        }
        let subject = Rc::new(Term::Ctor {
            name: format!("call:{name}"),
            args,
        });
        Some(not_(atomic_("panic", vec![subject])))
    }
}

impl<'ast> syn::visit::Visit<'ast> for CallableParamPreconditionVisitor<'_> {
    fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
        if let Some(atom) = self.callsite_precondition(call) {
            self.atoms.push(atom);
        }
        syn::visit::visit_expr_call(self, call);
    }

    fn visit_expr_closure(&mut self, _closure: &'ast syn::ExprClosure) {}

    fn visit_expr_async(&mut self, _async_block: &'ast syn::ExprAsync) {}

    fn visit_item_fn(&mut self, _function: &'ast syn::ItemFn) {}
}

/// The BROAD warrant: every value body warrants, down to bare functionality.
/// Either we THINK it constrains (so warrant it -- dumbly, opaquely if need be)
/// or it NEVER constrains (no output -> None, the caller refuses by vacuity).
/// There is no swamp in between.
///
/// Order = strongest constraint first: the STRUCTURAL lift (`emit_value_contract`
/// -- membership, bounded universes, value-ifs, EUF terms: strong teeth), then
/// the DUMB functional fallback `out = call:NAME(params)` -- "out is a
/// deterministic function of the inputs" (weak teeth: bites only nondeterminism,
/// but still a real vendor DEMAND). A unit-returning body has no output to
/// constrain -> None.
///
/// Safe to be this dumb because the vendor is the referee (see the keystone): a
/// bogus broad warrant either finds no pin (harmless, unrefuted) or goes
/// all-UNSAT and self-retracts; it can only become a finding after a SAT
/// licenses it. We never have to PROVE the lift sound -- the check does.
pub fn broad_functional_warrant(
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<ContractDecl> {
    let assertion_decl = emit_source_assertion_contract(name, block);
    let callable_pre_decl = emit_callable_param_precondition_contract(name, sig, block);
    // Try encoder body Sugar (str.eq-bv-blocks) BEFORE the generic structural
    // lift. This produces strong symbolic teeth for functional string-encoder
    // bodies (const table + ord byte-assigns + subscript-concat return).
    if let Some(encoder_atom) =
        super::generic_body_sugar::recognize_and_emit_encoder_contract(name, sig, block)
    {
        let mut decl = source_value_contract(name, encoder_atom);
        if let Some(ref pre_decl) = callable_pre_decl {
            decl.pre = pre_decl.pre.clone();
        }
        return Some(decl);
    }
    if !block_has_for_loop(block) {
        if let Some(mut value_decl) = emit_value_contract(name, block) {
            if let Some(assertion_decl) = assertion_decl {
                let mut atoms = Vec::new();
                if let Some(inv) = value_decl.inv.take() {
                    atoms.push(inv);
                }
                if let Some(inv) = assertion_decl.inv {
                    atoms.push(inv);
                }
                value_decl.inv = Some(and_(atoms));
            }
            if let Some(callable_pre_decl) = callable_pre_decl {
                value_decl.pre = callable_pre_decl.pre;
            }
            return Some(value_decl); // structural -- strongest teeth
        }
    }
    if let Some(assertion_decl) = assertion_decl {
        if sig_returns_unit(sig) {
            let mut decl = assertion_decl;
            if let Some(callable_pre_decl) = callable_pre_decl {
                decl.pre = callable_pre_decl.pre;
            }
            return Some(decl);
        }
        let fallback = eq(
            make_var("out"),
            Rc::new(Term::Ctor {
                name: format!("call:{name}"),
                args: sig_param_vars(sig),
            }),
        );
        let inv = assertion_decl
            .inv
            .unwrap_or_else(|| atomic_("true", Vec::new()));
        let mut decl = source_value_contract(name, and_(vec![inv, fallback]));
        if let Some(callable_pre_decl) = callable_pre_decl {
            decl.pre = callable_pre_decl.pre;
        }
        return Some(decl);
    }
    if sig_returns_unit(sig) {
        if callable_pre_decl.is_some() {
            return callable_pre_decl;
        }
        return None; // no output to constrain -> the caller refuses by vacuity
    }
    // Bare functionality: out = call:NAME(params). The fn name keys it to the
    // vendor's call-site pins (intra-kit; CID-canonicalization is downstream).
    let term = Rc::new(Term::Ctor {
        name: format!("call:{name}"),
        args: sig_param_vars(sig),
    });
    let mut decl = source_value_contract(name, eq(make_var("out"), term));
    if let Some(callable_pre_decl) = callable_pre_decl {
        decl.pre = callable_pre_decl.pre;
    }
    Some(decl)
}

fn block_has_for_loop(block: &syn::Block) -> bool {
    struct ForLoopVisitor {
        seen: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for ForLoopVisitor {
        fn visit_expr_for_loop(&mut self, _node: &'ast syn::ExprForLoop) {
            self.seen = true;
        }
    }
    let mut visitor = ForLoopVisitor { seen: false };
    syn::visit::Visit::visit_block(&mut visitor, block);
    visitor.seen
}

/// True iff the signature returns `()` (explicit or default) -- no output to
/// constrain. Mirrored in the RPC bin's classifier.
pub fn sig_returns_unit(sig: &syn::Signature) -> bool {
    match &sig.output {
        syn::ReturnType::Default => true,
        syn::ReturnType::Type(_, ty) => matches!(&**ty, syn::Type::Tuple(t) if t.elems.is_empty()),
    }
}

/// The bound parameter names as EUF vars: a receiver -> `self`, a simple
/// `ident: T` -> `ident`. Destructuring/complex param patterns are skipped (they
/// only weaken the opaque functional term, never make it unsound).
fn sig_param_vars(sig: &syn::Signature) -> Vec<Rc<Term>> {
    sig.inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Receiver(_) => Some(make_var("self")),
            syn::FnArg::Typed(pt) => match &*pt.pat {
                syn::Pat::Ident(id) => Some(make_var(id.ident.to_string())),
                _ => None,
            },
        })
        .collect()
}

fn sig_param_name_set(sig: &syn::Signature) -> BTreeSet<String> {
    sig.inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Receiver(_) => Some("self".to_string()),
            syn::FnArg::Typed(pt) => match &*pt.pat {
                syn::Pat::Ident(id) => Some(id.ident.to_string()),
                _ => None,
            },
        })
        .collect()
}

/// The new-doctrine check: conjoin a body's emitted warrant with a VENDOR pin --
/// the sworn output at concrete arguments -- and hand the conjunction to the
/// solver. We do NOT analyze the body's effects, order, or interior; we
/// INSTANTIATE the warrant `out = <body over params>` at the vendor call's
/// argument bindings, conjoin the vendor's asserted output `out = <answer>`, and
/// let z3 be the only referee:
///   SAT   -> the warranted constraint coexists with the sworn answer; the warrant
///            holds, and the interior mess never mattered.
///   UNSAT -> the derived constraint cannot coexist with the sworn answer -> the
///            warrant (or the impl) is refuted -> REFUSE, carrying the
///            contradiction. Nondeterminism/mutation self-surface here too: the
///            same arguments pinned to two different vendor answers conjoin to
///            UNSAT under the functional warrant.
/// `bindings` maps the body's parameter names to the vendor call's integer
/// arguments; `asserted_out` is the vendor's sworn integer return value. Returns
/// the conjoined `ContractDecl` for the solver, or None if the body emitted no
/// warrant (nothing to check against the vendor).
pub fn warrant_conjoined_with_vendor(
    decl: &ContractDecl,
    bindings: &[(&str, i64)],
    asserted_out: i64,
) -> ContractDecl {
    let term_bindings: Vec<(&str, Rc<Term>)> = bindings
        .iter()
        .map(|(n, v)| (*n, num(i128::from(*v))))
        .collect();
    warrant_conjoined_with_vendor_terms(decl, &term_bindings, num(i128::from(asserted_out)))
}

/// General form: instantiate the body warrant at arbitrary scalar argument TERMS
/// (int / bool / string / ...), then conjoin the vendor's sworn output term. The
/// `i64` form above is the int special case. Same closed check (substitute the
/// params, conjoin `out == asserted_out`); the interior is an unopened EUF box.
pub fn warrant_conjoined_with_vendor_terms(
    decl: &ContractDecl,
    bindings: &[(&str, Rc<Term>)],
    asserted_out: Rc<Term>,
) -> ContractDecl {
    let mut inv = decl
        .inv
        .clone()
        .unwrap_or_else(|| atomic_("true", Vec::new()));
    for (name, value) in bindings {
        inv = subst_var_in_formula(&inv, name, value);
    }
    let conjoined = and_(vec![inv, eq(make_var("out"), asserted_out)]);
    ContractDecl {
        inv: Some(conjoined),
        ..decl.clone()
    }
}

/// The consistency `inv` for a block.
///
/// Fast paths (in order):
///   1. Single tail expression -> `tail_inv` (the most common case).
///   2. Leading immutable `let` prefix + tail -> `let_prefix_inv`.
///   3. Everything else (guard-clause, if/else, nested if, mixed stmts) ->
///      `block_stmt_inv` which routes through the factory's BlockSugar.
///
/// Law: `block_inv` is the ONLY caller of `emit_guard_return_value`'s replacement
/// (`block_stmt_inv`). No other function iterates stmts to build a Formula by hand.
fn block_inv(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Formula>> {
    if let [Stmt::Expr(tail, None)] = block.stmts.as_slice() {
        return tail_inv(tail, scope);
    }
    if let Some(inv) = let_prefix_inv(block, scope) {
        return Some(inv);
    }
    if block.stmts.last().is_some_and(
        |stmt| matches!(stmt, Stmt::Expr(tail, None) if is_non_term_control_expr(tail)),
    ) {
        return None;
    }
    block_stmt_inv(block, scope)
}

/// Factory-based block -> Formula conversion. Wraps the block as a
/// `Stmt::Expr(Expr::Block(..))` and dispatches through `build_stmt_role` ->
/// BlockSugar, then converts the resulting fully routed
/// `StmtBlock { guarded, raises, .. }` to a conjunction of
/// `implies(guards, eq(out, term))` clauses. Residual raises refuse formula
/// emission instead of being silently dropped.
///
/// This SUBSUMES `emit_guard_return_value`: the narrow guard-clause shape
/// (`(if COND { return v; })+ tail`) is now just a special case of the general
/// BlockSugar composition path, which also handles if/else and nested if.
fn block_stmt_inv(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let block_stmt = Stmt::Expr(
        Expr::Block(syn::ExprBlock {
            attrs: vec![],
            label: None,
            block: block.clone(),
        }),
        None,
    );
    let options = LiftOptions::default();
    let let_inits = std::collections::BTreeMap::new();
    let items: Vec<Item> = Vec::new();
    let fcx = SugarBuildCtx::new(scope, &options, &let_inits);
    let block_node = build_stmt_role(&block_stmt, &fcx, SugarRole::Statement);
    let reducer = ReductionCtx::from_items_with_imports(&items, scope.macro_registry());
    let mut float_widths = FloatWidthScope::new();
    let ctx = sugar_ctx_with_factory_audits(scope, &options, &reducer, &mut float_widths, 0, None);
    match block_node.reduce(&ctx) {
        Outcome::Complete(Desugared::StmtBlock {
            guarded, raises, ..
        }) => block_stmt_to_formula(guarded, raises),
        _ => None,
    }
}

/// The consistency `inv` for a SINGLE tail expression (no prefix). Tries, in
/// order: bool-membership universe (matches!), bounded-output universe (clamp),
/// EUF value term (incl. method-call-as-EUF), value-if chain, scalar match, and
/// bool predicate (comparison/&&/||). None if the tail is none of these.
fn tail_inv(tail: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    // Slice 14 -- `unsafe { .. }` / plain `{ .. }` are VALUE-TRANSPARENT: the inv
    // is the inner block's inv (unsafe is a compile-time obligation, not a value
    // transform). Unwrap before the per-shape branches.
    if let Expr::Unsafe(u) = tail {
        return block_inv(&u.block, scope);
    }
    if let Expr::Block(b) = tail {
        return block_inv(&b.block, scope);
    }
    if let Expr::Paren(p) = tail {
        return tail_inv(&p.expr, scope);
    }
    if let Expr::Group(g) = tail {
        return tail_inv(&g.expr, scope);
    }
    // (a) Slice 1 -- matches! membership: out <-> m.
    if let Some(membership) = emit_bool_membership_formula(tail, scope) {
        return Some(biconditional_out(membership));
    }
    // (b) Slice 4 -- bounded-output universe (clamp), BEFORE the EUF path so the
    //     bound's teeth aren't shadowed by an opaque `out = clamp(..)`.
    if let Some(universe) = bounded_output_universe(tail, scope) {
        return Some(universe);
    }
    // (e) Slice 8 -- value-position if / else-if / else -> ite via implies/and.
    if let Some(inv) = emit_if_value(tail, scope) {
        return Some(inv);
    }
    // (g) Slice 10 -- value-position scalar match (literal/range/_ arms) -> ite.
    if let Some(inv) = emit_match_value(tail, scope) {
        return Some(inv);
    }
    if is_non_term_control_expr(tail) {
        return None;
    }
    // (f) Slice 9 -- bool-predicate body (comparison / && / || / !), GATED so it
    //     can't mis-accept a non-bool call as a predicate. out <-> F. This runs
    //     before the EUF-term path because value-contract boolean predicates own
    //     comparisons/connectives in this position; term-position `cmp:*` ctors are
    //     for nested values, not the returned bool relation itself.
    if is_bool_shaped_expr(tail) {
        if let Ok(entry) = crate::sugar::constraint::assertion_entry_with_audits(
            tail,
            scope,
            &FloatWidthScope::new(),
            None,
        ) {
            return Some(biconditional_out(entry.atom));
        }
    }
    if contains_builtin_matches_expr(tail) {
        return None;
    }
    // (c) Slice 2/5 -- value-term + method-call-as-EUF: out = <euf term>.
    if let Ok(term) = translate_term_in_scope(tail, scope) {
        if term_is_euf_value(&term) {
            return Some(eq(make_var("out"), term));
        }
    }
    None
}

/// `out <-> F`, encoded as (out=true => F) ∧ (F => out=true) (no `iff` in the
/// compiler).
fn biconditional_out(f: Rc<Formula>) -> Rc<Formula> {
    let out_true = atomic_("=", vec![make_var("out"), bool_const(true)]);
    and_(vec![
        implies(out_true.clone(), f.clone()),
        implies(f, out_true),
    ])
}

/// Slice 6/11: a body `(let <ident> = <euf>;)* <tail>` -- collect the immutable
/// let substitution, compute the TAIL's inv (any single-tail shape), then
/// substitute the lets into that Formula (referential transparency over
/// deterministic EUF terms). None if any binding is mut / let-else / shadowing /
/// non-EUF, the prefix is empty (single-tail handled above), or the tail has no inv.
fn let_prefix_inv(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let (last, prefix) = block.stmts.split_last()?;
    let Stmt::Expr(tail_expr, None) = last else {
        return None;
    };
    if prefix.is_empty() {
        return None;
    }
    let subst = collect_let_subst(prefix, scope)?;
    let mut inv = tail_inv(tail_expr, scope)?;
    for (n, t) in &subst {
        inv = subst_var_in_formula(&inv, n, t);
    }
    Some(inv)
}

/// Collect the substitution map for a leading immutable-`let` prefix: each
/// `let <ident> = <euf>;` becomes (name -> EUF term), earlier bindings
/// substituted into later RHSs. None if any statement is not such a `let`
/// (mut / ref / destructuring / let-else / shadowing / non-EUF RHS).
fn collect_let_subst(prefix: &[Stmt], scope: &TemporalScope) -> Option<Vec<(String, Rc<Term>)>> {
    let mut subst: Vec<(String, Rc<Term>)> = Vec::new();
    for stmt in prefix {
        let Stmt::Local(local) = stmt else {
            return None;
        };
        let init = local.init.as_ref()?;
        if init.diverge.is_some() {
            return None;
        }
        let mut rhs = translate_term_in_scope(&init.expr, scope).ok()?;
        for (n, t) in &subst {
            rhs = subst_var_in_term(&rhs, n, t);
        }
        if !term_is_euf_value(&rhs) {
            return None;
        }
        for (name, term) in let_bindings(&local.pat, &rhs)? {
            if subst.iter().any(|(n, _)| n == &name) {
                return None; // shadowing breaks sequential substitution
            }
            subst.push((name, term));
        }
    }
    Some(subst)
}

/// The (name -> term) bindings a `let <pat> = <rhs>` introduces. A simple ident
/// binds the whole rhs; a tuple destructuring `let (a, _, c) = rhs` binds each
/// position i to the uninterpreted projection `field:i(rhs)` (the same accessor
/// the kit's `Expr::Field` translation uses, so `let (a,_) = t; a` is congruent
/// with `t.0`). `mut` / `ref` / nested sub-patterns are refused (None).
fn let_bindings(pat: &Pat, rhs: &Rc<Term>) -> Option<Vec<(String, Rc<Term>)>> {
    match pat {
        Pat::Ident(id) if id.subpat.is_none() && id.mutability.is_none() && id.by_ref.is_none() => {
            Some(vec![(id.ident.to_string(), rhs.clone())])
        }
        Pat::Type(t) => let_bindings(&t.pat, rhs),
        Pat::Paren(p) => let_bindings(&p.pat, rhs),
        Pat::Tuple(t) => {
            let mut out = Vec::new();
            for (i, elem) in t.elems.iter().enumerate() {
                match elem {
                    Pat::Wild(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() =>
                    {
                        out.push((
                            id.ident.to_string(),
                            Rc::new(Term::Ctor {
                                name: format!("field:{i}"),
                                args: vec![rhs.clone()],
                            }),
                        ));
                    }
                    _ => return None,
                }
            }
            Some(out)
        }
        _ => None,
    }
}

/// A leading immutable-`let` prefix reduced to a single EUF TERM tail (for an
/// if/match BRANCH that needs a value term, not a Formula). None unless the tail
/// is an EUF value term after substitution.
fn let_prefix_euf_term(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Term>> {
    let (last, prefix) = block.stmts.split_last()?;
    let Stmt::Expr(tail_expr, None) = last else {
        return None;
    };
    if prefix.is_empty() {
        return None;
    }
    let subst = collect_let_subst(prefix, scope)?;
    let mut tail = euf_value_term_in_scope(tail_expr, scope)?;
    for (n, t) in &subst {
        tail = subst_var_in_term(&tail, n, t);
    }
    Some(tail)
}

/// True iff an expression is syntactically a boolean predicate the assertion
/// lifter can handle as `out <-> F`: a comparison / logical-op binary, a `!`, or
/// those through paren/group. Deliberately EXCLUDES bare calls and `matches!`
/// (matches! is handled by emit_bool_membership_formula; a bare call's bool-ness
/// is unknown and must not be mis-warranted as a predicate).
fn is_bool_shaped_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Binary(b) => matches!(
            b.op,
            BinOp::Eq(_)
                | BinOp::Ne(_)
                | BinOp::Lt(_)
                | BinOp::Le(_)
                | BinOp::Gt(_)
                | BinOp::Ge(_)
                | BinOp::And(_)
                | BinOp::Or(_)
        ),
        Expr::Unary(u) => matches!(u.op, UnOp::Not(_)),
        Expr::Paren(p) => is_bool_shaped_expr(&p.expr),
        Expr::Group(g) => is_bool_shaped_expr(&g.expr),
        _ => false,
    }
}

fn contains_builtin_matches_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Macro(m) => m.mac.path.is_ident("matches"),
        Expr::Unary(u) if matches!(u.op, UnOp::Not(_)) => contains_builtin_matches_expr(&u.expr),
        Expr::Binary(b)
            if matches!(
                b.op,
                BinOp::And(_) | BinOp::Or(_) | BinOp::BitAnd(_) | BinOp::BitOr(_)
            ) =>
        {
            contains_builtin_matches_expr(&b.left) || contains_builtin_matches_expr(&b.right)
        }
        Expr::Paren(p) => contains_builtin_matches_expr(&p.expr),
        Expr::Group(g) => contains_builtin_matches_expr(&g.expr),
        _ => false,
    }
}

fn is_non_term_control_expr(expr: &Expr) -> bool {
    match expr {
        Expr::If(_) | Expr::Let(_) | Expr::Match(_) | Expr::While(_) | Expr::ForLoop(_) => true,
        Expr::Loop(loop_expr) => !loop_has_single_break_payload(loop_expr),
        Expr::Return(_) | Expr::Break(_) | Expr::Continue(_) => true,
        Expr::Paren(p) => is_non_term_control_expr(&p.expr),
        Expr::Group(g) => is_non_term_control_expr(&g.expr),
        _ => false,
    }
}

fn loop_has_single_break_payload(loop_expr: &syn::ExprLoop) -> bool {
    matches!(
        loop_expr.body.stmts.as_slice(),
        [Stmt::Expr(Expr::Break(expr_break), _)]
            if expr_break.label.is_none() && expr_break.expr.is_some()
    )
}

fn euf_value_term_in_scope(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Term>> {
    if is_non_term_control_expr(expr) {
        return None;
    }
    let term = translate_term_in_scope(expr, scope).ok()?;
    term_is_euf_value(&term).then_some(term)
}

/// A value-position `match` (no arm guards) over a scalar OR enum scrutinee,
/// encoded as the ite via the existing implies/and atoms:
/// `and_i implies(guard_i, out = term_i)`, guard_i = the arm's discriminant
/// conjoined with the negations of earlier arms. Arm discriminants:
///   - scalar literal/range/or -> pattern-membership over the scrutinee;
///   - enum variant (Path / TupleStruct / Struct, all-wild or 1-field binding) ->
///     `variant_of(scrutinee) == "variant::<tag>"`, the panic-locus form, with a
///     single field binding mapped to the uninterpreted `payload:<tag>(scrutinee)`
///     accessor (substituted into the arm body);
///   - `_` or a bare `Pat::Ident` -> CATCH-ALL: guard = ¬earlier (terminal). A
///     bare ident is sound whether it is a unit variant or a binding -- for an
///     exhaustive match `¬earlier` IS the residual case, and the binding (if any)
///     is substituted to the scrutinee (a no-op for a unit variant).
/// None if the scrutinee isn't EUF, any arm has a guard, any arm pattern is
/// unsupported (multi-field binding, nested), or any body isn't EUF.
fn emit_match_value(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let m = match expr {
        Expr::Match(m) => m,
        Expr::Paren(p) => return emit_match_value(&p.expr, scope),
        Expr::Group(g) => return emit_match_value(&g.expr, scope),
        _ => return None,
    };
    let scrutinee = translate_term_in_scope(&m.expr, scope).ok()?;
    if !term_is_euf_value(&scrutinee) {
        return None;
    }
    let mut negated: Vec<Rc<Formula>> = Vec::new();
    let mut clauses: Vec<(Rc<Formula>, Rc<Term>)> = Vec::new();
    for arm in &m.arms {
        if arm.guard.is_some() {
            return None;
        }
        let (atom, bindings) = match_arm_discriminant(&scrutinee, &arm.pat)?;
        let mut body = arm_body_euf_term(&arm.body, scope)?;
        for (n, t) in &bindings {
            body = subst_var_in_term(&body, n, t);
        }
        match atom {
            // Catch-all (`_` / bare ident): guard = ¬earlier, terminal.
            None => {
                let guard = match negated.len() {
                    0 => atomic_("true", vec![]),
                    1 => negated[0].clone(),
                    _ => and_(negated.clone()),
                };
                clauses.push((guard, body));
                let out = make_var("out");
                return Some(and_(
                    clauses
                        .into_iter()
                        .map(|(g, t)| implies(g, eq(out.clone(), t)))
                        .collect(),
                ));
            }
            Some(a) => {
                let mut gp = negated.clone();
                gp.push(a.clone());
                let guard = if gp.len() == 1 {
                    gp.remove(0)
                } else {
                    and_(gp)
                };
                clauses.push((guard, body));
                negated.push(not_(a));
            }
        }
    }
    // No catch-all: an exhaustive variant match -- the conditional clauses are
    // sound regardless of completeness (each is `if discriminant then out=term`).
    if clauses.is_empty() {
        return None;
    }
    let out = make_var("out");
    Some(and_(
        clauses
            .into_iter()
            .map(|(g, t)| implies(g, eq(out.clone(), t)))
            .collect(),
    ))
}

/// Classify a match-arm pattern over `scrutinee`: returns (discriminant atom or
/// None for a catch-all, payload bindings to substitute into the arm body). None
/// (the outer Option) for an unsupported pattern -> the whole match refuses.
#[allow(clippy::type_complexity)]
fn match_arm_discriminant(
    scrutinee: &Rc<Term>,
    pat: &Pat,
) -> Option<(Option<Rc<Formula>>, Vec<(String, Rc<Term>)>)> {
    let variant_eq = |tag: &str| {
        eq(
            Rc::new(Term::Ctor {
                name: "variant_of".to_string(),
                args: vec![scrutinee.clone()],
            }),
            str_const(format!("variant::{tag}")),
        )
    };
    match pat {
        Pat::Wild(_) => Some((None, vec![])),
        Pat::Ident(id) if id.subpat.is_none() && id.mutability.is_none() && id.by_ref.is_none() => {
            // catch-all binding (or unit variant): bind name -> scrutinee.
            Some((None, vec![(id.ident.to_string(), scrutinee.clone())]))
        }
        Pat::Lit(_) | Pat::Range(_) | Pat::Or(_) | Pat::Paren(_) => {
            Some((Some(pattern_membership_formula(scrutinee, pat)?), vec![]))
        }
        Pat::Path(p) => Some((Some(variant_eq(&path_to_variant_string(&p.path))), vec![])),
        Pat::TupleStruct(ts) => {
            let tag = path_to_variant_string(&ts.path);
            // A `..` rest makes positional payload indices ambiguous -> only
            // allowed when there are no bindings at all (all wild/rest).
            let all_inert = ts
                .elems
                .iter()
                .all(|e| matches!(e, Pat::Wild(_) | Pat::Rest(_)));
            if all_inert {
                return Some((Some(variant_eq(&tag)), vec![]));
            }
            if ts.elems.iter().any(|e| matches!(e, Pat::Rest(_))) {
                return None; // rest + bindings: ambiguous positions, refuse
            }
            let n = ts.elems.len();
            let mut bindings = Vec::new();
            for (i, elem) in ts.elems.iter().enumerate() {
                match elem {
                    Pat::Wild(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() =>
                    {
                        // Single-field keeps `payload:tag` (matches the kit's
                        // wrapped_variant_entry congruence); multi-field is indexed.
                        let acc = if n == 1 {
                            format!("payload:{tag}")
                        } else {
                            format!("payload:{tag}.{i}")
                        };
                        bindings.push((
                            id.ident.to_string(),
                            Rc::new(Term::Ctor {
                                name: acc,
                                args: vec![scrutinee.clone()],
                            }),
                        ));
                    }
                    _ => return None, // nested pattern -> refuse
                }
            }
            Some((Some(variant_eq(&tag)), bindings))
        }
        Pat::Struct(s) => {
            let tag = path_to_variant_string(&s.path);
            let mut bindings = Vec::new();
            for f in &s.fields {
                let field_name = match &f.member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                match &*f.pat {
                    Pat::Wild(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() =>
                    {
                        bindings.push((
                            id.ident.to_string(),
                            Rc::new(Term::Ctor {
                                name: format!("payload:{tag}.{field_name}"),
                                args: vec![scrutinee.clone()],
                            }),
                        ));
                    }
                    _ => return None,
                }
            }
            // A `..` rest is fine here (it only drops unbound fields, no index shift).
            Some((Some(variant_eq(&tag)), bindings))
        }
        Pat::Reference(r) => match_arm_discriminant(scrutinee, &r.pat),
        _ => None,
    }
}

/// A match arm's body as an EUF term (a block via block_euf_term, else a direct
/// EUF tail expression).
fn arm_body_euf_term(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Term>> {
    match expr {
        Expr::Block(b) => block_euf_term(&b.block, scope),
        other => euf_value_term_in_scope(other, scope),
    }
}

/// A block's value as an EUF term: a single EUF tail expression, or a leading
/// immutable-let prefix substituted into an EUF tail. None if neither shape.
fn block_euf_term(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Term>> {
    if let [Stmt::Expr(tail, None)] = block.stmts.as_slice() {
        return euf_value_term_in_scope(tail, scope);
    }
    let_prefix_euf_term(block, scope)
}

/// A value-position `if` / `else if` / `else` chain (TOTAL -- a final `else` is
/// required, else `out` is undefined on a branch and we cannot warrant). Encoded
/// as the ite via the EXISTING implies/and atoms: `and_i implies(guard_i, out =
/// term_i)`, where guard_i is the i-th branch condition conjoined with the
/// negations of all earlier conditions. None if any condition does not translate
/// to a Formula (e.g. `if let`), any branch is not an EUF block, or no final else.
fn emit_if_value(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let mut clauses: Vec<(Rc<Formula>, Rc<Term>)> = Vec::new();
    collect_if_clauses(expr, scope, &mut Vec::new(), &mut clauses)?;
    if clauses.is_empty() {
        return None;
    }
    let out = make_var("out");
    Some(and_(
        clauses
            .into_iter()
            .map(|(guard, term)| implies(guard, eq(out.clone(), term)))
            .collect(),
    ))
}

fn collect_if_clauses(
    expr: &Expr,
    scope: &TemporalScope,
    negated: &mut Vec<Rc<Formula>>,
    out_clauses: &mut Vec<(Rc<Formula>, Rc<Term>)>,
) -> Option<()> {
    let if_expr = match expr {
        Expr::If(i) => i,
        Expr::Paren(p) => return collect_if_clauses(&p.expr, scope, negated, out_clauses),
        Expr::Group(g) => return collect_if_clauses(&g.expr, scope, negated, out_clauses),
        _ => return None,
    };
    // The `if` condition as a Formula. First try the assertion bool-lifter
    // (comparisons / &&/|| / matches! / string predicates). If that declines,
    // fall back to a bool-returning EUF expression (`if f(x)`, `if x.is_valid()`):
    // model it as `cond_term == true`. The if-condition POSITION guarantees the
    // expr is bool, so this is sound (no is_bool_shaped gate needed here). An
    // `if let` cond is an Expr::Let -> neither path -> None.
    if is_non_term_control_expr(&if_expr.cond) {
        return None;
    }
    let cond = match crate::sugar::constraint::assertion_entry_with_audits(
        &if_expr.cond,
        scope,
        &FloatWidthScope::new(),
        None,
    ) {
        Ok(entry) => entry.atom,
        Err(_) => {
            let t = translate_term_in_scope(&if_expr.cond, scope).ok()?;
            if !term_is_euf_value(&t) {
                return None;
            }
            eq(t, bool_const(true))
        }
    };
    let then_term = block_euf_term(&if_expr.then_branch, scope)?;
    let mut gp = negated.clone();
    gp.push(cond.clone());
    let guard = if gp.len() == 1 {
        gp.remove(0)
    } else {
        and_(gp)
    };
    out_clauses.push((guard, then_term));
    // A final `else` is required for totality.
    let (_, else_expr) = if_expr.else_branch.as_ref()?;
    match &**else_expr {
        Expr::If(_) => {
            negated.push(not_(cond));
            let r = collect_if_clauses(else_expr, scope, negated, out_clauses);
            negated.pop();
            r
        }
        Expr::Block(b) => {
            let else_term = block_euf_term(&b.block, scope)?;
            let mut gp = negated.clone();
            gp.push(not_(cond));
            let guard = if gp.len() == 1 {
                gp.remove(0)
            } else {
                and_(gp)
            };
            out_clauses.push((guard, else_term));
            Some(())
        }
        _ => None,
    }
}

// (substitution reuses the existing `subst_var_in_term` defined earlier.)

/// A bounded-output universe over `out` from a known TOTAL rust primitive in the
/// tail: a UNIVERSAL over the output (not a pin). Today `recv.clamp(lo, hi)` =>
/// `lo <= out <= hi`, when receiver and bounds are side-effect-free terms. The
/// bound holds on every returning input regardless of the receiver -- the teeth
/// that statically refute an out-of-bound twin.
fn bounded_output_universe(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let call = match expr {
        Expr::MethodCall(c) => c,
        Expr::Paren(p) => return bounded_output_universe(&p.expr, scope),
        Expr::Group(g) => return bounded_output_universe(&g.expr, scope),
        _ => return None,
    };
    if call.method == "clamp" && call.args.len() == 2 {
        let recv = translate_term_in_scope(&call.receiver, scope).ok()?;
        let lo = translate_term_in_scope(&call.args[0], scope).ok()?;
        let hi = translate_term_in_scope(&call.args[1], scope).ok()?;
        if term_is_euf_value(&recv) && term_is_euf_value(&lo) && term_is_euf_value(&hi) {
            return Some(and_(vec![
                gte(make_var("out"), lo),
                lte(make_var("out"), hi),
            ]));
        }
    }
    None
}

/// A closed consistency source contract `inv` over `out` (the return value).
fn source_value_contract(name: &str, inv: Rc<Formula>) -> ContractDecl {
    ContractDecl {
        name: format!("rust-source::{name}"),
        pre: None,
        post: None,
        inv: Some(inv),
        out_binding: "out".to_string(),
        evidence: None,
        panic_loci: Vec::new(),
        concept_hint: None,
    }
}

/// True iff a value term is an emittable EUF value: reads, total operators,
/// value constructors, AND value-position calls (`method:`/`call:`) treated as
/// uninterpreted deterministic functions -- the method-call-as-EUF shape, the
/// same policy Python's `_Emitter` applies to value-position calls (`out =
/// m(recv, args)` over an uninterpreted `m`). Excluded: a known PANIC method
/// (unwrap/expect family -> divergence, refused as an effect by `effect_refusal`),
/// `await` (async effect), and a `macro:` var (unknown). Statement-level effects
/// (assignment, `&mut`, loops) never reach here: an assignment/`&mut` tail fails
/// translation and multi-statement bodies are not a single tail expr -- both fall
/// through to `effect_refusal`.
fn term_is_euf_value(term: &Term) -> bool {
    match term {
        Term::Var { name } => !name.starts_with("macro:"),
        Term::Const { .. } => true,
        Term::Ctor { name, args } => {
            let panicker = matches!(
                name.as_str(),
                "method:unwrap"
                    | "method:expect"
                    | "method:unwrap_unchecked"
                    | "method:unwrap_err"
                    | "method:expect_err"
            );
            let async_effect = name == "await";
            !panicker && !async_effect && args.iter().all(|a| term_is_euf_value(a))
        }
        Term::Lambda { body, .. } => term_is_euf_value(body),
        Term::Let { bindings, body } => {
            bindings.iter().all(|b| term_is_euf_value(&b.bound_term)) && term_is_euf_value(body)
        }
    }
}

/// A boolean body as a membership formula: `matches!` predicates joined by
/// `&&`/`||`/`!`. Any other shape is not emittable here (-> None).
fn emit_bool_membership_formula(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    match expr {
        Expr::Paren(p) => emit_bool_membership_formula(&p.expr, scope),
        Expr::Group(g) => emit_bool_membership_formula(&g.expr, scope),
        Expr::Unary(u) if matches!(u.op, UnOp::Not(_)) => {
            Some(not_(emit_bool_membership_formula(&u.expr, scope)?))
        }
        Expr::Binary(b) => match b.op {
            BinOp::Or(_) | BinOp::BitOr(_) => Some(or_(vec![
                emit_bool_membership_formula(&b.left, scope)?,
                emit_bool_membership_formula(&b.right, scope)?,
            ])),
            BinOp::And(_) | BinOp::BitAnd(_) => Some(and_(vec![
                emit_bool_membership_formula(&b.left, scope)?,
                emit_bool_membership_formula(&b.right, scope)?,
            ])),
            _ => None,
        },
        Expr::Macro(m) => matches_membership_formula(&m.mac, scope),
        _ => None,
    }
}

/// `matches!(<scrutinee>, <pattern> [if <guard>])` -> the membership formula.
/// Unguarded scalar/string patterns reduce over the scrutinee's value
/// (`scrutinee_scalar_var` + `pattern_membership_formula`). A guard, or an enum
/// pattern with bindings, routes through `match_arm_discriminant` (the SAME
/// `variant_of`/`payload:` machinery as a value-`match`): the discriminant is
/// conjoined with the guard translated as a bool predicate, with each pattern
/// binding substituted by its payload accessor (`p` in `Punct(p)` -> the
/// `payload:Punct(scrutinee)` term). The guard must be a bool-predicate the
/// assertion translator accepts and must compose; anything else -> None (the
/// body stays unclassified, never a hollow warrant).
fn matches_membership_formula(mac: &syn::Macro, scope: &TemporalScope) -> Option<Rc<Formula>> {
    if !mac
        .path
        .segments
        .last()
        .is_some_and(|s| s.ident == "matches")
    {
        return None;
    }
    let (scrutinee, pat, guard) = mac
        .parse_body_with(|input: ParseStream| {
            let scrutinee: Expr = input.parse()?;
            input.parse::<Token![,]>()?;
            let pat = Pat::parse_multi_with_leading_vert(input)?;
            let guard = if input.peek(Token![if]) {
                input.parse::<Token![if]>()?;
                Some(input.parse::<Expr>()?)
            } else {
                None
            };
            Ok::<_, syn::Error>((scrutinee, pat, guard))
        })
        .ok()?;
    let Some(guard) = guard else {
        // Unguarded. A simple-name scrutinee: scalar/string code-point membership,
        // then enum-variant discrimination (`is_ipv4`/`is_some`: `variant_of(x) ==
        // "variant::V"` via match_arm_discriminant; a bare binding/wildcard has no
        // discriminant -> vacuous -> None, never a teethless `out <-> true`).
        if let Some(scrutinee_term) = scrutinee_scalar_var(&scrutinee) {
            if let Some(f) = pattern_membership_formula(&scrutinee_term, &pat) {
                return Some(f);
            }
            if let Some((Some(disc), _bindings)) = match_arm_discriminant(&scrutinee_term, &pat) {
                return Some(disc);
            }
        }
        // Slice pattern over a general (possibly method-call) scrutinee:
        // `matches!(self.octets(), [169, 254, ..])` (the net is_documentation /
        // is_link_local family).
        return emit_slice_pattern_membership(&scrutinee, &pat, scope);
    };
    // Guarded: discriminant /\ guard[pattern bindings := payload accessors].
    let scrutinee_term = scrutinee_scalar_var(&scrutinee)?;
    let (disc, bindings) = match_arm_discriminant(&scrutinee_term, &pat)?;
    let entry = crate::sugar::constraint::assertion_entry_with_audits(
        &guard,
        scope,
        &FloatWidthScope::new(),
        None,
    )
    .ok()?;
    let mut guard_f = entry.atom;
    for (name, term) in &bindings {
        guard_f = subst_var_in_formula(&guard_f, name, term);
    }
    Some(match disc {
        Some(d) => and_(vec![d, guard_f]),
        None => guard_f,
    })
}

/// A slice-pattern `matches!(scrut, [lit, _, .., lit])` as a membership formula:
/// each fixed FRONT position `i` (before an optional TRAILING `..`) becomes
/// `index(scrut, i) == lit` over the existing `index` accessor, conjoined.
/// Wildcards skip a position; a trailing `..` leaves the rest unconstrained. The
/// scrutinee is any EUF term (`self.octets()` -> `method:octets(self)`). A
/// non-trailing `..` (back-indexing), a binding/nested element, or an all-wild
/// pattern (no teeth) -> None.
fn emit_slice_pattern_membership(
    scrutinee: &Expr,
    pat: &Pat,
    scope: &TemporalScope,
) -> Option<Rc<Formula>> {
    let Pat::Slice(slice) = pat else {
        return None;
    };
    let scrut = translate_term_in_scope(scrutinee, scope).ok()?;
    if !term_is_euf_value(&scrut) {
        return None;
    }
    let last = slice.elems.len().saturating_sub(1);
    let mut conj: Vec<Rc<Formula>> = Vec::new();
    for (i, elem) in slice.elems.iter().enumerate() {
        match elem {
            // A `..` rest is only sound at the end: a mid-pattern rest shifts the
            // following elements to back-indexing, which `index(scrut, i)` (front)
            // does not model.
            Pat::Rest(_) => {
                if i != last {
                    return None;
                }
                break;
            }
            Pat::Wild(_) => {}
            Pat::Lit(p) => {
                let elem_term = Rc::new(Term::Ctor {
                    name: "index".to_string(),
                    args: vec![scrut.clone(), num(i as i128)],
                });
                conj.push(eq(elem_term, lit_membership_term(&p.lit)?));
            }
            _ => return None,
        }
    }
    if conj.is_empty() {
        return None; // all wild / bare rest -> vacuous, no teeth
    }
    Some(and_(conj))
}

/// The scrutinee of a char/byte `matches!` reduces to a single bound name (its
/// code point): `*self` / `self` / a one-segment path, through deref/ref/paren.
fn scrutinee_scalar_var(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Paren(p) => scrutinee_scalar_var(&p.expr),
        Expr::Group(g) => scrutinee_scalar_var(&g.expr),
        Expr::Unary(u) if matches!(u.op, UnOp::Deref(_)) => scrutinee_scalar_var(&u.expr),
        Expr::Reference(r) => scrutinee_scalar_var(&r.expr),
        Expr::Path(p) if p.path.segments.len() == 1 => {
            Some(make_var(p.path.segments[0].ident.to_string()))
        }
        _ => None,
    }
}

/// A char/byte/int pattern as a membership formula over `scrutinee` (its code
/// point): literal -> `=`, inclusive/half-open range -> bounded `and`, or-pattern
/// -> `or`, wildcard -> `true`. Bindings/structs/etc. are not emittable (-> None).
pub(crate) fn pattern_membership_formula(scrutinee: &Rc<Term>, pat: &Pat) -> Option<Rc<Formula>> {
    match pat {
        Pat::Paren(p) => pattern_membership_formula(scrutinee, &p.pat),
        Pat::Wild(_) => Some(atomic_("true", vec![])),
        Pat::Or(o) => {
            let mut cases = Vec::with_capacity(o.cases.len());
            for c in &o.cases {
                cases.push(pattern_membership_formula(scrutinee, c)?);
            }
            Some(or_(cases))
        }
        Pat::Lit(p) => Some(eq(scrutinee.clone(), lit_membership_term(&p.lit)?)),
        Pat::Range(r) => {
            let inclusive = matches!(r.limits, syn::RangeLimits::Closed(_));
            let mut conj = Vec::new();
            if let Some(lo) = r.start.as_deref().and_then(expr_codepoint) {
                conj.push(gte(scrutinee.clone(), num(lo)));
            }
            if let Some(hi) = r.end.as_deref().and_then(expr_codepoint) {
                conj.push(if inclusive {
                    lte(scrutinee.clone(), num(hi))
                } else {
                    lt(scrutinee.clone(), num(hi))
                });
            }
            if conj.is_empty() {
                return None;
            }
            Some(and_(conj))
        }
        _ => None,
    }
}

/// A `matches!` literal pattern bound as a membership *term* to equate the
/// scrutinee against: a string literal becomes a `String`-sorted constant
/// (string-theory regime; the scrutinee is the string value itself), every
/// scalar (char/byte/int) becomes its `Int` code point. A `matches!` arm is
/// homogeneous in practice (`matches!(x, "a" | 1)` is a type error), so a
/// String/Int mix never reaches the same scrutinee.
pub(crate) fn lit_membership_term(lit: &Lit) -> Option<Rc<Term>> {
    match lit {
        Lit::Str(s) => Some(str_const(s.value())),
        _ => Some(num(lit_codepoint(lit)?)),
    }
}

/// The integer code point of a char / byte / integer literal pattern bound.
/// i128 carrier: a wide integer pattern (`match x { 0xffff_..._u64 => .. }`)
/// folds to its EXACT value via `parse_int_lit`, never a truncation.
fn lit_codepoint(lit: &Lit) -> Option<i128> {
    match lit {
        Lit::Char(c) => Some(i128::from(u32::from(c.value()))),
        Lit::Byte(b) => Some(i128::from(b.value())),
        Lit::Int(i) => parse_int_lit(i).ok(),
        _ => None,
    }
}

fn expr_codepoint(expr: &Expr) -> Option<i128> {
    match expr {
        Expr::Lit(ExprLit { lit, .. }) => lit_codepoint(lit),
        Expr::Paren(p) => expr_codepoint(&p.expr),
        Expr::Group(g) => expr_codepoint(&g.expr),
        _ => None,
    }
}
