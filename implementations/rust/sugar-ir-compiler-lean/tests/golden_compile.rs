// SPDX-License-Identifier: MIT OR Apache-2.0
//
// golden-coq-lean-targets: Lean compile-golden test.
//
// The SAME ProofIR fixture as the Coq golden-pair
// (`sugar-ir-compiler-coq/tests/golden_compile.rs`): atomic `>`/`<`, `and`,
// `implies`, and a `forall` sort declaration over `Int`. The fixture is
// CID-pinned (content-addressing is over the JSON, not the target, so this
// constant is byte-identical to the Coq crate's `FIXTURE_CID`), then the
// `LeanCompiler`'s emitted script is asserted to match a checked-in golden
// file EXACTLY, mirroring the existing `tests/fixtures/reflexivity.lean`
// convention in this crate (see `tests/lowering.rs`). No prover invocation
// here; see `golden_solve.rs` for the lake+mathlib-gated companion.

use serde_json::{json, Value as Json};
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT};

/// `forall x : Int, ((x > 0) and (x < 10)) -> (x > 0)`. See the Coq
/// golden-pair's `fixture()` doc comment for why this propositional shape
/// (`(A ∧ B) -> A` over concrete linear-arithmetic atoms) was chosen.
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

/// Pinned CID of the fixture's canonical JSON bytes (JCS + blake3-512).
/// Byte-identical to `sugar-ir-compiler-coq/tests/golden_compile.rs::FIXTURE_CID`
/// -- same fixture JSON, target-independent content address.
pub const FIXTURE_CID: &str = "blake3-512:31064f18f580d66af4fa5961a8f190dd0b0688f07d54136b1b4d9c75e5fac514d6bf7ed7a3cf85b981d0dd0bf030f63d1395ab82efa628fa2675a0e033cf9897";

#[test]
fn fixture_bytes_are_cid_pinned() {
    let cid = sugar_canonicalizer::jcs_cid_of_json(&fixture());
    assert_eq!(
        cid, FIXTURE_CID,
        "golden fixture JSON drifted; regenerate FIXTURE_CID only after confirming the change is intentional"
    );
}

#[test]
fn lean_emits_the_golden_script_exactly() {
    let input = CompilerInput::decode_json(fixture()).expect("fixture decodes");
    let compiled = LeanCompiler::new()
        .compile_typed(&input, DIALECT)
        .expect("compile");
    assert_eq!(
        compiled.script(),
        include_str!("fixtures/golden_and_implies.lean"),
        "Lean emission drifted from the checked-in golden fixture"
    );
    assert!(
        compiled.free_vars.is_empty(),
        "the forall binder must not leak x as a free var"
    );
}
