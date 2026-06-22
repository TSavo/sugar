// SPDX-License-Identifier: Apache-2.0
//
// `LenSugar`: std literal-sequence length in term position. For written literal arrays,
// slices, ranges, and identity iterator chains over them, `.len()` is a compiler/std
// axiom over the source construction: the value is the concrete element count. Runtime
// receivers decline to `MethodSugar`.

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::term_leaf::reasoned_hit;
use crate::{simple_path_name, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("len", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "len" || !call.args.is_empty() {
        return None;
    }
    // REFUSE: a mut-iterator local consumed by .next()/.by_ref()/etc. has a stale
    // internal position -- the static length the lifter computes is the PRE-consumption
    // value, which refutes true post-consumption assertions (e.g. `it.len() == 0` after
    // exhausting a while-let loop). See `collect_consumed_iterator_locals`.
    if let Some(name) = simple_path_name(&call.receiver) {
        if fcx.scope().is_consumed_iterator_local(&name) {
            return Some(reasoned_hit(format!(
                "consumed-iterator local `{name}` -- \
                 `.len()` returns stale pre-consumption length (temporal instability)"
            )));
        }
    }
    if has_composite(&call.receiver, fcx) {
        return Some(Box::new(LenSugar {
            inner: Some(build_composite(&call.receiver, fcx)),
            len: None,
        }));
    }
    let len = method_family::literal_sequence_static_len_in_scope(
        &call.receiver,
        fcx.let_inits(),
        fcx.scope(),
    )?;
    Some(Box::new(LenSugar {
        inner: None,
        len: Some(len),
    }))
}

struct LenSugar {
    inner: Option<Box<dyn Sugar>>,
    len: Option<usize>,
}

impl Sugar for LenSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let len = match &self.inner {
                Some(inner) => inner.desugar(ctx).dug()?.into_seq()?.len(),
                None => self.len?,
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::len",
                len,
                "reducing literal sequence len"
            );
            Some(Desugared::Term(num(len as i128)))
        })())
    }
}
