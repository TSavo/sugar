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
// THE CHILDREN ARE LAZY. The container `a` and the index `i` are held as raw source
// expressions. `desugar` builds and completes the container FIRST, then the index, mirroring
// the arm's
// `let container = translate_term_in_scope(&index.expr, scope)?;` /
// `let idx = translate_term_in_scope(&index.index, scope)?;` order, and emits
// `index(container, idx)` -- the args in that exact order. A child that does not reduce
// to a term (`into_term` -> `None`) bails the whole node (the byte-identical structural
// backstop, the old `?`-propagated `Err`); a child that `Incomplete`s a named order-loss
// boundary propagates that `Incomplete` VERBATIM (the old named inner `Err`).
//
// THE RECOGNIZER PREAMBLE. The `Expr::Index` shape has TWO
// EARLY-RETURN recognizers BEFORE the constructive tail:
//
//   if let Some(term) = const_index_term_in_scope(index, scope)? {
//       return Ok(term);
//   }
//   ...
//   if let Some(node) = sugar::temporal_read::decompose_temporal_read(expr, scope) {
//       if let Outcome::Incomplete(effect @ Effect::TemporalRead { .. }) = node.desugar_ctx_free()
//       {
//           return Err(effect.reason());
//       }
//   }
//
// The const-index fold (`const_index_term_in_scope`, with its own `?`-propagated `Err`)
// and the mutable-container TEMPORAL-READ refusal (`decompose_temporal_read` ->
// `Effect::TemporalRead`, owned by `TemporalReadSugar`) run first inside `desugar`:
// they decide whether the constructive `index` ctor is reached at all. `IndexSugar`
// then emits the `index` ctor only after those preambles decline.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, ExprIndex};

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::temporal_read::decompose_temporal_read;
use crate::{
    const_fold_int_term, const_index_term_in_scope, num, simple_path_name, ConstVal, Desugared,
    Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("index", recognize);

/// TERM recognizer for `Expr::Index`. Captures the raw source site; `IndexSugar::desugar`
/// replays the source-of-truth arm order lazily.
pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Index(index) = expr else {
        return None;
    };
    Some(Box::new(IndexSugar::new(index.clone())))
}

/// A general index read `a[i]` in term position, composed as a node whose `desugar`
/// emits the `index` ctor over its container and index child terms (the constructive
/// tail of the `Expr::Index` arm). See the module header.
pub(crate) struct IndexSugar {
    /// The raw `a[i]` source site. `desugar` replays the old preambles first, then
    /// builds the container and index child terms lazily if the constructive tail is
    /// reached.
    index: ExprIndex,
}

impl IndexSugar {
    /// Build an `IndexSugar` from the raw source index expression. Child sugar is
    /// intentionally not constructed until `desugar`.
    pub(crate) fn new(index: ExprIndex) -> Self {
        IndexSugar { index }
    }

    /// Ground `literal_array[const_k]` to the element TERM, or `None` if it does not
    /// cleanly ground (non-literal container, non-const / out-of-bounds index, non-int
    /// element). The caller then emits the symbolic `index` ctor. SOUND: only an
    /// in-bounds const index into a literal int Seq grounds; a non-literal read is never
    /// given a guessed value, and an out-of-bounds index (a rust panic) stays symbolic.
    fn ground_literal_index(&self, ctx: &SugarCtx) -> Option<Rc<Term>> {
        let let_inits = scope_let_inits(ctx);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let seq = method_family::build_literal_sequence_composite(&self.index.expr, &fcx)?
            .desugar(ctx)
            .complete()?
            .into_seq()?;
        let idx = build_term(&self.index.index, &fcx)
            .desugar(ctx)
            .complete()?
            .into_term()?;
        let k = const_fold_int_term(&idx).and_then(|k| usize::try_from(k).ok())?;
        let elem = seq.get(k)?;
        let n = elem.value.as_ref().and_then(ConstVal::as_int)?;
        Some(num(n))
    }

    fn ground_temporal_rewrite_index(&self, ctx: &SugarCtx) -> Option<Outcome> {
        let base = simple_path_name(&self.index.expr)?;
        let let_inits = scope_let_inits(ctx);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let idx = build_term(&self.index.index, &fcx)
            .desugar(ctx)
            .complete()?
            .into_term()?;
        let k = const_fold_int_term(&idx).and_then(|k| usize::try_from(k).ok())?;
        let elem = ctx.scope.temporal_rewrite_index_expr_for(&base, k)?;
        Some(build_term(&elem, &fcx).desugar(ctx))
    }
}

impl Sugar for IndexSugar {
    /// Dig the container child to its `Term`, then the index child, then emit the
    /// `index` ctor over `[container, idx]` -- the constructive tail of the
    /// `Expr::Index` arm, byte-identical (ctor name `"index"`, args in container-then-
    /// index order). A child that `Incomplete`s a named order-loss boundary propagates that
    /// `Incomplete` verbatim (the old named inner `Err`); a child that completes to a non-term
    /// `Desugared` (`into_term` -> `None`) bails the node via the structural backstop
    /// (`Outcome::from_opt(None)`, the old `?`-propagated generic refusal).
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match const_index_term_in_scope(&self.index, ctx.scope) {
            Ok(Some(term)) => return Outcome::Complete(Desugared::Term(term)),
            Ok(None) => {}
            Err(reason) => return Outcome::Incomplete(Effect::Unsupported { reason }),
        }
        if let Some(outcome) = self.ground_temporal_rewrite_index(ctx) {
            return outcome;
        }
        let source = Expr::Index(self.index.clone());
        if let Some(node) = decompose_temporal_read(&source, ctx.scope) {
            if let Outcome::Incomplete(effect @ Effect::TemporalRead { .. }) =
                node.desugar_ctx_free()
            {
                return Outcome::Incomplete(Effect::Unsupported {
                    reason: effect.reason(),
                });
            }
        }
        // c2: ground `literal_array[const_k]` to the element (`[10,20,99][2]` -> `99`) so
        // the index reaches the floor, instead of an uninterpreted `index(..)` ctor a
        // solver can satisfy with anything (which would over-discharge `a[k] == wrong`).
        // Falls through to the symbolic ctor for a non-literal container.
        if let Some(term) = self.ground_literal_index(ctx) {
            return Outcome::Complete(Desugared::Term(term));
        }
        let let_inits = scope_let_inits(ctx);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let container = match build_term(&self.index.expr, &fcx).desugar(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        let idx = match build_term(&self.index.index, &fcx).desugar(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "index".to_string(),
            args: vec![container, idx],
        })))
    }
}

fn scope_let_inits<'a, 'c>(ctx: &SugarCtx<'a, 'c>) -> BTreeMap<String, &'a Expr> {
    ctx.scope
        .let_bindings_iter()
        .map(|(name, init)| (name.clone(), init))
        .collect()
}

#[cfg(test)]
mod tests {
    // `IndexSugar` is the CONSTRUCTIVE composer for a raw `a[i]` site. These tests
    // assert it keeps the source child expressions raw and still emits the exact ctor
    // after child terms are built lazily in `desugar`.
    use super::*;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::{parse_quote, Expr, Item};

    fn node_from(expr: Expr) -> IndexSugar {
        let Expr::Index(index) = expr else {
            panic!("expected an index expression")
        };
        IndexSugar::new(index)
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
    fn holds_raw_container_and_index_exprs() {
        let node = node_from(parse_quote!(values[pos]));
        let Expr::Path(container) = &*node.index.expr else {
            panic!("expected raw container path")
        };
        let Expr::Path(idx) = &*node.index.index else {
            panic!("expected raw index path")
        };
        assert!(container.path.is_ident("values"));
        assert!(idx.path.is_ident("pos"));
    }

    #[test]
    fn emits_index_ctor_container_then_idx() {
        // `a[i]` -> `Ctor { name: "index", args: [Var(a), Var(i)] }` -- the exact ctor
        // the `Expr::Index` constructive tail emits, container FIRST then index.
        let node = node_from(parse_quote!(a[i]));
        let Outcome::Complete(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Complete term");
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
}
