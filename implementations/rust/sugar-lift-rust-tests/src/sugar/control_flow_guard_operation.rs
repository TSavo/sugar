// SPDX-License-Identifier: Apache-2.0
//
// ControlFlowGuardOperation: algebra-side guard composition for statement exits.
//
// Python reference:
// `operations/control_flow_guard_operation.py` dispatches over `BlockValue` and
// prefixes `ReturnValue` / `GuardedReturn` exits with branch guards. Rust keeps
// that mechanism as a closed visitor over `Desugared` statement floors instead
// of Python's runtime `perform_operation` reflection.
//
// Deliberate seam: this module consumes `Rc<Formula>` guards and `Rc<Term>`
// statement floors. It does NOT cross into `sugar-walk`'s `IrTerm` branch-guard
// construction (`wrap_branch_guard`); the campaign plan reserves that type
// convergence / generated-dispatch decision for Phase 4.

use std::rc::Rc;

use sugar_ir_symbolic::{Formula, Term};

use crate::sugar::guarded_return::GuardedReturn;
use crate::{Desugared, Outcome};

pub(crate) trait ControlFlowGuardVisitor {
    type Output;

    fn visit_stmt_return(self, term: Rc<Term>) -> Self::Output;
    fn visit_stmt_guarded(self, guarded_return: GuardedReturn) -> Self::Output;
    fn visit_stmt_block(
        self,
        guarded: Vec<GuardedReturn>,
        fall_through: Vec<Rc<Formula>>,
    ) -> Self::Output;
    fn visit_non_control_flow(self, floor: Desugared) -> Self::Output;
}

pub(crate) trait ControlFlowGuardAccept {
    fn accept_control_flow_guard<V: ControlFlowGuardVisitor>(self, visitor: V) -> V::Output;
}

impl ControlFlowGuardAccept for Desugared {
    fn accept_control_flow_guard<V: ControlFlowGuardVisitor>(self, visitor: V) -> V::Output {
        match self {
            Desugared::StmtReturn(term) => visitor.visit_stmt_return(term),
            Desugared::StmtGuarded(guarded_return) => visitor.visit_stmt_guarded(guarded_return),
            Desugared::StmtBlock {
                guarded,
                fall_through,
            } => visitor.visit_stmt_block(guarded, fall_through),
            other => visitor.visit_non_control_flow(other),
        }
    }
}

pub(crate) struct ControlFlowGuardOperation<'a> {
    guards: Vec<Rc<Formula>>,
    owner: &'a str,
}

impl<'a> ControlFlowGuardOperation<'a> {
    pub(crate) fn new(guards: Vec<Rc<Formula>>, owner: &'a str) -> Self {
        Self { guards, owner }
    }
}

impl ControlFlowGuardVisitor for ControlFlowGuardOperation<'_> {
    type Output = Outcome;

    fn visit_stmt_return(self, term: Rc<Term>) -> Self::Output {
        if self.guards.is_empty() {
            Outcome::Complete(Desugared::StmtReturn(term))
        } else {
            Outcome::Complete(Desugared::StmtGuarded(GuardedReturn::new(
                self.guards,
                term,
            )))
        }
    }

    fn visit_stmt_guarded(self, guarded_return: GuardedReturn) -> Self::Output {
        let guarded_return = if self.guards.is_empty() {
            guarded_return
        } else {
            guarded_return.with_prefix(&self.guards)
        };
        Outcome::Complete(Desugared::StmtGuarded(guarded_return))
    }

    fn visit_stmt_block(
        self,
        guarded: Vec<GuardedReturn>,
        fall_through: Vec<Rc<Formula>>,
    ) -> Self::Output {
        let guarded = if self.guards.is_empty() {
            guarded
        } else {
            guarded
                .into_iter()
                .map(|guarded_return| guarded_return.with_prefix(&self.guards))
                .collect()
        };
        Outcome::Complete(Desugared::StmtBlock {
            guarded,
            fall_through,
        })
    }

    fn visit_non_control_flow(self, floor: Desugared) -> Self::Output {
        panic!(
            "{}: write more ControlFlowGuardOperation for `{}`",
            self.owner,
            desugared_floor_name(&floor)
        )
    }
}

pub(crate) fn guard_exit(
    statement: Desugared,
    guards: &[Rc<Formula>],
    owner: &'static str,
) -> GuardedReturn {
    let outcome =
        statement.accept_control_flow_guard(ControlFlowGuardOperation::new(guards.to_vec(), owner));
    match complete_guard_operation(outcome, owner) {
        Desugared::StmtReturn(term) => GuardedReturn::new(Vec::new(), term),
        Desugared::StmtGuarded(guarded_return) => guarded_return,
        other => guard_operation_gap(owner, "single exit", &other),
    }
}

pub(crate) fn guard_block(
    guarded: Vec<GuardedReturn>,
    fall_through: Vec<Rc<Formula>>,
    guards: &[Rc<Formula>],
    owner: &'static str,
) -> (Vec<GuardedReturn>, Vec<Rc<Formula>>) {
    let outcome = Desugared::StmtBlock {
        guarded,
        fall_through,
    }
    .accept_control_flow_guard(ControlFlowGuardOperation::new(guards.to_vec(), owner));
    match complete_guard_operation(outcome, owner) {
        Desugared::StmtBlock {
            guarded,
            fall_through,
        } => (guarded, fall_through),
        other => guard_operation_gap(owner, "block", &other),
    }
}

fn complete_guard_operation(outcome: Outcome, owner: &'static str) -> Desugared {
    match outcome {
        Outcome::Complete(desugared) => desugared,
        Outcome::Incomplete(effect) => {
            panic!("{owner}: ControlFlowGuardOperation returned Incomplete({effect:?})")
        }
    }
}

fn guard_operation_gap(owner: &str, expected: &str, actual: &Desugared) -> ! {
    panic!(
        "{owner}: ControlFlowGuardOperation produced {} where {expected} was required",
        desugared_floor_name(actual)
    )
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
        Desugared::StmtSupport => "StmtSupport",
        Desugared::StmtBound(_) => "StmtBound",
        Desugared::StmtReturn(_) => "StmtReturn",
        Desugared::StmtGuarded(_) => "StmtGuarded",
        Desugared::StmtBlock { .. } => "StmtBlock",
    }
}
