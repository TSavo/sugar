// SPDX-License-Identifier: Apache-2.0

use std::path::PathBuf;

use serde_json::json;
use sugar_ir_compiler::{subprocess::JsonRpcCompiler, IrCompiler};
use sugar_ir_compiler_coq::{CoqCompiler, DIALECT};

fn binary_path() -> Option<PathBuf> {
    let p = option_env!("CARGO_BIN_EXE_sugar-ir-coq").map(PathBuf::from)?;
    p.exists().then_some(p)
}

#[test]
fn subprocess_compile_matches_in_process_byte_for_byte() {
    let Some(bin) = binary_path() else {
        eprintln!("skip: sugar-ir-coq binary not built yet");
        return;
    };
    let ir = json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}},
            {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let via_subprocess = JsonRpcCompiler::spawn(&bin)
        .expect("spawn")
        .compile(&ir, DIALECT)
        .expect("compile");
    let via_in_process = CoqCompiler::new().compile(&ir, DIALECT).expect("compile");
    assert_eq!(via_subprocess, via_in_process);
}
