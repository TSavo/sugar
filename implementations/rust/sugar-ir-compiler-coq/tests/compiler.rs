// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Coq compiler tests for new IR constructs (lambda, let, choice).

use serde_json::{json, Value as Json};

use sugar_ir_compiler::{CompileError, CompiledFormula, CompilerInput, IrCompiler};
use sugar_ir_compiler_coq::{CoqCompiler, DIALECT};

fn compile_json(
    compiler: &CoqCompiler,
    ir: &Json,
    dialect: &str,
) -> Result<CompiledFormula, CompileError> {
    let input = CompilerInput::decode_json(ir.clone())?;
    compiler.compile_typed(&input, dialect)
}

#[test]
fn lambda_emits_coq_fun() {
    let ir = json!({
        "kind": "lambda",
        "paramName": "x",
        "paramSort": {"kind": "primitive", "name": "Int"},
        "body": {"kind": "const", "value": 42, "sort": {"kind": "primitive", "name": "Int"}}
    });
    let compiler = CoqCompiler::new();
    let result = compile_json(&compiler, &ir, DIALECT);
    assert!(result.is_ok(), "compile failed: {:?}", result.err());
    let compiled = result.unwrap();
    let coq_code = compiled.body;
    assert!(
        coq_code.contains("fun (x : Z)"),
        "Expected Coq lambda syntax"
    );
    assert!(coq_code.contains("42"), "Expected body in output");
}

#[test]
fn let_emits_coq_let_in() {
    let ir = json!({
        "kind": "let",
        "bindings": [
            {"name": "x", "boundTerm": {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}}
        ],
        "body": {"kind": "var", "name": "x"}
    });
    let compiler = CoqCompiler::new();
    let result = compile_json(&compiler, &ir, DIALECT);
    assert!(result.is_ok(), "compile failed: {:?}", result.err());
    let compiled = result.unwrap();
    let coq_code = compiled.body;
    assert!(coq_code.contains("let x"), "Expected Coq let syntax");
    assert!(coq_code.contains(" in"), "Expected 'in' keyword");
}

#[test]
fn choice_emits_coq_sig() {
    let ir = json!({
        "kind": "choice",
        "varName": "x",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {"kind": "atomic", "name": "true", "args": []}
    });
    let compiler = CoqCompiler::new();
    let result = compile_json(&compiler, &ir, DIALECT);
    assert!(result.is_ok(), "compile failed: {:?}", result.err());
    let compiled = result.unwrap();
    let coq_code = compiled.body;
    assert!(coq_code.contains("@sig"), "Expected Coq sig for choice");
    assert!(coq_code.contains("fun x"), "Expected fun binder");
}

#[test]
fn lambda_produces_valid_coq_syntax() {
    let ir = json!({
        "kind": "lambda",
        "paramName": "s",
        "paramSort": {"kind": "primitive", "name": "String"},
        "body": {"kind": "const", "value": "hello", "sort": {"kind": "primitive", "name": "String"}}
    });
    let compiler = CoqCompiler::new();
    let result = compile_json(&compiler, &ir, DIALECT);
    assert!(result.is_ok());
    let compiled = result.unwrap();
    let coq_code = compiled.body;
    // Should have Goal
    assert!(coq_code.contains("Goal"), "Expected Goal");
}

// ----------------------------------------------------------------------------
// FunctionSort + DependentSort (issue #331)
//
// Soundness rationale: Coq is the portfolio seat that covers higher-order and
// dependent types. FunctionSort maps to Coq's `->` (with parenthesization for
// right-associative correctness on nested function args); DependentSort maps
// to a Π-type `forall <var> : <index_sort>, <name> <var>` (instantiated form,
// matching the `Vec n` example in the issue body).
//
// "Round-trip" interpretation: the Coq compiler is emit-only: there is no
// Coq parser. So round-trip here means (a) IR JSON serde round-trips, and
// (b) emission is deterministic byte-for-byte across calls. Surface-shape
// assertions cover the actual translation.
// ----------------------------------------------------------------------------

#[test]
fn function_sort_in_forall_emits_coq_arrow() {
    let ir = json!({
        "kind": "forall",
        "name": "f",
        "sort": {
            "kind": "function",
            "args": [{"kind": "primitive", "name": "Int"}],
            "return": {"kind": "primitive", "name": "Bool"}
        },
        "body": {"kind": "atomic", "name": "true", "args": []}
    });
    let compiler = CoqCompiler::new();
    let result = compile_json(&compiler, &ir, DIALECT);
    assert!(result.is_ok(), "compile failed: {:?}", result.err());
    let coq_code = result.unwrap().body;
    assert!(
        coq_code.contains("forall f : Z -> bool"),
        "Expected Coq forall over function type, got:\n{}",
        coq_code
    );
}

#[test]
fn function_sort_multi_arg_curries_left_to_right() {
    // (Int, Int) -> Bool  =>  Z -> Z -> bool   (right-associative, equivalent shape)
    let ir = json!({
        "kind": "forall",
        "name": "g",
        "sort": {
            "kind": "function",
            "args": [
                {"kind": "primitive", "name": "Int"},
                {"kind": "primitive", "name": "Int"}
            ],
            "return": {"kind": "primitive", "name": "Bool"}
        },
        "body": {"kind": "atomic", "name": "true", "args": []}
    });
    let compiler = CoqCompiler::new();
    let coq_code = compile_json(&compiler, &ir, DIALECT).unwrap().body;
    assert!(
        coq_code.contains("forall g : Z -> Z -> bool"),
        "Expected curried multi-arg arrow, got:\n{}",
        coq_code
    );
}

#[test]
fn function_sort_higher_order_arg_is_parenthesized() {
    // `(Int -> Int) -> Bool` differs from `Int -> Int -> Bool` in Coq.
    // The arg position is itself a Function, so it MUST be parenthesized.
    let ir = json!({
        "kind": "forall",
        "name": "hof",
        "sort": {
            "kind": "function",
            "args": [
                {
                    "kind": "function",
                    "args": [{"kind": "primitive", "name": "Int"}],
                    "return": {"kind": "primitive", "name": "Int"}
                }
            ],
            "return": {"kind": "primitive", "name": "Bool"}
        },
        "body": {"kind": "atomic", "name": "true", "args": []}
    });
    let compiler = CoqCompiler::new();
    let coq_code = compile_json(&compiler, &ir, DIALECT).unwrap().body;
    assert!(
        coq_code.contains("forall hof : (Z -> Z) -> bool"),
        "Higher-order arg must be parenthesized for soundness, got:\n{}",
        coq_code
    );
    // Negative check: the unparenthesized form would be wrong.
    assert!(
        !coq_code.contains("forall hof : Z -> Z -> bool"),
        "Must NOT collapse parens on a function-typed arg"
    );
}

#[test]
fn lambda_over_function_sort_emits_coq_fun() {
    let ir = json!({
        "kind": "lambda",
        "paramName": "f",
        "paramSort": {
            "kind": "function",
            "args": [{"kind": "primitive", "name": "Int"}],
            "return": {"kind": "primitive", "name": "Int"}
        },
        "body": {"kind": "var", "name": "f"}
    });
    let compiler = CoqCompiler::new();
    let coq_code = compile_json(&compiler, &ir, DIALECT).unwrap().body;
    assert!(
        coq_code.contains("fun (f : Z -> Z)"),
        "Expected Coq fun over function sort, got:\n{}",
        coq_code
    );
}

#[test]
fn dependent_sort_emits_coq_pi_type() {
    // DependentSort `Vec` indexed by `n : Int`  =>  forall n : Z, Vec n
    let ir = json!({
        "kind": "forall",
        "name": "v",
        "sort": {
            "kind": "dependent",
            "name": "Vec",
            "indexVar": "n",
            "indexSort": {"kind": "primitive", "name": "Int"}
        },
        "body": {"kind": "atomic", "name": "true", "args": []}
    });
    let compiler = CoqCompiler::new();
    let coq_code = compile_json(&compiler, &ir, DIALECT).unwrap().body;
    assert!(
        coq_code.contains("forall n : Z, Vec n"),
        "Expected Coq Π-type with instantiated index, got:\n{}",
        coq_code
    );
}

#[test]
fn dependent_sort_in_lambda_param_position() {
    let ir = json!({
        "kind": "lambda",
        "paramName": "v",
        "paramSort": {
            "kind": "dependent",
            "name": "Vec",
            "indexVar": "n",
            "indexSort": {"kind": "primitive", "name": "Int"}
        },
        "body": {"kind": "var", "name": "v"}
    });
    let compiler = CoqCompiler::new();
    let coq_code = compile_json(&compiler, &ir, DIALECT).unwrap().body;
    assert!(
        coq_code.contains("fun (v : forall n : Z, Vec n)"),
        "Expected lambda binder over Π-type, got:\n{}",
        coq_code
    );
}

#[test]
fn dependent_sort_in_function_arg_position_is_parenthesized() {
    // Coq's `forall` extends maximally to the right, so an unparenthesized
    // DependentSort in a FunctionSort argument silently re-scopes the binder:
    //   `forall n : Z, Vec n -> bool`     parses as   `forall n : Z, (Vec n -> bool)`
    //   `(forall n : Z, Vec n) -> bool`   is the intended type
    // The emitter must wrap Sort::Dependent in parens whenever it sits in
    // function-argument position. Three reviewers (chatgpt-codex / Copilot /
    // CodeRabbit) flagged this on PR #364; positive + negative assertions.
    let ir = json!({
        "kind": "forall",
        "name": "f",
        "sort": {
            "kind": "function",
            "args": [
                {"kind": "dependent", "name": "Vec", "indexVar": "n",
                 "indexSort": {"kind": "primitive", "name": "Int"}}
            ],
            "return": {"kind": "primitive", "name": "Bool"}
        },
        "body": {"kind": "atomic", "name": "true", "args": []}
    });
    let compiler = CoqCompiler::new();
    let coq_code = compile_json(&compiler, &ir, DIALECT).unwrap().body;
    assert!(
        coq_code.contains("(forall n : Z, Vec n) -> bool"),
        "Expected parenthesized Π-type in arg position, got:\n{}",
        coq_code
    );
    assert!(
        !coq_code.contains("forall n : Z, Vec n -> bool"),
        "Unparenthesized Π-type leaks binder into function arrow:\n{}",
        coq_code
    );
}

#[test]
fn function_sort_serde_roundtrip() {
    // IR JSON -> Sort -> IR JSON: byte-identical via canonical serde.
    let original = json!({
        "kind": "function",
        "args": [
            {"kind": "primitive", "name": "Int"},
            {
                "kind": "function",
                "args": [{"kind": "primitive", "name": "Bool"}],
                "return": {"kind": "primitive", "name": "Int"}
            }
        ],
        "return": {"kind": "primitive", "name": "Bool"}
    });
    let parsed: sugar_ir_types::Sort =
        serde_json::from_value(original.clone()).expect("FunctionSort deserialization");
    let reemitted = serde_json::to_value(&parsed).expect("FunctionSort serialization");
    assert_eq!(
        original, reemitted,
        "FunctionSort IR JSON did not round-trip"
    );
}

#[test]
fn dependent_sort_serde_roundtrip() {
    let original = json!({
        "kind": "dependent",
        "name": "Vec",
        "indexVar": "n",
        "indexSort": {"kind": "primitive", "name": "Int"}
    });
    let parsed: sugar_ir_types::Sort =
        serde_json::from_value(original.clone()).expect("DependentSort deserialization");
    let reemitted = serde_json::to_value(&parsed).expect("DependentSort serialization");
    assert_eq!(
        original, reemitted,
        "DependentSort IR JSON did not round-trip"
    );
}

#[test]
fn coq_emission_is_deterministic_for_new_sorts() {
    // Two compile calls on the same IR must produce byte-identical Coq output;
    // any nondeterminism (HashMap iteration etc.) would break the conformance
    // gate that pins compiler output by hash.
    let ir = json!({
        "kind": "forall",
        "name": "f",
        "sort": {
            "kind": "function",
            "args": [
                {
                    "kind": "function",
                    "args": [{"kind": "primitive", "name": "Int"}],
                    "return": {"kind": "primitive", "name": "Int"}
                },
                {"kind": "dependent", "name": "Vec", "indexVar": "k",
                 "indexSort": {"kind": "primitive", "name": "Int"}}
            ],
            "return": {"kind": "primitive", "name": "Bool"}
        },
        "body": {"kind": "atomic", "name": "true", "args": []}
    });
    let compiler = CoqCompiler::new();
    let a = compile_json(&compiler, &ir, DIALECT).unwrap().body;
    let b = compile_json(&compiler, &ir, DIALECT).unwrap().body;
    assert_eq!(a, b, "Coq emission must be byte-deterministic");
}

#[test]
fn let_with_multiple_bindings() {
    let ir = json!({
        "kind": "let",
        "bindings": [
            {"name": "x", "boundTerm": {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}},
            {"name": "y", "boundTerm": {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}}
        ],
        "body": {"kind": "var", "name": "y"}
    });
    let compiler = CoqCompiler::new();
    let result = compile_json(&compiler, &ir, DIALECT);
    assert!(result.is_ok(), "compile failed: {:?}", result.err());
    let compiled = result.unwrap();
    let coq_code = compiled.body;
    // Should have two let bindings
    let let_count = coq_code.matches("let").count();
    assert!(
        let_count >= 2,
        "Expected at least 2 let occurrences, got {}",
        let_count
    );
}

#[test]
fn unknown_atom_refuses_loudly() {
    let ir = json!({
        "kind": "atomic",
        "name": "totally.unknown.op",
        "args": [{"kind": "var", "name": "x"}]
    });
    let compiler = CoqCompiler::new();

    match compile_json(&compiler, &ir, DIALECT) {
        Ok(compiled) => panic!(
            "unknown atom must refuse instead of weakening; before-output was:\n{}{}",
            compiled.preamble, compiled.body
        ),
        Err(err) => {
            let msg = err.to_string();
            assert!(msg.contains("totally.unknown.op"), "{msg}");
            assert!(msg.contains("no Coq encoding registered"), "{msg}");
            assert!(msg.contains("COQ_UNINTERPRETED_ALLOWLIST"), "{msg}");
        }
    }
}

#[test]
fn allowlisted_atom_emits_uninterpreted() {
    let ir = json!({
        "kind": "atomic",
        "name": "roundTrips",
        "args": [{"kind": "var", "name": "s"}]
    });
    let compiler = CoqCompiler::new();

    let compiled =
        compile_json(&compiler, &ir, DIALECT).expect("roundTrips is deliberately opaque in Coq");

    assert!(
        compiled.body.contains("Parameter s : Z."),
        "{}",
        compiled.body
    );
    assert!(
        compiled.body.contains("Goal roundTrips s."),
        "{}",
        compiled.body
    );
}

#[test]
fn unmapped_binop_refuses() {
    let ir = json!({
        "kind": "ctor",
        "name": "\u{2260}",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let compiler = CoqCompiler::new();

    match compile_json(&compiler, &ir, DIALECT) {
        Ok(compiled) => panic!(
            "unmapped Coq binop must refuse instead of weakening; before-output was:\n{}{}",
            compiled.preamble, compiled.body
        ),
        Err(err) => {
            let msg = err.to_string();
            assert!(msg.contains("\u{2260}"), "{msg}");
            assert!(msg.contains("no Coq encoding registered"), "{msg}");
        }
    }
}
