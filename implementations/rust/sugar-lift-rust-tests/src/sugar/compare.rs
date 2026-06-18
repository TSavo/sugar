// SPDX-License-Identifier: Apache-2.0
//
// `CompareSugar`: the CONSTRUCTIVE term node for a COMPARISON in genuine TERM
// position (`a[0] < b[0]` as the operand of an outer `==`, or the LHS of
// `assert_eq!(false == false, true)`). It mirrors EXACTLY the bool-valued `cmp:*`
// constructor the `translate_term_in_scope` `Expr::Binary` arm emits when
// `relation_from_binop(&op).is_some()` and the operands are non-const-but-stable:
//
//     Term::Ctor { name: format!("cmp:{}", rel.cmp_ctor_name()), args: vec![l, r] }
//
// keyed per relation (`cmp:lt`/`cmp:le`/.../`cmp:eq`/`cmp:neq`/`cmp:ge`) so two
// contradictory comparisons over the same operands are DISTINCT terms (the teeth).
//
// THIS NODE IS THE COMPOSER ONLY. The `Expr::Binary` shape has a PREAMBLE before the
// constructive ctor (the `FormatSugar` string-`+` hook, and the const-fold to a Bool
// literal via `const_eval`) -- those early returns are owned by `binop::recognize`,
// which builds this node only for the non-const comparison tail. This node composes
// its two pre-built children and emits the `cmp:*` ctor over their terms, propagating
// a child `Hit` verbatim.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{Desugared, Outcome, RelationOp, Sugar, SugarCtx};

/// The constructive comparison-term node. `left`/`right` are the pre-built operand
/// children (the factory desugars each operand expr into a `Sugar`); `rel` is the
/// captured relation (`relation_from_binop(&binary.op)` at construction). `desugar`
/// composes the children's terms and emits `cmp:<rel.cmp_ctor_name()>(l, r)` --
/// byte-identical to the `translate_term_in_scope` arm.
pub(crate) struct CompareSugar {
    pub(crate) left: Box<dyn Sugar>,
    pub(crate) right: Box<dyn Sugar>,
    pub(crate) rel: RelationOp,
}

impl Sugar for CompareSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let lhs = match self.left.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let rhs = match self.right.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("cmp:{}", self.rel.cmp_ctor_name()),
            args: vec![lhs, rhs],
        })))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Effect;
    use sugar_ir_symbolic::make_var;

    // ── LOCAL stub children: a `StubTerm` digs to its held term (`Dug(Term)`); a
    // `StubHit` strikes a named effect (`Hit`). They IGNORE `ctx`, so the parent's
    // `desugar(ctx)` can run over a minimal real `SugarCtx`. ──
    struct StubTerm(Rc<Term>);
    impl Sugar for StubTerm {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Dug(Desugared::Term(Rc::clone(&self.0)))
        }
    }

    struct StubHit;
    impl Sugar for StubHit {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Hit(Effect::Mutation {
                boundary: "stub".to_string(),
            })
        }
    }

    // A minimal real `SugarCtx` over an empty source. The stub children ignore it;
    // it exists only to satisfy the trait signature.
    fn run(node: &dyn Sugar) -> Outcome {
        let scope = crate::TemporalScope::new("test", crate::TemporalPlan::default());
        let options = crate::LiftOptions::default();
        let items: Vec<syn::Item> = Vec::new();
        let reducer = crate::ReductionCtx::from_items(&items);
        let mut float_widths = crate::FloatWidthScope::new();
        let ctx = crate::sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    fn ctor<'a>(t: &'a Term) -> (&'a str, &'a [Rc<Term>]) {
        match t {
            Term::Ctor { name, args } => (name.as_str(), args.as_slice()),
            _ => panic!("expected a Ctor term, got {t:?}"),
        }
    }

    fn var_name(t: &Term) -> &str {
        match t {
            Term::Var { name } => name.as_str(),
            _ => panic!("expected a Var term, got {t:?}"),
        }
    }

    #[test]
    fn compare_lt_emits_cmp_lt_ctor_over_both_operand_terms() {
        let node = CompareSugar {
            left: Box::new(StubTerm(make_var("x"))),
            right: Box::new(StubTerm(make_var("y"))),
            rel: RelationOp::Lt,
        };
        let term = match run(&node) {
            Outcome::Dug(d) => d.into_term().expect("a Term"),
            Outcome::Hit(_) => panic!("expected Dug, got Hit"),
        };
        let (name, args) = ctor(&term);
        assert_eq!(name, "cmp:lt");
        assert_eq!(args.len(), 2);
        assert_eq!(var_name(&args[0]), "x");
        assert_eq!(var_name(&args[1]), "y");
    }

    #[test]
    fn compare_ne_keys_cmp_neq_distinct_from_eq() {
        // The teeth: `!=` keys `cmp:neq`, NOT `cmp:eq` (the cmp_ctor_name split).
        let node = CompareSugar {
            left: Box::new(StubTerm(make_var("a"))),
            right: Box::new(StubTerm(make_var("b"))),
            rel: RelationOp::Ne,
        };
        let term = match run(&node) {
            Outcome::Dug(d) => d.into_term().expect("a Term"),
            Outcome::Hit(_) => panic!("expected Dug, got Hit"),
        };
        let (name, _) = ctor(&term);
        assert_eq!(name, "cmp:neq");
    }

    #[test]
    fn compare_propagates_left_child_hit_verbatim() {
        let node = CompareSugar {
            left: Box::new(StubHit),
            right: Box::new(StubTerm(make_var("y"))),
            rel: RelationOp::Lt,
        };
        match run(&node) {
            Outcome::Hit(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            Outcome::Hit(_) => {
                panic!("expected the left child's Mutation Hit, got a different Effect")
            }
            Outcome::Dug(_) => panic!("expected the left child's Hit, got Dug"),
        }
    }

    #[test]
    fn compare_propagates_right_child_hit_verbatim() {
        let node = CompareSugar {
            left: Box::new(StubTerm(make_var("x"))),
            right: Box::new(StubHit),
            rel: RelationOp::Lt,
        };
        match run(&node) {
            Outcome::Hit(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            Outcome::Hit(_) => {
                panic!("expected the right child's Mutation Hit, got a different Effect")
            }
            Outcome::Dug(_) => panic!("expected the right child's Hit, got Dug"),
        }
    }
}
