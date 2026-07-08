// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeSet;

use super::primitives::{compose, verify_sig};
use super::traits::{Catalog, CoreError, DischargeMode, Domain, Kit};
use super::types::{Boundary, Cid, DomainClaim, DomainKind, Input, Truth, Verdict};

/// Named verb: transform an input into an unresolved domain claim.
///
/// Composition: `Kit::transform`.
pub fn transform(kit: &dyn Kit, input: &Input) -> Result<DomainClaim, CoreError> {
    Ok(kit.transform(input)?)
}

/// Named verb: prove an already-transformed domain claim.
///
/// Composition: `Kit::prove`.
pub fn prove(kit: &dyn Kit, claim: DomainClaim) -> Result<DomainClaim, CoreError> {
    Ok(kit.prove(claim)?)
}

/// Named verb: verify a truth by recomputing, resolving, and checking witness.
///
/// Composition: `address-recompute ; resolve/byte-compare ; check-sig ;
/// Domain::discharge(Check)`. This is the bluepaper's constant-size,
/// complete verification theorem expressed as primitive composition.
pub fn verify(truth: &Truth, domain: &dyn Domain, catalog: &dyn Catalog) -> bool {
    let claim = truth.claim();
    let cid = claim.cid();
    let Some(bytes) = catalog.get(&cid) else {
        return false;
    };
    if bytes != claim.canonical_bytes() {
        return false;
    }
    if !verify_sig(claim) {
        return false;
    }
    match domain.discharge(claim.clone(), DischargeMode::Check) {
        Ok(checked) => checked.verdict == Verdict::Proved && checked.witness.is_some(),
        Err(_) => false,
    }
}

/// Named verb: realize a claim into a target dialect.
///
/// Primitive claims no longer embed language terms. Realization must resolve
/// one of the claim's addressed artifacts through a kit-owned catalog; the
/// initial pass keeps the typed boundary and reports the unresolved edge.
pub fn realize(
    _domain: &dyn Domain,
    _target: &dyn Kit,
    _claim: &DomainClaim,
) -> Result<Input, CoreError> {
    Err(CoreError::MissingTerm)
}

/// Named verb: cross-compile through a domain morphism.
///
/// Composition: `transform(src) ; compose(morphism) ; target.serialize`. This
/// is the N+M+N-morphisms shape: kits parse and serialize independently while
/// morphisms are themselves claims/paths.
pub fn cross_compile(
    src: &dyn Kit,
    tgt: &dyn Kit,
    _domain: &dyn Domain,
    input: &Input,
    morphism: &DomainClaim,
    _boundary: &Boundary,
) -> Result<Input, CoreError> {
    let source_claim = transform(src, input)?;
    let _composed = compose(&source_claim, morphism)?;
    let _ = tgt;
    Err(CoreError::MissingTerm)
}

/// Named verb: link module claims by folding category composition.
///
/// This is `fold(compose)` over already-built module/domain claims.
pub fn link(claims: &[DomainClaim]) -> Result<DomainClaim, CoreError> {
    let Some((first, rest)) = claims.split_first() else {
        return Err(CoreError::EmptyLink);
    };
    let mut acc = first.clone();
    for claim in rest {
        match compose(&acc, claim) {
            Ok(composed) => acc = composed,
            Err(_) => return link_by_shared_contract(claims),
        }
    }
    Ok(acc)
}

fn link_by_shared_contract(claims: &[DomainClaim]) -> Result<DomainClaim, CoreError> {
    let Some(first) = claims.first() else {
        return Err(CoreError::EmptyLink);
    };
    let Some(shared_contract) = shared_contract_cid(claims) else {
        return Err(CoreError::NoSharedContractLink);
    };

    let mut artifacts = Vec::new();
    let mut from = Vec::new();
    let mut premises = Vec::new();
    let mut verdict = Verdict::Proved;
    for claim in claims {
        artifacts.extend(claim.artifacts.iter().cloned());
        from.extend(claim.from.iter().cloned());
        premises.push(claim.cid());
        verdict = link_verdict(verdict, claim.verdict);
    }
    artifacts.sort();
    artifacts.dedup();
    from.sort();
    from.dedup();
    premises.sort();
    premises.dedup();

    Ok(DomainClaim {
        domain: DomainKind::Other("linked-program".to_string()),
        contract: first.contract.clone(),
        artifacts,
        from,
        premises,
        to: shared_contract,
        witness: None,
        payload: None,
        verdict,
        attestation: None,
    })
}

fn shared_contract_cid(claims: &[DomainClaim]) -> Option<Cid> {
    let mut sets = claims.iter().map(|claim| {
        Cid::try_from(claim.contract.cid.clone())
            // sugar-audit: default-ok(malformed-contract-cid-empties-that-claims-set-so-intersection-fails-closed-to-refusal-never-a-wrong-link)
            .ok()
            .into_iter()
            .collect::<BTreeSet<_>>()
    });
    let mut shared = sets.next()?;
    for set in sets {
        shared = shared.intersection(&set).cloned().collect();
    }
    shared.into_iter().next()
}

fn link_verdict(left: Verdict, right: Verdict) -> Verdict {
    match (left, right) {
        (Verdict::Refuted, _) | (_, Verdict::Refuted) => Verdict::Refuted,
        (Verdict::Unknown, _) | (_, Verdict::Unknown) => Verdict::Unknown,
        (Verdict::Unresolved, _) | (_, Verdict::Unresolved) => Verdict::Unresolved,
        (Verdict::Proved, Verdict::Proved) => Verdict::Proved,
    }
}
