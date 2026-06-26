// SPDX-License-Identifier: Apache-2.0
//
// InfinityEqSugar: `x == f32::INFINITY` / `x == f64::NEG_INFINITY` is not
// ordinary path equality. Rustc gives the width/sign on the constant side; we
// read that out loud as float refinement atoms over the receiver.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::configuration;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::float_floor::{
    stable_width_from_method_name, stable_width_from_path, stable_width_from_suffix,
    stable_width_from_type_key, IeeeFloatWidth, IeeeFloatWidthAccept, IeeeFloatWidthNameVisitor,
};
use crate::{
    bool_const, callsite_assertion_name, parse_macro_args, sugar_ctx_with_factory_audits,
    token_key, AssertionEntry, AssertionFactKind, CfgDisposition, CfgPredicate, Desugared, Effect,
    FactoryAuditLog, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, SugarCtx, Warrant,
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
    width: IeeeFloatWidth,
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

pub(crate) fn assertion_entry_with_audits(
    lhs: &Expr,
    rhs: &Expr,
    scope: &crate::TemporalScope,
    _float_widths: &FloatWidthScope,
    factory_audits: Option<&FactoryAuditLog>,
) -> Result<Option<AssertionEntry>, Effect> {
    let (width, is_positive, receiver_expr) =
        match (infinity_constant_kind(lhs), infinity_constant_kind(rhs)) {
            (Some((w, pos)), _) => (w, pos, rhs),
            (None, Some((w, pos))) => (w, pos, lhs),
            (None, None) => return Ok(None),
        };
    assertion_entry_for_infinity(width, is_positive, receiver_expr, scope, factory_audits).map(Some)
}

fn assertion_entry_for_infinity(
    width: IeeeFloatWidth,
    is_positive: bool,
    receiver_expr: &Expr,
    scope: &crate::TemporalScope,
    factory_audits: Option<&FactoryAuditLog>,
) -> Result<AssertionEntry, Effect> {
    if let Some(receiver_width) = float_receiver_width(receiver_expr, scope) {
        if receiver_width != width {
            infinity_eq_gap(&format!(
                "infinity equality: receiver width `{}` conflicts with constant width `{}` in `{}`",
                width_name(receiver_width),
                width_name(width),
                token_key(receiver_expr)
            ));
        }
    }

    let options = LiftOptions::default();
    let reducer = ReductionCtx::from_items(&[]);
    let let_inits = std::collections::BTreeMap::new();
    let fcx = SugarBuildCtx::new(scope, &options, &let_inits);
    let mut local_float_widths = FloatWidthScope::new();
    let ctx = sugar_ctx_with_factory_audits(
        scope,
        &options,
        &reducer,
        &mut local_float_widths,
        0,
        factory_audits,
    );
    let receiver = match SugarBody::term(receiver_expr, &fcx).reduce(&ctx) {
        Outcome::Complete(desugared) => desugared
            .into_term()
            .unwrap_or_else(|| infinity_eq_gap("receiver reduced to a non-term floor")),
        Outcome::Incomplete(effect) => return Err(effect),
    };

    let sign_pred = if is_positive {
        "is_sign_positive"
    } else {
        "is_sign_negative"
    };
    let atom = and_(vec![
        atomic_(
            float_predicate_atom_name(width, "is_infinite"),
            vec![receiver.clone()],
        ),
        atomic_(
            float_predicate_atom_name(width, sign_pred),
            vec![receiver.clone()],
        ),
    ]);
    Ok(AssertionEntry {
        name: callsite_assertion_name(receiver.as_ref(), scope.local_scope()),
        atom,
        fact_span: None,
        kind: AssertionFactKind::Warranted,
        claim_count: 1,
    })
}

impl Sugar for InfinityEqSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = inactive_debug_assertion(&self.name, self.debug_gated, ctx) {
            return outcome;
        }

        let receiver_width = float_receiver_width(&self.receiver_expr, ctx.scope);
        if let Some(receiver_width) = receiver_width {
            if receiver_width != self.width {
                infinity_eq_gap(&format!(
                    "infinity equality: receiver width `{}` conflicts with constant width `{}` in `{}`",
                    width_name(receiver_width),
                    width_name(self.width),
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
                float_predicate_atom_name(self.width, "is_infinite"),
                vec![receiver.clone()],
            ),
            atomic_(
                float_predicate_atom_name(self.width, sign_pred),
                vec![receiver.clone()],
            ),
        ]);
        constraint(
            atom,
            callsite_assertion_name(receiver.as_ref(), ctx.scope.local_scope()),
        )
    }
}

fn infinity_constant_kind(expr: &Expr) -> Option<(IeeeFloatWidth, bool)> {
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
    let width = stable_width_from_type_key(&segs[0].ident.to_string())?;
    let is_positive = match segs[1].ident.to_string().as_str() {
        "INFINITY" => true,
        "NEG_INFINITY" => false,
        _ => return None,
    };
    Some((width, is_positive))
}

fn float_receiver_width(expr: &Expr, scope: &crate::TemporalScope) -> Option<IeeeFloatWidth> {
    match expr {
        Expr::Path(path) => {
            let name = path_to_name(&path.path);
            scope
                .let_binding_expected_type(&name)
                .and_then(stable_width_from_type_key)
                .or_else(|| stable_width_from_path(&path.path))
        }
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Float(lit),
            ..
        }) => stable_width_from_suffix(lit.suffix()),
        Expr::MethodCall(call) => {
            stable_width_from_method_name(&call.method.to_string()).or_else(|| {
                if call.method == "unwrap" {
                    float_receiver_width(&call.receiver, scope)
                } else {
                    None
                }
            })
        }
        Expr::Paren(paren) => float_receiver_width(&paren.expr, scope),
        Expr::Group(group) => float_receiver_width(&group.expr, scope),
        _ => None,
    }
}

fn width_name(width: IeeeFloatWidth) -> &'static str {
    width.accept_ieee_float_width(IeeeFloatWidthNameVisitor)
}

fn float_predicate_atom_name(width: IeeeFloatWidth, method: &str) -> String {
    format!("float.{}.{}", width_name(width), method)
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
        CfgDisposition::Ambiguous(reason) => {
            let reason = format!("ambiguous cfg: {name}!: cfg(debug_assertions) skipped: {reason}");
            Some(Outcome::Incomplete(Effect::Configuration {
                boundary: format!("{name}!: cfg(debug_assertions)"),
                reason,
            }))
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    use crate::{record_simple_value_binding, TemporalPlan, TemporalScope};
    use syn::{parse_quote, Expr, Local, Stmt};

    fn local_from_stmt(stmt: Stmt) -> Local {
        let Stmt::Local(local) = stmt else {
            panic!("expected local statement");
        };
        local
    }

    fn scope_after(local: Local) -> TemporalScope {
        let mut scope = TemporalScope::new("infinity-eq-test", TemporalPlan::default());
        record_simple_value_binding(&mut scope, &local);
        scope
    }

    #[test]
    fn float_width_positive_infinity_constant_reads_width_from_constant_side() {
        let expr: Expr = parse_quote!(x == f64::INFINITY);
        let Expr::Binary(binary) = expr else {
            panic!("expected binary infinity equality");
        };

        assert_eq!(
            infinity_constant_kind(&binary.right),
            Some((IeeeFloatWidth::F64, true))
        );
    }

    #[test]
    fn float_width_negative_infinity_constant_reads_width_from_constant_side() {
        let expr: Expr = parse_quote!(x == f32::NEG_INFINITY);
        let Expr::Binary(binary) = expr else {
            panic!("expected binary infinity equality");
        };

        assert_eq!(
            infinity_constant_kind(&binary.right),
            Some((IeeeFloatWidth::F32, false))
        );
    }

    #[test]
    fn float_width_typed_infinity_receiver_resolves_through_temporal_scope() {
        let local = local_from_stmt(parse_quote!(let x: f32 = 1.0;));
        let scope = scope_after(local);
        let receiver: Expr = parse_quote!(x);

        assert_eq!(
            float_receiver_width(&receiver, &scope),
            Some(IeeeFloatWidth::F32)
        );
        assert_eq!(
            float_predicate_atom_name(IeeeFloatWidth::F32, "is_infinite"),
            "float.f32.is_infinite"
        );
    }
}
