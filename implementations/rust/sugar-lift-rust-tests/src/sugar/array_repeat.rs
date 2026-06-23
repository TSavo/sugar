// SPDX-License-Identifier: Apache-2.0
//
// `ArrayRepeatSugar`: the REFUSE-side node for an `[elem; N]` array-repeat whose length `N`
// is NOT a literal. It OWNS, in its own `desugar`, the single non-literal-length verdict the
// old inline `Expr::Repeat` `let-else` else-branch made -- a repeat with a symbolic count
// (`[0u8; SIZE]`, `[(); SIZE - 1]`: a const-generic / const expr) is NOT a finite construction
// from the written literal, so the universe size cannot be pinned and no aggregate term can be
// built. A SOURCE property, not a missing lifter. Typed as `Effect::ArrayRepeat`.
//
// THE TARGET SHAPE (`walk -> new -> compose -> desugar() collapses to one Outcome`):
// `decompose_array_repeat` (the `build` arm) recognizes the construct (an `Expr::Repeat` whose
// `len` does NOT reduce to a literal `usize` -- reusing the shared `repeat_count_literal`
// scanner imported from `crate::`) and `new`s the node, composing the repeat expr's token-key
// as the single CHILD LEAF -- with NO degeneracy opinion and no early exit (its only `None` is
// non-recognition: a non-`Repeat` expr, OR a repeat with a LITERAL count, is not an
// array-repeat-refuse bucket -- nothing to classify here; the LITERAL-count repeat stays on
// the constructive `translate_term_in_scope` path that expands it into the N-fold aggregate
// term). `desugar` is where the verdict is made, and the single LEAF owns it:
//   * the LENGTH leaf: a recognized non-literal length is a symbolic universe size -- no
//     finite construction from the written literal -> `ArrayRepeat`.
// The composite makes NO check of its own: a recognized node always Hits its length leaf
// (recognition -- a non-literal length -- IS the verdict's precondition). The verdict is purely
// SYNTACTIC, so it is delegated by `desugar` to `desugar_ctx_free`. The STRUCTURAL backstop
// (`Effect::Unsupported` with `STRUCTURAL_BACKSTOP_REASON`) is the total-but-unreachable tail
// kept to mirror the node shape -- never reached for a built node, never a fake-refuse.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::backstop::boxed;
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    const_eval, repeat_count_in_scope, repeat_count_literal, token_key, Desugared, DesugaredElem,
    Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON, SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("array_repeat", recognize_composite);

/// COMPOSITE recognizer for `Expr::Repeat`: the `ArrayRepeatSugar` refuse-shape (via
/// [`decompose_array_repeat`]). Byte-identical to the
/// `Expr::Repeat(_) => boxed(decompose_array_repeat(expr))` arm of the old fat
/// `build_composite`. DISTINCT from the TERM-position `Expr::Repeat` (which expands a
/// literal-count aggregate); the two roles genuinely differ.
pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Repeat(repeat) = expr else {
        return None;
    };
    // CONSTRUCTIVE side: a finite, TEXT-DETERMINED count `[elem; N]` is a finite construction
    // from the written literal -- expand it to a Seq of N copies of `elem` (bounded by the seq
    // cap; the element must itself const-eval to a literal value). `N` is finite-by-text when
    // it is a literal (`[7; 3]`) OR a const-bound length resolvable through scope
    // (`const SIZE: usize = 3; [7; SIZE]`) -- `repeat_count_in_scope` unifies both, so a
    // const-length repeat reaches the SAME constructive floor (and element-wise teeth) a
    // literal-length one does. This is the Composite-role analogue of the TERM-role N-fold
    // aggregate expansion. The REFUSE side (a NON-const count: `[x; runtime_len]`, or an
    // opaque element `[MaybeUninit::uninit(); 64]`) stays the `Effect::ArrayRepeat` refuse,
    // below -- finite-or-refuse, never a fabricated universe size.
    if let Some(count) = repeat_count_in_scope(&repeat.len, fcx.scope()) {
        return Some(Box::new(LiteralRepeatSugar {
            elem: (*repeat.expr).clone(),
            count,
            boundary: token_key(expr),
        }));
    }
    Some(boxed(decompose_array_repeat(expr)))
}

/// CONSTRUCTIVE `[elem; N]` with a LITERAL count: desugars to a Seq of `N` copies of the
/// element. `elem` must const-eval to a literal value (a `[0; 64]` grounds; a
/// `[MaybeUninit::uninit(); 64]` does NOT -- its element is opaque, so it falls through to
/// the array-repeat refuse, finite-or-refuse). `N` must fit the sequence cap.
pub(crate) struct LiteralRepeatSugar {
    elem: Expr,
    count: usize,
    boundary: String,
}

impl Sugar for LiteralRepeatSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        // An enormous repeat is not a usefully-finite construction -> refuse (finite-or-refuse).
        if self.count > SUGAR_SEQ_CAP as usize {
            return Outcome::Hit(Effect::ArrayRepeat {
                boundary: self.boundary.clone(),
            });
        }
        // The element must be a literal VALUE; an opaque/effectful element
        // (`MaybeUninit::uninit()`, a runtime call) is not a finite literal -> refuse.
        let Some(value) = const_eval(&self.elem, &BTreeMap::new()) else {
            return Outcome::Hit(Effect::ArrayRepeat {
                boundary: self.boundary.clone(),
            });
        };
        let seq: Vec<DesugaredElem> = (0..self.count)
            .map(|_| DesugaredElem {
                expr: self.elem.clone(),
                value: Some(value.clone()),
            })
            .collect();
        Outcome::Dug(Desugared::Seq(seq))
    }
}

/// The non-literal-length `[elem; N]` array-repeat, composed as a node whose `desugar` makes
/// the array-repeat verdict at its single LEAF (the length). See the module header.
pub(crate) struct ArrayRepeatSugar {
    /// The full `[elem; N]` repeat expr's token-key -- the `boundary` is `token_key(&repeat)`
    /// (byte-identical to the old inline `token_key(expr)`), the leaf whose length is the
    /// non-literal symbolic count.
    boundary: String,
}

impl ArrayRepeatSugar {
    /// LENGTH leaf: a recognized non-literal length is a symbolic universe size -- the repeat
    /// is not a finite construction from the written literal, so no aggregate term can be
    /// pinned -> `ArrayRepeat`. Recognition (a non-literal length) is this leaf's precondition,
    /// so it always fires for a built node; it never Digs.
    fn array_repeat_effect(&self) -> Option<Effect> {
        Some(Effect::ArrayRepeat {
            boundary: self.boundary.clone(),
        })
    }

    /// The total reduction, made WITHOUT a `SugarCtx` -- the verdict is purely SYNTACTIC (it
    /// reads only the recognized non-literal-length shape), so it does not need scope/options.
    /// The `Sugar::desugar(&ctx)` impl delegates here so the node has the canonical trait shape,
    /// while the ctx-less thin caller-router (the `Expr::Repeat` else-branch) reads the SAME
    /// verdict here. The composite makes NO verdict of its own: it Hits its single LENGTH leaf.
    /// A built node always names `ArrayRepeat` (recognition is the verdict's precondition); the
    /// STRUCTURAL backstop is the total-but-unreachable tail.
    pub(crate) fn desugar_ctx_free(&self) -> Outcome {
        if let Some(effect) = self.array_repeat_effect() {
            return Outcome::Hit(effect);
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}

impl Sugar for ArrayRepeatSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        // The verdict is ctx-independent; delegate to the ctx-free reduction so the trait
        // shape and the thin caller-router agree by construction.
        self.desugar_ctx_free()
    }
}

/// Build (`new` + compose, NO degeneracy opinion) an `ArrayRepeatSugar` from an expr.
/// Recognizes the construct: an `Expr::Repeat` whose `len` does NOT reduce to a literal `usize`
/// (reusing the shared `repeat_count_literal` scanner imported from `crate::`). Returns `None`
/// (declines to RECOGNIZE) for a non-`Repeat` expr OR a repeat with a LITERAL count -- the
/// literal-count repeat is NOT refused; it stays on the constructive `translate_term_in_scope`
/// path that expands it into the N-fold aggregate term (the fake-refuse guardrail). It makes NO
/// verdict -- the array-repeat decision is `ArrayRepeatSugar::desugar`'s (and its leaf's) alone.
pub(crate) fn decompose_array_repeat(expr: &Expr) -> Option<ArrayRepeatSugar> {
    let Expr::Repeat(repeat) = expr else {
        return None;
    };
    if repeat_count_literal(&repeat.len).is_some() {
        return None;
    }
    Some(ArrayRepeatSugar {
        boundary: token_key(expr),
    })
}
