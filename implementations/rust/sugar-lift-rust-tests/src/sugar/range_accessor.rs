// SPDX-License-Identifier: Apache-2.0
//
// Literal `RangeInclusive` endpoint accessors.
//
// `RangeInclusive::{start,end}` returns shared references to the written endpoints.  For an
// inline inclusive range whose selected endpoint digs to a concrete integer literal, this is
// value sugar: lower to `ref(<endpoint>)` so the existing unary deref rule can reduce
// `*(a..=b).start()` / `*(a..=b).end()` to the literal floor. Recognition is deliberately
// syntactic and lazy: it only captures the raw receiver, and the endpoint child is built here
// in `desugar`, where the live binding context is available.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, RangeLimits};

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
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
    Some(Box::new(RangeAccessorSugar {
        kind,
        receiver: call.receiver.as_ref().clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

#[derive(Clone, Copy)]
enum EndpointKind {
    Start,
    End,
}

struct RangeAccessorSugar {
    kind: EndpointKind,
    receiver: Expr,
    let_inits: BTreeMap<String, Expr>,
}

impl Sugar for RangeAccessorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let Expr::Range(range) = strip_refs_groups(&self.receiver) else {
            return Outcome::from_opt(None);
        };
        if !matches!(range.limits, RangeLimits::Closed(_)) {
            return Outcome::from_opt(None);
        }
        let endpoint = match self.kind {
            EndpointKind::Start => range.start.as_deref(),
            EndpointKind::End => range.end.as_deref(),
        };
        let Some(endpoint) = endpoint else {
            return Outcome::from_opt(None);
        };
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let endpoint = match build_term(endpoint, &fcx).desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(effect) => return Outcome::Hit(effect),
        };
        if const_fold_int_term(&endpoint).is_none() {
            return Outcome::from_opt(None);
        }
        Outcome::Dug(Desugared::Term(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![endpoint],
        })))
    }
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}
