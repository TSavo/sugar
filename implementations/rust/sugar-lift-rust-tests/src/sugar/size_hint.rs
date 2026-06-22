// SPDX-License-Identifier: Apache-2.0
//
// `size_hint` — a delayed tuple-valued PRODUCER for the shared `tuple_decomp` arm.
//
// The recognizer only owns the source shape: `<composite>.size_hint()`, capturing the raw
// receiver. The decomposition is delayed until `desugar`, where exact static-size adaptor
// shapes are handled first and the old composite enumeration remains the fallback. If a path
// reaches a finite sequence, std `ExactSizeIterator` semantics give `(len, Some(len))`; if it
// hits an effect/runtime boundary, that boundary propagates. Empty literal domains are inert
// and contribute length zero.

use std::collections::BTreeMap;

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::monadic;
use crate::{const_int, strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const TUPLE_PRODUCER_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::tuple_producer("size_hint_tuple_producer", recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "size_hint" || !call.args.is_empty() {
        return None;
    }
    if !has_composite(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(SizeHintTupleProducer {
        receiver: (*call.receiver).clone(),
    }))
}

struct SizeHintTupleProducer {
    receiver: Expr,
}

impl Sugar for SizeHintTupleProducer {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let let_inits = scope_let_inits(ctx);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        if let Some(len) = exact_static_size_hint_len(&self.receiver) {
            return tuple_components(len);
        }
        let receiver = build_composite(&self.receiver, &fcx);
        let seq = match receiver.desugar(ctx) {
            Outcome::Dug(desugared) => match desugared.into_seq() {
                Some(seq) => seq,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(Effect::Unsupported { reason }) if reason == EMPTY_DOMAIN_REASON => {
                Vec::new()
            }
            Outcome::Hit(effect) => return Outcome::Hit(effect),
        };
        let len = seq.len();
        debug!(
            target: "sugar_lift_rust_tests::sugar::size_hint",
            len,
            "resolved finite composite size_hint to tuple components"
        );
        tuple_components(len)
    }
}

fn tuple_components(len: usize) -> Outcome {
    Outcome::Dug(Desugared::TupleComponents(vec![
        num(len as i128),
        monadic::some_term(num(len as i128)),
    ]))
}

fn scope_let_inits<'a, 'c>(ctx: &SugarCtx<'a, 'c>) -> BTreeMap<String, &'a Expr> {
    ctx.scope
        .let_bindings_iter()
        .map(|(name, init)| (name.clone(), init))
        .collect()
}

fn exact_static_size_hint_len(expr: &Expr) -> Option<usize> {
    match strip_refs_groups(expr) {
        Expr::Range(range) => literal_range_len(range),
        Expr::MethodCall(call) if call.args.is_empty() => match call.method.to_string().as_str() {
            "iter" | "into_iter" | "cloned" | "copied" | "fuse" | "peekable" | "rev"
            | "enumerate" => exact_static_size_hint_len(&call.receiver),
            _ => None,
        },
        Expr::MethodCall(call) if call.args.len() == 1 => {
            let n = const_usize(&call.args[0])?;
            match call.method.to_string().as_str() {
                "skip" => {
                    exact_static_size_hint_len(&call.receiver).map(|len| len.saturating_sub(n))
                }
                "take" => exact_static_size_hint_len(&call.receiver)
                    .map(|len| len.min(n))
                    .or_else(|| is_open_ended_literal_range(&call.receiver).then_some(n)),
                "step_by" if n > 0 => {
                    exact_static_size_hint_len(&call.receiver).map(|len| stepped_len(len, n))
                }
                _ => None,
            }
        }
        _ => None,
    }
}

fn const_usize(expr: &Expr) -> Option<usize> {
    usize::try_from(const_int(expr).or_else(|| primitive_integer_assoc_const(expr))?).ok()
}

fn stepped_len(len: usize, step: usize) -> usize {
    if len == 0 {
        0
    } else {
        1 + (len - 1) / step
    }
}

fn literal_range_len(range: &syn::ExprRange) -> Option<usize> {
    let (Some(start), Some(end)) = (range.start.as_deref(), range.end.as_deref()) else {
        return None;
    };
    let start = literal_signed_int(start)?;
    let end = literal_signed_int(end)?;
    let len = match range.limits {
        syn::RangeLimits::HalfOpen(_) => {
            if end <= start {
                0
            } else {
                usize::try_from(end.checked_sub(start)?).ok()?
            }
        }
        syn::RangeLimits::Closed(_) => {
            if end < start {
                0
            } else {
                usize::try_from(end.checked_sub(start)?.checked_add(1)?).ok()?
            }
        }
    };
    Some(len)
}

fn is_open_ended_literal_range(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Range(range) => {
            range.start.is_some()
                && range.end.is_none()
                && matches!(range.limits, syn::RangeLimits::HalfOpen(_))
        }
        _ => false,
    }
}

fn literal_signed_int(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(i),
            ..
        }) => i.base10_parse::<i128>().ok(),
        Expr::Unary(unary) if matches!(unary.op, syn::UnOp::Neg(_)) => {
            literal_signed_int(&unary.expr).and_then(|n| n.checked_neg())
        }
        Expr::Path(_) => primitive_integer_assoc_const(expr),
        _ => None,
    }
}

fn primitive_integer_assoc_const(expr: &Expr) -> Option<i128> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    if path.qself.is_some() || path.path.leading_colon.is_some() {
        return None;
    }
    let mut segments = path.path.segments.iter();
    let ty = segments.next()?;
    let assoc = segments.next()?;
    if segments.next().is_some()
        || !matches!(ty.arguments, syn::PathArguments::None)
        || !matches!(assoc.arguments, syn::PathArguments::None)
    {
        return None;
    }
    let ty = ty.ident.to_string();
    let assoc = assoc.ident.to_string();
    match (ty.as_str(), assoc.as_str()) {
        ("isize", "MIN") => Some(isize::MIN as i128),
        ("isize", "MAX") => Some(isize::MAX as i128),
        ("usize", "MIN") => Some(usize::MIN as i128),
        ("usize", "MAX") => Some(usize::MAX as i128),
        _ => None,
    }
}
