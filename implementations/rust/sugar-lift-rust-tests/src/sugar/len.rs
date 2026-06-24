// SPDX-License-Identifier: Apache-2.0
//
// `LenSugar`: std literal-sequence length in term position. For written literal arrays,
// slices, ranges, and identity iterator chains over them, `.len()` is a compiler/std
// axiom over the source construction: the value is the concrete element count. Recognition
// constructs the receiver body and any static-length verifier body without reducing them.
// Named receiver `Incomplete`s propagate; impossible non-sequence child floors panic.

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::factory::{build_composite, CompositeFloor, SugarBody, SugarBuildCtx};
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
    let consumed_receiver = simple_path_name(&call.receiver);
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
        sequence_body(&call.receiver, fcx),
        static_len,
        static_collection_len,
        consumed_receiver,
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
    receiver: SugarBody<CompositeFloor>,
    static_len: Option<usize>,
    static_collection_len: Option<StaticLenSource>,
    consumed_receiver: Option<String>,
}

struct StaticLenSource {
    len: usize,
    source: SugarBody<CompositeFloor>,
}

impl Sugar for LenSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(name) = &self.consumed_receiver {
            if ctx.scope.is_consumed_iterator_local(&name) {
                if self.static_len == Some(0) {
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::len",
                        len = 0usize,
                        binding = name.as_str(),
                        "reducing exhausted consumed-iterator len through temporal rewrite"
                    );
                    return Outcome::Complete(Desugared::Term(num(0)));
                }
                return Outcome::Incomplete(Effect::RuntimeArgument {
                    boundary: name.clone(),
                    reason: format!(
                        "consumed-iterator local `{name}` -- \
                     `.len()` is a temporally unstable stale pre-consumption length read"
                    ),
                });
            }
        }
        if self.static_len == Some(0) {
            debug!(
                target: "sugar_lift_rust_tests::sugar::len",
                len = 0usize,
                "reducing empty literal sequence len"
            );
            return Outcome::Complete(Desugared::Term(num(0)));
        }
        let seq = match sequence_from_body(&self.receiver, ctx, "len receiver") {
            Ok(seq) => seq,
            Err(Outcome::Incomplete(effect))
                if effect.reason() == EMPTY_DOMAIN_REASON && self.static_len == Some(0) =>
            {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::len",
                    len = 0usize,
                    "reducing empty literal sequence len"
                );
                return Outcome::Complete(Desugared::Term(num(0)));
            }
            Err(Outcome::Complete(_)) => {
                len_gap("len receiver sequence helper returned unexpected Complete")
            }
            Err(Outcome::Incomplete(effect)) => return Outcome::Incomplete(effect),
            Err(gap) => {
                if let Some(static_len) = &self.static_collection_len {
                    match source_reduces_to_sequence(&static_len.source, ctx) {
                        Ok(true) => {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::len",
                                len = static_len.len,
                                "reducing literal collection len through verified length-only adapter"
                            );
                            return Outcome::Complete(Desugared::Term(num(static_len.len as i128)));
                        }
                        Ok(false) => {}
                        Err(outcome) => return outcome,
                    }
                }
                return gap;
            }
        };
        let len = seq.len();
        debug!(
            target: "sugar_lift_rust_tests::sugar::len",
            len,
            "reducing literal sequence len"
        );
        Outcome::Complete(Desugared::Term(num(len as i128)))
    }
}

impl LenSugar {
    fn new(
        receiver: SugarBody<CompositeFloor>,
        static_len: Option<usize>,
        static_collection_len: Option<StaticLenSource>,
        consumed_receiver: Option<String>,
    ) -> Box<dyn Sugar> {
        Box::new(Self {
            receiver,
            static_len,
            static_collection_len,
            consumed_receiver,
        })
    }
}

fn sequence_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
    SugarBody::from_node(
        method_family::build_literal_sequence_composite(expr, fcx)
            .unwrap_or_else(|| build_composite(expr, fcx)),
    )
}

fn sequence_from_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Vec<DesugaredElem>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .ok_or_else(|| len_gap(&format!("{label} reduced to non-sequence"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn source_reduces_to_sequence(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
) -> Result<bool, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d.into_seq().is_some()),
        Outcome::Incomplete(effect) if effect.reason() == EMPTY_DOMAIN_REASON => Ok(true),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn len_gap(reason: &str) -> ! {
    panic!("len completed without a literal sequence floor: {reason}")
}
