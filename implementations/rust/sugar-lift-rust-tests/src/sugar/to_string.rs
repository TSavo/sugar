// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib `<literal>.to_string()`. Unknown receivers
// decline so generic MethodSugar can continue digging the method-call universe.

use syn::Expr;

use std::rc::Rc;

use sugar_ir_symbolic::{str_const, Term};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::factory::{SugarBody, TermFloor};
use crate::sugar::format::{display_literal_term_floor, is_to_string_shape};
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "to_string",
        &["method", "transparent_term"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if !is_to_string_shape(expr) {
        return None;
    }
    Some(Box::new(ToStringTermSugar {
        receiver: SugarBody::term(&call.receiver, fcx),
    }))
}

struct ToStringTermSugar {
    receiver: SugarBody<TermFloor>,
}

impl Sugar for ToStringTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| panic!("to_string receiver completed as non-term")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        if let Some(value) = display_literal_term_floor(&receiver) {
            return Outcome::Complete(Desugared::Term(str_const(value)));
        }
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "method:to_string".to_string(),
            args: vec![receiver],
        })))
    }
}
