// SPDX-License-Identifier: Apache-2.0
//
// End-to-end subprocess test. Spawns the standalone
// `sugar-ir-smt-lib` binary, performs handshake and one compile via
// the JSON-RPC protocol, asserts the result equals the in-process
// trait output. This is acceptance criterion #2 + #3 in one shot.

use std::path::PathBuf;

use serde_json::json;

use sugar_ir_compiler::{
    subprocess::JsonRpcCompiler, CompileError, CompiledFormula, CompilerInput, IrCompiler,
};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT};

fn compile_to_parts(ir: &serde_json::Value) -> Result<CompiledFormula, CompileError> {
    let input = CompilerInput::decode_json(ir.clone()).expect("fixture decodes");
    SmtLibCompiler::new().compile_typed(&input, DIALECT)
}

fn binary_path() -> Option<PathBuf> {
    // Cargo sets CARGO_BIN_EXE_<name> for binaries in this package.
    let p = option_env!("CARGO_BIN_EXE_sugar-ir-smt-lib").map(PathBuf::from)?;
    if p.exists() {
        Some(p)
    } else {
        None
    }
}

#[test]
fn subprocess_handshake_returns_smt_lib_dialect() {
    let Some(bin) = binary_path() else {
        eprintln!("skip: sugar-ir-smt-lib binary not built yet");
        return;
    };
    let c = JsonRpcCompiler::spawn(&bin).expect("spawn");
    let caps = c.capabilities();
    assert_eq!(caps.protocol_version, "sugar-ir-compiler/1");
    assert!(caps.dialects.iter().any(|d| d == DIALECT));
    assert!(caps.supported_sorts.iter().any(|s| s == "Int"));
    assert!(caps.supported_predicates.iter().any(|p| p == "forall"));
}

#[test]
fn subprocess_compile_matches_in_process_byte_for_byte() {
    let Some(bin) = binary_path() else {
        eprintln!("skip: sugar-ir-smt-lib binary not built yet");
        return;
    };
    let c = JsonRpcCompiler::spawn(&bin).expect("spawn");
    let ir = json!({
        "kind": "forall", "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let input = CompilerInput::decode_json(ir.clone()).expect("fixture decodes");
    let via_subprocess = c.compile_typed(&input, DIALECT).expect("compile");
    let via_in_process = compile_to_parts(&ir).expect("compile_to_parts");
    assert_eq!(via_subprocess, via_in_process);
}
