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
// `Some`, then the `term_binop_name` lookup itself). Those early returns and the op-name
// resolution are owned by `recognize`, which builds this node only for the arithmetic
// tail. If the operator has no arithmetic owner here, construction declines and the
// factory gap stays loud. This node composes its two pre-built children and emits the
// arithmetic ctor over their terms, propagating a child `Incomplete` verbatim.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Term};

use crate::sugar::compare::CompareSugar;
use crate::sugar::factory::{BoolFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::term_dispatch::{BoolFloorAccept, RequiredBoolVisitor};
use crate::sugar::term_leaf::resolved_term;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, const_fold_int_term, const_fold_u128_term, num,
    u128_term, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term("binop", recognize);

/// TERM recognizer for `Expr::Binary`. Mirrors the source-of-truth arm in order: the
/// comparison branch (const-fold to a Bool, else the `cmp:*` [`CompareSugar`]), then
/// the arithmetic-op [`BinOpSugar`]. If no arithmetic op exists after the bool/compare
/// branches, this sugar does not own the expression and the factory gap path remains loud.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Gate: must be a BinOp (Expr::Binary) fragment.
    if frag.observed() != "BinOp" {
        return None;
    }
    // Const-fold the whole expression first: `1 + 2` -> `num(3)`, `1 < 2` -> `bool_const(true)`.
    if let Some(term) = frag.binop_const_folded_term() {
        return Some(resolved_term(term));
    }
    // Boolean logic operators (&&, ||): both operands are BoolFloor.
    let op_kind = frag.binop_op_kind()?;
    if op_kind == "And" || op_kind == "Or" {
        let left_frag = frag.binop_left()?;
        let right_frag = frag.binop_right()?;
        return Some(Box::new(BoolLogicSugar {
            left: SugarBody::<BoolFloor>::bool_expr_frag(&left_frag, fcx),
            right: SugarBody::<BoolFloor>::bool_expr_frag(&right_frag, fcx),
            is_and: op_kind == "And",
        }));
    }
    // Comparison operators (==, !=, <, <=, >, >=): emit a `cmp:*` ctor via CompareSugar.
    if let Some(rel) = frag.binop_relation() {
        let left_frag = frag.binop_left()?;
        let right_frag = frag.binop_right()?;
        return Some(Box::new(CompareSugar {
            left: SugarBody::term_frag(&left_frag, fcx),
            right: SugarBody::term_frag(&right_frag, fcx),
            rel,
        }));
    }
    // Arithmetic operators (+, -, *, /, %): emit arithmetic ctor; declines for bit-ops
    // and any operator without an arithmetic term name (factory gap stays loud).
    let op = frag.binop_term_name()?;
    let left_frag = frag.binop_left()?;
    let right_frag = frag.binop_right()?;
    Some(Box::new(BinOpSugar {
        left: SugarBody::term_frag(&left_frag, fcx),
        right: SugarBody::term_frag(&right_frag, fcx),
        op_name: op,
    }))
}

pub(crate) struct BoolLogicSugar {
    pub(crate) left: SugarBody<BoolFloor>,
    pub(crate) right: SugarBody<BoolFloor>,
    pub(crate) is_and: bool,
}

impl Sugar for BoolLogicSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let left = match bool_body_value(&self.left, ctx, "binary boolean operator") {
            Ok(value) => value,
            Err(outcome) => return outcome,
        };
        if self.is_and && !left {
            return Outcome::Complete(Desugared::Term(bool_const(false)));
        }
        if !self.is_and && left {
            return Outcome::Complete(Desugared::Term(bool_const(true)));
        }
        let right = match bool_body_value(&self.right, ctx, "binary boolean operator") {
            Ok(value) => value,
            Err(outcome) => return outcome,
        };
        Outcome::Complete(Desugared::Term(bool_const(right)))
    }
}

fn bool_body_value(
    body: &SugarBody<BoolFloor>,
    ctx: &SugarCtx,
    owner: &'static str,
) -> Result<bool, Outcome> {
    let term = match body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_term()
            .unwrap_or_else(|| binop_gap("boolean child completed as non-term")),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    Ok(term.accept_bool_floor(RequiredBoolVisitor { owner }))
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
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let lhs = match self.left.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => binop_gap(
                    "binary operator child completed a non-Term where a Term was required",
                ),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        let rhs = match self.right.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => binop_gap(
                    "binary operator child completed a non-Term where a Term was required",
                ),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        let term = Rc::new(Term::Ctor {
            name: self.op_name.to_string(),
            args: vec![lhs, rhs],
        });
        if let Some(value) = const_fold_u128_term(&term) {
            return Outcome::Complete(Desugared::Term(u128_term(value)));
        }
        if int_fold_is_sort_safe(&term) {
            if let Some(value) = const_fold_int_term(&term) {
                return Outcome::Complete(Desugared::Term(num(value)));
            }
        }
        Outcome::Complete(Desugared::Term(term))
    }
}

fn binop_gap(reason: &str) -> ! {
    panic!("binary operator did not reach lawful child floors: {reason}; write more Sugar for this AST")
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

    fn bool_const_value(t: &Term) -> bool {
        match t {
            Term::Const {
                value: ConstValue::Bool(value),
                sort,
            } => {
                assert_eq!(sort.name, "Bool");
                *value
            }
            _ => panic!("expected a Bool const term, got {t:?}"),
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
    fn bool_logic_and_dispatches_left_floor_and_short_circuits_false() {
        let node = BoolLogicSugar {
            left: SugarBody::from_node(Box::new(StubTerm(bool_const(false)))),
            right: SugarBody::from_node(Box::new(StubIncomplete)),
            is_and: true,
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected left-false && to complete before right"),
        };
        assert!(!bool_const_value(&term));
    }

    #[test]
    fn bool_logic_or_dispatches_left_floor_and_short_circuits_true() {
        let node = BoolLogicSugar {
            left: SugarBody::from_node(Box::new(StubTerm(bool_const(true)))),
            right: SugarBody::from_node(Box::new(StubIncomplete)),
            is_and: false,
        };
        let term = match run(&node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected left-true || to complete before right"),
        };
        assert!(bool_const_value(&term));
    }

    #[test]
    fn bool_logic_propagates_right_child_hit_when_right_is_evaluated() {
        let node = BoolLogicSugar {
            left: SugarBody::from_node(Box::new(StubTerm(bool_const(true)))),
            right: SugarBody::from_node(Box::new(StubIncomplete)),
            is_and: true,
        };
        match run(&node) {
            Outcome::Incomplete(Effect::Mutation { boundary }) => {
                assert_eq!(boundary, "stub");
            }
            Outcome::Incomplete(_) => {
                panic!("expected the right child's Mutation Incomplete, got a different Effect")
            }
            Outcome::Complete(_) => panic!("expected evaluated right child's Incomplete"),
        }
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

// ---------------------------------------------------------------------------
// Phase-3 from_src tests: source -> SourceFragment -> observed -> accessor ->
// assert shape. No parse_quote!, no StubTerm, no run().
// ---------------------------------------------------------------------------
#[cfg(test)]
mod from_src_tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use sugar_ir_symbolic::{ConstValue, Term};

    /// Navigate to the tail expression of the first function in a one-liner source.
    fn binop_frag_from<'a>(file: &'a syn::File, src_name: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), src_name);
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// An arithmetic binop yields `binop_term_name()` and has no relation or const fold.
    #[test]
    fn from_src_arithmetic_binop_term_name_maps_to_canonical_op() {
        let src = "fn f(a: i32, b: i32) -> i32 { a + b }";
        let file = parse_file(src);
        let frag = binop_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.binop_term_name(), Some("+"), "Add must map to \"+\"");
        assert!(frag.binop_relation().is_none(), "a + b is not a comparison");
        assert!(frag.binop_const_folded_term().is_none(), "a + b has variables; no fold");
    }

    /// A comparison binop yields `binop_relation()` and no arithmetic term name.
    #[test]
    fn from_src_comparison_binop_relation_is_some_term_name_is_none() {
        let src = "fn f(a: i32, b: i32) -> bool { a < b }";
        let file = parse_file(src);
        let frag = binop_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert!(frag.binop_relation().is_some(), "a < b must have a RelationOp");
        assert!(frag.binop_term_name().is_none(), "a < b is not an arithmetic binop");
    }

    /// A ground integer addition const-folds to its sum.
    #[test]
    fn from_src_const_fold_ground_addition_folds_to_int_term() {
        let src = "fn f() -> i32 { 2 + 3 }";
        let file = parse_file(src);
        let frag = binop_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        let term = frag
            .binop_const_folded_term()
            .expect("2 + 3 must const-fold to 5");
        match &*term {
            Term::Const { value: ConstValue::Int(v), .. } => {
                assert_eq!(*v, 5, "2 + 3 must fold to 5");
            }
            other => panic!("expected Int const 5, got {other:?}"),
        }
    }

    /// A boolean-logic binop (&&) has `op_kind == "And"` and neither term-name nor relation.
    #[test]
    fn from_src_bool_logic_and_has_op_kind_but_no_term_name_or_relation() {
        let src = "fn f(a: bool, b: bool) -> bool { a && b }";
        let file = parse_file(src);
        let frag = binop_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.binop_op_kind(), Some("And"));
        assert!(frag.binop_term_name().is_none(), "&& is not an arithmetic binop");
        assert!(frag.binop_relation().is_none(), "&& is not a comparison");
    }
}
