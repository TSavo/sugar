// SPDX-License-Identifier: Apache-2.0
//
//! Raw-AST recognizer ratchet (IDD Phase-3 migration tracker).
//!
//! Scans every `src/sugar/*.rs` file and counts files whose `recognize`
//! function still takes a raw `&Expr`, `&Stmt`, or `&Item` parameter
//! instead of `&SourceFragment`. The count is R(t) -- the migration state.
//!
//! `RAW_SYN_CEILING` pins today's measured value. The test fails RED if
//! R(t) exceeds the ceiling -- a new raw recognizer was added or a migration
//! was reverted. Tighten the ceiling IN THE SAME PR when a recognizer is
//! migrated to `&SourceFragment`.
//!
//! Target: R(t) = 0 (all recognizers take `&SourceFragment`).

use std::fs;
use std::path::PathBuf;

/// Pinned ceiling. NEVER raise this value; only lower it as recognizers
/// are migrated to `&SourceFragment`.
///
/// Measured on this branch: all 125 sugar files that define a `recognize`
/// function still take raw `&Expr`, `&Stmt`, or `&Item`. This is the
/// starting point of the migration ratchet.
const RAW_SYN_CEILING: usize = 125;

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// All `.rs` files directly under `src/sugar/` (no subdirectories).
fn sugar_rs_files() -> Vec<PathBuf> {
    let dir = manifest_dir().join("src/sugar");
    let mut files: Vec<_> = fs::read_dir(&dir)
        .expect("read src/sugar/")
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.file_type().map(|ft| ft.is_file()).unwrap_or(false)
                && e.path().extension().map(|x| x == "rs").unwrap_or(false)
        })
        .map(|e| e.path())
        .collect();
    files.sort();
    files
}

/// Returns `true` if `src` contains a `fn recognize(` whose parameter list
/// mentions `&Expr`, `&Stmt`, or `&Item` (raw syn types not yet migrated to
/// `&SourceFragment`).
///
/// Handles both single-line and multi-line function signatures by scanning a
/// 400-char window after each `fn recognize(` occurrence and stopping at the
/// opening `{` of the function body.
fn is_raw_recognizer(src: &str) -> bool {
    let needle = "fn recognize(";
    let mut pos = 0_usize;
    while pos < src.len() {
        let Some(rel) = src[pos..].find(needle) else {
            break;
        };
        // Window starts just after the opening `(`
        let sig_start = pos + rel + needle.len();
        let window_end = (sig_start + 400).min(src.len());
        let window = &src[sig_start..window_end];
        // Signature ends at the first `{` (function body open brace)
        let sig_end = window.find('{').unwrap_or(window.len());
        let signature = &window[..sig_end];
        if signature.contains("&Expr")
            || signature.contains("&Stmt")
            || signature.contains("&Item")
        {
            return true;
        }
        pos += rel + 1;
    }
    false
}

#[test]
fn raw_ast_recognizer_ratchet() {
    let files = sugar_rs_files();
    let mut unmigrated: Vec<String> = files
        .iter()
        .filter_map(|path| {
            let src = fs::read_to_string(path)
                .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
            if is_raw_recognizer(&src) {
                Some(path.file_name().unwrap().to_string_lossy().into_owned())
            } else {
                None
            }
        })
        .collect();
    unmigrated.sort();

    let r_t = unmigrated.len();
    eprintln!("--- raw-AST recognizer ratchet ---");
    eprintln!("R(t) = {r_t}  (ceiling = {RAW_SYN_CEILING}, target = 0)");
    if !unmigrated.is_empty() {
        eprintln!("Remaining files with raw-syn recognizers ({r_t}):");
        for f in &unmigrated {
            eprintln!("  src/sugar/{f}");
        }
        eprintln!(
            "Migrate each to `fn recognize(frag: &SourceFragment, ...) -> Option<Box<dyn Sugar>>`"
        );
    }

    assert!(
        r_t <= RAW_SYN_CEILING,
        "RATCHET REGRESSION: raw-syn recognizer count {r_t} exceeds ceiling \
         {RAW_SYN_CEILING}. A recognizer was added or reverted to raw syn.\n\
         Migrate to &SourceFragment and lower RAW_SYN_CEILING. Remaining ({r_t}):\n{}",
        unmigrated
            .iter()
            .map(|f| format!("  src/sugar/{f}"))
            .collect::<Vec<_>>()
            .join("\n")
    );

    if r_t < RAW_SYN_CEILING {
        eprintln!(
            "RATCHET IMPROVED: R(t) = {r_t} < ceiling {RAW_SYN_CEILING}. \
             Tighten RAW_SYN_CEILING to {r_t} in this PR."
        );
    }
}
