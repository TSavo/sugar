// SPDX-License-Identifier: Apache-2.0

use serde_json::{json, Value as Json};
use sugar_ir_compiler::{CompileError, CompilerInput, IrCompiler};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT};

fn const_ir(value: Json, sort_name: &str) -> Json {
    json!({
        "kind": "const",
        "value": value,
        "sort": {"kind": "primitive", "name": sort_name}
    })
}

fn compile_const(value: Json, sort_name: &str) -> Result<String, CompileError> {
    let compiler = LeanCompiler::new();
    let input = CompilerInput::decode_json(const_ir(value, sort_name))?;
    compiler
        .compile_typed(&input, DIALECT)
        .map(|compiled| compiled.script())
}

#[test]
fn unknown_primitive_const_refuses() {
    let err = compile_const(json!(-7), "BitVec32")
        .expect_err("unknown primitive literal sort must refuse instead of defaulting to Int");
    let message = err.to_string();
    assert!(
        message.contains("BitVec32"),
        "error must name the unsupported sort:\n{message}"
    );
    assert!(
        message.contains("-7"),
        "error must name the const it was annotating:\n{message}"
    );
}

#[test]
fn real_bool_string_int_consts_annotate() {
    let cases = [
        ("Int", json!(-7), "(-7 : Int)"),
        ("Real", json!("1.25"), "(1.25 : Real)"),
        ("Bool", json!(true), "true"),
        ("String", json!("hello"), "\"hello\""),
    ];

    for (sort_name, value, expected) in cases {
        let source = compile_const(value, sort_name).expect("compile known primitive const");
        assert!(
            source.contains(expected),
            "{sort_name} const should emit `{expected}`:\n{source}"
        );
    }
}
