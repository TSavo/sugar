// SPDX-License-Identifier: MIT OR Apache-2.0

use std::rc::Rc;

use syn::{Expr, ExprLit, ExprPath, Lit, UnOp};

use crate::sugar::factory::SugarBuildCtx;
use crate::{const_fold_int_term, const_fold_u128_term, strip_refs_groups, u128_term};
use sugar_ir_symbolic::{num, ConstValue, Sort, Term};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct IntKind {
    pub(crate) signed: bool,
    pub(crate) bits: u32,
    pub(crate) name: &'static str,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ExactInt {
    Signed(i128),
    Unsigned(u128),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct ExactIntSource {
    pub(crate) value: ExactInt,
    pub(crate) kind: Option<IntKind>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum NumericFloor {
    Untyped(i128),
    Typed { value: ExactInt, kind: IntKind },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum NumericSqrt {
    Root(NumericFloor),
    Negative,
}

pub(crate) trait NumericLiteralVisitor {
    type Output;

    fn visit_untyped(self, value: i128) -> Self::Output;
    fn visit_signed(self, value: i128, kind: IntKind) -> Self::Output;
    fn visit_unsigned(self, value: u128, kind: IntKind) -> Self::Output;
}

pub(crate) struct WrappingNegVisitor;

impl NumericLiteralVisitor for WrappingNegVisitor {
    type Output = Option<NumericFloor>;

    fn visit_untyped(self, value: i128) -> Self::Output {
        value.checked_neg().map(NumericFloor::Untyped)
    }

    fn visit_signed(self, value: i128, kind: IntKind) -> Self::Output {
        wrapping_neg_typed(ExactInt::Signed(value), kind)
    }

    fn visit_unsigned(self, value: u128, kind: IntKind) -> Self::Output {
        wrapping_neg_typed(ExactInt::Unsigned(value), kind)
    }
}

pub(crate) struct IsqrtVisitor;

impl NumericLiteralVisitor for IsqrtVisitor {
    type Output = Option<NumericSqrt>;

    fn visit_untyped(self, value: i128) -> Self::Output {
        match value.checked_isqrt() {
            Some(root) => Some(NumericSqrt::Root(NumericFloor::Untyped(root))),
            None => Some(NumericSqrt::Negative),
        }
    }

    fn visit_signed(self, value: i128, kind: IntKind) -> Self::Output {
        match value.checked_isqrt() {
            Some(root) => Some(NumericSqrt::Root(NumericFloor::Typed {
                value: ExactInt::Signed(root),
                kind,
            })),
            None => Some(NumericSqrt::Negative),
        }
    }

    fn visit_unsigned(self, value: u128, kind: IntKind) -> Self::Output {
        Some(NumericSqrt::Root(NumericFloor::Typed {
            value: ExactInt::Unsigned(value.isqrt()),
            kind,
        }))
    }
}

pub(crate) struct PowVisitor {
    pub(crate) exponent: u32,
}

impl NumericLiteralVisitor for PowVisitor {
    type Output = Option<NumericFloor>;

    fn visit_untyped(self, value: i128) -> Self::Output {
        value.checked_pow(self.exponent).map(NumericFloor::Untyped)
    }

    fn visit_signed(self, value: i128, kind: IntKind) -> Self::Output {
        let result = value.checked_pow(self.exponent)?;
        let exact = ExactInt::Signed(result);
        exact
            .fits_kind(kind)
            .then_some(NumericFloor::Typed { value: exact, kind })
    }

    fn visit_unsigned(self, value: u128, kind: IntKind) -> Self::Output {
        let result = value.checked_pow(self.exponent)?;
        let exact = ExactInt::Unsigned(result);
        exact
            .fits_kind(kind)
            .then_some(NumericFloor::Typed { value: exact, kind })
    }
}

pub(crate) struct MidpointVisitor {
    pub(crate) rhs: NumericFloor,
    pub(crate) kind: IntKind,
}

impl NumericLiteralVisitor for MidpointVisitor {
    type Output = Option<NumericFloor>;

    fn visit_untyped(self, value: i128) -> Self::Output {
        midpoint_for_kind(NumericFloor::Untyped(value), self.rhs, self.kind)
    }

    fn visit_signed(self, value: i128, lhs_kind: IntKind) -> Self::Output {
        midpoint_for_kind(
            NumericFloor::Typed {
                value: ExactInt::Signed(value),
                kind: lhs_kind,
            },
            self.rhs,
            self.kind,
        )
    }

    fn visit_unsigned(self, value: u128, lhs_kind: IntKind) -> Self::Output {
        midpoint_for_kind(
            NumericFloor::Typed {
                value: ExactInt::Unsigned(value),
                kind: lhs_kind,
            },
            self.rhs,
            self.kind,
        )
    }
}

pub(crate) fn primitive_int_kind(name: &str) -> Option<IntKind> {
    let (signed, bits, name) = match name {
        "i8" => (true, 8, "i8"),
        "i16" => (true, 16, "i16"),
        "i32" => (true, 32, "i32"),
        "i64" => (true, 64, "i64"),
        "i128" => (true, 128, "i128"),
        "isize" => (true, isize::BITS, "isize"),
        "u8" => (false, 8, "u8"),
        "u16" => (false, 16, "u16"),
        "u32" => (false, 32, "u32"),
        "u64" => (false, 64, "u64"),
        "u128" => (false, 128, "u128"),
        "usize" => (false, usize::BITS, "usize"),
        _ => return None,
    };
    Some(IntKind { signed, bits, name })
}

pub(crate) fn exact_int_value(expr: &Expr, fcx: Option<&SugarBuildCtx>) -> Option<ExactInt> {
    exact_int_source(expr, fcx).map(|source| source.value)
}

pub(crate) fn exact_int_source(expr: &Expr, fcx: Option<&SugarBuildCtx>) -> Option<ExactIntSource> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => {
            let suffix = i.suffix();
            if let Some(kind) = primitive_int_kind(suffix) {
                let raw = i.base10_parse::<u128>().ok()?;
                let value = ExactInt::Unsigned(raw);
                value.fits_kind(kind).then_some(ExactIntSource {
                    value: if kind.signed {
                        ExactInt::Signed(value.as_signed_for_kind(kind)?)
                    } else {
                        ExactInt::Unsigned(raw)
                    },
                    kind: Some(kind),
                })
            } else {
                i.base10_parse::<i128>().ok().map(|value| ExactIntSource {
                    value: ExactInt::Signed(value),
                    kind: None,
                })
            }
        }
        Expr::Lit(ExprLit {
            lit: Lit::Byte(b), ..
        }) => Some(ExactIntSource {
            value: ExactInt::Unsigned(u128::from(b.value())),
            kind: primitive_int_kind("u8"),
        }),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => {
            let source = exact_int_source(&u.expr, fcx)?;
            Some(ExactIntSource {
                value: source.value.checked_neg()?,
                kind: source.kind,
            })
        }
        Expr::Path(p) => path_int_value(p, fcx),
        _ => None,
    }
}

pub(crate) fn from_impl_exists(src: IntKind, dst: IntKind) -> bool {
    if src.name == dst.name {
        return true;
    }
    if dst.signed {
        if src.signed {
            dst.bits >= src.bits
        } else {
            dst.bits > src.bits
        }
    } else {
        !src.signed && dst.bits >= src.bits
    }
}

pub(crate) fn numeric_floor_from_term(term: &Rc<Term>) -> Option<NumericFloor> {
    if let Some(value) = const_fold_u128_term(term) {
        return Some(NumericFloor::Typed {
            value: ExactInt::Unsigned(value),
            kind: primitive_int_kind("u128")?,
        });
    }

    match term.as_ref() {
        Term::Const {
            value: ConstValue::Int(value),
            sort,
        } => {
            let Some(kind) = primitive_int_kind(&sort.name) else {
                return Some(NumericFloor::Untyped(*value));
            };
            let exact = if kind.signed {
                ExactInt::Signed(*value)
            } else {
                ExactInt::Unsigned(u128::try_from(*value).ok()?)
            };
            exact
                .fits_kind(kind)
                .then_some(NumericFloor::Typed { value: exact, kind })
        }
        Term::Ctor { name, args } if args.len() == 1 && name.starts_with("cast:") => {
            let kind = primitive_int_kind(name.strip_prefix("cast:")?)?;
            let value = const_fold_int_term(term)?;
            let exact = if kind.signed {
                ExactInt::Signed(value)
            } else {
                ExactInt::Unsigned(u128::try_from(value).ok()?)
            };
            exact
                .fits_kind(kind)
                .then_some(NumericFloor::Typed { value: exact, kind })
        }
        _ => const_fold_int_term(term).map(NumericFloor::Untyped),
    }
}

impl NumericFloor {
    pub(crate) fn accept<V: NumericLiteralVisitor>(self, visitor: V) -> V::Output {
        match self {
            NumericFloor::Untyped(value) => visitor.visit_untyped(value),
            NumericFloor::Typed {
                value: ExactInt::Signed(value),
                kind,
            } => visitor.visit_signed(value, kind),
            NumericFloor::Typed {
                value: ExactInt::Unsigned(value),
                kind,
            } => visitor.visit_unsigned(value, kind),
        }
    }

    pub(crate) fn term(self) -> Option<Rc<Term>> {
        match self {
            NumericFloor::Untyped(value) => Some(num(value)),
            NumericFloor::Typed { value, kind } => typed_int_term(value, kind),
        }
    }

    fn exact_for_kind(self, kind: IntKind) -> Option<ExactInt> {
        let exact = match self {
            NumericFloor::Untyped(value) => ExactInt::Signed(value),
            NumericFloor::Typed { value, .. } => value,
        };
        if !exact.fits_kind(kind) {
            return None;
        }
        if kind.signed {
            Some(ExactInt::Signed(exact.as_signed_for_kind(kind)?))
        } else {
            Some(ExactInt::Unsigned(exact.as_unsigned()?))
        }
    }
}

fn wrapping_neg_typed(value: ExactInt, kind: IntKind) -> Option<NumericFloor> {
    let raw = value.raw_for_kind(kind)?;
    let result = mask_raw(raw.wrapping_neg(), kind.bits);
    Some(NumericFloor::Typed {
        value: ExactInt::from_raw_for_kind(result, kind)?,
        kind,
    })
}

impl ExactInt {
    pub(crate) fn fits_kind(self, kind: IntKind) -> bool {
        if kind.signed {
            match self {
                ExactInt::Signed(value) => {
                    let (min, max) = signed_bounds(kind.bits);
                    value >= min && value <= max
                }
                ExactInt::Unsigned(value) => value <= signed_max(kind.bits),
            }
        } else {
            match self {
                ExactInt::Signed(value) => {
                    value >= 0 && u128::try_from(value).is_ok_and(|v| v <= unsigned_max(kind.bits))
                }
                ExactInt::Unsigned(value) => value <= unsigned_max(kind.bits),
            }
        }
    }

    pub(crate) fn term_for_kind(self, kind: IntKind) -> Option<Rc<Term>> {
        if !self.fits_kind(kind) {
            return None;
        }
        if !kind.signed && kind.bits == 128 {
            return Some(u128_term(self.as_unsigned()?));
        }
        Some(num(self.as_signed_for_kind(kind)?))
    }

    pub(crate) fn label(self) -> String {
        match self {
            ExactInt::Signed(value) => value.to_string(),
            ExactInt::Unsigned(value) => format!("{value}u"),
        }
    }

    fn as_unsigned(self) -> Option<u128> {
        match self {
            ExactInt::Signed(value) => u128::try_from(value).ok(),
            ExactInt::Unsigned(value) => Some(value),
        }
    }

    fn as_signed_for_kind(self, kind: IntKind) -> Option<i128> {
        match self {
            ExactInt::Signed(value) => Some(value),
            ExactInt::Unsigned(value) => {
                if kind.signed && kind.bits == 128 {
                    i128::try_from(value).ok()
                } else {
                    i128::try_from(value).ok()
                }
            }
        }
    }

    fn checked_neg(self) -> Option<ExactInt> {
        match self {
            ExactInt::Signed(value) => value.checked_neg().map(ExactInt::Signed),
            ExactInt::Unsigned(value) => {
                let value = i128::try_from(value).ok()?;
                value.checked_neg().map(ExactInt::Signed)
            }
        }
    }

    fn raw_for_kind(self, kind: IntKind) -> Option<u128> {
        if !self.fits_kind(kind) {
            return None;
        }
        if kind.signed {
            return match self {
                ExactInt::Signed(value) => Some(mask_raw(value as u128, kind.bits)),
                ExactInt::Unsigned(value) => Some(mask_raw(value, kind.bits)),
            };
        }
        Some(mask_raw(self.as_unsigned()?, kind.bits))
    }

    fn from_raw_for_kind(raw: u128, kind: IntKind) -> Option<ExactInt> {
        let raw = mask_raw(raw, kind.bits);
        if kind.signed {
            Some(ExactInt::Signed(signed_from_raw(raw, kind.bits)?))
        } else {
            Some(ExactInt::Unsigned(raw))
        }
    }
}

fn midpoint_for_kind(lhs: NumericFloor, rhs: NumericFloor, kind: IntKind) -> Option<NumericFloor> {
    let lhs = lhs.exact_for_kind(kind)?;
    let rhs = rhs.exact_for_kind(kind)?;
    let value = if kind.signed {
        ExactInt::Signed(signed_midpoint(
            lhs.as_signed_for_kind(kind)?,
            rhs.as_signed_for_kind(kind)?,
            kind,
        )?)
    } else {
        ExactInt::Unsigned(unsigned_midpoint(
            lhs.as_unsigned()?,
            rhs.as_unsigned()?,
            kind,
        )?)
    };
    Some(NumericFloor::Typed { value, kind })
}

fn signed_midpoint(lhs: i128, rhs: i128, kind: IntKind) -> Option<i128> {
    let (min, max) = signed_bounds(kind.bits);
    if lhs < min || lhs > max || rhs < min || rhs > max {
        return None;
    }
    if (lhs < 0) == (rhs < 0) {
        let halves = (lhs / 2).checked_add(rhs / 2)?;
        let remainders = (lhs % 2).checked_add(rhs % 2)?;
        halves.checked_add(remainders / 2)
    } else {
        lhs.checked_add(rhs)?.checked_div(2)
    }
}

fn unsigned_midpoint(lhs: u128, rhs: u128, kind: IntKind) -> Option<u128> {
    let max = unsigned_max(kind.bits);
    if lhs > max || rhs > max {
        return None;
    }
    Some((lhs & rhs) + ((lhs ^ rhs) >> 1))
}

pub(crate) fn typed_int_term(value: ExactInt, kind: IntKind) -> Option<Rc<Term>> {
    if !value.fits_kind(kind) {
        return None;
    }
    if !kind.signed && kind.bits == 128 {
        return Some(u128_term(value.as_unsigned()?));
    }
    Some(Rc::new(Term::Const {
        value: ConstValue::Int(value.as_signed_for_kind(kind)?),
        sort: Sort {
            name: kind.name.to_string(),
        },
    }))
}

fn path_int_value(p: &ExprPath, fcx: Option<&SugarBuildCtx>) -> Option<ExactIntSource> {
    let last = p.path.segments.last()?.ident.to_string();
    if last == "MAX" || last == "MIN" {
        let ty = if let Some(qself) = &p.qself {
            let syn::Type::Path(tp) = &*qself.ty else {
                return None;
            };
            tp.path.segments.last()?.ident.to_string()
        } else {
            p.path.segments.iter().rev().nth(1)?.ident.to_string()
        };
        return primitive_const_value(&ty, last == "MAX");
    }
    let fcx = fcx?;
    if p.qself.is_none() {
        let name = p.path.get_ident()?.to_string();
        if fcx.resolving_bound_path(&name) {
            return None;
        }
        let init = fcx.scope().stable_let_binding_for_term(&name)?;
        return exact_int_source(init, Some(&fcx.with_bound_path(&name)));
    }
    None
}

fn primitive_const_value(ty: &str, is_max: bool) -> Option<ExactIntSource> {
    let kind = primitive_int_kind(ty)?;
    let value = if kind.signed {
        let value = if is_max {
            i128::try_from(signed_max(kind.bits)).ok()?
        } else {
            signed_bounds(kind.bits).0
        };
        ExactInt::Signed(value)
    } else if is_max {
        ExactInt::Unsigned(unsigned_max(kind.bits))
    } else {
        ExactInt::Unsigned(0)
    };
    Some(ExactIntSource {
        value,
        kind: Some(kind),
    })
}

fn signed_bounds(bits: u32) -> (i128, i128) {
    if bits >= 128 {
        (i128::MIN, i128::MAX)
    } else {
        let sign = 1i128 << (bits - 1);
        (-sign, sign - 1)
    }
}

fn signed_max(bits: u32) -> u128 {
    if bits >= 128 {
        i128::MAX as u128
    } else {
        (1u128 << (bits - 1)) - 1
    }
}

fn unsigned_max(bits: u32) -> u128 {
    if bits >= 128 {
        u128::MAX
    } else {
        (1u128 << bits) - 1
    }
}

fn mask_raw(value: u128, bits: u32) -> u128 {
    if bits >= 128 {
        value
    } else {
        value & ((1u128 << bits) - 1)
    }
}

fn signed_from_raw(raw: u128, bits: u32) -> Option<i128> {
    if bits >= 128 {
        return Some(raw as i128);
    }
    let raw = mask_raw(raw, bits);
    let sign = 1u128 << (bits - 1);
    if raw & sign == 0 {
        i128::try_from(raw).ok()
    } else {
        let modulus = 1i128.checked_shl(bits)?;
        let magnitude = i128::try_from(raw).ok()?;
        magnitude.checked_sub(modulus)
    }
}
