// SPDX-License-Identifier: Apache-2.0
//
// `MapSugar`: the `.map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that replaces each element with the closure's const value. Bails
// (None) on an opaque element (no const value), a runtime/overflowing closure, or a
// mapped value it cannot materialize back to an `Expr`. Lifted verbatim from the
// `Adaptor::Map(closure)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{
    const_eval_unary_closure, literal_aggregate_term_in_scope, strip_refs_groups, Desugared,
    DesugaredElem, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::secondary_composite("map", recognize_composite);
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
    if !method_family::resolves_literal_sequence(expr, fcx.let_inits()) {
        return None;
    }
    Some(Box::new(MapSugar {
        inner: build_map_receiver(&call.receiver, fcx)?,
        f: f.clone(),
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
    if !resolves_direct_literal_array_receiver(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(MapTermSugar {
        source: expr.clone(),
        inner: build_map_receiver(&call.receiver, fcx)?,
        f: f.clone(),
    }))
}

/// Replace each element with the const value of `f` applied to it.
pub(crate) struct MapSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) f: syn::ExprClosure,
}

impl Sugar for MapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt(reduce_map(self.inner.as_ref(), &self.f, ctx).map(Desugared::Seq))
    }
}

pub(crate) struct MapTermSugar {
    pub(crate) source: Expr,
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) f: syn::ExprClosure,
}

impl Sugar for MapTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let mapped = reduce_map(self.inner.as_ref(), &self.f, ctx)?;
            let exprs: Vec<Expr> = mapped.into_iter().map(|elem| elem.expr).collect();
            let term =
                literal_aggregate_term_in_scope("Array", exprs.iter(), &self.source, ctx.scope)
                    .ok()?;
            Some(Desugared::Term(term))
        })())
    }
}

fn reduce_map(
    inner: &dyn Sugar,
    f: &syn::ExprClosure,
    ctx: &SugarCtx,
) -> Option<Vec<DesugaredElem>> {
    let seq = inner.desugar(ctx).dug()?.into_seq()?;
    let mut out = Vec::with_capacity(seq.len());
    for elem in seq {
        let v = elem.value.as_ref()?; // opaque element under a map -> bail
        let mapped = const_eval_unary_closure(f, v)?;
        let mexpr = mapped.to_expr()?; // materialize for EUF translation
        out.push(DesugaredElem {
            expr: mexpr,
            value: Some(mapped),
        });
    }
    tracing::debug!(
        target: "sugar_lift_rust_tests::sugar::map",
        len = out.len(),
        "literal closure map reduced"
    );
    Some(out)
}

fn build_map_receiver(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Expr::Path(path) = strip_refs_groups(expr) {
        if path.qself.is_none() {
            if let Some(name) = path.path.get_ident().map(ToString::to_string) {
                if fcx.resolving_bound_path(&name) {
                    return None;
                }
                if let Some(init) = fcx.let_inits().get(&name) {
                    let child_fcx = fcx.with_bound_path(&name);
                    return Some(build_composite(init, &child_fcx));
                }
            }
        }
    }
    Some(build_composite(expr, fcx))
}

fn resolves_direct_literal_array_receiver(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    match strip_refs_groups(expr) {
        Expr::Array(_) => true,
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            if fcx.resolving_bound_path(&name) {
                return false;
            }
            fcx.let_inits()
                .get(&name)
                .is_some_and(|init| resolves_direct_literal_array_receiver(init, fcx))
        }
        _ => false,
    }
}
