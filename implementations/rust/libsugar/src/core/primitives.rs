// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_canonicalizer::blake3_512_of;
use sugar_proof_envelope::{
    ed25519_pubkey_string, ed25519_sign_string, ed25519_verify_string, Ed25519Seed, Signature,
};
use thiserror::Error;

use crate::compose::{
    compose_function_contracts, ComposedFunctionContract, FunctionContractMemento,
};

use super::traits::{Canonical, Catalog};
use super::types::{Attestation, Cid, Contract, DomainClaim, DomainKind, Verdict};

/// Signing-key type for primitive 8, `sign`.
///
/// This wraps the reachable `sugar-proof-envelope` Ed25519 helper. The
/// helper accepts deterministic 32-byte seeds and emits the protocol's
/// self-identifying `ed25519:<base64>` public-key and signature strings.
pub type SigningKey = Ed25519Seed;

/// Primitive 1: address a canonical structure with JCS + BLAKE3-512.
///
/// This is the substrate identity function: canonical bytes are computed by
/// the value's [`Canonical`] implementation, then hashed by
/// `sugar-canonicalizer::blake3_512_of`.
pub fn address<T: Canonical + ?Sized>(structure: &T) -> Cid {
    Cid::from_hash_output(blake3_512_of(&structure.canonical_bytes()))
}

/// Primitive 2: resolve bytes from a catalog by CID.
///
/// This is the reverse of `address` at the storage boundary. The primitive is
/// intentionally byte-oriented so callers can decide which typed structure to
/// parse from the canonical payload.
pub fn resolve(cid: &Cid, catalog: &dyn Catalog) -> Option<Vec<u8>> {
    catalog.get(cid)
}

/// Primitive 6: category composition for domain claims.
///
/// The initial pass implements the function-contract special case by
/// delegating to the existing CCP algebra `compose_function_contracts`.
/// General domain premise entailment is left to domain-specific extensions.
pub fn compose(a: &DomainClaim, b: &DomainClaim) -> Result<DomainClaim, ComposeError> {
    if a.domain != b.domain {
        return Err(ComposeError::DomainMismatch {
            left: a.domain.clone(),
            right: b.domain.clone(),
        });
    }
    if !b.from.iter().any(|cid| cid == &a.to) {
        return Err(ComposeError::EndpointMismatch {
            left_to: a.to.clone(),
            right_from: b.from.clone(),
        });
    }

    match a.domain {
        DomainKind::FunctionContract => compose_function_contract_claims(a, b),
        _ => Err(ComposeError::UnsupportedDomain(a.domain.clone())),
    }
}

/// Primitive 8: attach an Ed25519 courtesy-layer attestation to a claim.
///
/// The signature covers the unsigned claim's canonical bytes. The attestation
/// is not included in [`DomainClaim`]'s canonical identity, preserving
/// author-independent verification.
pub fn sign(mut claim: DomainClaim, key: &SigningKey) -> DomainClaim {
    claim.attestation = None;
    let signed_cid = claim.cid();
    let message = claim.canonical_bytes();
    let signer = ed25519_pubkey_string(key);
    let signature = ed25519_sign_string(key, &message);
    claim.attestation = Some(Attestation {
        signer,
        signature,
        signed_cid,
    });
    claim
}

/// Verify the courtesy-layer Ed25519 attestation if one is present.
///
/// Claims without attestations are accepted: signatures are not part of the
/// bluepaper's author-independent verification theorem.
pub fn verify_sig(claim: &DomainClaim) -> bool {
    let Some(attestation) = &claim.attestation else {
        return true;
    };
    if attestation.signed_cid != claim.cid() {
        return false;
    }
    let Ok(signature) = Signature::try_parse(attestation.signature.clone()) else {
        return false;
    };
    ed25519_verify_string(
        &attestation.signer,
        &signature,
        &claim.unsigned().canonical_bytes(),
    )
}

/// Composition errors for primitive 6.
#[derive(Debug, Error)]
pub enum ComposeError {
    /// Claims from different domains cannot compose.
    #[error("cannot compose claims from different domains: {left:?} vs {right:?}")]
    DomainMismatch { left: DomainKind, right: DomainKind },
    /// The left path's output does not feed any right-path premise.
    #[error(
        "cannot compose endpoints: left to {left_to} does not appear in right from {right_from:?}"
    )]
    EndpointMismatch { left_to: Cid, right_from: Vec<Cid> },
    /// This domain has no core composition rule in the initial pass.
    #[error("core compose does not yet support domain {0:?}")]
    UnsupportedDomain(DomainKind),
    /// The function-contract CCP algebra refused the special case.
    #[error("function-contract composition failed")]
    FunctionContractCompositionFailed,
    /// A composed contract CID did not satisfy CID shape validation.
    #[error("composed function-contract CID was invalid")]
    InvalidComposedCid,
}

fn compose_function_contract_claims(
    inner_claim: &DomainClaim,
    outer_claim: &DomainClaim,
) -> Result<DomainClaim, ComposeError> {
    let composed = compose_function_contracts(&outer_claim.contract, &inner_claim.contract, 0)
        .ok_or(ComposeError::FunctionContractCompositionFailed)?;
    let contract = composed_to_contract(&composed, &outer_claim.contract, &inner_claim.contract);
    let to = Cid::try_from(composed.cid.clone()).map_err(|_| ComposeError::InvalidComposedCid)?;
    let mut from = inner_claim.from.clone();
    from.extend(
        outer_claim
            .from
            .iter()
            .filter(|cid| *cid != &inner_claim.to)
            .cloned(),
    );
    from.sort();
    from.dedup();
    let mut premises = vec![inner_claim.cid(), outer_claim.cid()];
    premises.sort();
    premises.dedup();
    let mut artifacts = inner_claim.artifacts.clone();
    artifacts.extend(outer_claim.artifacts.iter().cloned());
    artifacts.sort();
    artifacts.dedup();

    Ok(DomainClaim {
        domain: DomainKind::FunctionContract,
        contract,
        artifacts,
        from,
        premises,
        to,
        witness: None,
        payload: None,
        verdict: compose_verdict(inner_claim.verdict, outer_claim.verdict),
        attestation: None,
    })
}

fn composed_to_contract(
    composed: &ComposedFunctionContract,
    outer: &FunctionContractMemento,
    inner: &FunctionContractMemento,
) -> Contract {
    Contract {
        fn_name: format!("{}__compose__{}", outer.fn_name, inner.fn_name),
        formals: inner.formals.clone(),
        formal_sorts: inner.formal_sorts.clone(),
        formal_regions: inner.formal_regions.clone(),
        return_sort: outer.return_sort.clone(),
        return_region: outer.return_region.clone(),
        pre: composed.pre.clone(),
        post: composed.post.clone(),
        body_cid: None,
        effects: crate::compose::EffectSet::empty(),
        locus: crate::compose::Locus::unknown(),
        canonical_bytes: composed.canonical_bytes.clone(),
        cid: composed.cid.clone(),
        auto_minted_mementos: vec![],
        panic_loci: vec![],
        concept_hint: None,
    }
}

fn compose_verdict(left: Verdict, right: Verdict) -> Verdict {
    match (left, right) {
        (Verdict::Refuted, _) | (_, Verdict::Refuted) => Verdict::Refuted,
        (Verdict::Proved, Verdict::Proved) => Verdict::Proved,
        (Verdict::Unknown, _) | (_, Verdict::Unknown) => Verdict::Unknown,
        _ => Verdict::Unresolved,
    }
}
