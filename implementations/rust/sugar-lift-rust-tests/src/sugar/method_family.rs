// SPDX-License-Identifier: Apache-2.0
//
// Shared recognition gates for stdlib sequence-method Sugars.

use std::collections::BTreeMap;

use syn::{Expr, ExprRange};

use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::sugar::literal_slice;
use crate::{
    const_int, peel_fold_adaptors, peel_fold_adaptors_in_scope, strip_refs_groups, Sugar,
    TemporalScope,
};

pub(crate) fn is_literal_sequence_base(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Range(_) => true,
        // A LITERAL-count repeat `[elem; N]` is a finite literal sequence (N copies of
        // elem); the `array_repeat` composite recognizer expands it. Non-literal counts
        // (`[x; SIZE]`) are not finite-by-construction HERE (ctx-free) -- the scope-aware
        // `is_literal_sequence_base_in_scope` resolves a const-bound count.
        Expr::Repeat(repeat) => crate::repeat_count_literal(&repeat.len).is_some(),
        // Finite-collection constructors over written literals (`vec![a, b, c]`,
        // `Vec::from([a, b, c])`) construct exactly an array literal -- classified the same.
        other => crate::sugar::collection_literal::collection_literal_array(other).is_some(),
    }
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
    match strip_refs_groups(expr) {
        Expr::Array(_) | Expr::Range(_) => true,
        Expr::Repeat(repeat) => crate::repeat_count_in_scope(&repeat.len, scope).is_some(),
        // Finite-collection constructors (`vec![..]`, `Vec::from([..])`) -- same as the
        // ctx-free classifier; recognition is purely syntactic, no scope needed.
        other => crate::sugar::collection_literal::collection_literal_array(other).is_some(),
    }
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
    if !is_literal_sequence_base_in_scope(base, fcx.scope())
        && !literal_slice::is_literal_slice_base(base, fcx.let_inits())
        && !has_composite(base, fcx)
    {
        return None;
    }
    let mut node = build_composite(base, fcx);
    for wrap in adaptors {
        node = wrap(node);
    }
    Some(node)
}

#[allow(dead_code)]
pub(crate) fn literal_sequence_static_len<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
) -> Option<usize> {
    literal_sequence_static_len_inner(expr, let_inits, None, 0)
}

pub(crate) fn literal_sequence_static_len_in_scope<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    scope: &'a TemporalScope,
) -> Option<usize> {
    literal_sequence_static_len_inner(expr, let_inits, Some(scope), 0)
}

fn literal_sequence_static_len_inner<'a>(
    expr: &'a Expr,
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
        Expr::Index(_) => literal_slice::literal_slice_len(expr, let_inits),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = let_inits
                .get(&name)
                .copied()
                .or_else(|| scope.and_then(|scope| scope.stable_let_binding_for_term(&name)))?;
            literal_sequence_static_len_inner(init, let_inits, scope, depth + 1)
        }
        Expr::MethodCall(call) if call.args.is_empty() => match call.method.to_string().as_str() {
            // Value-identity adaptors over the element sequence: same length as the receiver.
            "iter" | "into_iter" | "cloned" | "copied" | "fuse" | "rev" | "enumerate"
            | "to_vec" | "as_slice" | "to_owned" | "into_vec" => {
                literal_sequence_static_len_inner(&call.receiver, let_inits, scope, depth + 1)
            }
            _ => None,
        },
        Expr::MethodCall(call) if call.args.len() == 1 => {
            let base_len =
                literal_sequence_static_len_inner(&call.receiver, let_inits, scope, depth + 1)?;
            let n = usize::try_from(const_int(&call.args[0])?).ok()?;
            match call.method.to_string().as_str() {
                "skip" => Some(base_len.saturating_sub(n)),
                "take" => Some(base_len.min(n)),
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

fn literal_range_len(range: &ExprRange) -> Option<usize> {
    let start = match &range.start {
        Some(start) => const_int(start)?,
        None => 0,
    };
    let end = match &range.end {
        Some(end) => const_int(end)?,
        None => return None,
    };
    if end < start {
        return None;
    }
    let span = end.checked_sub(start)?;
    let len = match range.limits {
        syn::RangeLimits::HalfOpen(_) => span,
        syn::RangeLimits::Closed(_) => span.checked_add(1)?,
    };
    usize::try_from(len).ok()
}
