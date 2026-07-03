// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Field` (`base.member`): the base child is constructed
// by the factory, and desugar visits the floor it returns. Tuple-component floors
// project directly; ordinary term floors emit the congruent `field:<member>` ctor.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::factory::{
    has_tuple_producer_frag, SugarBody, SugarBuildCtx, TermFloor, TupleProducerFloor,
};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{DesugaredFloorAccept, DesugaredFloorVisitor};
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "field_term",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
#[derive(Debug, PartialEq)]
struct WitnessPoint { x: i32 }

#[test]
fn t_field_term_good() {
    assert_eq!(WitnessPoint { x: 5 }.x, 5);
}
"#,
            r#"
#[derive(Debug, PartialEq)]
struct WitnessPoint { x: i32 }

#[test]
fn t_field_term_bad() {
    assert_eq!(WitnessPoint { x: 5 }.x, 6);
}
"#,
        ),
        recognize,
    );

/// TERM recognizer for `Expr::Field`.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.observed() != "Field" {
        return None;
    }
    let member = frag.attr_name()?;
    let base_frag = frag.field_receiver()?;
    let tuple_index = frag.field_tuple_index();

    if frag.field_is_unnamed() && has_tuple_producer_frag(&base_frag, fcx) {
        Some(Box::new(FieldTermSugar {
            member,
            base: FieldBase::Tuple {
                body: SugarBody::tuple_producer_frag(&base_frag, fcx),
            },
            tuple_index,
        }))
    } else {
        Some(Box::new(FieldTermSugar {
            member,
            base: FieldBase::Term {
                body: SugarBody::term_frag(&base_frag, fcx),
            },
            tuple_index,
        }))
    }
}

struct FieldTermSugar {
    member: String,
    base: FieldBase,
    tuple_index: Option<usize>,
}

enum FieldBase {
    Term { body: SugarBody<TermFloor> },
    Tuple { body: SugarBody<TupleProducerFloor> },
}

impl Sugar for FieldTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let floor = match &self.base {
            FieldBase::Term { body } => match body.reduce(ctx) {
                Outcome::Complete(floor) => floor,
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            },
            FieldBase::Tuple { body } => match body.reduce(ctx) {
                Outcome::Complete(floor) => floor,
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            },
        };
        floor.accept_desugared_floor(FieldProjectionVisitor {
            member: &self.member,
            tuple_index: self.tuple_index,
        })
    }
}

struct FieldProjectionVisitor<'a> {
    member: &'a str,
    tuple_index: Option<usize>,
}

impl DesugaredFloorVisitor for FieldProjectionVisitor<'_> {
    type Output = Outcome;

    fn visit_term(self, term: Rc<Term>) -> Self::Output {
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("field:{}", self.member),
            args: vec![term],
        })))
    }

    fn visit_term_seq(self, _terms: Vec<Rc<Term>>) -> Self::Output {
        field_gap(self.member)
    }

    fn visit_tuple_components(self, parts: Vec<Rc<Term>>) -> Self::Output {
        let index = self.tuple_index.unwrap_or_else(|| field_gap(self.member));
        let term = parts
            .get(index)
            .cloned()
            .unwrap_or_else(|| field_gap(self.member));
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_passthrough(self, _floor: Desugared) -> Self::Output {
        field_gap(self.member)
    }
}

fn field_gap(member: &str) -> ! {
    panic!(
        "FieldTermSugar `{member}` base completed a floor that cannot own field projection; write more Sugar for this AST"
    )
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // field accessors (attr_name, field_receiver, field_is_unnamed, field_tuple_index)
    // -> assert struct fields. No parse_quote!, no StubTerm, no run(). The struct
    // holds ONLY String + FieldBase(SugarBody) + Option<usize> -- zero raw-syn fields
    // -- proving the migration is complete.
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the tail-expression term fragment in a one-line fn body.
    fn tail_term_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        stmts[0]
            .terms()
            .into_iter()
            .next()
            .expect("term in first statement")
    }

    /// Positive: `s.x` -> observed "Field", attr_name "x", not unnamed, no tuple_index,
    /// field_receiver is the base fragment. Proves the named-field accessor path is clean.
    #[test]
    fn from_src_named_field_accessors_are_clean() {
        let src = "fn f(s: S) -> i32 { s.x }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Field");
        assert_eq!(frag.attr_name().as_deref(), Some("x"));
        assert!(!frag.field_is_unnamed(), "named field must not be unnamed");
        assert!(
            frag.field_tuple_index().is_none(),
            "named field has no tuple index"
        );

        let base = frag
            .field_receiver()
            .expect("field_receiver must return Some for Field node");
        // The base of `s.x` is the path `s`.
        assert_eq!(base.observed(), "Name");
    }

    /// Discrimination: `t.0` -> observed "Field", attr_name "0", is unnamed, tuple_index Some(0).
    /// Proves the unnamed (tuple projection) path is detected and the index is correct.
    #[test]
    fn from_src_unnamed_field_detects_tuple_index() {
        let src = "fn f(t: T) -> i32 { t.0 }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Field");
        assert_eq!(frag.attr_name().as_deref(), Some("0"));
        assert!(frag.field_is_unnamed(), "tuple projection must be unnamed");
        assert_eq!(
            frag.field_tuple_index(),
            Some(0),
            "tuple index must be 0 for .0"
        );

        let base = frag
            .field_receiver()
            .expect("field_receiver must return Some");
        assert_eq!(base.observed(), "Name");
    }

    /// Structural: a non-Field fragment (BinOp) must return None / false from all
    /// field-specific accessors. Proves the guards do not over-claim on other shapes.
    #[test]
    fn from_src_non_field_returns_none_for_field_accessors() {
        let src = "fn f() -> i32 { 1 + 2 }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert!(frag.attr_name().is_none(), "BinOp has no attr_name");
        assert!(!frag.field_is_unnamed(), "BinOp must not be unnamed");
        assert!(
            frag.field_tuple_index().is_none(),
            "BinOp has no tuple_index"
        );
        assert!(
            frag.field_receiver().is_none(),
            "BinOp has no field_receiver"
        );
    }
}
