// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Walk-on-canonicalizer dogfood. Closes #368 AC #7:
// "Dogfood on at least one function in `sugar-canonicalizer`."
//
// The canonicalizer is the substrate's own JCS + BLAKE3-512 layer
// (the bytes that *every* memento goes through to produce its CID).
// Lifting one of its functions through the walker, wrapping it as a
// MintedEnvelope, and verifying the cache hits on a second invocation
// proves the recursive substrate claim end-to-end: the substrate's
// canonicalizer is itself substrate-eligible. Paper 07 §6's
// "compose for free, compress to nothing" is empirical, not asserted.
//
// Combined with the cache assertion this also closes AC #6:
// "Second invocation hits cache (no re-mint, demonstrated via
// mint-counter assertion)."

use std::path::PathBuf;

use sugar_walk::contract::build_function_contract_with_file;
use sugar_walk::{wrap_function_contract_cached, EnvelopeCache, DEV_SIGNER_SEED};

fn read_canonicalizer_source(filename: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-walk has a parent dir")
        .join("sugar-canonicalizer")
        .join("src")
        .join(filename);
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("failed to read {:?}: {}", path, e))
}

fn first_function_named<'a>(file: &'a syn::File, name: &str) -> Option<&'a syn::ItemFn> {
    file.items.iter().find_map(|item| match item {
        syn::Item::Fn(f) if f.sig.ident == name => Some(f),
        _ => None,
    })
}

#[test]
fn walk_lifts_canonicalizer_blake3_function_to_envelope() {
    // Step 1: Read canonicalizer's hash.rs as bytes.
    let src = read_canonicalizer_source("hash.rs");

    // Step 2: Parse via syn — same parser the walker uses on its own
    // input. This is the substrate's own canonicalizer source becoming
    // an AST in the substrate's walker.
    let file: syn::File = syn::parse_str(&src).expect("hash.rs parses");

    // Step 3: Pick `blake3_512_of` — the public hash entry point.
    let item_fn = first_function_named(&file, "blake3_512_of")
        .expect("blake3_512_of present in canonicalizer hash.rs");

    // Step 4: Build the FunctionContractMemento. We pass the source
    // file path so the contract's locus carries the canonicalizer's
    // location. body_cid is None — this is a structural lift only.
    let contract =
        build_function_contract_with_file(item_fn, None, Some("sugar-canonicalizer/src/hash.rs"));
    assert_eq!(contract.fn_name, "blake3_512_of");

    // Step 5: Wrap as a signed MintedEnvelope and verify cache behavior.
    let mut cache = EnvelopeCache::new();
    let env_first = wrap_function_contract_cached(
        &contract,
        "2026-05-05T00:00:00Z",
        &DEV_SIGNER_SEED,
        &mut cache,
    )
    .expect("first wrap mints");

    assert_eq!(cache.mints, 1, "first invocation must mint");
    assert_eq!(cache.hits, 0);
    assert!(env_first.cid.starts_with("blake3-512:"));
    assert!(env_first.contract_cid.starts_with("blake3-512:"));

    // Step 6: AC #6 — second invocation on the same contract must hit
    // the cache; mints stays at 1, hits ticks to 1.
    let env_second = wrap_function_contract_cached(
        &contract,
        "2026-05-05T00:00:00Z",
        &DEV_SIGNER_SEED,
        &mut cache,
    )
    .expect("second wrap hits cache");
    assert_eq!(cache.mints, 1, "second invocation must NOT re-mint");
    assert_eq!(cache.hits, 1);
    assert_eq!(env_first.cid, env_second.cid);
    assert_eq!(env_first.contract_cid, env_second.contract_cid);
    assert_eq!(env_first.canonical_bytes, env_second.canonical_bytes);
}

#[test]
fn walk_lifts_multiple_canonicalizer_functions_into_one_cache() {
    // Both `blake3_512_of` and `blake3_512_hex` go into the same cache.
    // Two distinct contracts → two mints; re-querying both → two hits.
    // No cross-contract contamination.
    let src = read_canonicalizer_source("hash.rs");
    let file: syn::File = syn::parse_str(&src).expect("hash.rs parses");

    let f_of = first_function_named(&file, "blake3_512_of").expect("blake3_512_of present");
    let f_hex = first_function_named(&file, "blake3_512_hex").expect("blake3_512_hex present");

    let c_of =
        build_function_contract_with_file(f_of, None, Some("sugar-canonicalizer/src/hash.rs"));
    let c_hex =
        build_function_contract_with_file(f_hex, None, Some("sugar-canonicalizer/src/hash.rs"));

    let mut cache = EnvelopeCache::new();
    let env_of_1 =
        wrap_function_contract_cached(&c_of, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
            .unwrap();
    let env_hex_1 =
        wrap_function_contract_cached(&c_hex, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
            .unwrap();
    assert_eq!(cache.mints, 2);
    assert_eq!(cache.hits, 0);
    assert_eq!(cache.len(), 2);
    assert_ne!(env_of_1.contract_cid, env_hex_1.contract_cid);

    // Re-mint pass: both come from cache.
    let env_of_2 =
        wrap_function_contract_cached(&c_of, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
            .unwrap();
    let env_hex_2 =
        wrap_function_contract_cached(&c_hex, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
            .unwrap();
    assert_eq!(cache.mints, 2, "no re-mint");
    assert_eq!(cache.hits, 2);
    assert_eq!(env_of_1.cid, env_of_2.cid);
    assert_eq!(env_hex_1.cid, env_hex_2.cid);
}

#[test]
fn walk_canonicalizer_function_locus_carries_canonicalizer_path() {
    // The locus on the contract memento must carry the canonicalizer's
    // file path — downstream consumers (the substrate's resolve/index
    // pipeline) use this to map mementos back to source for developer
    // feedback ("compile error at <file>:<line>").
    let src = read_canonicalizer_source("hash.rs");
    let file: syn::File = syn::parse_str(&src).expect("hash.rs parses");
    let item_fn = first_function_named(&file, "blake3_512_of").expect("blake3_512_of present");
    let contract =
        build_function_contract_with_file(item_fn, None, Some("sugar-canonicalizer/src/hash.rs"));
    assert_eq!(
        contract.locus.file.as_deref(),
        Some("sugar-canonicalizer/src/hash.rs")
    );
    assert!(contract.locus.line > 0, "locus line populated");
}
