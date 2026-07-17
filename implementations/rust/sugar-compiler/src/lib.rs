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

/// The kit rendezvous/dispatch engine (`KitRegistry`, `execute_path`,
/// `PathAlgebra`, `LiftKit`, the resident child-process pool). Moved from
/// `sugar-cli/src/kit_path/` in SEAM 3b. Lives with the `Kit` noun here.
/// Realize-sidecar strip is membrane law in libsugar (#3855); kit_path itself
/// has no `sugar-walk` import (instrumented). SourceMemento/SrcSpan also live
/// in libsugar — sugar-compiler has no sugar-walk Cargo edge (arch-guard ban).
pub mod kit_path;

/// The kit declaration loader: spawns a kit's declared command and performs
/// the `initialize` + `sugar.plugin.kit_declaration` + `shutdown` JSON-RPC
/// round-trip. Moved from `sugar-cli/src/kit_declaration.rs` (SEAM 3b
/// review follow-up): `Kit::rendezvous` calls this to earn the
/// "declared, connected" claim in its own doc comment, rather than only
/// checking the manifest shape.
pub mod kit_declaration;

/// The unforgeable `Kit` frontend handle. See `kit::Kit::rendezvous`.
pub mod kit;

/// The two-reds typed solve outcome. See `outcome::Outcome`.
pub mod outcome;

/// `ProofGraph::solve`, the `Orchestrate` extension trait. See
/// `orchestrate::Orchestrate`.
pub mod orchestrate;

/// Derive `sugar_linker::LinkerInputs` from a pool's real bridge data
/// (sugar#3857). See `linker_inputs::derive_linker_inputs`.
pub mod linker_inputs;

/// The resolve verbs (SEAM 4): `Kit::testimony` (vendor dependency proofs)
/// and `Kit::source` (source-oracle lookup). See `resolve` module docs.
pub mod resolve;

/// Part 6, Phases 1+2: the strongly-typed navigable tree
/// (`SourceFile`/`Function`/`CallSite`/`Assertion`/`Fact`/...) and the
/// `sugar.enumerate` wire method that drives it lazily over the kit's
/// membrane. See `tree` module docs.
pub mod tree;

/// Campaign B: fold the enumerate tree into a `ProofGraph` via `feed`.
/// Task 5 ships the red instrument surface; Task 6 implements the walk.
/// See `feed_from_tree` module docs.
pub mod feed_from_tree;

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
        (
            ed25519_pubkey_string(&default_signer_seed),
            default_signer_seed,
        )
    }
}

/// Hand-sign an arbitrary message with an ed25519 seed, returning
/// `(signer_pubkey_string, signature_string)`.
///
/// The single sign path for the MINT pipeline: both `seal_proof_graph` and
/// the formerly hand-rolled `json!` site in `sugar-cli`'s
/// `mint_toolchain_output_witness_decl` (originally `cmd_mint.rs:2068-2069`)
/// route through here. Other sugar-cli sign sites (report_witness,
/// cmd_verify, witness_verify) are NOT yet consolidated -- they move in the
/// later verify/report seams of the compiler-shape plan.
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
