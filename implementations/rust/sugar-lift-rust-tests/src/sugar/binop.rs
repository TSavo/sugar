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
// THIS NODE IS THE COMPOSER ONLY. The `Expr::Binary` shape has a PREAMBLE before the
// arithmetic ctor (the comparison branch that fires when `relation_from_binop(&op)` is
// `Some`, then the `term_binop_name` lookup itself -- a `None` there is the "unsupported
// term operator" refusal). Those early returns and the op-name resolution are owned by
// `recognize`, which builds this node only for the arithmetic tail. This node composes
// its two pre-built children and emits the arithmetic ctor over their terms, propagating
// a child `Incomplete` verbatim.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Term};
use syn::{BinOp, Expr};

use crate::sugar::compare::CompareSugar;
use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx, TermFloor,
};
use crate::sugar::term_leaf::{reasoned_incomplete, resolved_term};
use crate::{
    const_eval, const_fold_int_term, const_fold_u128_term, const_val_term, num,
    relation_from_binop, term_binop_name, token_key, u128_term, ConstVal, Desugared, Effect,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term("binop", recognize);

/// TERM recognizer for `Expr::Binary`. Mirrors the source-of-truth arm in order: the
/// comparison branch (const-fold to a Bool, else the `cmp:*` [`CompareSugar`]), then
/// the arithmetic-op [`BinOpSugar`] (or the
/// `term_binop_name`-`None` "unsupported term operator" reasoned-Incomplete).
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Binary(binary) = expr else {
        return None;
    };
    if let Some(term) = const_eval(expr, &BTreeMap::new()).and_then(|value| const_val_term(&value))
    {
        return Some(resolved_term(term));
    }
    if matches!(binary.op, BinOp::And(_) | BinOp::Or(_)) {
        return Some(Box::new(BoolLogicSugar {
            whole: expr.clone(),
            let_inits: capture_let_inits(fcx),
        }));
    }
    if let Some(rel) = relation_from_binop(&binary.op) {
        return Some(Box::new(CompareSugar {
            left: SugarBody::term(&binary.left, fcx),
            right: SugarBody::term(&binary.right, fcx),
            rel,
        }));
    }
    let Some(op) = term_binop_name(&binary.op) else {
        return Some(reasoned_incomplete(format!(
            "unsupported term operator `{}`",
            token_key(expr)
        )));
    };
    Some(Box::new(BinOpSugar {
        left: SugarBody::term(&binary.left, fcx),
        right: SugarBody::term(&binary.right, fcx),
        op_name: op,
    }))
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}

fn const_env(bindings: &BTreeMap<String, &Expr>) -> BTreeMap<String, ConstVal> {
    let mut env = BTreeMap::new();
    for _ in 0..bindings.len() {
        let mut changed = false;
        for (name, init) in bindings {
            if env.contains_key(name) {
                continue;
            }
            if let Some(value) = const_eval(init, &env) {
                env.insert(name.clone(), value);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    env
}

struct BoolLogicSugar {
    whole: Expr,
    let_inits: BTreeMap<String, Expr>,
}

impl Sugar for BoolLogicSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        if let Some(term) =
            const_eval(&self.whole, &const_env(&let_inits)).and_then(|value| const_val_term(&value))
        {
            return Outcome::Complete(Desugared::Term(term));
        }
        Outcome::Incomplete(Effect::Unsupported {
            reason: format!("unsupported term operator `{}`", token_key(&self.whole)),
        })
    }
}

/// The constructive arithmetic-term node. `left`/`right` are the pre-built operand
/// children (the factory desugars each operand expr into a `Sugar`); `op_name` is the
/// captured `term_binop_name(&binary.op)` string at construction. `desugar` composes
/// the children's terms and emits `Term::Ctor { name: op_name, args: vec![l, r] }` --
/// byte-identical to the `translate_term_in_scope` arm.
pub(crate) struct BinOpSugar {
    pub(crate) left: SugarBody<TermFloor>,
    pub(crate) right: SugarBody<TermFloor>,
    pub(crate) op_name: &'static str,
}

impl Sugar for BinOpSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let lhs = match self.left.reduce(ctx)? {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => {
                    return Err(FactoryGap::new(
                        "binary operator child completed a non-Term where a Term was required; write more Sugar for this AST",
                    ))
                }
            },
            Outcome::Incomplete(e) => return Ok(Outcome::Incomplete(e)),
        };
        let rhs = match self.right.reduce(ctx)? {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => {
                    return Err(FactoryGap::new(
                        "binary operator child completed a non-Term where a Term was required; write more Sugar for this AST",
                    ))
                }
            },
            Outcome::Incomplete(e) => return Ok(Outcome::Incomplete(e)),
        };
        let term = Rc::new(Term::Ctor {
            name: self.op_name.to_string(),
            args: vec![lhs, rhs],
        });
        if let Some(value) = const_fold_u128_term(&term) {
            return Ok(Outcome::Complete(Desugared::Term(u128_term(value))));
        }
        if int_fold_is_sort_safe(&term) {
            if let Some(value) = const_fold_int_term(&term) {
                return Ok(Outcome::Complete(Desugared::Term(num(value))));
            }
        }
        Ok(Outcome::Complete(Desugared::Term(term)))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

fn int_fold_is_sort_safe(term: &Term) -> bool {
    match term {
        Term::Const {
            value: ConstValue::Int(_),
            sort,
        } => sort.name == "Int",
        Term::Ctor { args, .. } => args.iter().all(|arg| int_fold_is_sort_safe(arg)),
        _ => false,
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

    fn int_const(t: &Term) -> i128 {
        match t {
            Term::Const {
                value: ConstValue::Int(value),
                sort,
            } => {
                assert_eq!(sort.name, "Int");
                *value
            }
            _ => panic!("expected an Int const term, got {t:?}"),
        }
    }

    #[test]
    fn binop_add_emits_plus_ctor_over_both_operand_terms() {
        let node = BinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("x")))),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("y")))),
            op_name: "+",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete, got Incomplete"),
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
            left: SugarBody::from_node(Box::new(StubTerm(make_var("a")))),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("b")))),
            op_name: "int-div",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete, got Incomplete"),
        };
        let (name, _) = ctor(&term);
        assert_eq!(name, "int-div");
    }

    #[test]
    fn binop_folds_ground_untyped_int_children_after_recursive_desugar() {
        let node = BinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(num(6)))),
            right: SugarBody::from_node(Box::new(StubTerm(num(1)))),
            op_name: "+",
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete, got Incomplete"),
        };
        assert_eq!(int_const(&term), 7);
    }

    #[test]
    fn binop_propagates_left_child_hit_verbatim() {
        let node = BinOpSugar {
            left: SugarBody::from_node(Box::new(StubIncomplete)),
            right: SugarBody::from_node(Box::new(StubTerm(make_var("y")))),
            op_name: "+",
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
    fn binop_propagates_right_child_hit_verbatim() {
        let node = BinOpSugar {
            left: SugarBody::from_node(Box::new(StubTerm(make_var("x")))),
            right: SugarBody::from_node(Box::new(StubIncomplete)),
            op_name: "+",
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
