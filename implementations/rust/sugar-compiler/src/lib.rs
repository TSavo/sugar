// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar-compiler`: mint-time proof signing and seal-time manifest assembly.
//
// Seam 1 of the sugar-compiler lift-and-shift: this crate holds the code
// MOVED verbatim out of `sugar-cli/src/cmd_mint.rs` (no rewrite, no
// reordering of passes). It is a pure relocation gated by byte-identical
// `.proof` output: every `.proof` filename is a blake3-512 CID of its
// bytes, so an unchanged filename set across the move IS the proof that
// no behavior changed.
//
// Nothing outside `sugar-cli` may depend on this crate yet -- the public
// surface here is plain `pub fn`s taking the same arguments the moved
// code took inline, not yet a trait/method surface (that comes in a
// later seam).

use std::collections::BTreeMap;

use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, ed25519_sign_string, Ed25519Seed,
    ProofEnvelopeInput, ProofGraph,
};

/// The signed, sealed `.proof` bytes plus the CID that names the file.
///
/// This is the moved `MintedIrDocument { bytes, filename_cid, .. }`
/// construction (originally `cmd_mint.rs:4498-4503`), narrowed to just the
/// two fields this crate's signing/sealing logic actually produces.
/// `sugar-cli` still owns the full `MintedIrDocument` struct (it also
/// carries `contract_set_cid` / `contract_bindings`, which are unrelated
/// to signing and were not part of this seam's move) and wraps this
/// return value into it.
#[derive(Debug, Clone)]
pub struct SignedProof {
    pub bytes: Vec<u8>,
    pub filename_cid: String,
}

/// Resolve the `(signer_cid, signer_seed)` pair a mint run signs its proof
/// envelope with.
///
/// Moved verbatim from `cmd_mint.rs:4419-4426`. There are two branches,
/// both preserved exactly: an authority-override path (an explicit
/// mint-time `proof` authority was declared, so its CID/seed sign) and a
/// dev-seed default path (no such authority, so the caller-supplied
/// default seed signs and its own pubkey is the signer CID). The
/// `default_signer_seed` is passed in by the caller rather than declared
/// here: `sugar-compiler` must not own `DEV_SIGNER_SEED`, a face-owned
/// (`sugar-cli`) default.
pub fn resolve_proof_signer(
    authority: Option<(String, Ed25519Seed)>,
    default_signer_seed: Ed25519Seed,
) -> (String, Ed25519Seed) {
    if let Some((cid, seed)) = authority {
        (cid, seed)
    } else {
        (ed25519_pubkey_string(&default_signer_seed), default_signer_seed)
    }
}

/// Hand-sign an arbitrary message with an ed25519 seed, returning
/// `(signer_pubkey_string, signature_string)`.
///
/// This is the single sign path both `resolve_proof_signer`'s callers and
/// any ad hoc hand-rolled-signature `json!` site (e.g. `sugar-cli`'s
/// `mint_toolchain_output_witness_decl`, originally `cmd_mint.rs:2068-2069`)
/// must route through, so no second, drifted signing implementation grows
/// elsewhere.
pub fn hand_sign(seed: &Ed25519Seed, message: &[u8]) -> (String, String) {
    let signer = ed25519_pubkey_string(seed);
    let signature = ed25519_sign_string(seed, message);
    (signer, signature)
}

/// Sign and seal a `ProofGraph` into its final `.proof` bytes.
///
/// Moved verbatim from `cmd_mint.rs:4456-4503` (the `ProofEnvelopeInput`
/// assembly plus the two-pass seal+manifest logic). TWO PASSES are kept
/// exactly as before and must never be collapsed into one: pass 1 builds
/// the envelope WITHOUT a manifest, self-loads those just-minted bytes
/// into a fresh pool via the same loader every `.proof` consumer uses, and
/// runs `build_manifest_from_pool` (the same grouping+ambient-collection
/// scan `verify_consistency` runs at every prove, scoped here to
/// once-per-seal). Pass 2 rebuilds the envelope WITH that sealed manifest
/// so it lands inside the signed root. Collapsing to one pass would mean
/// the manifest could never describe the proof its own signature covers.
pub fn seal_proof_graph(
    graph: ProofGraph,
    signer_cid: String,
    signer_seed: Ed25519Seed,
    produced_at: String,
    metadata: Option<BTreeMap<String, String>>,
) -> Result<SignedProof, String> {
    let proof_input = ProofEnvelopeInput {
        name: "ir-document".to_string(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata,
        graph,
        signer_cid,
        signer_seed,
        declared_at: produced_at,
        manifest: None,
    };

    // SEAL-TIME MANIFEST (join-manifest design, lane 1). Two-pass mint: build
    // the envelope once WITHOUT a manifest, load those just-minted bytes into
    // a fresh (this-proof-only) pool via the exact loader every consumer of a
    // `.proof` file uses, then run the SAME grouping+ambient-collection logic
    // `verify_consistency` runs at every prove -- `build_manifest_from_pool`
    // is a pure relocation of that scan, scoped here to once-per-seal instead
    // of once-per-verify-pass. Re-build the envelope WITH the sealed manifest
    // so it lands inside the signed root (a byte-flip anywhere in it then
    // fails the whole-proof trust root, per G4). Any failure in this second
    // pass (malformed just-built bytes, pool load error) is loud: it means
    // the manifest could not be honestly computed from what was just minted,
    // so minting must not silently ship a stale/empty one.
    let unsealed = build_proof_envelope(&proof_input);
    let mut pool = sugar_verifier::types::MementoPool::default();
    let proof_bytes = sugar_verifier::load_all_proofs::ProofBytes::try_from_parts(
        "seal-time-manifest-self-load",
        unsealed.cid.clone(),
        unsealed.bytes.clone(),
        sugar_verifier::Speaker::consumer("seal-time-manifest-self-load"),
    )
    .map_err(|e| format!("seal-time manifest: could not stage just-minted proof bytes: {e}"))?;
    sugar_verifier::load_all_proofs::load_proof_bytes_into_pool(&[proof_bytes], &mut pool);
    let manifest = sugar_verifier::consistency::build_manifest_from_pool(&pool, &unsealed.cid);

    let sealed_input = ProofEnvelopeInput {
        manifest: Some(manifest),
        ..proof_input
    };
    let built = build_proof_envelope(&sealed_input);

    Ok(SignedProof {
        bytes: built.bytes,
        filename_cid: built.cid,
    })
}
