// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Unit tests for the cargo-test witness model. These exercise the PURE,
// deterministic core (parser, body shape, bundle, memento, contract IR, discharge
// logic) WITHOUT spawning `cargo test` -- a nested cargo invocation would recurse
// and is non-hermetic. The full run-the-suite path is exercised by the
// rust-witness-showcase example's run.sh (the end-to-end gate).

use super::*;
use sugar_proof_envelope::ed25519_verify_string;

const CC: &str = "blake3-512:code";
const RC: &str = "blake3-512:runtime";

fn w(test: &str, outcome: &str) -> Witness {
    // Mirror make_witness via the public body path so the test pins the SAME
    // canonical bytes the lifter emits.
    let body = witness_value(CC, RC, test, outcome, &["src/lib.rs".to_string()]);
    let bytes = encode_jcs(&body).into_bytes();
    let cid = blake3_512_of(&bytes);
    Witness {
        code_cid: CC.to_string(),
        runtime_cid: RC.to_string(),
        test_id: test.to_string(),
        outcome: outcome.to_string(),
        code_files: vec!["src/lib.rs".to_string()],
        cid,
    }
}

// ------- PARSER -------

const SAMPLE_OUTPUT: &str = r#"
running 3 tests
test tests::adds_two ... ok
test math::tests::subtracts ... FAILED
test tests::skipped_one ... ignored
test result: FAILED. 1 passed; 1 failed; 1 ignored; 0 measured; 0 filtered out
"#;

#[test]
fn parser_extracts_outcomes_and_drops_summary() {
    let parsed = parse_cargo_test_output(SAMPLE_OUTPUT);
    assert_eq!(parsed.len(), 3, "three per-test lines, summary excluded");
    assert_eq!(parsed[0].test_id, "tests::adds_two");
    assert_eq!(parsed[0].raw, "ok");
    assert_eq!(parsed[1].test_id, "math::tests::subtracts");
    assert_eq!(parsed[1].raw, "failed");
    assert_eq!(parsed[2].raw, "ignored");
}

#[test]
fn parser_ignored_tests_drop_from_witnesses() {
    let parsed = parse_cargo_test_output(SAMPLE_OUTPUT);
    let ws = witnesses_from_parsed(&parsed, CC, RC, &["src/lib.rs".to_string()]);
    // ignored is dropped: only the ok + FAILED survive.
    assert_eq!(ws.len(), 2);
    assert_eq!(ws[0].outcome, "passed");
    assert_eq!(ws[1].outcome, "failed");
}

#[test]
fn parser_ignores_non_test_lines() {
    let parsed = parse_cargo_test_output("Compiling foo v0.1.0\nrunning 0 tests\nFinished\n");
    assert!(parsed.is_empty());
}

#[test]
fn failed_child_without_test_rows_refuses_with_exit_and_stderr() {
    let error = witnesses_from_cargo_run(
        false,
        Some(101),
        "",
        "error[E0308]: mismatched types",
        CC,
        RC,
        &["src/lib.rs".to_string()],
    )
    .unwrap_err();

    assert!(error.contains("cargo test failed before producing test testimony"));
    assert!(error.contains("exitCode=101"));
    assert!(error.contains("error[E0308]: mismatched types"));
}

#[test]
fn successful_zero_test_run_remains_an_honest_empty_suite() {
    let witnesses = witnesses_from_cargo_run(
        true,
        Some(0),
        "running 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n",
        "",
        CC,
        RC,
        &["src/lib.rs".to_string()],
    )
    .unwrap();

    assert!(witnesses.is_empty());
}

#[test]
fn successful_output_without_test_population_testimony_refuses() {
    let error = witnesses_from_cargo_run(
        true,
        Some(0),
        "Finished test profile target(s)",
        "",
        CC,
        RC,
        &["src/lib.rs".to_string()],
    )
    .unwrap_err();

    assert!(error.contains("cargo test produced no test-population testimony"));
}

// ------- PER-TEST BODY SHAPE -------

#[test]
fn per_test_body_has_exact_jcs_shape() {
    let body = witness_body(&w("tests::foo", "passed"));
    let s = String::from_utf8(body).unwrap();
    // JCS sorts keys alphabetically: codeCid, codeFiles, kind, outcome, runtimeCid, test
    let expected = format!(
        r#"{{"codeCid":"{CC}","codeFiles":"src/lib.rs","kind":"cargo-test-witness","outcome":"passed","runtimeCid":"{RC}","test":"tests::foo"}}"#
    );
    assert_eq!(s, expected);
}

#[test]
fn body_blake3s_to_its_cid() {
    let wit = w("tests::foo", "passed");
    assert_eq!(blake3_512_of(&witness_body(&wit)), wit.cid);
}

// ------- BUNDLE DETERMINISM -------

#[test]
fn bundle_is_deterministic_and_sorted() {
    let a = vec![w("tests::b", "passed"), w("tests::a", "passed")];
    let b = vec![w("tests::a", "passed"), w("tests::b", "passed")];
    let (buf_a, cid_a, sorted_a) = build_bundle(&a);
    let (buf_b, cid_b, _) = build_bundle(&b);
    // Same inputs (any order) -> same bytes -> same cid.
    assert_eq!(cid_a, cid_b, "bundle cid is order-independent");
    assert_eq!(buf_a, buf_b);
    // Sorted by test id.
    assert_eq!(sorted_a[0].test_id, "tests::a");
    assert_eq!(sorted_a[1].test_id, "tests::b");
    // bundle_cid = blake3 of the bytes.
    assert_eq!(blake3_512_of(&buf_a), cid_a);
    // Each line + trailing newline; two witnesses -> two newlines.
    assert_eq!(buf_a.iter().filter(|&&b| b == b'\n').count(), 2);
}

#[test]
fn bundle_lines_each_address_their_witness() {
    let ws = vec![w("tests::a", "passed"), w("tests::b", "failed")];
    let (buf, _, sorted) = build_bundle(&ws);
    let s = String::from_utf8(buf).unwrap();
    for (line, wit) in s.lines().zip(sorted.iter()) {
        assert_eq!(
            blake3_512_of(line.as_bytes()),
            wit.cid,
            "each bundle line content-addresses its own witness"
        );
    }
}

// ------- MEMENTO (signed pointer) -------

#[test]
fn memento_signature_verifies_over_bundle_cid() {
    let ws = vec![w("tests::a", "passed")];
    let (_, cid, _) = build_bundle(&ws);
    let m = witness_package_memento(
        &cid,
        &[".".to_string()],
        &["src/lib.rs".to_string()],
        1,
        1,
        Some(WITNESS_SIGNER_SEED),
    )
    .unwrap();
    assert_eq!(m["witness_cid"], cid);
    assert_eq!(m["witness_kind"], "cargo-test-witness-package");
    let signer = m["signer"].as_str().unwrap();
    let signature =
        sugar_proof_envelope::Signature::try_parse(m["signature"].as_str().unwrap().to_string())
            .expect("witness signature must parse");
    // The rust verifier checks the mark with THIS primitive, over the cid bytes.
    assert!(
        ed25519_verify_string(signer, &signature, cid.as_bytes()),
        "memento signature must verify over the bundle cid (the verifier's check)"
    );
    // A wrong message must NOT verify (discrimination).
    assert!(!ed25519_verify_string(signer, &signature, b"not the cid"));
}

#[test]
fn memento_has_no_top_level_outcome_so_verifier_proceeds_to_recompute() {
    // The verifier refuses a memento whose top-level outcome == "failed". A
    // PACKAGE memento must NOT carry one (the per-test outcomes live in the
    // bundle), so an all-passed-or-not suite proceeds to recompute uniformly.
    let m = witness_package_memento(
        "blake3-512:x",
        &[".".to_string()],
        &[],
        2,
        1,
        Some(WITNESS_SIGNER_SEED),
    )
    .unwrap();
    assert!(m.get("outcome").is_none());
}

// ------- CONTRACT IR + PROOFDATA -------

#[test]
fn proof_data_is_sorted_compact_json() {
    let pd = witness_package_proof_data(
        "blake3-512:bundle",
        &["b.rs".to_string(), "a.rs".to_string()],
        &["src/lib.rs".to_string()],
        3,
        3,
    );
    // sort_keys=True, separators=(",",":"); keys sorted: codeFiles, count, kind,
    // packageCid, passed, testFiles. testFiles sorted within.
    let expected = r#"{"codeFiles":["src/lib.rs"],"count":3,"kind":"witness-package","packageCid":"blake3-512:bundle","passed":3,"testFiles":["a.rs","b.rs"]}"#;
    assert_eq!(pd, expected);
}

#[test]
fn contract_ir_carries_custom_evidence_pinning_bundle_cid() {
    let cid = "blake3-512:bundle";
    let ir = witness_package_contract_ir(cid, RC, &[".".to_string()], &[], 1, 1);
    assert_eq!(ir["kind"], "contract");
    assert_eq!(ir["name"], format!("witness-package:{cid}"));
    assert_eq!(ir["inv"]["name"], "witnessed");
    let cert = &ir["evidence"]["certificate"];
    assert_eq!(ir["evidence"]["proofType"], "custom");
    assert_eq!(cert["tool"], "cargo-test");
    assert_eq!(cert["version"], RC);
    assert_eq!(cert["formulaHash"], cid);
    let warrants = ir["proofirProvenance"]["warrants"]
        .as_array()
        .expect("witness package contract must carry proofirProvenance warrants");
    assert_eq!(
        warrants.len(),
        1,
        "witness package emits one execution-witness provenance kind"
    );
    assert_eq!(
        warrants[0]["kind"], "Derived",
        "cargo-test witness packages are recomputed execution testimony, not source-stated facts"
    );
    // proofData round-trips and pins the SAME package cid.
    let pd = parse_evidence_proof_data(&serde_json::to_string(&ir["evidence"]).unwrap()).unwrap();
    assert_eq!(pd["packageCid"], cid);
    assert_eq!(pd["kind"], "witness-package");
}

// ------- ROUND TRIP: build bundle -> recompute logic reproduces the cid -------

#[test]
fn round_trip_rebuild_reproduces_bundle_cid() {
    // The recompute branch's invariant: rebuilding the bundle from the SAME
    // witnesses yields the SAME cid. (recompute_bundle_body adds the cargo run;
    // here we isolate the determinism the recompute check relies on.)
    let ws = vec![
        w("tests::a", "passed"),
        w("tests::c", "passed"),
        w("tests::b", "passed"),
    ];
    let (_, cid1, _) = build_bundle(&ws);
    // Re-run with a shuffled order (what a fresh suite run might surface).
    let mut shuffled = ws.clone();
    shuffled.reverse();
    let (_, cid2, _) = build_bundle(&shuffled);
    assert_eq!(cid1, cid2, "recompute must reproduce the pinned bundle cid");
}

// ------- DISCHARGE LOGIC (the all-passed teeth, isolated from cargo) -------
//
// discharge_bundle itself spawns cargo; here we prove the DECISION the example
// gate hinges on: a reproducing bundle with a failing test is REFUSED, an
// all-passed one would discharge. We exercise the pure decision via the bundle
// shape (the same all-passed test discharge_bundle applies after reproduction).

#[test]
fn a_failing_test_in_the_bundle_is_the_refusal_signal() {
    let good = vec![w("tests::a", "passed"), w("tests::b", "passed")];
    let bad = vec![w("tests::a", "passed"), w("tests::b", "failed")];
    let good_failed = good.iter().filter(|x| x.outcome != "passed").count();
    let bad_failed = bad.iter().filter(|x| x.outcome != "passed").count();
    assert_eq!(good_failed, 0, "all-passed suite discharges");
    assert_eq!(bad_failed, 1, "a failing test refuses the whole package");
    // The good and bad suites have DIFFERENT bundle cids (different bodies), so a
    // failing run cannot borrow a passing package's cid.
    let (_, good_cid, _) = build_bundle(&good);
    let (_, bad_cid, _) = build_bundle(&bad);
    assert_ne!(good_cid, bad_cid);
}

// ------- PER-TEST RECOMPUTE + ANTI-TAMPER (the python pytest-witness parity) ----
//
// The per-test resolve arm. `recompute_one_test_body` takes the runner as an
// INJECTED closure so these prove the guard's behavior (and whether the runner
// ran) WITHOUT nesting a real `cargo test`. Production wires `run_one_test_witness`.

#[test]
fn per_test_recompute_returns_rerun_body_when_memento_reconstructs() {
    // A per-test memento whose fields reconstruct its cid: the pre-check passes,
    // the (injected) runner re-runs the single test, and the rebuilt body blake3's
    // to the SAME cid (the witness reproduced).
    let wit = w("tests::adds_two_numbers", "passed");
    let ran = std::cell::Cell::new(false);
    let body = recompute_one_test_body(
        &wit.cid,
        &wit.code_cid,
        &wit.runtime_cid,
        &wit.test_id,
        &wit.outcome,
        &wit.code_files,
        |tid, cfs| {
            ran.set(true);
            // The runner re-runs the test and returns its witness. Here the test
            // still passes, so the returned witness is byte-identical to the probe.
            assert_eq!(tid, "tests::adds_two_numbers");
            assert_eq!(cfs, &["src/lib.rs".to_string()]);
            Ok(w(tid, "passed"))
        },
    )
    .expect("a reconstructing memento must resolve");
    assert!(
        ran.get(),
        "the runner MUST have executed once the pre-check passed"
    );
    // The returned body is the re-run body; it blake3's to the pinned cid (the
    // witness reproduced) -- this is what the verifier checks itself.
    assert_eq!(blake3_512_of(&body), wit.cid);
}

#[test]
fn per_test_recompute_returns_failed_body_when_test_now_fails() {
    // A re-run whose outcome FLIPPED (the test now fails) returns a `failed` body,
    // NOT the probe's `passed` body. Its cid differs from the pinned passed cid, so
    // the verifier's reproduction check refuses -- the teeth. The guard does NOT
    // verify outcome; reproduction does, downstream.
    let wit = w("tests::adds_two_numbers", "passed");
    let body = recompute_one_test_body(
        &wit.cid,
        &wit.code_cid,
        &wit.runtime_cid,
        &wit.test_id,
        &wit.outcome,
        &wit.code_files,
        |tid, _cfs| Ok(w(tid, "failed")), // the test now fails
    )
    .expect("pre-check passes (memento is consistent); the re-run body is returned");
    // The body is the FAILED witness body; it does NOT reproduce the pinned cid.
    assert_ne!(blake3_512_of(&body), wit.cid);
    let failed = w("tests::adds_two_numbers", "failed");
    assert_eq!(blake3_512_of(&body), failed.cid);
}

#[test]
fn anti_tamper_refuses_before_running_when_memento_does_not_reconstruct() {
    // A per-test memento whose fields DON'T reconstruct its pinned cid: the
    // pre-check fails and the runner is NEVER invoked. This is the security
    // property -- never execute a path from a memento that doesn't hash to its own
    // cid. The AtomicBool DIRECTLY proves non-execution.
    use std::sync::atomic::{AtomicBool, Ordering};
    let wit = w("tests::adds_two_numbers", "passed");
    let tampered_cid = "blake3-512:deadbeefdeadbeef"; // not the body's real cid
    assert_ne!(tampered_cid, wit.cid);
    let executed = AtomicBool::new(false);
    let res = recompute_one_test_body(
        tampered_cid,
        &wit.code_cid,
        &wit.runtime_cid,
        &wit.test_id,
        &wit.outcome,
        &wit.code_files,
        |_tid, _cfs| {
            executed.store(true, Ordering::SeqCst);
            panic!("the runner MUST NOT execute on a tampered memento");
        },
    );
    let err = res.expect_err("a tampered memento must be REFUSED");
    // Byte-for-byte the python guard message shape.
    assert!(
        err.contains(&format!(
            "memento fields do not reconstruct witness_cid {tampered_cid}"
        )),
        "guard message must name the pinned cid; got: {err}"
    );
    assert!(
        err.contains("refusing to re-run a tampered memento"),
        "guard message must state the refusal; got: {err}"
    );
    assert!(
        !executed.load(Ordering::SeqCst),
        "the runner MUST NOT have run -- anti-tamper is a PRE-check"
    );
}

// ------- CID-FILENAME convention -------

#[test]
fn cid_filename_replaces_colon_with_underscore() {
    let proof_name = sugar_proof_envelope::proof_filename("blake3-512:abc");
    let proof_stem = proof_name
        .strip_suffix(".proof")
        .expect("proof filename suffix");
    assert_eq!(
        cid_filename("blake3-512:abc", ".witness"),
        format!("{proof_stem}.witness")
    );
}

// ------- sugar.enumerate PRIMITIVES -------
//
// There is no `lift` kit method: full-tree construction is `sugar.enumerate`
// over the SourceTree (#6222). These pin the two decisions the wire glue in
// `bin/witness_rpc.rs` delegates here -- file IDENTITY and the universe ANCHOR
// -- so neither can drift without a red test. They do not spawn `cargo test`.

/// A scratch crate laid out the way `discover_rust_files` walks: `.rs` under
/// the project root, `target/` skipped.
fn scratch_project(tag: &str) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "sugar-witness-enumerate-{tag}-{}-{}",
        std::process::id(),
        blake3_512_of(tag.as_bytes())
            .chars()
            .rev()
            .take(12)
            .collect::<String>()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("src")).expect("mkdir scratch src");
    dir
}

#[test]
fn file_memento_mints_identity_through_the_shared_content_door() {
    let dir = scratch_project("identity");
    let body = "pub fn one() -> u32 { 1 }\n";
    std::fs::write(dir.join("src").join("lib.rs"), body).expect("write source");

    let memento = file_source_memento(&dir, "src/lib.rs").expect("seal the locator");

    assert_eq!(memento["kind"], "source-memento");
    assert_eq!(memento["file"], "src/lib.rs");
    // The CID is the content address of the DECODED utf-8 bytes -- the same
    // door `path_source` uses python-side. A kit minting its own identity would
    // address the same file differently than every other kit.
    assert_eq!(memento["source_cid"], blake3_of(body.as_bytes()));
    // A whole file has no single body span or AST template.
    assert!(memento["span"].is_null(), "file locator carries no span");
    assert!(
        memento["template_cid"].is_null(),
        "file locator carries no ast template"
    );
    assert_eq!(memento["function_name"], "");

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn undecodable_source_is_a_loud_error_never_a_made_up_identity() {
    let dir = scratch_project("undecodable");
    // Lone 0x80 continuation byte: valid to read, invalid utf-8.
    std::fs::write(dir.join("src").join("lib.rs"), [0x80u8]).expect("write source");

    let sealed = file_source_memento(&dir, "src/lib.rs");

    let reason = sealed.expect_err("undecodable source must not seal a locator");
    assert!(
        reason.contains("src/lib.rs") && reason.contains("utf-8"),
        "the gap must name the file and why it could not be sealed: {reason}"
    );

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn missing_source_is_a_loud_error_never_a_made_up_identity() {
    let dir = scratch_project("missing");

    let sealed = file_source_memento(&dir, "src/absent.rs");

    let reason = sealed.expect_err("an absent file must not seal a locator");
    assert!(
        reason.contains("src/absent.rs"),
        "the gap must name the file it could not read: {reason}"
    );

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn universe_anchor_is_the_first_sealable_code_file_in_sorted_order() {
    let dir = scratch_project("anchor");
    std::fs::write(dir.join("src").join("zeta.rs"), "pub fn z() {}\n").expect("write zeta");
    std::fs::write(dir.join("src").join("alpha.rs"), "pub fn a() {}\n").expect("write alpha");

    let anchor = enumerate_anchor_file(&dir).expect("a readable code file anchors the universe");

    // The witness package is a WHOLE-SUITE artifact emitted at exactly one
    // file; sorted order is what makes that one file deterministic.
    assert_eq!(anchor, "src/alpha.rs");

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn universe_anchor_skips_a_file_that_gapped_in_the_census() {
    let dir = scratch_project("anchor-gap");
    // `alpha.rs` sorts first but cannot be sealed, so it has no memento to be
    // asked `at` and can never be the anchor.
    std::fs::write(dir.join("src").join("alpha.rs"), [0x80u8]).expect("write alpha");
    std::fs::write(dir.join("src").join("beta.rs"), "pub fn b() {}\n").expect("write beta");

    let anchor = enumerate_anchor_file(&dir).expect("the sealable file anchors the universe");

    assert_eq!(anchor, "src/beta.rs");

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn a_project_with_no_sealable_code_file_has_no_anchor() {
    let dir = scratch_project("anchor-none");

    assert!(
        enumerate_anchor_file(&dir).is_none(),
        "no readable code file means an empty universe, not a fabricated anchor"
    );

    let _ = std::fs::remove_dir_all(&dir);
}
