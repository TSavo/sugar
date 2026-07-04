// SPDX-License-Identifier: MIT OR Apache-2.0
//
// CARDINAL-SIN REGRESSION (Python analog of `cmd_verify_go_division_unsound.rs`):
// the verify-facing Python lifter must NEVER sign a witness for a Python-false
// statement via an op whose SMT-LIB semantics diverge from Python.
//
// Python integer floor-division `//` and modulo `%` (and true division `/`,
// which is float) have no faithful SMT-LIB-core mapping for signed ints:
//   Python `-7 // 2 == -4` (floor toward -inf)
//   SMT    `(div -7 2) == -4`  -- coincidentally agrees on THIS axis, but
//          truncation/float semantics diverge elsewhere, and we refuse to
//          model any of them.
//
// The verify-facing dialect (`verify_dialect.py`) therefore leaves
// `python:floordiv` / `python:div` / `python:mod` UNINTERPRETED (namespaced).
// The function-contract and its auto-bridge are STILL written, so the
// body-discharge seam resolves the callee and runs wp -- which hits the opaque
// op and returns a refusal, so verify reports Undecidable
// (EXIT_SOLVER_FAIL = 3) with NO witness. That is the honest "I cannot prove
// this", and it routes through the SAME proven-safe wp-refusal path Go's
// `go:div` does (NOT a fall-through that risks a vacuous pass).
//
// This test drives the REAL Python lifter + REAL `sugar mint`/`verify` and
// asserts: NO discharge, NO signed witness, exit 3. Both the Python-false
// (`-4`) and Python-true (`-3`) assertions become Undecidable -- that is
// correct; the cardinal point is that NEITHER false-discharges.
//
// Requires `python3` and `z3` on PATH; guards skip loudly otherwise.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

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

fn python_source_lift_src() -> PathBuf {
    repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-lift-python-source")
        .join("src")
}

fn python_test_lift_src() -> PathBuf {
    repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-lift-py-tests")
        .join("src")
}

fn python_lift_pythonpath() -> String {
    std::env::join_paths([python_source_lift_src(), python_test_lift_src()])
        .expect("join Python lift source roots")
        .into_string()
        .expect("Python lift source roots must be UTF-8")
}

fn shell_single_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn toml_string(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn python_available() -> bool {
    Command::new("python3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-py-divunsound-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn build_python_lift_verify() -> PathBuf {
    use std::io::Write as _;
    use std::sync::atomic::{AtomicU64, Ordering};
    // Unique per call: parallel tests in this binary share one process id, so a
    // pid-keyed path collides (ETXTBSY when one execs while another writes).
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let pythonpath = python_lift_pythonpath();
    let quoted_pythonpath = shell_single_quote(&pythonpath);
    let script = std::env::temp_dir().join(format!(
        "sugar-lift-python-verify-div-{}-{}.sh",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::Relaxed)
    ));
    let body = format!(
        "#!/bin/sh\nPYTHON=${{PYTHON:-python3}}\n\
         PYTHONPATH={quoted_pythonpath}${{PYTHONPATH:+:$PYTHONPATH}}\n\
         export PYTHONPATH\n\
         exec \"$PYTHON\" -c \"from sugar_lift_python_source.verify_rpc import run_rpc; run_rpc()\"\n"
    );
    // sync_all + drop writer fd before chmod/spawn so exec never sees an open writer.
    {
        let mut f = fs::File::create(&script).expect("create python lift wrapper");
        f.write_all(body.as_bytes())
            .expect("write python lift wrapper");
        f.sync_all().expect("sync python lift wrapper");
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&script).expect("stat wrapper").permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&script, perms).expect("chmod wrapper");
    }
    script
}

/// Stage a `halve(x) = x // 2` project whose harvested assertion is
/// `halve(-7) == expected`. `expected = -4` is the value SMT floor-div would
/// give; `-3` is truncation. Both must be Undecidable with `//` uninterpreted.
fn stage_halve_project(suffix: &str, lift_script: &Path, expected: i64) -> PathBuf {
    let example = repo_root().join("examples").join("python-double");
    let project = unique_dir(suffix);

    fs::write(
        project.join("halve.py"),
        "def halve(x: int) -> int:\n    return x // 2\n",
    )
    .expect("write halve.py");
    fs::write(
        project.join("test_halve.py"),
        format!(
            "from halve import halve\n\n\ndef test_halve():\n    assert halve(-7) == {expected}\n"
        ),
    )
    .expect("write test_halve.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python")).expect("mkdir lift/python");
    fs::create_dir_all(sugar.join("components").join("python-lift"))
        .expect("mkdir components/python-lift");
    fs::copy(
        example.join(".sugar").join("config.toml"),
        sugar.join("config.toml"),
    )
    .expect("copy config.toml");
    let manifest = format!(
        "name = \"python\"\ncommand = [\"{}\", \"--rpc\"]\nworking_dir = \".\"\n",
        lift_script.display()
    );
    fs::write(
        sugar.join("lift").join("python").join("manifest.toml"),
        manifest,
    )
    .expect("write manifest");
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

fn run_mint(project: &Path) {
    let out = Command::new(sugar_bin())
        .args(["mint", "--project"])
        .arg(project)
        .arg("--out")
        .arg(project)
        .args(["--quiet"])
        .output()
        .expect("spawn mint");
    assert!(
        out.status.success(),
        "mint must succeed\n  stderr: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}

fn run_verify(project: &Path, witness_dir: &Path) -> (Json, i32) {
    let out = Command::new(sugar_bin())
        .args(["verify", "--project"])
        .arg(project)
        .arg("--emit-witnesses")
        .arg(witness_dir)
        .arg("--json")
        .output()
        .expect("spawn verify");
    let stdout = String::from_utf8_lossy(&out.stdout);
    let receipt = serde_json::from_str(&stdout)
        .unwrap_or_else(|e| panic!("verify JSON parse failed: {e}\nstdout: {stdout}"));
    (receipt, out.status.code().unwrap_or(-1))
}

/// Assert that the `halve(-7) == expected` claim does NOT discharge, writes NO
/// witness, and exits 3 (Undecidable) -- never a false discharge.
fn assert_undecidable_no_witness(suffix: &str, expected: i64) {
    let lift_script = build_python_lift_verify();
    let project = stage_halve_project(suffix, &lift_script, expected);
    run_mint(&project);

    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify(&project, &witnesses);

    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    let claim = &receipt["claims"].as_array().expect("claims")[0];
    assert_eq!(
        claim["pass"], false,
        "an integer-division claim must NEVER discharge (// is uninterpreted); claim: {claim}"
    );
    assert_ne!(
        claim["status"], "discharged",
        "CARDINAL SIN: a division claim discharged -- inverted proof regression; claim: {claim}"
    );
    assert_eq!(
        claim["status"], "undecidable",
        "division claim must be Undecidable; claim: {claim}"
    );
    assert!(
        claim["witnessCid"].is_null(),
        "NO signed witness may exist for a division claim; claim: {claim}"
    );

    let witness_files: Vec<_> = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).collect())
        .unwrap_or_default();
    assert!(
        witness_files.is_empty(),
        "witness dir must be empty for a division claim; found {} files",
        witness_files.len()
    );

    assert_eq!(
        code, 3,
        "division claim must exit 3 (EXIT_SOLVER_FAIL / undecidable), not 0 (discharged); got {code}"
    );
    eprintln!(
        "PYTHON_DIV_UNSOUND_GUARD expected={expected} status=undecidable exit={code} witnesses=0"
    );

    let _ = fs::remove_dir_all(&project);
}

/// The Python-false-under-truncation assertion `halve(-7) == -4` must NOT
/// discharge and must write NO witness -- the inverted-proof guard.
#[test]
fn python_division_floor_value_assertion_does_not_false_discharge() {
    if !python_available() || !z3_available() {
        eprintln!("python3/z3 not on PATH: skipping python division unsoundness regression");
        return;
    }
    assert_undecidable_no_witness("floor-neg4", -4);
}

/// The truncation-value assertion `halve(-7) == -3` is ALSO Undecidable with
/// `//` uninterpreted -- correct: we refuse rather than risk an unfaithful
/// model.
#[test]
fn python_division_trunc_value_assertion_is_undecidable_not_discharged() {
    if !python_available() || !z3_available() {
        eprintln!("python3/z3 not on PATH: skipping");
        return;
    }
    assert_undecidable_no_witness("trunc-neg3", -3);
}
