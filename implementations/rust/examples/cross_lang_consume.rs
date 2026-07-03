// SPDX-License-Identifier: Apache-2.0
//
// THE RUST END-TO-END CROSS-LANGUAGE DEMO.
//
//   Rust signs Rust.
//   Rust calls a peer language (via the bridged kit primitive parseInt).
//   Rust detects parseInt(num(0)).
//
// Architecture (mirrors implementations/cpp/.../example/cross_lang_consumer.cpp):
//   1. A peer kit (C++ or Go) shipped a v1.1.0 .proof with parseInt's
//      precondition (forall n: Int. n > 0).
//   2. Rust consumer authors invariants via kit primitives parse_int(num(...))
//: every call emits a Ctor("parseInt", [arg]) IrTerm.
//   3. Rust consumer mints + signs its property mementos in pure Rust.
//   4. Rust consumer bundles them into its own .proof file in pure Rust.
//   5. Rust bridge enforcement runner walks both .proofs:
//        - load-all-proofs builds a unified CID pool.
//        - enumerate-callsites finds Ctor("parseInt", ...) inside Rust's properties.
//        - resolve-bridge-target hash-looks-up the bridge -> peer's contract memento.
//        - instantiate-obligation substitutes the call's arg into `forall n. n > 0`.
//        - solve-obligation invokes z3 (parallel via rayon).
//        - report aggregates.
//
//   parse_int(num(5)) -> instantiate `5 > 0` -> unsat -> DISCHARGED
//   parse_int(num(0)) -> instantiate `0 > 0` -> sat   -> UNSATISFIED
//
// Rust imports zero lines of the peer language. The connection is the
// protocol: bytes the peer kit produced, walked by the Rust verifier,
// closed by Z3.
//
// Usage:
//   cargo run --release --example cross_lang_consume <path-to-peer.proof>

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;

use sugar_canonicalizer::{blake3_512_of, Value};
use sugar_claim_envelope::{mint_contract_with_body_cid, Authoring, MintContractArgs};
use sugar_ir_symbolic::serialize::formula_to_value;
use sugar_ir_symbolic::{begin_collecting, eq, finish, must, num, parse_int, reset_collector};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, AtomMemento, ClaimContractMemento, ContractBody,
    Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};
use sugar_verifier::{ObligationVerdict, Runner, RunnerConfig};

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

fn copy_file(src: &Path, dst: &Path) -> std::io::Result<()> {
    if let Some(parent) = dst.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::copy(src, dst)?;
    Ok(())
}

fn run() -> Result<(), String> {
    let argv: Vec<String> = std::env::args().collect();
    if argv.len() < 2 {
        return Err(format!(
            "Usage: {} <path-to-peer-proof>",
            argv.first()
                .map(String::as_str)
                .unwrap_or("cross_lang_consume")
        ));
    }
    let peer_proof_path = PathBuf::from(&argv[1]);
    if !peer_proof_path.exists() {
        return Err(format!(
            "ERROR: peer .proof not found at {} -- regenerate the peer publisher first.",
            peer_proof_path.display()
        ));
    }

    // ---- 1. Lay out a project_root with the peer's .proof in node_modules ----
    let project_root = tempdir_unique("rust-cross-lang")?;
    // Pick a peer-kit layer label off the parent dir to make the
    // node_modules subdir self-explanatory in logs.
    let peer_label = peer_proof_path
        .parent()
        .and_then(Path::file_name)
        .and_then(|s| s.to_str())
        .map(|s| s.replace("/tmp/", "").replace("-out-v11", ""))
        .unwrap_or_else(|| "peer".into());
    let peer_node_dir = project_root
        .join("node_modules")
        .join("@example")
        .join(format!("{peer_label}-kit"));
    let peer_dst = peer_node_dir.join(
        peer_proof_path
            .file_name()
            .ok_or_else(|| "peer path has no filename".to_string())?,
    );
    copy_file(&peer_proof_path, &peer_dst).map_err(|e| {
        format!(
            "ERROR: failed to copy peer .proof to {}: {e}",
            peer_dst.display()
        )
    })?;
    println!("  installed peer .proof at: {}", peer_dst.display());

    // ---- 2. Author Rust-side invariants ----
    reset_collector();
    begin_collecting();

    // parse_int(num(5)) -- should DISCHARGE
    must(
        "calls-parseInt-with-positive-5",
        eq(parse_int(num(5)), num(5)),
    );
    // parse_int(num(0)) -- should be UNSATISFIED (caught by peer's precondition)
    must("calls-parseInt-with-zero", eq(parse_int(num(0)), num(0)));

    let decls = finish();
    if decls.len() != 2 {
        return Err(format!(
            "ERROR: expected 2 declarations, got {}",
            decls.len()
        ));
    }

    // ---- 3. Mint each graph-backed contract memento (Rust signs Rust) ----
    let signer_seed: Ed25519Seed = [0x37; 32];
    let declared_at = "2026-04-30T15:30:00.000Z";
    let produced_by = "rust-consumer@1";

    let mut graph = ProofGraph::new();
    let mut contract_names_by_cid: HashMap<String, String> = HashMap::new();
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
        let contract_body = register_contract_body_graph(
            &mut graph,
            args.pre.as_ref(),
            args.post.as_ref(),
            args.inv.as_ref(),
        )
        .map_err(|e| format!("contract body graph({}): {e}", d.name))?;
        let body_cid = contract_body.cid().as_str().to_string();
        let minted = mint_contract_with_body_cid(&args, Some(&body_cid))
            .map_err(|e| format!("mint_contract_with_body_cid({}): {e}", d.name))?;
        println!("  contract minted: {} -> CID {}", d.name, minted.cid);
        let memento = ClaimContractMemento::new(minted.canonical_bytes);
        assert_eq!(memento.cid().as_str(), minted.cid);
        contract_names_by_cid.insert(minted.cid.clone(), d.name.clone());
        graph.push_claim_contract(memento);
    }

    // ---- 4. Bundle the consumer's .proof file ----
    let catalog_seed: Ed25519Seed = [0x73; 32];
    let signer_pubkey = ed25519_pubkey_string(&catalog_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let proof_input = ProofEnvelopeInput {
        name: "@example/rust-consumer".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed: catalog_seed,
        declared_at: declared_at.into(),
    };
    let built = build_proof_envelope(&proof_input);
    let consumer_path = project_root.join(format!("{}.proof", built.cid));
    fs::write(&consumer_path, &built.bytes).map_err(|e| {
        format!(
            "ERROR: cannot write consumer .proof to {}: {e}",
            consumer_path.display()
        )
    })?;
    println!(
        "  Rust consumer .proof: {} ({} bytes)",
        consumer_path.display(),
        built.bytes.len()
    );

    // ---- 5. Run the Rust bridge enforcement runner ----
    let cfg = RunnerConfig {
        project_root: project_root.clone(),
        legacy_z3_fallback: Some(sugar_verifier::LegacyZ3Fallback::compat(
            std::env::var("SUGAR_Z3").unwrap_or_else(|_| "z3".into()),
        )),
        ..Default::default()
    };
    let runner = Runner::new(cfg);
    let report = runner.run();

    for le in &report.load_errors {
        println!("  load error: {}: {}", le.proof_path, le.reason);
    }

    let mut ok = true;
    if report.total_callsites != 2 {
        eprintln!("FAIL: expected 2 callsites, got {}", report.total_callsites);
        ok = false;
    }

    let mut passing: Option<&_> = None;
    let mut failing: Option<&_> = None;
    for row in &report.rows {
        let row_property_cid = row.callsite.property_cid.as_ref().map(ToString::to_string);
        let property_label = row_property_cid
            .as_ref()
            .and_then(|cid| contract_names_by_cid.get(cid))
            .map(String::as_str)
            .unwrap_or(row.callsite.property_name.as_str());
        let reason = if row.reason.is_empty() {
            String::new()
        } else {
            format!(" -- {}", row.reason)
        };
        println!("    {}: {}{}", property_label, row.status.as_str(), reason);
        if property_label == "calls-parseInt-with-positive-5" {
            passing = Some(row);
        } else if property_label == "calls-parseInt-with-zero" {
            failing = Some(row);
        }
    }

    match passing {
        None => {
            eprintln!("FAIL: missing positive-5 row");
            ok = false;
        }
        Some(r) if r.status != ObligationVerdict::Discharged => {
            eprintln!(
                "FAIL: parse_int(num(5)) status = {}, want discharged",
                r.status.as_str()
            );
            ok = false;
        }
        _ => {}
    }
    match failing {
        None => {
            eprintln!("FAIL: missing zero row");
            ok = false;
        }
        Some(r) if r.status != ObligationVerdict::Unsatisfied => {
            eprintln!(
                "FAIL: parse_int(num(0)) status = {}, want unsatisfied",
                r.status.as_str()
            );
            ok = false;
        }
        _ => {}
    }

    if ok {
        println!(
            "\n  DEMO: Rust verifier caught parse_int(num(0)) using the peer-authored precondition.\n    Discharged calls:  {}\n    Caught violations: {}",
            report.discharged, report.violations
        );
    }

    // best-effort cleanup; don't fail the demo if rmdir hiccups
    let _ = fs::remove_dir_all(&project_root);

    if ok {
        Ok(())
    } else {
        Err("one or more cells failed".into())
    }
}

fn tempdir_unique(prefix: &str) -> Result<PathBuf, String> {
    // Avoid pulling tempfile into the workspace's release build for
    // a single dir; mkdir under /tmp with a process-local nonce.
    let nonce = blake3_512_of(
        format!(
            "{}-{}-{}",
            prefix,
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        )
        .as_bytes(),
    );
    let suffix: String = nonce
        .trim_start_matches("blake3-512:")
        .chars()
        .take(12)
        .collect();
    let dir = std::env::temp_dir().join(format!("{prefix}-{suffix}"));
    fs::create_dir_all(&dir).map_err(|e| format!("mkdir {}: {e}", dir.display()))?;
    Ok(dir)
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("{e}");
            ExitCode::from(1)
        }
    }
}
