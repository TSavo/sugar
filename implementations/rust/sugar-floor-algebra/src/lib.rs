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
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RaiseEffect {
    Panic { boundary: String },
    ResultErr { boundary: String },
    EarlyReturn { boundary: String },
}

impl RaiseEffect {
    pub fn boundary(&self) -> &str {
        match self {
            Self::Panic { boundary }
            | Self::ResultErr { boundary }
            | Self::EarlyReturn { boundary } => boundary,
        }
    }

    pub fn family(&self) -> &'static str {
        match self {
            Self::Panic { .. } => "panic",
            Self::ResultErr { .. } => "result-err",
            Self::EarlyReturn { .. } => "early-return",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Effect {
    Raise(RaiseEffect),
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
