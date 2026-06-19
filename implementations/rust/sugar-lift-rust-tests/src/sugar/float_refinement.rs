// SPDX-License-Identifier: Apache-2.0
//
// FloatRefinementSugar: constraint-shaped stdlib float predicates. These are
// first-order refinement atoms over the receiver, not generic
// `method:is_nan(receiver) == true` booleans.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{
    callsite_assertion_name, token_key, AssertionFactKind, Desugared, Effect, FloatWidthScope,
    Outcome, Sugar, SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{atomic_, Formula, Term};
use syn::{Expr, ExprLit, ExprMethodCall, Lit, Type};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_float_refinement",
    SugarRole::Constraint,
    SugarPriority::Primary,
    recognize,
);

struct FloatRefinementSugar {
    method: String,
    receiver: Box<dyn Sugar>,
    receiver_expr: Expr,
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
        receiver: build_term(&call.receiver, fcx),
        receiver_expr: (*call.receiver).clone(),
        site: token_key(Expr::MethodCall(call.clone())),
    }))
}

impl Sugar for FloatRefinementSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let width = {
            let widths = ctx.float_widths.borrow();
            float_refinement_receiver_width(&self.receiver_expr, &widths)
        };
        let Some(width) = width else {
            return unsupported(format!(
                "float refinement predicate `{}` requires known f32/f64 receiver width `{}`",
                self.method, self.site
            ));
        };
        let receiver = match term_payload(&*self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let name = callsite_assertion_name(receiver.as_ref(), ctx.scope.local_scope());
        constraint(
            atomic_(format!("float.{width}.{}", self.method), vec![receiver]),
            name,
        )
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

fn float_width_from_method_turbofish(call: &ExprMethodCall) -> Option<&'static str> {
    if call.method != "parse" {
        return None;
    }
    let args = call.turbofish.as_ref()?;
    float_width_from_angle_args(args)
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

fn float_width_from_type(ty: &Type) -> Option<&'static str> {
    match ty {
        Type::Path(path) => float_width_from_path(&path.path),
        Type::Paren(paren) => float_width_from_type(&paren.elem),
        Type::Group(group) => float_width_from_type(&group.elem),
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

fn float_width_from_suffix(suffix: &str) -> Option<&'static str> {
    match suffix {
        "f32" => Some("f32"),
        "f64" => Some("f64"),
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
    Outcome::Dug(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn term_payload(node: &dyn Sugar, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match node.desugar(ctx) {
        Outcome::Dug(desugared) => desugared.into_term().ok_or_else(|| {
            Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            })
        }),
        Outcome::Hit(effect) => Err(Outcome::Hit(effect)),
    }
}

fn unsupported(reason: String) -> Outcome {
    Outcome::Hit(Effect::Unsupported { reason })
}
