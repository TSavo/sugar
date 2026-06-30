// SPDX-License-Identifier: Apache-2.0
//
// `.for_each(|var| body)` bounded universal sugar.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::forall;
use crate::Sugar;
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("for_each", recognize);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::MethodCall(_) => forall::decompose_for_each(expr, fcx.let_inits(), fcx)
            .map(|node| Box::new(node) as Box<dyn Sugar>),
        _ => None,
    }
}
