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
use sugar_linker::{link, LinkerErrorKind, LinkerInputs};
use sugar_proof_envelope::{build_proof_envelope, ProofEnvelopeInput, ProofGraph};
use sugar_verifier::consistency::verify_consistency;
use sugar_verifier::load_all_proofs::{load_proof_bytes_into_pool, ProofBytes};
use sugar_verifier::{MementoPool, SolverHandle, SolverPlan, SolverSeat, Speaker};

use crate::outcome::Outcome;

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
        let links = crate::linker_inputs::derive_linker_inputs(&pool);

        // Beat 1 -- LINK, over the pool-derived program.
        if let Some(outcome) = link_beat(links) {
            return Ok(outcome);
        }

        // Beat 2 -- DISCHARGE, over the SAME pool beat 1 was derived from.
        let verdicts = verify_consistency(&pool, plan, registry, compilers, project_root);
        Ok(Outcome::Verdicts(verdicts))
    }
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
}

/// KNOWN LIMITATION (macroscope on #3858, matches the SEAM 2 finding):
/// the self-load stamps EVERY member `Speaker::consumer("solve-self-load")`.
/// ProofGraph does not carry per-member attribution -- attribution is a
/// property of the feed EVENT (`feed(other, speaker)`, the open design seam)
/// -- so vendor members are misattributed as consumer here. Harmless for the
/// two-reds discrimination (conjoin still fires), but Tier-2 signer-trust
/// attribution through THIS door is not meaningful until the feed-attribution
/// seam lands. Documented, not hidden.
fn pool_from_graph(graph: &ProofGraph) -> Result<MementoPool, String> {
    let proof_input = ProofEnvelopeInput {
        name: "solve-self-load".to_string(),
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
    let proof_bytes = ProofBytes::try_from_parts(
        "solve-self-load",
        sealed.cid.clone(),
        sealed.bytes,
        Speaker::consumer("solve-self-load"),
    )
    .map_err(|e| format!("could not stage self-sealed proof bytes: {e}"))?;
    load_proof_bytes_into_pool(&[proof_bytes], &mut pool);
    Ok(pool)
}
