// SPDX-License-Identifier: Apache-2.0
//
// Build the runtime solver registry from a parsed SolversConfig.
// Maps each `[solvers.<name>]` block to one of:
//
//   * StubSolver           - when `binary = "stub:..."`.
//   * CoqSubprocessSolver  - when `ir_compiler = "coq"` (or, for
//                            forward compat, the `sugar-ir-compiler-coq`
//                            DIALECT constant). Coq is a non-SMT solver:
//                            it reads IR-JSON, compiles to Coq via
//                            `CoqCompiler`, and runs `coqc` on the
//                            generated `.v` file.
//   * MaudeSubprocessSolver - when `ir_compiler = "maude"`.
//                            It compiles equational theory obligations
//                            and trusts reduce only when the CeTA gate
//                            accepts termination and confluence.
//   * SubprocessSolver     - default. Generic SMT-LIB v2.6 driver
//                            (Z3, cvc5, bitwuzla, MathSAT, ...).
//
// The Coq branch makes Coq a real producer in the multi-solver
// portfolio rather than a compile-time-only translator. Three-way
// consensus (z3 + cvc5 + coq) is now a registry-resolvable plan.
//
// Spec: protocol/specs/2026-05-02-multi-solver-protocol-v2.md
//       (Coq's seat in `Portfolio { consensus, coverage_required: true }`).
// Note: this file ships the registry seat. Consensus coverage policy
// and opacity manifests are handled by the compiler and runner layers.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use sugar_ir_compiler_coq::DIALECT as COQ_DIALECT;
use sugar_ir_compiler_lean::DIALECT as LEAN_DIALECT;
use sugar_ir_compiler_maude::DIALECT as MAUDE_DIALECT;

use crate::solvers::{
    CetaGateConfig, CoqSubprocessSolver, LeanSubprocessSolver, MaudeSubprocessSolver, SolverConfig,
    SolverHandle, SolversConfig, StubSolver, SubprocessSolver,
};

pub fn build(cfg: &SolversConfig) -> HashMap<String, SolverHandle> {
    let mut out: HashMap<String, SolverHandle> = HashMap::new();
    for (name, sc) in &cfg.solvers {
        out.insert(name.clone(), build_one(name, sc));
    }
    out
}

/// Returns true if the configured `ir_compiler` selects the Coq
/// pipeline. Accepts the canonical `coq` value alongside the
/// dialect constant exported by `sugar-ir-compiler-coq` so that
/// renaming the dialect at the compiler crate is the only edit
/// required.
fn is_coq_compiler(ir_compiler: &str) -> bool {
    ir_compiler == "coq" || ir_compiler == COQ_DIALECT
}

fn is_maude_compiler(ir_compiler: &str) -> bool {
    ir_compiler == "maude" || ir_compiler == MAUDE_DIALECT
}

fn is_lean_compiler(ir_compiler: &str) -> bool {
    ir_compiler == "lean" || ir_compiler == LEAN_DIALECT
}

/// Backstop solver timeout when the config sets none. A PINNED obligation is a
/// closed ground consistency check — `and(out == <answer>, relation)` — which z3
/// decides in microseconds. Anything that runs for seconds is not a slow answer:
/// it is an UNPINNED / open lowering (free vars, nonlinear, deep string theory)
/// that left the solver an open search. We cap it so such a query returns a
/// loudly-bounded Undecidable instead of hanging forever (the old `None`).
/// Override with `SUGAR_SOLVER_TIMEOUT_SECS` (0 = no timeout, restores `None`).
fn default_solver_timeout() -> Option<Duration> {
    // A pinned ground check is microseconds; even with z3 process startup it is
    // ~60ms. 250ms is generous headroom, so anything that hits it is an
    // unpinned/open obligation -> loudly-bounded Undecidable. SUGAR_SOLVER_TIMEOUT_MS
    // (preferred) or _SECS override; 0 disables (restores the old hang).
    if let Ok(v) = std::env::var("SUGAR_SOLVER_TIMEOUT_MS") {
        return match v.trim().parse::<u64>() {
            Ok(0) => None,
            Ok(n) => Some(Duration::from_millis(n)),
            Err(_) => Some(Duration::from_millis(250)),
        };
    }
    match std::env::var("SUGAR_SOLVER_TIMEOUT_SECS") {
        Ok(v) => match v.trim().parse::<u64>() {
            Ok(0) => None,
            Ok(n) => Some(Duration::from_secs(n)),
            Err(_) => Some(Duration::from_millis(250)),
        },
        Err(_) => Some(Duration::from_millis(250)),
    }
}

fn build_one(name: &str, sc: &SolverConfig) -> SolverHandle {
    if let Some(stub) = StubSolver::from_binary(name, &sc.binary) {
        return Arc::new(stub) as SolverHandle;
    }
    let timeout = sc
        .timeout_seconds
        .map(Duration::from_secs)
        .or_else(default_solver_timeout);
    let bin = if sc.binary.is_empty() && is_lean_compiler(&sc.ir_compiler) {
        "lake".to_string()
    } else if sc.binary.is_empty() {
        name.to_string()
    } else {
        sc.binary.clone()
    };
    if is_coq_compiler(&sc.ir_compiler) {
        return Arc::new(CoqSubprocessSolver::new(
            name,
            bin,
            sc.version.clone(),
            timeout,
        )) as SolverHandle;
    }
    if is_maude_compiler(&sc.ir_compiler) {
        return Arc::new(MaudeSubprocessSolver::new(
            name,
            bin,
            sc.version.clone(),
            timeout,
            CetaGateConfig {
                enabled: sc.ceta_gate,
                ceta_binary: sc.ceta_binary.clone(),
                termination_prover: sc.termination_prover.clone(),
                confluence_checker: sc.confluence_checker.clone(),
                timeout,
            },
        )) as SolverHandle;
    }
    if is_lean_compiler(&sc.ir_compiler) {
        return Arc::new(LeanSubprocessSolver::new(
            name,
            bin,
            sc.version.clone(),
            timeout,
            sc.lake_project.clone(),
            sc.lean_toolchain.clone(),
        )) as SolverHandle;
    }
    Arc::new(SubprocessSolver::new(
        name,
        bin,
        sc.version.clone(),
        sc.ir_compiler.clone(),
        sc.flags.clone(),
        timeout,
    )) as SolverHandle
}

/// Convenience: build a registry with a single Z3 SubprocessSolver
/// at the given binary path. Used by the legacy `RunnerConfig.z3_path`
/// fallback when no `.sugar/config.toml` is present.
///
/// A 30-second per-invocation timeout is applied as defense-in-depth.
/// Without a timeout, a Z3 invocation that reads from stdin without
/// receiving EOF (e.g. when inherited in a subprocess chain) can block
/// indefinitely.  30 s is a conservative upper bound for any SMT-LIB
/// obligation that would arise from a Sugar proof graph.
pub fn build_default_z3(z3_path: &str) -> HashMap<String, SolverHandle> {
    let mut out: HashMap<String, SolverHandle> = HashMap::new();
    out.insert(
        "z3".into(),
        Arc::new(SubprocessSolver::new(
            "z3",
            z3_path,
            "4.x",
            "smt-lib-v2.6",
            vec!["-smt2".into(), "-in".into()],
            Some(Duration::from_secs(30)),
        )) as SolverHandle,
    );
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_from_stub_config() {
        let toml = r#"
[solvers]
default = "stubA"
[solvers.stubA]
binary = "stub:unsat"
"#;
        let c = SolversConfig::from_toml(toml).unwrap();
        let r = build(&c);
        assert!(r.contains_key("stubA"));
        let s = r.get("stubA").unwrap();
        let res = s.solve("");
        assert_eq!(res.verdict, crate::types::ObligationVerdict::Discharged);
    }

    #[test]
    fn default_z3_built() {
        let r = build_default_z3("/usr/bin/z3");
        assert!(r.contains_key("z3"));
        assert_eq!(r.get("z3").unwrap().name(), "z3");
    }

    #[test]
    fn build_recognizes_coq_ir_compiler() {
        // When `ir_compiler = "coq"` the registry must instantiate
        // CoqSubprocessSolver, NOT a generic SMT-LIB SubprocessSolver
        // pointed at coqc (which would silently fail because Coq does
        // not speak SMT-LIB).
        //
        // The empirical assertion is by ir_compiler tag: the Coq
        // solver reports DIALECT as its ir_compiler tag, while the
        // generic subprocess solver reports the configured one
        // (which here would be "coq" round-tripped). They happen to
        // be equal strings, so we additionally probe behavior: the
        // Coq solver returns Undecidable with a parse error when
        // handed SMT-LIB instead of IR-JSON; the SMT subprocess
        // solver returns a binary-not-found error. We assert the
        // Coq error path.
        let toml = r#"
[solvers]
default = "coq"
[solvers.coq]
binary = "coqc"
ir_compiler = "coq"
"#;
        let c = SolversConfig::from_toml(toml).unwrap();
        let r = build(&c);
        let s = r.get("coq").expect("coq registered");
        assert_eq!(s.ir_compiler(), "coq");
        // Hand the solver SMT-LIB. CoqSubprocessSolver expects
        // IR-JSON, so this MUST return Undecidable with a JSON parse
        // error, never a "binary not found" error from the SMT
        // subprocess driver. This is the load-bearing assertion: if
        // the registry built a SubprocessSolver instead of a
        // CoqSubprocessSolver, the error message would mention spawn
        // failure on `coqc`, not JSON parsing.
        let res = s.solve("(check-sat)");
        assert_eq!(res.verdict, crate::types::ObligationVerdict::Undecidable);
        assert!(
            res.error.contains("parse IR-JSON") || res.error.contains("IR-JSON"),
            "expected IR-JSON parse error from CoqSubprocessSolver, got: {}",
            res.error
        );
    }

    #[test]
    fn build_recognizes_lean_ir_compiler() {
        let toml = r#"
[solvers]
default = "lean"
[solvers.lean]
binary = "lake"
ir_compiler = "lean"
"#;
        let c = SolversConfig::from_toml(toml).unwrap();
        let r = build(&c);
        let s = r.get("lean").expect("lean registered");
        assert_eq!(s.ir_compiler(), "lean");
        let res = s.solve("(check-sat)");
        assert_eq!(res.verdict, crate::types::ObligationVerdict::Undecidable);
        assert!(
            res.error.contains("parse IR-JSON") || res.error.contains("IR-JSON"),
            "expected IR-JSON parse error from LeanSubprocessSolver, got: {}",
            res.error
        );
    }

    #[test]
    fn build_recognizes_default_workspace_portfolio() {
        // Closes #251 (cvc5) + #252 Tier 1 (Vampire).
        //
        // Reads the canonical `.sugar/config.toml` from the repo
        // root (computed from CARGO_MANIFEST_DIR) and asserts that the
        // file parses cleanly and registers all five default-portfolio
        // solvers with the right ir_compiler tags. This is a
        // registry-build smoke test only: it does not spawn any solver
        // binary, so it passes even on hosts that lack
        // cvc5/vampire/coqc on PATH (which is the whole point of the
        // first-wins mode in the default config).
        //
        // Closes #296: the prior version parsed an inline TOML string
        // instead of the actual file, letting the repo config drift
        // without test signal.
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .ancestors()
            .nth(3)
            .expect("could not find repository root");
        let config_path = root.join(".sugar").join("config.toml");
        let body = std::fs::read_to_string(&config_path)
            .unwrap_or_else(|e| panic!("could not read {}: {e}", config_path.display()));
        let c = SolversConfig::from_toml(&body).expect("config parses");
        let r = build(&c);

        // All six seats register.
        for name in ["z3", "cvc5", "vampire", "coq", "maude", "lean"] {
            assert!(r.contains_key(name), "{name} seat missing from registry");
        }

        // SMT seats route to the generic SubprocessSolver
        // (ir_compiler tag round-trips as "smt-lib-v2.6").
        for name in ["z3", "cvc5", "vampire"] {
            let s = r.get(name).unwrap();
            assert_eq!(s.name(), name);
            assert_eq!(
                s.ir_compiler(),
                "smt-lib-v2.6",
                "{name} should route to the SMT-LIB SubprocessSolver",
            );
        }

        // Coq seat routes to CoqSubprocessSolver. The Coq solver's
        // ir_compiler() tag is COQ_DIALECT ("coq"), and (per
        // `build_recognizes_coq_ir_compiler`) handing it SMT-LIB MUST
        // surface an IR-JSON parse error rather than a binary-spawn
        // error. We only check the tag here; the load-bearing
        // dispatch assertion already lives in the dedicated test
        // above.
        let coq = r.get("coq").unwrap();
        assert_eq!(coq.ir_compiler(), "coq");
        let maude = r.get("maude").unwrap();
        assert_eq!(maude.ir_compiler(), "maude");
        let lean = r.get("lean").unwrap();
        assert_eq!(lean.ir_compiler(), "lean");
    }

    #[test]
    fn build_keeps_smt_solvers_for_non_coq_ir_compiler() {
        // Sanity check: an `ir_compiler = "smt-lib-v2.6"` solver is
        // still built as a SubprocessSolver. This confirms the Coq
        // branch is selective rather than capturing every entry.
        let toml = r#"
[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
"#;
        let c = SolversConfig::from_toml(toml).unwrap();
        let r = build(&c);
        let s = r.get("z3").expect("z3 registered");
        assert_eq!(s.ir_compiler(), "smt-lib-v2.6");
    }
}
