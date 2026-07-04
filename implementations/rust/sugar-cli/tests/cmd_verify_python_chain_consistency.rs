// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Python chain seam regression:
//
//   def h(x): return x + 1
//   def g(x): return h(x)
//   assert g(5) == 6
//
// The lift emits the seam, not an inline lie:
//   call:g(5) == call:h(5)
//   call:h(5) == 6
//
// Body-discharge may reduce `g` to the `call:h` seam, but consistency owns the
// sibling ground `call:` facts. The product proof must compose those engines so
// the GOOD twin discharges and the BAD twin refutes, with no Python-side proof.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;

use serde_json::{json, Value as Json};

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

fn python_lift_pythonpath() -> String {
    let root = repo_root();
    std::env::join_paths([
        root.join("implementations/python/sugar-lift-py-pytest-witness/src"),
        root.join("implementations/python/sugar-lift-py-tests/src"),
        root.join("implementations/python/sugar-lift-python-source/src"),
    ])
    .expect("join Python lift source roots")
    .into_string()
    .expect("Python lift source roots must be UTF-8")
}

fn toml_string(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}

fn python_available() -> bool {
    Command::new("python3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn python_deps_available() -> bool {
    Command::new("python3")
        .arg("-c")
        .arg("import blake3, cbor2, nacl, pytest")
        .env("PYTHONPATH", python_lift_pythonpath())
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn unique_project(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let project = std::env::temp_dir()
        .join("sugar-python-chain-consistency")
        .join(format!("{stamp}-{suffix}"));
    fs::create_dir_all(&project).expect("mkdir project");
    project
}

fn active_profile_bin(name: &str) -> PathBuf {
    let mut bin = sugar_bin()
        .parent()
        .expect("CARGO_BIN_EXE_sugar has a profile directory")
        .join(name);
    if !std::env::consts::EXE_SUFFIX.is_empty() {
        bin.set_extension(std::env::consts::EXE_EXTENSION);
    }
    bin
}

fn cargo_profile_args() -> Vec<String> {
    let sugar = sugar_bin();
    let profile_dir = sugar
        .parent()
        .and_then(Path::file_name)
        .and_then(|name| name.to_str())
        .unwrap_or("debug");
    match profile_dir {
        "debug" => Vec::new(),
        "release" => vec!["--release".to_string()],
        other => vec!["--profile".to_string(), other.to_string()],
    }
}

fn ensure_active_profile_smt_compiler_built() -> PathBuf {
    static BUILT: OnceLock<PathBuf> = OnceLock::new();
    BUILT
        .get_or_init(|| {
            let bin = active_profile_bin("sugar-ir-smt-lib");
            if !bin.is_file() {
                let mut cmd = Command::new("cargo");
                cmd.arg("build")
                    .arg("--manifest-path")
                    .arg(repo_root().join("implementations/rust/Cargo.toml"))
                    .args(cargo_profile_args())
                    .args([
                        "-p",
                        "sugar-ir-compiler-smt-lib",
                        "--bin",
                        "sugar-ir-smt-lib",
                    ]);
                let out = cmd.output().expect("spawn cargo build for SMT compiler");
                assert!(
                    out.status.success(),
                    "active-profile SMT compiler must build for python-chain consistency test\nstdout: {}\nstderr: {}",
                    String::from_utf8_lossy(&out.stdout),
                    String::from_utf8_lossy(&out.stderr)
                );
            }
            assert!(
                bin.is_file(),
                "active-profile SMT compiler binary missing after build: {}",
                bin.display()
            );
            bin
        })
        .clone()
}

fn install_smt_compiler_manifest(project: &Path) {
    let manifest_dir = project.join(".sugar").join("ir-compilers").join("smt-lib");
    fs::create_dir_all(&manifest_dir).expect("mkdir ir compiler manifest");
    let rust_workspace = repo_root().join("implementations/rust");
    let smt_bin = ensure_active_profile_smt_compiler_built();
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            r#"name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = [{}]
working_dir = "{}"
dialects = ["smt-lib-v2.6"]
"#,
            toml_string(&smt_bin.display().to_string()),
            rust_workspace.display()
        ),
    )
    .expect("write ir compiler manifest");
}

fn stage_chain_project(suffix: &str, expected: i64) -> PathBuf {
    let project = unique_project(suffix);
    fs::write(
        project.join("test_chain.py"),
        format!(
            "def h(x):\n    return x + 1\n\n\
             def g(x):\n    return h(x)\n\n\
             def test_chain():\n    assert g(5) == {expected}\n"
        ),
    )
    .expect("write chain source");
    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python")).expect("mkdir .sugar/lift/python");
    fs::create_dir_all(sugar.join("components").join("python-lift"))
        .expect("mkdir .sugar/components/python-lift");
    install_smt_compiler_manifest(&project);
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-lift"
kind = "lift"
surface = "python"

[solvers]
default = "z3"

[solvers.dispatch]
linear_arithmetic = "z3"
default = "z3"

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar.join("lift").join("python").join("manifest.toml"),
        r#"name = "python"
command = ["python3", "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"]
working_dir = "."
"#,
    )
    .expect("write python lift manifest");
    let component_script = sugar
        .join("components")
        .join("python-lift")
        .join("component.sh");
    let initialize_response = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "name": "python-lift-component",
            "protocol_version": "sugar-component/1",
            "capabilities": {}
        }
    })
    .to_string();
    let plan_response = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "decision": "claim",
            "plugins": [{
                "name": "python-lift",
                "kind": "lift",
                "surface": "python"
            }],
            "diagnostics": [{
                "level": "info",
                "message": "python lift component planned"
            }]
        }
    })
    .to_string();
    let shutdown_response = json!({
        "jsonrpc": "2.0",
        "id": 3,
        "result": null
    })
    .to_string();
    fs::write(
        &component_script,
        format!(
            r#"while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{initialize_response}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '%s\n' '{plan_response}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{shutdown_response}'
      exit 0
      ;;
  esac
done
"#
        ),
    )
    .expect("write python component script");
    fs::write(
        sugar
            .join("components")
            .join("python-lift")
            .join("manifest.toml"),
        format!(
            "name = \"python-lift-component\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"/bin/sh\", {}]\n",
            toml_string(&component_script.display().to_string())
        ),
    )
    .expect("write python component manifest");
    project
}

fn run_sugar(project: &Path, args: &[&str]) -> (Json, i32, String, String) {
    let out = Command::new(sugar_bin())
        .args(args)
        .current_dir(project)
        .env("PYTHONPATH", python_lift_pythonpath())
        .env_remove("SUGAR_COMPONENT_PATH")
        .output()
        .expect("spawn sugar");
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    let stderr = String::from_utf8_lossy(&out.stderr).to_string();
    let json = serde_json::from_str(&stdout)
        .unwrap_or_else(|e| panic!("JSON parse failed: {e}\nstdout: {stdout}\nstderr: {stderr}"));
    (json, out.status.code().unwrap_or(-1), stdout, stderr)
}

fn run_mint(project: &Path) {
    let out = Command::new(sugar_bin())
        .args(["mint", "--out", ".", "--quiet"])
        .current_dir(project)
        .env("PYTHONPATH", python_lift_pythonpath())
        .env_remove("SUGAR_COMPONENT_PATH")
        .output()
        .expect("spawn mint");
    assert!(
        out.status.success(),
        "mint must succeed\nstdout: {}\nstderr: {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}

fn row<'a>(doc: &'a Json, needle: &str) -> &'a Json {
    doc.get("rows")
        .and_then(Json::as_array)
        .expect("rows")
        .iter()
        .find(|row| {
            row.get("property")
                .and_then(Json::as_str)
                .unwrap_or_default()
                .contains(needle)
        })
        .unwrap_or_else(|| panic!("missing row containing `{needle}` in {doc:#}"))
}

fn assert_tooling_available() -> bool {
    if !python_available() || !z3_available() || !python_deps_available() {
        eprintln!(
            "python3/z3/python deps unavailable: skipping Python chain consistency regression"
        );
        return false;
    }
    true
}

#[test]
fn python_chain_good_twin_composes_body_discharge_with_consistency() {
    if !assert_tooling_available() {
        return;
    }

    let project = stage_chain_project("good", 6);
    run_mint(&project);

    let (prove, prove_code, _, _) = run_sugar(&project, &["prove", ".", "--json"]);
    assert_eq!(
        prove_code, 0,
        "GOOD chain must prove through call:g(5)==call:h(5) and call:h(5)==6; prove: {prove:#}"
    );
    assert_eq!(row(&prove, "#euf#")["status"], "discharged");
    assert_eq!(row(&prove, "h#euf#")["status"], "discharged");

    let (verify, verify_code, _, _) = run_sugar(&project, &["verify", "--project", ".", "--json"]);
    assert_eq!(
        verify_code, 0,
        "GOOD chain durable proof must verify; verify: {verify:#}"
    );
    assert_eq!(row(&verify, "#euf#")["status"], "discharged");

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_chain_bad_twin_refutes_through_the_same_call_seam() {
    if !assert_tooling_available() {
        return;
    }

    let project = stage_chain_project("bad", 99);
    run_mint(&project);

    let (prove, prove_code, _, _) = run_sugar(&project, &["prove", ".", "--json"]);
    assert_ne!(prove_code, 0, "BAD chain must not prove; prove: {prove:#}");
    assert_eq!(row(&prove, "#euf#")["status"], "unsatisfied");

    let (verify, verify_code, _, _) = run_sugar(&project, &["verify", "--project", ".", "--json"]);
    assert_ne!(
        verify_code, 0,
        "BAD chain durable proof must not verify; verify: {verify:#}"
    );
    assert_eq!(row(&verify, "#euf#")["status"], "unsatisfied");

    let _ = fs::remove_dir_all(&project);
}
