// SPDX-License-Identifier: Apache-2.0
//
// `MatchSugar`: an N-arm match reduced to the conjunction of `guard_i => body_i`, each
// `guard_i` the discriminant predicate the arm's pattern states over the scrutinee (the
// trailing `_` arm's guard is the negation of all prior guards). Relocated verbatim from
// the `lib.rs` monolith (pure code-motion, zero behavior change). Carries its OWNED
// machinery: the `MatchArmLift` struct, `match_arm_guard`, `arm_body_stmts`, and the
// `decompose_match` constructor. The shared `match_arm_discriminant` (called from the
// scrutinee-translation path OUTSIDE this node) stays in `crate::` and is imported.

use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, implies, not_, or_, str_const, Formula, Term};
use syn::visit::Visit;
use syn::{Expr, Pat, Stmt};

use crate::sugar::configuration::{CfgDisposition, ConfigurationSugar};
use crate::sugar::factory::{ConstraintFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_literal::translate_lit;
use crate::{
    bool_const, closure_body_is_side_effecting, collect_assertion_entries, count_asserts_in_stmts,
    expr_diverges, loop_body_mutates, path_to_variant_string, strict_variant_path, substitute_expr,
    substitute_stmts, token_key, translate_term_in_scope, wrapped_variant, AssertionFactKind,
    ConstVal, Desugared, Effect, ExprBindings, LiftOptions, Outcome, ReductionCtx, Sugar, SugarCtx,
    TemporalScope, Warrant,
};
use crate::{FactoryAuditLog, FloatWidthScope};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "match_node",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_match_node_good() {
                    match 2_i32 {
                        1 => assert_eq!(10, 11),
                        2 => assert_eq!(20, 20),
                        _ => assert_eq!(0, 1),
                    }
                }
            "#,
            r#"
                #[test]
                fn t_match_node_bad() {
                    match 2_i32 {
                        1 => assert_eq!(10, 10),
                        2 => assert_eq!(20, 21),
                        _ => assert_eq!(0, 0),
                    }
                }
            "#,
        ),
        recognize_composite,
    );

pub(crate) const CONSTRAINT_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::constraint_before(
        "constraint_closed_match",
        &["constraint_bool_expr"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_constraint_closed_match_good() {
                    assert!(match 2_i32 {
                        1 => false,
                        2 => true,
                        _ => false,
                    });
                }
            "#,
            r#"
                #[test]
                fn t_constraint_closed_match_bad() {
                    assert!(match 2_i32 {
                        1 => true,
                        2 => false,
                        _ => true,
                    });
                }
            "#,
        ),
        recognize_constraint,
    );

pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "match_value_term",
        &["match_scrutinee_term"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_const_match_good() {
                    assert!((match 2 { 1 => 10, 2 => 20, _ => 0 }) == 20);
                }
            "#,
            r#"
                #[test]
                fn t_const_match_bad() {
                    assert!((match 2 { 1 => 10, 2 => 20, _ => 0 }) == 21);
                }
            "#,
        ),
        recognize_term,
    );

/// COMPOSITE recognizer for `Expr::Match`: the conjunction composite ([`MatchSugar`]
/// via [`decompose_match`]). If the match cannot construct a lawful node, this
/// recognizer declines and lets the factory's structural gap stay loud.
pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::Match(m) => decompose_match(m, fcx.scope(), fcx.options())
            .map(|node| Box::new(node) as Box<dyn Sugar>),
        _ => None,
    }
}

/// CONSTRAINT recognizer for a closed `match` whose scrutinee determines exactly one
/// reachable arm from source literals/consts. The selected arm is delegated to the
/// ordinary constraint floor after pattern bindings have been substituted.
fn recognize_constraint(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Match(m) = expr else {
        return None;
    };
    let selected = selected_closed_arm_body(m, fcx.scope(), fcx.options())?;
    Some(Box::new(ClosedMatchConstraintSugar {
        body: SugarBody::constraint(&selected, fcx),
    }))
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_statement_match(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    let_inits: &BTreeMap<String, &Expr>,
    macro_depth: usize,
    factory_audits: Option<&FactoryAuditLog>,
) -> Outcome {
    crate::sugar::statement_position::desugar_composite_expr(
        expr,
        scope,
        options,
        reducer,
        float_widths,
        let_inits,
        macro_depth,
        factory_audits,
    )
}

/// TERM recognizer for a value-producing match whose losing arms diverge:
///
///     match r { Ok(v) => v, Err(e) => panic!(...) }
///
/// This is the value half of the same source shape `panic_locus_match_entry` uses for
/// facts. The fact side says the surviving pattern held; the term side says the match
/// expression evaluates to the surviving arm's value under that pattern binding.
fn recognize_term(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Match(m) = expr else {
        return None;
    };
    if let Some(selected) = selected_closed_arm_body(m, fcx.scope(), fcx.options()) {
        return Some(Box::new(ClosedMatchTermSugar {
            body: SugarBody::term(&selected, fcx),
        }));
    }
    // A fully-constant `match` over a const scrutinee collapses to the taken arm's
    // ground value -- the SAME `const_eval` + `const_val_term` path `binop`/`const_if`
    // ship, so the term is sort-identical to the literal the source would have written.
    // A non-const scrutinee / undecidable arm falls through to the divergent-arm value
    // node below (finite-or-refuse).
    if let Some(term) =
        crate::const_eval(expr, &BTreeMap::new()).and_then(|value| crate::const_val_term(&value))
    {
        return Some(crate::sugar::term_leaf::resolved_term(term));
    }
    if let Some((pat, _)) = single_surviving_value_arm(m) {
        value_arm_pattern_is_term_bindable(pat)?;
        return Some(Box::new(MatchValueTermSugar {
            scrutinee: SugarBody::term(&m.expr, fcx),
            m: m.clone(),
        }));
    }
    if crate::sugar::match_scrutinee::expr_resolves_runtime_call_result(&m.expr, fcx, 0) {
        return None;
    }
    match_has_runtime_term_interior(m).then(|| {
        Box::new(RuntimeMatchTermSugar {
            boundary: token_key(expr),
        }) as Box<dyn Sugar>
    })
}

/// A match arm reduced to its discriminant guard + body statements. The guard is
/// the FOL predicate the arm's pattern states over the scrutinee (a literal `1 =>`
/// is `scrut == 1`; a qualified variant `Poll::Ready(_) =>` is
/// `variant_of(scrut) == "variant::Poll::Ready"`); the final wildcard `_ =>`
/// carries `None`, signaling "the negation of every prior arm's guard".
struct MatchArmLift {
    /// `Some(guard)` for a discriminant arm; `None` for the catch-all `_` arm.
    guard: Option<Rc<Formula>>,
    body_stmts: Vec<Stmt>,
}

/// guard_i = the discriminant predicate pat_i states over scrut; the trailing `_`
/// arm's guard is the negation of the disjunction of all prior arm guards. This IS
/// `ConditionalSugar` generalized from two branches (the bool guard `c` and its
/// negation) to N arms (each pattern's discriminant). SOUNDNESS: a value reaching
/// arm i's body matched pat_i, so guard_i holds there -- we emit `guard_i ⇒ A_i`,
/// never bare `A_i`.
pub(crate) struct MatchSugar {
    arms: Vec<MatchArmLift>,
}

/// BAILS (Err analog = `Ok(None)` is the wildcard, `None` is the bail) on:
///   - a binding `x =>` that binds the scrutinee (single-segment `Pat::Ident`):
///     a binding always matches and re-names the scrutinee -- not a discriminant;
///   - an or-pattern `A | B =>`: a disjunction is not a single discriminant;
///   - range patterns, ref/struct/tuple binding patterns, and anything else we do
///     not translate to an unambiguous discriminant.
/// Returns `Some(Some(guard))` for a discriminant arm, `Some(None)` for the final
/// wildcard, `None` to BAIL (refusal stands).
fn match_arm_guard(
    pat: &syn::Pat,
    scrut: &Rc<Term>,
    is_last: bool,
    scope: &TemporalScope,
) -> Option<Option<Rc<Formula>>> {
    match pat {
        // The catch-all wildcard. Only the LAST arm may be a bare `_` (a non-final
        // wildcard would shadow later arms -- not a shape we model); the caller
        // fills its guard with the negation of all prior arm guards.
        syn::Pat::Wild(_) if is_last => Some(None),
        // A UNIT pattern `() =>` over a `()` scrutinee is irrefutable -- it always
        // matches (there is exactly one value of type `()`). Like `_`, it is a
        // catch-all: only valid as the last arm (a non-final `()` would shadow later
        // arms). The caller fills its guard with the negation of all prior guards
        // (vacuously `true` when it is the sole arm). Corpus shape: num/wrapping.rs
        // `match () { #[cfg(..)] () => { assert } .. }` after inactive arms are
        // stripped -- the single surviving unit arm is unconditional.
        syn::Pat::Tuple(t) if t.elems.is_empty() && is_last => Some(None),
        // A literal pattern: `1 =>`, `'a' =>`, `"s" =>`, `true =>`. The discriminant
        // is `scrut == <lit>`, lifted via the SAME literal translator the equality
        // assertion path uses (concrete value + width sort -- no masking).
        syn::Pat::Lit(lit) => {
            let lit_term = translate_lit(lit).ok()?;
            Some(Some(eq(scrut.clone(), lit_term)))
        }
        // A qualified variant (`Type::Variant`, with or without a value subpattern)
        // or a known prelude wrapper (`Some`/`Ok`/`Err`). The discriminant is
        // `variant_of(scrut) == "variant::<tag>"` -- the construction-semantics atom
        // panic-locus / `matches!` lifting emits, with the same teeth (two variants
        // are distinct string constants). REUSE `strict_variant_path` (qualified
        // path) and the prelude-wrapper check.
        syn::Pat::TupleStruct(_) | syn::Pat::Struct(_) | syn::Pat::Path(_) => {
            let tag = strict_variant_path(pat).or_else(|| {
                // A single-segment prelude wrapper `Some`/`Ok`/`Err` as a guard is
                // an unambiguous variant tag (same allow-list `wrapped_variant`
                // uses); a unit `Ok =>` likewise.
                wrapped_variant(pat).map(|(w, _)| w).or_else(|| {
                    if let syn::Pat::Path(p) = pat {
                        let name = path_to_variant_string(&p.path);
                        matches!(
                            p.path
                                .segments
                                .last()
                                .map(|s| s.ident.to_string())
                                .as_deref(),
                            Some("None")
                        )
                        .then_some(name)
                    } else {
                        None
                    }
                })
            })?;
            let variant_of = Rc::new(Term::Ctor {
                name: "variant_of".to_string(),
                args: vec![scrut.clone()],
            });
            Some(Some(eq(variant_of, str_const(format!("variant::{tag}")))))
        }
        // A reference pattern peels the `&` and re-asks (mirrors the variant/wrapper
        // helpers, which all strip `Pat::Reference`).
        syn::Pat::Reference(r) => match_arm_guard(&r.pat, scrut, is_last, scope),
        syn::Pat::Paren(p) => match_arm_guard(&p.pat, scrut, is_last, scope),
        // Everything else BAILS: a binding `x =>` (always matches, re-names the
        // scrutinee), an or-pattern `A | B =>` (a disjunction, not a single
        // discriminant), a range pattern, a tuple/struct binding pattern, a
        // non-final wildcard. EXACT-OR-BAIL.
        _ => None,
    }
}

/// The statements of a match arm body: a block `{ .. }` contributes its own
/// statements; any other body expression (a bare `assert_eq!(..)`, a value) is
/// wrapped as one expression statement so the normal collector lifts it.
fn arm_body_stmts(body: &Expr) -> Vec<Stmt> {
    match body {
        Expr::Block(b) => b.block.stmts.clone(),
        Expr::Unsafe(u) => u.block.stmts.clone(),
        other => vec![Stmt::Expr(other.clone(), None)],
    }
}

/// translate as a stable term (no mut local, no effect -- reuse the term
/// translator, which bails on an opaque/effectful scrutinee), and every arm
/// pattern must reduce to a discriminant guard (or the final `_`). None (BAIL,
/// refusal stands) on any arm with a guard `if cond =>` (which value reaches the
/// arm is genuinely guard-dependent), a binding/or/range/struct-binding pattern,
/// or a non-translatable scrutinee. The body lift (all-or-nothing) happens in
/// `MatchSugar::desugar`.
/// The trivial inner for an arm's `ConfigurationSugar`: the arm-filter asks the node only
/// for its `disposition` (which never desugars the inner), so this placeholder's `desugar`
/// is never reached on the filter path. It completes the empty floor for soundness if it ever is.
struct ArmPresent;
impl Sugar for ArmPresent {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::Seq(Vec::new()))
    }
}

struct MatchValueTermSugar {
    scrutinee: SugarBody<TermFloor>,
    m: syn::ExprMatch,
}

struct RuntimeMatchTermSugar {
    boundary: String,
}

struct ClosedMatchTermSugar {
    body: SugarBody<TermFloor>,
}

struct ClosedMatchConstraintSugar {
    body: SugarBody<ConstraintFloor>,
}

impl Sugar for ClosedMatchTermSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        self.body.reduce(ctx)
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

impl Sugar for ClosedMatchConstraintSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        self.body.reduce(ctx)
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

impl Sugar for MatchValueTermSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let Some((pat, body)) = single_surviving_value_arm(&self.m) else {
            unreachable!("MatchValueTermSugar constructed without one surviving arm");
        };
        let scrutinee = match self.scrutinee.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => unreachable!("typed match scrutinee body reduced to a non-term floor"),
            },
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        if let Some(effect) = panic_payload_downcast_effect(pat, body, &scrutinee) {
            return Outcome::Incomplete(effect);
        }
        let Some(bindings) = value_arm_term_bindings(pat, &scrutinee) else {
            unreachable!("MatchValueTermSugar constructed with an unbindable value pattern");
        };
        let mut arm_scope = ctx.scope.clone();
        for (name, term) in bindings {
            arm_scope.record_let_term_binding(&name, term);
        }
        match translate_term_in_scope(body, &arm_scope) {
            Ok(term) => Outcome::Complete(Desugared::Term(term)),
            Err(effect) => Outcome::Incomplete(effect),
        }
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

impl Sugar for RuntimeMatchTermSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::RuntimeMatchTerm {
            boundary: self.boundary.clone(),
        })
    }
}

fn panic_payload_downcast_effect(pat: &Pat, body: &Expr, scrutinee: &Rc<Term>) -> Option<Effect> {
    let binding = catch_unwind_err_binding(pat, scrutinee)?;
    body_downcasts_binding(body, &binding).then(|| Effect::PanicPayload {
        boundary: token_key(body),
    })
}

fn catch_unwind_err_binding(pat: &Pat, scrutinee: &Rc<Term>) -> Option<String> {
    if !scrutinee_is_catch_unwind(scrutinee) {
        return None;
    }
    match pat {
        Pat::TupleStruct(ts)
            if ts
                .path
                .segments
                .last()
                .is_some_and(|segment| segment.ident == "Err")
                && ts.elems.len() == 1 =>
        {
            match &ts.elems[0] {
                Pat::Ident(id)
                    if id.subpat.is_none() && id.mutability.is_none() && id.by_ref.is_none() =>
                {
                    Some(id.ident.to_string())
                }
                _ => None,
            }
        }
        Pat::Reference(reference) => catch_unwind_err_binding(&reference.pat, scrutinee),
        Pat::Paren(paren) => catch_unwind_err_binding(&paren.pat, scrutinee),
        _ => None,
    }
}

fn scrutinee_is_catch_unwind(term: &Rc<Term>) -> bool {
    match term.as_ref() {
        Term::Ctor { name, .. } if name.starts_with("call:") => name.contains("catch_unwind"),
        Term::Ctor { args, .. } => args.iter().any(scrutinee_is_catch_unwind),
        _ => false,
    }
}

fn body_downcasts_binding(body: &Expr, binding: &str) -> bool {
    struct Scan<'a> {
        binding: &'a str,
        found: bool,
    }
    impl<'ast> Visit<'ast> for Scan<'_> {
        fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
            if matches!(
                call.method.to_string().as_str(),
                "downcast" | "downcast_ref" | "downcast_mut"
            ) && expr_refs_binding(&call.receiver, self.binding)
            {
                self.found = true;
                return;
            }
            syn::visit::visit_expr_method_call(self, call);
        }
    }
    let mut scan = Scan {
        binding,
        found: false,
    };
    Visit::visit_expr(&mut scan, body);
    scan.found
}

fn expr_refs_binding(expr: &Expr, binding: &str) -> bool {
    struct Refs<'a> {
        binding: &'a str,
        found: bool,
    }
    impl<'ast> Visit<'ast> for Refs<'_> {
        fn visit_expr_path(&mut self, path: &'ast syn::ExprPath) {
            if path
                .path
                .get_ident()
                .is_some_and(|ident| ident == self.binding)
            {
                self.found = true;
                return;
            }
            syn::visit::visit_expr_path(self, path);
        }
    }
    let mut refs = Refs {
        binding,
        found: false,
    };
    Visit::visit_expr(&mut refs, expr);
    refs.found
}

fn single_surviving_value_arm(m: &syn::ExprMatch) -> Option<(&Pat, &Expr)> {
    let mut surviving = Vec::new();
    let mut diverging = 0usize;
    for arm in &m.arms {
        if arm.guard.is_some() {
            return None;
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
    let arm = surviving[0];
    Some((&arm.pat, &arm.body))
}

fn match_has_runtime_term_interior(m: &syn::ExprMatch) -> bool {
    m.arms
        .iter()
        .filter(|arm| !expr_diverges(&arm.body))
        .any(|arm| expr_has_runtime_term_interior(&arm.body))
}

fn stmt_has_runtime_term_interior(stmt: &Stmt) -> bool {
    match stmt {
        Stmt::Local(local) => local
            .init
            .as_ref()
            .is_some_and(|init| expr_has_runtime_term_interior(&init.expr)),
        Stmt::Item(_) => false,
        Stmt::Expr(expr, _) => expr_has_runtime_term_interior(expr),
        Stmt::Macro(_) => true,
    }
}

fn expr_has_runtime_term_interior(expr: &Expr) -> bool {
    match expr {
        Expr::Call(_) | Expr::MethodCall(_) | Expr::Try(_) | Expr::Macro(_) => true,
        Expr::Block(block) => block.block.stmts.iter().any(stmt_has_runtime_term_interior),
        Expr::If(if_expr) => {
            expr_has_runtime_term_interior(&if_expr.cond)
                || if_expr
                    .then_branch
                    .stmts
                    .iter()
                    .any(stmt_has_runtime_term_interior)
                || if_expr
                    .else_branch
                    .as_ref()
                    .is_some_and(|(_, else_expr)| expr_has_runtime_term_interior(else_expr))
        }
        Expr::Match(match_expr) => match_has_runtime_term_interior(match_expr),
        Expr::Paren(paren) => expr_has_runtime_term_interior(&paren.expr),
        Expr::Group(group) => expr_has_runtime_term_interior(&group.expr),
        Expr::Reference(reference) => expr_has_runtime_term_interior(&reference.expr),
        Expr::Unary(unary) => expr_has_runtime_term_interior(&unary.expr),
        Expr::Binary(binary) => {
            expr_has_runtime_term_interior(&binary.left)
                || expr_has_runtime_term_interior(&binary.right)
        }
        Expr::Field(field) => expr_has_runtime_term_interior(&field.base),
        Expr::Index(index) => {
            expr_has_runtime_term_interior(&index.expr)
                || expr_has_runtime_term_interior(&index.index)
        }
        _ => false,
    }
}

fn value_arm_pattern_is_term_bindable(pat: &Pat) -> Option<()> {
    match pat {
        Pat::Wild(_) | Pat::Path(_) => Some(()),
        Pat::Ident(id) if id.subpat.is_none() && id.mutability.is_none() && id.by_ref.is_none() => {
            Some(())
        }
        Pat::TupleStruct(ts) => {
            for elem in &ts.elems {
                match elem {
                    Pat::Wild(_) | Pat::Rest(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() => {}
                    _ => return None,
                }
            }
            Some(())
        }
        Pat::Struct(s) => {
            for field in &s.fields {
                match &*field.pat {
                    Pat::Wild(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() => {}
                    _ => return None,
                }
            }
            Some(())
        }
        Pat::Reference(r) => value_arm_pattern_is_term_bindable(&r.pat),
        Pat::Paren(p) => value_arm_pattern_is_term_bindable(&p.pat),
        _ => None,
    }
}

fn value_arm_term_bindings(pat: &Pat, scrutinee: &Rc<Term>) -> Option<Vec<(String, Rc<Term>)>> {
    match pat {
        Pat::Wild(_) | Pat::Path(_) => Some(Vec::new()),
        Pat::Ident(id) if id.subpat.is_none() && id.mutability.is_none() && id.by_ref.is_none() => {
            Some(vec![(id.ident.to_string(), scrutinee.clone())])
        }
        Pat::TupleStruct(ts) => {
            let tag = path_to_variant_string(&ts.path);
            let n = ts.elems.len();
            let mut out = Vec::new();
            for (i, elem) in ts.elems.iter().enumerate() {
                match elem {
                    Pat::Wild(_) | Pat::Rest(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() =>
                    {
                        out.push((
                            id.ident.to_string(),
                            payload_term(&tag, (n > 1).then_some(i), scrutinee),
                        ));
                    }
                    _ => return None,
                }
            }
            Some(out)
        }
        Pat::Struct(s) => {
            let tag = path_to_variant_string(&s.path);
            let mut out = Vec::new();
            for field in &s.fields {
                let field_name = match &field.member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                match &*field.pat {
                    Pat::Wild(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() =>
                    {
                        out.push((
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
            Some(out)
        }
        Pat::Reference(r) => value_arm_term_bindings(&r.pat, scrutinee),
        Pat::Paren(p) => value_arm_term_bindings(&p.pat, scrutinee),
        _ => None,
    }
}

fn payload_term(tag: &str, index: Option<usize>, scrutinee: &Rc<Term>) -> Rc<Term> {
    if index.is_none() {
        if let Some(inner) = monadic_payload_term(tag, scrutinee) {
            return inner;
        }
    }
    let accessor = match index {
        Some(i) => format!("payload:{tag}.{i}"),
        None => format!("payload:{tag}"),
    };
    Rc::new(Term::Ctor {
        name: accessor,
        args: vec![scrutinee.clone()],
    })
}

fn monadic_payload_term(tag: &str, scrutinee: &Rc<Term>) -> Option<Rc<Term>> {
    let leaf = tag.rsplit("::").next().unwrap_or(tag);
    let Term::Ctor { name, args } = scrutinee.as_ref() else {
        return None;
    };
    let [inner] = args.as_slice() else {
        return None;
    };
    match (leaf, name.as_str()) {
        ("Some", monadic::OPT_SOME) | ("Ok", monadic::RES_OK) | ("Err", monadic::RES_ERR) => {
            Some(inner.clone())
        }
        _ => None,
    }
}

fn selected_closed_arm_body(
    m: &syn::ExprMatch,
    scope: &TemporalScope,
    options: &LiftOptions,
) -> Option<Expr> {
    let (arm, bindings) = selected_closed_arm(m, scope, options)?;
    Some(substitute_expr(&arm.body, &bindings))
}

fn selected_closed_arm_stmts(
    m: &syn::ExprMatch,
    scope: &TemporalScope,
    options: &LiftOptions,
) -> Option<Vec<Stmt>> {
    let (arm, bindings) = selected_closed_arm(m, scope, options)?;
    Some(substitute_stmts(&arm_body_stmts(&arm.body), &bindings))
}

fn selected_closed_arm<'a>(
    m: &'a syn::ExprMatch,
    scope: &TemporalScope,
    options: &LiftOptions,
) -> Option<(&'a syn::Arm, ExprBindings)> {
    if crate::expr_is_runtime_call_result(&m.expr) {
        // Runtime-call scrutinees are owned by match_scrutinee. Closed-match only
        // selects arms from source-closed data; a catch-all arm must not launder
        // runtime arm selection into a closed rewrite.
        return None;
    }
    if closure_body_is_side_effecting(&m.expr)
        || expr_contains_mutable_reference_or_raw_addr(&m.expr)
    {
        return None;
    }
    let scrutinee = resolve_closed_match_expr(scope, &m.expr, 0)?;
    for arm in active_match_arms(m, options)? {
        match source_pattern_bindings(&scrutinee, &arm.pat, scope) {
            SourcePatternOutcome::NoMatch => continue,
            SourcePatternOutcome::Unsupported => return None,
            SourcePatternOutcome::Match(bindings) => {
                if let Some((_, guard)) = &arm.guard {
                    let guard = substitute_expr(guard, &bindings);
                    if !closed_bool_value(scope, &guard)? {
                        continue;
                    }
                }
                return Some((arm, bindings));
            }
        }
    }
    None
}

fn active_match_arms<'a>(
    m: &'a syn::ExprMatch,
    options: &LiftOptions,
) -> Option<Vec<&'a syn::Arm>> {
    let mut kept = Vec::with_capacity(m.arms.len());
    for arm in &m.arms {
        // cfg COMPOSES as a node: wrap the arm in a `ConfigurationSugar` and ask the
        // node for its disposition over the pinned facts (build the node, ask it),
        // rather than re-deriving a `CfgEval` dispatch here. Present -> the arm exists
        // on this target (keep); Absent -> rustc stripped it (drop); Ambiguous -> no
        // facts, we cannot know whether the arm is present (bail, refusal stands).
        let gated = ConfigurationSugar::new(arm.attrs.clone(), Box::new(ArmPresent));
        match gated.disposition(options) {
            CfgDisposition::Present => kept.push(arm),
            CfgDisposition::Absent(_) => {}
            CfgDisposition::Ambiguous(_) => return None,
        }
    }
    Some(kept)
}

enum SourcePatternOutcome {
    Match(ExprBindings),
    NoMatch,
    Unsupported,
}

fn source_pattern_bindings(
    scrutinee: &Expr,
    pat: &Pat,
    scope: &TemporalScope,
) -> SourcePatternOutcome {
    match pat {
        Pat::Wild(_) => SourcePatternOutcome::Match(ExprBindings::new()),
        Pat::Ident(ident)
            if ident.subpat.is_none()
                && ident.mutability.is_none()
                && ident.by_ref.is_none()
                && is_const_pattern_ident(&ident.ident.to_string()) =>
        {
            let pat_expr = Expr::Path(syn::ExprPath {
                attrs: Vec::new(),
                qself: None,
                path: ident.ident.clone().into(),
            });
            match const_expr_eq(scope, scrutinee, &pat_expr) {
                Some(true) => SourcePatternOutcome::Match(ExprBindings::new()),
                Some(false) => SourcePatternOutcome::NoMatch,
                None => SourcePatternOutcome::Unsupported,
            }
        }
        Pat::Ident(ident)
            if ident.subpat.is_none() && ident.mutability.is_none() && ident.by_ref.is_none() =>
        {
            let mut bindings = ExprBindings::new();
            bindings.insert(ident.ident.to_string(), scrutinee.clone());
            SourcePatternOutcome::Match(bindings)
        }
        Pat::Lit(lit) => {
            let pat_expr = Expr::Lit(lit.clone());
            match const_expr_eq(scope, scrutinee, &pat_expr) {
                Some(true) => SourcePatternOutcome::Match(ExprBindings::new()),
                Some(false) => SourcePatternOutcome::NoMatch,
                None => SourcePatternOutcome::Unsupported,
            }
        }
        Pat::Path(path) => {
            let pat_expr = Expr::Path(syn::ExprPath {
                attrs: Vec::new(),
                qself: None,
                path: path.path.clone(),
            });
            match const_expr_eq(scope, scrutinee, &pat_expr) {
                Some(true) => SourcePatternOutcome::Match(ExprBindings::new()),
                Some(false) => SourcePatternOutcome::NoMatch,
                None => SourcePatternOutcome::Unsupported,
            }
        }
        Pat::Tuple(tuple_pat) => {
            let Expr::Tuple(tuple_value) = crate::strip_refs_groups(scrutinee) else {
                return SourcePatternOutcome::Unsupported;
            };
            if tuple_pat.elems.len() != tuple_value.elems.len() {
                return SourcePatternOutcome::Unsupported;
            }
            let mut out = ExprBindings::new();
            for (elem_pat, elem_value) in tuple_pat.elems.iter().zip(tuple_value.elems.iter()) {
                match source_pattern_bindings(elem_value, elem_pat, scope) {
                    SourcePatternOutcome::NoMatch => return SourcePatternOutcome::NoMatch,
                    SourcePatternOutcome::Unsupported => return SourcePatternOutcome::Unsupported,
                    SourcePatternOutcome::Match(bindings) => {
                        out.extend(bindings);
                    }
                }
            }
            SourcePatternOutcome::Match(out)
        }
        Pat::Range(range) => match range_pattern_matches(scope, scrutinee, range) {
            Some(true) => SourcePatternOutcome::Match(ExprBindings::new()),
            Some(false) => SourcePatternOutcome::NoMatch,
            None => SourcePatternOutcome::Unsupported,
        },
        Pat::Or(or_pat) => {
            for case in &or_pat.cases {
                match source_pattern_bindings(scrutinee, case, scope) {
                    SourcePatternOutcome::NoMatch => {}
                    other => return other,
                }
            }
            SourcePatternOutcome::NoMatch
        }
        Pat::Paren(paren) => source_pattern_bindings(scrutinee, &paren.pat, scope),
        Pat::Reference(reference) if reference.mutability.is_none() => {
            source_pattern_bindings(scrutinee, &reference.pat, scope)
        }
        Pat::Type(typed) => source_pattern_bindings(scrutinee, &typed.pat, scope),
        _ => SourcePatternOutcome::Unsupported,
    }
}

fn range_pattern_matches(
    scope: &TemporalScope,
    scrutinee: &Expr,
    range: &syn::PatRange,
) -> Option<bool> {
    let value = closed_const_value(scope, scrutinee)?;
    if let Some(start) = &range.start {
        let start = closed_const_value(scope, start)?;
        if crate::const_cmp(&value, &start)? == std::cmp::Ordering::Less {
            return Some(false);
        }
    }
    if let Some(end) = &range.end {
        let end = closed_const_value(scope, end)?;
        let ord = crate::const_cmp(&value, &end)?;
        if matches!(range.limits, syn::RangeLimits::Closed(_)) {
            if ord == std::cmp::Ordering::Greater {
                return Some(false);
            }
        } else if ord != std::cmp::Ordering::Less {
            return Some(false);
        }
    }
    Some(range.start.is_some() || range.end.is_some())
}

fn is_const_pattern_ident(name: &str) -> bool {
    name.chars().any(|ch| ch.is_ascii_uppercase())
        && name
            .chars()
            .all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_')
}

fn const_expr_eq(scope: &TemporalScope, lhs: &Expr, rhs: &Expr) -> Option<bool> {
    let lhs = closed_const_value(scope, lhs)?;
    let rhs = closed_const_value(scope, rhs)?;
    crate::const_eq(&lhs, &rhs)
}

fn closed_bool_value(scope: &TemporalScope, expr: &Expr) -> Option<bool> {
    match closed_const_value(scope, expr)? {
        ConstVal::Bool(value) => Some(value),
        _ => None,
    }
}

fn closed_const_value(scope: &TemporalScope, expr: &Expr) -> Option<ConstVal> {
    let resolved = resolve_closed_match_expr(scope, expr, 0)?;
    crate::const_eval(&resolved, &BTreeMap::new())
}

fn resolve_closed_match_expr(scope: &TemporalScope, expr: &Expr, depth: usize) -> Option<Expr> {
    const MAX_DEPTH: usize = 16;
    if depth > MAX_DEPTH {
        return None;
    }
    match expr {
        Expr::Paren(paren) => resolve_closed_match_expr(scope, &paren.expr, depth + 1),
        Expr::Group(group) => resolve_closed_match_expr(scope, &group.expr, depth + 1),
        Expr::Reference(reference) if reference.mutability.is_none() => {
            resolve_closed_match_expr(scope, &reference.expr, depth + 1)
        }
        Expr::Unary(unary) => {
            let mut out = unary.clone();
            out.expr = Box::new(resolve_closed_match_expr(scope, &unary.expr, depth + 1)?);
            Some(Expr::Unary(out))
        }
        Expr::Binary(binary) => {
            let mut out = binary.clone();
            out.left = Box::new(resolve_closed_match_expr(scope, &binary.left, depth + 1)?);
            out.right = Box::new(resolve_closed_match_expr(scope, &binary.right, depth + 1)?);
            Some(Expr::Binary(out))
        }
        Expr::Cast(cast) => {
            let mut out = cast.clone();
            out.expr = Box::new(resolve_closed_match_expr(scope, &cast.expr, depth + 1)?);
            Some(Expr::Cast(out))
        }
        Expr::Tuple(tuple) => {
            let mut out = tuple.clone();
            out.elems = tuple
                .elems
                .iter()
                .map(|elem| resolve_closed_match_expr(scope, elem, depth + 1))
                .collect::<Option<_>>()?;
            Some(Expr::Tuple(out))
        }
        Expr::Array(array) => {
            let mut out = array.clone();
            out.elems = array
                .elems
                .iter()
                .map(|elem| resolve_closed_match_expr(scope, elem, depth + 1))
                .collect::<Option<_>>()?;
            Some(Expr::Array(out))
        }
        Expr::Path(path) if path.qself.is_none() => {
            if let Some(name) = path.path.get_ident().map(ToString::to_string) {
                if let Some(expr) = scope.temporal_rewrite_expr_for(&name) {
                    return resolve_closed_match_expr(scope, &expr, depth + 1);
                }
                if let Some(expr) = scope.stable_let_binding_for_term(&name) {
                    return resolve_closed_match_expr(scope, expr, depth + 1);
                }
            }
            if let Some(expr) = scope.const_expr_for_path(&path.path) {
                return resolve_closed_match_expr(scope, &expr, depth + 1);
            }
            Some(expr.clone())
        }
        _ => Some(expr.clone()),
    }
}

fn expr_contains_mutable_reference_or_raw_addr(expr: &Expr) -> bool {
    struct Scan {
        found: bool,
    }

    impl<'ast> Visit<'ast> for Scan {
        fn visit_expr_reference(&mut self, reference: &'ast syn::ExprReference) {
            if reference.mutability.is_some() {
                self.found = true;
            }
            syn::visit::visit_expr_reference(self, reference);
        }

        fn visit_expr_raw_addr(&mut self, raw: &'ast syn::ExprRawAddr) {
            self.found = true;
            syn::visit::visit_expr_raw_addr(self, raw);
        }
    }

    let mut scan = Scan { found: false };
    scan.visit_expr(expr);
    scan.found
}

fn closed_statement_selection_needed(m: &syn::ExprMatch) -> bool {
    m.arms
        .iter()
        .any(|arm| arm.guard.is_some() || pattern_needs_closed_selection(&arm.pat))
}

fn pattern_needs_closed_selection(pat: &Pat) -> bool {
    match pat {
        Pat::Ident(ident) => {
            ident.subpat.is_none()
                && ident.mutability.is_none()
                && ident.by_ref.is_none()
                && !is_const_pattern_ident(&ident.ident.to_string())
        }
        Pat::Tuple(_) | Pat::Or(_) | Pat::Range(_) => true,
        Pat::Paren(paren) => pattern_needs_closed_selection(&paren.pat),
        Pat::Reference(reference) if reference.mutability.is_none() => {
            pattern_needs_closed_selection(&reference.pat)
        }
        Pat::Type(typed) => pattern_needs_closed_selection(&typed.pat),
        _ => false,
    }
}

pub(crate) fn decompose_match(
    m: &syn::ExprMatch,
    scope: &TemporalScope,
    options: &LiftOptions,
) -> Option<MatchSugar> {
    if closed_statement_selection_needed(m) {
        if let Some(body_stmts) = selected_closed_arm_stmts(m, scope, options) {
            if loop_body_mutates(&body_stmts) {
                return None;
            }
            if count_asserts_in_stmts(&body_stmts) > 0 {
                return Some(MatchSugar {
                    arms: vec![MatchArmLift {
                        guard: Some(eq(bool_const(true), bool_const(true))),
                        body_stmts,
                    }],
                });
            }
        }
    }

    // The scrutinee must NOT mutate / advance state and must translate to a stable
    // term (a side-effecting scrutinee is not a timeless value).
    if closure_body_is_side_effecting(&m.expr) {
        return None;
    }
    // Arm-level `#[cfg(..)]` resolution: an arm gated by an INACTIVE cfg does not
    // exist on this target (rustc strips it before codegen), so we drop it before
    // building discriminant guards. A `#[cfg]` whose facts are AMBIGUOUS (no explicit
    // target facts) -> bail (we cannot know whether the arm is present). Corpus shape:
    // num/wrapping.rs `match () { #[cfg(target_pointer_width="32")] () => .., #[cfg(
    // target_pointer_width="64")] () => .. }` -- exactly one arm survives, and the
    // surviving `() => { assert }` is an unconditional body (unit pattern, no
    // discriminant). SOUND: stripping an inactive arm matches the compiled program;
    // an ambiguous cfg bails rather than guess.
    let active_arms = active_match_arms(m, options)?;
    let scrut = translate_term_in_scope(&m.expr, scope).ok()?;
    let last_idx = active_arms.len().checked_sub(1)?;
    let mut arms = Vec::with_capacity(active_arms.len());
    let mut total_asserts = 0usize;
    for (i, arm) in active_arms.iter().enumerate() {
        // An arm guard `pat if cond =>` changes which values reach the arm; the
        // discriminant `pat` alone no longer characterizes the arm. BAIL.
        if arm.guard.is_some() {
            return None;
        }
        let guard = match_arm_guard(&arm.pat, &scrut, i == last_idx, scope)?;
        let body_stmts = arm_body_stmts(&arm.body);
        if loop_body_mutates(&body_stmts) {
            return None;
        }
        total_asserts += count_asserts_in_stmts(&body_stmts);
        arms.push(MatchArmLift { guard, body_stmts });
    }
    (total_asserts > 0).then_some(MatchSugar { arms })
}

impl Sugar for MatchSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let total: usize = self
            .arms
            .iter()
            .map(|a| count_asserts_in_stmts(&a.body_stmts))
            .sum();
        debug_assert!(total > 0, "MatchSugar constructed without assertions");
        let mut conjuncts: Vec<Rc<Formula>> = Vec::new();
        // Running disjunction of prior arms' discriminant guards -- the wildcard's
        // guard is its negation (`_` fires iff no prior arm matched).
        let mut prior_guards: Vec<Rc<Formula>> = Vec::new();
        for arm in &self.arms {
            let arm_guard = match &arm.guard {
                Some(g) => {
                    prior_guards.push(g.clone());
                    g.clone()
                }
                // The final `_`: guard = negation of the disjunction of all prior
                // arm guards. (`decompose_match` guarantees only the last arm is a
                // bare `_`, so `prior_guards` is every preceding discriminant.)
                None => {
                    if prior_guards.is_empty() {
                        // `match scrut { _ => .. }` -- a single catch-all is
                        // unconditional; its guard is vacuous. Lift the body bare
                        // (the asserts are point-wise). Use `true` antecedent so the
                        // emit stays a uniform implication shape.
                        eq(bool_const(true), bool_const(true))
                    } else if prior_guards.len() == 1 {
                        not_(prior_guards[0].clone())
                    } else {
                        not_(or_(prior_guards.clone()))
                    }
                }
            };
            let count = count_asserts_in_stmts(&arm.body_stmts);
            if count == 0 {
                // A diverging / non-asserting arm (`panic!()`, `do_a()`) carries no
                // claim -- it contributes no implication, only its guard to the
                // wildcard's negation (already pushed above). Skip.
                continue;
            }
            let body_conj = self
                .lift_arm_conj(&arm.body_stmts, count, ctx)
                .unwrap_or_else(|| unreachable!("constructed match arm body did not lift"));
            conjuncts.push(implies(arm_guard, body_conj));
        }
        debug_assert!(
            !conjuncts.is_empty(),
            "MatchSugar constructed with assertions but no lifted arm"
        );
        let atom = and_(conjuncts);
        let warrant = Warrant {
            name: Some(format!("{}::match", ctx.scope.local_scope())),
        };
        Outcome::Complete(Desugared::Constraints {
            atom,
            n: total,
            kind: AssertionFactKind::Warranted,
            warrant,
        })
    }
}

impl MatchSugar {
    /// Lift an arm body's statements all-or-nothing through the normal collector,
    /// returning the conjunction of its assert atoms or None (BAIL) if any assert
    /// refuses / is missing (truth-table-or-gutter -- IDENTICAL to
    /// `ConditionalSugar::lift_branch_conj`).
    fn lift_arm_conj(
        &self,
        body_stmts: &[Stmt],
        expected: usize,
        ctx: &SugarCtx,
    ) -> Option<Rc<Formula>> {
        let mut body_entries = Vec::new();
        let mut body_skipped = Vec::new();
        let mut body_lifted = 0usize;
        let mut body_helpers = HashSet::new();
        collect_assertion_entries(
            body_stmts,
            ctx.scope.local_scope(),
            ctx.options,
            ctx.reducer,
            *ctx.float_widths.borrow_mut(),
            &mut body_entries,
            &mut body_skipped,
            &mut body_lifted,
            &mut body_helpers,
            ctx.factory_audits,
            ctx.macro_depth,
            &ctx.scope.plan.interior_mut,
            None,
            ctx.scope.macro_registry(),
            &BTreeMap::new(),
            ctx.scope.fn_registry(),
            &ctx.scope.layout_type_registry,
        );
        let warranted: usize = body_entries
            .iter()
            .filter(|entry| matches!(entry.kind, AssertionFactKind::Warranted))
            .map(|entry| entry.claim_count)
            .sum();
        if !body_skipped.is_empty() || warranted != expected {
            return None;
        }
        Some(and_(body_entries.iter().map(|e| e.atom.clone()).collect()))
    }
}
