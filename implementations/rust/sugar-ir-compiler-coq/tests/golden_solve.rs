// SPDX-License-Identifier: MIT OR Apache-2.0
//
// golden-coq-lean-targets: Coq solve-golden test.
//
// Compiles the SAME pinned ProofIR fixture as `golden_compile.rs`, shells
// out to the real `coqc` binary, and asserts the golden script actually
// discharges (`Qed` succeeds, exit 0). Gated on `coqc` presence following
// this codebase's existing env-gating idiom for real-binary solver tests
// (see `sugar-verifier/tests/three_way_consensus.rs::binary_on_path`):
// green when `coqc` is on PATH, cleanly skipped (not red) when it is not.
//
// A bad-twin control is included so the test is not vacuous: negating the
// fixture's consequent produces a FALSE statement over the same hypothesis,
// and `coqc` must reject it (non-zero exit). Without this, a compiler bug
// that always emits a script `coqc` happens to accept (or a `admit.`
// regression) would go unnoticed.

use std::path::Path;
use std::process::Command;

use serde_json::json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_coq::{CoqCompiler, DIALECT};

/// Same fixture as `golden_compile.rs::fixture()` and the SAME golden script
/// pinned there as `GOLDEN_SCRIPT`, reproduced inline (self-contained test
/// file, matching this crate's existing convention, e.g. `subprocess.rs`)
/// rather than importing that file's module, which would re-register its
/// `#[test]`s under this binary too.
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

const GOLDEN_SCRIPT: &str = "Require Import ZArith String List Lia.\nOpen Scope string.\nOpen Scope Z.\n\n\nGoal forall x : Z, (((x > 0) /\\ (x < 10)) -> (x > 0)).\nProof.\n  intros.\n  lia.\nQed.\n";

fn binary_on_path(name: &str) -> bool {
    Command::new(name)
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// The fixture's bad-twin: same hypothesis, FALSE consequent (`x < 0` when
/// the hypothesis already asserts `x > 0`). `lia` must refute it.
fn bad_twin_fixture() -> serde_json::Value {
    serde_json::json!({
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
    CoqCompiler::new()
        .compile_typed(&input, DIALECT)
        .expect("compile")
        .script()
}

/// Write `script` to `dir/name.v` and run `coqc` on it. Returns whether
/// `coqc` exited successfully.
fn coqc_accepts(dir: &Path, name: &str, script: &str) -> bool {
    let path = dir.join(format!("{name}.v"));
    std::fs::write(&path, script).expect("write .v fixture");
    Command::new("coqc")
        .arg(&path)
        .current_dir(dir)
        .output()
        .expect("spawn coqc")
        .status
        .success()
}

#[test]
fn coqc_discharges_the_golden_script_and_refutes_its_bad_twin() {
    if !binary_on_path("coqc") {
        eprintln!(
            "SKIP coqc_discharges_the_golden_script_and_refutes_its_bad_twin: \
             coqc not on PATH; install Coq to run this test."
        );
        return;
    }

    let dir = std::env::temp_dir().join(format!(
        "sugar-coq-golden-solve-{}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).expect("create scratch dir");

    let golden_script = compile_script(golden_fixture());
    assert_eq!(
        golden_script, GOLDEN_SCRIPT,
        "golden_solve must exercise the exact same script golden_compile pins"
    );
    assert!(
        coqc_accepts(&dir, "golden", &golden_script),
        "coqc must discharge the golden fixture (Qed on `(A /\\ B) -> A` over linear arithmetic)"
    );

    let bad_script = compile_script(bad_twin_fixture());
    assert!(
        !coqc_accepts(&dir, "bad_twin", &bad_script),
        "coqc must REJECT the bad-twin (false consequent contradicting the hypothesis); \
         a pass here means the golden test is vacuous"
    );

    let _ = std::fs::remove_dir_all(&dir);
}
