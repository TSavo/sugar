// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::RawAddr` (`&raw const x` / `&raw mut x`): a raw pointer
// -> reasoned Hit. Byte-identical to the `Expr::RawAddr` arm of the old fat factory.

use crate::sugar::factory::FactoryCtx;
use crate::sugar::term_leaf::reasoned_hit;
use crate::{token_key, Effect, Sugar, UnsupportedTermCause};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("raw_addr_term", recognize);

/// TERM recognizer for `Expr::RawAddr`.
pub(crate) fn recognize(expr: &Expr, _fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::RawAddr(_) => {
            let effect =
                Effect::unsupported_term(&token_key(expr), UnsupportedTermCause::RawPointer);
            Some(reasoned_hit(effect.reason()))
        }
        _ => None,
    }
}
