// SPDX-License-Identifier: Apache-2.0
//
// `CallSequenceSugar`: `Expr::Call` in COMPOSITE position.
//
// Term-position `CallSugar` can peel a visible pure helper to a grounded term.
// This is the sequence-floor sibling: when a visible helper returns source that
// recursively reaches a literal sequence base, the call can feed iterator sugar
// directly:
//
//   make_vec().iter().next().len()
//   make_vec() -> vec![1, 2] -> Seq([1, 2]) -> next(drop 1) -> len == 1
//
// The recognizer is deliberately boring: any `Expr::Call` in composite position is
// this sugar. Desugar owns the semantic question and either digs through the
// recursive factory to `Seq` or hits the structural/effect boundary.

use syn::Expr;
use tracing::debug;

use crate::sugar::factory::SugarBuildCtx;
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("call_sequence", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    let args: Vec<Expr> = call.args.iter().cloned().collect();
    Some(Box::new(CallSequenceSugar {
        func: (*call.func).clone(),
        args,
    }))
}

struct CallSequenceSugar {
    func: Expr,
    args: Vec<Expr>,
}

impl Sugar for CallSequenceSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match ctx.try_inline_sequence_call(&self.func, &self.args) {
            Outcome::Dug(desugared) => {
                let len = match &desugared {
                    Desugared::Seq(seq) => seq.len(),
                    _ => 0,
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::call_sequence",
                    len,
                    "inlined visible helper call to literal sequence"
                );
                Outcome::Dug(desugared)
            }
            hit @ Outcome::Hit(_) => hit,
        }
    }
}
