// SPDX-License-Identifier: MIT OR Apache-2.0

//! Core Sugar interface.
//!
//! This module lays down the eight primitive operations as Rust traits,
//! structs, and functions. The familiar verbs are intentionally thin
//! compositions over those primitives:
//!
//! - `transform = parse ; project ; address`
//! - `prove = transform ; discharge(Search)`
//! - `verify = address-recompute ; check-signature ; discharge(Check)`
//! - `realize = serialize` when the faithful term is still present
//! - `cross_compile = transform ; compose ; serialize`
//! - `link = fold(compose)`
//!
//! `mint` is `transform` on an [`Input::Spec`]. `pattern_scan` is a catalog
//! filter over [`DomainClaim`]s followed by `discharge` of matched
//! composition obligations. `commit` is `compose(parent, change)` followed by
//! `sign`.

pub mod lift_canonical;
pub mod primitives;
pub mod source_memento;
pub mod stubs;
pub mod traits;
pub mod types;
pub mod verbs;
pub mod walks;

pub use lift_canonical::strip_realize_sidecar_from_lift_term;
pub use primitives::{address, compose, resolve, sign, verify_sig, ComposeError, SigningKey};
pub use source_memento::{SourceMemento, SrcSpan};
pub use stubs::{CKit, FunctionContractDomain, NoopPortfolio, RustKit};
pub use traits::{
    Canonical, Catalog, ComponentRegistry, CoreError, Domain, DomainError, HashMapCatalog,
    HashMapInputCatalog, InputCatalog, Kit, KitError, Portfolio,
};
pub use types::{
    ArityShape, AritySlot, Attestation, Boundary, ChainIntegrityFailureWitness,
    ChainIntegrityWitness, Cid, CidError, ConformanceDeclaration, Contract, Dialect, DomainClaim,
    DomainKind, Formula, Input, LanguageSignature, OperationSignature, Path, PathAlgebra,
    PathDocument, PathDocumentError, PathError, PathInputBinding, PathInputMaterial, Refutation,
    SignatureCatalogError, SlotEvaluation, SlotSort, Term, Truth, Verb, Verdict,
    VerdictCoercionError, Witness,
};
pub use verbs::{cross_compile, link, prove, realize, transform, verify};
pub use walks::{
    assert_concept_tier, walk_premises_to_root, walk_premises_to_root_with_failure_steps,
    ChainBreak, ChainWalkFailure, HubMissingNode,
};
