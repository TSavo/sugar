// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};

use sugar_canonicalizer::blake3_512_of;
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, ClaimContractMemento, ProofEnvelopeInput,
    ProofGraph,
};
use sugar_walk::envelope::register_function_contract_body_graph;
use sugar_walk::{
    build_function_contract, wrap_function_contract, wrap_function_contract_cached, EnvelopeCache,
    DEV_SIGNER_SEED,
};

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system clock")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "sugar-walk-envelope-bodycid-{}-{stamp}-{suffix}",
        std::process::id()
    ));
    fs::create_dir_all(&dir).expect("create temp proof dir");
    dir
}

fn fixture_contract(src: &str) -> sugar_walk::contract::FunctionContractMemento {
    let file: syn::File = syn::parse_str(src).expect("fixture source parses");
    let item_fn = file
        .items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) => Some(f),
            _ => None,
        })
        .expect("fixture contains a function");
    build_function_contract(&item_fn, None)
}

fn write_proof(dir: &Path, graph: ProofGraph) {
    let signer_pubkey = ed25519_pubkey_string(&DEV_SIGNER_SEED);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let proof = build_proof_envelope(&ProofEnvelopeInput {
        name: "@test/sugar-walk-envelope-bodycid".to_string(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed: DEV_SIGNER_SEED,
        declared_at: "2026-07-01T00:00:00Z".to_string(),
    });
    let hex = proof
        .cid
        .strip_prefix("blake3-512:")
        .expect("proof cid prefix");
    fs::write(dir.join(format!("{hex}.proof")), proof.bytes).expect("write proof");
}

#[test]
fn wrap_function_contract_proof_loads_through_verifier() {
    let dir = unique_dir("fresh");
    let contract = fixture_contract("fn inc(x: i64) -> i64 { x + 1 }");
    let produced_at = "2026-07-01T00:00:00Z";
    let env =
        wrap_function_contract(&contract, produced_at, &DEV_SIGNER_SEED).expect("wrap contract");

    let mut graph = ProofGraph::new();
    let _body =
        register_function_contract_body_graph(&mut graph, &contract, produced_at, &DEV_SIGNER_SEED)
            .expect("register contract body graph");
    graph.push_claim_contract(ClaimContractMemento::new(env.canonical_bytes));
    write_proof(&dir, graph);

    let pool = sugar_verifier::load_all_proofs::run(&dir);
    assert!(
        pool.load_errors.is_empty(),
        "verifier load errors: {:?}",
        pool.load_errors
    );
    assert_eq!(
        pool.body.len(),
        1,
        "proof graph must carry a body map entry"
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn cached_wrap_function_contract_proof_loads_through_verifier() {
    let dir = unique_dir("cached");
    let contract = fixture_contract("fn same(x: i64) -> i64 { x }");
    let produced_at = "2026-07-01T00:00:00Z";
    let mut cache = EnvelopeCache::new();

    let first = wrap_function_contract_cached(&contract, produced_at, &DEV_SIGNER_SEED, &mut cache)
        .expect("first wrap");
    let second =
        wrap_function_contract_cached(&contract, produced_at, &DEV_SIGNER_SEED, &mut cache)
            .expect("cached wrap");
    assert_eq!(cache.mints, 1);
    assert_eq!(cache.hits, 1);
    assert_eq!(first.canonical_bytes, second.canonical_bytes);

    let mut graph = ProofGraph::new();
    let _body =
        register_function_contract_body_graph(&mut graph, &contract, produced_at, &DEV_SIGNER_SEED)
            .expect("register contract body graph");
    graph.push_claim_contract(ClaimContractMemento::new(second.canonical_bytes));
    write_proof(&dir, graph);

    let pool = sugar_verifier::load_all_proofs::run(&dir);
    assert!(
        pool.load_errors.is_empty(),
        "verifier load errors: {:?}",
        pool.load_errors
    );
    assert_eq!(
        pool.body.len(),
        1,
        "proof graph must carry a body map entry"
    );
    let _ = fs::remove_dir_all(&dir);
}
