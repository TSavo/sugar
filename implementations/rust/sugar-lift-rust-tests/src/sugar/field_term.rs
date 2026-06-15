// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Field` (`base.member`): the `field:<member>` ctor over
// the base child. Byte-identical to the `Expr::Field` arm of the old fat factory.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, FactoryCtx};
use crate::{token_key, Sugar};
use syn::Expr;

/// TERM recognizer for `Expr::Field`.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Field(field) => Some(Box::new(CtorSugar::new(
            format!("field:{}", token_key(&field.member)),
            vec![build_term(&field.base, fcx)],
        ))),
        _ => None,
    }
}
