// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::HashMap;

use thiserror::Error;

use super::primitives::ComposeError;
use super::types::{Boundary, Cid, Contract, Dialect, DomainClaim, DomainKind, Input, Term};

/// Values that have stable JCS-canonical bytes and can therefore be addressed.
///
/// This is primitive 1's input contract: `address` canonicalizes the structure
/// and hashes the bytes with BLAKE3-512. Implementations in this module use
/// `sugar-canonicalizer`'s JCS encoder and hash helper.
pub trait Canonical {
    /// Return the canonical byte representation used for content addressing.
    ///
    /// The bytes are the durable, signer-independent identity of the value.
    /// For function contracts this delegates to the stored canonical bytes
    /// already carried by `FunctionContractMemento`.
    fn canonical_bytes(&self) -> Vec<u8>;
}

/// Content-addressed retrieval by CID.
///
/// This is primitive 2, `resolve`: reverse an `address` by asking a catalog
/// for the bytes currently stored under a CID.
pub trait Catalog {
    /// Return the canonical bytes stored at `cid`, or `None` when absent.
    fn get(&self, cid: &Cid) -> Option<Vec<u8>>;

    /// Returns true iff `get(cid)` would return `Some(_)`.
    ///
    /// Default impl performs the full `get` and discards the bytes. Impls that
    /// can answer presence cheaply (in-memory HashMaps via `contains_key`,
    /// filesystem-backed impls via `stat()` rather than `read()`) should
    /// override. When a filesystem-backed `Catalog` impl is minted in
    /// libsugar::core, override `contains` to use `exists()` so verifier-side
    /// hot paths don't pay full-read I/O cost.
    fn contains(&self, cid: &Cid) -> bool {
        self.get(cid).is_some()
    }
}

/// In-memory content-addressed byte catalog used by unit tests and small examples.
///
/// Real catalogs may be backed by files, databases, or remote object stores;
/// the trait boundary is intentionally just `Cid -> bytes`.
#[derive(Debug, Clone, Default)]
pub struct HashMapCatalog {
    entries: HashMap<Cid, Vec<u8>>,
}

impl HashMapCatalog {
    /// Store raw canonical bytes under an already-known CID.
    pub fn put(&mut self, cid: Cid, bytes: Vec<u8>) {
        self.entries.insert(cid, bytes);
    }

    /// Canonicalize, address, and store a value in the catalog.
    pub fn insert<T: Canonical>(&mut self, value: &T) -> Cid {
        let cid = super::primitives::address(value);
        self.put(cid.clone(), value.canonical_bytes());
        cid
    }
}

impl Catalog for HashMapCatalog {
    fn get(&self, cid: &Cid) -> Option<Vec<u8>> {
        self.entries.get(cid).cloned()
    }

    fn contains(&self, cid: &Cid) -> bool {
        self.entries.contains_key(cid)
    }
}

/// Typed resolver for materialized transform inputs addressed from [`PathAlgebra`](super::types::PathAlgebra).
///
/// The reusable primitive shape carries input CIDs; concrete execution layers
/// decide how to materialize those CIDs into kit inputs.
pub trait InputCatalog {
    /// Return the input stored at `cid`, or `None` when the material is absent.
    fn get_input(&self, cid: &Cid) -> Option<Input>;
}

/// In-memory typed input catalog for command adapters and tests.
#[derive(Debug, Clone, Default)]
pub struct HashMapInputCatalog {
    entries: HashMap<Cid, Input>,
}

impl HashMapInputCatalog {
    /// Store an already-addressed input under its CID.
    pub fn put(&mut self, cid: Cid, input: Input) {
        self.entries.insert(cid, input);
    }

    /// Address and store an input, returning the input CID used by paths.
    pub fn insert(&mut self, input: Input) -> Cid {
        let cid = super::primitives::address(&input);
        self.put(cid.clone(), input);
        cid
    }
}

impl InputCatalog for HashMapInputCatalog {
    fn get_input(&self, cid: &Cid) -> Option<Input> {
        self.entries.get(cid).cloned()
    }
}

/// One transformation kit: the on-ramp and off-ramp for a source language or target.
///
/// `transform` is the primary primitive: `Kit(Input) -> DomainClaim`.
/// `prove` discharges an already-transformed claim in the kit's configured
/// proving context. `parse` and `serialize` are retained as term-level escape
/// hatches for realization and legacy callers.
pub trait Kit {
    /// The dialect this kit accepts and emits.
    fn dialect(&self) -> Dialect;

    /// Primitive: transform input into a domain claim.
    fn transform(&self, input: &Input) -> Result<DomainClaim, KitError>;

    /// Primitive: attempt to prove or otherwise discharge a domain claim.
    fn prove(&self, _claim: DomainClaim) -> Result<DomainClaim, KitError> {
        Err(KitError::NotSupported)
    }

    /// Deprecated term-level escape hatch.
    #[deprecated(note = "kits transform Input into DomainClaim; consume `transform` instead")]
    fn parse(&self, input: &Input) -> Result<Term, KitError>;

    /// Serialize a faithful [`Term`] back to dialect input.
    fn serialize(&self, term: &Term) -> Result<Input, KitError>;
}

/// One semantic domain: function contracts, protocol evolution, supply graphs.
///
/// `project` is primitive 5, the lossy Dijkstra weakest-precondition projection
/// from faithful terms into durable contracts. `discharge` is primitive 7, the
/// witnesser/checker that resolves a claim's verdict.
pub trait Domain {
    /// The domain kind used as the polymorphism axis in [`DomainClaim`].
    fn name(&self) -> DomainKind;

    /// Primitive 5: project a faithful term through a paper-9 boundary.
    fn project(&self, term: &Term, boundary: &Boundary) -> Result<Contract, DomainError>;

    /// Primitive 7: search for, or check, a witness for a claim.
    fn discharge(
        &self,
        claim: DomainClaim,
        mode: DischargeMode<'_>,
    ) -> Result<DomainClaim, DomainError>;
}

/// Solver portfolio back-end used by `Domain::discharge(Search)`.
///
/// The initial pass exposes the boundary and ships a `NoopPortfolio`; real
/// portfolios shell or RPC to Z3, cvc5, Vampire, Coq, Lean, and friends.
pub trait Portfolio {
    /// Solve an SMT-LIB-like obligation and return the normalized verdict.
    fn solve(&self, smt: &str) -> SolverVerdict;
}

/// Mode for primitive 7, `Domain::discharge`.
pub enum DischargeMode<'a> {
    /// Witness search using a solver portfolio.
    Search { portfolio: &'a dyn Portfolio },
    /// Witness checking by re-walking an existing proof or counterexample.
    Check,
}

/// Normalized result from a solver portfolio.
#[derive(Debug, Clone, PartialEq)]
pub enum SolverVerdict {
    /// The obligation was proved and carries a proof transcript/tree.
    Proved { transcript: serde_json::Value },
    /// The obligation was refuted and carries a counterexample model.
    Refuted { model: serde_json::Value },
    /// The solver could not decide the obligation.
    Unknown { transcript: serde_json::Value },
}

/// Errors from dialect kits.
#[derive(Debug, Error)]
pub enum KitError {
    /// The requested primitive is not implemented by this kit.
    #[error("kit primitive not supported")]
    NotSupported,
    /// The input belongs to another dialect or has no faithful term.
    #[error("kit {dialect:?}: unsupported input: {message}")]
    UnsupportedInput { dialect: Dialect, message: String },
    /// Transforming input into a domain claim failed.
    #[error("kit transform failed: {0}")]
    Transformation(String),
    /// Serialization failed inside a stub or concrete kit.
    #[error("kit serialization failed: {0}")]
    Serialization(String),
}

/// Errors from semantic domains.
#[derive(Debug, Error)]
pub enum DomainError {
    /// The domain stub cannot project the supplied term shape.
    #[error("domain {domain:?}: unsupported projection: {message}")]
    UnsupportedProjection { domain: DomainKind, message: String },
    /// Witness checking was requested for a claim without a witness.
    #[error("domain {domain:?}: check mode requires an existing witness")]
    MissingWitness { domain: DomainKind },
}

/// Top-level error for named verb compositions.
#[derive(Debug, Error)]
pub enum CoreError {
    /// A kit primitive failed.
    #[error(transparent)]
    Kit(#[from] KitError),
    /// A domain primitive failed.
    #[error(transparent)]
    Domain(#[from] DomainError),
    /// Category composition failed.
    #[error(transparent)]
    Compose(#[from] ComposeError),
    /// A verb needed a faithful term that had already been discarded.
    #[error("claim has no faithful term to serialize")]
    MissingTerm,
    /// Linking requires at least one claim.
    #[error("link requires at least one claim")]
    EmptyLink,
    /// Linking needs ordinary composition or a shared contract CID.
    #[error("link requires composable claims or a shared contract cid")]
    NoSharedContractLink,
}

/// SEAM 3a: inversion point for the census path's IR-compiler registry.
///
/// The concrete registry (`sugar_verifier::compiler_registry::build`) lives
/// above `libsugar` in the compiler DAG (`verifier -> libsugar` is the
/// allowed baseline edge; the reverse is the forbidden D4 cycle guarded by
/// `sugar-arch-guard::libsugar_never_reaches_verifier_or_linker`). Rather
/// than have the census path (`component_plan.rs`) call the verifier crate
/// directly, it depends on this trait; the verifier-backed implementation is
/// constructed above and injected in.
///
/// The registry's concrete type (`sugar_ir_compiler::registry::Registry`)
/// is intentionally NOT named here: naming it would require `libsugar` to
/// depend on `sugar-ir-compiler`, and this trait exists precisely so
/// `libsugar` gains no new dependency to perform the inversion. The
/// associated type lets each crate that implements this trait supply its
/// own concrete registry type; `libsugar` only ever sees `Self::Registry`
/// as an opaque, caller-chosen type.
pub trait ComponentRegistry {
    /// The concrete IR-compiler registry type this implementation builds.
    type Registry;

    /// Build a registry of IR compilers discovered for `project_root`.
    fn build(&self, project_root: &std::path::Path) -> Self::Registry;
}
