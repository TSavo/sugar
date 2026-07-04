// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Public route-raises spine.
//
// Python reference: `TrySugar._route_incomplete` returns non-raise outcomes
// unchanged, asks handlers in order for raise-like effects, and returns an
// unmatched raise unchanged. `operations/route_raises_operation.py` uses the
// same handler protocol for block-interior raises-as-data. Rust mirrors that
// split: `route_incomplete` is the TrySugar-equivalent router, and
// `RouteRaisesAccept` is the block-data dispatch seam. Scope-specific handler
// context lives with the consumer; this shared crate deliberately carries only
// the algebraic effect and guard data needed across the IrTerm boundary.

use std::rc::Rc;

use sugar_ir_symbolic::{and_, Formula};

use crate::control_flow_guard_operation::{guard_block, guard_exit};
use crate::{
    desugared_floor_name, is_raise_like_effect, Desugared, Effect, GuardedRaise, GuardedReturn,
    Outcome, RaiseValue,
};

pub trait RouteRaiseHandler {
    fn matches(&self, effect: &Effect) -> bool;
    fn reduce(&self, effect: &Effect) -> Outcome;
}

pub trait RouteRaisesVisitor {
    type Output;

    fn visit_stmt_raise(self, raise: RaiseValue) -> Self::Output;
    fn visit_stmt_guarded_raise(self, guarded_raise: GuardedRaise) -> Self::Output;
    fn visit_stmt_block(
        self,
        guarded: Vec<GuardedReturn>,
        raises: Vec<GuardedRaise>,
        fall_through: Vec<Rc<Formula>>,
    ) -> Self::Output;
    fn visit_non_raise_route(self, floor: Desugared) -> Self::Output;
}

pub trait RouteRaisesAccept {
    fn accept_route_raises<V: RouteRaisesVisitor>(self, visitor: V) -> V::Output;
}

impl RouteRaisesAccept for Desugared {
    fn accept_route_raises<V: RouteRaisesVisitor>(self, visitor: V) -> V::Output {
        match self {
            Desugared::StmtRaise(raise) => visitor.visit_stmt_raise(raise),
            Desugared::StmtGuardedRaise(guarded_raise) => {
                visitor.visit_stmt_guarded_raise(guarded_raise)
            }
            Desugared::StmtBlock {
                guarded,
                raises,
                fall_through,
            } => visitor.visit_stmt_block(guarded, raises, fall_through),
            other => visitor.visit_non_raise_route(other),
        }
    }
}

pub struct RouteRaisesOperation<'a> {
    handlers: Vec<&'a dyn RouteRaiseHandler>,
    owner: &'a str,
}

impl<'a> RouteRaisesOperation<'a> {
    pub fn new(handlers: Vec<&'a dyn RouteRaiseHandler>, owner: &'a str) -> Self {
        Self { handlers, owner }
    }

    pub fn route_incomplete(self, outcome: Outcome) -> Outcome {
        let Outcome::Incomplete(effect) = outcome else {
            return outcome;
        };
        if !is_raise_like_effect(&effect) {
            return Outcome::Incomplete(effect);
        }
        for handler in &self.handlers {
            if handler.matches(&effect) {
                return handler.reduce(&effect);
            }
        }
        Outcome::Incomplete(effect)
    }

    pub fn route_desugared(self, desugared: Desugared) -> Outcome {
        desugared.accept_route_raises(self)
    }

    pub fn route_outcome(self, outcome: Outcome) -> Outcome {
        match outcome {
            Outcome::Complete(desugared) => self.route_desugared(desugared),
            Outcome::Incomplete(_) => self.route_incomplete(outcome),
        }
    }
}

impl RouteRaisesVisitor for RouteRaisesOperation<'_> {
    type Output = Outcome;

    fn visit_stmt_raise(self, raise: RaiseValue) -> Self::Output {
        route_single_raise(
            GuardedRaise::from_raise(Vec::new(), raise),
            self.handlers,
            self.owner,
        )
    }

    fn visit_stmt_guarded_raise(self, guarded_raise: GuardedRaise) -> Self::Output {
        route_single_raise(guarded_raise, self.handlers, self.owner)
    }

    fn visit_stmt_block(
        self,
        mut guarded: Vec<GuardedReturn>,
        raises: Vec<GuardedRaise>,
        mut fall_through: Vec<Rc<Formula>>,
    ) -> Self::Output {
        let mut residual_raises = Vec::new();
        for raise in raises {
            match route_guarded_raise(&raise, &self.handlers, self.owner) {
                RaiseRoute::Unhandled(raise) => residual_raises.push(raise),
                RaiseRoute::Incomplete(effect) => return Outcome::Incomplete(effect),
                RaiseRoute::Handled(block) => {
                    guarded.extend(block.guarded);
                    residual_raises.extend(block.raises);
                    fall_through.extend(block.fall_through);
                }
            }
        }
        Outcome::Complete(Desugared::StmtBlock {
            guarded,
            raises: residual_raises,
            fall_through,
        })
    }

    fn visit_non_raise_route(self, floor: Desugared) -> Self::Output {
        Outcome::Incomplete(Effect::ControlFlow {
            boundary: format!(
                "{}: RouteRaisesOperation cannot route {}",
                self.owner,
                desugared_floor_name(&floor)
            ),
        })
    }
}

struct RoutedBlock {
    guarded: Vec<GuardedReturn>,
    raises: Vec<GuardedRaise>,
    fall_through: Vec<Rc<Formula>>,
}

enum RaiseRoute {
    Handled(RoutedBlock),
    Unhandled(GuardedRaise),
    Incomplete(Effect),
}

fn route_single_raise(
    raise: GuardedRaise,
    handlers: Vec<&dyn RouteRaiseHandler>,
    owner: &str,
) -> Outcome {
    match route_guarded_raise(&raise, &handlers, owner) {
        RaiseRoute::Handled(block) => Outcome::Complete(Desugared::StmtBlock {
            guarded: block.guarded,
            raises: block.raises,
            fall_through: block.fall_through,
        }),
        RaiseRoute::Unhandled(raise) => Outcome::Complete(Desugared::StmtGuardedRaise(raise)),
        RaiseRoute::Incomplete(effect) => Outcome::Incomplete(effect),
    }
}

fn route_guarded_raise(
    raise: &GuardedRaise,
    handlers: &[&dyn RouteRaiseHandler],
    owner: &str,
) -> RaiseRoute {
    let Some(handler) = handlers
        .iter()
        .find(|handler| handler.matches(raise.effect()))
    else {
        return RaiseRoute::Unhandled(raise.clone());
    };
    let outcome = handler.reduce(raise.effect());
    match outcome {
        Outcome::Incomplete(effect) => RaiseRoute::Incomplete(effect),
        Outcome::Complete(desugared) => {
            match guarded_statement_block(desugared, raise.guards(), owner) {
                Ok(block) => RaiseRoute::Handled(block),
                Err(effect) => RaiseRoute::Incomplete(effect),
            }
        }
    }
}

fn guarded_statement_block(
    desugared: Desugared,
    guards: &[Rc<Formula>],
    owner: &str,
) -> Result<RoutedBlock, Effect> {
    match desugared {
        Desugared::StmtBlock {
            guarded,
            raises,
            fall_through,
        } => {
            let (guarded, raises, fall_through) =
                guard_block(guarded, raises, fall_through, guards, "RouteRaises");
            Ok(RoutedBlock {
                guarded,
                raises,
                fall_through: guarded_fall_through(guards, fall_through),
            })
        }
        Desugared::StmtReturn(_) | Desugared::StmtGuarded(_) => Ok(RoutedBlock {
            guarded: vec![guard_exit(desugared, guards, "RouteRaises")],
            raises: Vec::new(),
            fall_through: Vec::new(),
        }),
        Desugared::StmtRaise(raise) => Ok(RoutedBlock {
            guarded: Vec::new(),
            raises: vec![GuardedRaise::from_raise(guards.to_vec(), raise)],
            fall_through: Vec::new(),
        }),
        Desugared::StmtGuardedRaise(raise) => Ok(RoutedBlock {
            guarded: Vec::new(),
            raises: vec![raise.with_prefix(guards)],
            fall_through: Vec::new(),
        }),
        other => Err(Effect::ControlFlow {
            boundary: format!(
                "{owner}: raise handler returned {}",
                desugared_floor_name(&other)
            ),
        }),
    }
}

fn guarded_fall_through(
    guards: &[Rc<Formula>],
    fall_through: Vec<Rc<Formula>>,
) -> Vec<Rc<Formula>> {
    if guards.is_empty() {
        return fall_through;
    }
    fall_through
        .into_iter()
        .map(|fall| {
            let mut conjuncts = guards.to_vec();
            conjuncts.push(fall);
            and_(conjuncts)
        })
        .collect()
}
