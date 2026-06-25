// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Const` (`const { EXPR }`). A const block translates
// its expression-only tail and scopes its locals; bare paths recurse into the
// ordinary term catalog, where `ConstSugar`, `UnitPathSugar`, or `PathSugar` own
// the source meaning.

use crate::sugar::block_term::translate_expression_only_block_in_scope;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::unit_path::{unit_path_literal_name, unit_path_name};
use crate::{make_var, scope_const_block_locals, token_key, Desugared, Outcome, Sugar, SugarCtx};
use syn::{Expr, Stmt};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("const_block", recognize);

/// TERM recognizer for `Expr::Const`.
pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Const(const_block) = expr else {
        return None;
    };
    Some(Box::new(ConstBlockSugar {
        block: const_block.block.clone(),
        site: token_key(expr),
    }))
}

struct ConstBlockSugar {
    block: syn::Block,
    site: String,
}

impl Sugar for ConstBlockSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let [Stmt::Expr(Expr::Path(path), None)] = self.block.stmts.as_slice() {
            if path.qself.is_none() {
                if let Some(name) = unit_path_name(&path.path) {
                    return Outcome::Complete(Desugared::Term(make_var(unit_path_literal_name(
                        &name,
                    ))));
                }
                if ctx.scope.const_expr_for_path(&path.path).is_none() {
                    panic!("unsupported term `{}`", self.site);
                }
            }
        }

        match translate_expression_only_block_in_scope(&self.block, "const", ctx.scope) {
            Ok(term) => Outcome::Complete(Desugared::Term(scope_const_block_locals(
                term,
                ctx.scope.local_scope(),
            ))),
            Err(reason) => panic!("{reason}"),
        }
    }
}
