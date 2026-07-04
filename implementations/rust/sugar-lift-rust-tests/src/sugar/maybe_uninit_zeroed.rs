// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizers for the all-zeros bit-pattern constructors.
//
// Covered patterns
// ────────────────
//   (A) `MaybeUninit::<T>::zeroed().assume_init()`
//   (B) `core::mem::zeroed::<T>()` / `std::mem::zeroed::<T>()` /
//       `mem::zeroed::<T>()`
//
// For types where all-zeros is a determinate valid value (primitive integers
// and `bool`), the sugar completes to the zero constant at desugar time —
// giving z3 TEETH: `MaybeUninit::<u32>::zeroed().assume_init() == 1` becomes
// UNSAT.
//
// Finite-or-refuse: for types where all-zeros is UB or indeterminate
// (`NonZero*`, references, raw pointers, user-defined structs, ...) the recognizer
// emits a named refusal. It never fabricates a zero and never falls through to an
// opaque generic sugar after recognizing the zeroed shape.
//
// Ambiguity guard
// ───────────────
// Pattern (A) fires only on the two-call chain
//   `assume_init()` over `MaybeUninit::<T>::zeroed()`.
// No other current Term recognizer in the catalog fires on that exact shape.
//
// Pattern (B) fires only on `Expr::Call` whose func ends in `mem::zeroed`
// with an explicit type argument. It declares it comes before `call`, the generic
// gravitational well for call terms.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, GenericArgument, PathArguments, Type};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{bool_const, num, strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

// ── (A) MaybeUninit::<T>::zeroed().assume_init() ─────────────────────────────

pub(crate) const ASSUME_INIT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "maybe_uninit_zeroed",
    &["method"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            use std::mem::MaybeUninit;

            #[test]
            fn t_maybe_uninit_zeroed_good() {
                let got = unsafe { MaybeUninit::<u32>::zeroed().assume_init() };
                assert_eq!(got, 0);
            }
        "#,
        r#"
            use std::mem::MaybeUninit;

            #[test]
            fn t_maybe_uninit_zeroed_bad() {
                let got = unsafe { MaybeUninit::<u32>::zeroed().assume_init() };
                assert_eq!(got, 1);
            }
        "#,
    ),
    recognize_assume_init,
);

fn recognize_assume_init(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    // Outer must be `.assume_init()` with no extra arguments.
    let Expr::MethodCall(outer) = expr else {
        return None;
    };
    if outer.method != "assume_init" || !outer.args.is_empty() {
        return None;
    }
    // Receiver must be `MaybeUninit::<T>::zeroed()`.
    let ty = maybe_uninit_zeroed_type(&outer.receiver)?;
    Some(Box::new(ZeroedSugar { ty }))
}

/// Return `T` for `MaybeUninit::<T>::zeroed()`, or `None` if the receiver is not that shape.
fn maybe_uninit_zeroed_type(expr: &Expr) -> Option<Type> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    // `zeroed()` takes no arguments.
    if !call.args.is_empty() {
        return None;
    }
    // func must be a path ending in `MaybeUninit::<T>::zeroed`.
    let Expr::Path(path_expr) = strip_refs_groups(&call.func) else {
        return None;
    };
    if path_expr.qself.is_some() {
        return None;
    }
    let segs = &path_expr.path.segments;
    if segs.len() < 2 {
        return None;
    }
    let last = segs.last().unwrap();
    let second_last = &segs[segs.len() - 2];
    if last.ident != "zeroed" || second_last.ident != "MaybeUninit" {
        return None;
    }
    // Type T comes from the angle brackets on the `MaybeUninit` segment:
    // `MaybeUninit::<T>`.
    angle_bracket_type_arg(&second_last.arguments)
}

// ── (B) mem::zeroed::<T>() ───────────────────────────────────────────────────

pub(crate) const MEM_ZEROED_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "mem_zeroed",
    &["call"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_mem_zeroed_good() {
                let got = unsafe { std::mem::zeroed::<u32>() };
                assert_eq!(got, 0);
            }
        "#,
        r#"
            #[test]
            fn t_mem_zeroed_bad() {
                let got = unsafe { std::mem::zeroed::<u32>() };
                assert_eq!(got, 1);
            }
        "#,
    ),
    recognize_mem_zeroed,
);

fn recognize_mem_zeroed(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Call(call) = expr else {
        return None;
    };
    // `zeroed::<T>()` takes no arguments.
    if !call.args.is_empty() {
        return None;
    }
    let ty = mem_zeroed_type(&call.func)?;
    Some(Box::new(ZeroedSugar { ty }))
}

/// Return `T` for `mem::zeroed::<T>()` / `core::mem::zeroed::<T>()`, or `None` if the func is not that shape.
fn mem_zeroed_type(func: &Expr) -> Option<Type> {
    let Expr::Path(path_expr) = strip_refs_groups(func) else {
        return None;
    };
    if path_expr.qself.is_some() {
        return None;
    }
    let segs = &path_expr.path.segments;
    if segs.is_empty() {
        return None;
    }
    let last = segs.last().unwrap();
    if last.ident != "zeroed" {
        return None;
    }
    // Require at least two segments so a bare `zeroed::<T>()` (without a `mem`
    // module prefix) is NOT accepted — too ambiguous without the module context.
    if segs.len() < 2 {
        return None;
    }
    let second_last = &segs[segs.len() - 2];
    if second_last.ident != "mem" {
        return None;
    }
    // Type T comes from the turbofish on the `zeroed` segment: `zeroed::<T>`.
    angle_bracket_type_arg(&last.arguments)
}

// ── Shared helpers ────────────────────────────────────────────────────────────

/// Extract the first `Type` argument from an `AngleBracketed` path segment
/// (e.g. `<u32>` in `MaybeUninit::<u32>` or `zeroed::<u32>`).
fn angle_bracket_type_arg(args: &PathArguments) -> Option<Type> {
    let PathArguments::AngleBracketed(ab) = args else {
        return None;
    };
    ab.args.iter().find_map(|a| {
        if let GenericArgument::Type(ty) = a {
            Some(ty.clone())
        } else {
            None
        }
    })
}

/// Map a primitive type name to its all-zeros value term.
///
/// * Primitive integers (`u8`…`u128`, `usize`, `i8`…`i128`, `isize`) →
///   `num(0)` (the plain unsorted integer zero, same sort as unsuffixed `0`
///   literals and `u32::MIN` / `i64::MIN` from `const_path`).
/// * `bool` → `bool_const(false)` (all-zeros bit-pattern for bool is `false`).
/// * Everything else (`NonZero*`, references, raw pointers, structs, ...) ->
///   `None` (finite-or-refuse: never fabricate a zero for these types).
fn primitive_zero_term(ty: &Type) -> Option<Rc<Term>> {
    let Type::Path(tp) = ty else {
        return None;
    };
    if tp.qself.is_some() {
        return None;
    }
    match tp.path.get_ident()?.to_string().as_str() {
        "u8" | "u16" | "u32" | "u64" | "u128" | "usize" | "i8" | "i16" | "i32" | "i64" | "i128"
        | "isize" => Some(num(0)),
        "bool" => Some(bool_const(false)),
        _ => None,
    }
}

struct ZeroedSugar {
    ty: Type,
}

impl Sugar for ZeroedSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if let Some(term) = primitive_zero_term(&self.ty) {
            return Outcome::Complete(Desugared::Term(term));
        }

        let ty = quote::ToTokens::to_token_stream(&self.ty).to_string();
        Outcome::Incomplete(Effect::InvalidBitPattern {
            reason: format!(
                "all-zeros bit-pattern is not a determinate valid value for `{ty}`; refused"
            ),
        })
    }
}
