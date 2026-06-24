// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for pure `bool` Option-producing methods. This sugar has no
// effect verdict of its own: it either composes child floors into the concrete
// Option constructor, or it bubbles a child Incomplete unchanged.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Term};
use syn::Expr;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic::{none_term, some_term};
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("bool_literal_method", &["method"], recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let kind = match call.method.to_string().as_str() {
        "then_some" if call.args.len() == 1 => BoolMethodKind::ThenSome {
            payload: SugarBody::term(&call.args[0], fcx),
        },
        "then" if call.args.len() == 1 => {
            let Expr::Closure(closure) = strip_refs_groups(&call.args[0]) else {
                return None;
            };
            if !closure.inputs.is_empty() {
                return None;
            }
            BoolMethodKind::Then {
                body: SugarBody::term(strip_refs_groups(closure.body.as_ref()), fcx),
            }
        }
        _ => return None,
    };
    Some(Box::new(BoolMethodSugar {
        receiver: SugarBody::term(&call.receiver, fcx),
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
