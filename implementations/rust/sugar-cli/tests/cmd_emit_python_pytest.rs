// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

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

fn python_bin() -> String {
    std::env::var("PYTHON").unwrap_or_else(|_| "python3".to_string())
}

fn python_available() -> bool {
    Command::new(python_bin())
        .args(["-c", "import blake3, pytest"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn install_emit_registration(project: &Path) {
    let python_src = repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-emit-python-pytest")
        .join("src");
    let pythonpath = python_src
        .display()
        .to_string()
        .replace('\\', "\\\\")
        .replace('"', "\\\"");
    let python = python_bin().replace('\\', "\\\\").replace('"', "\\\"");

    let sugar_dir = project.join(".sugar");
    fs::create_dir_all(&sugar_dir).expect("mkdir .sugar");
    fs::write(
        sugar_dir.join("config.toml"),
        "[[plugins]]\n\
         name = \"python-pytest\"\n\
         surface = \"python-pytest\"\n\
         emit = \"pytest\"\n",
    )
    .expect("write project config");

    let manifest = project
        .join(".sugar")
        .join("emit")
        .join("python-pytest")
        .join("manifest.toml");
    fs::create_dir_all(manifest.parent().unwrap()).expect("mkdir manifest");
    fs::write(
        manifest,
        format!(
            "name = \"python-pytest\"\ncommand = [\"env\", \"PYTHONPATH={pythonpath}\", \"{python}\", \"-m\", \"sugar_emit_python_pytest\", \"--rpc\"]\nworking_dir = \".\"\nprotocol_versions = [\"pep/1.7.0\"]\n"
        ),
    )
    .expect("write emit manifest");
}

fn copy_dir_recursive(src: &Path, dst: &Path) {
    fs::create_dir_all(dst).unwrap_or_else(|_| panic!("mkdir {}", dst.display()));
    for entry in fs::read_dir(src).unwrap_or_else(|_| panic!("read {}", src.display())) {
        let entry = entry.expect("read dir entry");
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        if entry.file_type().expect("entry file type").is_dir() {
            copy_dir_recursive(&src_path, &dst_path);
        } else {
            fs::copy(&src_path, &dst_path).unwrap_or_else(|_| {
                panic!("copy {} -> {}", src_path.display(), dst_path.display())
            });
        }
    }
}

fn rewrite_python_emit_manifest(manifest: &Path) {
    let python_src = repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-emit-python-pytest")
        .join("src");
    let pythonpath = python_src
        .display()
        .to_string()
        .replace('\\', "\\\\")
        .replace('"', "\\\"");
    let python = python_bin().replace('\\', "\\\\").replace('"', "\\\"");
    let text = fs::read_to_string(manifest)
        .unwrap_or_else(|_| panic!("read checked-in manifest {}", manifest.display()));
    let rewritten = text
        .lines()
        .map(|line| {
            if line.trim_start().starts_with("command = ") {
                format!(
                    "command = [\"env\", \"PYTHONPATH={pythonpath}\", \"{python}\", \"-m\", \"sugar_emit_python_pytest\", \"--rpc\"]"
                )
            } else {
                line.to_string()
            }
        })
        .collect::<Vec<_>>()
        .join("\n");
    fs::write(manifest, format!("{rewritten}\n"))
        .unwrap_or_else(|_| panic!("write manifest {}", manifest.display()));
}

fn write_basic_emit_plan(plan: &Path) {
    fs::write(
        plan,
        serde_json::to_vec_pretty(&serde_json::json!({
            "contract_id": "concept:eq",
            "function": "identity",
            "params": ["a", "b"],
            "param_types": ["int", "int"],
            "predicates": [{
                "kind": "atomic",
                "name": "concept:eq",
                "args": [
                    {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}},
                    {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }]
        }))
        .expect("encode plan"),
    )
    .expect("write plan");
}

#[test]
fn emit_python_pytest_dispatches_real_emitter_and_pytest_checks_output() {
    if !python_available() {
        eprintln!("skipping: python3 cannot import blake3 and pytest");
        return;
    }

    let temp = tempfile::tempdir().expect("tempdir");
    let project = temp.path().join("project");
    let out_dir = temp.path().join("out");
    fs::create_dir_all(&project).expect("mkdir project");
    fs::create_dir_all(&out_dir).expect("mkdir out");
    install_emit_registration(&project);

    let plan = project.join("plan.json");
    write_basic_emit_plan(&plan);

    let output = Command::new(sugar_bin())
        .arg("emit")
        .arg("--project")
        .arg(&project)
        .arg("--target")
        .arg("python")
        .arg("--framework")
        .arg("pytest")
        .arg("--plan")
        .arg(&plan)
        .arg("--out-dir")
        .arg(&out_dir)
        .arg("--compile-check")
        .arg("--json")
        .output()
        .expect("spawn sugar emit python");

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "sugar emit python failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let receipt: Value = serde_json::from_str(&stdout).expect("emit stdout is JSON");
    assert_eq!(receipt["ok"], true, "receipt: {receipt}");
    assert_eq!(receipt["targetLanguage"], "python", "receipt: {receipt}");
    assert_eq!(receipt["targetFramework"], "pytest", "receipt: {receipt}");
    assert_eq!(receipt["isComplete"], true, "receipt: {receipt}");

    let emitted_path = out_dir.join("test_identity_contract.py");
    let emitted = fs::read_to_string(&emitted_path)
        .unwrap_or_else(|_| panic!("read emitted {}", emitted_path.display()));
    assert!(
        emitted.contains("def test_verifies_eq_0():"),
        "emitted:\n{emitted}"
    );
    assert!(emitted.contains("assert 2 == 2"), "emitted:\n{emitted}");
}

#[test]
fn emit_python_pytest_uses_checked_in_python_double_registration() {
    if !python_available() {
        eprintln!("skipping: python3 cannot import blake3 and pytest");
        return;
    }

    let temp = tempfile::tempdir().expect("tempdir");
    let project = temp.path().join("python-double");
    let out_dir = temp.path().join("out");
    fs::create_dir_all(&project).expect("mkdir project");
    fs::create_dir_all(&out_dir).expect("mkdir out");
    copy_dir_recursive(
        &repo_root()
            .join("examples")
            .join("python-double")
            .join(".sugar"),
        &project.join(".sugar"),
    );
    rewrite_python_emit_manifest(
        &project
            .join(".sugar")
            .join("emit")
            .join("python-pytest")
            .join("manifest.toml"),
    );

    let plan = project.join("plan.json");
    write_basic_emit_plan(&plan);

    let output = Command::new(sugar_bin())
        .arg("emit")
        .arg("--project")
        .arg(&project)
        .arg("--target")
        .arg("python")
        .arg("--framework")
        .arg("pytest")
        .arg("--plan")
        .arg(&plan)
        .arg("--out-dir")
        .arg(&out_dir)
        .arg("--compile-check")
        .arg("--json")
        .output()
        .expect("spawn sugar emit python");

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "checked-in Python fixture registration must drive pytest emit\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let receipt: Value = serde_json::from_str(&stdout).expect("emit stdout is JSON");
    assert_eq!(receipt["ok"], true, "receipt: {receipt}");
    assert_eq!(receipt["surface"], "python-pytest", "receipt: {receipt}");
    assert_eq!(receipt["targetLanguage"], "python", "receipt: {receipt}");
    assert_eq!(receipt["targetFramework"], "pytest", "receipt: {receipt}");
}
