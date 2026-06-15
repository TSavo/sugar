// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Cast` (`x as T`): a shared `dyn Any` cast or a scalar
// cast -> `cast:<T>` ctor over the child; any other cast -> reasoned Hit. Byte-
// identical to the `Expr::Cast` arm of the old fat factory.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, FactoryCtx};
use crate::sugar::term_leaf::reasoned_hit;
use crate::{is_shared_dyn_any_type, scalar_cast_type_key, token_key, type_key, Sugar};
use syn::Expr;

/// TERM recognizer for `Expr::Cast`.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Cast(cast) = expr else {
        return None;
    };
    if is_shared_dyn_any_type(&cast.ty) {
        return Some(Box::new(CtorSugar::new(
            format!("cast:{}", type_key(&cast.ty)),
            vec![build_term(&cast.expr, fcx)],
        )));
    }
    if let Some(cast_type) = scalar_cast_type_key(&cast.ty) {
        return Some(Box::new(CtorSugar::new(
            format!("cast:{cast_type}"),
            vec![build_term(&cast.expr, fcx)],
        )));
    }
    Some(reasoned_hit(format!(
        "unsupported term `{}`",
        token_key(expr)
    )))
}
