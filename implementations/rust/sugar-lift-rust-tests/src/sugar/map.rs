// SPDX-License-Identifier: Apache-2.0
//
// `MapSugar`: the `.map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that replaces each element with the closure's const value. Bails
// (None) on an opaque element (no const value), a runtime/overflowing closure, or a
// mapped value it cannot materialize back to an `Expr`. Lifted verbatim from the
// `Adaptor::Map(closure)` arm of the former `apply_one_adaptor` match.

use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, Pat, Type};

use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx,
};
use crate::sugar::method_family;
use crate::{
    canonical_term_sig, closure_body_mutates_captured_runtime_state, const_eval_unary_closure,
    const_eval_unary_closure_with_u128_shift, const_val_term, strip_refs_groups, substitute_expr,
    Desugared, DesugaredElem, Effect, ExprBindings, Outcome, Sugar, SugarCtx, TemporalScope,
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
    if !crate::resolves_literal_sequence_in_scope(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(MapCallSugar {
        inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &call.receiver,
            fcx,
        )?),
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
    if !crate::resolves_literal_sequence_in_scope(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(MapTermSugar {
        inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &call.receiver,
            fcx,
        )?),
        f: f.clone(),
        u128_shift_hint: receiver_is_u128_count_ones_range(&call.receiver),
    }))
}

/// A source-level `.map(..)` site. It captures the raw receiver and builds the
/// sequence child lazily in `desugar`, once the full scope is available.
struct MapCallSugar {
    inner: SugarBody,
    f: syn::ExprClosure,
    u128_shift_hint: bool,
}

impl Sugar for MapCallSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        if let Some(outcome) = captured_mutation_refusal(&self.f) {
            return Ok(outcome);
        }
        if let Some(outcome) = captured_runtime_read_refusal(&self.f, ctx) {
            return Ok(outcome);
        }
        let mapped = match reduce_map_body(&self.inner, &self.f, self.u128_shift_hint, ctx) {
            Ok(mapped) => mapped,
            Err(reduction) => return reduction,
        };
        Ok(Outcome::Complete(Desugared::Seq(mapped)))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
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
        if let Some(outcome) = captured_runtime_read_refusal(&self.f, ctx) {
            return outcome;
        }
        Outcome::from_opt(
            reduce_map(self.inner.as_ref(), &self.f, self.u128_shift_hint, ctx).map(Desugared::Seq),
        )
    }
}

pub(crate) struct MapTermSugar {
    pub(crate) inner: SugarBody,
    pub(crate) f: syn::ExprClosure,
    pub(crate) u128_shift_hint: bool,
}

impl Sugar for MapTermSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        if let Some(outcome) = captured_mutation_refusal(&self.f) {
            return Ok(outcome);
        }
        if let Some(outcome) = captured_runtime_read_refusal(&self.f, ctx) {
            return Ok(outcome);
        }
        let mapped = match reduce_map_body(&self.inner, &self.f, self.u128_shift_hint, ctx) {
            Ok(mapped) => mapped,
            Err(reduction) => return reduction,
        };
        let term = literal_array_term_from_mapped_values(&mapped)
            .ok_or_else(|| FactoryGap::new("map term produced non-literal mapped element"))?;
        Ok(Outcome::Complete(Desugared::Term(term)))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

fn captured_mutation_refusal(f: &syn::ExprClosure) -> Option<Outcome> {
    if !closure_body_mutates_captured_runtime_state(&Expr::Closure(f.clone())) {
        return None;
    }
    Some(Outcome::Incomplete(Effect::Unsupported {
        reason: "iterator/option adaptor `.map(|..| ..)` over a LITERAL domain whose closure body \
                 MUTATES captured runtime state (bin-2: runtime side effect during value \
                 construction, not constructed from source literals); refused"
            .to_string(),
    }))
}

fn captured_runtime_read_refusal(f: &syn::ExprClosure, ctx: &SugarCtx) -> Option<Outcome> {
    let names = runtime_capture_names(f, ctx.scope);
    if names.is_empty() {
        return None;
    }
    Some(Outcome::Incomplete(Effect::Unsupported {
        reason: format!(
            "iterator adaptor `.map(|..| ..)` over a LITERAL domain whose closure body READS \
             runtime capture `{}` (bin-2: runtime data, not constructed from source literals); \
             refused",
            names.into_iter().collect::<Vec<_>>().join(",")
        ),
    }))
}

fn runtime_capture_names(f: &syn::ExprClosure, scope: &TemporalScope) -> BTreeSet<String> {
    let mut params = BTreeSet::new();
    for pat in &f.inputs {
        collect_pat_idents(pat, &mut params);
    }
    let locals = closure_local_bindings(f);

    struct Scan<'a> {
        params: &'a BTreeSet<String>,
        locals: &'a BTreeSet<String>,
        scope: &'a TemporalScope,
        out: BTreeSet<String>,
    }

    impl<'ast> syn::visit::Visit<'ast> for Scan<'_> {
        fn visit_expr_path(&mut self, path: &'ast syn::ExprPath) {
            if let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) {
                if !self.params.contains(&name)
                    && !self.locals.contains(&name)
                    && self.scope.stable_let_binding_for_term(&name).is_none()
                    && self.scope.stable_term_binding_for_term(&name).is_none()
                    && self.scope.const_expr_for_path(&path.path).is_none()
                    && !self.scope.has_visible_fn(&name)
                    && !matches!(name.as_str(), "Some" | "None" | "Ok" | "Err")
                {
                    self.out.insert(name);
                    return;
                }
            }
            syn::visit::visit_expr_path(self, path);
        }

        fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
            if !matches!(strip_refs_groups(&call.func), Expr::Path(_)) {
                syn::visit::Visit::visit_expr(self, &call.func);
            }
            for arg in &call.args {
                syn::visit::Visit::visit_expr(self, arg);
            }
        }

        fn visit_expr_closure(&mut self, _closure: &'ast syn::ExprClosure) {
            // A nested closure has its own capture boundary.
        }
    }

    let mut scan = Scan {
        params: &params,
        locals: &locals,
        scope,
        out: BTreeSet::new(),
    };
    syn::visit::Visit::visit_expr(&mut scan, &f.body);
    scan.out
}

fn collect_pat_idents(pat: &Pat, out: &mut BTreeSet<String>) {
    match pat {
        Pat::Ident(p) => {
            out.insert(p.ident.to_string());
            if let Some((_, subpat)) = &p.subpat {
                collect_pat_idents(subpat, out);
            }
        }
        Pat::Reference(r) => collect_pat_idents(&r.pat, out),
        Pat::Paren(p) => collect_pat_idents(&p.pat, out),
        Pat::Type(t) => collect_pat_idents(&t.pat, out),
        Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_pat_idents(elem, out);
            }
        }
        _ => {}
    }
}

fn closure_local_bindings(f: &syn::ExprClosure) -> BTreeSet<String> {
    struct Locals {
        names: BTreeSet<String>,
    }

    impl<'ast> syn::visit::Visit<'ast> for Locals {
        fn visit_local(&mut self, local: &'ast syn::Local) {
            collect_pat_idents(&local.pat, &mut self.names);
            syn::visit::visit_local(self, local);
        }

        fn visit_expr_closure(&mut self, _closure: &'ast syn::ExprClosure) {
            // Nested closure locals belong to that nested closure.
        }
    }

    let mut locals = Locals {
        names: BTreeSet::new(),
    };
    syn::visit::Visit::visit_expr(&mut locals, &f.body);
    locals.names
}

fn reduce_map(
    inner: &dyn Sugar,
    f: &syn::ExprClosure,
    u128_shift_hint: bool,
    ctx: &SugarCtx,
) -> Option<Vec<DesugaredElem>> {
    let seq = inner.desugar(ctx).complete()?.into_seq()?;
    reduce_map_sequence(seq, f, u128_shift_hint, ctx)
}

fn reduce_map_body(
    inner: &SugarBody,
    f: &syn::ExprClosure,
    u128_shift_hint: bool,
    ctx: &SugarCtx,
) -> Result<Vec<DesugaredElem>, FactoryReduction> {
    let seq = match inner.reduce(ctx) {
        Ok(Outcome::Complete(d)) => d
            .into_seq()
            .ok_or_else(|| Err(FactoryGap::new("map receiver reduced to non-sequence")))?,
        Ok(Outcome::Incomplete(effect)) => return Err(Ok(Outcome::Incomplete(effect))),
        Err(gap) => return Err(Err(gap)),
    };
    reduce_map_sequence(seq, f, u128_shift_hint, ctx).ok_or_else(|| {
        Err(FactoryGap::new(
            "map closure did not reduce over literal sequence",
        ))
    })
}

fn reduce_map_sequence(
    seq: Vec<DesugaredElem>,
    f: &syn::ExprClosure,
    u128_shift_hint: bool,
    ctx: &SugarCtx,
) -> Option<Vec<DesugaredElem>> {
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
        let expr = rewrite_map_elem(f, &elem.expr, ctx)?;
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

fn literal_array_term_from_mapped_values(mapped: &[DesugaredElem]) -> Option<Rc<Term>> {
    let terms = mapped
        .iter()
        .map(|elem| const_val_term(elem.value.as_ref()?))
        .collect::<Option<Vec<_>>>()?;
    let inner = terms
        .iter()
        .map(|term| canonical_term_sig(term))
        .collect::<Vec<_>>()
        .join(",");
    Some(make_var(format!("literal:Array({inner})")))
}

fn rewrite_map_elem(f: &syn::ExprClosure, elem: &Expr, ctx: &SugarCtx) -> Option<Expr> {
    if f.inputs.len() != 1 {
        return None;
    }
    let body = closure_value_body(f)?;
    let mut bindings = ExprBindings::new();
    match closure_param_ident(f.inputs.first()?) {
        Some(param) => {
            bindings.insert(param, elem.clone());
        }
        None if closure_param_ignores_arg(f.inputs.first()?) => {}
        None => return None,
    }
    let expr = substitute_expr(body, &bindings);
    Some(substitute_stable_captures(&expr, ctx))
}

fn substitute_stable_captures(expr: &Expr, ctx: &SugarCtx) -> Expr {
    let mut bindings = ExprBindings::new();
    for (name, _) in ctx.scope.let_bindings_iter() {
        if let Some(init) = ctx.scope.stable_let_binding_for_term(name) {
            bindings.insert(name.clone(), init.clone());
        }
    }
    substitute_expr(expr, &bindings)
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

fn closure_param_ignores_arg(pat: &Pat) -> bool {
    match pat {
        Pat::Wild(_) => true,
        Pat::Reference(r) => closure_param_ignores_arg(&r.pat),
        Pat::Paren(p) => closure_param_ignores_arg(&p.pat),
        Pat::Type(t) => closure_param_ignores_arg(&t.pat),
        _ => false,
    }
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
