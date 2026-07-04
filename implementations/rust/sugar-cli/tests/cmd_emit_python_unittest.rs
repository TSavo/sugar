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
        .args(["-c", "import blake3"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn install_emit_registration(project: &Path) {
    let python_src = repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-emit-python-unittest")
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
         name = \"python-unittest\"\n\
         surface = \"python-unittest\"\n\
         emit = \"unittest\"\n",
    )
    .expect("write project config");

    let manifest = project
        .join(".sugar")
        .join("emit")
        .join("python-unittest")
        .join("manifest.toml");
    fs::create_dir_all(manifest.parent().unwrap()).expect("mkdir manifest");
    fs::write(
        manifest,
        format!(
            "name = \"python-unittest\"\ncommand = [\"env\", \"PYTHONPATH={pythonpath}\", \"{python}\", \"-m\", \"sugar_emit_python_unittest\", \"--rpc\"]\nworking_dir = \".\"\nprotocol_versions = [\"pep/1.7.0\"]\n"
        ),
    )
    .expect("write emit manifest");
}

#[test]
fn emit_python_unittest_dispatches_real_emitter_and_unittest_checks_output() {
    if !python_available() {
        eprintln!("skipping: python3 cannot import blake3");
        return;
    }

    let temp = tempfile::tempdir().expect("tempdir");
    let project = temp.path().join("project");
    let out_dir = temp.path().join("out");
    fs::create_dir_all(&project).expect("mkdir project");
    fs::create_dir_all(&out_dir).expect("mkdir out");
    install_emit_registration(&project);

    let plan = project.join("plan.json");
    fs::write(
        &plan,
        serde_json::to_vec_pretty(&serde_json::json!({
            "contract_id": "concept:eq",
            "function": "identity",
            "params": ["actual", "expected"],
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

    let output = Command::new(sugar_bin())
        .arg("emit")
        .arg("--project")
        .arg(&project)
        .arg("--target")
        .arg("python")
        .arg("--framework")
        .arg("unittest")
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
        "sugar emit python unittest failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );

    let receipt: Value = serde_json::from_str(&stdout).expect("emit stdout is JSON");
    assert_eq!(receipt["ok"], true, "receipt: {receipt}");
    assert_eq!(receipt["targetLanguage"], "python", "receipt: {receipt}");
    assert_eq!(receipt["targetFramework"], "unittest", "receipt: {receipt}");
    assert_eq!(receipt["isComplete"], true, "receipt: {receipt}");
    assert_eq!(receipt["compileCheck"]["ok"], true, "receipt: {receipt}");

    let emitted_path = out_dir.join("test_identity_contract.py");
    let emitted = fs::read_to_string(&emitted_path)
        .unwrap_or_else(|_| panic!("read emitted {}", emitted_path.display()));
    assert!(emitted.contains("import unittest"), "emitted:\n{emitted}");
    assert!(
        emitted.contains("class TestIdentityContract(unittest.TestCase):"),
        "emitted:\n{emitted}"
    );
    assert!(
        emitted.contains("self.assertEqual(2, 2)"),
        "emitted:\n{emitted}"
    );
}
