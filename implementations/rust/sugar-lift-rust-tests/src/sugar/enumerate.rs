// SPDX-License-Identifier: Apache-2.0
//
// `EnumerateSugar`: the `.enumerate()` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that pairs each element with its position `(i, e)`. Lifted
// verbatim from the `Adaptor::Enumerate` arm of the former `apply_one_adaptor`
// match.

use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{ConstVal, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("enumerate", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "enumerate" && call.args.is_empty() {
        return Some(Box::new(EnumerateSugar {
            inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
                &call.receiver,
                fcx,
            )?),
        }));
    }
    None
}

/// Pair each element with its position: element `e` at index `i` becomes `(i, e)`.
pub(crate) struct EnumerateSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
}

impl Sugar for EnumerateSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.inner.reduce(ctx) {
            Outcome::Complete(d) => {
                let seq = d
                    .into_seq()
                    .unwrap_or_else(|| enumerate_gap("inner reduced to non-sequence"));
                let mut out = Vec::with_capacity(seq.len());
                for (i, elem) in seq.into_iter().enumerate() {
                    // Pair value: (i, elem). The EXPR pair `(i, <expr>)` is always
                    // materializable for EUF; the pair VALUE needs the element const.
                    let e = &elem.expr;
                    let pair_expr: Expr =
                        syn::parse_str(&format!("({}, {})", i, quote::quote!(#e)))
                            .unwrap_or_else(|_| enumerate_gap("pair expression did not parse"));
                    let pair_cv = elem
                        .value
                        .map(|c| ConstVal::Tuple(vec![ConstVal::Int(i as i128), c]));
                    out.push(DesugaredElem {
                        expr: pair_expr,
                        value: pair_cv,
                    });
                }
                Outcome::Complete(Desugared::Seq(out))
            }
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

fn enumerate_gap(reason: &str) -> ! {
    panic!("enumerate did not reach a lawful floor: {reason}")
}
