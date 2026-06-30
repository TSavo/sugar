// SPDX-License-Identifier: Apache-2.0
//
//! Raw-AST recognizer ratchet (IDD Phase-3 migration tracker).
//!
//! Scans every `src/sugar/*.rs` file and counts files whose `recognize`
//! function is NOT yet fully migrated. A recognizer counts as MIGRATED
//! only when BOTH conditions hold:
//!   (a) it takes `&SourceFragment` (not raw `&Expr`/`&Stmt`/`&Item`), AND
//!   (b) its body contains NO `as_expr()`/`as_stmt()`/`as_item()` call and
//!       no raw `Expr::`/`Stmt::`/`Item::` match arm access.
//!
//! A signature-flipped-but-shimmed recognizer (body calls `as_expr()` etc.)
//! still counts toward R(t) -- as_expr*/raw-access = residual.
//!
//! `RAW_SYN_CEILING` pins today's measured value. The test fails RED if
//! R(t) exceeds the ceiling. Tighten the ceiling IN THE SAME PR when a
//! recognizer is fully migrated (body logic rewritten to use SourceFragment
//! typed accessors with no as_expr/as_stmt/as_item shim).
//!
//! Target: R(t) = 0 (all recognizers fully migrated, no shim residual).

use std::fs;
use std::path::PathBuf;

/// Pinned ceiling. NEVER raise this value; only lower it as recognizers are
/// fully migrated away from as_expr*/as_stmt*/as_item* shims.
///
/// Post-shim baseline (Phase-3 linchpin): 124 files have `fn recognize`
/// taking `&SourceFragment` but still shim via `as_expr()`/`as_stmt()`/
/// `as_item()` in the body. factory.rs is excluded (doc comment only,
/// no real function body).
const RAW_SYN_CEILING: usize = 124;

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

/// Returns `true` if `src` contains a `fn recognize(` that is NOT yet fully
/// migrated. A recognizer is residual when:
///   - its signature has `&Expr`, `&Stmt`, or `&Item` (old raw syn), OR
///   - its signature has `&SourceFragment` AND its body calls
///     `as_expr()`, `as_stmt()`, or `as_item()` (transitional shim).
///
/// Handles both single-line and multi-line function signatures by scanning a
/// 400-char window after each `fn recognize(` occurrence and stopping at the
/// opening `{` of the function body. Then scans 2000 chars of body for shim
/// indicators.
fn is_raw_recognizer(src: &str) -> bool {
    let needle = "fn recognize(";
    let mut pos = 0_usize;
    while pos < src.len() {
        let Some(rel) = src[pos..].find(needle) else {
            break;
        };
        let sig_start = pos + rel + needle.len();
        let window_end = (sig_start + 400).min(src.len());
        let window = &src[sig_start..window_end];
        let Some(brace) = window.find('{') else {
            pos += rel + 1;
            continue;
        };
        let signature = &window[..brace];

        // Old raw syn: parameter is still &Expr, &Stmt, or &Item
        if signature.contains("&Expr")
            || signature.contains("&Stmt")
            || signature.contains("&Item")
        {
            return true;
        }

        // Shim residual: signature uses &SourceFragment but body still escapes
        // back to raw syn via as_expr()/as_stmt()/as_item() accessors.
        if signature.contains("&SourceFragment") {
            let body_start = sig_start + brace + 1;
            let body_end = (body_start + 2000).min(src.len());
            let body = &src[body_start..body_end];
            if body.contains("as_expr()")
                || body.contains("as_stmt()")
                || body.contains("as_item()")
            {
                return true;
            }
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
        eprintln!("Remaining files with shim residual ({r_t}):");
        for f in &unmigrated {
            eprintln!("  src/sugar/{f}");
        }
        eprintln!(
            "Migrate each: rewrite body to use &SourceFragment typed accessors, \
             remove as_expr()/as_stmt()/as_item() shim call."
        );
    }

    assert!(
        r_t <= RAW_SYN_CEILING,
        "RATCHET REGRESSION: residual recognizer count {r_t} exceeds ceiling \
         {RAW_SYN_CEILING}. A recognizer was added or reverted to raw syn / shim.\n\
         Migrate to &SourceFragment typed accessors and lower RAW_SYN_CEILING. Remaining ({r_t}):\n{}",
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
