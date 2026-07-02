// SPDX-License-Identifier: Apache-2.0
//
// IrTerm boundary-collapse campaign (#3191), Slice 1 Instrument B.
//
// The campaign's byte-compat evidence must be reusable by every later slice,
// not a one-off shell transcript. This test keeps the harness callable and
// verifies that it fails closed on a planted drift.

use std::path::PathBuf;
use std::process::Command;

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

#[test]
fn irterm_byte_compat_harness_self_test_passes_and_detects_drift() {
    let script = repo_root().join("tools/irterm-boundary/byte-compat.sh");
    let output = Command::new(&script)
        .arg("--self-test")
        .output()
        .unwrap_or_else(|err| panic!("run {} --self-test: {err}", script.display()));

    assert!(
        output.status.success(),
        "{} --self-test failed\nstdout:\n{}\nstderr:\n{}",
        script.display(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8_lossy(&output.stdout).contains("irterm-byte-compat self-test ok"),
        "self-test should report success after proving same-output pass and drift failure\nstdout:\n{}",
        String::from_utf8_lossy(&output.stdout)
    );
}
