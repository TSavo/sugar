// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for the VALUE-TRANSPARENT blocks `Expr::Unsafe` (`unsafe { expr }`)
// and `Expr::Block` (`{ expr }`): a single-tail block is the value of its tail (recurse
// through `build_term`); any other block shape is refused by name. Byte-identical to
// the `Expr::Unsafe`/`Expr::Block` arms of the old fat factory.

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::reasoned_hit;
use crate::sugar::unsafe_memory;
use crate::{token_key, Sugar};
use syn::{Expr, Stmt};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("block_term", recognize);

/// TERM recognizer for `Expr::Unsafe` / `Expr::Block`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Unsafe(block) => Some(match block.block.stmts.as_slice() {
            [Stmt::Expr(tail, None)] => build_term(tail, fcx),
            stmts if unsafe_memory::unsafe_memory_boundary_stmts(stmts) => {
                reasoned_hit(unsafe_memory::runtime_memory_reason(&token_key(expr)))
            }
            _ => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
        }),
        Expr::Block(block) => Some(match block.block.stmts.as_slice() {
            [Stmt::Expr(tail, None)] => build_term(tail, fcx),
            _ => reasoned_hit(format!("unsupported term `{}`", token_key(expr))),
        }),
        _ => None,
    }
}
