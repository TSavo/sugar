// SPDX-License-Identifier: Apache-2.0
//
// InfinityEqSugar: `x == f32::INFINITY` / `x == f64::NEG_INFINITY` is not
// ordinary path equality. Rustc gives the width/sign on the constant side; we
// read that out loud as float refinement atoms over the receiver.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::configuration;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{
    bool_const, callsite_assertion_name, parse_macro_args, token_key, AssertionFactKind,
    CfgDisposition, CfgPredicate, Desugared, Outcome, Sugar, SugarCtx, Warrant,
};
use sugar_ir_symbolic::{and_, atomic_, eq, Formula, Term};
use syn::{BinOp, Expr, ExprBinary, ExprMacro};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("constraint_infinity_eq", SugarRole::Constraint, recognize);

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "assertion_surface_infinity_eq",
    SugarRole::AssertionSurface,
    recognize,
);

struct InfinityEqSugar {
    name: String,
    receiver: SugarBody<TermFloor>,
    receiver_expr: Expr,
    width: &'static str,
    is_positive: bool,
    debug_gated: bool,
}

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(paren) => recognize(&paren.expr, fcx),
        Expr::Group(group) => recognize(&group.expr, fcx),
        Expr::Binary(binary) => recognize_binary(binary, fcx),
        Expr::Macro(expr_macro) => recognize_macro(expr_macro, fcx),
        _ => None,
    }
}

fn recognize_binary(binary: &ExprBinary, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !matches!(binary.op, BinOp::Eq(_)) {
        return None;
    }
    build("assert", &binary.left, &binary.right, false, fcx)
}

fn recognize_macro(expr_macro: &ExprMacro, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let name = expr_macro.mac.path.segments.last()?.ident.to_string();
    let debug_gated = match name.as_str() {
        "assert_eq" => false,
        "debug_assert_eq" => true,
        _ => return None,
    };
    let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    build(&name, &args.exprs[0], &args.exprs[1], debug_gated, fcx)
}

fn build(
    name: &str,
    lhs: &Expr,
    rhs: &Expr,
    debug_gated: bool,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let (width, is_positive, receiver_expr) =
        match (infinity_constant_kind(lhs), infinity_constant_kind(rhs)) {
            (Some((width, positive)), _) => (width, positive, rhs.clone()),
            (None, Some((width, positive))) => (width, positive, lhs.clone()),
            (None, None) => return None,
        };
    Some(Box::new(InfinityEqSugar {
        name: name.to_string(),
        receiver: SugarBody::term(&receiver_expr, fcx),
        receiver_expr,
        width,
        is_positive,
        debug_gated,
    }))
}

impl Sugar for InfinityEqSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = inactive_debug_assertion(&self.name, self.debug_gated, ctx) {
            return outcome;
        }

        let receiver_width = {
            let widths = ctx.float_widths.borrow();
            float_receiver_width(&self.receiver_expr, &widths)
        };
        if let Some(receiver_width) = receiver_width {
            if receiver_width != self.width {
                infinity_eq_gap(&format!(
                    "infinity equality: receiver width `{receiver_width}` conflicts with constant width `{}` in `{}`",
                    self.width,
                    token_key(&self.receiver_expr)
                ));
            }
        }

        let receiver = match term_payload(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let sign_pred = if self.is_positive {
            "is_sign_positive"
        } else {
            "is_sign_negative"
        };
        let atom = and_(vec![
            atomic_(
                format!("float.{}.is_infinite", self.width),
                vec![receiver.clone()],
            ),
            atomic_(
                format!("float.{}.{}", self.width, sign_pred),
                vec![receiver.clone()],
            ),
        ]);
        constraint(
            atom,
            callsite_assertion_name(receiver.as_ref(), ctx.scope.local_scope()),
        )
    }
}

fn infinity_constant_kind(expr: &Expr) -> Option<(&'static str, bool)> {
    let path = match expr {
        Expr::Path(p) if p.qself.is_none() => &p.path,
        Expr::Paren(paren) => return infinity_constant_kind(&paren.expr),
        Expr::Group(group) => return infinity_constant_kind(&group.expr),
        _ => return None,
    };
    let segs: Vec<_> = path.segments.iter().collect();
    if segs.len() != 2
        || segs
            .iter()
            .any(|segment| !matches!(segment.arguments, syn::PathArguments::None))
    {
        return None;
    }
    let width = match segs[0].ident.to_string().as_str() {
        "f32" => "f32",
        "f64" => "f64",
        _ => return None,
    };
    let is_positive = match segs[1].ident.to_string().as_str() {
        "INFINITY" => true,
        "NEG_INFINITY" => false,
        _ => return None,
    };
    Some((width, is_positive))
}

fn float_receiver_width(
    expr: &Expr,
    float_widths: &crate::FloatWidthScope,
) -> Option<&'static str> {
    match expr {
        Expr::Path(path) => {
            let name = path_to_name(&path.path);
            float_widths
                .get(&name)
                .copied()
                .or_else(|| float_width_from_path(&path.path))
        }
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Float(lit),
            ..
        }) => float_width_from_suffix(lit.suffix()),
        Expr::MethodCall(call) => {
            float_width_from_method_name(&call.method.to_string()).or_else(|| {
                if call.method == "unwrap" {
                    float_receiver_width(&call.receiver, float_widths)
                } else {
                    None
                }
            })
        }
        Expr::Paren(paren) => float_receiver_width(&paren.expr, float_widths),
        Expr::Group(group) => float_receiver_width(&group.expr, float_widths),
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

fn inactive_debug_assertion(name: &str, debug_gated: bool, ctx: &SugarCtx) -> Option<Outcome> {
    if !debug_gated {
        return None;
    }
    match configuration::resolve_predicate(
        &CfgPredicate::Name("debug_assertions".to_string()),
        ctx.options,
    ) {
        CfgDisposition::Present => None,
        CfgDisposition::Absent(reason) => Some(inert_support_constraint(format!(
            "{name}!: cfg(debug_assertions) not active; skipped: {reason}"
        ))),
        CfgDisposition::Ambiguous(reason) => infinity_eq_gap(&format!(
            "{name}!: cfg(debug_assertions) ambiguous; skipped: {reason}"
        )),
    }
}

fn constraint(atom: Rc<Formula>, name: Option<String>) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn inert_support_constraint(reason: String) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom: eq(bool_const(true), bool_const(true)),
        n: 0,
        kind: AssertionFactKind::Support,
        warrant: Warrant { name: Some(reason) },
    })
}

fn term_payload(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| infinity_eq_gap("receiver reduced to a non-term floor"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn infinity_eq_gap(reason: &str) -> ! {
    panic!("infinity_eq did not reach a lawful floor: {reason}")
}
