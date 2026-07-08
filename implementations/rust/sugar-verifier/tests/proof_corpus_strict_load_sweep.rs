// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Proof-corpus strict-load sweep (#3840 follow-up).
//
// #3840 tightened `libsugar`'s contract-field decode from silent-default to
// loud: a `pre`/`post`/`formalSorts`/`returnSort` field (or a required effect
// sub-field) that is PRESENT but fails to deserialize now panics instead of
// silently collapsing to the same default an ABSENT field gets (see
// `implementations/rust/libsugar/src/core/types.rs`'s `solver_input_field`,
// `solver_input_vec_field`, `parse_effect_set`, and `parse_effect`).
//
// This test is the receipt that every `.proof` file currently committed to
// the repository still loads cleanly through the CURRENT (strict)
// `load_all_proofs` path: no panic anywhere in the walk. It is a permanent
// regression guard -- a future `.proof` fixture with a malformed field that
// the OLD loader would have silently swallowed fails this test the moment it
// lands, rather than riding along as a vacuous green.
//
// `load_all_proofs::run` walks its `project_root` argument itself, so
// pointing it at the repository root sweeps every `.proof` file in one call;
// `find_proof_files` below is an independent walk used only to assert the
// sweep actually covered a non-empty, known set of files (so the test can't
// pass vacuously if the corpus goes to zero) and to name them in the
// receipt.

use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-verifier has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn find_proof_files(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for entry in walkdir::WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_map(|entry| entry.ok())
    {
        if entry.file_type().is_file()
            && entry.path().extension().and_then(|ext| ext.to_str()) == Some("proof")
        {
            out.push(entry.path().to_path_buf());
        }
    }
    out.sort();
    out
}

#[test]
fn every_committed_proof_file_loads_without_panicking_through_the_strict_loader() {
    let root = repo_root();
    let proof_files = find_proof_files(&root);

    // A vacuous sweep (zero fixtures) would pass trivially without proving
    // anything about the strict loader. Fail loud instead so a corpus that
    // silently disappears (e.g. an accidental .gitignore) is caught here.
    assert!(
        !proof_files.is_empty(),
        "expected at least one committed .proof fixture under {}; the sweep \
         would otherwise pass vacuously",
        root.display()
    );

    // `run` re-walks `root` itself and drives every member through the
    // current strict decode path. A panic anywhere in that walk (this
    // process, this test binary) fails this test rather than being caught
    // and swallowed -- that IS the assertion: the corpus loads clean.
    let pool = sugar_verifier::load_all_proofs::run(&root);

    eprintln!(
        "proof-corpus-strict-load-sweep: {} .proof file(s) found, {} memento(s) loaded, {} load_errors",
        proof_files.len(),
        pool.mementos.len(),
        pool.load_errors.len(),
    );
    for file in &proof_files {
        eprintln!("  scanned: {}", file.display());
    }
    for error in &pool.load_errors {
        eprintln!("  load_error: {} -- {}", error.proof_path, error.reason);
    }
}
