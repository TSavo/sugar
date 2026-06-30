// SPDX-License-Identifier: Apache-2.0
//
// `ValueIfSugar`: a term-position `if cond { a } else { b }` whose branches
// already have term floors. The sugar owns only the source composition; branch
// selection is delegated to the term floor helper so map/closure currying can
// substitute a literal argument into the guard and pick the concrete branch.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, Stmt};

use crate::sugar::factory::{BoolFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::term_dispatch::{value_if_term, DesugaredFloorAccept, RequiredTermVisitor};
use crate::{Desugared, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("value_if", recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::If(if_expr) = expr else {
        return None;
    };
    if crate::closure_body_is_side_effecting(&if_expr.cond) {
        return None;
    }
    let then_expr = single_expr_tail(&if_expr.then_branch.stmts)?;
    let (_, else_expr) = if_expr.else_branch.as_ref()?;
    Some(Box::new(ValueIfSugar {
        cond: SugarBody::bool_expr(&if_expr.cond, fcx),
        then_body: SugarBody::term(then_expr, fcx),
        else_body: SugarBody::term(else_expr, fcx),
    }))
}

struct ValueIfSugar {
    cond: SugarBody<BoolFloor>,
    then_body: SugarBody<TermFloor>,
    else_body: SugarBody<TermFloor>,
}

impl Sugar for ValueIfSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let cond = match reduce_required_term(&self.cond, "value_if condition", ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let then_term = match reduce_required_term(&self.then_body, "value_if then branch", ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let else_term = match reduce_required_term(&self.else_body, "value_if else branch", ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        Outcome::Complete(Desugared::Term(value_if_term(cond, then_term, else_term)))
    }
}

fn single_expr_tail(stmts: &[Stmt]) -> Option<&Expr> {
    match stmts {
        [Stmt::Expr(expr, None)] => Some(expr),
        _ => None,
    }
}

fn reduce_required_term<F: crate::sugar::factory::BodyFloor>(
    body: &SugarBody<F>,
    owner: &'static str,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d.accept_desugared_floor(RequiredTermVisitor { owner })),
        Outcome::Incomplete(e) => Err(Outcome::Incomplete(e)),
    }
}
