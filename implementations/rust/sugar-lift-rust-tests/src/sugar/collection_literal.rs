// SPDX-License-Identifier: Apache-2.0
//
// `collection_literal`: finite-collection CONSTRUCTORS over written literals --
// `vec![a, b, c]`, `Vec::from([a, b, c])` / `Vec::from(&[a, b, c])`, and
// `Box::new([a, b, c])` -- recognized as the literal sequence they construct. Each is
// value-identical to the array literal `[a, b, c]`, so it grounds to the SAME `Seq` floor
// (and element-wise teeth) `[a, b, c]` already does: the constructor is NORMALIZED to its
// equivalent array `Expr` and delegated to the shared `LiteralSugar`. No new element/length
// machinery -- the array path const-evaluates each element, so a non-literal element
// (`vec![compute(), 2]`) stays symbolic for that element (finite-or-refuse), exactly as a
// written `[compute(), 2]` would.
//
// SCOPE: the COMMA-LIST form only. `vec![x; n]` (the REPEAT form) is the array-repeat shape
// (`array_repeat`), not a written element list -- the `[#tokens]` normalization parses it as
// `Expr::Repeat` and so declines it here. Likewise `Vec::from(<runtime>)` /
// `Box::new(<runtime>)` (a non-array arg) is declined -- only a written array argument is a
// finite literal sequence.

use quote::quote;
use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::literal::LiteralSugar;
use crate::sugar::source_fragment::SourceFragment;
use crate::{strip_refs_groups, Sugar};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "collection_literal",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "owner-mismatch collection row: aggregate literal witnesses dispatch elsewhere",
        ),
        recognize_composite,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    _fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let array = collection_literal_array(expr)?;
    Some(Box::new(LiteralSugar { base: array }))
}

/// The equivalent array-literal `Expr` a finite-collection constructor builds, or `None`.
/// `vec![a, b, c]`, `Vec::from([a, b, c])` / `Vec::from(&[a, b, c])`, and
/// `Box::new([a, b, c])` construct exactly the array `[a, b, c]`; returning that array lets
/// the shared `LiteralSugar`, `is_literal_sequence_base`, and the static-length path treat
/// the constructor identically to a written array literal. The `vec![x; n]` repeat form
/// normalizes to `Expr::Repeat` and is declined (cardinality is the `array_repeat` shape,
/// not a written element list).
pub(crate) fn collection_literal_array(expr: &Expr) -> Option<Expr> {
    match strip_refs_groups(expr) {
        // `vec![a, b, c]` -- normalize the macro body to `[a, b, c]` and accept ONLY when it
        // is an array (the comma form). `vec![x; n]` normalizes to `Expr::Repeat` -> declined.
        Expr::Macro(m) if m.mac.path.segments.last().is_some_and(|s| s.ident == "vec") => {
            let tokens = &m.mac.tokens;
            let array: Expr = syn::parse2(quote!([#tokens])).ok()?;
            matches!(strip_refs_groups(&array), Expr::Array(_)).then_some(array)
        }
        // `Vec::from([a, b, c])` / `Vec::from(&[a, b, c])` and `Box::new([a, b, c])` --
        // the single argument IS the constructed array value.
        Expr::Call(call)
            if (is_vec_from_callee(&call.func) || is_box_new_callee(&call.func))
                && call.args.len() == 1 =>
        {
            let inner = strip_refs_groups(&call.args[0]);
            matches!(inner, Expr::Array(_)).then(|| inner.clone())
        }
        _ => None,
    }
}

/// `Vec::from` / `Vec::<T>::from` (the collection-from constructor claimed here). Matches the
/// final-segment ident `from` together with a `Vec` segment, so a qualified / turbofished path
/// (`std::vec::Vec::from`, `Vec::<i32>::from`) is recognized while an unrelated `from` is not.
fn is_vec_from_callee(func: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == "from")
        && path.path.segments.iter().any(|seg| seg.ident == "Vec")
}

/// `Box::new` / `std::boxed::Box::new` over a written array. The box changes storage, not
/// the finite literal sequence semantics owned by the array floor.
fn is_box_new_callee(func: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == "new")
        && path.path.segments.iter().any(|seg| seg.ident == "Box")
}
