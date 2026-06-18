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
use syn::{Arm, Expr, Lit, Pat, Path, Stmt};

use crate::sugar::backstop::boxed;
use crate::sugar::configuration::{CfgDisposition, ConfigurationSugar};
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    bool_const, closure_body_is_side_effecting, collect_assertion_entries, count_asserts_in_stmts,
    loop_body_mutates, path_to_variant_string, strict_variant_path, translate_lit,
    translate_term_in_scope, wrapped_variant, Desugared, LiftOptions, Outcome, Sugar, SugarCtx,
    TemporalScope, Warrant,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("match_node", recognize_composite);

/// COMPOSITE recognizer for `Expr::Match`: the conjunction composite ([`MatchSugar`]
/// via [`decompose_match`]). Byte-identical to the
/// `Expr::Match(m) => boxed(decompose_match(m, fcx.scope(), fcx.options()))` arm of the old
/// fat `build_composite`.
pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Match(m) => Some(boxed(decompose_match(m, fcx.scope(), fcx.options()))),
        _ => None,
    }
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
/// is never reached on the filter path. It digs the empty floor for soundness if it ever is.
struct ArmPresent;
impl Sugar for ArmPresent {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Dug(Desugared::Seq(Vec::new()))
    }
}

pub(crate) fn decompose_match(
    m: &syn::ExprMatch,
    scope: &TemporalScope,
    options: &LiftOptions,
) -> Option<MatchSugar> {
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
    let active_arms: Vec<&syn::Arm> = {
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
        kept
    };
    let scrut = translate_term_in_scope(&m.expr, scope).ok()?;
    let last_idx = active_arms.len().checked_sub(1)?;
    let mut arms = Vec::with_capacity(active_arms.len());
    for (i, arm) in active_arms.iter().enumerate() {
        // An arm guard `pat if cond =>` changes which values reach the arm; the
        // discriminant `pat` alone no longer characterizes the arm. BAIL.
        if arm.guard.is_some() {
            return None;
        }
        let guard = match_arm_guard(&arm.pat, &scrut, i == last_idx, scope)?;
        arms.push(MatchArmLift {
            guard,
            body_stmts: arm_body_stmts(&arm.body),
        });
    }
    Some(MatchSugar { arms })
}

impl Sugar for MatchSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // TOTAL: the dig body computes the legacy `Option<Desugared>`; `Outcome::from_opt`
        // lifts it (the structural bail -> `Hit(Effect::Unsupported)`, discarded by the
        // fall-through consumer exactly as the old `None` was).
        Outcome::from_opt((|| {
            // At least one arm must carry an assertion (else nothing to classify --
            // leave it to the existing handling, e.g. a non-asserting `match p { A =>
            // do_a(), B => do_b() }`). Mirrors `ConditionalSugar`'s `then+else == 0`.
            let total: usize = self
                .arms
                .iter()
                .map(|a| count_asserts_in_stmts(&a.body_stmts))
                .sum();
            if total == 0 {
                return None;
            }
            // No arm body may mutate captured state: a single guarded implication is a
            // point-wise claim only if the body is pure (mirrors `ConditionalSugar`).
            if self.arms.iter().any(|a| loop_body_mutates(&a.body_stmts)) {
                return None;
            }
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
                let body_conj = self.lift_arm_conj(&arm.body_stmts, count, ctx)?;
                conjuncts.push(implies(arm_guard, body_conj));
            }
            // If every asserting arm bailed there'd be nothing here -- but `total > 0`
            // and each asserting arm either lifts (push) or returns None above, so a
            // non-empty `conjuncts` is guaranteed when we reach here.
            let atom = and_(conjuncts);
            let warrant = Warrant {
                name: Some(format!("{}::match", ctx.scope.local_scope())),
            };
            Some(Desugared::Constraints {
                atom,
                n: total,
                warrant,
            })
        })())
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
            ctx.macro_depth,
            &ctx.scope.plan.interior_mut,
            &BTreeMap::new(),
        );
        if !body_skipped.is_empty() || body_entries.len() != expected {
            return None;
        }
        Some(and_(body_entries.iter().map(|e| e.atom.clone()).collect()))
    }
}
