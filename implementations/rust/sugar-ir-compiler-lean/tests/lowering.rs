// SPDX-License-Identifier: Apache-2.0

use serde_json::json;
use sugar_ir_compiler::{subprocess::JsonRpcCompiler, IrCompiler};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT};

fn reflexivity_ir() -> serde_json::Value {
    json!({
        "kind": "forall",
        "name": "x",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "x"},
                {"kind": "var", "name": "x"}
            ]
        }
    })
}

#[test]
fn lowers_reflexivity_fixture_byte_for_byte() {
    let compiler = LeanCompiler::new();
    let out = compiler
        .compile(&reflexivity_ir(), DIALECT)
        .expect("compile");
    let source = format!("{}{}", out.preamble, out.body);
    assert_eq!(
        source,
        include_str!("fixtures/reflexivity.lean"),
        "Lean lowering drifted from the checked fixture"
    );
}

#[test]
fn declares_dependent_and_categorical_coverage() {
    let compiler = LeanCompiler::new();
    let caps = compiler.capabilities();
    assert!(caps.supported_sorts.iter().any(|s| s == "Dependent"));
    assert!(caps
        .supported_sorts
        .iter()
        .any(|s| s == "CategoricalStructure"));
    assert!(caps.supported_predicates.iter().any(|p| p == "mathlib"));
}

#[test]
fn false_obligation_gets_checked_by_automation_without_sorry() {
    let compiler = LeanCompiler::new();
    let ir = json!({"kind": "atomic", "name": "false", "args": []});
    let out = compiler.compile(&ir, DIALECT).expect("compile");
    let source = format!("{}{}", out.preamble, out.body);
    assert!(source.contains("theorem sugar_obligation : False := by"));
    assert!(!source.contains("sorry"));
}

#[test]
fn binary_serves_lean_source_over_json_rpc() {
    let Some(bin) = option_env!("CARGO_BIN_EXE_sugar-ir-lean") else {
        eprintln!("skip: sugar-ir-lean binary path not supplied by cargo");
        return;
    };
    let compiler = JsonRpcCompiler::spawn(bin).expect("spawn sugar-ir-lean");
    let compiled = compiler
        .compile(&reflexivity_ir(), DIALECT)
        .expect("compile");
    assert_eq!(compiled.script(), include_str!("fixtures/reflexivity.lean"));
}
