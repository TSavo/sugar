// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn crate_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock before epoch")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "sugar_frontend_boundary_s7_{label}_{}_{}",
        std::process::id(),
        now
    ))
}

#[test]
fn planted_json_ingress_backend_fails_to_compile_against_typed_trait() {
    let temp = unique_temp_dir("compile_fail");
    fs::create_dir_all(temp.join("src")).expect("create temp crate");
    fs::write(
        temp.join("Cargo.toml"),
        format!(
            r#"[package]
name = "s7-planted-json-ingress"
version = "0.0.0"
edition = "2021"

[dependencies]
sugar-ir-compiler = {{ path = "{}" }}
serde_json = "1"
"#,
            crate_root().display()
        ),
    )
    .expect("write Cargo.toml");
    fs::write(
        temp.join("src/lib.rs"),
        r#"
use serde_json::{json, Value as Json};
use sugar_ir_compiler::{
    Capabilities, CompileError, CompiledFormula, CompilerInput, IrCompiler, PROTOCOL_VERSION,
};

pub struct PlantedJsonIngressBackend;

impl PlantedJsonIngressBackend {
    fn oddly_named_obligation_decode(&self, ir: &Json) -> Result<CompiledFormula, CompileError> {
        let _decoded: sugar_ir_compiler::CompilerInput = CompilerInput::decode_json(ir.clone())?;
        Ok(CompiledFormula {
            preamble: String::new(),
            body: "(check-sat)\n".to_string(),
            free_vars: Vec::new(),
            opacity_manifest: Default::default(),
            metadata: Json::Null,
        })
    }
}

impl IrCompiler for PlantedJsonIngressBackend {
    fn compile_typed(
        &self,
        ir: &CompilerInput,
        dialect: &str,
    ) -> Result<CompiledFormula, CompileError> {
        let raw = ir.to_json_value()?;
        self.compile(&raw, dialect)
    }

    fn compile(&self, ir: &Json, _dialect: &str) -> Result<CompiledFormula, CompileError> {
        self.oddly_named_obligation_decode(ir)
    }

    fn capabilities(&self) -> Capabilities {
        Capabilities {
            name: "planted-json-ingress".to_string(),
            version: "0.0.0".to_string(),
            protocol_version: PROTOCOL_VERSION.to_string(),
            dialects: vec!["planted".to_string()],
            supported_sorts: vec![],
            supported_predicates: vec![],
        }
    }
}

#[allow(dead_code)]
fn exercise() -> Result<(), CompileError> {
    let input = CompilerInput::decode_json(json!({
        "kind": "atomic",
        "name": "=",
        "args": [{"kind": "var", "name": "x"}, {"kind": "var", "name": "x"}]
    }))?;
    PlantedJsonIngressBackend.compile_typed(&input, "planted")?;
    Ok(())
}
"#,
    )
    .expect("write planted lib");

    let mut command = Command::new(std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_string()));
    command
        .arg("check")
        .arg("--quiet")
        .current_dir(&temp)
        .env("CARGO_TARGET_DIR", temp.join("target"));
    let output = command.output().expect("run cargo check");
    let _ = fs::remove_dir_all(&temp);
    assert!(
        !output.status.success(),
        "planted backend with compile(&Json) ingress must fail to compile once the typed trait closes; stdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("not a member of trait `IrCompiler`")
            || stderr.contains("no method named `compile`"),
        "compile failure must be the structural typed-trait close, got:\n{stderr}"
    );
}
