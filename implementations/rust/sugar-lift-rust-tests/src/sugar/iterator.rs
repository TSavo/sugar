// SPDX-License-Identifier: Apache-2.0
//
// `IteratorSugar`: the `.iter()` / `.into_iter()` identity-family adaptor over a
// sequence Sugar. It is the explicit node between a literal domain and terminals like
// `.next()`: `[1, 2, 3]` -> `LiteralSugar`, `.iter()` -> `IteratorSugar`, `.next()` ->
// `IterTerminalSugar`.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("iterator", recognize_composite);

/// COMPOSITE recognizer for identity-family iterator adaptors.
pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    match call.method.to_string().as_str() {
        "iter" | "into_iter" | "cloned" | "copied" | "fuse" => {
            let inner = method_family::build_literal_sequence_composite(&call.receiver, fcx)?;
            Some(Box::new(IteratorSugar { inner }))
        }
        _ => None,
    }
}

/// Identity-family iterator adaptor. Desugars by passing through the inner sequence.
pub(crate) struct IteratorSugar {
    pub(crate) inner: Box<dyn Sugar>,
}

impl Sugar for IteratorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            Some(Desugared::Seq(seq))
        })())
    }
}
