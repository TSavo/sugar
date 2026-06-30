// SPDX-License-Identifier: Apache-2.0
//
// `IntSqrtSugar`: Rust's primitive integer `isqrt` family over a grounded integer is
// a stdlib/compiler axiom. The receiver child owns the numeric floor; this sugar
// dispatches the sqrt operation to that floor and handles only the method surface
// (`isqrt` panic vs `checked_isqrt` Option wrapping).

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{numeric_floor_from_term, IsqrtVisitor, NumericSqrt};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::primitive_int::deferred_primitive_method_term;
use crate::sugar::source_fragment::SourceFragment;
use crate::{const_fold_int_term, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("int_sqrt", SugarRole::Term, recognize);

// FULLY MIGRATED (Phase-3 ratchet): no as_expr(), no raw Expr:: / MethodCall field
// access. Uses call_method_key(), call_arg_count(), call_receiver(), token_str(),
// and SugarBody::term_frag() exclusively.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let method_key = frag.call_method_key()?;
    let kind = match method_key.as_str() {
        "isqrt" => Kind::Sqrt,
        "checked_isqrt" => Kind::CheckedSqrt,
        _ => return None,
    };
    if frag.call_arg_count() != 0 {
        return None;
    }
    let receiver_frag = frag.call_receiver()?;
    Some(Box::new(IntSqrtSugar {
        kind,
        site: frag.token_str(),
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
    }))
}

#[derive(Clone, Copy)]
enum Kind {
    Sqrt,
    CheckedSqrt,
}

impl Kind {
    fn method_name(self) -> &'static str {
        match self {
            Kind::Sqrt => "isqrt",
            Kind::CheckedSqrt => "checked_isqrt",
        }
    }
}

struct IntSqrtSugar {
    kind: Kind,
    site: String,
    receiver: SugarBody<TermFloor>,
}

impl Sugar for IntSqrtSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(floor) = numeric_floor_from_term(&receiver) else {
            return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                self.kind.method_name(),
                receiver,
                Vec::new(),
            )));
        };
        let Some(result) = floor.accept(IsqrtVisitor) else {
            panic!(
                "int sqrt numeric floor could not compute a result; write the owning typed floor before Outcome"
            );
        };
        match (self.kind, result) {
            (Kind::Sqrt, NumericSqrt::Root(root)) => {
                let Some(term) = root.term() else {
                    panic!("int sqrt numeric floor could not reify its result term");
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::int_sqrt",
                    ?floor,
                    ?root,
                    "resolved primitive integer isqrt stdlib axiom to literal"
                );
                Outcome::Complete(Desugared::Term(term))
            }
            (Kind::Sqrt, NumericSqrt::Negative) => Outcome::Incomplete(Effect::LiteralPanic {
                boundary: self.site.clone(),
                reason: format!(
                    "primitive integer `isqrt` on negative literal `{}` panics; refused",
                    receiver_label(&receiver)
                ),
            }),
            (Kind::CheckedSqrt, NumericSqrt::Root(root)) => {
                let Some(term) = root.term() else {
                    panic!("checked_isqrt numeric floor could not reify its result term");
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::int_sqrt",
                    ?floor,
                    ?root,
                    "resolved primitive integer checked_isqrt stdlib axiom to Some literal"
                );
                Outcome::Complete(Desugared::Term(some_term(term)))
            }
            (Kind::CheckedSqrt, NumericSqrt::Negative) => {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::int_sqrt",
                    ?floor,
                    "resolved primitive integer checked_isqrt stdlib axiom to None"
                );
                Outcome::Complete(Desugared::Term(none_term()))
            }
        }
    }
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before int sqrt"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn receiver_label(receiver: &Rc<Term>) -> String {
    const_fold_int_term(receiver).map_or_else(|| format!("{receiver:?}"), |value| value.to_string())
}

pub(crate) fn term_as_int(term: &Rc<Term>) -> Option<i128> {
    const_fold_int_term(term)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn isqrt_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        // The tail expression statement is the only statement;
        // `terms()` on the Expr stmt yields the single method-call expr child.
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `x.isqrt()` is classified as `"MethodCall"`, `call_method_key()` returns
    /// `"isqrt"`, `call_arg_count()` is 0, `call_receiver()` yields a `"Name"` fragment.
    /// Decodes to `Kind::Sqrt` -- no raw syn.
    #[test]
    fn from_src_isqrt_observed_method_key_and_receiver() {
        let file = parse_file("fn f(x: u32) -> u32 { x.isqrt() }");
        let frag = isqrt_expr_frag(&file, "f.rs");

        // observed
        assert_eq!(frag.observed(), "MethodCall");

        // method key via typed accessor (no as_expr / Expr:: / MethodCall field access here)
        assert_eq!(frag.call_method_key().as_deref(), Some("isqrt"));

        // arg count: zero (the method takes no explicit args)
        assert_eq!(frag.call_arg_count(), 0);

        // receiver: `x` is a Name fragment
        let recv = frag.call_receiver().expect("receiver present");
        assert_eq!(recv.observed(), "Name");

        // floor: decode to Kind::Sqrt -- the struct holds this, not raw syn
        let method_key = frag.call_method_key().unwrap();
        let kind = match method_key.as_str() {
            "isqrt" => Kind::Sqrt,
            "checked_isqrt" => Kind::CheckedSqrt,
            _ => panic!("unexpected method key: {method_key}"),
        };
        assert!(matches!(kind, Kind::Sqrt));
    }

    /// Discrimination: `x.checked_isqrt()` has method key `"checked_isqrt"` and
    /// decodes to `Kind::CheckedSqrt`. Proves `call_method_key()` distinguishes
    /// CheckedSqrt from Sqrt.
    #[test]
    fn discrimination_checked_isqrt_decodes_to_checked_sqrt_kind() {
        let file = parse_file("fn f(x: i32) -> Option<i32> { x.checked_isqrt() }");
        let frag = isqrt_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("checked_isqrt"));
        assert_eq!(frag.call_arg_count(), 0);

        let recv = frag.call_receiver().expect("receiver present");
        assert_eq!(recv.observed(), "Name");

        let method_key = frag.call_method_key().unwrap();
        let kind = match method_key.as_str() {
            "isqrt" => Kind::Sqrt,
            "checked_isqrt" => Kind::CheckedSqrt,
            _ => panic!("unexpected method key: {method_key}"),
        };
        assert!(matches!(kind, Kind::CheckedSqrt));
    }

    /// Structural: a `BinOp` fragment returns `None` from both `call_method_key()` and
    /// `call_receiver()` -- the accessors are shape-specific and do not bleed across kinds.
    #[test]
    fn structural_binop_returns_none_from_call_method_accessors() {
        let file = parse_file("fn f(a: i32, b: i32) -> i32 { a + b }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let binop_frag = &terms[0];

        assert_eq!(binop_frag.observed(), "BinOp");
        assert_eq!(binop_frag.call_method_key(), None);
        assert!(binop_frag.call_receiver().is_none());
        assert_eq!(binop_frag.call_arg_count(), 0); // returns 0 (not found, empty vec)
    }
}
