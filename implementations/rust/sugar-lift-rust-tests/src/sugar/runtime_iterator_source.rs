// SPDX-License-Identifier: Apache-2.0
//
// Runtime iterator producers that are real Composite sources but do not own a
// finite, timeless sequence floor. Adaptors over them should delegate here and
// bubble the named temporal effect instead of manufacturing effects themselves.

use syn::{Expr, ExprCall, ExprMethodCall};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::collection_literal::collection_literal_array;
use crate::sugar::factory::{CompositeFloor, FloorRead, SugarBody, SugarBuildCtx};
use crate::{const_int, simple_path_name, token_key, Desugared, Effect, Outcome, Sugar, SugarCtx};

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
        Expr::MethodCall(call)
            if runtime_iterator_adaptor(call) && runtime_iterator_source_expr(&call.receiver) =>
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
    if !runtime_iterator_source_expr(init) {
        return None;
    }
    Some(Box::new(RuntimeIteratorBindingSugar {
        source: SugarBody::composite(init, fcx),
    }))
}

fn runtime_iterator_source_expr(expr: &Expr) -> bool {
    if collection_literal_array(expr).is_some() {
        return false;
    }
    match strip_groups(expr) {
        Expr::Call(call) => runtime_iterator_source(call),
        Expr::MethodCall(call) => {
            runtime_iterator_adaptor(call) && runtime_iterator_source_expr(&call.receiver)
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
        "iter" | "iter_mut" | "into_iter" | "cloned" | "copied" | "fuse" | "peekable" | "rev"
        | "enumerate" | "flatten" => call.args.is_empty(),
        "skip" | "take" | "step_by" => call.args.len() == 1 && const_int(&call.args[0]).is_some(),
        "map" | "filter" | "filter_map" | "skip_while" | "take_while" | "inspect" | "flat_map"
        | "scan" => call.args.len() == 1,
        _ => false,
    }
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
