// SPDX-License-Identifier: Apache-2.0
//
// `aggregate_decomp` -- assertion-surface decomposition for array/slice equality.
//
// This is the array/slice sibling of `tuple_decomp`: `assert_eq!(&[1, 2], &[1, 3])`
// is not a scalar assertion, but it is fully determined by source text. Lower it to
// scalar teeth: a length equality plus one equality per element. Runtime elements or
// unstable bindings Incomplete at desugar time.

use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, atomic_, num, str_const, Term};
use syn::{BinOp, Expr, ExprMacro};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_composite, build_term, SugarBuildCtx};
use crate::sugar::literal::RUNTIME_ELEM_REASON;
use crate::sugar::monadic::{is_grounded_literal_term, RES_OK};
use crate::{
    callsite_assertion_name, parse_macro_args, path_to_variant_string, repeat_count_in_scope,
    strip_refs_groups, token_key, AssertionFactKind, Desugared, Effect, Outcome, RelationOp, Sugar,
    SugarCtx, Warrant, SUGAR_SEQ_CAP,
};

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::fallback_with_ordering(
        "assertion_surface_aggregate_decomp",
        SugarRole::AssertionSurface,
        &[
            "assertion_surface_relation_macro",
            "assertion_surface_assert_macro",
        ],
        recognize,
    );

fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(expr_macro) = expr else {
        return None;
    };
    let (lhs, rhs, op, bare_assert) = macro_eq_operands(expr_macro)?;
    let shape_matches = if bare_assert {
        explicit_aggregateish(&lhs) || explicit_aggregateish(&rhs)
    } else {
        aggregateish(&lhs) || aggregateish(&rhs)
    };
    if !shape_matches {
        return None;
    }
    Some(Box::new(AggregateDecompSugar { lhs, rhs, op }))
}

fn macro_eq_operands(expr_macro: &ExprMacro) -> Option<(Expr, Expr, RelationOp, bool)> {
    let name = expr_macro.mac.path.segments.last()?.ident.to_string();
    let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
    match name.as_str() {
        "assert_eq" => {
            if args.exprs.len() < 2 {
                return None;
            }
            Some((
                args.exprs[0].clone(),
                args.exprs[1].clone(),
                RelationOp::Eq,
                false,
            ))
        }
        "assert" => {
            let Expr::Binary(binary) = args.exprs.first()? else {
                return None;
            };
            if !matches!(binary.op, BinOp::Eq(_)) {
                return None;
            }
            Some((
                (*binary.left).clone(),
                (*binary.right).clone(),
                RelationOp::Eq,
                true,
            ))
        }
        _ => None,
    }
}

fn aggregateish(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Repeat(_) => true,
        Expr::Struct(_) | Expr::Path(_) => true,
        Expr::Index(index) => is_full_range(&index.index) || aggregateish(&index.expr),
        Expr::Cast(cast) => aggregateish(&cast.expr),
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect") =>
        {
            true
        }
        Expr::Call(call) => call.args.iter().any(explicit_aggregateish),
        Expr::Paren(paren) => aggregateish(&paren.expr),
        Expr::Group(group) => aggregateish(&group.expr),
        Expr::Reference(reference) => aggregateish(&reference.expr),
        _ => false,
    }
}

fn explicit_aggregateish(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Repeat(_) | Expr::Struct(_) => true,
        Expr::Index(index) => is_full_range(&index.index) || explicit_aggregateish(&index.expr),
        Expr::Cast(cast) => explicit_aggregateish(&cast.expr),
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect") =>
        {
            true
        }
        Expr::Call(call) => call.args.iter().any(explicit_aggregateish),
        Expr::Paren(paren) => explicit_aggregateish(&paren.expr),
        Expr::Group(group) => explicit_aggregateish(&group.expr),
        Expr::Reference(reference) => explicit_aggregateish(&reference.expr),
        Expr::Path(_) => false,
        _ => false,
    }
}

struct AggregateDecompSugar {
    lhs: Expr,
    rhs: Expr,
    op: RelationOp,
}

impl Sugar for AggregateDecompSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let let_inits = scope_let_inits(ctx);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let lhs = aggregate_components(&self.lhs, &fcx, ctx, &mut BTreeSet::new());
        let rhs = aggregate_components(&self.rhs, &fcx, ctx, &mut BTreeSet::new());
        match (lhs, rhs) {
            (Ok(Some(lhs)), Ok(Some(rhs))) => decompose_eq(lhs, rhs, ctx),
            (Err(outcome), _) | (_, Err(outcome)) => outcome,
            _ => fallback_relation(&self.lhs, &self.rhs, self.op, &fcx, ctx),
        }
    }
}

fn decompose_eq(lhs: Vec<Rc<Term>>, rhs: Vec<Rc<Term>>, ctx: &SugarCtx) -> Outcome {
    let mut atoms = Vec::with_capacity(lhs.len().min(rhs.len()) + 1);
    atoms.push(atomic_(
        "=".to_string(),
        vec![num(lhs.len() as i128), num(rhs.len() as i128)],
    ));
    let mut anchor = None;
    for (l, r) in lhs.into_iter().zip(rhs.into_iter()) {
        let l = strip_value_ref(l);
        let r = strip_value_ref(r);
        if anchor.is_none() {
            anchor = Some(Rc::clone(&l));
        }
        atoms.push(atomic_("=".to_string(), vec![l, r]));
    }
    let name =
        anchor.and_then(|term| callsite_assertion_name(term.as_ref(), ctx.scope.local_scope()));
    Outcome::Complete(Desugared::Constraints {
        atom: and_(atoms),
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn aggregate_components(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
    seen: &mut BTreeSet<String>,
) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    match strip_refs_groups(expr) {
        Expr::Array(array) => {
            let mut out = Vec::with_capacity(array.elems.len());
            for elem in &array.elems {
                append_expr_components(&mut out, elem, fcx, ctx, seen)?;
            }
            Ok(Some(out))
        }
        Expr::Repeat(repeat) => {
            let Some(count) = repeat_count_in_scope(&repeat.len, ctx.scope) else {
                return Err(Outcome::Incomplete(Effect::ArrayRepeat {
                    boundary: token_key(expr),
                }));
            };
            if count > SUGAR_SEQ_CAP as usize {
                return Err(Outcome::Incomplete(Effect::ArrayRepeat {
                    boundary: token_key(expr),
                }));
            }
            let mut elem = Vec::new();
            append_expr_components(&mut elem, &repeat.expr, fcx, ctx, seen)?;
            let Some(total) = elem.len().checked_mul(count) else {
                return Err(Outcome::Incomplete(Effect::ArrayRepeat {
                    boundary: token_key(expr),
                }));
            };
            if total > SUGAR_SEQ_CAP as usize {
                return Err(Outcome::Incomplete(Effect::ArrayRepeat {
                    boundary: token_key(expr),
                }));
            }
            let mut out = Vec::with_capacity(total);
            for _ in 0..count {
                out.extend(elem.iter().cloned());
            }
            Ok(Some(out))
        }
        Expr::Struct(strukt) => {
            if strukt.rest.is_some() {
                return Err(Outcome::Incomplete(Effect::Unsupported {
                    reason: format!(
                        "struct literal with `..rest` is not fully pinned from the literal: `{}`",
                        token_key(expr)
                    ),
                }));
            }
            let mut fields: Vec<(String, &Expr)> = strukt
                .fields
                .iter()
                .map(|field| {
                    let name = match &field.member {
                        syn::Member::Named(ident) => ident.to_string(),
                        syn::Member::Unnamed(index) => index.index.to_string(),
                    };
                    (name, &field.expr)
                })
                .collect();
            fields.sort_by(|a, b| a.0.cmp(&b.0));
            let mut out = Vec::with_capacity(fields.len() * 2 + 1);
            out.push(str_const(format!(
                "struct:{}",
                path_to_variant_string(&strukt.path)
            )));
            for (name, value) in fields {
                out.push(str_const(format!("field:{name}")));
                append_expr_components(&mut out, value, fcx, ctx, seen)?;
            }
            Ok(Some(out))
        }
        Expr::Index(index) if is_full_range(&index.index) => {
            aggregate_components(&index.expr, fcx, ctx, seen)
        }
        Expr::Cast(cast) => aggregate_components(&cast.expr, fcx, ctx, seen),
        Expr::MethodCall(call)
            if call.method == "collect"
                && call.args.is_empty()
                && crate::sugar::collect::collects_vec(call) =>
        {
            collect_vec_components(&call.receiver, fcx, ctx, seen)
        }
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return Ok(None);
            };
            if !seen.insert(name.clone()) {
                return Ok(None);
            }
            let resolved = ctx
                .scope
                .temporal_rewrite_expr_for(&name)
                .or_else(|| ctx.scope.stable_let_binding_for_term(&name).cloned());
            let Some(init) = resolved else {
                return Ok(None);
            };
            let result = aggregate_components(&init, &fcx.with_bound_path(&name), ctx, seen);
            seen.remove(&name);
            result
        }
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect") =>
        {
            if call.method == "unwrap" && !call.args.is_empty() {
                return Ok(None);
            }
            if call.method == "expect" && call.args.len() != 1 {
                return Ok(None);
            }
            unwrap_result_components(&call.receiver, fcx, ctx, seen)
        }
        Expr::Call(call) => structural_call_components(call, fcx, ctx, seen),
        Expr::Macro(expr_macro) => vec_macro_components(expr_macro, fcx, ctx, seen),
        Expr::Paren(paren) => aggregate_components(&paren.expr, fcx, ctx, seen),
        Expr::Group(group) => aggregate_components(&group.expr, fcx, ctx, seen),
        _ => Ok(None),
    }
}

fn collect_vec_components(
    receiver: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
    seen: &mut BTreeSet<String>,
) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    let seq = match build_composite(receiver, fcx).desugar(ctx) {
        Outcome::Complete(desugared) => {
            let Some(seq) = desugared.into_seq() else {
                return Ok(None);
            };
            seq
        }
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    let mut out = Vec::with_capacity(seq.len());
    for elem in seq {
        append_expr_components(&mut out, &elem.expr, fcx, ctx, seen)?;
    }
    Ok(Some(out))
}

fn append_expr_components(
    out: &mut Vec<Rc<Term>>,
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
    seen: &mut BTreeSet<String>,
) -> Result<(), Outcome> {
    match aggregate_components(expr, fcx, ctx, seen)? {
        Some(parts) => {
            out.extend(parts);
            Ok(())
        }
        None => {
            let term = text_determined_term(expr, fcx, ctx)?;
            match grounded_term_components(term)? {
                Some(parts) => {
                    out.extend(parts);
                    Ok(())
                }
                None => Err(runtime_hit()),
            }
        }
    }
}

fn structural_call_components(
    call: &syn::ExprCall,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
    seen: &mut BTreeSet<String>,
) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    let Some(name) = structural_ctor_term_name(&call.func) else {
        return Ok(None);
    };
    match (name, call.args.len()) {
        ("opt:some" | "res:ok" | "res:err", 1) => {
            let Some(parts) = aggregate_components(&call.args[0], fcx, ctx, seen)? else {
                return Ok(None);
            };
            let mut out = vec![str_const(format!("ctor:{name}:1"))];
            out.extend(parts);
            Ok(Some(out))
        }
        _ => Ok(None),
    }
}

fn vec_macro_components(
    expr_macro: &ExprMacro,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
    seen: &mut BTreeSet<String>,
) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    let Some(name) = expr_macro
        .mac
        .path
        .segments
        .last()
        .map(|seg| seg.ident.to_string())
    else {
        return Ok(None);
    };
    if name != "vec" {
        return Ok(None);
    }
    let Ok(args) = parse_macro_args(expr_macro.mac.tokens.clone()) else {
        return Ok(None);
    };
    let mut out = Vec::new();
    for expr in args.exprs {
        append_expr_components(&mut out, &expr, fcx, ctx, seen)?;
    }
    Ok(Some(out))
}

fn unwrap_result_components(
    receiver: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
    seen: &mut BTreeSet<String>,
) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    match strip_refs_groups(receiver) {
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return Ok(None);
            };
            if !seen.insert(name.clone()) {
                return Ok(None);
            }
            let resolved = ctx
                .scope
                .temporal_rewrite_expr_for(&name)
                .or_else(|| ctx.scope.stable_let_binding_for_term(&name).cloned());
            let Some(init) = resolved else {
                return Err(runtime_hit());
            };
            let result = unwrap_result_components(&init, &fcx.with_bound_path(&name), ctx, seen);
            seen.remove(&name);
            result
        }
        Expr::Call(call) if call.args.len() == 1 && is_try_from_callee(&call.func) => {
            aggregate_components(&call.args[0], fcx, ctx, seen)
        }
        Expr::Call(_) => {
            let term = build_term(receiver, fcx).desugar(ctx);
            let Outcome::Complete(desugared) = term else {
                return match term {
                    Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
                    Outcome::Complete(_) => Ok(None),
                };
            };
            let Some(term) = desugared.into_term() else {
                return Ok(None);
            };
            let Term::Ctor { name, args } = term.as_ref() else {
                return Ok(None);
            };
            if name == RES_OK && args.len() == 1 {
                grounded_term_components(Rc::clone(&args[0]))
            } else {
                Ok(None)
            }
        }
        Expr::Paren(paren) => unwrap_result_components(&paren.expr, fcx, ctx, seen),
        Expr::Group(group) => unwrap_result_components(&group.expr, fcx, ctx, seen),
        _ => Ok(None),
    }
}

fn text_determined_term(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Complete(desugared) => {
            let Some(term) = desugared.into_term() else {
                return Err(runtime_hit());
            };
            if is_grounded_literal_term(term.as_ref()) {
                Ok(term)
            } else {
                Err(runtime_hit())
            }
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn grounded_term_components(term: Rc<Term>) -> Result<Option<Vec<Rc<Term>>>, Outcome> {
    let term = strip_value_ref(term);
    match term.as_ref() {
        Term::Ctor { name, .. } if name == "agg:Array" => Err(runtime_hit()),
        Term::Var { name } if name.starts_with("agg:Array(") => Err(runtime_hit()),
        Term::Const { .. } => Ok(Some(vec![Rc::clone(&term)])),
        Term::Var { name } if name.starts_with("literal:") => Ok(Some(vec![Rc::clone(&term)])),
        Term::Var { .. } => Ok(None),
        Term::Ctor { name, args } if text_structural_ctor(name) => {
            let mut out = Vec::with_capacity(args.len() + 1);
            out.push(str_const(format!("ctor:{name}:{}", args.len())));
            for arg in args {
                let Some(parts) = grounded_term_components(Rc::clone(arg))? else {
                    return Ok(None);
                };
                out.extend(parts);
            }
            Ok(Some(out))
        }
        _ => Ok(None),
    }
}

fn text_structural_ctor(name: &str) -> bool {
    !name.starts_with("call:")
        && !name.starts_with("method:")
        && (name == "literal:Array"
            || name.starts_with("struct:")
            || name.starts_with("field:")
            || matches!(
                name,
                "opt:some" | "opt:none" | "res:ok" | "res:err" | "ref" | "ref_mut"
            ))
}

fn structural_ctor_term_name(func: &Expr) -> Option<&'static str> {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return None;
    };
    path.path
        .segments
        .last()
        .and_then(|segment| match segment.ident.to_string().as_str() {
            "Some" => Some("opt:some"),
            "Ok" => Some("res:ok"),
            "Err" => Some("res:err"),
            "None" => Some("opt:none"),
            _ => None,
        })
}

fn fallback_relation(
    lhs: &Expr,
    rhs: &Expr,
    op: RelationOp,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Outcome {
    let lhs = match text_term_or_backstop(lhs, fcx, ctx) {
        Ok(term) => term,
        Err(outcome) => return outcome,
    };
    let rhs = match text_term_or_backstop(rhs, fcx, ctx) {
        Ok(term) => term,
        Err(outcome) => return outcome,
    };
    let entry = crate::assertion_entry_from_relation(lhs, rhs, op, ctx.scope);
    Outcome::Complete(Desugared::Constraints {
        atom: entry.atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name: entry.name },
    })
}

fn text_term_or_backstop(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Complete(desugared) => desugared.into_term().ok_or_else(runtime_hit),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn is_try_from_callee(func: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(func) else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "try_from")
}

fn is_full_range(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Range(range) if range.start.is_none() && range.end.is_none())
}

fn strip_value_ref(mut term: Rc<Term>) -> Rc<Term> {
    loop {
        match term.as_ref() {
            Term::Ctor { name, args }
                if matches!(name.as_str(), "ref" | "ref_mut") && args.len() == 1 =>
            {
                term = Rc::clone(&args[0]);
            }
            _ => return term,
        }
    }
}

fn runtime_hit() -> Outcome {
    Outcome::Incomplete(Effect::Unsupported {
        reason: RUNTIME_ELEM_REASON.to_string(),
    })
}

fn scope_let_inits<'a, 'c>(ctx: &SugarCtx<'a, 'c>) -> BTreeMap<String, &'a Expr> {
    ctx.scope
        .let_bindings_iter()
        .map(|(name, init)| (name.clone(), init))
        .collect()
}
