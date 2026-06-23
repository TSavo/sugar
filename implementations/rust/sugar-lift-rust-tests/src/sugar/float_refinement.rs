// SPDX-License-Identifier: Apache-2.0
//
// FloatRefinementSugar: constraint-shaped stdlib float predicates. These are
// first-order refinement atoms over the receiver, not generic
// `method:is_nan(receiver) == true` booleans.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx,
};
use crate::{
    bool_const, callsite_assertion_name, eq, strip_refs_groups, token_key, AssertionFactKind,
    Desugared, Effect, FloatWidthScope, Outcome, Sugar, SugarCtx, Warrant,
    STRUCTURAL_BACKSTOP_REASON,
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
    receiver_expr: Expr,
    receiver: SugarBody,
    site: String,
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
        method,
        receiver_expr: (*call.receiver).clone(),
        receiver: SugarBody::term(&call.receiver, fcx),
        site: token_key(Expr::MethodCall(call.clone())),
    }))
}

impl Sugar for FloatRefinementSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let width = {
            let widths = ctx.float_widths.borrow();
            float_refinement_receiver_width(&self.receiver_expr, &widths)
        };
        if let Some(unstable_width) = float_refinement_receiver_unstable_width(&self.receiver_expr)
        {
            let width_reason = if unstable_width == "f16" && self.method == "is_nan" {
                "f16 NaN width not modeled".to_string()
            } else {
                format!("{unstable_width} bit-width not modeled")
            };
            return Ok(unsupported(format!(
                "float refinement predicate `{}` {width_reason} `{}`",
                self.method, self.site
            )));
        }
        let Some(width) = width else {
            return Ok(unsupported(format!(
                "float refinement predicate `{}` requires known f32/f64 receiver width `{}`",
                self.method, self.site
            )));
        };
        if let Some(value) = literal_float_refinement_value(&self.method, &self.receiver_expr) {
            return Ok(constraint(eq(bool_const(value), bool_const(true)), None));
        }
        let receiver = match term_payload(&self.receiver, ctx) {
            Ok(term) => term,
            Err(reduction) => return reduction,
        };
        let name = callsite_assertion_name(receiver.as_ref(), ctx.scope.local_scope());
        Ok(constraint(
            atomic_(format!("float.{width}.{}", self.method), vec![receiver]),
            name,
        ))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
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

fn term_payload(body: &SugarBody, ctx: &SugarCtx) -> Result<Rc<Term>, FactoryReduction> {
    match body.reduce(ctx) {
        Ok(Outcome::Complete(desugared)) => desugared.into_term().ok_or_else(|| {
            Err(FactoryGap::new(format!(
                "float refinement receiver reduced to non-term: {STRUCTURAL_BACKSTOP_REASON}"
            )))
        }),
        Ok(Outcome::Incomplete(effect)) => Err(Ok(Outcome::Incomplete(effect))),
        Err(gap) => Err(Err(gap)),
    }
}

fn unsupported(reason: String) -> Outcome {
    Outcome::Incomplete(Effect::Unsupported { reason })
}
