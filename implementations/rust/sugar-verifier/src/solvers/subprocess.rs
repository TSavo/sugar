// SPDX-License-Identifier: Apache-2.0
//
// Subprocess solver. Generic SMT-LIB v2.6 driver: pipe the script to
// `<binary> [flags...]` on stdin, read the first non-empty stdout line,
// map it to ObligationVerdict.
//
// Replaces the old `solve_obligation::run` Z3-only path. That legacy
// path remains as a back-compat shim for callers that still pass a
// single Z3 binary path.

use std::io::Write;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crate::solvers::{SolveResult, Solver, SolverExitKind, SolverExitMetadata, SolverIdentity};
use crate::types::ObligationVerdict;

#[derive(Debug, Clone)]
pub struct SubprocessSolver {
    name: String,
    version: String,
    ir_compiler: String,
    binary: String,
    flags: Vec<String>,
    timeout: Option<Duration>,
    identity: SolverIdentity,
}

impl SubprocessSolver {
    pub fn new(
        name: impl Into<String>,
        binary: impl Into<String>,
        version: impl Into<String>,
        ir_compiler: impl Into<String>,
        flags: Vec<String>,
        timeout: Option<Duration>,
    ) -> Self {
        Self {
            name: name.into(),
            version: version.into(),
            ir_compiler: ir_compiler.into(),
            binary: binary.into(),
            flags,
            timeout,
            identity: SolverIdentity::default(),
        }
    }

    pub fn with_identity(mut self, identity: SolverIdentity) -> Self {
        self.identity = identity;
        self
    }
}

impl Solver for SubprocessSolver {
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
    fn solve(&self, smt: &str) -> SolveResult {
        let started = Instant::now();
        let mut cmd = Command::new(&self.binary);
        for f in &self.flags {
            cmd.arg(f);
        }
        // Feed via stdin, read stdout.
        cmd.stdin(Stdio::piped());
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                eprintln!(
                    "[sugar-verifier] failed to spawn solver {:?} (binary={:?}): {e}",
                    self.name, self.binary
                );
                return SolveResult::with_evidence(
                    ObligationVerdict::Undecidable,
                    self.name.clone(),
                    self.version.clone(),
                    SolverExitMetadata::new(SolverExitKind::SpawnError),
                    Some(format!("spawn {}: {e}", self.binary)),
                    None,
                    None,
                    started.elapsed(),
                    false,
                );
            }
        };

        if let Some(mut stdin) = child.stdin.take() {
            if let Err(e) = stdin.write_all(smt.as_bytes()) {
                return SolveResult::with_evidence(
                    ObligationVerdict::Undecidable,
                    self.name.clone(),
                    self.version.clone(),
                    SolverExitMetadata::new(SolverExitKind::StdinError),
                    Some(format!("write to {} stdin: {e}", self.binary)),
                    None,
                    None,
                    started.elapsed(),
                    false,
                );
            }
        }

        // Soft timeout: poll wait_timeout-style. We avoid pulling in
        // `wait-timeout` to keep the dep set tight; busy-wait with a
        // small sleep is good enough for the verifier's call-site
        // cardinality (10s-100s, not millions).
        let timed_out;
        if let Some(to) = self.timeout {
            let deadline = started + to;
            loop {
                match child.try_wait() {
                    Ok(Some(_)) => {
                        timed_out = false;
                        break;
                    }
                    Ok(None) => {
                        if Instant::now() >= deadline {
                            let _ = child.kill();
                            let _ = child.wait();
                            // A pinned obligation is microseconds; hitting the
                            // timeout means this query was UNPINNED/open (free
                            // vars / hard theory). Loudly bounded -> Undecidable,
                            // never a hang.
                            eprintln!(
                                "[verify] {} TIMEOUT after {}s — unpinned/open obligation \
                                 (a pinned check is microseconds); -> Undecidable",
                                self.name,
                                to.as_secs().max(1)
                            );
                            return SolveResult::with_evidence(
                                ObligationVerdict::Undecidable,
                                self.name.clone(),
                                self.version.clone(),
                                SolverExitMetadata::new(SolverExitKind::Timeout),
                                Some(format!("timeout after {}s", to.as_secs().max(1))),
                                None,
                                None,
                                started.elapsed(),
                                true,
                            );
                        }
                        std::thread::sleep(Duration::from_millis(20));
                    }
                    Err(e) => {
                        return SolveResult::with_evidence(
                            ObligationVerdict::Undecidable,
                            self.name.clone(),
                            self.version.clone(),
                            SolverExitMetadata::new(SolverExitKind::WaitError),
                            Some(format!("wait {}: {e}", self.binary)),
                            None,
                            None,
                            started.elapsed(),
                            false,
                        );
                    }
                }
            }
        } else {
            timed_out = false;
        }

        let output = match child.wait_with_output() {
            Ok(o) => o,
            Err(e) => {
                return SolveResult::with_evidence(
                    ObligationVerdict::Undecidable,
                    self.name.clone(),
                    self.version.clone(),
                    SolverExitMetadata::new(SolverExitKind::WaitError),
                    Some(format!("wait {}: {e}", self.binary)),
                    None,
                    None,
                    started.elapsed(),
                    timed_out,
                );
            }
        };

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let verdict_line = stdout
            .lines()
            .map(|s| s.trim_end_matches('\r'))
            .find(|s| !s.is_empty())
            .unwrap_or_default()
            .to_string();
        let (verdict, error) = match verdict_line.as_str() {
            "unsat" => (ObligationVerdict::Discharged, String::new()),
            "sat" => (ObligationVerdict::Unsatisfied, String::new()),
            // An undeclared/uninterpreted symbol means OUR lowering emitted a
            // construct the solver cannot interpret (e.g. `method:map_err`). There
            // is no sound discharger, so we REFUSE -- loudly, by name -- rather
            // than mislabel it "undecidable" or crash. (trichotomy: refuse.)
            _ if unknown_symbol(&stdout).is_some() => {
                let sym = unknown_symbol(&stdout).unwrap_or_default();
                (
                    ObligationVerdict::Refused,
                    format!(
                        "no discharger for `{sym}`: precondition lowers to a construct the \
                         solver cannot interpret (unknown constant); refused, not guessed"
                    ),
                )
            }
            other => (
                ObligationVerdict::Undecidable,
                format!("unrecognized solver verdict: {other}"),
            ),
        };
        let exit_kind = if error.is_empty() {
            SolverExitKind::Ok
        } else if verdict == ObligationVerdict::Refused {
            SolverExitKind::UnsupportedLowering
        } else {
            SolverExitKind::UnrecognizedVerdict
        };
        SolveResult::with_evidence(
            verdict,
            self.name.clone(),
            self.version.clone(),
            SolverExitMetadata::new(exit_kind).with_code(output.status.code()),
            (!error.is_empty()).then_some(error),
            Some(stdout),
            (!stderr.is_empty()).then_some(stderr),
            started.elapsed(),
            timed_out,
        )
    }
}

/// Extract the undeclared symbol from a z3 `unknown constant <sym> ...` error, if
/// present. Its presence marks an UNSUPPORTED LOWERING: our SMT referenced a
/// function the solver has no definition for, so the obligation has no discharger
/// and must be REFUSED rather than mislabelled undecidable. Returns the symbol
/// (e.g. `method:map_err`) for the refusal reason.
fn unknown_symbol(stdout: &str) -> Option<String> {
    const MARK: &str = "unknown constant ";
    let start = stdout.find(MARK)? + MARK.len();
    let sym: String = stdout[start..]
        .chars()
        .take_while(|c| !c.is_whitespace() && *c != '(' && *c != ')')
        .collect();
    (!sym.is_empty()).then_some(sym)
}

#[cfg(test)]
mod refusal_tests {
    use super::*;

    // DISCRIMINATION: an obligation whose precondition lowers to a construct the
    // solver cannot interpret (z3 "unknown constant") is REFUSED by name -- not
    // undecidable, not a panic, not a silent pass. We drive the real solver with
    // a script referencing an undeclared function and assert the verdict.
    #[test]
    fn unknown_constant_lowers_to_a_named_refusal_not_undecidable() {
        if Command::new("z3").arg("--version").output().is_err() {
            eprintln!("z3 absent: skipping refusal discrimination test");
            return;
        }
        let solver = SubprocessSolver::new(
            "z3",
            "z3",
            "4.x",
            "smt-lib-v2.6",
            vec!["-smt2".into(), "-in".into()],
            None,
        );
        // `map_err` is never declared -> z3 emits `unknown constant map_err`
        // (the same class as the real `unknown constant method:map_err` the
        // Result::map_err lowering produces; the colon form quotes in context).
        let script = "(assert (= (map_err 1) 2))\n(check-sat)\n";
        let r = solver.solve(script);
        assert_eq!(
            r.verdict,
            ObligationVerdict::Refused,
            "unsupported lowering must REFUSE, got {:?} (stdout: {})",
            r.verdict,
            r.solver_stdout()
        );
        assert!(
            r.error().contains("no discharger") && r.error().contains("map_err"),
            "refusal must name the undischarjable construct, got: {}",
            r.error()
        );
    }

    // A genuinely-unparseable verdict (not an unknown-constant lowering gap) stays
    // Undecidable -- refusal is reserved for the unsupported-lowering class.
    #[test]
    fn unknown_symbol_extracts_the_constant_name() {
        assert_eq!(
            unknown_symbol("(error \"line 6 column 97: unknown constant method:map_err (Int)\")"),
            Some("method:map_err".to_string())
        );
        assert_eq!(unknown_symbol("sat"), None);
    }
}
