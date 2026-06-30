// SPDX-License-Identifier: Apache-2.0
//
// `TakeWhileSugar`: the `.take_while(pred)` adaptor. A decorator `Sugar` over an
// inner sequence-`Sugar` that keeps the leading run of elements where the closure
// const-evaluates true. Bails (None) on an opaque element in the kept prefix or a
// non-bool / runtime closure result. Lifted verbatim from the
// `Adaptor::TakeWhile(closure)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::bool_predicate::BoolPredicateClosure;
use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("take_while", recognize_composite);

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "take_while" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(pred) = &call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(TakeWhileRecognizedSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        pred: BoolPredicateClosure::build(pred.clone(), fcx)?,
    }))
}

struct TakeWhileRecognizedSugar {
    inner: SugarBody<CompositeFloor>,
    pred: BoolPredicateClosure,
}

impl Sugar for TakeWhileRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_take_while(&self.inner, &self.pred, ctx)
    }
}

/// Keep the leading run of elements where `pred` const-evaluates true.
pub(crate) struct TakeWhileSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) pred: BoolPredicateClosure,
}

impl Sugar for TakeWhileSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_take_while(&self.inner, &self.pred, ctx)
    }
}

fn reduce_take_while(
    inner: &SugarBody<CompositeFloor>,
    pred: &BoolPredicateClosure,
    ctx: &SugarCtx,
) -> Outcome {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .unwrap_or_else(|| take_while_gap("take_while receiver reduced to non-sequence")),
        Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
    };
    let mut out = Vec::new();
    for (idx, elem) in seq.into_iter().enumerate() {
        let keep = match pred.eval_for_elem(&elem, idx, "take_while", ctx) {
            Ok(keep) => keep,
            Err(outcome) => return outcome,
        };
        if keep {
            out.push(elem);
        } else {
            break;
        }
    }
    Outcome::Complete(Desugared::Seq(out))
}

fn take_while_gap(reason: &str) -> ! {
    panic!("take_while did not reach a lawful floor: {reason}")
}
