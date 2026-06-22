// SPDX-License-Identifier: Apache-2.0
//
// `IterNextSugar`: consuming iterator terminals in COMPOSITE position.
//
// In term position, `.next()` is a value terminal: it returns `Option<Item>` and is owned by
// `IterTerminalSugar`. In receiver/composite position, the same source shape is an iterator
// state transition: `<seq>.next()` advances the sequence by one and returns the remaining
// iterator state. That lets chains desugar structurally:
//
//   [1, 2].iter().next().next().len()
//   array literal -> iterator -> next(drop 1) -> next(drop 1) -> len == 0
//
// This node only recognizes when the receiver is already a factory-owned composite
// sequence. Runtime / effect receivers do not enter the node and fall through normally.

use syn::Expr;
use tracing::debug;

use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::{const_int, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("iter_next", recognize_composite);

enum Direction {
    Front,
    Back,
}

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let (direction, count) = match (call.method.to_string().as_str(), call.args.len()) {
        ("next", 0) => (Direction::Front, 1usize),
        ("next_back", 0) => (Direction::Back, 1usize),
        ("nth", 1) => {
            let n: usize = const_int(&call.args[0])?.try_into().ok()?;
            (Direction::Front, n.checked_add(1)?)
        }
        ("nth_back", 1) => {
            let n: usize = const_int(&call.args[0])?.try_into().ok()?;
            (Direction::Back, n.checked_add(1)?)
        }
        _ => return None,
    };
    if !has_composite(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(IterNextSugar {
        inner: build_composite(&call.receiver, fcx),
        direction,
        count,
    }))
}

struct IterNextSugar {
    inner: Box<dyn Sugar>,
    direction: Direction,
    count: usize,
}

impl Sugar for IterNextSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            debug!(
                target: "sugar_lift_rust_tests::sugar::iter_next",
                len = seq.len(),
                count = self.count,
                from_back = matches!(self.direction, Direction::Back),
                "advancing literal iterator state in composite position"
            );
            let out = match self.direction {
                Direction::Front => seq.into_iter().skip(self.count).collect(),
                Direction::Back => {
                    let keep = seq.len().saturating_sub(self.count);
                    seq.into_iter().take(keep).collect()
                }
            };
            Some(Desugared::Seq(out))
        })())
    }
}
