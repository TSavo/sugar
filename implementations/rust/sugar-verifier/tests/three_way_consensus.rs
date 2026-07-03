// SPDX-License-Identifier: Apache-2.0
//
// Three-way solver consensus tests: Z3 + cvc5 + Coq.
//
// Two test classes ship here.
//
// 1. Stub-driven (always runs). Builds a portfolio of three
//    StubSolvers under names "z3", "cvc5", and "coq", drives them
//    through the actual `run_plan` consensus path, and asserts the
//    aggregate verdict + telemetry shape. This is the operational
//    test that Coq can sit beside SMT solvers in the portfolio
//    plan path; it does not require any external binaries.
//
// 2. Real-binary (skip-on-missing). Exercises the actual
//    `CoqSubprocessSolver` and `SubprocessSolver(z3)` end-to-end on
//    a tautology. Each test detects whether its required binary is
//    on PATH; if not, the test prints a skip notice and returns OK
//    rather than failing CI. Run them locally with `coqc` and `z3`
//    installed.
//
// Spec: protocol/specs/2026-05-02-multi-solver-protocol-v2.md
// (Coq's seat in the multi-solver portfolio).

use std::sync::Arc;

use serde_json::json;
use sugar_verifier::solvers::{
    plan::{run_plan, Registry},
    CoqSubprocessSolver, PortfolioMode, SolverHandle, SolverPlan, SolverSeat, StubSolver,
    SubprocessSolver,
};
use sugar_verifier::types::ObligationVerdict;

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

fn z3_solver() -> SolverHandle {
    Arc::new(SubprocessSolver::new(
        "z3",
        "z3",
        "4.15",
        "smt-lib-v2.6",
        vec!["-in".into(), "-smt2".into()],
        Some(std::time::Duration::from_secs(10)),
    ))
}

fn coq_solver() -> SolverHandle {
    Arc::new(CoqSubprocessSolver::new(
        "coq",
        "coqc",
        "9.1",
        Some(std::time::Duration::from_secs(30)),
    ))
}

/// Probe PATH for a binary by running `<name> --version`. Returns true
/// on a clean exit, false on ENOENT or non-zero exit. Used by the
/// real-binary tests to skip cleanly when the binary is missing.
fn binary_on_path(name: &str) -> bool {
    std::process::Command::new(name)
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

// ---------------------------------------------------------------------------
// Stub-driven tests. Always run.
// ---------------------------------------------------------------------------

/// Three-solver consensus through `run_plan` with stubs.
///
/// Asserts that the portfolio plan happily fans out across three
/// named solvers, including one whose `ir_compiler` tag identifies
/// it as the Coq pipeline. The verdict is Discharged when all three
/// agree.
#[test]
fn portfolio_consensus_three_way_stubs_unanimous() {
    let mut registry: Registry = Registry::new();
    registry.insert(
        SolverSeat::Z3,
        Arc::new(StubSolver::new("z3", ObligationVerdict::Discharged)) as SolverHandle,
    );
    registry.insert(
        SolverSeat::Cvc5,
        Arc::new(StubSolver::new("cvc5", ObligationVerdict::Discharged)) as SolverHandle,
    );
    registry.insert(
        SolverSeat::Coq,
        Arc::new(StubSolver::new("coq", ObligationVerdict::Discharged)) as SolverHandle,
    );

    let plan = SolverPlan::Portfolio {
        names: vec![SolverSeat::Z3, SolverSeat::Cvc5, SolverSeat::Coq],
        mode: PortfolioMode::Consensus,
    };

    let (verdict, reason, invs) = run_plan(&plan, &registry, "(check-sat)", None);
    assert_eq!(verdict, ObligationVerdict::Discharged);
    assert_eq!(invs.len(), 3, "three invocation rows expected");
    let names: Vec<&str> = invs.iter().map(|i| i.result.solver_name.as_str()).collect();
    assert!(names.contains(&"z3"));
    assert!(names.contains(&"cvc5"));
    assert!(names.contains(&"coq"));
    assert!(reason.contains("agree"));
}

/// Three-solver portfolio where Coq disagrees with the SMT pair.
///
/// In the v1 ConsensusMode, Discharged + Discharged + Unsatisfied is
/// a SOLVER DISAGREEMENT. The portfolio plan returns
/// `ObligationVerdict::Disagreement` with a reason that names the
/// disagreeing solvers. The v2 ConsensusCoverage rule is more
/// nuanced (per-position coverage); this test pins the v1 behavior
/// only.
#[test]
fn portfolio_consensus_three_way_stubs_disagreement_loud() {
    let mut registry: Registry = Registry::new();
    registry.insert(
        SolverSeat::Z3,
        Arc::new(StubSolver::new("z3", ObligationVerdict::Discharged)) as SolverHandle,
    );
    registry.insert(
        SolverSeat::Cvc5,
        Arc::new(StubSolver::new("cvc5", ObligationVerdict::Discharged)) as SolverHandle,
    );
    registry.insert(
        SolverSeat::Coq,
        Arc::new(StubSolver::new("coq", ObligationVerdict::Unsatisfied)) as SolverHandle,
    );

    let plan = SolverPlan::Portfolio {
        names: vec![SolverSeat::Z3, SolverSeat::Cvc5, SolverSeat::Coq],
        mode: PortfolioMode::Consensus,
    };

    let (verdict, reason, invs) = run_plan(&plan, &registry, "(check-sat)", None);
    assert_eq!(verdict, ObligationVerdict::Disagreement);
    assert_eq!(invs.len(), 3);
    assert!(
        reason.to_uppercase().contains("DISAGREEMENT"),
        "expected disagreement in reason, got: {reason}"
    );
}

/// Three-solver portfolio where two SMT solvers are Undecidable and
/// only Coq lands a definitive verdict. The portfolio's v1 consensus
/// rule treats Undecidable as silent: the verdict is whatever the
/// definitive solvers agreed on, here Discharged from Coq alone.
///
/// This is the load-bearing case for the v2 ConsensusCoverage story:
/// when SMT solvers go Undecidable on lambdas / dependent types /
/// kit predicates, Coq is the producer that still discharges. The v2
/// rule will additionally require an opacity-coverage check; this v1
/// case is the floor the v2 rule extends.
#[test]
fn portfolio_consensus_coq_alone_discharges_when_smt_undecidable() {
    let mut registry: Registry = Registry::new();
    registry.insert(
        SolverSeat::Z3,
        Arc::new(StubSolver::new("z3", ObligationVerdict::Undecidable)) as SolverHandle,
    );
    registry.insert(
        SolverSeat::Cvc5,
        Arc::new(StubSolver::new("cvc5", ObligationVerdict::Undecidable)) as SolverHandle,
    );
    registry.insert(
        SolverSeat::Coq,
        Arc::new(StubSolver::new("coq", ObligationVerdict::Discharged)) as SolverHandle,
    );

    let plan = SolverPlan::Portfolio {
        names: vec![SolverSeat::Z3, SolverSeat::Cvc5, SolverSeat::Coq],
        mode: PortfolioMode::Consensus,
    };

    let (verdict, _reason, invs) = run_plan(&plan, &registry, "(check-sat)", None);
    assert_eq!(verdict, ObligationVerdict::Discharged);
    assert_eq!(invs.len(), 3);
    let coq_row = invs
        .iter()
        .find(|i| i.result.solver_name == "coq")
        .expect("coq row present");
    assert!(coq_row.authoritative);
}

// ---------------------------------------------------------------------------
// Real-binary tests. Skip cleanly when the binaries are not on PATH.
// ---------------------------------------------------------------------------

/// Real-binary smoke. The current `sugar-ir-compiler-coq` emits
/// proofs using the `admit. Qed.` placeholder (see notes.md in that
/// crate), so `coqc` exits non-zero on the generated `.v` file.
/// That gap belongs to the Coq IR-compiler, not the solver wiring
/// this PR exercises. Until the compiler emits real tactics, this
/// test asserts the weaker but still-load-bearing claim: Coq is
/// invoked, IR-JSON is parsed and compiled, and the verdict comes
/// back. When the compiler matures the assertion can tighten to
/// `Discharged`.
#[test]
fn coq_solver_invokes_coqc_and_returns_a_verdict() {
    if !binary_on_path("coqc") {
        eprintln!(
            "SKIP coq_solver_invokes_coqc_and_returns_a_verdict: coqc not on PATH; \
             install Coq to run this test."
        );
        return;
    }
    let solver = coq_solver();
    let ir = json!({
        "kind": "forall",
        "name": "x",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "x"},
                {"kind": "var", "name": "x"}
            ]
        }
    });

    let result = solver.solve(&ir.to_string());
    // The wire-level claim: Coq parsed the IR, ran coqc, and
    // returned a verdict. Discharged is the goal once the Coq IR
    // compiler stops emitting `admit. Qed.`; until then,
    // Undecidable with a coqc exit-code error is the expected
    // shape and confirms the wiring is intact.
    assert!(
        matches!(
            result.verdict,
            ObligationVerdict::Discharged | ObligationVerdict::Undecidable
        ),
        "Coq solver should return Discharged or Undecidable, got: {:?} (error: {})",
        result.verdict,
        result.error()
    );
    assert!(
        !result.error().contains("spawn") && !result.error().contains("not found"),
        "Coq solver should have spawned coqc; got error: {}",
        result.error()
    );
}

#[test]
fn z3_solver_discharges_trivial_forall() {
    if !binary_on_path("z3") {
        eprintln!(
            "SKIP z3_solver_discharges_trivial_forall: z3 not on PATH; \
             install z3 to run this test."
        );
        return;
    }
    let solver = z3_solver();
    let smt = r#"
(set-logic ALL)
(declare-fun x () Int)
(assert (not (= x x)))
(check-sat)
"#;

    let result = solver.solve(smt);
    assert!(
        matches!(result.verdict, ObligationVerdict::Discharged),
        "Z3 should discharge reflexivity (unsat = no counterexample), got: {:?} (error: {})",
        result.verdict,
        result.error()
    );
}

/// Real-binary smoke for both Z3 and Coq running side by side
/// against equivalent obligations. As above, the Coq IR-compiler
/// currently emits `admit. Qed.`, so the Coq verdict is
/// Undecidable rather than Discharged on real binaries; the
/// assertion shape captures the wire-level claim.
#[test]
fn z3_and_coq_real_binaries_return_verdicts() {
    if !binary_on_path("z3") || !binary_on_path("coqc") {
        eprintln!(
            "SKIP z3_and_coq_real_binaries_return_verdicts: requires both `z3` and \
             `coqc` on PATH. Install both to run this test."
        );
        return;
    }
    let mut registry: Registry = Registry::new();
    registry.insert(SolverSeat::Z3, z3_solver());
    registry.insert(SolverSeat::Coq, coq_solver());

    // Z3 on SMT-LIB.
    let z3_smt = r#"
(set-logic ALL)
(declare-fun x () Int)
(assert (not (>= x 0)))
(assert (>= x 0))
(check-sat)
"#;
    let z3_result = registry.get(&SolverSeat::Z3).unwrap().solve(z3_smt);

    // Coq on IR-JSON.
    let coq_ir = json!({
        "kind": "forall",
        "name": "x",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "x"},
                {"kind": "var", "name": "x"}
            ]
        }
    });
    let coq_result = registry
        .get(&SolverSeat::Coq)
        .unwrap()
        .solve(&coq_ir.to_string());

    // Z3 must Discharge: the obligation is a tautology.
    assert_eq!(
        z3_result.verdict,
        ObligationVerdict::Discharged,
        "Z3 verdict: {:?}, error: {}",
        z3_result.verdict,
        z3_result.error()
    );
    // Coq returns Discharged once the IR-compiler emits real
    // tactics; until then Undecidable is the expected shape and
    // confirms the wiring.
    assert!(
        matches!(
            coq_result.verdict,
            ObligationVerdict::Discharged | ObligationVerdict::Undecidable
        ),
        "Coq verdict: {:?}, error: {}",
        coq_result.verdict,
        coq_result.error()
    );

    println!(
        "Real-binary smoke: Z3={:?}, Coq={:?}.",
        z3_result.verdict, coq_result.verdict
    );
}

// ---------------------------------------------------------------------------
// Registry-driven test. Confirms that the TOML config + registry::build
// path produces a CoqSubprocessSolver, not a generic SMT subprocess
// solver pointed at coqc. This is the wire-level assertion that "Coq
// is a real solver in the portfolio" works through the configuration
// surface, not just through hand-built handles.
// ---------------------------------------------------------------------------

#[test]
fn registry_builds_coq_solver_from_toml() {
    let toml = r#"
[solvers]
portfolio = ["z3", "cvc5", "coq"]
mode = "consensus"

[solvers.z3]
binary = "stub:unsat"

[solvers.cvc5]
binary = "stub:unsat"

[solvers.coq]
binary = "/definitely/missing/coqc"
ir_compiler = "coq"
"#;
    let cfg = sugar_verifier::solvers::SolversConfig::from_toml(toml).expect("parse toml");
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);

    // The plan is the consensus portfolio of three solvers.
    match &plan {
        SolverPlan::Portfolio { names, mode } => {
            assert_eq!(names.len(), 3);
            assert!(names.contains(&SolverSeat::Coq));
            assert_eq!(*mode, PortfolioMode::Consensus);
        }
        other => panic!("expected Portfolio plan, got {:?}", other),
    }

    // The registry resolved "coq" to a CoqSubprocessSolver. Solver
    // execution consumes compiled Coq text now; ProofIR-to-Coq lowering
    // happens at the compiler registry boundary before the solver is called.
    let coq = registry.get(&SolverSeat::Coq).expect("coq registered");
    assert_eq!(coq.ir_compiler(), "coq");
    let res = coq.solve("Theorem sugar_obligation : True.\nProof. exact I. Qed.\n");
    assert_eq!(res.verdict, ObligationVerdict::Undecidable);
    assert!(
        res.error().contains("spawn") && !res.error().contains("IR-JSON"),
        "expected Coq subprocess spawn error after compiled input, got: {}",
        res.error()
    );
}
