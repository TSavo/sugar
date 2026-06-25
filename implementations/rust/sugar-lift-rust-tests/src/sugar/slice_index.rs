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
// value for `index`). The mutable variants use the same value semantics only
// when their slice source is a written literal; runtime mutable slices remain a
// real representation boundary.

use syn::{Expr, Lit, RangeLimits};

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::monadic;
use crate::sugar::sequence_floor::{SequenceSelection, SequenceSelectionVisitor};
use crate::{
    parse_int_lit, strip_refs_groups, token_key, Desugared, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("slice_index", recognize);

struct SliceIndexRepresentationSugar {
    boundary: String,
    kind: String,
}

impl Sugar for SliceIndexRepresentationSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::RepresentationCast {
            boundary: self.boundary.clone(),
            kind: self.kind.clone(),
        })
    }
}

fn representation_boundary(expr: &Expr, kind: &'static str) -> Box<dyn Sugar> {
    Box::new(SliceIndexRepresentationSugar {
        boundary: token_key(expr),
        kind: kind.to_string(),
    })
}

struct SliceIndexSugar {
    kind: MethodKind,
    boundary: String,
    clamp: bool,
    index: IndexSpec,
    slice: SugarBody<CompositeFloor>,
}

impl Sugar for SliceIndexSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.slice.reduce(ctx) {
            Outcome::Complete(Desugared::Seq(seq)) => seq,
            Outcome::Complete(_) => {
                panic!("slice_index slice body completed as a non-sequence floor")
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let selection = evaluate_index(&self.index, seq.len(), self.clamp);
        let term = match (self.kind, selection) {
            (MethodKind::Get, None) => monadic::none_term(),
            (MethodKind::Get, Some(selection)) => monadic::some_term(select_term(&seq, selection)),
            (MethodKind::Index, None) => {
                return Outcome::Incomplete(Effect::LiteralPanic {
                    boundary: self.boundary.clone(),
                    reason: format!(
                        "slice index `{}` is out of bounds for a literal slice; refused",
                        self.boundary
                    ),
                });
            }
            (MethodKind::Index, Some(selection)) => select_term(&seq, selection),
            (MethodKind::Unchecked, None) => {
                return Outcome::Incomplete(Effect::UndefinedBehavior {
                    boundary: self.boundary.clone(),
                    reason: format!(
                        "out-of-bounds unchecked slice indexing `{}` is undefined behavior with no determinate value; refused",
                        self.boundary
                    ),
                });
            }
            (MethodKind::Unchecked, Some(selection)) => select_term(&seq, selection),
        };
        Outcome::Complete(Desugared::Term(term))
    }
}

pub(crate) fn recognize(
    expr: &Expr,
    fcx: &crate::sugar::factory::SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    let kind = match method.as_str() {
        "get" if call.args.len() == 1 => MethodKind::Get,
        "get_mut" if call.args.len() == 1 => MethodKind::Get,
        "index" if call.args.len() == 1 => MethodKind::Index,
        "index_mut" if call.args.len() == 1 => MethodKind::Index,
        "get_unchecked" | "get_unchecked_mut" if call.args.len() == 1 => MethodKind::Unchecked,
        _ => return None,
    };
    let mutable_result = matches!(
        method.as_str(),
        "get_mut" | "index_mut" | "get_unchecked_mut"
    );
    let boundary = token_key(expr);
    let (clamp, index, slice) =
        if matches!(kind, MethodKind::Unchecked) && has_composite(&call.receiver, fcx) {
            (false, index_spec(call.args.first()?)?, &*call.receiver)
        } else {
            let (clamp, index) = receiver_index(&call.receiver)?;
            (clamp, index, call.args.first()?)
        };
    let Some(slice) = slice_body_or_boundary(slice, expr, fcx, mutable_result) else {
        return None;
    };
    tracing::debug!(
        target: "sugar_lift_rust_tests::slice_index",
        method = %call.method,
        clamp = clamp,
        "recognized literal-backed SliceIndex method"
    );
    Some(Box::new(SliceIndexSugar {
        kind,
        boundary,
        clamp,
        index,
        slice,
    }))
}

#[derive(Clone, Copy)]
enum MethodKind {
    Get,
    Index,
    Unchecked,
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

fn slice_body_or_boundary(
    slice: &Expr,
    expr: &Expr,
    fcx: &SugarBuildCtx,
    mutable_result: bool,
) -> Option<SugarBody<CompositeFloor>> {
    if has_composite(slice, fcx) {
        return Some(SugarBody::composite(slice, fcx));
    }
    if mutable_result {
        return Some(SugarBody::from_node(representation_boundary(
            expr,
            "a `&mut` slice borrow",
        )));
    }
    None
}

fn evaluate_index(index: &IndexSpec, len: usize, clamp: bool) -> Option<SequenceSelection> {
    match *index {
        IndexSpec::Single(idx) => {
            if clamp {
                (len > 0).then_some(SequenceSelection::Elem(idx.min(len - 1)))
            } else {
                (idx < len).then_some(SequenceSelection::Elem(idx))
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
            Some(SequenceSelection::Slice { start, end })
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

fn select_term(
    seq: &[crate::DesugaredElem],
    selection: SequenceSelection,
) -> std::rc::Rc<sugar_ir_symbolic::Term> {
    Desugared::Seq(seq.to_vec()).accept_sequence_floor(SequenceSelectionVisitor {
        owner: "slice_index",
        selection,
    })
}
