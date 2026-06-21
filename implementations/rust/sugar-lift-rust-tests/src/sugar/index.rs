// SPDX-License-Identifier: Apache-2.0
//
// `IndexSugar`: the CONSTRUCTIVE term node for a general index read `a[i]` -- the
// constructive tail of the `Expr::Index` arm of `translate_term_in_scope`. It is the
// term-floor sibling of `CallSugar`: a composite term `Sugar` that builds the
// container and the index as child `Sugar`s, reads each child's `Term` back out
// through `Desugared::into_term`, and emits the EXACT `Term::Ctor` the arm's
// constructive tail produces:
//
//   Term::Ctor { name: "index".to_string(), args: vec![container, idx] }
//
// THE CHILDREN ARE PRE-BUILT CHILD SUGAR. The container `a` and the index `i` are each
// held as a `Box<dyn Sugar>` (built by the factory from `index.expr` / `index.index`).
// `desugar` digs the container FIRST, then the index, mirroring the arm's
// `let container = translate_term_in_scope(&index.expr, scope)?;` /
// `let idx = translate_term_in_scope(&index.index, scope)?;` order, and emits
// `index(container, idx)` -- the args in that exact order. A child that does not reduce
// to a term (`into_term` -> `None`) bails the whole node (the byte-identical structural
// backstop, the old `?`-propagated `Err`); a child that `Hit`s a named order-loss
// boundary propagates that `Hit` VERBATIM (the old named inner `Err`).
//
// THE RECOGNIZER PREAMBLE. The `Expr::Index` shape has TWO
// EARLY-RETURN recognizers BEFORE the constructive tail:
//
//   if let Some(term) = const_index_term_in_scope(index, scope)? {
//       return Ok(term);
//   }
//   ...
//   if let Some(node) = sugar::temporal_read::decompose_temporal_read(expr, scope) {
//       if let Outcome::Hit(effect @ Effect::TemporalRead { .. }) = node.desugar_ctx_free()
//       {
//           return Err(effect.reason());
//       }
//   }
//
// The const-index fold (`const_index_term_in_scope`, with its own `?`-propagated `Err`)
// and the mutable-container TEMPORAL-READ refusal (`decompose_temporal_read` ->
// `Effect::TemporalRead`, owned by `TemporalReadSugar`) are owned by this Sugar's
// `recognize`: they decide whether the constructive `index` ctor is reached at all.
// `IndexSugar` is the CONSTRUCTIVE COMPOSER ONLY -- it is built only after those
// preambles decline, then emits the `index` ctor.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::temporal_read::decompose_temporal_read;
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::{
    const_fold_int_term, const_index_term_in_scope, num, ConstVal, Desugared, Effect, Outcome,
    Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("index", recognize);

/// TERM recognizer for `Expr::Index`. Mirrors the source-of-truth arm in order: the
/// const-index preamble FIRST (a digit-index resolved term, or a reasoned-Hit on
/// `Err`), then the `TemporalRead` refuse-shape, then the general constructive `index`
/// ctor over `[container, idx]` ([`IndexSugar`]).
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Index(index) = expr else {
        return None;
    };
    let scope = fcx.scope();
    match const_index_term_in_scope(index, scope) {
        Ok(Some(term)) => return Some(resolved_term(term)),
        Ok(None) => {}
        Err(reason) => return Some(reasoned_hit(reason)),
    }
    if let Some(node) = decompose_temporal_read(expr, scope) {
        if let Outcome::Hit(effect @ Effect::TemporalRead { .. }) = node.desugar_ctx_free() {
            return Some(reasoned_hit(effect.reason()));
        }
    }
    Some(Box::new(IndexSugar::new(
        build_term(&index.expr, fcx),
        build_term(&index.index, fcx),
        method_family::build_literal_sequence_composite(&index.expr, fcx),
    )))
}

/// A general index read `a[i]` in term position, composed as a node whose `desugar`
/// emits the `index` ctor over its container and index child terms (the constructive
/// tail of the `Expr::Index` arm). See the module header.
pub(crate) struct IndexSugar {
    /// The container `a` child `Sugar` (`index.expr`). `desugar` digs it FIRST -- its
    /// `Term` is the first ctor arg.
    container: Box<dyn Sugar>,
    /// The index `i` child `Sugar` (`index.index`). `desugar` digs it SECOND -- its
    /// `Term` is the second ctor arg.
    idx: Box<dyn Sugar>,
    /// The container ALSO built as a literal-sequence composite, when it resolves to one
    /// (`build_literal_sequence_composite`: peels `.iter()`, strips `&`, resolves let-bound
    /// names). Lets `desugar` GROUND `literal[const]` to the element instead of an
    /// uninterpreted `index(..)` ctor a solver can satisfy with anything. `None` for a
    /// non-literal container -> the symbolic ctor is kept.
    container_seq: Option<Box<dyn Sugar>>,
}

impl IndexSugar {
    /// Build an `IndexSugar` from the pre-built container and index children. The
    /// decomposer hands the factory-built `Sugar` for `index.expr` and `index.index`,
    /// plus the optional literal-sequence form of the container for const-index grounding.
    pub(crate) fn new(
        container: Box<dyn Sugar>,
        idx: Box<dyn Sugar>,
        container_seq: Option<Box<dyn Sugar>>,
    ) -> Self {
        IndexSugar {
            container,
            idx,
            container_seq,
        }
    }

    /// Ground `literal_array[const_k]` to the element TERM, or `None` if it does not
    /// cleanly ground (non-literal container, non-const / out-of-bounds index, non-int
    /// element). The caller then emits the symbolic `index` ctor. SOUND: only an
    /// in-bounds const index into a literal int Seq grounds; a non-literal read is never
    /// given a guessed value, and an out-of-bounds index (a rust panic) stays symbolic.
    fn ground_literal_index(&self, ctx: &SugarCtx) -> Option<Rc<Term>> {
        let seq = self.container_seq.as_ref()?.desugar(ctx).dug()?.into_seq()?;
        let idx = self.idx.desugar(ctx).dug()?.into_term()?;
        let k = const_fold_int_term(&idx).and_then(|k| usize::try_from(k).ok())?;
        let elem = seq.get(k)?;
        let n = elem.value.as_ref().and_then(ConstVal::as_int)?;
        Some(num(n))
    }
}

impl Sugar for IndexSugar {
    /// Dig the container child to its `Term`, then the index child, then emit the
    /// `index` ctor over `[container, idx]` -- the constructive tail of the
    /// `Expr::Index` arm, byte-identical (ctor name `"index"`, args in container-then-
    /// index order). A child that `Hit`s a named order-loss boundary propagates that
    /// `Hit` verbatim (the old named inner `Err`); a child that digs to a non-term
    /// `Desugared` (`into_term` -> `None`) bails the node via the structural backstop
    /// (`Outcome::from_opt(None)`, the old `?`-propagated generic refusal).
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // c2: ground `literal_array[const_k]` to the element (`[10,20,99][2]` -> `99`) so
        // the index reaches the floor, instead of an uninterpreted `index(..)` ctor a
        // solver can satisfy with anything (which would over-discharge `a[k] == wrong`).
        // Falls through to the symbolic ctor for a non-literal container.
        if let Some(term) = self.ground_literal_index(ctx) {
            return Outcome::Dug(Desugared::Term(term));
        }
        let container = match self.container.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let idx = match self.idx.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
            name: "index".to_string(),
            args: vec![container, idx],
        })))
    }
}

#[cfg(test)]
mod tests {
    // `IndexSugar` is the CONSTRUCTIVE composer: given a pre-built container child and
    // index child, it emits the `index` ctor over `[container, idx]`. The tests
    // exercise that constructive tail directly with LOCAL stub children (`StubTerm`
    // digs to a fixed leaf term; `StubHit` Hits a named boundary), asserting the EXACT
    // emitted ctor (name + args order) and verbatim `Hit` propagation. A real
    // `SugarCtx` is built from the crate's own constructors (see `CallSugar`'s tests);
    // the stubs ignore `ctx`, so any well-formed ctx exercises the dig/collect/emit
    // path.
    use super::*;
    use crate::{
        sugar_ctx, Desugared, Effect, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar,
        SugarCtx, TemporalPlan, TemporalScope,
    };
    use sugar_ir_symbolic::{make_var, Term};
    use syn::Item;

    /// A test-double leaf `Sugar` that digs to a fixed `Var` term named `tag`.
    struct StubTerm {
        tag: &'static str,
    }
    impl Sugar for StubTerm {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Dug(Desugared::Term(make_var(self.tag)))
        }
    }

    /// A test-double leaf `Sugar` that Hits a named order-loss boundary.
    struct StubHit {
        boundary: &'static str,
    }
    impl Sugar for StubHit {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Hit(Effect::TemporalRead {
                boundary: self.boundary.to_string(),
            })
        }
    }

    /// Run `node.desugar` against a freshly-built, minimal-but-real `SugarCtx`.
    fn run(node: &IndexSugar) -> Outcome {
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        node.desugar(&ctx)
    }

    #[test]
    fn emits_index_ctor_container_then_idx() {
        // `a[i]` -> `Ctor { name: "index", args: [Var(a), Var(i)] }` -- the exact ctor
        // the `Expr::Index` constructive tail emits, container FIRST then index.
        let node = IndexSugar::new(
            Box::new(StubTerm { tag: "a" }),
            Box::new(StubTerm { tag: "i" }),
            None,
        );
        let Outcome::Dug(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Dug term");
        };
        match &*term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "index");
                assert_eq!(args.len(), 2);
                let vars: Vec<String> = args
                    .iter()
                    .map(|a| match &**a {
                        Term::Var { name } => name.clone(),
                        other => panic!("expected a Var arg, got {other:?}"),
                    })
                    .collect();
                // Container is the FIRST arg, index the SECOND (order is significant).
                assert_eq!(vars, vec!["a".to_string(), "i".to_string()]);
            }
            other => panic!("expected a Ctor, got {other:?}"),
        }
    }

    #[test]
    fn propagates_container_hit_verbatim() {
        // A container child that Hits aborts the node with that SAME `Hit`, BEFORE the
        // index child is even dug (the container is dug first).
        let node = IndexSugar::new(
            Box::new(StubHit {
                boundary: "mut-container",
            }),
            Box::new(StubTerm { tag: "i" }),
            None,
        );
        match run(&node) {
            Outcome::Hit(Effect::TemporalRead { boundary }) => {
                assert_eq!(boundary, "mut-container");
            }
            Outcome::Hit(_) => {
                panic!("expected the container's TemporalRead Hit, got a different Hit")
            }
            Outcome::Dug(_) => panic!("expected the container's Hit to propagate, got a Dug"),
        }
    }

    #[test]
    fn propagates_index_hit_verbatim() {
        // An index child that Hits aborts the node with that SAME `Hit` (the container
        // dug cleanly first).
        let node = IndexSugar::new(
            Box::new(StubTerm { tag: "a" }),
            Box::new(StubHit {
                boundary: "mut-index",
            }),
            None,
        );
        match run(&node) {
            Outcome::Hit(Effect::TemporalRead { boundary }) => {
                assert_eq!(boundary, "mut-index");
            }
            Outcome::Hit(_) => panic!("expected the index's TemporalRead Hit, got a different Hit"),
            Outcome::Dug(_) => panic!("expected the index's Hit to propagate, got a Dug"),
        }
    }
}
