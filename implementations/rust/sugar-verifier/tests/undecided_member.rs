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
//     `owed` counts it;
//   - a member the join answers (its symbol bound to an imported contract)
//     is not owed; a member with no symbol at the same line still is.

use std::fs;
use std::path::PathBuf;

use sugar_canonicalizer::{blake3_512_of, cid_hex};
use sugar_claim_envelope::{mint_undecided, MintUndecidedArgs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, AtomCid, Ed25519Seed, MementoCid, MementoPool,
    ProofEnvelopeInput, ProofGraph, UndecidedMember, UndecidedMemento, UndecidedReason,
    UndecidedSite,
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

/// Step 9: an imported proof's own owed members are that proof's debt. They
/// are carried as the import's state and never counted in the importing
/// project's `owed`; the project's own member still is.
#[test]
fn an_imported_proofs_owed_members_are_its_own_never_the_importers() {
    let dir = make_unique_dir("imported-owed");
    let imports = dir.join(".sugar").join("imports");
    fs::create_dir_all(&imports).expect("mkdir imports");
    let mut vendor_a = refused_f();
    vendor_a.symbol = Some("python:b64vendor.ord".into());
    vendor_a.site.file = "b64vendor.py".into();
    let mut vendor_b = vendor_a.clone();
    vendor_b.site.start_line = 9;
    publish(&imports, &[vendor_a, vendor_b]);
    let mut own = refused_f();
    own.symbol = Some("python:test_consumer.helper".into());
    own.site.file = "test_consumer.py".into();
    publish(&dir, &[own]);

    let pool = load_all_proofs::run_prove_inputs(&dir);
    assert!(pool.load_errors.is_empty(), "{:?}", pool.load_errors);
    assert_eq!(pool.undecided_members().count(), 3);
    let mut report = Report::default();
    sugar_verifier::report::add_undecided_members(&pool, &mut report);

    assert_eq!(report.owed, 1, "only the project's own member is owed");
    assert_eq!(report.violations, 0);
    assert_eq!(report.rows.len(), 1);
    assert_eq!(
        report.rows[0].callsite.file.as_deref(),
        Some("test_consumer.py")
    );
    assert_eq!(report.imported.len(), 2, "the import's members are carried");
    assert_eq!(report.imported_owed(), 2);
    for row in &report.imported {
        assert_eq!(row.status, ObligationVerdict::Undecidable);
        assert_eq!(row.callsite.file.as_deref(), Some("b64vendor.py"));
    }
    let _ = fs::remove_dir_all(&dir);
}

/// The pool form of a minted `undecided` member: its header, `cid` included.
fn undecided_envelope(member: &UndecidedMember) -> serde_json::Value {
    let mut header = member.header_preimage();
    header["cid"] = serde_json::Value::String(member.header_cid());
    serde_json::json!({ "header": header })
}

fn pool_cid(raw: String) -> MementoCid {
    MementoCid::try_parse(raw).expect("a blake3-512 CID")
}

/// One line of a consumer test: `assert encodeBase64("xyz") == "eHl6"`.
/// The call is the unanswered member with the import door's symbol; the
/// `==` on its result is a second member at the same line with no symbol.
fn consumer_line_nine() -> (UndecidedMember, UndecidedMember) {
    let site = |start_col, end_col| UndecidedSite {
        file: "test_consumer.py".into(),
        source_cid: AtomCid::try_parse(format!("blake3-512:{}", "c".repeat(128))).unwrap(),
        start_line: 9,
        start_col,
        end_line: 9,
        end_col,
    };
    let call = UndecidedMember {
        symbol: Some("python:b64vendor.encodeBase64".into()),
        site: site(11, 28),
        reason: UndecidedReason::Unanswered,
    };
    let compare = UndecidedMember {
        symbol: None,
        site: site(11, 38),
        reason: UndecidedReason::Unanswered,
    };
    (call, compare)
}

fn consumer_pool(staged: bool) -> MementoPool {
    let (call, compare) = consumer_line_nine();
    let mut pool = MementoPool::default();
    for member in [&call, &compare] {
        let cid = pool_cid(member.header_cid());
        pool.insert_unanchored_for_tests(cid, undecided_envelope(member));
    }
    if staged {
        // The vendor's proof: a contract stating a post for the symbol, and
        // the bridge from the symbol to it.
        let contract_cid = blake3_512_of(b"vendor-encodeBase64-contract");
        pool.insert_unanchored_for_tests(
            pool_cid(contract_cid.clone()),
            serde_json::json!({
                "evidence": {
                    "kind": "contract",
                    "body": {
                        "contractName": "encodeBase64",
                        "formals": ["value"],
                        "outBinding": "out",
                        "post": {
                            "kind": "atomic",
                            "name": "=",
                            "args": [
                                {"kind": "var", "name": "out"},
                                {"kind": "var", "name": "value"}
                            ]
                        }
                    }
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            pool_cid(blake3_512_of(b"vendor-encodeBase64-bridge")),
            serde_json::json!({
                "evidence": {
                    "kind": "bridge",
                    "body": {
                        "sourceSymbol": "python:b64vendor.encodeBase64",
                        "targetContractCid": contract_cid
                    }
                }
            }),
        );
    }
    pool
}

fn owed_names(pool: &MementoPool) -> Vec<String> {
    let mut report = Report::default();
    sugar_verifier::report::add_undecided_members(pool, &mut report);
    assert_eq!(report.owed, report.rows.len());
    let mut names: Vec<_> = report
        .rows
        .iter()
        .map(|row| row.callsite.property_name.clone())
        .collect();
    names.sort();
    names
}

#[test]
fn a_member_the_join_answers_is_not_owed() {
    // Unstaged: nothing answers the call; both members are owed.
    assert_eq!(
        owed_names(&consumer_pool(false)),
        vec![
            "undecided:python:b64vendor.encodeBase64".to_string(),
            "undecided:test_consumer.py:9".to_string(),
        ]
    );
    // Staged: the join binds the call's symbol to the vendor's contract, so
    // the call is answered and leaves `owed`. The `==` member at the same
    // line names no symbol: nothing joins it, and it stays owed under its
    // site, `undecided:test_consumer.py:9`.
    assert_eq!(
        owed_names(&consumer_pool(true)),
        vec!["undecided:test_consumer.py:9".to_string()]
    );
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
