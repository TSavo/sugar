// SPDX-License-Identifier: Apache-2.0
//
// Shared recognition gates for stdlib sequence-method Sugars.

use std::collections::BTreeMap;

use syn::{Expr, ExprCall, ExprRange, GenericArgument, Type, UnOp};

use crate::sugar::factory::{
    build_composite, has_composite, CompositeFloor, SugarBody, SugarBuildCtx,
};
use crate::sugar::literal::OVERSIZE_DOMAIN_REASON;
use crate::sugar::literal_slice;
use crate::{
    const_eval, const_int, literal_byte_string_value, literal_string_value, peel_fold_adaptors,
    peel_fold_adaptors_in_scope, resolve_value_call_inline, strip_refs_groups, ConstVal, Desugared,
    DesugaredElem, Effect, LiftOptions, Outcome, Sugar, SugarCtx, TemporalScope, SUGAR_SEQ_CAP,
};

pub(crate) fn is_literal_sequence_base(expr: &Expr) -> bool {
    (match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Range(_) => true,
        // A LITERAL-count repeat `[elem; N]` is a finite literal sequence (N copies of
        // elem); the `array_repeat` composite recognizer expands it. Non-literal counts
        // (`[x; SIZE]`) are not finite-by-construction HERE (ctx-free) -- the scope-aware
        // `is_literal_sequence_base_in_scope` resolves a const-bound count.
        Expr::Repeat(repeat) => crate::repeat_count_literal(&repeat.len).is_some(),
        // Finite-collection constructors over written literals (`vec![a, b, c]`,
        // `Vec::from([a, b, c])`) construct exactly an array literal -- classified the same.
        other => crate::sugar::collection_literal::collection_literal_array(other).is_some(),
    }) || literal_iter_call_base(expr)
        || literal_method_sequence_base(expr)
}

/// Scope-aware [`is_literal_sequence_base`]: additionally treats a CONST-length repeat
/// (`const SIZE: usize = 3; [7; SIZE]`) as a finite literal sequence, resolving the count
/// through the scope's const registry (`repeat_count_in_scope`). A strict superset of the
/// ctx-free classifier -- it only ever ADMITS more (a const-evaluable length); a runtime /
/// non-const length is still rejected, so the repeat stays the `Effect::ArrayRepeat` refuse.
/// Used at the `build_literal_sequence_composite` chokepoint so a const-length repeat reaches
/// the same constructive `LiteralRepeatSugar` floor (and element-wise grounding teeth) that a
/// literal-length repeat already does.
pub(crate) fn is_literal_sequence_base_in_scope(expr: &Expr, scope: &TemporalScope) -> bool {
    (match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Range(_) => true,
        Expr::Repeat(repeat) => crate::repeat_count_in_scope(&repeat.len, scope).is_some(),
        // Finite-collection constructors (`vec![..]`, `Vec::from([..])`) -- same as the
        // ctx-free classifier; recognition is purely syntactic, no scope needed.
        other => crate::sugar::collection_literal::collection_literal_array(other).is_some(),
    }) || literal_iter_call_base(expr)
        || literal_method_sequence_base(expr)
}

pub(crate) fn resolves_literal_sequence<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> bool {
    let Some((base, _)) = peel_fold_adaptors(expr, let_inits, 0) else {
        return false;
    };
    is_literal_sequence_base(base) || literal_slice::is_literal_slice_base(base, let_inits)
}

pub(crate) fn resolves_literal_array_sequence<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> bool {
    let Some((base, _)) = peel_fold_adaptors(expr, let_inits, 0) else {
        return false;
    };
    matches!(strip_refs_groups(base), Expr::Array(_))
}

pub(crate) fn build_literal_sequence_composite(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    if let Some(node) = build_owned_sequence_composite(expr, fcx) {
        return Some(node);
    }
    if let Some(inlined) = resolve_vec_value_call_inline(expr, fcx.scope(), fcx.options()) {
        return build_literal_sequence_composite(&inlined, fcx);
    }
    let (base, adaptors) = peel_fold_adaptors_in_scope(expr, fcx.let_inits(), fcx.scope(), 0)?;
    // Scope-aware base gate: a const-length repeat (`[7; SIZE]`) resolves to a finite literal
    // sequence here so the constructive floor (and its element-wise teeth) is reached.
    if !is_literal_sequence_base_in_scope(&base, fcx.scope())
        && !literal_slice::is_literal_slice_base_in_scope(&base, fcx.let_inits(), fcx.scope())
        && !literal_iter_call_base(&base)
        && !has_composite(&base, fcx)
    {
        return None;
    }
    let mut node = if literal_iter_call_base(&base) {
        Box::new(LiteralIterCallSugar {
            seq: literal_iter_call_sequence(&base)?,
        }) as Box<dyn Sugar>
    } else if literal_method_sequence_base(&base) {
        Box::new(LiteralIterCallSugar {
            seq: literal_method_sequence(&base)?,
        }) as Box<dyn Sugar>
    } else {
        build_composite(&base, fcx)
    };
    for wrap in adaptors {
        node = wrap(node, fcx);
    }
    Some(node)
}

fn build_owned_sequence_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(node) = crate::sugar::cycle::recognize_cycle_take_composite(expr, fcx) {
        return Some(node);
    }
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    match call.method.to_string().as_str() {
        "repeat" if call.args.len() == 1 => {
            let count = method_arg_const_usize(call, Some(fcx.scope()))?;
            literal_sequence_static_len_for_build(&call.receiver, fcx)?;
            Some(Box::new(RepeatSequenceSugar {
                inner: SugarBody::from_node(build_literal_sequence_composite(&call.receiver, fcx)?),
                count,
            }))
        }
        "collect" if call.args.is_empty() && collects_vec_like(call) => {
            Some(build_composite(&call.receiver, fcx))
        }
        _ => None,
    }
}

struct RepeatSequenceSugar {
    inner: SugarBody<CompositeFloor>,
    count: usize,
}

impl Sugar for RepeatSequenceSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(desugared) => desugared
                .into_seq()
                .unwrap_or_else(|| repeat_sequence_gap("receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let len = match seq.len().checked_mul(self.count) {
            Some(len) if len <= SUGAR_SEQ_CAP as usize => len,
            _ => {
                return Outcome::Incomplete(Effect::LiteralDomain {
                    reason: OVERSIZE_DOMAIN_REASON.to_string(),
                })
            }
        };
        let mut out = Vec::with_capacity(len);
        for _ in 0..self.count {
            out.extend(seq.iter().cloned());
        }
        Outcome::Complete(Desugared::Seq(out))
    }
}

fn repeat_sequence_gap(reason: &str) -> ! {
    panic!("repeat sequence did not reach a lawful floor: {reason}")
}

struct LiteralIterCallSugar {
    seq: Vec<DesugaredElem>,
}

impl Sugar for LiteralIterCallSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::Seq(self.seq.clone()))
    }
}

fn literal_iter_call_base(expr: &Expr) -> bool {
    literal_iter_call_len_expr(expr).is_some()
}

fn literal_method_sequence_base(expr: &Expr) -> bool {
    literal_method_sequence(expr).is_some()
}

fn literal_method_sequence(expr: &Expr) -> Option<Vec<DesugaredElem>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    match call.method.to_string().as_str() {
        "chars" => literal_string_value(&call.receiver).map(|value| {
            value
                .chars()
                .map(|ch| DesugaredElem {
                    expr: char_expr(ch),
                    value: Some(ConstVal::Char(ch)),
                })
                .collect()
        }),
        "bytes" => literal_string_value(&call.receiver).map(|value| {
            value
                .bytes()
                .map(|byte| DesugaredElem {
                    expr: byte_expr(byte),
                    value: Some(ConstVal::Int(i128::from(byte))),
                })
                .collect()
        }),
        "iter" => literal_byte_string_value(&call.receiver).map(|bytes| {
            bytes
                .into_iter()
                .map(|byte| DesugaredElem {
                    expr: byte_expr(byte),
                    value: Some(ConstVal::Int(i128::from(byte))),
                })
                .collect()
        }),
        _ => None,
    }
}

fn char_expr(ch: char) -> Expr {
    syn::parse_str(&format!("{ch:?}")).expect("char debug form is a Rust char literal")
}

fn byte_expr(byte: u8) -> Expr {
    syn::parse_str(&format!("{byte}u8")).expect("u8 literal text is a Rust expression")
}

fn literal_iter_call_sequence(expr: &Expr) -> Option<Vec<DesugaredElem>> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    match literal_iter_call_name(call)?.as_str() {
        "empty" if call.args.is_empty() => Some(Vec::new()),
        "once" if call.args.len() == 1 => {
            let elem = call.args.first()?.clone();
            let value = const_eval(&elem, &BTreeMap::new())?;
            Some(vec![DesugaredElem {
                expr: elem,
                value: Some(value),
            }])
        }
        _ => None,
    }
}

fn literal_iter_call_len_expr(expr: &Expr) -> Option<usize> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    literal_iter_call_len(call)
}

fn literal_iter_call_len(call: &ExprCall) -> Option<usize> {
    match literal_iter_call_name(call)?.as_str() {
        "empty" if call.args.is_empty() => Some(0),
        "once"
            if call.args.len() == 1
                && const_eval(call.args.first()?, &BTreeMap::new()).is_some() =>
        {
            Some(1)
        }
        _ => None,
    }
}

fn literal_iter_call_name(call: &ExprCall) -> Option<String> {
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    path.path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
}

pub(crate) fn finite_int_iter_sequence(expr: &Expr) -> Option<Vec<DesugaredElem>> {
    finite_int_iter_sequence_with_env(expr, &BTreeMap::new())
}

pub(crate) fn finite_int_iter_sequence_in_build_ctx(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<Vec<DesugaredElem>> {
    let env = const_env_from_build_ctx(fcx);
    finite_int_iter_sequence_with_env(expr, &env)
}

fn finite_int_iter_sequence_with_env(
    expr: &Expr,
    env: &BTreeMap<String, ConstVal>,
) -> Option<Vec<DesugaredElem>> {
    finite_iter_sequence(expr, 0).or_else(|| {
        crate::const_eval_finite_int_iter_values(expr, env, None)?
            .into_iter()
            .map(|value| {
                let expr = value.to_expr()?;
                Some(DesugaredElem {
                    expr,
                    value: Some(value),
                })
            })
            .collect()
    })
}

pub(crate) fn const_usize_in_build_ctx(expr: &Expr, fcx: &SugarBuildCtx) -> Option<usize> {
    crate::repeat_count_in_scope(expr, fcx.scope()).or_else(|| {
        let env = const_env_from_build_ctx(fcx);
        const_eval(expr, &env)
            .and_then(|value| value.as_int())
            .and_then(|value| usize::try_from(value).ok())
    })
}

fn const_env_from_build_ctx(fcx: &SugarBuildCtx) -> BTreeMap<String, ConstVal> {
    let mut env = BTreeMap::new();
    for _ in 0..fcx.let_inits().len().saturating_add(1) {
        let mut changed = false;
        for (name, expr) in fcx.let_inits() {
            if env.contains_key(name.as_str()) {
                continue;
            }
            if let Some(value) = const_eval(expr, &env) {
                env.insert(name.clone(), value);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    env
}

fn finite_iter_sequence(expr: &Expr, depth: usize) -> Option<Vec<DesugaredElem>> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Call(_) => literal_iter_call_sequence(expr),
        Expr::MethodCall(call) if call.args.is_empty() => match call.method.to_string().as_str() {
            "collect" if collects_vec_like(call) => finite_iter_sequence(&call.receiver, depth + 1),
            "iter" | "iter_mut" | "into_iter" | "cloned" | "copied" | "fuse" | "peekable"
            | "by_ref" | "clone" | "rev" | "enumerate" | "to_vec" | "as_slice" | "to_owned"
            | "into_vec" => finite_iter_sequence(&call.receiver, depth + 1),
            _ => None,
        },
        Expr::MethodCall(call) if call.args.len() == 1 => match call.method.to_string().as_str() {
            "take" => {
                let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                if let Some((elem, value)) = iter_repeat_call_elem(&call.receiver) {
                    return repeat_elem_sequence(elem, value, n);
                }
                let mut seq = finite_iter_sequence(&call.receiver, depth + 1)?;
                seq.truncate(n);
                Some(seq)
            }
            "skip" => {
                let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                Some(
                    finite_iter_sequence(&call.receiver, depth + 1)?
                        .into_iter()
                        .skip(n)
                        .collect(),
                )
            }
            "step_by" => {
                let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                if n == 0 {
                    return None;
                }
                Some(
                    finite_iter_sequence(&call.receiver, depth + 1)?
                        .into_iter()
                        .step_by(n)
                        .collect(),
                )
            }
            "chain" => {
                let mut left = finite_iter_sequence(&call.receiver, depth + 1)?;
                let right = finite_iter_sequence(&call.args[0], depth + 1)?;
                let len = left.len().checked_add(right.len())?;
                if len > SUGAR_SEQ_CAP as usize {
                    return None;
                }
                left.extend(right);
                Some(left)
            }
            _ => None,
        },
        _ => None,
    }
}

fn iter_repeat_call_elem(expr: &Expr) -> Option<(Expr, ConstVal)> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if literal_iter_call_name(call)?.as_str() != "repeat" || call.args.len() != 1 {
        return None;
    }
    let elem = call.args.first()?.clone();
    let value = const_eval(&elem, &BTreeMap::new())?;
    Some((elem, value))
}

fn repeat_elem_sequence(elem: Expr, value: ConstVal, count: usize) -> Option<Vec<DesugaredElem>> {
    if count > SUGAR_SEQ_CAP as usize {
        return None;
    }
    Some(
        (0..count)
            .map(|_| DesugaredElem {
                expr: elem.clone(),
                value: Some(value.clone()),
            })
            .collect(),
    )
}

fn method_arg_const_usize(
    call: &syn::ExprMethodCall,
    scope: Option<&TemporalScope>,
) -> Option<usize> {
    if call.args.len() != 1 {
        return None;
    }
    scope
        .and_then(|scope| crate::repeat_count_in_scope(&call.args[0], scope))
        .or_else(|| usize::try_from(const_int(&call.args[0])?).ok())
}

fn collects_vec_like(call: &syn::ExprMethodCall) -> bool {
    call.turbofish.as_ref().is_some_and(|args| {
        args.args.iter().any(|arg| {
            matches!(
                arg,
                GenericArgument::Type(syn::Type::Path(path))
                    if path.qself.is_none()
                        && path.path.segments.iter().any(|segment| segment.ident == "Vec")
            )
        })
    })
}

fn resolve_vec_value_call_inline(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
) -> Option<Expr> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    call_returns_vec(call, scope)?;
    let args: Vec<Expr> = call.args.iter().cloned().collect();
    let inlined = resolve_value_call_inline(&call.func, &args, scope, options)?;
    Some(annotate_vec_collect_return(inlined))
}

fn call_returns_vec(call: &ExprCall, scope: &TemporalScope) -> Option<()> {
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    let name = path.path.get_ident()?.to_string();
    let helper = scope.fn_registry().lookup(&name)?;
    return_type_is_vec(&helper.sig.output).then_some(())
}

fn annotate_vec_collect_return(expr: Expr) -> Expr {
    let Expr::MethodCall(mut call) = expr else {
        return expr;
    };
    if call.method == "collect" && call.args.is_empty() && call.turbofish.is_none() {
        call.turbofish = Some(syn::parse_quote!(::<Vec<_>>));
    }
    Expr::MethodCall(call)
}

fn return_type_is_vec(output: &syn::ReturnType) -> bool {
    let syn::ReturnType::Type(_, ty) = output else {
        return false;
    };
    matches!(
        ty.as_ref(),
        Type::Path(path)
            if path.qself.is_none()
                && path.path.segments.iter().any(|segment| segment.ident == "Vec")
    )
}

pub(crate) fn literal_sequence_static_len_in_scope<'a>(
    expr: &Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
) -> Option<usize> {
    literal_sequence_static_len_inner(expr, let_inits, Some(scope), None, 0)
}

pub(crate) fn literal_sequence_static_len_for_build<'a, 'e>(
    expr: &Expr,
    fcx: &SugarBuildCtx<'a, 'e>,
) -> Option<usize> {
    literal_sequence_static_len_inner(
        expr,
        fcx.let_inits(),
        Some(fcx.scope()),
        Some(fcx.options()),
        0,
    )
}

pub(crate) fn literal_range_sequence_static_len_in_scope<'a>(
    expr: &Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
) -> Option<usize> {
    literal_range_sequence_static_len_inner(expr, let_inits, scope, 0)
}

pub(crate) struct StaticCollectionLen {
    pub(crate) source: Expr,
    pub(crate) len: usize,
}

pub(crate) fn literal_collection_adapter_static_len_in_scope<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
) -> Option<StaticCollectionLen> {
    let proof = literal_collection_static_len_proof_inner(expr, let_inits, scope, 0)?;
    proof
        .saw_length_only_adapter
        .then_some(StaticCollectionLen {
            source: proof.source,
            len: proof.len,
        })
}

fn literal_sequence_static_len_inner<'a>(
    expr: &Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: Option<&'a TemporalScope>,
    options: Option<&'a LiftOptions>,
    depth: usize,
) -> Option<usize> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        _ if literal_byte_string_value(expr).is_some() => {
            Some(literal_byte_string_value(expr)?.len())
        }
        Expr::Array(array) => Some(array.elems.len()),
        Expr::Range(range) => literal_range_len(range),
        Expr::Index(index) => match scope {
            Some(scope) => literal_slice::literal_slice_len_in_scope(expr, let_inits, scope)
                .or_else(|| {
                    let len = literal_sequence_static_len_inner(
                        &index.expr,
                        let_inits,
                        Some(scope),
                        options,
                        depth + 1,
                    )?;
                    let (start, end) = literal_slice::slice_bounds(&index.index, len)?;
                    Some(end - start)
                }),
            None => literal_slice::literal_slice_len(expr, let_inits).or_else(|| {
                let len = literal_sequence_static_len_inner(
                    &index.expr,
                    let_inits,
                    None,
                    None,
                    depth + 1,
                )?;
                let (start, end) = literal_slice::slice_bounds(&index.index, len)?;
                Some(end - start)
            }),
        },
        Expr::Call(call) => literal_iter_call_len(call).or_else(|| {
            let scope = scope?;
            let inlined = match options {
                Some(options) => resolve_vec_value_call_inline(expr, scope, options)?,
                None => {
                    let default_options = LiftOptions::default();
                    resolve_vec_value_call_inline(expr, scope, &default_options)?
                }
            };
            literal_sequence_static_len_inner(&inlined, let_inits, Some(scope), options, depth + 1)
        }),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if let Some(current) = scope.and_then(|scope| scope.temporal_rewrite_expr_for(&name)) {
                return literal_sequence_static_len_inner(
                    &current,
                    let_inits,
                    scope,
                    options,
                    depth + 1,
                );
            }
            let init = let_inits
                .get(&name)
                .copied()
                .or_else(|| scope.and_then(|scope| scope.stable_let_binding_for_term(&name)))?;
            literal_sequence_static_len_inner(init, let_inits, scope, options, depth + 1)
        }
        Expr::MethodCall(call) if call.args.is_empty() => match call.method.to_string().as_str() {
            "collect" if collects_vec_like(call) => literal_sequence_static_len_inner(
                &call.receiver,
                let_inits,
                scope,
                options,
                depth + 1,
            ),
            // Value-identity adaptors over the element sequence: same length as the receiver.
            "iter" | "iter_mut" | "into_iter" | "cloned" | "copied" | "fuse" | "clone" | "rev"
            | "enumerate" | "to_vec" | "as_slice" | "to_owned" | "into_vec" => {
                literal_sequence_static_len_inner(
                    &call.receiver,
                    let_inits,
                    scope,
                    options,
                    depth + 1,
                )
            }
            _ => None,
        },
        Expr::MethodCall(call) if call.args.len() == 1 => {
            if call.method == "take" && iter_repeat_call_elem(&call.receiver).is_some() {
                return method_arg_const_usize(call, scope);
            }
            if call.method == "repeat" {
                let base_len = literal_sequence_static_len_inner(
                    &call.receiver,
                    let_inits,
                    scope,
                    options,
                    depth + 1,
                )?;
                return base_len.checked_mul(method_arg_const_usize(call, scope)?);
            }
            if call.method == "chain" {
                let base_len = literal_sequence_static_len_inner(
                    &call.receiver,
                    let_inits,
                    scope,
                    options,
                    depth + 1,
                )?;
                let rhs_len = literal_sequence_static_len_inner(
                    &call.args[0],
                    let_inits,
                    scope,
                    options,
                    depth + 1,
                )?;
                return base_len.checked_add(rhs_len);
            }
            let base_len = literal_sequence_static_len_inner(
                &call.receiver,
                let_inits,
                scope,
                options,
                depth + 1,
            )?;
            match call.method.to_string().as_str() {
                "skip" => {
                    let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                    Some(base_len.saturating_sub(n))
                }
                "take" => {
                    let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                    Some(base_len.min(n))
                }
                "intersperse" | "intersperse_with" => {
                    Some(base_len.checked_mul(2)?.saturating_sub(1))
                }
                "step_by" => {
                    let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                    (n > 0).then_some(stepped_len(base_len, n))
                }
                _ => None,
            }
        }
        // `vec![..]` / `Vec::from([..])` construct an array literal -- its element count.
        other => match crate::sugar::collection_literal::collection_literal_array(other) {
            Some(array) => match strip_refs_groups(&array) {
                Expr::Array(arr) => Some(arr.elems.len()),
                _ => None,
            },
            None => None,
        },
    }
}

fn literal_range_sequence_static_len_inner<'a>(
    expr: &Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
    depth: usize,
) -> Option<usize> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Range(range) => literal_range_len(range),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if let Some(current) = scope.temporal_rewrite_expr_for(&name) {
                return literal_range_sequence_static_len_inner(
                    &current,
                    let_inits,
                    scope,
                    depth + 1,
                );
            }
            let init = let_inits
                .get(&name)
                .copied()
                .or_else(|| scope.stable_let_binding_for_term(&name))?;
            literal_range_sequence_static_len_inner(init, let_inits, scope, depth + 1)
        }
        Expr::MethodCall(call) if call.args.is_empty() => match call.method.to_string().as_str() {
            "iter" | "into_iter" | "cloned" | "copied" | "fuse" | "rev" | "enumerate" => {
                literal_range_sequence_static_len_inner(&call.receiver, let_inits, scope, depth + 1)
            }
            _ => None,
        },
        Expr::MethodCall(call) if call.args.len() == 1 => {
            let base_len = literal_range_sequence_static_len_inner(
                &call.receiver,
                let_inits,
                scope,
                depth + 1,
            )?;
            let n = usize::try_from(const_int(&call.args[0])?).ok()?;
            match call.method.to_string().as_str() {
                "skip" => Some(base_len.saturating_sub(n)),
                "take" => Some(base_len.min(n)),
                "step_by" if n > 0 => Some(stepped_len(base_len, n)),
                _ => None,
            }
        }
        _ => None,
    }
}

struct StaticCollectionLenProof {
    source: Expr,
    len: usize,
    saw_length_only_adapter: bool,
}

fn literal_collection_static_len_proof_inner<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
    depth: usize,
) -> Option<StaticCollectionLenProof> {
    const MAX_DEPTH: usize = 12;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Array(array) => Some(StaticCollectionLenProof {
            source: expr.clone(),
            len: array.elems.len(),
            saw_length_only_adapter: false,
        }),
        Expr::Repeat(repeat) => Some(StaticCollectionLenProof {
            source: expr.clone(),
            len: crate::repeat_count_in_scope(&repeat.len, scope)?,
            saw_length_only_adapter: false,
        }),
        Expr::Index(_) => Some(StaticCollectionLenProof {
            source: expr.clone(),
            len: literal_slice::literal_slice_len_in_scope(expr, let_inits, scope)?,
            saw_length_only_adapter: false,
        }),
        Expr::Call(call) if literal_iter_call_len(call).is_some() => {
            Some(StaticCollectionLenProof {
                source: expr.clone(),
                len: literal_iter_call_len(call)?,
                saw_length_only_adapter: false,
            })
        }
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if let Some(current) = scope.temporal_rewrite_expr_for(&name) {
                return literal_collection_static_len_proof_inner(
                    &current,
                    let_inits,
                    scope,
                    depth + 1,
                );
            }
            let init = let_inits
                .get(&name)
                .copied()
                .or_else(|| scope.replayable_let_binding_for_source(&name))?;
            literal_collection_static_len_proof_inner(init, let_inits, scope, depth + 1)
        }
        Expr::Call(call) if into_iter_arg(call).is_some() => {
            literal_collection_static_len_proof_inner(
                into_iter_arg(call)?,
                let_inits,
                scope,
                depth + 1,
            )
        }
        Expr::MethodCall(call) if call.args.is_empty() => match call.method.to_string().as_str() {
            "iter" | "into_iter" | "cloned" | "copied" | "fuse" | "peekable" | "by_ref"
            | "clone" | "rev" | "enumerate" | "to_vec" | "as_slice" | "to_owned" | "into_vec" => {
                literal_collection_static_len_proof_inner(
                    &call.receiver,
                    let_inits,
                    scope,
                    depth + 1,
                )
            }
            "array_windows" => {
                let mut base = literal_collection_static_len_proof_inner(
                    &call.receiver,
                    let_inits,
                    scope,
                    depth + 1,
                )?;
                let n = method_const_usize(call)?;
                if n == 0 {
                    return None;
                }
                base.len = window_count(base.len, n);
                base.saw_length_only_adapter = true;
                Some(base)
            }
            "array_chunks" => {
                let mut base = literal_collection_static_len_proof_inner(
                    &call.receiver,
                    let_inits,
                    scope,
                    depth + 1,
                )?;
                let n = method_const_usize(call)?;
                if n == 0 {
                    return None;
                }
                base.len /= n;
                base.saw_length_only_adapter = true;
                Some(base)
            }
            _ => None,
        },
        Expr::MethodCall(call) if call.args.len() == 1 => {
            let mut base = literal_collection_static_len_proof_inner(
                &call.receiver,
                let_inits,
                scope,
                depth + 1,
            )?;
            match call.method.to_string().as_str() {
                "skip" => {
                    let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                    base.len = base.len.saturating_sub(n);
                    Some(base)
                }
                "take" => {
                    let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                    base.len = base.len.min(n);
                    Some(base)
                }
                "intersperse" | "intersperse_with" => {
                    base.len = base.len.checked_mul(2)?.saturating_sub(1);
                    Some(base)
                }
                "chunks" | "chunks_mut" | "rchunks" | "rchunks_mut" => {
                    let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                    if n == 0 {
                        return None;
                    }
                    base.len = ceil_div(base.len, n);
                    base.saw_length_only_adapter = true;
                    Some(base)
                }
                "chunks_exact" | "chunks_exact_mut" | "rchunks_exact" | "rchunks_exact_mut" => {
                    let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                    if n == 0 {
                        return None;
                    }
                    base.len /= n;
                    base.saw_length_only_adapter = true;
                    Some(base)
                }
                "windows" => {
                    let n = usize::try_from(const_int(&call.args[0])?).ok()?;
                    if n == 0 {
                        return None;
                    }
                    base.len = window_count(base.len, n);
                    base.saw_length_only_adapter = true;
                    Some(base)
                }
                _ => None,
            }
        }
        other => match crate::sugar::collection_literal::collection_literal_array(other) {
            Some(array) => match strip_refs_groups(&array) {
                Expr::Array(arr) => Some(StaticCollectionLenProof {
                    source: expr.clone(),
                    len: arr.elems.len(),
                    saw_length_only_adapter: false,
                }),
                _ => None,
            },
            None => None,
        },
    }
}

fn ceil_div(n: usize, d: usize) -> usize {
    if n == 0 {
        0
    } else {
        1 + ((n - 1) / d)
    }
}

fn window_count(len: usize, width: usize) -> usize {
    len.checked_sub(width).map_or(0, |rest| rest + 1)
}

fn method_const_usize(call: &syn::ExprMethodCall) -> Option<usize> {
    let args = call.turbofish.as_ref()?;
    if args.args.len() != 1 {
        return None;
    }
    let GenericArgument::Const(expr) = args.args.first()? else {
        return None;
    };
    usize::try_from(const_int(expr)?).ok()
}

fn into_iter_arg(call: &ExprCall) -> Option<&Expr> {
    if call.args.len() != 1 {
        return None;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let is_into_iter = path
        .path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == "into_iter")
        && path
            .path
            .segments
            .iter()
            .any(|seg| seg.ident == "IntoIterator");
    is_into_iter.then(|| &call.args[0])
}

fn literal_range_len(range: &ExprRange) -> Option<usize> {
    let start = match &range.start {
        Some(start) => const_range_endpoint_int(start)?,
        None => 0,
    };
    let end = match &range.end {
        Some(end) => const_range_endpoint_int(end)?,
        None => return None,
    };
    let len = match range.limits {
        syn::RangeLimits::HalfOpen(_) => {
            if end <= start {
                0
            } else {
                end.checked_sub(start)?
            }
        }
        syn::RangeLimits::Closed(_) => {
            if end < start {
                0
            } else {
                end.checked_sub(start)?.checked_add(1)?
            }
        }
    };
    usize::try_from(len).ok()
}

fn const_range_endpoint_int(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            const_range_endpoint_int(&unary.expr)?.checked_neg()
        }
        other => const_int(other),
    }
}

fn stepped_len(len: usize, step: usize) -> usize {
    if len == 0 {
        0
    } else {
        1 + (len - 1) / step
    }
}
