// SPDX-License-Identifier: MIT OR Apache-2.0
//
// END-TO-END REGRESSION for the ambient-universal forall-rewrite
// (`with_ambient_foralls`): a `#euf#` obligation conjoins a lifted universal
// contract as a `forall` QUANTIFIER (not materialized ground instances), and the
// solver instantiates it via e-matching. This test proves the WHOLE production
// pipeline does real work, through the real `sugar` CLI with a real lifter and a
// real config/manifest -- NOT library calls, NOT hand-built IR/proof JSON.
//
// THE MEDAL PROPERTY (why a quantifier, not materialization, is required):
// the lifted universe must decide an input that NO assertion ever named.
//
//   * VENDOR source (`tests/vendor.rs`): a bounded loop
//         for x in 0..5 { assert_eq!(g(x), 1); }
//     lifts to the universe `forall x in 0..5. g(x) == 1`. This is the ONLY thing
//     covering the in-range inputs -- there are NO per-point vendor assertions
//     `g(3)==..`/`g(4)==..` anywhere.
//   * USER sources (separate files -> separate `#euf#` callsite mementos):
//         tests/user_false.rs:  assert_eq!(g(3), 2);   // x=3 named nowhere else
//         tests/user_true.rs:   assert_eq!(g(4), 1);   // x=4 named nowhere else
//
// We detect MEANING by verifier rows, never by string/AST matching:
//   * g(3)==2  -> UNSATISFIED  (z3 instantiates the universe at x=3: g(3)==1,
//                 contradicting g(3)==2 -- EUF: a pure g(3) has one value).
//   * g(4)==1  -> DISCHARGED   (the lifted universe is minted as a Derived member:
//                 Sugar's temporal floor walked the literal range `0..5` and
//                 counted the universe by its own construction path, so it is
//                 independent testimony -- an independent-KIND witness that
//                 corroborates the user's g(4)==1. See T's Part-2 ruling, #3445).
// The universe decides BOTH un-named inputs: it refutes the false one and
// corroborates the true one. `g`'s body is opaque (the fn is never defined in the
// fixture), so the ONLY source of g's behavior is the lifted universe -- a
// discharge of g(4) can therefore come only from the floor-derived universe.
//
// REAL-WORK PROOF (non-triviality): an identical fixture WITHOUT the vendor loop
// (no universe) must NOT refute `g(3)==2` -- it is refused as vacuous instead of
// becoming a green discharge. The unsat in the first fixture therefore came from
// the lifted universe, not a pattern. And because nothing ever materialized g(3),
// the contradiction can only come from z3 instantiating the conjoined `forall` --
// the exact behavior the rewrite enables.
//
// Requires `z3` on PATH; skips otherwise.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value as Json};

const USER_FALSE_EUF: &str =
    "consistency:tests/user_false.rs::user_false_claim::g#euf#c:callresult_g_a1(i:3)::assertion";
const USER_TRUE_EUF: &str =
    "consistency:tests/user_true.rs::user_true_claim::g#euf#c:callresult_g_a1(i:4)::assertion";
const VENDOR_LOOP: &str = "consistency:tests/vendor.rs::vendor_universe::loop::x";
const USER_TRUE_PANIC: &str =
    "consistency:tests/user_true.rs::user_true_claim::g#panic_callsite#euf#c:callresult_g_panic_callsite_a1(i:4)::assertion";
const USER_FALSE_PANIC: &str =
    "consistency:tests/user_false.rs::user_false_claim::g#panic_callsite#euf#c:callresult_g_panic_callsite_a1(i:3)::assertion";

#[derive(Debug, Clone, PartialEq, Eq)]
struct ProveRow {
    property: String,
    status: String,
}

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn rust_workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-cli has a parent workspace")
        .to_path_buf()
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

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-forall-universe-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir fixture");
    p
}

/// Build a fixture PROJECT. `with_vendor` controls whether the loop-universe
/// source is present. Plugin binaries are spawned via `cargo run` against the
/// workspace so the test is portable / CI-safe (no hardcoded binary paths).
fn build_fixture(with_vendor: bool, suffix: &str) -> PathBuf {
    let ws = rust_workspace();
    let dir = unique_dir(suffix);
    fs::create_dir_all(dir.join("tests")).unwrap();
    fs::create_dir_all(dir.join(".sugar/lift/rust-test-assertions")).unwrap();
    fs::create_dir_all(dir.join(".sugar/components/rust-test-assertions")).unwrap();
    fs::create_dir_all(dir.join(".sugar/ir-compilers/smt-lib")).unwrap();

    // USER sources: separate files -> separate `#euf#` callsite mementos. `g` is
    // intentionally UNDEFINED (opaque/EUF) so only the lifted universe constrains
    // it. x=3 and x=4 are named NOWHERE except (implicitly) by the universe.
    fs::write(
        dir.join("tests/user_false.rs"),
        "#[test]\nfn user_false_claim() {\n    assert_eq!(g(3), 2);\n}\n",
    )
    .unwrap();
    fs::write(
        dir.join("tests/user_true.rs"),
        "#[test]\nfn user_true_claim() {\n    assert_eq!(g(4), 1);\n}\n",
    )
    .unwrap();
    if with_vendor {
        // VENDOR source: the loop is the ONLY thing covering 0..5. No per-point
        // g(3)/g(4) assertions exist -- the universe alone constrains them.
        fs::write(
            dir.join("tests/vendor.rs"),
            "#[test]\nfn vendor_universe() {\n    for x in 0..5 {\n        assert_eq!(g(x), 1);\n    }\n}\n",
        )
        .unwrap();
    }

    fs::write(
        dir.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "rust-test-assertions-lift"
kind = "lift"
surface = "rust-test-assertions"
emit = "ir-document"

[platform_profile]
language = "rust"
library = "forall-universe-fixture"
version = "rustc 1.96.0"

[solvers]
mode = "first-wins"
portfolio = ["z3"]

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 30
version = "4.x"

[rust-test-assertions.target_cfg]
target = "x86_64-apple-darwin"
facts = ["test", "debug_assertions", "target_arch=\"x86_64\"", "target_pointer_width=\"64\"", "target_os=\"macos\"", "unix"]
"#,
    )
    .unwrap();

    // Lift plugin = the REAL rust-test-assertions RPC, via cargo run (builds on
    // demand; working_dir = workspace so `-p` resolves).
    fs::write(
        dir.join(".sugar/lift/rust-test-assertions/manifest.toml"),
        format!(
            r#"name = "rust-test-assertions-lift"
version = "0.1.0"
protocol_version = "pep/1.7.0"
kind = "lift"
command = ["cargo", "run", "-p", "sugar-lift-rust-tests", "--bin", "rust_test_assertions_rpc", "--quiet", "--"]
working_dir = "{ws}"

[capabilities]
authoring_surfaces = ["rust-test-assertions"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            ws = ws.display()
        ),
    )
    .unwrap();

    let component_script = dir
        .join(".sugar/components/rust-test-assertions")
        .join("component.sh");
    let lift_command = vec![
        "cargo",
        "run",
        "-p",
        "sugar-lift-rust-tests",
        "--bin",
        "rust_test_assertions_rpc",
        "--quiet",
        "--",
    ];
    let initialize_response = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "name": "rust-test-assertions-component",
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
                "name": "rust-test-assertions-lift",
                "kind": "lift",
                "surface": "rust-test-assertions",
                "emit": "ir-document"
            }],
            "lift_manifests": [{
                "surface": "rust-test-assertions",
                "name": "rust-test-assertions-lift",
                "version": "0.1.0",
                "protocol_version": "pep/1.7.0",
                "command": lift_command,
                "working_dir": ws.display().to_string()
            }],
            "diagnostics": [{
                "level": "info",
                "message": "rust-test-assertions component planned"
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
    .unwrap();
    fs::write(
        dir.join(".sugar/components/rust-test-assertions/manifest.toml"),
        format!(
            "name = \"rust-test-assertions-component\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"/bin/sh\", {}]\n",
            toml_string(&component_script.display().to_string())
        ),
    )
    .unwrap();

    // IR compiler = the REAL smt-lib compiler, via cargo run.
    fs::write(
        dir.join(".sugar/ir-compilers/smt-lib/manifest.toml"),
        format!(
            r#"name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["cargo", "run", "-p", "sugar-ir-compiler-smt-lib", "--bin", "sugar-ir-smt-lib", "--quiet", "--"]
working_dir = "{ws}"
dialects = ["smt-lib-v2.6"]
"#,
            ws = ws.display()
        ),
    )
    .unwrap();

    dir
}

/// Drive the real CLI: `sugar mint` (lift -> .proof) then `sugar prove --json`
/// (discharge the on-disk .proof). Returns (property, status) for every row.
fn mint_and_prove(dir: &Path) -> Vec<ProveRow> {
    let mint = Command::new(sugar_bin())
        .current_dir(dir)
        .arg("mint")
        .arg("--out")
        .arg(dir)
        .arg("--quiet")
        .output()
        .expect("spawn sugar mint");
    assert!(
        mint.status.success(),
        "sugar mint failed:\n  stdout: {}\n  stderr: {}",
        String::from_utf8_lossy(&mint.stdout),
        String::from_utf8_lossy(&mint.stderr)
    );

    let prove = Command::new(sugar_bin())
        .current_dir(dir)
        .arg("prove")
        .arg("--json")
        .arg("--z3")
        .arg("z3")
        .output()
        .expect("spawn sugar prove");
    let stdout = String::from_utf8_lossy(&prove.stdout);
    let doc: Json = serde_json::from_str(&stdout).unwrap_or_else(|e| {
        panic!(
            "prove JSON parse failed: {e}\nstdout: {stdout}\nstderr: {}",
            String::from_utf8_lossy(&prove.stderr)
        )
    });
    doc["rows"]
        .as_array()
        .expect("prove report has rows")
        .iter()
        .map(|r| ProveRow {
            property: r["property"].as_str().unwrap_or_default().to_string(),
            status: r["status"].as_str().unwrap_or_default().to_string(),
        })
        .collect()
}

fn assert_rows(rows: &[ProveRow], expected: &[(&str, &str)]) {
    let actual: Vec<(&str, &str)> = rows
        .iter()
        .map(|row| (row.property.as_str(), row.status.as_str()))
        .collect();
    assert_eq!(actual, expected, "prove rows changed: {rows:#?}");
}

#[test]
fn lifted_universe_refutes_false_unnamed_input_without_self_discharge() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping lifted-universe end-to-end test");
        return;
    }
    let dir = build_fixture(true, "with-universe");
    let rows = mint_and_prove(&dir);
    eprintln!("WITH UNIVERSE rows: {rows:?}");

    // The universe `forall x in 0..5. g(x)==1` REFUTES the user's g(3)==2 -- x=3
    // was never materialized; z3 instantiated the conjoined quantifier at 3.
    // The matching TRUE claim g(4)==1 is now DISCHARGED: the universe is minted as
    // a Derived member (Sugar's temporal floor counted it from the walked literal
    // range), so it is the independent-KIND witness the discharge law requires --
    // exactly the flip T's Part-2 ruling (#3445) authorized. The universe member
    // itself (VENDOR_LOOP) is a lone forall with no sibling to contradict, so it
    // stays refused; the panic-callsite rows have no covering universe of their
    // own sort and stay refused. Prove row order follows bridge-member traversal.
    assert_rows(
        &rows,
        &[
            (USER_FALSE_EUF, "unsatisfied"),
            (USER_FALSE_PANIC, "refused"),
            (USER_TRUE_EUF, "discharged"),
            (USER_TRUE_PANIC, "refused"),
            (VENDOR_LOOP, "refused"),
        ],
    );
    let _ = fs::remove_dir_all(&dir);
}

/// DISCRIMINATION twin (T's Part-2 ruling, #3445): a Stated-sourced covering fact
/// must NOT confirm a matching Stated user claim. The guard is unchanged; only the
/// FLOOR-DERIVED universe path flips. Here the vendor covers x=4 with a DIRECT
/// point assertion `assert_eq!(g(4), 1)` -- a vendor STATED fact, not a universe
/// Sugar's temporal floor counted from program structure. Its provenance stays
/// Stated, so it cannot corroborate the user's Stated `g(4)==1`: g(4) stays
/// REFUSED (Stated->Stated still refuses; MissingIndependentKindWitness intact).
#[test]
fn stated_point_source_does_not_confirm_matching_true_claim() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping Stated-point discrimination twin");
        return;
    }
    let dir = build_fixture(true, "stated-point");
    // Replace the floor-derived loop universe with a direct vendor point assertion.
    fs::write(
        dir.join("tests/vendor.rs"),
        "#[test]\nfn vendor_point() {\n    assert_eq!(g(4), 1);\n}\n",
    )
    .unwrap();
    let rows = mint_and_prove(&dir);
    eprintln!("STATED POINT rows: {rows:?}");
    let status_of = |property: &str| -> Option<&str> {
        rows.iter()
            .find(|row| row.property == property)
            .map(|row| row.status.as_str())
    };
    // The Stated point cannot confirm the user's matching Stated claim.
    assert_eq!(
        status_of(USER_TRUE_EUF),
        Some("refused"),
        "a Stated point source must not self-discharge a matching Stated user claim: {rows:#?}"
    );
    // No universe covers x=3, so the lying g(3)==2 cannot be refuted here (refused
    // as a lone uncorroborated constraint, NOT unsatisfied) -- the refutation in
    // the acceptance test came from the floor-derived universe, not a point fact.
    assert_eq!(
        status_of(USER_FALSE_EUF),
        Some("refused"),
        "without a covering universe the lying point is refused, not refuted: {rows:#?}"
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn unnamed_input_is_refused_without_the_lifted_universe() {
    if !z3_available() {
        eprintln!("z3 not on PATH: skipping real-work-proof test");
        return;
    }
    // Same user sources, but the vendor loop (the universe) is GONE.
    let dir = build_fixture(false, "no-universe");
    let rows = mint_and_prove(&dir);
    eprintln!("NO UNIVERSE rows: {rows:?}");

    // With nothing constraining g, the previously-refuted g(3)==2 is now
    // REFUSED as a vacuous single constraint. The unsat in the other test
    // therefore came from the lifted universe (real work), not a pattern -- and
    // could only come from z3 instantiating the `forall` at x=3, which nothing
    // materialized.
    // The twin keeps the same row-order law while proving the lying EUF is still
    // refused when the universe is absent.
    assert_rows(
        &rows,
        &[
            (USER_FALSE_EUF, "refused"),
            (USER_FALSE_PANIC, "refused"),
            (USER_TRUE_EUF, "refused"),
            (USER_TRUE_PANIC, "refused"),
        ],
    );
    let _ = fs::remove_dir_all(&dir);
}
