// SPDX-License-Identifier: Apache-2.0
//
// Sugar for unsafe-memory writes. `clone_to_uninit` mutates raw / MaybeUninit
// storage, so a value flowing through it is not a timeless construction from
// source literals. The method call owns the typed boundary; enclosing blocks only
// bubble this effect.

use syn::Expr;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("unsafe_memory", SugarRole::Term, recognize);

pub(crate) const STATEMENT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "statement_unsafe_memory",
    SugarRole::StatementEffect,
    recognize,
);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    is_unsafe_memory_method(&call.method).then(|| {
        Box::new(UnsafeMemorySugar {
            boundary: token_key(expr),
        }) as Box<dyn Sugar>
    })
}

fn is_unsafe_memory_method(method: &syn::Ident) -> bool {
    method == "clone_to_uninit"
}

struct UnsafeMemorySugar {
    boundary: String,
}

impl Sugar for UnsafeMemorySugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::RuntimeExprStmt {
            boundary: self.boundary.clone(),
        })
    }
}
