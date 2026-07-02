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

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, jcs_cid_of_json, Value as CValue};
use sugar_claim_envelope::{mint_bridge, MintBridgeArgs, MintedEnvelope};
use sugar_ir_symbolic::{forall, gt, must, num, reset_collector, Int};
use sugar_proof_envelope::{
    build_proof_envelope, cbor_encode_bstr, cbor_encode_map_head, cbor_encode_tstr,
    ed25519_pubkey_string, ed25519_sign_string, BridgeMemento, ContractBody, ContractMemento,
    ContractMementoRef, Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
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

/// Build a proper body-graph contract (atom → body → ContractMemento) and
/// register it in `graph`.  Returns the contract's member CID.  Tests that
/// load .proof files require contracts to carry a `bodyCid` pointer; the old
/// inline-body `ClaimContractMemento` path was rejected by the strict loader.
fn add_body_graph_contract(
    graph: &mut ProofGraph,
    name: &str,
    signer_seed: Ed25519Seed,
    declared_at: &str,
) -> String {
    // Dummy post atom — deterministic per name, content not checked by tests.
    let post_atom = FlatAtom::new(CValue::object([
        ("kind", CValue::string("contract-atom")),
        ("name", CValue::string(name.to_owned())),
    ]));
    let post_memento = graph.register_atom(post_atom);
    // register_contract asserts the metadata atom is present.
    graph.register_atom(FlatAtom::empty_metadata());
    let body = graph.register_body(ContractBody::new(&post_memento));
    let contract = ContractMemento::new_at(name, &body, signer_seed, declared_at);
    let cid = contract.cid().as_str().to_string();
    graph.register_contract(contract);
    cid
}

fn push_bridge(graph: &mut ProofGraph, minted: MintedEnvelope) -> String {
    let cid = minted.cid.clone();
    let memento = BridgeMemento::new(minted.canonical_bytes);
    assert_eq!(memento.cid().as_str(), cid);
    graph.push_bridge(memento);
    cid
}

fn flat_member_cid(env: &Json) -> String {
    let mut unsigned = env.clone();
    if let Json::Object(map) = &mut unsigned {
        map.shift_remove("cid");
        map.shift_remove("producerSignature");
    }
    jcs_cid_of_json(&unsigned)
}

fn write_minimal_member_proof(dir: &Path, member_cid: &str, member_bytes: &[u8]) -> String {
    let mut proof_bytes = Vec::new();
    cbor_encode_map_head(&mut proof_bytes, 1);
    cbor_encode_tstr(&mut proof_bytes, "members");
    cbor_encode_map_head(&mut proof_bytes, 1);
    cbor_encode_tstr(&mut proof_bytes, member_cid);
    cbor_encode_bstr(&mut proof_bytes, member_bytes);

    let proof_cid = blake3_512_of(&proof_bytes);
    let hex = proof_cid.strip_prefix("blake3-512:").unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &proof_bytes).expect("write proof");
    proof_cid
}

fn proof_bytes(label: &str, expected_cid: String, bytes: Vec<u8>) -> load_all_proofs::ProofBytes {
    load_all_proofs::ProofBytes::try_from_parts(label.to_string(), expected_cid, bytes)
        .expect("test proof CID must parse")
}

fn flat_source_member(signature: Option<String>) -> (String, Vec<u8>) {
    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let signer = ed25519_pubkey_string(&signer_seed);
    let mut env = json!({
        "signer": signer,
        "evidence": {
            "kind": "source-memento",
            "body": {
                "path": "src/lib.rs",
                "language": "rust"
            }
        }
    });
    if let Some(signature) = signature {
        env.as_object_mut()
            .expect("flat member object")
            .insert("producerSignature".to_string(), Json::String(signature));
    }
    let member_cid = flat_member_cid(&env);
    let member_bytes = serde_json::to_vec(&env).expect("member json");
    (member_cid, member_bytes)
}

fn publish_parseint_proof(dir: &Path) -> String {
    // Publish a real parseInt .proof via the Rust kit, return its CID.
    reset_collector();
    must("parseInt", forall(Int(), |n| gt(n, num(0))));
    let decls = sugar_ir_symbolic::finish();
    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let declared_at = "2026-04-30T00:00:00.000Z";
    let produced_by = "rust-test@1.0";
    let mut graph = ProofGraph::new();
    let mut name_to_cid = std::collections::HashMap::<String, String>::new();
    for d in &decls {
        let cid = add_body_graph_contract(&mut graph, &d.name, signer_seed, declared_at);
        name_to_cid.insert(d.name.clone(), cid);
    }
    let bridge_args = MintBridgeArgs {
        produced_by: produced_by.into(),
        produced_at: declared_at.into(),
        source_symbol: "parseInt".into(),
        source_layer: "ts".into(),
        target_contract: ContractMementoRef::new(name_to_cid["parseInt"].clone()),
        target_layer: "rust-kit".into(),
        ir_arg_sorts: vec!["String".into()],
        ir_return_sort: "Int".into(),
        notes: String::new(),
        signer_seed,
        target_proof_cid: None,
        callsite: None,
    };
    let bridge = mint_bridge(&bridge_args);
    push_bridge(&mut graph, bridge);

    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let input = ProofEnvelopeInput {
        name: "@test/load-all-proofs".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
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

fn only_proof_path(dir: &Path) -> PathBuf {
    let entries: Vec<_> = fs::read_dir(dir)
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("proof"))
        .collect();
    assert_eq!(entries.len(), 1);
    entries[0].path()
}

fn rename_to_wrong_content_cid(dir: &Path) -> PathBuf {
    let original = only_proof_path(dir);
    let bogus_hex = "0".repeat(128);
    let renamed = dir.join(format!("{bogus_hex}.proof"));
    fs::rename(&original, &renamed).unwrap();
    renamed
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
fn catalog_graph_sections_load_flat_atoms_and_pointer_bodies_by_cid() {
    let dir = make_unique_dir("catalog-graph-sections");
    let signer_seed: Ed25519Seed = [0x42u8; 32];
    let mut graph = ProofGraph::new();
    let atom = FlatAtom::new(CValue::object([
        ("kind", CValue::string("atom")),
        ("predicate", CValue::string("result = x")),
    ]));
    let atom_cid = atom.cid().as_str().to_string();
    let atom_bytes = atom.bytes().to_vec();
    let atom_memento = graph.register_atom(atom);
    let body = graph.register_body(ContractBody::new(&atom_memento));
    let body_cid = body.cid().as_str().to_string();
    let body_bytes = body.bytes().to_vec();
    let signer_cid = blake3_512_of(ed25519_pubkey_string(&signer_seed).as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@test/catalog-graph".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: "2026-04-30T00:00:00.000Z".into(),
    });
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write");

    let pool = load_all_proofs::run(&dir);
    assert_eq!(pool.load_errors.len(), 0, "{:?}", pool.load_errors);
    assert_eq!(
        pool.atoms.get(atom_cid.as_str()),
        Some(&atom_bytes),
        "flat atom bytes must live in the catalog `atoms` map under their CID"
    );
    assert_eq!(
        pool.body.get(body_cid.as_str()),
        Some(&body_bytes),
        "contract bodies must be pointer-only graph entries under their body CID"
    );
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

#[test]
fn invalid_member_signature_is_a_load_error() {
    let dir = make_unique_dir("invalid-member-signature");
    let wrong_seed: Ed25519Seed = [0x99u8; 32];
    let wrong_signature = ed25519_sign_string(&wrong_seed, b"not this member");
    let (member_cid, member_bytes) = flat_source_member(Some(wrong_signature));
    write_minimal_member_proof(&dir, &member_cid, &member_bytes);

    let pool = load_all_proofs::run(&dir);

    assert!(
        pool.load_errors.iter().any(|err| {
            err.reason.contains(&member_cid)
                && err.reason.contains("producerSignature does not verify")
        }),
        "invalid member signature must be a load error: {:#?}",
        pool.load_errors
    );
    assert!(
        !pool.mementos.contains_key(member_cid.as_str()),
        "member with invalid signature must not enter the pool"
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn unsigned_member_still_loads() {
    let dir = make_unique_dir("unsigned-member");
    let (member_cid, member_bytes) = flat_source_member(None);
    write_minimal_member_proof(&dir, &member_cid, &member_bytes);

    let pool = load_all_proofs::run(&dir);

    assert_eq!(
        pool.load_errors.len(),
        0,
        "unsigned members remain acceptable for now: {:#?}",
        pool.load_errors
    );
    assert!(
        pool.mementos.contains_key(member_cid.as_str()),
        "unsigned member must still enter the pool"
    );
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
fn filesystem_load_rejects_content_cid_mismatch() {
    let dir = make_unique_dir("rule-1");
    publish_parseint_proof(&dir);

    // Find the .proof and rename it to a wrong-hash filename.
    rename_to_wrong_content_cid(&dir);

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
fn explicit_proof_file_ingress_rejects_content_cid_mismatch() {
    let dir = make_unique_dir("explicit-file-rule-1");
    publish_parseint_proof(&dir);
    let forged_path = rename_to_wrong_content_cid(&dir);
    let mut pool = sugar_verifier::MementoPool::default();

    load_all_proofs::load_files_into_pool(&[forged_path], &mut pool);

    assert!(
        pool.load_errors.iter().any(|e| e.reason.contains("rule 1")),
        "expected explicit-file rule 1 error; got {:?}",
        pool.load_errors
    );
    assert_eq!(pool.mementos.len(), 0);
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn proof_bytes_ingress_rejects_content_cid_mismatch() {
    let dir = make_unique_dir("proof-bytes-rule-1");
    publish_parseint_proof(&dir);
    let proof_path = only_proof_path(&dir);
    let bytes = fs::read(&proof_path).expect("read proof bytes");
    let wrong_cid = format!("blake3-512:{}", "0".repeat(128));
    let mut pool = sugar_verifier::MementoPool::default();

    load_all_proofs::load_proof_bytes_into_pool(
        &[proof_bytes("forged proof bytes", wrong_cid.clone(), bytes)],
        &mut pool,
    );

    assert!(
        pool.load_errors.iter().any(|e| {
            e.reason.contains("expected proof CID")
                && e.reason.contains(&wrong_cid)
                && e.reason.contains("content hash")
        }),
        "expected proof-bytes trust-root error; got {:?}",
        pool.load_errors
    );
    assert_eq!(pool.mementos.len(), 0);
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn extra_project_merge_rejects_content_cid_mismatch() {
    let project = make_unique_dir("extra-project-base");
    let extra = make_unique_dir("extra-project-forged");
    publish_parseint_proof(&extra);
    rename_to_wrong_content_cid(&extra);

    let mut pool = load_all_proofs::run(&project);
    let extra_pool = load_all_proofs::run(&extra);
    pool.merge(extra_pool);

    assert!(
        pool.load_errors.iter().any(|e| e.reason.contains("rule 1")),
        "expected merged extra-project load error; got {:?}",
        pool.load_errors
    );
    assert_eq!(pool.mementos.len(), 0);
    let _ = fs::remove_dir_all(&project);
    let _ = fs::remove_dir_all(&extra);
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
    let mut graph = ProofGraph::new();
    for d in &decls {
        add_body_graph_contract(&mut graph, &d.name, signer_seed, declared_at);
    }
    let signer_cid = blake3_512_of(ed25519_pubkey_string(&signer_seed).as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@test/second".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
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
