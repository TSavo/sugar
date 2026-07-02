// SPDX-License-Identifier: Apache-2.0

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use clap::Parser;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::doctor::{report_from_floor_signals, CheckSeverity, DoctorMode, DoctorReport};
use crate::floor_runtime_check::{algebra_gap_boundary, FloorSignals};
use crate::{EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

#[derive(Parser, Debug, Clone)]
pub struct ReleaseGateArgs {
    /// Emit structured JSON release evidence.
    #[arg(long)]
    pub json: bool,
    /// Optional TOML target list. Defaults to sugar-cli and libsugar.
    #[arg(long)]
    pub config: Option<PathBuf>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GateInvocation {
    pub target_name: String,
    pub target_path: String,
    pub command: String,
    pub args: Vec<OsString>,
}

#[derive(Debug, Clone)]
pub struct GateOutput {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
}

pub trait GateExecutor {
    fn run(&mut self, invocation: &GateInvocation) -> Result<GateOutput, String>;
}

#[derive(Debug, Clone)]
pub struct ReleaseGateReceipt {
    pub release_ready: bool,
    pub targets: Vec<TargetReceipt>,
    pub failures: Vec<ReleaseGateFailure>,
}

#[derive(Debug, Clone)]
pub struct ReleaseGateFailure {
    pub target: String,
    pub command: String,
    pub reason: String,
}

#[derive(Debug, Clone)]
pub struct TargetReceipt {
    pub name: String,
    pub path: String,
    pub doctor: GateCommandReceipt,
    pub self_check: GateCommandReceipt,
    pub evidence: TargetEvidence,
    pub floor_report: DoctorReport,
    pub release_ready: bool,
}

#[derive(Debug, Clone)]
pub struct GateCommandReceipt {
    pub command: String,
    pub ok: bool,
    pub exit_code: i32,
    pub stdout_json: Value,
    pub stderr: String,
}

#[derive(Debug, Clone)]
pub struct TargetEvidence {
    pub k_panic_safe: u64,
    pub floor: FloorSignals,
    pub residue: ResidueEvidence,
    pub doctor_checks: Vec<DoctorCheckEvidence>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResidueEvidence {
    pub residue: usize,
    pub tier_to_close: usize,
    pub raw_unproven: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DoctorCheckEvidence {
    pub name: String,
    pub status: String,
    pub detail: String,
}

#[derive(Debug, Clone, Deserialize)]
struct ReleaseGateConfig {
    #[serde(default)]
    target: Vec<ReleaseGateConfigTarget>,
}

#[derive(Debug, Clone, Deserialize)]
struct ReleaseGateConfigTarget {
    name: String,
    path: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ReleaseGateTarget {
    name: String,
    path: String,
}

pub fn run(args: ReleaseGateArgs) -> u8 {
    let repo_root = match discover_repo_root() {
        Ok(root) => root,
        Err(error) => {
            eprintln!("release-gate failed: {error}");
            return EXIT_USER_ERROR;
        }
    };
    let bin = match std::env::current_exe() {
        Ok(bin) => bin,
        Err(error) => {
            eprintln!("release-gate failed: resolve current executable: {error}");
            return EXIT_USER_ERROR;
        }
    };
    let mut executor = SystemGateExecutor { bin, repo_root };
    match run_release_gate_with_executor(args.clone(), &mut executor) {
        Ok(receipt) => {
            if args.json {
                println!("{}", receipt_json(&receipt));
            } else {
                print_human(&receipt);
            }
            release_gate_exit_code(&receipt)
        }
        Err(error) => {
            eprintln!("release-gate failed: {error}");
            EXIT_USER_ERROR
        }
    }
}

pub fn release_gate_plan(args: &ReleaseGateArgs) -> Result<Vec<GateInvocation>, String> {
    let mut plan = Vec::new();
    for target in release_gate_targets(args)? {
        plan.push(doctor_invocation(&target));
        plan.push(self_check_invocation(&target));
    }
    Ok(plan)
}

pub fn run_release_gate_with_executor(
    args: ReleaseGateArgs,
    executor: &mut dyn GateExecutor,
) -> Result<ReleaseGateReceipt, String> {
    let plan = release_gate_plan(&args)?;
    let mut target_receipts = Vec::new();
    let mut failures = Vec::new();

    for pair in plan.chunks(2) {
        let [doctor_invocation, self_check_invocation] = pair else {
            return Err("release-gate plan must contain doctor/self-check pairs".to_string());
        };
        let target_name = doctor_invocation.target_name.clone();
        let target_path = doctor_invocation.target_path.clone();

        let doctor_output = executor.run(doctor_invocation)?;
        let doctor = command_receipt(doctor_invocation, doctor_output, doctor_gate_ok);
        if !doctor.ok {
            failures.push(ReleaseGateFailure {
                target: target_name.clone(),
                command: doctor.command.clone(),
                reason: failed_gate_reason(&doctor),
            });
        }

        let self_check_output = executor.run(self_check_invocation)?;
        let self_check =
            command_receipt(self_check_invocation, self_check_output, self_check_gate_ok);
        if !self_check.ok {
            failures.push(ReleaseGateFailure {
                target: target_name.clone(),
                command: self_check.command.clone(),
                reason: failed_gate_reason(&self_check),
            });
        }

        let floor = floor_signals_from_self_check_json(&self_check.stdout_json);
        let floor_report = report_from_floor_signals(
            Path::new(&target_path),
            DoctorMode::ReleaseGate,
            floor.clone(),
        );
        if !floor_report.ok {
            failures.push(ReleaseGateFailure {
                target: target_name.clone(),
                command: "floor".to_string(),
                reason: "release-gate floor aggregation failed".to_string(),
            });
        }

        let evidence = TargetEvidence {
            k_panic_safe: k_panic_safe(&self_check.stdout_json),
            floor,
            residue: residue_evidence(&self_check.stdout_json),
            doctor_checks: doctor_check_evidence(&doctor.stdout_json),
        };
        let release_ready = doctor.ok && self_check.ok && floor_report.release_ready;
        target_receipts.push(TargetReceipt {
            name: target_name,
            path: target_path,
            doctor,
            self_check,
            evidence,
            floor_report,
            release_ready,
        });
    }

    let release_ready =
        failures.is_empty() && target_receipts.iter().all(|target| target.release_ready);
    Ok(ReleaseGateReceipt {
        release_ready,
        targets: target_receipts,
        failures,
    })
}

pub fn release_gate_exit_code(receipt: &ReleaseGateReceipt) -> u8 {
    if receipt.release_ready {
        EXIT_OK
    } else {
        EXIT_VERIFY_FAIL
    }
}

fn release_gate_targets(args: &ReleaseGateArgs) -> Result<Vec<ReleaseGateTarget>, String> {
    if let Some(config) = &args.config {
        let text = std::fs::read_to_string(config)
            .map_err(|e| format!("read release-gate config {}: {e}", config.display()))?;
        let parsed: ReleaseGateConfig = toml::from_str(&text)
            .map_err(|e| format!("parse release-gate config {}: {e}", config.display()))?;
        if parsed.target.is_empty() {
            return Err(format!(
                "release-gate config {} has no [[target]] entries",
                config.display()
            ));
        }
        return Ok(parsed
            .target
            .into_iter()
            .map(|target| ReleaseGateTarget {
                name: target.name,
                path: target.path,
            })
            .collect());
    }
    Ok(vec![
        ReleaseGateTarget {
            name: "sugar-cli".to_string(),
            path: "implementations/rust/sugar-cli".to_string(),
        },
        ReleaseGateTarget {
            name: "libsugar".to_string(),
            path: "implementations/rust/libsugar".to_string(),
        },
    ])
}

fn doctor_invocation(target: &ReleaseGateTarget) -> GateInvocation {
    GateInvocation {
        target_name: target.name.clone(),
        target_path: target.path.clone(),
        command: "doctor".to_string(),
        args: vec![
            "doctor".into(),
            "--target".into(),
            target.path.clone().into(),
            "--mode".into(),
            "releaseGate".into(),
            "--oracle".into(),
            "--json".into(),
        ],
    }
}

fn self_check_invocation(target: &ReleaseGateTarget) -> GateInvocation {
    GateInvocation {
        target_name: target.name.clone(),
        target_path: target.path.clone(),
        command: "self-check".to_string(),
        args: vec![
            "self-check".into(),
            "--target".into(),
            target.path.clone().into(),
            "--oracle".into(),
            "--json".into(),
        ],
    }
}

fn command_receipt(
    invocation: &GateInvocation,
    output: GateOutput,
    gate_ok: fn(i32, &Value) -> bool,
) -> GateCommandReceipt {
    let stdout_json = serde_json::from_str(&output.stdout).unwrap_or(Value::Null);
    let ok = gate_ok(output.exit_code, &stdout_json);
    GateCommandReceipt {
        command: invocation.command.clone(),
        ok,
        exit_code: output.exit_code,
        stdout_json,
        stderr: output.stderr,
    }
}

fn doctor_gate_ok(exit_code: i32, stdout_json: &Value) -> bool {
    exit_code == 0
        && stdout_json
            .get("ok")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        && stdout_json
            .get("releaseReady")
            .and_then(Value::as_bool)
            .unwrap_or(false)
}

fn self_check_gate_ok(exit_code: i32, stdout_json: &Value) -> bool {
    exit_code == 0 && stdout_json.is_object()
}

fn failed_gate_reason(command: &GateCommandReceipt) -> String {
    if !command.stderr.trim().is_empty() {
        return command.stderr.trim().to_string();
    }
    format!("{} exited {}", command.command, command.exit_code)
}

fn floor_signals_from_self_check_json(json: &Value) -> FloorSignals {
    let split = json.get("dischargeSplit").unwrap_or(&Value::Null);
    FloorSignals {
        silently_dropped: json
            .get("silentlyDropped")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        false_pass: split.get("falsePass").and_then(Value::as_u64).unwrap_or(0),
        dropped_sites_count: json
            .get("droppedSites")
            .and_then(Value::as_array)
            .map_or(0, Vec::len),
        panic_census_unnamed_count: json.get("panicCensus").and_then(Value::as_array).map_or(
            0,
            |rows| {
                rows.iter()
                    .filter(|row| {
                        row.get("status").and_then(Value::as_str) != Some("proven")
                            && row.get("category").is_none()
                            && row.get("tierToClose").is_none()
                    })
                    .count()
            },
        ),
        total_callsites: json
            .get("totalCallsites")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        discharge_split_present: json
            .get("dischargeSplit")
            .is_some_and(|value| !value.is_null()),
        monoid_fold_gaps_by_element_type: monoid_fold_gaps_by_element_type_from_json(json),
        algebra_gaps_by_boundary: algebra_gaps_by_boundary_from_json(json),
    }
}

fn monoid_fold_gaps_by_element_type_from_json(json: &Value) -> BTreeMap<String, u64> {
    let mut counts = BTreeMap::new();
    let Some(rows) = json.get("panicCensus").and_then(Value::as_array) else {
        return counts;
    };
    for row in rows {
        let Some(reason) = row.get("reason").and_then(Value::as_str) else {
            continue;
        };
        let Some(element_type) = monoid_fold_gap_element_type(reason) else {
            continue;
        };
        *counts.entry(element_type).or_insert(0) += 1;
    }
    counts
}

fn monoid_fold_gap_element_type(reason: &str) -> Option<String> {
    if !reason.contains("MonoidFold") {
        return None;
    }
    let (_, tail) = reason.split_once("element_type=")?;
    let element_type = tail
        .split(',')
        .next()
        .unwrap_or("")
        .trim()
        .trim_matches('`');
    (!element_type.is_empty()).then(|| element_type.to_string())
}

fn algebra_gaps_by_boundary_from_json(json: &Value) -> BTreeMap<String, u64> {
    let mut counts = BTreeMap::new();
    let Some(rows) = json.get("panicCensus").and_then(Value::as_array) else {
        return counts;
    };
    for row in rows {
        let Some(reason) = row.get("reason").and_then(Value::as_str) else {
            continue;
        };
        let Some(boundary) = algebra_gap_boundary(reason) else {
            continue;
        };
        *counts.entry(boundary).or_insert(0) += 1;
    }
    counts
}

fn k_panic_safe(json: &Value) -> u64 {
    json.get("dischargeSplit")
        .and_then(|split| split.get("panicSafe"))
        .and_then(Value::as_u64)
        .unwrap_or(0)
}

fn residue_evidence(json: &Value) -> ResidueEvidence {
    let mut evidence = ResidueEvidence {
        residue: 0,
        tier_to_close: 0,
        raw_unproven: 0,
    };
    let Some(rows) = json.get("panicCensus").and_then(Value::as_array) else {
        return evidence;
    };
    for row in rows {
        let status = row.get("status").and_then(Value::as_str).unwrap_or("");
        let category = row.get("category").and_then(Value::as_str);
        let tier_to_close = row.get("tierToClose").and_then(Value::as_str);
        if status == "residue" || category.is_some_and(|value| value.ends_with("_residue")) {
            evidence.residue += 1;
        } else if status != "proven" && tier_to_close.is_some() {
            evidence.tier_to_close += 1;
        } else if status != "proven" && category.is_none() && tier_to_close.is_none() {
            evidence.raw_unproven += 1;
        }
    }
    evidence
}

fn doctor_check_evidence(json: &Value) -> Vec<DoctorCheckEvidence> {
    json.get("checks")
        .and_then(Value::as_array)
        .map(|checks| {
            checks
                .iter()
                .map(|check| DoctorCheckEvidence {
                    name: check
                        .get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string(),
                    status: check
                        .get("status")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string(),
                    detail: check
                        .get("detail")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string(),
                })
                .collect()
        })
        .unwrap_or_default()
}

struct SystemGateExecutor {
    bin: PathBuf,
    repo_root: PathBuf,
}

impl GateExecutor for SystemGateExecutor {
    fn run(&mut self, invocation: &GateInvocation) -> Result<GateOutput, String> {
        let output = Command::new(&self.bin)
            .current_dir(&self.repo_root)
            .args(&invocation.args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .map_err(|e| format!("run {:?}: {e}", invocation.args))?;
        Ok(GateOutput {
            exit_code: output.status.code().unwrap_or(EXIT_VERIFY_FAIL as i32),
            stdout: String::from_utf8_lossy(&output.stdout).to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        })
    }
}

fn discover_repo_root() -> Result<PathBuf, String> {
    let mut dir = std::env::current_dir().map_err(|e| format!("read current directory: {e}"))?;
    loop {
        if dir
            .join("implementations/rust/sugar-cli/Cargo.toml")
            .is_file()
            && dir
                .join("implementations/rust/libsugar/Cargo.toml")
                .is_file()
        {
            return Ok(dir);
        }
        if !dir.pop() {
            return Err("could not discover sugar repository root".to_string());
        }
    }
}

fn print_human(receipt: &ReleaseGateReceipt) {
    println!("Sugar release-gate");
    for target in &receipt.targets {
        let status = if target.release_ready {
            "ready"
        } else {
            "blocked"
        };
        println!(
            "target: {} ({}) K={} residue={} tierToClose={} rawUnproven={}",
            target.name,
            status,
            target.evidence.k_panic_safe,
            target.evidence.residue.residue,
            target.evidence.residue.tier_to_close,
            target.evidence.residue.raw_unproven
        );
    }
    println!("releaseReady: {}", receipt.release_ready);
}

fn receipt_json(receipt: &ReleaseGateReceipt) -> Value {
    json!({
        "releaseReady": receipt.release_ready,
        "targets": receipt.targets.iter().map(target_json).collect::<Vec<_>>(),
        "failures": receipt.failures.iter().map(|failure| {
            json!({
                "target": failure.target,
                "command": failure.command,
                "reason": failure.reason,
            })
        }).collect::<Vec<_>>(),
    })
}

fn target_json(target: &TargetReceipt) -> Value {
    json!({
        "name": target.name,
        "path": target.path,
        "releaseReady": target.release_ready,
        "doctor": command_json(&target.doctor),
        "selfCheck": command_json(&target.self_check),
        "evidence": {
            "kPanicSafe": target.evidence.k_panic_safe,
            "floor": floor_json(&target.evidence.floor),
            "residue": {
                "residue": target.evidence.residue.residue,
                "tierToClose": target.evidence.residue.tier_to_close,
                "rawUnproven": target.evidence.residue.raw_unproven,
            },
            "doctorChecks": target.evidence.doctor_checks.iter().map(|check| {
                json!({
                    "name": check.name,
                    "status": check.status,
                    "detail": check.detail,
                })
            }).collect::<Vec<_>>(),
        },
        "floorReport": doctor_report_json(&target.floor_report),
    })
}

fn command_json(command: &GateCommandReceipt) -> Value {
    json!({
        "command": command.command,
        "ok": command.ok,
        "exitCode": command.exit_code,
        "stdoutJson": command.stdout_json,
        "stderr": command.stderr,
    })
}

fn floor_json(floor: &FloorSignals) -> Value {
    json!({
        "silentlyDropped": floor.silently_dropped,
        "falsePass": floor.false_pass,
        "droppedSites": floor.dropped_sites_count,
        "panicCensusUnnamed": floor.panic_census_unnamed_count,
        "monoidFoldCarrierEmbeddingGaps": &floor.monoid_fold_gaps_by_element_type,
        "algebraGapsByBoundary": &floor.algebra_gaps_by_boundary,
        "totalCallsites": floor.total_callsites,
        "dischargeSplitPresent": floor.discharge_split_present,
    })
}

fn doctor_report_json(report: &DoctorReport) -> Value {
    json!({
        "mode": report.mode.as_str(),
        "ok": report.ok,
        "releaseReady": report.release_ready,
        "checks": report.checks.iter().map(|check| {
            json!({
                "id": check.id,
                "name": check.name,
                "status": check.status.as_str(),
                "severity": severity_as_str(&check.severity),
                "domain": check.domain,
                "detail": check.detail,
                "evidence": check.evidence,
            })
        }).collect::<Vec<_>>(),
    })
}

fn severity_as_str(severity: &CheckSeverity) -> &'static str {
    match severity {
        CheckSeverity::Advisory => "advisory",
        CheckSeverity::Hard => "hard",
    }
}
