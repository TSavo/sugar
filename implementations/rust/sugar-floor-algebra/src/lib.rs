// SPDX-License-Identifier: Apache-2.0
//
// Shared floor algebra reachability crate.
//
// This crate is the Phase-4 boundary-collapse seam (#3192): it makes the
// algebra-side floor/operation world reachable from crates that must not depend
// on `sugar-lift-rust-tests`. The initial public surface is deliberately small:
// enough to cross the IrTerm boundary and drive ControlFlowGuardOperation
// without moving the source-lifter's crate-local factory state.

use std::rc::Rc;

use sugar_ir_symbolic::{Formula, Term};

pub mod control_flow_guard_operation;
pub mod guarded_raise;
pub mod guarded_return;
pub mod pattern_projection;
pub mod predicate_value;
pub mod raise_value;
pub mod route_raises_operation;
pub mod symbolic_value;
pub mod term_dispatch;

pub use control_flow_guard_operation::{
    guard_block, guard_exit, ControlFlowGuardAccept, ControlFlowGuardOperation,
    ControlFlowGuardVisitor,
};
pub use guarded_raise::GuardedRaise;
pub use guarded_return::{guarded_returns_to_formula, GuardedReturn};
pub use pattern_projection::{
    field_projection, index_projection, tuple_projection, tuple_struct_projection,
};
pub use predicate_value::PredicateValue;
pub use raise_value::{is_raise_like_effect, RaiseValue};
pub use route_raises_operation::{
    RouteRaiseHandler, RouteRaisesAccept, RouteRaisesOperation, RouteRaisesVisitor,
};
pub use symbolic_value::SymbolicValue;
pub use term_dispatch::{
    PredicateValueFloorAccept, PredicateValueFloorVisitor, RequiredPredicateValueVisitor,
    SymbolicValueFloorAccept, SymbolicValueFloorVisitor, TermFloorAccept, TermFloorVisitor,
};

/// Routeable raise-like control-flow effects.
///
/// Python's reference has a single `RaiseEffect` type. Rust keeps the existing
/// `PanicMacro`/`LiteralPanic`/`ControlFlow` siblings below for byte-compatible
/// legacy reasons, and uses this family for newly-typed raise cases such as
/// `Result::Err` and early-return routing.
#[derive(Clone, Debug)]
pub enum RaiseEffect {
    Panic { boundary: String },
    ResultErr { boundary: String },
    EarlyReturn { boundary: String },
    EarlyReturnValue { boundary: String, value: Rc<Term> },
}

impl RaiseEffect {
    pub fn boundary(&self) -> &str {
        match self {
            Self::Panic { boundary }
            | Self::ResultErr { boundary }
            | Self::EarlyReturn { boundary }
            | Self::EarlyReturnValue { boundary, .. } => boundary,
        }
    }

    pub fn family(&self) -> &'static str {
        match self {
            Self::Panic { .. } => "panic",
            Self::ResultErr { .. } => "result-err",
            Self::EarlyReturn { .. } | Self::EarlyReturnValue { .. } => "early-return",
        }
    }
}

impl PartialEq for RaiseEffect {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Panic { boundary: left }, Self::Panic { boundary: right })
            | (Self::ResultErr { boundary: left }, Self::ResultErr { boundary: right })
            | (Self::EarlyReturn { boundary: left }, Self::EarlyReturn { boundary: right }) => {
                left == right
            }
            (
                Self::EarlyReturnValue {
                    boundary: left_boundary,
                    value: left_value,
                },
                Self::EarlyReturnValue {
                    boundary: right_boundary,
                    value: right_value,
                },
            ) => left_boundary == right_boundary && Rc::ptr_eq(left_value, right_value),
            _ => false,
        }
    }
}

/// Runtime effects that are not routeable raises.
///
/// Python exposes `RuntimeEffect` as a typed sibling of `RaiseEffect` and
/// `CoverageGapEffect`; `_route_incomplete` propagates it unchanged. Rust uses
/// that shape for Drop/finally refusal corners: they are first-class data, but
/// not handler-consumable control-flow exits.
#[derive(Clone, Debug, PartialEq)]
pub enum RuntimeEffect {
    ObservableDrop { boundary: String, reason: String },
    FinallyOverIncomplete { boundary: String },
}

impl RuntimeEffect {
    pub fn boundary(&self) -> &str {
        match self {
            Self::ObservableDrop { boundary, .. } | Self::FinallyOverIncomplete { boundary } => {
                boundary
            }
        }
    }

    pub fn family(&self) -> &'static str {
        match self {
            Self::ObservableDrop { .. } => "drop",
            Self::FinallyOverIncomplete { .. } => "finally-over-incomplete",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Effect {
    Raise(RaiseEffect),
    Runtime(RuntimeEffect),
    PanicMacro { boundary: String },
    LiteralPanic { boundary: String },
    ControlFlow { boundary: String },
    CoverageGap { boundary: String, reason: String },
}

#[derive(Clone)]
pub enum Desugared {
    Term(Rc<Term>),
    SymbolicValue(SymbolicValue),
    PredicateValue(PredicateValue),
    StmtSupport,
    StmtReturn(Rc<Term>),
    StmtGuarded(GuardedReturn),
    StmtRaise(RaiseValue),
    StmtGuardedRaise(GuardedRaise),
    StmtBlock {
        guarded: Vec<GuardedReturn>,
        raises: Vec<GuardedRaise>,
        fall_through: Vec<Rc<Formula>>,
    },
}

impl Desugared {
    pub fn into_term(self) -> Option<Rc<Term>> {
        match self {
            Self::Term(term) => Some(term),
            _ => None,
        }
    }
}

pub enum Outcome {
    Complete(Desugared),
    Incomplete(Effect),
}

pub fn desugared_floor_name(desugared: &Desugared) -> &'static str {
    match desugared {
        Desugared::Term(_) => "Term",
        Desugared::SymbolicValue(_) => "SymbolicValue",
        Desugared::PredicateValue(_) => "PredicateValue",
        Desugared::StmtSupport => "StmtSupport",
        Desugared::StmtReturn(_) => "StmtReturn",
        Desugared::StmtGuarded(_) => "StmtGuarded",
        Desugared::StmtRaise(_) => "StmtRaise",
        Desugared::StmtGuardedRaise(_) => "StmtGuardedRaise",
        Desugared::StmtBlock { .. } => "StmtBlock",
    }
}
