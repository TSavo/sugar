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
// THE ROUTER PREAMBLE IS NOT THIS NODE'S JOB. The `Expr::Index` arm has TWO
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
// `Effect::TemporalRead`, ALREADY owned by `TemporalReadSugar`) are ROUTER concerns:
// they decide whether the constructive `index` ctor is reached at all. They live in the
// factory arm the coordinator wires (the decomposer / dispatch that builds this node
// ONLY when both preamble recognizers declined). `IndexSugar` is the CONSTRUCTIVE
// COMPOSER ONLY -- it assumes the preamble has been cleared (the container is a stable,
// non-`mut`-local read) and emits the `index` ctor.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{Desugared, Outcome, Sugar, SugarCtx};

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
}

impl IndexSugar {
    /// Build an `IndexSugar` from the pre-built container and index children. The
    /// decomposer hands the factory-built `Sugar` for `index.expr` and `index.index`.
    pub(crate) fn new(container: Box<dyn Sugar>, idx: Box<dyn Sugar>) -> Self {
        IndexSugar { container, idx }
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
        );
        match run(&node) {
            Outcome::Hit(Effect::TemporalRead { boundary }) => {
                assert_eq!(boundary, "mut-container");
            }
            Outcome::Hit(_) => panic!("expected the container's TemporalRead Hit, got a different Hit"),
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
