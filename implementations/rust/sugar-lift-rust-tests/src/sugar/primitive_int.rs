// SPDX-License-Identifier: Apache-2.0
//
// `PrimitiveIntSugar`: small primitive-integer stdlib/compiler axioms over
// grounded literal terms. The compiler owns these semantics; this sugar reads
// them out when the receiver/argument have already bottomed out.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{num, real_const, ConstValue, Term};
use syn::{Expr, ExprPath, PathArguments, Type};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::nonzero::nonzero_assoc_const_expr;
use crate::sugar::option_unwrap::is_known_monadic_source;
use crate::{
    const_fold_int_term, const_fold_u128_term, simple_path_name, strip_refs_groups, u128_term,
    Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("primitive_int", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    let kind = match (method.as_str(), call.args.len()) {
        ("count_ones", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => Kind::CountOnes,
        ("count_zeros", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::ZeroCount(ZeroCountOp::Count)
        }
        ("leading_zeros", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::ZeroCount(ZeroCountOp::Leading)
        }
        ("trailing_zeros", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::ZeroCount(ZeroCountOp::Trailing)
        }
        ("bit_width", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => Kind::BitWidth,
        ("isolate_highest_one", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::IsolateHighestOne
        }
        ("min", 1) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::Min(call.args[0].clone())
        }
        ("max", 1)
            if integer_receiver_can_ground(&call.receiver, fcx, 0)
                && integer_receiver_can_ground(&call.args[0], fcx, 0) =>
        {
            Kind::Max(call.args[0].clone())
        }
        ("checked_add", 1) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::Checked(CheckedOp::Add, call.args[0].clone())
        }
        ("checked_sub", 1) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::Checked(CheckedOp::Sub, call.args[0].clone())
        }
        ("checked_mul", 1) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::Checked(CheckedOp::Mul, call.args[0].clone())
        }
        ("checked_div", 1) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::Checked(CheckedOp::Div, call.args[0].clone())
        }
        ("wrapping_add", 1)
            if integer_receiver_can_ground(&call.receiver, fcx, 0)
                && integer_receiver_can_ground(&call.args[0], fcx, 0) =>
        {
            Kind::Wrapping(WrappingOp::Add, call.args[0].clone())
        }
        ("wrapping_sub", 1)
            if integer_receiver_can_ground(&call.receiver, fcx, 0)
                && integer_receiver_can_ground(&call.args[0], fcx, 0) =>
        {
            Kind::Wrapping(WrappingOp::Sub, call.args[0].clone())
        }
        ("wrapping_mul", 1)
            if integer_receiver_can_ground(&call.receiver, fcx, 0)
                && integer_receiver_can_ground(&call.args[0], fcx, 0) =>
        {
            Kind::Wrapping(WrappingOp::Mul, call.args[0].clone())
        }
        ("abs", 0) if numeric_receiver_can_ground(&call.receiver, fcx, 0) => Kind::Abs,
        ("signum", 0) if numeric_receiver_can_ground(&call.receiver, fcx, 0) => Kind::Signum,
        _ => return None,
    };
    Some(Box::new(PrimitiveIntSugar {
        method,
        receiver_expr: (*call.receiver).clone(),
        receiver: (*call.receiver).clone(),
        kind,
        let_inits: capture_let_inits(fcx),
    }))
}

fn integer_receiver_can_ground(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => matches!(
            lit.lit,
            syn::Lit::Int(_) | syn::Lit::Byte(_) | syn::Lit::Char(_)
        ),
        Expr::Path(path) => {
            if primitive_assoc_const_path(path).is_some() {
                return true;
            }
            if nonzero_assoc_const_expr(expr).is_some() {
                return true;
            }
            if let Some(init) = fcx.scope().const_expr_for_path(&path.path) {
                return integer_receiver_can_ground(&init, fcx, depth + 1);
            }
            let Some(name) = simple_path_name(expr) else {
                return false;
            };
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .is_some_and(|init| integer_receiver_can_ground(init, fcx, depth + 1))
        }
        Expr::Cast(cast) => integer_receiver_can_ground(&cast.expr, fcx, depth + 1),
        Expr::Unary(unary) => integer_receiver_can_ground(&unary.expr, fcx, depth + 1),
        Expr::Binary(binary) => {
            integer_receiver_can_ground(&binary.left, fcx, depth + 1)
                && integer_receiver_can_ground(&binary.right, fcx, depth + 1)
        }
        Expr::Paren(paren) => integer_receiver_can_ground(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => integer_receiver_can_ground(&group.expr, fcx, depth + 1),
        Expr::Reference(reference) => integer_receiver_can_ground(&reference.expr, fcx, depth + 1),
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "count_ones"
                    | "count_zeros"
                    | "leading_zeros"
                    | "trailing_zeros"
                    | "bit_width"
                    | "isolate_highest_one"
                    | "min"
                    | "max"
                    | "checked_add"
                    | "checked_sub"
                    | "checked_mul"
                    | "checked_div"
                    | "wrapping_add"
                    | "wrapping_sub"
                    | "wrapping_mul"
                    | "abs"
                    | "signum"
            ) =>
        {
            integer_receiver_can_ground(&call.receiver, fcx, depth + 1)
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

fn numeric_receiver_can_ground(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    integer_receiver_can_ground(expr, fcx, depth) || float_receiver_can_ground(expr, fcx, depth)
}

fn float_receiver_can_ground(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => matches!(lit.lit, syn::Lit::Float(_)),
        Expr::Path(path) => {
            if let Some(init) = fcx.scope().const_expr_for_path(&path.path) {
                return float_receiver_can_ground(&init, fcx, depth + 1);
            }
            let Some(name) = simple_path_name(expr) else {
                return false;
            };
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .is_some_and(|init| float_receiver_can_ground(init, fcx, depth + 1))
        }
        Expr::Cast(cast) => float_receiver_can_ground(&cast.expr, fcx, depth + 1),
        Expr::Unary(unary) => float_receiver_can_ground(&unary.expr, fcx, depth + 1),
        Expr::Paren(paren) => float_receiver_can_ground(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => float_receiver_can_ground(&group.expr, fcx, depth + 1),
        Expr::Reference(reference) => float_receiver_can_ground(&reference.expr, fcx, depth + 1),
        _ => false,
    }
}

enum Kind {
    CountOnes,
    ZeroCount(ZeroCountOp),
    BitWidth,
    IsolateHighestOne,
    Min(Expr),
    Max(Expr),
    Checked(CheckedOp, Expr),
    Wrapping(WrappingOp, Expr),
    Abs,
    Signum,
}

#[derive(Clone, Copy)]
enum ZeroCountOp {
    Count,
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

#[derive(Clone, Copy)]
enum WrappingOp {
    Add,
    Sub,
    Mul,
}

struct PrimitiveIntSugar {
    method: String,
    receiver_expr: Expr,
    receiver: Expr,
    kind: Kind,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}

fn desugar_term_expr(
    expr: &Expr,
    ctx: &SugarCtx,
    fcx: &SugarBuildCtx,
) -> Result<Rc<Term>, Outcome> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Dug(d) => d.into_term().ok_or_else(|| Outcome::from_opt(None)),
        Outcome::Hit(e) => Err(Outcome::Hit(e)),
    }
}

impl Sugar for PrimitiveIntSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if matches!(&self.kind, Kind::CountOnes) {
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

        let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let receiver = match desugar_term_expr(&self.receiver, ctx, &fcx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let lhs_u128 = const_fold_u128_term(&receiver);
        let lhs_i128 = const_fold_int_term(&receiver);
        let kind_hint = integer_kind_hint_in_scope(&self.receiver_expr, &fcx, 0);

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
                let Some(value) = count_ones_value(lhs, kind_hint) else {
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
                let Some(value) = zero_count_value(lhs_i128, lhs_u128, kind_hint, *op) else {
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
            Kind::IsolateHighestOne => {
                let Some(term) = isolate_highest_one_term(lhs_i128, lhs_u128, kind_hint) else {
                    return Outcome::from_opt(None);
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive isolate_highest_one integer axiom"
                );
                Outcome::Dug(Desugared::Term(term))
            }
            Kind::Min(rhs) | Kind::Max(rhs) => {
                let rhs = match desugar_term_expr(rhs, ctx, &fcx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
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
                    let value = if matches!(&self.kind, Kind::Min(_)) {
                        lhs.min(rhs)
                    } else {
                        lhs.max(rhs)
                    };
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        lhs = %lhs,
                        rhs = %rhs,
                        value = %value,
                        "resolved primitive u128 extremum axiom"
                    );
                    return Outcome::Dug(Desugared::Term(u128_term(value)));
                }
                let Some(lhs) = lhs_i128 else {
                    return Outcome::from_opt(None);
                };
                let Some(rhs) = const_fold_int_term(&rhs) else {
                    return Outcome::from_opt(None);
                };
                let value = if matches!(&self.kind, Kind::Min(_)) {
                    lhs.min(rhs)
                } else {
                    lhs.max(rhs)
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs,
                    rhs,
                    value,
                    "resolved primitive extremum axiom"
                );
                Outcome::Dug(Desugared::Term(num(value)))
            }
            Kind::Checked(op, rhs) => {
                let rhs = match desugar_term_expr(rhs, ctx, &fcx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
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
                let result = checked_int_op(lhs, rhs, *op, kind_hint);
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
            Kind::Wrapping(op, rhs) => {
                let rhs = match desugar_term_expr(rhs, ctx, &fcx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                let Some(term) = wrapping_int_op_term(lhs_i128, lhs_u128, &rhs, *op, kind_hint)
                else {
                    return Outcome::from_opt(None);
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive wrapping integer axiom"
                );
                Outcome::Dug(Desugared::Term(term))
            }
            Kind::Abs => {
                if let Some(value) = const_fold_real_term(&receiver) {
                    let Some(value) = real_abs_value(&value) else {
                        return Outcome::from_opt(None);
                    };
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        value = value.as_str(),
                        "resolved primitive float abs axiom"
                    );
                    return Outcome::Dug(Desugared::Term(real_const(value)));
                }
                let Some(term) = abs_int_term(lhs_i128, lhs_u128, kind_hint) else {
                    return Outcome::from_opt(None);
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive integer abs axiom"
                );
                Outcome::Dug(Desugared::Term(term))
            }
            Kind::Signum => {
                if let Some(value) = const_fold_real_term(&receiver) {
                    let Some(value) = real_signum_value(&value) else {
                        return Outcome::from_opt(None);
                    };
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        value = value.as_str(),
                        "resolved primitive float signum axiom"
                    );
                    return Outcome::Dug(Desugared::Term(real_const(value)));
                }
                let Some(value) = signum_int_value(lhs_i128, lhs_u128, kind_hint) else {
                    return Outcome::from_opt(None);
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    value,
                    "resolved primitive integer signum axiom"
                );
                Outcome::Dug(Desugared::Term(num(value)))
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

fn wrapping_int_op_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    rhs: &Rc<Term>,
    op: WrappingOp,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    let kind = kind?;
    if kind.signed {
        let lhs = lhs_i128?;
        let rhs = const_fold_int_term(rhs)?;
        if !fits_kind(lhs, kind) || !fits_kind(rhs, kind) {
            return None;
        }
        let lhs = masked_raw_bits(lhs, kind)?;
        let rhs = masked_raw_bits(rhs, kind)?;
        let raw = apply_wrapping_raw(lhs, rhs, kind.bits, op)?;
        return Some(num(signed_value_from_raw(raw, kind)?));
    }

    let lhs = lhs_u128.or_else(|| lhs_i128.and_then(|value| u128::try_from(value).ok()))?;
    let rhs = const_fold_u128_term(rhs)
        .or_else(|| const_fold_int_term(rhs).and_then(|value| u128::try_from(value).ok()))?;
    let raw = apply_wrapping_raw(lhs, rhs, kind.bits, op)?;
    if kind.bits == 128 {
        Some(u128_term(raw))
    } else {
        Some(num(i128::try_from(raw).ok()?))
    }
}

fn apply_wrapping_raw(lhs: u128, rhs: u128, bits: u32, op: WrappingOp) -> Option<u128> {
    let mask = mask_for_bits(bits)?;
    let value = match op {
        WrappingOp::Add => lhs.wrapping_add(rhs),
        WrappingOp::Sub => lhs.wrapping_sub(rhs),
        WrappingOp::Mul => lhs.wrapping_mul(rhs),
    };
    Some(value & mask)
}

fn mask_for_bits(bits: u32) -> Option<u128> {
    if bits == 128 {
        Some(u128::MAX)
    } else {
        (1u128.checked_shl(bits)?).checked_sub(1)
    }
}

fn signed_value_from_raw(raw: u128, kind: IntegerKind) -> Option<i128> {
    if kind.bits == 128 {
        return Some(raw as i128);
    }
    let sign_bit = 1u128.checked_shl(kind.bits - 1)?;
    if raw & sign_bit == 0 {
        i128::try_from(raw).ok()
    } else {
        let modulus = 1i128.checked_shl(kind.bits)?;
        i128::try_from(raw).ok()?.checked_sub(modulus)
    }
}

fn abs_int_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    if lhs_u128.is_some() || kind.is_some_and(|kind| !kind.signed) {
        return None;
    }
    let lhs = lhs_i128?;
    if let Some(kind) = kind {
        if !kind.signed || !fits_kind(lhs, kind) {
            return None;
        }
        let (min, _) = signed_bounds(kind.bits);
        if lhs == min {
            return None;
        }
    }
    lhs.checked_abs().map(num)
}

fn signum_int_value(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<i128> {
    if lhs_u128.is_some() || kind.is_some_and(|kind| !kind.signed) {
        return None;
    }
    let lhs = lhs_i128?;
    if let Some(kind) = kind {
        if !kind.signed || !fits_kind(lhs, kind) {
            return None;
        }
    }
    Some(lhs.signum())
}

fn const_fold_real_term(term: &Rc<Term>) -> Option<String> {
    match term.as_ref() {
        Term::Const {
            value: ConstValue::Real(value),
            ..
        } => Some(value.clone()),
        Term::Ctor { name, args } if name == "ref" && args.len() == 1 => {
            const_fold_real_term(&args[0])
        }
        _ => None,
    }
}

fn real_abs_value(value: &str) -> Option<String> {
    if real_literal_is_zero_text(value) {
        return None;
    }
    Some(value.strip_prefix('-').unwrap_or(value).to_string())
}

fn real_signum_value(value: &str) -> Option<String> {
    if real_literal_is_zero_text(value) {
        return None;
    }
    if value.starts_with('-') {
        Some("-1".to_string())
    } else {
        Some("1".to_string())
    }
}

fn real_literal_is_zero_text(text: &str) -> bool {
    let text = text.strip_prefix('-').unwrap_or(text);
    let mut saw_digit = false;
    for ch in text.chars() {
        if ch == '.' {
            continue;
        }
        saw_digit = true;
        if ch != '0' {
            return false;
        }
    }
    saw_digit
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
        ZeroCountOp::Count => None,
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

fn isolate_highest_one_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    if let Some(kind) = kind {
        let raw = if let Some(value) = lhs_u128 {
            value & mask_for_bits(kind.bits)?
        } else {
            masked_raw_bits(lhs_i128?, kind)?
        };
        let isolated = isolate_highest_raw(raw, kind.bits)?;
        return if kind.signed {
            signed_value_from_raw(isolated, kind).map(num)
        } else if kind.bits == 128 {
            Some(u128_term(isolated))
        } else {
            Some(num(i128::try_from(isolated).ok()?))
        };
    }

    if let Some(value) = lhs_u128 {
        return Some(u128_term(isolate_highest_raw(value, 128)?));
    }
    let value = u128::try_from(lhs_i128?).ok()?;
    Some(num(i128::try_from(isolate_highest_raw(value, 128)?).ok()?))
}

fn isolate_highest_raw(value: u128, bits: u32) -> Option<u128> {
    if value == 0 {
        return Some(0);
    }
    let leading = apply_zero_count(value, bits, ZeroCountOp::Leading);
    1u128.checked_shl(bits.checked_sub(1)?.checked_sub(leading)?)
}

fn apply_zero_count(raw: u128, bits: u32, op: ZeroCountOp) -> u32 {
    match op {
        ZeroCountOp::Count => bits - raw.count_ones(),
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

fn integer_kind_hint_in_scope(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    depth: usize,
) -> Option<IntegerKind> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            syn::Lit::Int(i) => primitive_integer_kind(i.suffix()),
            _ => None,
        },
        Expr::Cast(cast) => integer_kind_from_type(&cast.ty),
        Expr::Path(path) => {
            if let Some((kind, _)) = primitive_assoc_const_path(path) {
                return Some(kind);
            }
            if let Some((kind, _)) = nonzero_assoc_const_expr(expr) {
                return Some(IntegerKind {
                    signed: kind.signed,
                    bits: kind.bits,
                });
            }
            if let Some(init) = fcx.scope().const_expr_for_path(&path.path) {
                return integer_kind_hint_in_scope(&init, fcx, depth + 1);
            }
            let name = simple_path_name(expr)?;
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .and_then(|init| integer_kind_hint_in_scope(init, fcx, depth + 1))
        }
        Expr::Unary(unary) => integer_kind_hint_in_scope(&unary.expr, fcx, depth + 1),
        Expr::Paren(paren) => integer_kind_hint_in_scope(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => integer_kind_hint_in_scope(&group.expr, fcx, depth + 1),
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect")
                && is_known_monadic_source(&call.receiver) =>
        {
            nonzero_new_integer_kind(&call.receiver)
                .or_else(|| integer_kind_hint_in_scope(&call.receiver, fcx, depth + 1))
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
