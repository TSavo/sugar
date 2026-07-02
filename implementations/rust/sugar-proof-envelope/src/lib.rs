// SPDX-License-Identifier: Apache-2.0
//
// sugar-proof-envelope
//
// Two responsibilities:
//
// 1. A small deterministic-CBOR encoder enforcing RFC 8949 §4.2.1
//    "Core Deterministic Encoding": shortest-form integer encoding,
//    definite-length items, and map keys sorted by bytewise CBOR
//    encoded form.
//
// 2. The .proof file builder: bundles a `(name, version, members,
//    signer, declaredAt, signature)` catalog into deterministic-CBOR
//    bytes whose BLAKE3-512 hash IS the filename CID.
//
// 3. An Ed25519 signing helper that returns the spec's
//    self-identifying `"ed25519:" + base64(sig)` string form, plus a
//    raw-byte form used for the .proof envelope's `signature` field
//    (which is a raw bstr per the spec).

pub mod cbor;
pub mod cbor_decode;
pub mod filename;
pub mod proof;
pub mod proof_graph;
pub mod sign;
pub mod typed_member;

pub use cbor::{
    cbor_encode_array_head, cbor_encode_bstr, cbor_encode_map_head, cbor_encode_tstr,
    cbor_encode_uint, CborMajor,
};
pub use cbor_decode::{CborDecodeError, CborValue};

/// The SOLE sanctioned raw-CBOR catalog read. For PROTOCOL-CONFORMANCE encoding
/// checks ONLY (deterministic re-encoding comparison, raw signature/kind/metadata).
/// To read the proof GRAPH (atoms/bodies/members/contracts) use ProofGraph::read /
/// ProofCatalog::read — NOT this. Hand-decoding the catalog to read members is the
/// crime this gate prevents.
pub fn decode_for_conformance(bytes: &[u8]) -> Result<CborValue, CborDecodeError> {
    crate::cbor_decode::decode(bytes)
}
pub use filename::{cid_from_proof_stem, proof_filename};
pub use proof::{build_proof_envelope, ProofEnvelopeInput, ProofEnvelopeOutput};
pub use proof_graph::{
    member_body, member_field, member_kind, member_signature, member_signer, recompute_member_cid,
    verify_member_signature, AnchoredMember, AssertionSurfaceMemento, AtomCid, AtomMemento,
    AuthorityMemento, AuthorityMementoRef, BridgeMemento, ClaimContractMemento, ContractBody,
    ContractBodyCid, ContractEntry, ContractMemento, ContractMementoRef,
    EffectSiteAnnotationMemento, FactoryWalkMemento, FlatAtom, ImplicationMemento,
    LibrarySugarBindingMemento, MemberView, MementoCid, PlanMemento, ProofCatalog, ProofGraph,
    ProofIdentity, ProofRunMemento, SourceMemento, StageReceiptMemento, StoredMember,
    WitnessClaimMemento, WitnessMemento,
};
pub use sign::{
    ed25519_pubkey_string, ed25519_sign_string, ed25519_sign_with_seed, ed25519_verify_bytes,
    ed25519_verify_string, Ed25519PublicKey, Ed25519Seed, Ed25519Signature, ED25519_KEY_PREFIX,
    ED25519_SIG_PREFIX,
};
pub use typed_member::{
    AssertionSurfaceMementoMember, AuthorityMember, BridgeMember, ContractMember,
    EffectSiteAnnotationMember, FactoryWalkMementoMember, ImplicationMember,
    LibrarySugarBindingEntryMember, Member, MemberError, MemberKind, PlanMementoMember,
    ProofRunMember, SourceMementoMember, StageReceiptMember, WitnessClaimMember,
    WitnessMementoMember,
};

#[derive(Debug, thiserror::Error)]
pub enum ProofEnvelopeError {
    #[error("proof-envelope: {0}")]
    Other(String),
}
