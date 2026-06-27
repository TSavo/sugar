// SPDX-License-Identifier: Apache-2.0
//
// `CycleTakeSugar`: `.cycle().take(n)` over a finite receiver. Bare `cycle()` is not
// a finite composite floor; it becomes constructible only when a downstream `take`
// supplies the bound.

use syn::{Expr, ExprMethodCall};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{CompositeFloor, FloorRead, SugarBody, SugarBuildCtx};
use crate::sugar::literal::OVERSIZE_DOMAIN_REASON;
use crate::sugar::method_family;
use crate::{token_key, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::composite_before("cycle_take", &["take"], recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    recognize_cycle_take_composite(expr, fcx)
}

pub(crate) fn recognize_cycle_take_composite(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(take) = crate::strip_refs_groups(expr) else {
        return None;
    };
    if take.method != "take" || take.args.len() != 1 {
        return None;
    }
    let count = method_family::const_usize_in_build_ctx(&take.args[0], fcx)?;
    let cycle = resolve_cycle_call(&take.receiver, fcx, 0)?;
    Some(Box::new(CycleTakeSugar {
        receiver: SugarBody::composite(&cycle.receiver, fcx),
        count,
        boundary: token_key(expr),
    }))
}

struct CycleTakeSugar {
    receiver: SugarBody<CompositeFloor>,
    count: usize,
    boundary: String,
}

impl Sugar for CycleTakeSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.receiver.reduce_sequence(ctx, "cycle receiver") {
            FloorRead::Complete(seq) => seq,
            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        match cycle_prefix(seq, self.count, &self.boundary) {
            Ok(seq) => Outcome::Complete(Desugared::Seq(seq)),
            Err(outcome) => outcome,
        }
    }
}

fn cycle_prefix(
    seq: Vec<DesugaredElem>,
    count: usize,
    boundary: &str,
) -> Result<Vec<DesugaredElem>, Outcome> {
    if count == 0 || seq.is_empty() {
        return Ok(Vec::new());
    }
    if count > SUGAR_SEQ_CAP as usize {
        return Err(Outcome::Incomplete(Effect::LiteralDomain {
            boundary: boundary.to_string(),
            reason: OVERSIZE_DOMAIN_REASON.to_string(),
        }));
    }
    let mut out = Vec::with_capacity(count);
    for idx in 0..count {
        out.push(seq[idx % seq.len()].clone());
    }
    Ok(out)
}

fn resolve_cycle_call(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> Option<ExprMethodCall> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match crate::strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.method == "cycle" && call.args.is_empty() => {
            Some(call.clone())
        }
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
                return resolve_cycle_call(&current, fcx, depth + 1);
            }
            if let Some(init) = fcx
                .scope()
                .replayable_let_binding_for_source(&name)
                .or_else(|| fcx.let_inits().get(&name).copied())
            {
                return resolve_cycle_call(init, fcx, depth + 1);
            }
            None
        }
        Expr::Paren(paren) => resolve_cycle_call(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => resolve_cycle_call(&group.expr, fcx, depth + 1),
        Expr::Reference(reference) => resolve_cycle_call(&reference.expr, fcx, depth + 1),
        _ => None,
    }
}
