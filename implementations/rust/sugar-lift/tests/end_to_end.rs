// SPDX-License-Identifier: MIT OR Apache-2.0
//
// End-to-end integration tests for sugar-lift.
//
// 1. Walk the planted `tests/fixtures/` directory.
// 2. Lift adapters mint per-shape ContractDecls.
// 3. Bundle into a `.proof` catalog.
// 4. Re-load through sugar-verifier::load_all_proofs and assert
//    every member envelope passes the trust-root + CID-redrive checks.

use std::path::{Path, PathBuf};
use std::process::Command;

use sugar_lift::{lift_and_mint, lift_path, mint_proof, LiftOptions};

fn fixtures_dir() -> PathBuf {
    let manifest = env!("CARGO_MANIFEST_DIR");
    Path::new(manifest).join("tests").join("fixtures")
}

#[test]
fn lifts_contracts_from_fixtures() {
    let report = lift_path(&fixtures_dir());
    let contracts = report
        .adapter_reports
        .iter()
        .find(|a| a.adapter == "contracts")
        .unwrap();
    assert!(
        contracts.lifted >= 3,
        "expected >=3 contracts lifts, got {} ({} seen, {} warnings)",
        contracts.lifted,
        contracts.seen,
        contracts.warnings.len()
    );
}

#[test]
fn proof_cid_is_deterministic_across_runs() {
    // Run lift_and_mint twice over the same fixture tree and assert the
    // resulting catalog CID is identical. This pins content-addressed
    // determinism: same inputs, same canonical IR, same blake3-512 CID.
    let nanos1 = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let dir1 =
        std::env::temp_dir().join(format!("sugar-lift-det1-{}-{nanos1}", std::process::id()));
    let dir2 =
        std::env::temp_dir().join(format!("sugar-lift-det2-{}-{nanos1}", std::process::id()));
    let opts = LiftOptions::default();
    let (_r1, m1, _p1) = lift_and_mint(&fixtures_dir(), &dir1, &opts).expect("first run");
    let (_r2, m2, _p2) = lift_and_mint(&fixtures_dir(), &dir2, &opts).expect("second run");
    assert_eq!(
        m1.cid, m2.cid,
        "lift catalog CID must be deterministic across runs"
    );
    assert_eq!(
        m1.member_count, m2.member_count,
        "member count must be stable across runs"
    );
    let _ = std::fs::remove_dir_all(&dir1);
    let _ = std::fs::remove_dir_all(&dir2);
}

#[test]
fn lifted_proof_loads_through_verifier() {
    // Use a tempdir keyed off the test name + nanos so parallel tests
    // don't collide.
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let out_dir =
        std::env::temp_dir().join(format!("sugar-lift-it-{}-{nanos}", std::process::id()));
    std::fs::create_dir_all(&out_dir).unwrap();
    let opts = LiftOptions::default();
    let (_report, minted, path) =
        lift_and_mint(&fixtures_dir(), &out_dir, &opts).expect("lift_and_mint");
    assert!(path.exists(), "proof file written");
    assert!(minted.member_count >= 3);

    let pool = sugar_verifier::load_all_proofs::run(&out_dir);
    assert!(
        pool.load_errors.is_empty(),
        "verifier load errors: {:?}",
        pool.load_errors
    );
    assert!(
        pool.mementos.len() >= minted.member_count,
        "verifier indexed fewer mementos ({}) than minted ({})",
        pool.mementos.len(),
        minted.member_count
    );
    let _ = std::fs::remove_dir_all(&out_dir);
}

#[test]
fn dedup_collapses_identical_ir_across_files() {
    // Build two declarations with identical IR via the contracts adapter.
    let src = r#"
        #[requires(x > 0)]
        #[ensures(ret >= 0)]
        fn p_equal_42(x: i64) -> i64 { x }
    "#;
    let f = syn::parse_file(src).unwrap();
    let a = sugar_lift_contracts::lift_file(&f, "a.rs");
    let b = sugar_lift_contracts::lift_file(&f, "b.rs");
    let mut decls = a.decls;
    // Same name same IR: should dedup at mint.
    decls.extend(b.decls);
    assert_eq!(decls.len(), 2);

    let opts = LiftOptions::default();
    let minted = mint_proof(&decls, &opts).expect("mint");
    assert_eq!(
        minted.member_count, 1,
        "two identical-IR contracts should collapse to one minted member"
    );
    assert_eq!(minted.deduplicated, 1);
}

#[test]
fn name_collision_on_different_ir_conjoins_for_the_solver() {
    // Two facts asserted under the same name (x == 42 and x == 99) are NOT a
    // mint-time error. They conjoin into ONE contract whose invariant is
    // (x == 42) ∧ (x == 99). That conjunction is unsatisfiable -- but detecting
    // the contradiction is the SOLVER's job, not the lifter's. The substrate's
    // job is to assemble the honest total fact about the name and hand it on;
    // routing the contradiction to the solver is the whole point of the system.
    let a_src = r#"
        #[requires(x == 42)]
        fn p_eq(x: i64) -> i64 { x }
    "#;
    let b_src = r#"
        #[requires(x == 99)]
        fn p_eq(x: i64) -> i64 { x }
    "#;
    let af = syn::parse_file(a_src).unwrap();
    let bf = syn::parse_file(b_src).unwrap();
    let mut decls = sugar_lift_contracts::lift_file(&af, "a.rs").decls;
    decls.extend(sugar_lift_contracts::lift_file(&bf, "b.rs").decls);
    let opts = LiftOptions::default();
    let minted = mint_proof(&decls, &opts)
        .expect("distinct facts under one name conjoin; they do not fail at mint");
    assert_eq!(
        minted.member_count, 1,
        "the two p_eq facts coalesce into one conjoined contract"
    );
    assert_eq!(
        minted.deduplicated, 0,
        "distinct facts are conjoined, not deduplicated"
    );
}

#[test]
fn cli_runs_against_fixtures() {
    // Smoke-test the run_cli entry by pointing it at the fixtures dir.
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let out = std::env::temp_dir().join(format!("sugar-lift-cli-{}-{nanos}", std::process::id()));
    let flags = sugar_lift::CliFlags {
        workspace: Some(fixtures_dir()),
        target_dir: Some(out.clone()),
        quiet: true,
        rpc: false,
    };
    let code = sugar_lift::run_cli(flags);
    assert_eq!(code, 0);
    let entries: Vec<_> = std::fs::read_dir(&out)
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().map(|x| x == "proof").unwrap_or(false))
        .collect();
    assert!(
        !entries.is_empty(),
        "expected at least one .proof file in {out:?}"
    );
    let _ = std::fs::remove_dir_all(&out);
}

#[test]
fn unknown_arg_exits_nonzero() {
    let output = Command::new(env!("CARGO_BIN_EXE_sugar-lift"))
        .arg("--definitely-not-a-flag")
        .output()
        .expect("spawn sugar-lift");

    assert!(
        !output.status.success(),
        "unknown argument must not proceed with exit 0"
    );
    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("sugar-lift: unrecognized argument: --definitely-not-a-flag"),
        "stderr should name the unknown argument, got {stderr:?}"
    );
    assert!(
        stderr.contains("sugar-lift: try --help"),
        "stderr should include usage hint, got {stderr:?}"
    );
}
