// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `reference_sequence`: a finite literal sequence in REFERENCE / IntoIterator position
// -- a `&<array>` (or `&name` resolving to a literal array) used directly as an iterator
// domain, e.g. the `&ys` RHS of `xs.iter().chain(&ys)` or `for &x in &ys`. Casted slice
// references such as `&mut [1, 2] as &mut [_]` are the same composite floor: the cast is
// only the Rust surface type boundary, not sequence semantics. The factory
// otherwise reaches the literal-sequence recognition (`build_literal_sequence_composite`)
// ONLY through the explicit `.iter()`-family adaptor (`iterator.rs`) or an array literal;
// a bare reference (implicitly `IntoIterator`, no `.iter()`) matches no recognizer, so
// `has_composite(&ys)` was false and consumers had to reach PAST the factory to the helper.
// This makes that recognition first-class for the reference position, so every adaptor
// (`chain`/`zip`/...) and the `for`-loop domain gate see `&ys` as a composite uniformly.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family::build_literal_sequence_composite;
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

// GENERAL "reference to a literal sequence" catch. A `&[1, 2, 3]`
// reference-to-slice-literal is also claimed by the specific `literal_slice`
// recognizer. `literal_slice` declares it comes before this gravitational well, so
// the catalog never relies on incidental order to select the narrower owner.
pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_composite(
        "reference_sequence",
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S5/S6 iterator/reference sequence standing",
        ),
        recognize_composite,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    // Narrow to reference-shaped wrappers: array/range literals and `.iter()`-family
    // calls keep their own specific recognizers; only the reference position is claimed.
    // `build_literal_sequence_composite` returns `None` for a non-literal referent (e.g.
    // `&mut runtime`), so the factory falls through for anything that is not a finite
    // literal sequence -- no new domain is admitted.
    let source = match expr {
        Expr::Reference(reference) => reference.expr.as_ref(),
        Expr::Cast(cast) => match cast.expr.as_ref() {
            Expr::Reference(reference) => reference.expr.as_ref(),
            _ => return None,
        },
        _ => return None,
    };
    build_literal_sequence_composite(source, fcx)
}
