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
// constructive ctor (the const-fold to a Bool literal via `const_eval`) -- that early
// return is owned by `binop::recognize`, which builds this node only for the non-const
// comparison tail. This node composes its two pre-built children and emits the `cmp:*`
// ctor over their terms, propagating a child `Incomplete` verbatim.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{bool_const, const_fold_int_term, Desugared, Outcome, RelationOp, Sugar, SugarCtx};

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
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        let rhs = match self.right.desugar(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => return Outcome::from_opt(None),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        // Collapse-inside-out: once BOTH operands ground to concrete integers
        // (e.g. `a[0] < b[0]` over immutable literal arrays, where `IndexSugar`
        // grounds each read to its element), the comparison is a KNOWN truth --
        // fold to a Bool literal rather than emit an (uninterpreted) `cmp:*` ctor.
        // This mirrors `BinOpSugar`'s desugar-time int fold and the
        // `binop::recognize` preamble's build-time const-fold; it is the
        // soundness completion of literal-index grounding (an uninterpreted
        // `cmp:lt(1,4)` could be mis-satisfied by a bad twin). Symbolic
        // (non-const) operands fall through to the `cmp:*` ctor unchanged.
        if let (Some(a), Some(b)) = (const_fold_int_term(&lhs), const_fold_int_term(&rhs)) {
            let value = match self.rel {
                RelationOp::Eq => a == b,
                RelationOp::Ne => a != b,
                RelationOp::Lt => a < b,
                RelationOp::Le => a <= b,
                RelationOp::Gt => a > b,
                RelationOp::Ge => a >= b,
            };
            return Outcome::Complete(Desugared::Term(bool_const(value)));
        }
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("cmp:{}", self.rel.cmp_ctor_name()),
            args: vec![lhs, rhs],
        })))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Effect;
    use sugar_ir_symbolic::{make_var, ConstValue};

    // ── LOCAL stub children: a `StubTerm` completes to its held term (`Complete(Term)`); a
    // `StubIncomplete` strikes a named effect (`Incomplete`). They IGNORE `ctx`, so the parent's
    // `desugar(ctx)` can run over a minimal real `SugarCtx`. ──
    struct StubTerm(Rc<Term>);
    impl Sugar for StubTerm {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Complete(Desugared::Term(Rc::clone(&self.0)))
        }
    }

    struct StubIncomplete;
    impl Sugar for StubIncomplete {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Incomplete(Effect::Mutation {
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
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete, got Incomplete"),
        };
        let (name, args) = ctor(&term);
        assert_eq!(name, "cmp:lt");
        assert_eq!(args.len(), 2);
        assert_eq!(var_name(&args[0]), "x");
        assert_eq!(var_name(&args[1]), "y");
    }

    #[test]
    fn compare_over_two_int_consts_folds_to_bool_not_cmp_ctor() {
        // Collapse-inside-out: when both operands ground to concrete ints, the
        // comparison folds to its real Bool value (no uninterpreted cmp ctor).
        let true_node = CompareSugar {
            left: Box::new(StubTerm(crate::num(1))),
            right: Box::new(StubTerm(crate::num(4))),
            rel: RelationOp::Lt,
        };
        match run(&true_node) {
            Outcome::Complete(d) => match d.into_term().expect("a Term").as_ref() {
                Term::Const {
                    value: ConstValue::Bool(v),
                    ..
                } => assert!(*v, "1 < 4 is true"),
                other => panic!("expected a Bool const, got {other:?}"),
            },
            Outcome::Incomplete(_) => panic!("expected Complete"),
        }
        // Discrimination: the SAME shape with the relation actually false folds to
        // Bool(false) -- the fold carries the real value, it is not a fake-true.
        let false_node = CompareSugar {
            left: Box::new(StubTerm(crate::num(4))),
            right: Box::new(StubTerm(crate::num(1))),
            rel: RelationOp::Lt,
        };
        match run(&false_node) {
            Outcome::Complete(d) => match d.into_term().expect("a Term").as_ref() {
                Term::Const {
                    value: ConstValue::Bool(v),
                    ..
                } => assert!(!*v, "4 < 1 is false"),
                other => panic!("expected a Bool const, got {other:?}"),
            },
            Outcome::Incomplete(_) => panic!("expected Complete"),
        }
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
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete, got Incomplete"),
        };
        let (name, _) = ctor(&term);
        assert_eq!(name, "cmp:neq");
    }

    #[test]
    fn compare_propagates_left_child_hit_verbatim() {
        let node = CompareSugar {
            left: Box::new(StubIncomplete),
            right: Box::new(StubTerm(make_var("y"))),
            rel: RelationOp::Lt,
        };
        match run(&node) {
            Outcome::Incomplete(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            Outcome::Incomplete(_) => {
                panic!("expected the left child's Mutation Incomplete, got a different Effect")
            }
            Outcome::Complete(_) => panic!("expected the left child's Incomplete, got Complete"),
        }
    }

    #[test]
    fn compare_propagates_right_child_hit_verbatim() {
        let node = CompareSugar {
            left: Box::new(StubTerm(make_var("x"))),
            right: Box::new(StubIncomplete),
            rel: RelationOp::Lt,
        };
        match run(&node) {
            Outcome::Incomplete(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            Outcome::Incomplete(_) => {
                panic!("expected the right child's Mutation Incomplete, got a different Effect")
            }
            Outcome::Complete(_) => panic!("expected the right child's Incomplete, got Complete"),
        }
    }
}
