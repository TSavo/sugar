// SPDX-License-Identifier: Apache-2.0
//
// `flatten`: the `.flatten()` adaptor over a finite literal of literal sub-sequences
// (`[[1, 2], [3, 4]].iter().flatten()`). It concatenates each element's OWN finite
// literal sequence in source order. Each completed outer element dispatches to its own
// literal floor via `SequenceElementVisitor`; this node never reconstructs nested sugar
// from raw syntax.
// This is the outermost-call
// recognizer; `peel_fold_adaptors` carries the same `FlattenSugar` when `.flatten()`
// sits inside a longer adaptor chain.

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::sequence_floor::SequenceElementVisitor;
use crate::{Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};
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
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let outer = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .unwrap_or_else(|| panic!("typed flatten receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let mut out = Vec::new();
        for elem in outer {
            let sub = match elem.accept_sequence(FlattenSubsequenceVisitor) {
                Ok(seq) => seq,
                Err(outcome) => return outcome,
            };
            let total = out
                .len()
                .checked_add(sub.len())
                .unwrap_or_else(|| panic!("flatten sequence length overflow"));
            if total > SUGAR_SEQ_CAP as usize {
                panic!("flatten sequence length {total} exceeds cap {SUGAR_SEQ_CAP}");
            }
            out.extend(sub);
        }
        Outcome::Complete(Desugared::Seq(out))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

struct FlattenSubsequenceVisitor;

impl SequenceElementVisitor for FlattenSubsequenceVisitor {
    type Output = Result<Vec<DesugaredElem>, Outcome>;

    fn visit_sequence(self, seq: Vec<DesugaredElem>) -> Self::Output {
        Ok(seq)
    }

    fn visit_runtime(self, elem: &DesugaredElem) -> Self::Output {
        let expr = &elem.expr;
        panic!(
            "flatten element did not dispatch to a nested sequence floor: {}",
            quote::quote!(#expr)
        )
    }

    fn visit_non_sequence_literal(self, _elem: &DesugaredElem) -> Self::Output {
        panic!("flatten element dispatched to a non-sequence literal floor")
    }
}
