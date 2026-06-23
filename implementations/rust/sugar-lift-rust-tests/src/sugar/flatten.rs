// SPDX-License-Identifier: Apache-2.0
//
// `flatten`: the `.flatten()` adaptor over a finite literal of literal sub-sequences
// (`[[1, 2], [3, 4]].iter().flatten()`). It concatenates each element's OWN finite
// literal sequence in source order. Each outer element is re-built as a composite
// from its `expr` and desugared to a sub-`Seq`; if ANY element is not itself a clean
// finite literal sub-sequence, the whole node bails (`None` -> refuse, never guess) --
// the same exact-or-refuse discipline as `chain`/`map`. This is the outermost-call
// recognizer; `peel_fold_adaptors` carries the same `FlattenSugar` when `.flatten()`
// sits inside a longer adaptor chain.

use std::collections::BTreeMap;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{Desugared, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};
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
            inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        }));
    }
    None
}

/// Concatenate each element's own finite literal sub-sequence in source order.
pub(crate) struct FlattenSugar {
    pub(crate) inner: Box<dyn Sugar>,
}

impl Sugar for FlattenSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let outer = self.inner.desugar(ctx).complete()?.into_seq()?;
            let let_inits = BTreeMap::new();
            let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
            let mut out = Vec::new();
            for elem in outer {
                // Each outer element must itself complete to a finite literal sub-sequence.
                let sub = build_composite(&elem.expr, &fcx)
                    .desugar(ctx)
                    .complete()?
                    .into_seq()?;
                let total = out.len().checked_add(sub.len())?;
                if total > SUGAR_SEQ_CAP as usize {
                    return None;
                }
                out.extend(sub);
            }
            Some(Desugared::Seq(out))
        })())
    }
}
