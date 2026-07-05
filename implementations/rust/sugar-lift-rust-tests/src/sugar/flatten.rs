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

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::flat_map::{FlatMapClosure, FlatMapSugar};
use crate::sugar::method_family;
use crate::sugar::sequence_floor::SequenceElementVisitor;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "flatten",
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S5 adapter family: flatten expansion",
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
    // The receiver must resolve to a finite literal sequence (whose ELEMENTS are
    // checked to be sub-sequences at desugar time, bailing if not).
    if call.method == "flatten" && call.args.is_empty() {
        if let Some(sugar) = {
            let _frag = SourceFragment::expr(call.receiver.as_ref(), "<src>");
            recognize_map_flatten(&_frag, fcx)
        } {
            return Some(sugar);
        }
        return Some(Box::new(FlattenSugar {
            inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
                &call.receiver,
                fcx,
            )?),
        }));
    }
    None
}

fn recognize_map_flatten(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let receiver = frag.as_expr()?;
    let Expr::MethodCall(map_call) = receiver else {
        return None;
    };
    if map_call.method != "map" || map_call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &map_call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(&map_call.receiver, fcx.let_inits())
        && !has_composite(&map_call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(FlatMapSugar {
        inner: SugarBody::composite(&map_call.receiver, fcx),
        mapper: FlatMapClosure::new(f.clone()),
    }))
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
        Err(Outcome::Incomplete(Effect::RuntimeFlattenElement {
            boundary: quote::quote!(#expr).to_string(),
        }))
    }

    fn visit_non_sequence_literal(self, _elem: &DesugaredElem) -> Self::Output {
        panic!("flatten element dispatched to a non-sequence literal floor")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::{
        sugar_ctx, ConstVal, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar,
        TemporalPlan, TemporalScope,
    };
    use syn::{Expr, Item};

    struct StubSeq {
        elems: Vec<DesugaredElem>,
    }

    impl Sugar for StubSeq {
        fn desugar(&self, _ctx: &crate::SugarCtx) -> Outcome {
            Outcome::Complete(Desugared::Seq(self.elems.clone()))
        }
    }

    fn run(node: &FlattenSugar) -> Outcome {
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let scope = TemporalScope::new("flatten-test", TemporalPlan::default());
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

    #[test]
    fn runtime_flatten_element_is_typed_effect_not_floor_panic() {
        let node = FlattenSugar {
            inner: crate::sugar::factory::SugarBody::from_node(Box::new(StubSeq {
                elems: vec![elem(
                    r#"edge.get("sourceContract").and_then(Value::as_str)"#,
                    None,
                )],
            })),
        };

        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| run(&node)))
            .expect("runtime flatten element must be a typed effect, not a floor panic");
        let Outcome::Incomplete(effect) = outcome else {
            panic!("runtime flatten element must not fabricate a nested sequence");
        };
        assert!(
            effect.reason().contains("runtime flatten element"),
            "effect should name the flatten boundary: {}",
            effect.reason()
        );
    }

    #[test]
    fn literal_nested_arrays_still_flatten() {
        let node = FlattenSugar {
            inner: crate::sugar::factory::SugarBody::from_node(Box::new(StubSeq {
                elems: vec![
                    elem(
                        "[1, 2]",
                        Some(ConstVal::Array(vec![ConstVal::Int(1), ConstVal::Int(2)])),
                    ),
                    elem("[3]", Some(ConstVal::Array(vec![ConstVal::Int(3)]))),
                ],
            })),
        };

        let Outcome::Complete(Desugared::Seq(out)) = run(&node) else {
            panic!("literal nested arrays should flatten to a sequence");
        };
        assert_eq!(out.len(), 3);
    }

    #[test]
    fn recognize_declines_wrong_method() {
        let expr: Expr = syn::parse_str("[[1]].iter().map(|x| x)").expect("expr");
        let frag = SourceFragment::expr(&expr, "test.rs");
        let scope = TemporalScope::new("flatten-structural", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize_composite(&frag, &fcx).is_none(),
            "flatten must not claim a non-flatten method call"
        );
    }
}
