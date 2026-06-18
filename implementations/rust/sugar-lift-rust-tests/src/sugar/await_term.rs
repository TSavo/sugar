// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Await` (`base.await`): the `await` ctor over the base
// child. Byte-identical to the `Expr::Await` arm of the old fat factory.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::Sugar;
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("await_term", recognize);

/// TERM recognizer for `Expr::Await`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Await(await_expr) => Some(Box::new(CtorSugar::new(
            "await",
            vec![build_term(&await_expr.base, fcx)],
        ))),
        _ => None,
    }
}
