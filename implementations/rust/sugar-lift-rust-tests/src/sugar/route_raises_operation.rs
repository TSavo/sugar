// SPDX-License-Identifier: MIT OR Apache-2.0
//
// RouteRaisesOperation: algebra-side routing for block-interior raise exits.
//
// Python reference: `operations/route_raises_operation.py` dispatches over a
// BlockValue, recognizes RaiseValue/GuardedRaise statements, and asks handlers
// whether they match. Rust keeps this as a closed visitor over `Desugared`
// statement floors. This slice deliberately builds only the algebra/mechanism;
// Phase 2 wires Rust `?`/panic/TrySugar-equivalent consumers into it.

use std::rc::Rc;

use sugar_ir_symbolic::{and_, Formula};

use crate::sugar::control_flow_guard_operation::{guard_block, guard_exit};
use crate::sugar::guarded_raise::GuardedRaise;
use crate::sugar::raise_value::{is_raise_like_effect, RaiseValue};
use crate::{Desugared, Effect, Outcome, TemporalScope};

pub(crate) trait RouteRaiseHandler {
    fn matches(&self, effect: &Effect) -> bool;
    fn reduce(&self, scope: &TemporalScope, effect: &Effect) -> Outcome;
}

pub(crate) trait RouteRaisesVisitor {
    type Output;

    fn visit_stmt_raise(self, raise: RaiseValue) -> Self::Output;
    fn visit_stmt_guarded_raise(self, guarded_raise: GuardedRaise) -> Self::Output;
    fn visit_stmt_block(
        self,
        guarded: Vec<crate::sugar::guarded_return::GuardedReturn>,
        raises: Vec<GuardedRaise>,
        fall_through: Vec<Rc<Formula>>,
    ) -> Self::Output;
    fn visit_non_raise_route(self, floor: Desugared) -> Self::Output;
}

pub(crate) trait RouteRaisesAccept {
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

pub(crate) struct RouteRaisesOperation<'a> {
    handlers: Vec<&'a dyn RouteRaiseHandler>,
    owner: &'a str,
}

impl<'a> RouteRaisesOperation<'a> {
    pub(crate) fn new(handlers: Vec<&'a dyn RouteRaiseHandler>, owner: &'a str) -> Self {
        Self { handlers, owner }
    }

    pub(crate) fn route_incomplete_with_scope(
        self,
        outcome: Outcome,
        scope: &TemporalScope,
    ) -> Outcome {
        let Outcome::Incomplete(effect) = outcome else {
            return outcome;
        };
        if !is_raise_like_effect(&effect) {
            return Outcome::Incomplete(effect);
        }
        for handler in &self.handlers {
            if handler.matches(&effect) {
                return handler.reduce(scope, &effect);
            }
        }
        Outcome::Incomplete(effect)
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
        mut guarded: Vec<crate::sugar::guarded_return::GuardedReturn>,
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
    guarded: Vec<crate::sugar::guarded_return::GuardedReturn>,
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
    let outcome = handler.reduce(raise.scope(), raise.effect());
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

fn desugared_floor_name(desugared: &Desugared) -> &'static str {
    match desugared {
        Desugared::Seq(_) => "Seq",
        Desugared::TermSeq(_) => "TermSeq",
        Desugared::Constraints { .. } => "Constraints",
        Desugared::Term(_) => "Term",
        Desugared::LiteralString(_) => "LiteralString",
        Desugared::LiteralCStr(_) => "LiteralCStr",
        Desugared::FormatValue(_) => "FormatValue",
        Desugared::TupleComponents(_) => "TupleComponents",
        Desugared::PredicateValue(_) => "PredicateValue",
        Desugared::StmtSupport => "StmtSupport",
        Desugared::StmtBound(_) => "StmtBound",
        Desugared::StmtReturn(_) => "StmtReturn",
        Desugared::StmtGuarded(_) => "StmtGuarded",
        Desugared::StmtRaise(_) => "StmtRaise",
        Desugared::StmtGuardedRaise(_) => "StmtGuardedRaise",
        Desugared::StmtBlock { .. } => "StmtBlock",
    }
}

#[cfg(test)]
mod tests {
    use sugar_ir_symbolic::{atomic_, num};

    use super::*;
    use crate::sugar::raise_value::RaiseValue;
    use crate::{RaiseEffect, TemporalPlan, TemporalScope};

    struct PanicHandler;

    impl RouteRaiseHandler for PanicHandler {
        fn matches(&self, effect: &Effect) -> bool {
            matches!(effect, Effect::PanicMacro { .. })
        }

        fn reduce(&self, _scope: &TemporalScope, _effect: &Effect) -> Outcome {
            Outcome::Complete(Desugared::StmtReturn(num(99)))
        }
    }

    fn panic_raise(guards: Vec<Rc<Formula>>) -> GuardedRaise {
        GuardedRaise::from_raise(
            guards,
            RaiseValue::new(
                Effect::PanicMacro {
                    boundary: "panic!()".to_string(),
                },
                TemporalScope::new("route-raise-test", TemporalPlan::default()),
            ),
        )
    }

    fn result_err_raise(guards: Vec<Rc<Formula>>) -> GuardedRaise {
        GuardedRaise::from_raise(
            guards,
            RaiseValue::new(
                Effect::Raise(RaiseEffect::ResultErr {
                    boundary: "fallible()?".to_string(),
                }),
                TemporalScope::new("route-result-err-test", TemporalPlan::default()),
            ),
        )
    }

    struct ResultErrHandler;

    impl RouteRaiseHandler for ResultErrHandler {
        fn matches(&self, effect: &Effect) -> bool {
            matches!(effect, Effect::Raise(RaiseEffect::ResultErr { .. }))
        }

        fn reduce(&self, _scope: &TemporalScope, _effect: &Effect) -> Outcome {
            Outcome::Complete(Desugared::StmtReturn(num(7)))
        }
    }

    #[test]
    fn route_raises_operation_routes_guarded_raise_with_handler() {
        let guard = atomic_("guard", vec![]);
        let handler = PanicHandler;
        let outcome = Desugared::StmtBlock {
            guarded: Vec::new(),
            raises: vec![panic_raise(vec![guard.clone()])],
            fall_through: Vec::new(),
        }
        .accept_route_raises(RouteRaisesOperation::new(vec![&handler], "test"));

        let Outcome::Complete(Desugared::StmtBlock {
            guarded,
            raises,
            fall_through,
        }) = outcome
        else {
            panic!("expected routed block");
        };
        assert_eq!(guarded.len(), 1);
        assert_eq!(guarded[0].guards.len(), 1);
        assert!(Rc::ptr_eq(&guarded[0].guards[0], &guard));
        assert!(raises.is_empty(), "handled raise must not remain residual");
        assert!(fall_through.is_empty());
    }

    #[test]
    fn route_raises_operation_accepts_typed_result_err_raise_effect() {
        let guard = atomic_("result_guard", vec![]);
        let handler = ResultErrHandler;
        let outcome = Desugared::StmtBlock {
            guarded: Vec::new(),
            raises: vec![result_err_raise(vec![guard.clone()])],
            fall_through: Vec::new(),
        }
        .accept_route_raises(RouteRaisesOperation::new(vec![&handler], "test"));

        let Outcome::Complete(Desugared::StmtBlock {
            guarded,
            raises,
            fall_through,
        }) = outcome
        else {
            panic!("expected routed block");
        };
        assert_eq!(guarded.len(), 1);
        assert_eq!(guarded[0].guards.len(), 1);
        assert!(Rc::ptr_eq(&guarded[0].guards[0], &guard));
        assert!(
            raises.is_empty(),
            "handled Result::Err raise must not remain residual"
        );
        assert!(fall_through.is_empty());
    }

    #[test]
    fn route_raises_operation_leaves_unhandled_raise_as_data() {
        let guard = atomic_("guard", vec![]);
        let outcome = Desugared::StmtBlock {
            guarded: Vec::new(),
            raises: vec![panic_raise(vec![guard.clone()])],
            fall_through: Vec::new(),
        }
        .accept_route_raises(RouteRaisesOperation::new(Vec::new(), "test"));

        let Outcome::Complete(Desugared::StmtBlock { raises, .. }) = outcome else {
            panic!("expected residual raise block");
        };
        assert_eq!(raises.len(), 1);
        assert_eq!(raises[0].guards().len(), 1);
        assert!(Rc::ptr_eq(&raises[0].guards()[0], &guard));
    }

    #[test]
    fn route_raises_operation_propagates_coverage_gap_unchanged() {
        let effect = Effect::CoverageGap {
            reason: "open plugin floor has no handler".to_string(),
        };
        let scope = TemporalScope::new("runtime-drop-test", TemporalPlan::default());
        let handler = PanicHandler;
        let routed = RouteRaisesOperation::new(vec![&handler], "test")
            .route_incomplete_with_scope(Outcome::Incomplete(effect.clone()), &scope);

        let Outcome::Incomplete(Effect::CoverageGap { reason }) = routed else {
            panic!("CoverageGap must propagate unchanged");
        };
        assert_eq!(reason, "open plugin floor has no handler");
    }

    #[test]
    fn route_raises_operation_prefixes_nested_guarded_raise() {
        struct ReRaiseHandler;
        impl RouteRaiseHandler for ReRaiseHandler {
            fn matches(&self, effect: &Effect) -> bool {
                matches!(effect, Effect::PanicMacro { .. })
            }

            fn reduce(&self, scope: &TemporalScope, _effect: &Effect) -> Outcome {
                Outcome::Complete(Desugared::StmtGuardedRaise(GuardedRaise::from_raise(
                    vec![atomic_("inner", vec![])],
                    RaiseValue::new(
                        Effect::PanicMacro {
                            boundary: "reraised".to_string(),
                        },
                        scope.clone(),
                    ),
                )))
            }
        }

        let outer = atomic_("outer", vec![]);
        let handler = ReRaiseHandler;
        let outcome = Desugared::StmtBlock {
            guarded: Vec::new(),
            raises: vec![panic_raise(vec![outer.clone()])],
            fall_through: Vec::new(),
        }
        .accept_route_raises(RouteRaisesOperation::new(vec![&handler], "test"));

        let Outcome::Complete(Desugared::StmtBlock { raises, .. }) = outcome else {
            panic!("expected block with reraised residual");
        };
        assert_eq!(raises.len(), 1);
        assert_eq!(raises[0].guards().len(), 2);
        assert!(Rc::ptr_eq(&raises[0].guards()[0], &outer));
    }
}
