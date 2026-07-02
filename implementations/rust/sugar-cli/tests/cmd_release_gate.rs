// SPDX-License-Identifier: Apache-2.0

use std::collections::VecDeque;
use std::path::PathBuf;

use clap::Parser;
use serde_json::{json, Value};
use sugar_cli::cmd_release_gate::{
    release_gate_exit_code, release_gate_plan, run_release_gate_with_executor, GateExecutor,
    GateInvocation, GateOutput, ReleaseGateArgs,
};
use sugar_cli::doctor::{report_from_floor_signals, DoctorMode};
use sugar_cli::floor_runtime_check::FloorSignals;

fn invocation_args(invocation: &GateInvocation) -> Vec<String> {
    invocation
        .args
        .iter()
        .map(|arg| arg.to_string_lossy().to_string())
        .collect()
}

#[test]
fn default_plan_runs_doctor_and_self_check_for_cli_and_lib() {
    let args = ReleaseGateArgs::try_parse_from(["release-gate"]).unwrap();
    let plan = release_gate_plan(&args).expect("default release-gate plan");

    let actual: Vec<(String, String, Vec<String>)> = plan
        .iter()
        .map(|invocation| {
            (
                invocation.target_name.clone(),
                invocation.command.clone(),
                invocation_args(invocation),
            )
        })
        .collect();

    assert_eq!(
        actual,
        vec![
            (
                "sugar-cli".to_string(),
                "doctor".to_string(),
                vec![
                    "doctor",
                    "--target",
                    "implementations/rust/sugar-cli",
                    "--mode",
                    "releaseGate",
                    "--oracle",
                    "--json",
                ]
                .into_iter()
                .map(str::to_string)
                .collect(),
            ),
            (
                "sugar-cli".to_string(),
                "self-check".to_string(),
                vec![
                    "self-check",
                    "--target",
                    "implementations/rust/sugar-cli",
                    "--oracle",
                    "--json",
                ]
                .into_iter()
                .map(str::to_string)
                .collect(),
            ),
            (
                "libsugar".to_string(),
                "doctor".to_string(),
                vec![
                    "doctor",
                    "--target",
                    "implementations/rust/libsugar",
                    "--mode",
                    "releaseGate",
                    "--oracle",
                    "--json",
                ]
                .into_iter()
                .map(str::to_string)
                .collect(),
            ),
            (
                "libsugar".to_string(),
                "self-check".to_string(),
                vec![
                    "self-check",
                    "--target",
                    "implementations/rust/libsugar",
                    "--oracle",
                    "--json",
                ]
                .into_iter()
                .map(str::to_string)
                .collect(),
            ),
        ]
    );
}

#[test]
fn config_file_replaces_default_targets() {
    let td = tempfile::tempdir().unwrap();
    let config = td.path().join("release-gate.toml");
    std::fs::write(
        &config,
        r#"
[[target]]
name = "custom"
path = "examples/custom"
"#,
    )
    .unwrap();

    let config_arg = config.to_string_lossy().to_string();
    let args =
        ReleaseGateArgs::try_parse_from(["release-gate", "--config", config_arg.as_str()]).unwrap();
    let plan = release_gate_plan(&args).expect("custom release-gate plan");

    assert_eq!(plan.len(), 2);
    assert!(plan
        .iter()
        .all(|invocation| invocation.target_name == "custom"));
    assert_eq!(
        invocation_args(&plan[0]),
        vec![
            "doctor",
            "--target",
            "examples/custom",
            "--mode",
            "releaseGate",
            "--oracle",
            "--json",
        ]
    );
    assert_eq!(
        invocation_args(&plan[1]),
        vec![
            "self-check",
            "--target",
            "examples/custom",
            "--oracle",
            "--json",
        ]
    );
}

#[test]
fn all_four_green_gates_mark_release_ready() {
    let args = ReleaseGateArgs::try_parse_from(["release-gate"]).unwrap();
    let mut executor = FakeExecutor::new(vec![
        ok_doctor("sugar-cli"),
        ok_self_check("implementations/rust/sugar-cli", 21, 53, 0),
        ok_doctor("libsugar"),
        ok_self_check("implementations/rust/libsugar", 12, 35, 0),
    ]);

    let receipt = run_release_gate_with_executor(args, &mut executor).expect("release receipt");

    assert!(receipt.release_ready, "{receipt:#?}");
    assert_eq!(release_gate_exit_code(&receipt), sugar_cli::EXIT_OK);
    assert_eq!(receipt.targets.len(), 2);
    assert_eq!(executor.invocations.len(), 4);
}

#[test]
fn any_failed_gate_marks_release_not_ready_and_names_failure() {
    let args = ReleaseGateArgs::try_parse_from(["release-gate"]).unwrap();
    let mut executor = FakeExecutor::new(vec![
        ok_doctor("sugar-cli"),
        failed_self_check("implementations/rust/sugar-cli"),
        ok_doctor("libsugar"),
        ok_self_check("implementations/rust/libsugar", 12, 35, 0),
    ]);

    let receipt = run_release_gate_with_executor(args, &mut executor).expect("release receipt");

    assert!(!receipt.release_ready, "{receipt:#?}");
    assert_eq!(
        release_gate_exit_code(&receipt),
        sugar_cli::EXIT_VERIFY_FAIL
    );
    assert_eq!(receipt.failures.len(), 1);
    assert_eq!(receipt.failures[0].target, "sugar-cli");
    assert_eq!(receipt.failures[0].command, "self-check");
}

#[test]
fn receipt_extracts_k_floor_residue_and_doctor_evidence() {
    let args = ReleaseGateArgs::try_parse_from(["release-gate"]).unwrap();
    let mut executor = FakeExecutor::new(vec![
        ok_doctor("sugar-cli"),
        ok_self_check("implementations/rust/sugar-cli", 21, 53, 9),
        ok_doctor("libsugar"),
        ok_self_check("implementations/rust/libsugar", 12, 35, 1),
    ]);

    let receipt = run_release_gate_with_executor(args, &mut executor).expect("release receipt");
    let cli = receipt
        .targets
        .iter()
        .find(|target| target.name == "sugar-cli")
        .expect("sugar-cli target");

    assert_eq!(cli.evidence.k_panic_safe, 21);
    assert_eq!(cli.evidence.floor.silently_dropped, 0);
    assert_eq!(cli.evidence.floor.false_pass, 0);
    assert_eq!(cli.evidence.floor.dropped_sites_count, 0);
    assert_eq!(cli.evidence.floor.total_callsites, 53);
    assert!(cli.evidence.floor.discharge_split_present);
    assert_eq!(cli.evidence.residue.residue, 9);
    assert_eq!(cli.evidence.residue.tier_to_close, 1);
    assert_eq!(cli.evidence.residue.raw_unproven, 0);
    assert!(cli
        .evidence
        .doctor_checks
        .iter()
        .any(|check| check.name == "dependency-pool-stable" && check.status == "pass"));
}

#[test]
fn total_callsites_zero_in_self_check_json_fails_floor_aggregation() {
    let args = ReleaseGateArgs::try_parse_from(["release-gate"]).unwrap();
    let mut executor = FakeExecutor::new(vec![
        ok_doctor("sugar-cli"),
        ok_self_check("implementations/rust/sugar-cli", 21, 0, 0),
        ok_doctor("libsugar"),
        ok_self_check("implementations/rust/libsugar", 12, 35, 0),
    ]);

    let receipt = run_release_gate_with_executor(args, &mut executor).expect("release receipt");
    let cli = receipt
        .targets
        .iter()
        .find(|target| target.name == "sugar-cli")
        .expect("sugar-cli target");

    assert!(!receipt.release_ready, "{receipt:#?}");
    assert!(cli.floor_report.checks.iter().any(|check| check.id
        == "floor.total_callsites.nonzero"
        && check.status.as_str() == "fail"));
}

#[test]
fn doctor_floor_aggregation_is_production_surface_for_release_gate() {
    let report = report_from_floor_signals(
        PathBuf::from("implementations/rust/sugar-cli").as_path(),
        DoctorMode::ReleaseGate,
        FloorSignals {
            silently_dropped: 0,
            false_pass: 0,
            dropped_sites_count: 0,
            panic_census_unnamed_count: 0,
            total_callsites: 1,
            discharge_split_present: true,
            monoid_fold_gaps_by_element_type: std::collections::BTreeMap::new(),
            algebra_gaps_by_boundary: std::collections::BTreeMap::new(),
        },
    );

    assert!(report.ok);
    assert!(report.release_ready);
}

#[derive(Debug)]
struct FakeExecutor {
    invocations: Vec<GateInvocation>,
    outputs: VecDeque<GateOutput>,
}

impl FakeExecutor {
    fn new(outputs: Vec<GateOutput>) -> Self {
        Self {
            invocations: Vec::new(),
            outputs: outputs.into(),
        }
    }
}

impl GateExecutor for FakeExecutor {
    fn run(&mut self, invocation: &GateInvocation) -> Result<GateOutput, String> {
        self.invocations.push(invocation.clone());
        self.outputs
            .pop_front()
            .ok_or_else(|| format!("no fake output for {invocation:?}"))
    }
}

fn ok_doctor(target: &str) -> GateOutput {
    GateOutput {
        exit_code: 0,
        stdout: json!({
            "mode": "releaseGate",
            "ok": true,
            "releaseReady": true,
            "checks": [
                {"name": "config-toml-parse", "status": "pass", "detail": target},
                {"name": "dependency-pool-stable", "status": "pass", "detail": "stable"}
            ]
        })
        .to_string(),
        stderr: String::new(),
    }
}

fn ok_self_check(
    target: &str,
    panic_safe: u64,
    total_callsites: u64,
    residue: usize,
) -> GateOutput {
    GateOutput {
        exit_code: 0,
        stdout: self_check_json(target, panic_safe, total_callsites, residue).to_string(),
        stderr: String::new(),
    }
}

fn failed_self_check(target: &str) -> GateOutput {
    GateOutput {
        exit_code: 1,
        stdout: self_check_json(target, 0, 1, 0).to_string(),
        stderr: "self-check invariant violation".to_string(),
    }
}

fn self_check_json(target: &str, panic_safe: u64, total_callsites: u64, residue: usize) -> Value {
    let mut panic_census = vec![
        json!({
            "file": "src/lib.rs",
            "line": 1,
            "callee": "method:unwrap",
            "status": "proven",
            "reason": "panic-safe"
        }),
        json!({
            "file": "src/lib.rs",
            "line": 2,
            "callee": "method:unwrap",
            "status": "unproven",
            "category": "D-lib",
            "tierToClose": "D-lib",
            "reason": "closeable"
        }),
    ];
    for idx in 0..residue {
        panic_census.push(json!({
            "file": "src/lib.rs",
            "line": 100 + idx,
            "callee": "method:expect",
            "status": "residue",
            "category": "lock_poisoning_residue",
            "tierToClose": "irreducible",
            "reason": "honest residue"
        }));
    }
    json!({
        "target": target,
        "catalogCid": "blake3-512:test",
        "lift": {
            "fnContracts": 1,
            "bodyDischargeEligible": 1,
            "bodyDischargeIneligible": {}
        },
        "bridges": {
            "emitted": 1,
            "liftGaps": {}
        },
        "oracle": {
            "requested": true,
            "engaged": true,
            "attempted": 1,
            "resolved": 1
        },
        "silentlyDropped": 0,
        "droppedSites": [],
        "totalCallsites": total_callsites,
        "dischargeSplit": {
            "panicSafe": panic_safe,
            "reflexive": 0,
            "vacuous": 0,
            "undecidable": 0,
            "falsePass": 0
        },
        "panicCensus": panic_census
    })
}
