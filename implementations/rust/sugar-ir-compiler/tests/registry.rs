// SPDX-License-Identifier: MIT OR Apache-2.0

use std::sync::Arc;

use serde_json::{json, Value as Json};

use sugar_ir_compiler::{
    registry::Registry, Capabilities, CompileError, CompiledFormula, CompilerInput, FreeVar,
    IrCompiler, OpacityManifest, PROTOCOL_VERSION,
};

fn reflexive_input() -> CompilerInput {
    CompilerInput::decode_json(json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "var", "name": "v"},
            {"kind": "var", "name": "v"}
        ]
    }))
    .expect("registry test fixture decodes")
}

struct FakeCompiler {
    name: String,
    dialects: Vec<String>,
}

impl IrCompiler for FakeCompiler {
    fn compile_typed(
        &self,
        _ir: &CompilerInput,
        dialect: &str,
    ) -> Result<CompiledFormula, CompileError> {
        if !self.dialects.iter().any(|d| d == dialect) {
            return Err(CompileError::UnsupportedDialect(dialect.into()));
        }
        Ok(CompiledFormula {
            preamble: format!("; from {}\n", self.name),
            body: "(check-sat)\n".into(),
            free_vars: vec![FreeVar {
                name: "v".into(),
                sort: "Int".into(),
            }],
            opacity_manifest: OpacityManifest {
                protocol_version: "ir-compiler-protocol/2".into(),
                compiler: self.name.clone(),
                compiler_version: "0.0".into(),
                opacities: vec![],
            },
            metadata: Json::Null,
        })
    }
    fn capabilities(&self) -> Capabilities {
        Capabilities {
            name: self.name.clone(),
            version: "0.0".into(),
            protocol_version: PROTOCOL_VERSION.into(),
            dialects: self.dialects.clone(),
            supported_sorts: vec!["Int".into()],
            supported_predicates: vec!["=".into()],
        }
    }
}

#[test]
fn registry_dispatches_to_registered_dialect() {
    let mut r = Registry::new();
    r.register(Arc::new(FakeCompiler {
        name: "fake".into(),
        dialects: vec!["smt-lib-v2.6".into()],
    }));
    let input = reflexive_input();
    let out = r.compile(&input, "smt-lib-v2.6").unwrap();
    assert!(out.preamble.contains("; from fake"));
}

#[test]
fn registry_returns_unsupported_for_missing_dialect() {
    let r = Registry::new();
    let input = reflexive_input();
    let err = r.compile(&input, "tptp-fof").unwrap_err();
    assert!(matches!(err, CompileError::UnsupportedDialect(_)));
}

#[test]
fn registry_register_returns_count_of_dialects() {
    let mut r = Registry::new();
    let n = r.register(Arc::new(FakeCompiler {
        name: "multi".into(),
        dialects: vec!["a".into(), "b".into(), "c".into()],
    }));
    assert_eq!(n, 3);
    assert!(r.get("a").is_some());
    assert!(r.get("b").is_some());
    assert!(r.get("c").is_some());
}

#[test]
fn registry_lists_all_dialects() {
    let mut r = Registry::new();
    r.register(Arc::new(FakeCompiler {
        name: "x".into(),
        dialects: vec!["d1".into(), "d2".into()],
    }));
    let mut ds = r.dialects();
    ds.sort();
    assert_eq!(ds, vec!["d1".to_string(), "d2".to_string()]);
}
