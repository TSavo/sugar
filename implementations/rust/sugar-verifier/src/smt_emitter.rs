// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Stage 5: smt_emitter. Render an obligation's IR to an SMT-LIB
// script.
//
// The implementation moved to crate `sugar-ir-compiler-smt-lib` so
// the same code serves both the in-process fast path (this re-export)
// and the standalone `sugar-ir-smt-lib` subprocess binary used by
// the IR compiler plugin protocol.
//
// Spec: protocol/specs/2026-04-30-ir-compiler-protocol.md.

use serde_json::Value as Json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT};

/// Render an obligation IR to an SMT-LIB script string. Equal to
/// `compile.preamble + compile.body` from the bundled SMT-LIB
/// compiler; the verifier's runner consumes the single-string form.
pub fn emit(ir_formula: &Json) -> Result<String, String> {
    let input =
        CompilerInput::decode_json(ir_formula.clone()).map_err(|error| error.to_string())?;
    SmtLibCompiler::new()
        .compile_typed(&input, DIALECT)
        .map(|compiled| compiled.script())
        .map_err(|error| error.to_string())
}
