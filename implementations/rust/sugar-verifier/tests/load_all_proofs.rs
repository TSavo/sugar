// SPDX-License-Identifier: Apache-2.0
//
// Stage 1 (load_all_proofs) tests. Pins:
//   - rule 1 (filename CID matches content): mismatched filename is
//     rejected and the LoadError carries "rule 1 (trust root)"
//   - rule 2 (member CIDs match envelope identities): member envelope
//     bytes whose hash doesn't match the catalog key is rejected with
//     "rule 2"
//   - empty / non-existent project_root yields an empty pool with no
//     load_errors
//   - happy path: a Rust-kit-published .proof loads cleanly, indexes
//     mementos by CID and bridges by sourceSymbol

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use sugar_canonicalizer::blake3_512_of;
use sugar_claim_envelope::{
    mint_bridge, mint_contract, Authoring, MintBridgeArgs, MintContractArgs,
};
use sugar_ir_symbolic::serialize::formula_to_value;
use sugar_ir_symbolic::{forall, gt, must, num, reset_collector, Int};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, Ed25519Seed, ProofEnvelopeInput,
};
use sugar_verifier::load_all_proofs;

fn make_unique_dir(suffix: &str) -> PathBuf {
    let base = std::env::temp_dir();
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = base.join(format!("sugar-rust-test-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn publish_parseint_proof(dir: &Path) -> String {
    // Publish a real parseInt .proof via the Rust kit, return its CID.
    reset_collector();
    must("parseInt", forall(Int(), |n| gt(n, num(0))));
    let decls = sugar_ir_symbolic::finish();
    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let declared_at = "2026-04-30T00:00:00.000Z";
    let produced_by = "rust-test@1.0";
    let mut members: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    let mut name_to_cid = std::collections::HashMap::<String, String>::new();
    for d in &decls {
        let args = MintContractArgs {
            evidence_term: None,
            formals: Vec::new(),
            emit_empty_formals: false,
            formal_sorts: Vec::new(),
            library: None,
            body_discharge_eligible: true,
            body_discharge_refusal_reason: None,
            panic_loci: Vec::new(),
            class_shapes: Vec::new(),
            source_warrants: Vec::new(),
            contract_name: d.name.clone(),
            pre: d.pre.as_deref().map(formula_to_value),
            post: d.post.as_deref().map(formula_to_value),
            inv: d.inv.as_deref().map(formula_to_value),
            out_binding: d.out_binding.clone(),
            produced_by: produced_by.into(),
            produced_at: declared_at.into(),
            input_cids: vec![],
            authoring: Authoring::KitAuthor {
                author: produced_by.into(),
                note: None,
            },
            signer_seed,
        };
        let m = mint_contract(&args).expect("mint_contract");
        members.insert(m.cid.clone(), m.canonical_bytes);
        name_to_cid.insert(d.name.clone(), m.cid);
    }
    let bridge_args = MintBridgeArgs {
        produced_by: produced_by.into(),
        produced_at: declared_at.into(),
        source_symbol: "parseInt".into(),
        source_layer: "ts".into(),
        target_contract_cid: name_to_cid["parseInt"].clone(),
        target_layer: "rust-kit".into(),
        ir_arg_sorts: vec!["String".into()],
        ir_return_sort: "Int".into(),
        notes: String::new(),
        signer_seed,
        target_proof_cid: None,
        callsite: None,
    };
    let bridge = mint_bridge(&bridge_args);
    members.insert(bridge.cid.clone(), bridge.canonical_bytes);

    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let input = ProofEnvelopeInput {
        name: "@test/load-all-proofs".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        members,
        signer_cid,
        signer_seed,
        declared_at: declared_at.into(),
    };
    let built = build_proof_envelope(&input);
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    let path = dir.join(format!("{hex}.proof"));
    fs::write(&path, &built.bytes).expect("write proof");
    built.cid
}

// ---------------------------------------------------------------------------
// Trivial cases
// ---------------------------------------------------------------------------

#[test]
fn nonexistent_project_root_returns_empty_pool() {
    let dir = std::env::temp_dir().join(format!(
        "sugar-rust-test-nonexistent-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    // Don't create it.
    let pool = load_all_proofs::run(&dir);
    assert_eq!(pool.mementos.len(), 0);
    assert_eq!(pool.bridges_by_symbol.len(), 0);
    assert_eq!(pool.load_errors.len(), 0);
}

#[test]
fn empty_dir_returns_empty_pool() {
    let dir = make_unique_dir("empty-dir");
    let pool = load_all_proofs::run(&dir);
    assert_eq!(pool.mementos.len(), 0);
    assert_eq!(pool.bridges_by_symbol.len(), 0);
    assert_eq!(pool.load_errors.len(), 0);
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn dir_with_unrelated_files_ignored() {
    let dir = make_unique_dir("unrelated-files");
    fs::write(dir.join("readme.txt"), b"hello").expect("write");
    fs::write(dir.join("config.yaml"), b"key: value").expect("write");
    let pool = load_all_proofs::run(&dir);
    assert_eq!(pool.mementos.len(), 0);
    assert_eq!(pool.load_errors.len(), 0);
    let _ = fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------------
// Happy path: round-trip a published .proof
// ---------------------------------------------------------------------------

#[test]
fn loads_published_proof_successfully() {
    let dir = make_unique_dir("loads-cleanly");
    let _cid = publish_parseint_proof(&dir);
    let pool = load_all_proofs::run(&dir);
    assert_eq!(
        pool.load_errors.len(),
        0,
        "no load errors expected; got {:?}",
        pool.load_errors
    );
    // 1 contract + 1 bridge = 2 mementos.
    assert_eq!(pool.mementos.len(), 2);
    // bridges_by_symbol indexes parseInt.
    assert!(pool.bridges_by_symbol.contains_key("parseInt"));
    let _ = fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------------
// Windows-safe filename: the colon-free `blake3-512_<hex>.proof` form loads.
// (Regression for the `:`-in-filename Windows problem.) The on-disk name has
// NO colon and retains the `blake3-512_` prefix; the loader recomputes the CID
// from bytes and indexes the mementos exactly as for the bare/colon forms.
// ---------------------------------------------------------------------------

#[test]
fn loads_colon_free_underscore_filename() {
    use sugar_proof_envelope::proof_filename;

    let dir = make_unique_dir("colon-free-filename");
    let cid = publish_parseint_proof(&dir);

    // Find the just-published proof and rename it to the canonical on-disk
    // (underscore) form produced by the shared helper.
    let entries: Vec<_> = fs::read_dir(&dir)
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("proof"))
        .collect();
    assert_eq!(entries.len(), 1);
    let original = entries[0].path();
    let underscore_name = proof_filename(&cid);
    assert!(
        !underscore_name.contains(':'),
        "on-disk filename must be colon-free for Windows: {underscore_name}"
    );
    assert!(
        underscore_name.starts_with("blake3-512_"),
        "on-disk filename must retain the blake3-512_ prefix: {underscore_name}"
    );
    let renamed = dir.join(&underscore_name);
    fs::rename(&original, &renamed).unwrap();

    let pool = load_all_proofs::run(&dir);
    assert_eq!(
        pool.load_errors.len(),
        0,
        "no load errors expected for the underscore filename; got {:?}",
        pool.load_errors
    );
    // 1 contract + 1 bridge = 2 mementos, identical to the bare/colon forms.
    assert_eq!(pool.mementos.len(), 2);
    assert!(pool.bridges_by_symbol.contains_key("parseInt"));
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn member_cids_in_pool_match_envelope_identities() {
    let dir = make_unique_dir("member-cid-match");
    let _ = publish_parseint_proof(&dir);
    let pool = load_all_proofs::run(&dir);
    for cid in pool.mementos.keys() {
        assert!(cid.starts_with("blake3-512:"));
        assert_eq!(cid.len(), "blake3-512:".len() + 128);
    }
    let _ = fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------------
// Rule 1 (trust root): filename CID must match content hash
// ---------------------------------------------------------------------------

#[test]
fn filename_cid_mismatch_is_rejected_with_rule_1_error() {
    let dir = make_unique_dir("rule-1");
    publish_parseint_proof(&dir);

    // Find the .proof and rename it to a wrong-hash filename.
    let entries: Vec<_> = fs::read_dir(&dir)
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("proof"))
        .collect();
    assert_eq!(entries.len(), 1);
    let original = entries[0].path();
    let bogus_hex = "0".repeat(128);
    let renamed = dir.join(format!("{bogus_hex}.proof"));
    fs::rename(&original, &renamed).unwrap();

    let pool = load_all_proofs::run(&dir);
    assert!(
        pool.load_errors.iter().any(|e| e.reason.contains("rule 1")),
        "expected rule 1 error; got {:?}",
        pool.load_errors
    );
    // No mementos indexed when the trust-root check fails.
    assert_eq!(pool.mementos.len(), 0);
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn non_hex_filename_is_rejected() {
    let dir = make_unique_dir("non-hex-filename");
    publish_parseint_proof(&dir);

    let entries: Vec<_> = fs::read_dir(&dir)
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("proof"))
        .collect();
    let original = entries[0].path();
    let renamed = dir.join("not-a-cid.proof");
    fs::rename(&original, &renamed).unwrap();

    let pool = load_all_proofs::run(&dir);
    assert!(
        pool.load_errors.iter().any(|e| e.reason.contains("rule 1")),
        "expected rule 1 (non-hex) error; got {:?}",
        pool.load_errors
    );
    let _ = fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------------
// Garbage input is rejected (CBOR decode errors land in load_errors)
// ---------------------------------------------------------------------------

#[test]
fn garbage_proof_file_with_correct_filename_lands_in_load_errors() {
    let dir = make_unique_dir("garbage");
    let bogus = b"this is not CBOR".to_vec();
    let cid = blake3_512_of(&bogus);
    let hex = cid.strip_prefix("blake3-512:").unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &bogus).expect("write");

    let pool = load_all_proofs::run(&dir);
    assert!(
        !pool.load_errors.is_empty(),
        "expected load error for garbage CBOR"
    );
    let _ = fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------------
// Multiple files in a directory
// ---------------------------------------------------------------------------

#[test]
fn multiple_proofs_in_one_dir_all_loaded() {
    let dir = make_unique_dir("multiple-proofs");
    publish_parseint_proof(&dir);

    // Publish a second proof with a different signer to get a different
    // catalog CID (a different filename).
    reset_collector();
    must("anotherContract", forall(Int(), |n| gt(n, num(1))));
    let decls = sugar_ir_symbolic::finish();
    let signer_seed: Ed25519Seed = [0x99u8; 32];
    let declared_at = "2026-04-30T01:00:00.000Z";
    let mut members: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    for d in &decls {
        let args = MintContractArgs {
            evidence_term: None,
            formals: Vec::new(),
            emit_empty_formals: false,
            formal_sorts: Vec::new(),
            library: None,
            body_discharge_eligible: true,
            body_discharge_refusal_reason: None,
            panic_loci: Vec::new(),
            class_shapes: Vec::new(),
            source_warrants: Vec::new(),
            contract_name: d.name.clone(),
            pre: d.pre.as_deref().map(formula_to_value),
            post: None,
            inv: None,
            out_binding: d.out_binding.clone(),
            produced_by: "rust-test@1.0".into(),
            produced_at: declared_at.into(),
            input_cids: vec![],
            authoring: Authoring::KitAuthor {
                author: "rust-test@1.0".into(),
                note: None,
            },
            signer_seed,
        };
        let m = mint_contract(&args).expect("mint");
        members.insert(m.cid, m.canonical_bytes);
    }
    let signer_cid = blake3_512_of(ed25519_pubkey_string(&signer_seed).as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@test/second".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        members,
        signer_cid,
        signer_seed,
        declared_at: declared_at.into(),
    });
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write");

    let pool = load_all_proofs::run(&dir);
    assert_eq!(pool.load_errors.len(), 0, "{:?}", pool.load_errors);
    // First proof: 1 contract + 1 bridge = 2; second: 1 contract = 1; total 3.
    assert_eq!(pool.mementos.len(), 3);
    let _ = fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------------
// Recursive walk: subdirs are scanned
// ---------------------------------------------------------------------------

#[test]
fn proofs_in_subdirectories_are_found() {
    let dir = make_unique_dir("subdirs");
    let sub = dir.join("nested").join("dir");
    fs::create_dir_all(&sub).unwrap();
    publish_parseint_proof(&sub);
    let pool = load_all_proofs::run(&dir);
    assert_eq!(pool.load_errors.len(), 0, "{:?}", pool.load_errors);
    assert_eq!(pool.mementos.len(), 2);
    let _ = fs::remove_dir_all(&dir);
}
