// SPDX-License-Identifier: Apache-2.0
//
// `NonZeroSugar`: `NonZero::<T>::new(literal)` and `.get()` over a NonZero-derived
// literal are stdlib value sugar. They are structural wrappers around the integer
// value, with `new(0)` represented as `Option::None`.

use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Term};
use syn::{Expr, ExprPath, PathArguments, Type};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::int_sqrt::term_as_int;
use crate::sugar::monadic::{none_term, some_term};
use crate::{const_fold_u128_term, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const NEW_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("nonzero_new", SugarRole::Term, recognize_new);

pub(crate) const ASSOC_CONST_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "nonzero_assoc_const",
    SugarRole::Term,
    recognize_assoc_const,
);

pub(crate) const GET_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("nonzero_get", SugarRole::Term, recognize_get);

fn recognize_assoc_const(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Path(path) = expr else {
        return None;
    };
    nonzero_assoc_const_path(path)?;
    Some(Box::new(NonZeroAssocConstSugar { expr: expr.clone() }))
}

fn recognize_new(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 || !is_nonzero_new_func(&call.func) {
        return None;
    }
    Some(Box::new(NonZeroNewSugar {
        value: build_term(&call.args[0], fcx),
    }))
}

fn recognize_get(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "get" || !call.args.is_empty() || !is_nonzero_derived(&call.receiver) {
        return None;
    }
    Some(Box::new(NonZeroGetSugar {
        receiver: build_term(&call.receiver, fcx),
    }))
}

struct NonZeroAssocConstSugar {
    expr: Expr,
}

impl Sugar for NonZeroAssocConstSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        let Expr::Path(path) = &self.expr else {
            return Outcome::from_opt(None);
        };
        let Some((kind, konst)) = nonzero_assoc_const_path(path) else {
            return Outcome::from_opt(None);
        };
        let Some(term) = nonzero_assoc_const_term(kind, &konst) else {
            return Outcome::from_opt(None);
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::nonzero",
            konst = konst.as_str(),
            "resolved NonZero associated constant axiom"
        );
        Outcome::Dug(Desugared::Term(term))
    }
}

struct NonZeroNewSugar {
    value: Box<dyn Sugar>,
}

impl Sugar for NonZeroNewSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let value = match self.value.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let Some(is_zero) = nonzero_scalar_is_zero(&value) else {
            return Outcome::from_opt(None);
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::nonzero",
            is_some = !is_zero,
            "resolved NonZero::new stdlib axiom"
        );
        let term = if is_zero {
            none_term()
        } else {
            some_term(value)
        };
        Outcome::Dug(Desugared::Term(term))
    }
}

fn nonzero_scalar_is_zero(term: &Rc<Term>) -> Option<bool> {
    nonzero_scalar_codepoint(term).map(|n| n == 0).or_else(|| {
        let value = const_fold_u128_term(term)?;
        Some(value == 0)
    })
}

fn nonzero_scalar_codepoint(term: &Rc<Term>) -> Option<i128> {
    term_as_int(term).or_else(|| char_literal_codepoint(term))
}

fn char_literal_codepoint(term: &Rc<Term>) -> Option<i128> {
    let Term::Const {
        value: ConstValue::String(value),
        sort,
    } = term.as_ref()
    else {
        return None;
    };
    if sort.name != "String" {
        return None;
    }
    let mut chars = value.chars();
    let ch = chars.next()?;
    chars.next().is_none().then_some(i128::from(u32::from(ch)))
}

struct NonZeroGetSugar {
    receiver: Box<dyn Sugar>,
}

impl Sugar for NonZeroGetSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let Some(value) = unwrap_some(&receiver).or_else(|| {
            if term_as_int(&receiver).is_some() || const_fold_u128_term(&receiver).is_some() {
                Some(Rc::clone(&receiver))
            } else {
                None
            }
        }) else {
            return Outcome::from_opt(None);
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::nonzero",
            "resolved NonZero::get stdlib axiom to inner literal"
        );
        Outcome::Dug(Desugared::Term(value))
    }
}

pub(crate) fn is_nonzero_new_call(expr: &Expr) -> bool {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return false;
    };
    is_nonzero_new_func(&call.func)
}

#[derive(Clone, Copy)]
pub(crate) struct NonZeroIntegerKind {
    pub(crate) signed: bool,
    pub(crate) bits: u32,
}

pub(crate) fn nonzero_assoc_const_expr(expr: &Expr) -> Option<(NonZeroIntegerKind, String)> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    nonzero_assoc_const_path(path)
}

pub(crate) fn nonzero_assoc_const_path(path: &ExprPath) -> Option<(NonZeroIntegerKind, String)> {
    let konst = path.path.segments.last()?.ident.to_string();
    if !matches!(konst.as_str(), "MIN" | "MAX" | "BITS") {
        return None;
    }
    let ty = if let Some(qself) = &path.qself {
        nonzero_kind_from_type(&qself.ty)?
    } else {
        let ty_segment = path.path.segments.iter().rev().nth(1)?;
        nonzero_kind_from_segment(ty_segment)?
    };
    Some((ty, konst))
}

fn nonzero_assoc_const_term(kind: NonZeroIntegerKind, konst: &str) -> Option<Rc<Term>> {
    let value = match konst {
        "BITS" => return Some(crate::num(i128::from(kind.bits))),
        "MIN" if kind.signed => signed_bounds(kind.bits)?.0,
        "MIN" => 1,
        "MAX" if kind.signed => signed_bounds(kind.bits)?.1,
        "MAX" => {
            let max = unsigned_max(kind.bits)?;
            return Some(unsigned_term(max, kind.bits));
        }
        _ => return None,
    };
    Some(crate::num(value))
}

fn nonzero_kind_from_type(ty: &Type) -> Option<NonZeroIntegerKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    let segment = path.path.segments.last()?;
    nonzero_kind_from_segment(segment)
}

fn nonzero_kind_from_segment(segment: &syn::PathSegment) -> Option<NonZeroIntegerKind> {
    let ident = segment.ident.to_string();
    if ident == "NonZero" {
        let PathArguments::AngleBracketed(args) = &segment.arguments else {
            return None;
        };
        return args.args.iter().find_map(|arg| match arg {
            syn::GenericArgument::Type(ty) => primitive_kind_from_type(ty),
            _ => None,
        });
    }
    ident
        .strip_prefix("NonZero")
        .map(|suffix| suffix.to_ascii_lowercase())
        .and_then(|suffix| primitive_kind(&suffix))
}

fn primitive_kind_from_type(ty: &Type) -> Option<NonZeroIntegerKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    primitive_kind(&path.path.segments.last()?.ident.to_string())
}

fn primitive_kind(name: &str) -> Option<NonZeroIntegerKind> {
    let (signed, bits) = match name {
        "i8" => (true, 8),
        "i16" => (true, 16),
        "i32" => (true, 32),
        "i64" => (true, 64),
        "i128" => (true, 128),
        "isize" => (true, usize::BITS),
        "u8" => (false, 8),
        "u16" => (false, 16),
        "u32" => (false, 32),
        "u64" => (false, 64),
        "u128" => (false, 128),
        "usize" => (false, usize::BITS),
        _ => return None,
    };
    Some(NonZeroIntegerKind { signed, bits })
}

fn signed_bounds(bits: u32) -> Option<(i128, i128)> {
    if bits == 128 {
        Some((i128::MIN, i128::MAX))
    } else {
        let max = (1i128.checked_shl(bits - 1)?).checked_sub(1)?;
        Some((-max - 1, max))
    }
}

fn unsigned_max(bits: u32) -> Option<u128> {
    if bits == 128 {
        Some(u128::MAX)
    } else {
        (1u128.checked_shl(bits)?).checked_sub(1)
    }
}

fn unsigned_term(value: u128, bits: u32) -> Rc<Term> {
    if bits == 128 {
        crate::u128_term(value)
    } else {
        crate::num(i128::try_from(value).expect("non-u128 unsigned max fits i128"))
    }
}

fn is_nonzero_new_func(func: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return false;
    };
    if path.qself.is_some() || path.path.segments.len() < 2 {
        return false;
    }
    let mut segments = path.path.segments.iter().rev();
    let Some(method) = segments.next() else {
        return false;
    };
    let Some(ty) = segments.next() else {
        return false;
    };
    method.ident == "new" && ty.ident.to_string().starts_with("NonZero")
}

fn is_nonzero_derived(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Call(_) => is_nonzero_new_call(expr),
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "expect" | "unwrap" | "isqrt" | "checked_isqrt" | "get"
            ) =>
        {
            is_nonzero_derived(&call.receiver)
        }
        _ => false,
    }
}

fn unwrap_some(term: &Rc<Term>) -> Option<Rc<Term>> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == crate::sugar::monadic::OPT_SOME && args.len() == 1 => {
            Some(Rc::clone(&args[0]))
        }
        _ => None,
    }
}
