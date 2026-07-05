// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Regression guard for the honesty-layer SMT-encoding bug.
//
// The reflexive-discharge honesty layer (#1716) added a pass that declares
// every `Term::Ctor` head it meets in TERM position as an UNINTERPRETED
// function (`Ok`, `Err`, `method:foo`, ...). The maven Java lifter lowers a
// binary arithmetic expression like `x * 2` to `ctor("*", [x, 2])`, so the
// pass wrongly emitted `(declare-fun * (Int Int) Int)`. Declaring an SMT-LIB
// theory builtin as an uninterpreted function shadows the theory: z3 then
// treats `*` as a free symbol, so the linear-arithmetic obligation
// `twice(3) == 6` (`(= (* 3 2) 6)`) becomes satisfiable (a counterexample is
// found) and the previously-discharged obligation regresses to `unsatisfied`.
//
// The interpreted term-operator set is exactly `+ - *` -- the same set the
// verifier's solver dispatcher (sugar-verifier/src/solvers/dispatch.rs)
// classifies as linear-arithmetic. Integer `/` and `%` deliberately stay
// uninterpreted (SMT Int division/modulo semantics differ from source
// truncation; see `fix(go): leave integer division/modulo uninterpreted`).

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

/// `(= (* 3 2) 6)` -- the exact shape of the regressed Java `twice` obligation.
fn twice_obligation() -> serde_json::Value {
    json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "ctor", "name": "*", "args": [
                {"kind": "const", "value": 3, "sort": {"kind": "primitive", "name": "Int"}},
                {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "const", "value": 6, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    })
}

#[test]
fn multiply_stays_interpreted_not_declared_uninterpreted() {
    let s = emit(&twice_obligation()).expect("emit");
    // The bug: `*` was declared as an uninterpreted function, shadowing the
    // SMT theory operator. It must NOT appear in a declare-fun.
    assert!(
        !s.contains("(declare-fun *"),
        "`*` is an SMT theory builtin and must stay interpreted; \
         it was wrongly declared uninterpreted:\n{s}"
    );
    // It must still be emitted as a builtin application.
    assert!(
        s.contains("(* 3 2)"),
        "multiply must render as the builtin `(* 3 2)`:\n{s}"
    );
}

/// Discrimination: a genuine non-builtin ctor (`Ok`) IS declared uninterpreted,
/// so the fix narrows the declaration set rather than disabling the pass.
#[test]
fn genuine_ctor_is_still_declared_uninterpreted() {
    let f = json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "ctor", "name": "Ok", "args": [
                {"kind": "const", "value": 6, "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "ctor", "name": "Ok", "args": [
                {"kind": "const", "value": 6, "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(
        s.contains("(declare-fun Ok"),
        "a genuine non-builtin ctor must still be declared uninterpreted:\n{s}"
    );
}

/// Addition and subtraction share the arithmetic builtin set with multiply.
#[test]
fn add_and_sub_stay_interpreted() {
    for op in ["+", "-"] {
        let f = json!({
            "kind": "atomic", "name": "=",
            "args": [
                {"kind": "ctor", "name": op, "args": [
                    {"kind": "var", "name": "a"},
                    {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}
                ]},
                {"kind": "var", "name": "b"}
            ]
        });
        let s = emit(&f).expect("emit");
        assert!(
            !s.contains(&format!("(declare-fun {op}")),
            "`{op}` is an SMT theory builtin and must stay interpreted:\n{s}"
        );
    }
}

/// Structural guard: integer division and modulo deliberately stay
/// uninterpreted (cardinal-sin guard -- SMT Int `/`/`%` semantics differ from
/// source truncation), so over-interpreting must NOT widen to them.
#[test]
fn division_and_modulo_stay_uninterpreted() {
    for op in ["/", "%"] {
        let f = json!({
            "kind": "atomic", "name": "=",
            "args": [
                {"kind": "ctor", "name": op, "args": [
                    {"kind": "var", "name": "a"},
                    {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}
                ]},
                {"kind": "var", "name": "b"}
            ]
        });
        let s = emit(&f).expect("emit");
        assert!(
            s.contains(&format!("(declare-fun {op}")),
            "`{op}` must stay uninterpreted (Int div/mod cardinal-sin guard):\n{s}"
        );
    }
}
