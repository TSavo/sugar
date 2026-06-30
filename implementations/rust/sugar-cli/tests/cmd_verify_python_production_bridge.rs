// SPDX-License-Identifier: Apache-2.0
//
// PYTHON end-to-end production-bridge gauntlet -- the Python analog of
// `cmd_verify_go_production_bridge.rs`. Proves the verification spine is
// LANGUAGE-NEUTRAL for Python: a Python function's body-derived contract lifts
// to ProofIR (`post = result == (* x 2)` plus `formals`) and the verifier
// discharges the obligation through the body via wp + z3, exactly as for Rust,
// Java, and Go.
//
// This drives the REAL verify-facing Python lift surface
// `sugar-lift-python-verify` (module
// `sugar_lift_python_source.verify_rpc`). That surface lifts the real
// Python sources in `examples/python-double`:
//
//   - `double.py`       -> function-contract `post = result == (* x 2)`
//                          (verify-facing dialect: `python:mul` normalized to
//                          `*`, `return_value` -> `result`, `python:return`
//                          wrapper stripped, `Int` sorts from the `: int`
//                          annotation).
//   - `test_double.py`  -> contract `inv = =(double(3), 6)` (Python Layer-0
//                          leaf-assertion harvester).
//
// `sugar mint` AUTO-WRITES the `double -> targetContractCid` bridge (#1443);
// the bridge is TOOL-written, asserted by inspecting `pool.bridges_by_symbol`.
// `sugar verify` then discharges both ways:
//
//   POSITIVE: `double(3) == 6` reduces through the body `(* 3 2) == 6` -> z3
//     discharges -> pass, signed witness, exit 0.
//   NEGATIVE: break the body to `x * 3` -> `(* 3 3) == 6` -> z3 refutes ->
//     Unsatisfied, exit 1, NO witness.
//
// Requires `python3` and `z3` on PATH; skips the solver-dependent asserts if z3
// is absent, and skips entirely (with a loud eprintln) if python3 is absent.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value as Json;

#[path = "support/contradiction.rs"]
mod contradiction;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

/// CARGO_MANIFEST_DIR = .../implementations/rust/sugar-cli; three parents up
/// is the repo root.
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

/// The verify-facing Python lifter source tree.
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
    let p = std::env::temp_dir().join(format!("sugar-py-prod-bridge-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir project");
    p
}

fn install_smt_compiler_manifest(project: &Path) {
    let manifest_dir = project.join(".sugar").join("ir-compilers").join("smt-lib");
    fs::create_dir_all(&manifest_dir).expect("mkdir ir compiler manifest");
    let rust_workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-cli has a parent workspace");
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            r#"name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["cargo", "run", "-p", "sugar-ir-compiler-smt-lib", "--bin", "sugar-ir-smt-lib", "--quiet", "--"]
working_dir = "{}"
dialects = ["smt-lib-v2.6"]
"#,
            rust_workspace.display()
        ),
    )
    .expect("write ir compiler manifest");
}

/// Write a small wrapper shell script that runs the verify-facing Python lift
/// surface with THIS checkout's source roots on `PYTHONPATH`, and return its
/// path. The Go test compiles a Go binary; Python is interpreted, so the analog
/// is a stable wrapper invoking `python3 -c "...; run_rpc()"`.
fn build_python_lift_verify() -> PathBuf {
    use std::io::Write as _;
    use std::sync::atomic::{AtomicU64, Ordering};
    // Unique per call: cargo runs the tests in this binary as parallel threads
    // of ONE process, so a `process::id()`-keyed path is SHARED across them.
    // One test exec'ing the wrapper while another truncates it for write =>
    // ETXTBSY (os error 26). An atomic counter gives each call its own path.
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let pythonpath = python_lift_pythonpath();
    let quoted_pythonpath = shell_single_quote(&pythonpath);
    let script = std::env::temp_dir().join(format!(
        "sugar-lift-python-verify-{}-{}.sh",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::Relaxed)
    ));
    let body = format!(
        "#!/bin/sh\nPYTHON=${{PYTHON:-python3}}\n\
         PYTHONPATH={quoted_pythonpath}${{PYTHONPATH:+:$PYTHONPATH}}\n\
         export PYTHONPATH\n\
         exec \"$PYTHON\" -c \"from sugar_lift_python_source.verify_rpc import run_rpc; run_rpc()\"\n"
    );
    // sync_all + drop the writer fd BEFORE chmod/spawn so `exec` never sees an
    // open writer (the second half of the ETXTBSY guard; see cli_surface.rs).
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

/// Copy the in-repo `examples/python-double` into a fresh tempdir, write the
/// `python` lift manifest pointing at the wrapper script, and (for the negative
/// case) mutate the body multiplier. Returns the tempdir project.
fn stage_python_project(suffix: &str, lift_script: &Path, body_factor: i64) -> PathBuf {
    let example = repo_root().join("examples").join("python-double");
    let project = unique_dir(suffix);

    // double.py: the library, with the body multiplier (2 honest, 3 broken).
    let double_src = format!("def double(x: int) -> int:\n    return x * {body_factor}\n");
    fs::write(project.join("double.py"), double_src).expect("write double.py");

    // test_double.py: copied verbatim (the harvested `double(3) == 6`).
    fs::copy(
        example.join("test_double.py"),
        project.join("test_double.py"),
    )
    .expect("copy test_double.py");

    // .sugar/config.toml: copied verbatim.
    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python")).expect("mkdir .sugar/lift/python");
    install_smt_compiler_manifest(&project);
    fs::copy(
        example.join(".sugar").join("config.toml"),
        sugar.join("config.toml"),
    )
    .expect("copy config.toml");

    // .sugar/lift/python/manifest.toml: point command[0] at the wrapper.
    let manifest = format!(
        "name = \"python\"\ncommand = [\"{}\", \"--rpc\"]\nworking_dir = \".\"\n",
        lift_script.display()
    );
    fs::write(
        sugar.join("lift").join("python").join("manifest.toml"),
        manifest,
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_precondition_project(suffix: &str, lift_script: &Path, arg: i64) -> PathBuf {
    let project = unique_dir(suffix);

    fs::write(
        project.join("bounded_digit.py"),
        r#"def bounded_digit(x: int) -> int:
    if x < 2 or x > 36:
        raise ValueError("x out of range")
    return x
"#,
    )
    .expect("write bounded_digit.py");

    fs::write(
        project.join("test_bounded_digit.py"),
        format!(
            "from bounded_digit import bounded_digit\n\n\n\
             def test_bounded_digit():\n    assert bounded_digit({arg}) == {arg}\n"
        ),
    )
    .expect("write test_bounded_digit.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python")).expect("mkdir .sugar/lift/python");
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
        format!(
            "name = \"python\"\ncommand = [\"{}\", \"--rpc\"]\nworking_dir = \".\"\n",
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
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

fn rewrite_manifest_command(manifest: &Path, command: &Path) {
    let text = fs::read_to_string(manifest)
        .unwrap_or_else(|_| panic!("read checked-in manifest {}", manifest.display()));
    let escaped = command
        .display()
        .to_string()
        .replace('\\', "\\\\")
        .replace('"', "\\\"");
    let rewritten = text
        .lines()
        .map(|line| {
            if line.trim_start().starts_with("command = ") {
                format!("command = [\"{escaped}\", \"--rpc\"]")
            } else {
                line.to_string()
            }
        })
        .collect::<Vec<_>>()
        .join("\n");
    fs::write(manifest, format!("{rewritten}\n"))
        .unwrap_or_else(|_| panic!("write manifest {}", manifest.display()));
}

fn run_mint(project: &Path) {
    let out = Command::new(sugar_bin())
        .arg("mint")
        .arg("--project")
        .arg(project)
        .arg("--out")
        .arg(project)
        .arg("--quiet")
        .output()
        .expect("spawn sugar mint");
    assert!(
        out.status.success(),
        "sugar mint must succeed\n  stdout: {}\n  stderr: {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}

fn run_verify_json_with_code(project: &Path, witness_dir: &Path) -> (Json, i32) {
    let out = Command::new(sugar_bin())
        .arg("verify")
        .arg("--project")
        .arg(project)
        .arg("--emit-witnesses")
        .arg(witness_dir)
        .arg("--json")
        .output()
        .expect("spawn sugar verify");
    let stdout = String::from_utf8_lossy(&out.stdout);
    let receipt = serde_json::from_str(&stdout)
        .unwrap_or_else(|e| panic!("verify JSON parse failed: {e}\nstdout: {stdout}"));
    (receipt, out.status.code().unwrap_or(-1))
}

#[test]
fn python_production_path_uses_checked_in_python_double_registration() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping checked-in python production-bridge test");
        return;
    }
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping checked-in python production-bridge test");
        return;
    }
    let lift_script = build_python_lift_verify();
    let project = unique_dir("checked-in-registration");
    let example = repo_root().join("examples").join("python-double");
    fs::copy(example.join("double.py"), project.join("double.py")).expect("copy double.py");
    fs::copy(
        example.join("test_double.py"),
        project.join("test_double.py"),
    )
    .expect("copy test_double.py");
    copy_dir_recursive(&example.join(".sugar"), &project.join(".sugar"));
    install_smt_compiler_manifest(&project);
    rewrite_manifest_command(
        &project
            .join(".sugar")
            .join("lift")
            .join("python")
            .join("manifest.toml"),
        &lift_script,
    );

    run_mint(&project);

    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);
    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    assert_eq!(receipt["ok"], true, "receipt: {receipt}");
    assert_eq!(
        code, 0,
        "checked-in Python route must prove; receipt: {receipt}"
    );

    let _ = fs::remove_dir_all(&project);
}

/// THE bridge-writer assertion (language-neutral, runs without z3): the TOOL
/// wrote a `bridge` member for `double` whose `targetContractCid` resolves to a
/// `contract` member carrying the body-derived `formals` + `post`. No
/// hand-bridging anywhere; the bridge came from `sugar mint`.
#[test]
fn python_mint_auto_writes_body_discharge_bridge() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python production-bridge bridge-writer test");
        return;
    }
    let lift_script = build_python_lift_verify();
    let project = stage_python_project("bridge", &lift_script, 2);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "tool-minted bundle must load cleanly: {:?}",
        pool.load_errors
    );

    // Validate the bridge was indexed by sourceSymbol (keeps error message listing indexed symbols).
    assert!(
        pool.bridges_by_symbol.contains_key("double"),
        "mint must auto-write + index a bridge with sourceSymbol=double; indexed: {:?}",
        pool.bridges_by_symbol.keys().collect::<Vec<_>>()
    );

    // Find bridge CID by scanning mementos for kind=bridge + sourceSymbol=double.
    let bridge_cid = pool
        .mementos
        .iter()
        .find(|(_, env)| {
            if let Ok(sugar_proof_envelope::Member::Bridge(b)) =
                sugar_proof_envelope::Member::from_value(env)
            {
                b.source_symbol == "double"
            } else {
                false
            }
        })
        .map(|(cid, _)| cid.clone())
        .unwrap_or_else(|| {
            panic!(
                "bridge for sourceSymbol=double not found in pool mementos; bridges: {:?}",
                pool.bridges_by_symbol.keys().collect::<Vec<_>>()
            )
        });

    let bridge_env = pool
        .mementos
        .get(&bridge_cid)
        .expect("bridge CID must exist in pool");
    let Ok(sugar_proof_envelope::Member::Bridge(bridge_m)) =
        sugar_proof_envelope::Member::from_value(bridge_env)
    else {
        panic!("bridge must parse as typed BridgeMember");
    };
    let target_cid = bridge_m.target_contract_cid.as_str().to_string();

    assert!(
        pool.mementos.contains_key(&target_cid),
        "bridge.targetContractCid {target_cid} must resolve to a member"
    );
    let target_env = pool
        .mementos
        .get(&target_cid)
        .expect("bridge target must exist in pool");
    let Ok(sugar_proof_envelope::Member::Contract(target_contract)) =
        sugar_proof_envelope::Member::from_value(target_env)
    else {
        panic!("bridge target must be a contract memento");
    };
    let formals = target_contract
        .formals
        .as_ref()
        .expect("tool-written op-contract must carry formals");
    assert_eq!(
        formals.first().map(|s| s.as_str()),
        Some("x"),
        "op-contract formals must be [x]"
    );
    assert!(
        target_contract.post.is_some(),
        "op-contract must carry the body-derived post"
    );

    let _ = fs::remove_dir_all(&project);
}

/// POSITIVE end-to-end: real Python lifter, tool-written bridge, verify
/// discharges through the body `(* x 2)`, signed witness, exit 0.
#[test]
fn python_production_path_double_discharges_and_mints_witness() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python production-bridge positive test");
        return;
    }
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping python production-bridge positive test");
        return;
    }
    let lift_script = build_python_lift_verify();
    let project = stage_python_project("pos", &lift_script, 2);
    run_mint(&project);

    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    assert_eq!(
        receipt["kind"], "verification-receipt",
        "receipt: {receipt}"
    );
    assert_eq!(
        receipt["totalClaims"], 1,
        "exactly one body-bearing callsite (the tool-written bridge made double(3) enumerate); receipt: {receipt}"
    );
    let claim = &receipt["claims"].as_array().expect("claims")[0];
    assert_eq!(
        claim["pass"], true,
        "double(3)==6 must discharge through body (* x 2); claim: {claim}"
    );
    assert_eq!(claim["status"], "discharged", "claim: {claim}");

    let solver = claim["dischargingSolver"].as_str().unwrap_or("");
    assert!(
        solver.starts_with("z3@"),
        "discharging solver must be z3; got `{solver}`"
    );

    let witness_cid = claim["witnessCid"].as_str().expect("witness minted");
    assert!(witness_cid.starts_with("blake3-512:"));
    eprintln!("PYTHON_PRODUCTION_POSITIVE_WITNESS_CID={witness_cid}");

    assert_eq!(receipt["ok"], true, "receipt: {receipt}");
    assert_eq!(code, 0, "positive run exits clean; got {code}");

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_precondition_body_guard_discharges_good_and_refuses_bad_callsite() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python precondition bridge test");
        return;
    }
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping python precondition bridge test");
        return;
    }
    let lift_script = build_python_lift_verify();

    let good_project = stage_python_precondition_project("pre-good", &lift_script, 16);
    run_mint(&good_project);
    let good_witnesses = good_project.join("witnesses-out");
    let (good, good_code) = run_verify_json_with_code(&good_project, &good_witnesses);
    assert_eq!(good["totalClaims"], 1, "GOOD receipt: {good}");
    let good_claim = &good["claims"].as_array().expect("claims")[0];
    assert_eq!(
        good_claim["status"], "discharged",
        "GOOD claim: {good_claim}"
    );
    assert_eq!(good_claim["pass"], true, "GOOD claim: {good_claim}");
    assert_eq!(good["ok"], true, "GOOD receipt: {good}");
    assert_eq!(good_code, 0, "GOOD verify exit code");

    let bad_project = stage_python_precondition_project("pre-bad", &lift_script, 1);
    run_mint(&bad_project);
    let bad_witnesses = bad_project.join("witnesses-out");
    let (bad, bad_code) = run_verify_json_with_code(&bad_project, &bad_witnesses);
    assert_eq!(bad["totalClaims"], 1, "BAD receipt: {bad}");
    let bad_claim = &bad["claims"].as_array().expect("claims")[0];
    assert_eq!(
        bad_claim["status"], "unsatisfied",
        "BAD callsite must violate bounded_digit precondition: {bad_claim}"
    );
    assert_eq!(bad_claim["pass"], false, "BAD claim: {bad_claim}");
    assert!(
        bad_claim["witnessCid"].is_null(),
        "BAD precondition violation must not mint a witness: {bad_claim}"
    );
    assert_eq!(bad["ok"], false, "BAD receipt: {bad}");
    assert_eq!(bad_code, 1, "BAD verify exit code");

    let _ = fs::remove_dir_all(&good_project);
    let _ = fs::remove_dir_all(&bad_project);
}

/// NEGATIVE end-to-end: broken body `x * 3`, verify Unsatisfied, exit 1, no
/// witness. The decisive proof the tool-written bridge does not vacuously pass:
/// a real violation is caught honestly.
#[test]
fn python_production_path_broken_body_fails_unsatisfied_no_witness() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python production-bridge negative test");
        return;
    }
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping python production-bridge negative test");
        return;
    }
    let lift_script = build_python_lift_verify();
    let project = stage_python_project("neg", &lift_script, 3);
    run_mint(&project);

    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);

    assert_eq!(receipt["totalClaims"], 1, "receipt: {receipt}");
    let claim = &receipt["claims"].as_array().expect("claims")[0];
    assert_eq!(
        claim["status"], "unsatisfied",
        "broken body x*3 must be UNSATISFIED (not undecidable); claim: {claim}"
    );
    assert_eq!(claim["pass"], false, "claim: {claim}");
    assert!(
        claim["witnessCid"].is_null(),
        "no witness for a violated claim; claim: {claim}"
    );
    assert_eq!(receipt["ok"], false, "receipt: {receipt}");

    let witness_files: Vec<_> = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).collect())
        .unwrap_or_default();
    assert!(
        witness_files.is_empty(),
        "witness dir must be empty for a violated claim; found {} files",
        witness_files.len()
    );

    assert_eq!(
        code, 1,
        "broken-body claim must exit 1 (EXIT_VERIFY_FAIL, not 3=undecidable); got {code}"
    );
    eprintln!(
        "PYTHON_PRODUCTION_NEGATIVE_EXIT_CODE={code} STATUS={}",
        claim["status"]
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_production_path_refuses_planted_contradictory_implication() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python contradictory-implication test");
        return;
    }
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping python contradictory-implication test");
        return;
    }
    let lift_script = build_python_lift_verify();
    let project = stage_python_project("contradiction", &lift_script, 2);
    run_mint(&project);

    let (green, green_code) = contradiction::run_prove_json_with_code(&sugar_bin(), &project);
    assert_eq!(
        green_code, 0,
        "base Python project must prove before planting contradiction; report: {green}"
    );
    contradiction::assert_green_proves_one_bridge(&green, green_code);

    contradiction::plant_contradictory_implication_proof(
        &project.join(".sugar"),
        "python",
        "python-tests",
        "python_parity",
    );
    let (red, red_code) = contradiction::run_prove_json_with_code(&sugar_bin(), &project);
    contradiction::assert_prove_refuses_contradiction(
        &red,
        red_code,
        "python_parity_requires_positive",
    );

    let _ = fs::remove_dir_all(&project);
}
