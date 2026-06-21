// SPDX-License-Identifier: Apache-2.0
//
// `from_bool`: `<IntT>::from(<bool literal>)` / `IntT::from(<bool literal>)` for a
// primitive INTEGER target type folds to the std `From<bool>` value -- `true -> 1`,
// `false -> 0`. The compiler owns this conversion: `From<bool>` is implemented in std
// ONLY for the integer types (i8..=i128, u8..=u128, isize, usize) with the fixed
// {true->1, false->0} mapping. With a bool-literal argument, overload resolution makes
// `<IntT>::from(bool)` unambiguously `From<bool>::from`, so the target integer type
// alone determines the 1/0 value (any `as Trait` qualifier cannot change it).
//
// We read it out only when the target is a KNOWN primitive integer and the argument is
// a bool literal. A non-integer target (a user type's `From<bool>` could map `true` to
// any value -- no determinate result), a float / `char` target (no std `From<bool>`),
// or a non-literal argument DECLINES, staying the opaque `call:from(..)` fallback.
// EXACT-OR-NONE: a wrong value would be a false discharge, so when in doubt, decline.

use syn::{Expr, Lit, PathArguments, Type};

use sugar_ir_symbolic::num;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::resolved_term;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("from_bool", recognize);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let Expr::Lit(lit) = &call.args[0] else {
        return None;
    };
    let Lit::Bool(b) = &lit.lit else {
        return None;
    };
    if !is_primitive_int_from(&call.func) {
        return None;
    }
    // std `From<bool>` for an integer: true -> 1, false -> 0.
    Some(resolved_term(num(if b.value { 1 } else { 0 })))
}

/// `<IntT>::from` (qself) or `IntT::from` (two-segment path) where `IntT` is a known
/// primitive integer type. Anything else (a user type, a float, `char`, a longer
/// path) is NOT a std `From<bool>` with the fixed 1/0 mapping and is declined.
fn is_primitive_int_from(func: &Expr) -> bool {
    let Expr::Path(path) = func else {
        return false;
    };
    let Some(last) = path.path.segments.last() else {
        return false;
    };
    if last.ident != "from" || !matches!(last.arguments, PathArguments::None) {
        return false;
    }
    if let Some(qself) = &path.qself {
        // `<IntT>::from(..)` or `<IntT as From<bool>>::from(..)`: the receiver type is
        // the qself. With a bool-literal argument the resolved `from` is necessarily
        // `From<bool>::from`, so the target type alone determines the 1/0 value.
        return type_is_primitive_int(&qself.ty);
    }
    // `IntT::from(..)`: a plain two-segment path `[IntT, from]`, no generics on `IntT`.
    path.path.segments.len() == 2
        && matches!(path.path.segments[0].arguments, PathArguments::None)
        && is_primitive_int_name(&path.path.segments[0].ident.to_string())
}

fn type_is_primitive_int(ty: &Type) -> bool {
    let Type::Path(path) = ty else {
        return false;
    };
    if path.qself.is_some() {
        return false;
    }
    match path.path.segments.last() {
        Some(seg) => {
            matches!(seg.arguments, PathArguments::None)
                && is_primitive_int_name(&seg.ident.to_string())
        }
        None => false,
    }
}

fn is_primitive_int_name(name: &str) -> bool {
    matches!(
        name,
        "i8" | "i16"
            | "i32"
            | "i64"
            | "i128"
            | "isize"
            | "u8"
            | "u16"
            | "u32"
            | "u64"
            | "u128"
            | "usize"
    )
}
