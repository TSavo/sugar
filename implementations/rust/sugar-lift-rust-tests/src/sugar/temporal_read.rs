// SPDX-License-Identifier: Apache-2.0
//
// `TemporalReadSugar`: the REFUSE-side node for THE DRAIN -- an index read `a[i]` whose
// container `a` is a provably-MUTABLE local (a `let mut` the `mut` oracle flags). It OWNS, in
// its own `desugar`, the single mutable-container-read verdict the old inline `Expr::Index`
// `is_mut_local` branch made -- a `mut` local may be index-assigned or method-mutated in ways
// the tracker cannot follow, so `index(a, i)` is a sequence/position-dependent read with no
// single timeless `t` (the index-read sibling of the whitelisted `temporally unstable`). A
// SOURCE property, not a missing lifter. Typed as `Effect::TemporalRead`.
//
// SOUNDNESS (the discrimination twin): the verdict is minted ONLY under `is_mut_local`. A
// non-`mut` (provably-immutable) container is a stable `index(a, i)` term -- the node declines
// to RECOGNIZE it, so the read stays on the constructive `translate_term_in_scope` path. No
// over-terminalization: the drain refuses ONLY a genuinely-mutable read, never a pure one.
//
// THE TARGET SHAPE (`walk -> new -> compose -> desugar() collapses to one Outcome`):
// `decompose_temporal_read` (the `build` arm) recognizes the construct (an `Expr::Index` whose
// container resolves -- via the shared `simple_path_name` scanner -- to a name the `mut` oracle
// `scope.is_mut_local` flags) and `new`s the node, composing the index expr's token-key as the
// single CHILD LEAF -- with NO degeneracy opinion and no early exit (its only `None` is
// non-recognition: a non-`Index` expr, an index over a non-simple-path container, OR an index
// over a non-`mut` local, is not a temporal-read bucket -- nothing to classify here; it stays
// on the constructive `index(a, i)` path / the const-index path / its own EUF term). `desugar`
// is where the verdict is made, and the single LEAF owns it:
//   * the CONTAINER leaf: a recognized mutable-local container is sequence/position-dependent
//     -- no single timeless `t` -> `TemporalRead`.
// The composite makes NO check of its own: a recognized node always Hits its container leaf
// (recognition -- a `mut`-local container -- IS the verdict's precondition). The verdict, once
// the `mut`-oracle predicate is settled at build time, is purely SYNTACTIC, so it is delegated
// by `desugar` to `desugar_ctx_free`. The STRUCTURAL backstop (`Effect::Unsupported` with
// `STRUCTURAL_BACKSTOP_REASON`) is the total-but-unreachable tail kept to mirror the node shape.

use syn::Expr;

use crate::{
    simple_path_name, token_key, Effect, Outcome, Sugar, SugarCtx, TemporalScope,
    STRUCTURAL_BACKSTOP_REASON,
};

/// The mutable-container index read `a[i]`, composed as a node whose `desugar` makes the
/// temporal-read verdict at its single LEAF (the container). See the module header.
pub(crate) struct TemporalReadSugar {
    /// The full `a[i]` index expr's token-key -- the `boundary` is `token_key(&index)`
    /// (byte-identical to the old inline `token_key(expr)`), the leaf whose container is the
    /// provably-mutable local.
    boundary: String,
}

impl TemporalReadSugar {
    /// CONTAINER leaf: a recognized mutable-local container is a sequence/position-dependent
    /// read -- the `mut` oracle proved it may be index-assigned or method-mutated, so there is
    /// no single timeless `t` -> `TemporalRead`. Recognition (a `mut`-local container) is this
    /// leaf's precondition, so it always fires for a built node; it never Digs.
    fn temporal_read_effect(&self) -> Option<Effect> {
        Some(Effect::TemporalRead {
            boundary: self.boundary.clone(),
        })
    }

    /// The total reduction, made WITHOUT a `SugarCtx` -- the `mut`-oracle predicate is settled
    /// at build time (`decompose` only `new`s the node for a flagged container), so the verdict
    /// reads only the recognized shape and does not need scope/options. The `Sugar::desugar(&ctx)`
    /// impl delegates here so the node has the canonical trait shape, while the thin caller-router
    /// (the `Expr::Index` arm) reads the SAME verdict here. The composite makes NO verdict of its
    /// own: it Hits its single CONTAINER leaf. A built node always names `TemporalRead`
    /// (recognition is the verdict's precondition); the STRUCTURAL backstop is the
    /// total-but-unreachable tail.
    pub(crate) fn desugar_ctx_free(&self) -> Outcome {
        if let Some(effect) = self.temporal_read_effect() {
            return Outcome::Hit(effect);
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}

impl Sugar for TemporalReadSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        // The verdict is settled at build time (the `mut` oracle); delegate to the ctx-free
        // reduction so the trait shape and the thin caller-router agree by construction.
        self.desugar_ctx_free()
    }
}

/// Build (`new` + compose, NO degeneracy opinion) a `TemporalReadSugar` from an expr.
/// Recognizes the construct: an `Expr::Index` whose container resolves (via the shared
/// `simple_path_name` scanner) to a name the `mut` oracle `scope.is_mut_local` flags. Returns
/// `None` (declines to RECOGNIZE) for a non-`Index` expr, an index over a non-simple-path
/// container, OR an index over a non-`mut` (provably-immutable) local -- none of those are
/// refused; they stay on the constructive `index(a, i)` path / EUF term (the fake-refuse
/// guardrail, and the discrimination twin's soundness gate). It makes NO verdict -- the
/// temporal-read decision is `TemporalReadSugar::desugar`'s (and its leaf's) alone.
pub(crate) fn decompose_temporal_read(expr: &Expr, scope: &TemporalScope) -> Option<TemporalReadSugar> {
    let Expr::Index(index) = expr else {
        return None;
    };
    let name = simple_path_name(&index.expr)?;
    if !scope.is_mut_local(&name) {
        return None;
    }
    Some(TemporalReadSugar {
        boundary: token_key(expr),
    })
}
