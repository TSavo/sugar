// SPDX-License-Identifier: MIT OR Apache-2.0
//
// join-manifest design, lane 1 (seal-time emission + G1).
//
// G1: recompute-from-pool == stored manifest, driven through the REAL
// base64 vendor/consumer fixtures the eager-vs-lazy differential
// (`sugar-proof-envelope/src/cbor_index.rs`) already uses -- not synthetic
// data. This test loads a real fixture's bytes into a `MementoPool` via the
// same loader every consumer of a `.proof` file uses
// (`load_all_proofs::load_proof_bytes_into_pool`), computes a manifest from
// that pool with `consistency::build_manifest_from_pool` (the seal-time
// grouping+ambient scan), seals it into a fresh envelope carrying the same
// graph, and asserts the manifest FETCHED BACK OUT of that envelope (via the
// lazy CID-verified `cbor_index::fetch_manifest` reader) is byte-identical
// to what was computed from the pool.
//
// G4: flipping one byte inside the sealed manifest's payload range makes
// `fetch_manifest` refuse (CID mismatch) -- the manifest's own local check --
// AND changes the whole envelope's BLAKE3-512 filename CID, i.e. the
// byte-flip fails the WHOLE-PROOF trust root, not just a side gate.
use std::path::{Path, PathBuf};

use sugar_proof_envelope::cbor_index::{build_index, fetch_manifest};
use sugar_proof_envelope::{build_proof_envelope, ProofEnvelopeInput, ProofGraph};
use sugar_verifier::consistency::build_manifest_from_pool;
use sugar_verifier::load_all_proofs::{load_proof_bytes_into_pool, ProofBytes};
use sugar_verifier::types::MementoPool;

fn fixture_path(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("implementations/rust")
        .join("sugar-proof-envelope/tests/fixtures")
        .join(name)
}

fn fixture_bytes(name: &str) -> Vec<u8> {
    let path = fixture_path(name);
    std::fs::read(&path).unwrap_or_else(|e| panic!("read fixture {}: {e}", path.display()))
}

/// Seal `graph` with `manifest` into a fresh envelope. Identity fields are
/// fixed dummies -- only the manifest slot's round trip is under test here,
/// not signing/identity (covered by `proof.rs`'s own tests).
fn seal_with_manifest(
    graph: ProofGraph,
    manifest: Option<sugar_proof_envelope::manifest::Manifest>,
) -> sugar_proof_envelope::ProofEnvelopeOutput {
    build_proof_envelope(&ProofEnvelopeInput {
        name: "@sugar/manifest-seal-g1-test".to_string(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid: "blake3-512:aa".to_string(),
        signer_seed: [0x33; 32],
        declared_at: "2026-07-06T00:00:00.000Z".to_string(),
        manifest,
    })
}

fn load_fixture_pool(bytes: &[u8]) -> MementoPool {
    let mut pool = MementoPool::default();
    // A well-formed `.proof` file's own CID IS blake3-512 of its final bytes
    // (see `proof.rs::build_proof_envelope` step 4) -- the same rule the
    // loader's `ProofBytes` staging enforces. Passing the bytes' own real
    // hash here does not weaken the check: `load_proof_bytes_into_pool` still
    // independently recomputes and verifies it against these actual bytes.
    let expected_cid = sugar_canonicalizer::blake3_512_of(bytes);
    let proof_bytes = ProofBytes::try_from_parts(
        "g1-fixture",
        expected_cid,
        bytes.to_vec(),
        sugar_verifier::Speaker::consumer("g1-fixture"),
    )
    .expect("fixture bytes stage into ProofBytes");
    load_proof_bytes_into_pool(&[proof_bytes], &mut pool);
    pool
}

fn g1_round_trip_for_bytes(fixture: &str, bytes: Vec<u8>) {
    let graph = ProofGraph::read(&bytes).unwrap_or_else(|e| panic!("{fixture}: read: {e}"));
    let pool = load_fixture_pool(&bytes);

    let manifest_from_pool = build_manifest_from_pool(&pool, "self");

    let sealed = seal_with_manifest(graph, Some(manifest_from_pool.clone()));

    let index = build_index(&sealed.bytes)
        .unwrap_or_else(|e| panic!("{fixture}: build_index on sealed bytes: {e:?}"));
    assert!(
        index.manifest.is_some(),
        "{fixture}: sealed envelope must carry a manifest range"
    );
    let recovered = fetch_manifest(&sealed.bytes, &index)
        .unwrap_or_else(|e| panic!("{fixture}: fetch_manifest: {e}"))
        .unwrap_or_else(|| panic!("{fixture}: fetch_manifest returned None for a sealed proof"));

    // G1: recompute-from-pool == stored manifest.
    assert_eq!(
        manifest_from_pool, recovered,
        "{fixture}: manifest recomputed from the pool must equal the manifest fetched back \
         out of the sealed envelope"
    );

    // G4: flip one byte inside the manifest's own payload range -> the local
    // fetch_manifest gate refuses, AND the whole envelope's filename CID
    // (BLAKE3-512 of the full signed bytes) changes -- the byte-flip fails
    // the WHOLE-PROOF trust root, not merely a side channel.
    let range = index.manifest.expect("checked above");
    assert!(
        range.len > 0,
        "{fixture}: non-empty manifest payload expected for a byte-flip test"
    );
    let mut flipped = sealed.bytes.clone();
    flipped[range.start] ^= 0x01;

    let flipped_index = build_index(&flipped)
        .unwrap_or_else(|e| panic!("{fixture}: build_index on flipped bytes: {e:?}"));
    let flip_result = fetch_manifest(&flipped, &flipped_index);
    assert!(
        flip_result.is_err(),
        "{fixture}: a single flipped manifest byte must fail fetch_manifest's CID check"
    );

    let flipped_cid = sugar_canonicalizer::blake3_512_of(&flipped);
    assert_ne!(
        sealed.cid, flipped_cid,
        "{fixture}: a flipped manifest byte must change the whole envelope's own CID"
    );
}

fn g1_round_trip_for_fixture(fixture: &str) {
    g1_round_trip_for_bytes(fixture, fixture_bytes(fixture));
}

#[test]
fn g1_recompute_from_pool_equals_stored_manifest_on_real_vendor_fixture() {
    g1_round_trip_for_fixture("base64_vendor.proof");
}

#[test]
fn g1_recompute_from_pool_equals_stored_manifest_on_real_consumer_fixture() {
    g1_round_trip_for_fixture("base64_consumer.proof");
}

#[test]
fn g1_recompute_from_pool_equals_stored_manifest_on_pandas_demo_proof_path_gated() {
    // Path-gated per the design brief (G2 wording): only runs if the pandas
    // demo checkout is present on this machine. Skips (does not fail) when
    // absent -- this is a bonus receipt against a much larger real proof,
    // not a substitute for the base64 fixture tests above.
    let dir = Path::new("/Users/tsavo/sugar-pandas-demo/consumer-bad");
    let Ok(entries) = std::fs::read_dir(dir) else {
        eprintln!("pandas demo path absent ({}), skipping", dir.display());
        return;
    };
    let mut ran_any = false;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("proof") {
            continue;
        }
        let bytes = std::fs::read(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
        let label = path.file_name().unwrap().to_string_lossy().to_string();
        g1_round_trip_for_bytes(&label, bytes);
        ran_any = true;
    }
    assert!(
        ran_any,
        "pandas demo directory present but contained no .proof files"
    );
}

#[test]
fn manifest_absent_on_a_real_fixture_sealed_without_one() {
    // Old-proof-shape parity: sealing WITHOUT a manifest (the pre-lane
    // behavior) must leave `CatalogIndex::manifest` as `None` and
    // `fetch_manifest` must return `Ok(None)`, never an error -- "no
    // behavior change when absent" is load-bearing, not just a comment.
    let bytes = fixture_bytes("base64_vendor.proof");
    let graph = ProofGraph::read(&bytes).expect("read vendor fixture");
    let sealed = seal_with_manifest(graph, None);
    let index = build_index(&sealed.bytes).expect("build_index on unsealed bytes");
    assert!(index.manifest.is_none());
    let fetched = fetch_manifest(&sealed.bytes, &index).expect("fetch_manifest on absent slot");
    assert!(fetched.is_none());
}
