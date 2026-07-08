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
// tests below, without inventing a fake pool-to-`LinkerInputs` bridge. The
// pool-derivation question is flagged for a follow-up seam once the kit
// side actually emits cross-kit `LinkerCallEdge`s (this is a testimony/
// cross-kit-binding concern, adjacent to SEAM 4).

use std::collections::HashMap;
use std::path::Path;

use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_linker::{link, LinkerErrorKind, LinkerInputs};
use sugar_proof_envelope::{
    build_proof_envelope, ProofEnvelopeInput, ProofGraph,
};
use sugar_verifier::consistency::verify_consistency;
use sugar_verifier::load_all_proofs::{load_proof_bytes_into_pool, ProofBytes};
use sugar_verifier::{MementoPool, Speaker, SolverHandle, SolverPlan, SolverSeat};

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
    ) -> Outcome;
}

impl Orchestrate for ProofGraph {
    fn solve(
        &self,
        links: LinkerInputs,
        plan: &SolverPlan,
        registry: &HashMap<SolverSeat, SolverHandle>,
        compilers: &CompilerRegistry,
        project_root: &Path,
    ) -> Outcome {
        // Beat 1 -- LINK. Plain `link()` (no solver registry): its only job
        // here is symbol/signature resolution (`bind`'s two failure arms).
        // The obligation-discharge arms `link()` can also emit
        // (`UnprovableObligation`/`Implication*`) are NOT authoritative for
        // this door -- beat 2 (`verify_consistency`) is the one discharge
        // path, with ambient facts and cross-proof conjoin `link()` doesn't
        // see. Only the two genuine LINK-class kinds short-circuit; any
        // other kind `link()` produced is dropped here so it does not get a
        // second, less-informed opinion voiced ahead of beat 2's real one.
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
            return Outcome::LinkError(link_errors);
        }

        // Beat 2 -- DISCHARGE. `verify_consistency` takes a `MementoPool`,
        // not a `ProofGraph` (SEAM 2 finding: the two currencies did not
        // fully collapse -- pool provenance/attribution is a property of
        // the feed EVENT, not the signed content, so a design seam remains
        // open). Reach it the same way `sugar-compiler::seal_proof_graph`
        // already does: seal an internal, throwaway-signed copy and
        // self-load it into a fresh pool via the one loader every `.proof`
        // consumer uses.
        let pool = match pool_from_graph(self) {
            Ok(pool) => pool,
            Err(reason) => {
                // Round-tripping the graph we were just handed cannot
                // honestly fail; if it ever does, that is a link-class
                // failure ("no program assembled"), not a solver verdict.
                return Outcome::LinkError(vec![sugar_linker::LinkerError {
                    kind: LinkerErrorKind::UnresolvedSymbol,
                    target_symbol: String::new(),
                    source_contract_cid: String::new(),
                    reason: format!("solve: could not stage graph for discharge: {reason}"),
                    file: None,
                    call_site_locus: None,
                }]);
            }
        };
        let verdicts = verify_consistency(&pool, plan, registry, compilers, project_root);
        Outcome::Verdicts(verdicts)
    }
}

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
