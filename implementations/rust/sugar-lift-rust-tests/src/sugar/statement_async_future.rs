// SPDX-License-Identifier: Apache-2.0
//
// Statement-position dormant async-future sugar.
//
// `let fut = async { assert_ok!(...) };` constructs a future. It does not execute the
// assertion vocabulary inside that future at the `let` site. The assertion becomes
// meaningful only when a driver consumes the future (`join!`, `spawn`, `block_on`, ...),
// and those driver semantics must be learned from source/proof. This sugar owns the
// factory-level accounting for the dormant construction so it does not fall into the
// generic let-initializer bucket.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::{count_asserts_in_stmts, token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::statement_effect("statement_async_future", recognize);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Async(async_expr) = expr else {
        return None;
    };
    (count_asserts_in_stmts(&async_expr.block.stmts) > 0).then(|| {
        Box::new(StatementAsyncFutureSugar {
            boundary: token_key(expr),
        }) as Box<dyn Sugar>
    })
}

struct StatementAsyncFutureSugar {
    boundary: String,
}

impl Sugar for StatementAsyncFutureSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::DormantFuture {
            boundary: self.boundary.clone(),
        })
    }
}
