// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `KMergeSugar`: itertools `.kmerge()` over a finite literal-derived sequence of
// finite literal-derived sub-sequences. Empty sub-sequences contribute no elements.
// Non-empty sub-sequences must expose exact integer values so the merged ordering is
// determined; otherwise the sugar declines rather than fabricating an order.

use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::sequence_floor::SequenceElementVisitor;
use crate::sugar::source_fragment::SourceFragment;
use crate::{ConstVal, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "kmerge",
    SugarRole::Composite,
    crate::sugar::claim::SugarWitnesses::temporal_campaign(
        "S5 adapter family: k-way merge standing",
    ),
    recognize_composite,
);

fn recognize_composite(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
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
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let outer = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .unwrap_or_else(|| panic!("typed kmerge receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let mut out = Vec::new();
        for elem in outer {
            let sub = match elem.accept_sequence(KMergeSubsequenceVisitor) {
                Ok(seq) => seq,
                Err(outcome) => return outcome,
            };
            let total = out
                .len()
                .checked_add(sub.len())
                .unwrap_or_else(|| panic!("kmerge sequence length overflow"));
            if total > SUGAR_SEQ_CAP as usize {
                panic!("kmerge sequence length {total} exceeds cap {SUGAR_SEQ_CAP}");
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
                    .unwrap_or_else(|| panic!("kmerge element is not literal integer-valued"));
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
        Outcome::Complete(Desugared::Seq(out))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

struct KMergeSubsequenceVisitor;

impl SequenceElementVisitor for KMergeSubsequenceVisitor {
    type Output = Result<Vec<DesugaredElem>, Outcome>;

    fn visit_sequence(self, seq: Vec<DesugaredElem>) -> Self::Output {
        Ok(seq)
    }

    fn visit_runtime(self, elem: &DesugaredElem) -> Self::Output {
        let expr = &elem.expr;
        panic!(
            "kmerge element did not dispatch to a nested sequence floor: {}",
            quote::quote!(#expr)
        )
    }

    fn visit_non_sequence_literal(self, _elem: &DesugaredElem) -> Self::Output {
        panic!("kmerge element dispatched to a non-sequence literal floor")
    }
}
