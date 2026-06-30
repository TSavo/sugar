// SPDX-License-Identifier: Apache-2.0
//
// `IntMidpointSugar`: primitive integer `T::midpoint(a, b)` over text-determined
// operands is a stdlib/compiler axiom. The associated type supplies the width and
// signedness; desugar composes typed operand floors and emits the exact literal
// result when both operands bottom out.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{
    numeric_floor_from_term, primitive_int_kind, IntKind, MidpointVisitor,
};
use crate::sugar::source_fragment::SourceFragment;
use crate::{canonical_term_sig, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("int_midpoint", &["call"], recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 2 {
        return None;
    }
    let kind = midpoint_kind(&call.func)?;
    Some(Box::new(IntMidpointSugar {
        lhs: SugarBody::term(&call.args[0], fcx),
        rhs: SugarBody::term(&call.args[1], fcx),
        kind,
    }))
}

fn midpoint_kind(func: &Expr) -> Option<IntKind> {
    let Expr::Path(path) = crate::strip_refs_groups(func) else {
        return None;
    };
    if path.path.segments.last()?.ident != "midpoint" {
        return None;
    }
    if let Some(qself) = &path.qself {
        let syn::Type::Path(ty) = qself.ty.as_ref() else {
            return None;
        };
        return primitive_int_kind(&ty.path.segments.last()?.ident.to_string());
    }
    let ty = path.path.segments.iter().rev().nth(1)?.ident.to_string();
    primitive_int_kind(&ty)
}

struct IntMidpointSugar {
    lhs: SugarBody<TermFloor>,
    rhs: SugarBody<TermFloor>,
    kind: IntKind,
}

impl Sugar for IntMidpointSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let lhs = match term_body(&self.lhs, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let rhs = match term_body(&self.rhs, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let lhs_floor = match numeric_floor_from_term(&lhs) {
            Some(floor) => floor,
            None => return runtime_midpoint_operand(&lhs, self.kind),
        };
        let rhs_floor = match numeric_floor_from_term(&rhs) {
            Some(floor) => floor,
            None => return runtime_midpoint_operand(&rhs, self.kind),
        };
        let Some(result) = lhs_floor.accept(MidpointVisitor {
            rhs: rhs_floor,
            kind: self.kind,
        }) else {
            panic!(
                "int midpoint numeric floors could not compute a result; write the owning typed floor before Outcome"
            );
        };
        let Some(term) = result.term() else {
            panic!("int midpoint numeric floor could not reify its result term");
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::int_midpoint",
            kind = self.kind.name,
            ?lhs_floor,
            ?rhs_floor,
            ?result,
            "resolved primitive integer midpoint stdlib axiom"
        );
        Outcome::Complete(Desugared::Term(term))
    }
}

fn runtime_midpoint_operand(term: &Rc<Term>, kind: IntKind) -> Outcome {
    Outcome::Incomplete(Effect::RuntimeNumericOperand {
        boundary: canonical_term_sig(term),
        operation: "midpoint".to_string(),
        kind: kind.name.to_string(),
    })
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before int midpoint"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}
