// SPDX-License-Identifier: MIT OR Apache-2.0
//
// solver 2/4 of the Real-tolerance fan-out: Lean.
//
// The producer emits the decimal-tolerance bound `|a-b| < T` as
// `(and (> (- a b) -T) (< (- a b) T))` with T a `Real` const carried as a
// canonical decimal string. Before this rung, Lean rendered `-` as an
// uninterpreted function over `Int` operands and the Real const as a quoted
// string literal -- a malformed theorem. It must now produce a sort-correct
// `Real` theorem: operands `Real`, `-` infix, the bound an ascribed real literal.

use serde_json::json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT};

fn emit(ir: &serde_json::Value) -> Result<String, sugar_ir_compiler::CompileError> {
    let input = CompilerInput::decode_json(ir.clone())?;
    LeanCompiler::new()
        .compile_typed(&input, DIALECT)
        .map(|compiled| compiled.script())
}

fn tolerance_bound() -> serde_json::Value {
    let diff = json!({
        "kind": "ctor", "name": "-",
        "args": [{"kind": "var", "name": "a"}, {"kind": "var", "name": "b"}]
    });
    json!({
        "kind": "and",
        "operands": [
            {"kind": "atomic", "name": ">", "args": [
                diff,
                {"kind": "const", "value": "-0.00000015",
                 "sort": {"kind": "primitive", "name": "Real"}}
            ]},
            {"kind": "atomic", "name": "<", "args": [
                diff,
                {"kind": "const", "value": "0.00000015",
                 "sort": {"kind": "primitive", "name": "Real"}}
            ]}
        ]
    })
}

#[test]
fn operands_meeting_a_real_bound_are_real_binders() {
    let s = emit(&tolerance_bound()).expect("emit");
    assert!(s.contains("(a : Real)"), "`a` must be a Real binder:\n{s}");
    assert!(s.contains("(b : Real)"), "`b` must be a Real binder:\n{s}");
    // and NOT the old uninterpreted-function form over Int.
    assert!(
        !s.contains("Int -> Int -> Real"),
        "`-` must not be a function:\n{s}"
    );
}

#[test]
fn difference_is_infix_subtraction_not_a_function() {
    let s = emit(&tolerance_bound()).expect("emit");
    assert!(
        s.contains("(a - b)"),
        "difference must render infix `(a - b)`:\n{s}"
    );
}

#[test]
fn real_const_is_an_ascribed_real_literal_not_a_string() {
    let s = emit(&tolerance_bound()).expect("emit");
    assert!(
        s.contains("(0.00000015 : Real)"),
        "positive bound as real literal:\n{s}"
    );
    assert!(
        s.contains("(-0.00000015 : Real)"),
        "negative bound as real literal:\n{s}"
    );
    assert!(
        !s.contains("\"0.00000015\""),
        "the bound must not be a string literal:\n{s}"
    );
}
