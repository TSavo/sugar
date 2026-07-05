// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Integration tests for the multi-solver layer driven through the
// public Runner API. Uses the `stub:` solver shorthand so CI doesn't
// need any solver binaries installed.
//
// Verifies, for each mode, that the SolverPlan compiles correctly
// from TOML, the registry resolves stubs, and `run_plan` produces the
// expected verdict. These exercise the same code paths the demo
// driver does.

use std::sync::Arc;

use sugar_ir_compiler::CompilerInput;
use sugar_verifier::solvers::{
    plan::{run_plan, Registry},
    SolverPlan, SolverSeat, SolversConfig, StubSolver,
};
use sugar_verifier::types::ObligationVerdict;
use sugar_verifier::SolverHandle;

fn parse(toml_body: &str) -> SolversConfig {
    SolversConfig::from_toml(toml_body).expect("parse toml")
}

fn compiler_input(value: serde_json::Value) -> CompilerInput {
    CompilerInput::decode_json(value).expect("multi-solver fixture decodes")
}

#[test]
fn end_to_end_chain_falls_through_undecidable_to_unsat() {
    let body = r#"
[solvers]
chain = ["vampire", "z3"]

[solvers.vampire]
binary = "stub:undecidable"

[solvers.z3]
binary = "stub:unsat"
"#;
    let cfg = parse(body);
    let plan = SolverPlan::from_config(&cfg);
    let registry: Registry = sugar_verifier::solvers::registry::build(&cfg);

    let (verdict, reason, invs) = run_plan(&plan, &registry, "(check-sat)", None);
    assert_eq!(verdict, ObligationVerdict::Discharged);
    assert_eq!(invs.len(), 2);
    assert!(reason.contains("chain"));
}

#[test]
fn end_to_end_portfolio_first_wins_takes_first_definitive() {
    let body = r#"
[solvers]
portfolio = ["vampire", "z3"]
mode = "first-wins"

[solvers.vampire]
binary = "stub:undecidable"

[solvers.z3]
binary = "stub:unsat"
"#;
    let cfg = parse(body);
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);
    let (verdict, _, invs) = run_plan(&plan, &registry, "(check-sat)", None);
    assert_eq!(verdict, ObligationVerdict::Discharged);
    assert_eq!(invs.len(), 2);
}

#[test]
fn end_to_end_portfolio_consensus_disagreement_flags_loud() {
    let body = r#"
[solvers]
portfolio = ["z3", "cvc5"]
mode = "consensus"

[solvers.z3]
binary = "stub:unsat"

[solvers.cvc5]
binary = "stub:sat"
"#;
    let cfg = parse(body);
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);
    let (verdict, reason, _) = run_plan(&plan, &registry, "(check-sat)", None);
    assert_eq!(verdict, ObligationVerdict::Disagreement);
    assert!(reason.to_uppercase().contains("DISAGREEMENT"));
}

#[test]
fn end_to_end_portfolio_consensus_unanimous() {
    let body = r#"
[solvers]
portfolio = ["z3", "cvc5", "bitwuzla"]
mode = "consensus"

[solvers.z3]
binary = "stub:unsat"

[solvers.cvc5]
binary = "stub:unsat"

[solvers.bitwuzla]
binary = "stub:unsat"
"#;
    let cfg = parse(body);
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);
    let (verdict, reason, _) = run_plan(&plan, &registry, "(check-sat)", None);
    assert_eq!(verdict, ObligationVerdict::Discharged);
    assert!(reason.contains("agree"));
}

#[test]
fn end_to_end_dispatch_routes_strings_to_string_solver() {
    let body = r#"
[solvers]
[solvers.dispatch]
strings = "cvc5"
"linear-arithmetic" = "z3"
default = "z3"

[solvers.cvc5]
binary = "stub:unsat"

[solvers.z3]
binary = "stub:undecidable"
"#;
    let cfg = parse(body);
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);

    let f = compiler_input(serde_json::json!({
        "kind": "atomic", "name": "length",
        "args": [{"kind":"var","name":"s"}]
    }));
    let (verdict, _, invs) = run_plan(&plan, &registry, "(check-sat)", Some(&f));
    assert_eq!(verdict, ObligationVerdict::Discharged);
    assert_eq!(invs[0].result.solver_name, "cvc5");
}

#[test]
fn end_to_end_dispatch_routes_lia_to_default_z3() {
    let body = r#"
[solvers]
[solvers.dispatch]
strings = "cvc5"
default = "z3"

[solvers.cvc5]
binary = "stub:unsat"

[solvers.z3]
binary = "stub:unsat"
"#;
    let cfg = parse(body);
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);
    let f = compiler_input(serde_json::json!({
        "kind":"atomic","name":">",
        "args":[
            {"kind":"var","name":"x"},
            {"kind":"const","value":0,"sort":{"kind":"primitive","name":"Int"}}
        ]
    }));
    let (_, _, invs) = run_plan(&plan, &registry, "(check-sat)", Some(&f));
    assert_eq!(invs[0].result.solver_name, "z3");
}

#[test]
fn registry_handles_subprocess_solver_with_missing_binary_gracefully() {
    let mut reg: Registry = std::collections::HashMap::new();
    let s = sugar_verifier::SubprocessSolver::new(
        "z3",
        "/nonexistent/binary/that/does/not/exist",
        "0",
        "smt-lib-v2.6",
        vec![],
        Some(std::time::Duration::from_secs(1)),
    );
    reg.insert(SolverSeat::Z3, Arc::new(s) as SolverHandle);
    let plan = SolverPlan::Single(SolverSeat::Z3);
    let (verdict, _reason, invs) = run_plan(&plan, &reg, "(check-sat)", None);
    assert_eq!(verdict, ObligationVerdict::Undecidable);
    assert_eq!(invs.len(), 1);
    assert!(!invs[0].result.error().is_empty());
}

#[test]
fn end_to_end_dispatch_no_match_no_default_undecidable() {
    let cfg = parse(
        r#"
[solvers]
[solvers.dispatch]
strings = "cvc5"

[solvers.cvc5]
binary = "stub:unsat"
"#,
    );
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);
    let f = compiler_input(serde_json::json!({"kind":"atomic","name":">","args":[]}));
    let (v, reason, _) = run_plan(&plan, &registry, "(check-sat)", Some(&f));
    assert_eq!(v, ObligationVerdict::Undecidable);
    assert!(reason.contains("no matching solver"));
}

#[test]
fn end_to_end_chain_records_all_attempts_in_invs() {
    let cfg = parse(
        r#"
[solvers]
chain = ["z3", "cvc5", "bitwuzla"]
[solvers.z3]
binary = "stub:undecidable"
[solvers.cvc5]
binary = "stub:undecidable"
[solvers.bitwuzla]
binary = "stub:unsat"
"#,
    );
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);
    let (v, _, invs) = run_plan(&plan, &registry, "(check-sat)", None);
    assert_eq!(v, ObligationVerdict::Discharged);
    assert_eq!(invs.len(), 3);
    let names: Vec<_> = invs.iter().map(|i| i.result.solver_name.as_str()).collect();
    assert_eq!(names, vec!["z3", "cvc5", "bitwuzla"]);
}

#[test]
fn portfolio_per_solver_telemetry_captures_versions() {
    let cfg = parse(
        r#"
[solvers]
portfolio = ["z3", "cvc5"]
mode = "first-wins"
[solvers.z3]
binary = "stub:unsat"
version = "1.2"
[solvers.cvc5]
binary = "stub:unsat"
version = "3.4"
"#,
    );
    let plan = SolverPlan::from_config(&cfg);
    let registry = sugar_verifier::solvers::registry::build(&cfg);
    let (_, _, invs) = run_plan(&plan, &registry, "(check-sat)", None);
    let versions: std::collections::BTreeSet<&str> = invs
        .iter()
        .map(|i| i.result.solver_version.as_str())
        .collect();
    // Stub solvers ignore the configured `version` field; they report
    // their own "stub-unsat" tag. The point of this test is just that
    // every invocation carries SOME version string we can stamp into
    // the implication memento body.prover.
    for v in &versions {
        assert!(!v.is_empty());
    }
    assert_eq!(invs.len(), 2);
}

#[test]
fn runner_aggregates_per_solver_telemetry() {
    // Construct a minimal Runner against an empty project_root so
    // load_all_proofs returns nothing; we're exercising the
    // build_plan_and_registry + run_with_tiers path here, not the
    // handshake. With zero call sites the per_solver map is empty
    // but solver_invocations should also be 0 and not panic.
    use sugar_verifier::{Runner, RunnerConfig};
    let tmp = std::env::temp_dir().join(format!("sugar-runner-empty-{}", std::process::id()));
    std::fs::create_dir_all(&tmp).unwrap();
    let cfg = RunnerConfig {
        project_root: tmp.clone(),
        legacy_z3_fallback: None,
        cache_dir: None,
        mint_seed: None,
        mint_producer_id: None,
        solvers_config: Some(
            SolversConfig::from_toml(
                r#"
[solvers]
default = "z3"
[solvers.z3]
binary = "stub:unsat"
"#,
            )
            .unwrap(),
        ),
        extra_projects: Vec::new(),
        extra_proof_files: Vec::new(),
        extra_proofs: Vec::new(),
        plan_artifact: None,
        trusted_implication_signers: Vec::new(),
    };
    let runner = Runner::new(cfg);
    let (report, stats) = runner.run_with_tiers();
    assert_eq!(report.total_callsites, 0);
    assert_eq!(stats.solver_invocations, 0);
    assert_eq!(stats.disagreements, 0);
    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn min_solver_witnesses_parsed_for_spec_compliance() {
    // Spec-only field in v0; we just verify it parses so the field
    // makes it into the runtime config object that future versions
    // will consult.
    let cfg = parse(
        r#"
[solvers]
default = "z3"
min_solver_witnesses = 2
[solvers.z3]
binary = "z3"
"#,
    );
    assert_eq!(cfg.min_solver_witnesses, Some(2));
    let _ = StubSolver::new("ignored", ObligationVerdict::Discharged);
}
