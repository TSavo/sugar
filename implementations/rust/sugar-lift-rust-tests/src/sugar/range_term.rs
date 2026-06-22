// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Range` (`a..b` / `a..=b`): `range`/`range_incl` over
// start (or `0`) and end (or `range_end_len`). Byte-identical to the `Expr::Range` arm
// of the old fat factory.

use std::collections::BTreeMap;

use sugar_ir_symbolic::{make_var, num};

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::resolved_term;
use crate::{Outcome, Sugar, SugarCtx};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("range_term", recognize);

/// TERM recognizer for `Expr::Range`.
pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Range(range) = expr else {
        return None;
    };
    let name = match range.limits {
        syn::RangeLimits::HalfOpen(_) => "range",
        syn::RangeLimits::Closed(_) => "range_incl",
    };
    Some(Box::new(RangeTermSugar {
        start: range.start.as_deref().cloned(),
        end: range.end.as_deref().cloned(),
        name,
    }))
}

struct RangeTermSugar {
    start: Option<Expr>,
    end: Option<Expr>,
    name: &'static str,
}

impl Sugar for RangeTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let let_inits = scope_let_inits(ctx);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let start: Box<dyn Sugar> = match &self.start {
            Some(expr) => build_term(expr, &fcx),
            None => resolved_term(num(0)),
        };
        let end: Box<dyn Sugar> = match &self.end {
            Some(expr) => build_term(expr, &fcx),
            None => resolved_term(make_var("range_end_len")),
        };
        CtorSugar::new(self.name, vec![start, end]).desugar(ctx)
    }
}

fn scope_let_inits<'a, 'c>(ctx: &SugarCtx<'a, 'c>) -> BTreeMap<String, &'a Expr> {
    ctx.scope
        .let_bindings_iter()
        .map(|(name, init)| (name.clone(), init))
        .collect()
}
