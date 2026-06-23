// SPDX-License-Identifier: Apache-2.0
//
// `ControlFlowTermSugar`: the REFUSE-side node for an effectful control-flow construct in TERM
// position -- a `try { .. }` block (`Expr::TryBlock`), an `async { .. }` block (`Expr::Async`),
// or a `?` operator (`Expr::Try`). It OWNS, in its own `desugar`, the single control-flow
// verdict the old inline `Expr::TryBlock | Expr::Async | Expr::Try` arm of
// `translate_term_in_scope` made -- such a construct is NOT a single timeless point-wise value:
// a `try` block early-returns its `Err`, an `async` block is a future evaluated elsewhere, a `?`
// is a conditional early-return. There is no construction-from-literals to walk, so no value
// lifter could read a single `t`. A SOURCE property, not a missing lift. Typed as
// `Effect::ControlFlow`.
//
// (This is the TERM-position producer of `Effect::ControlFlow`. The STATEMENT-position
// producer is the `.await` continuation leaf of the landed `StatementPositionSugar` node; an
// assertion-bearing async future handed to a driver call is a separate FutureHandoff sugar.)
//
// THE TARGET SHAPE (`walk -> new -> compose -> desugar() collapses to one Outcome`):
// `decompose_control_flow_term` (the `build` arm) recognizes the construct (an `Expr::TryBlock`
// / `Expr::Async` / `Expr::Try`) and `new`s the node, composing the expr's token-key as the
// single CHILD LEAF -- with NO degeneracy opinion and no early exit (its only `None` is
// non-recognition: any other expr is not a control-flow-term bucket -- nothing to classify here;
// it stays on the constructive `translate_term_in_scope` paths / the term catch-all). `desugar`
// is where the verdict is made, and the single LEAF owns it:
//   * the CONTROL-FLOW leaf: a recognized try/async/`?` construct is deferred/early-returning
//     control flow, not a timeless point-wise value -> `ControlFlow`.
// The composite makes NO check of its own: a recognized node always returns Incomplete its control-flow leaf
// (recognition -- a try/async/`?` construct -- IS the verdict's precondition). The verdict is
// purely SYNTACTIC, so it is delegated by `desugar` to `desugar_ctx_free`. The STRUCTURAL
// backstop (`Effect::Unsupported` with `STRUCTURAL_BACKSTOP_REASON`) is the total-but-unreachable
// tail kept to mirror the node shape.

use syn::Expr;

use crate::sugar::backstop::boxed;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::reasoned_incomplete;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("control_flow_term", recognize_term);

pub(crate) const COMPOSITE_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("control_flow_composite", recognize_composite);

/// TERM recognizer for effectful control-flow (`Expr::TryBlock`/`Async`/`Try`): the
/// `ControlFlowTermSugar` refuse-shape, surfaced as a reasoned-Incomplete carrying the
/// `Effect::ControlFlow` reason (or the term catch-all on a non-`ControlFlow` verdict).
/// Byte-identical to the `Expr::TryBlock | Expr::Async | Expr::Try` TERM arm of the old
/// fat factory. DISTINCT from the COMPOSITE recognizer, which boxes the node directly.
pub(crate) fn recognize_term(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => {
            Some(match decompose_control_flow_term(expr) {
                Some(node) => match node.desugar_ctx_free() {
                    Outcome::Incomplete(effect @ Effect::ControlFlow { .. }) => {
                        reasoned_incomplete(effect.reason())
                    }
                    _ => reasoned_incomplete(format!("unsupported term `{}`", token_key(expr))),
                },
                None => reasoned_incomplete(format!("unsupported term `{}`", token_key(expr))),
            })
        }
        _ => None,
    }
}

/// COMPOSITE recognizer for effectful control-flow (`Expr::TryBlock`/`Async`/`Try`):
/// boxes the `ControlFlowTermSugar` refuse-shape directly (the collector's `.complete()`
/// site reads its `Effect::ControlFlow` Incomplete). Byte-identical to the
/// `Expr::TryBlock | Expr::Async | Expr::Try => boxed(decompose_control_flow_term(expr))`
/// COMPOSITE arm of the old fat factory.
pub(crate) fn recognize_composite(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => {
            Some(boxed(decompose_control_flow_term(expr)))
        }
        _ => None,
    }
}

/// The effectful control-flow construct in term position (`try`/`async`/`?`), composed as a
/// node whose `desugar` makes the control-flow verdict at its single LEAF. See the module header.
pub(crate) struct ControlFlowTermSugar {
    /// The full term expr's token-key -- the `boundary` is `token_key(&expr)` (byte-identical
    /// to the old inline `token_key(expr)`), the leaf whose construct is the deferred/early-
    /// returning control flow.
    boundary: String,
}

impl ControlFlowTermSugar {
    /// CONTROL-FLOW leaf: a recognized try/async/`?` construct is deferred or early-returning
    /// control flow -- not a single timeless point-wise value, no construction-from-literals to
    /// walk -> `ControlFlow`. Recognition (the construct shape) is this leaf's precondition, so
    /// it always fires for a built node; it never completes.
    fn control_flow_effect(&self) -> Option<Effect> {
        Some(Effect::ControlFlow {
            boundary: self.boundary.clone(),
        })
    }

    /// The total reduction, made WITHOUT a `SugarCtx` -- the verdict is purely SYNTACTIC (it
    /// reads only the recognized construct shape), so it does not need scope/options. The
    /// `Sugar::desugar(&ctx)` impl delegates here so the node has the canonical trait shape,
    /// while the thin caller-router (the `Expr::TryBlock | Expr::Async | Expr::Try` arm) reads
    /// the SAME verdict here. The composite makes NO verdict of its own: it returns Incomplete its single
    /// CONTROL-FLOW leaf. A built node always names `ControlFlow` (recognition is the verdict's
    /// precondition); the STRUCTURAL backstop is the total-but-unreachable tail.
    pub(crate) fn desugar_ctx_free(&self) -> Outcome {
        if let Some(effect) = self.control_flow_effect() {
            return Outcome::Incomplete(effect);
        }
        Outcome::Incomplete(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}

impl Sugar for ControlFlowTermSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        // The verdict is ctx-independent; delegate to the ctx-free reduction so the trait
        // shape and the thin caller-router agree by construction.
        self.desugar_ctx_free()
    }
}

/// Build (`new` + compose, NO degeneracy opinion) a `ControlFlowTermSugar` from an expr.
/// Recognizes the construct: an `Expr::TryBlock` / `Expr::Async` / `Expr::Try`. Returns `None`
/// (declines to RECOGNIZE) for any other expr -- those are NOT refused here; they stay on the
/// constructive `translate_term_in_scope` paths / the term catch-all (the fake-refuse
/// guardrail). It makes NO verdict -- the control-flow decision is
/// `ControlFlowTermSugar::desugar`'s (and its leaf's) alone.
pub(crate) fn decompose_control_flow_term(expr: &Expr) -> Option<ControlFlowTermSugar> {
    match expr {
        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => Some(ControlFlowTermSugar {
            boundary: token_key(expr),
        }),
        _ => None,
    }
}
