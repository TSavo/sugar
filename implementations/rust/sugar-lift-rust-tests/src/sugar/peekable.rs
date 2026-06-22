// SPDX-License-Identifier: Apache-2.0
//
// `peekable`: the `.peekable()` adaptor. `Iterator::peekable` yields the SAME items in
// the SAME order -- it only ADDS `peek`/`next_if` capability; it never alters the value
// stream. So over a finite literal sequence it is the IDENTITY adaptor, reusing
// `IdentitySugar` over the receiver's composite. This is the outermost-call recognizer
// (so `build_composite([..].iter().peekable())` resolves); `peel_fold_adaptors` carries
// the same identity treatment when `.peekable()` sits inside a longer adaptor chain
// (e.g. the `while let next_if` rewrite's `<seq>.iter().peekable().take_while(..)`).

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::identity::IdentitySugar;
use crate::sugar::method_family;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("peekable", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "peekable" && call.args.is_empty() {
        return Some(Box::new(IdentitySugar {
            inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        }));
    }
    None
}
