// SPDX-License-Identifier: Apache-2.0
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

use serde_json::Value as Json;
use sugar_ir_compiler::IrCompiler;
use sugar_ir_compiler_coq::{CoqCompiler, DIALECT};

use crate::solvers::{SolveResult, Solver, SolverIdentity};
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

    fn solve(&self, smt: &str) -> SolveResult {
        let started = Instant::now();

        // Parse the input as IR-JSON (not SMT-LIB)
        let ir: Json = match serde_json::from_str(smt) {
            Ok(j) => j,
            Err(e) => {
                return SolveResult {
                    verdict: ObligationVerdict::Undecidable,
                    solver_name: self.name.clone(),
                    solver_version: self.version.clone(),
                    error: format!("coq: failed to parse IR-JSON: {e}"),
                    solver_stdout: String::new(),
                    wall_clock: started.elapsed(),
                    timed_out: false,
                };
            }
        };

        // Compile IR to Coq syntax
        let compiler = CoqCompiler::new();
        let compiled = match compiler.compile(&ir, DIALECT) {
            Ok(c) => c,
            Err(e) => {
                return SolveResult {
                    verdict: ObligationVerdict::Undecidable,
                    solver_name: self.name.clone(),
                    solver_version: self.version.clone(),
                    error: format!("coq: compilation error: {e}"),
                    solver_stdout: String::new(),
                    wall_clock: started.elapsed(),
                    timed_out: false,
                };
            }
        };

        // Write to temp file
        let tmp_dir = std::env::temp_dir().join(format!(
            "sugar-coq-{}-{}",
            std::process::id(),
            started.elapsed().as_nanos()
        ));
        if let Err(e) = std::fs::create_dir_all(&tmp_dir) {
            return SolveResult {
                verdict: ObligationVerdict::Undecidable,
                solver_name: self.name.clone(),
                solver_version: self.version.clone(),
                error: format!("coq: failed to create temp dir: {e}"),
                solver_stdout: String::new(),
                wall_clock: started.elapsed(),
                timed_out: false,
            };
        }

        let v_file = tmp_dir.join("proof.v");
        let full_source = format!("{}\n{}", compiled.preamble, compiled.body);
        if let Err(e) = std::fs::write(&v_file, full_source) {
            return SolveResult {
                verdict: ObligationVerdict::Undecidable,
                solver_name: self.name.clone(),
                solver_version: self.version.clone(),
                error: format!("coq: failed to write .v file: {e}"),
                solver_stdout: String::new(),
                wall_clock: started.elapsed(),
                timed_out: false,
            };
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
                return SolveResult {
                    verdict: ObligationVerdict::Undecidable,
                    solver_name: self.name.clone(),
                    solver_version: self.version.clone(),
                    error: format!("coq: spawn {}: {e}", self.binary),
                    solver_stdout: String::new(),
                    wall_clock: started.elapsed(),
                    timed_out: false,
                };
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
                            return SolveResult {
                                verdict: ObligationVerdict::Undecidable,
                                solver_name: self.name.clone(),
                                solver_version: self.version.clone(),
                                error: format!("coq: timeout after {}s", to.as_secs().max(1)),
                                solver_stdout: String::new(),
                                wall_clock: started.elapsed(),
                                timed_out: true,
                            };
                        }
                        std::thread::sleep(Duration::from_millis(20));
                    }
                    Err(e) => {
                        let _ = std::fs::remove_dir_all(&tmp_dir);
                        return SolveResult {
                            verdict: ObligationVerdict::Undecidable,
                            solver_name: self.name.clone(),
                            solver_version: self.version.clone(),
                            error: format!("coq: wait error: {e}"),
                            solver_stdout: String::new(),
                            wall_clock: started.elapsed(),
                            timed_out: false,
                        };
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
                return SolveResult {
                    verdict: ObligationVerdict::Undecidable,
                    solver_name: self.name.clone(),
                    solver_version: self.version.clone(),
                    error: format!("coq: wait error: {e}"),
                    solver_stdout: String::new(),
                    wall_clock: started.elapsed(),
                    timed_out,
                };
            }
        };
        let _ = std::fs::remove_dir_all(&tmp_dir);

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let verdict = if output.status.success() {
            ObligationVerdict::Discharged
        } else {
            ObligationVerdict::Undecidable
        };

        SolveResult {
            verdict,
            solver_name: self.name.clone(),
            solver_version: self.version.clone(),
            error: if output.status.success() {
                String::new()
            } else {
                format!("coqc exited with code {:?}", output.status.code())
            },
            solver_stdout: stdout,
            wall_clock: started.elapsed(),
            timed_out,
        }
    }
}
