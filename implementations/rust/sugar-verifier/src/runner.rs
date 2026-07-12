// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Verifier runner. Composes the seven stages and fans out per
// callsite via rayon. Stage 6 (solve) is now driven by the
// `solvers::run_plan` multi-solver layer (see
// `protocol/specs/2026-04-30-multi-solver-protocol.md`); the
// legacy single-Z3 path is preserved when no `.sugar/config.toml`
// is found.
//
// Stage 4 handshake: Tier 0c in-pool implication (`pool.can_implies` /
// ImplicationMemento) -> Tier 1 hash equality -> Tier 3 solver plan.
// #3809 cut #7: no `cache_dir` disk lookup / mint (production never set
// it; vestige deleted).
//
// #3809 implication steps 2+ (prove-then-feed, D2 option 1):
// After a REAL Tier-3 / tactic discharge of `post ⊃ pre`, mint an
// ImplicationMemento and queue it for pool insert (reuse / federation by
// CID). Never seal-without-discharge: lying twins must never enter the pool,
// or Tier 0c would false-green. Seal is memoization of proven, never proof.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use crate::formula_rewrite;

use rayon::prelude::*;
use serde_json::json;
use serde_json::Value as Json;
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_ir_compiler::CompilerInput;
use tracing::{debug, info, warn};

use crate::body_discharge::callee_post_guard_fact;
use crate::handshake::{formula_hash, try_tier1};
use crate::solvers::{
    plan::SolverInvocation, registry, run_plan_with_compilers, SolverHandle, SolverPlan,
    SolverSeat, SolversConfig,
};
use crate::types::{AnchoredMember, CallSite, MementoCid, MementoPool, ObligationVerdict, Report};
use crate::{
    body_discharge, compiler_registry, enumerate_callsites, instantiate,
    load_all_proofs::{self, ProofBytes},
    report as report_stage, resolve_target,
};

pub const VERIFIER_STAGE_VOCABULARY: &[&str] = &[
    "load_all_proofs",
    "enumerate_callsites",
    "resolve_target",
    "instantiate",
    STAGE_SMT_EMIT,
    "solve_obligation",
    "report",
];

pub const STAGE_SMT_EMIT: &str = "smt_emit";

const RUN_SIGNER_SEED: [u8; 32] = [0x72; 32];

#[derive(Debug, Clone)]
pub struct ProofRunArtifact {
    pub report: Report,
    pub stats: TierStats,
    pub memento: sugar_ir_types::ProofRunMemento,
    pub stage_receipts: Vec<sugar_ir_types::StageReceipt>,
    pub bundle_cid: String,
    /// Empty when sealed in memory (#3809 cut #8). Faces that want a durable
    /// receipt call [`persist_proof_run_to_project`] with [`Self::bundle_bytes`].
    pub bundle_path: PathBuf,
    /// Sealed proof-run envelope bytes (always produced; face may persist).
    pub bundle_bytes: Vec<u8>,
    pub plan_artifact: Option<PlanArtifactInput>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlanArtifactInput {
    pub plan_cid: String,
    pub member_cid: String,
    pub member_bytes: Vec<u8>,
}

#[derive(Debug, thiserror::Error)]
pub enum ProofRunArtifactError {
    #[error("proof-run artifact: {0}")]
    Build(String),
    #[error("proof-run artifact io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Default)]
pub struct RunnerConfig {
    pub project_root: PathBuf,
    /// Legacy single-Z3 compatibility fallback. The typed solver plan remains
    /// the long-term interface; command surfaces that still accept `--z3` must
    /// opt into this compat hatch explicitly.
    pub legacy_z3_fallback: Option<LegacyZ3Fallback>,
    /// Client-fed trust anchors (config-fed by faces, cut #4). Retained for
    /// face config plumbing / future pool-fed implication trust checks.
    pub trusted_implication_signers: Vec<String>,
    /// Client-fed SolversConfig (#3809 PR A). Solve never opens
    /// `.sugar/config.toml` for `[solvers]` — faces load and set this.
    /// When `None`, only `legacy_z3_fallback` (if any) builds the plan.
    pub solvers_config: Option<SolversConfig>,
    /// Additional project directories whose .proof files should
    /// also be loaded (e.g., OpenAPI spec project for cross-kit
    /// verification).
    pub extra_projects: Vec<PathBuf>,
    /// Additional individual .proof files resolved by kit-owned package
    /// managers. These are still loaded by content address; the verifier
    /// never interprets the package graph that surfaced them.
    pub extra_proof_files: Vec<PathBuf>,
    /// Additional proof catalogs carried over kit RPC. Package managers and
    /// archive layouts stay kit-owned; the verifier consumes bytes only.
    pub extra_proofs: Vec<ProofBytes>,
    /// Optional component-plan artifact minted by sugar-cli. The verifier treats
    /// it as an already-addressed run input and stores the plan-memento bytes in
    /// the proof-run bundle without reinterpreting component discovery.
    pub plan_artifact: Option<PlanArtifactInput>,
    /// Client-fed content CID of `link-bundle.json` for the proof-run header
    /// (#3809 cut #2). Solve never opens that file — faces hash and set this.
    /// `None` → honest placeholder CID.
    pub link_bundle_cid: Option<String>,
    /// Client-fed content CID of `plugin-registry.json` for the proof-run header
    /// (#3809 cut #2). Solve never opens that file. `None` → placeholder CID.
    pub plugin_registry_cid: Option<String>,
    /// #3809: typed witness-discharge context (project_dir + resolvers).
    /// Sole config surface for custom-witness package recompute (step 3:
    /// `SUGAR_WITNESS_PROJECT_DIR` / `SUGAR_WITNESS_RESOLVERS` env retired).
    pub witness_discharge: crate::consistency::WitnessDischargeContext,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LegacyZ3Fallback {
    pub binary: String,
}

impl LegacyZ3Fallback {
    pub fn compat(binary: impl Into<String>) -> Self {
        let binary = binary.into();
        let binary = if binary.trim().is_empty() {
            "z3".to_string()
        } else {
            binary
        };
        Self { binary }
    }
}

/// Per-solver telemetry, surfaced in the report alongside the legacy
/// per-tier counters.
#[derive(Debug, Default, Clone)]
pub struct SolverStats {
    /// How many call sites this solver discharged (returned unsat).
    pub discharged: usize,
    /// How many call sites this solver returned sat (counterexample).
    pub unsatisfied: usize,
    /// How many call sites this solver returned unknown / parse-error.
    pub undecidable: usize,
    /// Subset of `undecidable`: returned because of timeout.
    pub timeouts: usize,
    /// Cumulative wall-clock spent in this solver across the run.
    pub wall_clock: Duration,
    /// Solver version string (as configured).
    pub version: String,
}

#[derive(Debug, Default, Clone)]
pub struct TierStats {
    pub discharged_by_hash: usize,
    pub discharged_by_cache: usize,
    pub vacuous_discharge: usize,
    pub solved_and_minted: usize,
    /// Subset of `solved_and_minted` discharged by REFLEXIVITY (`T == T`
    /// over uninterpreted ctors): sound but shallow (proves the function
    /// returns what it returns). Reported apart from substantive proofs.
    pub reflexive_discharge: usize,
    /// Subset of `solved_and_minted` where the solver did substantive work
    /// (real arithmetic / implication; the equality's sides differ).
    pub substantive_discharge: usize,
    pub residue: usize,
    pub violations: usize,
    pub disagreements: usize,
    /// Cumulative number of solver invocations across all call sites.
    /// Replaces the old `z3_invocations` (kept as alias for back-compat).
    pub solver_invocations: usize,
    /// Per-solver breakdown.
    pub per_solver: BTreeMap<String, SolverStats>,
}

impl TierStats {
    /// Back-compat alias for the old `z3_invocations` counter.
    pub fn z3_invocations(&self) -> usize {
        self.solver_invocations
    }
}

pub struct Runner {
    cfg: RunnerConfig,
    plan: SolverPlan,
    registry: HashMap<SolverSeat, SolverHandle>,
    compilers: CompilerRegistry,
}

impl Runner {
    pub fn new(cfg: RunnerConfig) -> Self {
        let compilers = compiler_registry::build(&cfg.project_root);
        Self::new_with_compilers(cfg, compilers)
    }

    pub fn new_with_compilers(cfg: RunnerConfig, compilers: CompilerRegistry) -> Self {
        // Solve is API-driven (#3809 PR A): signers + solvers ride only on
        // client-fed `cfg` fields. Faces (CLI/LSP) read `.sugar/config.toml`
        // and set `trusted_implication_signers` / `solvers_config` /
        // `legacy_z3_fallback` — solve does not open config.toml.
        //
        // Precedence for the plan:
        //   1. cfg.solvers_config (client-fed)
        //   2. cfg.legacy_z3_fallback
        //   3. empty registry (loud at solver layer)
        let (plan, registry) = build_plan_and_registry(&cfg);
        Self {
            cfg,
            plan,
            registry,
            compilers,
        }
    }

    pub fn run(&self) -> Report {
        let compute = || self.run_with_tiers();
        let (report, _stats) = match build_solve_pool() {
            Some(pool) => pool.install(compute),
            None => compute(),
        };
        report
    }

    pub fn run_with_proof_run(&self) -> Result<ProofRunArtifact, ProofRunArtifactError> {
        self.run_with_proof_run_with_pool(load_pool(&self.cfg))
    }

    /// Same discharge as [`run_with_proof_run`](Runner::run_with_proof_run) but
    /// over a caller-supplied `pool` (already built via [`load_pool`], the SAME
    /// construction `run_with_proof_run` uses inline). Lets an orchestration
    /// layer derive its linker inputs from the SAME pool this run discharges,
    /// rather than decoding the pool twice (sugar#3859). The returned
    /// `ProofRunArtifact` -- report bytes included -- is identical to
    /// `run_with_proof_run` given the same pool.
    pub fn run_with_proof_run_with_pool(
        &self,
        pool: MementoPool,
    ) -> Result<ProofRunArtifact, ProofRunArtifactError> {
        match build_solve_pool() {
            Some(rayon_pool) => rayon_pool.install(move || self.run_with_proof_run_inner(pool)),
            None => self.run_with_proof_run_inner(pool),
        }
    }

    fn run_with_proof_run_inner(
        &self,
        mut pool: MementoPool,
    ) -> Result<ProofRunArtifact, ProofRunArtifactError> {
        // Input CIDs for the proof-run memento (#3809 cut #1): always from the
        // client-fed pool + in-memory extra_proofs / plan_artifact. Never
        // WalkDir project_root for *.proof files — faces load/fold first.
        let input_artifact_cids = discover_input_artifact_cids_from_pool(&pool, &self.cfg);
        let proof_envelope_cid = input_artifact_cids
            .iter()
            .next()
            .cloned()
            .unwrap_or_else(|| placeholder_cid("empty-proof-inputs"));
        // Named run inputs (#3809 cut #2): client-fed only. Solve never reads
        // link-bundle.json / plugin-registry.json under project_root.
        let link_bundle_cid = self
            .cfg
            .link_bundle_cid
            .clone()
            .unwrap_or_else(|| placeholder_cid("absent-link-bundle"));
        let plugin_registry_cid = self
            .cfg
            .plugin_registry_cid
            .clone()
            .unwrap_or_else(|| placeholder_cid("absent-plugin-registry"));

        let mut stages = Vec::with_capacity(4);
        let mut report = Report::default();

        let load_stage = StageCapture::start(
            "load_all_proofs",
            input_artifact_cids.iter().cloned().collect(),
        );
        // `pool` is supplied by the caller (built via `load_pool`, the same
        // construction this method used inline before sugar#3859) so a solve
        // orchestration layer can derive linker inputs from the SAME pool.
        let loaded_cids = sorted_keys(&pool.mementos);
        let load_diagnostics: Vec<Json> = pool
            .load_errors
            .iter()
            .map(|e| json!({"kind": "load-error", "proof_path": e.proof_path, "reason": e.reason}))
            .collect();
        stages.push(load_stage.finish(
            loaded_cids.clone(),
            Vec::new(),
            load_diagnostics,
            if pool.load_errors.is_empty() {
                sugar_ir_types::StageVerdict::Ok
            } else {
                sugar_ir_types::StageVerdict::Warned
            },
        )?);

        let enumerate_stage = StageCapture::start("enumerate_callsites", loaded_cids.clone());
        // #3809 cut #3: solve never WalkDirs `*.call-edges.json`. Discharge
        // edges come from pool bridges + `enumerate_callsites` only. Faces
        // that want report.call_edges telemetry rebuild from the pool.
        let callsites = enumerate_callsites::run(&pool);
        let callsite_property_cids: Vec<String> = callsites
            .iter()
            .filter_map(|cs| cs.property_cid.as_ref().map(|cid| cid.to_string()))
            .collect();
        stages.push(enumerate_stage.finish(
            sorted(callsite_property_cids),
            Vec::new(),
            vec![json!({"kind": "stage-summary", "callsites": callsites.len(), "call_edges": 0})],
            sugar_ir_types::StageVerdict::Ok,
        )?);

        let n_hash = AtomicUsize::new(0);
        let n_cache = AtomicUsize::new(0);
        let n_vacuous = AtomicUsize::new(0);
        let n_solved = AtomicUsize::new(0);
        let n_residue = AtomicUsize::new(0);
        let n_disagree = AtomicUsize::new(0);
        let n_invoc = AtomicUsize::new(0);
        let n_reflexive = AtomicUsize::new(0);
        let n_substantive = AtomicUsize::new(0);
        let invs_sink: Mutex<Vec<SolverInvocation>> =
            Mutex::new(Vec::with_capacity(callsites.len()));
        let minted_sink = Mutex::new(Vec::with_capacity(callsites.len()));

        let fanout_input = sorted(
            callsites
                .iter()
                .filter_map(|cs| cs.property_cid.as_ref().map(|cid| cid.to_string()))
                .chain(loaded_cids.iter().cloned())
                .collect(),
        );
        let fanout_started = iso_now();
        let per_results: Vec<CallsiteResult> = callsites
            .par_iter()
            .map(|cs| {
                work_one(
                    cs,
                    &pool,
                    &self.plan,
                    &self.registry,
                    &self.compilers,
                    &self.cfg,
                    &n_hash,
                    &n_cache,
                    &n_vacuous,
                    &n_solved,
                    &n_residue,
                    &n_disagree,
                    &n_invoc,
                    &n_reflexive,
                    &n_substantive,
                    &invs_sink,
                    &minted_sink,
                )
            })
            .collect();
        let fanout_finished = iso_now();

        let minted = minted_sink.into_inner().unwrap_or_default();
        for (cid, envelope) in minted.iter() {
            let member = AnchoredMember::new(cid.clone(), envelope.clone())
                .unwrap_or_else(|error| panic!("freshly minted memento failed anchoring: {error}"));
            pool.insert(member);
        }
        let output_artifact_cids = sorted(minted.iter().map(|(cid, _)| cid.to_string()).collect());

        for stage_name in [
            "resolve_target",
            "instantiate",
            STAGE_SMT_EMIT,
            "solve_obligation",
        ] {
            stages.push(make_stage_receipt(
                stage_name,
                fanout_input.clone(),
                output_artifact_cids.clone(),
                Vec::new(),
                vec![json!({"kind": "stage-summary", "callsites": callsites.len()})],
                fanout_started.clone(),
                fanout_finished.clone(),
                if callsites.is_empty() {
                    sugar_ir_types::StageVerdict::Skipped
                } else {
                    sugar_ir_types::StageVerdict::Ok
                },
            )?);
        }

        let report_stage_capture = StageCapture::start("report", sorted_keys(&pool.mementos));
        let mut violations = 0usize;
        for (cs, verdict, reason, method, body_tier) in per_results {
            if callsite_row_is_owned_by_consistency(&cs, &pool)
                || callsite_row_is_owned_by_self_post(&cs, &pool)
            {
                debug!(
                    bridge = %cs.bridge_ir_name,
                    property = %cs.property_name,
                    "verifier/linker: pool-level verifier owns body-bearing callsite row"
                );
                continue;
            }
            if verdict != ObligationVerdict::Discharged {
                violations += 1;
            }
            report_stage::add_callsite_with_discharge(
                cs,
                verdict,
                &reason,
                method,
                body_tier,
                &mut report,
            );
        }
        report_stage::add_load_errors(&pool.load_errors, &mut report);

        // Self-post pass (THE 309): verify each body-derived contract's OWN
        // postcondition `post[result := body]`. See `verify_contract_self_posts`.
        // The Runner's callsite enumeration never touches a contract's own
        // post, so this is where a body-discharge-eligible contract is
        // actually verified. Results flow into the same buckets.
        let self_post_results =
            verify_contract_self_posts(&pool, &self.plan, &self.registry, &self.compilers);
        for spr in &self_post_results {
            match spr.verdict {
                ObligationVerdict::Discharged => {
                    n_solved.fetch_add(1, Ordering::Relaxed);
                    match spr.method {
                        Some(body_discharge::DischargeMethod::Reflexive) => {
                            n_reflexive.fetch_add(1, Ordering::Relaxed);
                        }
                        Some(body_discharge::DischargeMethod::Substantive) => {
                            n_substantive.fetch_add(1, Ordering::Relaxed);
                        }
                        None => {}
                    }
                }
                _ => {
                    violations += 1;
                    n_residue.fetch_add(1, Ordering::Relaxed);
                }
            }
            report_stage::add_self_post_with_method(
                &spr.contract_cid,
                spr.verdict,
                &spr.reason,
                spr.method.map(|m| m.as_str().to_string()),
                &mut report,
            );
        }
        info!(
            self_posts = self_post_results.len(),
            self_post_reflexive = self_post_results
                .iter()
                .filter(|r| r.method == Some(body_discharge::DischargeMethod::Reflexive))
                .count(),
            self_post_substantive = self_post_results
                .iter()
                .filter(|r| r.method == Some(body_discharge::DischargeMethod::Substantive))
                .count(),
            self_post_undecidable = self_post_results
                .iter()
                .filter(|r| r.verdict != ObligationVerdict::Discharged)
                .count(),
            "verifier: contract self-post pass complete"
        );

        // Receipt 1: test-assertion consistency pass. Picks up coalesced
        // inv-only contracts (no enumerable bridge call site) that
        // `enumerate_callsites` would otherwise drop silently, and proves /
        // refuses their internal consistency. Discharged => PROVEN-consistent;
        // Unsatisfied => REFUSED-contradictory; Undecidable => encoding STOP
        // surfaced as a violation (never silently passed).
        let consistency_results = crate::consistency::verify_consistency_with_policy(
            &pool,
            &self.plan,
            &self.registry,
            &self.compilers,
            &self.cfg.project_root,
            &self.cfg.witness_discharge,
        );
        for cr in &consistency_results {
            match cr.verdict {
                ObligationVerdict::Discharged => {
                    n_solved.fetch_add(1, Ordering::Relaxed);
                }
                _ => {
                    violations += 1;
                    n_residue.fetch_add(1, Ordering::Relaxed);
                }
            }
            report_stage::add_consistency_with_verification(
                &cr.contract_cid,
                &cr.property_name,
                cr.verdict,
                &cr.reason,
                cr.verification.as_ref().map(|v| v.to_json()),
                cr.locus.clone(),
                &mut report,
            );
        }
        report_stage::add_toolchain_plans(&pool, &mut report);

        let invs = invs_sink.into_inner().unwrap_or_default();
        let mut per_solver: BTreeMap<String, SolverStats> = BTreeMap::new();
        for inv in &invs {
            let r = &inv.result;
            let entry = per_solver.entry(r.solver_name.clone()).or_default();
            entry.version = r.solver_version.clone();
            entry.wall_clock += r.wall_clock;
            match r.verdict {
                ObligationVerdict::Discharged => entry.discharged += 1,
                ObligationVerdict::Unsatisfied => entry.unsatisfied += 1,
                ObligationVerdict::Undecidable => entry.undecidable += 1,
                ObligationVerdict::SolverTimeout => entry.undecidable += 1,
                ObligationVerdict::Disagreement => entry.undecidable += 1,
                // A refusal is "no sound discharger" -- not the solver's failure;
                // for per-solver telemetry it groups with the not-discharged bucket.
                ObligationVerdict::Refused => entry.undecidable += 1,
            }
            if r.timed_out {
                entry.timeouts += 1;
            }
        }

        let stats = TierStats {
            discharged_by_hash: n_hash.load(Ordering::Relaxed),
            discharged_by_cache: n_cache.load(Ordering::Relaxed),
            vacuous_discharge: n_vacuous.load(Ordering::Relaxed),
            reflexive_discharge: n_reflexive.load(Ordering::Relaxed),
            substantive_discharge: n_substantive.load(Ordering::Relaxed),
            solved_and_minted: n_solved.load(Ordering::Relaxed),
            residue: n_residue.load(Ordering::Relaxed),
            violations,
            disagreements: n_disagree.load(Ordering::Relaxed),
            solver_invocations: n_invoc.load(Ordering::Relaxed),
            per_solver,
        };
        stages.push(report_stage_capture.finish(
            Vec::new(),
            Vec::new(),
            vec![json!({"kind": "stage-summary", "total_callsites": report.total_callsites, "violations": report.violations})],
            if report.violations == 0 {
                sugar_ir_types::StageVerdict::Ok
            } else {
                sugar_ir_types::StageVerdict::Refused
            },
        )?);

        let stage_receipt_cids = stages.iter().map(|s| s.header.cid.clone()).collect();
        let mut run_inputs: Vec<String> = input_artifact_cids.into_iter().collect();
        run_inputs.push(link_bundle_cid.clone());
        run_inputs.push(plugin_registry_cid.clone());
        if let Some(plan_artifact) = &self.cfg.plan_artifact {
            run_inputs.push(plan_artifact.plan_cid.clone());
        }
        run_inputs = sorted(run_inputs);
        let run_verdict = if report.violations == 0 && pool.load_errors.is_empty() {
            sugar_ir_types::ProofRunVerdict::Admissible
        } else if report.violations > 0 {
            sugar_ir_types::ProofRunVerdict::Refused
        } else {
            sugar_ir_types::ProofRunVerdict::Partial
        };
        let memento = make_proof_run_memento(
            stage_receipt_cids,
            run_inputs,
            output_artifact_cids,
            proof_envelope_cid,
            link_bundle_cid,
            plugin_registry_cid,
            run_verdict,
        )?;
        // #3809 cut #8: always seal in memory. Faces persist via
        // `persist_proof_run_to_project` if they want a durable receipt.
        let (bundle_cid, bundle_bytes) =
            write_proof_run_bundle(&memento, &stages, self.cfg.plan_artifact.as_ref())?;

        Ok(ProofRunArtifact {
            report,
            stats,
            memento,
            stage_receipts: stages,
            bundle_cid,
            bundle_path: PathBuf::new(),
            bundle_bytes,
            plan_artifact: self.cfg.plan_artifact.clone(),
        })
    }

    pub fn run_with_tiers(&self) -> (Report, TierStats) {
        let _span = tracing::info_span!(
            "verifier",
            root = %self.cfg.project_root.display()
        )
        .entered();
        info!(root = %self.cfg.project_root.display(), "verifier: starting proof run");

        let mut report = Report::default();
        let mut pool = load_all_proofs::run(&self.cfg.project_root);

        // Load contracts from extra project dirs (e.g., OpenAPI spec)
        for extra in &self.cfg.extra_projects {
            let extra_pool = load_all_proofs::run(extra);
            pool.merge(extra_pool);
        }
        load_all_proofs::load_files_into_pool(&self.cfg.extra_proof_files, &mut pool);
        load_all_proofs::load_proof_bytes_into_pool(&self.cfg.extra_proofs, &mut pool);

        info!(
            mementos = pool.mementos.len(),
            load_errors = pool.load_errors.len(),
            "verifier: proofs loaded"
        );

        // #3809 cut #3: no `*.call-edges.json` WalkDir. Pool bridges +
        // enumerate_callsites only.
        let callsites = enumerate_callsites::run(&pool);
        info!(
            callsites = callsites.len(),
            "verifier: callsite enumeration complete"
        );

        let n_hash = AtomicUsize::new(0);
        let n_cache = AtomicUsize::new(0);
        let n_vacuous = AtomicUsize::new(0);
        let n_solved = AtomicUsize::new(0);
        let n_residue = AtomicUsize::new(0);
        let n_disagree = AtomicUsize::new(0);
        let n_invoc = AtomicUsize::new(0);
        let n_reflexive = AtomicUsize::new(0);
        let n_substantive = AtomicUsize::new(0);

        // Per-solver telemetry sink. Mutex-guarded; rayon workers append
        // their per-callsite SolverInvocations here.
        let invs_sink: Mutex<Vec<SolverInvocation>> =
            Mutex::new(Vec::with_capacity(callsites.len()));

        let cfg = &self.cfg;
        let plan = &self.plan;
        let registry = &self.registry;
        let compilers = &self.compilers;

        let minted_sink = Mutex::new(Vec::with_capacity(callsites.len()));
        let per_results: Vec<CallsiteResult> = callsites
            .par_iter()
            .map(|cs| {
                work_one(
                    cs,
                    &pool,
                    plan,
                    registry,
                    compilers,
                    cfg,
                    &n_hash,
                    &n_cache,
                    &n_vacuous,
                    &n_solved,
                    &n_residue,
                    &n_disagree,
                    &n_invoc,
                    &n_reflexive,
                    &n_substantive,
                    &invs_sink,
                    &minted_sink,
                )
            })
            .collect();

        // Insert freshly minted implication mementos into the pool
        // so subsequent stages can use them immediately.
        if let Ok(minted) = minted_sink.lock() {
            for (cid, envelope) in minted.iter() {
                let member =
                    AnchoredMember::new(cid.clone(), envelope.clone()).unwrap_or_else(|error| {
                        panic!("freshly minted memento failed anchoring: {error}")
                    });
                pool.insert(member);
            }
        }

        // Aggregate report rows.
        let mut violations = 0usize;
        for (cs, verdict, reason, method, body_tier) in per_results {
            if callsite_row_is_owned_by_consistency(&cs, &pool)
                || callsite_row_is_owned_by_self_post(&cs, &pool)
            {
                debug!(
                    bridge = %cs.bridge_ir_name,
                    property = %cs.property_name,
                    "verifier/linker: pool-level verifier owns body-bearing callsite row"
                );
                continue;
            }
            if verdict != ObligationVerdict::Discharged {
                violations += 1;
            }
            report_stage::add_callsite_with_discharge(
                cs,
                verdict,
                &reason,
                method,
                body_tier,
                &mut report,
            );
        }
        report_stage::add_load_errors(&pool.load_errors, &mut report);

        // Self-post pass: verify every body-derived contract's OWN
        // postcondition. A contract carries `post = (result == <body
        // term>)`; substituting `result := <body term>` yields `<body> ==
        // <body>` (plus any conjoined entry-precondition, left intact),
        // which the real encoder + z3 discharge by reflexivity when the
        // self-post is unconditionally valid. THIS is "the 309": the
        // Runner's callsite enumeration never touches a contract's own
        // post, so without this pass a body-discharge-eligible contract is
        // eligible-but-never-verified. Each result flows into the SAME
        // reflexive / substantive / residue buckets so the proof-run split
        // is unified.
        let self_post_results = verify_contract_self_posts(&pool, plan, registry, compilers);
        for spr in &self_post_results {
            match spr.verdict {
                ObligationVerdict::Discharged => {
                    n_solved.fetch_add(1, Ordering::Relaxed);
                    match spr.method {
                        Some(body_discharge::DischargeMethod::Reflexive) => {
                            n_reflexive.fetch_add(1, Ordering::Relaxed);
                        }
                        Some(body_discharge::DischargeMethod::Substantive) => {
                            n_substantive.fetch_add(1, Ordering::Relaxed);
                        }
                        None => {}
                    }
                }
                _ => {
                    violations += 1;
                    n_residue.fetch_add(1, Ordering::Relaxed);
                }
            }
            report_stage::add_self_post_with_method(
                &spr.contract_cid,
                spr.verdict,
                &spr.reason,
                spr.method.map(|m| m.as_str().to_string()),
                &mut report,
            );
        }
        info!(
            self_posts = self_post_results.len(),
            self_post_reflexive = self_post_results
                .iter()
                .filter(|r| r.method == Some(body_discharge::DischargeMethod::Reflexive))
                .count(),
            self_post_substantive = self_post_results
                .iter()
                .filter(|r| r.method == Some(body_discharge::DischargeMethod::Substantive))
                .count(),
            self_post_undecidable = self_post_results
                .iter()
                .filter(|r| r.verdict != ObligationVerdict::Discharged)
                .count(),
            "verifier: contract self-post pass complete"
        );

        // Receipt 1: test-assertion consistency pass (see the matching block
        // in the primary run path).
        let consistency_results = crate::consistency::verify_consistency_with_policy(
            &pool,
            plan,
            registry,
            compilers,
            &self.cfg.project_root,
            &self.cfg.witness_discharge,
        );
        for cr in &consistency_results {
            match cr.verdict {
                ObligationVerdict::Discharged => {
                    n_solved.fetch_add(1, Ordering::Relaxed);
                }
                _ => {
                    violations += 1;
                    n_residue.fetch_add(1, Ordering::Relaxed);
                }
            }
            report_stage::add_consistency_with_verification(
                &cr.contract_cid,
                &cr.property_name,
                cr.verdict,
                &cr.reason,
                cr.verification.as_ref().map(|v| v.to_json()),
                cr.locus.clone(),
                &mut report,
            );
        }
        report_stage::add_toolchain_plans(&pool, &mut report);

        // Aggregate per-solver stats from telemetry sink.
        let invs = invs_sink.into_inner().unwrap_or_default();
        let mut per_solver: BTreeMap<String, SolverStats> = BTreeMap::new();
        for inv in &invs {
            let r = &inv.result;
            let entry = per_solver.entry(r.solver_name.clone()).or_default();
            entry.version = r.solver_version.clone();
            entry.wall_clock += r.wall_clock;
            match r.verdict {
                ObligationVerdict::Discharged => entry.discharged += 1,
                ObligationVerdict::Unsatisfied => entry.unsatisfied += 1,
                ObligationVerdict::Undecidable => entry.undecidable += 1,
                ObligationVerdict::SolverTimeout => entry.undecidable += 1,
                ObligationVerdict::Disagreement => entry.undecidable += 1,
                // A refusal is "no sound discharger" -- not the solver's failure;
                // for per-solver telemetry it groups with the not-discharged bucket.
                ObligationVerdict::Refused => entry.undecidable += 1,
            }
            if r.timed_out {
                entry.timeouts += 1;
            }
        }

        let stats = TierStats {
            discharged_by_hash: n_hash.load(Ordering::Relaxed),
            discharged_by_cache: n_cache.load(Ordering::Relaxed),
            vacuous_discharge: n_vacuous.load(Ordering::Relaxed),
            reflexive_discharge: n_reflexive.load(Ordering::Relaxed),
            substantive_discharge: n_substantive.load(Ordering::Relaxed),
            solved_and_minted: n_solved.load(Ordering::Relaxed),
            residue: n_residue.load(Ordering::Relaxed),
            violations,
            disagreements: n_disagree.load(Ordering::Relaxed),
            solver_invocations: n_invoc.load(Ordering::Relaxed),
            per_solver: per_solver.clone(),
        };

        if violations > 0 {
            warn!(
                violations = violations,
                discharged_by_hash = stats.discharged_by_hash,
                discharged_by_cache = stats.discharged_by_cache,
                vacuous = stats.vacuous_discharge,
                solved = stats.solved_and_minted,
                reflexive = stats.reflexive_discharge,
                solver_substantive = stats.substantive_discharge,
                residue = stats.residue,
                solver_invocations = stats.solver_invocations,
                "verifier: proof run complete with VIOLATIONS [solved split: {} reflexive, {} solver-substantive]",
                stats.reflexive_discharge,
                stats.substantive_discharge
            );
        } else {
            info!(
                violations = violations,
                discharged_by_hash = stats.discharged_by_hash,
                discharged_by_cache = stats.discharged_by_cache,
                vacuous = stats.vacuous_discharge,
                solved = stats.solved_and_minted,
                reflexive = stats.reflexive_discharge,
                solver_substantive = stats.substantive_discharge,
                residue = stats.residue,
                solver_invocations = stats.solver_invocations,
                "verifier: proof run complete, all obligations discharged [solved split: {} reflexive, {} solver-substantive]",
                stats.reflexive_discharge,
                stats.substantive_discharge
            );
        }
        for (solver_name, solver_stats) in &stats.per_solver {
            debug!(
                solver = %solver_name,
                discharged = solver_stats.discharged,
                unsatisfied = solver_stats.unsatisfied,
                undecidable = solver_stats.undecidable,
                timeouts = solver_stats.timeouts,
                wall_clock_ms = solver_stats.wall_clock.as_millis(),
                "verifier: per-solver stats"
            );
        }

        (report, stats)
    }

    pub fn run_load_and_enumerate(&self) -> (MementoPool, Vec<CallSite>) {
        let mut pool = load_all_proofs::run(&self.cfg.project_root);
        for extra in &self.cfg.extra_projects {
            let extra_pool = load_all_proofs::run(extra);
            pool.merge(extra_pool);
        }
        load_all_proofs::load_files_into_pool(&self.cfg.extra_proof_files, &mut pool);
        load_all_proofs::load_proof_bytes_into_pool(&self.cfg.extra_proofs, &mut pool);
        let cs = enumerate_callsites::run(&pool);
        (pool, cs)
    }

    pub fn plan(&self) -> &SolverPlan {
        &self.plan
    }
}

struct StageCapture {
    stage_name: String,
    input_cids: Vec<String>,
    started_at: String,
}

impl StageCapture {
    fn start(stage_name: &str, input_cids: Vec<String>) -> Self {
        Self {
            stage_name: stage_name.to_string(),
            input_cids: sorted(input_cids),
            started_at: iso_now(),
        }
    }

    fn finish(
        self,
        output_cids: Vec<String>,
        refusal_cids: Vec<String>,
        diagnostics: Vec<Json>,
        verdict: sugar_ir_types::StageVerdict,
    ) -> Result<sugar_ir_types::StageReceipt, ProofRunArtifactError> {
        make_stage_receipt(
            &self.stage_name,
            self.input_cids,
            output_cids,
            refusal_cids,
            diagnostics,
            self.started_at,
            iso_now(),
            verdict,
        )
    }
}

fn make_stage_receipt(
    stage_name: &str,
    input_cids: Vec<String>,
    output_cids: Vec<String>,
    refusal_cids: Vec<String>,
    diagnostics: Vec<Json>,
    started_at: String,
    finished_at: String,
    verdict: sugar_ir_types::StageVerdict,
) -> Result<sugar_ir_types::StageReceipt, ProofRunArtifactError> {
    let mut receipt = sugar_ir_types::StageReceipt {
        envelope: unsigned_envelope(&finished_at),
        header: sugar_ir_types::StageReceiptHeader {
            cid: "blake3-512:PENDING".into(),
            diagnostics,
            finished_at,
            input_cids: sorted(input_cids),
            kind: "stage-receipt".into(),
            output_cids: sorted(output_cids),
            refusal_cids: sorted(refusal_cids),
            schema_version: "1".into(),
            stage_name: stage_name.into(),
            started_at,
            verdict,
        },
        metadata: sugar_ir_types::StageReceiptMetadata::default(),
    };
    receipt.header.cid = receipt
        .recompute_header_cid()
        .map_err(|e| ProofRunArtifactError::Build(e.to_string()))?;
    receipt.envelope.signature = sign_header_metadata(&receipt.header, &receipt.metadata)?;
    receipt.header.cid = proof_run_envelope_cid(&receipt.envelope)?;
    Ok(receipt)
}

fn make_proof_run_memento(
    stage_receipt_cids: Vec<String>,
    input_artifact_cids: Vec<String>,
    output_artifact_cids: Vec<String>,
    proof_envelope_cid: String,
    link_bundle_cid: String,
    plugin_registry_cid: String,
    verdict: sugar_ir_types::ProofRunVerdict,
) -> Result<sugar_ir_types::ProofRunMemento, ProofRunArtifactError> {
    let sealed_at = iso_now();
    let mut memento = sugar_ir_types::ProofRunMemento {
        envelope: unsigned_envelope(&sealed_at),
        header: sugar_ir_types::ProofRunHeader {
            cid: "blake3-512:PENDING".into(),
            input_artifact_cids: sorted(input_artifact_cids),
            input_run_cids: Vec::new(),
            kind: "proof-run".into(),
            link_bundle_cid,
            output_artifact_cids: sorted(output_artifact_cids),
            plugin_registry_cid,
            proof_envelope_cid,
            schema_version: "1".into(),
            sealed_at,
            stage_receipt_cids,
            verdict,
            // TODO(#799): replace this deterministic vocabulary hash with
            // VerifierPipelineMemento once that substrate artifact lands.
            verifier_pipeline_cid: verifier_pipeline_placeholder_cid(),
        },
        metadata: sugar_ir_types::ProofRunMetadata {
            note: Some("sugar-verifier run receipt".into()),
            source_url: None,
        },
    };
    memento.header.cid = memento
        .recompute_header_cid()
        .map_err(|e| ProofRunArtifactError::Build(e.to_string()))?;
    memento.envelope.signature = sign_header_metadata(&memento.header, &memento.metadata)?;
    memento.header.cid = proof_run_envelope_cid(&memento.envelope)?;
    Ok(memento)
}

/// Seal the proof-run envelope in memory (#3809 cut #8).
/// Returns `(bundle_cid, sealed_bytes)`. Never writes under project_root —
/// faces call [`persist_proof_run_to_project`] for durable receipts.
fn write_proof_run_bundle(
    memento: &sugar_ir_types::ProofRunMemento,
    stages: &[sugar_ir_types::StageReceipt],
    plan_artifact: Option<&PlanArtifactInput>,
) -> Result<(String, Vec<u8>), ProofRunArtifactError> {
    use sugar_proof_envelope::{
        build_proof_envelope, PlanMemento, ProofEnvelopeInput, ProofGraph, ProofRunMemento,
        StageReceiptMemento,
    };

    let mut graph = ProofGraph::new();
    if let Some(plan_artifact) = plan_artifact {
        graph.push_plan(PlanMemento::new(plan_artifact.member_bytes.clone()));
    }
    graph.push_proof_run(ProofRunMemento::new(
        memento
            .to_jcs_string()
            .map_err(|e| ProofRunArtifactError::Build(e.to_string()))?
            .into_bytes(),
    ));
    for stage in stages {
        graph.push_stage_receipt(StageReceiptMemento::new(
            stage
                .to_jcs_string()
                .map_err(|e| ProofRunArtifactError::Build(e.to_string()))?
                .into_bytes(),
        ));
    }

    let signer = sugar_proof_envelope::ed25519_pubkey_string(&RUN_SIGNER_SEED);
    let signer_cid = sugar_canonicalizer::blake3_512_of(signer.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@sugar/verifier-run".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed: RUN_SIGNER_SEED,
        declared_at: iso_now(),
        manifest: None,
    });
    Ok((built.cid, built.bytes))
}

/// Face helper (#3809 cut #8): write sealed proof-run bytes under
/// `project_root/.sugar/runs/`. Solve never calls this.
pub fn persist_proof_run_to_project(
    project_root: &Path,
    bundle_cid: &str,
    bundle_bytes: &[u8],
) -> Result<PathBuf, ProofRunArtifactError> {
    let out_dir = project_root.join(".sugar").join("runs");
    std::fs::create_dir_all(&out_dir)?;
    let path = out_dir.join(sugar_proof_envelope::proof_filename(bundle_cid));
    std::fs::write(&path, bundle_bytes)?;
    Ok(path)
}

fn unsigned_envelope(declared_at: &str) -> sugar_ir_types::ProofRunEnvelope {
    sugar_ir_types::ProofRunEnvelope {
        declared_at: declared_at.to_string(),
        signature: String::new(),
        signer: sugar_proof_envelope::ed25519_pubkey_string(&RUN_SIGNER_SEED),
    }
}

fn sign_header_metadata<H: serde::Serialize, M: serde::Serialize>(
    header: &H,
    metadata: &M,
) -> Result<String, ProofRunArtifactError> {
    let payload = json!({ "header": header, "metadata": metadata });
    let canonical = json_to_canonical(&payload)?;
    let jcs = sugar_canonicalizer::encode_jcs(&canonical);
    Ok(sugar_proof_envelope::ed25519_sign_string(
        &RUN_SIGNER_SEED,
        jcs.as_bytes(),
    ))
}

fn proof_run_envelope_cid(
    envelope: &sugar_ir_types::ProofRunEnvelope,
) -> Result<String, ProofRunArtifactError> {
    let json =
        serde_json::to_value(envelope).map_err(|e| ProofRunArtifactError::Build(e.to_string()))?;
    let canonical = json_to_canonical(&json)?;
    let jcs = sugar_canonicalizer::encode_jcs(&canonical);
    Ok(sugar_canonicalizer::blake3_512_of(jcs.as_bytes()))
}

fn verifier_pipeline_placeholder_cid() -> String {
    let vocabulary = Json::Array(
        VERIFIER_STAGE_VOCABULARY
            .iter()
            .map(|s| Json::String((*s).to_string()))
            .collect(),
    );
    let canonical = json_to_canonical(&vocabulary).expect("stage vocabulary canonicalizes");
    let jcs = sugar_canonicalizer::encode_jcs(&canonical);
    sugar_canonicalizer::blake3_512_of(jcs.as_bytes())
}

/// Input CIDs from the client-fed pool + in-memory `extra_proofs` / plan only.
/// No `WalkDir` / `std::fs::read` of project `*.proof` files (#3809 cut #1).
fn discover_input_artifact_cids_from_pool(
    pool: &MementoPool,
    cfg: &RunnerConfig,
) -> BTreeSet<String> {
    let mut cids: BTreeSet<String> = pool.mementos.keys().map(|cid| cid.to_string()).collect();
    for proof in &cfg.extra_proofs {
        cids.insert(sugar_canonicalizer::blake3_512_of(&proof.bytes));
    }
    // plan_artifact is an already-addressed run input carried on cfg.
    if let Some(plan) = &cfg.plan_artifact {
        cids.insert(plan.plan_cid.clone());
        cids.insert(plan.member_cid.clone());
    }
    cids
}

/// Hash a named project file for faces that want to feed run-header CIDs.
/// Client helper — solve never calls this (#3809 cut #2).
pub fn hash_named_project_artifact(project_root: &Path, name: &str) -> Option<String> {
    let path = project_root.join(name);
    std::fs::read(path)
        .ok()
        .map(|bytes| sugar_canonicalizer::blake3_512_of(&bytes))
}

fn placeholder_cid(label: &str) -> String {
    sugar_canonicalizer::blake3_512_of(format!("sugar-verifier:{label}:v1").as_bytes())
}

fn sorted(mut values: Vec<String>) -> Vec<String> {
    values.sort();
    values.dedup();
    values
}

fn sorted_keys<K: ToString + Ord, V>(map: &BTreeMap<K, V>) -> Vec<String> {
    map.keys().map(|key| key.to_string()).collect()
}

fn iso_now() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

fn json_to_canonical(
    value: &Json,
) -> Result<std::sync::Arc<sugar_canonicalizer::Value>, ProofRunArtifactError> {
    use sugar_canonicalizer::Value as CanonicalValue;
    match value {
        Json::Null => Ok(CanonicalValue::null()),
        Json::Bool(b) => Ok(CanonicalValue::boolean(*b)),
        Json::Number(n) => {
            let Some(i) = n.as_i64() else {
                return Err(ProofRunArtifactError::Build(format!(
                    "unsupported JSON number in proof-run signing payload: {n}"
                )));
            };
            Ok(CanonicalValue::integer(i128::from(i)))
        }
        Json::String(s) => Ok(CanonicalValue::string(s.clone())),
        Json::Array(items) => Ok(CanonicalValue::array(
            items
                .iter()
                .map(json_to_canonical)
                .collect::<Result<Vec<_>, _>>()?,
        )),
        Json::Object(object) => Ok(CanonicalValue::object(
            object
                .iter()
                .map(|(key, value)| Ok((key.clone(), json_to_canonical(value)?)))
                .collect::<Result<Vec<_>, ProofRunArtifactError>>()?,
        )),
    }
}

/// Build a scoped rayon pool sized for the per-obligation solve loop.
///
/// Each obligation does CPU-bound IR compilation (now one warm compiler child
/// PER worker) and spawns a solver; rayon's default pool = LOGICAL cores, which
/// oversubscribes the physical cores for this CPU+process-heavy work. Measured
/// on the stdlib coretests corpus vs the old single-shared-compiler baseline:
/// logical (16 here) -> 0.48x the speed (thrashing); PHYSICAL (8) -> 1.77x. So
/// default solve concurrency to physical cores. `RAYON_NUM_THREADS` overrides
/// (operator wins). SCOPED (not `build_global`) so it works regardless of rayon
/// use earlier in the process (e.g. the lift->prove path) and never mutates the
/// caller's global pool. `None` on build failure -> fall back to the ambient
/// pool rather than abort.
fn build_solve_pool() -> Option<rayon::ThreadPool> {
    let threads = std::env::var("RAYON_NUM_THREADS")
        .ok()
        .and_then(|v| v.trim().parse::<usize>().ok())
        .filter(|&n| n > 0)
        .unwrap_or_else(|| num_cpus::get_physical().max(1));
    rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .thread_name(|i| format!("sugar-solve-{i}"))
        .build()
        .ok()
}

/// Load the full memento pool for `cfg` (canonical project root + configured
/// extras), exactly as `run_with_tiers`/`run_with_proof_run_inner` do inline.
/// Extracted (part of #3774 warm-daemon slice) so a resident daemon can call
/// the SAME construction once at startup and hold the result, instead of
/// re-running `load_all_proofs::run` (a full 96MB CBOR pool decode) on every
/// prove request.
pub fn load_pool(cfg: &RunnerConfig) -> MementoPool {
    let mut pool = load_all_proofs::run(&cfg.project_root);
    for extra in &cfg.extra_projects {
        let extra_pool = load_all_proofs::run(extra);
        pool.merge(extra_pool);
    }
    load_all_proofs::load_files_into_pool(&cfg.extra_proof_files, &mut pool);
    load_all_proofs::load_proof_bytes_into_pool(&cfg.extra_proofs, &mut pool);
    pool
}

/// Public wrapper around the solver-plan construction `Runner::new_with_compilers`
/// uses, so a resident daemon can build the identical `(SolverPlan, registry)`
/// once at startup rather than reimplementing solver config resolution.
pub fn build_plan_and_registry_pub(
    cfg: &RunnerConfig,
) -> (SolverPlan, HashMap<SolverSeat, SolverHandle>) {
    build_plan_and_registry(cfg)
}

fn build_plan_and_registry(cfg: &RunnerConfig) -> (SolverPlan, HashMap<SolverSeat, SolverHandle>) {
    if let Some(sc) = &cfg.solvers_config {
        return (SolverPlan::from_config(sc), registry::build(sc));
    }
    // Client-fed only (#3809 PR A): no SolversConfig::load(project_root).
    // Faces that want [solvers] from config.toml call SolversConfig::load
    // themselves and set cfg.solvers_config before constructing the Runner.
    let registry = cfg
        .legacy_z3_fallback
        .as_ref()
        .map(|fallback| registry::build_default_z3(&fallback.binary))
        .unwrap_or_default();
    (SolverPlan::Single(SolverSeat::Z3), registry)
}

/// One contract's self-post verification outcome.
struct SelfPostResult {
    contract_cid: String,
    verdict: ObligationVerdict,
    reason: String,
    method: Option<body_discharge::DischargeMethod>,
}

type CallsiteResult = (
    CallSite,
    ObligationVerdict,
    String,
    Option<String>,
    Option<String>,
);

fn callsite_row_is_owned_by_consistency(cs: &CallSite, pool: &MementoPool) -> bool {
    let Some(property_cid) = cs.property_cid.as_ref() else {
        return false;
    };
    let Some(body) = pool.contract_body_by_cid(property_cid) else {
        return false;
    };
    // A consistency candidate with linked body posts is a pool-level EUF
    // composition problem, not a set of independent per-callsite obligations.
    // Body-discharge can reduce one local view to `call:h(5) == 6`, but only
    // consistency owns the sibling facts/posts that define `call:h(5)`. Delegate
    // every local row for that property, regardless of its local verdict; the
    // consistency row below will add the authoritative pass or violation.
    crate::consistency::linked_post_instance_count(pool, &body) > 0
}

fn callsite_row_is_owned_by_self_post(cs: &CallSite, pool: &MementoPool) -> bool {
    let Some(property_cid) = cs.property_cid.as_ref() else {
        return false;
    };
    let Some(body) = pool.contract_body_by_cid(property_cid) else {
        return false;
    };
    let body_derived_post = body.get("post").is_some_and(|v| v.is_object())
        && body.get("formals").is_some_and(|v| v.is_array())
        && !body.get("inv").is_some_and(|v| v.is_object());
    if !body_derived_post {
        return false;
    }
    // Calls inside a body-derived post are the universe's own expression
    // (`out == call:h(x)`). The self-post pass owns that universe check. Keep
    // effect/pre-bearing sites visible: a panic/partial call still needs the
    // guard-discharge path, not a quiet self-post delegation.
    !cs.panic_site && !body_discharge::target_has_nontrivial_pre(cs, pool)
}

/// Verify each body-derived contract's OWN postcondition. For a contract
/// with `post = (result == <body>)` (and optionally a conjoined
/// entry-precondition), the self-post obligation is `post[result :=
/// <body>]`. The pure `result == body` conjunct becomes `body == body`,
/// proven by reflexivity over the (uninterpreted) body term; a conjoined
/// precondition (`x >= 10`) survives and keeps the obligation honest -- it
/// discharges only if unconditionally valid, otherwise z3 returns sat and
/// the verdict is undecidable. The substitution is the REAL one (not a
/// hand-built `v == v`), so the soundness property is exercised on the
/// real solver path.
fn verify_contract_self_posts(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> Vec<SelfPostResult> {
    let contracts: Vec<(MementoCid, Json)> = pool
        .contract_members_with_bodies()
        .map(|(cid, body)| (cid.clone(), body))
        .collect();

    contracts
        .par_iter()
        .filter_map(|(cid, body)| {
            // Body-derived contracts carry `formals` + `post`. A contract
            // without `post` (or without a result equation) has no
            // self-post to verify here.
            let post_json = body.get("post")?;
            let post: sugar_ir_types::IrFormula = serde_json::from_value(post_json.clone()).ok()?;
            let value_expr = libsugar::wp::find_result_equation(&post, "result")?;

            // Self-post obligation: post[result := <body value term>].
            let obligation_formula =
                libsugar::wp::substitute_in_formula(post, "result", &value_expr);
            let obligation_json = serde_json::to_value(&obligation_formula).ok()?;

            let obligation_input = match CompilerInput::decode_json(obligation_json.clone()) {
                Ok(input) => input,
                Err(error) => {
                    return Some(SelfPostResult {
                        contract_cid: cid.to_string(),
                        verdict: ObligationVerdict::Undecidable,
                        reason: format!("self-post frontend decode: {}", error.payload),
                        method: None,
                    });
                }
            };
            let (verdict, reason, _invs) =
                run_plan_with_compilers(plan, registry, compilers, &obligation_input);
            let method = if verdict == ObligationVerdict::Discharged {
                let m = body_discharge::classify_discharge_method(&obligation_json);
                Some(m)
            } else {
                None
            };
            let tagged_reason = match method {
                Some(m) => format!("[method={}] self-post: {reason}", m.as_str()),
                None => format!("self-post: {reason}"),
            };
            Some(SelfPostResult {
                contract_cid: cid.to_string(),
                verdict,
                reason: tagged_reason,
                method,
            })
        })
        .collect()
}

#[allow(clippy::too_many_arguments)]
fn work_one(
    cs: &CallSite,
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    cfg: &RunnerConfig,
    n_hash: &AtomicUsize,
    n_cache: &AtomicUsize,
    n_vacuous: &AtomicUsize,
    n_solved: &AtomicUsize,
    n_residue: &AtomicUsize,
    n_disagree: &AtomicUsize,
    n_invoc: &AtomicUsize,
    n_reflexive: &AtomicUsize,
    n_substantive: &AtomicUsize,
    invs_sink: &Mutex<Vec<SolverInvocation>>,
    minted_sink: &Mutex<Vec<(MementoCid, Json)>>,
) -> CallsiteResult {
    // #3809 cut #7: disk tier-2 removed; n_cache was tier-2 hit counter.
    // minted_sink is live again for prove-then-feed (in-pool only, no disk).
    let _ = (n_cache, cfg);

    if let Some(result) = crate::attribute_safety::try_discharge(cs, pool) {
        if result.verdict == ObligationVerdict::Discharged {
            n_solved.fetch_add(1, Ordering::Relaxed);
            n_substantive.fetch_add(1, Ordering::Relaxed);
        } else {
            n_residue.fetch_add(1, Ordering::Relaxed);
        }
        return (
            cs.clone(),
            result.verdict,
            result.reason,
            result.discharge_method,
            None,
        );
    }

    // ROUTING (the call-site-obligation precedence rule, generic + language-blind):
    // if the resolved TARGET CONTRACT carries a non-trivial `pre` (a real
    // precondition, not None/true), this call-site obligation is to DISCHARGE
    // THAT `pre` UNDER THE GUARD CONTEXT (`cs.guard_facts`), and that discharge
    // takes PRECEDENCE over the reflexive self-post path. So we SKIP
    // `extract_body_obligation` (which would otherwise reduce the callee's
    // body-derived self-post to `unwrap(opt) == unwrap(opt)` and discharge it
    // REFLEXIVELY -- a vacuous pass that, on an UNGUARDED pre-bearing call,
    // would falsely report "cannot panic"). The reflexive self-post path below
    // applies ONLY when the target has no pre. The verifier recognizes no
    // predicate name: the rule keys purely on "target has a non-trivial pre."
    let target_has_pre = body_discharge::target_has_nontrivial_pre(cs, pool);
    if target_has_pre {
        debug!(
            bridge = %cs.bridge_ir_name,
            target_cid = ?cs.bridge_target_cid,
            guard_facts = cs.guard_facts.len(),
            "work_one: target carries a non-trivial pre -> routing to guard-discharge \
             (precondition under guards), skipping reflexive self-post body-discharge"
        );
    }
    if !target_has_pre {
        match body_discharge::extract_body_obligation(cs, pool) {
            Ok(Some(body_discharge::BodyObligation::Reduced {
                formula: reduced,
                tier,
            })) => {
                let body_tier = Some(tier.as_str().to_string());
                let reduced_input = match CompilerInput::decode_json(reduced.clone()) {
                    Ok(input) => input,
                    Err(error) => {
                        n_residue.fetch_add(1, Ordering::Relaxed);
                        return (
                            cs.clone(),
                            ObligationVerdict::Undecidable,
                            format!("body-discharge frontend decode: {}", error.payload),
                            None,
                            body_tier,
                        );
                    }
                };
                let (verdict, mut reason, invs) =
                    run_plan_with_compilers(plan, registry, compilers, &reduced_input);
                let mut discharge_method = None;
                n_invoc.fetch_add(invs.len(), Ordering::Relaxed);
                if verdict == ObligationVerdict::Discharged {
                    n_solved.fetch_add(1, Ordering::Relaxed);
                    // Tag HOW it discharged: a self-derived post reduces to
                    // `<term> == <term>` and is proven by reflexivity over
                    // uninterpreted ctors (sound but shallow); anything else is
                    // substantive solver work. Counted apart so a reflexive
                    // discharge is never conflated with a meaningful proof. The
                    // method is also stamped on the row reason so the receipt
                    // surfaces the split per-callsite.
                    let method = body_discharge::classify_discharge_method(&reduced);
                    match method {
                        body_discharge::DischargeMethod::Reflexive => {
                            n_reflexive.fetch_add(1, Ordering::Relaxed);
                        }
                        body_discharge::DischargeMethod::Substantive => {
                            n_substantive.fetch_add(1, Ordering::Relaxed);
                        }
                    }
                    reason = format!("[method={}] {reason}", method.as_str());
                    discharge_method = Some(method.as_str().to_string());
                } else if verdict == ObligationVerdict::Disagreement {
                    n_disagree.fetch_add(1, Ordering::Relaxed);
                    n_residue.fetch_add(1, Ordering::Relaxed);
                } else {
                    n_residue.fetch_add(1, Ordering::Relaxed);
                }
                if let Ok(mut g) = invs_sink.lock() {
                    g.extend(invs);
                }
                return (cs.clone(), verdict, reason, discharge_method, body_tier);
            }
            Ok(None) => {}
            Err(e) => {
                n_residue.fetch_add(1, Ordering::Relaxed);
                return (
                    cs.clone(),
                    ObligationVerdict::Undecidable,
                    format!("body-discharge: {e}"),
                    None,
                    None,
                );
            }
        }
    }

    let resolved = match resolve_target::run(cs, pool) {
        Ok(r) => r,
        Err(e) => {
            n_residue.fetch_add(1, Ordering::Relaxed);
            return (
                cs.clone(),
                ObligationVerdict::Undecidable,
                format!("resolve-target: {e}"),
                None,
                None,
            );
        }
    };

    if resolved.ir_formula.is_none() {
        // HONESTY BOUNDARY (mirrors cmd_verify::verify_one_claim). The
        // vacuous-discharge shortcut ("no precondition => nothing to prove")
        // is legitimate ONLY for a genuinely non-body-bearing, claim-free
        // target. Two shapes are refused before reaching the vacuous branch:
        //
        // 1. Body-bearing (carries `formals`): a body-derived op-contract
        //    whose obligation the runner did NOT reduce. Vacuous-passing it
        //    would be a false green.
        //
        // 2. Post-bearing (carries `post` but no `formals` and no `pre`):
        //    a "publisher post-only" contract that asserts a specific output
        //    value (e.g. `eq(out, "AAAA")`). This is an obligation-carrying
        //    shape — the post makes a factual claim that must be verified
        //    against the callsite, not skipped. A FALSE claim (e.g.
        //    encodeVendor(abc)=="AAAA" when the real encoding is "YWJj")
        //    must NOT vacuously discharge; it must be Undecidable (no
        //    universe supplied to refute or confirm it at this tier).
        //
        // The vacuous path is only legitimate for targets that are truly
        // claim-free: no pre, no post (e.g. a bare structural marker).
        if resolved.target_is_body_bearing {
            n_residue.fetch_add(1, Ordering::Relaxed);
            return (
                cs.clone(),
                ObligationVerdict::Undecidable,
                format!(
                    "body-discharge: refuse: target `{}` is body-bearing \
                     (carries `formals`) but the runner did not reduce its \
                     obligation and it has no precondition; refusing rather \
                     than reporting a vacuous pass",
                    cs.bridge_ir_name
                ),
                None,
                None,
            );
        }
        if resolved.target_has_post {
            n_residue.fetch_add(1, Ordering::Relaxed);
            return (
                cs.clone(),
                ObligationVerdict::Undecidable,
                format!(
                    "vacuous-door: refuse: target `{}` carries a `post` but \
                     no `pre` and no `formals`; a lone opaque equality \
                     obligation has no constraining universe at this tier \
                     and must not vacuously discharge",
                    cs.bridge_ir_name
                ),
                None,
                None,
            );
        }
        n_vacuous.fetch_add(1, Ordering::Relaxed);
        return (
            cs.clone(),
            ObligationVerdict::Discharged,
            "vacuous: no precondition on target (publisher post-only)".into(),
            Some("vacuous".to_string()),
            None,
        );
    }

    let consumer_pre = resolved.ir_formula.as_ref();
    let consumer_pre_hash = consumer_pre.map(formula_hash);
    // Producer-post resolution governs the IMPLICATION composition path only
    // (Tier 0c/1/2 and the Tier-3 `post -> pre` form). For a PANIC site that
    // path is never the sound one: the unwrap pre is `is_ok(receiver)` and the
    // only producer post that could entail it is the callee totality `is_ok`,
    // so the implication degenerates to the reflexive `is_ok(X) -> is_ok(X)`
    // tautology. z3 discharges it WITHOUT using the totality axiom, and the
    // refuse-floor (report_fmt) correctly flags any non-`panic-safe` discharge
    // of a panic site as a false pass. So a panic site resolves NO producer
    // post here; it falls through to the guard branch (the `else` below), where
    // `callee_post_guard_fact` supplies `is_ok(arg)` ONLY when the receiver's
    // co-located (callsite-scoped via `bridges_by_callsite`) target contract
    // carries the exact `is_ok(result)` totality singleton (body_discharge.rs).
    // That is the single floor-sanctioned panic-safe path: f@25 (Value totality)
    // discharges panic-safe; g@38 (MyStruct, no totality) gets None -> stays
    // undecidable. Non-panic sites keep the per-symbol implication path
    // byte-for-byte.
    //
    // ASSUMPTION (name it, do not bury it): no panic site benefits from a
    // SUBSTANTIVE (non-reflexive) implication composition. True for the current
    // unwrap/expect + is_ok scope. A future bounds-check tier wanting
    // `len > idx |- idx < len` for an index panic would need to revisit this
    // blanket null and route such sites to a substantive (still floor-audited)
    // discharge rather than the guard-fact path.
    let producer_post = if cs.panic_site {
        None
    } else {
        pool.producer_post_for_arg_term(&cs.arg_term)
    };

    // Tier 0: Memento IS verification. Look up the formula CID in the pool.
    // The hash IS the boundary: we verify by hash lookup, not by solving.
    if let Some(pre_formula) = consumer_pre {
        if let Some(memento) = pool.verify(pre_formula) {
            n_hash.fetch_add(1, Ordering::Relaxed);
            return (
                cs.clone(),
                ObligationVerdict::Discharged,
                format!(
                    "tier0: memento-is-verification (cid={})",
                    short(memento.cid().as_str())
                ),
                Some("hash-tier".to_string()),
                None,
            );
        }

        // Tier 0b: Sub-formula composition. If parts of the formula are
        // already verified, note them for partial discharge.
        let verified_subs = pool.find_verified_subformulas(pre_formula);
        if !verified_subs.is_empty() {
            // TODO: In v1, use verified_subs to build a reduced obligation
            // for the solver. For now, we just note it in telemetry.
            let sub_cids: Vec<String> = verified_subs
                .into_iter()
                .map(|(cid, _)| short(&cid))
                .collect();
            debug!(
                bridge = %cs.bridge_ir_name,
                sub_formula_count = sub_cids.len(),
                sub_cids = %sub_cids.join(", "),
                "work_one: formula has verified sub-formulas (partial discharge candidate)"
            );
        }
    }

    if let (Some(pre_hash), Some((_post_formula, post_hash))) =
        (consumer_pre_hash.as_ref(), producer_post.as_ref())
    {
        // Tier 0c: Implication composition. Is postA → preB already
        // proven in the memento pool? Direct or transitive?
        match pool.can_implies(post_hash, pre_hash) {
            crate::types::ImplicationResult::ProvenDirect { memento_cid } => {
                n_hash.fetch_add(1, Ordering::Relaxed);
                return (
                    cs.clone(),
                    ObligationVerdict::Discharged,
                    format!(
                        "tier0c: implication proven direct (memento {})",
                        short(&memento_cid)
                    ),
                    Some("hash-tier".to_string()),
                    None,
                );
            }
            crate::types::ImplicationResult::ProvenTransitive { path } => {
                n_hash.fetch_add(1, Ordering::Relaxed);
                let path_str = path
                    .iter()
                    .map(|s| short(s))
                    .collect::<Vec<_>>()
                    .join(" → ");
                return (
                    cs.clone(),
                    ObligationVerdict::Discharged,
                    format!("tier0c: implication proven transitive ({path_str})"),
                    Some("hash-tier".to_string()),
                    None,
                );
            }
            crate::types::ImplicationResult::ProvenReflexive => {
                n_hash.fetch_add(1, Ordering::Relaxed);
                return (
                    cs.clone(),
                    ObligationVerdict::Discharged,
                    "tier0c: implication reflexive (post == pre)".into(),
                    Some("hash-tier".to_string()),
                    None,
                );
            }
            crate::types::ImplicationResult::Unknown => {}
        }

        if try_tier1(post_hash, pre_hash) {
            n_hash.fetch_add(1, Ordering::Relaxed);
            return (
                cs.clone(),
                ObligationVerdict::Discharged,
                format!(
                    "tier1: hash equality (post == pre, hash={})",
                    short(pre_hash)
                ),
                Some("hash-tier".to_string()),
                None,
            );
        }
        // #3809 cut #7: no tier-2 `cache_dir` disk lookup. In-pool
        // ImplicationMemento discharge is Tier 0c (`can_implies`) above.
    }

    // Tier 3: build the ProofIR obligation and run the configured plan.
    let formula_for_dispatch: Json;
    let used_implication_form: bool;

    if let (Some((post_formula, _)), Some(pre_formula)) = (producer_post.as_ref(), consumer_pre) {
        used_implication_form = true;
        let implication = match build_implication_obligation(post_formula, pre_formula) {
            Ok(f) => f,
            Err(e) => {
                n_residue.fetch_add(1, Ordering::Relaxed);
                return (
                    cs.clone(),
                    ObligationVerdict::Undecidable,
                    format!("build-implication: {e}"),
                    None,
                    None,
                );
            }
        };

        // Tier 3a: Apply proof tactics before invoking solver.
        // Contrapositive, sub-formula weakening, etc.
        match formula_rewrite::apply_tactics(&implication, pool) {
            formula_rewrite::TacticResult::Discharged { reason } => {
                n_solved.fetch_add(1, Ordering::Relaxed);
                // Prove-then-feed: tactic discharge is real discharge.
                if let (Some((_, post_hash)), Some(pre_hash)) =
                    (producer_post.as_ref(), consumer_pre_hash.as_ref())
                {
                    queue_proven_implication(minted_sink, post_hash, pre_hash, "tier3a-tactic", 0);
                }
                return (
                    cs.clone(),
                    ObligationVerdict::Discharged,
                    format!("tier3a: tactic discharged ({reason})"),
                    Some("solver-substantive".to_string()),
                    None,
                );
            }
            formula_rewrite::TacticResult::Reduced {
                new_formula,
                reason: _,
            } => {
                formula_for_dispatch = new_formula;
                // Continue to solver with reduced formula
            }
            formula_rewrite::TacticResult::NoChange => {
                formula_for_dispatch = implication;
            }
        }
    } else {
        used_implication_form = false;
        let actual_terms = callsite_actual_terms(cs);
        let ob = match instantiate::run_specialized(
            &resolved,
            &actual_terms,
            cs.formal_actuals.as_ref(),
        ) {
            Ok(o) => o,
            Err(e) => {
                n_residue.fetch_add(1, Ordering::Relaxed);
                return (
                    cs.clone(),
                    ObligationVerdict::Undecidable,
                    format!("instantiate: {e}"),
                    None,
                    None,
                );
            }
        };
        // PANIC-FREEDOM guard discharge. A panic partial's instantiated pre is
        // an uninterpreted predicate over a free term (e.g. `is_some(recv)`),
        // unprovable on its own -> the site is honestly undecidable. But when
        // the call is DOMINATED by the matching guard, the Rust KIT has wrapped
        // the dominated branch in `cf_guarded(<resolved-predicate>, value)` (the
        // kit, not this verifier, knows which predicate governs a branch), and
        // enumerate_callsites threads that opaque atom into `cs.guard_facts`.
        // The obligation becomes `(and guard_facts) => pre`. With the kit's
        // then-branch guard syntactically identical to the partial's pre after
        // substitution, the implication is valid -> PROVABLY panic-safe. An
        // unwrapped site has empty guard_facts and keeps the bare (unprovable)
        // pre, so it stays undecidable. An else-branch site carries the kit's
        // COMPLEMENT predicate, which never establishes the positive pre, so it
        // also stays undecidable. Fail-safe by construction: no path marks an
        // unguarded site panic-safe. This verifier recognizes no predicate name.
        // The call-site obligation is the target pre SPECIALIZED to this
        // call's actual terms (`pre[formal_i := actual_i]`, free vars), never a
        // source-language effect model. `run_specialized` returns that bare
        // predicate directly. Keep the strip as a defensive no-op for older
        // hand-built obligations that still arrive with one redundant outer
        // forall.
        let specialized = instantiate::strip_outer_forall(&ob.ir_formula);
        if specialized != ob.ir_formula {
            debug!(
                bridge = %cs.bridge_ir_name,
                before = %ob.ir_formula,
                after = %specialized,
                "work_one: panic obligation: stripped redundant outer forall -> specialized \
                 pre over the free callsite arg (avoids guard-var capture and the opaque-sort \
                 `forall`->`true` emitter collapse)"
            );
        }
        // D-lib (cross-function-postcondition-as-assumable-fact): if the panic
        // receiver is itself a call whose bridge target carries the strengthened
        // `is_ok(result)` totality post, inject `is_ok(arg)` as a guard fact.
        // This is the SAME language-blind mechanism cmd_verify uses; the prove
        // path (the scoreboard's path) was missing it, so every D-lib panic site
        // stayed unguarded -> undecidable. callee_post_guard_fact returns None
        // for a non-total receiver (generic Result), preserving the refuse-floor.
        let mut all_guard_facts: Vec<Json> = cs.guard_facts.clone();
        if let Some(callee_fact) = callee_post_guard_fact(cs, pool) {
            debug!(
                bridge = %cs.bridge_ir_name,
                callee_fact = %callee_fact,
                "work_one: D-lib callee post supplies is_ok guard fact (totality contract on \
                 the unwrap receiver -> adding is_ok(arg) to guard context)"
            );
            all_guard_facts.push(callee_fact);
        }
        let guarded_formula = if all_guard_facts.is_empty() {
            info!(
                bridge = %cs.bridge_ir_name,
                target_cid = ?cs.bridge_target_cid,
                obligation = %specialized,
                "work_one: UNGUARDED panic site -> bare specialized pre obligation (no guard \
                 establishes it; the solver must leave it SAT-for-negation -> NOT-discharged: \
                 the refuse-floor negative control)"
            );
            specialized
        } else {
            let antecedent = if all_guard_facts.len() == 1 {
                all_guard_facts[0].clone()
            } else {
                json!({ "kind": "and", "operands": all_guard_facts.clone() })
            };
            let guarded = json!({
                "kind": "implies",
                "operands": [antecedent, specialized],
            });
            info!(
                bridge = %cs.bridge_ir_name,
                target_cid = ?cs.bridge_target_cid,
                guard_count = cs.guard_facts.len(),
                antecedent = %antecedent,
                obligation = %guarded,
                "work_one: GUARDED panic site -> `(and guard_facts) => pre` obligation \
                 (the guard must establish the pre; expected discharged)"
            );
            guarded
        };
        formula_for_dispatch = guarded_formula;
    }

    debug!(
        bridge = %cs.bridge_ir_name,
        "work_one: invoking solver plan (tier 3)"
    );
    let formula_input = match CompilerInput::decode_json(formula_for_dispatch.clone()) {
        Ok(input) => input,
        Err(error) => {
            n_residue.fetch_add(1, Ordering::Relaxed);
            return (
                cs.clone(),
                ObligationVerdict::Undecidable,
                format!("frontend decode: {}", error.payload),
                None,
                None,
            );
        }
    };
    let (verdict, reason, invs) =
        run_plan_with_compilers(plan, registry, compilers, &formula_input);

    debug!(
        bridge = %cs.bridge_ir_name,
        verdict = ?verdict,
        reason = %reason,
        solver_invocations = invs.len(),
        "work_one: solver plan verdict"
    );
    n_invoc.fetch_add(invs.len(), Ordering::Relaxed);

    if verdict == ObligationVerdict::Disagreement {
        n_disagree.fetch_add(1, Ordering::Relaxed);
        n_residue.fetch_add(1, Ordering::Relaxed);
    }

    // Prove-then-feed (#3809 D2 option 1): ONLY after real discharge of the
    // implication form, mint an ImplicationMemento keyed by the same
    // formula_hash pair Tier 0c looks up. Never mint on unsat/refuse — a
    // lying twin must not enter the pool (Tier 0c would false-green).
    if verdict == ObligationVerdict::Discharged && used_implication_form {
        n_solved.fetch_add(1, Ordering::Relaxed);
        if let (Some((_, post_hash)), Some(pre_hash)) =
            (producer_post.as_ref(), consumer_pre_hash.as_ref())
        {
            let prover_tag = invs
                .first()
                .map(|inv| format!("{}@{}", inv.result.solver_name, inv.result.solver_version))
                .unwrap_or_else(|| "tier3-discharged".to_string());
            let prover_run_ms = invs
                .first()
                .map(|inv| inv.result.wall_clock.as_millis() as i64)
                .unwrap_or(0);
            queue_proven_implication(minted_sink, post_hash, pre_hash, &prover_tag, prover_run_ms);
        }
    }
    if verdict != ObligationVerdict::Discharged && verdict != ObligationVerdict::Disagreement {
        n_residue.fetch_add(1, Ordering::Relaxed);
    }

    // Push telemetry into the sink.
    if let Ok(mut g) = invs_sink.lock() {
        g.extend(invs);
    }

    let discharge_method = if verdict == ObligationVerdict::Discharged {
        if !used_implication_form && cs.panic_site {
            Some("panic-safe".to_string())
        } else {
            Some("solver-substantive".to_string())
        }
    } else {
        None
    };

    (cs.clone(), verdict, reason, discharge_method, None)
}

/// Deterministic prove-then-feed seal (pure of endpoint hashes under fixed seed).
/// Distinct from step-1 `OBLIGATION_SEAL_*` (edge identity utterance); this
/// memento is minted only after discharge and is what Tier 0c treats as proven.
const PROVE_THEN_FEED_SEED: sugar_proof_envelope::Ed25519Seed = [0x0cu8; 32];
const PROVE_THEN_FEED_AT: &str = "1970-01-01T00:00:00.000Z";

/// Mint an ImplicationMemento for a **already-discharged** `post ⊃ pre` edge.
///
/// Endpoint hashes MUST be the same `formula_hash` values Tier 0c uses
/// (`runner` `post_hash` / `pre_hash`). Mint-convention `verdict: "holds"` is
/// not itself proof — callers must only invoke this after real discharge.
fn mint_proven_implication_memento(
    post_hash: &str,
    pre_hash: &str,
    prover: &str,
    prover_run_ms: i64,
) -> Result<(MementoCid, Json), String> {
    use sugar_claim_envelope::{mint_implication, MintImplicationArgs};
    use sugar_proof_envelope::ContractMementoRef;

    let args = MintImplicationArgs {
        produced_by: "sugar-verifier/prove-then-feed".into(),
        produced_at: PROVE_THEN_FEED_AT.into(),
        antecedent_hash: post_hash.to_string(),
        consequent_hash: pre_hash.to_string(),
        // Formula-level endpoints: hash IS identity for Tier 0c lookup.
        antecedent: ContractMementoRef::new(post_hash.to_string()),
        consequent: ContractMementoRef::new(pre_hash.to_string()),
        additional_inputs: Vec::new(),
        antecedent_slot: "post".into(),
        consequent_slot: "pre".into(),
        prover: prover.to_string(),
        prover_run_ms,
        smt_lib_input: String::new(),
        proof_witness: "(unsat)".into(),
        signer_seed: PROVE_THEN_FEED_SEED,
    };
    let minted = mint_implication(&args);
    let envelope: Json = serde_json::from_slice(&minted.canonical_bytes)
        .map_err(|e| format!("prove-then-feed: decode minted memento: {e}"))?;
    let cid = MementoCid::try_parse(minted.cid.clone())
        .map_err(|e| format!("prove-then-feed: invalid minted CID {}: {e}", minted.cid))?;
    Ok((cid, envelope))
}

/// Queue a proven implication for pool insert after parallel fan-out.
/// No-op on mint failure (warn); discharge already succeeded — reuse is best-effort.
fn queue_proven_implication(
    minted_sink: &Mutex<Vec<(MementoCid, Json)>>,
    post_hash: &str,
    pre_hash: &str,
    prover: &str,
    prover_run_ms: i64,
) {
    match mint_proven_implication_memento(post_hash, pre_hash, prover, prover_run_ms) {
        Ok((cid, envelope)) => {
            if let Ok(mut g) = minted_sink.lock() {
                g.push((cid, envelope));
            }
        }
        Err(e) => {
            warn!(
                post = %short(post_hash),
                pre = %short(pre_hash),
                error = %e,
                "prove-then-feed: mint after discharge failed (reuse skipped)"
            );
        }
    }
}

fn callsite_actual_terms(cs: &CallSite) -> Vec<Json> {
    if !cs.arg_terms.is_empty() {
        return cs.arg_terms.clone();
    }
    cs.arg_term.iter().cloned().collect()
}

fn short(s: &str) -> String {
    let cleaned = sugar_canonicalizer::cid_hex(s).unwrap_or(s);
    let take: String = cleaned.chars().take(12).collect();
    format!("blake3-512:{take}...")
}

fn build_implication_obligation(post_formula: &Json, pre_formula: &Json) -> Result<Json, String> {
    let post_obj = post_formula.as_object().ok_or("post is not an object")?;
    let pre_obj = pre_formula.as_object().ok_or("pre is not an object")?;
    if post_obj.get("kind").and_then(|v| v.as_str()) != Some("forall") {
        return Err("post is not a forall".into());
    }
    if pre_obj.get("kind").and_then(|v| v.as_str()) != Some("forall") {
        return Err("pre is not a forall".into());
    }
    let post_name = post_obj
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or("post forall name missing")?;
    let pre_name = pre_obj
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or("pre forall name missing")?;
    let sort = post_obj.get("sort").cloned().unwrap_or_else(|| {
        pre_obj
            .get("sort")
            .cloned()
            .unwrap_or_else(|| serde_json::json!({"kind":"primitive","name":"Int"}))
    });
    let post_body = post_obj.get("body").cloned().ok_or("post body missing")?;
    let pre_body = pre_obj.get("body").cloned().ok_or("pre body missing")?;

    let shared = "_h0";
    let replacement = serde_json::json!({"kind": "var", "name": shared});
    let post_body_renamed =
        crate::instantiate::substitute_formula_pub(&post_body, post_name, &replacement);
    let pre_body_renamed =
        crate::instantiate::substitute_formula_pub(&pre_body, pre_name, &replacement);

    Ok(serde_json::json!({
        "kind": "forall",
        "name": shared,
        "sort": sort,
        "body": {
            "kind": "implies",
            "operands": [post_body_renamed, pre_body_renamed]
        }
    }))
}

#[cfg(test)]
mod consistency_owned_callsite_tests {
    use super::*;
    use crate::BridgePin;
    use serde_json::json;

    fn cid_string(seed: &str) -> String {
        sugar_canonicalizer::blake3_512_of(seed.as_bytes())
    }

    fn memento_cid(cid: &str) -> MementoCid {
        MementoCid::try_parse(cid.to_string()).expect("test CID must parse")
    }

    fn generated_cid(seed: &str) -> MementoCid {
        memento_cid(&cid_string(seed))
    }

    fn string_const(s: &str) -> Json {
        json!({"kind":"const","value":s,"sort":{"kind":"primitive","name":"String"}})
    }

    fn eqf(a: Json, b: Json) -> Json {
        json!({"kind":"atomic","name":"=","args":[a,b]})
    }

    fn linked_pool_and_callsite() -> (MementoPool, CallSite, MementoCid) {
        let source_symbol = "call:enc";
        let vendor_cid = cid_string("vendor-enc");
        let assertion_cid = cid_string("consumer-assertion");
        let bridge_cid = generated_cid("linked-post-bridge");
        let call = json!({"kind":"ctor","name":source_symbol,"args":[string_const("def")]});
        let assertion = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "src/lib.rs::tests::fresh_vendor_fol_good::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion",
                    "inv": eqf(call, string_const("ghi"))
                }
            }
        });
        let vendor = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "rust-source::enc",
                    "formals": ["input"],
                    "outBinding": "out",
                    "post": {
                        "kind": "implies",
                        "operands": [
                            eqf(json!({"kind":"var","name":"input"}), string_const("def")),
                            eqf(json!({"kind":"var","name":"out"}), string_const("ghi"))
                        ]
                    }
                }
            }
        });
        let bridge = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": source_symbol,
                    "targetContractCid": vendor_cid.clone()
                }
            }
        });
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(memento_cid(&assertion_cid), assertion);
        pool.insert_unanchored_for_tests(memento_cid(&vendor_cid), vendor);
        pool.insert_bridge_by_symbol(source_symbol, bridge_cid.clone(), bridge);
        let cs = CallSite {
            bridge_ir_name: source_symbol.to_string(),
            property_name: "src/lib.rs::tests::fresh_vendor_fol_good::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion".to_string(),
            property_cid: Some(memento_cid(&assertion_cid)),
            ..CallSite::default()
        };
        (pool, cs, bridge_cid)
    }

    #[test]
    fn linked_assertion_callsite_row_is_owned_by_consistency() {
        let (pool, cs, _) = linked_pool_and_callsite();
        assert!(callsite_row_is_owned_by_consistency(&cs, &pool));
    }

    #[test]
    fn unlinked_assertion_callsite_row_stays_visible() {
        let (mut pool, cs, bridge_cid) = linked_pool_and_callsite();
        pool.bridges_by_symbol.clear();
        pool.mementos.remove(&bridge_cid);
        assert!(!callsite_row_is_owned_by_consistency(&cs, &pool));
    }

    fn make_unique_cache_dir(label: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "sugar-tier2-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).expect("create cache dir");
        dir
    }

    fn json_to_canonical_value(value: &Json) -> std::sync::Arc<sugar_canonicalizer::Value> {
        match value {
            Json::Null => sugar_canonicalizer::Value::null(),
            Json::Bool(v) => sugar_canonicalizer::Value::boolean(*v),
            Json::Number(n) => {
                if let Some(i) = n.as_i64() {
                    sugar_canonicalizer::Value::integer(i128::from(i))
                } else if let Some(u) = n.as_u64() {
                    sugar_canonicalizer::Value::integer(i128::from(u))
                } else if let Some(f) = n.as_f64() {
                    sugar_canonicalizer::Value::string(f.to_string())
                } else {
                    sugar_canonicalizer::Value::null()
                }
            }
            Json::String(s) => sugar_canonicalizer::Value::string(s.clone()),
            Json::Array(items) => sugar_canonicalizer::Value::array(
                items.iter().map(json_to_canonical_value).collect(),
            ),
            Json::Object(map) => sugar_canonicalizer::Value::object(
                map.iter()
                    .map(|(k, v)| (k.as_str(), json_to_canonical_value(v)))
                    .collect::<Vec<_>>(),
            ),
        }
    }

    fn jcs(value: &Json) -> String {
        sugar_canonicalizer::encode_jcs(&json_to_canonical_value(value))
    }

    #[test]
    fn legacy_z3_path_is_explicit_compat_fallback_not_runner_config_string() {
        let cfg = RunnerConfig {
            legacy_z3_fallback: Some(LegacyZ3Fallback::compat("z3")),
            ..RunnerConfig::default()
        };

        let (plan, registry) = build_plan_and_registry(&cfg);

        assert!(matches!(plan, SolverPlan::Single(SolverSeat::Z3)));
        assert!(
            registry.contains_key(&SolverSeat::Z3),
            "compat fallback should still build the legacy z3 registry when explicitly requested"
        );
    }

    #[test]
    fn smt_emit_stage_vocabulary_is_single_sourced_and_legacy_receipts_replay() {
        assert_eq!(STAGE_SMT_EMIT, "smt_emit");
        assert!(VERIFIER_STAGE_VOCABULARY.contains(&STAGE_SMT_EMIT));
        assert!(
            !VERIFIER_STAGE_VOCABULARY.contains(&"smt_emitter"),
            "pipeline v1 uses the current wire label, while old receipt labels remain replayable"
        );

        let legacy = make_stage_receipt(
            "smt_emitter",
            vec![cid_string("legacy-input")],
            vec![cid_string("legacy-output")],
            Vec::new(),
            Vec::new(),
            "2026-07-02T00:00:00Z".to_string(),
            "2026-07-02T00:00:01Z".to_string(),
            sugar_ir_types::StageVerdict::Ok,
        )
        .expect("legacy stage receipt labels remain tstr replay data");
        assert_eq!(legacy.header.stage_name, "smt_emitter");
    }

    #[test]
    fn proof_run_bundle_embeds_plan_artifact_and_references_plan_cid() {
        let plan_body = json!({
            "kind": "component-plan-artifact",
            "schemaVersion": "1",
            "selectionInputs": {
                "projectRoot": "/tmp/sugar-plan",
                "intent": "prove",
                "allowFailedComponents": false
            },
            "selectedComponents": [{
                "name": "fixture-lift",
                "version": "1.0.0",
                "protocolVersion": "component-plan.v1",
                "command": ["fixture-lift"],
                "workingDir": "/tmp/sugar-plan",
                "source": "/tmp/sugar-plan/sugar.toml",
                "sourceCid": cid_string("fixture-lift-manifest")
            }]
        });
        let plan_cid = sugar_canonicalizer::blake3_512_of(jcs(&plan_body).as_bytes());
        let member = json!({
            "body": plan_body,
            "header": {
                "kind": "plan-memento",
                "planCid": plan_cid
            },
            "schemaVersion": "1"
        });
        let member_bytes = jcs(&member).into_bytes();
        let member_cid = sugar_canonicalizer::blake3_512_of(&member_bytes);
        let plan_artifact = PlanArtifactInput {
            plan_cid: plan_cid.clone(),
            member_cid: member_cid.clone(),
            member_bytes: member_bytes.clone(),
        };

        let stage = make_stage_receipt(
            "load_all_proofs",
            vec![cid_string("proof-envelope")],
            vec![cid_string("loaded-proof")],
            Vec::new(),
            Vec::new(),
            "2026-07-02T00:00:00Z".to_string(),
            "2026-07-02T00:00:01Z".to_string(),
            sugar_ir_types::StageVerdict::Ok,
        )
        .expect("stage receipt");
        let memento = make_proof_run_memento(
            vec![stage.header.cid.clone()],
            vec![cid_string("proof-envelope"), plan_cid.clone()],
            vec![cid_string("proof-run-output")],
            cid_string("proof-envelope"),
            cid_string("link-bundle"),
            cid_string("plugin-registry"),
            sugar_ir_types::ProofRunVerdict::Admissible,
        )
        .expect("proof-run memento");

        assert!(
            memento.header.input_artifact_cids.contains(&plan_cid),
            "proof-run input pins must reference the selected component PlanArtifact"
        );

        let project_root = make_unique_cache_dir("plan-artifact-bundle");
        let (bundle_cid, bytes) = write_proof_run_bundle(&memento, &[stage], Some(&plan_artifact))
            .expect("proof-run bundle");
        // Face-side persist (solve never writes).
        let bundle_path =
            persist_proof_run_to_project(&project_root, &bundle_cid, &bytes).expect("persist");
        assert!(bundle_path.exists());
        let graph = sugar_proof_envelope::ProofGraph::read(&bytes).expect("read proof graph");
        let plans = graph.plans().collect::<Vec<_>>();
        assert_eq!(
            plans.len(),
            1,
            "proof-run bundle must carry exactly the pinned PlanArtifact memento"
        );
        assert_eq!(plans[0].cid().as_str(), plan_artifact.member_cid);
        assert_eq!(plans[0].bytes(), plan_artifact.member_bytes.as_slice());
        assert_eq!(
            plans[0].field("planCid").as_deref(),
            Some(plan_artifact.plan_cid.as_str())
        );

        let _ = std::fs::remove_dir_all(project_root);
    }
}

#[cfg(test)]
mod prove_then_feed_teeth {
    //! #3809 D2 prove-then-feed teeth: truthful edge seals and Tier 0c hits;
    //! lying twin is never sealed so Tier 0c stays Unknown.
    //! Force-sealing a lying twin would false-green Tier 0c — that path is
    //! rejected; production only mints after Discharged.

    use super::*;
    use crate::handshake::formula_hash;
    use crate::types::ImplicationResult;
    use serde_json::json;

    fn forall_ge(name: &str, n: i64) -> Json {
        json!({
            "kind": "forall",
            "name": name,
            "sort": {"kind": "primitive", "name": "Int"},
            "body": {
                "kind": "atomic",
                "name": ">=",
                "args": [
                    {"kind": "var", "name": name},
                    {"kind": "const", "value": n, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        })
    }

    /// Truthful: after real discharge we mint; Tier 0c proves direct.
    #[test]
    fn truthful_post_implies_pre_seals_and_tier0c_hits() {
        // Stronger post (x>=5) vs weaker pre (x>=0): hashes differ; need a
        // sealed implication memento for Tier 0c (not mere reflexivity).
        let post = forall_ge("x", 5);
        let pre = forall_ge("x", 0);
        let post_hash = formula_hash(&post);
        let pre_hash = formula_hash(&pre);
        assert_ne!(
            post_hash, pre_hash,
            "teeth need a non-reflexive edge so Tier 0c needs a memento"
        );

        // Simulate cold path: discharge succeeded → prove-then-feed mint.
        let (cid, envelope) =
            mint_proven_implication_memento(&post_hash, &pre_hash, "teeth-truthful", 0)
                .expect("mint after discharge");

        let mut pool = MementoPool::default();
        // Production inserts via AnchoredMember after fan-out; tests use the
        // same unanchored helper as other pool fixture paths.
        pool.insert_unanchored_for_tests(cid, envelope);

        match pool.can_implies(&post_hash, &pre_hash) {
            ImplicationResult::ProvenDirect { memento_cid } => {
                assert!(
                    !memento_cid.is_empty(),
                    "Tier 0c must cite the sealed memento"
                );
            }
            other => panic!("truthful sealed edge must Tier 0c ProvenDirect, got {other:?}"),
        }
    }

    /// Lying twin: never sealed → Tier 0c Unknown (must not short-circuit green).
    #[test]
    fn lying_twin_never_sealed_tier0c_unknown() {
        let post = forall_ge("x", 0); // weaker
        let pre = forall_ge("x", 5); // stronger — does NOT follow
        let post_hash = formula_hash(&post);
        let pre_hash = formula_hash(&pre);

        // Production: Unsatisfied ⇒ no queue_proven_implication call.
        let pool = MementoPool::default();
        match pool.can_implies(&post_hash, &pre_hash) {
            ImplicationResult::Unknown => {}
            other => {
                panic!("lying twin must not be in pool; Tier 0c must be Unknown, got {other:?}")
            }
        }
    }

    /// If we violated D2 and sealed without discharge, Tier 0c would false-green.
    /// This instrument proves the feed would be decorative/dangerous — and
    /// documents why production only mints after Discharged.
    #[test]
    fn force_seal_lying_twin_would_false_green_tier0c_hence_prove_then_feed() {
        let post = forall_ge("x", 0);
        let pre = forall_ge("x", 5);
        let post_hash = formula_hash(&post);
        let pre_hash = formula_hash(&pre);

        // Counterfactual: seal WITHOUT discharge (FORBIDDEN on production path).
        let (cid, envelope) =
            mint_proven_implication_memento(&post_hash, &pre_hash, "teeth-lying-force", 0)
                .expect("mint machinery");
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(cid, envelope);

        // Tier 0c would wrongly ProvenDirect — this is the false green D2 prevents.
        assert!(
            matches!(
                pool.can_implies(&post_hash, &pre_hash),
                ImplicationResult::ProvenDirect { .. }
            ),
            "force-seal of lying twin false-greens Tier 0c — prove-then-feed is mandatory"
        );
    }

    /// Mint is pure under fixed seed: same hashes → same CID (reuse by content).
    #[test]
    fn prove_then_feed_mint_is_deterministic_for_same_edge() {
        let post_hash = formula_hash(&forall_ge("x", 5));
        let pre_hash = formula_hash(&forall_ge("x", 0));
        let a = mint_proven_implication_memento(&post_hash, &pre_hash, "p", 0).unwrap();
        let b = mint_proven_implication_memento(&post_hash, &pre_hash, "p", 0).unwrap();
        assert_eq!(a.0, b.0, "same discharged edge must mint identical CID");
        assert_eq!(
            a.1, b.1,
            "same discharged edge must mint identical envelope bytes"
        );
    }

    /// queue_proven_implication + post-fanout insert path (production insert shape).
    #[test]
    fn queue_then_insert_feeds_pool_for_tier0c() {
        let post_hash = formula_hash(&forall_ge("r", 3));
        let pre_hash = formula_hash(&forall_ge("r", 1));
        let sink = Mutex::new(Vec::new());
        queue_proven_implication(&sink, &post_hash, &pre_hash, "queue-test", 1);
        let minted = sink.into_inner().unwrap();
        assert_eq!(minted.len(), 1, "one proven edge → one memento queued");

        let mut pool = MementoPool::default();
        for (cid, envelope) in minted {
            let member = AnchoredMember::new(cid, envelope)
                .unwrap_or_else(|e| panic!("anchoring proven implication: {e}"));
            pool.insert(member);
        }
        assert!(
            matches!(
                pool.can_implies(&post_hash, &pre_hash),
                ImplicationResult::ProvenDirect { .. }
            ),
            "queued+inserted proven implication must Tier 0c hit"
        );
    }
}
