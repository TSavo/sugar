// SPDX-License-Identifier: MIT OR Apache-2.0

use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use sugar_verifier::load_all_proofs;

fn rust_workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-verifier crate has workspace parent")
        .to_path_buf()
}

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system clock")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "sugar-examples-bodycid-{}-{stamp}-{suffix}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

fn cargo_command() -> Command {
    let cargo = std::env::var_os("CARGO").unwrap_or_else(|| OsStr::new("cargo").to_os_string());
    let mut command = Command::new(cargo);
    command.current_dir(rust_workspace());
    command
}

fn run_parse_int_publish(out_dir: &Path) -> String {
    let output = cargo_command()
        .args([
            "run",
            "-p",
            "sugar-ir-symbolic",
            "--example",
            "parseInt_publish",
            "--",
        ])
        .arg(out_dir)
        .output()
        .expect("run parseInt_publish example");
    assert!(
        output.status.success(),
        "parseInt_publish failed\nstatus: {}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn only_proof_file(dir: &Path) -> PathBuf {
    let proofs = std::fs::read_dir(dir)
        .expect("read proof dir")
        .map(|entry| entry.expect("dir entry").path())
        .filter(|path| path.extension().and_then(OsStr::to_str) == Some("proof"))
        .collect::<Vec<_>>();
    assert_eq!(proofs.len(), 1, "expected one proof file in {dir:?}");
    proofs[0].clone()
}

fn run_cross_lang_consume(peer_proof: &Path) -> Output {
    cargo_command()
        .args([
            "run",
            "-p",
            "sugar-verifier",
            "--example",
            "cross_lang_consume",
            "--",
        ])
        .arg(peer_proof)
        .output()
        .expect("run cross_lang_consume example")
}

#[test]
fn parse_int_publish_output_loads_through_verifier() {
    let out_dir = unique_dir("parse-int");
    let stdout = run_parse_int_publish(&out_dir);
    assert!(stdout.contains("wrote .proof"), "stdout:\n{stdout}");

    let pool = load_all_proofs::run(&out_dir);
    assert!(
        pool.load_errors.is_empty(),
        "parseInt_publish proof load errors: {:?}",
        pool.load_errors
    );
    assert!(
        !pool.mementos.is_empty(),
        "parseInt_publish proof should index at least one memento"
    );
    let _ = std::fs::remove_dir_all(&out_dir);
}

#[test]
fn cross_lang_consume_output_reaches_solver_without_load_errors() {
    let peer_out_dir = unique_dir("peer");
    run_parse_int_publish(&peer_out_dir);
    let peer_proof = only_proof_file(&peer_out_dir);

    let output = run_cross_lang_consume(&peer_proof);
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        !stdout.contains("load error:"),
        "cross_lang_consume should load peer and consumer proofs cleanly:\n{stdout}"
    );
    assert!(
        !stdout.contains("missing bodyCid"),
        "bodyCid migration must remove legacy loader refusals:\n{stdout}"
    );
    assert!(
        output.status.success() || stdout.contains("unsupported dialect: smt-lib-v2.6"),
        "cross_lang_consume failed before/after the loader for an unexpected reason\nstatus: {}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        stdout,
        stderr
    );
    let _ = std::fs::remove_dir_all(&peer_out_dir);
}

#[test]
fn cross_lang_consume_discharges_end_to_end() {
    let peer_out_dir = unique_dir("peer-e2e");
    run_parse_int_publish(&peer_out_dir);
    let peer_proof = only_proof_file(&peer_out_dir);

    let output = run_cross_lang_consume(&peer_proof);
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "cross_lang_consume should discharge end-to-end\nstatus: {}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        stdout,
        stderr
    );
    assert!(
        !stdout.contains("unsupported dialect: smt-lib-v2.6"),
        "default SMT-LIB dialect must be supported by the verifier runner:\n{stdout}"
    );
    assert!(
        stdout.contains("calls-parseInt-with-positive-5: discharged"),
        "positive peer precondition call should discharge:\n{stdout}"
    );
    assert!(
        stdout.contains("calls-parseInt-with-zero: unsatisfied"),
        "zero peer precondition call should be caught as unsatisfied:\n{stdout}"
    );
    assert!(
        stdout.contains("DEMO: Rust verifier caught parse_int(num(0))"),
        "demo success summary should print:\n{stdout}"
    );
    let _ = std::fs::remove_dir_all(&peer_out_dir);
}
