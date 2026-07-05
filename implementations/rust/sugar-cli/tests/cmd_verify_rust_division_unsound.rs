// SPDX-License-Identifier: MIT OR Apache-2.0
//
// RUST INTEGER-DIVISION SOUNDNESS PROBE (#1446 rust-side equivalent).
//
// THE CARDINAL-SIN QUESTION: does the rust production verify path discharge
// (and SIGN A WITNESS FOR) a FALSE integer-division contract?
//
// The verifier's discharge path (`sugar_ir_compiler_smt_lib::compile_formula`)
// renders an IR `ctor` node's NAME VERBATIM as the SMT-LIB symbol, and does
// NOT pre-declare ctors as uninterpreted functions (only the asserted-formula
// path does). So whatever op symbol sits in the body-derived `post` is what
// z3 interprets under `(set-logic ALL)`:
//
//   * bare SMT `div` is a BUILTIN: z3 floors toward -inf.
//       (div -7 2) == -4    [Euclidean/floor in SMT-LIB]
//   * rust integer `/` TRUNCATES toward zero:
//       -7 / 2 == -3        [rust semantics]
//   * a NAMESPACED `concept:div` is NOT a z3 builtin and is NOT declared on
//       the discharge path, so z3 errors -> the obligation does NOT discharge
//       (honest refusal / undecidable). This is the SAFE shape.
//
// So for `fn halve(x: i64) -> i64 { x / 2 }`, the FALSE rust claim
// `halve(-7) == -4` becomes, after reducing through the body:
//   * ctor name "div" or "/": z3 sees (= (div -7 2) -4) -> TRUE in SMT ->
//       negation UNSAT -> DISCHARGES -> SIGNS WITNESS. INVERTED PROOF.
//   * ctor name "concept:div": z3 errors on the unknown symbol -> NO discharge.
//
// This test pins the verifier SEAM at each ctor name using the SAME mock-lifter
// pattern as `cmd_verify_production_bridge.rs` (the lifter is upstream of and
// orthogonal to the discharge, so a mock faithfully exercises the production
// mint+verify discharge without requiring an external Rust compiler oracle in
// the test environment).
//
// GATING REGRESSION: the SAFE namespaced shape (`concept:div`) MUST NOT
// discharge the FALSE contract and MUST write NO witness. If a bare-`div`
// shape ever reaches the discharge path it would false-discharge — that is the
// cardinal sin and is asserted-against here.
//
// Requires `z3` on PATH; skips the solver-dependent asserts otherwise.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value as Json};

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn z3_available() -> bool {
    Command::new("z3")
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
    let p = std::env::temp_dir().join(format!("sugar-rust-div-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir project");
    p
}

fn rust_workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-cli has a parent workspace")
        .to_path_buf()
}

fn install_smt_compiler_manifest(project: &Path) {
    let manifest_dir = project.join(".sugar").join("ir-compilers").join("smt-lib");
    fs::create_dir_all(&manifest_dir).expect("mkdir ir compiler manifest");
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
            rust_workspace().display()
        ),
    )
    .expect("write ir compiler manifest");
}

fn int_const(n: i64) -> Json {
    json!({"kind": "const", "value": n, "sort": {"kind": "primitive", "name": "Int"}})
}

/// Body-derived `function-contract` for `halve(x) = x <op> 2`, plus a
/// harvested assertion `halve(arg) == rhs`. `op` is the ctor NAME placed in
/// the body's binary node (e.g. "div", "/", "concept:div"). This mirrors the
/// shape walk's emit (`function-contract` with `formals`/`post`) and the
/// harvested `contract` (`inv = =(halve(arg), rhs)`); NO bridge -- the TOOL
/// writes that.
fn ir_document(op: &str, arg: i64, rhs: i64) -> Json {
    json!({
        "kind": "ir-document",
        "diagnostics": [],
        "ir": [
            {
                "kind": "function-contract",
                "fn_name": "halve",
                "formals": ["x"],
                "formalSorts": [{"kind": "primitive", "name": "Int"}],
                "returnSort": {"kind": "primitive", "name": "Int"},
                "outBinding": "result",
                "post": {
                    "kind": "atomic", "name": "=",
                    "args": [
                        {"kind": "var", "name": "result"},
                        {"kind": "ctor", "name": op, "args": [
                            {"kind": "var", "name": "x"},
                            int_const(2)
                        ]}
                    ]
                }
            },
            {
                "kind": "contract",
                "symbol": "halve_test",
                "outBinding": "out",
                "inv": {
                    "kind": "atomic", "name": "=",
                    "args": [
                        {"kind": "ctor", "name": "halve", "args": [int_const(arg)]},
                        int_const(rhs)
                    ]
                }
            }
        ]
    })
}

fn write_mock_lifter(project: &Path, surface: &str, op: &str, arg: i64, rhs: i64) {
    let lift_dir = project.join(".sugar").join("lift").join(surface);
    fs::create_dir_all(&lift_dir).expect("mkdir lift surface dir");

    let ir_doc = ir_document(op, arg, rhs);
    let init_result = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"name": surface, "protocol_version": "pep/1.7.0"}
    });
    let mut lift_obj = json!({"jsonrpc": "2.0", "id": 2})
        .as_object()
        .unwrap()
        .clone();
    lift_obj.insert("result".into(), ir_doc);
    let lift_line = serde_json::to_string(&Json::Object(lift_obj)).expect("serialize lift result");
    let init_line = serde_json::to_string(&init_result).expect("serialize init result");

    let script = format!(
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*|*'"method": "initialize"'*)
      printf '%s\n' '{init_line}'
      ;;
    *'"method":"lift"'*|*'"method": "lift"'*)
      printf '%s\n' '{lift_line}'
      ;;
    *'"method":"shutdown"'*|*'"method": "shutdown"'*)
      exit 0
      ;;
  esac
done
"#,
        init_line = init_line.replace('\'', "'\\''"),
        lift_line = lift_line.replace('\'', "'\\''"),
    );

    let script_path = lift_dir.join("mock-lifter.sh");
    fs::write(&script_path, script).expect("write mock lifter script");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&script_path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&script_path, perms).expect("chmod mock lifter");
    }

    let manifest = format!(
        "name = \"{surface}\"\ncommand = [\"{}\"]\nworking_dir = \".\"\n",
        script_path.display()
    );
    fs::write(lift_dir.join("manifest.toml"), manifest).expect("write manifest.toml");
}

/// Mint a halve project whose body uses ctor `op`, with harvested assertion
/// `halve(arg) == rhs`. Returns the project dir.
fn mint_halve_project(suffix: &str, op: &str, arg: i64, rhs: i64) -> PathBuf {
    let surface = "mock";
    let project = unique_dir(suffix);
    fs::create_dir_all(project.join(".sugar")).expect("mkdir .sugar");
    install_smt_compiler_manifest(&project);
    fs::write(
        project.join(".sugar").join("config.toml"),
        format!(
            "[authoring]\nsurface = \"{surface}\"\n\n\
             [solvers]\ndefault = \"z3\"\n\n\
             [solvers.dispatch]\nlinear_arithmetic = \"z3\"\ndefault = \"z3\"\n\n\
             [solvers.z3]\nbinary = \"z3\"\nir_compiler = \"smt-lib-v2.6\"\nflags = [\"-smt2\", \"-in\"]\n"
        ),
    )
    .expect("write config.toml");
    write_mock_lifter(&project, surface, op, arg, rhs);

    let out = Command::new(sugar_bin())
        .arg("mint")
        .arg("--project")
        .arg(&project)
        .arg("--out")
        .arg(&project)
        .arg("--quiet")
        .output()
        .expect("spawn sugar mint");
    assert!(
        out.status.success(),
        "sugar mint must succeed (op={op})\n  stdout: {}\n  stderr: {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    project
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

/// Drive the full mint+verify production path for one (op, arg, rhs) and
/// report (status, pass, witnessCid_is_some, exit_code, witness_files_present).
/// This is the empirical transcript-builder.
fn probe(op: &str, arg: i64, rhs: i64, suffix: &str) -> (String, bool, bool, i32, bool) {
    let project = mint_halve_project(suffix, op, arg, rhs);
    let witnesses = project.join("witnesses-out");
    let (receipt, code) = run_verify_json_with_code(&project, &witnesses);
    let claim = &receipt["claims"].as_array().expect("claims")[0];
    let status = claim["status"].as_str().unwrap_or("<none>").to_string();
    let pass = claim["pass"].as_bool().unwrap_or(false);
    let witness = claim["witnessCid"].as_str().is_some();
    let witness_files = fs::read_dir(&witnesses)
        .map(|rd| rd.filter_map(|e| e.ok()).count())
        .unwrap_or(0)
        > 0;
    eprintln!(
        "PROBE op={op} arg={arg} rhs={rhs} -> status={status} pass={pass} witness={witness} exit={code} witness_files={witness_files}"
    );
    let _ = fs::remove_dir_all(&project);
    (status, pass, witness, code, witness_files)
}

/// EMPIRICAL TRANSCRIPT: enumerate the three ctor-name shapes against the
/// FALSE contract (halve(-7) == -4, false in rust because -7/2 == -3) and the
/// TRUE contract (halve(-7) == -3) and the agreeing case (halve(6) == 3).
/// Prints the full transcript; runs without asserting so the verdict is
/// readable via --nocapture.
#[test]
fn rust_division_seam_transcript() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping rust-division transcript");
        return;
    }
    eprintln!("=== RUST DIVISION SOUNDNESS TRANSCRIPT (fn halve(x)= x / 2) ===");
    eprintln!("--- ctor name \"div\" (bare SMT builtin, floors) ---");
    probe("div", -7, -4, "div-false");
    probe("div", -7, -3, "div-true");
    probe("div", 6, 3, "div-agree");
    eprintln!("--- ctor name \"/\" (bare, the lift.rs:667 mapping) ---");
    probe("/", -7, -4, "slash-false");
    probe("/", -7, -3, "slash-true");
    probe("/", 6, 3, "slash-agree");
    eprintln!("--- ctor name \"concept:div\" (namespaced, walk_rpc.rs:3461 production) ---");
    probe("concept:div", -7, -4, "concept-false");
    probe("concept:div", -7, -3, "concept-true");
    probe("concept:div", 6, 3, "concept-agree");
}

/// Drive the REAL `sugar-walk-rpc` `walk.contract` method against rust
/// source and return the ctor `name` in the body-derived `post`. This is the
/// production function-contract builder (`build_function_contract_with_file` ->
/// `lift::lift_function_postcondition`); it is the syn-source path.
/// Returns the op-symbol the lifter actually emits for the body's `/`.
fn production_post_op_for_division() -> String {
    let req = json!({
        "jsonrpc": "2.0", "id": 1, "method": "walk.contract",
        "params": {"src": "fn halve(x: i64) -> i64 { x / 2 }", "fn_name": "halve", "file": "halve.rs"}
    });
    use std::io::Write;
    let mut command = if let Some(bin) = std::env::var("CARGO_BIN_EXE_sugar").ok().and_then(|p| {
        let dir = PathBuf::from(&p).parent()?.to_path_buf();
        let cand = dir.join("sugar-walk-rpc");
        cand.exists().then_some(cand)
    }) {
        Command::new(bin)
    } else {
        let mut command = Command::new("cargo");
        command
            .arg("run")
            .arg("-p")
            .arg("sugar-walk")
            .arg("--bin")
            .arg("sugar-walk-rpc")
            .arg("--quiet")
            .arg("--")
            .current_dir(rust_workspace());
        command
    };
    let mut child = command
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .expect("spawn sugar-walk-rpc");
    child
        .stdin
        .take()
        .unwrap()
        .write_all(format!("{req}\n").as_bytes())
        .expect("write rpc request");
    let out = child.wait_with_output().expect("walk-rpc output");
    let line = String::from_utf8_lossy(&out.stdout);
    let resp: Json = serde_json::from_str(line.lines().next().unwrap_or(""))
        .unwrap_or_else(|e| panic!("walk.contract JSON parse failed: {e}\nstdout: {line}"));
    resp["result"]["post"]["args"][1]["name"]
        .as_str()
        .unwrap_or_else(|| panic!("walk.contract post missing ctor name; resp: {resp}"))
        .to_string()
}

/// GATING REGRESSION (soundness): the REAL production rust lifter
/// (`sugar-walk-rpc walk.contract` -> `lift_function_postcondition`) emits
/// for `x / 2` an op symbol that MUST NOT be the bare SMT-LIB builtin `div`.
/// Bare `div` is the cardinal-sin shape: z3 floor-divides, so the FALSE rust
/// contract `halve(-7)==-4` would discharge + sign a witness (see the
/// transcript). This pins the syn-source LIFTER OUTPUT directly -- where the
/// regression risk lives (lift.rs op-name maps) -- so any silent rewrite of
/// the division op-name to bare `div` trips here.
#[test]
fn production_division_op_is_not_bare_smt_div() {
    let op = production_post_op_for_division();
    assert_ne!(
        op, "div",
        "PRODUCTION rust lifter must NOT emit bare SMT `div` for `/` (z3 floors -> false-discharge of halve(-7)==-4); got `{op}`"
    );
    // Today the production lifter emits `/` (real-division in z3 -> never
    // discharges integer division: soundness-safe but discipline-drifted; see
    // follow-up #1446). Pin the current symbol so a change is conscious.
    assert_eq!(
        op, "/",
        "production division op drifted from `/`; if intentional (e.g. to `concept:div`), update this pin and confirm it is NOT bare `div`; got `{op}`"
    );
    eprintln!("PRODUCTION_DIVISION_OP={op} (NOT bare `div`: soundness-safe)");
}

/// GATING REGRESSION (seam): drive mint+verify with the bare `/` symbol the
/// production lifter actually emits. It MUST NOT discharge the FALSE contract
/// halve(-7)==-4 and MUST write NO witness. (z3 reads `/` as real-division, so
/// it refutes everything integer -- never an inverted proof.)
#[test]
fn production_slash_false_contract_no_witness() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping production `/` regression");
        return;
    }
    let (status, pass, witness, _code, witness_files) = probe("/", -7, -4, "regr-slash-false");
    assert!(
        !pass,
        "PRODUCTION `/` MUST NOT discharge the FALSE contract halve(-7)==-4; status={status}"
    );
    assert_ne!(
        status, "discharged",
        "FALSE division contract must NOT be `discharged` on the production `/` path; status={status}"
    );
    assert!(
        !witness,
        "NO witness may be signed for a non-discharged false division contract"
    );
    assert!(
        !witness_files,
        "witness dir must be empty for a non-discharged false division contract"
    );
}

/// CHARACTERIZATION (NOT A GUARD): pins the UNSOUND behavior of the bare SMT
/// `div` symbol for the on-record documentation. This test ASSERTS the cardinal
/// sin happens (bare `div` floor-divides -> halve(-7)==-4 discharges + signs a
/// witness). It is a witness to the hazard, proving WHY bare `div` must never
/// reach the discharge path -- it is NOT a protection against it. The SOUNDNESS
/// GUARDS are `production_division_op_is_not_bare_smt_div` (lifter output) and
/// `production_slash_false_contract_no_witness` (seam). If a future change wires
/// bare `div` into the lifter, the GUARD trips, not this test.
#[test]
#[ignore = "Tests Product B (the from-scratch white-box panic/soundness seam), the \
overdoing the Python kit ships none of. Slated for demotion to the Python gold standard \
(Product A: lift assertions -> EUF contracts -> inheritance). Ignored rather than \
fixture-updated so the gate stops grading the overdoing. #1926"]
fn bare_div_seam_documents_unsound_floor_division() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping bare-div characterization");
        return;
    }
    // The AGREEING case (halve(6)==3) discharges regardless of op: seam exercised.
    let (status_agree, pass_agree, _w, _c, _wf) = probe("div", 6, 3, "char-agree");
    assert!(
        pass_agree && status_agree == "discharged",
        "sanity: halve(6)==3 must discharge (agreeing case); status={status_agree}"
    );

    // The divergent (-7) shape: bare `div` FLOORS, so the FALSE rust contract
    // halve(-7)==-4 DISCHARGES. This is the documented hazard.
    let (status_false, pass_false, witness_false, _c, _wf) = probe("div", -7, -4, "char-false");
    assert!(
        pass_false && status_false == "discharged" && witness_false,
        "DOCUMENTED HAZARD: bare `div` floor-divides so the FALSE contract halve(-7)==-4 \
         discharges + signs a witness. If this no longer holds, z3's `div` semantics or the \
         seam changed -- re-examine the soundness guards. status={status_false} pass={pass_false}"
    );
    eprintln!(
        "BARE_DIV_HAZARD: halve(-7)==-4 under bare `div` -> status={status_false} pass={pass_false} witness={witness_false} \
         (rust -7/2==-3, SMT floor-div==-4: this is why bare `div` must never reach discharge)"
    );
}
