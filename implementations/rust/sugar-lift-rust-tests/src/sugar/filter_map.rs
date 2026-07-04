// SPDX-License-Identifier: MIT OR Apache-2.0
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
    const_eval_option_closure, token_key, ConstVal, Desugared, DesugaredElem, Effect, Outcome,
    Sugar, SugarCtx,
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
            let Some(v) = elem.value.as_ref() else {
                return Err(filter_map_effect(
                    "filter_map element was not literal",
                    &elem.expr,
                ));
            };
            let Some(mapped) = self.mapper.eval(v) else {
                return Err(filter_map_effect(
                    "filter_map closure did not reduce to Option",
                    &elem.expr,
                ));
            };
            mapped
                .map(|mapped| {
                    let Some(mexpr) = mapped.to_expr() else {
                        return Err(filter_map_effect(
                            "filter_map result could not materialize",
                            &elem.expr,
                        ));
                    };
                    Ok(DesugaredElem {
                        expr: mexpr,
                        value: Some(mapped),
                    })
                })
                .transpose()
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

fn filter_map_effect(reason: &str, boundary: &Expr) -> Outcome {
    Outcome::Incomplete(Effect::RuntimeFilterMap {
        reason: reason.to_string(),
        boundary: token_key(boundary),
    })
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
        F: FnMut(DesugaredElem) -> Result<Option<DesugaredElem>, Outcome>,
    {
        let visited = seq.len();
        let measured = seq.into_iter().map(mapper).collect::<Result<Vec<_>, _>>()?;
        let out = measured.into_iter().flatten().collect();
        self.counted
            .assert_input_count(&operand, visited)
            .map_err(filter_map_floor_refusal)?;
        self.counted.output(out).map_err(filter_map_floor_refusal)
    }
}

fn filter_map_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    use syn::Item;

    use crate::{
        sugar::source_fragment::SourceFragment, sugar_ctx, FloatWidthScope, LiftOptions,
        ReductionCtx, TemporalPlan, TemporalScope,
    };

    struct StubSeq {
        elems: Vec<DesugaredElem>,
    }

    impl Sugar for StubSeq {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Complete(Desugared::Seq(self.elems.clone()))
        }
    }

    fn run(node: &FilterMapSugar) -> Outcome {
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let scope = TemporalScope::new("filter-map-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        node.desugar(&ctx)
    }

    fn elem(src: &str, value: Option<ConstVal>) -> DesugaredElem {
        DesugaredElem {
            expr: syn::parse_str(src).expect("element expr"),
            value,
        }
    }

    fn node_with_elems(elems: Vec<DesugaredElem>) -> FilterMapSugar {
        let closure = syn::parse_str("|x| Some(x)").expect("filter_map closure");
        FilterMapSugar {
            inner: crate::sugar::factory::SugarBody::from_node(Box::new(StubSeq { elems })),
            mapper: FilterMapClosure::new(closure),
        }
    }

    #[test]
    fn runtime_filter_map_element_is_typed_effect_not_floor_panic() {
        let node = node_with_elems(vec![elem(
            r#"edge.get("sourceContract").and_then(Value::as_str)"#,
            None,
        )]);

        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| run(&node)))
            .expect("runtime filter_map element must be a typed effect, not a floor panic");
        let Outcome::Incomplete(effect) = outcome else {
            panic!("runtime filter_map element must not fabricate an adapter result");
        };
        assert!(
            effect.reason().contains("runtime filter_map"),
            "effect should name the filter_map boundary: {}",
            effect.reason()
        );
    }

    #[test]
    fn literal_filter_map_still_keeps_some_values() {
        let node = node_with_elems(vec![
            elem("1", Some(ConstVal::Int(1))),
            elem("2", Some(ConstVal::Int(2))),
        ]);

        let Outcome::Complete(Desugared::Seq(out)) = run(&node) else {
            panic!("literal filter_map should reduce through the counted adapter floor");
        };
        assert_eq!(out.len(), 2);
        assert!(out.iter().all(|elem| elem.value.is_some()));
    }

    #[test]
    fn recognize_declines_non_filter_map_method() {
        let expr: Expr = syn::parse_str("[1].iter().map(|x| Some(x))").expect("expr");
        let frag = SourceFragment::expr(&expr, "test.rs");
        let scope = TemporalScope::new("filter-map-structural", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize_composite(&frag, &fcx).is_none(),
            "filter_map must not claim a non-filter_map method call"
        );
    }
}
