// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Residual rust-CLI behavior assertion from the former Go codegen
// gauntlet. The deleted Go codegen kit tests have been removed; this negative test
// remains because it asserts a property of the *Rust CLI itself* -- that go
// source discovery is kit-owned over RPC and not hardcoded in the CLI's
// legacy source scanner.

use std::fs;
use std::path::PathBuf;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}

#[test]
fn rust_cli_materialize_scanner_does_not_claim_go_files() {
    let source = fs::read_to_string(
        repo_root()
            .join("implementations")
            .join("rust")
            .join("sugar-cli")
            .join("src")
            .join("cmd_materialize.rs"),
    )
    .expect("read cmd_materialize.rs");
    assert!(
        !source.contains(r#"| "go""#) && !source.contains(r#""go" |"#),
        "Go source discovery/transformation must be kit-owned over RPC, not listed in the CLI's legacy source scanner"
    );
}
