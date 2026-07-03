// SPDX-License-Identifier: Apache-2.0
//
// Maude subprocess solver for equational theory obligations.

use std::fs;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde::Serialize;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_ir_compiler::CompiledFormula;
use sugar_ir_compiler_maude::{MaudeQueries, TrsSpec, DIALECT};

use crate::solvers::ceta::{run_command_capture, CetaGate, CetaGateConfig, CetaGateReceipt};
use crate::solvers::{SolveResult, Solver, SolverExitKind, SolverExitMetadata, SolverIdentity};
use crate::types::ObligationVerdict;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MaudeDecision {
    ReduceEqual,
    SearchSolution,
    NoMatch,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedMaudeOutput {
    pub normal_forms: Vec<String>,
    pub decision: MaudeDecision,
}

#[derive(Debug, Serialize)]
struct MaudeVerdictReceipt {
    maude_version: String,
    module_cid: String,
    queries: MaudeQueriesReceipt,
    normal_forms: Vec<String>,
    decision: MaudeDecision,
    verdict: String,
}

#[derive(Debug, Serialize)]
struct MaudeQueriesReceipt {
    lhs_reduce: String,
    rhs_reduce: String,
    search: String,
}

#[derive(Debug, Serialize)]
struct MaudeReceipt {
    maude_verdict: MaudeVerdictReceipt,
    ceta_gate: CetaGateReceipt,
}

#[derive(Debug)]
pub struct MaudeSubprocessSolver {
    name: String,
    version: String,
    binary: String,
    timeout: Option<Duration>,
    ceta_config: CetaGateConfig,
    identity: SolverIdentity,
}

impl MaudeSubprocessSolver {
    pub fn new(
        name: impl Into<String>,
        binary: impl Into<String>,
        version: impl Into<String>,
        timeout: Option<Duration>,
        ceta_config: CetaGateConfig,
    ) -> Self {
        Self {
            name: name.into(),
            version: version.into(),
            binary: binary.into(),
            timeout,
            ceta_config,
            identity: SolverIdentity::default(),
        }
    }

    pub fn with_identity(mut self, identity: SolverIdentity) -> Self {
        self.identity = identity;
        self
    }
}

impl Solver for MaudeSubprocessSolver {
    fn name(&self) -> &str {
        &self.name
    }

    fn version(&self) -> &str {
        &self.version
    }

    fn ir_compiler(&self) -> &str {
        DIALECT
    }

    fn identity(&self) -> SolverIdentity {
        self.identity.clone()
    }

    fn solve(&self, _input: &str) -> SolveResult {
        let started = Instant::now();
        unknown_result(
            &self.name,
            &self.version,
            started,
            false,
            "maude: compiled metadata missing; route ProofIR through the IR compiler registry"
                .to_string(),
            String::new(),
        )
    }

    fn solve_compiled(&self, compiled: &CompiledFormula) -> SolveResult {
        let started = Instant::now();
        let (queries, trs) = match maude_metadata(compiled) {
            Ok(metadata) => metadata,
            Err(e) => {
                return unknown_result(&self.name, &self.version, started, false, e, String::new());
            }
        };

        let full_source = compiled.script();
        let module_cid = module_cid(&full_source);
        let maude_version =
            read_maude_version(&self.binary).unwrap_or_else(|_| self.version.clone());
        let ceta_gate = CetaGate::new(self.ceta_config.clone());

        let maude_source = full_source.clone();
        let maude_binary = self.binary.clone();
        let maude_timeout = self.timeout;
        let (maude_run, ceta_result) = std::thread::scope(|scope| {
            let maude_handle =
                scope.spawn(|| run_maude_file(&maude_binary, &maude_source, maude_timeout));
            let ceta_handle = scope.spawn(|| ceta_gate.check(&trs));
            let maude_run = maude_handle
                .join()
                .unwrap_or_else(|_| Err("maude worker panicked".to_string()));
            let ceta_result =
                ceta_handle
                    .join()
                    .unwrap_or_else(|_| crate::solvers::ceta::CetaGateResult {
                        receipt: CetaGateReceipt {
                            termination_cert_cid: None,
                            confluence_cert_cid: None,
                            ceta_accepted: false,
                            bypassed: false,
                            error: "ceta worker panicked".to_string(),
                        },
                        stdout: String::new(),
                        timed_out: false,
                    });
            (maude_run, ceta_result)
        });

        let capture = match maude_run {
            Ok(c) if c.status_success => c,
            Ok(c) => {
                let receipt = build_receipt(
                    &maude_version,
                    &module_cid,
                    &queries,
                    Vec::new(),
                    MaudeDecision::NoMatch,
                    ObligationVerdict::Undecidable,
                    ceta_result.receipt,
                );
                return unknown_result(
                    &self.name,
                    &self.version,
                    started,
                    c.timed_out,
                    format!("maude failed: {}", String::from_utf8_lossy(&c.stderr)),
                    receipt,
                );
            }
            Err(e) => {
                let receipt = build_receipt(
                    &maude_version,
                    &module_cid,
                    &queries,
                    Vec::new(),
                    MaudeDecision::NoMatch,
                    ObligationVerdict::Undecidable,
                    ceta_result.receipt,
                );
                return unknown_result(&self.name, &self.version, started, false, e, receipt);
            }
        };

        let mut stdout = String::from_utf8_lossy(&capture.stdout).to_string();
        stdout.push_str(&String::from_utf8_lossy(&capture.stderr));
        let parsed = match parse_maude_output(&stdout) {
            Ok(p) => p,
            Err(e) => {
                let receipt = build_receipt(
                    &maude_version,
                    &module_cid,
                    &queries,
                    Vec::new(),
                    MaudeDecision::NoMatch,
                    ObligationVerdict::Undecidable,
                    ceta_result.receipt,
                );
                return unknown_result(&self.name, &self.version, started, false, e, receipt);
            }
        };

        let verdict = match parsed.decision {
            MaudeDecision::SearchSolution => ObligationVerdict::Discharged,
            MaudeDecision::ReduceEqual if ceta_result.receipt.ceta_accepted => {
                ObligationVerdict::Discharged
            }
            MaudeDecision::ReduceEqual | MaudeDecision::NoMatch => ObligationVerdict::Undecidable,
        };
        let error = match (parsed.decision, verdict) {
            (MaudeDecision::ReduceEqual, ObligationVerdict::Undecidable) => {
                "maude reduce result discarded because ceta gate did not accept".to_string()
            }
            (MaudeDecision::NoMatch, _) => "maude returned no entailment witness".to_string(),
            _ => String::new(),
        };
        let receipt = build_receipt(
            &maude_version,
            &module_cid,
            &queries,
            parsed.normal_forms,
            parsed.decision,
            verdict,
            ceta_result.receipt,
        );

        let timed_out = capture.timed_out || ceta_result.timed_out;
        SolveResult::with_evidence(
            verdict,
            self.name.clone(),
            self.version.clone(),
            SolverExitMetadata::new(if error.is_empty() {
                SolverExitKind::Ok
            } else {
                SolverExitKind::NonZeroExit
            }),
            (!error.is_empty()).then_some(error),
            Some(receipt),
            None,
            started.elapsed(),
            timed_out,
        )
    }
}

pub fn parse_maude_output(stdout: &str) -> Result<ParsedMaudeOutput, String> {
    let mut normal_forms = Vec::new();
    let mut saw_solution = false;
    for line in stdout.lines() {
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix("result ") {
            if let Some((_, normal)) = rest.split_once(':') {
                normal_forms.push(normal.trim().to_string());
            }
        }
        let lower = trimmed.to_ascii_lowercase();
        if lower.starts_with("solution ") || lower == "solution" {
            saw_solution = true;
        }
    }
    if normal_forms.len() >= 2 && normal_forms[0] == normal_forms[1] {
        return Ok(ParsedMaudeOutput {
            normal_forms,
            decision: MaudeDecision::ReduceEqual,
        });
    }
    if saw_solution {
        return Ok(ParsedMaudeOutput {
            normal_forms,
            decision: MaudeDecision::SearchSolution,
        });
    }
    Ok(ParsedMaudeOutput {
        normal_forms,
        decision: MaudeDecision::NoMatch,
    })
}

fn run_maude_file(
    binary: &str,
    source: &str,
    timeout: Option<Duration>,
) -> Result<crate::solvers::ceta::CommandCapture, String> {
    let started = Instant::now();
    let tmp_dir = std::env::temp_dir().join(format!(
        "sugar-maude-{}-{}",
        std::process::id(),
        started.elapsed().as_nanos()
    ));
    fs::create_dir_all(&tmp_dir).map_err(|e| format!("maude: create temp dir: {e}"))?;
    let path = tmp_dir.join("obligation.maude");
    fs::write(&path, source).map_err(|e| format!("maude: write module file: {e}"))?;
    let path_str = path.to_string_lossy();
    let result = run_command_capture(binary, &[path_str.as_ref()], timeout);
    let _ = fs::remove_dir_all(&tmp_dir);
    result
}

fn read_maude_version(binary: &str) -> Result<String, String> {
    let output = Command::new(binary)
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("maude --version: {e}"))?;
    let mut text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if text.is_empty() {
        text = String::from_utf8_lossy(&output.stderr).trim().to_string();
    }
    if text.is_empty() {
        Err("maude --version returned no output".to_string())
    } else {
        Ok(text)
    }
}

fn module_cid(source: &str) -> String {
    let value = Value::string(source.to_string());
    let canonical = encode_jcs(&value);
    blake3_512_of(canonical.as_bytes())
}

fn maude_metadata(compiled: &CompiledFormula) -> Result<(MaudeQueries, TrsSpec), String> {
    let maude = compiled
        .metadata
        .get("maude")
        .ok_or_else(|| "maude: compiler metadata missing `maude` object".to_string())?;
    let queries = maude
        .get("queries")
        .cloned()
        .ok_or_else(|| "maude: compiler metadata missing `maude.queries`".to_string())
        .and_then(|value| {
            serde_json::from_value::<MaudeQueries>(value)
                .map_err(|e| format!("maude: decode compiler metadata queries: {e}"))
        })?;
    let trs = maude
        .get("trs")
        .cloned()
        .ok_or_else(|| "maude: compiler metadata missing `maude.trs`".to_string())
        .and_then(|value| {
            serde_json::from_value::<TrsSpec>(value)
                .map_err(|e| format!("maude: decode compiler metadata trs: {e}"))
        })?;
    Ok((queries, trs))
}

fn build_receipt(
    maude_version: &str,
    module_cid: &str,
    queries: &MaudeQueries,
    normal_forms: Vec<String>,
    decision: MaudeDecision,
    verdict: ObligationVerdict,
    ceta_gate: CetaGateReceipt,
) -> String {
    let receipt = MaudeReceipt {
        maude_verdict: MaudeVerdictReceipt {
            maude_version: maude_version.to_string(),
            module_cid: module_cid.to_string(),
            queries: MaudeQueriesReceipt {
                lhs_reduce: queries.lhs_reduce.clone(),
                rhs_reduce: queries.rhs_reduce.clone(),
                search: queries.search.clone(),
            },
            normal_forms,
            decision,
            verdict: verdict.as_str().to_string(),
        },
        ceta_gate,
    };
    serde_json::to_string(&receipt).unwrap_or_else(|e| format!(r#"{{"receipt_error":"{e}"}}"#))
}

fn unknown_result(
    name: &str,
    version: &str,
    started: Instant,
    timed_out: bool,
    error: String,
    solver_stdout: String,
) -> SolveResult {
    SolveResult::with_evidence(
        ObligationVerdict::Undecidable,
        name.to_string(),
        version.to_string(),
        SolverExitMetadata::new(if timed_out {
            SolverExitKind::Timeout
        } else {
            SolverExitKind::CompileError
        }),
        Some(error),
        Some(solver_stdout),
        None,
        started.elapsed(),
        timed_out,
    )
}
