// SPDX-License-Identifier: MIT OR Apache-2.0
//
// solver 3/4 of the Real-tolerance fan-out: Coq.
//
// Coq mapped `Real -> Z` and proved with `lia` (integer arithmetic). The decimal-
// tolerance bound `|a-b| < T` is REAL, so a Real-bearing obligation must lower
// over `R` with `lra`: operands declared `R`, `-` infix real subtraction, the
// bound an exact RATIONAL `(num / den)%R` (Coq's R has no decimal literal), under
// `Open Scope R` with `Require Import Reals ... Lra`. A Real-free obligation is
// unchanged (Z + lia). Verified end-to-end with coqc on a valid instance
// (`(c - c) < eps`, discharged by lra); these string assertions are the portable
// guard.

use serde_json::json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_coq::CoqCompiler;

fn compile(f: &serde_json::Value) -> String {
    let input = CompilerInput::decode_json(f.clone()).expect("fixture decodes");
    let r = CoqCompiler.compile_typed(&input, "coq").expect("compile");
    format!("{}{}", r.preamble, r.body)
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
fn real_obligation_lowers_over_r_with_lra() {
    let s = compile(&tolerance_bound());
    assert!(
        s.contains("Parameter a : R."),
        "`a` must be an R parameter:\n{s}"
    );
    assert!(
        s.contains("Parameter b : R."),
        "`b` must be an R parameter:\n{s}"
    );
    assert!(s.contains("Open Scope R."), "must open the R scope:\n{s}");
    assert!(
        s.contains("Require Import Reals") && s.contains("Lra"),
        "needs Reals + Lra:\n{s}"
    );
    assert!(s.contains("lra."), "must discharge with lra, not lia:\n{s}");
    assert!(
        !s.contains("lia."),
        "lia is the integer tactic; must not appear:\n{s}"
    );
}

#[test]
fn difference_is_infix_and_bound_is_an_exact_rational() {
    let s = compile(&tolerance_bound());
    assert!(
        s.contains("(a - b)"),
        "difference must be infix real subtraction:\n{s}"
    );
    // 1.5 * 10^-7 = 15 / 10^8, exact, content-stable, no decimal literal.
    assert!(
        s.contains("(15 / 100000000)%R"),
        "positive bound as exact rational:\n{s}"
    );
    assert!(
        s.contains("(- (15 / 100000000))%R"),
        "negative bound negates the rational:\n{s}"
    );
    assert!(
        !s.contains("\"0.00000015\""),
        "the bound must not be a Coq string:\n{s}"
    );
}

// Discrimination: a Real-free obligation stays on the integer path (Z + lia).
#[test]
fn real_free_obligation_stays_on_z_and_lia() {
    let f = json!({
        "kind": "atomic", "name": "=",
        "args": [{"kind": "var", "name": "x"},
                 {"kind": "const", "value": 5, "sort": {"kind": "primitive", "name": "Int"}}]
    });
    let s = compile(&f);
    assert!(
        s.contains("Parameter x : Z."),
        "Real-free var stays Z:\n{s}"
    );
    assert!(
        s.contains("lia.") && s.contains("Open Scope Z."),
        "integer path unchanged:\n{s}"
    );
}
