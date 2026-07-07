// SPDX-License-Identifier: MIT OR Apache-2.0
//
// state.rs: per-project daemon state.
//
// The daemon maintains a union of all kits' contracts and call-edges in
// memory. Each `parseFile` RPC replaces the (kitId, file) slice in the
// union, re-derives bridges via `sugar_linker::link()`, and stores the
// resulting `LinkerOutput`.
//
// Cache contract (R12-R13): we key the last `LinkerOutput` on the pair
// `(contractSetCid, callEdgeSetCid)` that produced it. If the next
// `parseFile` call's union yields the same key, we return the cached
// output directly: by the content-addressing invariant this is
// byte-identical to a fresh derivation.
//
// LRU eviction (R12): we maintain a simple bounded LRU map keyed on
// `(contractSetCid, callEdgeSetCid)`. The default cap is 1024.
// Eviction never changes output correctness: a miss just triggers a fresh
// `link()` call that produces the same result (R13).

use std::collections::{BTreeMap, VecDeque};

use serde_json::Value as Json;
use sugar_linker::solver_api::SolverPlan;
use sugar_linker::{
    link, link_with_solvers, LinkerCallEdge, LinkerContract, LinkerInputs, LinkerOutput, Registry,
};

/// Solver wiring for SEMANTIC obligation discharge.
///
/// When a `SolverContext` is attached, `update_and_link`/`relink` call
/// `sugar_linker::link_with_solvers` instead of the pure `link()`. That routes
/// every structurally-distinct `post_caller \u{2283} pre_callee` obligation
/// through the real solver registry (built by the verifier's
/// `solvers::registry::build` from the same `SolversConfig` `sugar prove` uses,
/// or a default single-z3 registry when z3 is on PATH). A literal-fact
/// assertion then discharges (green) or is refuted UNSAT (red) live in the
/// editor.
///
/// When NO context is attached the daemon runs pure `link()`: obligations
/// discharge only structurally / vacuously. That is a real degraded mode, and
/// it is reported by name in `projectStatus` (`solverMode: "structural"`) —
/// never silently.
pub struct SolverContext {
    pub registry: Registry,
    pub plan: SolverPlan,
    /// Seat labels (e.g. `["z3"]`) for the capabilities report.
    pub seats: Vec<String>,
}

/// Key type for the LRU cache.
type CacheKey = (String, String);

/// LRU cache keyed by (contractSetCid, callEdgeSetCid).
pub struct Lru {
    cap: usize,
    /// Front = most-recently-used.
    order: VecDeque<CacheKey>,
    map: BTreeMap<CacheKey, LinkerOutput>,
}

impl Lru {
    pub fn new(cap: usize) -> Self {
        Self {
            cap,
            order: VecDeque::new(),
            map: BTreeMap::new(),
        }
    }

    #[allow(dead_code)]
    pub fn get(&mut self, key: &CacheKey) -> Option<&LinkerOutput> {
        if self.map.contains_key(key) {
            self.order.retain(|k| k != key);
            self.order.push_front(key.clone());
            self.map.get(key)
        } else {
            None
        }
    }

    pub fn insert(&mut self, key: CacheKey, value: LinkerOutput) {
        if self.map.contains_key(&key) {
            self.order.retain(|k| *k != key);
        }
        self.order.push_front(key.clone());
        self.map.insert(key, value);
        while self.map.len() > self.cap {
            if let Some(evicted) = self.order.pop_back() {
                self.map.remove(&evicted);
            }
        }
    }

    pub fn clear(&mut self) {
        self.order.clear();
        self.map.clear();
    }
}

/// Per-project daemon state.
///
/// One instance lives behind a `tokio::sync::Mutex` inside the server.
/// All methods are synchronous (no async): the caller holds the mutex
/// while calling them.
pub struct ProjectState {
    /// Maps (kitId, absolute file path) -> (contracts, call_edges) produced
    /// by the last `parseFile` for that slot.
    streams: BTreeMap<(String, String), (Vec<LinkerContract>, Vec<LinkerCallEdge>)>,
    /// Most recent linker output.
    last_output: Option<LinkerOutput>,
    /// LRU cache: (contractSetCid, callEdgeSetCid) -> LinkerOutput.
    cache: Lru,
    /// Solver wiring. `None` = structural (degraded) mode; `Some` = semantic.
    solvers: Option<SolverContext>,
}

impl ProjectState {
    pub fn new(cache_cap: usize) -> Self {
        Self {
            streams: BTreeMap::new(),
            last_output: None,
            cache: Lru::new(cache_cap),
            solvers: None,
        }
    }

    /// Attach (or clear) the solver context and re-derive the current union so
    /// a warm-started daemon immediately reflects the mode. Called once at
    /// startup after the state is constructed (fresh or snapshot-restored).
    pub fn attach_solvers(&mut self, solvers: Option<SolverContext>) {
        self.solvers = solvers;
        // A restored snapshot already has streams: re-run under the new mode so
        // the first projectStatus/diagnostics reflect semantic discharge.
        self.cache.clear();
        self.relink();
    }

    /// Run the linker over `inputs`, dispatching to the semantic solver path
    /// when a context is attached and the pure path otherwise. This is the ONE
    /// place the daemon chooses link() vs link_with_solvers().
    fn run_link(&self, inputs: LinkerInputs) -> LinkerOutput {
        match &self.solvers {
            Some(ctx) => link_with_solvers(inputs, &ctx.registry, &ctx.plan),
            None => link(inputs),
        }
    }

    /// Capabilities projection for `projectStatus`: names the discharge mode so
    /// no consumer mistakes a structural (solver-less) session for a semantic
    /// one. `solverMode` is `"semantic"` when a registry is wired, else
    /// `"structural"`.
    pub fn solver_capabilities(&self) -> Json {
        match &self.solvers {
            Some(ctx) => serde_json::json!({
                "solverMode": "semantic",
                "solverSeats": ctx.seats,
            }),
            None => serde_json::json!({
                "solverMode": "structural",
                "solverSeats": [],
            }),
        }
    }

    /// Update the (kitId, file) slot and re-derive bridges.
    ///
    /// Returns the updated `LinkerOutput` (possibly from cache).
    pub fn update_and_link(
        &mut self,
        kit_id: &str,
        file: &str,
        contracts: Vec<LinkerContract>,
        call_edges: Vec<LinkerCallEdge>,
    ) -> &LinkerOutput {
        // Replace the slot.
        self.streams.insert(
            (kit_id.to_string(), file.to_string()),
            (contracts, call_edges),
        );

        // Build union inputs.
        let mut all_contracts: Vec<LinkerContract> = Vec::new();
        let mut all_call_edges: Vec<LinkerCallEdge> = Vec::new();
        for (_, (cs, ces)) in &self.streams {
            all_contracts.extend(cs.iter().cloned());
            all_call_edges.extend(ces.iter().cloned());
        }

        // Run the linker. Semantic when a solver context is attached (verdicts
        // stable per the crate's determinism contract; subprocess wall-time is
        // not, and is bounded by the SolverPlan's own typed timeout terminal),
        // pure/structural otherwise.
        let output = self.run_link(LinkerInputs {
            contracts: all_contracts,
            call_edges: all_call_edges,
        });

        // Cache under the CID key.
        let key: CacheKey = (
            output.contract_set_cid.clone(),
            output.call_edge_set_cid.clone(),
        );
        self.cache.insert(key, output.clone());
        self.last_output = Some(output);
        self.last_output.as_ref().unwrap()
    }

    /// Try to re-run link using the current union stream without mutating
    /// the stream. Used internally when cache is flushed.
    fn relink(&mut self) {
        let mut all_contracts: Vec<LinkerContract> = Vec::new();
        let mut all_call_edges: Vec<LinkerCallEdge> = Vec::new();
        for (_, (cs, ces)) in &self.streams {
            all_contracts.extend(cs.iter().cloned());
            all_call_edges.extend(ces.iter().cloned());
        }
        if all_contracts.is_empty() && all_call_edges.is_empty() {
            return;
        }
        let output = self.run_link(LinkerInputs {
            contracts: all_contracts,
            call_edges: all_call_edges,
        });
        self.last_output = Some(output);
    }

    /// Return all linker errors for the given file from the last output.
    pub fn diagnostics_for_file(&self, file: &str) -> Vec<Json> {
        let Some(output) = &self.last_output else {
            return Vec::new();
        };
        output
            .linker_errors
            .iter()
            .filter(|e| e.file.as_deref() == Some(file))
            .map(|e| {
                serde_json::json!({
                    "kind": "linker-error",
                    "errorKind": e.kind,
                    "targetSymbol": e.target_symbol,
                    "sourceContractCid": e.source_contract_cid,
                    "reason": e.reason,
                    "file": e.file,
                    "callSiteLocus": e.call_site_locus_json,
                })
            })
            .collect()
    }

    /// Return the rank-3 pin from the last output, or None if no link has run yet.
    pub fn project_status(&self) -> Option<Json> {
        let output = self.last_output.as_ref()?;
        Some(serde_json::json!({
            "contractSetCid": output.contract_set_cid,
            "callEdgeSetCid": output.call_edge_set_cid,
            "bridgeSetCid":   output.bridge_set_cid,
            "linkBundleCid":  output.link_bundle_cid,
        }))
    }

    /// Flush all cached derivations. Next `update_and_link` will re-derive cold.
    pub fn flush_cache(&mut self) {
        self.cache.clear();
        self.last_output = None;
    }

    /// Serialise state to bytes for snapshot persistence (R14).
    ///
    /// Format: JSON of per-slot records. Simple and self-describing.
    pub fn to_snapshot_bytes(&self) -> Vec<u8> {
        let slots: Vec<Json> = self
            .streams
            .iter()
            .map(|((kit, file), (contracts, edges))| {
                serde_json::json!({
                    "kit": kit,
                    "file": file,
                    "contracts": contracts,
                    "callEdges": edges,
                })
            })
            .collect();
        let snapshot = serde_json::json!({ "slots": slots });
        serde_json::to_vec(&snapshot).unwrap_or_default()
    }

    /// Restore state from snapshot bytes. Returns `Ok(state)` on success,
    /// `Err(reason)` if the snapshot is invalid.
    pub fn from_snapshot_bytes(bytes: &[u8]) -> Result<Self, String> {
        let v: Json =
            serde_json::from_slice(bytes).map_err(|e| format!("snapshot JSON parse error: {e}"))?;
        let slots = v
            .get("slots")
            .and_then(|s| s.as_array())
            .ok_or_else(|| "snapshot missing 'slots' array".to_string())?;
        let mut state = Self::new(1024);
        for slot in slots {
            let kit = slot
                .get("kit")
                .and_then(|v| v.as_str())
                .ok_or_else(|| "slot missing 'kit'".to_string())?
                .to_string();
            let file = slot
                .get("file")
                .and_then(|v| v.as_str())
                .ok_or_else(|| "slot missing 'file'".to_string())?
                .to_string();
            let contracts: Vec<LinkerContract> = serde_json::from_value(
                slot.get("contracts")
                    .cloned()
                    .unwrap_or(Json::Array(vec![])),
            )
            .map_err(|e| format!("slot contracts parse error: {e}"))?;
            let call_edges: Vec<LinkerCallEdge> = serde_json::from_value(
                slot.get("callEdges")
                    .cloned()
                    .unwrap_or(Json::Array(vec![])),
            )
            .map_err(|e| format!("slot callEdges parse error: {e}"))?;
            state.streams.insert((kit, file), (contracts, call_edges));
        }
        // Re-derive last_output from the restored streams.
        state.relink();
        Ok(state)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_contract(name: &str, kit: &str, cid: &str) -> LinkerContract {
        LinkerContract {
            name: name.to_string(),
            kit: kit.to_string(),
            contract_cid: cid.to_string(),
            pre_json: None,
            post_json: None,
            ..Default::default()
        }
    }

    #[test]
    fn test_update_and_link_returns_output() {
        let mut state = ProjectState::new(16);
        let contracts = vec![make_contract(
            "foo",
            "rust-kit",
            "blake3-512:aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001",
        )];
        let output = state.update_and_link("rust-kit", "/tmp/foo.rs", contracts, vec![]);
        assert!(output.link_bundle_cid.starts_with("blake3-512:"));
    }

    #[test]
    fn test_idempotent_same_inputs() {
        let mut state = ProjectState::new(16);
        let contracts = vec![make_contract(
            "bar",
            "go-kit",
            "blake3-512:ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002",
        )];
        let cid1 = state
            .update_and_link("go-kit", "/tmp/bar.go", contracts.clone(), vec![])
            .link_bundle_cid
            .clone();
        let cid2 = state
            .update_and_link("go-kit", "/tmp/bar.go", contracts, vec![])
            .link_bundle_cid
            .clone();
        assert_eq!(cid1, cid2, "idempotent: same inputs => same linkBundleCid");
    }

    #[test]
    fn test_project_status_after_link() {
        let mut state = ProjectState::new(16);
        assert!(state.project_status().is_none());
        state.update_and_link("rust-kit", "/tmp/x.rs", vec![], vec![]);
        let status = state.project_status();
        assert!(status.is_some());
        let s = status.unwrap();
        assert!(s.get("linkBundleCid").is_some());
    }

    #[test]
    fn test_flush_cache_clears_output() {
        let mut state = ProjectState::new(16);
        state.update_and_link("rust-kit", "/tmp/x.rs", vec![], vec![]);
        assert!(state.project_status().is_some());
        state.flush_cache();
        assert!(state.project_status().is_none());
    }

    #[test]
    fn diagnostics_for_file_preserve_callsite_locus() {
        let mut state = ProjectState::new(4);
        let source_cid = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let locus = serde_json::json!({
            "file": "/tmp/caller.rs",
            "line": 7,
            "column": 13
        });

        state.update_and_link(
            "rust",
            "/tmp/caller.rs",
            vec![LinkerContract {
                name: "caller".into(),
                kit: "rust-kit".into(),
                contract_cid: source_cid.into(),
                pre_json: None,
                post_json: Some(serde_json::json!({
                    "kind": "atomic",
                    "name": "true",
                    "args": []
                })),
                ..Default::default()
            }],
            vec![LinkerCallEdge {
                source_contract_cid: source_cid.into(),
                target_contract_cid: None,
                target_symbol: "rust-kit:missing".into(),
                call_site_locus_json: locus.clone(),
                evidence_term_json: serde_json::json!({
                    "kind": "Atomic",
                    "name": "obligation",
                    "args": []
                }),
                ..Default::default()
            }],
        );

        let diagnostics = state.diagnostics_for_file("/tmp/caller.rs");
        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0]["callSiteLocus"], locus);
    }

    #[test]
    fn test_snapshot_roundtrip() {
        let mut state = ProjectState::new(16);
        let contracts = vec![make_contract(
            "baz",
            "go-kit",
            "blake3-512:ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003",
        )];
        let original_cid = state
            .update_and_link("go-kit", "/tmp/baz.go", contracts, vec![])
            .link_bundle_cid
            .clone();

        let bytes = state.to_snapshot_bytes();
        let restored = ProjectState::from_snapshot_bytes(&bytes).expect("restore");
        let restored_cid = restored
            .project_status()
            .and_then(|s| s.get("linkBundleCid").cloned())
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .expect("restored cid");
        assert_eq!(
            original_cid, restored_cid,
            "snapshot roundtrip preserves CID"
        );
    }
}
