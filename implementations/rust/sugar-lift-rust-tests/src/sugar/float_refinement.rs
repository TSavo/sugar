// SPDX-License-Identifier: Apache-2.0
//
// FloatRefinementSugar: constraint-shaped stdlib float predicates. These are
// first-order refinement atoms over the receiver, not generic
// `method:is_nan(receiver) == true` booleans.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{
    bool_const, callsite_assertion_name, eq, strip_refs_groups, sugar_ctx_with_factory_audits,
    token_key, AssertionEntry, AssertionFactKind, Desugared, Effect, FloatWidthScope, LiftOptions,
    Outcome, ReductionCtx, Sugar, SugarCtx, Warrant,
};
use sugar_ir_symbolic::{atomic_, Formula, Term};
use syn::{Expr, ExprLit, ExprMethodCall, Lit, Type};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_float_refinement",
    SugarRole::Constraint,
    recognize,
);

struct FloatRefinementSugar {
    method: String,
    receiver_width: FloatReceiverWidth,
    literal_value: Option<bool>,
    receiver: SugarBody<TermFloor>,
    site: String,
}

enum FloatReceiverWidth {
    Static(&'static str),
    ScopePath(String),
    Unstable(&'static str),
    Unknown,
}

enum FloatWidthResolution {
    Known(&'static str),
    Unstable(&'static str),
    Unknown,
}

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(paren) => recognize(&paren.expr, fcx),
        Expr::Group(group) => recognize(&group.expr, fcx),
        Expr::MethodCall(call) => recognize_method(call, fcx),
        _ => None,
    }
}

fn recognize_method(call: &ExprMethodCall, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let method = call.method.to_string();
    if !is_liftable_float_refinement_method(&method) {
        return None;
    }
    Some(Box::new(FloatRefinementSugar {
        method: method.clone(),
        literal_value: literal_float_refinement_value(&method, &call.receiver),
        receiver_width: float_receiver_width_source(&call.receiver),
        receiver: SugarBody::term(&call.receiver, fcx),
        site: token_key(Expr::MethodCall(call.clone())),
    }))
}

pub(crate) fn assertion_entry(
    expr: &Expr,
    scope: &crate::TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<Option<AssertionEntry>, String> {
    match expr {
        Expr::Paren(paren) => assertion_entry(&paren.expr, scope, float_widths),
        Expr::Group(group) => assertion_entry(&group.expr, scope, float_widths),
        Expr::MethodCall(call) => assertion_entry_method(call, scope, float_widths),
        _ => Ok(None),
    }
}

fn assertion_entry_method(
    call: &ExprMethodCall,
    scope: &crate::TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<Option<AssertionEntry>, String> {
    let method = call.method.to_string();
    let site = token_key(Expr::MethodCall(call.clone()));
    if !is_liftable_float_refinement_method(&method) {
        return Ok(None);
    }
    if !call.args.is_empty() {
        return Err(format!(
            "float refinement predicate takes no arguments `{site}`"
        ));
    }
    if let Some(unstable_width) = float_refinement_receiver_unstable_width(&call.receiver) {
        let width_reason = if unstable_width == "f16" && method == "is_nan" {
            "f16 NaN width not modeled".to_string()
        } else {
            format!("{unstable_width} bit-width not modeled")
        };
        return Err(format!(
            "float refinement predicate `{method}` {width_reason} `{site}`"
        ));
    }
    let Some(width) = float_refinement_receiver_width(&call.receiver, float_widths) else {
        return Err(format!(
            "float refinement predicate `{method}` requires known f32/f64 receiver width `{site}`"
        ));
    };
    if let Some(value) = literal_float_refinement_value(&method, &call.receiver) {
        return Ok(Some(AssertionEntry {
            name: None,
            atom: eq(bool_const(value), bool_const(true)),
            fact_span: None,
            kind: AssertionFactKind::Warranted,
            claim_count: 1,
        }));
    }

    let options = LiftOptions::default();
    let reducer = ReductionCtx::from_items(&[]);
    let let_inits = std::collections::BTreeMap::new();
    let fcx = SugarBuildCtx::new(scope, &options, &let_inits);
    let mut local_float_widths = float_widths.clone();
    let ctx =
        sugar_ctx_with_factory_audits(scope, &options, &reducer, &mut local_float_widths, 0, None);
    let receiver = match SugarBody::term(&call.receiver, &fcx).reduce(&ctx) {
        Outcome::Complete(desugared) => desugared
            .into_term()
            .unwrap_or_else(|| panic!("typed float refinement receiver reduced to non-term")),
        Outcome::Incomplete(effect) => {
            return Err(format!(
                "float refinement receiver term translation failed for `{}`: {}",
                token_key(&call.receiver),
                effect.reason()
            ));
        }
    };
    Ok(Some(AssertionEntry {
        name: callsite_assertion_name(receiver.as_ref(), scope.local_scope()),
        atom: atomic_(format!("float.{width}.{method}"), vec![receiver]),
        fact_span: None,
        kind: AssertionFactKind::Warranted,
        claim_count: 1,
    }))
}

impl Sugar for FloatRefinementSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let width = match {
            let widths = ctx.float_widths.borrow();
            self.receiver_width.resolve(&widths)
        } {
            FloatWidthResolution::Known(width) => width,
            FloatWidthResolution::Unstable(unstable_width) => {
                let width_reason = if unstable_width == "f16" && self.method == "is_nan" {
                    "f16 NaN width not modeled".to_string()
                } else {
                    format!("{unstable_width} bit-width not modeled")
                };
                return Outcome::Incomplete(Effect::FloatIeeeRefinement {
                    boundary: self.site.clone(),
                    reason: format!(
                        "float refinement predicate `{}` {width_reason} `{}`",
                        self.method, self.site
                    ),
                });
            }
            FloatWidthResolution::Unknown => {
                return Outcome::Incomplete(Effect::FloatIeeeRefinement {
                    boundary: self.site.clone(),
                    reason: format!(
                        "float refinement predicate `{}` requires known f32/f64 receiver width `{}`",
                        self.method, self.site
                    ),
                });
            }
        };
        if let Some(value) = self.literal_value {
            return constraint(eq(bool_const(value), bool_const(true)), None);
        }
        let receiver = match term_payload(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let name = callsite_assertion_name(receiver.as_ref(), ctx.scope.local_scope());
        constraint(
            atomic_(format!("float.{width}.{}", self.method), vec![receiver]),
            name,
        )
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

impl FloatReceiverWidth {
    fn resolve(&self, float_widths: &FloatWidthScope) -> FloatWidthResolution {
        match self {
            FloatReceiverWidth::Static(width) => FloatWidthResolution::Known(width),
            FloatReceiverWidth::ScopePath(name) => float_widths
                .get(name)
                .copied()
                .map(FloatWidthResolution::Known)
                .unwrap_or(FloatWidthResolution::Unknown),
            FloatReceiverWidth::Unstable(width) => FloatWidthResolution::Unstable(width),
            FloatReceiverWidth::Unknown => FloatWidthResolution::Unknown,
        }
    }
}

enum LiteralFloat {
    F32(f32),
    F64(f64),
}

impl LiteralFloat {
    fn is_nan(&self) -> bool {
        match self {
            LiteralFloat::F32(value) => value.is_nan(),
            LiteralFloat::F64(value) => value.is_nan(),
        }
    }
}

fn literal_float_refinement_value(method: &str, receiver: &Expr) -> Option<bool> {
    match method {
        "is_nan" => parsed_literal_float(receiver).map(|value| value.is_nan()),
        _ => None,
    }
}

fn parsed_literal_float(expr: &Expr) -> Option<LiteralFloat> {
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.method == "unwrap" && call.args.is_empty() => {
            parsed_literal_float(&call.receiver)
        }
        Expr::MethodCall(call) if call.method == "parse" && call.args.is_empty() => {
            parse_literal_float_call(call)
        }
        _ => None,
    }
}

fn parse_literal_float_call(call: &ExprMethodCall) -> Option<LiteralFloat> {
    let width = float_width_from_method_turbofish(call)?;
    let Expr::Lit(ExprLit {
        lit: Lit::Str(lit), ..
    }) = strip_refs_groups(&call.receiver)
    else {
        return None;
    };
    match width {
        "f32" => lit.value().parse::<f32>().ok().map(LiteralFloat::F32),
        "f64" => lit.value().parse::<f64>().ok().map(LiteralFloat::F64),
        _ => None,
    }
}

fn is_liftable_float_refinement_method(method: &str) -> bool {
    matches!(
        method,
        "is_nan"
            | "is_infinite"
            | "is_finite"
            | "is_normal"
            | "is_sign_positive"
            | "is_sign_negative"
    )
}

fn float_receiver_width_source(expr: &Expr) -> FloatReceiverWidth {
    if let Some(width) = float_refinement_receiver_unstable_width(expr) {
        return FloatReceiverWidth::Unstable(width);
    }
    if let Some(width) = float_refinement_receiver_static_width(expr) {
        return FloatReceiverWidth::Static(width);
    }
    match expr {
        Expr::Path(path) => FloatReceiverWidth::ScopePath(path_to_name(&path.path)),
        Expr::Paren(paren) => float_receiver_width_source(&paren.expr),
        Expr::Group(group) => float_receiver_width_source(&group.expr),
        Expr::MethodCall(call) if call.method == "unwrap" => {
            float_receiver_width_source(&call.receiver)
        }
        _ => FloatReceiverWidth::Unknown,
    }
}

fn float_refinement_receiver_static_width(expr: &Expr) -> Option<&'static str> {
    match expr {
        Expr::MethodCall(call) => float_width_from_method_name(&call.method.to_string())
            .or_else(|| float_width_from_method_turbofish(call))
            .or_else(|| {
                if call.method == "unwrap" {
                    float_refinement_receiver_static_width(&call.receiver)
                } else {
                    None
                }
            }),
        Expr::Path(path) => float_width_from_path(&path.path),
        Expr::Lit(ExprLit {
            lit: Lit::Float(lit),
            ..
        }) => float_width_from_suffix(lit.suffix()),
        Expr::Paren(paren) => float_refinement_receiver_static_width(&paren.expr),
        Expr::Group(group) => float_refinement_receiver_static_width(&group.expr),
        _ => None,
    }
}

fn float_refinement_receiver_width(
    expr: &Expr,
    float_widths: &FloatWidthScope,
) -> Option<&'static str> {
    match expr {
        Expr::MethodCall(call) => float_width_from_method_name(&call.method.to_string())
            .or_else(|| float_width_from_method_turbofish(call))
            .or_else(|| {
                if call.method == "unwrap" {
                    float_refinement_receiver_width(&call.receiver, float_widths)
                } else {
                    None
                }
            }),
        Expr::Path(path) => {
            let name = path_to_name(&path.path);
            float_widths
                .get(&name)
                .copied()
                .or_else(|| float_width_from_path(&path.path))
        }
        Expr::Lit(ExprLit {
            lit: Lit::Float(lit),
            ..
        }) => float_width_from_suffix(lit.suffix()),
        Expr::Paren(paren) => float_refinement_receiver_width(&paren.expr, float_widths),
        Expr::Group(group) => float_refinement_receiver_width(&group.expr, float_widths),
        _ => None,
    }
}

fn float_refinement_receiver_unstable_width(expr: &Expr) -> Option<&'static str> {
    match expr {
        Expr::MethodCall(call) => unstable_width_from_method_name(&call.method.to_string())
            .or_else(|| unstable_width_from_method_turbofish(call))
            .or_else(|| {
                if call.method == "unwrap" {
                    float_refinement_receiver_unstable_width(&call.receiver)
                } else {
                    None
                }
            }),
        Expr::Path(path) => unstable_width_from_path(&path.path),
        Expr::Lit(ExprLit {
            lit: Lit::Float(lit),
            ..
        }) => unstable_width_from_suffix(lit.suffix()),
        Expr::Paren(paren) => float_refinement_receiver_unstable_width(&paren.expr),
        Expr::Group(group) => float_refinement_receiver_unstable_width(&group.expr),
        _ => None,
    }
}

fn float_width_from_method_turbofish(call: &ExprMethodCall) -> Option<&'static str> {
    if call.method != "parse" {
        return None;
    }
    let args = call.turbofish.as_ref()?;
    float_width_from_angle_args(args)
}

fn unstable_width_from_method_turbofish(call: &ExprMethodCall) -> Option<&'static str> {
    if call.method != "parse" {
        return None;
    }
    let args = call.turbofish.as_ref()?;
    unstable_width_from_angle_args(args)
}

fn float_width_from_angle_args(args: &syn::AngleBracketedGenericArguments) -> Option<&'static str> {
    if args.args.len() != 1 {
        return None;
    }
    let Some(syn::GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    float_width_from_type(ty)
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

fn float_width_from_type(ty: &Type) -> Option<&'static str> {
    match ty {
        Type::Path(path) => float_width_from_path(&path.path),
        Type::Paren(paren) => float_width_from_type(&paren.elem),
        Type::Group(group) => float_width_from_type(&group.elem),
        _ => None,
    }
}

fn unstable_width_from_type(ty: &Type) -> Option<&'static str> {
    match ty {
        Type::Path(path) => unstable_width_from_path(&path.path),
        Type::Paren(paren) => unstable_width_from_type(&paren.elem),
        Type::Group(group) => unstable_width_from_type(&group.elem),
        _ => None,
    }
}

fn float_width_from_method_name(method: &str) -> Option<&'static str> {
    if method.ends_with("_f32") {
        Some("f32")
    } else if method.ends_with("_f64") {
        Some("f64")
    } else {
        None
    }
}

fn unstable_width_from_method_name(method: &str) -> Option<&'static str> {
    if method.ends_with("_f16") {
        Some("f16")
    } else if method.ends_with("_f128") {
        Some("f128")
    } else {
        None
    }
}

fn float_width_from_path(path: &syn::Path) -> Option<&'static str> {
    for segment in &path.segments {
        match segment.ident.to_string().as_str() {
            "f32" => return Some("f32"),
            "f64" => return Some("f64"),
            _ => {}
        }
    }
    None
}

fn unstable_width_from_path(path: &syn::Path) -> Option<&'static str> {
    for segment in &path.segments {
        match segment.ident.to_string().as_str() {
            "f16" => return Some("f16"),
            "f128" => return Some("f128"),
            _ => {}
        }
    }
    None
}

fn float_width_from_suffix(suffix: &str) -> Option<&'static str> {
    match suffix {
        "f32" => Some("f32"),
        "f64" => Some("f64"),
        _ => None,
    }
}

fn unstable_width_from_suffix(suffix: &str) -> Option<&'static str> {
    match suffix {
        "f16" => Some("f16"),
        "f128" => Some("f128"),
        _ => None,
    }
}

fn path_to_name(path: &syn::Path) -> String {
    path.segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect::<Vec<_>>()
        .join("::")
}

fn constraint(atom: Rc<Formula>, name: Option<String>) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn term_payload(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| panic!("typed float refinement receiver reduced to non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}
