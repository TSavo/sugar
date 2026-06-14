// SPDX-License-Identifier: Apache-2.0
//
// Multi-solver subsystem for the verifier.
//
// Replaces the previous one-shot Z3 subprocess invocation with a
// pluggable Solver trait. Three concrete impls ship in-tree:
//
//   * SubprocessSolver  - generic SMT-LIB v2.6 subprocess driver
//                         (Z3, cvc5, bitwuzla, MathSAT, ...).
//   * StubSolver        - deterministic verdict + optional delay,
//                         used by tests and by the multi-solver demo
//                         so CI passes without any solver binaries
//                         installed.
//
// Composition over solvers is expressed by `SolverPlan`, derived from
// `.sugar/config.toml` (see `config.rs`). The plan is one of:
//
//   * Single (default)            - invoke one solver.
//   * Chain                       - sequential fall-through; first
//                                   definitive verdict wins.
//   * Portfolio { first-wins }    - parallel via rayon; first
//                                   definitive verdict wins; remaining
//                                   solvers are best-effort cancelled.
//   * Portfolio { consensus }     - parallel via rayon; ALL definitive
//                                   verdicts must agree, otherwise
//                                   `ObligationVerdict::Disagreement`
//                                   is reported and a "verdict-
//                                   disagreement" event is logged.
//   * Dispatch                    - inspect the formula and pick the
//                                   matching solver for that fragment.

pub mod batch;
pub mod ceta;
pub mod config;
pub mod coq;
pub mod dispatch;
pub mod lean;
pub mod maude;
pub mod model;
pub mod plan;
pub mod registry;
pub mod stub;
pub mod subprocess;

use std::sync::Arc;
use std::time::Duration;

use crate::types::ObligationVerdict;

/// A single solver invocation outcome.
#[derive(Debug, Clone)]
pub struct SolveResult {
    pub verdict: ObligationVerdict,
    pub solver_name: String,
    pub solver_version: String,
    pub error: String,
    pub solver_stdout: String,
    pub wall_clock: Duration,
    pub timed_out: bool,
}

impl SolveResult {
    pub fn definitive(&self) -> bool {
        matches!(
            self.verdict,
            ObligationVerdict::Discharged | ObligationVerdict::Unsatisfied
        )
    }
}

/// Solver abstraction. Implementors run an SMT-LIB v2.6 script and
/// return a `SolveResult`. They MUST be `Send + Sync` so the rayon
/// portfolio can fan them out across threads.
pub trait Solver: Send + Sync {
    fn name(&self) -> &str;
    fn version(&self) -> &str;
    fn ir_compiler(&self) -> &str;
    fn solve(&self, smt: &str) -> SolveResult;
}

/// Convenience type alias: trait objects come through the registry as
/// shared, cheaply-clonable handles.
pub type SolverHandle = Arc<dyn Solver>;

pub use ceta::{CetaGate, CetaGateConfig};
pub use config::{DispatchConfig, PortfolioMode, SolverConfig, SolverPlan, SolversConfig};
pub use coq::CoqSubprocessSolver;
pub use dispatch::{classify, dispatch_for_formula, FormulaTheory};
pub use lean::LeanSubprocessSolver;
pub use maude::MaudeSubprocessSolver;
pub use plan::{run_plan, SolverInvocation};
pub use stub::StubSolver;
pub use subprocess::SubprocessSolver;
