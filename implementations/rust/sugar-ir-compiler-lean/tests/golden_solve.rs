// SPDX-License-Identifier: MIT OR Apache-2.0
//
// golden-coq-lean-targets: Lean solve-golden test.
//
// Compiles the SAME pinned ProofIR fixture as `golden_compile.rs`, shells
// out to the real `lake env lean` pipeline, and asserts the golden script
// actually discharges (no `sorry`/`sorryAx` in the axiom listing). Gated on
// the SAME env-gating idiom this codebase already uses for real Lean+mathlib
// solver tests (see `sugar-verifier/tests/lean_solver.rs`:
// `binary_on_path("lake")` + `binary_on_path("lean")` + a Lake project
// directory containing `lakefile.lean`, found via `SUGAR_LEAN_PROJECT` or
// the default `/opt/lean-mathlib` install path documented in
// `tools/portfolio/lean-mathlib-install.md`). Green when a mathlib-backed
// Lake project is present, cleanly SKIPPED (not red) when it is not.
//
// Unlike Coq (a bare `coqc` binary suffices) Lean's `import Mathlib` needs a
// resolved Lake project with prebuilt `.olean` caches; that is a multi-GB,
// separately-provisioned dependency (see the install doc), not something
// this crate's test suite can assume is present. This is the crate's
// existing idiom for that gap, reused rather than reinvented.
//
// A bad-twin control mirrors the Coq solve-golden test: negating the
// fixture's consequent produces a FALSE statement over the same hypothesis,
// which `aesop` must fail to close.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT};

/// Same fixture as `golden_compile.rs::fixture()`, reproduced inline
/// (self-contained test file, matching this crate's existing convention,
/// e.g. `subprocess.rs` / `lowering.rs`) rather than importing that file's
/// module, which would re-register its `#[test]`s under this binary too.
fn golden_fixture() -> serde_json::Value {
    json!({
        "kind": "forall",
        "name": "x",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "implies",
            "operands": [
                {"kind": "and", "operands": [
                    {"kind": "atomic", "name": ">", "args": [
                        {"kind": "var", "name": "x"},
                        {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                    ]},
                    {"kind": "atomic", "name": "<", "args": [
                        {"kind": "var", "name": "x"},
                        {"kind": "const", "value": 10, "sort": {"kind": "primitive", "name": "Int"}}
                    ]}
                ]},
                {"kind": "atomic", "name": ">", "args": [
                    {"kind": "var", "name": "x"},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]}
            ]
        }
    })
}

/// Bad-twin: same hypothesis, FALSE consequent (`x < 0` contradicts `x > 0`).
fn bad_twin_fixture() -> serde_json::Value {
    json!({
        "kind": "forall",
        "name": "x",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "implies",
            "operands": [
                {"kind": "and", "operands": [
                    {"kind": "atomic", "name": ">", "args": [
                        {"kind": "var", "name": "x"},
                        {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                    ]},
                    {"kind": "atomic", "name": "<", "args": [
                        {"kind": "var", "name": "x"},
                        {"kind": "const", "value": 10, "sort": {"kind": "primitive", "name": "Int"}}
                    ]}
                ]},
                {"kind": "atomic", "name": "<", "args": [
                    {"kind": "var", "name": "x"},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]}
            ]
        }
    })
}

fn compile_script(ir: serde_json::Value) -> String {
    let input = CompilerInput::decode_json(ir).expect("fixture decodes");
    LeanCompiler::new()
        .compile_typed(&input, DIALECT)
        .expect("compile")
        .script()
}

fn binary_on_path(name: &str) -> bool {
    Command::new(name)
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Locate a Lake project with a resolved mathlib, exactly as
/// `sugar-verifier/tests/lean_solver.rs::lean_project_dir` does: prefer
/// `SUGAR_LEAN_PROJECT`, fall back to `/opt/lean-mathlib`, require
/// `lakefile.lean` to be present in either.
fn lean_project_dir() -> Option<PathBuf> {
    if let Ok(path) = std::env::var("SUGAR_LEAN_PROJECT") {
        let project = PathBuf::from(path);
        if project.join("lakefile.lean").is_file() {
            return Some(project);
        }
        eprintln!(
            "skipping: SUGAR_LEAN_PROJECT does not contain lakefile.lean: {}",
            project.display()
        );
        return None;
    }
    let project = PathBuf::from("/opt/lean-mathlib");
    if project.join("lakefile.lean").is_file() {
        Some(project)
    } else {
        eprintln!("skipping: SUGAR_LEAN_PROJECT is not set and /opt/lean-mathlib is absent");
        None
    }
}

/// Write `script` to `dir/name.lean` and run `lake env lean` on it from
/// `project`. Returns the captured stdout+stderr and whether the process
/// exited successfully.
fn lake_env_lean(project: &Path, dir: &Path, name: &str, script: &str) -> (bool, String) {
    let path = dir.join(format!("{name}.lean"));
    std::fs::write(&path, script).expect("write .lean fixture");
    let output = Command::new("lake")
        .args(["env", "lean"])
        .arg(&path)
        .current_dir(project)
        .output()
        .expect("spawn lake env lean");
    let combined = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    (output.status.success(), combined)
}

#[test]
fn lake_env_lean_discharges_the_golden_script_and_refutes_its_bad_twin() {
    if !binary_on_path("lake") {
        eprintln!("SKIP: lake not on PATH; install Lean+Lake to run this test.");
        return;
    }
    if !binary_on_path("lean") {
        eprintln!("SKIP: lean not on PATH; install Lean to run this test.");
        return;
    }
    let Some(project) = lean_project_dir() else {
        return;
    };

    let dir = std::env::temp_dir().join(format!(
        "sugar-lean-golden-solve-{}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).expect("create scratch dir");

    let golden_script = compile_script(golden_fixture());
    assert_eq!(
        golden_script,
        include_str!("fixtures/golden_and_implies.lean"),
        "golden_solve must exercise the exact same script golden_compile pins"
    );
    let (ok, out) = lake_env_lean(&project, &dir, "golden", &golden_script);
    assert!(ok, "lake env lean must discharge the golden fixture; output:\n{out}");
    assert!(
        !out.contains("sorryAx") && !out.contains("declaration uses 'sorry'"),
        "golden fixture must discharge without sorry; output:\n{out}"
    );

    let bad_script = compile_script(bad_twin_fixture());
    let (bad_ok, bad_out) = lake_env_lean(&project, &dir, "bad_twin", &bad_script);
    assert!(
        !bad_ok,
        "lake env lean must REJECT the bad-twin (false consequent contradicting the \
         hypothesis); a pass here means the golden test is vacuous. output:\n{bad_out}"
    );

    let _ = std::fs::remove_dir_all(&dir);
}
