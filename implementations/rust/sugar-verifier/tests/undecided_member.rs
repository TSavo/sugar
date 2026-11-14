// SPDX-License-Identifier: MIT OR Apache-2.0
//
// The `undecided` member end to end on the prove side (step 8, step 9):
//   - mint_undecided -> ProofGraph -> .proof bytes -> load_all_proofs::run:
//     the member loads with no load error, and decodes back to exactly what
//     was minted (symbol, site, reason);
//   - every header field is in the CID preimage: a different symbol, site or
//     reason is a different member CID;
//   - add_undecided_members: one row per member, status `undecidable`,
//     reason `owed: <owner>: <observed>`, the site as its locus, and
//     `owed` counts it.

use std::fs;
use std::path::PathBuf;

use sugar_canonicalizer::{blake3_512_of, cid_hex};
use sugar_claim_envelope::{mint_undecided, MintUndecidedArgs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, AtomCid, Ed25519Seed, ProofEnvelopeInput,
    ProofGraph, UndecidedMember, UndecidedMemento, UndecidedReason, UndecidedSite,
};
use sugar_verifier::{load_all_proofs, ObligationVerdict, Report};

const SEED: Ed25519Seed = [0x42u8; 32];
const AT: &str = "2026-11-13T00:00:00.000Z";

fn make_unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-undecided-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn refused_f() -> UndecidedMember {
    UndecidedMember {
        symbol: Some("python:m.f".into()),
        site: UndecidedSite {
            file: "m.py".into(),
            source_cid: AtomCid::try_parse(format!("blake3-512:{}", "a".repeat(128))).unwrap(),
            start_line: 4,
            start_col: 0,
            end_line: 5,
            end_col: 20,
        },
        reason: UndecidedReason::Refused {
            owner: "proofir.scope".into(),
            observed: "illegal free var(s): LIMIT".into(),
        },
    }
}

fn minted_cid(member: UndecidedMember) -> String {
    mint_undecided(&MintUndecidedArgs {
        produced_by: "rust-test@1.0".into(),
        produced_at: AT.into(),
        member,
        signer_seed: SEED,
    })
    .cid
}

fn publish(dir: &std::path::Path, members: &[UndecidedMember]) {
    let mut graph = ProofGraph::new();
    for member in members {
        let minted = mint_undecided(&MintUndecidedArgs {
            produced_by: "rust-test@1.0".into(),
            produced_at: AT.into(),
            member: member.clone(),
            signer_seed: SEED,
        });
        let memento = UndecidedMemento::new(minted.canonical_bytes);
        assert_eq!(memento.cid().as_str(), minted.cid);
        graph.push_undecided(memento);
    }
    let signer_pubkey = ed25519_pubkey_string(&SEED);
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "@test/undecided".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid: blake3_512_of(signer_pubkey.as_bytes()),
        signer_seed: SEED,
        declared_at: AT.into(),
        manifest: None,
    });
    let hex = cid_hex(&built.cid).unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
}

#[test]
fn an_undecided_member_loads_and_decodes_to_what_was_minted() {
    let dir = make_unique_dir("loads");
    publish(&dir, &[refused_f()]);
    let pool = load_all_proofs::run_prove_inputs(&dir);
    assert!(pool.load_errors.is_empty(), "{:?}", pool.load_errors);
    let members: Vec<_> = pool.undecided_members().collect();
    assert_eq!(members.len(), 1);
    let (cid, stored) = members[0];
    assert_eq!(cid.as_str(), minted_cid(refused_f()));
    let decoded = UndecidedMember::from_stored(stored).expect("decodes");
    assert_eq!(decoded, refused_f());
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn every_header_field_is_in_the_member_cid() {
    let base = minted_cid(refused_f());
    let mut other_symbol = refused_f();
    other_symbol.symbol = None;
    let mut other_site = refused_f();
    other_site.site.start_line = 5;
    let mut other_file = refused_f();
    other_file.site.file = "n.py".into();
    let mut other_reason = refused_f();
    other_reason.reason = UndecidedReason::Unanswered;
    let mut other_observed = refused_f();
    other_observed.reason = UndecidedReason::Refused {
        owner: "proofir.scope".into(),
        observed: "illegal free var(s): OTHER".into(),
    };
    let cids = [
        minted_cid(other_symbol),
        minted_cid(other_site),
        minted_cid(other_file),
        minted_cid(other_reason),
        minted_cid(other_observed),
    ];
    for cid in &cids {
        assert_ne!(cid, &base);
    }
    // The same member mints to the same CID.
    assert_eq!(minted_cid(refused_f()), base);
}

#[test]
fn prove_reports_each_member_owed_and_undecidable() {
    let dir = make_unique_dir("owed");
    let mut g = refused_f();
    g.symbol = Some("python:m.test_f".into());
    g.site.start_line = 8;
    publish(&dir, &[refused_f(), g]);
    let pool = load_all_proofs::run_prove_inputs(&dir);
    assert!(pool.load_errors.is_empty(), "{:?}", pool.load_errors);
    let mut report = Report::default();
    sugar_verifier::report::add_undecided_members(&pool, &mut report);
    assert_eq!(report.owed, 2);
    assert_eq!(report.violations, 0);
    let mut names: Vec<_> = report
        .rows
        .iter()
        .map(|row| {
            assert_eq!(row.status, ObligationVerdict::Undecidable);
            assert_eq!(
                row.reason,
                "owed: proofir.scope: illegal free var(s): LIMIT"
            );
            assert_eq!(row.callsite.file.as_deref(), Some("m.py"));
            (row.callsite.property_name.clone(), row.callsite.line)
        })
        .collect();
    names.sort();
    assert_eq!(
        names,
        vec![
            ("undecided:python:m.f".to_string(), Some(4)),
            ("undecided:python:m.test_f".to_string(), Some(8)),
        ]
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn an_unanswered_member_without_a_symbol_names_its_site() {
    let dir = make_unique_dir("unanswered");
    let mut call = refused_f();
    call.symbol = None;
    call.reason = UndecidedReason::Unanswered;
    publish(&dir, &[call]);
    let pool = load_all_proofs::run_prove_inputs(&dir);
    assert!(pool.load_errors.is_empty(), "{:?}", pool.load_errors);
    let mut report = Report::default();
    sugar_verifier::report::add_undecided_members(&pool, &mut report);
    assert_eq!(report.owed, 1);
    assert_eq!(report.rows[0].callsite.property_name, "undecided:m.py:4");
    assert_eq!(
        report.rows[0].reason,
        "owed: no contract for m.py:4 in this proof"
    );
    let _ = fs::remove_dir_all(&dir);
}
