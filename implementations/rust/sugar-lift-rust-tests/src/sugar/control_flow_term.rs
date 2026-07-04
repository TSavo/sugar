// SPDX-License-Identifier: Apache-2.0
//
// `ControlFlowTermSugar`: the refuse/router-side node for an effectful control-flow construct in
// TERM position -- a `try { .. }` block (`Expr::TryBlock`), an `async { .. }` block
// (`Expr::Async`), or a `?` operator (`Expr::Try`). `try { .. }` and `async { .. }` still own the
// single `Effect::ControlFlow` verdict the old inline
// `Expr::TryBlock | Expr::Async | Expr::Try` arm of `translate_term_in_scope` made: those
// constructs are not timeless point-wise values. `?` now first reduces its child through the term
// floor; a grounded `res:ok(v)` becomes `v`, and a grounded `res:err(_)` becomes typed
// `RaiseEffect::ResultErr` routed through `RouteRaisesOperation`. Non-Result or unsupported `?`
// shapes remain the old loud `ControlFlow` refusal.
//
// (This is the TERM-position producer of `Effect::ControlFlow`. The STATEMENT-position
// producer is the `.await` continuation leaf of the landed `StatementPositionSugar` node; an
// assertion-bearing async future handed to a driver call is a separate FutureHandoff sugar.)
//
// THE TARGET SHAPE (`walk -> new -> compose -> desugar() collapses to one Outcome`):
// `decompose_control_flow_term` (the `build` arm) recognizes the construct (an `Expr::TryBlock`
// / `Expr::Async` / `Expr::Try`) and `new`s the node, composing the expr's token-key and, for
// `?`, the inner term floor -- with NO degeneracy opinion and no early exit (its only `None` is
// non-recognition: any other expr is not a control-flow-term bucket -- nothing to classify here;
// it stays on the constructive `translate_term_in_scope` paths / the term catch-all). `desugar`
// is where the verdict is made:
//   * the CONTROL-FLOW leaf: a recognized try/async construct is deferred/early-returning
//     control flow, not a timeless point-wise value -> `ControlFlow`.
//   * the QUESTION-MARK leaf: a grounded Result is routed through the Phase 2 raise spine.
// The composite makes NO check of its own: recognition selects the node; reduction owns the
// verdict.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::route_raises_operation::{RouteRaiseHandler, RouteRaisesOperation};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{MonadicFloorAccept, MonadicFloorVisitor};
use crate::{token_key, Desugared, Effect, Outcome, RaiseEffect, Sugar, SugarCtx};

pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "control_flow_term",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_question_mark_good() -> Result<(), i32> {
                    let value = Ok::<i32, i32>(5)?;
                    assert_eq!(value, 5);
                    Ok(())
                }
            "#,
            r#"
                #[test]
                fn t_question_mark_bad() -> Result<(), i32> {
                    let value = Ok::<i32, i32>(5)?;
                    assert_eq!(value, 6);
                    Ok(())
                }
            "#,
        ),
        recognize_term,
    );

pub(crate) const COMPOSITE_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "control_flow_composite",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "control-flow composite effect surface needs statement-position assertion anchoring",
        ),
        recognize_composite,
    );

/// TERM recognizer for effectful control-flow (`Expr::TryBlock`/`Async`/`Try`): the
/// `ControlFlowTermSugar` refuse-shape. TERM and COMPOSITE roles both carry the same typed node;
/// the child effect's reason is rendered only when the caller consumes the `Outcome`.
pub(crate) fn recognize_term(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => boxed_control_flow(expr, fcx),
        _ => None,
    }
}

/// COMPOSITE recognizer for effectful control-flow (`Expr::TryBlock`/`Async`/`Try`):
/// boxes the `ControlFlowTermSugar` refuse-shape directly (the collector's `.complete()`
/// site reads its `Effect::ControlFlow` Incomplete). Byte-identical to the
/// `Expr::TryBlock | Expr::Async | Expr::Try => decompose_control_flow_term(expr)`
/// COMPOSITE arm of the old fat factory.
pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => boxed_control_flow(expr, fcx),
        _ => None,
    }
}

fn boxed_control_flow(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    decompose_control_flow_term(expr, fcx).map(|node| Box::new(node) as Box<dyn Sugar>)
}

/// The effectful control-flow construct in term position (`try`/`async`/`?`), composed as a
/// node whose `desugar` makes the control-flow verdict at its single LEAF. See the module header.
pub(crate) struct ControlFlowTermSugar {
    /// The full term expr's token-key -- the `boundary` is `token_key(&expr)` (byte-identical
    /// to the old inline `token_key(expr)`), the leaf whose construct is the deferred/early-
    /// returning control flow.
    boundary: String,
    kind: ControlFlowTermKind,
}

enum ControlFlowTermKind {
    DeferredControlFlow,
    QuestionMark { inner: SugarBody<TermFloor> },
}

impl ControlFlowTermSugar {
    /// CONTROL-FLOW leaf: a recognized try/async construct is deferred or early-returning
    /// control flow -- not a single timeless point-wise value, no construction-from-literals to
    /// walk -> `ControlFlow`. Recognition (the construct shape) is this leaf's precondition, so
    /// it always fires for a built node; it never completes.
    fn control_flow_effect(&self) -> Effect {
        Effect::ControlFlow {
            boundary: self.boundary.clone(),
        }
    }

    /// The ctx-free reduction for the try/async leaf. `?` uses the ctx-aware route below because
    /// it must reduce its child and preserve the current scope for matching handlers.
    pub(crate) fn desugar_ctx_free(&self) -> Outcome {
        Outcome::Incomplete(self.control_flow_effect())
    }
}

impl Sugar for ControlFlowTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.kind {
            ControlFlowTermKind::DeferredControlFlow => self.desugar_ctx_free(),
            ControlFlowTermKind::QuestionMark { inner } => {
                reduce_question_mark(inner, &self.boundary, ctx, Vec::new())
            }
        }
    }
}

/// Build (`new` + compose, NO degeneracy opinion) a `ControlFlowTermSugar` from an expr.
/// Recognizes the construct: an `Expr::TryBlock` / `Expr::Async` / `Expr::Try`. Returns `None`
/// (declines to RECOGNIZE) for any other expr -- those are NOT refused here; they stay on the
/// constructive `translate_term_in_scope` paths / the term catch-all (the fake-refuse
/// guardrail). It makes NO verdict -- the control-flow decision is
/// `ControlFlowTermSugar::desugar`'s (and its leaf's) alone.
pub(crate) fn decompose_control_flow_term(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<ControlFlowTermSugar> {
    match expr {
        Expr::TryBlock(_) | Expr::Async(_) => Some(ControlFlowTermSugar {
            boundary: token_key(expr),
            kind: ControlFlowTermKind::DeferredControlFlow,
        }),
        Expr::Try(try_expr) => Some(ControlFlowTermSugar {
            boundary: token_key(expr),
            kind: ControlFlowTermKind::QuestionMark {
                inner: SugarBody::term(&try_expr.expr, fcx),
            },
        }),
        _ => None,
    }
}

fn reduce_question_mark(
    inner: &SugarBody<TermFloor>,
    boundary: &str,
    ctx: &SugarCtx,
    handlers: Vec<&dyn RouteRaiseHandler>,
) -> Outcome {
    let term = match inner.reduce(ctx) {
        Outcome::Complete(desugared) => match desugared.into_term() {
            Some(term) => term,
            None => panic!("question-mark inner completed as non-term for `{boundary}`"),
        },
        Outcome::Incomplete(effect) => {
            return RouteRaisesOperation::new(handlers, "QuestionMark")
                .route_incomplete_with_scope(Outcome::Incomplete(effect), ctx.scope)
        }
    };
    term.accept_monadic_floor(QuestionMarkVisitor {
        boundary,
        scope: ctx.scope,
        handlers,
    })
}

struct QuestionMarkVisitor<'a> {
    boundary: &'a str,
    scope: &'a crate::TemporalScope,
    handlers: Vec<&'a dyn RouteRaiseHandler>,
}

impl MonadicFloorVisitor for QuestionMarkVisitor<'_> {
    type Output = Outcome;

    fn visit_some(self, _inner: &Rc<Term>) -> Self::Output {
        self.unsupported_control_flow("Option::Some")
    }

    fn visit_none(self) -> Self::Output {
        self.unsupported_control_flow("Option::None")
    }

    fn visit_ok(self, inner: &Rc<Term>) -> Self::Output {
        Outcome::Complete(Desugared::Term(Rc::clone(inner)))
    }

    fn visit_err(self, _inner: &Rc<Term>) -> Self::Output {
        let effect = Effect::Raise(RaiseEffect::ResultErr {
            boundary: self.boundary.to_string(),
        });
        RouteRaisesOperation::new(self.handlers, "QuestionMark")
            .route_incomplete_with_scope(Outcome::Incomplete(effect), self.scope)
    }

    fn visit_non_monadic(self, _term: &Rc<Term>) -> Self::Output {
        self.unsupported_control_flow("non-Result")
    }
}

impl QuestionMarkVisitor<'_> {
    fn unsupported_control_flow(self, kind: &str) -> Outcome {
        Outcome::Incomplete(Effect::ControlFlow {
            boundary: format!("{} ({kind} ?)", self.boundary),
        })
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use sugar_ir_symbolic::{ConstValue, Term};

    use super::*;
    use crate::{Desugared, LiftOptions, RaiseEffect, ReductionCtx, TemporalPlan, TemporalScope};

    fn ctx() -> (TemporalScope, LiftOptions) {
        (
            TemporalScope::new("question-mark-test", TemporalPlan::default()),
            LiftOptions::default(),
        )
    }

    fn run_expr(src: &str) -> Outcome {
        let expr: Expr = syn::parse_str(src).expect("question-mark expr parses");
        let (scope, options) = ctx();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize_term(&SourceFragment::expr(&expr, "<question-mark-test>"), &fcx)
            .expect("question mark recognized");
        let items: Vec<syn::Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = crate::FloatWidthScope::new();
        let sugar_ctx = crate::sugar_ctx_with_factory_audits(
            &scope,
            &options,
            &reducer,
            &mut float_widths,
            0,
            None,
        );
        sugar.reduce(&sugar_ctx)
    }

    fn assert_int_term(outcome: Outcome, expected: i128) {
        let Outcome::Complete(Desugared::Term(term)) = outcome else {
            panic!("expected complete term");
        };
        let Term::Const {
            value: ConstValue::Int(got),
            ..
        } = term.as_ref()
        else {
            panic!("expected int const term");
        };
        assert_eq!(*got, expected);
    }

    #[test]
    fn question_mark_ok_path_reduces_to_inner_term() {
        assert_int_term(run_expr("Ok(7)?"), 7);
    }

    #[test]
    fn question_mark_err_path_routes_to_unmatched_result_err() {
        let Outcome::Incomplete(Effect::Raise(RaiseEffect::ResultErr { boundary })) =
            run_expr("Err(9)?")
        else {
            panic!("Err(_)? must propagate a typed ResultErr raise");
        };
        assert!(
            boundary.contains("Err"),
            "boundary should name the question-mark source, got {boundary}"
        );
    }
}
