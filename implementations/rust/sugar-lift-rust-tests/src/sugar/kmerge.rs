// SPDX-License-Identifier: Apache-2.0
//
// `KMergeSugar`: itertools `.kmerge()` over a finite literal-derived sequence of
// finite literal-derived sub-sequences. Empty sub-sequences contribute no elements.
// Non-empty sub-sequences must expose exact integer values so the merged ordering is
// determined; otherwise the sugar declines rather than fabricating an order.

use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{
    compat_reduction, has_composite, CompositeFloor, FactoryGap, FactoryReduction, SugarBody,
    SugarBuildCtx,
};
use crate::sugar::literal::{LiteralSugar, EMPTY_DOMAIN_REASON};
use crate::{ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("kmerge", SugarRole::Composite, recognize_composite);

fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "kmerge" || !call.args.is_empty() {
        return None;
    }
    if !has_composite(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(KMergeSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
    }))
}

struct KMergeSugar {
    inner: SugarBody<CompositeFloor>,
}

impl Sugar for KMergeSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let outer = match self.inner.reduce(ctx)? {
            Outcome::Complete(d) => d
                .into_seq()
                .ok_or_else(|| FactoryGap::new("kmerge receiver reduced to non-sequence"))?,
            Outcome::Incomplete(effect) => return Ok(Outcome::Incomplete(effect)),
        };
        let mut out = Vec::new();
        for elem in outer {
            let sub = literal_subsequence_from_expr(&elem.expr, ctx)?;
            let total = out
                .len()
                .checked_add(sub.len())
                .ok_or_else(|| FactoryGap::new("kmerge sequence length overflow"))?;
            if total > SUGAR_SEQ_CAP as usize {
                return Err(FactoryGap::new(format!(
                    "kmerge sequence length {total} exceeds cap {SUGAR_SEQ_CAP}"
                )));
            }
            out.extend(sub);
        }
        if !out.is_empty() {
            let mut sortable = Vec::with_capacity(out.len());
            for elem in out {
                let key = elem
                    .value
                    .as_ref()
                    .and_then(ConstVal::as_int)
                    .ok_or_else(|| {
                        FactoryGap::new("kmerge element is not literal integer-valued")
                    })?;
                sortable.push((key, elem));
            }
            sortable.sort_by_key(|(key, _)| *key);
            out = sortable
                .into_iter()
                .map(|(_, elem): (i128, DesugaredElem)| elem)
                .collect();
        }
        debug!(
            target: "sugar_lift_rust_tests::sugar::kmerge",
            len = out.len(),
            "merged finite literal-derived iterator family"
        );
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
            .ok_or_else(|| FactoryGap::new("kmerge element reduced to non-sequence")),
        Outcome::Incomplete(Effect::Unsupported { reason }) if reason == EMPTY_DOMAIN_REASON => {
            Ok(Vec::new())
        }
        Outcome::Incomplete(_) => Err(FactoryGap::new(
            "kmerge element is not a literal-determined sub-sequence",
        )),
    }
}
