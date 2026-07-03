use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use serde_json::json;
use sugar_ir_compiler::{registry::Registry as CompilerRegistry, CompilerInput, IrCompiler};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT as SMT_DIALECT};
use sugar_verifier::solvers::{
    plan::{run_plan, run_plan_with_compilers, Registry, SolverInvocation},
    SolveResult, Solver, SolverPlan, SolverSeat,
};
use sugar_verifier::types::ObligationVerdict;
use sugar_verifier::SolverHandle;

#[derive(Debug)]
struct CapturingSolver {
    name: &'static str,
    version: &'static str,
    ir_compiler: &'static str,
    verdict: ObligationVerdict,
}

impl Solver for CapturingSolver {
    fn name(&self) -> &str {
        self.name
    }

    fn version(&self) -> &str {
        self.version
    }

    fn ir_compiler(&self) -> &str {
        self.ir_compiler
    }

    fn solve(&self, input: &str) -> SolveResult {
        SolveResult {
            verdict: self.verdict,
            solver_name: self.name.to_string(),
            solver_version: self.version.to_string(),
            error: String::new(),
            solver_stdout: format!("input-bytes={}\n", input.len()),
            wall_clock: Duration::ZERO,
            timed_out: false,
        }
    }
}

fn formula_json() -> serde_json::Value {
    json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": 7, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    })
}

fn compiler_input() -> CompilerInput {
    CompilerInput::decode_json(formula_json()).expect("S4 formula fixture decodes")
}

fn solver_registry(ir_compiler: &'static str, verdict: ObligationVerdict) -> Registry {
    let mut registry: Registry = HashMap::new();
    registry.insert(
        SolverSeat::Z3,
        Arc::new(CapturingSolver {
            name: "z3",
            version: "s4-stub",
            ir_compiler,
            verdict,
        }) as SolverHandle,
    );
    registry
}

fn compiler_registry() -> CompilerRegistry {
    let mut compilers = CompilerRegistry::new();
    compilers.register(Arc::new(SmtLibCompiler::new()));
    compilers
}

fn assert_invocation_shape_eq(left: &SolverInvocation, right: &SolverInvocation) {
    assert_eq!(left.authoritative, right.authoritative);
    assert_eq!(left.compiler, right.compiler);
    assert_eq!(left.identity.artifact_cid, right.identity.artifact_cid);
    assert_eq!(left.identity.invocation_cid, right.identity.invocation_cid);
    assert_eq!(
        left.identity.vendor_memento_cid,
        right.identity.vendor_memento_cid
    );
    assert_eq!(left.result.verdict, right.result.verdict);
    assert_eq!(left.result.solver_name, right.result.solver_name);
    assert_eq!(left.result.solver_version, right.result.solver_version);
    assert_eq!(left.result.error, right.result.error);
    assert_eq!(left.result.solver_stdout, right.result.solver_stdout);
    assert_eq!(left.result.wall_clock, right.result.wall_clock);
    assert_eq!(left.result.timed_out, right.result.timed_out);
}

#[test]
fn typed_verifier_plan_matches_precompiled_smt_verdict_and_invocation_shape() {
    let input = compiler_input();
    let compiled = SmtLibCompiler::new()
        .compile_typed(&input, SMT_DIALECT)
        .expect("typed SMT-LIB compile");
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let solvers = solver_registry(SMT_DIALECT, ObligationVerdict::Discharged);
    let compilers = compiler_registry();

    let precompiled = run_plan(&plan, &solvers, &compiled.script(), Some(&input));
    let typed = run_plan_with_compilers(&plan, &solvers, &compilers, &input);

    assert_eq!(typed.0, precompiled.0);
    assert_eq!(typed.1, precompiled.1);
    assert_eq!(typed.2.len(), precompiled.2.len());
    assert_invocation_shape_eq(&typed.2[0], &precompiled.2[0]);
}

#[test]
fn planted_solver_input_drift_changes_invocation_receipt() {
    let input = compiler_input();
    let compiled = SmtLibCompiler::new()
        .compile_typed(&input, SMT_DIALECT)
        .expect("typed SMT-LIB compile");
    let mut drifted_script = compiled.script();
    drifted_script.push_str("; planted-s4-drift-control\n");

    let plan = SolverPlan::Single(SolverSeat::Z3);
    let solvers = solver_registry(SMT_DIALECT, ObligationVerdict::Discharged);
    let clean = run_plan(&plan, &solvers, &compiled.script(), Some(&input));
    let drifted = run_plan(&plan, &solvers, &drifted_script, Some(&input));

    assert_eq!(clean.0, drifted.0);
    assert_ne!(
        clean.2[0].result.solver_stdout, drifted.2[0].result.solver_stdout,
        "planted solver-input drift must be visible in invocation telemetry"
    );
}

#[test]
fn row_10_precompiled_non_smt_solver_refuses_loudly() {
    let input = compiler_input();
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let solvers = solver_registry("lean", ObligationVerdict::Discharged);

    let (verdict, reason, invocations) = run_plan(&plan, &solvers, "(check-sat)\n", Some(&input));

    assert_eq!(verdict, ObligationVerdict::Undecidable);
    assert!(reason.contains("precompiled solver input is SMT-LIB text"));
    assert_eq!(invocations.len(), 1);
    assert!(invocations[0]
        .result
        .error
        .contains("route typed ProofIR through run_plan_with_compilers"));
}

#[test]
fn missing_compiler_for_typed_plan_remains_undecidable() {
    let input = compiler_input();
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let solvers = solver_registry("missing-dialect", ObligationVerdict::Discharged);
    let compilers = CompilerRegistry::new();

    let (verdict, reason, invocations) =
        run_plan_with_compilers(&plan, &solvers, &compilers, &input);

    assert_eq!(verdict, ObligationVerdict::Undecidable);
    assert!(reason.contains("ir compiler `missing-dialect`"));
    assert_eq!(invocations.len(), 1);
}
