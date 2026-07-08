// SPDX-License-Identifier: MIT OR Apache-2.0
//
// LANE C golden pair (2/2): z3-solve golden.
//
// This is the FIRST per-target golden unit test keyed on the ONE object
// (an SMT-LIB script -> an `ObligationVerdict`) on the SOLVE side. It feeds
// two hand-written, golden SMT-LIB v2.6 scripts (one built to be UNSAT, one
// built to be SAT) to the real z3 binary through the same `Solver` trait /
// `SubprocessSolver` seat production code uses, and asserts the resulting
// `ObligationVerdict` matches exactly.
//
// The companion z3-compile golden lives in
// sugar-ir-compiler-smt-lib/tests/golden_z3_compile.rs and pins the OTHER
// half of the pipeline (ProofIR IrFormula -> emitted SMT-LIB script, no
// solver involved). Together the two tests are the template for the other
// compiler targets (coq, lean): a compile-side golden per compiler crate,
// and a solve-side golden per verifier seat.
//
// -- z3-presence gating --
//
// Green-or-skipped, never red-on-missing-z3: this follows the SAME idiom
// already used throughout the tree (e.g.
// `sugar-verifier/src/solvers/subprocess.rs`'s
// `unknown_constant_lowers_to_a_named_refusal_not_undecidable`, and the
// several `z3 absent: skipping ...` call sites in
// `sugar-ir-compiler-smt-lib/src/emitter.rs`): probe
// `z3 --version` first and `eprintln!` + early-`return` (not `#[ignore]`)
// when it is absent, so the test reports green in environments without a
// z3 binary on PATH instead of failing red on missing tooling.

use std::process::Command;

use sugar_verifier::solvers::{Solver, SubprocessSolver};
use sugar_verifier::types::ObligationVerdict;

fn z3_present() -> bool {
    Command::new("z3").arg("--version").output().is_ok()
}

fn z3_solver() -> SubprocessSolver {
    SubprocessSolver::new(
        "z3",
        "z3",
        "4.x",
        "smt-lib-v2.6",
        vec!["-smt2".into(), "-in".into()],
        None,
    )
}

/// Golden UNSAT script: asserts the negation of `x + 1 > x`, a fact true for
/// every integer `x`. The negation therefore has no model -> z3 reports
/// `unsat` -> `SubprocessSolver` maps that to `ObligationVerdict::Discharged`
/// (the obligation `x + 1 > x` is proved).
const GOLDEN_UNSAT_SCRIPT: &str = "(set-logic ALL)\n\
(declare-const x Int)\n\
(assert (not (> (+ x 1) x)))\n\
(check-sat)\n";

/// Golden SAT script: asserts the negation of `x > 0`, which is NOT true for
/// every integer (e.g. `x = 0` is a counterexample). The negation therefore
/// has a model -> z3 reports `sat` -> `SubprocessSolver` maps that to
/// `ObligationVerdict::Unsatisfied` (the obligation `x > 0` is not proved).
const GOLDEN_SAT_SCRIPT: &str = "(set-logic ALL)\n\
(declare-const x Int)\n\
(assert (not (> x 0)))\n\
(check-sat)\n";

#[test]
fn z3_solve_golden_unsat_script_discharges() {
    if !z3_present() {
        eprintln!("z3 absent: skipping z3-solve golden UNSAT test");
        return;
    }
    let result = z3_solver().solve(GOLDEN_UNSAT_SCRIPT);
    assert_eq!(
        result.verdict,
        ObligationVerdict::Discharged,
        "golden UNSAT script must discharge; stdout={:?} stderr={:?}",
        result.solver_stdout(),
        result.solver_stderr()
    );
}

#[test]
fn z3_solve_golden_sat_script_is_unsatisfied() {
    if !z3_present() {
        eprintln!("z3 absent: skipping z3-solve golden SAT test");
        return;
    }
    let result = z3_solver().solve(GOLDEN_SAT_SCRIPT);
    assert_eq!(
        result.verdict,
        ObligationVerdict::Unsatisfied,
        "golden SAT script must be Unsatisfied (obligation not proved); stdout={:?} stderr={:?}",
        result.solver_stdout(),
        result.solver_stderr()
    );
}
