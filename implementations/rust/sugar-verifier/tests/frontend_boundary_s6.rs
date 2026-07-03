use std::path::Path;

use serde_json::{json, Value as Json};
use sugar_ir_compiler::{
    BinaryProofIrFrontend, CompileError, CompiledFormula, CompiledFormulaFieldPath, CompilerInput,
    FrontendErrorKind, FrontendProvenancePolicy, IrCompiler,
};
use sugar_ir_compiler_maude::{MaudeCompiler, DIALECT as MAUDE_DIALECT};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT as SMT_DIALECT};

fn repo_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-verifier lives under implementations/rust/sugar-verifier")
}

fn int_sort() -> Json {
    json!({"kind": "primitive", "name": "Int"})
}

fn int_const(value: i64) -> Json {
    json!({"kind": "const", "value": value, "sort": int_sort()})
}

fn var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
}

fn formula_fixture() -> Json {
    json!({
        "kind": "atomic",
        "name": "=",
        "args": [var("x"), int_const(7)]
    })
}

fn equational_theory_fixture() -> Json {
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
                        {"kind": "ctor", "name": "s", "args": [{"kind": "var", "name": "N"}]},
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
                {"kind": "ctor", "name": "s", "args": [{"kind": "ctor", "name": "zero", "args": []}]},
                {"kind": "ctor", "name": "s", "args": [{"kind": "ctor", "name": "zero", "args": []}]}
            ]},
            "rhs": {"kind": "ctor", "name": "s", "args": [
                {"kind": "ctor", "name": "s", "args": [{"kind": "ctor", "name": "zero", "args": []}]}
            ]}
        }
    })
}

fn compile_via_json_and_binary(
    compiler: &dyn IrCompiler,
    dialect: &str,
    fixture: Json,
) -> Result<(CompiledFormula, CompiledFormula), CompileError> {
    let json_input = CompilerInput::decode_json(fixture)?;
    let binary = BinaryProofIrFrontend::encode(&json_input)?;
    let binary_input = BinaryProofIrFrontend::decode(&binary)?;
    assert_eq!(binary_input, json_input);

    let json_output = compiler.compile_typed(&json_input, dialect)?;
    let binary_output = compiler.compile_typed(&binary_input, dialect)?;
    Ok((json_output, binary_output))
}

fn policy_admits(field: CompiledFormulaFieldPath, policy: &[FrontendProvenancePolicy]) -> bool {
    policy.iter().any(|row| {
        !row.owner.trim().is_empty()
            && !row.reason.trim().is_empty()
            && row
                .retirement
                .as_deref()
                .is_some_and(|retirement| !retirement.trim().is_empty())
            && row.allowed_fields.contains(&field)
    })
}

fn assert_compiled_formula_equal_under_policy(
    left: &CompiledFormula,
    right: &CompiledFormula,
    policy: &[FrontendProvenancePolicy],
) -> Result<(), String> {
    let mut unadmitted = Vec::new();
    if left.preamble != right.preamble && !policy_admits(CompiledFormulaFieldPath::Preamble, policy)
    {
        unadmitted.push("preamble");
    }
    if left.body != right.body && !policy_admits(CompiledFormulaFieldPath::Body, policy) {
        unadmitted.push("body");
    }
    if left.free_vars != right.free_vars
        && !policy_admits(CompiledFormulaFieldPath::FreeVars, policy)
    {
        unadmitted.push("free_vars");
    }
    if left.opacity_manifest != right.opacity_manifest
        && !policy_admits(CompiledFormulaFieldPath::OpacityManifest, policy)
    {
        unadmitted.push("opacity_manifest");
    }
    if left.metadata != right.metadata && !policy_admits(CompiledFormulaFieldPath::Metadata, policy)
    {
        unadmitted.push("metadata");
    }

    if unadmitted.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "unadmitted JSON/binary frontend output difference in {}",
            unadmitted.join(", ")
        ))
    }
}

#[test]
fn binary_frontend_serialization_symbols_do_not_enter_backend_crates() {
    for rel_path in [
        "implementations/rust/sugar-ir-compiler-smt-lib/src/lib.rs",
        "implementations/rust/sugar-ir-compiler-lean/src/lib.rs",
        "implementations/rust/sugar-ir-compiler-coq/src/lib.rs",
        "implementations/rust/sugar-ir-compiler-maude/src/lib.rs",
    ] {
        let text = std::fs::read_to_string(repo_root().join(rel_path)).expect(rel_path);
        for forbidden in [
            "BinaryProofIrFrontend",
            "proofir-cbor-v1",
            "FrontendProvenancePolicy",
        ] {
            assert!(
                !text.contains(forbidden),
                "{rel_path} must not know about frontend serialization symbol `{forbidden}`"
            );
        }
    }
}

#[test]
fn instrument_c_json_and_binary_frontends_are_byte_equal_through_smtlib_and_maude() {
    let (json_output, binary_output) =
        compile_via_json_and_binary(&SmtLibCompiler::new(), SMT_DIALECT, formula_fixture())
            .expect("SMT-LIB JSON/binary compile");
    assert_compiled_formula_equal_under_policy(&json_output, &binary_output, &[])
        .expect("default-empty policy requires SMT-LIB byte identity");

    let (json_output, binary_output) = compile_via_json_and_binary(
        &MaudeCompiler::new(),
        MAUDE_DIALECT,
        equational_theory_fixture(),
    )
    .expect("Maude JSON/binary compile");
    assert_compiled_formula_equal_under_policy(&json_output, &binary_output, &[])
        .expect("default-empty policy requires Maude byte identity, including metadata");
}

#[test]
fn corrupted_binary_frontend_payload_is_typed() {
    let input = CompilerInput::decode_json(formula_fixture()).expect("formula fixture decodes");
    let mut binary = BinaryProofIrFrontend::encode(&input).expect("binary fixture encodes");
    binary[0] ^= 0xff;

    let err = BinaryProofIrFrontend::decode(&binary).expect_err("corrupted binary refuses");
    assert_eq!(err.payload.kind, FrontendErrorKind::MalformedTransport);
    assert_eq!(
        err.payload.frontend,
        "sugar-ir-compiler::frontend::BinaryProofIrFrontend::decode"
    );
    assert_eq!(err.payload.input_format, "proofir-cbor-v1");
    assert_eq!(err.payload.path, "$");
}

#[test]
fn instrument_c_reds_on_unadmitted_and_passes_on_policy_admitted_difference() {
    let (json_output, mut drifted) =
        compile_via_json_and_binary(&SmtLibCompiler::new(), SMT_DIALECT, formula_fixture())
            .expect("SMT-LIB JSON/binary compile");
    drifted.body.push_str("; planted-s6-unadmitted-drift\n");

    let unadmitted = assert_compiled_formula_equal_under_policy(&json_output, &drifted, &[])
        .expect_err("default-empty policy must red on planted output drift");
    assert!(unadmitted.contains("body"));

    let policy = FrontendProvenancePolicy {
        owner: "typed ProofIR frontend-boundary campaign".to_string(),
        allowed_fields: vec![CompiledFormulaFieldPath::Body],
        reason: "planted S6 policy-admitted drift control".to_string(),
        retirement: Some("delete this test-only allowance with the planted control".to_string()),
    };
    assert_compiled_formula_equal_under_policy(&json_output, &drifted, &[policy])
        .expect("typed provenance policy admits the named planted body difference");
}
