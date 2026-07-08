// SPDX-License-Identifier: MIT OR Apache-2.0
//
// golden-coq-lean-targets: Coq compile-golden test.
//
// A small ProofIR fixture (atomic `>`/`<`, `and`, `implies`, and a `forall`
// sort declaration over `Int`) is CID-pinned so drift in the fixture bytes
// themselves is caught, then the CoqCompiler's emitted script is asserted to
// match a golden string EXACTLY, byte for byte. No prover invocation here;
// see `golden_solve.rs` for the coqc-gated companion that actually discharges
// this fixture (and refutes its negated bad-twin) with the real binary.
//
// The fixture is the propositional shape `(A ∧ B) -> A` instantiated with
// concrete linear-arithmetic atoms (`x > 0`, `x < 10`), universally
// quantified over `x : Int`. This is deliberately provable by structure
// alone (no arithmetic decision procedure is required to see it's true),
// which keeps the companion solve test robust across backends.

use serde_json::{json, Value as Json};
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_coq::{CoqCompiler, DIALECT};

/// `forall x : Int, ((x > 0) and (x < 10)) -> (x > 0)`.
///
/// Exercises: `atomic` (`>`, `<`), `and`, `implies`, and a `forall` sort
/// declaration in one fixture, per the golden-pair spec.
pub fn fixture() -> Json {
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

/// Pinned CID of the fixture's canonical JSON bytes (JCS + blake3-512), per
/// `sugar_canonicalizer::jcs_cid_of_json`. This is the SAME fixture JSON used
/// by the Lean golden-pair (`sugar-ir-compiler-lean/tests/golden_compile.rs`)
/// -- content-addressing is over the JSON, not the target -- so the two
/// pinned constants must be byte-identical. If this drifts, either the
/// fixture literal above changed or the canonicalizer's encoding changed;
/// both are load-bearing to notice.
pub const FIXTURE_CID: &str = "blake3-512:31064f18f580d66af4fa5961a8f190dd0b0688f07d54136b1b4d9c75e5fac514d6bf7ed7a3cf85b981d0dd0bf030f63d1395ab82efa628fa2675a0e033cf9897";

/// The exact Coq script `CoqCompiler` emits for `fixture()`. Any change to
/// the emitter's formula/sort lowering, free-var handling, or tactic choice
/// must show up here as a diff, not a silent pass.
pub const GOLDEN_SCRIPT: &str = "Require Import ZArith String List Lia.\nOpen Scope string.\nOpen Scope Z.\n\n\nGoal forall x : Z, (((x > 0) /\\ (x < 10)) -> (x > 0)).\nProof.\n  intros.\n  lia.\nQed.\n";

#[test]
fn fixture_bytes_are_cid_pinned() {
    let cid = sugar_canonicalizer::jcs_cid_of_json(&fixture());
    assert_eq!(
        cid, FIXTURE_CID,
        "golden fixture JSON drifted; regenerate FIXTURE_CID only after confirming the change is intentional"
    );
}

#[test]
fn coq_emits_the_golden_script_exactly() {
    let input = CompilerInput::decode_json(fixture()).expect("fixture decodes");
    let compiled = CoqCompiler::new()
        .compile_typed(&input, DIALECT)
        .expect("compile");
    assert_eq!(
        compiled.script(),
        GOLDEN_SCRIPT,
        "Coq emission drifted from the pinned golden script"
    );
    assert!(
        compiled.free_vars.is_empty(),
        "the forall binder must not leak x as a free var"
    );
}
