// SPDX-License-Identifier: Apache-2.0

use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;

use sugar_ir_compiler::{registry::Registry as CompilerRegistry, CompilerInput};
use sugar_ir_compiler_lean::LeanCompiler;
use sugar_verifier::solvers::{
    plan::run_plan_with_compilers, registry, LeanSubprocessSolver, Solver, SolverPlan, SolverSeat,
    SolversConfig,
};
use sugar_verifier::types::ObligationVerdict;

fn binary_on_path(name: &str) -> bool {
    Command::new("sh")
        .arg("-c")
        .arg(format!("command -v {name} >/dev/null 2>&1"))
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn lean_project_dir() -> Option<PathBuf> {
    if let Ok(path) = std::env::var("SUGAR_LEAN_PROJECT") {
        let project = PathBuf::from(path);
        if project.join("lakefile.lean").is_file() {
            return Some(project);
        }
        eprintln!(
            "skipping: SUGAR_LEAN_PROJECT does not contain lakefile.lean: {}",
            project.display()
        );
        return None;
    }

    let project = PathBuf::from("/opt/lean-mathlib");
    if project.join("lakefile.lean").is_file() {
        Some(project)
    } else {
        eprintln!("skipping: SUGAR_LEAN_PROJECT is not set and /opt/lean-mathlib is absent");
        None
    }
}

#[test]
fn lean_file_cid_uses_sugar_canonicalizer_hash() {
    let source = "theorem sugar_obligation : True := by trivial\n";
    assert_eq!(
        LeanSubprocessSolver::lean_file_cid(source),
        sugar_canonicalizer::blake3_512_of(source.as_bytes())
    );
}

#[test]
fn axiom_parser_detects_sorry_ax() {
    let output = "axioms sugar_obligation: [propext, Quot.sound, sorryAx]\n";
    let axioms = LeanSubprocessSolver::parse_axiom_set(output, "sugar_obligation");
    assert!(axioms.iter().any(|a| a == "sorryAx"));
    assert!(LeanSubprocessSolver::uses_sorry_or_sorry_ax(
        "theorem sugar_obligation : True := by trivial\n",
        output
    ));
}

#[test]
fn registry_recognizes_lean_ir_compiler() {
    let cfg = SolversConfig::from_toml(
        r#"
[solvers]
default = "lean"

[solvers.lean]
binary = "/definitely/missing/lake"
ir_compiler = "lean"
"#,
    )
    .expect("parse");
    let plan = SolverPlan::from_config(&cfg);
    let registry = registry::build(&cfg);
    let solver = registry.get(&SolverSeat::Lean).expect("lean registered");
    assert_eq!(solver.ir_compiler(), "lean");
    match plan {
        SolverPlan::Single(name) => assert_eq!(name, SolverSeat::Lean),
        _ => panic!("expected single lean solver"),
    }
    let result = solver.solve("theorem sugar_obligation : True := by trivial\n");
    assert_eq!(result.verdict, ObligationVerdict::Undecidable);
    assert!(
        result.error().contains("spawn") && !result.error().contains("IR-JSON"),
        "Lean solver should consume compiled Lean text, got: {}",
        result.error()
    );
}

#[test]
fn run_plan_compiles_formula_before_lean_solver() {
    let cfg = SolversConfig::from_toml(
        r#"
[solvers]
default = "lean"

[solvers.lean]
binary = "/definitely/missing/lake"
ir_compiler = "lean"
"#,
    )
    .expect("parse");
    let plan = SolverPlan::from_config(&cfg);
    let registry = registry::build(&cfg);
    let mut compilers = CompilerRegistry::new();
    compilers.register(Arc::new(LeanCompiler::new()));
    let formula = serde_json::json!({"kind": "atomic", "name": "true", "args": []});
    let input = CompilerInput::decode_json(formula).expect("Lean solver fixture decodes");
    let (verdict, _reason, invocations) =
        run_plan_with_compilers(&plan, &registry, &compilers, &input);
    assert_eq!(verdict, ObligationVerdict::Undecidable);
    let error = &invocations[0].result.error();
    assert!(
        error.contains("spawn")
            && !error.contains("parse IR-JSON")
            && !error.contains("ir compiler"),
        "ProofIR should compile to Lean before spawning lake, got: {error}"
    );
}

#[test]
fn mathlib_commit_parser_reads_lake_manifest() {
    let dir = std::env::temp_dir().join(format!("sugar-lean-manifest-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    std::fs::write(
        dir.join("lake-manifest.json"),
        r#"{"packages":[{"name":"mathlib","rev":"abc123"}]}"#,
    )
    .expect("write manifest");
    let commit = LeanSubprocessSolver::mathlib_commit_from_project(&dir);
    let _ = std::fs::remove_dir_all(&dir);
    assert_eq!(commit.as_deref(), Some("abc123"));
}

#[test]
fn lean_solver_discharges_reflexivity_with_local_mathlib() {
    if !binary_on_path("lake") {
        eprintln!("skipping: lake not on PATH");
        return;
    }
    if !binary_on_path("lean") {
        eprintln!("skipping: lean not on PATH");
        return;
    }
    let Some(project) = lean_project_dir() else {
        return;
    };
    let solver = LeanSubprocessSolver::new(
        "lean",
        "lake",
        "4.x",
        Some(std::time::Duration::from_secs(60)),
        Some(project.to_string_lossy().into_owned()),
        None,
    );
    let ir = serde_json::json!({
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
    assert_eq!(result.verdict, ObligationVerdict::Discharged);
    assert!(!result.solver_stdout().contains("sorryAx"));
}
