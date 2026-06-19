// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Cast` (`x as T`): an inferred target (`as _`) is
// compiler type inference and therefore transparent; raw-pointer target casts are
// refused as provenance/address boundaries; a shared `dyn Any` cast or a scalar cast
// -> `cast:<T>` ctor over the child; any other cast -> reasoned Hit.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::reasoned_hit;
use crate::{
    is_shared_dyn_any_type, scalar_cast_type_key, token_key, type_key, Effect, Sugar,
    UnsupportedTermCause,
};
use syn::{Expr, Type};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("cast_term", recognize);

/// TERM recognizer for `Expr::Cast`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Cast(cast) = expr else {
        return None;
    };
    if matches!(cast.ty.as_ref(), Type::Infer(_)) {
        return Some(build_term(&cast.expr, fcx));
    }
    if matches!(cast.ty.as_ref(), Type::Ptr(_)) {
        let effect =
            Effect::unsupported_term(&token_key(expr), UnsupportedTermCause::RawPointerCast);
        return Some(reasoned_hit(effect.reason()));
    }
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
