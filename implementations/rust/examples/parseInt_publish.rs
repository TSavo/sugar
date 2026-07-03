// SPDX-License-Identifier: Apache-2.0
//
// End-to-end Rust kit-as-author: writes a real .proof file containing
// a contract memento (parseInt's pre) + a bridge memento (TS-layer
// parseInt -> that contract). All signed, all in pure Rust.
//
// Mirrors implementations/cpp/sugar-ir-symbolic/example/parseInt_kit_proof.cpp.
//
// Pipeline:
//   1. Author the contract via kit primitives.
//   2. Mint each contract as a signed ClaimEnvelope (memento).
//   3. Mint the bridge referencing the contract's CID.
//   4. Bundle into a .proof catalog (deterministic CBOR).
//   5. Write <hex>.proof to the directory passed as argv[1].
//   6. Print the full self-identifying CID to stdout.

use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;

use sugar_canonicalizer::Value;
use sugar_claim_envelope::{
    mint_bridge, mint_contract_with_body_cid, Authoring, MintBridgeArgs, MintContractArgs,
};
use sugar_ir_symbolic::serialize::formula_to_value;
use sugar_ir_symbolic::{begin_collecting, finish, forall, gt, must, num, reset_collector, Int};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, AtomMemento, BridgeMemento, ClaimContractMemento,
    ContractBody, ContractMementoRef, Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};

fn register_contract_body_graph(
    proof_graph: &mut ProofGraph,
    pre: Option<&Arc<Value>>,
    post: Option<&Arc<Value>>,
    inv: Option<&Arc<Value>>,
) -> Result<ContractBody, String> {
    let mut slots: Vec<(&'static str, AtomMemento)> = Vec::new();
    if let Some(formula) = pre {
        slots.push((
            "pre",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if let Some(formula) = post {
        slots.push((
            "post",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if let Some(formula) = inv {
        slots.push((
            "inv",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if slots.is_empty() {
        return Err("contract body graph requires at least one formula slot".to_string());
    }

    let slot_refs = slots
        .iter()
        .map(|(slot, atom)| (*slot, atom))
        .collect::<Vec<_>>();
    Ok(proof_graph.register_body(ContractBody::from_slots(slot_refs)))
}

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().collect();
    let out_dir = if argv.len() >= 2 {
        PathBuf::from(&argv[1])
    } else {
        PathBuf::from(".")
    };

    if let Err(e) = fs::create_dir_all(&out_dir) {
        eprintln!("ERROR: cannot create out_dir {}: {e}", out_dir.display());
        return ExitCode::from(1);
    }

    // ----- 1. Author the contract via kit primitives -----
    reset_collector();
    begin_collecting();

    // parseInt's pre: forall n. n > 0. (Mirrors the C++ demo.)
    must("parseInt", forall(Int(), |n| gt(n, num(0))));

    let contract_decls = finish();

    // ----- 2. Mint each contract as a signed graph-backed ClaimEnvelope -----
    let signer_seed: Ed25519Seed = [0x42; 32]; // deterministic for the demo
    let declared_at = "2026-04-30T12:00:00.000Z";
    let produced_by = "rust-kit@1.0";

    let mut graph = ProofGraph::new();
    let mut contract_name_to_cid = std::collections::HashMap::<String, String>::new();

    for d in &contract_decls {
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
            proofir_provenance: None,
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
        let contract_body = match register_contract_body_graph(
            &mut graph,
            args.pre.as_ref(),
            args.post.as_ref(),
            args.inv.as_ref(),
        ) {
            Ok(body) => body,
            Err(e) => {
                eprintln!("ERROR: contract body graph({}): {e}", d.name);
                return ExitCode::from(1);
            }
        };
        let body_cid = contract_body.cid().as_str().to_string();
        let minted = match mint_contract_with_body_cid(&args, Some(&body_cid)) {
            Ok(m) => m,
            Err(e) => {
                eprintln!("ERROR: mint_contract_with_body_cid({}): {e}", d.name);
                return ExitCode::from(1);
            }
        };
        println!("  contract minted: {} -> CID {}", d.name, minted.cid);
        let memento = ClaimContractMemento::new(minted.canonical_bytes);
        assert_eq!(memento.cid().as_str(), minted.cid);
        contract_name_to_cid.insert(d.name.clone(), minted.cid);
        graph.push_claim_contract(memento);
    }

    // ----- 3. Mint the bridge: parseInt (TS surface) -> contract memento -----
    let parseint_target_cid = match contract_name_to_cid.get("parseInt") {
        Some(c) => c.clone(),
        None => {
            eprintln!("ERROR: parseInt contract was not minted");
            return ExitCode::from(1);
        }
    };
    let bridge_args = MintBridgeArgs {
        produced_by: produced_by.into(),
        produced_at: declared_at.into(),
        source_symbol: "parseInt".into(),
        source_layer: "ts".into(),
        target_contract: ContractMementoRef::new(parseint_target_cid),
        target_layer: "rust-kit".into(),
        ir_arg_sorts: vec!["String".into()],
        ir_return_sort: "Int".into(),
        notes: String::new(),
        signer_seed,
        target_proof_cid: None,
        callsite: None,
    };
    let minted_bridge = mint_bridge(&bridge_args);
    println!("  bridge   minted: parseInt -> CID {}", minted_bridge.cid);
    let bridge_memento = BridgeMemento::new(minted_bridge.canonical_bytes);
    assert_eq!(bridge_memento.cid().as_str(), minted_bridge.cid);
    graph.push_bridge(bridge_memento);

    // ----- 4. Bundle into a .proof catalog -----
    // Compute a real signer CID: hash the producer's public key bytes
    // (the public-key memento isn't authored in this demo, but we
    // produce a content-addressed signer reference).
    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = sugar_canonicalizer::blake3_512_of(signer_pubkey.as_bytes());

    let proof_input = ProofEnvelopeInput {
        name: "@example/rust-kit".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: declared_at.into(),
    };
    let built = build_proof_envelope(&proof_input);

    // ----- 5. Write <full-cid>.proof to disk -----
    // v1.1.0 filename shape is `blake3-512:<hex>.proof`: same as the
    // C++ and Go peers. Self-identifying so cross-language verifiers
    // can match by regex. The full self-identifying CID is also printed
    // to stdout for downstream consumers.
    let out_path = out_dir.join(format!("{}.proof", built.cid));
    if let Err(e) = fs::write(&out_path, &built.bytes) {
        eprintln!("ERROR: write to {} failed: {e}", out_path.display());
        return ExitCode::from(1);
    }
    println!(
        "\n  wrote .proof: {} ({} bytes, cid={})",
        out_path.display(),
        built.bytes.len(),
        built.cid
    );
    ExitCode::SUCCESS
}
