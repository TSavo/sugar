// SPDX-License-Identifier: Apache-2.0
//
// `LenSugar`: std literal-sequence length in term position. For written literal arrays,
// slices, ranges, and identity iterator chains over them, `.len()` is a compiler/std
// axiom over the source construction: the value is the concrete element count. Recognition
// constructs the receiver body and any static-length verifier body without reducing them.
// Named receiver `Incomplete`s propagate; structural bails take the factory gap path.

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::factory::{
    build_composite, compat_reduction, FactoryGap, FactoryReduction, SugarBody, SugarBuildCtx,
};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method_family;
use crate::{simple_path_name, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("len", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "len" || !call.args.is_empty() {
        return None;
    }
    if !len_receiver_is_owned_by_literal_sugar(&call.receiver, fcx) {
        return None;
    }
    let receiver_expr = (*call.receiver).clone();
    let static_len = method_family::literal_sequence_static_len_in_scope(
        &call.receiver,
        fcx.let_inits(),
        fcx.scope(),
    );
    let static_collection_len = method_family::literal_collection_adapter_static_len_in_scope(
        &call.receiver,
        fcx.let_inits(),
        fcx.scope(),
    )
    .map(|static_len| StaticLenSource {
        len: static_len.len,
        source: sequence_body(&static_len.source, fcx),
    });
    Some(LenSugar::new(
        receiver_expr,
        sequence_body(&call.receiver, fcx),
        static_len,
        static_collection_len,
    ))
}

fn len_receiver_is_owned_by_literal_sugar(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    method_family::resolves_literal_sequence(expr, fcx.let_inits())
        || method_family::literal_sequence_static_len_in_scope(expr, fcx.let_inits(), fcx.scope())
            .is_some()
        || method_family::literal_collection_adapter_static_len_in_scope(
            expr,
            fcx.let_inits(),
            fcx.scope(),
        )
        .is_some()
        || simple_path_name(expr).is_some_and(|name| fcx.scope().is_consumed_iterator_local(&name))
}

struct LenSugar {
    receiver_expr: Expr,
    receiver: SugarBody,
    static_len: Option<usize>,
    static_collection_len: Option<StaticLenSource>,
}

struct StaticLenSource {
    len: usize,
    source: SugarBody,
}

impl Sugar for LenSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        if let Some(name) = simple_path_name(&self.receiver_expr) {
            if ctx.scope.is_consumed_iterator_local(&name) {
                if self.static_len == Some(0) {
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::len",
                        len = 0usize,
                        binding = name.as_str(),
                        "reducing exhausted consumed-iterator len through temporal rewrite"
                    );
                    return Ok(Outcome::Complete(Desugared::Term(num(0))));
                }
                return Ok(Outcome::Incomplete(Effect::Unsupported {
                    reason: format!(
                        "consumed-iterator local `{name}` -- \
                     `.len()` is a temporally unstable stale pre-consumption length read"
                    ),
                }));
            }
        }
        if self.static_len == Some(0) {
            debug!(
                target: "sugar_lift_rust_tests::sugar::len",
                len = 0usize,
                "reducing empty literal sequence len"
            );
            return Ok(Outcome::Complete(Desugared::Term(num(0))));
        }
        let seq = match sequence_from_body(&self.receiver, ctx, "len receiver") {
            Ok(seq) => seq,
            Err(Ok(Outcome::Incomplete(Effect::Unsupported { reason })))
                if reason == EMPTY_DOMAIN_REASON && self.static_len == Some(0) =>
            {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::len",
                    len = 0usize,
                    "reducing empty literal sequence len"
                );
                return Ok(Outcome::Complete(Desugared::Term(num(0))));
            }
            Err(Ok(Outcome::Complete(_))) => {
                return Err(FactoryGap::new(
                    "len receiver sequence helper returned unexpected Complete",
                ))
            }
            Err(Ok(Outcome::Incomplete(effect))) => return Ok(Outcome::Incomplete(effect)),
            Err(Err(gap)) => {
                if let Some(static_len) = &self.static_collection_len {
                    match source_reduces_to_sequence(&static_len.source, ctx) {
                        Ok(true) => {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::len",
                                len = static_len.len,
                                "reducing literal collection len through verified length-only adapter"
                            );
                            return Ok(Outcome::Complete(Desugared::Term(num(
                                static_len.len as i128
                            ))));
                        }
                        Ok(false) => {}
                        Err(reduction) => return reduction,
                    }
                }
                return Err(gap);
            }
        };
        let len = seq.len();
        debug!(
            target: "sugar_lift_rust_tests::sugar::len",
            len,
            "reducing literal sequence len"
        );
        Ok(Outcome::Complete(Desugared::Term(num(len as i128))))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

impl LenSugar {
    fn new(
        receiver_expr: Expr,
        receiver: SugarBody,
        static_len: Option<usize>,
        static_collection_len: Option<StaticLenSource>,
    ) -> Box<dyn Sugar> {
        Box::new(Self {
            receiver_expr,
            receiver,
            static_len,
            static_collection_len,
        })
    }
}

fn sequence_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody {
    SugarBody::from_node(
        method_family::build_literal_sequence_composite(expr, fcx)
            .unwrap_or_else(|| build_composite(expr, fcx)),
    )
}

fn sequence_from_body(
    body: &SugarBody,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Vec<DesugaredElem>, FactoryReduction> {
    match body.reduce(ctx) {
        Ok(Outcome::Complete(d)) => d
            .into_seq()
            .ok_or_else(|| Err(FactoryGap::new(format!("{label} reduced to non-sequence")))),
        Ok(Outcome::Incomplete(effect)) => Err(Ok(Outcome::Incomplete(effect))),
        Err(gap) => Err(Err(gap)),
    }
}

fn source_reduces_to_sequence(body: &SugarBody, ctx: &SugarCtx) -> Result<bool, FactoryReduction> {
    match body.reduce(ctx) {
        Ok(Outcome::Complete(d)) => Ok(d.into_seq().is_some()),
        Ok(Outcome::Incomplete(Effect::Unsupported { reason }))
            if reason == EMPTY_DOMAIN_REASON =>
        {
            Ok(true)
        }
        Ok(Outcome::Incomplete(effect)) => Err(Ok(Outcome::Incomplete(effect))),
        Err(gap) => Err(Err(gap)),
    }
}
