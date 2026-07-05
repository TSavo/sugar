// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Cross-kit pin generator for `claim_envelope` byte-equivalence tests in
// other kits (python, cpp, csharp, go). Run with --nocapture to print
// the canonical fixture's hex bytes, attestation CID, and contractSetCid.
// The python kit pins the printed values verbatim and asserts byte
// equality.
//
// Usage:
//   cargo test -p sugar-claim-envelope --test cross_kit_pin -- --nocapture
//
// Reproducibility: the only inputs are this file's hard-coded constants
// (seed [0x42; 32], canonical produced_at, canonical formulas). Output
// is deterministic across runs by construction.

use std::sync::Arc;

use sugar_canonicalizer::Value;
use sugar_claim_envelope::{
    compute_contract_set_cid, contract_cid, mint_contract, Authoring, MintContractArgs,
};
use sugar_proof_envelope::Ed25519Seed;

fn seed() -> Ed25519Seed {
    [0x42u8; 32]
}

/// Canonical pre formula: `forall n: Int. n > 0`.
/// Matches `pre_n_gt_0()` in `tests/mint_contract.rs`. Stable shape.
fn pre_n_gt_0() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("forall")),
        ("name", Value::string("n")),
        (
            "sort",
            Value::object([
                ("kind", Value::string("primitive")),
                ("name", Value::string("Int")),
            ]),
        ),
        (
            "body",
            Value::object([
                ("kind", Value::string("atomic")),
                ("name", Value::string(">")),
                (
                    "args",
                    Value::array(vec![
                        Value::object([
                            ("kind", Value::string("var")),
                            ("name", Value::string("n")),
                        ]),
                        Value::object([
                            ("kind", Value::string("const")),
                            ("value", Value::integer(0)),
                            (
                                "sort",
                                Value::object([
                                    ("kind", Value::string("primitive")),
                                    ("name", Value::string("Int")),
                                ]),
                            ),
                        ]),
                    ]),
                ),
            ]),
        ),
    ])
}

/// Canonical post formula: `out = 0` (atomic equality).
fn post_out_eq_0() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("atomic")),
        ("name", Value::string("=")),
        (
            "args",
            Value::array(vec![
                Value::object([
                    ("kind", Value::string("var")),
                    ("name", Value::string("out")),
                ]),
                Value::object([
                    ("kind", Value::string("const")),
                    ("value", Value::integer(0)),
                    (
                        "sort",
                        Value::object([
                            ("kind", Value::string("primitive")),
                            ("name", Value::string("Int")),
                        ]),
                    ),
                ]),
            ]),
        ),
    ])
}

/// Canonical fixture args used by every kit's cross-kit byte test.
fn fixture_args() -> MintContractArgs {
    MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        bridge_source_symbol: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: None,
        contract_name: "demo".into(),
        pre: Some(pre_n_gt_0()),
        post: Some(post_out_eq_0()),
        inv: None,
        out_binding: "out".into(),
        produced_by: "rust-test@1.0".into(),
        produced_at: "2026-04-30T00:00:00.000Z".into(),
        input_cids: vec![],
        authoring: Authoring::KitAuthor {
            author: "rust-test@1.0".into(),
            note: None,
        },
        signer_seed: seed(),
    }
}

/// Second canonical fixture for contractSetCid pinning. Different name.
fn fixture_args_second() -> MintContractArgs {
    let mut a = fixture_args();
    a.contract_name = "second".into();
    a
}

#[test]
fn print_canonical_claim_envelope_bytes() {
    let m = mint_contract(&fixture_args()).expect("mint");
    println!();
    println!("# canonical claim-envelope fixture (contract: demo)");
    println!(
        "CLAIM_ENVELOPE_FIXTURE_BYTES_HEX = \"{}\"",
        hex::encode(&m.canonical_bytes)
    );
    println!("CLAIM_ENVELOPE_FIXTURE_CID = \"{}\"", m.cid);
    println!(
        "CLAIM_ENVELOPE_FIXTURE_CONTRACT_CID = \"{}\"",
        m.contract_cid
    );

    // Direct contract_cid() call must equal m.contract_cid (signer-independent).
    let direct = contract_cid(&fixture_args());
    assert_eq!(direct, m.contract_cid);
}

#[test]
fn print_canonical_contract_set_cid() {
    let cid_a = contract_cid(&fixture_args());
    let cid_b = contract_cid(&fixture_args_second());
    let set_cid = compute_contract_set_cid(vec![cid_a.clone(), cid_b.clone()]);
    println!();
    println!("# canonical contractSetCid fixture (2 contracts: demo, second)");
    println!("CONTRACT_A_CID = \"{}\"", cid_a);
    println!("CONTRACT_B_CID = \"{}\"", cid_b);
    println!("CONTRACT_SET_CID = \"{}\"", set_cid);

    // Order-independence sanity: reversing input gives same set CID.
    let set_cid_rev = compute_contract_set_cid(vec![cid_b, cid_a]);
    assert_eq!(set_cid, set_cid_rev);
}
