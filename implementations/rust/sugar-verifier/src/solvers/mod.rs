// SPDX-License-Identifier: Apache-2.0
//
// Multi-solver subsystem for the verifier.
//
// Replaces the previous one-shot Z3 subprocess invocation with a
// pluggable Solver trait. Three concrete impls ship in-tree:
//
//   * SubprocessSolver  - generic SMT-LIB v2.6 subprocess driver
//                         (Z3, cvc5, bitwuzla, MathSAT, ...).
//   * StubSolver        - deterministic verdict + optional delay,
//                         used by tests and by the multi-solver demo
//                         so CI passes without any solver binaries
//                         installed.
//
// Composition over solvers is expressed by `SolverPlan`, derived from
// `.sugar/config.toml` (see `config.rs`). The plan is one of:
//
//   * Single (default)            - invoke one solver.
//   * Chain                       - sequential fall-through; first
//                                   definitive verdict wins.
//   * Portfolio { first-wins }    - parallel via rayon; first
//                                   definitive verdict wins; remaining
//                                   solvers are best-effort cancelled.
//   * Portfolio { consensus }     - parallel via rayon; ALL definitive
//                                   verdicts must agree, otherwise
//                                   `ObligationVerdict::Disagreement`
//                                   is reported and a "verdict-
//                                   disagreement" event is logged.
//   * Dispatch                    - inspect the formula and pick the
//                                   matching solver for that fragment.

pub mod batch;
pub mod ceta;
pub mod config;
pub mod coq;
pub mod dispatch;
pub mod lean;
pub mod maude;
pub mod model;
pub mod plan;
pub mod registry;
pub mod stub;
pub mod subprocess;

use std::sync::Arc;
use std::time::Duration;

use serde_json::Value as Json;
use sugar_ir_compiler::CompiledFormula;
use sugar_ir_compiler::FrontendErrorPayload;

use crate::types::ObligationVerdict;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SolverExitKind {
    Ok,
    SpawnError,
    StdinError,
    Timeout,
    WaitError,
    NonZeroExit,
    UnrecognizedVerdict,
    UnsupportedLowering,
    CompileError,
    FrontendDecodeError,
    Stub,
}

impl SolverExitKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            SolverExitKind::Ok => "ok",
            SolverExitKind::SpawnError => "spawn-error",
            SolverExitKind::StdinError => "stdin-error",
            SolverExitKind::Timeout => "timeout",
            SolverExitKind::WaitError => "wait-error",
            SolverExitKind::NonZeroExit => "non-zero-exit",
            SolverExitKind::UnrecognizedVerdict => "unrecognized-verdict",
            SolverExitKind::UnsupportedLowering => "unsupported-lowering",
            SolverExitKind::CompileError => "compile-error",
            SolverExitKind::FrontendDecodeError => "frontend-decode-error",
            SolverExitKind::Stub => "stub",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SolverExitMetadata {
    pub kind: SolverExitKind,
    pub code: Option<i32>,
    pub timed_out: bool,
    pub diagnostic_cid: Option<String>,
    pub frontend_error: Option<FrontendErrorPayload>,
}

impl SolverExitMetadata {
    pub fn new(kind: SolverExitKind) -> Self {
        Self {
            kind,
            code: None,
            timed_out: false,
            diagnostic_cid: None,
            frontend_error: None,
        }
    }

    pub fn with_code(mut self, code: Option<i32>) -> Self {
        self.code = code;
        self
    }

    pub fn with_frontend_error(mut self, payload: FrontendErrorPayload) -> Self {
        self.frontend_error = Some(payload);
        self
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SolverEvidenceSidecar {
    pub cid: String,
    pub byte_len: usize,
    content: String,
}

impl SolverEvidenceSidecar {
    pub fn from_text(text: String) -> Option<Self> {
        if text.is_empty() {
            return None;
        }
        Some(Self {
            cid: sugar_canonicalizer::blake3_512_of(text.as_bytes()),
            byte_len: text.len(),
            content: text,
        })
    }

    pub fn text(&self) -> &str {
        &self.content
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SolverEvidence {
    pub stdout: Option<SolverEvidenceSidecar>,
    pub stderr: Option<SolverEvidenceSidecar>,
    pub diagnostic: Option<SolverEvidenceSidecar>,
}

/// A single solver invocation outcome.
#[derive(Debug, Clone)]
pub struct SolveResult {
    pub verdict: ObligationVerdict,
    pub solver_name: String,
    pub solver_version: String,
    pub exit: SolverExitMetadata,
    pub evidence: SolverEvidence,
    pub wall_clock: Duration,
    pub timed_out: bool,
}

impl SolveResult {
    pub fn definitive(&self) -> bool {
        matches!(
            self.verdict,
            ObligationVerdict::Discharged | ObligationVerdict::Unsatisfied
        )
    }

    pub fn with_evidence(
        verdict: ObligationVerdict,
        solver_name: impl Into<String>,
        solver_version: impl Into<String>,
        mut exit: SolverExitMetadata,
        diagnostic: Option<String>,
        stdout: Option<String>,
        stderr: Option<String>,
        wall_clock: Duration,
        timed_out: bool,
    ) -> Self {
        exit.timed_out = timed_out;
        let diagnostic = diagnostic.and_then(SolverEvidenceSidecar::from_text);
        exit.diagnostic_cid = diagnostic.as_ref().map(|sidecar| sidecar.cid.clone());
        Self {
            verdict,
            solver_name: solver_name.into(),
            solver_version: solver_version.into(),
            exit,
            evidence: SolverEvidence {
                stdout: stdout.and_then(SolverEvidenceSidecar::from_text),
                stderr: stderr.and_then(SolverEvidenceSidecar::from_text),
                diagnostic,
            },
            wall_clock,
            timed_out,
        }
    }

    pub fn frontend_decode_error(
        solver_name: impl Into<String>,
        solver_version: impl Into<String>,
        payload: FrontendErrorPayload,
    ) -> Self {
        let diagnostic = format!("frontend decode: {payload}");
        Self::with_evidence(
            ObligationVerdict::Undecidable,
            solver_name,
            solver_version,
            SolverExitMetadata::new(SolverExitKind::FrontendDecodeError)
                .with_frontend_error(payload),
            Some(diagnostic),
            None,
            None,
            Duration::ZERO,
            false,
        )
    }

    pub fn error(&self) -> &str {
        self.evidence
            .diagnostic
            .as_ref()
            .map(SolverEvidenceSidecar::text)
            .unwrap_or("")
    }

    pub fn solver_stdout(&self) -> &str {
        self.evidence
            .stdout
            .as_ref()
            .map(SolverEvidenceSidecar::text)
            .unwrap_or("")
    }

    pub fn solver_stderr(&self) -> &str {
        self.evidence
            .stderr
            .as_ref()
            .map(SolverEvidenceSidecar::text)
            .unwrap_or("")
    }
}

/// Solver abstraction. Implementors run an SMT-LIB v2.6 script and
/// return a `SolveResult`. They MUST be `Send + Sync` so the rayon
/// portfolio can fan them out across threads.
pub trait Solver: Send + Sync {
    fn name(&self) -> &str;
    fn version(&self) -> &str;
    fn ir_compiler(&self) -> &str;
    fn identity(&self) -> SolverIdentity {
        SolverIdentity::default()
    }
    fn solve(&self, smt: &str) -> SolveResult;
    fn solve_compiled(&self, compiled: &CompiledFormula) -> SolveResult {
        self.solve(&compiled.script())
    }
}

/// Convenience type alias: trait objects come through the registry as
/// shared, cheaply-clonable handles.
pub type SolverHandle = Arc<dyn Solver>;

/// CID-addressed solver identity. Human labels (`name`, `version`) are
/// diagnostics; replay pins are CIDs. If a vendor has their own address space
/// (sha256, package-integrity, etc.), that relation is carried as a memento
/// whose own address is a Sugar CID.
#[derive(Debug, Clone, Default)]
pub struct SolverIdentity {
    pub artifact_cid: Option<String>,
    pub invocation_cid: Option<String>,
    pub vendor_memento_cid: Option<String>,
    pub vendor_memento: Option<Json>,
}

pub use ceta::{CetaGate, CetaGateConfig};
pub use config::{
    DispatchConfig, PortfolioMode, SolverConfig, SolverPlan, SolverSeat, SolversConfig,
};
pub use coq::CoqSubprocessSolver;
pub use dispatch::{classify, dispatch_for_formula, FormulaTheory};
pub use lean::LeanSubprocessSolver;
pub use maude::MaudeSubprocessSolver;
pub use plan::{run_plan, run_plan_with_compilers, SolverInvocation};
pub use stub::StubSolver;
pub use subprocess::SubprocessSolver;

#[cfg(test)]
mod telemetry_tests {
    use super::*;
    use sugar_canonicalizer::blake3_512_of;
    use sugar_ir_compiler::{FrontendErrorKind, FrontendErrorPayload};

    #[test]
    fn solve_result_pins_stdout_and_error_as_sidecar_evidence() {
        let result = SolveResult::with_evidence(
            ObligationVerdict::Undecidable,
            "z3",
            "4.13",
            SolverExitMetadata::new(SolverExitKind::UnrecognizedVerdict),
            Some("unrecognized solver verdict: maybe".to_string()),
            Some("maybe\n".to_string()),
            None,
            Duration::from_millis(7),
            false,
        );

        let stdout = result
            .evidence
            .stdout
            .as_ref()
            .expect("stdout evidence sidecar");
        assert_eq!(stdout.cid, blake3_512_of(b"maybe\n"));
        assert_eq!(stdout.byte_len, "maybe\n".len());
        assert_eq!(result.solver_stdout(), "maybe\n");

        let diagnostic = result
            .evidence
            .diagnostic
            .as_ref()
            .expect("diagnostic evidence sidecar");
        assert_eq!(
            diagnostic.cid,
            blake3_512_of(b"unrecognized solver verdict: maybe")
        );
        assert_eq!(result.error(), "unrecognized solver verdict: maybe");
        assert_eq!(
            result.exit.diagnostic_cid.as_deref(),
            Some(diagnostic.cid.as_str())
        );
    }

    #[test]
    fn frontend_decode_payload_survives_in_solve_result_telemetry() {
        let payload = FrontendErrorPayload {
            kind: FrontendErrorKind::MalformedTransport,
            frontend: "json-rpc".to_string(),
            input_format: "sugar-ir-json".to_string(),
            path: "$.kind".to_string(),
            detail: "missing kind".to_string(),
            retirement: "typed ProofIR frontend boundary".to_string(),
        };
        let result = SolveResult::frontend_decode_error("z3", "4.13", payload.clone());

        assert_eq!(result.verdict, ObligationVerdict::Undecidable);
        assert_eq!(result.exit.kind, SolverExitKind::FrontendDecodeError);
        assert_eq!(result.exit.frontend_error.as_ref(), Some(&payload));
        assert!(result.error().contains("missing kind"));
        assert!(result
            .evidence
            .diagnostic
            .as_ref()
            .expect("diagnostic evidence sidecar")
            .cid
            .starts_with("blake3-512:"));
    }
}
