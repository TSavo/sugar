// SPDX-License-Identifier: Apache-2.0
//
// `SliceIndexSugar`: term-position stdlib slice indexing over written literal
// slices. This owns the `SliceIndex` method-call surface used by coretests'
// `test_clamp!` macro:
//
//   Clamp(1..4).get(&[0, 1, 2] as &[_])
//   (1..2).index(&[0, 1] as &[_])
//
// When the slice and index are literal-backed, rustc/stdlib already determine
// the exact value. We read that axiom out loud and emit the corresponding
// literal term (`Some(elem)`, `Some(literal:Array(..))`, or the direct indexed
// value for `index`). Mutable and unchecked pointer-producing methods are not
// handled here; the existing mutable-reference/raw-pointer refusals keep those
// boundaries explicit.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, Lit, RangeLimits};

use crate::sugar::monadic;
use crate::sugar::term_leaf::{reasoned_incomplete, resolved_term};
use crate::{
    literal_aggregate_term_in_scope, parse_int_lit, strip_refs_groups, token_key,
    translate_term_in_scope, Sugar,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("slice_index", recognize);

pub(crate) fn recognize(
    expr: &Expr,
    fcx: &crate::sugar::factory::SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    match call.method.to_string().as_str() {
        "get_mut" | "index_mut" if call.args.len() == 1 => {
            return Some(reasoned_incomplete(format!(
                "unsupported term `{}`: effectful / raw-pointer / mutable-reference term (a `&mut` slice borrow) is not a constructible timeless value; refused",
                token_key(expr)
            )));
        }
        "get_unchecked_mut" if call.args.len() == 1 => {
            // `&mut T` result: a mutable-reference term, not a constructible timeless
            // value -- same boundary as `get_mut`/`index_mut`. Warranting a value
            // through a `&mut` belongs to the borrow path, not here.
            return Some(reasoned_incomplete(format!(
                "unsupported term `{}`: effectful / raw-pointer / mutable-reference term (an unchecked `&mut` slice borrow) is not a constructible timeless value; refused",
                token_key(expr)
            )));
        }
        "get_unchecked" if call.args.len() == 1 => {
            // `get_unchecked` returns `&T`/`&[T]`; on a literal-backed slice with an
            // in-domain index it is fully text-determined -- rustc/std give the exact
            // element/sub-slice. The unsafe pointer boundary is an impl detail, not an
            // unspeakable value: read the axiom out loud exactly like `index`. An index
            // OUTSIDE the literal domain is out-of-bounds UB with no determinate value
            // -> REFUSE (never fabricate). Handles both the SliceIndex-trait shape
            // (`Clamp(r).get_unchecked(&slice)`) and the inherent shape
            // (`[10, 20, 30].get_unchecked(1)`).
            return recognize_get_unchecked(call, expr, fcx);
        }
        _ => {}
    }
    let kind = match call.method.to_string().as_str() {
        "get" if call.args.len() == 1 => MethodKind::Get,
        "index" if call.args.len() == 1 => MethodKind::Index,
        _ => return None,
    };
    let (clamp, index) = receiver_index(&call.receiver)?;
    let slice = literal_slice_arg(call.args.first()?)?;
    let selection = evaluate_index(&index, slice.len(), clamp);
    let term = match (kind, selection) {
        (MethodKind::Get, None) => monadic::none_term(),
        (MethodKind::Get, Some(selection)) => {
            let inner = selection_term(selection, &slice, expr, fcx.scope()).ok()?;
            monadic::some_term(inner)
        }
        (MethodKind::Index, None) => {
            return Some(reasoned_incomplete(format!(
                "slice index `{}` is out of bounds for a literal slice; refused",
                token_key(expr)
            )));
        }
        (MethodKind::Index, Some(selection)) => {
            selection_term(selection, &slice, expr, fcx.scope()).ok()?
        }
    };
    tracing::debug!(
        target: "sugar_lift_rust_tests::slice_index",
        method = %call.method,
        clamp = clamp,
        slice_len = slice.len(),
        "grounded literal-backed SliceIndex method"
    );
    Some(resolved_term(term))
}

/// Ground `get_unchecked` over a literal-backed slice. `get_unchecked` returns
/// `&T`/`&[T]`; with an in-domain index it equals `index` (value semantics), so we
/// reuse the same `evaluate_index`/`selection_term` grounding. The only refusal is an
/// out-of-domain index -- genuine UB with no determinate value. A receiver that is
/// neither a literal slice (inherent form) nor an index spec (trait form) -- e.g. a
/// local-bound `&[_]` -- is left unresolved (honest dark), never refused: a borrow of a
/// literal local is speakable on the borrow path, not a sound stop here.
fn recognize_get_unchecked(
    call: &syn::ExprMethodCall,
    expr: &Expr,
    fcx: &crate::sugar::factory::SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    // A literal-array receiver only matches the inherent arm and an index-shaped
    // receiver only the trait arm, so the two layouts are disjoint.
    let (clamp, index, slice) = if let Some(slice) = literal_slice_arg(&call.receiver) {
        // Inherent: `<literal slice>.get_unchecked(<index>)`.
        (false, index_spec(call.args.first()?)?, slice)
    } else if let Some((clamp, index)) = receiver_index(&call.receiver) {
        // SliceIndex-trait: `<index>.get_unchecked(<literal slice>)`.
        (clamp, index, literal_slice_arg(call.args.first()?)?)
    } else {
        return None;
    };
    match evaluate_index(&index, slice.len(), clamp) {
        Some(selection) => {
            let term = selection_term(selection, &slice, expr, fcx.scope()).ok()?;
            tracing::debug!(
                target: "sugar_lift_rust_tests::slice_index",
                clamp = clamp,
                slice_len = slice.len(),
                "grounded literal-backed get_unchecked"
            );
            Some(resolved_term(term))
        }
        None => Some(reasoned_incomplete(format!(
            "out-of-bounds unchecked slice indexing `{}` is undefined behavior with no determinate value; refused",
            token_key(expr)
        ))),
    }
}

#[derive(Clone, Copy)]
enum MethodKind {
    Get,
    Index,
}

#[derive(Clone, Copy, Debug)]
enum IndexSpec {
    Single(usize),
    Range {
        start: Option<usize>,
        end: Option<usize>,
        inclusive: bool,
    },
}

#[derive(Clone, Copy)]
enum Selection {
    Elem(usize),
    Slice { start: usize, end: usize },
}

fn receiver_index(expr: &Expr) -> Option<(bool, IndexSpec)> {
    let expr = strip_clone(expr);
    if let Some(inner) = clamp_inner(expr) {
        return Some((true, index_spec(strip_clone(inner))?));
    }
    Some((false, index_spec(expr)?))
}

fn clamp_inner(expr: &Expr) -> Option<&Expr> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    path_final_ident(&call.func)
        .is_some_and(|ident| ident == "Clamp")
        .then(|| &call.args[0])
}

fn index_spec(expr: &Expr) -> Option<IndexSpec> {
    let expr = strip_clone(expr);
    if let Some(from_arg) = range_from_arg(expr) {
        return index_spec(from_arg);
    }
    match strip_refs_groups(expr) {
        Expr::Lit(syn::ExprLit {
            lit: Lit::Int(int), ..
        }) => usize::try_from(parse_int_lit(int).ok()?)
            .ok()
            .map(IndexSpec::Single),
        Expr::Range(range) => {
            let start = range.start.as_deref().and_then(int_expr);
            let end = range.end.as_deref().and_then(int_expr);
            Some(IndexSpec::Range {
                start,
                end,
                inclusive: matches!(range.limits, RangeLimits::Closed(_)),
            })
        }
        _ => None,
    }
}

fn range_from_arg(expr: &Expr) -> Option<&Expr> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    path_final_ident(&call.func)
        .is_some_and(|ident| ident == "from")
        .then(|| &call.args[0])
}

fn path_final_ident(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.segments.last().map(|seg| seg.ident.to_string())
}

fn strip_clone(expr: &Expr) -> &Expr {
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.method == "clone" && call.args.is_empty() => {
            strip_clone(&call.receiver)
        }
        other => other,
    }
}

fn int_expr(expr: &Expr) -> Option<usize> {
    let expr = strip_clone(expr);
    match strip_refs_groups(expr) {
        Expr::Lit(syn::ExprLit {
            lit: Lit::Int(int), ..
        }) => usize::try_from(parse_int_lit(int).ok()?).ok(),
        _ => None,
    }
}

fn literal_slice_arg(expr: &Expr) -> Option<Vec<Expr>> {
    let mut expr = strip_refs_groups(expr);
    if let Expr::Cast(cast) = expr {
        expr = strip_refs_groups(&cast.expr);
    }
    if let Expr::Reference(reference) = expr {
        if reference.mutability.is_some() {
            return None;
        }
        expr = strip_refs_groups(&reference.expr);
    }
    let Expr::Array(array) = expr else {
        return None;
    };
    Some(array.elems.iter().cloned().collect())
}

fn evaluate_index(index: &IndexSpec, len: usize, clamp: bool) -> Option<Selection> {
    match *index {
        IndexSpec::Single(idx) => {
            if clamp {
                (len > 0).then_some(Selection::Elem(idx.min(len - 1)))
            } else {
                (idx < len).then_some(Selection::Elem(idx))
            }
        }
        IndexSpec::Range {
            start,
            end,
            inclusive,
        } => {
            let (start, end) = if clamp {
                clamp_range(start, end, inclusive, len)?
            } else {
                normal_range(start, end, inclusive, len)?
            };
            Some(Selection::Slice { start, end })
        }
    }
}

fn normal_range(
    start: Option<usize>,
    end: Option<usize>,
    inclusive: bool,
    len: usize,
) -> Option<(usize, usize)> {
    let start = start.unwrap_or(0);
    if inclusive {
        let end = end?;
        if end >= len || start > end.saturating_add(1) {
            return None;
        }
        Some((start, end + 1))
    } else {
        let end = end.unwrap_or(len);
        (start <= end && end <= len).then_some((start, end))
    }
}

fn clamp_range(
    start: Option<usize>,
    end: Option<usize>,
    inclusive: bool,
    len: usize,
) -> Option<(usize, usize)> {
    if inclusive {
        if len == 0 {
            return None;
        }
        let max = len - 1;
        let start = start.unwrap_or(0).min(max);
        let end = end.unwrap_or(max).min(max);
        (start <= end).then_some((start, end + 1))
    } else {
        let start = start.unwrap_or(0).min(len);
        let end = end.unwrap_or(len).min(len);
        (start <= end).then_some((start, end))
    }
}

fn selection_term(
    selection: Selection,
    slice: &[Expr],
    source: &Expr,
    scope: &crate::TemporalScope,
) -> Result<Rc<Term>, String> {
    match selection {
        Selection::Elem(index) => translate_term_in_scope(&slice[index], scope),
        Selection::Slice { start, end } => {
            literal_aggregate_term_in_scope("Array", slice[start..end].iter(), source, scope)
        }
    }
}
