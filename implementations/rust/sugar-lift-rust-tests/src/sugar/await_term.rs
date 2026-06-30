// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Await` (`base.await`): the `await` ctor over the already
// constructed base child. The parent node is born with its body Sugar; desugar never
// goes back to the factory through a raw child expression.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::Sugar;
use syn::Expr;
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("await_term", recognize);

/// TERM recognizer for `Expr::Await`.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::Await(await_expr) => Some(Box::new(CtorSugar::new(
            "await",
            vec![SugarBody::term(&await_expr.base, fcx)],
        ))),
        _ => None,
    }
}
