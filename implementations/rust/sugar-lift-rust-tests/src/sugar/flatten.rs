// SPDX-License-Identifier: Apache-2.0
//
// `flatten`: the `.flatten()` adaptor over a finite literal of literal sub-sequences
// (`[[1, 2], [3, 4]].iter().flatten()`). It concatenates each element's OWN finite
// literal sequence in source order. Each outer element must itself be a clean finite
// literal sub-sequence; if not, the node gaps rather than rebuilding through the factory.
// This is the outermost-call
// recognizer; `peel_fold_adaptors` carries the same `FlattenSugar` when `.flatten()`
// sits inside a longer adaptor chain.

use crate::sugar::factory::{
    compat_reduction, CompositeFloor, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx,
};
use crate::sugar::literal::{LiteralSugar, EMPTY_DOMAIN_REASON};
use crate::sugar::method_family;
use crate::{Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("flatten", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    // The receiver must resolve to a finite literal sequence (whose ELEMENTS are
    // checked to be sub-sequences at desugar time, bailing if not).
    if call.method == "flatten" && call.args.is_empty() {
        return Some(Box::new(FlattenSugar {
            inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
                &call.receiver,
                fcx,
            )?),
        }));
    }
    None
}

/// Concatenate each element's own finite literal sub-sequence in source order.
pub(crate) struct FlattenSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
}

impl Sugar for FlattenSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let outer = match self.inner.reduce(ctx)? {
            Outcome::Complete(d) => d
                .into_seq()
                .ok_or_else(|| FactoryGap::new("flatten receiver reduced to non-sequence"))?,
            Outcome::Incomplete(effect) => return Ok(Outcome::Incomplete(effect)),
        };
        let mut out = Vec::new();
        for elem in outer {
            let sub = literal_subsequence_from_expr(&elem.expr, ctx)?;
            let total = out
                .len()
                .checked_add(sub.len())
                .ok_or_else(|| FactoryGap::new("flatten sequence length overflow"))?;
            if total > SUGAR_SEQ_CAP as usize {
                return Err(FactoryGap::new(format!(
                    "flatten sequence length {total} exceeds cap {SUGAR_SEQ_CAP}"
                )));
            }
            out.extend(sub);
        }
        Ok(Outcome::Complete(Desugared::Seq(out)))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

fn literal_subsequence_from_expr(
    expr: &Expr,
    ctx: &SugarCtx,
) -> Result<Vec<DesugaredElem>, FactoryGap> {
    match (LiteralSugar { base: expr.clone() }).desugar(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .ok_or_else(|| FactoryGap::new("flatten element reduced to non-sequence")),
        Outcome::Incomplete(Effect::Unsupported { reason }) if reason == EMPTY_DOMAIN_REASON => {
            Ok(Vec::new())
        }
        Outcome::Incomplete(_) => Err(FactoryGap::new(
            "flatten element is not a literal-determined sub-sequence",
        )),
    }
}
