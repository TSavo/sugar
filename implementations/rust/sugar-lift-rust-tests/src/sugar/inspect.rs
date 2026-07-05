// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `inspect`: value-preserving `.inspect(f)` surfaces. `Iterator::inspect` yields the
// SAME items in the SAME order, so over a finite literal sequence it is the IDENTITY
// adaptor. `Result::{inspect, inspect_err}` similarly returns the original Result; the
// term-level arm below erases it only when the receiver is a stable Result constructor
// and the callback is syntactically proven no-op. A non-noop callback is a named
// refusal; an impossible non-Result receiver is a construction-law panic.

use quote::ToTokens;
use syn::{Expr, ExprClosure};

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
use crate::sugar::monadic::{RES_ERR, RES_OK};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{
    AdapterFloorOutput, AdapterOutputIterMember, CountedAdapterFloor, IterStanding,
    TemporalFloorRefusal,
};
use crate::{strip_refs_groups, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "inspect",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_inspect_good() {
                    let got = [1i32, 2, 3].iter().inspect(|x| { let _ = x; }).count();
                    assert_eq!(got, 3);
                }
            "#,
            r#"
                #[test]
                fn t_inspect_bad() {
                    let got = [1i32, 2, 3].iter().inspect(|x| { let _ = x; }).count();
                    assert_eq!(got, 4);
                }
            "#,
        ),
        recognize_composite,
    );

pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "result_inspect",
        &["method"],
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S6 Option-Result family: inspect on Result",
        ),
        recognize_term,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "inspect" && call.args.len() == 1 {
        return Some(Box::new(InspectSugar {
            inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
                &call.receiver,
                fcx,
            )?),
        }));
    }
    None
}

pub(crate) struct InspectSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
}

impl Sugar for InspectSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .unwrap_or_else(|| inspect_gap("inspect receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let floor = InspectFloor::default();
        let operand = match floor.derived_operand(seq.len()) {
            Ok(operand) => operand,
            Err(outcome) => return outcome,
        };
        let output = match floor.desugar(operand, seq) {
            Ok(output) => output,
            Err(outcome) => return outcome,
        };
        ctx.record_adapter_floor_audit("inspect", output.standing().count());
        Outcome::Complete(Desugared::Seq(output.into_items()))
    }
}

pub(crate) fn recognize_term(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !matches!(call.method.to_string().as_str(), "inspect" | "inspect_err")
        || call.args.len() != 1
    {
        return None;
    }
    if !is_stable_result_source(&call.receiver, fcx) {
        return None;
    }
    let receiver = SugarBody::term(&call.receiver, fcx);
    Some(ResultInspectSugar::new(receiver, call.args[0].clone()))
}

struct ResultInspectSugar {
    receiver: SugarBody<TermFloor>,
    callback: ResultInspectCallback,
}

impl ResultInspectSugar {
    fn new(receiver: SugarBody<TermFloor>, callback: Expr) -> Box<dyn Sugar> {
        Box::new(Self {
            receiver,
            callback: ResultInspectCallback::new(callback),
        })
    }
}

struct ResultInspectCallback {
    callback_source: Expr,
}

impl ResultInspectCallback {
    fn new(callback_source: Expr) -> Self {
        Self { callback_source }
    }

    fn is_noop(&self, ctx: &SugarCtx) -> bool {
        callback_is_noop(&self.callback_source, ctx)
    }

    fn boundary(&self) -> String {
        self.callback_source.to_token_stream().to_string()
    }
}

impl Sugar for ResultInspectSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if !self.callback.is_noop(ctx) {
            return Outcome::Incomplete(Effect::ResultInspectCallback {
                boundary: self.callback.boundary(),
            });
        }
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => result_inspect_gap("Result inspect receiver reduced to non-term"),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        match receiver.as_ref() {
            sugar_ir_symbolic::Term::Ctor { name, .. } if name == RES_OK || name == RES_ERR => {
                Outcome::Complete(Desugared::Term(receiver))
            }
            _ => result_inspect_gap("Result inspect receiver did not reduce to Result constructor"),
        }
    }
}

fn result_inspect_gap(reason: &str) -> ! {
    panic!("ResultInspectSugar did not reach a lawful value floor: {reason}")
}

#[derive(Clone, Copy)]
struct InspectFloor {
    counted: CountedAdapterFloor,
}

impl Default for InspectFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("inspect", AdapterOutputIterMember::inspect),
        }
    }
}

impl InspectFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(inspect_floor_refusal)
    }

    fn desugar(
        &self,
        operand: IterStanding,
        seq: Vec<DesugaredElem>,
    ) -> Result<AdapterFloorOutput<DesugaredElem>, Outcome> {
        let expected = operand.count();
        let out = seq.into_iter().inspect(|_| {}).collect::<Vec<_>>();
        self.counted
            .assert_output_count(&operand, expected, out.len())
            .map_err(inspect_floor_refusal)?;
        self.counted.output(out).map_err(inspect_floor_refusal)
    }
}

fn inspect_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
}

fn inspect_gap(reason: &str) -> ! {
    panic!("InspectSugar did not reach a lawful floor: {reason}")
}

pub(crate) fn is_stable_result_source(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    is_stable_result_source_inner(expr, fcx, 0)
}

fn is_stable_result_source_inner(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return false;
            };
            let Some(init) = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
            else {
                return false;
            };
            is_stable_result_source_inner(init, fcx, depth + 1)
        }
        Expr::Call(call) => {
            is_static_result_ctor_call(call, fcx, depth)
                || crate::sugar::try_from::folds_to_result(call, Some(fcx))
        }
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "inspect" | "inspect_err")
                && call.args.len() == 1 =>
        {
            callback_is_noop_in_scope(&call.args[0], fcx.scope())
                && is_stable_result_source_inner(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => is_stable_result_source_inner(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => is_stable_result_source_inner(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn is_static_result_ctor_call(call: &syn::ExprCall, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if call.args.len() != 1 {
        return false;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return false;
    };
    let is_result_ctor = path
        .path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == "Ok" || seg.ident == "Err");
    is_result_ctor && static_payload(&call.args[0], fcx, depth + 1)
}

fn static_payload(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(_) => true,
        Expr::Tuple(tuple) if tuple.elems.is_empty() => true,
        Expr::Unary(unary) => matches!(&*unary.expr, Expr::Lit(_)),
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return false;
            };
            let Some(init) = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
            else {
                return false;
            };
            static_payload(init, fcx, depth + 1)
        }
        Expr::Paren(paren) => static_payload(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => static_payload(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn callback_is_noop(expr: &Expr, ctx: &SugarCtx) -> bool {
    callback_is_noop_in_scope(expr, ctx.scope)
}

fn callback_is_noop_in_scope(expr: &Expr, scope: &crate::TemporalScope) -> bool {
    match strip_refs_groups(expr) {
        Expr::Closure(closure) => closure_is_noop(closure),
        Expr::Path(path) if path.qself.is_none() => path
            .path
            .get_ident()
            .is_some_and(|name| scope.visible_fn_has_noop_body(&name.to_string())),
        _ => false,
    }
}

fn closure_is_noop(closure: &ExprClosure) -> bool {
    match strip_refs_groups(&closure.body) {
        Expr::Tuple(tuple) if tuple.elems.is_empty() => true,
        Expr::Block(block) => block.block.stmts.is_empty(),
        _ => false,
    }
}
