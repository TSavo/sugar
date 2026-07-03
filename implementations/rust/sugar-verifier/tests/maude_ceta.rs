use std::process::Command;
use std::time::Duration;

use serde_json::{json, Value as Json};
use sugar_verifier::solvers::ceta::{parse_ceta_output, CetaDecision};
use sugar_verifier::solvers::maude::{parse_maude_output, MaudeDecision};
use sugar_verifier::solvers::{CetaGateConfig, MaudeSubprocessSolver, Solver};
use sugar_verifier::types::ObligationVerdict;

fn binary_on_path(name: &str) -> bool {
    Command::new("sh")
        .arg("-c")
        .arg(format!("command -v {name} >/dev/null 2>&1"))
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn skip_unless_binaries_exist(names: &[&str]) -> bool {
    for name in names {
        if !binary_on_path(name) {
            eprintln!("skipping: {name} not on PATH");
            return false;
        }
    }
    true
}

fn nat_discharge_obligation() -> Json {
    json!({
        "kind": "atomic",
        "name": "equational_theory",
        "theory": {
            "name": "sugar-nat",
            "sorts": ["Nat"],
            "operators": [
                {"name": "zero", "arity": [], "result": "Nat"},
                {"name": "s", "arity": ["Nat"], "result": "Nat"},
                {"name": "plus", "arity": ["Nat", "Nat"], "result": "Nat"}
            ],
            "variables": [
                {"name": "N", "sort": "Nat"},
                {"name": "M", "sort": "Nat"}
            ],
            "equations": [
                {
                    "label": "plus-zero-left",
                    "lhs": {"kind": "ctor", "name": "plus", "args": [
                        {"kind": "ctor", "name": "zero", "args": []},
                        {"kind": "var", "name": "N"}
                    ]},
                    "rhs": {"kind": "var", "name": "N"}
                },
                {
                    "label": "plus-s-left",
                    "lhs": {"kind": "ctor", "name": "plus", "args": [
                        {"kind": "ctor", "name": "s", "args": [
                            {"kind": "var", "name": "N"}
                        ]},
                        {"kind": "var", "name": "M"}
                    ]},
                    "rhs": {"kind": "ctor", "name": "s", "args": [
                        {"kind": "ctor", "name": "plus", "args": [
                            {"kind": "var", "name": "N"},
                            {"kind": "var", "name": "M"}
                        ]}
                    ]}
                }
            ]
        },
        "obligation": {
            "lhs": {"kind": "ctor", "name": "plus", "args": [
                {"kind": "ctor", "name": "s", "args": [
                    {"kind": "ctor", "name": "zero", "args": []}
                ]},
                {"kind": "ctor", "name": "s", "args": [
                    {"kind": "ctor", "name": "zero", "args": []}
                ]}
            ]},
            "rhs": {"kind": "ctor", "name": "s", "args": [
                {"kind": "ctor", "name": "s", "args": [
                    {"kind": "ctor", "name": "zero", "args": []}
                ]}
            ]}
        }
    })
}

#[test]
fn maude_parser_accepts_equal_reduce_normal_forms() {
    let stdout = "\
reduce in SUGAR-NAT : plus(s(zero), s(zero)) .
result Nat: s(s(zero))
reduce in SUGAR-NAT : s(s(zero)) .
result Nat: s(s(zero))
search in SUGAR-NAT : plus(s(zero), s(zero)) =>* s(s(zero)) .
No solution.
";
    let parsed = parse_maude_output(stdout).unwrap();
    assert_eq!(parsed.normal_forms, vec!["s(s(zero))", "s(s(zero))"]);
    assert_eq!(parsed.decision, MaudeDecision::ReduceEqual);
}

#[test]
fn maude_parser_accepts_search_solution() {
    let stdout = "\
reduce in M : lhs .
result Elt: lhs
reduce in M : rhs .
result Elt: rhs
search in M : lhs =>* rhs .
Solution 1
state: rhs
";
    let parsed = parse_maude_output(stdout).unwrap();
    assert_eq!(parsed.decision, MaudeDecision::SearchSolution);
}

#[test]
fn maude_parser_returns_unknown_for_no_match() {
    let stdout = "\
reduce in M : lhs .
result Elt: lhs
reduce in M : rhs .
result Elt: rhs
search in M : lhs =>* rhs .
No solution.
";
    let parsed = parse_maude_output(stdout).unwrap();
    assert_eq!(parsed.decision, MaudeDecision::NoMatch);
}

#[test]
fn ceta_parser_accepts_only_certified_success() {
    assert_eq!(parse_ceta_output("YES\n").unwrap(), CetaDecision::Accepted);
    assert_eq!(
        parse_ceta_output("Certificate accepted\n").unwrap(),
        CetaDecision::Accepted
    );
    assert_eq!(parse_ceta_output("NO\n").unwrap(), CetaDecision::Rejected);
    assert_eq!(
        parse_ceta_output("error: invalid certificate\n").unwrap(),
        CetaDecision::Rejected
    );
}

#[test]
fn non_confluent_gate_rejection_discards_reduce() {
    let maude_stdout = "\
reduce in BAD : a .
result Elt: c
reduce in BAD : b .
result Elt: c
search in BAD : a =>* b .
No solution.
";
    let maude = parse_maude_output(maude_stdout).unwrap();
    assert_eq!(maude.decision, MaudeDecision::ReduceEqual);
    let ceta = parse_ceta_output("NO\n").unwrap();
    assert_eq!(ceta, CetaDecision::Rejected);
}

#[test]
fn binary_dependent_maude_and_ceta_gate_smoke() {
    if !skip_unless_binaries_exist(&["maude", "aprove", "ceta", "csi"]) {
        return;
    }

    let solver = MaudeSubprocessSolver::new(
        "maude",
        "maude",
        "3.x",
        Some(Duration::from_secs(30)),
        CetaGateConfig {
            enabled: true,
            ceta_binary: "ceta".to_string(),
            termination_prover: "aprove".to_string(),
            confluence_checker: "csi".to_string(),
            timeout: Some(Duration::from_secs(30)),
        },
    );

    let result = solver.solve(&nat_discharge_obligation().to_string());
    assert_eq!(
        result.verdict,
        ObligationVerdict::Discharged,
        "Maude should discharge the Nat reflexivity obligation, error: {}, stdout: {}",
        result.error(),
        result.solver_stdout()
    );
    assert!(
        result.solver_stdout().contains("\"ceta_gate\""),
        "expected a CeTA gate receipt, got: {}",
        result.solver_stdout()
    );
    assert!(
        !result.solver_stdout().contains("\"bypassed\":true"),
        "expected the CeTA gate to run on a nonempty TRS, got: {}",
        result.solver_stdout()
    );
}
