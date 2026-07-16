// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `ConditionalSugar`: a guarded point-wise claim (`if cond { asserts } else { asserts }`)
// reduced to `cond => then-conj` and `!cond => else-conj`. Relocated verbatim from the
// `lib.rs` monolith (pure code-motion, zero behavior change). Carries its OWNED
// `decompose_if` constructor. Shared substrate (the collector, the bool-assertion
// translator, `const_fold_bool_guard`, the purity gates) stays in `crate::`.

use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use quote::format_ident;
use sugar_ir_symbolic::{and_, eq, implies, not_, Formula, Term};
use syn::{BinOp, Expr, Stmt};

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, closure_body_is_side_effecting, collect_assertion_entries, const_fold_int_term,
    const_fold_u128_term, count_asserts_in_stmts, loop_body_mutates, token_key, AssertionFactKind,
    Desugared, Effect, FactoryAuditLog, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar,
    SugarCtx, TemporalScope, Warrant,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "conditional",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_conditional_good() {
                    let guard = std::env::args().len() > 0;
                    if guard {
                        assert_eq!(2_i32 + 2, 4);
                    } else {
                        assert_eq!(2_i32 + 2, 4);
                    }
                }
            "#,
            r#"
                #[test]
                fn t_conditional_bad() {
                    let guard = std::env::args().len() > 0;
                    if guard {
                        assert_eq!(2_i32 + 2, 5);
                    } else {
                        assert_eq!(2_i32 + 2, 5);
                    }
                }
            "#,
        ),
        recognize_composite,
    );

/// COMPOSITE recognizer for `Expr::If`: the implication composite ([`ConditionalSugar`]
/// via [`decompose_if`]). Byte-identical to the `Expr::If(i) => decompose_if(i)`
/// arm of the old fat `build_composite`, with gaps now loud.
pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::If(i) => decompose_if(i, fcx).map(|node| Box::new(node) as Box<dyn Sugar>),
        _ => None,
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_statement_conditional(
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

/// EXACT-OR-BAIL: the guard must translate to a Formula via the SAME path an
/// `assert!(guard)` would take (`translate_bool_assertion`); the then/else asserts
/// must lift all-or-nothing through the normal collector; the guard / body must be
/// pure (no mutation / iterator-advance -- a side-effecting branch is not a
/// timeless point-wise claim). Any miss -> None (bail; the existing if-context
/// refusal stands).
pub(crate) struct ConditionalSugar {
    cond: Expr,
    guard_eval: GuardEval,
    then_stmts: Vec<Stmt>,
    else_stmts: Vec<Stmt>,
    then_tail: Option<SugarBody<CompositeFloor>>,
    else_tail: Option<SugarBody<CompositeFloor>>,
}

impl Sugar for ConditionalSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let then_count = count_asserts_in_stmts(&self.then_stmts);
        let else_count = count_asserts_in_stmts(&self.else_stmts);
        if then_count + else_count == 0 {
            return self.desugar_sequence_branch(ctx).unwrap_or_else(|| {
                if self.then_tail.is_none() && self.else_tail.is_none() {
                    Outcome::Complete(Desugared::Seq(Vec::new()))
                } else {
                    self.runtime_guard_or_gap("sequence conditional did not select a branch")
                }
            });
        }
        // The assertion-bearing path still uses the legacy `Option<Desugared>` bridge.
        // A structural `None` here is plumbing for the older fall-through path, not a
        // semantic runtime/effect verdict.
        match (|| {
            // An `if let PAT = e { .. }` is a pattern-match guard, not a boolean
            // predicate -- the panic-locus path handles the diverging-else shape;
            // anything else here bails (we do not model the bound bindings).
            if matches!(&self.cond, Expr::Let(_)) {
                return None;
            }
            // The guard must not mutate / advance state (a side-effecting condition is
            // not a timeless predicate). Reuse the verified closure-body scanner over
            // the condition expression.
            if closure_body_is_side_effecting(&self.cond) {
                return Some(Outcome::Incomplete(Effect::IfGuardRuntime {
                    boundary: token_key(&self.cond),
                }));
            }
            // At least one branch must carry an assertion (else nothing to classify --
            // leave it to the existing handling).
            match const_fold_bool_guard(ctx, &self.guard_eval) {
                Ok(Some(guard_value)) => {
                    let (active_stmts, active_count, inactive_count) = if guard_value {
                        (&self.then_stmts, then_count, else_count)
                    } else {
                        (&self.else_stmts, else_count, then_count)
                    };
                    let mut conjuncts = Vec::new();
                    if active_count > 0 {
                        conjuncts.push(self.lift_branch_conj(active_stmts, active_count, ctx)?);
                    }
                    if inactive_count > 0 {
                        conjuncts.push(eq(bool_const(true), bool_const(true)));
                    }
                    if conjuncts.is_empty() {
                        return None;
                    }
                    let atom = and_(conjuncts);
                    let warrant = Warrant {
                        name: Some(format!("{}::if", ctx.scope.local_scope())),
                    };
                    return Some(Outcome::Complete(Desugared::Constraints {
                        atom,
                        n: active_count + inactive_count,
                        kind: AssertionFactKind::Warranted,
                        warrant,
                    }));
                }
                Ok(None) => {}
                Err(effect) => return Some(Outcome::Incomplete(effect)),
            }
            // Neither branch may mutate captured state: a single guarded implication is
            // a point-wise claim only if the branch body is pure.
            if loop_body_mutates(&self.then_stmts) || loop_body_mutates(&self.else_stmts) {
                return Some(Outcome::Incomplete(Effect::ConditionalBranchMutation {
                    boundary: self.branch_mutation_boundary(),
                }));
            }
            // The guard formula. FIRST try const-folding a compile-time-constant guard
            // (`!false` -> true, `!true` -> false, `cfg!(target_pointer_width=..)` ->
            // the resolved cfg bool): such a guard's truth is fixed from the source, so
            // it lifts as a CONSTANT antecedent `<folded> == true`. The emitted
            // `guard_const => P` is faithful -- a true guard forces P, a false guard makes
            // the implication trivially hold (the body never runs). This drains the
            // const/cfg if-guard bucket (corpus: bool.rs / step.rs / fmt/mod.rs) the
            // expression-predicate path below cannot reach (a bare bool literal / `cfg!`
            // is not a translatable comparison). Otherwise fall back to lifting the guard
            // EXACTLY as `assert!(guard)` would; a guard outside the liftable predicate
            // set (an opaque method call, a float refinement we cannot width, ...) bails.
            let guard = match crate::sugar::constraint::assertion_entry_with_audits(
                &self.cond,
                ctx.scope,
                &ctx.float_widths.borrow(),
                ctx.factory_audits,
            ) {
                Ok(lowered) => lowered.atom,
                Err(effect) => return Some(Outcome::Incomplete(effect)),
            };

            let mut conjuncts: Vec<Rc<Formula>> = Vec::new();
            if then_count > 0 {
                let then_conj = self.lift_branch_conj(&self.then_stmts, then_count, ctx)?;
                // guard => then.
                conjuncts.push(implies(guard.clone(), then_conj));
            }
            if else_count > 0 {
                let else_conj = self.lift_branch_conj(&self.else_stmts, else_count, ctx)?;
                // not guard => else (the else branch fires when the guard is false).
                conjuncts.push(implies(not_(guard.clone()), else_conj));
            }
            let atom = and_(conjuncts);
            let warrant = Warrant {
                name: Some(format!("{}::if", ctx.scope.local_scope())),
            };
            Some(Outcome::Complete(Desugared::Constraints {
                atom,
                n: then_count + else_count,
                kind: AssertionFactKind::Warranted,
                warrant,
            }))
        })() {
            Some(outcome) => outcome,
            None => self.runtime_guard_or_gap("assertion conditional did not reduce"),
        }
    }
}

impl ConditionalSugar {
    fn desugar_sequence_branch(&self, ctx: &SugarCtx) -> Option<Outcome> {
        if guard_exits_with_return(&self.cond) {
            return Some(Outcome::Complete(Desugared::Seq(Vec::new())));
        }
        let guard_value = match const_fold_bool_guard(ctx, &self.guard_eval) {
            Ok(Some(value)) => value,
            Ok(None) => return None,
            Err(effect) => return Some(Outcome::Incomplete(effect)),
        };
        let branch = if guard_value {
            &self.then_tail
        } else {
            &self.else_tail
        };
        branch.as_ref().map(|tail| tail.desugar(ctx))
    }

    /// Lift a branch's statements all-or-nothing through the normal collector,
    /// returning the conjunction of its assert atoms or None (bail) if any branch
    /// assert refuses / is missing (truth-table-or-gutter, mirroring
    /// `lift_bounded_forall`'s body lift).
    fn lift_branch_conj(
        &self,
        branch_stmts: &[Stmt],
        expected: usize,
        ctx: &SugarCtx,
    ) -> Option<Rc<Formula>> {
        let branch_stmts = branch_stmts_with_stable_bindings(branch_stmts, ctx);
        let mut body_entries = Vec::new();
        let mut body_skipped = Vec::new();
        let mut body_lifted = 0usize;
        let mut body_helpers = HashSet::new();
        collect_assertion_entries(
            &branch_stmts,
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
        if !body_skipped.is_empty() || body_lifted != expected {
            return None;
        }
        Some(and_(body_entries.iter().map(|e| e.atom.clone()).collect()))
    }

    fn runtime_guard_or_gap(&self, reason: &str) -> Outcome {
        if matches!(&self.cond, Expr::Let(_)) || crate::if_guard_is_runtime(&self.cond) {
            return Outcome::Incomplete(Effect::IfGuardRuntime {
                boundary: token_key(&self.cond),
            });
        }
        conditional_gap(reason)
    }

    fn branch_mutation_boundary(&self) -> String {
        let branch = if loop_body_mutates(&self.then_stmts) {
            "then"
        } else {
            "else"
        };
        format!("{branch} branch guarded by `{}`", token_key(&self.cond))
    }
}

fn single_expr_tail(stmts: &[Stmt]) -> Option<&Expr> {
    match stmts {
        [Stmt::Expr(expr, None)] => Some(expr),
        _ => None,
    }
}

fn guard_exits_with_return(cond: &Expr) -> bool {
    match cond {
        Expr::Return(_) => true,
        Expr::Paren(p) => guard_exits_with_return(&p.expr),
        Expr::Group(g) => guard_exits_with_return(&g.expr),
        Expr::Unary(u) => guard_exits_with_return(&u.expr),
        _ => false,
    }
}

struct GuardEval {
    expr: Expr,
    kind: GuardEvalKind,
}

enum GuardEvalKind {
    Transparent(Box<GuardEval>),
    Not(Box<GuardEval>),
    And(Box<GuardEval>, Box<GuardEval>),
    Or(Box<GuardEval>, Box<GuardEval>),
    Compare {
        lhs: SugarBody<TermFloor>,
        rhs: SugarBody<TermFloor>,
        op: GuardCompareOp,
    },
    Other,
}

#[derive(Clone, Copy)]
enum GuardCompareOp {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl GuardCompareOp {
    fn eval(self, ordering: std::cmp::Ordering) -> bool {
        match self {
            Self::Eq => ordering == std::cmp::Ordering::Equal,
            Self::Ne => ordering != std::cmp::Ordering::Equal,
            Self::Lt => ordering == std::cmp::Ordering::Less,
            Self::Le => ordering != std::cmp::Ordering::Greater,
            Self::Gt => ordering == std::cmp::Ordering::Greater,
            Self::Ge => ordering != std::cmp::Ordering::Less,
        }
    }
}

impl GuardEval {
    fn new(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        let kind = match expr {
            Expr::Paren(p) => GuardEvalKind::Transparent(Box::new(Self::new(&p.expr, fcx))),
            Expr::Group(g) => GuardEvalKind::Transparent(Box::new(Self::new(&g.expr, fcx))),
            Expr::Unary(u) if matches!(u.op, syn::UnOp::Not(_)) => {
                GuardEvalKind::Not(Box::new(Self::new(&u.expr, fcx)))
            }
            Expr::Binary(binary) => match binary.op {
                BinOp::And(_) | BinOp::BitAnd(_) => GuardEvalKind::And(
                    Box::new(Self::new(&binary.left, fcx)),
                    Box::new(Self::new(&binary.right, fcx)),
                ),
                BinOp::Or(_) | BinOp::BitOr(_) => GuardEvalKind::Or(
                    Box::new(Self::new(&binary.left, fcx)),
                    Box::new(Self::new(&binary.right, fcx)),
                ),
                BinOp::Eq(_) => compare_guard(&binary.left, &binary.right, GuardCompareOp::Eq, fcx),
                BinOp::Ne(_) => compare_guard(&binary.left, &binary.right, GuardCompareOp::Ne, fcx),
                BinOp::Lt(_) => compare_guard(&binary.left, &binary.right, GuardCompareOp::Lt, fcx),
                BinOp::Le(_) => compare_guard(&binary.left, &binary.right, GuardCompareOp::Le, fcx),
                BinOp::Gt(_) => compare_guard(&binary.left, &binary.right, GuardCompareOp::Gt, fcx),
                BinOp::Ge(_) => compare_guard(&binary.left, &binary.right, GuardCompareOp::Ge, fcx),
                _ => GuardEvalKind::Other,
            },
            _ => GuardEvalKind::Other,
        };
        Self {
            expr: expr.clone(),
            kind,
        }
    }

    fn eval(&self, ctx: &SugarCtx) -> Result<Option<bool>, Effect> {
        if let Some(value) = crate::const_fold_bool_guard(&self.expr, ctx.options) {
            return Ok(Some(value));
        }
        if guard_mentions_stable_local_path(ctx, &self.expr) {
            return Ok(None);
        }
        match &self.kind {
            GuardEvalKind::Transparent(inner) => inner.eval(ctx),
            GuardEvalKind::Not(inner) => Ok(inner.eval(ctx)?.map(|value| !value)),
            GuardEvalKind::And(left, right) => {
                let Some(left) = left.eval(ctx)? else {
                    return Ok(None);
                };
                if !left {
                    return Ok(Some(false));
                }
                Ok(right.eval(ctx)?.map(|right| left && right))
            }
            GuardEvalKind::Or(left, right) => {
                let Some(left) = left.eval(ctx)? else {
                    return Ok(None);
                };
                if left {
                    return Ok(Some(true));
                }
                Ok(right.eval(ctx)?.map(|right| left || right))
            }
            GuardEvalKind::Compare { lhs, rhs, op } => compare_terms(ctx, lhs, rhs, *op),
            GuardEvalKind::Other => Ok(None),
        }
    }
}

fn compare_guard(lhs: &Expr, rhs: &Expr, op: GuardCompareOp, fcx: &SugarBuildCtx) -> GuardEvalKind {
    GuardEvalKind::Compare {
        lhs: SugarBody::term(lhs, fcx),
        rhs: SugarBody::term(rhs, fcx),
        op,
    }
}

fn const_fold_bool_guard(ctx: &SugarCtx, guard: &GuardEval) -> Result<Option<bool>, Effect> {
    guard.eval(ctx)
}

fn guard_mentions_stable_local_path(ctx: &SugarCtx, expr: &Expr) -> bool {
    match expr {
        Expr::Path(path) if path.qself.is_none() => path.path.get_ident().is_some_and(|ident| {
            ctx.scope
                .stable_let_binding_for_term(&ident.to_string())
                .is_some()
        }),
        Expr::Path(_) => false,
        Expr::Paren(p) => guard_mentions_stable_local_path(ctx, &p.expr),
        Expr::Group(g) => guard_mentions_stable_local_path(ctx, &g.expr),
        Expr::Unary(u) => guard_mentions_stable_local_path(ctx, &u.expr),
        Expr::Binary(binary) => {
            guard_mentions_stable_local_path(ctx, &binary.left)
                || guard_mentions_stable_local_path(ctx, &binary.right)
        }
        _ => false,
    }
}

fn compare_terms(
    ctx: &SugarCtx,
    lhs: &SugarBody<TermFloor>,
    rhs: &SugarBody<TermFloor>,
    op: GuardCompareOp,
) -> Result<Option<bool>, Effect> {
    let lhs = term_for_guard_operand(ctx, lhs)?;
    let rhs = term_for_guard_operand(ctx, rhs)?;
    let (Some(lhs), Some(rhs)) = (lhs, rhs) else {
        return Ok(None);
    };
    let ordering = match (const_fold_u128_term(&lhs), const_fold_u128_term(&rhs)) {
        (Some(left), Some(right)) => left.cmp(&right),
        (Some(left), None) => {
            let Some(right) =
                const_fold_int_term(&rhs).and_then(|value| u128::try_from(value).ok())
            else {
                return Ok(None);
            };
            left.cmp(&right)
        }
        (None, Some(right)) => {
            let Some(left) = const_fold_int_term(&lhs).and_then(|value| u128::try_from(value).ok())
            else {
                return Ok(None);
            };
            left.cmp(&right)
        }
        (None, None) => {
            let (Some(left), Some(right)) = (const_fold_int_term(&lhs), const_fold_int_term(&rhs))
            else {
                return Ok(None);
            };
            left.cmp(&right)
        }
    };
    Ok(Some(op.eval(ordering)))
}

fn term_for_guard_operand(
    ctx: &SugarCtx,
    body: &SugarBody<TermFloor>,
) -> Result<Option<Rc<Term>>, Effect> {
    match body.desugar(ctx) {
        Outcome::Complete(desugared) => Ok(desugared.into_term()),
        Outcome::Incomplete(effect) => Err(effect),
    }
}

fn branch_stmts_with_stable_bindings(branch_stmts: &[Stmt], ctx: &SugarCtx) -> Vec<Stmt> {
    let mut stmts = Vec::new();
    for (name, init) in ctx.scope.let_bindings_iter() {
        let ident = format_ident!("{name}");
        let init = init.clone();
        stmts.push(syn::parse_quote!(let #ident = #init;));
    }
    stmts.extend(branch_stmts.iter().cloned());
    stmts
}

fn conditional_gap(reason: &str) -> ! {
    panic!("conditional did not reach a lawful floor: {reason}")
}

/// Build a `ConditionalSugar` from a `Stmt::Expr(Expr::If(..))`. The then-branch
/// statements and the else-branch statements (a plain `else { .. }` block; an
/// `else if` chains as a nested `Expr::If`, captured as the single else statement)
/// are the guarded claims. None if the if has no body to classify.
pub(crate) fn decompose_if(i: &syn::ExprIf, fcx: &SugarBuildCtx) -> Option<ConditionalSugar> {
    let else_stmts: Vec<Stmt> = match &i.else_branch {
        Some((_, else_expr)) => match &**else_expr {
            Expr::Block(b) => b.block.stmts.clone(),
            // `else if ..` / any other else expr: keep as one statement so its
            // asserts are counted and lifted (a nested ConditionalSugar reached via
            // the recursive collector). A non-block else with asserts that does not
            // fully lift will make the branch lift bail -- honest.
            other => vec![Stmt::Expr(other.clone(), None)],
        },
        None => Vec::new(),
    };
    Some(ConditionalSugar {
        cond: (*i.cond).clone(),
        guard_eval: GuardEval::new(&i.cond, fcx),
        then_tail: branch_tail_body(&i.then_branch.stmts, fcx),
        else_tail: branch_tail_body(&else_stmts, fcx),
        then_stmts: i.then_branch.stmts.clone(),
        else_stmts,
    })
}

fn branch_tail_body(stmts: &[Stmt], fcx: &SugarBuildCtx) -> Option<SugarBody<CompositeFloor>> {
    single_expr_tail(stmts).map(|tail| SugarBody::composite(tail, fcx))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, ReductionCtx, TemporalPlan,
        TemporalScope,
    };

    #[test]
    fn if_let_sequence_guard_is_typed_effect_not_term_factory_gap() {
        let expr: Expr = syn::parse_str("if let Some(req) = require { vec![req] } else { vec![] }")
            .expect("parse if-let expression");
        let Expr::If(if_expr) = expr else {
            panic!("expected if expression");
        };
        let scope = TemporalScope::new("conditional-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = decompose_if(&if_expr, &fcx).expect("conditional recognizes if-let shape");
        let items: Vec<syn::Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);

        let outcome =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| sugar.desugar(&ctx)))
                .expect("if-let sequence guard must be a typed effect, not a term factory gap");

        let Outcome::Incomplete(effect) = outcome else {
            panic!("if-let guard must not fabricate a selected branch");
        };
        assert!(
            effect.reason().contains("assertion under if context"),
            "effect should name the runtime if-let guard: {}",
            effect.reason()
        );
    }

    #[test]
    fn literal_sequence_conditional_still_selects_branch() {
        let expr: Expr = syn::parse_str("if true { vec![1] } else { vec![2] }")
            .expect("parse conditional expression");
        let Expr::If(if_expr) = expr else {
            panic!("expected if expression");
        };
        let scope = TemporalScope::new("conditional-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = decompose_if(&if_expr, &fcx).expect("conditional recognizes if shape");
        let items: Vec<syn::Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);

        let Outcome::Complete(Desugared::Seq(seq)) = sugar.desugar(&ctx) else {
            panic!("literal guard should select a sequence branch");
        };
        assert_eq!(seq.len(), 1);
        assert_eq!(
            seq[0].value.as_ref().and_then(crate::ConstVal::as_int),
            Some(1)
        );
    }
}
