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

pub use cbor::{
    cbor_encode_array_head, cbor_encode_bstr, cbor_encode_map_head, cbor_encode_tstr,
    cbor_encode_uint, CborMajor,
};
pub use cbor_decode::{decode as cbor_decode, CborDecodeError, CborValue};
pub use filename::{cid_from_proof_stem, proof_filename};
pub use proof::{build_proof_envelope, ProofEnvelopeInput, ProofEnvelopeOutput};
pub use proof_graph::{
    AssertionSurfaceMemento, AtomCid, AtomMemento, AuthorityMemento, AuthorityMementoRef,
    BridgeMemento, ClaimContractMemento, ContractBody, ContractBodyCid, ContractEntry,
    ContractMemento, ContractMementoRef, EffectSiteAnnotationMemento, FactoryWalkMemento, FlatAtom,
    member_body, member_field, member_kind, member_signature, member_signer, ImplicationMemento,
    LibrarySugarBindingMemento,
    MemberView, MementoCid, PlanMemento, ProofCatalog, ProofGraph, ProofIdentity, ProofRunMemento,
    SourceMemento,
    StageReceiptMemento, WitnessClaimMemento, WitnessMemento,
};
pub use sign::{
    ed25519_pubkey_string, ed25519_sign_string, ed25519_sign_with_seed, ed25519_verify_bytes,
    ed25519_verify_string, Ed25519PublicKey, Ed25519Seed, Ed25519Signature, ED25519_KEY_PREFIX,
    ED25519_SIG_PREFIX,
};

#[derive(Debug, thiserror::Error)]
pub enum ProofEnvelopeError {
    #[error("proof-envelope: {0}")]
    Other(String),
}
