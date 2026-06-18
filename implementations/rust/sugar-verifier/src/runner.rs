// SPDX-License-Identifier: Apache-2.0
//
// Verifier runner. Composes the seven stages and fans out per
// callsite via rayon. Stage 6 (solve) is now driven by the
// `solvers::run_plan` multi-solver layer (see
// `protocol/specs/2026-04-30-multi-solver-protocol.md`); the
// legacy single-Z3 path is preserved when no `.sugar/config.toml`
// is found.
//
// Stage 4 handshake is unchanged: Tier 1 (publisher-post hash ==
// consumer-pre hash, zero solver work) -> Tier 2 (signed implication
// memento in `cache_dir`) -> Tier 3 (the configured solver plan). On
// Tier 3 unsat we mint+cache a fresh implication memento PER SOLVER
// so the lattice records each independent witness.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use crate::formula_rewrite;

use rayon::prelude::*;
use serde_json::json;
use serde_json::Value as Json;
use tracing::{debug, info, warn};

use crate::body_discharge::callee_post_guard_fact;
use crate::handshake::{
    formula_hash, implication_property_hash, locate_producer_post, try_tier1, try_tier2,
};
use crate::solvers::{
    plan::SolverInvocation, registry, run_plan, SolverHandle, SolverPlan, SolversConfig,
};
use crate::types::{memento_body, CallSite, MementoPool, ObligationVerdict, Report};
use crate::{
    body_discharge, call_edge_loader, enumerate_callsites, instantiate,
    load_all_proofs::{self, ProofBytes},
    report as report_stage, resolve_target, smt_emitter,
};

pub const VERIFIER_STAGE_VOCABULARY: &[&str] = &[
    "load_all_proofs",
    "enumerate_callsites",
    "resolve_target",
    "instantiate",
    "smt_emit",
    "solve_obligation",
    "report",
];

const RUN_SIGNER_SEED: [u8; 32] = [0x72; 32];

#[derive(Debug, Clone)]
pub struct ProofRunArtifact {
    pub report: Report,
    pub stats: TierStats,
    pub memento: sugar_ir_types::ProofRunMemento,
    pub stage_receipts: Vec<sugar_ir_types::StageReceipt>,
    pub bundle_cid: String,
    pub bundle_path: PathBuf,
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
    /// Legacy: path to z3 binary. Used as a fallback when no
    /// `.sugar/config.toml` `[solvers]` table is found. Existing
    /// examples and tests pass this directly.
    pub z3_path: String,
    /// Per-project implication-memento cache directory.
    pub cache_dir: Option<PathBuf>,
    /// Ed25519 seed used to sign minted implication mementos.
    pub mint_seed: Option<[u8; 32]>,
    /// Producer id stamped into minted implication mementos.
    pub mint_producer_id: Option<String>,
    /// Optional pre-loaded SolversConfig. If set, bypasses
    /// `.sugar/config.toml` discovery (used by tests and the
    /// multi-solver demo).
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
    registry: HashMap<String, SolverHandle>,
}

impl Runner {
    pub fn new(cfg: RunnerConfig) -> Self {
        // Resolve solver config. Precedence:
        //   1. cfg.solvers_config (test/demo override)
        //   2. .sugar/config.toml under project_root
        //   3. fallback: single Z3 at cfg.z3_path
        let (plan, registry) = build_plan_and_registry(&cfg);
        Self {
            cfg,
            plan,
            registry,
        }
    }

    pub fn run(&self) -> Report {
        let (report, _stats) = self.run_with_tiers();
        report
    }

    pub fn run_with_proof_run(&self) -> Result<ProofRunArtifact, ProofRunArtifactError> {
        let input_artifact_cids = discover_input_artifact_cids(&self.cfg);
        let proof_envelope_cid = input_artifact_cids
            .iter()
            .next()
            .cloned()
            .unwrap_or_else(|| placeholder_cid("empty-proof-inputs"));
        let link_bundle_cid =
            discover_named_artifact_cid(&self.cfg.project_root, "link-bundle.json")
                .unwrap_or_else(|| placeholder_cid("absent-link-bundle"));
        let plugin_registry_cid =
            discover_named_artifact_cid(&self.cfg.project_root, "plugin-registry.json")
                .unwrap_or_else(|| placeholder_cid("absent-plugin-registry"));

        let mut stages = Vec::new();
        let mut report = Report::default();

        let load_stage = StageCapture::start(
            "load_all_proofs",
            input_artifact_cids.iter().cloned().collect(),
        );
        let mut pool = load_all_proofs::run(&self.cfg.project_root);
        for extra in &self.cfg.extra_projects {
            let extra_pool = load_all_proofs::run(extra);
            pool.merge(extra_pool);
        }
        load_all_proofs::load_files_into_pool(&self.cfg.extra_proof_files, &mut pool);
        load_all_proofs::load_proof_bytes_into_pool(&self.cfg.extra_proofs, &mut pool);
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
        let call_edges = call_edge_loader::load_call_edge_files(&self.cfg.project_root);
        let obligations = call_edge_loader::process_call_edges(&call_edges, &pool);
        for (source_cid, target_cid, locus) in &obligations {
            let file = locus
                .as_ref()
                .and_then(|l| l.get("file"))
                .and_then(|f| f.as_str())
                .unwrap_or("<unknown>");
            report.call_edges.push(crate::types::ResolvedCallEdge {
                source_contract_cid: source_cid.clone(),
                target_contract_cid: target_cid.clone(),
                file: file.to_string(),
            });
        }
        let callsites = enumerate_callsites::run(&pool);
        let callsite_property_cids: Vec<String> =
            callsites.iter().map(|cs| cs.property_cid.clone()).collect();
        stages.push(enumerate_stage.finish(
            sorted(callsite_property_cids),
            Vec::new(),
            vec![json!({"kind": "stage-summary", "callsites": callsites.len(), "call_edges": obligations.len()})],
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
        let invs_sink: Mutex<Vec<SolverInvocation>> = Mutex::new(vec![]);
        let minted_sink = Mutex::new(Vec::new());

        let fanout_input = sorted(
            callsites
                .iter()
                .map(|cs| cs.property_cid.clone())
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
            pool.insert(cid.clone(), envelope.clone());
        }
        let output_artifact_cids = sorted(minted.iter().map(|(cid, _)| cid.clone()).collect());

        for stage_name in [
            "resolve_target",
            "instantiate",
            "smt_emit",
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
            if callsite_body_refusal_is_owned_by_consistency(&cs, verdict, &reason, &pool) {
                debug!(
                    bridge = %cs.bridge_ir_name,
                    property = %cs.property_name,
                    "verifier/linker: consistency owns body-bearing assertion callsite row"
                );
                continue;
            }
            if verdict != ObligationVerdict::Discharged {
                violations += 1;
            }
            report_stage::add_callsite_with_discharge(
                &cs,
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
        let self_post_results = verify_contract_self_posts(&pool, &self.plan, &self.registry);
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
        let consistency_results =
            crate::consistency::verify_consistency(&pool, &self.plan, &self.registry);
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
                cr.verification.clone(),
                &mut report,
            );
        }

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
        let (bundle_cid, bundle_path) =
            write_proof_run_bundle(&self.cfg.project_root, &memento, &stages)?;

        Ok(ProofRunArtifact {
            report,
            stats,
            memento,
            stage_receipts: stages,
            bundle_cid,
            bundle_path,
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

        // Load and process call edges
        let call_edges = call_edge_loader::load_call_edge_files(&self.cfg.project_root);
        let obligations = call_edge_loader::process_call_edges(&call_edges, &pool);

        // Report resolved call-edge obligations using the single
        // `obligations` computation above (do not call process_call_edges
        // a second time: it's an O(callgraph) walk over all loaded
        // mementos).
        for (source_cid, target_cid, locus) in &obligations {
            let file = locus
                .as_ref()
                .and_then(|l| l.get("file"))
                .and_then(|f| f.as_str())
                .unwrap_or("<unknown>");
            report.call_edges.push(crate::types::ResolvedCallEdge {
                source_contract_cid: source_cid.clone(),
                target_contract_cid: target_cid.clone(),
                file: file.to_string(),
            });
        }

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
        let invs_sink: Mutex<Vec<SolverInvocation>> = Mutex::new(vec![]);

        let cfg = &self.cfg;
        let plan = &self.plan;
        let registry = &self.registry;

        let minted_sink = Mutex::new(Vec::new());
        let per_results: Vec<CallsiteResult> = callsites
            .par_iter()
            .map(|cs| {
                work_one(
                    cs,
                    &pool,
                    plan,
                    registry,
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
                pool.insert(cid.clone(), envelope.clone());
            }
        }

        // Aggregate report rows.
        let mut violations = 0usize;
        for (cs, verdict, reason, method, body_tier) in per_results {
            if callsite_body_refusal_is_owned_by_consistency(&cs, verdict, &reason, &pool) {
                debug!(
                    bridge = %cs.bridge_ir_name,
                    property = %cs.property_name,
                    "verifier/linker: consistency owns body-bearing assertion callsite row"
                );
                continue;
            }
            if verdict != ObligationVerdict::Discharged {
                violations += 1;
            }
            report_stage::add_callsite_with_discharge(
                &cs,
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
        let self_post_results = verify_contract_self_posts(&pool, plan, registry);
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
        let consistency_results = crate::consistency::verify_consistency(&pool, plan, registry);
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
                cr.verification.clone(),
                &mut report,
            );
        }

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
    Ok(memento)
}

fn write_proof_run_bundle(
    project_root: &Path,
    memento: &sugar_ir_types::ProofRunMemento,
    stages: &[sugar_ir_types::StageReceipt],
) -> Result<(String, PathBuf), ProofRunArtifactError> {
    use sugar_proof_envelope::{build_proof_envelope, ProofEnvelopeInput};

    let mut members = BTreeMap::new();
    members.insert(
        memento.header.cid.clone(),
        memento
            .to_jcs_string()
            .map_err(|e| ProofRunArtifactError::Build(e.to_string()))?
            .into_bytes(),
    );
    for stage in stages {
        members.insert(
            stage.header.cid.clone(),
            stage
                .to_jcs_string()
                .map_err(|e| ProofRunArtifactError::Build(e.to_string()))?
                .into_bytes(),
        );
    }

    let signer = sugar_proof_envelope::ed25519_pubkey_string(&RUN_SIGNER_SEED);
    let signer_cid = sugar_canonicalizer::blake3_512_of(signer.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@sugar/verifier-run".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        members,
        signer_cid,
        signer_seed: RUN_SIGNER_SEED,
        declared_at: iso_now(),
    });
    let out_dir = project_root.join(".sugar").join("runs");
    std::fs::create_dir_all(&out_dir)?;
    let hex = built.cid.trim_start_matches("blake3-512:");
    let path = out_dir.join(format!("{hex}.proof"));
    std::fs::write(&path, built.bytes)?;
    Ok((built.cid, path))
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

fn discover_input_artifact_cids(cfg: &RunnerConfig) -> BTreeSet<String> {
    let mut cids = BTreeSet::new();
    collect_proof_file_cids(&cfg.project_root, &mut cids);
    for extra in &cfg.extra_projects {
        collect_proof_file_cids(extra, &mut cids);
    }
    for proof_file in &cfg.extra_proof_files {
        collect_one_proof_file_cid(proof_file, &mut cids);
    }
    for proof in &cfg.extra_proofs {
        cids.insert(sugar_canonicalizer::blake3_512_of(&proof.bytes));
    }
    cids
}

fn collect_proof_file_cids(root: &Path, out: &mut BTreeSet<String>) {
    if !root.exists() {
        return;
    }
    for entry in walkdir::WalkDir::new(root)
        .follow_links(true)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }
        if entry.path().extension().and_then(|s| s.to_str()) != Some("proof") {
            continue;
        }
        if let Ok(bytes) = std::fs::read(entry.path()) {
            out.insert(sugar_canonicalizer::blake3_512_of(&bytes));
        }
    }
}

fn collect_one_proof_file_cid(path: &Path, out: &mut BTreeSet<String>) {
    if path.extension().and_then(|s| s.to_str()) != Some("proof") {
        return;
    }
    if let Ok(bytes) = std::fs::read(path) {
        out.insert(sugar_canonicalizer::blake3_512_of(&bytes));
    }
}

fn discover_named_artifact_cid(project_root: &Path, name: &str) -> Option<String> {
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

fn sorted_keys(map: &BTreeMap<String, Json>) -> Vec<String> {
    map.keys().cloned().collect()
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

fn build_plan_and_registry(cfg: &RunnerConfig) -> (SolverPlan, HashMap<String, SolverHandle>) {
    if let Some(sc) = &cfg.solvers_config {
        return (SolverPlan::from_config(sc), registry::build(sc));
    }
    if let Ok(Some(sc)) = SolversConfig::load(&cfg.project_root) {
        return (SolverPlan::from_config(&sc), registry::build(&sc));
    }
    // Fallback: legacy single-Z3 plan.
    let z3 = if cfg.z3_path.is_empty() {
        "z3".to_string()
    } else {
        cfg.z3_path.clone()
    };
    (
        SolverPlan::Single("z3".into()),
        registry::build_default_z3(&z3),
    )
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

fn callsite_body_refusal_is_owned_by_consistency(
    cs: &CallSite,
    verdict: ObligationVerdict,
    reason: &str,
    pool: &MementoPool,
) -> bool {
    if verdict != ObligationVerdict::Undecidable
        || !reason.starts_with("body-discharge: refuse: target")
    {
        return false;
    }
    let Some(body) = pool.mementos.get(&cs.property_cid).and_then(memento_body) else {
        return false;
    };
    crate::consistency::linked_post_instance_count(pool, body) > 0
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
    registry: &HashMap<String, SolverHandle>,
) -> Vec<SelfPostResult> {
    use crate::types::{memento_body, memento_kind};

    let contracts: Vec<(&String, &Json)> = pool
        .mementos
        .iter()
        .filter(|(_, env)| memento_kind(env) == Some("contract"))
        .collect();

    contracts
        .par_iter()
        .filter_map(|(cid, env)| {
            let body = memento_body(env)?;
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

            let smt = match smt_emitter::emit(&obligation_json) {
                Ok(s) => s,
                Err(e) => {
                    return Some(SelfPostResult {
                        contract_cid: (*cid).clone(),
                        verdict: ObligationVerdict::Undecidable,
                        reason: format!("self-post smt-emit: {e}"),
                        method: None,
                    });
                }
            };
            let (verdict, reason, _invs) = run_plan(plan, registry, &smt, Some(&obligation_json));
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
                contract_cid: (*cid).clone(),
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
    registry: &HashMap<String, SolverHandle>,
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
    minted_sink: &Mutex<Vec<(String, Json)>>,
) -> CallsiteResult {
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
            target_cid = %cs.bridge_target_cid,
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
                let smt = match smt_emitter::emit(&reduced) {
                    Ok(s) => s,
                    Err(e) => {
                        n_residue.fetch_add(1, Ordering::Relaxed);
                        return (
                            cs.clone(),
                            ObligationVerdict::Undecidable,
                            format!("smt-emit: {e}"),
                            None,
                            body_tier,
                        );
                    }
                };
                let (verdict, mut reason, invs) = run_plan(plan, registry, &smt, Some(&reduced));
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
        // is legitimate ONLY for a genuinely non-body-bearing target. A
        // target carrying `formals` is a body-derived op-contract: its `post`
        // describes a body whose obligation the runner does NOT reduce here,
        // so vacuous-passing it would be a false green. Refuse instead
        // (Undecidable): not discharged, no witness.
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
        locate_producer_post(&cs.arg_term, &pool.mementos, &pool.bridges_by_symbol)
    };

    // Tier 0: Memento IS verification. Look up the formula CID in the pool.
    // The hash IS the boundary: we verify by hash lookup, not by solving.
    if let Some(pre_formula) = consumer_pre {
        if let Some(memento) = pool.verify(pre_formula) {
            n_hash.fetch_add(1, Ordering::Relaxed);
            let memento_cid = memento
                .get("cid")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown");
            return (
                cs.clone(),
                ObligationVerdict::Discharged,
                format!(
                    "tier0: memento-is-verification (cid={})",
                    short(memento_cid)
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
        if let Some(cache_dir) = &cfg.cache_dir {
            if let Some(impl_cid) = try_tier2(cache_dir, post_hash, pre_hash) {
                n_cache.fetch_add(1, Ordering::Relaxed);
                return (
                    cs.clone(),
                    ObligationVerdict::Discharged,
                    format!(
                        "tier2: cache hit (implication memento {})",
                        short(&impl_cid)
                    ),
                    Some("hash-tier".to_string()),
                    None,
                );
            }
        }
    }

    // Tier 3: build SMT-LIB and run the configured plan.
    let smt: String;
    let formula_for_dispatch: Option<Json>;
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
                // Use the reduced formula for SMT emission
                smt = match smt_emitter::emit(&new_formula) {
                    Ok(s) => s,
                    Err(e) => {
                        n_residue.fetch_add(1, Ordering::Relaxed);
                        return (
                            cs.clone(),
                            ObligationVerdict::Undecidable,
                            format!("smt-emit: {e}"),
                            None,
                            None,
                        );
                    }
                };
                formula_for_dispatch = Some(new_formula);
                // Continue to solver with reduced formula
            }
            formula_rewrite::TacticResult::NoChange => {
                smt = match smt_emitter::emit(&implication) {
                    Ok(s) => s,
                    Err(e) => {
                        n_residue.fetch_add(1, Ordering::Relaxed);
                        return (
                            cs.clone(),
                            ObligationVerdict::Undecidable,
                            format!("smt-emit: {e}"),
                            None,
                            None,
                        );
                    }
                };
                formula_for_dispatch = Some(implication);
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
                target_cid = %cs.bridge_target_cid,
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
                target_cid = %cs.bridge_target_cid,
                guard_count = cs.guard_facts.len(),
                antecedent = %antecedent,
                obligation = %guarded,
                "work_one: GUARDED panic site -> `(and guard_facts) => pre` obligation \
                 (the guard must establish the pre; expected discharged)"
            );
            guarded
        };
        smt = match smt_emitter::emit(&guarded_formula) {
            Ok(s) => s,
            Err(e) => {
                n_residue.fetch_add(1, Ordering::Relaxed);
                return (
                    cs.clone(),
                    ObligationVerdict::Undecidable,
                    format!("smt-emit: {e}"),
                    None,
                    None,
                );
            }
        };
        formula_for_dispatch = Some(guarded_formula);
    }

    debug!(
        bridge = %cs.bridge_ir_name,
        "work_one: invoking solver plan (tier 3)"
    );
    let (verdict, reason, invs) = run_plan(plan, registry, &smt, formula_for_dispatch.as_ref());

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

    // Mint per-solver mementos for every solver that returned unsat
    // when the implication form was used.
    if used_implication_form {
        if let (Some(post_hash), Some(pre_hash), Some(cache_dir), Some(seed), Some(producer)) = (
            producer_post.as_ref().map(|(_, h)| h.clone()),
            consumer_pre_hash.clone(),
            cfg.cache_dir.as_ref(),
            cfg.mint_seed.as_ref(),
            cfg.mint_producer_id.as_ref(),
        ) {
            for inv in &invs {
                if inv.result.verdict == ObligationVerdict::Discharged {
                    let prover_tag =
                        format!("{}@{}", inv.result.solver_name, inv.result.solver_version);
                    match mint_and_cache(
                        cache_dir,
                        seed,
                        producer,
                        &post_hash,
                        &pre_hash,
                        producer_post.as_ref().map(|(p, _)| p.clone()),
                        consumer_pre.cloned(),
                        &smt,
                        &prover_tag,
                        inv.result.wall_clock.as_millis() as i64,
                    ) {
                        Ok((cid, envelope)) => {
                            // Queue for insertion into pool after parallel
                            // work completes (pool is not Sync).
                            if let Ok(mut g) = minted_sink.lock() {
                                g.push((cid, envelope));
                            }
                        }
                        Err(e) => {
                            warn!(bridge = %cs.bridge_ir_name, error = %e, "mint_and_cache failed");
                        }
                    }
                }
            }
        }
    }

    if verdict == ObligationVerdict::Discharged && used_implication_form {
        n_solved.fetch_add(1, Ordering::Relaxed);
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

fn callsite_actual_terms(cs: &CallSite) -> Vec<Json> {
    if !cs.arg_terms.is_empty() {
        return cs.arg_terms.clone();
    }
    cs.arg_term.iter().cloned().collect()
}

fn short(s: &str) -> String {
    let cleaned = s.trim_start_matches("blake3-512:");
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

/// Mint an implication memento and cache it to disk.
/// Returns (cid, envelope_json) so the caller can insert into the pool.
#[allow(clippy::too_many_arguments)]
fn mint_and_cache(
    cache_dir: &std::path::Path,
    seed: &[u8; 32],
    producer_id: &str,
    post_hash: &str,
    pre_hash: &str,
    post_formula: Option<Json>,
    pre_formula: Option<Json>,
    smt_lib_input: &str,
    prover_tag: &str,
    prover_run_ms: i64,
) -> Result<(String, Json), Box<dyn std::error::Error>> {
    use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
    use sugar_proof_envelope::{
        build_proof_envelope, ed25519_pubkey_string, ed25519_sign_string, ProofEnvelopeInput,
    };

    std::fs::create_dir_all(cache_dir)?;
    let now = "2026-04-30T00:00:00.000Z";
    let pubkey = ed25519_pubkey_string(seed);
    let _ = (post_formula, pre_formula);

    // Layered shape (v1.2). The verifier's own implication-extension
    // mint emits the same `{envelope, header, metadata}` shape that
    // `sugar-claim-envelope::mint_implication` produces; mirroring
    // it inline keeps the runner free of an extra runtime dep on the
    // claim-envelope crate.
    let bh = Value::object([
        ("antecedentHash", Value::string(post_hash.to_string())),
        ("consequentHash", Value::string(pre_hash.to_string())),
    ]);
    let binding_hash = blake3_512_of(encode_jcs(&bh).as_bytes());
    let property_hash = implication_property_hash(post_hash, pre_hash);

    let mut input_cids = vec!["blake3-512:0000".to_string(), "blake3-512:0000".to_string()];
    input_cids.sort();
    let cids_arr: Vec<std::sync::Arc<Value>> = input_cids.into_iter().map(Value::string).collect();

    // Header: schemaVersion / kind / cid + kind-specific REQUIRED.
    // The header CID hashes the substrate-load-bearing claim content
    // (antecedent/consequent hashes + slots).
    let header_content = Value::object([
        ("antecedentHash", Value::string(post_hash.to_string())),
        ("consequentHash", Value::string(pre_hash.to_string())),
        (
            "antecedentCid",
            Value::string("blake3-512:0000".to_string()),
        ),
        (
            "consequentCid",
            Value::string("blake3-512:0000".to_string()),
        ),
        ("antecedentSlot", Value::string("post".to_string())),
        ("consequentSlot", Value::string("pre".to_string())),
    ]);
    let header_cid = blake3_512_of(encode_jcs(&header_content).as_bytes());

    let header = Value::object([
        ("schemaVersion", Value::string("2")),
        ("kind", Value::string("implication")),
        ("cid", Value::string(header_cid)),
        ("antecedentHash", Value::string(post_hash.to_string())),
        ("consequentHash", Value::string(pre_hash.to_string())),
        (
            "antecedentCid",
            Value::string("blake3-512:0000".to_string()),
        ),
        (
            "consequentCid",
            Value::string("blake3-512:0000".to_string()),
        ),
        ("antecedentSlot", Value::string("post".to_string())),
        ("consequentSlot", Value::string("pre".to_string())),
        ("verdict", Value::string("holds")),
        ("bindingHash", Value::string(binding_hash)),
        ("propertyHash", Value::string(property_hash.clone())),
        ("inputCids", Value::array(cids_arr)),
    ]);

    let mut metadata_kvs: Vec<(String, std::sync::Arc<Value>)> = vec![
        ("producedBy".into(), Value::string(producer_id.to_string())),
        ("producedAt".into(), Value::string(now.to_string())),
        ("prover".into(), Value::string(prover_tag.to_string())),
        (
            "proverRunMs".into(),
            Value::integer(i128::from(prover_run_ms)),
        ),
        ("producerPubkey".into(), Value::string(pubkey.clone())),
    ];
    if !smt_lib_input.is_empty() {
        metadata_kvs.push((
            "smtLibInput".into(),
            Value::string(smt_lib_input.to_string()),
        ));
    }
    metadata_kvs.push(("proofWitness".into(), Value::string("(unsat)".to_string())));
    let metadata = std::sync::Arc::new(Value::Object(metadata_kvs));

    // Sign over JCS({header, metadata}) per spec §2 R2.
    let signing_msg = Value::object([("header", header.clone()), ("metadata", metadata.clone())]);
    let signing_bytes = encode_jcs(&signing_msg);
    let producer_sig = ed25519_sign_string(seed, signing_bytes.as_bytes());

    // Envelope CID is blake3_512(JCS(envelope-with-signature)).
    let envelope = Value::object([
        ("signer", Value::string(pubkey.clone())),
        ("declaredAt", Value::string(now.to_string())),
        ("signature", Value::string(producer_sig)),
    ]);
    let envelope_jcs = encode_jcs(&envelope);
    let cid = blake3_512_of(envelope_jcs.as_bytes());

    let memento = Value::object([
        ("envelope", envelope),
        ("header", header),
        ("metadata", metadata),
    ]);
    let final_canonical = encode_jcs(&memento).into_bytes();

    let mut members: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    members.insert(cid.clone(), final_canonical.clone());
    let signer_cid = blake3_512_of(pubkey.as_bytes());
    // Encode prover_tag into the filename to disambiguate per-solver
    // mementos for the same (antecedent, consequent) pair.
    let safe_prover: String = prover_tag
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect();
    let proof_input = ProofEnvelopeInput {
        name: format!(
            "@cache/implication-{}-{}",
            short(&property_hash),
            safe_prover
        ),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        members,
        signer_cid,
        signer_seed: *seed,
        declared_at: now.into(),
    };
    let built = build_proof_envelope(&proof_input);

    let fname = format!("{}-{}.proof", property_hash, safe_prover);
    let path = cache_dir.join(fname);
    std::fs::write(path, built.bytes)?;

    // Convert the canonicalizer Value back to serde_json for pool insertion
    let envelope_json: Json = serde_json::from_slice(&final_canonical)?;

    Ok((cid, envelope_json))
}

#[cfg(test)]
mod consistency_owned_callsite_tests {
    use super::*;
    use serde_json::json;

    fn string_const(s: &str) -> Json {
        json!({"kind":"const","value":s,"sort":{"kind":"primitive","name":"String"}})
    }

    fn eqf(a: Json, b: Json) -> Json {
        json!({"kind":"atomic","name":"=","args":[a,b]})
    }

    fn linked_pool_and_callsite() -> (MementoPool, CallSite) {
        let source_symbol = "call:enc";
        let vendor_cid = "blake3-512:vendor-enc";
        let assertion_cid = "blake3-512:consumer-assertion";
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
                    "targetContractCid": vendor_cid
                }
            }
        });
        let mut pool = MementoPool::default();
        pool.insert(assertion_cid.to_string(), assertion);
        pool.mementos.insert(vendor_cid.to_string(), vendor);
        pool.bridges_by_symbol
            .insert(source_symbol.to_string(), bridge);
        let cs = CallSite {
            bridge_ir_name: source_symbol.to_string(),
            property_name: "src/lib.rs::tests::fresh_vendor_fol_good::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion".to_string(),
            property_cid: assertion_cid.to_string(),
            ..CallSite::default()
        };
        (pool, cs)
    }

    #[test]
    fn linked_assertion_body_refusal_is_owned_by_consistency() {
        let (pool, cs) = linked_pool_and_callsite();
        assert!(callsite_body_refusal_is_owned_by_consistency(
            &cs,
            ObligationVerdict::Undecidable,
            "body-discharge: refuse: target `call:enc` is body-bearing",
            &pool
        ));
    }

    #[test]
    fn unlinked_assertion_body_refusal_stays_visible() {
        let (mut pool, cs) = linked_pool_and_callsite();
        pool.bridges_by_symbol.clear();
        assert!(!callsite_body_refusal_is_owned_by_consistency(
            &cs,
            ObligationVerdict::Undecidable,
            "body-discharge: refuse: target `call:enc` is body-bearing",
            &pool
        ));
    }
}
