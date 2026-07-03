// SPDX-License-Identifier: Apache-2.0
//
// BoolBitwiseSugar: Rust permits `&` and `|` over `bool`. In assertion
// position, those are first-order conjunction/disjunction after each side has
// been lowered by the constraint factory.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{ConstraintFloor, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant};
use sugar_ir_symbolic::{and_, or_, Formula};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_bool_bitwise",
    SugarRole::Constraint,
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_constraint_bool_bitwise_good() {
                assert!(true & true);
            }
        "#,
        r#"
            #[test]
            fn t_constraint_bool_bitwise_bad() {
                assert!(true & false);
            }
        "#,
    ),
    recognize,
);

struct BoolBitwiseSugar {
    left: SugarBody<ConstraintFloor>,
    right: SugarBody<ConstraintFloor>,
    is_and: bool,
}

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let frag = frag.strip_refs_groups();
    let is_and = match frag.binop_op_kind()? {
        "BitAnd" => true,
        "BitOr" => false,
        _ => return None,
    };
    let left_frag = frag.binop_left()?;
    let right_frag = frag.binop_right()?;
    Some(Box::new(BoolBitwiseSugar {
        left: SugarBody::constraint_frag(&left_frag, fcx),
        right: SugarBody::constraint_frag(&right_frag, fcx),
        is_and,
    }))
}

impl Sugar for BoolBitwiseSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let left = match constraint_payload(&self.left, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let right = match constraint_payload(&self.right, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let atom = if self.is_and {
            and_(vec![left.atom, right.atom])
        } else {
            or_(vec![left.atom, right.atom])
        };
        Outcome::Complete(Desugared::Constraints {
            atom,
            n: 1,
            kind: if left.kind.is_warranted() || right.kind.is_warranted() {
                AssertionFactKind::Warranted
            } else {
                AssertionFactKind::Support
            },
            warrant: Warrant {
                name: common_constraint_name(&left.name, &right.name),
            },
        })
    }
}

struct ConstraintPayload {
    atom: Rc<Formula>,
    kind: AssertionFactKind,
    name: Option<String>,
}

fn constraint_payload(
    body: &SugarBody<ConstraintFloor>,
    ctx: &SugarCtx,
) -> Result<ConstraintPayload, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(Desugared::Constraints {
            atom,
            kind,
            warrant,
            ..
        }) => Ok(ConstraintPayload {
            atom,
            kind,
            name: warrant.name,
        }),
        Outcome::Complete(_) => bool_bitwise_gap("child reduced to a non-constraint floor"),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn common_constraint_name(left: &Option<String>, right: &Option<String>) -> Option<String> {
    match (left, right) {
        (Some(left), Some(right)) if left == right => Some(left.clone()),
        _ => None,
    }
}

fn bool_bitwise_gap(reason: &str) -> ! {
    panic!("bool_bitwise did not reach a lawful floor: {reason}")
}

#[cfg(test)]
mod from_src_tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the tail expression of the first function body.
    fn bitwise_frag_from<'a>(file: &'a syn::File, src_name: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), src_name);
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// `a & b` is observed as "BinOp", op_kind is "BitAnd", and both children are present.
    #[test]
    fn from_src_bitand_is_binop_with_bitand_op_kind_and_two_children() {
        let src = "fn f(a: bool, b: bool) -> bool { a & b }";
        let file = parse_file(src);
        let frag = bitwise_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.binop_op_kind(), Some("BitAnd"));
        assert!(
            frag.binop_left().is_some(),
            "BitAnd must have a left operand"
        );
        assert!(
            frag.binop_right().is_some(),
            "BitAnd must have a right operand"
        );
    }

    /// `a | b` is observed as "BinOp", op_kind is "BitOr", and both children are present.
    #[test]
    fn from_src_bitor_is_binop_with_bitor_op_kind_and_two_children() {
        let src = "fn f(a: bool, b: bool) -> bool { a | b }";
        let file = parse_file(src);
        let frag = bitwise_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert_eq!(frag.binop_op_kind(), Some("BitOr"));
        assert!(
            frag.binop_left().is_some(),
            "BitOr must have a left operand"
        );
        assert!(
            frag.binop_right().is_some(),
            "BitOr must have a right operand"
        );
    }

    /// `(a & b)` -- strip_refs_groups peels the paren wrapper and exposes the BinOp.
    #[test]
    fn from_src_paren_wrapped_bitand_strips_to_binop() {
        let src = "fn f(a: bool, b: bool) -> bool { (a & b) }";
        let file = parse_file(src);
        let frag = bitwise_frag_from(&file, "f.rs");

        // The raw fragment is a Paren; after stripping it becomes BinOp.
        let inner = frag.strip_refs_groups();
        assert_eq!(inner.observed(), "BinOp");
        assert_eq!(inner.binop_op_kind(), Some("BitAnd"));
    }
}
