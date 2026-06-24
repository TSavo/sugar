// SPDX-License-Identifier: Apache-2.0
//
// Literal `RangeInclusive` endpoint accessors.
//
// `RangeInclusive::{start,end}` returns shared references to the written endpoints.  For an
// inline inclusive range whose selected endpoint completes to a concrete integer literal, this is
// value sugar: lower to `ref(<endpoint>)` so the existing unary deref rule can reduce
// `*(a..=b).start()` / `*(a..=b).end()` to the literal floor. Recognition is deliberately
// syntactic and lazy: it selects the endpoint site and constructs the endpoint child body without
// reducing it. Desugar/reduce owns the terminal decision.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, RangeLimits};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::term_dispatch::{
    DesugaredFloorAccept, RequiredTermVisitor, TermFloorAccept, TermFloorVisitor,
};
use crate::{const_fold_int_term, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

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
    Some(RangeAccessorSugar::new(
        kind,
        SugarBody::term(endpoint, fcx),
    ))
}

#[derive(Clone, Copy)]
enum EndpointKind {
    Start,
    End,
}

struct RangeAccessorSugar {
    kind: EndpointKind,
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
        endpoint.accept_term_floor(RequiredLiteralEndpointVisitor {
            endpoint: self.kind.name(),
        });
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![endpoint],
        })))
    }
}

struct RequiredLiteralEndpointVisitor<'a> {
    endpoint: &'a str,
}

impl TermFloorVisitor for RequiredLiteralEndpointVisitor<'_> {
    type Output = ();

    fn visit_term(self, term: &Rc<Term>) -> Self::Output {
        if const_fold_int_term(term).is_none() {
            panic!(
                "range accessor {} endpoint did not dispatch to an integer literal floor",
                self.endpoint
            );
        }
    }
}

impl EndpointKind {
    fn name(self) -> &'static str {
        match self {
            Self::Start => "start",
            Self::End => "end",
        }
    }
}

impl RangeAccessorSugar {
    fn new(kind: EndpointKind, endpoint: SugarBody<TermFloor>) -> Box<dyn Sugar> {
        Box::new(Self { kind, endpoint })
    }
}
