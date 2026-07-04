// SPDX-License-Identifier: MIT OR Apache-2.0
//! Go/no-go probe for the rust-analyzer hover type-resolution refinement.
//!
//! The hover refinement's parser is unit-tested against SYNTHETIC markdown
//! (`core::result::Result` as the first fenced block). What no test confirms is
//! what LIVE rust-analyzer actually renders at a method-ident position on the
//! real census shape -- it might emit the module path, an `impl<T> Result<T,E>`
//! header, or the `pub fn unwrap(...)` signature first (which the parser
//! correctly REFUSES). If it refuses, hover is inert and silently falls back to
//! the def-file-stem -- a false foundation for the Tier work stacked on it.
//!
//! This probe points a cold-spawned `RaOracle` at a standalone fixture whose
//! `.unwrap()` receiver is a workspace-local std-`Result` expression
//! (`serde_json::to_string(value).unwrap()`), then:
//!   1. prints the RAW hover markdown (the assumed-but-unseen input),
//!   2. runs it through the public parser,
//!   3. drives `resolve_typed_classified`,
//!   4. prints a PASS/FAIL discrimination verdict: PASS iff the stem came from
//!      HOVER (`stem_source == "hover"`), not merely that the final stem is right.
//!
//! Usage:  hover_probe <crate-root> [<src-rel-path>]
//!   defaults: crate-root="examples/oracle-hover-fixture", src="src/lib.rs"
//! Requires SUGAR_RESOLVE_ORACLE=rust-analyzer (set here if unset).
//! Exit: 0 = PASS (hover fired), 3 = NO-GO (hover inert / refused),
//!       2 = could not run (oracle/RA unavailable).

use std::path::PathBuf;
use sugar_walk::ra_oracle::{type_stem_from_hover_markdown, RaOracle, ResolveQuery};

/// Locate the method-ident position of the first `.<method>(` in `src` and
/// return (lsp_line, lsp_col), both 0-based (LSP). proc-macro2 columns are
/// already 0-based and the production pipeline uses `span.line - 1` for the LSP
/// line; this mirrors that. ASCII fixture, so byte offset == UTF-16 offset.
fn locate_method(src: &str, method: &str) -> Option<(u32, u32)> {
    let needle = format!(".{method}");
    for (i, line) in src.lines().enumerate() {
        // Skip comment lines: the fixture's doc block contains the call shape as
        // PROSE (`serde_json::to_string(value).unwrap()`), and pointing RA at a
        // comment position resolves to nothing (a false NO-GO). Only real code.
        if line.trim_start().starts_with("//") {
            continue;
        }
        if let Some(dot) = line.find(&needle) {
            let col = dot + 1; // char index of the ident start, just past the '.'
            return Some((i as u32, col as u32));
        }
    }
    None
}

fn main() {
    // Init a stderr tracing subscriber so the ra_oracle readiness/quiescence and
    // per-request round-trip logs actually surface under RUST_LOG (e.g.
    // RUST_LOG=info,sugar_walk::ra_oracle=debug). Without this the probe is
    // blind to WHY a resolution refused (not-ready vs. genuine null).
    init_tracing();

    if std::env::var_os("SUGAR_RESOLVE_ORACLE").as_deref()
        != Some(std::ffi::OsStr::new("rust-analyzer"))
    {
        std::env::set_var("SUGAR_RESOLVE_ORACLE", "rust-analyzer");
    }

    let args: Vec<String> = std::env::args().collect();
    let crate_root_arg = args
        .get(1)
        .cloned()
        .unwrap_or_else(|| "examples/oracle-hover-fixture".to_string());
    let src_rel = args
        .get(2)
        .cloned()
        .unwrap_or_else(|| "src/lib.rs".to_string());

    let crate_root = PathBuf::from(&crate_root_arg)
        .canonicalize()
        .unwrap_or_else(|e| panic!("crate root {crate_root_arg:?}: {e}"));
    let abs_path = crate_root
        .join(&src_rel)
        .canonicalize()
        .unwrap_or_else(|e| panic!("source {src_rel:?} under crate root: {e}"));

    let source = std::fs::read_to_string(&abs_path).expect("read fixture source");
    let (lsp_line, lsp_col) =
        locate_method(&source, "unwrap").expect("fixture has a `.unwrap()` site");

    println!("== hover_probe ==");
    println!("crate root : {}", crate_root.display());
    println!("source     : {}", abs_path.display());
    println!("position   : line {lsp_line}, col {lsp_col} (0-based LSP) at `unwrap`");

    let mut oracle = match RaOracle::start(&crate_root) {
        Some(o) => o,
        None => {
            eprintln!(
                "PROBE COULD NOT RUN: RaOracle did not start \
                 (rust-analyzer missing/disabled). Set SUGAR_RUST_ANALYZER \
                 or put rust-analyzer on PATH."
            );
            std::process::exit(2);
        }
    };

    let q = ResolveQuery {
        abs_path: abs_path.clone(),
        lsp_line,
        lsp_col,
    };

    // 1+2: raw hover markdown + what the parser makes of it.
    println!("\n===== RAW HOVER MARKDOWN (live rust-analyzer at `unwrap`) =====");
    let hover_md = oracle.hover_markdown_raw(&q);
    let hover_stem = match &hover_md {
        Some(md) => {
            println!("{md}");
            println!("----- (end raw markdown) -----");
            let stem = type_stem_from_hover_markdown(md);
            match &stem {
                Some(s) => println!("parser     -> hover stem = {s:?}"),
                None => println!(
                    "parser     -> REFUSED (None): first ```rust``` block is not a \
                     bare type path (signature/binding/module/empty)"
                ),
            }
            stem
        }
        None => {
            println!("(no hover result: RA returned null / not-ready / transport failure)");
            None
        }
    };

    // 3: the production resolution path.
    println!("\n===== resolve_typed_classified (production path) =====");
    let resolved = oracle.resolve_typed_classified(&q);
    match &resolved {
        Ok(Some(res)) => {
            println!("krate      = {}", res.krate);
            println!("type_stem  = {:?}", res.type_stem);
        }
        Ok(None) => println!("deterministic refuse (Ok(None)): no crate resolved"),
        Err(()) => println!("not-ready (Err(())): ContentModified budget exhausted"),
    }

    // 4: the discrimination verdict.
    println!("\n===== VERDICT =====");
    let final_stem = match &resolved {
        Ok(Some(res)) => res.type_stem.clone(),
        // sugar-audit: not-mine(debug-cli-verdict-keeps-unresolved-or-not-ready-as-no-final-stem)
        _ => None,
    };
    let stem_source = if hover_stem.is_some() {
        "hover"
    } else {
        "definition-file-stem (or unresolved)"
    };
    println!("stem_source = {stem_source}");
    println!("final stem  = {final_stem:?}");

    let pass = hover_stem.is_some() && final_stem.is_some() && hover_stem == final_stem;
    if pass {
        println!(
            "RESULT: PASS -- hover FIRED and supplied the receiver-type stem \
             on a workspace-local std-typed receiver. cli-K foundation is real."
        );
        std::process::exit(0);
    } else if hover_stem.is_none() && final_stem.is_some() {
        println!(
            "RESULT: NO-GO -- hover REFUSED; the stem ({final_stem:?}) came from the \
             def-file-stem fallback, not hover. Hover is INERT on this shape. The \
             raw markdown above shows why; the parser or the queried position needs \
             to change before any Tier work is stacked on hover."
        );
        std::process::exit(3);
    } else {
        println!(
            "RESULT: NO-GO -- no stem resolved at all (hover and fallback both \
             empty). The receiver did not resolve; investigate the raw markdown \
             and the def path above."
        );
        std::process::exit(3);
    }
}

fn init_tracing() {
    let filter = tracing_subscriber::EnvFilter::builder()
        .with_default_directive(tracing_subscriber::filter::LevelFilter::WARN.into())
        .from_env_lossy();
    if let Ok(path) = std::env::var("SUGAR_LOG_FILE") {
        match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
        {
            Ok(file) => {
                tracing_subscriber::fmt()
                    .with_writer(file)
                    .with_ansi(false)
                    .with_env_filter(filter)
                    .init();
            }
            Err(error) => {
                eprintln!(
                    "warning: could not open SUGAR_LOG_FILE {path}: {error}; logging to stderr"
                );
                tracing_subscriber::fmt()
                    .with_writer(std::io::stderr)
                    .with_env_filter(filter)
                    .init();
            }
        }
    } else {
        tracing_subscriber::fmt()
            .with_writer(std::io::stderr)
            .with_env_filter(filter)
            .init();
    }
}
