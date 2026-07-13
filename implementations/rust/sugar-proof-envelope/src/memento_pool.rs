// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Pipeline types. Mirrors implementations/cpp/.../verifier/types.hpp.
//
// Shape compatibility is normalized at the proof-envelope boundary. The pool
// stores typed member views, not raw member envelope JSON trees.

use std::collections::BTreeMap;
use std::fmt;

pub use crate::{AnchoredMember, AtomCid, ContractBodyCid, MemberKind, MementoCid, StoredMember};
use serde_json::Value as Json;

fn contract_body_pointer(member: &StoredMember) -> Option<ContractBodyCid> {
    member
        .field("bodyCid")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .and_then(|s| ContractBodyCid::try_parse(s.to_string()).ok())
}

#[derive(Debug, Clone)]
pub struct LoadError {
    pub proof_path: String,
    pub reason: String,
}

/// Which side of the vendor/consumer conversation a speaker is on. This is
/// the ONLY thing the consistency labeling ever reads: a `Vendor` speaker's
/// members become the VENDOR-FACT half of a report row, a `Consumer`
/// speaker's members become the YOUR-FACT half.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum SpeakerRole {
    Vendor,
    Consumer,
}

/// WHO SAID a pool member (#3807/#3812): the identity stamped against each
/// member CID at the moment its bytes enter the pool, by the loader (or
/// utterance verb) that actually knows where they came from.
///
/// This is the CONSTRUCTED attribution stamp: instead of inferring "is this
/// a vendor fact?" from callsite position (first()), authorship heuristics
/// in the report renderer, or a buffer relabel in the editor, the intake
/// that KNOWS who spoke a member records it here, once, at insert time.
/// Every later consumer (consistency partitioning, report rendering) reads
/// this stamp instead of re-deriving it. Minimal by design: no
/// authentication yet, just a label and a role.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Speaker {
    /// Human-readable identity label. For path-walk loads this is the
    /// `.proof` bundle path; for `ProofBytes` loads the caller's label; for
    /// utterance verbs whatever identity the caller supplied. Not a
    /// MementoCid: some intakes supply a human label rather than a bundle
    /// CID.
    pub id: String,
    /// `Vendor` when the member arrived from a staged vendor bundle
    /// (`.sugar/imports/**`) or a vendor-role utterance; `Consumer` when it
    /// is the consumer's own project output (own bundle, scratch overlay,
    /// self-check fixture, consumer-role utterance).
    pub role: SpeakerRole,
}

impl Speaker {
    pub fn vendor(id: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            role: SpeakerRole::Vendor,
        }
    }

    pub fn consumer(id: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            role: SpeakerRole::Consumer,
        }
    }
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

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct SourcePath(String);

impl SourcePath {
    pub fn new(path: impl Into<String>) -> Result<Self, String> {
        let path = path.into();
        if path.is_empty() {
            return Err("source path must not be empty".to_string());
        }
        Ok(Self(path))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for SourcePath {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl fmt::Display for SourcePath {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct SourceLine(usize);

impl SourceLine {
    pub fn new(line: usize) -> Self {
        Self(line)
    }

    pub fn as_usize(self) -> usize {
        self.0
    }
}

impl fmt::Display for SourceLine {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct SourceSymbol(String);

impl SourceSymbol {
    pub fn new(symbol: impl Into<String>) -> Result<Self, String> {
        let symbol = symbol.into();
        if symbol.is_empty() {
            return Err("source symbol must not be empty".to_string());
        }
        Ok(Self(symbol))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for SourceSymbol {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl fmt::Display for SourceSymbol {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct BundleScopedCallsiteKey {
    bundle: MementoCid,
    file: SourcePath,
    line: SourceLine,
    symbol: SourceSymbol,
}

impl BundleScopedCallsiteKey {
    pub fn new(
        bundle: MementoCid,
        file: SourcePath,
        line: SourceLine,
        symbol: SourceSymbol,
    ) -> Self {
        Self {
            bundle,
            file,
            line,
            symbol,
        }
    }

    pub fn from_parts(
        bundle: MementoCid,
        file: impl Into<String>,
        line: usize,
        symbol: impl Into<String>,
    ) -> Result<Self, String> {
        Ok(Self::new(
            bundle,
            SourcePath::new(file)?,
            SourceLine::new(line),
            SourceSymbol::new(symbol)?,
        ))
    }

    pub fn bundle(&self) -> &MementoCid {
        &self.bundle
    }

    pub fn file(&self) -> &SourcePath {
        &self.file
    }

    pub fn line(&self) -> SourceLine {
        self.line
    }

    pub fn symbol(&self) -> &SourceSymbol {
        &self.symbol
    }
}

impl fmt::Display for BundleScopedCallsiteKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}:{}:{}:{}",
            self.bundle, self.file, self.line, self.symbol
        )
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ResolvedContractBody(Json);

impl ResolvedContractBody {
    pub fn as_json(&self) -> &Json {
        &self.0
    }

    pub fn into_json(self) -> Json {
        self.0
    }

    pub fn get(&self, key: &str) -> Option<&Json> {
        self.0.get(key)
    }

    pub fn is_object(&self) -> bool {
        self.0.is_object()
    }
}

#[derive(Debug)]
pub struct VerifiedContract<'pool> {
    cid: MementoCid,
    member: &'pool StoredMember,
    body: Option<ResolvedContractBody>,
}

impl<'pool> VerifiedContract<'pool> {
    pub fn cid(&self) -> &MementoCid {
        &self.cid
    }

    pub fn member(&self) -> &'pool StoredMember {
        self.member
    }

    pub fn body(&self) -> Option<&Json> {
        self.body.as_ref().map(ResolvedContractBody::as_json)
    }

    pub fn resolved_body(&self) -> Option<&ResolvedContractBody> {
        self.body.as_ref()
    }
}

#[derive(Debug, Default, Clone)]
pub struct MementoPool {
    /// Canonical sugar.enumerate question CID -> response. This cache has no
    /// invalidation API: it is valid exactly for the lifetime of the RPC
    /// client that owns the pool and disappears when that client is dropped.
    rpc_questions: BTreeMap<MementoCid, Json>,
    /// CID -> normalized typed memento storage.
    /// The memento IS the verification. To verify something is to find
    /// its memento in this map.
    pub mementos: BTreeMap<MementoCid, StoredMember>,
    /// Atom CID -> flat atom bytes from the proof catalog.
    ///
    /// Leaves live here exactly once. Body graphs and mementos point to these
    /// CIDs instead of embedding semantic leaves inline.
    pub atoms: BTreeMap<AtomCid, Vec<u8>>,
    /// Body/composition CID -> pointer-only body bytes from the proof catalog.
    ///
    /// Contract mementos name, bind, and locate a body by `bodyCid`; the body
    /// map stores the composition graph that bottoms out in `atoms`.
    pub body: BTreeMap<ContractBodyCid, Vec<u8>>,
    /// Formula CID -> memento CID. Index for fast formula lookup.
    /// The hash IS the boundary: systems don't exchange formulas,
    /// they exchange hashes. This index lets us find the memento
    /// for a given formula hash without scanning all mementos.
    pub formula_to_memento: BTreeMap<String, MementoCid>,
    /// sourceSymbol (IR ctor name) -> bridge memento CID.
    ///
    /// The bridge envelope itself lives exactly once in `mementos`; this index
    /// is a pointer into that verified pool entry.
    pub bridges_by_symbol: BTreeMap<String, MementoCid>,
    /// `(bundle_cid, file, line, sourceSymbol)` -> bridge memento CID.
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
    bridges_by_callsite: BTreeMap<BundleScopedCallsiteKey, MementoCid>,
    /// `(bundle_cid, file, line, callee)` -> panic-freedom annotation memento.
    ///
    /// Effect-site annotations are diagnostic proof mementos, not discharge
    /// evidence. They annotate a specific unproven/residue effect occurrence
    /// after `prove --json` has produced its panic census. Bundle scoping is
    /// load-bearing: paths like `src/lib.rs` and call symbols collide across
    /// packages, so the annotation must join only to the proof bundle that
    /// produced the row it describes.
    pub panic_effect_site_annotations:
        BTreeMap<(MementoCid, String, usize, String), EffectSiteAnnotation>,
    /// sourceSymbol -> the `.proof` bundle CID the bridge memento was loaded
    /// from. Lets resolve_target enforce the self-pinned (no `targetProofCid`)
    /// case: the target contract must be a co-member of this bundle. Keyed by
    /// sourceSymbol to match `bridges_by_symbol` (same last-writer-wins key).
    pub bridge_self_bundle_by_symbol: BTreeMap<String, MementoCid>,
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
    pub bundle_members: BTreeMap<MementoCid, std::collections::BTreeSet<MementoCid>>,
    /// THE ATTRIBUTION MAP (#3807/#3812): member CID -> `Speaker`. Stamped
    /// at insert time by the intake that knows who spoke a member's bytes
    /// (`load_all_proofs`, the utterance verbs `speak_*`, the daemon's
    /// overlay/base-pool loads, or a test fixture's explicit
    /// `attribute_member_for_tests`). A side map, not a `StoredMember`
    /// field: attribution is a POOL-INTAKE fact ("who handed me these
    /// bytes"), not part of the memento's own signed content.
    pub member_speaker: BTreeMap<MementoCid, Speaker>,
    pub load_errors: Vec<LoadError>,
    /// Contract CID -> contract name (indexed during load)
    pub cid_to_name: BTreeMap<MementoCid, String>,
    /// Contract name -> CID (reverse index)
    pub name_to_cid: BTreeMap<String, MementoCid>,
    /// Contract name -> body CID pointer carried by the contract memento.
    ///
    /// `name_to_cid` keeps the resolver-facing memento/member identity. This
    /// table follows the memento's body pointer so semantic diff can compare
    /// composed pointer graphs without deriving them sideways from the envelope.
    pub name_to_body_cid: BTreeMap<String, ContractBodyCid>,

    // ---- Opacity discharge indexes (issue #384 B.5) ----
    //
    // These maps are indexed during `insert()` when a memento of the
    // corresponding discharge kind is loaded. The substrate's
    // `compose_function_contracts_checked` queries these via the
    // `OpacityMementoLookup` impl below.
    /// loopCid (from header.loopCid of a LoopInvariantMemento) ->
    /// memento CID. Populated when a "loop-invariant" kind memento is
    /// inserted. Spec: protocol/specs/2026-05-05-loop-invariant-memento.md
    pub loop_cid_to_memento: BTreeMap<String, MementoCid>,

    /// tryCid (from header.tryCid of a TryBranchMemento) -> memento CID.
    /// Populated when a "try-branch" kind memento is inserted.
    /// Spec: protocol/specs/2026-05-05-try-branch-memento.md
    pub try_cid_to_memento: BTreeMap<String, MementoCid>,

    /// bodyFnCid (from header.bodyFnCid of a ClosureBindingMemento) ->
    /// memento CID. Populated when a "closure-binding" kind memento is
    /// inserted. Spec: protocol/specs/2026-05-05-closure-binding-memento.md
    pub body_fn_cid_to_memento: BTreeMap<String, MementoCid>,

    /// AliasingMemento discharge index: (formal_a, formal_b) ->
    /// memento CID. Populated when an "aliasing-memento" kind memento is
    /// inserted. The key is the sorted pair of formal parameter names.
    pub aliasing_pair_to_memento: BTreeMap<(String, String), MementoCid>,

    /// Composite key "functionCid\x00target" -> memento CID. Populated
    /// when a "pin-invariant" kind memento is inserted. The composite
    /// key ensures the memento is anchored to both the function contract
    /// and the pinned parameter name.
    /// Spec: protocol/specs/2026-05-05-pin-invariant-memento.md
    pub pin_invariant_to_memento: BTreeMap<String, MementoCid>,
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
    pub fn rpc_question(&self, question_cid: &MementoCid) -> Option<&Json> {
        self.rpc_questions.get(question_cid)
    }

    pub fn remember_rpc_question(&mut self, question_cid: MementoCid, answer: Json) {
        self.rpc_questions.entry(question_cid).or_insert(answer);
    }

    /// The fundamental verification operation: look up a formula by its
    /// content hash. The memento IS the verification; if found, the
    /// formula is verified. No solver is invoked.
    ///
    /// Returns the memento that verifies this formula.
    pub fn verify_by_hash(&self, formula_cid: &str) -> Option<&StoredMember> {
        self.formula_to_memento
            .get(formula_cid)
            .and_then(|memento_cid| self.mementos.get(memento_cid))
    }

    /// Compute the CID for a formula JSON node, then look it up.
    /// The canonicalization + hash IS the boundary between systems.
    pub fn verify(&self, formula: &Json) -> Option<&StoredMember> {
        let cid = compute_formula_cid(formula);
        self.verify_by_hash(&cid)
    }

    /// Return a verified stored member by CID without exposing the pool map at
    /// consumer call sites.
    pub fn stored_member<'a>(&'a self, cid: &MementoCid) -> Option<&'a StoredMember> {
        self.mementos.get(cid)
    }

    /// Attribute a member CID to a speaker (#3807/#3812). Called by the
    /// intake that knows who spoke the member's bytes. IDEMPOTENT by CID:
    /// first writer wins, so re-speaking an already-attributed member is a
    /// no-op, and a later `merge()` from another pool preserves the FIRST
    /// pool's stamp on collision (same policy as every other index).
    pub fn attribute_member(&mut self, cid: MementoCid, speaker: Speaker) {
        self.member_speaker.entry(cid).or_insert(speaker);
    }

    /// Test/fixture-only attribution stamping by CID string, so consistency
    /// and report tests can construct vendor/consumer member sets without
    /// going through the on-disk `.proof` loader.
    #[doc(hidden)]
    pub fn attribute_member_for_tests(&mut self, cid: &str, role: SpeakerRole, id: &str) {
        if let Ok(cid) = MementoCid::try_parse(cid.to_string()) {
            self.attribute_member(
                cid,
                Speaker {
                    id: id.to_string(),
                    role,
                },
            );
        }
    }

    /// Look up who spoke a member, if attribution was stamped at intake.
    pub fn member_speaker(&self, cid: &MementoCid) -> Option<&Speaker> {
        self.member_speaker.get(cid)
    }

    /// Was this member CID spoken by a VENDOR-role speaker (staged
    /// `.sugar/imports/**` bundle or vendor utterance)? Members with no
    /// recorded attribution (e.g. pool built entirely by
    /// `insert_unanchored_for_tests` fixtures that never call
    /// `attribute_member_for_tests`) are treated as CONSUMER -- the safe
    /// default that reproduces pre-#3807 behavior (everything conjoined as
    /// the client's own fact) for callers that never opted into attribution.
    pub fn is_vendor_member(&self, cid: &str) -> bool {
        MementoCid::try_parse(cid.to_string())
            .ok()
            .and_then(|cid| self.member_speaker.get(&cid))
            .is_some_and(|speaker| speaker.role == SpeakerRole::Vendor)
    }

    /// Iterate verified members of one kind in pool CID order.
    pub fn members_by_kind(
        &self,
        kind: MemberKind,
    ) -> impl Iterator<Item = (&MementoCid, &StoredMember)> + '_ {
        self.mementos
            .iter()
            .filter(move |(_, member)| member.kind() == kind)
    }

    pub fn member_count_by_kind(&self, kind: MemberKind) -> usize {
        self.members_by_kind(kind).count()
    }

    pub fn has_member_kind(&self, kind: MemberKind) -> bool {
        self.members_by_kind(kind).next().is_some()
    }

    pub fn contract_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)> + '_ {
        self.members_by_kind(MemberKind::Contract)
    }

    pub fn bridge_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)> + '_ {
        self.members_by_kind(MemberKind::Bridge)
    }

    pub fn implication_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)> + '_ {
        self.members_by_kind(MemberKind::Implication)
    }

    pub fn witness_memento_members(
        &self,
    ) -> impl Iterator<Item = (&MementoCid, &StoredMember)> + '_ {
        self.members_by_kind(MemberKind::WitnessMemento)
    }

    pub fn source_memento_members(
        &self,
    ) -> impl Iterator<Item = (&MementoCid, &StoredMember)> + '_ {
        self.members_by_kind(MemberKind::SourceMemento)
    }

    pub fn plan_memento_members(&self) -> impl Iterator<Item = (&MementoCid, &StoredMember)> + '_ {
        self.members_by_kind(MemberKind::PlanMemento)
    }

    /// Resolve a contract member's semantic body without exposing the legacy
    /// compatibility accessor name to migrated consumers.
    pub fn contract_body_for_member(&self, member: &StoredMember) -> Option<Json> {
        self.resolved_contract_body(member)
    }

    /// Return a verified contract view by CID. The CID selects the stored
    /// contract member; the optional body is resolved through the pool-owned
    /// body/atom graph instead of by raw envelope traversal at call sites.
    pub fn verified_contract_by_cid<'a>(
        &'a self,
        cid: &MementoCid,
    ) -> Option<VerifiedContract<'a>> {
        let member = self.mementos.get(cid)?;
        if member.kind() != MemberKind::Contract {
            return None;
        }
        Some(VerifiedContract {
            cid: cid.clone(),
            member,
            body: self
                .resolved_contract_body(member)
                .map(ResolvedContractBody),
        })
    }

    /// Return every verified contract member with its resolved semantic body,
    /// preserving the pool's CID ordering. Enumeration uses this instead of
    /// iterating raw storage and re-checking member kind at each call site.
    pub fn contract_members_with_bodies(&self) -> impl Iterator<Item = (&MementoCid, Json)> + '_ {
        self.mementos.iter().filter_map(|(cid, member)| {
            if member.kind() != MemberKind::Contract {
                return None;
            }
            let body = self
                .resolved_contract_body(member)
                .filter(|v| v.is_object())?;
            Some((cid, body))
        })
    }

    /// Return a verified contract body by CID. `None` means the CID is absent,
    /// present with a non-contract kind, or carries no object body.
    pub fn contract_body_by_cid(&self, cid: &MementoCid) -> Option<Json> {
        self.verified_contract_by_cid(cid)?
            .resolved_body()
            .filter(|body| body.is_object())
            .cloned()
            .map(ResolvedContractBody::into_json)
    }

    /// Return the target contract's formal list through the same body-resolution
    /// path used by verifier callsite resolution.
    pub fn contract_formals_by_cid(&self, cid: &MementoCid) -> Option<Vec<Json>> {
        self.contract_body_by_cid(cid)?
            .get("formals")?
            .as_array()
            .map(|items| items.to_vec())
    }

    /// Return the verified bridge member indexed for a source symbol.
    ///
    /// Slice-4 callsite enumeration uses this typed accessor name so the audit
    /// can distinguish migrated bridge consumers from the older generic bridge
    /// JSON accessors that later slices still own.
    pub fn bridge_member_for_symbol<'a>(&'a self, source_symbol: &str) -> Option<&'a StoredMember> {
        self.bridges_by_symbol
            .get(source_symbol)
            .and_then(|memento_cid| self.mementos.get(memento_cid))
    }

    /// Iterate verified bridge members in the same order as the source-symbol
    /// bridge index, preserving the indexed symbol for fallback metadata.
    pub fn bridge_members_by_indexed_symbol(
        &self,
    ) -> impl Iterator<Item = (&str, &StoredMember)> + '_ {
        self.bridges_by_symbol
            .iter()
            .filter_map(|(source_symbol, memento_cid)| {
                self.mementos
                    .get(memento_cid)
                    .map(|member| (source_symbol.as_str(), member))
            })
    }

    /// Return the verified bridge member indexed for a callsite-scoped key.
    pub fn bridge_member_for_callsite_key<'a>(
        &'a self,
        key: &BundleScopedCallsiteKey,
    ) -> Option<&'a StoredMember> {
        self.bridges_by_callsite
            .get(key)
            .and_then(|memento_cid| self.mementos.get(memento_cid))
    }

    /// Iterate verified bridge members for one bundle/callee pair.
    pub fn bridge_members_for_callsite_bundle_and_callee<'a>(
        &'a self,
        bundle: &'a MementoCid,
        callee: &'a str,
    ) -> impl Iterator<Item = &'a StoredMember> + 'a {
        self.bridges_by_callsite
            .iter()
            .filter_map(move |(key, bridge_cid)| {
                if key.bundle() != bundle || key.symbol().as_str() != callee {
                    return None;
                }
                self.mementos.get(bridge_cid)
            })
    }

    /// Index an already-stored bridge member by source symbol.
    pub fn insert_bridge_by_symbol(
        &mut self,
        source_symbol: impl Into<String>,
        bridge_cid: MementoCid,
        _bridge_env: Json,
    ) {
        #[cfg(test)]
        if !self.mementos.contains_key(&bridge_cid) {
            self.insert_unanchored_for_tests(bridge_cid.clone(), _bridge_env.clone());
        }
        self.bridges_by_symbol
            .insert(source_symbol.into(), bridge_cid);
    }

    /// Index an already-stored bridge member by exact callsite key.
    pub fn insert_bridge_by_callsite(
        &mut self,
        key: BundleScopedCallsiteKey,
        bridge_cid: MementoCid,
        _bridge_env: Json,
    ) {
        #[cfg(test)]
        if !self.mementos.contains_key(&bridge_cid) {
            self.insert_unanchored_for_tests(bridge_cid.clone(), _bridge_env.clone());
        }
        self.bridges_by_callsite.insert(key, bridge_cid);
    }

    pub fn index_bridge_by_callsite_if_absent(
        &mut self,
        key: BundleScopedCallsiteKey,
        bridge_cid: MementoCid,
    ) {
        self.bridges_by_callsite.entry(key).or_insert(bridge_cid);
    }

    /// Return the semantic contract body for a loaded contract memento.
    ///
    /// Modern `.proof` catalogs store formula leaves in `atoms` and body
    /// composition in the catalog `body` map. The contract memento itself
    /// carries only binding/header metadata plus `bodyCid`. Callers that need
    /// semantic slots (`pre`, `post`, `inv`) must resolve through the pool so
    /// the graph, not legacy inline fields, is the source of truth.
    fn resolved_contract_body(&self, member: &StoredMember) -> Option<Json> {
        let mut body = member.body()?.as_object()?.clone();
        if let Some(body_cid) = contract_body_pointer(member) {
            for (slot, formula) in self.resolve_body_formula_slots(&body_cid)? {
                body.insert(slot, formula);
            }
        }
        Some(Json::Object(body))
    }

    fn resolve_body_formula_slots(
        &self,
        body_cid: &ContractBodyCid,
    ) -> Option<BTreeMap<String, Json>> {
        let body_bytes = self.body.get(body_cid)?;
        let body_doc: Json = serde_json::from_slice(body_bytes).ok()?;
        let slots = body_doc.pointer("/body")?.as_object()?;
        let mut resolved = BTreeMap::new();
        for (slot, slot_memento) in slots {
            let atom_cid = slot_memento
                .get("atomCid")
                .and_then(|value| value.as_str())
                .and_then(|raw| AtomCid::try_parse(raw.to_string()).ok())?;
            let atom_bytes = self.atoms.get(&atom_cid)?;
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
    pub fn verify_implication(
        &self,
        antecedent_cid: &str,
        consequent_cid: &str,
    ) -> Option<&StoredMember> {
        // The proof of `P → Q` is the implication memento that links them, not
        // the presence of P or Q in `formula_to_memento`. (P, the antecedent,
        // is no longer indexed there at all -- it is an assumption, not a
        // fact.) Scan for an implication memento with these exact endpoints.
        // Shape-agnostic: under v1.2 these references live in the
        // metadata; under v1.1 they live in evidence.body.
        for member in self.mementos.values() {
            if member.kind() == MemberKind::Implication {
                let ant = member.field("antecedentHash").and_then(|v| v.as_str());
                let con = member.field("consequentHash").and_then(|v| v.as_str());
                if ant == Some(antecedent_cid) && con == Some(consequent_cid) {
                    return Some(member);
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
        for member in self.mementos.values() {
            if member.kind() == MemberKind::Implication {
                if let (Some(ant), Some(con)) = (
                    member.field("antecedentHash").and_then(|v| v.as_str()),
                    member.field("consequentHash").and_then(|v| v.as_str()),
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
                memento_cid: memento.cid().to_string(),
            };
        }

        // 3. Transitive implication
        if let Some(path) = self.implies_transitive(antecedent_cid, consequent_cid) {
            return ImplicationResult::ProvenTransitive { path };
        }

        ImplicationResult::Unknown
    }

    /// Insert an anchored memento into the pool and index it by formula hash.
    ///
    /// The .proof protocol IS the cache: storing a memento IS caching the
    /// verification result. Anchoring is an ingress obligation; `insert` is an
    /// indexing primitive and only accepts a member whose catalog key was
    /// re-derived from its contents and whose member signature has been checked.
    pub fn insert(&mut self, member: AnchoredMember) {
        let (memento_cid, member) = member
            .into_stored_member()
            .expect("anchored member must carry a known member kind");
        self.insert_anchored_parts(memento_cid, member);
    }

    /// Insert an anchored memento after a load-time indexer inspects its typed view.
    ///
    /// This keeps `AnchoredMember` as the production ingress witness while letting
    /// load_all_proofs validate and index by `StoredMember` without normalizing the
    /// same envelope twice. Returning `None` from the callback skips insertion.
    pub fn try_insert_anchored_with<T, F>(
        &mut self,
        member: AnchoredMember,
        before_insert: F,
    ) -> Result<Option<T>, crate::MemberError>
    where
        F: FnOnce(&MementoCid, &StoredMember, &mut Self) -> Option<T>,
    {
        let (memento_cid, member) = member.into_stored_member()?;
        let Some(value) = before_insert(&memento_cid, &member, self) else {
            return Ok(None);
        };
        self.insert_anchored_parts(memento_cid, member);
        Ok(Some(value))
    }

    /// Test-only fixture helper: insert a raw envelope without signature
    /// anchoring. Not `#[cfg(test)]` (part of #3774 warm-daemon slice) so
    /// sugar-linkerd's `tests/prove_consistency.rs` integration test can build
    /// the identical fixture shape this crate's own consistency tests use,
    /// rather than duplicating envelope-shape knowledge in a second crate.
    #[doc(hidden)]
    pub fn insert_unanchored_for_tests(&mut self, memento_cid: MementoCid, envelope: Json) {
        let member = StoredMember::from_envelope(memento_cid.clone(), &envelope)
            .expect("test member must carry a known member kind");
        self.insert_verified_member_for_tests(memento_cid, member);
    }

    #[doc(hidden)]
    pub fn insert_verified_member_for_tests(
        &mut self,
        memento_cid: MementoCid,
        member: StoredMember,
    ) {
        self.insert_anchored_parts(memento_cid, member);
    }

    fn insert_anchored_parts(&mut self, memento_cid: MementoCid, member: StoredMember) {
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
        let formula_hashes: Vec<String> = ["postHash", "invHash"]
            .iter()
            .filter_map(|field| {
                member
                    .field(field)
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
            })
            .collect();
        let indexed_memento_cid = memento_cid.clone();
        self.mementos.insert(memento_cid, member);
        let memento_cid = indexed_memento_cid;
        for hash in formula_hashes {
            self.formula_to_memento.insert(hash, memento_cid.clone());
        }

        // Index by contract name for cross-kit resolution.
        // Gate on memento kind: only contract-shaped mementos carry a
        // contractName/name that's a stable cross-kit identifier. Other
        // kinds (implication, etc.) sometimes have a header.name field
        // but it's not a contract identity, so indexing them would
        // mis-resolve call edges.
        let is_contract = self
            .mementos
            .get(&memento_cid)
            .is_some_and(|member| member.kind() == MemberKind::Contract);
        if is_contract {
            let member_for_name = self.mementos.get(&memento_cid);
            let name = member_for_name
                .and_then(|member| {
                    member
                        .field("contractName")
                        .or_else(|| member.field("name"))
                })
                .and_then(|v| v.as_str());

            if let Some(n) = name {
                let n = n.to_string();
                let body_cid = member_for_name.and_then(contract_body_pointer);

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
                        let new_member = self.mementos.get(&memento_cid);
                        let existing_member = self.mementos.get(&existing);
                        let new_has_pre = new_member
                            .and_then(|member| member.field("preHash"))
                            .is_some();
                        let existing_has_pre = existing_member
                            .and_then(|member| member.field("preHash"))
                            .is_some();
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
                        } else if is_euf_inv_only_conjoin_duplicate(&n, existing_member, new_member)
                        {
                            // Same-name #euf# inv-only contracts are the
                            // intentional cross-proof conjoin case. Keep the
                            // first name index for symbol lookup, keep both
                            // mementos in the pool, and let
                            // consistency::verify_consistency conjoin them.
                        } else if same_canonical_contract_cid(existing_member, new_member) {
                            // Same behavior, different member envelope. A
                            // vendor's staged .proof and a consumer's own
                            // re-mint of the identical source (e.g. the same
                            // function imported under a different call
                            // surface, at a different absolute path, or with
                            // a different source span offset) hash to two
                            // distinct member-envelope CIDs even though the
                            // contract's own canonical `header.cid` -- the
                            // name-stripped behavior identity -- is
                            // byte-identical. That is cosmetic drift (file
                            // path, source span, bridge-source phrasing), not
                            // a genuine collision: don't poison the run with a
                            // LoadError over it.
                        } else {
                            // Same tier (both pre-bearing or both post-only): genuine collision.
                            self.load_errors.push(LoadError {
                                proof_path: memento_cid.to_string(),
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

        // Raw class-shape payload boundary: `classShapes` is IR/report data
        // carried inside a typed contract member, not a member envelope. No
        // typed class-shape model owns it yet, so the pool indexes the payload
        // as JSON while keeping member-envelope access typed.
        let class_shapes_to_index: Vec<Json> = if let Some(member) = self.mementos.get(&memento_cid)
        {
            if member.kind() == MemberKind::Contract {
                if let Some(body) = member.body() {
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
        // StoredMember::kind/field cover both v1.1 flat (evidence.body.*)
        // and v1.2 layered (header.*) shapes at this pool-owned boundary.
        // The `.map(str::to_string)` at each field lookup converts the
        // borrowed &str to an owned String before the mutable index entry,
        // avoiding a simultaneous shared+mutable borrow on self.
        let kind = self.mementos.get(&memento_cid).map(|member| member.kind());
        match kind {
            Some(MemberKind::LoopInvariant) => {
                // header.loopCid (v1.2) or evidence.body.loopCid (v1.1)
                if let Some(loop_cid) = self
                    .mementos
                    .get(&memento_cid)
                    .and_then(|member| member.field("loopCid"))
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                {
                    self.loop_cid_to_memento
                        .entry(loop_cid)
                        .or_insert(memento_cid.clone());
                }
            }
            Some(MemberKind::TryBranch) => {
                // header.tryCid (v1.2) or evidence.body.tryCid (v1.1)
                if let Some(try_cid) = self
                    .mementos
                    .get(&memento_cid)
                    .and_then(|member| member.field("tryCid"))
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                {
                    self.try_cid_to_memento
                        .entry(try_cid)
                        .or_insert(memento_cid.clone());
                }
            }
            Some(MemberKind::ClosureBinding) => {
                // header.bodyFnCid (v1.2) or evidence.body.bodyFnCid (v1.1)
                if let Some(body_fn_cid) = self
                    .mementos
                    .get(&memento_cid)
                    .and_then(|member| member.field("bodyFnCid"))
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                {
                    self.body_fn_cid_to_memento
                        .entry(body_fn_cid)
                        .or_insert(memento_cid.clone());
                }
            }
            Some(MemberKind::AliasingMemento) => {
                // header.formal_a and header.formal_b (v1.2) or evidence.body.formal_a/formal_b (v1.1)
                // Index by the sorted (formal_a, formal_b) pair. Convert to owned
                // Strings before the mutable entry borrow.
                let formal_a = self
                    .mementos
                    .get(&memento_cid)
                    .and_then(|member| member.field("formal_a"))
                    .and_then(|v| v.as_str())
                    .map(str::to_string);
                let formal_b = self
                    .mementos
                    .get(&memento_cid)
                    .and_then(|member| member.field("formal_b"))
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
            Some(MemberKind::PinInvariant) => {
                // header.functionCid + header.pinnedTarget -> composite key
                let function_cid = self
                    .mementos
                    .get(&memento_cid)
                    .and_then(|member| member.field("functionCid"))
                    .and_then(|v| v.as_str())
                    .map(str::to_string);
                let target = self
                    .mementos
                    .get(&memento_cid)
                    .and_then(|member| member.field("pinnedTarget"))
                    .and_then(|v| v.as_str())
                    .map(str::to_string);
                if let (Some(fc), Some(t)) = (function_cid, target) {
                    let key = format!("{}\x00{}", fc, t);
                    self.pin_invariant_to_memento
                        .entry(key)
                        .or_insert(memento_cid.clone());
                }
            }
            Some(MemberKind::AssertionSurfaceMemento)
            | Some(MemberKind::Authority)
            | Some(MemberKind::Bridge)
            | Some(MemberKind::Contract)
            | Some(MemberKind::EffectSiteAnnotation)
            | Some(MemberKind::FactoryWalkMemento)
            | Some(MemberKind::Implication)
            | Some(MemberKind::LibrarySugarBindingEntry)
            | Some(MemberKind::PlanMemento)
            | Some(MemberKind::ProofRun)
            | Some(MemberKind::SourceMemento)
            | Some(MemberKind::StageReceipt)
            | Some(MemberKind::Witness)
            | Some(MemberKind::WitnessMemento)
            | None => {}
        }
    }

    /// Sub-formula composition: walk the formula DAG and return all
    /// sub-formula CIDs that have mementos in the pool. If P is verified
    /// and we need to prove P ∧ Q, this returns P's CID so the solver
    /// can focus on Q.
    pub fn find_verified_subformulas(&self, formula: &Json) -> Vec<(String, &StoredMember)> {
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
                        proof_path: v.to_string(),
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
        for (k, v) in other.member_speaker {
            self.member_speaker.entry(k).or_insert(v);
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
                            proof_path: v.to_string(),
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
    existing_member: Option<&StoredMember>,
    new_member: Option<&StoredMember>,
) -> bool {
    name.contains("#euf#")
        && existing_member.is_some_and(is_inv_only_consistency_contract)
        && new_member.is_some_and(is_inv_only_consistency_contract)
}

/// True when two contract members carry the same canonical, name-stripped
/// behavior CID (`header.cid`) despite hashing to different member-envelope
/// CIDs. The member-envelope CID also folds in cosmetic authoring metadata
/// (source file path, source span, bridge-source call-surface phrasing) that
/// legitimately differs between a vendor's staged `.proof` and a consumer's
/// own re-mint of the identical function -- so two mementos can disagree on
/// envelope CID while agreeing, byte for byte, on behavior. Comparing
/// `header.cid` is the doctrine-correct check: same behavior, same CID.
fn same_canonical_contract_cid(
    existing_member: Option<&StoredMember>,
    new_member: Option<&StoredMember>,
) -> bool {
    let is_contract = |m: &StoredMember| m.kind() == MemberKind::Contract;
    let canonical_cid = |m: &StoredMember| -> Option<String> {
        m.field("cid").and_then(Json::as_str).map(str::to_string)
    };
    match (existing_member, new_member) {
        (Some(existing), Some(new)) => {
            is_contract(existing)
                && is_contract(new)
                && canonical_cid(existing).is_some()
                && canonical_cid(existing) == canonical_cid(new)
        }
        _ => false,
    }
}

fn is_inv_only_consistency_contract(member: &StoredMember) -> bool {
    if member.kind() != MemberKind::Contract {
        return false;
    }
    let Some(body) = member.body() else {
        return false;
    };
    let has_inv = body.get("inv").is_some()
        || body.get("invariant").is_some()
        || member.field("invHash").is_some();
    let has_pre = body.get("pre").is_some()
        || body.get("precondition").is_some()
        || member.field("preHash").is_some();
    let has_post = body.get("post").is_some()
        || body.get("postcondition").is_some()
        || member.field("postHash").is_some();
    has_inv && !has_pre && !has_post
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
