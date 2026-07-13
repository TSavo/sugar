// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `ProofGraph::solve` -- SEAM 5 of the compiler-shape plan
// (~/.claude/plans/sugar-compiler-liftshift.md). An extension trait
// (`Orchestrate`), because the orphan rule forbids `sugar-proof-envelope`
// (the leaf, below `sugar-linker`/`sugar-verifier`) from implementing a
// method that calls upward into them; `sugar-compiler` sits above both
// towers and may legally down-call into each.
//
// FINDING recorded here rather than left implicit (per doctrine: report the
// disposition, don't narrate a shift that didn't happen): the plan's stated
// shift source, `sugar-linkerd::run_link`, no longer exists in this tree --
// `sugar-linkerd` itself was retired (see `sugar-cli/tests/polyglot_smoke.rs`,
// "daemon-3-delete cut removed sugar-linkerd itself"). More load-bearing:
// `sugar_linker::{LinkerContract, LinkerCallEdge, LinkerInputs, bind}` is
// NOT wired to anything in the production `MementoPool`/`ProofGraph`
// pipeline today -- grep confirms zero call sites outside `sugar-linker`'s
// own crate and its `polyglot_smoke.rs` cross-kit fixture. Production
// consistency solving (`verify_consistency_from_indexes`) resolves cross-kit
// calls through an ENTIRELY different mechanism: bridges the KIT itself
// pins at lift time (`bridges_by_symbol`/`bridges_by_callsite` in
// `sugar_verifier::types::MementoPool`), where an unresolved call is
// represented by the ABSENCE of a bridge, not a typed `LinkerCallEdge`
// carrying an `Unbound` state. There is today no derivation from
// `MementoPool`'s bridge indexes into `sugar_linker::LinkerInputs`, and
// building one honestly (recognizing which pool contents constitute
// "pending edges needing resolution" in the bridge model) is a real design
// question, not a lift-and-shift -- fabricating a shim that always returns
// an empty `LinkerInputs` would make gate A(a) pass on a fixture while
// never firing on real production data, exactly the "frontier-masked
// green" the plan's own gate language warns against.
//
// Resolution taken for this seam: `solve` takes `LinkerInputs` as an
// explicit parameter (beat 1's actual program to bind) rather than silently
// deriving one from `self`. This keeps `sugar_linker::bind`'s real two-arm
// behavior (`UnresolvedSymbol`/`SignatureMismatch` short-circuit `Verdicts`
// entirely) wired in front of discharge, verified by the discrimination
// tests below, without inventing a fake pool-to-`LinkerInputs` bridge.
//
// FOLLOW-UP LANDED (sugar#3857): the pool-derivation question above is no
// longer open. `crate::linker_inputs::derive_linker_inputs` derives
// `LinkerInputs` from a `MementoPool`'s own contract union and its
// `enumerate_callsites` output -- the pool's bridge indexes
// (`bridges_by_symbol`/`bridges_by_callsite`) ARE the "kit emitting
// cross-kit `LinkerCallEdge`s" mechanism this comment was waiting on; they
// were just never read into the linker's vocabulary before. See that
// module's doc comment for the absence-becomes-typed-edge mechanism.
// `solve_deriving_links` below is the auto variant that self-loads a pool
// and derives from THAT SAME pool (one self-load, not two); `solve` (the
// explicit-`LinkerInputs` form) is kept unchanged for callers that already
// have richer edges than the pool alone can supply (e.g. a daemon's
// in-memory kit-stream union, per this module's original doc above).

use std::collections::HashMap;
use std::path::Path;

use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_linker::{link, LinkerError, LinkerErrorKind, LinkerInputs};
use sugar_proof_envelope::{build_proof_envelope, ProofEnvelopeInput, ProofGraph};
use sugar_proof_envelope::{MementoPool, Speaker};
use sugar_verifier::consistency::verify_consistency;
use sugar_verifier::load_all_proofs::{load_proof_bytes_into_pool, ProofBytes};
use sugar_verifier::runner::{load_pool, ProofRunArtifact, ProofRunArtifactError, Runner};
use sugar_verifier::{RunnerConfig, SolverHandle, SolverPlan, SolverSeat};

use crate::feed_from_tree::{self, FeedError};
use crate::kit::Kit;
use crate::linker_inputs::derive_linker_inputs;
use crate::outcome::{Outcome, OutcomeClass};
use crate::resolve::{TestimonyError, TestimonyOutcome};

/// Throwaway seed for the internal graph->pool self-load round trip `solve`
/// performs to reach beat 2. This is never a real signature over anything
/// a caller inspects (mirrors `seal_proof_graph`'s own
/// "seal-time-manifest-self-load" round trip, in `lib.rs`); `solve` discards
/// the sealed bytes the instant they're decoded back into a `MementoPool`.
const SOLVE_SELF_LOAD_SEED: [u8; 32] = [0x53; 32]; // 'S' for solve

/// Orchestration verbs for `ProofGraph`, homed in `sugar-compiler` because
/// they down-call both `sugar-linker` (beat 1) and `sugar-verifier` (beat 2)
/// -- arrows the leaf crate is forbidden from making.
pub trait Orchestrate {
    /// Beat 1 (link): bind every call edge in `links` against its
    /// contracts. Any `UnresolvedSymbol`/`SignatureMismatch` short-circuits
    /// to `Outcome::LinkError` -- beat 2 never runs. Beat 2 (discharge):
    /// `verify_consistency` over `self`'s contents, wrapped as
    /// `Outcome::Verdicts`.
    fn solve(
        &self,
        links: LinkerInputs,
        plan: &SolverPlan,
        registry: &HashMap<SolverSeat, SolverHandle>,
        compilers: &CompilerRegistry,
        project_root: &Path,
    ) -> Result<Outcome, SolveError>;

    /// Auto variant of [`solve`](Orchestrate::solve): self-loads `self` into
    /// a `MementoPool` exactly once, derives `LinkerInputs` from THAT pool
    /// (`crate::linker_inputs::derive_linker_inputs` -- real bridge data,
    /// sugar#3857), then runs the same two beats over the same pool. Use
    /// this when the caller has no richer edge source than the graph's own
    /// contents; use [`solve`](Orchestrate::solve) directly when the caller
    /// (e.g. a daemon holding a live per-kit stream union) already has
    /// `LinkerInputs` beat 1 should bind instead.
    fn solve_deriving_links(
        &self,
        plan: &SolverPlan,
        registry: &HashMap<SolverSeat, SolverHandle>,
        compilers: &CompilerRegistry,
        project_root: &Path,
    ) -> Result<Outcome, SolveError>;
}

impl Orchestrate for ProofGraph {
    fn solve(
        &self,
        links: LinkerInputs,
        plan: &SolverPlan,
        registry: &HashMap<SolverSeat, SolverHandle>,
        compilers: &CompilerRegistry,
        project_root: &Path,
    ) -> Result<Outcome, SolveError> {
        // Beat 1 -- LINK, over the caller-supplied program.
        if let Some(outcome) = link_beat(links) {
            return Ok(outcome);
        }

        // Beat 2 -- DISCHARGE. `verify_consistency` takes a `MementoPool`,
        // not a `ProofGraph` (SEAM 2 finding: the two currencies did not
        // fully collapse -- pool provenance/attribution is a property of
        // the feed EVENT, not the signed content, so a design seam remains
        // open). Reach it the same way `sugar-compiler::seal_proof_graph`
        // already does: seal an internal, throwaway-signed copy and
        // self-load it into a fresh pool via the one loader every `.proof`
        // consumer uses.
        let pool = self_load_pool(self)?;
        let verdicts = verify_consistency(&pool, plan, registry, compilers, project_root);
        Ok(Outcome::Verdicts(verdicts))
    }

    fn solve_deriving_links(
        &self,
        plan: &SolverPlan,
        registry: &HashMap<SolverSeat, SolverHandle>,
        compilers: &CompilerRegistry,
        project_root: &Path,
    ) -> Result<Outcome, SolveError> {
        // ONE self-load. The pool derived here is both beat 1's program
        // source (`derive_linker_inputs`) and beat 2's discharge pool --
        // there is exactly one production truth about this graph's
        // contents, and both beats read it, rather than each independently
        // re-staging the graph.
        let pool = self_load_pool(self)?;
        let links = crate::linker_inputs::derive_linker_inputs(&pool)?;

        // Beat 1 -- LINK, over the pool-derived program.
        if let Some(outcome) = link_beat(links) {
            return Ok(outcome);
        }

        // Beat 2 -- DISCHARGE, over the SAME pool beat 1 was derived from.
        let verdicts = verify_consistency(&pool, plan, registry, compilers, project_root);
        Ok(Outcome::Verdicts(verdicts))
    }
}

/// A production solve, classified. Beat 1 (`link_errors`, derived from the
/// pool's real bridge data) ANNOTATES the run; beat 2 (`artifact`, the
/// untouched `ProofRunArtifact` from the real `Runner` pipeline) IS the run.
/// `outcome_class` partitions `artifact.report` onto today's exit-code law.
///
/// # Why beat 1 ANNOTATES and never blocks (do not relitigate)
///
/// `solve_project` runs the full `Runner` pipeline REGARDLESS of whether
/// `link_errors` is empty. It does NOT short-circuit the way
/// `Orchestrate::solve`/`solve_deriving_links` do. The reason is empirical:
/// `derive_linker_inputs` turns every unbridged callsite in the pool into an
/// `UnresolvedSymbol` link error (see `linker_inputs.rs`), and real
/// production pools routinely carry unbridged callsites (prior work measured
/// ~5 bridges against ~44k pool members). Short-circuiting on a non-empty
/// `link_errors` would therefore brick nearly every real `prove`/`verify`
/// run. So the link errors are carried ALONGSIDE the artifact as typed data,
/// a distinct dimension from the report's verdicts, and they do NOT affect
/// the exit code today.
///
/// Whether unresolved edges SHOULD one day tighten the exit code (closing the
/// silent-vacuous soundness gap #3857 names) is an exit-code-law question that
/// is deliberately OUT OF SCOPE here: this door keeps exit codes byte-identical
/// to the pre-`solve_project` faces. Evolving the law is T's call, not this
/// wrapper's.
#[derive(Debug, Clone)]
pub struct ProvenOutcome {
    /// Beat 1: unresolved / signature-mismatched cross-kit edges the pool's
    /// bridge data left unbound. ANNOTATION ONLY -- non-empty here does NOT
    /// suppress or alter `artifact`, and does NOT change the exit code today.
    pub link_errors: Vec<LinkerError>,
    /// Beat 1 could not even derive edges (e.g. a malformed contract body,
    /// #3869's strict decode). ANNOTATION ONLY, same law as `link_errors`:
    /// production discharge (beat 2) still runs -- a pool that proves today
    /// must not brick because its LINK VIEW is undecodable (gitar/Devin on
    /// #3891). The strict doors (`solve`/`solve_deriving_links`) keep their
    /// hard Err; this production wrapper annotates.
    pub link_derivation_error: Option<String>,
    /// Beat 2: the untouched rich artifact from the real `Runner` pipeline
    /// (witnesses, stages, report). Report bytes are identical to a direct
    /// `Runner::run_with_proof_run` over the same pool.
    pub artifact: ProofRunArtifact,
    /// The report-derived verdict class; `outcome_class.exit_code()`
    /// reproduces today's CLI exit code bit-for-bit.
    pub outcome_class: OutcomeClass,
}

impl ProvenOutcome {
    /// `true` iff beat 1 surfaced at least one unbound/mismatched edge. Pure
    /// annotation -- see the type doc: this never gates the pipeline.
    pub fn has_link_errors(&self) -> bool {
        !self.link_errors.is_empty()
    }
}

/// THE production solve door (sugar#3859). Runs the real
/// `Runner::run_with_proof_run` pipeline as beat 2 -- the one, unchanged
/// production discharge body -- and wraps it in a typed VIEW:
///
///   - beat 1 derives `LinkerInputs` from the SAME pool the run discharges
///     (`load_pool` once, threaded into both beats -- no second pool decode)
///     and binds it, carrying any unresolved/mismatched edges as
///     `link_errors`;
///   - beat 2 is the untouched `ProofRunArtifact` (report bytes byte-identical
///     to a direct `run_with_proof_run` over the same pool);
///   - `outcome_class` classifies `artifact.report` onto today's exit-code law.
///
/// Beat 1 ANNOTATES, it does not block: the run happens regardless of
/// `link_errors` (see `ProvenOutcome`'s doc for the empirical reason -- real
/// pools are mostly unbridged, so a short-circuit would brick real runs).
///
/// Disk-load face: builds the pool via [`load_pool`] then runs the **one**
/// discharge body. Solve is one path, zero project FS (#3809 series).
///
/// Callers that already hold a multi-speaker pool (e.g. [`prove_from_kit`])
/// use [`solve_project_with_pool`] — same body, preloaded pool, one path.
pub fn solve_project(
    cfg: RunnerConfig,
    compilers: CompilerRegistry,
) -> Result<ProvenOutcome, SolveError> {
    // ONE pool decode, shared by both beats. `load_pool` is the exact
    // construction `run_with_proof_run` uses inline, so deriving beat-1 links
    // from it and discharging beat 2 over it read the SAME production truth.
    let pool = load_pool(&cfg);
    discharge_with_pool(cfg, compilers, pool)
}

/// Production solve over a **preloaded** pool (sugar#3809 Task 8 / one-solve).
///
/// Same annotate-not-block link + `Runner::run_with_proof_run_with_pool`
/// discharge as [`solve_project`], without re-walking the project for
/// `.proof` files. Use this when the pool was assembled with speakers via
/// [`pool_from_graph_with_speaker`] and vendor `ProofBytes` merge.
///
/// ## One path — zero project FS
///
/// There is no separate `warm_solve` and no `pool_only_inputs` flag. The
/// caller already holds claim facts in `pool` (fold / prior load). Solve
/// never WalkDirs or opens project FS for claim inputs. Claim bytes +
/// solvers + signers + plan_artifact ride on `cfg` / `pool` / `compilers`.
///
/// Disk-load face remains [`solve_project`] (load then the same discharge).
///
/// ## Out of scope (not "warm solve FS")
///
/// - **Kit process source reads during fold/enumerate** — that is *lift*,
///   done before this door; owned by rendezvous + `sugar.enumerate`.
/// - **CLI `plan_workspace` / `read_project_config`** — cold front that
///   *builds* the pinned plan; a warm re-solve must pass the already-pinned
///   `RunnerConfig` (and compilers) without calling those again.
/// - **z3 process spawn** — process execution, not a project filesystem read.
/// - **Full pandas CLI wall (~33s)** — vendor-feed volume / unscoped solve,
///   not residual plan/manifest I/O on this door.
pub fn solve_project_with_pool(
    cfg: RunnerConfig,
    compilers: CompilerRegistry,
    pool: MementoPool,
) -> Result<ProvenOutcome, SolveError> {
    // One path: pool is already resident; no flag to derive.
    discharge_with_pool(cfg, compilers, pool)
}

/// THE solve body: annotate-not-block LINK + Runner discharge over one pool.
fn discharge_with_pool(
    cfg: RunnerConfig,
    compilers: CompilerRegistry,
    pool: MementoPool,
) -> Result<ProvenOutcome, SolveError> {
    // Beat 1 -- LINK (annotate). Derive real edges from the pool's bridge data
    // and bind; keep only the genuine LINK-class failures (mirrors
    // `link_beat`'s filter). This never short-circuits beat 2.
    let (link_errors, link_derivation_error) = match derive_linker_inputs(&pool) {
        Ok(links) => (link_class_errors(links), None),
        // Annotate-not-block, applied to the derivation itself: a malformed
        // contract makes the LINK VIEW undecodable, not the discharge
        // invalid. Beat 2 proceeds; the refusal rides as typed data.
        Err(reason) => (Vec::new(), Some(reason.to_string())),
    };

    // Beat 2 -- DISCHARGE. The real pipeline, over the SAME pool.
    let runner = Runner::new_with_compilers(cfg, compilers);
    let artifact = runner.run_with_proof_run_with_pool(pool)?;

    let outcome_class = OutcomeClass::from_report(&artifact.report);
    Ok(ProvenOutcome {
        link_errors,
        link_derivation_error,
        artifact,
        outcome_class,
    })
}

/// Failures staging the kit walk + testimony into a dischargeable pool —
/// precondition class, distinct from either red (link error or verdict).
#[derive(Debug, thiserror::Error)]
pub enum ProveFromKitError {
    #[error("prove_from_kit: fold claim tree failed: {0}")]
    Fold(#[from] FeedError),
    #[error("prove_from_kit: could not load local folded graph with speaker: {0}")]
    LocalLoad(String),
    #[error("prove_from_kit: vendor testimony resolve failed: {0}")]
    Testimony(#[from] TestimonyError),
    #[error(transparent)]
    Solve(#[from] SolveError),
}

/// One walk entry for project prove (#3809 Task 8–9): fold the kit claim tree
/// as the consumer speaker, fold in vendor testimony when available, and
/// discharge through the production solve beats — **without** batch mint.
///
/// Algorithm:
/// 1. `local = fold_project(kit, root, Some(&speaker))` — content only
/// 2. `pool = pool_from_graph_with_speaker(local, speaker)` — consumer stamp
/// 3. `kit.testimony(root)` → when `Proofs`, `load_proof_bytes_into_pool`
///    (vendor speakers already on each `ProofBytes`; first-writer-wins merge)
/// 4. `cfg.extra_proofs` → same pool merge (CLI dependency-proof face; the
///    preloaded-pool Runner path does not re-walk `extra_proofs`)
/// 5. [`solve_project_with_pool`] — same annotate + Runner path as disk prove
///
/// Production face: `sugar prove` routes here when a lift kit can rendezvous
/// for the project surface (Task 9). Batch mint remains for `.proof` sealing
/// / publish; prove no longer requires a prior mint for the local surface.
pub fn prove_from_kit(
    kit: &Kit,
    workspace_root: &Path,
    speaker: Speaker,
    cfg: RunnerConfig,
    compilers: CompilerRegistry,
) -> Result<ProvenOutcome, ProveFromKitError> {
    // LIFT front (not solve DoD): fold + testimony assemble the pool.
    // Kit source reads / enumerate RPC live here — rendezvous front, kept.
    let pool = fold_kit_to_pool(kit, workspace_root, speaker, &cfg)?;

    // SOLVE half: one preloaded-pool discharge. Warmth is derived inside
    // solve_project_with_pool (pool already resident) — no second door.
    Ok(solve_project_with_pool(cfg, compilers, pool)?)
}

/// LIFT half of [`prove_from_kit`]: walk enumerate + optional testimony into
/// a multi-speaker pool. May spawn the kit and (kit-side) read sources.
/// Not the solve DoD surface — use [`solve_project_with_pool`] once the pool is fed.
pub fn fold_kit_to_pool(
    kit: &Kit,
    workspace_root: &Path,
    speaker: Speaker,
    cfg: &RunnerConfig,
) -> Result<MementoPool, ProveFromKitError> {
    // 1. Local claim walk. Speaker is typed through fold so walk face and
    // pool intake share one identity; stamping happens at step 2.
    let local = feed_from_tree::fold_project(kit, workspace_root, Some(&speaker))?;

    // 2. Graph→pool intake with the consumer speaker (Task 7 door).
    let mut pool =
        pool_from_graph_with_speaker(&local, speaker).map_err(ProveFromKitError::LocalLoad)?;

    // 3. Vendor testimony when the kit implements resolve_dependency_proofs.
    // Unavailable is a LINK-class absence (local-only prove still runs), not
    // a hard error — same law as Kit::testimony / resolve_testimony.
    //
    // Diagnostics are NOT silent (#3901): the kit may have partially resolved
    // proofs and still have something to say. Surface them at warn so a
    // dropped byte is greppable; do not fold them into load_errors (those
    // are pool-decode failures, a different class).
    let resolution = kit.testimony(workspace_root)?;
    for diagnostic in &resolution.diagnostics {
        tracing::warn!(
            target: "sugar_compiler::prove_from_kit",
            "testimony diagnostic: {diagnostic}"
        );
    }
    match resolution.outcome {
        TestimonyOutcome::Proofs(proofs) => {
            load_proof_bytes_into_pool(&proofs, &mut pool);
        }
        TestimonyOutcome::Unavailable { plugin, reason } => {
            // Honest empty vendor feed: discharge over local members only.
            // Name the absence — same law as gaps-are-nodes (never silent empty).
            tracing::warn!(
                target: "sugar_compiler::prove_from_kit",
                plugin = %plugin,
                reason = %reason,
                "vendor testimony unavailable; proving over local fold only"
            );
        }
    }

    // 4. CLI / RunnerConfig dependency proofs (same merge disk load_pool uses).
    // Must happen here: `run_with_proof_run_with_pool` does not re-apply
    // `cfg.extra_proofs` (pool is already assembled).
    if !cfg.extra_proofs.is_empty() {
        load_proof_bytes_into_pool(&cfg.extra_proofs, &mut pool);
    }

    Ok(pool)
}

impl From<ProofRunArtifactError> for SolveError {
    fn from(error: ProofRunArtifactError) -> Self {
        SolveError::ProofRun(error.to_string())
    }
}

/// Run `link()` over `links` and keep only the genuine LINK-class failures
/// (`UnresolvedSymbol` / `SignatureMismatch`) -- the same filter
/// [`link_beat`] applies. Returns them as a plain vec (annotation), rather
/// than the short-circuit `Outcome` `link_beat` produces.
fn link_class_errors(links: LinkerInputs) -> Vec<LinkerError> {
    link(links)
        .linker_errors
        .into_iter()
        .filter(|e| {
            matches!(
                e.kind,
                LinkerErrorKind::UnresolvedSymbol | LinkerErrorKind::SignatureMismatch
            )
        })
        .collect()
}

/// Beat 1 -- LINK. Plain `link()` (no solver registry): its only job here is
/// symbol/signature resolution (`bind`'s two failure arms). The obligation-
/// discharge arms `link()` can also emit (`UnprovableObligation`/
/// `Implication*`) are NOT authoritative for this door -- beat 2
/// (`verify_consistency`) is the one discharge path, with ambient facts and
/// cross-proof conjoin `link()` doesn't see. Only the two genuine
/// LINK-class kinds short-circuit; any other kind `link()` produced is
/// dropped here so it does not get a second, less-informed opinion voiced
/// ahead of beat 2's real one. Returns `Some(Outcome::LinkError(..))` when
/// beat 1 must short-circuit, `None` when beat 2 should run.
fn link_beat(links: LinkerInputs) -> Option<Outcome> {
    let link_output = link(links);
    let link_errors: Vec<sugar_linker::LinkerError> = link_output
        .linker_errors
        .into_iter()
        .filter(|e| {
            matches!(
                e.kind,
                LinkerErrorKind::UnresolvedSymbol | LinkerErrorKind::SignatureMismatch
            )
        })
        .collect();
    if !link_errors.is_empty() {
        return Some(Outcome::LinkError(link_errors));
    }
    None
}

/// Self-load `graph` into a fresh, validated `MementoPool`. A failed
/// self-load is neither of the two reds -- it is a precondition failure (the
/// graph could not even be staged), so it is a typed `Err`, never a
/// fabricated `LinkError` (gitar on #3858) and never a verdict.
fn self_load_pool(graph: &ProofGraph) -> Result<MementoPool, SolveError> {
    let pool = pool_from_graph(graph).map_err(SolveError::SelfLoad)?;
    // The loader records partial rejections (duplicate contract names,
    // malformed members) in pool.load_errors rather than failing -- a
    // partial pool would discharge silently over missing members
    // (macroscope on #3858). Refuse loudly instead.
    if !pool.load_errors.is_empty() {
        return Err(SolveError::PartialLoad {
            errors: pool.load_errors.iter().map(|e| format!("{e:?}")).collect(),
        });
    }
    Ok(pool)
}

/// Failure to stage the graph for discharge -- a PRECONDITION failure,
/// structurally distinct from both reds (neither a link error nor a verdict).
#[derive(Debug, thiserror::Error)]
pub enum SolveError {
    #[error("solve: could not stage graph for discharge: {0}")]
    SelfLoad(String),
    #[error("solve: loader rejected part of the graph; refusing to discharge a partial pool: {errors:?}")]
    PartialLoad { errors: Vec<String> },
    /// A loaded contract body carried a field the linker-input derivation
    /// could not decode (sugar#3869) -- deriving over a silently-thinned
    /// contract would be an incomplete-load false green, so it is a typed
    /// precondition failure, same class as `SelfLoad`/`PartialLoad`.
    #[error("solve: refusing to derive linker inputs over malformed contract data: {0}")]
    MalformedContract(#[from] crate::linker_inputs::MalformedContractField),
    /// The real `Runner` pipeline (beat 2) failed to build its proof-run
    /// artifact. Surfaced as a typed precondition failure, same class as the
    /// others -- distinct from either red (link error or verdict).
    #[error("solve: proof-run pipeline failed: {0}")]
    ProofRun(String),
}

/// Load a `ProofGraph` into a fresh `MementoPool`, stamping **every** member
/// CID with `speaker` via the one attribution map
/// (`MementoPool.member_speaker`, first-writer-wins — same policy as
/// `utterance::speak_*` and pool `merge`).
///
/// This is the graph→pool intake door for speaker attribution (#3809 Task 7).
/// ProofGraph itself carries no attribution (content only); who spoke is a
/// property of the feed **event**, recorded at pool intake. For multi-speaker
/// conversations, load each speaker's graph separately and `merge` the pools
/// (first speaker wins on CID collision — do not invent a second map).
///
/// Uses the same throwaway-seal + `load_proof_bytes_into_pool` path as the
/// Orchestrate self-load fixture; only the stamped `Speaker` differs.
pub fn pool_from_graph_with_speaker(
    graph: &ProofGraph,
    speaker: Speaker,
) -> Result<MementoPool, String> {
    let label = speaker.id.clone();
    let proof_input = ProofEnvelopeInput {
        name: label.clone(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata: None,
        graph: graph.clone(),
        signer_cid: sugar_proof_envelope::ed25519_pubkey_string(&SOLVE_SELF_LOAD_SEED),
        signer_seed: SOLVE_SELF_LOAD_SEED,
        declared_at: "1970-01-01T00:00:00.000Z".to_string(),
        manifest: None,
    };
    let sealed = build_proof_envelope(&proof_input);
    let mut pool = MementoPool::default();
    let proof_bytes = ProofBytes::try_from_parts(label, sealed.cid.clone(), sealed.bytes, speaker)
        .map_err(|e| format!("could not stage speaker-stamped proof bytes: {e}"))?;
    load_proof_bytes_into_pool(&[proof_bytes], &mut pool);
    // Fail-loud (PR #3897 Medium→fix with Highs): never return Ok over a
    // partial pool. self_load_pool already refuses load_errors; this door must
    // too so vendor/local load failures cannot green as empty attribution.
    if !pool.load_errors.is_empty() {
        return Err(format!(
            "loader rejected part of the graph; refusing to discharge a partial pool: {:?}",
            pool.load_errors
                .iter()
                .map(|e| format!("{e:?}"))
                .collect::<Vec<_>>()
        ));
    }
    Ok(pool)
}

/// Fixture-only self-load for `Orchestrate::solve` / `solve_deriving_links`:
/// stamps every member `Speaker::consumer("solve-self-load")`.
///
/// KNOWN LIMITATION (macroscope on #3858, SEAM 2): ProofGraph does not carry
/// per-member attribution, so this door cannot distinguish vendor vs consumer
/// inside one graph. Harmless for two-reds discrimination (conjoin still
/// fires), but Tier-2 signer-trust attribution through THIS door is not
/// meaningful. Callers that know the real speaker must use
/// [`pool_from_graph_with_speaker`] (and multi-speaker merge when needed).
fn pool_from_graph(graph: &ProofGraph) -> Result<MementoPool, String> {
    pool_from_graph_with_speaker(graph, Speaker::consumer("solve-self-load"))
}
