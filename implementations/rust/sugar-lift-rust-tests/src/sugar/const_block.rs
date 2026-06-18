// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Const` (`const { EXPR }`). A bare-path const block is a
// NAME (sugar) -> reasoned Hit; a computed const block translates its expression-only
// tail and scopes its locals. Byte-identical to the `Expr::Const` arm of the old fat
// factory.

use crate::sugar::factory::FactoryCtx;
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::{
    scope_const_block_locals, token_key, translate_expression_only_block_in_scope, Effect, Sugar,
    UnsupportedTermCause,
};
use syn::{Expr, Stmt};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("const_block", recognize);

/// TERM recognizer for `Expr::Const`.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Const(const_block) = expr else {
        return None;
    };
    let scope = fcx.scope;
    if let [Stmt::Expr(Expr::Path(_), None)] = const_block.block.stmts.as_slice() {
        let effect =
            Effect::unsupported_term(&token_key(expr), UnsupportedTermCause::ConstBlockPath);
        return Some(reasoned_hit(effect.reason()));
    }
    match translate_expression_only_block_in_scope(&const_block.block, "const", scope) {
        Ok(term) => Some(resolved_term(scope_const_block_locals(
            term,
            scope.local_scope(),
        ))),
        Err(reason) => Some(reasoned_hit(reason)),
    }
}
