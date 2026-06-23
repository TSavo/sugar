// SPDX-License-Identifier: Apache-2.0
//
// Exact IEEE-754 literal method sugar for f32/f64 bit conversions.
//
// Recognition is lazy: it captures `to_bits` / `from_bits` source shapes and raw
// child expressions only. Desugar resolves the receiver/argument under the live
// scope and either emits the exact literal floor or propagates a named Hit.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{real_const, ConstValue, Sort, Term};
use syn::{Expr, ExprCall, ExprLit, ExprMethodCall, ExprPath, Lit, UnOp};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{
    const_fold_int_term, const_fold_u128_term, simple_path_name, strip_refs_groups, token_key,
    Desugared, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "float_literal_method",
    &["primitive_int", "call", "method"],
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::MethodCall(call) => recognize_method(call, fcx),
        Expr::Call(call) => recognize_call(call, fcx),
        _ => None,
    }
}

fn recognize_method(call: &ExprMethodCall, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if call.method != "to_bits" || !call.args.is_empty() {
        return None;
    }
    Some(Box::new(FloatLiteralMethodSugar::ToBits {
        receiver: (*call.receiver).clone(),
        let_inits: capture_let_inits(fcx),
        site: token_key(Expr::MethodCall(call.clone())),
    }))
}

fn recognize_call(call: &ExprCall, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if call.args.len() != 1 {
        return None;
    }
    let width = from_bits_width(&call.func)?;
    Some(Box::new(FloatLiteralMethodSugar::FromBits {
        width,
        bits: call.args[0].clone(),
        let_inits: capture_let_inits(fcx),
        site: token_key(Expr::Call(call.clone())),
    }))
}

enum FloatLiteralMethodSugar {
    ToBits {
        receiver: Expr,
        let_inits: BTreeMap<String, Expr>,
        site: String,
    },
    FromBits {
        width: FloatWidth,
        bits: Expr,
        let_inits: BTreeMap<String, Expr>,
        site: String,
    },
}

impl Sugar for FloatLiteralMethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            FloatLiteralMethodSugar::ToBits {
                receiver,
                let_inits,
                site,
            } => {
                let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
                let let_inits = merge_let_inits(&stable, let_inits);
                let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
                let value = match resolve_float(receiver, ctx, &fcx, 0, site) {
                    Ok(value) => value,
                    Err(outcome) => return outcome,
                };
                Outcome::Dug(Desugared::Term(value.to_bits_term()))
            }
            FloatLiteralMethodSugar::FromBits {
                width,
                bits,
                let_inits,
                site,
            } => {
                let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
                let let_inits = merge_let_inits(&stable, let_inits);
                let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
                let bits = match resolve_bits(bits, ctx, &fcx, site) {
                    Ok(bits) => bits,
                    Err(outcome) => return outcome,
                };
                let value = match bits_to_float(*width, bits, site) {
                    Ok(value) => value,
                    Err(outcome) => return outcome,
                };
                match value.to_real_term(site) {
                    Ok(term) => Outcome::Dug(Desugared::Term(term)),
                    Err(outcome) => outcome,
                }
            }
        }
    }
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

#[derive(Clone, Copy)]
enum FloatWidth {
    F32,
    F64,
}

#[derive(Clone, Copy)]
enum FloatValue {
    F32(f32),
    F64(f64),
}

impl FloatValue {
    fn to_bits_term(self) -> Rc<Term> {
        match self {
            FloatValue::F32(value) => int_width_term(i128::from(value.to_bits()), "u32"),
            FloatValue::F64(value) => int_width_term(i128::from(value.to_bits()), "u64"),
        }
    }

    fn to_real_term(self, site: &str) -> Result<Rc<Term>, Outcome> {
        match self {
            FloatValue::F32(value) => finite_float_real_term_f32(value, site),
            FloatValue::F64(value) => finite_float_real_term_f64(value, site),
        }
    }

    fn neg(self) -> Self {
        match self {
            FloatValue::F32(value) => FloatValue::F32(-value),
            FloatValue::F64(value) => FloatValue::F64(-value),
        }
    }
}

fn int_width_term(value: i128, sort: &str) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Int(value),
        sort: Sort {
            name: sort.to_string(),
        },
    })
}

fn finite_float_real_term_f32(value: f32, site: &str) -> Result<Rc<Term>, Outcome> {
    if value.is_nan() || value.is_infinite() {
        return Err(unsupported(format!(
            "float bit pattern is not expressible as a finite Real literal `{site}`"
        )));
    }
    if value == 0.0 && value.is_sign_negative() {
        return Err(unsupported(format!(
            "signed zero float literal remains an IEEE refinement `{site}`"
        )));
    }
    Ok(real_const(value.to_string()))
}

fn finite_float_real_term_f64(value: f64, site: &str) -> Result<Rc<Term>, Outcome> {
    if value.is_nan() || value.is_infinite() {
        return Err(unsupported(format!(
            "float bit pattern is not expressible as a finite Real literal `{site}`"
        )));
    }
    if value == 0.0 && value.is_sign_negative() {
        return Err(unsupported(format!(
            "signed zero float literal remains an IEEE refinement `{site}`"
        )));
    }
    Ok(real_const(value.to_string()))
}

fn resolve_float(
    expr: &Expr,
    ctx: &SugarCtx,
    fcx: &SugarBuildCtx,
    depth: usize,
    site: &str,
) -> Result<FloatValue, Outcome> {
    if depth > 8 {
        return Err(runtime_float(site));
    }
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Float(lit),
            ..
        }) => float_lit_value(lit, site),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            Ok(resolve_float(&unary.expr, ctx, fcx, depth + 1, site)?.neg())
        }
        Expr::Path(path) => {
            if let Some(value) = primitive_float_assoc_const(path, site)? {
                return Ok(value);
            }
            if let Some(init) = ctx.scope.const_expr_for_path(&path.path) {
                return resolve_float(&init, ctx, fcx, depth + 1, site);
            }
            let Some(name) = simple_path_name(expr) else {
                return Err(runtime_float(site));
            };
            if let Some(init) = ctx.scope.stable_let_binding_for_term(&name) {
                return resolve_float(init, ctx, fcx, depth + 1, site);
            }
            Err(runtime_float(site))
        }
        Expr::Call(call) => {
            let Some(width) = from_bits_width(&call.func) else {
                return Err(runtime_float(site));
            };
            if call.args.len() != 1 {
                return Err(runtime_float(site));
            }
            let bits = resolve_bits(&call.args[0], ctx, fcx, site)?;
            bits_to_float(width, bits, site)
        }
        Expr::Paren(paren) => resolve_float(&paren.expr, ctx, fcx, depth + 1, site),
        Expr::Group(group) => resolve_float(&group.expr, ctx, fcx, depth + 1, site),
        Expr::Reference(reference) => resolve_float(&reference.expr, ctx, fcx, depth + 1, site),
        _ => Err(runtime_float(site)),
    }
}

fn resolve_bits(
    expr: &Expr,
    ctx: &SugarCtx,
    fcx: &SugarBuildCtx,
    site: &str,
) -> Result<u128, Outcome> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Dug(d) => {
            let Some(term) = d.into_term() else {
                return Err(runtime_float(site));
            };
            const_fold_u128_term(&term)
                .or_else(|| const_fold_int_term(&term).and_then(|n| u128::try_from(n).ok()))
                .ok_or_else(|| runtime_float(site))
        }
        Outcome::Hit(effect) => Err(Outcome::Hit(effect)),
    }
}

fn bits_to_float(width: FloatWidth, bits: u128, site: &str) -> Result<FloatValue, Outcome> {
    Ok(match width {
        FloatWidth::F32 => {
            let bits = u32::try_from(bits).map_err(|_| runtime_float(site))?;
            FloatValue::F32(f32::from_bits(bits))
        }
        FloatWidth::F64 => {
            let bits = u64::try_from(bits).map_err(|_| runtime_float(site))?;
            FloatValue::F64(f64::from_bits(bits))
        }
    })
}

fn float_lit_value(lit: &syn::LitFloat, site: &str) -> Result<FloatValue, Outcome> {
    let digits = lit.base10_digits().replace('_', "");
    match lit.suffix() {
        "f32" => digits
            .parse::<f32>()
            .map(FloatValue::F32)
            .map_err(|_| runtime_float(site)),
        "f64" => digits
            .parse::<f64>()
            .map(FloatValue::F64)
            .map_err(|_| runtime_float(site)),
        _ => Err(unsupported(format!(
            "float literal bit model requires explicit f32/f64 width `{site}`"
        ))),
    }
}

fn from_bits_width(func: &Expr) -> Option<FloatWidth> {
    let Expr::Path(ExprPath { qself, path, .. }) = strip_refs_groups(func) else {
        return None;
    };
    let last = path.segments.last()?;
    if last.ident != "from_bits" {
        return None;
    }
    if let Some(qself) = qself {
        return width_from_type(&qself.ty);
    }
    if path.segments.len() != 2 {
        return None;
    }
    width_from_ident(&path.segments[0].ident.to_string())
}

fn primitive_float_assoc_const(path: &ExprPath, site: &str) -> Result<Option<FloatValue>, Outcome> {
    if path.qself.is_some() || path.path.segments.len() != 2 {
        return Ok(None);
    }
    let ty = path.path.segments[0].ident.to_string();
    let konst = path.path.segments[1].ident.to_string();
    let value = match (ty.as_str(), konst.as_str()) {
        ("f32", "MIN") => FloatValue::F32(f32::MIN),
        ("f32", "MAX") => FloatValue::F32(f32::MAX),
        ("f32", "EPSILON") => FloatValue::F32(f32::EPSILON),
        ("f32", "MIN_POSITIVE") => FloatValue::F32(f32::MIN_POSITIVE),
        ("f32", "INFINITY") => FloatValue::F32(f32::INFINITY),
        ("f32", "NEG_INFINITY") => FloatValue::F32(f32::NEG_INFINITY),
        ("f32", "NAN") => FloatValue::F32(f32::NAN),
        ("f64", "MIN") => FloatValue::F64(f64::MIN),
        ("f64", "MAX") => FloatValue::F64(f64::MAX),
        ("f64", "EPSILON") => FloatValue::F64(f64::EPSILON),
        ("f64", "MIN_POSITIVE") => FloatValue::F64(f64::MIN_POSITIVE),
        ("f64", "INFINITY") => FloatValue::F64(f64::INFINITY),
        ("f64", "NEG_INFINITY") => FloatValue::F64(f64::NEG_INFINITY),
        ("f64", "NAN") => FloatValue::F64(f64::NAN),
        ("f16" | "f128", _) => {
            return Err(unsupported(format!(
                "f16/f128 float bit model is not expressible `{site}`"
            )));
        }
        _ => return Ok(None),
    };
    Ok(Some(value))
}

fn width_from_type(ty: &syn::Type) -> Option<FloatWidth> {
    let syn::Type::Path(path) = ty else {
        return None;
    };
    width_from_ident(&path.path.segments.last()?.ident.to_string())
}

fn width_from_ident(ident: &str) -> Option<FloatWidth> {
    match ident {
        "f32" => Some(FloatWidth::F32),
        "f64" => Some(FloatWidth::F64),
        _ => None,
    }
}

fn runtime_float(site: &str) -> Outcome {
    unsupported(format!("runtime float operand, not literal `{site}`"))
}

fn unsupported(reason: String) -> Outcome {
    Outcome::Hit(Effect::Unsupported { reason })
}
