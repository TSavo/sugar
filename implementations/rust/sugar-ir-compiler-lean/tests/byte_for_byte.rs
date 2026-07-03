// SPDX-License-Identifier: Apache-2.0

use serde_json::json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT};

#[test]
fn repeated_compiles_are_byte_identical() {
    let ir = json!({
        "kind": "forall",
        "name": "f",
        "sort": {
            "kind": "function",
            "args": [{"kind": "primitive", "name": "Int"}],
            "return": {"kind": "primitive", "name": "Int"}
        },
        "body": {
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "ctor", "name": "f", "args": [{"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}]},
                {"kind": "ctor", "name": "f", "args": [{"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}]}
            ]
        }
    });

    let compiler = LeanCompiler::new();
    let input = CompilerInput::decode_json(ir).expect("fixture decodes");
    let first = compiler
        .compile_typed(&input, DIALECT)
        .expect("first compile");
    let second = compiler
        .compile_typed(&input, DIALECT)
        .expect("second compile");
    assert_eq!(first, second);
    assert_eq!(
        format!("{}{}", first.preamble, first.body),
        format!("{}{}", second.preamble, second.body)
    );
}
