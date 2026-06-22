// SPDX-License-Identifier: Apache-2.0
//
// `LenSugar`: std literal-sequence length in term position. For written literal arrays,
// slices, ranges, and identity iterator chains over them, `.len()` is a compiler/std
// axiom over the source construction: the value is the concrete element count. Recognition
// only captures the raw receiver; desugar composes the receiver to a literal `Seq` in the
// live binding context, then reduces. Named receiver `Hit`s propagate; structural bails
// remain opaque/undecided at the term accounting layer.

use std::collections::BTreeMap;

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method;
use crate::sugar::method_family;
use crate::sugar::term_leaf::reasoned_hit;
use crate::{simple_path_name, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("len", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "len" || !call.args.is_empty() {
        return None;
    }
    Some(Box::new(LenSugar {
        receiver: (*call.receiver).clone(),
        fallback: expr.clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct LenSugar {
    receiver: Expr,
    fallback: Expr,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for LenSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(name) = simple_path_name(&self.receiver) {
            if ctx.scope.is_consumed_iterator_local(&name) {
                return reasoned_hit(format!(
                    "consumed-iterator local `{name}` -- \
                     `.len()` returns stale pre-consumption length (temporal instability)"
                ))
                .desugar(ctx);
            }
        }
        let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
        let let_inits: BTreeMap<String, &Expr> = stable
            .iter()
            .map(|(name, init)| (name.clone(), init))
            .chain(
                self.let_inits
                    .iter()
                    .map(|(name, init)| (name.clone(), init)),
            )
            .collect();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let seq = match build_composite(&self.receiver, &fcx).desugar(ctx) {
            Outcome::Dug(d) => match d.into_seq() {
                Some(seq) => seq,
                None => return self.fallback_method(ctx, &fcx),
            },
            Outcome::Hit(Effect::Unsupported { reason })
                if reason == EMPTY_DOMAIN_REASON
                    && method_family::literal_sequence_static_len_in_scope(
                        &self.receiver,
                        &let_inits,
                        ctx.scope,
                    ) == Some(0) =>
            {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::len",
                    len = 0usize,
                    "reducing empty literal sequence len"
                );
                return Outcome::Dug(Desugared::Term(num(0)));
            }
            hit if hit.is_structural_bail() => {
                match method_family::build_literal_sequence_composite(&self.receiver, &fcx) {
                    Some(inner) => match inner.desugar(ctx) {
                        Outcome::Dug(d) => match d.into_seq() {
                            Some(seq) => seq,
                            None => return self.fallback_method(ctx, &fcx),
                        },
                        Outcome::Hit(Effect::Unsupported { reason })
                            if reason == EMPTY_DOMAIN_REASON =>
                        {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::len",
                                len = 0usize,
                                "reducing empty literal sequence len"
                            );
                            return Outcome::Dug(Desugared::Term(num(0)));
                        }
                        hit if hit.is_structural_bail() => return self.fallback_method(ctx, &fcx),
                        hit => return hit,
                    },
                    None => {
                        if let Some(static_len) =
                            method_family::literal_collection_adapter_static_len_in_scope(
                                &self.receiver,
                                &let_inits,
                                ctx.scope,
                            )
                        {
                            match self.verify_static_len_source(&static_len.source, ctx, &fcx) {
                                Ok(true) => {
                                    debug!(
                                        target: "sugar_lift_rust_tests::sugar::len",
                                        len = static_len.len,
                                        "reducing literal collection len through verified length-only adapter"
                                    );
                                    return Outcome::Dug(Desugared::Term(num(
                                        static_len.len as i128
                                    )));
                                }
                                Ok(false) => return self.fallback_method(ctx, &fcx),
                                Err(hit) => return hit,
                            }
                        }
                        return self.fallback_method(ctx, &fcx);
                    }
                }
            }
            hit => return hit,
        };
        let len = seq.len();
        debug!(
            target: "sugar_lift_rust_tests::sugar::len",
            len,
            "reducing literal sequence len"
        );
        Outcome::Dug(Desugared::Term(num(len as i128)))
    }
}

impl LenSugar {
    fn verify_static_len_source(
        &self,
        source: &Expr,
        ctx: &SugarCtx,
        fcx: &SugarBuildCtx,
    ) -> Result<bool, Outcome> {
        let candidate = method_family::build_literal_sequence_composite(source, fcx)
            .unwrap_or_else(|| build_composite(source, fcx));
        match candidate.desugar(ctx) {
            Outcome::Dug(d) => Ok(d.into_seq().is_some()),
            Outcome::Hit(Effect::Unsupported { reason }) if reason == EMPTY_DOMAIN_REASON => {
                Ok(true)
            }
            hit if hit.is_structural_bail() => Ok(false),
            hit => Err(hit),
        }
    }

    fn fallback_method(&self, ctx: &SugarCtx, fcx: &SugarBuildCtx) -> Outcome {
        match method::recognize(&self.fallback, fcx) {
            Some(fallback) => fallback.desugar(ctx),
            None => Outcome::from_opt(None),
        }
    }
}
