// SPDX-License-Identifier: Apache-2.0
//
// Literal `RangeInclusive` endpoint accessors.
//
// `RangeInclusive::{start,end}` returns shared references to the written endpoints.  For an
// inline inclusive range, this is value sugar: lower to `ref(<endpoint floor>)` so the existing
// unary deref rule can reduce `*(a..=b).start()` / `*(a..=b).end()` through the endpoint's own
// floor. Recognition is deliberately syntactic and lazy: it selects the endpoint site and
// constructs the endpoint child body without reducing it. Desugar/reduce owns the terminal
// decision and bubbles any endpoint effect.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, RangeLimits};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::term_dispatch::{DesugaredFloorAccept, RequiredTermVisitor};
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before("range_accessor", &["method"], recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    let kind = match call.method.to_string().as_str() {
        "start" => EndpointKind::Start,
        "end" => EndpointKind::End,
        _ => return None,
    };
    let Expr::Range(range) = strip_refs_groups(&call.receiver) else {
        return None;
    };
    if !matches!(range.limits, RangeLimits::Closed(_)) {
        return None;
    }
    let endpoint = match kind {
        EndpointKind::Start => range.start.as_deref(),
        EndpointKind::End => range.end.as_deref(),
    }?;
    Some(RangeAccessorSugar::new(SugarBody::term(endpoint, fcx)))
}

#[derive(Clone, Copy)]
enum EndpointKind {
    Start,
    End,
}

struct RangeAccessorSugar {
    endpoint: SugarBody<TermFloor>,
}

impl Sugar for RangeAccessorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let endpoint = match self.endpoint.reduce(ctx) {
            Outcome::Complete(d) => d.accept_desugared_floor(RequiredTermVisitor {
                owner: "range accessor endpoint",
            }),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![endpoint],
        })))
    }
}

impl RangeAccessorSugar {
    fn new(endpoint: SugarBody<TermFloor>) -> Box<dyn Sugar> {
        Box::new(Self { endpoint })
    }
}
