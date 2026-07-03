use std::path::Path;

use serde_json::{json, Value as Json};
use sugar_ir_compiler::{CompileError, CompilerInput, FrontendErrorKind, IrCompiler};
use sugar_ir_compiler_coq::{CoqCompiler, DIALECT as COQ_DIALECT};
use sugar_ir_compiler_maude::{MaudeCompiler, DIALECT as MAUDE_DIALECT};

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

fn term_fixture() -> Json {
    int_const(7)
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

fn typed(ir: Json) -> CompilerInput {
    CompilerInput::decode_json(ir).expect("fixture decodes through frontend")
}

#[test]
fn coq_and_maude_compile_typed_do_not_reencode_or_decode_transport_json() {
    for (label, rel_path, forbidden) in [
        (
            "coq",
            "implementations/rust/sugar-ir-compiler-coq/src/lib.rs",
            vec![
                "compile_json_adapter",
                "fn compile(&self, ir: &Json",
                "let ir = ir.to_json_value()?",
                "serde_json::from_value(ir.clone())",
            ],
        ),
        (
            "maude",
            "implementations/rust/sugar-ir-compiler-maude/src/lib.rs",
            vec![
                "compile_json_adapter",
                "fn compile(&self, ir: &Json",
                "let ir = ir.to_json_value()?",
                "struct RawObligation",
                "struct RawTheory",
                "struct RawEquation",
                "serde_json::from_value(ir.clone()).map_err",
            ],
        ),
    ] {
        let text = std::fs::read_to_string(repo_root().join(rel_path)).expect(rel_path);
        for needle in forbidden {
            assert!(
                !text.contains(needle),
                "{label} S3b typed backend ingress still contains legacy transport decode/twin `{needle}`"
            );
        }
    }
}

#[test]
fn coq_compile_typed_formula_and_term_are_deterministic() {
    let coq = CoqCompiler::new();
    for ir in [formula_fixture(), term_fixture()] {
        let typed = typed(ir);
        let compiled = coq.compile_typed(&typed, COQ_DIALECT).expect("typed coq");
        assert_eq!(
            compiled,
            coq.compile_typed(&typed, COQ_DIALECT)
                .expect("typed coq repeats")
        );
    }
}

#[test]
fn maude_compile_typed_equational_theory_matches_legacy_bytes_and_metadata() {
    let ir = equational_theory_fixture();
    let typed = typed(ir);
    let maude = MaudeCompiler::new();
    let native = maude
        .compile_typed(&typed, MAUDE_DIALECT)
        .expect("typed maude");
    let CompilerInput::EquationalTheory(obligation) = &typed else {
        panic!("fixture should decode as an equational theory");
    };
    let expected = sugar_ir_compiler_maude::compile_equational_theory_artifact(obligation)
        .expect("typed Maude artifact")
        .compiled;
    assert_eq!(native, expected);
    assert_eq!(native.metadata, expected.metadata);

    let maude_metadata = native
        .metadata
        .get("maude")
        .expect("Maude metadata side-table must survive typed ingress");
    assert!(maude_metadata.get("moduleSource").is_some());
    assert!(maude_metadata.get("queries").is_some());
    assert!(maude_metadata.get("trs").is_some());
}

#[test]
fn maude_malformed_theory_fails_at_frontend_decode() {
    let malformed = json!({
        "kind": "atomic",
        "name": "equational_theory",
        "theory": {
            "name": "broken",
            "operators": [{"name": "zero"}]
        },
        "obligation": {
            "lhs": {"kind": "ctor", "name": "zero", "args": []},
            "rhs": {"kind": "ctor", "name": "zero", "args": []}
        }
    });
    let err = CompilerInput::decode_json(malformed.clone()).unwrap_err();
    assert_eq!(err.payload.kind, FrontendErrorKind::InvalidTypedIr);

    assert_eq!(err.payload.path, "$");
}

#[test]
fn maude_admissibility_errors_stay_backend_owned_on_typed_input() {
    let invalid_operator = json!({
        "kind": "atomic",
        "name": "equational_theory",
        "theory": {
            "name": "backend-owned",
            "sorts": ["Nat"],
            "operators": [
                {"name": "bad token", "arity": [], "result": "Nat"}
            ],
            "equations": []
        },
        "obligation": {
            "lhs": {"kind": "ctor", "name": "bad token", "args": []},
            "rhs": {"kind": "ctor", "name": "bad token", "args": []}
        }
    });
    let typed = typed(invalid_operator);
    let err = MaudeCompiler::new()
        .compile_typed(&typed, MAUDE_DIALECT)
        .expect_err("Maude token admissibility stays backend-owned");
    assert!(
        matches!(err, CompileError::MalformedIr(detail) if detail.contains("operator name is not Maude-safe"))
    );
}

#[test]
fn byte_identity_control_would_notice_s3b_maude_metadata_drift() {
    let typed = typed(equational_theory_fixture());
    let mut drifted = MaudeCompiler::new()
        .compile_typed(&typed, MAUDE_DIALECT)
        .expect("compile");
    let original = drifted.clone();
    drifted.metadata["maude"]["moduleSource"] = json!("planted-drift-control");
    assert_ne!(drifted, original);
}
