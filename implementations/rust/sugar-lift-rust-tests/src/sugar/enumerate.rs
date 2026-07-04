// SPDX-License-Identifier: Apache-2.0
//
// `EnumerateSugar`: the `.enumerate()` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that pairs each element with its position `(i, e)`. Lifted
// verbatim from the `Adaptor::Enumerate` arm of the former `apply_one_adaptor`
// match.

use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{
    AdapterFloorOutput, AdapterOutputIterMember, CountedAdapterFloor, IterStanding,
    TemporalFloorRefusal,
};
use crate::{ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "enumerate",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_enumerate_good() {
                    let got = [10i32, 20, 30].into_iter().enumerate().count();
                    assert_eq!(got, 3);
                }
            "#,
            r#"
                #[test]
                fn t_enumerate_bad() {
                    let got = [10i32, 20, 30].into_iter().enumerate().count();
                    assert_eq!(got, 4);
                }
            "#,
        ),
        recognize_composite,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
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
                let floor = EnumerateFloor::default();
                let operand = match floor.derived_operand(seq.len()) {
                    Ok(operand) => operand,
                    Err(outcome) => return outcome,
                };
                let output = match floor.desugar(operand, seq, enumerate_pair) {
                    Ok(output) => output,
                    Err(outcome) => return outcome,
                };
                ctx.record_adapter_floor_audit("enumerate", output.standing().count());
                Outcome::Complete(Desugared::Seq(output.into_items()))
            }
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

fn enumerate_pair(i: usize, elem: DesugaredElem) -> DesugaredElem {
    // Pair value: (i, elem). The EXPR pair `(i, <expr>)` is always
    // materializable for EUF; the pair VALUE needs the element const.
    let e = &elem.expr;
    let pair_expr: Expr = syn::parse_str(&format!("({}, {})", i, quote::quote!(#e)))
        .unwrap_or_else(|_| enumerate_gap("pair expression did not parse"));
    let pair_cv = elem
        .value
        .map(|c| ConstVal::Tuple(vec![ConstVal::Int(i as i128), c]));
    DesugaredElem {
        expr: pair_expr,
        value: pair_cv,
    }
}

#[derive(Clone, Copy)]
struct EnumerateFloor {
    counted: CountedAdapterFloor,
}

impl Default for EnumerateFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("enumerate", AdapterOutputIterMember::enumerate),
        }
    }
}

impl EnumerateFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(enumerate_floor_refusal)
    }

    fn desugar<T, U, F>(
        &self,
        operand: IterStanding,
        seq: Vec<T>,
        mut pair: F,
    ) -> Result<AdapterFloorOutput<U>, Outcome>
    where
        F: FnMut(usize, T) -> U,
    {
        let expected = operand.count();
        let out = seq
            .into_iter()
            .enumerate()
            .map(|(idx, item)| pair(idx, item))
            .collect::<Vec<_>>();
        self.counted
            .assert_output_count(&operand, expected, out.len())
            .map_err(enumerate_floor_refusal)?;
        self.counted.output(out).map_err(enumerate_floor_refusal)
    }
}

fn enumerate_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
}

fn enumerate_gap(reason: &str) -> ! {
    panic!("enumerate did not reach a lawful floor: {reason}")
}
