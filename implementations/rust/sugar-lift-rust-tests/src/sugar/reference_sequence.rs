// SPDX-License-Identifier: Apache-2.0
//
// `reference_sequence`: a finite literal sequence in REFERENCE / IntoIterator position
// -- a `&<array>` (or `&name` resolving to a literal array) used directly as an iterator
// domain, e.g. the `&ys` RHS of `xs.iter().chain(&ys)` or `for &x in &ys`. The factory
// otherwise reaches the literal-sequence recognition (`build_literal_sequence_composite`)
// ONLY through the explicit `.iter()`-family adaptor (`iterator.rs`) or an array literal;
// a bare reference (implicitly `IntoIterator`, no `.iter()`) matches no recognizer, so
// `has_composite(&ys)` was false and consumers had to reach PAST the factory to the helper.
// This makes that recognition first-class for the reference position, so every adaptor
// (`chain`/`zip`/...) and the `for`-loop domain gate see `&ys` as a composite uniformly.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family::build_literal_sequence_composite;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("reference_sequence", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Narrow to `Expr::Reference`: array/range literals and `.iter()`-family calls keep
    // their own specific recognizers; only the bare reference position is newly claimed.
    // `build_literal_sequence_composite` returns `None` for a non-literal referent (e.g.
    // `&mut runtime`), so the factory falls through for anything that is not a finite
    // literal sequence -- no new domain is admitted.
    let Expr::Reference(_) = expr else {
        return None;
    };
    build_literal_sequence_composite(expr, fcx)
}
