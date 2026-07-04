// SPDX-License-Identifier: MIT OR Apache-2.0
//
// CeTA certificate gate for Maude reduce results.

use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde::Serialize;
use sugar_canonicalizer::blake3_512_of;
use sugar_ir_compiler_maude::TrsSpec;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CetaDecision {
    Accepted,
    Rejected,
}

#[derive(Debug, Clone)]
pub struct CetaGateConfig {
    pub enabled: bool,
    pub ceta_binary: String,
    pub termination_prover: String,
    pub confluence_checker: String,
    pub timeout: Option<Duration>,
}

impl Default for CetaGateConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            ceta_binary: "ceta".to_string(),
            termination_prover: "aprove".to_string(),
            confluence_checker: "csi".to_string(),
            timeout: Some(Duration::from_secs(60)),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct CetaGateReceipt {
    pub termination_cert_cid: Option<String>,
    pub confluence_cert_cid: Option<String>,
    pub ceta_accepted: bool,
    pub bypassed: bool,
    pub error: String,
}

#[derive(Debug, Clone)]
pub struct CetaGateResult {
    pub receipt: CetaGateReceipt,
    pub stdout: String,
    pub timed_out: bool,
}

#[derive(Debug, Clone)]
pub struct CommandCapture {
    pub status_success: bool,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
    pub timed_out: bool,
}

pub struct CetaGate {
    config: CetaGateConfig,
}

impl CetaGate {
    pub fn new(config: CetaGateConfig) -> Self {
        Self { config }
    }

    pub fn check(&self, trs: &TrsSpec) -> CetaGateResult {
        if trs.rules.is_empty() {
            return CetaGateResult {
                receipt: CetaGateReceipt {
                    termination_cert_cid: None,
                    confluence_cert_cid: None,
                    ceta_accepted: true,
                    bypassed: true,
                    error: "no user equations require a TRS gate".to_string(),
                },
                stdout: String::new(),
                timed_out: false,
            };
        }
        if !self.config.enabled {
            return CetaGateResult {
                receipt: CetaGateReceipt {
                    termination_cert_cid: None,
                    confluence_cert_cid: None,
                    ceta_accepted: false,
                    bypassed: false,
                    error: "ceta gate disabled".to_string(),
                },
                stdout: String::new(),
                timed_out: false,
            };
        }
        self.run_external_gate(trs)
    }

    fn run_external_gate(&self, trs: &TrsSpec) -> CetaGateResult {
        let started = Instant::now();
        let tmp_dir = std::env::temp_dir().join(format!(
            "sugar-ceta-{}-{}",
            std::process::id(),
            started.elapsed().as_nanos()
        ));
        if let Err(e) = fs::create_dir_all(&tmp_dir) {
            return gate_error(format!("ceta: create temp dir: {e}"), false);
        }

        let trs_file = tmp_dir.join("system.trs");
        let trs_body = emit_wst(trs);
        if let Err(e) = fs::write(&trs_file, trs_body) {
            let _ = fs::remove_dir_all(&tmp_dir);
            return gate_error(format!("ceta: write TRS input: {e}"), false);
        }

        let term = run_command_capture(
            &self.config.termination_prover,
            &[trs_file.to_string_lossy().as_ref()],
            self.config.timeout,
        );
        let term = match term {
            Ok(c) if c.status_success => c,
            Ok(c) => {
                let _ = fs::remove_dir_all(&tmp_dir);
                return gate_error(command_error("termination prover", &c), c.timed_out);
            }
            Err(e) => {
                let _ = fs::remove_dir_all(&tmp_dir);
                return gate_error(format!("termination prover: {e}"), false);
            }
        };
        let term_cert = tmp_dir.join("termination.cpf");
        if let Err(e) = fs::write(&term_cert, &term.stdout) {
            let _ = fs::remove_dir_all(&tmp_dir);
            return gate_error(format!("ceta: write termination certificate: {e}"), false);
        }

        let conf = run_command_capture(
            &self.config.confluence_checker,
            &[trs_file.to_string_lossy().as_ref()],
            self.config.timeout,
        );
        let conf = match conf {
            Ok(c) if c.status_success => c,
            Ok(c) => {
                let _ = fs::remove_dir_all(&tmp_dir);
                return gate_error(command_error("confluence checker", &c), c.timed_out);
            }
            Err(e) => {
                let _ = fs::remove_dir_all(&tmp_dir);
                return gate_error(format!("confluence checker: {e}"), false);
            }
        };
        let conf_cert = tmp_dir.join("confluence.cpf");
        if let Err(e) = fs::write(&conf_cert, &conf.stdout) {
            let _ = fs::remove_dir_all(&tmp_dir);
            return gate_error(format!("ceta: write confluence certificate: {e}"), false);
        }

        let term_check = verify_with_ceta(&self.config, &term_cert);
        let conf_check = verify_with_ceta(&self.config, &conf_cert);
        let mut stdout = String::new();
        let term_ok = match term_check {
            Ok((decision, out, timed_out)) => {
                stdout.push_str(&out);
                decision == CetaDecision::Accepted && !timed_out
            }
            Err(e) => {
                let _ = fs::remove_dir_all(&tmp_dir);
                return gate_error(e, false);
            }
        };
        let conf_ok = match conf_check {
            Ok((decision, out, timed_out)) => {
                stdout.push_str(&out);
                decision == CetaDecision::Accepted && !timed_out
            }
            Err(e) => {
                let _ = fs::remove_dir_all(&tmp_dir);
                return gate_error(e, false);
            }
        };

        let receipt = CetaGateReceipt {
            termination_cert_cid: Some(blake3_512_of(&term.stdout)),
            confluence_cert_cid: Some(blake3_512_of(&conf.stdout)),
            ceta_accepted: term_ok && conf_ok,
            bypassed: false,
            error: if term_ok && conf_ok {
                String::new()
            } else {
                "ceta rejected at least one certificate".to_string()
            },
        };
        let timed_out = term.timed_out || conf.timed_out;
        let _ = fs::remove_dir_all(&tmp_dir);
        CetaGateResult {
            receipt,
            stdout,
            timed_out,
        }
    }
}

pub fn parse_ceta_output(stdout: &str) -> Result<CetaDecision, String> {
    let lower = stdout.to_ascii_lowercase();
    if lower.lines().any(|line| {
        let trimmed = line.trim();
        trimmed == "yes"
            || trimmed == "accepted"
            || trimmed.contains("certificate accepted")
            || trimmed.contains("proof accepted")
    }) {
        return Ok(CetaDecision::Accepted);
    }
    if lower.lines().any(|line| {
        let trimmed = line.trim();
        trimmed == "no"
            || trimmed == "rejected"
            || trimmed.contains("invalid")
            || trimmed.contains("error")
            || trimmed.contains("failed")
    }) {
        return Ok(CetaDecision::Rejected);
    }
    Ok(CetaDecision::Rejected)
}

pub fn emit_wst(trs: &TrsSpec) -> String {
    let mut out = String::new();
    out.push_str("(VAR");
    for variable in &trs.variables {
        out.push(' ');
        out.push_str(variable);
    }
    out.push_str(")\n(RULES\n");
    for rule in &trs.rules {
        out.push_str("  ");
        out.push_str(&rule.lhs);
        out.push_str(" -> ");
        out.push_str(&rule.rhs);
        out.push('\n');
    }
    out.push_str(")\n");
    out
}

pub fn run_command_capture(
    binary: &str,
    args: &[&str],
    timeout: Option<Duration>,
) -> Result<CommandCapture, String> {
    let started = Instant::now();
    let mut command = Command::new(binary);
    command.args(args);
    command.stdin(Stdio::null());
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|e| format!("spawn {binary}: {e}"))?;

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
                        return Ok(CommandCapture {
                            status_success: false,
                            stdout: Vec::new(),
                            stderr: format!("timeout after {}s", to.as_secs().max(1)).into_bytes(),
                            timed_out: true,
                        });
                    }
                    std::thread::sleep(Duration::from_millis(20));
                }
                Err(e) => return Err(format!("wait {binary}: {e}")),
            }
        }
    } else {
        timed_out = false;
    }

    let output = child
        .wait_with_output()
        .map_err(|e| format!("wait {binary}: {e}"))?;
    Ok(CommandCapture {
        status_success: output.status.success(),
        stdout: output.stdout,
        stderr: output.stderr,
        timed_out,
    })
}

fn verify_with_ceta(
    config: &CetaGateConfig,
    cert_path: &Path,
) -> Result<(CetaDecision, String, bool), String> {
    let cert = cert_path.to_string_lossy();
    let capture = run_command_capture(&config.ceta_binary, &[cert.as_ref()], config.timeout)?;
    let mut out = String::from_utf8_lossy(&capture.stdout).to_string();
    out.push_str(&String::from_utf8_lossy(&capture.stderr));
    Ok((parse_ceta_output(&out)?, out, capture.timed_out))
}

fn gate_error(error: String, timed_out: bool) -> CetaGateResult {
    CetaGateResult {
        receipt: CetaGateReceipt {
            termination_cert_cid: None,
            confluence_cert_cid: None,
            ceta_accepted: false,
            bypassed: false,
            error,
        },
        stdout: String::new(),
        timed_out,
    }
}

fn command_error(label: &str, capture: &CommandCapture) -> String {
    let stderr = String::from_utf8_lossy(&capture.stderr);
    let stdout = String::from_utf8_lossy(&capture.stdout);
    format!("{label} failed: {stderr}{stdout}")
}
