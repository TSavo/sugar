// SPDX-License-Identifier: Apache-2.0
//
// Stub solver. Returns a hard-coded verdict after an optional sleep.
// Used by the multi-solver demo so CI can exercise every mode without
// any solver binary installed, and by unit tests that need
// deterministic timing or known disagreements.
//
// Wired in via `binary = "stub:unsat"` / `"stub:sat"` /
// `"stub:undecidable"` / `"stub:timeout"` in `.sugar/config.toml`.

use std::time::{Duration, Instant};

use crate::solvers::{SolveResult, Solver, SolverIdentity};
use crate::types::ObligationVerdict;

#[derive(Debug, Clone)]
pub struct StubSolver {
    name: String,
    version: String,
    ir_compiler: String,
    verdict: ObligationVerdict,
    delay: Duration,
    timed_out: bool,
    identity: SolverIdentity,
}

impl StubSolver {
    pub fn new(name: impl Into<String>, verdict: ObligationVerdict) -> Self {
        Self {
            name: name.into(),
            version: "stub-0".into(),
            ir_compiler: "smt-lib-v2.6".into(),
            verdict,
            delay: Duration::from_millis(0),
            timed_out: false,
            identity: SolverIdentity::default(),
        }
    }
    pub fn with_version(mut self, v: impl Into<String>) -> Self {
        self.version = v.into();
        self
    }
    pub fn with_delay(mut self, d: Duration) -> Self {
        self.delay = d;
        self
    }
    pub fn with_timed_out(mut self, t: bool) -> Self {
        self.timed_out = t;
        self
    }
    pub fn with_identity(mut self, identity: SolverIdentity) -> Self {
        self.identity = identity;
        self
    }

    /// Parse `binary` shorthand. Returns `Some` when `binary` matches
    /// the `stub:<verdict>` form. Used by the registry builder to
    /// replace SubprocessSolver with a StubSolver for fixture configs.
    ///
    /// Note: stub solvers built via this path always emit a synthetic
    /// version string `stub-<verdict>` and ignore the configured
    /// `version` field on SolverConfig. Tests that need an explicit
    /// version should construct a StubSolver manually via
    /// `StubSolver::new(...).with_version("...")`.
    pub fn from_binary(name: &str, binary: &str) -> Option<Self> {
        let suffix = binary.strip_prefix("stub:")?;
        let (verdict, timed_out) = match suffix {
            "unsat" => (ObligationVerdict::Discharged, false),
            "sat" => (ObligationVerdict::Unsatisfied, false),
            "undecidable" => (ObligationVerdict::Undecidable, false),
            "timeout" => (ObligationVerdict::Undecidable, true),
            "disagreement" => (ObligationVerdict::Disagreement, false),
            _ => return None,
        };
        Some(Self {
            name: name.to_string(),
            version: format!("stub-{suffix}"),
            ir_compiler: "smt-lib-v2.6".into(),
            verdict,
            delay: Duration::from_millis(0),
            timed_out,
            identity: SolverIdentity::default(),
        })
    }
}

impl Solver for StubSolver {
    fn name(&self) -> &str {
        &self.name
    }
    fn version(&self) -> &str {
        &self.version
    }
    fn ir_compiler(&self) -> &str {
        &self.ir_compiler
    }
    fn identity(&self) -> SolverIdentity {
        self.identity.clone()
    }
    fn solve(&self, _smt: &str) -> SolveResult {
        let started = Instant::now();
        if !self.delay.is_zero() {
            std::thread::sleep(self.delay);
        }
        SolveResult {
            verdict: self.verdict,
            solver_name: self.name.clone(),
            solver_version: self.version.clone(),
            error: if self.timed_out {
                "stub: timeout".into()
            } else {
                String::new()
            },
            solver_stdout: format!(
                "{}\n",
                match self.verdict {
                    ObligationVerdict::Discharged => "unsat",
                    ObligationVerdict::Unsatisfied => "sat",
                    ObligationVerdict::Undecidable => "unknown",
                    ObligationVerdict::Disagreement => "disagreement",
                    ObligationVerdict::Refused => "refused",
                }
            ),
            wall_clock: started.elapsed(),
            timed_out: self.timed_out,
        }
    }
}
