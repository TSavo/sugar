// SPDX-License-Identifier: Apache-2.0
//
// IEEE f32/f64 literal floor.
//
// This is the specialization that owns float representation semantics. Callers such as
// `to_bits` and `integer_decode` do not inspect receiver syntax; they reduce this floor
// and dispatch a visitor. If the source is not a literal-determined f32/f64 value, the
// floor emits the named runtime-float boundary. If the value is IEEE-shaped but outside
// the modeled stable f32/f64 floor, the floor emits the named IEEE refinement boundary.

use std::collections::BTreeSet;
use std::rc::Rc;

use sugar_ir_symbolic::{ConstValue, Sort, Term};
use syn::{
    Expr, ExprCall, ExprLit, ExprMethodCall, ExprPath, FnArg, ForeignItem, Item, ItemFn, Lit, Pat,
    ReturnType, Stmt, UnOp,
};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::format::{ldexp_f32, ldexp_f64};
use crate::{
    const_fold_int_term, const_fold_u128_term, real_const, simple_call_name, simple_path_name,
    strip_refs_groups, token_key, Desugared, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) type FloatWidthScope = std::collections::BTreeMap<String, IeeeFloatWidth>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum IeeeFloatWidth {
    F32,
    F64,
}

pub(crate) trait IeeeFloatWidthVisitor {
    type Output;

    fn visit_f32(self) -> Self::Output;
    fn visit_f64(self) -> Self::Output;
}

pub(crate) trait IeeeFloatWidthAccept {
    fn accept_ieee_float_width<V: IeeeFloatWidthVisitor>(self, visitor: V) -> V::Output;
}

impl IeeeFloatWidthAccept for IeeeFloatWidth {
    fn accept_ieee_float_width<V: IeeeFloatWidthVisitor>(self, visitor: V) -> V::Output {
        match self {
            IeeeFloatWidth::F32 => visitor.visit_f32(),
            IeeeFloatWidth::F64 => visitor.visit_f64(),
        }
    }
}

pub(crate) struct IeeeFloatWidthNameVisitor;

impl IeeeFloatWidthVisitor for IeeeFloatWidthNameVisitor {
    type Output = &'static str;

    fn visit_f32(self) -> Self::Output {
        "f32"
    }

    fn visit_f64(self) -> Self::Output {
        "f64"
    }
}

#[derive(Clone, Copy)]
pub(crate) enum IeeeFloatValue {
    F32(f32),
    F64(f64),
}

impl IeeeFloatValue {
    pub(crate) fn to_bits_term(self) -> Rc<Term> {
        match self {
            IeeeFloatValue::F32(value) => int_width_term(i128::from(value.to_bits()), "u32"),
            IeeeFloatValue::F64(value) => int_width_term(i128::from(value.to_bits()), "u64"),
        }
    }

    pub(crate) fn to_real_term(self, site: &str) -> Result<Rc<Term>, Outcome> {
        match self {
            IeeeFloatValue::F32(value) => finite_float_real_term_f32(value, site),
            IeeeFloatValue::F64(value) => finite_float_real_term_f64(value, site),
        }
    }

    pub(crate) fn from_bits(
        width: IeeeFloatWidth,
        bits: u128,
        _site: &str,
    ) -> Result<Self, Outcome> {
        Ok(match width {
            IeeeFloatWidth::F32 => {
                let bits = u32::try_from(bits).unwrap_or_else(|_| {
                    float_floor_gap("f32::from_bits received a non-u32 bit pattern")
                });
                IeeeFloatValue::F32(f32::from_bits(bits))
            }
            IeeeFloatWidth::F64 => {
                let bits = u64::try_from(bits).unwrap_or_else(|_| {
                    float_floor_gap("f64::from_bits received a non-u64 bit pattern")
                });
                IeeeFloatValue::F64(f64::from_bits(bits))
            }
        })
    }

    pub(crate) fn integer_decode(self) -> (u64, i16, i8) {
        match self {
            IeeeFloatValue::F32(value) => integer_decode_f32(value),
            IeeeFloatValue::F64(value) => integer_decode_f64(value),
        }
    }

    pub(crate) fn into_width_term(self, target: IeeeFloatWidth, site: &str) -> Rc<Term> {
        self.into_width(target, site).term()
    }

    fn into_width(self, target: IeeeFloatWidth, site: &str) -> Self {
        match (self, target) {
            (IeeeFloatValue::F32(value), IeeeFloatWidth::F32) => IeeeFloatValue::F32(value),
            (IeeeFloatValue::F32(value), IeeeFloatWidth::F64) => {
                IeeeFloatValue::F64(f64::from(value))
            }
            (IeeeFloatValue::F64(value), IeeeFloatWidth::F64) => IeeeFloatValue::F64(value),
            (IeeeFloatValue::F64(_), IeeeFloatWidth::F32) => {
                let target = target.accept_ieee_float_width(IeeeFloatWidthNameVisitor);
                panic!("std Into is not implemented from `f64` to `{target}` for `{site}`")
            }
        }
    }

    pub(crate) fn neg(self) -> Self {
        match self {
            IeeeFloatValue::F32(value) => IeeeFloatValue::F32(-value),
            IeeeFloatValue::F64(value) => IeeeFloatValue::F64(-value),
        }
    }

    fn term(self) -> Rc<Term> {
        match self {
            IeeeFloatValue::F32(value) => Rc::new(Term::Ctor {
                name: FLOAT_F32_CTOR.to_string(),
                args: vec![int_width_term(i128::from(value.to_bits()), "u32")],
            }),
            IeeeFloatValue::F64(value) => Rc::new(Term::Ctor {
                name: FLOAT_F64_CTOR.to_string(),
                args: vec![int_width_term(i128::from(value.to_bits()), "u64")],
            }),
        }
    }
}

pub(crate) trait IeeeFloatVisitor {
    type Output;

    fn visit_float(self, value: IeeeFloatValue) -> Self::Output;
    fn visit_non_float(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait IeeeFloatAccept {
    fn accept_ieee_float<V: IeeeFloatVisitor>(&self, visitor: V) -> V::Output;
}

impl IeeeFloatAccept for Rc<Term> {
    fn accept_ieee_float<V: IeeeFloatVisitor>(&self, visitor: V) -> V::Output {
        match self.as_ref() {
            Term::Ctor { name, args } if name == FLOAT_F32_CTOR && args.len() == 1 => {
                let Some(bits) = const_fold_u128_term(&args[0])
                    .or_else(|| const_fold_int_term(&args[0]).and_then(|n| u128::try_from(n).ok()))
                else {
                    return visitor.visit_non_float(self);
                };
                let Ok(bits) = u32::try_from(bits) else {
                    return visitor.visit_non_float(self);
                };
                visitor.visit_float(IeeeFloatValue::F32(f32::from_bits(bits)))
            }
            Term::Ctor { name, args } if name == FLOAT_F64_CTOR && args.len() == 1 => {
                let Some(bits) = const_fold_u128_term(&args[0])
                    .or_else(|| const_fold_int_term(&args[0]).and_then(|n| u128::try_from(n).ok()))
                else {
                    return visitor.visit_non_float(self);
                };
                let Ok(bits) = u64::try_from(bits) else {
                    return visitor.visit_non_float(self);
                };
                visitor.visit_float(IeeeFloatValue::F64(f64::from_bits(bits)))
            }
            _ => visitor.visit_non_float(self),
        }
    }
}

const NAN_COMPARISON_SCAN_CAP: usize = 64;

pub(crate) fn nan_comparison_effect(
    owner: &str,
    lhs: &Expr,
    rhs: &Expr,
    ctx: &SugarCtx,
) -> Option<Effect> {
    let mut seen = BTreeSet::new();
    let boundary = nan_comparison_boundary(lhs, ctx, &mut seen, 0).or_else(|| {
        seen.clear();
        nan_comparison_boundary(rhs, ctx, &mut seen, 0)
    })?;
    Some(Effect::FloatIeeeRefinement {
        reason: format!(
            "{owner}: NaN comparison `{boundary}` uses Rust float PartialEq/PartialOrd \
             semantics, not ordinary total-order/equality semantics; refused"
        ),
    })
}

fn nan_comparison_boundary(
    expr: &Expr,
    ctx: &SugarCtx,
    seen: &mut BTreeSet<String>,
    depth: usize,
) -> Option<String> {
    if depth > NAN_COMPARISON_SCAN_CAP {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) => {
            let site = token_key(expr.clone());
            if primitive_float_nan_assoc_const(path, &site) {
                return Some(site);
            }
            if let Some(init) = ctx.scope.const_expr_for_path(&path.path) {
                if let Some(boundary) = nan_comparison_boundary(&init, ctx, seen, depth + 1) {
                    return Some(boundary);
                }
            }
            let name = simple_path_name(expr)?;
            if !seen.insert(name.clone()) {
                return None;
            }
            let boundary = ctx
                .scope
                .stable_let_binding_for_term(&name)
                .and_then(|init| nan_comparison_boundary(init, ctx, seen, depth + 1));
            seen.remove(&name);
            boundary
        }
        Expr::Array(array) => array
            .elems
            .iter()
            .find_map(|elem| nan_comparison_boundary(elem, ctx, seen, depth + 1)),
        Expr::Tuple(tuple) => tuple
            .elems
            .iter()
            .find_map(|elem| nan_comparison_boundary(elem, ctx, seen, depth + 1)),
        Expr::Repeat(repeat) => nan_comparison_boundary(&repeat.expr, ctx, seen, depth + 1),
        Expr::Reference(reference) => {
            nan_comparison_boundary(&reference.expr, ctx, seen, depth + 1)
        }
        Expr::Cast(cast) => nan_comparison_boundary(&cast.expr, ctx, seen, depth + 1),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            nan_comparison_boundary(&unary.expr, ctx, seen, depth + 1)
        }
        Expr::Block(block) => nan_comparison_block_tail(&block.block.stmts)
            .and_then(|tail| nan_comparison_boundary(tail, ctx, seen, depth + 1)),
        _ => None,
    }
}

fn nan_comparison_block_tail(stmts: &[Stmt]) -> Option<&Expr> {
    match stmts.last()? {
        Stmt::Expr(expr, None) => Some(expr),
        _ => None,
    }
}

fn primitive_float_nan_assoc_const(path: &ExprPath, site: &str) -> bool {
    match primitive_float_assoc_const(path, site) {
        Some(IeeeFloatSource::Value(IeeeFloatValue::F32(value))) => value.is_nan(),
        Some(IeeeFloatSource::Value(IeeeFloatValue::F64(value))) => value.is_nan(),
        _ => false,
    }
}

const FLOAT_F32_CTOR: &str = "float:f32";
const FLOAT_F64_CTOR: &str = "float:f64";

enum IeeeFloatSource {
    Value(IeeeFloatValue),
    Neg(SugarBody<crate::sugar::factory::IeeeFloatFloor>),
    FromBits {
        width: IeeeFloatWidth,
        bits: SugarBody<TermFloor>,
        site: String,
    },
    Ldexp {
        width: IeeeFloatWidth,
        mantissa: SugarBody<crate::sugar::factory::IeeeFloatFloor>,
        exponent: SugarBody<TermFloor>,
        site: String,
    },
    Runtime {
        boundary: String,
    },
    IeeeRefinement {
        boundary: String,
        reason: String,
    },
}

struct IeeeFloatSugar {
    source: IeeeFloatSource,
}

impl Sugar for IeeeFloatSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.source {
            IeeeFloatSource::Value(value) => Outcome::Complete(Desugared::Term(value.term())),
            IeeeFloatSource::Neg(inner) => {
                let value = match reduce_ieee_float(inner, ctx) {
                    Ok(value) => value,
                    Err(outcome) => return outcome,
                };
                Outcome::Complete(Desugared::Term(value.neg().term()))
            }
            IeeeFloatSource::FromBits { width, bits, site } => {
                let bits = match reduce_bits(bits, ctx, site, "from_bits") {
                    Ok(bits) => bits,
                    Err(outcome) => return outcome,
                };
                let value = match IeeeFloatValue::from_bits(*width, bits, site) {
                    Ok(value) => value,
                    Err(outcome) => return outcome,
                };
                Outcome::Complete(Desugared::Term(value.term()))
            }
            IeeeFloatSource::Ldexp {
                width,
                mantissa,
                exponent,
                site,
            } => {
                let mantissa = match reduce_ieee_float(mantissa, ctx) {
                    Ok(value) => value,
                    Err(outcome) => return outcome,
                };
                let exponent = match reduce_i32(exponent, ctx, site, "ldexp") {
                    Ok(exponent) => exponent,
                    Err(outcome) => return outcome,
                };
                let value = match (width, mantissa) {
                    (IeeeFloatWidth::F32, IeeeFloatValue::F32(value)) => {
                        IeeeFloatValue::F32(ldexp_f32(value, exponent))
                    }
                    (IeeeFloatWidth::F64, IeeeFloatValue::F64(value)) => {
                        IeeeFloatValue::F64(ldexp_f64(value, exponent))
                    }
                    _ => float_floor_gap("ldexp width and mantissa floor diverged"),
                };
                Outcome::Complete(Desugared::Term(value.term()))
            }
            IeeeFloatSource::Runtime { boundary } => runtime_float(boundary),
            IeeeFloatSource::IeeeRefinement { boundary, reason } => {
                ieee_refinement(boundary, reason.clone())
            }
        }
    }
}

pub(crate) fn build_ieee_float(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    width_hint: Option<IeeeFloatWidth>,
    operation: &'static str,
) -> Box<dyn Sugar> {
    Box::new(IeeeFloatSugar {
        source: build_ieee_float_source(expr, fcx, width_hint, operation, 0),
    })
}

fn build_ieee_float_source(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    width_hint: Option<IeeeFloatWidth>,
    operation: &'static str,
    depth: usize,
) -> IeeeFloatSource {
    if depth > 8 {
        return runtime_source(expr, operation);
    }
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => literal_source(lit, width_hint, operation),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            IeeeFloatSource::Neg(SugarBody::from_node(Box::new(IeeeFloatSugar {
                source: build_ieee_float_source(&unary.expr, fcx, width_hint, operation, depth + 1),
            })))
        }
        Expr::Path(path) => path_source(path, expr, fcx, width_hint, operation, depth),
        Expr::Call(call) => call_source(call, expr, fcx, width_hint, operation, depth),
        Expr::Paren(paren) => {
            build_ieee_float_source(&paren.expr, fcx, width_hint, operation, depth + 1)
        }
        Expr::Group(group) => {
            build_ieee_float_source(&group.expr, fcx, width_hint, operation, depth + 1)
        }
        Expr::Reference(reference) if reference.mutability.is_none() => {
            build_ieee_float_source(&reference.expr, fcx, width_hint, operation, depth + 1)
        }
        _ => runtime_source(expr, operation),
    }
}

fn literal_source(
    lit: &ExprLit,
    width_hint: Option<IeeeFloatWidth>,
    operation: &'static str,
) -> IeeeFloatSource {
    let site = token_key(Expr::Lit(lit.clone()));
    let Some((digits, suffix)) = float_lit_digits_suffix(&lit.lit) else {
        return runtime_source_from_site(site, operation);
    };
    let width = match suffix.as_str() {
        "f32" => Some(IeeeFloatWidth::F32),
        "f64" => Some(IeeeFloatWidth::F64),
        "f16" | "f128" => {
            return ieee_refinement_source(
                site.clone(),
                format!("f16/f128 float bit model is not expressible `{site}`"),
            );
        }
        "" => width_hint,
        _ => None,
    };
    let Some(width) = width else {
        return runtime_source_from_site(site, operation);
    };
    let digits = digits.replace('_', "");
    match width {
        IeeeFloatWidth::F32 => digits
            .parse::<f32>()
            .map(IeeeFloatValue::F32)
            .map(IeeeFloatSource::Value)
            .unwrap_or_else(|_| runtime_source_from_site(site, operation)),
        IeeeFloatWidth::F64 => digits
            .parse::<f64>()
            .map(IeeeFloatValue::F64)
            .map(IeeeFloatSource::Value)
            .unwrap_or_else(|_| runtime_source_from_site(site, operation)),
    }
}

fn path_source(
    path: &ExprPath,
    expr: &Expr,
    fcx: &SugarBuildCtx,
    width_hint: Option<IeeeFloatWidth>,
    operation: &'static str,
    depth: usize,
) -> IeeeFloatSource {
    let site = token_key(expr.clone());
    if let Some(value) = primitive_float_assoc_const(path, &site) {
        return value;
    }
    if let Some(init) = fcx.scope().const_expr_for_path(&path.path) {
        return build_ieee_float_source(&init, fcx, width_hint, operation, depth + 1);
    }
    if let Some(name) = simple_path_name(expr) {
        if let Some(init) = fcx.let_inits().get(&name) {
            return build_ieee_float_source(init, fcx, width_hint, operation, depth + 1);
        }
        if let Some(init) = fcx.scope().stable_let_binding_for_term(&name) {
            return build_ieee_float_source(init, fcx, width_hint, operation, depth + 1);
        }
    }
    runtime_source(expr, operation)
}

fn call_source(
    call: &ExprCall,
    expr: &Expr,
    fcx: &SugarBuildCtx,
    width_hint: Option<IeeeFloatWidth>,
    operation: &'static str,
    depth: usize,
) -> IeeeFloatSource {
    let site = token_key(expr.clone());
    if let Some(width) = from_bits_width(&call.func) {
        if call.args.len() != 1 {
            return runtime_source(expr, operation);
        }
        return IeeeFloatSource::FromBits {
            width,
            bits: SugarBody::term(&call.args[0], fcx),
            site,
        };
    }
    if let Some((width, mantissa, exponent)) = ldexp_call_parts(call, fcx) {
        return IeeeFloatSource::Ldexp {
            width,
            mantissa: SugarBody::from_node(Box::new(IeeeFloatSugar {
                source: build_ieee_float_source(mantissa, fcx, Some(width), operation, depth + 1),
            })),
            exponent: SugarBody::term(exponent, fcx),
            site,
        };
    }
    if width_hint.is_some() {
        return runtime_source_from_site(site, operation);
    }
    runtime_source(expr, operation)
}

fn ldexp_call_parts<'a>(
    call: &'a ExprCall,
    fcx: &SugarBuildCtx,
) -> Option<(IeeeFloatWidth, &'a Expr, &'a Expr)> {
    let name = simple_call_name(call)?;
    if call.args.len() != 2 || !visible_ldexp_helper_matches(fcx.scope(), &name) {
        return None;
    }
    let width = match name.as_str() {
        "ldexp_f32" => IeeeFloatWidth::F32,
        "ldexp_f64" => IeeeFloatWidth::F64,
        _ => return None,
    };
    Some((width, call.args.first()?, call.args.iter().nth(1)?))
}

fn reduce_ieee_float(
    child: &SugarBody<crate::sugar::factory::IeeeFloatFloor>,
    ctx: &SugarCtx,
) -> Result<IeeeFloatValue, Outcome> {
    match child.reduce(ctx) {
        Outcome::Complete(desugared) => {
            let Some(term) = desugared.into_term() else {
                float_floor_gap("IEEE float child completed as non-term");
            };
            term.accept_ieee_float(RequiredIeeeFloatVisitor)
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

struct RequiredIeeeFloatVisitor;

impl IeeeFloatVisitor for RequiredIeeeFloatVisitor {
    type Output = Result<IeeeFloatValue, Outcome>;

    fn visit_float(self, value: IeeeFloatValue) -> Self::Output {
        Ok(value)
    }

    fn visit_non_float(self, _term: &Rc<Term>) -> Self::Output {
        float_floor_gap("IEEE float body did not reduce to an IEEE float floor")
    }
}

pub(crate) fn reduce_bits(
    bits: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
    site: &str,
    _operation: &str,
) -> Result<u128, Outcome> {
    match bits.reduce(ctx) {
        Outcome::Complete(desugared) => {
            let Some(term) = desugared.into_term() else {
                float_floor_gap("float bit source completed as non-term");
            };
            const_fold_u128_term(&term)
                .or_else(|| const_fold_int_term(&term).and_then(|n| u128::try_from(n).ok()))
                .ok_or_else(|| runtime_float(site))
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn reduce_i32(
    exponent: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
    site: &str,
    _operation: &str,
) -> Result<i32, Outcome> {
    let value = match exponent.reduce(ctx) {
        Outcome::Complete(desugared) => {
            let Some(term) = desugared.into_term() else {
                float_floor_gap("float exponent source completed as non-term");
            };
            const_fold_int_term(&term).ok_or_else(|| runtime_float(site))?
        }
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    i32::try_from(value).map_err(|_| runtime_float(site))
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
        return Err(ieee_refinement(
            site,
            format!("float bit pattern is not expressible as a finite Real literal `{site}`"),
        ));
    }
    if value == 0.0 && value.is_sign_negative() {
        return Err(ieee_refinement(
            site,
            format!("signed zero float literal remains an IEEE refinement `{site}`"),
        ));
    }
    Ok(real_const(value.to_string()))
}

fn finite_float_real_term_f64(value: f64, site: &str) -> Result<Rc<Term>, Outcome> {
    if value.is_nan() || value.is_infinite() {
        return Err(ieee_refinement(
            site,
            format!("float bit pattern is not expressible as a finite Real literal `{site}`"),
        ));
    }
    if value == 0.0 && value.is_sign_negative() {
        return Err(ieee_refinement(
            site,
            format!("signed zero float literal remains an IEEE refinement `{site}`"),
        ));
    }
    Ok(real_const(value.to_string()))
}

fn float_lit_digits_suffix(lit: &Lit) -> Option<(String, String)> {
    match lit {
        Lit::Float(f) => Some((f.base10_digits().to_string(), f.suffix().to_string())),
        Lit::Int(i) if matches!(i.suffix(), "f16" | "f32" | "f64" | "f128") => {
            Some((i.base10_digits().to_string(), i.suffix().to_string()))
        }
        _ => None,
    }
}

pub(crate) fn from_bits_width(func: &Expr) -> Option<IeeeFloatWidth> {
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

pub(crate) fn stable_width_from_type_key(ty: &str) -> Option<IeeeFloatWidth> {
    ty.rsplit("::").next().and_then(width_from_ident)
}

pub(crate) fn stable_width_from_method_turbofish(call: &ExprMethodCall) -> Option<IeeeFloatWidth> {
    if call.method != "parse" {
        return None;
    }
    let args = call.turbofish.as_ref()?;
    stable_width_from_angle_args(args)
}

pub(crate) fn unstable_width_from_method_turbofish(call: &ExprMethodCall) -> Option<&'static str> {
    if call.method != "parse" {
        return None;
    }
    let args = call.turbofish.as_ref()?;
    unstable_width_from_angle_args(args)
}

pub(crate) fn stable_width_from_method_name(method: &str) -> Option<IeeeFloatWidth> {
    if method.ends_with("_f32") {
        Some(IeeeFloatWidth::F32)
    } else if method.ends_with("_f64") {
        Some(IeeeFloatWidth::F64)
    } else {
        None
    }
}

pub(crate) fn unstable_width_from_method_name(method: &str) -> Option<&'static str> {
    if method.ends_with("_f16") {
        Some("f16")
    } else if method.ends_with("_f128") {
        Some("f128")
    } else {
        None
    }
}

pub(crate) fn stable_width_from_type(ty: &syn::Type) -> Option<IeeeFloatWidth> {
    match ty {
        syn::Type::Path(path) => stable_width_from_path(&path.path),
        syn::Type::Paren(paren) => stable_width_from_type(&paren.elem),
        syn::Type::Group(group) => stable_width_from_type(&group.elem),
        _ => None,
    }
}

pub(crate) fn stable_width_from_path(path: &syn::Path) -> Option<IeeeFloatWidth> {
    for segment in &path.segments {
        if let Some(width) = width_from_ident(&segment.ident.to_string()) {
            return Some(width);
        }
    }
    None
}

pub(crate) fn unstable_width_from_type(ty: &syn::Type) -> Option<&'static str> {
    match ty {
        syn::Type::Path(path) => unstable_width_from_path(&path.path),
        syn::Type::Paren(paren) => unstable_width_from_type(&paren.elem),
        syn::Type::Group(group) => unstable_width_from_type(&group.elem),
        _ => None,
    }
}

pub(crate) fn stable_width_from_suffix(suffix: &str) -> Option<IeeeFloatWidth> {
    match suffix {
        "f32" => Some(IeeeFloatWidth::F32),
        "f64" => Some(IeeeFloatWidth::F64),
        _ => None,
    }
}

pub(crate) fn unstable_width_from_suffix(suffix: &str) -> Option<&'static str> {
    match suffix {
        "f16" => Some("f16"),
        "f128" => Some("f128"),
        _ => None,
    }
}

fn stable_width_from_angle_args(
    args: &syn::AngleBracketedGenericArguments,
) -> Option<IeeeFloatWidth> {
    if args.args.len() != 1 {
        return None;
    }
    let Some(syn::GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    stable_width_from_type(ty)
}

fn unstable_width_from_angle_args(
    args: &syn::AngleBracketedGenericArguments,
) -> Option<&'static str> {
    if args.args.len() != 1 {
        return None;
    }
    let Some(syn::GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    unstable_width_from_type(ty)
}

pub(crate) fn unstable_width_from_path(path: &syn::Path) -> Option<&'static str> {
    for segment in &path.segments {
        match segment.ident.to_string().as_str() {
            "f16" => return Some("f16"),
            "f128" => return Some("f128"),
            _ => {}
        }
    }
    None
}

fn primitive_float_assoc_const(path: &ExprPath, site: &str) -> Option<IeeeFloatSource> {
    let (ty, konst) = if let Some(qself) = &path.qself {
        let konst = path
            .path
            .segments
            .last()
            .map(|segment| segment.ident.to_string())?;
        let width = primitive_float_type_name(&qself.ty)?;
        (width, konst)
    } else {
        if path.path.segments.len() != 2 {
            return None;
        }
        (
            path.path.segments[0].ident.to_string(),
            path.path.segments[1].ident.to_string(),
        )
    };
    let value = match (ty.as_str(), konst.as_str()) {
        ("f32", "MIN") => IeeeFloatValue::F32(f32::MIN),
        ("f32", "MAX") => IeeeFloatValue::F32(f32::MAX),
        ("f32", "EPSILON") => IeeeFloatValue::F32(f32::EPSILON),
        ("f32", "MIN_POSITIVE") => IeeeFloatValue::F32(f32::MIN_POSITIVE),
        ("f32", "INFINITY") => IeeeFloatValue::F32(f32::INFINITY),
        ("f32", "NEG_INFINITY") => IeeeFloatValue::F32(f32::NEG_INFINITY),
        ("f32", "NAN") => IeeeFloatValue::F32(f32::NAN),
        ("f32", "NEG_NAN") => IeeeFloatValue::F32(-f32::NAN),
        ("f64", "MIN") => IeeeFloatValue::F64(f64::MIN),
        ("f64", "MAX") => IeeeFloatValue::F64(f64::MAX),
        ("f64", "EPSILON") => IeeeFloatValue::F64(f64::EPSILON),
        ("f64", "MIN_POSITIVE") => IeeeFloatValue::F64(f64::MIN_POSITIVE),
        ("f64", "INFINITY") => IeeeFloatValue::F64(f64::INFINITY),
        ("f64", "NEG_INFINITY") => IeeeFloatValue::F64(f64::NEG_INFINITY),
        ("f64", "NAN") => IeeeFloatValue::F64(f64::NAN),
        ("f64", "NEG_NAN") => IeeeFloatValue::F64(-f64::NAN),
        ("f16" | "f128", _) => {
            return Some(ieee_refinement_source(
                site.to_string(),
                format!("f16/f128 float bit model is not expressible `{site}`"),
            ));
        }
        _ => return None,
    };
    Some(IeeeFloatSource::Value(value))
}

fn primitive_float_type_name(ty: &syn::Type) -> Option<String> {
    let syn::Type::Path(path) = ty else {
        return None;
    };
    Some(path.path.segments.last()?.ident.to_string())
}

fn width_from_type(ty: &syn::Type) -> Option<IeeeFloatWidth> {
    stable_width_from_type(ty)
}

fn width_from_ident(ident: &str) -> Option<IeeeFloatWidth> {
    match ident {
        "f32" => Some(IeeeFloatWidth::F32),
        "f64" => Some(IeeeFloatWidth::F64),
        _ => None,
    }
}

fn visible_ldexp_helper_matches(scope: &crate::TemporalScope, name: &str) -> bool {
    let Some(helper) = scope.fn_registry().lookup(name) else {
        return false;
    };
    match name {
        "ldexp_f32" => ldexp_f32_helper_matches(&helper),
        "ldexp_f64" => ldexp_f64_helper_matches(&helper),
        _ => false,
    }
}

fn ldexp_f32_helper_matches(helper: &ItemFn) -> bool {
    let Some((a, b)) = two_simple_param_names(helper) else {
        return false;
    };
    if !returns_type(helper, "f32") {
        return false;
    }
    let [Stmt::Expr(expr, None)] = helper.block.stmts.as_slice() else {
        return false;
    };
    let Expr::Cast(ret_cast) = strip_refs_groups(expr) else {
        return false;
    };
    if !type_is_ident(&ret_cast.ty, "f32") {
        return false;
    }
    let Expr::Call(call) = strip_refs_groups(&ret_cast.expr) else {
        return false;
    };
    if simple_call_name(call).as_deref() != Some("ldexp_f64") || call.args.len() != 2 {
        return false;
    }
    let Some(first_arg) = call.args.first() else {
        return false;
    };
    let Some(second_arg) = call.args.iter().nth(1) else {
        return false;
    };
    let Expr::Cast(arg_cast) = strip_refs_groups(first_arg) else {
        return false;
    };
    type_is_ident(&arg_cast.ty, "f64")
        && expr_is_path_ident(&arg_cast.expr, &a)
        && expr_is_path_ident(second_arg, &b)
}

fn ldexp_f64_helper_matches(helper: &ItemFn) -> bool {
    let Some((a, b)) = two_simple_param_names(helper) else {
        return false;
    };
    if !returns_type(helper, "f64") {
        return false;
    }
    let mut has_foreign_ldexp = false;
    let mut has_return_call = false;
    for stmt in &helper.block.stmts {
        match stmt {
            Stmt::Item(Item::ForeignMod(foreign)) => {
                has_foreign_ldexp |= foreign
                    .items
                    .iter()
                    .any(|item| matches!(item, ForeignItem::Fn(f) if f.sig.ident == "ldexp"));
            }
            Stmt::Expr(expr, None) => {
                has_return_call |= unsafe_block_returns_ldexp_call(expr, &a, &b);
            }
            _ => {}
        }
    }
    has_foreign_ldexp && has_return_call
}

fn unsafe_block_returns_ldexp_call(expr: &Expr, a: &str, b: &str) -> bool {
    let Expr::Unsafe(unsafe_expr) = strip_refs_groups(expr) else {
        return false;
    };
    let [Stmt::Expr(ret, None)] = unsafe_expr.block.stmts.as_slice() else {
        return false;
    };
    let Expr::Call(call) = strip_refs_groups(ret) else {
        return false;
    };
    simple_call_name(call).as_deref() == Some("ldexp")
        && call.args.len() == 2
        && expr_is_path_ident(call.args.first().unwrap(), a)
        && expr_is_path_ident(call.args.iter().nth(1).unwrap(), b)
}

fn two_simple_param_names(helper: &ItemFn) -> Option<(String, String)> {
    let mut inputs = helper.sig.inputs.iter();
    let a = simple_fn_arg_name(inputs.next()?)?;
    let b = simple_fn_arg_name(inputs.next()?)?;
    if inputs.next().is_some() {
        return None;
    }
    Some((a, b))
}

fn simple_fn_arg_name(arg: &FnArg) -> Option<String> {
    let FnArg::Typed(typed) = arg else {
        return None;
    };
    let Pat::Ident(pat) = typed.pat.as_ref() else {
        return None;
    };
    Some(pat.ident.to_string())
}

fn returns_type(helper: &ItemFn, ty: &str) -> bool {
    matches!(&helper.sig.output, ReturnType::Type(_, ret) if type_is_ident(ret, ty))
}

fn type_is_ident(ty: &syn::Type, ident: &str) -> bool {
    matches!(ty, syn::Type::Path(path) if path.qself.is_none() && path.path.is_ident(ident))
}

fn expr_is_path_ident(expr: &Expr, ident: &str) -> bool {
    matches!(strip_refs_groups(expr), Expr::Path(path) if path.qself.is_none() && path.path.is_ident(ident))
}

fn integer_decode_f32(f: f32) -> (u64, i16, i8) {
    let bits: u32 = f.to_bits();
    let sign: i8 = if bits >> 31 == 0 { 1 } else { -1 };
    let mut exponent: i16 = ((bits >> 23) & 0xff) as i16;
    let mantissa = if exponent == 0 {
        (bits & 0x7f_ffff) << 1
    } else {
        (bits & 0x7f_ffff) | 0x80_0000
    };
    exponent -= 127 + 23;
    (u64::from(mantissa), exponent, sign)
}

fn integer_decode_f64(f: f64) -> (u64, i16, i8) {
    let bits: u64 = f.to_bits();
    let sign: i8 = if bits >> 63 == 0 { 1 } else { -1 };
    let mut exponent: i16 = ((bits >> 52) & 0x7ff) as i16;
    let mantissa = if exponent == 0 {
        (bits & 0xf_ffff_ffff_ffff) << 1
    } else {
        (bits & 0xf_ffff_ffff_ffff) | 0x10_0000_0000_0000
    };
    exponent -= 1023 + 52;
    (mantissa, exponent, sign)
}

fn runtime_source(expr: &Expr, operation: &'static str) -> IeeeFloatSource {
    runtime_source_from_site(token_key(expr.clone()), operation)
}

fn runtime_source_from_site(site: String, _operation: &'static str) -> IeeeFloatSource {
    IeeeFloatSource::Runtime { boundary: site }
}

fn ieee_refinement_source(boundary: String, reason: String) -> IeeeFloatSource {
    IeeeFloatSource::IeeeRefinement { boundary, reason }
}

pub(crate) fn runtime_float(boundary: &str) -> Outcome {
    Outcome::Incomplete(Effect::RuntimeFloatOperand {
        boundary: boundary.to_string(),
    })
}

pub(crate) fn ieee_refinement(_boundary: &str, reason: String) -> Outcome {
    Outcome::Incomplete(Effect::FloatIeeeRefinement { reason })
}

fn float_floor_gap(reason: &str) -> ! {
    panic!("IEEE float floor did not reach a lawful floor: {reason}")
}

#[cfg(test)]
mod tests {
    use super::*;

    use syn::{parse_quote, Expr};

    #[test]
    fn float_width_type_keys_parse_as_floor_widths() {
        assert_eq!(stable_width_from_type_key("f64"), Some(IeeeFloatWidth::F64));
        assert_eq!(
            stable_width_from_type_key("std::primitive::f32"),
            Some(IeeeFloatWidth::F32)
        );
        assert_eq!(stable_width_from_type_key("usize"), None);
    }

    #[test]
    fn float_width_parse_turbofish_delegates_to_floor_width() {
        let expr: Expr = parse_quote!("NaN".parse::<f32>());
        let Expr::MethodCall(call) = expr else {
            panic!("expected parse::<f32>() method call");
        };

        assert_eq!(
            stable_width_from_method_turbofish(&call),
            Some(IeeeFloatWidth::F32)
        );
    }

    #[test]
    fn float_width_visitor_projects_atom_label_width() {
        assert_eq!(
            IeeeFloatWidth::F64.accept_ieee_float_width(IeeeFloatWidthNameVisitor),
            "f64"
        );
    }

    #[test]
    fn float_width_into_widens_f32_to_f64_floor() {
        let term = IeeeFloatValue::F32(1.5).into_width_term(IeeeFloatWidth::F64, "test");
        let value = match term.accept_ieee_float(RequiredIeeeFloatVisitor) {
            Ok(value) => value,
            Err(_) => panic!("expected widened float floor"),
        };

        match value {
            IeeeFloatValue::F64(actual) => assert_eq!(actual, 1.5),
            _ => panic!("expected widened f64 floor"),
        }
    }
}
