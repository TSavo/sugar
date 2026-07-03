// SPDX-License-Identifier: Apache-2.0

use std::path::PathBuf;

use serde_json::{json, Value as Json};
use sugar_ir_compiler::{subprocess::JsonRpcCompiler, CompilerInput, IrCompiler};
use sugar_ir_compiler_maude::{MaudeCompiler, DIALECT};

fn binary_path() -> Option<PathBuf> {
    let p = option_env!("CARGO_BIN_EXE_sugar-ir-maude").map(PathBuf::from)?;
    p.exists().then_some(p)
}

fn nat_obligation() -> Json {
    json!({
        "kind": "atomic",
        "name": "equational_theory",
        "theory": {
            "name": "sugar-nat",
            "sorts": ["Nat"],
            "operators": [
                {"name": "zero", "arity": [], "result": "Nat"},
                {"name": "s", "arity": ["Nat"], "result": "Nat"},
                {"name": "plus", "arity": ["Nat", "Nat"], "result": "Nat"}
            ],
            "variables": [
                {"name": "N", "sort": "Nat"},
                {"name": "M", "sort": "Nat"}
            ],
            "equations": [
                {
                    "label": "plus-zero-left",
                    "lhs": {"kind": "ctor", "name": "plus", "args": [
                        {"kind": "ctor", "name": "zero", "args": []},
                        {"kind": "var", "name": "N"}
                    ]},
                    "rhs": {"kind": "var", "name": "N"}
                },
                {
                    "label": "plus-s-left",
                    "lhs": {"kind": "ctor", "name": "plus", "args": [
                        {"kind": "ctor", "name": "s", "args": [
                            {"kind": "var", "name": "N"}
                        ]},
                        {"kind": "var", "name": "M"}
                    ]},
                    "rhs": {"kind": "ctor", "name": "s", "args": [
                        {"kind": "ctor", "name": "plus", "args": [
                            {"kind": "var", "name": "N"},
                            {"kind": "var", "name": "M"}
                        ]}
                    ]}
                }
            ]
        },
        "obligation": {
            "lhs": {"kind": "ctor", "name": "plus", "args": [
                {"kind": "ctor", "name": "s", "args": [
                    {"kind": "ctor", "name": "zero", "args": []}
                ]},
                {"kind": "ctor", "name": "s", "args": [
                    {"kind": "ctor", "name": "zero", "args": []}
                ]}
            ]},
            "rhs": {"kind": "ctor", "name": "s", "args": [
                {"kind": "ctor", "name": "s", "args": [
                    {"kind": "ctor", "name": "zero", "args": []}
                ]}
            ]}
        }
    })
}

#[test]
fn subprocess_compile_matches_in_process_byte_for_byte() {
    let Some(bin) = binary_path() else {
        eprintln!("skip: sugar-ir-maude binary not built yet");
        return;
    };
    let ir = nat_obligation();
    let input = CompilerInput::decode_json(ir).expect("fixture decodes");
    let via_subprocess = JsonRpcCompiler::spawn(&bin)
        .expect("spawn")
        .compile_typed(&input, DIALECT)
        .expect("compile");
    let via_in_process = MaudeCompiler::new()
        .compile_typed(&input, DIALECT)
        .expect("compile");
    assert_eq!(via_subprocess, via_in_process);
    assert!(via_subprocess.metadata.get("maude").is_some());
}
