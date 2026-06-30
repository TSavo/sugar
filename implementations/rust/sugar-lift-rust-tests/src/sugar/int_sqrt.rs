// SPDX-License-Identifier: Apache-2.0
//
// `IntSqrtSugar`: Rust's primitive integer `isqrt` family over a grounded integer is
// a stdlib/compiler axiom. The receiver child owns the numeric floor; this sugar
// dispatches the sqrt operation to that floor and handles only the method surface
// (`isqrt` panic vs `checked_isqrt` Option wrapping).

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{numeric_floor_from_term, IsqrtVisitor, NumericSqrt};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::primitive_int::deferred_primitive_method_term;
use crate::{const_fold_int_term, token_key, Desugared, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("int_sqrt", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    let kind = match call.method.to_string().as_str() {
        "isqrt" => Kind::Sqrt,
        "checked_isqrt" => Kind::CheckedSqrt,
        _ => return None,
    };
    Some(Box::new(IntSqrtSugar {
        kind,
        site: token_key(expr),
        receiver: SugarBody::term(&call.receiver, fcx),
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
