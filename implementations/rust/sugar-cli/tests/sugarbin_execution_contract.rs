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
