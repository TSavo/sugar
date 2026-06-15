// SPDX-License-Identifier: Apache-2.0
//
// `BinOpSugar`: the CONSTRUCTIVE term node for an ARITHMETIC binary operator in TERM
// position (`a + b`, `x * y`, `n << 2`, ...). It mirrors EXACTLY the arithmetic
// constructor the `translate_term_in_scope` `Expr::Binary` arm emits when
// `term_binop_name(&op).is_some()`:
//
//     Term::Ctor { name: op_name.to_string(), args: vec![l, r] }
//
// where `op_name` is the `&'static str` `term_binop_name` returns for the operator
// (`"+"`/`"-"`/`"*"`/`"int-div"`/`"int-rem"`/`"bit-and"`/.../`"shift-right"`).
//
// THIS NODE IS THE COMPOSER ONLY. The `Expr::Binary` arm has a PREAMBLE before the
// arithmetic ctor (the `FormatSugar` string-`+` hook, then the comparison branch that
// fires when `relation_from_binop(&op).is_some()`, then the `term_binop_name` lookup
// itself -- a `None` there is the "unsupported term operator" refusal). Those early
// returns / the op-name resolution are NOT in this node; the factory arm the
// coordinator wires resolves `op_name` and hands it to the constructor (see the
// report's preamble note). This node composes its two pre-built children and emits the
// arithmetic ctor over their terms, propagating a child `Hit` verbatim.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{Desugared, Outcome, Sugar, SugarCtx};

/// The constructive arithmetic-term node. `left`/`right` are the pre-built operand
/// children (the factory desugars each operand expr into a `Sugar`); `op_name` is the
/// captured `term_binop_name(&binary.op)` string at construction. `desugar` composes
/// the children's terms and emits `Term::Ctor { name: op_name, args: vec![l, r] }` --
/// byte-identical to the `translate_term_in_scope` arm.
pub(crate) struct BinOpSugar {
    pub(crate) left: Box<dyn Sugar>,
    pub(crate) right: Box<dyn Sugar>,
    pub(crate) op_name: &'static str,
}

impl Sugar for BinOpSugar {
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
            name: self.op_name.to_string(),
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
    fn binop_add_emits_plus_ctor_over_both_operand_terms() {
        let node = BinOpSugar {
            left: Box::new(StubTerm(make_var("x"))),
            right: Box::new(StubTerm(make_var("y"))),
            op_name: "+",
        };
        let term = match run(&node) {
            Outcome::Dug(d) => d.into_term().expect("a Term"),
            Outcome::Hit(_) => panic!("expected Dug, got Hit"),
        };
        let (name, args) = ctor(&term);
        assert_eq!(name, "+");
        assert_eq!(args.len(), 2);
        assert_eq!(var_name(&args[0]), "x");
        assert_eq!(var_name(&args[1]), "y");
    }

    #[test]
    fn binop_carries_the_captured_op_name_verbatim() {
        // The node emits the op-name string it was handed unchanged (e.g. `int-div`
        // for `/`, `shift-right` for `>>`) -- it does NOT re-derive it.
        let node = BinOpSugar {
            left: Box::new(StubTerm(make_var("a"))),
            right: Box::new(StubTerm(make_var("b"))),
            op_name: "int-div",
        };
        let term = match run(&node) {
            Outcome::Dug(d) => d.into_term().expect("a Term"),
            Outcome::Hit(_) => panic!("expected Dug, got Hit"),
        };
        let (name, _) = ctor(&term);
        assert_eq!(name, "int-div");
    }

    #[test]
    fn binop_propagates_left_child_hit_verbatim() {
        let node = BinOpSugar {
            left: Box::new(StubHit),
            right: Box::new(StubTerm(make_var("y"))),
            op_name: "+",
        };
        match run(&node) {
            Outcome::Hit(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            Outcome::Hit(_) => panic!("expected the left child's Mutation Hit, got a different Effect"),
            Outcome::Dug(_) => panic!("expected the left child's Hit, got Dug"),
        }
    }

    #[test]
    fn binop_propagates_right_child_hit_verbatim() {
        let node = BinOpSugar {
            left: Box::new(StubTerm(make_var("x"))),
            right: Box::new(StubHit),
            op_name: "+",
        };
        match run(&node) {
            Outcome::Hit(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            Outcome::Hit(_) => panic!("expected the right child's Mutation Hit, got a different Effect"),
            Outcome::Dug(_) => panic!("expected the right child's Hit, got Dug"),
        }
    }
}
