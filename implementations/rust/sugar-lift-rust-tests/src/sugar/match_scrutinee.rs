// SPDX-License-Identifier: Apache-2.0
//
// `MatchScrutineeSugar`: the REFUSE-side node for a `match <runtime call> { .. }` whose
// asserted value is the arm taken by a RUNTIME non-scalar result. It OWNS, in its own
// `desugar`, the single runtime-match-scrutinee verdict the old external
// `runtime_match_scrutinee_effect` predicate made -- a `match` whose scrutinee is a method
// call (`b.binary_search(&3)`) or a free-function call produces its value only when run, so
// the arm taken (and thus the asserted value) is not constructible from source literals and
// has no single timeless `t` (kin to `bin-2`). A SOURCE property, not a missing lifter.
// Typed as `RuntimeMatchScrutinee`. This is the SAME terminal cause whether the `match`
// surfaces at STATEMENT position (the `Stmt::Expr(Expr::Match)` residue) or in EXPRESSION
// position (the `translate_bool_assertion` half-refuse) -- so BOTH callsites now route
// through this ONE node, not a scattered predicate sequenced by hand at two call sites.
//
// THE TARGET SHAPE (`walk -> new -> compose -> desugar() collapses to one Outcome`):
// `decompose_match_scrutinee` (the `build` arm) recognizes the construct (an `Expr::Match`
// whose scrutinee resolves -- through parens/groups/references -- to a runtime call result)
// and `new`s the node, composing the match expr as the single CHILD LEAF -- with NO
// degeneracy opinion and no early exit (its only `None` is non-recognition: a non-`match`
// expr, or a `match` over a CONSTRUCTED literal / path / index scrutinee, is not a
// runtime-match-scrutinee bucket -- nothing to classify; it stays on the generic
// unclassified path, the inverse-of-fake-refuse guardrail). `desugar` is where the verdict
// is made, and the single LEAF owns it:
//   * the SCRUTINEE leaf: a recognized runtime-call scrutinee is a non-scalar runtime result
//     -- the arm taken is not constructible from source literals -> `RuntimeMatchScrutinee`.
// The composite makes NO check of its own: a recognized node always Hits its scrutinee leaf
// (recognition -- a runtime-call scrutinee -- IS the verdict's precondition). The STRUCTURAL
// backstop (`Effect::Unsupported` with `STRUCTURAL_BACKSTOP_REASON`) is the total-but-
// unreachable tail kept to mirror the node shape -- a `Hit` the fall-through routers (both
// callsites) discard exactly as the old `None` was, never a fake-refuse.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::{
    expr_is_runtime_call_result, token_key, Effect, Outcome, Sugar, SugarCtx,
    STRUCTURAL_BACKSTOP_REASON,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_composite("match_scrutinee", recognize_composite);

pub(crate) const VERDICT_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::match_scrutinee_verdict(
        "match_scrutinee",
        recognize_verdict,
    );

/// COMPOSITE method-call recognizer for a match-scrutinee method shape
/// ([`MatchScrutineeSugar`] via [`decompose_match_scrutinee`]): `Some` only for a
/// recognized shape, else `None`. Mirrors the LAST arm of the old
/// `build_method_call_composite` chain — AFTER `closure_adaptor`.
pub(crate) fn recognize_composite(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::MethodCall(_) => {
            decompose_match_scrutinee(expr).map(|node| Box::new(node) as Box<dyn Sugar>)
        }
        _ => None,
    }
}

/// MATCH-position recognizer ([`MatchScrutineeSugar`] via [`decompose_match_scrutinee`]):
/// `Some` only for an `Expr::Match` over a RUNTIME call-result scrutinee, else `None`.
/// DISTINCT from `recognize_composite`, which owns the method-call-chain placeholder slot.
pub(crate) fn recognize_verdict(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    decompose_match_scrutinee(expr).map(|node| Box::new(node) as Box<dyn Sugar>)
}

/// The `match <runtime call> { .. }` whose asserted value is the arm taken by a runtime
/// non-scalar result, composed as a node whose `desugar` makes the runtime-match-scrutinee
/// verdict at its single LEAF (the scrutinee). See the module header.
pub(crate) struct MatchScrutineeSugar {
    /// The full `match` expr -- the `boundary` token-key is `token_key(&expr)` (byte-identical
    /// to the old predicate's `token_key(expr)`), and the leaf whose scrutinee is the runtime
    /// call result.
    expr: Expr,
}

impl MatchScrutineeSugar {
    /// SCRUTINEE leaf: a recognized `match` over a RUNTIME call result (a method/free-fn call,
    /// through parens/groups/references) reads its asserted value out of the arm taken by a
    /// value produced only at run time -- not constructible from source literals, no single
    /// timeless `t` -> `RuntimeMatchScrutinee`. Recognition (a runtime-call scrutinee) is this
    /// leaf's precondition, so it always fires for a built node; it never Digs.
    fn runtime_scrutinee_effect(&self) -> Option<Effect> {
        Some(Effect::RuntimeMatchScrutinee {
            boundary: token_key(&self.expr),
        })
    }

    /// The total reduction, made WITHOUT a `SugarCtx` -- the verdict is purely SYNTACTIC (it
    /// reads only the recognized scrutinee shape), so it does not need scope/options. The
    /// `Sugar::desugar(&ctx)` impl delegates here so the node has the canonical trait shape,
    /// while the thin node-router (`runtime_match_scrutinee_effect`) reads the SAME verdict
    /// through the trait.
    /// The composite makes NO verdict of its own: it Hits its single SCRUTINEE leaf. A built
    /// node always names `RuntimeMatchScrutinee` (recognition is the verdict's precondition);
    /// the STRUCTURAL backstop is the total-but-unreachable tail the fall-through routers
    /// discard as the old `None`.
    pub(crate) fn desugar_ctx_free(&self) -> Outcome {
        if let Some(effect) = self.runtime_scrutinee_effect() {
            return Outcome::Hit(effect);
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}

impl Sugar for MatchScrutineeSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        // The verdict is ctx-independent; delegate to the ctx-free reduction so the trait
        // shape and the thin node-router agree by construction.
        self.desugar_ctx_free()
    }
}

/// Build (`new` + compose, NO degeneracy opinion) a `MatchScrutineeSugar` from an expr.
/// Recognizes the construct: an `Expr::Match` whose SCRUTINEE is a RUNTIME call result (a
/// method/free-fn call, looking through parens/groups/references -- reusing the shared
/// `expr_is_runtime_call_result` scanner imported from `crate::`). Returns `None` (declines
/// to RECOGNIZE) for a non-`match` expr OR a `match` over a CONSTRUCTED literal / path / index
/// scrutinee -- it is NOT refused; it stays on the generic unclassified path (the fake-refuse
/// guardrail). It makes NO verdict -- the runtime-match-scrutinee decision is
/// `MatchScrutineeSugar::desugar`'s (and its leaf's) alone.
pub(crate) fn decompose_match_scrutinee(expr: &Expr) -> Option<MatchScrutineeSugar> {
    let Expr::Match(m) = expr else {
        return None;
    };
    if !expr_is_runtime_call_result(&m.expr) {
        return None;
    }
    Some(MatchScrutineeSugar { expr: expr.clone() })
}
