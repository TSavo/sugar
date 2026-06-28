// SPDX-License-Identifier: Apache-2.0
//
// Pipeline types. Mirrors implementations/cpp/.../verifier/types.hpp.
//
// Shape compatibility: a memento envelope is either the v1.1 flat
// shape (top-level `evidence`/`bindingHash`/`producerSignature`/...) or
// the v1.2 layered shape (top-level `envelope`/`header`/`metadata`).
// The accessors `memento_kind` and `memento_body` paper over the cut so
// the rest of the verifier doesn't have to branch.

use std::collections::BTreeMap;

use libsugar::compose::{OpacityMementoLookup, PinInvariantMementoView};
use serde::Serialize;
use serde_json::Value as Json;

/// Return the kind discriminator of a memento, regardless of shape:
///
/// * v1.2 layered: `header.kind`
/// * lean header/body members: `header.kind`
/// * v1.1 flat:    `evidence.kind`
pub fn memento_kind(envelope: &Json) -> Option<&str> {
    envelope
        .pointer("/header/kind")
        .or_else(|| envelope.pointer("/envelope/header/kind"))
        .or_else(|| envelope.pointer("/evidence/kind"))
        .and_then(|v| v.as_str())
}

/// Return the substrate-relevant inner object of a memento (the
/// container of kind-specific fields), regardless of shape:
///
/// * v1.2 layered: `header`
/// * lean header/body members: `body`, falling back to `header`
/// * v1.1 flat:    `evidence.body`
///
/// Note: for v1.1, formula references like `preHash`/`antecedentHash`
/// live under `evidence.body`; under v1.2 they live in `metadata`. Use
/// `memento_body_field` for those lookups.
pub fn memento_body(envelope: &Json) -> Option<&Json> {
    if envelope.get("envelope").is_some() {
        envelope
            .get("header")
            .or_else(|| envelope.pointer("/envelope/header"))
    } else if envelope.get("header").is_some() || envelope.get("body").is_some() {
        envelope.get("body").or_else(|| envelope.get("header"))
    } else {
        envelope.pointer("/evidence/body")
    }
}

/// Look up a body-tier field that the verifier needs (formula-hash
/// references and similar) regardless of shape:
///
/// * v1.2 layered: prefer `header.<field>` (substrate-load-bearing
///   bridge/contract/implication kind-specific fields), then fall back
///   to `metadata.<field>` (per-formula derived hashes like preHash).
/// * lean header/body members: prefer `header.<field>`, then `body.<field>`.
/// * v1.1 flat:    `evidence.body.<field>` (legacy flat).
///
/// This single helper covers both the substrate references the
/// verifier indexes by (antecedentHash / consequentHash on
/// implications, sourceSymbol on bridges) and the convenience hashes
/// (preHash / postHash / invHash) that ride in metadata under v1.2.
pub fn memento_body_field<'a>(envelope: &'a Json, field: &str) -> Option<&'a Json> {
    if envelope.get("envelope").is_some() {
        envelope
            .pointer("/header")
            .and_then(|h| h.get(field))
            .or_else(|| envelope.pointer("/metadata").and_then(|m| m.get(field)))
            .or_else(|| {
                envelope
                    .pointer("/envelope/header")
                    .and_then(|h| h.get(field))
            })
            .or_else(|| {
                envelope
                    .pointer("/envelope/metadata")
                    .and_then(|m| m.get(field))
            })
    } else if envelope.get("header").is_some() || envelope.get("body").is_some() {
        envelope
            .pointer("/header")
            .and_then(|h| h.get(field))
            .or_else(|| envelope.pointer("/body").and_then(|b| b.get(field)))
            .or_else(|| envelope.pointer("/metadata").and_then(|m| m.get(field)))
    } else {
        envelope
            .pointer("/evidence/body")
            .and_then(|b| b.get(field))
    }
}

fn contract_body_pointer(envelope: &Json) -> Option<String> {
    memento_body_field(envelope, "bodyCid")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

#[derive(Debug, Clone)]
pub struct LoadError {
    pub proof_path: String,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectSiteAnnotation {
    pub effect_kind: String,
    pub file: String,
    pub line: usize,
    pub callee: String,
    pub status: String,
    pub category: String,
    pub tier_to_close: String,
    pub reason: String,
    pub memento_cid: String,
    pub bundle_cid: String,
}

#[derive(Debug, Default, Clone)]
pub struct MementoPool {
    /// CID -> the canonical-bytes-decoded memento envelope (as JSON).
    /// The memento IS the verification. To verify something is to find
    /// its memento in this map.
    pub mementos: BTreeMap<String, Json>,
    /// Atom CID -> flat atom bytes from the proof catalog.
    ///
    /// Leaves live here exactly once. Body graphs and mementos point to these
    /// CIDs instead of embedding semantic leaves inline.
    pub atoms: BTreeMap<String, Vec<u8>>,
    /// Body/composition CID -> pointer-only body bytes from the proof catalog.
    ///
    /// Contract mementos name, bind, and locate a body by `bodyCid`; the body
    /// map stores the composition graph that bottoms out in `atoms`.
    pub body: BTreeMap<String, Vec<u8>>,
    /// Formula CID -> memento CID. Index for fast formula lookup.
    /// The hash IS the boundary: systems don't exchange formulas,
    /// they exchange hashes. This index lets us find the memento
    /// for a given formula hash without scanning all mementos.
    pub formula_to_memento: BTreeMap<String, String>,
    /// sourceSymbol (IR ctor name) -> bridge envelope JSON.
    pub bridges_by_symbol: BTreeMap<String, Json>,
    /// `(bundle_cid, file, line, sourceSymbol)` -> bridge envelope JSON.
    ///
    /// Callsite-SCOPED bridge index, populated alongside `bridges_by_symbol`
    /// for every bridge whose body carries a `callsite` with both a file and a
    /// line. Where `bridges_by_symbol` is last-writer-wins per bare symbol (so
    /// two producers sharing a symbol -- e.g. `serde_json::to_string::<Value>`
    /// with an `is_ok` totality post and the std `to_string` with a body-eq
    /// post -- collapse to a single slot), this index keeps them distinct by
    /// the call SITE they were minted at. A panic obligation whose argument is
    /// itself a call resolves its producer post HERE, scoped to the panic
    /// site's own `(bundle, file, line)`, so the producer guarantee that
    /// actually governs THAT call is selected rather than whichever same-symbol
    /// bridge won the per-symbol slot. The `bundle_cid` component is load-
    /// bearing for soundness: relative paths like `src/lib.rs` collide across
    /// crates, so two different crates can both have a `to_string` producer at
    /// `src/lib.rs:43`; bundle scoping keeps the panic site bound to the
    /// producer minted in its OWN bundle (bridges are minted in the caller's
    /// bundle, so the co-located producer bridge is a co-member). First-writer
    /// wins per full key; a `(bundle,file,line,symbol)` collision would mean
    /// two same-symbol calls on one source line, which (same bundle => same
    /// target contract => same post) is a K-completeness edge, not a false-pass.
    pub bridges_by_callsite: BTreeMap<(String, String, usize, String), Json>,
    /// `(bundle_cid, file, line, callee)` -> panic-freedom annotation memento.
    ///
    /// Effect-site annotations are diagnostic proof mementos, not discharge
    /// evidence. They annotate a specific unproven/residue effect occurrence
    /// after `prove --json` has produced its panic census. Bundle scoping is
    /// load-bearing: paths like `src/lib.rs` and call symbols collide across
    /// packages, so the annotation must join only to the proof bundle that
    /// produced the row it describes.
    pub panic_effect_site_annotations:
        BTreeMap<(String, String, usize, String), EffectSiteAnnotation>,
    /// sourceSymbol -> the `.proof` bundle CID the bridge memento was loaded
    /// from. Lets resolve_target enforce the self-pinned (no `targetProofCid`)
    /// case: the target contract must be a co-member of this bundle. Keyed by
    /// sourceSymbol to match `bridges_by_symbol` (same last-writer-wins key).
    pub bridge_self_bundle_by_symbol: BTreeMap<String, String>,
    /// Bundle (.proof file) CID -> set of member CIDs the bundle contained.
    ///
    /// Required to enforce `BridgeDeclaration.ConsequentBundlePinned`
    /// (see `protocol/specs/2026-04-30-ir-formal-grammar.md`
    /// § "Bridge target pinning: the shim-poisoning vector"). A bridge's
    /// `targetProofCid` names the bundle that is allowed to discharge
    /// it; we must answer "is this contract member from THAT bundle?".
    /// Multi-valued because the same member CID can legitimately appear
    /// in two bundles (an honest one and a poisoned one); we never want
    /// last-writer-wins to silently swap them.
    pub bundle_members: BTreeMap<String, std::collections::BTreeSet<String>>,
    pub load_errors: Vec<LoadError>,
    /// Contract CID -> contract name (indexed during load)
    pub cid_to_name: BTreeMap<String, String>,
    /// Contract name -> CID (reverse index)
    pub name_to_cid: BTreeMap<String, String>,
    /// Contract name -> body CID pointer carried by the contract memento.
    ///
    /// `name_to_cid` keeps the resolver-facing memento/member identity. This
    /// table follows the memento's body pointer so semantic diff can compare
    /// composed pointer graphs without deriving them sideways from the envelope.
    pub name_to_body_cid: BTreeMap<String, String>,

    // ---- Opacity discharge indexes (issue #384 B.5) ----
    //
    // These maps are indexed during `insert()` when a memento of the
    // corresponding discharge kind is loaded. The substrate's
    // `compose_function_contracts_checked` queries these via the
    // `OpacityMementoLookup` impl below.
    /// loopCid (from header.loopCid of a LoopInvariantMemento) ->
    /// memento CID. Populated when a "loop-invariant" kind memento is
    /// inserted. Spec: protocol/specs/2026-05-05-loop-invariant-memento.md
    pub loop_cid_to_memento: BTreeMap<String, String>,

    /// tryCid (from header.tryCid of a TryBranchMemento) -> memento CID.
    /// Populated when a "try-branch" kind memento is inserted.
    /// Spec: protocol/specs/2026-05-05-try-branch-memento.md
    pub try_cid_to_memento: BTreeMap<String, String>,

    /// bodyFnCid (from header.bodyFnCid of a ClosureBindingMemento) ->
    /// memento CID. Populated when a "closure-binding" kind memento is
    /// inserted. Spec: protocol/specs/2026-05-05-closure-binding-memento.md
    pub body_fn_cid_to_memento: BTreeMap<String, String>,

    /// AliasingMemento discharge index: (formal_a, formal_b) ->
    /// memento CID. Populated when an "aliasing-memento" kind memento is
    /// inserted. The key is the sorted pair of formal parameter names.
    pub aliasing_pair_to_memento: BTreeMap<(String, String), String>,

    /// Composite key "functionCid\x00target" -> memento CID. Populated
    /// when a "pin-invariant" kind memento is inserted. The composite
    /// key ensures the memento is anchored to both the function contract
    /// and the pinned parameter name.
    /// Spec: protocol/specs/2026-05-05-pin-invariant-memento.md
    pub pin_invariant_to_memento: BTreeMap<String, String>,
    /// Python class-shape catalog entries, indexed by their fully-qualified
    /// `className`. These entries are signed contract-header evidence emitted by
    /// the Python source lifter and are consumed only by the attribute-safety
    /// discharge arm.
    pub class_shapes_by_class: BTreeMap<String, Json>,
}

/// Key for implication lookups: (antecedent CID, consequent CID).
/// The implication memento itself has a CID derived from this pair.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct ImplicationKey(pub String, pub String);

impl MementoPool {
    /// The fundamental verification operation: look up a formula by its
    /// content hash. The memento IS the verification; if found, the
    /// formula is verified. No solver is invoked.
    ///
    /// Returns the memento envelope that verifies this formula.
    pub fn verify_by_hash(&self, formula_cid: &str) -> Option<&Json> {
        self.formula_to_memento
            .get(formula_cid)
            .and_then(|memento_cid| self.mementos.get(memento_cid))
    }

    /// Compute the CID for a formula JSON node, then look it up.
    /// The canonicalization + hash IS the boundary between systems.
    pub fn verify(&self, formula: &Json) -> Option<&Json> {
        let cid = compute_formula_cid(formula);
        self.verify_by_hash(&cid)
    }

    /// Return the kind discriminator of a stored member by CID. Covers all
    /// envelope shapes (v1.2 layered, lean header/body, v1.1 flat). Typed
    /// accessor so callers write `pool.member_kind(cid)` instead of
    /// `memento_kind(pool.mementos.get(cid))`.
    pub fn member_kind(&self, cid: &str) -> Option<&str> {
        self.mementos.get(cid).and_then(memento_kind)
    }

    /// Return the JSON value of a kind-specific field from a stored member,
    /// regardless of envelope shape. Typed accessor so callers write
    /// `pool.member_field(cid, "postHash")` instead of
    /// `memento_body_field(pool.mementos.get(cid), "postHash")`.
    pub fn member_field<'a>(&'a self, cid: &str, name: &str) -> Option<&'a Json> {
        self.mementos
            .get(cid)
            .and_then(|env| memento_body_field(env, name))
    }

    /// Return the semantic contract body for a loaded contract memento.
    ///
    /// Modern `.proof` catalogs store formula leaves in `atoms` and body
    /// composition in the catalog `body` map. The contract memento itself
    /// carries only binding/header metadata plus `bodyCid`. Callers that need
    /// semantic slots (`pre`, `post`, `inv`) must resolve through the pool so
    /// the graph, not legacy inline fields, is the source of truth.
    pub fn resolve_contract_body(&self, envelope: &Json) -> Option<Json> {
        let mut body = memento_body(envelope)?.as_object()?.clone();
        if let Some(body_cid) = contract_body_pointer(envelope) {
            for (slot, formula) in self.resolve_body_formula_slots(&body_cid)? {
                body.insert(slot, formula);
            }
        }
        Some(Json::Object(body))
    }

    fn resolve_body_formula_slots(&self, body_cid: &str) -> Option<BTreeMap<String, Json>> {
        let body_bytes = self.body.get(body_cid)?;
        let body_doc: Json = serde_json::from_slice(body_bytes).ok()?;
        let slots = body_doc.pointer("/body")?.as_object()?;
        let mut resolved = BTreeMap::new();
        for (slot, slot_memento) in slots {
            let atom_cid = slot_memento
                .get("atomCid")
                .and_then(|value| value.as_str())?;
            let atom_bytes = self.atoms.get(atom_cid)?;
            let formula: Json = serde_json::from_slice(atom_bytes).ok()?;
            resolved.insert(slot.clone(), formula);
        }
        Some(resolved)
    }

    /// Check if P → Q is already proven in the pool.
    /// Looks for an implication memento whose evidence body contains
    /// both antecedentHash = P and consequentHash = Q.
    ///
    /// This is the core of bridge enforcement: "does the publisher's
    /// post imply the consumer's pre?"
    pub fn verify_implication(&self, antecedent_cid: &str, consequent_cid: &str) -> Option<&Json> {
        // The proof of `P → Q` is the implication memento that links them, not
        // the presence of P or Q in `formula_to_memento`. (P, the antecedent,
        // is no longer indexed there at all -- it is an assumption, not a
        // fact.) Scan for an implication memento with these exact endpoints.
        // Shape-agnostic: under v1.2 these references live in the
        // metadata; under v1.1 they live in evidence.body.
        for envelope in self.mementos.values() {
            if memento_kind(envelope) == Some("implication") {
                let ant = memento_body_field(envelope, "antecedentHash").and_then(|v| v.as_str());
                let con = memento_body_field(envelope, "consequentHash").and_then(|v| v.as_str());
                if ant == Some(antecedent_cid) && con == Some(consequent_cid) {
                    return Some(envelope);
                }
            }
        }
        None
    }

    /// Check if P → Q via transitive chaining.
    /// If P → R and R → Q are both in the pool, then P → Q.
    /// Uses BFS on the implication graph.
    pub fn implies_transitive(
        &self,
        antecedent_cid: &str,
        consequent_cid: &str,
    ) -> Option<Vec<String>> {
        if antecedent_cid == consequent_cid {
            return Some(vec![antecedent_cid.to_string()]);
        }

        // Build implication graph adjacency list on-the-fly.
        // Shape-agnostic per the body/header accessors.
        let mut graph: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for envelope in self.mementos.values() {
            if memento_kind(envelope) == Some("implication") {
                if let (Some(ant), Some(con)) = (
                    memento_body_field(envelope, "antecedentHash").and_then(|v| v.as_str()),
                    memento_body_field(envelope, "consequentHash").and_then(|v| v.as_str()),
                ) {
                    graph
                        .entry(ant.to_string())
                        .or_default()
                        .push(con.to_string());
                }
            }
        }

        // BFS
        let mut visited = std::collections::HashSet::new();
        let mut queue = std::collections::VecDeque::new();
        let mut path_map = BTreeMap::new();

        queue.push_back(antecedent_cid.to_string());
        visited.insert(antecedent_cid.to_string());
        path_map.insert(antecedent_cid.to_string(), vec![antecedent_cid.to_string()]);

        while let Some(current) = queue.pop_front() {
            if let Some(neighbors) = graph.get(&current) {
                for neighbor in neighbors {
                    if neighbor == consequent_cid {
                        let mut path = path_map.get(&current).unwrap().clone();
                        path.push(neighbor.clone());
                        return Some(path);
                    }
                    if visited.insert(neighbor.clone()) {
                        let mut path = path_map.get(&current).unwrap().clone();
                        path.push(neighbor.clone());
                        path_map.insert(neighbor.clone(), path);
                        queue.push_back(neighbor.clone());
                    }
                }
            }
        }

        None
    }

    /// Full implication check: direct, transitive, or via sub-formula composition.
    /// Returns the proof path if P → Q holds.
    pub fn can_implies(&self, antecedent_cid: &str, consequent_cid: &str) -> ImplicationResult {
        // 1. Reflexivity: P → P always holds (check first)
        if antecedent_cid == consequent_cid {
            return ImplicationResult::ProvenReflexive;
        }

        // 2. Direct implication
        if let Some(memento) = self.verify_implication(antecedent_cid, consequent_cid) {
            return ImplicationResult::ProvenDirect {
                memento_cid: memento
                    .get("cid")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown")
                    .to_string(),
            };
        }

        // 3. Transitive implication
        if let Some(path) = self.implies_transitive(antecedent_cid, consequent_cid) {
            return ImplicationResult::ProvenTransitive { path };
        }

        ImplicationResult::Unknown
    }

    /// Insert a memento into the pool and index it by formula hash.
    /// The .proof protocol IS the cache: storing a memento IS caching
    /// the verification result.
    pub fn insert(&mut self, memento_cid: String, envelope: Json) {
        // Index ONLY the formula hashes that name an ESTABLISHED FACT into
        // `formula_to_memento` -- the map Tier 0 (`verify`) trusts as "this
        // formula is proven true". A precondition (`preHash`) and an
        // implication antecedent (`antecedentHash`) are OBLIGATIONS /
        // ASSUMPTIONS, not facts: indexing them let a callsite's consumer
        // precondition self-discharge merely because the callee DECLARES it
        // (the missing-edge hole; see `precondition_is_obligation_not_verified_fact`).
        // Established facts: a function's `postHash`/`invHash` (guarantees on
        // return / always). NOT `consequentHash`: an implication's consequent
        // `Q` holds only GIVEN its antecedent `P`, so indexing it would make
        // Tier 0 `verify(Q)` treat a conditional as unconditional -- the same
        // category error as `preHash`/`antecedentHash`. Proven implications
        // discharge via `verify_implication`/`can_implies`, which scan
        // implication mementos directly and don't need the consequent here.
        for field in &["postHash", "invHash"] {
            if let Some(hash) = memento_body_field(&envelope, field).and_then(|v| v.as_str()) {
                self.formula_to_memento
                    .insert(hash.to_string(), memento_cid.clone());
            }
        }
        self.mementos.insert(memento_cid.clone(), envelope);

        // Index by contract name for cross-kit resolution.
        // Gate on memento kind: only contract-shaped mementos carry a
        // contractName/name that's a stable cross-kit identifier. Other
        // kinds (implication, etc.) sometimes have a header.name field
        // but it's not a contract identity, so indexing them would
        // mis-resolve call edges.
        let is_contract = self.member_kind(&memento_cid) == Some("contract");
        if is_contract {
            let env_for_name = self.mementos.get(&memento_cid);
            let name = env_for_name
                .and_then(|env| {
                    env.pointer("/header/contractName")
                        .or_else(|| env.pointer("/header/name"))
                        .or_else(|| env.pointer("/evidence/body/contractName"))
                        .or_else(|| env.pointer("/evidence/body/name"))
                })
                .and_then(|v| v.as_str());

            if let Some(n) = name {
                let n = n.to_string();
                let body_cid = env_for_name.and_then(contract_body_pointer);

                // Detect collisions: same contract name, different CIDs.
                // When two surfaces in the same proof emit a contract with the
                // same name (e.g. rust-bind emits a post-only `option_unwrap`
                // and rust-fn-contracts emits a pre-bearing `option_unwrap`),
                // prefer the pre-bearing shape over the post-only shape:
                // PRE-bearing > body-bearing(post) > inv-only. This mirrors the
                // dependency-harvest ranking in cmd_mint.rs. Silently upgrade
                // the index (no LoadError) when the new contract is strictly
                // more dischargeable than the existing one; report a LoadError
                // only for genuinely ambiguous same-tier collisions.
                if let Some(existing) = self.name_to_cid.get(&n).cloned() {
                    if existing != memento_cid {
                        let new_has_pre = self.member_field(&memento_cid, "preHash").is_some();
                        let existing_has_pre = self.member_field(&existing, "preHash").is_some();
                        let new_env = self.mementos.get(&memento_cid);
                        let existing_env = self.mementos.get(&existing);
                        if new_has_pre && !existing_has_pre {
                            // Upgrade: pre-bearing newcomer beats post-only incumbent.
                            self.cid_to_name.remove(&existing);
                            self.cid_to_name.insert(memento_cid.clone(), n.clone());
                            self.name_to_cid.insert(n.clone(), memento_cid.clone());
                            if let Some(body_cid) = body_cid {
                                self.name_to_body_cid.insert(n, body_cid);
                            }
                        } else if !new_has_pre && existing_has_pre {
                            // Incumbent is already pre-bearing; silently drop the new post-only.
                        } else if is_euf_inv_only_conjoin_duplicate(&n, existing_env, new_env) {
                            // Same-name #euf# inv-only contracts are the
                            // intentional cross-proof conjoin case. Keep the
                            // first name index for symbol lookup, keep both
                            // mementos in the pool, and let
                            // consistency::verify_consistency conjoin them.
                        } else {
                            // Same tier (both pre-bearing or both post-only): genuine collision.
                            self.load_errors.push(LoadError {
                                proof_path: memento_cid.clone(),
                                reason: format!(
                                    "duplicate contract name `{n}` resolves to two CIDs: {existing} (kept) and {memento_cid} (dropped)"
                                ),
                            });
                        }
                    }
                } else {
                    self.cid_to_name.insert(memento_cid.clone(), n.clone());
                    self.name_to_cid.insert(n.clone(), memento_cid.clone());
                    if let Some(body_cid) = body_cid {
                        self.name_to_body_cid.insert(n, body_cid);
                    }
                }
            }
        }

        let class_shapes_to_index: Vec<Json> = if let Some(env) = self.mementos.get(&memento_cid) {
            if memento_kind(env) == Some("contract") {
                if let Some(body) = memento_body(env) {
                    body.get("classShapes")
                        .and_then(|v| v.as_array())
                        .into_iter()
                        .flatten()
                        .cloned()
                        .collect()
                } else {
                    Vec::new()
                }
            } else {
                Vec::new()
            }
        } else {
            Vec::new()
        };
        for shape in class_shapes_to_index {
            self.index_class_shape_for_tests(shape);
        }

        // ---- Opacity discharge indexing (issue #384 B.5) ----
        // Index discharge mementos by their opacity-site CID fields so that
        // OpacityMementoLookup queries are O(log n) BTreeMap lookups rather
        // than a full pool scan.
        //
        // member_kind / member_field cover both v1.1 flat (evidence.body.*)
        // and v1.2 layered (header.*) shapes without call-site branching.
        // The `.map(str::to_string)` at each field lookup converts the
        // borrowed &str to an owned String before the mutable index entry,
        // avoiding a simultaneous shared+mutable borrow on self.
        let kind = self.member_kind(&memento_cid).map(str::to_string);
        match kind.as_deref() {
            Some("loop-invariant") => {
                // header.loopCid (v1.2) or evidence.body.loopCid (v1.1)
                if let Some(loop_cid) = self
                    .member_field(&memento_cid, "loopCid")
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                {
                    self.loop_cid_to_memento
                        .entry(loop_cid)
                        .or_insert(memento_cid.clone());
                }
            }
            Some("try-branch") => {
                // header.tryCid (v1.2) or evidence.body.tryCid (v1.1)
                if let Some(try_cid) = self
                    .member_field(&memento_cid, "tryCid")
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                {
                    self.try_cid_to_memento
                        .entry(try_cid)
                        .or_insert(memento_cid.clone());
                }
            }
            Some("closure-binding") => {
                // header.bodyFnCid (v1.2) or evidence.body.bodyFnCid (v1.1)
                if let Some(body_fn_cid) = self
                    .member_field(&memento_cid, "bodyFnCid")
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                {
                    self.body_fn_cid_to_memento
                        .entry(body_fn_cid)
                        .or_insert(memento_cid.clone());
                }
            }
            Some("aliasing-memento") => {
                // header.formal_a and header.formal_b (v1.2) or evidence.body.formal_a/formal_b (v1.1)
                // Index by the sorted (formal_a, formal_b) pair. Convert to owned
                // Strings before the mutable entry borrow.
                let formal_a = self
                    .member_field(&memento_cid, "formal_a")
                    .and_then(|v| v.as_str())
                    .map(str::to_string);
                let formal_b = self
                    .member_field(&memento_cid, "formal_b")
                    .and_then(|v| v.as_str())
                    .map(str::to_string);
                if let (Some(formal_a), Some(formal_b)) = (formal_a, formal_b) {
                    let mut pair = (formal_a, formal_b);
                    // Sort the pair for canonical ordering
                    if pair.0 > pair.1 {
                        pair = (pair.1, pair.0);
                    }
                    self.aliasing_pair_to_memento
                        .entry(pair)
                        .or_insert(memento_cid.clone());
                }
            }
            Some("pin-invariant") => {
                // header.functionCid + header.pinnedTarget -> composite key
                let function_cid = self
                    .member_field(&memento_cid, "functionCid")
                    .and_then(|v| v.as_str())
                    .map(str::to_string);
                let target = self
                    .member_field(&memento_cid, "pinnedTarget")
                    .and_then(|v| v.as_str())
                    .map(str::to_string);
                if let (Some(fc), Some(t)) = (function_cid, target) {
                    let key = format!("{}\x00{}", fc, t);
                    self.pin_invariant_to_memento
                        .entry(key)
                        .or_insert(memento_cid.clone());
                }
            }
            _ => {}
        }
    }

    /// Sub-formula composition: walk the formula DAG and return all
    /// sub-formula CIDs that have mementos in the pool. If P is verified
    /// and we need to prove P ∧ Q, this returns P's CID so the solver
    /// can focus on Q.
    pub fn find_verified_subformulas(&self, formula: &Json) -> Vec<(String, &Json)> {
        let mut verified = Vec::new();
        let mut stack = vec![formula.clone()];
        let mut visited = std::collections::HashSet::new();

        while let Some(node) = stack.pop() {
            let cid = compute_formula_cid(&node);
            if !visited.insert(cid.clone()) {
                continue;
            }

            if let Some(memento) = self.verify_by_hash(&cid) {
                verified.push((cid, memento));
            }

            // Push children for recursive checking
            if let Some(obj) = node.as_object() {
                match obj.get("kind").and_then(|v| v.as_str()) {
                    Some("and") | Some("or") | Some("not") | Some("implies") => {
                        if let Some(ops) = obj.get("operands").and_then(|v| v.as_array()) {
                            for op in ops {
                                stack.push(op.clone());
                            }
                        }
                    }
                    Some("forall") | Some("exists") | Some("choice") => {
                        if let Some(body) = obj.get("body") {
                            stack.push(body.clone());
                        }
                    }
                    _ => {}
                }
            }
        }

        verified
    }

    /// Merge another pool into this one.
    ///
    /// Collision policy: for keys that already exist in `self`, the
    /// existing value wins (insert-only-if-absent). Cross-project merges
    /// must not silently overwrite earlier-loaded resolutions; surface
    /// collisions via `load_errors` so the verifier reports them.
    pub fn merge(&mut self, other: Self) {
        for (cid, bytes) in other.atoms {
            self.atoms.entry(cid).or_insert(bytes);
        }
        for (cid, bytes) in other.body {
            self.body.entry(cid).or_insert(bytes);
        }
        for (cid, env) in other.mementos {
            self.mementos.entry(cid).or_insert(env);
        }
        for (k, v) in other.formula_to_memento {
            if let Some(existing) = self.formula_to_memento.get(&k) {
                if existing != &v {
                    self.load_errors.push(LoadError {
                        proof_path: v.clone(),
                        reason: format!(
                            "merge collision for formula `{k}`: kept `{existing}`, dropped `{v}`"
                        ),
                    });
                }
            } else {
                self.formula_to_memento.insert(k, v);
            }
        }
        for (k, v) in other.bridges_by_symbol {
            self.bridges_by_symbol.entry(k).or_insert(v);
        }
        for (k, v) in other.bridges_by_callsite {
            self.bridges_by_callsite.entry(k).or_insert(v);
        }
        for (k, v) in other.panic_effect_site_annotations {
            if let Some(existing) = self.panic_effect_site_annotations.get(&k) {
                if existing.memento_cid != v.memento_cid {
                    self.load_errors.push(LoadError {
                        proof_path: v.memento_cid.clone(),
                        reason: format!(
                            "[effect-site-annotation-duplicate] for ({}, {}, {}, {}): kept `{}`, dropped `{}`",
                            k.0, k.1, k.2, k.3, existing.memento_cid, v.memento_cid
                        ),
                    });
                }
            } else {
                self.panic_effect_site_annotations.insert(k, v);
            }
        }
        for (k, v) in other.bridge_self_bundle_by_symbol {
            self.bridge_self_bundle_by_symbol.entry(k).or_insert(v);
        }
        for (k, vs) in other.bundle_members {
            self.bundle_members.entry(k).or_default().extend(vs);
        }
        self.load_errors.extend(other.load_errors);
        for (k, v) in other.cid_to_name {
            self.cid_to_name.entry(k).or_insert(v);
        }
        for (k, v) in other.name_to_cid {
            if let Some(existing) = self.name_to_cid.get(&k) {
                if existing != &v {
                    if !is_euf_inv_only_conjoin_duplicate(
                        &k,
                        self.mementos.get(existing),
                        self.mementos.get(&v),
                    ) {
                        self.load_errors.push(LoadError {
                            proof_path: v.clone(),
                            reason: format!(
                                "merge collision for contract name `{k}`: kept `{existing}`, dropped `{v}`"
                            ),
                        });
                    }
                }
            } else {
                self.name_to_cid.insert(k, v);
            }
        }
        for (k, v) in other.name_to_body_cid {
            self.name_to_body_cid.entry(k).or_insert(v);
        }
        // Opacity discharge indexes: first-insertion wins (same policy as
        // other single-valued indexes). Collisions on these keys mean two
        // proofs supply different discharge mementos for the same opacity
        // site: keep the first, let the substrate use whichever it loaded
        // first.
        for (k, v) in other.loop_cid_to_memento {
            self.loop_cid_to_memento.entry(k).or_insert(v);
        }
        for (k, v) in other.try_cid_to_memento {
            self.try_cid_to_memento.entry(k).or_insert(v);
        }
        for (k, v) in other.body_fn_cid_to_memento {
            self.body_fn_cid_to_memento.entry(k).or_insert(v);
        }
        for (k, v) in other.aliasing_pair_to_memento {
            self.aliasing_pair_to_memento.entry(k).or_insert(v);
        }
        for (k, v) in other.pin_invariant_to_memento {
            self.pin_invariant_to_memento.entry(k).or_insert(v);
        }
        for (k, v) in other.class_shapes_by_class {
            self.class_shapes_by_class.entry(k).or_insert(v);
        }
    }

    pub fn index_class_shape_for_tests(&mut self, shape: Json) {
        if let Some(class_name) = shape
            .get("className")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(str::to_string)
        {
            self.class_shapes_by_class
                .entry(class_name)
                .or_insert(shape);
        }
    }
}

fn is_euf_inv_only_conjoin_duplicate(
    name: &str,
    existing_env: Option<&Json>,
    new_env: Option<&Json>,
) -> bool {
    name.contains("#euf#")
        && existing_env.is_some_and(is_inv_only_consistency_contract)
        && new_env.is_some_and(is_inv_only_consistency_contract)
}

fn is_inv_only_consistency_contract(env: &Json) -> bool {
    if memento_kind(env) != Some("contract") {
        return false;
    }
    let Some(body) = memento_body(env) else {
        return false;
    };
    let has_inv = body.get("inv").is_some()
        || body.get("invariant").is_some()
        || memento_body_field(env, "invHash").is_some();
    let has_pre = body.get("pre").is_some()
        || body.get("precondition").is_some()
        || memento_body_field(env, "preHash").is_some();
    let has_post = body.get("post").is_some()
        || body.get("postcondition").is_some()
        || memento_body_field(env, "postHash").is_some();
    has_inv && !has_pre && !has_post
}

/// `MementoPool` implements `OpacityMementoLookup` so that
/// `compose_function_contracts_checked` in `libsugar` can query
/// whether a discharge memento is present for a given opacity site CID.
///
/// Each lookup is an O(log n) BTreeMap probe against the three
/// opacity-discharge indexes populated by `MementoPool::insert()`.
impl OpacityMementoLookup for MementoPool {
    fn has_loop_invariant(&self, loop_cid: &str) -> bool {
        self.loop_cid_to_memento.contains_key(loop_cid)
    }
    fn has_try_branch(&self, try_cid: &str) -> bool {
        self.try_cid_to_memento.contains_key(try_cid)
    }
    fn has_closure_binding(&self, body_fn_cid: &str) -> bool {
        self.body_fn_cid_to_memento.contains_key(body_fn_cid)
    }
    fn has_drop_contract(&self, _type_name: &str) -> bool {
        // No drop-contract discharge memento kind is specified yet
        // (follow-up to issue #384). Return false so the substrate
        // refuses composition rather than silently assuming the drop
        // is effect-free. Wire this to a real index once the
        // drop-contract memento spec lands under protocol/specs/.
        false
    }
    fn has_aliasing_memento(&self, formal_a: &str, formal_b: &str) -> bool {
        // Check if the pool has an aliasing memento for this pair of formals.
        // Canonicalize by sorting the pair.
        let mut pair = (formal_a.to_string(), formal_b.to_string());
        if pair.0 > pair.1 {
            pair = (pair.1, pair.0);
        }
        self.aliasing_pair_to_memento.contains_key(&pair)
    }
    fn lookup_pin_invariant(
        &self,
        function_cid: &str,
        target: &str,
    ) -> Option<PinInvariantMementoView> {
        let key = format!("{}\x00{}", function_cid, target);
        let memento_cid = self.pin_invariant_to_memento.get(&key)?;
        let memento = self.mementos.get(memento_cid)?;
        let invariant = memento_body_field(memento, "invariant")?
            .as_str()?
            .to_string();
        Some(PinInvariantMementoView {
            function_cid: function_cid.to_string(),
            pinned_target: target.to_string(),
            invariant,
        })
    }
}

/// Result of an implication check.
#[derive(Debug, Clone)]
pub enum ImplicationResult {
    /// Direct implication memento found in pool.
    ProvenDirect { memento_cid: String },
    /// Transitive chain of implications found.
    ProvenTransitive { path: Vec<String> },
    /// Trivial: P → P.
    ProvenReflexive,
    /// No known implication path.
    Unknown,
}

impl ImplicationResult {
    pub fn is_proven(&self) -> bool {
        !matches!(self, Self::Unknown)
    }
}

/// Compute the CID for a formula JSON node by canonicalizing and hashing.
/// The hash IS the boundary: this function is the gate between the
/// formula domain and the hash domain.
pub fn compute_formula_cid(formula: &Json) -> String {
    use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};

    fn json_to_value(j: &Json) -> std::sync::Arc<Value> {
        match j {
            Json::Null => Value::null(),
            Json::Bool(b) => Value::boolean(*b),
            Json::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Value::integer(i128::from(i))
                } else if let Some(u) = n.as_u64() {
                    Value::integer(i128::from(u))
                } else if let Some(f) = n.as_f64() {
                    Value::integer(f as i128)
                } else {
                    Value::integer(0)
                }
            }
            Json::String(s) => Value::string(s.clone()),
            Json::Array(items) => {
                let v: Vec<_> = items.iter().map(json_to_value).collect();
                Value::array(v)
            }
            Json::Object(map) => {
                let entries: Vec<(String, _)> = map
                    .iter()
                    .map(|(k, v)| (k.clone(), json_to_value(v)))
                    .collect();
                std::sync::Arc::new(Value::Object(entries))
            }
        }
    }

    let value_tree = json_to_value(formula);
    let canonical = encode_jcs(&value_tree);
    blake3_512_of(canonical.as_bytes())
}

#[derive(Debug, Default, Clone)]
pub struct CallSite {
    pub bridge_ir_name: String,
    pub bridge_target_cid: String,
    pub bridge_source_layer: String,
    pub bridge_target_layer: String,
    /// Forward pin: the specific `.proof` bundle CID this bridge commits
    /// to as its consequent (CROSS-bundle target). `None` means the bridge is
    /// SELF-pinned: its target contract must be a co-member of the bridge's
    /// own bundle (see `bridge_self_bundle_cid`). Either way the pin is
    /// enforced; there is no unpinned path. See
    /// `protocol/specs/2026-04-30-ir-formal-grammar.md`
    /// § "Bridge target pinning: the shim-poisoning vector".
    pub bridge_target_proof_cid: Option<String>,
    /// The `.proof` bundle CID the bridge memento itself was loaded from.
    /// Used to enforce the self-pinned (`bridge_target_proof_cid == None`)
    /// case: the target contract must be a co-member of this same bundle.
    /// `None` only if the bridge memento was not associated with any bundle
    /// (a hand-built in-memory pool); resolve_target then cannot self-pin.
    pub bridge_self_bundle_cid: Option<String>,
    pub property_name: String,
    pub property_cid: String,
    /// The `.proof` bundle CID containing the property/contract whose body
    /// produced this callsite. For panic-site producer lookup, co-located
    /// receiver bridges are minted in this same caller bundle; this is distinct
    /// from the selected bridge memento's own bundle, which can be polluted by
    /// a global per-symbol bridge index when target and import proofs are
    /// loaded together.
    pub callsite_bundle_cid: Option<String>,
    pub arg_term: Option<Json>,
    /// All actual argument terms on the bridged call, in source order. The
    /// legacy `arg_term` remains the first actual for producer-post and
    /// panic-site paths that intentionally operate on a single receiver/value.
    /// Multi-formal precondition discharge uses this vector to specialize a
    /// target pre over every formal without interpreting the language.
    pub arg_terms: Vec<Json>,
    /// Optional kit-provided binding from target formal name to the callsite
    /// actual term that denotes it. This is opaque verifier data: the language
    /// kit owns receiver/argument alignment; the verifier substitutes by these
    /// names and fails closed when a required binding is absent.
    pub formal_actuals: Option<Json>,
    /// Optional kit-provided producer provenance for panic-site receiver calls.
    /// For `producer().expect(..)`, the panic leaf and the producer call can
    /// start on different source lines. The verifier treats these as opaque
    /// coordinates into `bridges_by_callsite`; the language kit owns how they
    /// were derived.
    pub producer_file: Option<String>,
    pub producer_line: Option<usize>,
    pub producer_symbol: Option<String>,
    /// The atomic predicate the matched call ctor sits directly inside, if
    /// the call was found as an argument of an atomic (e.g. the `=` in a
    /// harvested `assert_eq!(double(3), 6)` -> `=(double(3), 6)`). Captured
    /// so the body-discharge path can derive the postcondition `Q` (the
    /// atomic with the call replaced by `result`). `None` when the call was
    /// not directly under an atomic. Does not participate in any CID.
    pub containing_atomic: Option<Json>,
    /// PANIC-FREEDOM guard context: the path conditions (as atomic-predicate
    /// formulas) that DOMINATE this call site in the lifted caller body. The
    /// dominating fact is RESOLVED BY THE RUST KIT, not by this verifier: the
    /// lifter wraps a guarded branch in `cf_guarded(<resolved-predicate>,
    /// value)` (then-branch -> positive predicate, else-branch -> the kit's
    /// complement), and `enumerate_callsites` copies that opaque atom into this
    /// vector verbatim, recognizing no Rust predicate name. The discharge of a
    /// panic partial's `pre` is performed UNDER these facts: a site dominated by
    /// the matching guard discharges panic-safe (`guard => pre` is valid), an
    /// unwrapped site keeps an empty guard set so the bare `pre` is unprovable
    /// -> honest undecidable. Fail-safe by construction: a missing wrapper can
    /// only UNDER-prove (K too low), never mark an unguarded site safe. Does not
    /// participate in any CID.
    pub guard_facts: Vec<Json>,
    /// Opaque kit-provided source file for observability. The verifier does
    /// not interpret this path, it only carries it into reports.
    pub file: Option<String>,
    /// Opaque kit-provided source line for observability.
    pub line: Option<usize>,
    /// Opaque kit-provided callee label for observability.
    pub callee: Option<String>,
    /// True when the kit classified this callsite as panic-relevant. The
    /// verifier and CLI do not derive this from language semantics.
    pub panic_site: bool,
    /// Python attribute-access safety obligation metadata. Present only when
    /// the Python source lifter knows the receiver's class at the access site.
    /// The verifier discharges it from signed `classShapes` evidence or from a
    /// dominating `attribute_present(receiver, attr)` guard; no other panic
    /// path reads it.
    pub attribute_safety: Option<AttributeSafetyObligation>,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct AttributeSafetyObligation {
    pub receiver_class: Option<String>,
    pub receiver_qualname: Option<String>,
    pub receiver_name: Option<String>,
    pub attribute: String,
}

#[derive(Debug, Default, Clone)]
pub struct ResolvedProperty {
    pub cid: String,
    pub ir_formula: Option<Json>,
    pub ir_kit_version: String,
    /// Target contract formal names and sorts, copied from the contract header
    /// when present. These are identity slots for callsite substitution only;
    /// the verifier does not interpret source-language types.
    pub formal_names: Vec<String>,
    pub formal_sorts: Vec<Json>,
    /// True iff the resolved target contract is a body-derived op-contract
    /// (body-bearing), not a plain refinement target.
    ///
    /// The canonical marker is a non-empty `formals` array on the contract
    /// body: that is what `core::bind::bind_function_bridge` mints and what
    /// body-bearing test fixtures construct. If a future contract shape
    /// carries body markers under a different field, it MUST be recognized
    /// here (`resolve_target::run` is the single setter) so the honesty
    /// boundary stays complete.
    ///
    /// A body-bearing target whose obligation cannot be reduced and
    /// discharged MUST be refused, never vacuous-passed -- the "no
    /// precondition => vacuously true" shortcut is only legitimate for
    /// genuinely non-body-bearing claims. Both consumers enforce this before
    /// their vacuous-discharge branch: `cmd_verify::verify_one_claim` and
    /// `runner::work_one`.
    pub target_is_body_bearing: bool,
}

#[derive(Debug, Clone)]
pub struct Obligation {
    pub property_cid: String,
    pub ir_kit_version: String,
    pub ir_formula: Json,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ObligationVerdict {
    Discharged,
    Unsatisfied,
    Undecidable,
    Disagreement,
    /// First-class, loudly-bounded REFUSAL: there is no sound discharger for this
    /// obligation (e.g. its precondition lowers to a construct the solver cannot
    /// interpret -- z3 "unknown constant"). NOT a violation, NOT an undecidable
    /// gap, NOT a crash: an honest "I decline to decide this, here is why." The
    /// trichotomy's third arm (exact / loudly-bounded-lossy / REFUSE), so it does
    /// not redden the gate -- a refusal is an expected, named outcome.
    Refused,
}

impl ObligationVerdict {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Discharged => "discharged",
            Self::Unsatisfied => "unsatisfied",
            Self::Undecidable => "undecidable",
            Self::Disagreement => "disagreement",
            Self::Refused => "refused",
        }
    }
}

#[derive(Debug, Clone)]
pub struct ReportRow {
    pub callsite: CallSite,
    pub status: String,
    pub reason: String,
    pub discharge_method: Option<String>,
    pub body_discharge_tier: Option<String>,
    pub verification: Option<Json>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ResolvedCallEdge {
    pub source_contract_cid: String,
    pub target_contract_cid: String,
    pub file: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ToolchainPlanReport {
    pub plan_memento_cid: String,
    pub plan_cid: String,
    pub status: String,
    pub reason: String,
    pub expected_output_cids: Vec<String>,
    pub witness_memento_cid: Option<String>,
    pub actual_output_cids: Vec<String>,
}

#[derive(Debug, Default, Clone)]
pub struct Report {
    pub total_callsites: usize,
    pub discharged: usize,
    pub violations: usize,
    /// Obligations honestly REFUSED (no sound discharger): not discharged (no
    /// false pass), not a violation (does not redden the gate). The trichotomy's
    /// third arm, surfaced in the scoreboard so refusals are loud, not hidden.
    pub refused: usize,
    pub rows: Vec<ReportRow>,
    pub load_errors: Vec<LoadError>,
    pub call_edges: Vec<ResolvedCallEdge>,
    pub toolchain_plans: Vec<ToolchainPlanReport>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn make_implication_memento(ant: &str, con: &str) -> Json {
        json!({
            "cid": format!("blake3-512:{}{}", ant, con),
            "evidence": {
                "kind": "implication",
                "body": {
                    "antecedentHash": ant,
                    "consequentHash": con,
                    "prover": "z3@4.12",
                    "proverRunMs": 42
                }
            }
        })
    }

    fn make_inv_only_contract(name: &str, value: i64) -> Json {
        json!({
            "envelope": {
                "signer": "ed25519:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "declaredAt": "2026-05-05T00:00:00Z",
                "signature": "ed25519:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            },
            "header": {
                "schemaVersion": "1",
                "kind": "contract",
                "contractName": name,
                "inv": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [
                        {"kind": "var", "name": "r"},
                        {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": value}
                    ]
                }
            }
        })
    }

    #[test]
    fn lean_header_body_source_memento_uses_common_accessors() {
        let memento = json!({
            "schemaVersion": "1",
            "header": {
                "kind": "source-memento",
                "contractName": "rust-source::enc",
                "sourceFunctionName": "enc"
            },
            "body": {
                "kind": "source-memento",
                "file": "src/lib.rs",
                "source_cid": "blake3-512:source"
            }
        });

        assert_eq!(memento_kind(&memento), Some("source-memento"));
        assert_eq!(memento_body(&memento), Some(&memento["body"]));
        assert_eq!(
            memento_body_field(&memento, "contractName"),
            Some(&memento["header"]["contractName"])
        );
        assert_eq!(
            memento_body_field(&memento, "source_cid"),
            Some(&memento["body"]["source_cid"])
        );
    }

    #[test]
    fn euf_inv_only_duplicate_names_are_conjoinable_not_load_errors() {
        let name = "decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion";
        let mut pool = MementoPool::default();

        pool.insert(
            "blake3-512:java".to_string(),
            make_inv_only_contract(name, 3),
        );
        pool.insert(
            "blake3-512:rust".to_string(),
            make_inv_only_contract(name, 4),
        );

        assert!(
            pool.load_errors.is_empty(),
            "same #euf# inv-only contracts are handled by consistency conjoin, not load errors: {:#?}",
            pool.load_errors
        );
        assert_eq!(
            pool.name_to_cid.get(name),
            Some(&"blake3-512:java".to_string())
        );
        assert!(pool.mementos.contains_key("blake3-512:java"));
        assert!(pool.mementos.contains_key("blake3-512:rust"));
    }

    #[test]
    fn non_euf_duplicate_names_remain_load_errors() {
        let name = "src/lib.rs::tests::same_name";
        let mut pool = MementoPool::default();

        pool.insert("blake3-512:a".to_string(), make_inv_only_contract(name, 1));
        pool.insert("blake3-512:b".to_string(), make_inv_only_contract(name, 2));

        assert!(
            pool.load_errors
                .iter()
                .any(|error| error.reason.contains("duplicate contract name")),
            "plain same-name duplicates must still be surfaced: {:#?}",
            pool.load_errors
        );
    }

    #[test]
    fn transitive_implication_chain_of_three() {
        let mut pool = MementoPool::default();

        // Insert P → Q and Q → R
        let p = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let q = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let r = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

        pool.insert("m1".to_string(), make_implication_memento(p, q));
        pool.insert("m2".to_string(), make_implication_memento(q, r));

        // Check P → R via transitivity
        let result = pool.can_implies(p, r);
        assert!(
            matches!(result, ImplicationResult::ProvenTransitive { .. }),
            "Expected transitive proof for P → R, got {:?}",
            result
        );
    }

    #[test]
    fn direct_implication_lookup() {
        let mut pool = MementoPool::default();

        let p = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let q = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

        pool.insert("m1".to_string(), make_implication_memento(p, q));

        let result = pool.can_implies(p, q);
        assert!(
            matches!(result, ImplicationResult::ProvenDirect { .. }),
            "Expected direct proof, got {:?}",
            result
        );
    }

    #[test]
    fn memento_pool_merge_preserves_effect_site_annotations() {
        let key = (
            "blake3-512:bundle".to_string(),
            "src/lib.rs".to_string(),
            42,
            "method:unwrap".to_string(),
        );
        let annotation = EffectSiteAnnotation {
            effect_kind: "panic-freedom".to_string(),
            file: "src/lib.rs".to_string(),
            line: 42,
            callee: "method:unwrap".to_string(),
            status: "residue".to_string(),
            category: "lock_poisoning_residue".to_string(),
            tier_to_close: "irreducible".to_string(),
            reason: "lock poisoning is runtime residue".to_string(),
            memento_cid: "blake3-512:annotation".to_string(),
            bundle_cid: "blake3-512:bundle".to_string(),
        };
        let mut left = MementoPool::default();
        let mut right = MementoPool::default();
        right
            .panic_effect_site_annotations
            .insert(key.clone(), annotation);

        left.merge(right);

        let merged = left
            .panic_effect_site_annotations
            .get(&key)
            .expect("merge must carry annotation index");
        assert_eq!(merged.effect_kind, "panic-freedom");
        assert_eq!(merged.status, "residue");
        assert!(left.load_errors.is_empty(), "{:#?}", left.load_errors);

        let original = EffectSiteAnnotation {
            memento_cid: "blake3-512:annotation-original".to_string(),
            ..merged.clone()
        };
        let duplicate = EffectSiteAnnotation {
            memento_cid: "blake3-512:annotation-duplicate".to_string(),
            ..merged.clone()
        };
        let mut left = MementoPool::default();
        left.panic_effect_site_annotations
            .insert(key.clone(), original);
        let mut right = MementoPool::default();
        right
            .panic_effect_site_annotations
            .insert(key.clone(), duplicate);

        left.merge(right);

        let kept = left
            .panic_effect_site_annotations
            .get(&key)
            .expect("original annotation must remain indexed");
        assert_eq!(kept.memento_cid, "blake3-512:annotation-original");
        assert!(
            left.load_errors
                .iter()
                .any(|error| error.reason.contains("[effect-site-annotation-duplicate]")),
            "duplicate merge must emit stable tagged load error: {:#?}",
            left.load_errors
        );
    }

    #[test]
    fn reflexive_implication_always_holds() {
        let pool = MementoPool::default();

        let p = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

        let result = pool.can_implies(p, p);
        assert!(
            matches!(result, ImplicationResult::ProvenReflexive),
            "Expected reflexive proof, got {:?}",
            result
        );
    }

    #[test]
    fn unknown_imputation_returns_unknown() {
        let pool = MementoPool::default();

        let p = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let q = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

        let result = pool.can_implies(p, q);
        assert!(
            matches!(result, ImplicationResult::Unknown),
            "Expected unknown, got {:?}",
            result
        );
    }

    // ---- PinInvariantMemento round-trip (real pool) ----

    fn make_pin_invariant_memento(
        cid: &str,
        function_cid: &str,
        target: &str,
        invariant: &str,
    ) -> Json {
        json!({
            "cid": cid,
            "envelope": {
                "signer": "ed25519:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "declaredAt": "2026-05-05T00:00:00Z",
                "signature": "ed25519:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            },
            "header": {
                "schemaVersion": "1",
                "kind": "pin-invariant",
                "cid": cid,
                "functionCid": function_cid,
                "pinnedTarget": target
            },
            "metadata": {
                "invariant": invariant
            }
        })
    }

    #[test]
    fn pin_invariant_insert_lookup_roundtrip() {
        let mut pool = MementoPool::default();
        let fc = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let m_cid = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".to_string();
        pool.insert(
            m_cid.clone(),
            make_pin_invariant_memento(&m_cid, fc, "pin", "0 <= state"),
        );
        let view = pool.lookup_pin_invariant(fc, "pin");
        assert!(view.is_some(), "expected Some after insert");
        let v = view.unwrap();
        assert_eq!(v.pinned_target, "pin");
        assert!(!v.invariant.is_empty());
        assert_eq!(v.function_cid, fc);
    }

    #[test]
    fn pin_invariant_cross_function_cid_mismatch() {
        let mut pool = MementoPool::default();
        let fc_a = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let fc_b = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let m_cid = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc".to_string();
        pool.insert(
            m_cid.clone(),
            make_pin_invariant_memento(&m_cid, fc_a, "pin", "0 <= state"),
        );
        // Same target "pin" but different function CID: should NOT match
        let view = pool.lookup_pin_invariant(fc_b, "pin");
        assert!(view.is_none(), "cross-function-CID lookup must return None");
    }

    #[test]
    fn pin_invariant_v11_flat_shape_roundtrip() {
        // v1.1 flat shape: no envelope wrapper, fields live in evidence.body.
        // This exercises the fallback path in memento_body_field that reads
        // from /evidence/body instead of /header and /metadata.
        let mut pool = MementoPool::default();
        let fc = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        let m_cid = "blake3-512:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
        let flat_memento = json!({
            "cid": m_cid,
            "evidence": {
                "kind": "pin-invariant",
                "body": {
                    "functionCid": fc,
                    "pinnedTarget": "pin",
                    "invariant": "state >= 0"
                }
            }
        });
        pool.insert(m_cid.to_string(), flat_memento);
        let view = pool.lookup_pin_invariant(fc, "pin");
        assert!(view.is_some(), "v1.1 flat memento must be found via lookup");
        let v = view.unwrap();
        assert_eq!(v.pinned_target, "pin");
        assert_eq!(v.invariant, "state >= 0");
        assert_eq!(v.function_cid, fc);
    }

    // ---- A precondition is an obligation, not a verified fact ----

    fn make_contract_memento(cid: &str, name: &str, pre: &Json, post: &Json) -> Json {
        // v1.1 flat shape: evidence.kind="contract", derived hashes in body.
        json!({
            "cid": cid,
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": name,
                    "pre": pre,
                    "post": post,
                    "preHash": compute_formula_cid(pre),
                    "postHash": compute_formula_cid(post),
                }
            }
        })
    }

    #[test]
    fn precondition_is_obligation_not_verified_fact() {
        // The missing-edge hole: indexing a contract's preHash into the
        // "verified formulas" map (formula_to_memento) makes Tier 0
        // `pool.verify(consumer_pre)` self-discharge — a callsite's consumer
        // precondition is satisfied merely by the callee DECLARING it. A
        // precondition is an obligation to discharge, never an established
        // fact. Only the post (and inv) are guarantees.
        let mut pool = MementoPool::default();
        let pre = json!({
            "kind": "atomic", "pred": "ge",
            "args": [{"kind":"var","name":"encoding"}, {"kind":"const","value":0}]
        });
        let post = json!({
            "kind": "atomic", "pred": "eq",
            "args": [{"kind":"var","name":"result"}, {"kind":"var","name":"value"}]
        });
        let m_cid =
            "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                .to_string();
        pool.insert(
            m_cid.clone(),
            make_contract_memento(&m_cid, "content_address", &pre, &post),
        );

        // A postcondition IS an established fact (the function guarantees it).
        assert!(
            pool.verify(&post).is_some(),
            "a contract's post must remain a verified fact"
        );

        // A bare precondition must NOT count as verified — else any callsite's
        // consumer pre self-discharges at Tier 0 and the missing edge hides.
        assert!(
            pool.verify(&pre).is_none(),
            "a contract's bare pre must NOT be treated as a verified fact"
        );
    }
}
