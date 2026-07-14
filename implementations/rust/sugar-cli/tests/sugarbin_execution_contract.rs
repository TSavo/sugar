use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli workspace root")
        .to_path_buf()
}

#[test]
fn sugarbin_local_execution_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_local_exec.sh"))
        .arg(&root)
        .status()
        .expect("run local execution contract");
    assert!(status.success(), "local execution contract failed: {status}");
}

#[test]
fn sugarbin_bx_execution_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_bx_exec.sh"))
        .arg(&root)
        .status()
        .expect("run bx execution contract");
    assert!(status.success(), "bx execution contract failed: {status}");
}

#[test]
fn sugarbin_docker_execution_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_docker_exec.sh"))
        .arg(&root)
        .status()
        .expect("run Docker execution contract");
    assert!(status.success(), "Docker execution contract failed: {status}");
}

#[test]
fn sugarbin_wrapper_compatibility_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_wrapper_compat.sh"))
        .arg(&root)
        .status()
        .expect("run wrapper compatibility contract");
    assert!(status.success(), "wrapper compatibility contract failed: {status}");
}

#[test]
fn sugarbin_artifact_manifest_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_artifact_manifest.sh"))
        .arg(&root)
        .status()
        .expect("run artifact manifest contract");
    assert!(status.success(), "artifact manifest contract failed: {status}");
}
