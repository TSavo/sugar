// SPDX-License-Identifier: MIT OR Apache-2.0
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

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::sequence_floor::RequiredSequenceVisitor;
use crate::sugar::source_fragment::SourceFragment;
use crate::{const_int, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "iter_next",
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S5/S6 iterator state family: next() consumption",
        ),
        recognize_composite,
    );

enum Direction {
    Front,
    Back,
}

pub(crate) fn sequence_consumption_adaptor(
    inner: Box<dyn Sugar>,
    method: &str,
    count: usize,
) -> Option<Box<dyn Sugar>> {
    let direction = match method {
        "next" | "nth" => Direction::Front,
        "next_back" | "nth_back" => Direction::Back,
        _ => return None,
    };
    Some(IterNextSugar::new(
        SugarBody::from_node(inner),
        direction,
        count,
    ))
}

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
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
    let inner = SugarBody::composite(&call.receiver, fcx);
    Some(IterNextSugar::new(inner, direction, count))
}

struct IterNextSugar {
    inner: SugarBody<CompositeFloor>,
    direction: Direction,
    count: usize,
}

impl IterNextSugar {
    fn new(inner: SugarBody<CompositeFloor>, direction: Direction, count: usize) -> Box<dyn Sugar> {
        Box::new(Self {
            inner,
            direction,
            count,
        })
    }
}

impl Sugar for IterNextSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(desugared) => {
                desugared.accept_sequence_floor(RequiredSequenceVisitor {
                    owner: "iter_next composite receiver",
                })
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
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
        Outcome::Complete(Desugared::Seq(out))
    }
}
