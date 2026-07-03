// SPDX-License-Identifier: Apache-2.0
//
// Stage 6: solve_obligation.
//
// HISTORICAL: this module used to spawn `z3` directly. The
// multi-solver upgrade (spec
// `protocol/specs/2026-04-30-multi-solver-protocol.md`) generalized
// the solver layer into `sugar_verifier::solvers`. This module is
// preserved as the back-compat shim used by existing examples and
// integration tests that pass a single Z3 binary path.
//
// New code should construct a SolverPlan + Registry and call
// `solvers::run_plan` directly.

use crate::solvers::{Solver, SubprocessSolver};
use crate::types::ObligationVerdict;

/// Legacy single-shot result type. Preserved verbatim so existing
/// callers (and the round-trip examples) keep compiling.
#[derive(Debug, Clone)]
pub struct SolveResult {
    pub verdict: ObligationVerdict,
    pub error: String,
    pub solver_stdout: String,
}

/// Legacy entry point: invoke a single Z3 SubprocessSolver. The
/// multi-solver runner does NOT route through here; it builds a
/// registry from `.sugar/config.toml` and calls `solvers::run_plan`.
pub fn run(z3_path: &str, smt_script: &str) -> SolveResult {
    let solver = SubprocessSolver::new(
        "z3",
        z3_path,
        "4.x",
        "smt-lib-v2.6",
        vec!["-smt2".into(), "-in".into()],
        // Legacy callers had no timeout; preserve that exactly.
        None,
    );
    let r = solver.solve(smt_script);
    SolveResult {
        verdict: r.verdict,
        error: r.error().to_string(),
        solver_stdout: r.solver_stdout().to_string(),
    }
}
