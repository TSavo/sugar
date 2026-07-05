// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Model-extraction solver runner.
//
// ADDITIVE path: does not modify the existing `solve()` / `Solver` trait or the
// discharge verdict mapping (`unsat`->Discharged / `sat`->Unsatisfied). The
// `solve_with_model` function here is a NEW, SEPARATE path used exclusively by
// `sugar derive`. It sends a QF_BV script that ends with `(get-value (r))` and
// reads TWO output lines: the `sat` verdict and the `((r #x........))` model.
//
// If z3 is absent, times out, or returns anything other than `sat`, an error
// is returned and no derived value is produced (honest refusal, not a guess).

use std::io::Write;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use sugar_ir_compiler_smt_lib::derive_query::parse_model_value;

/// The outcome of a model-extraction query.
#[derive(Debug, Clone)]
pub struct ModelResult {
    /// The z3 first-line verdict (`"sat"`, `"unsat"`, or other).
    pub verdict_line: String,
    /// The derived i32 value, present only when verdict == "sat" and
    /// `(get-value (r))` returned a parseable hex bitvector.
    pub derived_value: Option<i32>,
    /// The raw stdout from z3 (both lines), for receipt / debugging.
    pub raw_stdout: String,
    /// Wall-clock time.
    pub wall_clock: Duration,
    /// Whether the solver timed out.
    pub timed_out: bool,
    /// Error string (empty on success).
    pub error: String,
}

/// Run a QF_BV model-extraction query against a z3 binary.
///
/// `z3_binary`: path to z3 (e.g. `"z3"` or `"/usr/bin/z3"`).
/// `smt`: the complete SMT-LIB script ending with `(check-sat)\n(get-value (r))\n`.
/// `result_var`: the name of the result variable in the `get-value` call (e.g. `"r"`).
/// `timeout`: optional timeout.
///
/// Returns `ModelResult`. On `sat`, parses the model value; on any other verdict or
/// parse failure, `derived_value` is `None`.
pub fn solve_with_model(
    z3_binary: &str,
    smt: &str,
    result_var: &str,
    timeout: Option<Duration>,
) -> ModelResult {
    let started = Instant::now();

    let mut cmd = Command::new(z3_binary);
    cmd.args(["-smt2", "-in"]);
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            return ModelResult {
                verdict_line: String::new(),
                derived_value: None,
                raw_stdout: String::new(),
                wall_clock: started.elapsed(),
                timed_out: false,
                error: format!("spawn z3 ({z3_binary}): {e}"),
            };
        }
    };

    // Write the SMT script.
    if let Some(mut stdin) = child.stdin.take() {
        if let Err(e) = stdin.write_all(smt.as_bytes()) {
            let _ = child.kill();
            return ModelResult {
                verdict_line: String::new(),
                derived_value: None,
                raw_stdout: String::new(),
                wall_clock: started.elapsed(),
                timed_out: false,
                error: format!("stdin write: {e}"),
            };
        }
        // stdin dropped here — EOF sent to z3.
    }

    // Soft timeout (same pattern as SubprocessSolver).
    let timed_out;
    if let Some(to) = timeout {
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
                        return ModelResult {
                            verdict_line: String::new(),
                            derived_value: None,
                            raw_stdout: String::new(),
                            wall_clock: started.elapsed(),
                            timed_out: true,
                            error: format!("timeout after {}s", to.as_secs().max(1)),
                        };
                    }
                    std::thread::sleep(Duration::from_millis(20));
                }
                Err(e) => {
                    return ModelResult {
                        verdict_line: String::new(),
                        derived_value: None,
                        raw_stdout: String::new(),
                        wall_clock: started.elapsed(),
                        timed_out: false,
                        error: format!("wait: {e}"),
                    };
                }
            }
        }
    } else {
        timed_out = false;
    }

    let output = match child.wait_with_output() {
        Ok(o) => o,
        Err(e) => {
            return ModelResult {
                verdict_line: String::new(),
                derived_value: None,
                raw_stdout: String::new(),
                wall_clock: started.elapsed(),
                timed_out,
                error: format!("wait_with_output: {e}"),
            };
        }
    };

    let raw_stdout = String::from_utf8_lossy(&output.stdout).to_string();

    // HONEST REFUSAL: if z3 exited non-zero (a crash, a parse error, an internal
    // failure), surface it as a solver ERROR with stderr preserved -- never parse
    // the verdict/model. A fabricated derived value from a failed solver run is a
    // silent lie. (trichotomy: refuse, loudly.)
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let code = output
            .status
            .code()
            .map(|c| c.to_string())
            .unwrap_or_else(|| "signal".to_string());
        // z3 writes its `(error ...)` diagnostics to stdout, not stderr; include
        // whichever carries the message so the refusal is legible.
        let diag = if !stderr.trim().is_empty() {
            stderr.trim().to_string()
        } else {
            raw_stdout.trim().to_string()
        };
        return ModelResult {
            verdict_line: String::new(),
            derived_value: None,
            raw_stdout,
            wall_clock: started.elapsed(),
            timed_out,
            error: format!("z3 exited non-zero (code {code}): {diag}"),
        };
    }

    // Collect non-empty lines.
    let lines: Vec<&str> = raw_stdout
        .lines()
        .map(|l| l.trim_end_matches('\r'))
        .filter(|l| !l.is_empty())
        .collect();

    let verdict_line = lines.first().copied().unwrap_or("").to_string();

    let derived_value = if verdict_line == "sat" {
        // Second line is the get-value response.
        lines.get(1).and_then(|l| parse_model_value(l, result_var))
    } else {
        None
    };

    ModelResult {
        verdict_line,
        derived_value,
        raw_stdout,
        wall_clock: started.elapsed(),
        timed_out,
        error: String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn solve_with_model_abs_min_value() {
        use sugar_ir_compiler_smt_lib::derive_query::emit_derive_query;
        if std::process::Command::new("z3")
            .arg("--version")
            .output()
            .is_err()
        {
            eprintln!("z3 absent: skipping solve_with_model test");
            return;
        }

        // abs bv_tree: bv32.ite(bv32.slt(a, 0), bv32.neg(a), a)
        let bv_tree = serde_json::json!({
            "kind": "ctor",
            "name": "bv32.ite",
            "args": [
                {
                    "kind": "ctor",
                    "name": "bv32.slt",
                    "args": [
                        {"kind": "var", "name": "a"},
                        {"kind": "const", "value": 0}
                    ]
                },
                {
                    "kind": "ctor",
                    "name": "bv32.neg",
                    "args": [{"kind": "var", "name": "a"}]
                },
                {"kind": "var", "name": "a"}
            ]
        });

        let dq = emit_derive_query(&bv_tree, &[i32::MIN]).expect("emit");
        let result = solve_with_model("z3", &dq.smt, &dq.result_var, None);

        assert!(
            result.error.is_empty(),
            "unexpected error: {}",
            result.error
        );
        assert_eq!(
            result.verdict_line, "sat",
            "expected sat, got: {:?}",
            result.verdict_line
        );
        assert_eq!(
            result.derived_value,
            Some(i32::MIN),
            "z3.model must derive abs(MIN_VALUE)=-2147483648; got {:?}\nraw stdout:\n{}",
            result.derived_value,
            result.raw_stdout
        );
    }

    #[test]
    fn nonzero_exit_is_an_honest_error_not_a_fabricated_value() {
        if std::process::Command::new("z3")
            .arg("--version")
            .output()
            .is_err()
        {
            eprintln!("z3 absent: skipping solver-error test");
            return;
        }
        // A script z3 rejects with a non-zero exit: a sort mismatch (asserting a
        // BitVec equals a Bool). z3 prints an (error ...) and exits non-zero. We
        // must surface a solver error with stderr/stdout preserved and NO derived
        // value -- never parse a verdict/model out of a failed run.
        let broken = "(set-logic QF_BV)\n(declare-const a (_ BitVec 32))\n(assert (= a true))\n(check-sat)\n(get-value (a))\n";
        let result = solve_with_model("z3", broken, "a", None);
        assert!(
            !result.error.is_empty(),
            "a non-zero z3 exit must yield a solver error, got error={:?} verdict={:?}",
            result.error,
            result.verdict_line
        );
        assert!(
            result.error.contains("non-zero"),
            "error must name the failure: {}",
            result.error
        );
        assert_eq!(
            result.derived_value, None,
            "must NOT fabricate a derived value on solver failure"
        );
        assert!(
            result.verdict_line.is_empty(),
            "must NOT report a verdict on solver failure"
        );
    }
}
