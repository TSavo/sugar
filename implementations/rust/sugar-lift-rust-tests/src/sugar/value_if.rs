// SPDX-License-Identifier: Apache-2.0
//
// `ValueIfSugar`: a term-position `if cond { a } else { b }` whose branches
// already have term floors. The sugar owns only the source composition; branch
// selection is delegated to the term floor helper so map/closure currying can
// substitute a literal argument into the guard and pick the concrete branch.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::factory::{BoolFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{value_if_term, DesugaredFloorAccept, RequiredTermVisitor};
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "value_if",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize,
    );

/// No `as_expr()`, `Expr::`, or raw syn in this function.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.if_test().is_none() {
        return None;
    }
    if frag.if_cond_is_side_effecting() {
        return None;
    }
    let then_frag = frag.if_then_single_expr_frag()?;
    let else_frag = frag.if_orelse()?;
    let cond_frag = frag.if_test()?;
    Some(Box::new(ValueIfSugar {
        cond: SugarBody::bool_expr_frag(&cond_frag, fcx),
        then_body: SugarBody::term_frag(&then_frag, fcx),
        else_body: SugarBody::term_frag(&else_frag, fcx),
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

// ---------------------------------------------------------------------------
// Phase-3 from_src tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    /// Positive: `if x { 1_i32 } else { 2_i32 }` is an If; accessors work.
    #[test]
    fn from_src_value_if_accessors_gate() {
        let expr: Expr = syn::parse_str("if x { 1_i32 } else { 2_i32 }").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "If");
        assert!(frag.if_test().is_some(), "must have condition");
        assert!(
            !frag.if_cond_is_side_effecting(),
            "simple var cond is not side-effecting"
        );
        assert!(
            frag.if_then_single_expr_frag().is_some(),
            "single-expr then branch"
        );
        assert!(frag.if_orelse().is_some(), "must have else branch");
    }

    /// Discrimination: a BinOp is not an If.
    #[test]
    fn from_src_binop_not_value_if() {
        let expr: Expr = syn::parse_str("x + 1").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "BinOp");
        assert!(frag.if_test().is_none());

        let scope = TemporalScope::new("value-if-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "BinOp must not be recognized as value_if"
        );
    }

    /// Structural: `if cond { a; b }` (multi-stmt then branch) returns None.
    #[test]
    fn from_src_multi_stmt_then_branch_not_recognized() {
        let expr: Expr =
            syn::parse_str("if x { let _a = 1_i32; 2_i32 } else { 3_i32 }").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "If");
        // multi-stmt then branch: if_then_single_expr_frag() returns None
        assert!(
            frag.if_then_single_expr_frag().is_none(),
            "multi-stmt then branch must return None"
        );

        let scope = TemporalScope::new("value-if-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "multi-stmt then branch must not be recognized"
        );
    }
}
