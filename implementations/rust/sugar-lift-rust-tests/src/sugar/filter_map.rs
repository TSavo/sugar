// SPDX-License-Identifier: Apache-2.0
//
// `FilterMapSugar`: the `.filter_map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that const-evaluates the `Option`-returning closure over each
// element and keeps the `Some(v)` values (dropping the `None`s). The composable
// `filter_map` arm uses the same `const_eval` floor and `Some`/`None` Option-shape as
// the other iterator sugars, wired as a decorator so a `filter_map` feeding a
// `fold`/`rfold`/`for_each`/for-loop terminal completes through the ordinary `Sugar` tree.
// Bails (None) on an opaque element (no const value), a non-`Option` / runtime closure
// result, or a kept value it cannot materialize back to an `Expr` -- exact-or-bail,
// same as `MapSugar` / `FilterSugar`.

use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{
    AdapterFloorOutput, AdapterOutputIterMember, CountedAdapterFloor, IterStanding,
    TemporalFloorRefusal,
};
use crate::{
    const_eval_option_closure, ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "filter_map",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_filter_map_good() {
                    let got = [0i32, 1, 2].iter()
                        .filter_map(|&x| if x % 2 == 0 { Some(x * 2) } else { None })
                        .count();
                    assert_eq!(got, 2);
                }
            "#,
            r#"
                #[test]
                fn t_filter_map_bad() {
                    let got = [0i32, 1, 2].iter()
                        .filter_map(|&x| if x % 2 == 0 { Some(x * 2) } else { None })
                        .count();
                    assert_eq!(got, 3);
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
    if call.method != "filter_map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    Some(Box::new(FilterMapSugar {
        inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &call.receiver,
            fcx,
        )?),
        mapper: FilterMapClosure::new(f.clone()),
    }))
}

pub(crate) struct FilterMapClosure {
    expr: syn::ExprClosure,
}

impl FilterMapClosure {
    pub(crate) fn new(expr: syn::ExprClosure) -> Self {
        Self { expr }
    }

    fn eval(&self, value: &ConstVal) -> Option<Option<ConstVal>> {
        const_eval_option_closure(&self.expr, value)
    }
}

/// Const-evaluate `f` (returning `Option`) over each element and keep the `Some` values.
pub(crate) struct FilterMapSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) mapper: FilterMapClosure,
}

impl Sugar for FilterMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .unwrap_or_else(|| filter_map_gap("filter_map receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let floor = FilterMapFloor::default();
        let operand = match floor.derived_operand(seq.len()) {
            Ok(operand) => operand,
            Err(outcome) => return outcome,
        };
        let output = match floor.desugar(operand, seq, |elem| {
            let v = elem
                .value
                .as_ref()
                .unwrap_or_else(|| filter_map_gap("filter_map element was not literal"));
            let mapped = self
                .mapper
                .eval(v)
                .unwrap_or_else(|| filter_map_gap("filter_map closure did not reduce to Option"));
            mapped.map(|mapped| {
                let mexpr = mapped
                    .to_expr()
                    .unwrap_or_else(|| filter_map_gap("filter_map result could not materialize"));
                DesugaredElem {
                    expr: mexpr,
                    value: Some(mapped),
                }
            })
        }) {
            Ok(output) => output,
            Err(outcome) => return outcome,
        };
        ctx.record_adapter_floor_audit("filter_map", output.standing().count());
        Outcome::Complete(Desugared::Seq(output.into_items()))
    }
}

fn filter_map_gap(reason: &str) -> ! {
    panic!("filter_map did not reach a lawful floor: {reason}")
}

#[derive(Clone, Copy)]
struct FilterMapFloor {
    counted: CountedAdapterFloor,
}

impl Default for FilterMapFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("filter_map", AdapterOutputIterMember::filter_map),
        }
    }
}

impl FilterMapFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(filter_map_floor_refusal)
    }

    fn desugar<F>(
        &self,
        operand: IterStanding,
        seq: Vec<DesugaredElem>,
        mapper: F,
    ) -> Result<AdapterFloorOutput<DesugaredElem>, Outcome>
    where
        F: FnMut(DesugaredElem) -> Option<DesugaredElem>,
    {
        let visited = seq.len();
        let out = seq.into_iter().filter_map(mapper).collect();
        self.counted
            .assert_input_count(&operand, visited)
            .map_err(filter_map_floor_refusal)?;
        self.counted.output(out).map_err(filter_map_floor_refusal)
    }
}

fn filter_map_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        boundary: "Iterator::filter_map".to_string(),
        reason: err.to_string(),
    })
}
