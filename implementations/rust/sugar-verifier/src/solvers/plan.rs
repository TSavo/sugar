// SPDX-License-Identifier: Apache-2.0
//
// Plan execution. Given a SolverPlan + a registry of named Solvers +
// the SMT-LIB script (and optionally the IR formula for dispatch),
// run the right solvers in the right pattern and return the verdict
// alongside per-solver telemetry the report layer aggregates.

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;

use rayon::prelude::*;
use serde_json::Value as Json;
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_ir_compiler::CompiledFormula;

use crate::solvers::{
    dispatch_for_formula, PortfolioMode, SolveResult, Solver, SolverHandle, SolverIdentity,
    SolverPlan, SolverSeat,
};
use crate::types::ObligationVerdict;

/// One row of solver telemetry per call site. Multiple rows are
/// produced by Portfolio modes (one per solver). The first row in the
/// outer Vec is the row whose verdict the caller should treat as
/// authoritative; subsequent rows are best-effort companions for
/// memento minting and disagreement bookkeeping.
#[derive(Debug, Clone)]
pub struct SolverInvocation {
    pub authoritative: bool,
    pub compiler: String,
    pub identity: SolverIdentity,
    pub result: SolveResult,
}

/// Solver registry: seat -> handle. Built once at runner construction
/// from the SolversConfig.
pub type Registry = HashMap<SolverSeat, SolverHandle>;

#[derive(Clone, Copy)]
enum InputSource<'a> {
    Precompiled(&'a str),
    Compilers(&'a CompilerRegistry),
}

enum PreparedInput {
    Text(String),
    Compiled(CompiledFormula),
}

/// Executor entry point. Returns the chosen verdict + a vec of
/// per-solver invocations (each its own SolveResult). The caller
/// (runner) aggregates these into TierStats and the per-solver
/// breakdown.
pub fn run_plan(
    plan: &SolverPlan,
    registry: &Registry,
    smt_script: &str,
    formula: Option<&Json>,
) -> (ObligationVerdict, String, Vec<SolverInvocation>) {
    run_plan_inner(
        plan,
        registry,
        InputSource::Precompiled(smt_script),
        formula,
    )
}

pub fn run_plan_with_compilers(
    plan: &SolverPlan,
    registry: &Registry,
    compilers: &CompilerRegistry,
    formula: &Json,
) -> (ObligationVerdict, String, Vec<SolverInvocation>) {
    run_plan_inner(
        plan,
        registry,
        InputSource::Compilers(compilers),
        Some(formula),
    )
}

fn run_plan_inner(
    plan: &SolverPlan,
    registry: &Registry,
    source: InputSource<'_>,
    formula: Option<&Json>,
) -> (ObligationVerdict, String, Vec<SolverInvocation>) {
    match plan {
        SolverPlan::Single(name) => single(*name, registry, source, formula),
        SolverPlan::Chain(names) => chain(names, registry, source, formula),
        SolverPlan::Portfolio { names, mode } => portfolio(names, *mode, registry, source, formula),
        SolverPlan::Dispatch(d) => match formula {
            Some(f) => match dispatch_for_formula(f, d) {
                Some(n) => single(n, registry, source, formula),
                None => (
                    ObligationVerdict::Undecidable,
                    "dispatch: no matching solver and no default".into(),
                    vec![],
                ),
            },
            None => (
                ObligationVerdict::Undecidable,
                "dispatch: no formula available for theory classification".into(),
                vec![],
            ),
        },
    }
}

fn lookup(name: SolverSeat, registry: &Registry) -> Result<&Arc<dyn Solver>, String> {
    registry
        .get(&name)
        .ok_or_else(|| format!("solver '{name}' not found in registry"))
}

fn single(
    name: SolverSeat,
    registry: &Registry,
    source: InputSource<'_>,
    formula: Option<&Json>,
) -> (ObligationVerdict, String, Vec<SolverInvocation>) {
    match lookup(name, registry) {
        Ok(s) => {
            let compiler = s.ir_compiler().to_string();
            let identity = s.identity();
            let r = solve_with_input(s.as_ref(), source, formula);
            let verdict = r.verdict;
            let reason = reason_for(&r);
            let inv = SolverInvocation {
                authoritative: true,
                compiler,
                identity,
                result: r,
            };
            (verdict, reason, vec![inv])
        }
        Err(e) => (ObligationVerdict::Undecidable, e, vec![]),
    }
}

fn chain(
    names: &[SolverSeat],
    registry: &Registry,
    source: InputSource<'_>,
    formula: Option<&Json>,
) -> (ObligationVerdict, String, Vec<SolverInvocation>) {
    let mut history: Vec<SolverInvocation> = vec![];
    let mut last_reason = String::new();
    for (idx, n) in names.iter().copied().enumerate() {
        match lookup(n, registry) {
            Ok(s) => {
                let compiler = s.ir_compiler().to_string();
                let identity = s.identity();
                let r = solve_with_input(s.as_ref(), source, formula);
                let definitive = matches!(
                    r.verdict,
                    ObligationVerdict::Discharged | ObligationVerdict::Unsatisfied
                );
                last_reason = reason_for(&r);
                if definitive {
                    let verdict = r.verdict;
                    let inv = SolverInvocation {
                        authoritative: true,
                        compiler,
                        identity,
                        result: r,
                    };
                    history.push(inv);
                    return (
                        verdict,
                        format!(
                            "chain: solver '{n}' (step {}/{}) returned {}: {}",
                            idx + 1,
                            names.len(),
                            verdict.as_str(),
                            last_reason
                        ),
                        history,
                    );
                }
                history.push(SolverInvocation {
                    authoritative: false,
                    compiler,
                    identity,
                    result: r,
                });
            }
            Err(e) => {
                last_reason = e.clone();
                continue;
            }
        }
    }
    (
        ObligationVerdict::Undecidable,
        format!(
            "chain: no solver returned a definitive verdict ({} attempted), last: {}",
            names.len(),
            last_reason
        ),
        history,
    )
}

fn portfolio(
    names: &[SolverSeat],
    mode: PortfolioMode,
    registry: &Registry,
    source: InputSource<'_>,
    formula: Option<&Json>,
) -> (ObligationVerdict, String, Vec<SolverInvocation>) {
    // Resolve handles up front; surface lookup misses as Undecidable.
    let mut handles: Vec<&Arc<dyn Solver>> = vec![];
    for n in names.iter().copied() {
        match lookup(n, registry) {
            Ok(h) => handles.push(h),
            Err(e) => {
                return (ObligationVerdict::Undecidable, e, vec![]);
            }
        }
    }

    // Run all in parallel via rayon. We do not implement subprocess
    // cancellation in v0; first-wins is "first to *return* a definitive
    // verdict" not "first to start". For SubprocessSolver this means
    // remaining solvers continue until natural completion or timeout.
    // The plan-execution semantics (first definitive verdict wins) is
    // still honored by the post-collection sort.
    let results: Vec<(String, SolverIdentity, SolveResult)> = handles
        .par_iter()
        .map(|s| {
            (
                s.ir_compiler().to_string(),
                s.identity(),
                solve_with_input(s.as_ref(), source, formula),
            )
        })
        .collect();

    match mode {
        PortfolioMode::FirstWins => {
            // Sort by wall_clock so the fastest result wins; ties broken
            // by name (deterministic).
            let mut sorted = results.clone();
            sorted.sort_by(|a, b| {
                a.2.wall_clock
                    .cmp(&b.2.wall_clock)
                    .then_with(|| a.2.solver_name.cmp(&b.2.solver_name))
            });
            let chosen = sorted
                .iter()
                .find(|(_, _, r)| {
                    matches!(
                        r.verdict,
                        ObligationVerdict::Discharged | ObligationVerdict::Unsatisfied
                    )
                })
                .cloned()
                .unwrap_or_else(|| sorted[0].clone());
            let mut invs: Vec<SolverInvocation> = vec![];
            for (compiler, identity, r) in results.into_iter() {
                let auth = r.solver_name == chosen.2.solver_name && r.verdict == chosen.2.verdict;
                invs.push(SolverInvocation {
                    authoritative: auth,
                    compiler,
                    identity,
                    result: r,
                });
            }
            let reason = format!(
                "portfolio[first-wins]: '{}' returned {} in {}ms",
                chosen.2.solver_name,
                chosen.2.verdict.as_str(),
                chosen.2.wall_clock.as_millis()
            );
            (chosen.2.verdict, reason, invs)
        }
        PortfolioMode::Consensus => {
            // ALL definitive verdicts must agree. Mixed Discharged +
            // Unsatisfied = Disagreement (loud log). Definitive +
            // Undecidable = ignore Undecidables, take definitive
            // consensus among the rest.
            let definitives: Vec<&SolveResult> = results
                .iter()
                .map(|(_, _, r)| r)
                .filter(|r| {
                    matches!(
                        r.verdict,
                        ObligationVerdict::Discharged | ObligationVerdict::Unsatisfied
                    )
                })
                .collect();
            if definitives.is_empty() {
                let invs: Vec<SolverInvocation> = results
                    .into_iter()
                    .map(|(compiler, identity, r)| SolverInvocation {
                        authoritative: false,
                        compiler,
                        identity,
                        result: r,
                    })
                    .collect();
                return (
                    ObligationVerdict::Undecidable,
                    "portfolio[consensus]: no definitive verdict from any solver".into(),
                    invs,
                );
            }
            let first = definitives[0].verdict;
            let agree = definitives.iter().all(|r| r.verdict == first);
            if agree {
                let n = definitives.len();
                let invs: Vec<SolverInvocation> = results
                    .into_iter()
                    .map(|(compiler, identity, r)| {
                        let auth = matches!(
                            r.verdict,
                            ObligationVerdict::Discharged | ObligationVerdict::Unsatisfied
                        );
                        SolverInvocation {
                            authoritative: auth,
                            compiler,
                            identity,
                            result: r,
                        }
                    })
                    .collect();
                (
                    first,
                    format!(
                        "portfolio[consensus]: {n} solvers agree on {}",
                        first.as_str()
                    ),
                    invs,
                )
            } else {
                // Disagreement. Record loud and pass back special
                // verdict so the report layer can flag the row.
                let parts: Vec<String> = definitives
                    .iter()
                    .map(|r| format!("{}={}", r.solver_name, r.verdict.as_str()))
                    .collect();
                let reason = format!(
                    "portfolio[consensus]: SOLVER DISAGREEMENT: {}",
                    parts.join(", ")
                );
                eprintln!("warning: {reason}");
                let invs: Vec<SolverInvocation> = results
                    .into_iter()
                    .map(|(compiler, identity, r)| SolverInvocation {
                        authoritative: false,
                        compiler,
                        identity,
                        result: r,
                    })
                    .collect();
                (ObligationVerdict::Disagreement, reason, invs)
            }
        }
    }
}

fn reason_for(r: &SolveResult) -> String {
    if !r.error.is_empty() {
        r.error.clone()
    } else {
        match r.verdict {
            ObligationVerdict::Discharged => format!(
                "solver '{}' returned unsat (obligation holds)",
                r.solver_name
            ),
            ObligationVerdict::Unsatisfied => format!(
                "solver '{}' returned sat (counterexample found)",
                r.solver_name
            ),
            ObligationVerdict::Undecidable => {
                format!("solver '{}' returned unknown", r.solver_name)
            }
            ObligationVerdict::Disagreement => {
                format!("solver '{}' produced disagreement", r.solver_name)
            }
            // Refusals always carry a named reason in `r.error` (handled above);
            // this is the exhaustive fallback.
            ObligationVerdict::Refused => {
                format!("solver '{}' refused: no sound discharger", r.solver_name)
            }
        }
    }
}

fn solve_with_input(
    solver: &dyn Solver,
    source: InputSource<'_>,
    formula: Option<&Json>,
) -> SolveResult {
    match solver_input(solver, source, formula) {
        Ok(PreparedInput::Text(text)) => solver.solve(&text),
        Ok(PreparedInput::Compiled(compiled)) => solver.solve_compiled(&compiled),
        Err(error) => compile_error_result(solver, error),
    }
}

fn solver_input(
    solver: &dyn Solver,
    source: InputSource<'_>,
    formula: Option<&Json>,
) -> Result<PreparedInput, String> {
    match source {
        InputSource::Precompiled(smt) => {
            if solver.ir_compiler() == "smt-lib-v2.6" {
                Ok(PreparedInput::Text(smt.to_string()))
            } else {
                Ok(PreparedInput::Text(
                    formula
                        .map(Json::to_string)
                        .unwrap_or_else(|| smt.to_string()),
                ))
            }
        }
        InputSource::Compilers(compilers) => {
            let formula = formula.ok_or_else(|| {
                format!(
                    "no ProofIR formula available for compiler `{}`",
                    solver.ir_compiler()
                )
            })?;
            compilers
                .compile(formula, solver.ir_compiler())
                .map(PreparedInput::Compiled)
                .map_err(|e| format!("ir compiler `{}`: {e}", solver.ir_compiler()))
        }
    }
}

fn compile_error_result(solver: &dyn Solver, error: String) -> SolveResult {
    SolveResult {
        verdict: ObligationVerdict::Undecidable,
        solver_name: solver.name().to_string(),
        solver_version: solver.version().to_string(),
        error,
        solver_stdout: String::new(),
        wall_clock: std::time::Duration::ZERO,
        timed_out: false,
    }
}

/// Helper for the runner's per-solver telemetry aggregator. Held in
/// an `Arc<Mutex<...>>` so the rayon callsite fan-out can append from
/// any worker thread.
pub type TelemetrySink = Arc<Mutex<Vec<SolverInvocation>>>;

#[cfg(test)]
mod tests {
    use super::*;
    use crate::solvers::StubSolver;
    use std::time::Duration;

    fn registry() -> Registry {
        let mut r: Registry = HashMap::new();
        r.insert(
            SolverSeat::Z3,
            Arc::new(StubSolver::new("z3", ObligationVerdict::Discharged)) as SolverHandle,
        );
        r.insert(
            SolverSeat::Cvc5,
            Arc::new(StubSolver::new("cvc5", ObligationVerdict::Unsatisfied)) as SolverHandle,
        );
        r.insert(
            SolverSeat::Vampire,
            Arc::new(StubSolver::new("vampire", ObligationVerdict::Undecidable)) as SolverHandle,
        );
        r
    }

    #[test]
    fn single_returns_solver_verdict() {
        let r = registry();
        let plan = SolverPlan::Single(SolverSeat::Z3);
        let (v, _, invs) = run_plan(&plan, &r, "(check-sat)", None);
        assert_eq!(v, ObligationVerdict::Discharged);
        assert_eq!(invs.len(), 1);
        assert!(invs[0].authoritative);
    }

    #[test]
    fn chain_falls_through_undecidable() {
        let r = registry();
        let plan = SolverPlan::Chain(vec![SolverSeat::Vampire, SolverSeat::Z3]);
        let (v, _, invs) = run_plan(&plan, &r, "x", None);
        assert_eq!(v, ObligationVerdict::Discharged);
        assert_eq!(invs.len(), 2);
        assert!(!invs[0].authoritative);
        assert!(invs[1].authoritative);
    }

    #[test]
    fn chain_all_undecidable_returns_undecidable() {
        let r = registry();
        let plan = SolverPlan::Chain(vec![SolverSeat::Vampire, SolverSeat::Vampire]);
        let (v, _, _) = run_plan(&plan, &r, "x", None);
        assert_eq!(v, ObligationVerdict::Undecidable);
    }

    #[test]
    fn portfolio_first_wins_picks_fastest_definitive() {
        let mut reg: Registry = HashMap::new();
        reg.insert(
            SolverSeat::Z3,
            Arc::new(
                StubSolver::new("z3", ObligationVerdict::Discharged)
                    .with_delay(Duration::from_millis(5)),
            ) as SolverHandle,
        );
        reg.insert(
            SolverSeat::Cvc5,
            Arc::new(
                StubSolver::new("cvc5", ObligationVerdict::Discharged)
                    .with_delay(Duration::from_millis(50)),
            ) as SolverHandle,
        );
        let plan = SolverPlan::Portfolio {
            names: vec![SolverSeat::Z3, SolverSeat::Cvc5],
            mode: PortfolioMode::FirstWins,
        };
        let (v, _, invs) = run_plan(&plan, &reg, "x", None);
        assert_eq!(v, ObligationVerdict::Discharged);
        assert_eq!(invs.len(), 2);
        let auth: Vec<_> = invs.iter().filter(|i| i.authoritative).collect();
        assert_eq!(auth.len(), 1);
        assert_eq!(auth[0].result.solver_name, "z3");
    }

    #[test]
    fn portfolio_consensus_agree() {
        let r = registry();
        let plan = SolverPlan::Portfolio {
            names: vec![SolverSeat::Z3, SolverSeat::Z3],
            mode: PortfolioMode::Consensus,
        };
        let (v, _, _) = run_plan(&plan, &r, "x", None);
        assert_eq!(v, ObligationVerdict::Discharged);
    }

    #[test]
    fn portfolio_consensus_disagree_flags_disagreement() {
        let r = registry();
        let plan = SolverPlan::Portfolio {
            names: vec![SolverSeat::Z3, SolverSeat::Cvc5],
            mode: PortfolioMode::Consensus,
        };
        let (v, reason, _) = run_plan(&plan, &r, "x", None);
        assert_eq!(v, ObligationVerdict::Disagreement);
        assert!(reason.contains("DISAGREEMENT"));
    }

    #[test]
    fn dispatch_picks_strings_solver() {
        let mut reg: Registry = HashMap::new();
        reg.insert(
            SolverSeat::Z3,
            Arc::new(StubSolver::new("z3", ObligationVerdict::Discharged)) as SolverHandle,
        );
        reg.insert(
            SolverSeat::Cvc5,
            Arc::new(StubSolver::new("cvc5", ObligationVerdict::Unsatisfied)) as SolverHandle,
        );
        let plan = SolverPlan::Dispatch(crate::solvers::DispatchConfig {
            equational_theory: None,
            first_order: None,
            strings: Some(SolverSeat::Cvc5),
            bitvectors: None,
            linear_arithmetic: Some(SolverSeat::Z3),
            dependent_type: None,
            categorical_structure: None,
            default: Some(SolverSeat::Z3),
        });
        let f = serde_json::json!({"kind":"atomic","name":"length","args":[]});
        let (v, _, invs) = run_plan(&plan, &reg, "x", Some(&f));
        assert_eq!(v, ObligationVerdict::Unsatisfied);
        assert_eq!(invs[0].result.solver_name, "cvc5");
    }

    #[test]
    fn dispatch_falls_back_to_default() {
        let mut reg: Registry = HashMap::new();
        reg.insert(
            SolverSeat::Z3,
            Arc::new(StubSolver::new("z3", ObligationVerdict::Discharged)) as SolverHandle,
        );
        let plan = SolverPlan::Dispatch(crate::solvers::DispatchConfig {
            equational_theory: None,
            first_order: None,
            strings: None,
            bitvectors: None,
            linear_arithmetic: None,
            dependent_type: None,
            categorical_structure: None,
            default: Some(SolverSeat::Z3),
        });
        let f = serde_json::json!({"kind":"atomic","name":"unknown","args":[]});
        let (v, _, _) = run_plan(&plan, &reg, "x", Some(&f));
        assert_eq!(v, ObligationVerdict::Discharged);
    }

    #[test]
    fn missing_solver_in_registry_yields_undecidable() {
        let r = registry();
        let plan = SolverPlan::Single(SolverSeat::Bitwuzla);
        let (v, _, _) = run_plan(&plan, &r, "x", None);
        assert_eq!(v, ObligationVerdict::Undecidable);
    }
}
