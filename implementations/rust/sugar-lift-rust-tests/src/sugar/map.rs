// SPDX-License-Identifier: Apache-2.0
//
// `MapSugar`: the `.map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that replaces each element with the closure's const value. Bails
// (None) on an opaque element (no const value), a runtime/overflowing closure, or a
// mapped value it cannot materialize back to an `Expr`. Lifted verbatim from the
// `Adaptor::Map(closure)` arm of the former `apply_one_adaptor` match.

use std::collections::BTreeMap;

use quote::quote;
use syn::{Expr, Pat, Type};

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{
    closure_body_mutates_captured_runtime_state, const_eval_unary_closure,
    const_eval_unary_closure_with_u128_shift, strip_refs_groups, substitute_expr, Desugared,
    DesugaredElem, Effect, ExprBindings, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("map", recognize_composite);
pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("map_term", recognize_term);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    Some(Box::new(MapSugar {
        inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        f: f.clone(),
        u128_shift_hint: receiver_is_u128_count_ones_range(&call.receiver),
    }))
}

pub(crate) fn recognize_term(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits()) {
        return None;
    }
    Some(Box::new(MapTermSugar {
        inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        f: f.clone(),
        u128_shift_hint: receiver_is_u128_count_ones_range(&call.receiver),
    }))
}

/// Replace each element with the const value of `f` applied to it.
pub(crate) struct MapSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) f: syn::ExprClosure,
    pub(crate) u128_shift_hint: bool,
}

impl Sugar for MapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = captured_mutation_refusal(&self.f) {
            return outcome;
        }
        Outcome::from_opt(
            reduce_map(self.inner.as_ref(), &self.f, self.u128_shift_hint, ctx).map(Desugared::Seq),
        )
    }
}

pub(crate) struct MapTermSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) f: syn::ExprClosure,
    pub(crate) u128_shift_hint: bool,
}

impl Sugar for MapTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = captured_mutation_refusal(&self.f) {
            return outcome;
        }
        Outcome::from_opt((|| {
            let mapped = reduce_map(self.inner.as_ref(), &self.f, self.u128_shift_hint, ctx)?;
            let exprs: Vec<Expr> = mapped.into_iter().map(|elem| elem.expr).collect();
            let array = array_expr(exprs)?;
            let let_inits = BTreeMap::new();
            let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
            let term = build_term(&array, &fcx).desugar(ctx).dug()?.into_term()?;
            Some(Desugared::Term(term))
        })())
    }
}

fn captured_mutation_refusal(f: &syn::ExprClosure) -> Option<Outcome> {
    if !closure_body_mutates_captured_runtime_state(&Expr::Closure(f.clone())) {
        return None;
    }
    Some(Outcome::Hit(Effect::Unsupported {
        reason: "iterator/option adaptor `.map(|..| ..)` over a LITERAL domain whose closure body \
                 MUTATES captured runtime state (bin-2: runtime side effect during value \
                 construction, not constructed from source literals); refused"
            .to_string(),
    }))
}

fn reduce_map(
    inner: &dyn Sugar,
    f: &syn::ExprClosure,
    u128_shift_hint: bool,
    ctx: &SugarCtx,
) -> Option<Vec<DesugaredElem>> {
    let seq = inner.desugar(ctx).dug()?.into_seq()?;
    let mut out = Vec::with_capacity(seq.len());
    for elem in seq {
        if let Some(mapped) = elem.value.as_ref().and_then(|v| {
            const_eval_unary_closure(f, v).or_else(|| {
                u128_shift_hint.then(|| const_eval_unary_closure_with_u128_shift(f, v))?
            })
        }) {
            let mexpr = mapped.to_expr()?; // materialize for EUF translation
            out.push(DesugaredElem {
                expr: mexpr,
                value: Some(mapped),
            });
            continue;
        }
        let expr = rewrite_map_elem(f, &elem.expr)?;
        let value = crate::const_eval(&expr, &BTreeMap::new());
        out.push(DesugaredElem { expr, value });
    }
    tracing::debug!(
        target: "sugar_lift_rust_tests::sugar::map",
        len = out.len(),
        "literal closure map reduced"
    );
    Some(out)
}

fn rewrite_map_elem(f: &syn::ExprClosure, elem: &Expr) -> Option<Expr> {
    if f.inputs.len() != 1 {
        return None;
    }
    let param = closure_param_ident(f.inputs.first()?)?;
    let body = closure_value_body(f)?;
    let mut bindings = ExprBindings::new();
    bindings.insert(param, elem.clone());
    Some(substitute_expr(body, &bindings))
}

fn closure_value_body(f: &syn::ExprClosure) -> Option<&Expr> {
    match &*f.body {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => Some(expr),
            _ => None,
        },
        expr => Some(expr),
    }
}

fn closure_param_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(p) if p.subpat.is_none() => Some(p.ident.to_string()),
        Pat::Reference(r) => closure_param_ident(&r.pat),
        Pat::Paren(p) => closure_param_ident(&p.pat),
        Pat::Type(t) => closure_param_ident(&t.pat),
        _ => None,
    }
}

fn array_expr(exprs: Vec<Expr>) -> Option<Expr> {
    syn::parse2(quote!([#(#exprs),*])).ok()
}

fn receiver_is_u128_count_ones_range(expr: &Expr) -> bool {
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return false;
    };
    range.end.as_deref().is_some_and(expr_is_u128_count_ones)
}

fn expr_is_u128_count_ones(expr: &Expr) -> bool {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return false;
    };
    call.method == "count_ones" && expr_is_u128_assoc_const(&call.receiver)
}

fn expr_is_u128_assoc_const(expr: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return false;
    };
    if let Some(qself) = &path.qself {
        return type_is_u128(&qself.ty);
    }
    path.path
        .segments
        .first()
        .is_some_and(|segment| segment.ident == "u128")
}

fn type_is_u128(ty: &Type) -> bool {
    let Type::Path(path) = ty else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "u128")
}
