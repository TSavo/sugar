// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for pure `bool` Option-producing methods. This sugar has no
// effect verdict of its own: it either composes child floors into the concrete
// Option constructor, or it bubbles a child Incomplete unchanged.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Term};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "bool_literal_method",
    &["method"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
                #[test]
                fn t_bool_method_good() {
                    assert_eq!(true.then_some(7_i32), Some(7_i32));
                }
            "#,
        r#"
                #[test]
                fn t_bool_method_bad() {
                    assert_eq!(true.then_some(7_i32), Some(8_i32));
                }
            "#,
    ),
    recognize,
);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let call_frag = frag.strip_refs_groups();
    if !call_frag.call_is_method_call() {
        return None;
    }
    let method_name = call_frag.call_target_name()?;
    let args = call_frag.call_args();
    let kind = match method_name.as_str() {
        "then_some" if args.len() == 1 => BoolMethodKind::ThenSome {
            payload: SugarBody::term_frag(&args[0], fcx),
        },
        "then" if args.len() == 1 => {
            let closure_frag = args[0].strip_refs_groups();
            if !closure_frag.closure_is_zero_input() {
                return None;
            }
            let body_frag = closure_frag.closure_body_frag()?;
            BoolMethodKind::Then {
                body: SugarBody::term_frag(&body_frag.strip_refs_groups(), fcx),
            }
        }
        _ => return None,
    };
    let receiver_frag = call_frag.call_receiver()?;
    Some(Box::new(BoolMethodSugar {
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
        kind,
    }))
}

struct BoolMethodSugar {
    receiver: SugarBody<TermFloor>,
    kind: BoolMethodKind,
}

enum BoolMethodKind {
    ThenSome { payload: SugarBody<TermFloor> },
    Then { body: SugarBody<TermFloor> },
}

impl Sugar for BoolMethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(value) = literal_bool(&receiver) else {
            panic!(
                "bool method receiver did not reduce to a literal bool; write the owning Sugar before Outcome"
            );
        };

        match &self.kind {
            BoolMethodKind::ThenSome { payload } => {
                let payload = match term_body(payload, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                Outcome::Complete(Desugared::Term(if value {
                    some_term(payload)
                } else {
                    none_term()
                }))
            }
            BoolMethodKind::Then { body } => {
                if !value {
                    return Outcome::Complete(Desugared::Term(none_term()));
                }
                let payload = match term_body(body, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                Outcome::Complete(Desugared::Term(some_term(payload)))
            }
        }
    }
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before bool method"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn literal_bool(term: &Term) -> Option<bool> {
    match term {
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(*value),
        _ => None,
    }
}

// Phase-3 from_src tests: source -> SourceFragment -> observed -> accessor -> assert shape.
// No parse_quote!, no StubTerm, no run().
#[cfg(test)]
mod from_src_tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the tail MethodCall expression of the first function in a one-liner source.
    fn call_frag_from<'a>(file: &'a syn::File, src_name: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), src_name);
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `true.then_some(42)` is a MethodCall named "then_some" with 1 arg and a receiver.
    #[test]
    fn from_src_then_some_is_method_call_with_one_arg() {
        let src = "fn f() -> Option<i32> { true.then_some(42) }";
        let file = parse_file(src);
        let frag = call_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert!(frag.call_is_method_call());
        assert_eq!(frag.call_target_name().as_deref(), Some("then_some"));
        assert_eq!(frag.call_arg_count(), 1);
        assert!(
            frag.call_receiver().is_some(),
            "then_some must have a receiver"
        );
    }

    /// Discrimination: `false.then_some(99)` has a PrimitiveLiteral receiver -- not "then".
    #[test]
    fn from_src_then_some_false_receiver_is_primitive_literal_not_then() {
        let src = "fn f() -> Option<i32> { false.then_some(99) }";
        let file = parse_file(src);
        let frag = call_frag_from(&file, "f.rs");

        assert_eq!(
            frag.call_target_name().as_deref(),
            Some("then_some"),
            "method must be then_some not then"
        );
        let recv = frag.call_receiver().expect("receiver must exist");
        assert_eq!(
            recv.observed(),
            "PrimitiveLiteral",
            "false receiver must be a PrimitiveLiteral"
        );
    }

    /// Structural: `true.then(|| 42)` arg is a zero-input closure whose body is accessible.
    #[test]
    fn from_src_then_zero_input_closure_body_is_accessible() {
        let src = "fn f() -> Option<i32> { true.then(|| 42) }";
        let file = parse_file(src);
        let frag = call_frag_from(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_target_name().as_deref(), Some("then"));
        assert_eq!(frag.call_arg_count(), 1);
        let args = frag.call_args();
        let closure_frag = args[0].strip_refs_groups();
        assert!(
            closure_frag.closure_is_zero_input(),
            "|| 42 must be a zero-input closure"
        );
        assert!(
            closure_frag.closure_body_frag().is_some(),
            "closure body must be accessible via closure_body_frag"
        );
    }
}
