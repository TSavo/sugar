// SPDX-License-Identifier: Apache-2.0
//
// Charon subprocess runner. Per #383, this is the bridge between a
// .rs source file and an `LlbcCrate` parsed from Charon's JSON output.
// Instead of vendoring .llbc fixtures into the repo, callers can lift
// straight from source whenever Charon is installed.
//
// Runner path resolution (first match wins):
//   1. The `bin` argument, if explicitly passed.
//   2. The `CHARON_BIN` environment variable.
//   3. `charon` on PATH.
//   4. `$HOME/projects/charon/charon/target/release/charon` —
//      the conventional location after `cargo build --release` from
//      a clone of `AeneasVerif/charon`.
//
// Charon is a heavyweight tool (downloads a pinned nightly toolchain
// the first time it's built; subprocess invocation costs ~hundreds of
// ms per call). Tests should skip-on-missing rather than failing CI
// when Charon isn't available — see `lift_dogfood.rs` for the pattern.

use std::path::{Path, PathBuf};
use std::process::Command;

use thiserror::Error;

use crate::llbc::{LlbcCrate, LlbcError};

#[derive(Debug, Error)]
pub enum RunnerError {
    #[error("charon binary not found (set CHARON_BIN or place on PATH)")]
    CharonNotFound,
    #[error("charon subprocess failed (status {status}): {stderr}")]
    CharonFailed { status: String, stderr: String },
    #[error("charon runner I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("charon runner: {0}")]
    Llbc(#[from] LlbcError),
}

/// Locate the `charon` binary. Returns None if every fallback is
/// exhausted. Callers can use this to skip-on-missing in tests.
pub fn find_charon_binary() -> Option<PathBuf> {
    if let Ok(path) = std::env::var("CHARON_BIN") {
        let p = PathBuf::from(path);
        if p.exists() {
            return Some(p);
        }
    }
    // Try `which charon` semantics via PATH lookup. We don't depend on
    // an external `which` binary; iterate PATH ourselves.
    if let Ok(path_var) = std::env::var("PATH") {
        for dir in std::env::split_paths(&path_var) {
            let candidate = dir.join("charon");
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    // Conventional location after `cargo build --release` from a
    // clone of AeneasVerif/charon under $HOME/projects/charon/.
    if let Ok(home) = std::env::var("HOME") {
        let candidate = PathBuf::from(home).join("projects/charon/charon/target/release/charon");
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Invoke `charon rustc --no-dedup-serialized-ast` on a single .rs
/// source file. The output `.llbc` JSON is read back into an
/// `LlbcCrate`. The temp output file is cleaned up on success.
///
/// The source file is treated as a `--crate-type=lib` so it doesn't
/// require a `main` function.
pub fn invoke_charon_on_rs_source(
    source_path: &Path,
    explicit_bin: Option<&Path>,
) -> Result<LlbcCrate, RunnerError> {
    let bin = explicit_bin
        .map(|p| p.to_path_buf())
        .or_else(find_charon_binary)
        .ok_or(RunnerError::CharonNotFound)?;

    // Place the output in the system temp dir with a unique-ish name
    // so concurrent test runs don't collide.
    let stem = match source_path.file_stem().and_then(|s| s.to_str()) {
        Some(stem) => stem,
        None => "source",
    };
    let pid = std::process::id();
    let nanos = match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
        Ok(duration) => duration.as_nanos(),
        Err(_) => 0,
    };
    let dest = std::env::temp_dir().join(format!("charon-{}-{}-{}.llbc", stem, pid, nanos));

    let output = Command::new(&bin)
        .arg("rustc")
        .arg("--no-dedup-serialized-ast")
        .arg(format!("--dest-file={}", dest.display()))
        .arg("--")
        .arg("--crate-type=lib")
        .arg(source_path)
        .output()?;

    if !output.status.success() {
        // Best-effort cleanup of any partial output.
        let _ = std::fs::remove_file(&dest);
        return Err(RunnerError::CharonFailed {
            status: format!("{}", output.status),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        });
    }

    let krate = LlbcCrate::from_path(&dest)?;
    let _ = std::fs::remove_file(&dest);
    Ok(krate)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_source(name: &str, body: &str) -> PathBuf {
        let pid = std::process::id();
        let nanos = match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
            Ok(duration) => duration.as_nanos(),
            Err(_) => 0,
        };
        let path =
            std::env::temp_dir().join(format!("charon-runner-{}-{}-{}.rs", name, pid, nanos));
        std::fs::write(&path, body).expect("write tmp source");
        path
    }

    /// Skip-on-missing. We don't fail CI when Charon isn't installed;
    /// the upstream tool requires a pinned nightly toolchain (~hundreds
    /// of MB of components) and a multi-minute cold build.
    fn skip_if_no_charon() -> Option<PathBuf> {
        let bin = find_charon_binary();
        if bin.is_none() {
            eprintln!(
                "charon binary not found; skipping (install AeneasVerif/charon and set CHARON_BIN, \
                 or place `charon` on PATH)"
            );
        }
        bin
    }

    #[test]
    fn invokes_charon_on_inline_source_and_finds_function_f() {
        let Some(_bin) = skip_if_no_charon() else {
            return;
        };
        let src = "fn f(x: u32) { if x < 10 { panic!(); } }\n";
        let path = write_source("inline", src);
        let krate =
            invoke_charon_on_rs_source(&path, None).expect("charon on inline source succeeds");
        let f = krate
            .function_by_name("f")
            .expect("function f present in lifted crate");
        assert_eq!(f.fn_name().as_deref(), Some("f"));
        assert_eq!(f.arg_count(), Some(1));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn end_to_end_charon_runner_to_llbc_lift_to_cross_layer_equality() {
        // Closure of the round trip: write .rs → charon → LlbcCrate →
        // lift_llbc_function → FunctionContractMemento. Compare to AST
        // walk's lift of the SAME source. Predicate bytes must match.
        let Some(_bin) = skip_if_no_charon() else {
            return;
        };
        use crate::canonical::{formula_to_canonical, jcs_bytes_of_value};
        use crate::contract::build_function_contract;
        use crate::llbc_lift::lift_llbc_function;

        let src = "fn f(x: u32) { if x < 10 { panic!(); } }\n";
        let path = write_source("e2e", src);

        // LLBC layer via runner (fully end-to-end, no vendored fixture).
        let krate = invoke_charon_on_rs_source(&path, None).expect("charon ok");
        let f = krate.function_by_name("f").unwrap();
        let llbc_contract = lift_llbc_function(f, path.to_str()).expect("lift_llbc_function ok");

        // AST layer.
        let file: syn::File = syn::parse_str(src).unwrap();
        let item_fn = file
            .items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) if f.sig.ident == "f" => Some(f),
                // sugar-audit: not-mine(test-helper-search-ignores-non-target-items)
                _ => None,
            })
            .unwrap();
        let ast_contract = build_function_contract(&item_fn, None);

        // Cross-layer formula equality.
        let ast_pre = jcs_bytes_of_value(&formula_to_canonical(&ast_contract.pre));
        let llbc_pre = jcs_bytes_of_value(&formula_to_canonical(&llbc_contract.pre));
        assert_eq!(
            ast_pre, llbc_pre,
            "round-trip cross-layer pre formula bytes must match"
        );

        let _ = std::fs::remove_file(&path);
    }
}
