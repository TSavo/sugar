// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Coq subprocess solver. Invokes `coqc` on a generated `.v` file.
//
// Unlike SMT solvers that read scripts from stdin and return
// "unsat"/"sat", Coq reads from a file and returns success via
// exit code. A successful compilation means the proof is complete.
//
// Workflow:
//   1. Compile IR-JSON to Coq syntax
//   2. Write to temp .v file
//   3. Spawn `coqc <file>`
//   4. Exit 0 → Discharged (proof holds)
//   5. Exit non-zero → Undecidable (proof incomplete or error)

use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use sugar_ir_compiler_coq::DIALECT;

use crate::solvers::registry::format_timeout;
use crate::solvers::{SolveResult, Solver, SolverExitKind, SolverExitMetadata, SolverIdentity};
use crate::types::ObligationVerdict;

#[derive(Debug)]
pub struct CoqSubprocessSolver {
    name: String,
    version: String,
    binary: String,
    timeout: Option<Duration>,
    identity: SolverIdentity,
}

impl CoqSubprocessSolver {
    pub fn new(
        name: impl Into<String>,
        binary: impl Into<String>,
        version: impl Into<String>,
        timeout: Option<Duration>,
    ) -> Self {
        Self {
            name: name.into(),
            version: version.into(),
            binary: binary.into(),
            timeout,
            identity: SolverIdentity::default(),
        }
    }

    pub fn with_identity(mut self, identity: SolverIdentity) -> Self {
        self.identity = identity;
        self
    }
}

impl Solver for CoqSubprocessSolver {
    fn name(&self) -> &str {
        &self.name
    }
    fn version(&self) -> &str {
        &self.version
    }
    fn ir_compiler(&self) -> &str {
        DIALECT
    }

    fn identity(&self) -> SolverIdentity {
        self.identity.clone()
    }

    fn solve(&self, coq_source: &str) -> SolveResult {
        let started = Instant::now();

        // Write to temp file
        let tmp_dir = std::env::temp_dir().join(format!(
            "sugar-coq-{}-{}",
            std::process::id(),
            started.elapsed().as_nanos()
        ));
        if let Err(e) = std::fs::create_dir_all(&tmp_dir) {
            return SolveResult::with_evidence(
                ObligationVerdict::Undecidable,
                self.name.clone(),
                self.version.clone(),
                SolverExitMetadata::new(SolverExitKind::CompileError),
                Some(format!("coq: failed to create temp dir: {e}")),
                None,
                None,
                started.elapsed(),
                false,
            );
        }

        let v_file = tmp_dir.join("proof.v");
        if let Err(e) = std::fs::write(&v_file, coq_source) {
            return SolveResult::with_evidence(
                ObligationVerdict::Undecidable,
                self.name.clone(),
                self.version.clone(),
                SolverExitMetadata::new(SolverExitKind::CompileError),
                Some(format!("coq: failed to write .v file: {e}")),
                None,
                None,
                started.elapsed(),
                false,
            );
        }

        // Spawn coqc
        let mut cmd = Command::new(&self.binary);
        cmd.arg("-q"); // quiet
        cmd.arg("-w").arg("-all"); // suppress warnings
        cmd.arg(&v_file);
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());
        // Set working dir so coqc can resolve relative imports
        cmd.current_dir(&tmp_dir);

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                return SolveResult::with_evidence(
                    ObligationVerdict::Undecidable,
                    self.name.clone(),
                    self.version.clone(),
                    SolverExitMetadata::new(SolverExitKind::SpawnError),
                    Some(format!("coq: spawn {}: {e}", self.binary)),
                    None,
                    None,
                    started.elapsed(),
                    false,
                );
            }
        };

        // Timeout handling
        let (output, timed_out) = if let Some(to) = self.timeout {
            let deadline = started + to;
            let result = loop {
                match child.try_wait() {
                    Ok(Some(_status)) => {
                        break child.wait_with_output();
                    }
                    Ok(None) => {
                        if Instant::now() >= deadline {
                            let _ = child.kill();
                            let _ = child.wait();
                            let _ = std::fs::remove_dir_all(&tmp_dir);
                            return SolveResult::with_evidence(
                                ObligationVerdict::SolverTimeout,
                                self.name.clone(),
                                self.version.clone(),
                                SolverExitMetadata::new(SolverExitKind::Timeout),
                                Some(format!("coq: timeout after {}", format_timeout(Some(to)))),
                                None,
                                None,
                                started.elapsed(),
                                true,
                            );
                        }
                        std::thread::sleep(Duration::from_millis(20));
                    }
                    Err(e) => {
                        let _ = std::fs::remove_dir_all(&tmp_dir);
                        return SolveResult::with_evidence(
                            ObligationVerdict::Undecidable,
                            self.name.clone(),
                            self.version.clone(),
                            SolverExitMetadata::new(SolverExitKind::WaitError),
                            Some(format!("coq: wait error: {e}")),
                            None,
                            None,
                            started.elapsed(),
                            false,
                        );
                    }
                }
            };
            (result, false)
        } else {
            // No timeout, just wait
            (child.wait_with_output(), false)
        };

        let output = match output {
            Ok(o) => o,
            Err(e) => {
                let _ = std::fs::remove_dir_all(&tmp_dir);
                return SolveResult::with_evidence(
                    ObligationVerdict::Undecidable,
                    self.name.clone(),
                    self.version.clone(),
                    SolverExitMetadata::new(SolverExitKind::WaitError),
                    Some(format!("coq: wait error: {e}")),
                    None,
                    None,
                    started.elapsed(),
                    timed_out,
                );
            }
        };
        let _ = std::fs::remove_dir_all(&tmp_dir);

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let verdict = if output.status.success() {
            ObligationVerdict::Discharged
        } else {
            ObligationVerdict::Undecidable
        };

        let diagnostic = (!output.status.success())
            .then(|| format!("coqc exited with code {:?}", output.status.code()));
        SolveResult::with_evidence(
            verdict,
            self.name.clone(),
            self.version.clone(),
            SolverExitMetadata::new(if output.status.success() {
                SolverExitKind::Ok
            } else {
                SolverExitKind::NonZeroExit
            })
            .with_code(output.status.code()),
            diagnostic,
            Some(stdout),
            (!stderr.is_empty()).then_some(stderr),
            started.elapsed(),
            timed_out,
        )
    }
}
