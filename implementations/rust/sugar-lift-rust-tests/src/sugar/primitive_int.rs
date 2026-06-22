// SPDX-License-Identifier: Apache-2.0
//
// `PrimitiveIntSugar`: small primitive-integer stdlib/compiler axioms over
// grounded literal terms. The compiler owns these semantics; this sugar reads
// them out when the receiver/argument have already bottomed out.

use sugar_ir_symbolic::num;
use syn::{Expr, ExprPath, PathArguments, Type};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::option_unwrap::is_known_monadic_source;
use crate::{
    const_fold_int_term, const_fold_u128_term, strip_refs_groups, u128_term, Desugared, Outcome,
    Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("primitive_int", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !receiver_can_ground(&call.receiver, fcx) {
        return None;
    }
    let method = call.method.to_string();
    let kind = match (method.as_str(), call.args.len()) {
        ("count_ones", 0) => Kind::CountOnes,
        ("leading_zeros", 0) => Kind::ZeroCount(ZeroCountOp::Leading),
        ("trailing_zeros", 0) => Kind::ZeroCount(ZeroCountOp::Trailing),
        ("bit_width", 0) => Kind::BitWidth,
        ("min", 1) => Kind::Min(build_term(&call.args[0], fcx)),
        ("checked_add", 1) => Kind::Checked(CheckedOp::Add, build_term(&call.args[0], fcx)),
        ("checked_sub", 1) => Kind::Checked(CheckedOp::Sub, build_term(&call.args[0], fcx)),
        ("checked_mul", 1) => Kind::Checked(CheckedOp::Mul, build_term(&call.args[0], fcx)),
        ("checked_div", 1) => Kind::Checked(CheckedOp::Div, build_term(&call.args[0], fcx)),
        _ => return None,
    };
    Some(Box::new(PrimitiveIntSugar {
        method,
        receiver_expr: (*call.receiver).clone(),
        receiver: build_term(&call.receiver, fcx),
        kind,
    }))
}

fn receiver_can_ground(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => matches!(
            lit.lit,
            syn::Lit::Int(_) | syn::Lit::Byte(_) | syn::Lit::Char(_)
        ),
        Expr::Path(path) => {
            primitive_assoc_const_path(path).is_some()
                || path
                    .path
                    .get_ident()
                    .is_some_and(|_| fcx.scope().const_expr_for_path(&path.path).is_some())
        }
        Expr::Cast(cast) => receiver_can_ground(&cast.expr, fcx),
        Expr::Unary(unary) => receiver_can_ground(&unary.expr, fcx),
        Expr::Binary(binary) => {
            receiver_can_ground(&binary.left, fcx) && receiver_can_ground(&binary.right, fcx)
        }
        Expr::Paren(paren) => receiver_can_ground(&paren.expr, fcx),
        Expr::Group(group) => receiver_can_ground(&group.expr, fcx),
        Expr::Reference(reference) => receiver_can_ground(&reference.expr, fcx),
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "count_ones"
                    | "leading_zeros"
                    | "trailing_zeros"
                    | "bit_width"
                    | "min"
                    | "checked_add"
                    | "checked_sub"
                    | "checked_mul"
                    | "checked_div"
            ) =>
        {
            receiver_can_ground(&call.receiver, fcx)
        }
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect")
                && is_known_monadic_source(&call.receiver) =>
        {
            true
        }
        _ => false,
    }
}

enum Kind {
    CountOnes,
    ZeroCount(ZeroCountOp),
    BitWidth,
    Min(Box<dyn Sugar>),
    Checked(CheckedOp, Box<dyn Sugar>),
}

#[derive(Clone, Copy)]
enum ZeroCountOp {
    Leading,
    Trailing,
}

#[derive(Clone, Copy)]
enum CheckedOp {
    Add,
    Sub,
    Mul,
    Div,
}

struct PrimitiveIntSugar {
    method: String,
    receiver_expr: Expr,
    receiver: Box<dyn Sugar>,
    kind: Kind,
}

impl Sugar for PrimitiveIntSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if matches!(self.kind, Kind::CountOnes) {
            if let Some(value) = assoc_const_count_ones(&self.receiver_expr) {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    value,
                    "resolved primitive associated-const count_ones axiom"
                );
                return Outcome::Dug(Desugared::Term(num(i128::from(value))));
            }
        }

        let receiver = match self.receiver.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let lhs_u128 = const_fold_u128_term(&receiver);
        let lhs_i128 = const_fold_int_term(&receiver);

        match &self.kind {
            Kind::CountOnes => {
                if let Some(lhs) = lhs_u128 {
                    let value = lhs.count_ones();
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        lhs = %lhs,
                        value,
                        "resolved primitive u128 count_ones axiom"
                    );
                    return Outcome::Dug(Desugared::Term(num(i128::from(value))));
                }
                let Some(lhs) = lhs_i128 else {
                    return Outcome::from_opt(None);
                };
                let Some(value) = count_ones_value(lhs, integer_kind_hint(&self.receiver_expr))
                else {
                    return Outcome::from_opt(None);
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs,
                    value,
                    "resolved primitive count_ones axiom"
                );
                Outcome::Dug(Desugared::Term(num(i128::from(value))))
            }
            Kind::ZeroCount(op) => {
                let Some(value) = zero_count_value(
                    lhs_i128,
                    lhs_u128,
                    integer_kind_hint(&self.receiver_expr),
                    *op,
                ) else {
                    return Outcome::from_opt(None);
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    value,
                    "resolved primitive zero-count integer axiom"
                );
                Outcome::Dug(Desugared::Term(num(i128::from(value))))
            }
            Kind::BitWidth => {
                let Some(value) = bit_width_value(lhs_i128, lhs_u128) else {
                    return Outcome::from_opt(None);
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    value,
                    "resolved primitive bit_width integer axiom"
                );
                Outcome::Dug(Desugared::Term(num(i128::from(value))))
            }
            Kind::Min(rhs) => {
                let rhs = match rhs.desugar(ctx) {
                    Outcome::Dug(d) => match d.into_term() {
                        Some(term) => term,
                        None => return Outcome::from_opt(None),
                    },
                    Outcome::Hit(e) => return Outcome::Hit(e),
                };
                if lhs_u128.is_some() || const_fold_u128_term(&rhs).is_some() {
                    let Some(lhs) =
                        lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))
                    else {
                        return Outcome::from_opt(None);
                    };
                    let Some(rhs) = const_fold_u128_term(&rhs)
                        .or_else(|| const_fold_int_term(&rhs).and_then(|n| u128::try_from(n).ok()))
                    else {
                        return Outcome::from_opt(None);
                    };
                    let value = lhs.min(rhs);
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        lhs = %lhs,
                        rhs = %rhs,
                        value = %value,
                        "resolved primitive u128 min axiom"
                    );
                    return Outcome::Dug(Desugared::Term(u128_term(value)));
                }
                let Some(lhs) = lhs_i128 else {
                    return Outcome::from_opt(None);
                };
                let Some(rhs) = const_fold_int_term(&rhs) else {
                    return Outcome::from_opt(None);
                };
                let value = lhs.min(rhs);
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs,
                    rhs,
                    value,
                    "resolved primitive min axiom"
                );
                Outcome::Dug(Desugared::Term(num(value)))
            }
            Kind::Checked(op, rhs) => {
                let rhs = match rhs.desugar(ctx) {
                    Outcome::Dug(d) => match d.into_term() {
                        Some(term) => term,
                        None => return Outcome::from_opt(None),
                    },
                    Outcome::Hit(e) => return Outcome::Hit(e),
                };
                if lhs_u128.is_some() || const_fold_u128_term(&rhs).is_some() {
                    let Some(lhs) =
                        lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))
                    else {
                        return Outcome::from_opt(None);
                    };
                    let Some(rhs) = const_fold_u128_term(&rhs)
                        .or_else(|| const_fold_int_term(&rhs).and_then(|n| u128::try_from(n).ok()))
                    else {
                        return Outcome::from_opt(None);
                    };
                    let result = checked_u128(lhs, rhs, *op);
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        lhs = %lhs,
                        rhs = %rhs,
                        is_some = result.is_some(),
                        "resolved primitive checked u128 integer axiom"
                    );
                    let term = match result {
                        Some(value) => some_term(u128_term(value)),
                        None => none_term(),
                    };
                    return Outcome::Dug(Desugared::Term(term));
                }
                let Some(lhs) = lhs_i128 else {
                    return Outcome::from_opt(None);
                };
                let Some(rhs) = const_fold_int_term(&rhs) else {
                    return Outcome::from_opt(None);
                };
                let result = checked_int_op(lhs, rhs, *op, integer_kind_hint(&self.receiver_expr));
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs,
                    rhs,
                    is_some = result.is_some(),
                    "resolved primitive checked integer axiom"
                );
                let term = match result {
                    Some(value) => some_term(num(value)),
                    None => none_term(),
                };
                Outcome::Dug(Desugared::Term(term))
            }
        }
    }
}

fn checked_u128(lhs: u128, rhs: u128, op: CheckedOp) -> Option<u128> {
    match op {
        CheckedOp::Add => lhs.checked_add(rhs),
        CheckedOp::Sub => lhs.checked_sub(rhs),
        CheckedOp::Mul => lhs.checked_mul(rhs),
        CheckedOp::Div => (rhs != 0).then(|| lhs / rhs),
    }
}

#[derive(Clone, Copy)]
struct IntegerKind {
    signed: bool,
    bits: u32,
}

fn checked_int_op(lhs: i128, rhs: i128, op: CheckedOp, kind: Option<IntegerKind>) -> Option<i128> {
    if let Some(kind) = kind {
        if !fits_kind(lhs, kind) || !fits_kind(rhs, kind) {
            return None;
        }
        let result = checked_i128(lhs, rhs, op)?;
        return fits_kind(result, kind).then_some(result);
    }
    checked_i128(lhs, rhs, op)
}

fn checked_i128(lhs: i128, rhs: i128, op: CheckedOp) -> Option<i128> {
    match op {
        CheckedOp::Add => lhs.checked_add(rhs),
        CheckedOp::Sub => lhs.checked_sub(rhs),
        CheckedOp::Mul => lhs.checked_mul(rhs),
        CheckedOp::Div => {
            if rhs == 0 {
                None
            } else {
                lhs.checked_div(rhs)
            }
        }
    }
}

fn count_ones_value(value: i128, kind: Option<IntegerKind>) -> Option<u32> {
    let Some(kind) = kind else {
        let value = u128::try_from(value).ok()?;
        return Some(value.count_ones());
    };
    let raw = raw_bits(value, kind)?;
    if kind.bits == 128 {
        Some(raw.count_ones())
    } else {
        let mask = (1u128.checked_shl(kind.bits)?).checked_sub(1)?;
        Some((raw & mask).count_ones())
    }
}

fn zero_count_value(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
    op: ZeroCountOp,
) -> Option<u32> {
    if let Some(kind) = kind {
        let raw = if let Some(value) = lhs_u128 {
            if kind.bits == 128 {
                value
            } else {
                let mask = (1u128.checked_shl(kind.bits)?).checked_sub(1)?;
                value & mask
            }
        } else {
            let value = lhs_i128.or_else(|| lhs_u128.and_then(|n| i128::try_from(n).ok()))?;
            masked_raw_bits(value, kind)?
        };
        return Some(apply_zero_count(raw, kind.bits, op));
    }
    if let Some(value) = lhs_u128 {
        return Some(apply_zero_count(value, 128, op));
    }
    let value = u128::try_from(lhs_i128?).ok()?;
    match op {
        ZeroCountOp::Leading => None,
        ZeroCountOp::Trailing => (value != 0).then_some(value.trailing_zeros()),
    }
}

/// `uint_bit_width` (`bit_width`): the number of bits required to represent the
/// value = highest-set-bit position + 1, with `0.bit_width() == 0`. This is
/// VALUE-determined, independent of the integer type's width: for a `T`-typed
/// unsigned value, `T::BITS - leading_zeros()` equals `128 - leading_zeros()` of
/// the same magnitude widened to `u128` (the leading-zero count grows by exactly
/// `128 - T::BITS`, which cancels). So we never need the receiver's type width.
/// A negative receiver (not a real `bit_width` site — the method is unsigned-only)
/// cannot be widened to `u128` and DECLINES rather than fabricate a value.
fn bit_width_value(lhs_i128: Option<i128>, lhs_u128: Option<u128>) -> Option<u32> {
    let value = lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))?;
    Some(if value == 0 {
        0
    } else {
        u128::BITS - value.leading_zeros()
    })
}

fn apply_zero_count(raw: u128, bits: u32, op: ZeroCountOp) -> u32 {
    match op {
        ZeroCountOp::Leading => {
            if bits == 128 {
                raw.leading_zeros()
            } else {
                (raw << (128 - bits)).leading_zeros()
            }
        }
        ZeroCountOp::Trailing => {
            if raw == 0 {
                bits
            } else {
                raw.trailing_zeros().min(bits)
            }
        }
    }
}

fn assoc_const_count_ones(expr: &Expr) -> Option<u32> {
    let (kind, konst) = primitive_assoc_const(expr)?;
    match (kind.signed, kind.bits, konst.as_str()) {
        (_, _, "MIN") if !kind.signed => Some(0),
        (_, _, "MAX") if !kind.signed => Some(kind.bits),
        (_, _, "MIN") => Some(1),
        (_, _, "MAX") => Some(kind.bits.saturating_sub(1)),
        _ => None,
    }
}

fn integer_kind_hint(expr: &Expr) -> Option<IntegerKind> {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            syn::Lit::Int(i) => primitive_integer_kind(i.suffix()),
            _ => None,
        },
        Expr::Cast(cast) => integer_kind_from_type(&cast.ty),
        Expr::Path(path) => primitive_assoc_const_path(path).map(|(kind, _)| kind),
        Expr::Unary(unary) => integer_kind_hint(&unary.expr),
        Expr::Paren(paren) => integer_kind_hint(&paren.expr),
        Expr::Group(group) => integer_kind_hint(&group.expr),
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect")
                && is_known_monadic_source(&call.receiver) =>
        {
            nonzero_new_integer_kind(&call.receiver).or_else(|| integer_kind_hint(&call.receiver))
        }
        _ => None,
    }
}

fn nonzero_new_integer_kind(expr: &Expr) -> Option<IntegerKind> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() < 2 {
        return None;
    }
    let mut segments = path.path.segments.iter().rev();
    let method = segments.next()?;
    let ty = segments.next()?;
    if method.ident != "new" {
        return None;
    }
    let ty_name = ty.ident.to_string();
    if ty_name == "NonZero" {
        let PathArguments::AngleBracketed(args) = &ty.arguments else {
            return None;
        };
        return args.args.iter().find_map(|arg| match arg {
            syn::GenericArgument::Type(ty) => integer_kind_from_type(&ty),
            _ => None,
        });
    }
    ty_name
        .strip_prefix("NonZero")
        .map(|suffix| suffix.to_ascii_lowercase())
        .and_then(|suffix| primitive_integer_kind(&suffix))
}

fn primitive_assoc_const(expr: &Expr) -> Option<(IntegerKind, String)> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    primitive_assoc_const_path(path)
}

fn primitive_assoc_const_path(path: &ExprPath) -> Option<(IntegerKind, String)> {
    if let Some(qself) = &path.qself {
        let kind = integer_kind_from_type(&qself.ty)?;
        let konst = path.path.segments.last()?.ident.to_string();
        return Some((kind, konst));
    }
    if path.path.segments.len() != 2 {
        return None;
    }
    if path
        .path
        .segments
        .iter()
        .any(|segment| !matches!(segment.arguments, PathArguments::None))
    {
        return None;
    }
    let ty = path.path.segments[0].ident.to_string();
    let kind = primitive_integer_kind(&ty)?;
    let konst = path.path.segments[1].ident.to_string();
    Some((kind, konst))
}

fn integer_kind_from_type(ty: &Type) -> Option<IntegerKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    primitive_integer_kind(&path.path.segments.last()?.ident.to_string())
}

fn primitive_integer_kind(name: &str) -> Option<IntegerKind> {
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
    Some(IntegerKind { signed, bits })
}

fn raw_bits(value: i128, kind: IntegerKind) -> Option<u128> {
    if !fits_kind(value, kind) {
        if !kind.signed && kind.bits == 128 {
            return Some(value as u128);
        }
        if kind.signed && value >= 0 && kind.bits < 128 {
            let raw = u128::try_from(value).ok()?;
            let max = (1u128.checked_shl(kind.bits)?).checked_sub(1)?;
            return (raw <= max).then_some(raw);
        }
        return None;
    }
    if value >= 0 {
        return u128::try_from(value).ok();
    }
    if kind.bits == 128 {
        return Some(value as u128);
    }
    let modulus = 1i128.checked_shl(kind.bits)?;
    u128::try_from(modulus.checked_add(value)?).ok()
}

fn masked_raw_bits(value: i128, kind: IntegerKind) -> Option<u128> {
    let raw = raw_bits(value, kind)?;
    if kind.bits == 128 {
        Some(raw)
    } else {
        let mask = (1u128.checked_shl(kind.bits)?).checked_sub(1)?;
        Some(raw & mask)
    }
}

fn fits_kind(value: i128, kind: IntegerKind) -> bool {
    if kind.signed {
        let (min, max) = signed_bounds(kind.bits);
        (min..=max).contains(&value)
    } else if kind.bits == 128 {
        value >= 0
    } else {
        let max = (1i128 << kind.bits) - 1;
        (0..=max).contains(&value)
    }
}

fn signed_bounds(bits: u32) -> (i128, i128) {
    if bits == 128 {
        (i128::MIN, i128::MAX)
    } else {
        let sign = 1i128 << (bits - 1);
        (-sign, sign - 1)
    }
}
