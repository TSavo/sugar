// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use syn::{Expr, ExprLit, ExprPath, Lit, UnOp};

use crate::sugar::factory::SugarBuildCtx;
use crate::{strip_refs_groups, u128_term};
use sugar_ir_symbolic::{num, Term};

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
