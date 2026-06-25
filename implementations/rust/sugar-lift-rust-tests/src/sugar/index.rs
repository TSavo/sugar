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

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
use crate::sugar::temporal_read::decompose_temporal_read;
use crate::{
    const_eval, const_fold_int_term, const_index_term_in_scope, const_val_term, num,
    simple_path_name, token_key, ConstVal, Desugared, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("index", recognize);

/// TERM recognizer for `Expr::Index`. Captures the raw source site; `IndexSugar::desugar`
/// replays the source-of-truth arm order lazily.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Index(index) = expr else {
        return None;
    };
    Some(Box::new(IndexSugar::new(index.clone(), fcx)))
}

/// A general index read `a[i]` in term position, composed as a node whose `desugar`
/// emits the `index` ctor over its container and index child terms (the constructive
/// tail of the `Expr::Index` arm). See the module header.
pub(crate) struct IndexSugar {
    /// The raw `a[i]` source site. `desugar` replays the old preambles first, then
    /// builds the container and index child terms lazily if the constructive tail is
    /// reached.
    index: ExprIndex,
    container: SugarBody<TermFloor>,
    idx: SugarBody<TermFloor>,
    literal_container: Option<SugarBody<CompositeFloor>>,
}

impl IndexSugar {
    /// Build an `IndexSugar` from the raw source index expression and its already-built
    /// container/index child bodies.
    pub(crate) fn new(index: ExprIndex, fcx: &SugarBuildCtx) -> Self {
        let literal_container = method_family::build_literal_sequence_composite(&index.expr, fcx)
            .map(SugarBody::from_node);
        let container = SugarBody::term(&index.expr, fcx);
        let idx = SugarBody::term(&index.index, fcx);
        IndexSugar {
            index,
            container,
            idx,
            literal_container,
        }
    }

    /// Ground `literal_array[const_k]` to the element TERM, or `None` if it does not
    /// cleanly ground (non-literal container, non-const / out-of-bounds index, non-int
    /// element). The caller then emits the symbolic `index` ctor. SOUND: only an
    /// in-bounds const index into a literal int Seq grounds; a non-literal read is never
    /// given a guessed value, and an out-of-bounds index (a rust panic) stays symbolic.
    fn ground_literal_index(&self, ctx: &SugarCtx) -> Result<Option<Rc<Term>>, Outcome> {
        let Some(container) = &self.literal_container else {
            return Ok(None);
        };
        let seq = match container.reduce(ctx) {
            Outcome::Complete(d) => match d.into_seq() {
                Some(seq) => seq,
                None => return Ok(None),
            },
            Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
        };
        let idx = match term_from_body(&self.idx, ctx, "index position") {
            Ok(term) => term,
            Err(outcome) => return Err(outcome),
        };
        let Some(k) = const_fold_int_term(&idx).and_then(|k| usize::try_from(k).ok()) else {
            return Ok(None);
        };
        let Some(elem) = seq.get(k) else {
            return Ok(None);
        };
        let Some(n) = elem.value.as_ref().and_then(ConstVal::as_int) else {
            return Ok(None);
        };
        Ok(Some(num(n)))
    }

    fn ground_temporal_rewrite_index(&self, ctx: &SugarCtx) -> Result<Option<Outcome>, Outcome> {
        let Some(base) = simple_path_name(&self.index.expr) else {
            return Ok(None);
        };
        let idx = match term_from_body(&self.idx, ctx, "index temporal position") {
            Ok(term) => term,
            Err(outcome) => return Err(outcome),
        };
        let Some(k) = const_fold_int_term(&idx).and_then(|k| usize::try_from(k).ok()) else {
            return Ok(None);
        };
        let Some(elem) = ctx.scope.temporal_rewrite_index_expr_for(&base, k) else {
            return Ok(None);
        };
        let value = const_eval(&elem, &BTreeMap::new())
            .and_then(|value| const_val_term(&value))
            .map(Desugared::Term)
            .map(Outcome::Complete)
            .unwrap_or_else(|| {
                index_gap("temporal index rewrite element is not literal-determined")
            });
        Ok(Some(value))
    }
}

impl Sugar for IndexSugar {
    /// Dig the container child to its `Term`, then the index child, then emit the
    /// `index` ctor over `[container, idx]` -- the constructive tail of the
    /// `Expr::Index` arm, byte-identical (ctor name `"index"`, args in container-then-
    /// index order). A child that `Incomplete`s a named order-loss boundary propagates that
    /// `Incomplete` verbatim (the old named inner `Err`); a child that completes to a non-term
    /// `Desugared` (`into_term` -> `None`) is an impossible floor mismatch and panics
    /// loudly instead of manufacturing a terminal verdict.
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match const_index_term_in_scope(&self.index, ctx.scope) {
            Ok(Some(term)) => return Outcome::Complete(Desugared::Term(term)),
            Ok(None) => {}
            Err(reason) => {
                return Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
                    boundary: token_key(&Expr::Index(self.index.clone())),
                    reason,
                })
            }
        }
        if let Some(outcome) = match self.ground_temporal_rewrite_index(ctx) {
            Ok(outcome) => outcome,
            Err(outcome) => return outcome,
        } {
            return outcome;
        }
        let source = Expr::Index(self.index.clone());
        if let Some(node) = decompose_temporal_read(&source, ctx.scope) {
            if let Outcome::Incomplete(effect @ Effect::TemporalRead { .. }) =
                node.desugar_ctx_free()
            {
                return Outcome::Incomplete(effect);
            }
        }
        // c2: ground `literal_array[const_k]` to the element (`[10,20,99][2]` -> `99`) so
        // the index reaches the floor, instead of an uninterpreted `index(..)` ctor a
        // solver can satisfy with anything (which would over-discharge `a[k] == wrong`).
        // Falls through to the symbolic ctor for a non-literal container.
        if let Some(term) = match self.ground_literal_index(ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        } {
            return Outcome::Complete(Desugared::Term(term));
        }
        let container = match term_from_body(&self.container, ctx, "index container") {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let idx = match term_from_body(&self.idx, ctx, "index position") {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "index".to_string(),
            args: vec![container, idx],
        })))
    }
}

fn term_from_body(
    body: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_term()
            .ok_or_else(|| index_gap(&format!("{label} reduced to non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn index_gap(reason: &str) -> ! {
    panic!("index completed without a term/composite floor: {reason}")
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
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        IndexSugar::new(index, &fcx)
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
