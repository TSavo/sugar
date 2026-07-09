// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Campaign B (plan: one-protocol enumerate + feed): fold the typed enumerate
// tree into a `ProofGraph` via `feed`.
//
// Task 5 ships the **red instrument** only: public surface + empty fold.
// Task 6 implements `graph_from_fact` / `graph_from_universe` and a real walk.
//
// Target shape (Task 6):
//   for each call site: feed(universe?) then feed(each fact)
//   `ProofGraph::feed` is the merge; content CIDs make order irrelevant.
//
// Replacement architecture (when green): tree nodes → claim-contract
// fragments with the same member content mint builds for `kind="contract"` /
// function-contract rows, then one fold door for solve intake. Do not invent
// a second mint path.

use std::path::Path;

use sugar_proof_envelope::ProofGraph;

use crate::kit::{Kit, KitError};
use crate::tree::{Fact, Universe};

/// Failures while turning an enumerate tree node into a `ProofGraph` fragment.
#[derive(Debug, thiserror::Error)]
pub enum FeedError {
    /// Surface still stubbed (Task 5). Task 6 deletes this arm by implementing
    /// the real constructors; the red instrument measures remaining work as
    /// empty-graph delta until then.
    #[error(
        "feed_from_tree::{what} is not implemented (Task 6): \
         build claim-contract members from Fact/Universe payloads + warrants \
         the same way mint builds kind=contract / function-contract rows"
    )]
    NotImplemented { what: &'static str },
    #[error(transparent)]
    Kit(#[from] KitError),
}

/// Build a single-member (or few-member) graph from one enumerated claim node.
///
/// **Stub (Task 5):** always `NotImplemented`. Task 6 constructs the same
/// contract member shape mint uses for `kind="contract"` rows.
pub fn graph_from_fact(_fact: &Fact) -> Result<ProofGraph, FeedError> {
    Err(FeedError::NotImplemented {
        what: "graph_from_fact",
    })
}

/// Build a graph fragment from one enumerated universe (function-contract).
///
/// **Stub (Task 5):** always `NotImplemented`.
pub fn graph_from_universe(_u: &Universe) -> Result<ProofGraph, FeedError> {
    Err(FeedError::NotImplemented {
        what: "graph_from_universe",
    })
}

/// Fold the full claim walk (facts + universes) into one graph.
///
/// **Stub (Task 5):** returns `ProofGraph::empty()` so the red instrument
/// compiles, runs, and reports `R_feed_*` against the live tree/mint floor.
/// Task 6 replaces this with the real walk + `feed` of `graph_from_*`.
pub fn fold_claim_tree(_kit: &Kit, _workspace_root: &Path) -> Result<ProofGraph, FeedError> {
    Ok(ProofGraph::empty())
}

/// Brief alias for `fold_claim_tree` (speaker attribution is Task 7).
///
/// `speaker` is accepted and ignored until pool intake stamps speakers
/// (`pool_from_graph_with_speaker` / utterance first-writer-wins).
pub fn fold_project(
    kit: &Kit,
    workspace_root: &Path,
    _speaker: Option<&str>,
) -> Result<ProofGraph, FeedError> {
    fold_claim_tree(kit, workspace_root)
}
