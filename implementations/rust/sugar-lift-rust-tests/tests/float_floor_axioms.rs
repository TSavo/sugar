// Family (e) float floor axioms (#3415), T's 2026-07-03 ruling. A float special
// value (`f32::NAN`, `f64::INFINITY`, ...) enters as a FLOOR value: the ground
// `float:fW(bits)` ctor whose bit pattern IS the identity. The SMT emitter classifies
// that bit pattern into the refinement axioms (`is_finite`/`is_nan`/`is_infinite`/
// `is_sign_*`). This discrimination gate proves both directions on the compiled SMT
// via real z3: a truthful witness stays SAT (consistent), a semantic lie flips to
// UNSAT (contradicted by the floor axiom). Asserted-path satisfiability.

use sugar_lift_rust_tests::{lift_file, AssertionFactKind};

fn parse(src: &str) -> syn::File {
    syn::parse_file(src).expect("parse")
}

fn z3() -> String {
    std::env::var("Z3").unwrap_or_else(|_| "z3".to_string())
}

fn asserted_sat(inv: &serde_json::Value, label: &str) -> bool {
    let input = sugar_ir_compiler::CompilerInput::decode_json(inv.clone())
        .unwrap_or_else(|e| panic!("decode {label}: {e:?}"));
    let formula = match input {
        sugar_ir_compiler::CompilerInput::Formula(f) => f,
        _ => panic!("expected formula input for {label}"),
    };
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_formula_to_parts(formula.formula())
        .unwrap_or_else(|e| panic!("compile {label}: {e:?}"));
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let path = std::env::temp_dir().join(format!("float_floor_instr_{label}.smt2"));
    std::fs::write(&path, &script).expect("write smt2");
    let out = std::process::Command::new(z3())
        .arg(&path)
        .output()
        .expect("run z3");
    let stdout = String::from_utf8_lossy(&out.stdout);
    println!("---- {label} script ----\n{script}\n---- z3: {stdout}");
    assert!(
        !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
        "{label} must be well-sorted:\n{stdout}"
    );
    stdout.contains("sat") && !stdout.contains("unsat")
}

fn check(label: &str, src: &str, expect_sat: bool) {
    let out = lift_file(&parse(src), "tests/float_floor_instrument.rs");
    let warranted: Vec<_> = out
        .decls
        .iter()
        .filter(|d| {
            out.assertion_facts.iter().any(|f| {
                f.kind == AssertionFactKind::Warranted
                    && f.claim_count > 0
                    && f.contract_name.as_str() == d.name
            })
        })
        .collect();
    assert_eq!(warranted.len(), 1, "{label}: expected one claim-bearing decl");
    let inv = {
        let doc =
            sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(warranted[0]));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        parsed[0]["inv"].clone()
    };
    let sat = asserted_sat(&inv, label);
    println!("RESULT {label}: sat={sat} (expected sat={expect_sat})");
    assert_eq!(sat, expect_sat, "{label}: verdict mismatch");
}

#[test]
fn float_special_floor_axioms_flip_the_lie_both_directions() {
    // truthful => consistent (sat); lie => contradicted by floor axiom (unsat)
    check(
        "nan_is_finite_truthful",
        r#"#[test] fn t() { assert!(!f32::NAN.is_finite()); }"#,
        true,
    );
    check(
        "nan_is_finite_LIE",
        r#"#[test] fn t() { assert!(f32::NAN.is_finite()); }"#,
        false,
    );
    check(
        "infinity_eq_truthful",
        r#"#[test] fn t() { assert_eq!(f32::INFINITY, f32::INFINITY); }"#,
        true,
    );
    check(
        "infinity_eq_LIE",
        r#"#[test] fn t() { assert_eq!(f32::INFINITY, f32::NEG_INFINITY); }"#,
        false,
    );
    // constraint_infinity_eq enrolled pair (binary `==` inside assert!)
    check(
        "constraint_infinity_eq_truthful",
        r#"#[test] fn t() { assert!(f32::INFINITY == f32::INFINITY); }"#,
        true,
    );
    check(
        "constraint_infinity_eq_LIE",
        r#"#[test] fn t() { assert!(f32::INFINITY == f32::NEG_INFINITY); }"#,
        false,
    );
    check(
        "nan_is_nan_truthful",
        r#"#[test] fn t() { assert!(f32::NAN.is_nan()); }"#,
        true,
    );
    check(
        "f64_infinity_is_infinite_truthful",
        r#"#[test] fn t() { assert!(f64::INFINITY.is_infinite()); }"#,
        true,
    );
}
