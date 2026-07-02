// SPDX-License-Identifier: Apache-2.0
//
// sugar-ir-compiler-coq: Coq compiler for IR contracts.
//
// Emits Coq .v files that can be verified with coqc.
// Supports kit-defined predicates via Definitions (unlike SMT-LIB!).
//
// ============================================================================
// CONNECTING TO REAL EMIT/PARSE IMPLEMENTATIONS
// ============================================================================
//
// The Coq compiler can bridge to the actual Rust emit/parse implementations via:
//
// 1. COQ EXTRACTION
//    - Write emit/parse in pure functional Rust
//    - Use `coqc -extract` to get OCaml
//    - Import OCaml as Coq definitions
//
// 2. HOTT/VERIFICATION APPROACH
//    - Prove emit/parse correctness as Coq theorems
//    - Use correctness proofs in verification
//
// 3. EXTERNAL SOLVER
//    - Call Rust from Coq via FFI (experimental)
//
// For now, we emit placeholder definitions that can be replaced with
// real semantics once the infrastructure is in place.

use serde_json::Value as Json;

use sugar_ir_compiler::{
    Capabilities, CompileError, CompiledFormula, FreeVar, IrCompiler, PROTOCOL_VERSION,
};

mod generated;

pub const DIALECT: &str = "coq";
pub const COMPILER_NAME: &str = "coq-reference";
pub const COMPILER_VERSION: &str = env!("CARGO_PKG_VERSION");

pub struct CoqCompiler;

fn is_term_kind(kind: &str) -> bool {
    matches!(kind, "var" | "const" | "ctor" | "lambda" | "let")
}

impl CoqCompiler {
    pub fn new() -> Self {
        Self
    }

    fn compile_inner(&self, ir: &Json) -> Result<(String, String, Vec<FreeVar>), CompileError> {
        let kind = ir.get("kind").and_then(|v| v.as_str()).unwrap_or("");
        if is_term_kind(kind) {
            let term: sugar_ir_types::Term = serde_json::from_value(ir.clone())
                .map_err(|e| CompileError::MalformedIr(format!("{e}")))?;
            let term_str = generated::emit_term(&term)?;
            let preamble =
                "Require Import ZArith String List.\nOpen Scope Z.\nOpen Scope string.\n\n"
                    .to_string();
            let body = format!("Goal {}.\nProof.\n  admit.\nQed.\n", term_str);
            Ok((preamble, body, vec![]))
        } else {
            let formula: sugar_ir_types::Formula = serde_json::from_value(ir.clone())
                .map_err(|e| CompileError::MalformedIr(format!("{e}")))?;
            generated::compile_formula(&formula)
        }
    }
}

impl Default for CoqCompiler {
    fn default() -> Self {
        Self::new()
    }
}

impl IrCompiler for CoqCompiler {
    fn compile(&self, ir: &Json, dialect: &str) -> Result<CompiledFormula, CompileError> {
        if dialect != DIALECT {
            return Err(CompileError::UnsupportedDialect(dialect.to_string()));
        }
        let (preamble, body, free_vars) = self.compile_inner(ir)?;
        Ok(CompiledFormula {
            preamble,
            body,
            free_vars,
            opacity_manifest: sugar_ir_compiler::OpacityManifest {
                protocol_version: "ir-compiler-protocol/2".to_string(),
                compiler: DIALECT.to_string(),
                compiler_version: COMPILER_VERSION.to_string(),
                opacities: vec![],
            },
            metadata: Json::Null,
        })
    }

    fn capabilities(&self) -> Capabilities {
        Capabilities {
            name: COMPILER_NAME.to_string(),
            version: COMPILER_VERSION.to_string(),
            protocol_version: PROTOCOL_VERSION.to_string(),
            dialects: vec![DIALECT.to_string()],
            supported_sorts: vec![
                "Int".to_string(),
                "Bool".to_string(),
                "Real".to_string(),
                "String".to_string(),
            ],
            supported_predicates: vec![
                "=".to_string(),
                "<".to_string(),
                "<=".to_string(),
                ">".to_string(),
                ">=".to_string(),
                "≠".to_string(),
                "and".to_string(),
                "or".to_string(),
                "not".to_string(),
                "implies".to_string(),
                "forall".to_string(),
                "exists".to_string(),
                // Kit-defined predicates ARE supported!
                "roundTrips".to_string(),
                "isErr".to_string(),
                "isMalformed".to_string(),
            ],
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn compiles_simple_formula() {
        let compiler = CoqCompiler::new();
        let ir = json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 42, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        });

        let result = compiler.compile(&ir, DIALECT).unwrap();
        assert!(result.body.contains("Goal"));
        assert!(result.body.contains("x = 42"));
    }

    #[test]
    fn defines_kit_predicates() {
        let compiler = CoqCompiler::new();
        let ir = json!({
            "kind": "atomic",
            "name": "roundTrips",
            "args": [{"kind": "var", "name": "s"}]
        });

        let result = compiler.compile(&ir, DIALECT).unwrap();
        // Generated compiler emits Parameter declarations in the body
        assert!(result.body.contains("Parameter s"));
        assert!(result.body.contains("roundTrips s"));
    }

    #[test]
    fn compiles_forall() {
        let compiler = CoqCompiler::new();
        let ir = json!({
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
        });

        let result = compiler.compile(&ir, DIALECT).unwrap();
        assert!(result.body.contains("forall x : Z"));
    }
}
