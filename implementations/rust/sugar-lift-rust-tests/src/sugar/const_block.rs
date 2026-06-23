// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Const` (`const { EXPR }`). A const block translates
// its expression-only tail and scopes its locals; bare paths recurse into the
// ordinary term catalog, where `ConstSugar`, `UnitPathSugar`, or `PathSugar` own
// the source meaning.

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::{reasoned_incomplete, resolved_term};
use crate::sugar::unit_path::{unit_path_literal_name, unit_path_name};
use crate::{
    make_var, scope_const_block_locals, token_key, translate_expression_only_block_in_scope, Sugar,
};
use syn::{Expr, Stmt};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("const_block", recognize);

/// TERM recognizer for `Expr::Const`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Const(const_block) = expr else {
        return None;
    };
    let scope = fcx.scope();
    if let [Stmt::Expr(Expr::Path(path), None)] = const_block.block.stmts.as_slice() {
        if path.qself.is_none() {
            if let Some(name) = unit_path_name(&path.path) {
                return Some(resolved_term(make_var(unit_path_literal_name(&name))));
            }
            if scope.const_expr_for_path(&path.path).is_none() {
                return Some(reasoned_incomplete(format!(
                    "unsupported term `{}`",
                    token_key(expr)
                )));
            }
        }
    }
    match translate_expression_only_block_in_scope(&const_block.block, "const", scope) {
        Ok(term) => Some(resolved_term(scope_const_block_locals(
            term,
            scope.local_scope(),
        ))),
        Err(reason) => Some(reasoned_incomplete(reason)),
    }
}
