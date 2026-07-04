// SPDX-License-Identifier: Apache-2.0
//
// sugar-verifier
//
// Six-stage bridge-enforcement pipeline. Mirrors the Go and C++
// verifiers. Stages:
//
//   1. load_all_proofs: walk <project_root> for *.proof files,
//                          re-derive each member envelope's CID,
//                          reject mismatches, index by CID and by
//                          sourceSymbol (for bridges).
//   2. enumerate_callsites: for every contract memento, walk
//                            pre/post/inv looking for ctor terms
//                            whose name matches a known bridge
//                            sourceSymbol; emit a CallSite per hit.
//   3. resolve_target: look up the CallSite's bridge.targetCid
//                          in the pool; return the target contract's
//                          `pre` formula as the discharge target.
//   4. instantiate: substitute the call's arg term for the
//                          forall's bound variable in the resolved
//                          pre formula (flat quantifier shape).
//   5. smt_emit: render the obligation IR to SMT-LIB script
//                          (set-logic ALL + free-var declarations +
//                          assert (not BODY) + check-sat).
//   6. solve_obligation: invoke the configured z3 binary as a
//                          subprocess; map "unsat" -> Discharged,
//                          "sat" -> Unsatisfied, anything else ->
//                          Undecidable.
//   7. report: aggregate per-callsite verdicts plus
//                          load-error rows.
//
// Stages 3-5 fan out per callsite via rayon (mirrors the C++
// std::async fan-out and Go goroutines).

pub mod attribute_safety;
pub mod body_discharge;
pub mod call_edge_loader;
pub mod callee_purity;
pub mod cbor_decode;
pub mod compiler_registry;
pub mod consistency;
pub mod domain_claim_shape_report;
pub mod effects;
pub mod enumerate_callsites;
pub mod formula_rewrite;
pub mod handshake;
pub mod instantiate;
pub mod load_all_proofs;
pub mod outlives;
pub mod proof_conformance;
pub mod report;
pub mod resolve_target;
pub mod runner;
pub mod smt_emitter;
pub mod solve_obligation;
pub mod solvers;
pub mod superposition;
pub mod types;

pub use domain_claim_shape_report::{
    shape_report_claim, shape_report_claims, validate_trichotomy, DomainClaimShapeReport,
    StatedClaimOutcome, TrichotomyError,
};
pub use effects::{
    VerifyEffect, VerifyEffectBoundary, WitnessDischargeGround, WitnessVerificationCheck,
    WitnessVerificationOutcome,
};
pub use runner::{
    LegacyZ3Fallback, PlanArtifactInput, ProofRunArtifact, ProofRunArtifactError, Runner,
    RunnerConfig, SolverStats, TierStats, VERIFIER_STAGE_VOCABULARY,
};
pub use solvers::{
    classify, dispatch_for_formula, run_plan, run_plan_with_compilers, DispatchConfig,
    FormulaTheory, PortfolioMode, SolveResult, Solver, SolverConfig, SolverHandle,
    SolverInvocation, SolverPlan, SolverSeat, SolversConfig, StubSolver, SubprocessSolver,
};
pub use types::*;
// Re-export the api owner's shape-agnostic member readers so crates that
// depend on the verifier (but not directly on sugar-proof-envelope) read
// member shapes through the api instead of the deleted memento_* accessors.
pub use sugar_proof_envelope::{member_body, member_field, member_kind};
