// SPDX-License-Identifier: Apache-2.0
//
// The Python decimal-tolerance lift emits a real-arithmetic two-sided bound
// `|a-b| < T` as `(and (> (- a b) -T) (< (- a b) T))`, where T is a `Real` const
// carried as a canonical decimal string (e.g. "0.00000015"). For the smt-lib
// solver to give a real verdict instead of a sort/parse error, the compiler must:
//   1. declare the operands `a`, `b` as `Real` (they meet a Real bound),
//   2. emit T verbatim as a real literal (negative as the unary-minus `(- X)`,
//      since SMT-LIB has no negative real *literal*),
//   3. keep `-` interpreted, not declared as an uninterpreted function.
//
// This is the smt-lib rung of the four-compiler fan-out for the Real sort. It is
// the first formula in the repo to carry a `Real` const: before this, every
// literal rolled into the Int universe (see literal_encoding.rs).

use serde_json::json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT};

fn emit(ir: &serde_json::Value) -> Result<String, String> {
    let input = CompilerInput::decode_json(ir.clone()).map_err(|error| error.to_string())?;
    SmtLibCompiler::new()
        .compile_typed(&input, DIALECT)
        .map(|compiled| compiled.script())
        .map_err(|error| error.to_string())
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
fn operands_meeting_a_real_bound_are_declared_real() {
    let s = emit(&tolerance_bound()).expect("emit");
    assert!(
        s.contains("(declare-const a Real)"),
        "`a` must declare as Real:\n{s}"
    );
    assert!(
        s.contains("(declare-const b Real)"),
        "`b` must declare as Real:\n{s}"
    );
    // and NOT as Int -- the operand sort follows the bound it meets.
    assert!(
        !s.contains("(declare-const a Int)"),
        "`a` must not be Int:\n{s}"
    );
}

#[test]
fn real_literal_emitted_verbatim_with_negative_as_unary_minus() {
    let s = emit(&tolerance_bound()).expect("emit");
    assert!(
        s.contains("0.00000015"),
        "the real literal must appear verbatim:\n{s}"
    );
    assert!(
        s.contains("(- 0.00000015)"),
        "a negative real must render as `(- X)`:\n{s}"
    );
}

#[test]
fn minus_stays_interpreted_over_reals() {
    let s = emit(&tolerance_bound()).expect("emit");
    assert!(
        !s.contains("(declare-fun -"),
        "`-` is a theory builtin, never declared:\n{s}"
    );
    assert!(
        s.contains("(- a b)"),
        "the difference must render as the builtin `(- a b)`:\n{s}"
    );
}

// Discrimination: a Real-free formula collects exactly as before -- its vars stay
// Int. Guards against the real-context inference leaking onto ordinary contracts.
#[test]
fn real_free_formula_keeps_int_operands() {
    let f = json!({
        "kind": "atomic", "name": "=",
        "args": [{"kind": "var", "name": "x"},
                 {"kind": "const", "value": 5, "sort": {"kind": "primitive", "name": "Int"}}]
    });
    let s = emit(&f).expect("emit");
    assert!(
        s.contains("(declare-const x Int)"),
        "Real-free var must stay Int:\n{s}"
    );
}
