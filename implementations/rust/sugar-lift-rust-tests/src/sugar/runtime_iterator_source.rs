// SPDX-License-Identifier: Apache-2.0
//
// Runtime iterator producers that are real Composite sources but do not own a
// finite, timeless sequence floor. Adaptors over them should delegate here and
// bubble the named temporal effect instead of manufacturing effects themselves.

use std::collections::BTreeSet;

use syn::{Expr, ExprCall, ExprMethodCall};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::collection_literal::collection_literal_array;
use crate::sugar::factory::{CompositeFloor, FloorRead, SugarBody, SugarBuildCtx};
use crate::{
    closure_body_is_side_effecting, closure_constructs_drop_side_effect_value, const_int,
    simple_path_name, token_key, Desugared, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::fallback_with_ordering(
    "runtime_iterator_source",
    SugarRole::Composite,
    &[],
    recognize_composite,
);

fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(binding) = recognize_mutable_source_binding(expr, fcx) {
        return Some(binding);
    }
    if collection_literal_array(expr).is_some() {
        return None;
    }
    match strip_groups(expr) {
        Expr::Call(call) => runtime_iterator_source(call).then(|| {
            Box::new(RuntimeIteratorSourceSugar {
                boundary: token_key(expr),
                producer: producer_name(call).unwrap_or_else(|| "iterator source".to_string()),
            }) as Box<dyn Sugar>
        }),
        Expr::MethodCall(call) if runtime_iterator_effectful_adaptor(call) => {
            Some(Box::new(RuntimeIteratorSourceSugar {
                boundary: token_key(expr),
                producer: call.method.to_string(),
            }))
        }
        Expr::MethodCall(call)
            if runtime_iterator_adaptor(call)
                && runtime_iterator_source_expr(&call.receiver, fcx) =>
        {
            Some(Box::new(RuntimeIteratorBindingSugar {
                source: SugarBody::composite(&call.receiver, fcx),
            }))
        }
        _ => None,
    }
}

struct RuntimeIteratorBindingSugar {
    source: SugarBody<CompositeFloor>,
}

struct RuntimeIteratorSourceSugar {
    boundary: String,
    producer: String,
}

impl Sugar for RuntimeIteratorBindingSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self
            .source
            .reduce_sequence(ctx, "runtime iterator binding source")
        {
            FloorRead::Complete(seq) => Outcome::Complete(Desugared::Seq(seq)),
            FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

impl Sugar for RuntimeIteratorSourceSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
            boundary: self.boundary.clone(),
            reason: format!(
                "unknown iterator consumption for `{}` via `{}`: OPAQUE runtime iterator source \
                 state is produced by a generator/closure/call, so there is no single timeless \
                 source sequence to read at the assertion; refused",
                self.boundary, self.producer
            ),
        })
    }
}

fn recognize_mutable_source_binding(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let name = simple_path_name(expr)?;
    if !fcx.scope().is_mut_local(&name) {
        return None;
    }
    let init = fcx.scope().let_binding_for_audit(&name)?;
    if !runtime_iterator_source_expr(init, fcx) {
        return None;
    }
    Some(Box::new(RuntimeIteratorBindingSugar {
        source: SugarBody::composite(init, fcx),
    }))
}

fn runtime_iterator_source_expr(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let mut seen = BTreeSet::new();
    runtime_iterator_source_expr_inner(expr, fcx, &mut seen)
}

fn runtime_iterator_source_expr_inner(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    seen: &mut BTreeSet<String>,
) -> bool {
    if collection_literal_array(expr).is_some() {
        return false;
    }
    match strip_groups(expr) {
        Expr::Call(call) => runtime_iterator_source(call),
        Expr::MethodCall(call) => {
            runtime_iterator_effectful_adaptor(call)
                || runtime_iterator_adaptor(call)
                    && runtime_iterator_source_expr_inner(&call.receiver, fcx, seen)
        }
        Expr::Path(_) => simple_path_name(expr).is_some_and(|name| {
            if !seen.insert(name.clone()) {
                return false;
            }
            fcx.scope()
                .unknown_iterator_consumption_reason(&name)
                .is_some()
                || fcx
                    .scope()
                    .let_binding_for_audit(&name)
                    .is_some_and(|init| runtime_iterator_source_expr_inner(init, fcx, seen))
        }),
        Expr::Paren(paren) => runtime_iterator_source_expr_inner(&paren.expr, fcx, seen),
        Expr::Group(group) => runtime_iterator_source_expr_inner(&group.expr, fcx, seen),
        Expr::Reference(reference) => {
            runtime_iterator_source_expr_inner(&reference.expr, fcx, seen)
        }
        _ => false,
    }
}

fn strip_groups(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_groups(&paren.expr),
        Expr::Group(group) => strip_groups(&group.expr),
        _ => expr,
    }
}

fn runtime_iterator_source(call: &ExprCall) -> bool {
    producer_name(call).is_some()
}

fn runtime_iterator_adaptor(call: &ExprMethodCall) -> bool {
    match call.method.to_string().as_str() {
        "iter" | "iter_mut" | "into_iter" | "cloned" | "copied" | "fuse" | "peekable" | "clone"
        | "rev" | "enumerate" | "flatten" | "array_chunks" => call.args.is_empty(),
        "skip" | "take" | "step_by" => call.args.len() == 1 && const_int(&call.args[0]).is_some(),
        "map" | "filter" | "filter_map" | "skip_while" | "take_while" | "inspect" | "flat_map"
        | "scan" => call.args.len() == 1,
        _ => false,
    }
}

fn runtime_iterator_effectful_adaptor(call: &ExprMethodCall) -> bool {
    matches!(
        call.method.to_string().as_str(),
        "map"
            | "filter"
            | "filter_map"
            | "skip_while"
            | "take_while"
            | "inspect"
            | "flat_map"
            | "scan"
    ) && call.args.iter().any(|arg| {
        let Expr::Closure(closure) = arg else {
            return false;
        };
        closure_body_is_side_effecting(&closure.body)
            || closure_constructs_drop_side_effect_value(closure)
    })
}

fn producer_name(call: &ExprCall) -> Option<String> {
    let Expr::Path(path) = call.func.as_ref() else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    let mut segments = path.path.segments.iter().rev();
    let last = segments.next()?;
    if last.ident == "successors"
        && call.args.len() == 2
        && segments.next().is_some_and(|parent| parent.ident == "iter")
    {
        return Some("successors".to_string());
    }
    Some(last.ident.to_string())
}
