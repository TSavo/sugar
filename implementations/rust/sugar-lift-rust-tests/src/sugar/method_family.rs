// SPDX-License-Identifier: Apache-2.0
//
// Shared recognition gates for stdlib sequence-method Sugars.

use std::collections::BTreeMap;

use syn::{Expr, ExprCall, ExprRange, GenericArgument, UnOp};

use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::sugar::literal_slice;
use crate::{
    const_eval, const_int, literal_byte_string_value, literal_string_value, peel_fold_adaptors,
    peel_fold_adaptors_in_scope, strip_refs_groups, ConstVal, Desugared, DesugaredElem, Outcome,
    Sugar, SugarCtx, TemporalScope,
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
    crate::const_eval_finite_int_iter(expr, &BTreeMap::new(), None)?
        .into_iter()
        .map(|value| {
            let expr = value.to_expr()?;
            Some(DesugaredElem {
                expr,
                value: Some(value),
            })
        })
        .collect()
}

#[allow(dead_code)]
pub(crate) fn literal_sequence_static_len<'a>(
    expr: &Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> Option<usize> {
    literal_sequence_static_len_inner(expr, let_inits, None, 0)
}

pub(crate) fn literal_sequence_static_len_in_scope<'a>(
    expr: &Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
) -> Option<usize> {
    literal_sequence_static_len_inner(expr, let_inits, Some(scope), 0)
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
    depth: usize,
) -> Option<usize> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Array(array) => Some(array.elems.len()),
        Expr::Range(range) => literal_range_len(range),
        Expr::Index(_) => match scope {
            Some(scope) => literal_slice::literal_slice_len_in_scope(expr, let_inits, scope),
            None => literal_slice::literal_slice_len(expr, let_inits),
        },
        Expr::Call(call) => literal_iter_call_len(call),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if let Some(current) = scope.and_then(|scope| scope.temporal_rewrite_expr_for(&name)) {
                return literal_sequence_static_len_inner(&current, let_inits, scope, depth + 1);
            }
            let init = let_inits
                .get(&name)
                .copied()
                .or_else(|| scope.and_then(|scope| scope.stable_let_binding_for_term(&name)))?;
            literal_sequence_static_len_inner(init, let_inits, scope, depth + 1)
        }
        Expr::MethodCall(call) if call.args.is_empty() => match call.method.to_string().as_str() {
            // Value-identity adaptors over the element sequence: same length as the receiver.
            "iter" | "iter_mut" | "into_iter" | "cloned" | "copied" | "fuse" | "clone" | "rev"
            | "enumerate" | "to_vec" | "as_slice" | "to_owned" | "into_vec" => {
                literal_sequence_static_len_inner(&call.receiver, let_inits, scope, depth + 1)
            }
            _ => None,
        },
        Expr::MethodCall(call) if call.args.len() == 1 => {
            let base_len =
                literal_sequence_static_len_inner(&call.receiver, let_inits, scope, depth + 1)?;
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
