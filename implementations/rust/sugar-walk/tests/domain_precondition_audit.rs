// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Domain-precondition audit (#3483).
//
// Kit domain = COMPILING programs. rustc yes -> correctness membrane. rustc
// no -> undefined (AGENTS.md, 1e5ca3bbd). Lift/walk code that reaches an AST
// node produced by `syn::parse_file`/`syn::parse2` over source rustc already
// accepted must never ask "is this even valid Rust?" — that question can
// only be true for rustc-REJECTED input, which cannot arrive here.
//
// This instrument sweeps the lift/walk/factory source files (excluding their
// `#[cfg(test)]` modules and excluding named RPC/data-transport membranes,
// where non-Rust bytes legitimately arrive) for validation-arm heuristics:
// panic/error strings claiming the *shape itself* is invalid Rust
// ("invalid rust", "not valid rust", "malformed rust", "not a valid
// expression/statement/pattern", "unexpected token" outside syn's own
// parser). R(validation-arms) is pinned at 0 over this file set. A red-first
// self-test proves the scanner actually fires on a planted offender so a
// silently-broken heuristic can't hide a regression.
//
// Non-offenders are NOT swept here: bare `None => panic!()`/`.unwrap()`/
// `.expect()` where rustc guarantees the shape (the doctrine itself), and the
// sacred "write more Sugar for this AST" coverage panic on VALID-but-
// unrecognized shapes (the honest frontier, not this audit's target).
//
// Class-(b) membranes (RPC ingress, JSON/CBOR transport, contract-memento
// fields, oracle daemon responses) are named and excluded below rather than
// silently skipped, because that boundary is real: those bytes have NOT been
// rustc-checked and validity questions there are legitimate. See the PR body
// for the (b)/(c) campaign map this audit produced.

use std::fs;
use std::path::{Path, PathBuf};

/// Files in the lift/walk/factory surface this audit sweeps. Deliberately
/// excludes `src/bin/*_rpc.rs` (walk_rpc.rs, contracts_rpc.rs) and
/// `ra_daemon_client.rs`/`source_oracle.rs`'s outermost `syn::parse_file`
/// entry points: those are the named class-(b) membrane, not lift/walk
/// interior logic operating on an already-parsed, rustc-accepted AST.
const TARGET_FILES: &[&str] = &[
    "implementations/rust/sugar-walk/src/lift.rs",
    "implementations/rust/sugar-walk/src/emit.rs",
    "implementations/rust/sugar-walk/src/walk.rs",
    "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
    "implementations/rust/sugar-walk/src/contract.rs",
    "implementations/rust/sugar-walk/src/locus.rs",
    "implementations/rust/sugar-walk/src/shadow.rs",
    "implementations/rust/sugar-walk/src/chain.rs",
    "implementations/rust/sugar-walk/src/type_decl.rs",
    "implementations/rust/sugar-walk/src/sort_translate.rs",
    "implementations/rust/sugar-lift/src/call_edges.rs",
    "implementations/rust/sugar-lift/src/lib.rs",
    "implementations/rust/sugar-lift-contracts/src/lib.rs",
];

/// Case-insensitive substrings that indicate a guard is classifying
/// *Rust-validity* rather than a real class-(b) membrane. Kept narrow and
/// literal (not a full parser) — this is a census heuristic, not a compiler.
const OFFENDER_SIGNALS: &[&str] = &[
    "not valid rust",
    "invalid rust",
    "malformed rust",
    "not a valid expression",
    "not a valid statement",
    "not a valid pattern",
    "is not a valid rust",
    "invalid expression syntax",
    "malformed expression syntax",
];

#[derive(Debug, Clone)]
struct OffenderHit {
    file: String,
    line: usize,
    text: String,
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-walk has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

/// Strips the trailing `#[cfg(test)] mod tests { ... }` block (by textual
/// prefix, matching this workspace's one-test-module-at-file-end
/// convention) so fixture/test-only strings never count as offenders.
fn strip_test_module(source: &str) -> &str {
    match source.find("#[cfg(test)]") {
        Some(idx) => &source[..idx],
        None => source,
    }
}

fn scan_source(file: &str, source: &str) -> Vec<OffenderHit> {
    let production = strip_test_module(source);
    let mut hits = Vec::new();
    for (idx, line) in production.lines().enumerate() {
        let lower = line.to_lowercase();
        for signal in OFFENDER_SIGNALS {
            if lower.contains(signal) {
                hits.push(OffenderHit {
                    file: file.to_string(),
                    line: idx + 1,
                    text: line.trim().to_string(),
                });
                break;
            }
        }
    }
    hits
}

fn scan_repo(root: &Path) -> Vec<OffenderHit> {
    let mut hits = Vec::new();
    for rel in TARGET_FILES {
        let path = root.join(rel);
        let source = fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        hits.extend(scan_source(rel, &source));
    }
    hits
}

/// Red-first: the scanner must actually fire on a planted validity-of-Rust
/// offender, proving the heuristic is live and not accidentally vacuous.
#[test]
fn scanner_fires_on_a_planted_offender() {
    let planted = r#"
        fn guard(e: &Expr) -> Result<(), String> {
            if is_weird(e) {
                return Err("not a valid expression for this position".to_string());
            }
            Ok(())
        }
    "#;
    let hits = scan_source("planted.rs", planted);
    assert_eq!(
        hits.len(),
        1,
        "planted validity-of-Rust offender must be caught by the census"
    );
}

/// Red-first (negative control): the scanner must NOT fire on the doctrine's
/// own non-offender shape (bare panic on a compiler-guaranteed None/Err), so
/// the census cannot regress into false-positive noise that gets muted.
#[test]
fn scanner_does_not_fire_on_bare_panic_doctrine_arm() {
    let compliant = r#"
        fn assert_macro_condition(mac: &Macro) -> Option<Expr> {
            match syn::parse2::<Expr>(tokens) {
                Ok(expr) => expr,
                Err(err) => panic!("{err}"),
            }
        }
    "#;
    let hits = scan_source("compliant.rs", compliant);
    assert!(
        hits.is_empty(),
        "bare panic on rustc-guaranteed input must not be flagged: {hits:?}"
    );
}

/// R(validation-arms) pinned at 0 across the lift/walk/factory source set.
/// A new hit here means a new validation-arm classifying Rust-validity was
/// added on a path only reachable via rustc-rejected input — the offender
/// class named in #3483. Replacement: collapse to unwrap/panic, the domain
/// precondition covers this; or, if it is genuinely a class-(b) RPC/data
/// boundary, name it explicitly and exclude it from TARGET_FILES with a
/// comment, the way ra_daemon_client.rs/*_rpc.rs are excluded above.
#[test]
fn no_validity_of_rust_arms_in_lift_walk_factory_sources() {
    let root = repo_root();
    let hits = scan_repo(&root);
    assert!(
        hits.is_empty(),
        "domain-precondition offenders found (delete; domain precondition covers this, \
         or name the class-(b) membrane and exclude): {:#?}",
        hits.iter()
            .map(|h| format!("{}:{}: {}", h.file, h.line, h.text))
            .collect::<Vec<_>>()
    );
}
