use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::Dialect;
use serde_json::Value;
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::tree::fold_recovered_audit;

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

fn python_blake3_available() -> bool {
    Command::new("python3")
        .arg("-c")
        .arg("import blake3")
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}

fn write_executable(path: &Path, text: &str) {
    let mut file = fs::File::create(path).expect("create kit wrapper");
    file.write_all(text.as_bytes()).expect("write kit wrapper");
    file.sync_all().expect("sync kit wrapper");
    #[cfg(unix)]
    {
        let mut permissions = fs::metadata(path).expect("stat wrapper").permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(path, permissions).expect("chmod wrapper");
    }
}

fn python_kit(dir: &Path) -> Kit {
    let py_tests_src = repo_root().join("implementations/python/sugar-lift-py-tests/src");
    let py_source_src = repo_root().join("implementations/python/sugar-lift-python-source/src");
    let script = dir.join("python-lift.sh");
    write_executable(
        &script,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}${{PYTHONPATH:+:$PYTHONPATH}}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            py_tests_src.display(),
            py_source_src.display()
        ),
    );
    Kit::rendezvous(LiftManifest {
        surface: "python".to_string(),
        name: "python-lift".to_string(),
        dialect: Dialect::Other("python".to_string()),
        command: vec![script.display().to_string()],
        working_dir: None,
        method: None,
    })
    .expect("rendezvous")
}

fn count(payload: &Value, field: &str) -> u64 {
    payload["census"][field]
        .as_u64()
        .unwrap_or_else(|| panic!("missing census field {field}: {payload}"))
}

#[test]
fn genuine_empty_workspace_mints_only_explicit_valid_empty_receipt() {
    if !python_blake3_available() {
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let workspace = dir.path().join("workspace");
    fs::create_dir(&workspace).expect("workspace");
    let payload = fold_recovered_audit(&python_kit(dir.path()), &workspace, &["python".into()])
        .expect("closed fold");

    assert_eq!(payload["status"], "valid-empty");
    assert_eq!(payload["census"]["kind"], "recovered-frontier-census");
    assert_eq!(count(&payload, "sourceFilesEnumerated"), 0);
    assert_eq!(count(&payload, "sourceBodiesDemanded"), 0);
    assert_eq!(count(&payload, "auditLeavesCompleted"), 0);
}

#[test]
fn known_nonempty_zero_frontier_proves_file_body_was_demanded() {
    if !python_blake3_available() {
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let workspace = dir.path().join("workspace");
    fs::create_dir(&workspace).expect("workspace");
    fs::write(workspace.join("__init__.py"), "# package marker only\n").expect("source");
    let payload = fold_recovered_audit(&python_kit(dir.path()), &workspace, &["python".into()])
        .expect("closed fold");

    assert_eq!(payload["status"], "complete");
    assert_eq!(count(&payload, "sourceFilesEnumerated"), 1);
    assert_eq!(count(&payload, "sourceBodiesDemanded"), 1);
    assert_eq!(count(&payload, "auditLeavesCompleted"), 0);
    assert_eq!(payload["panics"].as_array().unwrap().len(), 0);
}

#[test]
fn successful_nonzero_frontier_has_completed_census_and_panics() {
    if !python_blake3_available() {
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let workspace = dir.path().join("workspace");
    fs::create_dir(&workspace).expect("workspace");
    fs::write(
        workspace.join("broken.py"),
        "def broken(xs):\n    match xs:\n        case 0:\n            return xs\n",
    )
    .expect("source");
    let payload = fold_recovered_audit(&python_kit(dir.path()), &workspace, &["python".into()])
        .expect("closed fold");

    assert_eq!(payload["status"], "failed");
    assert_eq!(count(&payload, "sourceFilesEnumerated"), 1);
    assert_eq!(count(&payload, "sourceBodiesDemanded"), 1);
    assert!(count(&payload, "auditLeavesCompleted") >= 1);
    assert!(!payload["panics"].as_array().unwrap().is_empty());
}
