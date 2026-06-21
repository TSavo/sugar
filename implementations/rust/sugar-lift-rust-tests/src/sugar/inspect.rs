// SPDX-License-Identifier: Apache-2.0
//
// `inspect`: the `.inspect(f)` adaptor. `Iterator::inspect` yields the SAME items in
// the SAME order -- the closure receives `&Item` and CANNOT alter the value stream
// (its side effect is irrelevant to the asserted values). So over a finite literal
// sequence it is the IDENTITY adaptor: it reuses `IdentitySugar` over the receiver's
// composite. This is the outermost-call recognizer; `peel_fold_adaptors` carries the
// same identity treatment when `.inspect(..)` sits inside a longer adaptor chain.

use syn::Expr;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::identity::IdentitySugar;
use crate::sugar::method_family;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("inspect", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "inspect"
        && call.args.len() == 1
        && method_family::resolves_literal_sequence(expr, fcx.let_inits())
    {
        return Some(Box::new(IdentitySugar {
            inner: build_composite(&call.receiver, fcx),
        }));
    }
    None
}
