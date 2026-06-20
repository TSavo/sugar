// SPDX-License-Identifier: Apache-2.0
//
// `for <var> in <literal-domain>` bounded universal sugar.

use syn::Expr;

use crate::sugar::backstop::boxed;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::forall;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::secondary_composite("forall_loop", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::ForLoop(f) => Some(boxed(forall::decompose_for_loop(
            f,
            fcx.scope(),
            fcx.let_inits(),
            fcx,
        ))),
        _ => None,
    }
}
