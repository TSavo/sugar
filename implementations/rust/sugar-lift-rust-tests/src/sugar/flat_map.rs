// SPDX-License-Identifier: Apache-2.0
//
// `flat_map`: the `.flat_map(|x| [..])` / `.flat_map(|&n| 0..n)` adaptor over a finite
// literal base whose closure maps each element to a finite literal SUB-SEQUENCE -- an
// array literal OR a bounded range literal (`a..b` / `a..=b`). It applies the closure to
// each element (const-eval, the SAME exact floor as `.map`) and concatenates the
// resulting sub-sequences in source order -- `map` + `flatten` in one step. This is the
// outermost-call recognizer; `peel_fold_adaptors` carries the same `FlatMapSugar` when
// `.flat_map(..)` sits inside a longer adaptor chain.
//
// EXACT-OR-REFUSE: an opaque element (no const value), an unbounded literal range, a
// runtime literal-domain bound, or an over-cap finite domain refuses with a named
// terminal literal-domain reason. Shapes the evaluator does not own are gaps and must
// stay loud. A range whose start >= end yields the empty sub-sequence, a legitimate
// flat_map drop.

use std::collections::BTreeMap;

use crate::sugar::factory::{build_composite, desugar_build_ctx};
use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    const_eval_flat_map_closure, substitute_expr, ConstVal, Desugared, DesugaredElem, Effect,
    FlatMapClosureEval, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP,
};
use syn::{Expr, Pat, Stmt};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("flat_map", recognize_composite);

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "flat_map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(FlatMapRecognizedSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        mapper: FlatMapClosure::new(f.clone()),
    }))
}

struct FlatMapRecognizedSugar {
    inner: SugarBody<CompositeFloor>,
    mapper: FlatMapClosure,
}

impl Sugar for FlatMapRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_flat_map(&self.inner, &self.mapper, ctx)
    }
}

pub(crate) struct FlatMapClosure {
    expr: syn::ExprClosure,
}

impl FlatMapClosure {
    pub(crate) fn new(expr: syn::ExprClosure) -> Self {
        Self { expr }
    }

    fn eval(&self, value: &ConstVal) -> FlatMapClosureEval {
        const_eval_flat_map_closure(&self.expr, value)
    }

    fn substituted_body_for(&self, value: &ConstVal) -> Option<Expr> {
        if self.expr.inputs.len() != 1 {
            return None;
        }
        let tail = closure_tail_expr(&self.expr)?;
        let mut bindings = BTreeMap::new();
        bind_expr_closure_arg(&self.expr.inputs[0], value, &mut bindings)?;
        Some(substitute_expr(tail, &bindings))
    }
}

/// Apply the closure to each element and concatenate the resulting finite literal
/// sub-sequences in source order.
pub(crate) struct FlatMapSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) mapper: FlatMapClosure,
}

impl Sugar for FlatMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_flat_map(&self.inner, &self.mapper, ctx)
    }
}

fn reduce_flat_map(
    inner: &SugarBody<CompositeFloor>,
    mapper: &FlatMapClosure,
    ctx: &SugarCtx,
) -> Outcome {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .unwrap_or_else(|| flat_map_gap("flat_map receiver reduced to non-sequence")),
        Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
    };
    let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
    let let_inits: BTreeMap<String, &Expr> = stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .collect();
    let fcx = desugar_build_ctx(ctx.scope, ctx.options, &let_inits);
    let mut out = Vec::new();
    for elem in seq {
        // An opaque element (no const value) cannot drive the closure.
        let Some(value) = elem.value.as_ref() else {
            return flat_map_literal_domain(
                "literal array element is not text-determined -- flat_map input element is not constructible from source literals; refused",
            );
        };
        let sub = match mapper.eval(value) {
            FlatMapClosureEval::Finite(sub) => flat_map_values_to_elems(sub),
            FlatMapClosureEval::LiteralDomain(reason) => return flat_map_literal_domain(reason),
            FlatMapClosureEval::Gap => {
                match reduce_flat_map_closure_sequence(mapper, value, ctx, &fcx) {
                    Ok(Some(sub)) => sub,
                    Ok(None) => {
                        flat_map_gap("flat_map closure did not reduce to a finite sequence")
                    }
                    Err(outcome) => return outcome,
                }
            }
        };
        let Some(total) = out.len().checked_add(sub.len()) else {
            flat_map_gap("flat_map literal sequence length overflowed");
        };
        if total > SUGAR_SEQ_CAP as usize {
            return flat_map_literal_domain(
                "literal domain exceeds SUGAR_SEQ_CAP -- flat_map concatenated sequence is finite but over-cap; refused",
            );
        }
        out.extend(sub);
    }
    Outcome::Complete(Desugared::Seq(out))
}

fn flat_map_values_to_elems(values: Vec<ConstVal>) -> Vec<DesugaredElem> {
    values
        .into_iter()
        .map(|value| DesugaredElem {
            expr: value
                .to_expr()
                .unwrap_or_else(|| flat_map_gap("flat_map result could not materialize")),
            value: Some(value),
        })
        .collect()
}

fn reduce_flat_map_closure_sequence(
    mapper: &FlatMapClosure,
    value: &ConstVal,
    ctx: &SugarCtx,
    fcx: &SugarBuildCtx,
) -> Result<Option<Vec<DesugaredElem>>, Outcome> {
    let Some(body) = mapper.substituted_body_for(value) else {
        return Ok(None);
    };
    let Some(node) = method_family::build_literal_sequence_composite(&body, fcx)
        .or_else(|| has_composite(&body, fcx).then(|| build_composite(&body, fcx)))
    else {
        return Ok(None);
    };
    match SugarBody::<CompositeFloor>::from_node(node).reduce(ctx) {
        Outcome::Complete(d) => {
            Ok(Some(d.into_seq().unwrap_or_else(|| {
                flat_map_gap("flat_map closure floor reduced to non-sequence")
            })))
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn closure_tail_expr(closure: &syn::ExprClosure) -> Option<&Expr> {
    match closure.body.as_ref() {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [Stmt::Expr(expr, None)] => Some(expr),
            _ => None,
        },
        other => Some(other),
    }
}

fn bind_expr_closure_arg(
    pat: &Pat,
    value: &ConstVal,
    bindings: &mut BTreeMap<String, Expr>,
) -> Option<()> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => {
            bindings.insert(ident.ident.to_string(), value.to_expr()?);
            Some(())
        }
        Pat::Tuple(tuple) => {
            let ConstVal::Tuple(items) = value else {
                return None;
            };
            if tuple.elems.len() != items.len() {
                return None;
            }
            for (pat, item) in tuple.elems.iter().zip(items) {
                bind_expr_closure_arg(pat, item, bindings)?;
            }
            Some(())
        }
        Pat::Wild(_) => Some(()),
        Pat::Paren(paren) => bind_expr_closure_arg(&paren.pat, value, bindings),
        Pat::Reference(reference) => bind_expr_closure_arg(&reference.pat, value, bindings),
        Pat::Type(typed) => bind_expr_closure_arg(&typed.pat, value, bindings),
        _ => None,
    }
}

fn flat_map_gap(reason: &str) -> ! {
    panic!("flat_map did not reach a lawful floor: {reason}")
}

fn flat_map_literal_domain(reason: &str) -> Outcome {
    Outcome::Incomplete(Effect::LiteralDomain {
        boundary: "flat_map".to_string(),
        reason: reason.to_string(),
    })
}
