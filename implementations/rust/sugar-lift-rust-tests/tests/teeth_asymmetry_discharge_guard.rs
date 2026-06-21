//! Soundness regression: a FALSE assertion is NEVER discharged.
//!
//! The source-audit ledger separates two layers, and this guard pins the
//! separation so a future change cannot collapse coverage into proof:
//!
//!   * LIFT `warranted` = COVERAGE -- "the locus lifted to a checkable FOL
//!     fact". It is a structural tally computed with NO solver
//!     (`rust_test_assertions_rpc.rs::source_ledger`, status assigned in
//!     `classify_nontest_fn` / the test-fn arm). A congruence-only / opaque
//!     lift (two distinct opaque array vars; an uninterpreted EUF method
//!     ctor like `MaybeUninit::new(lit).assume_init()`) still lifts -- its
//!     invariant is SAT for ANY right-hand side, so lift-level SAT carries no
//!     teeth and proves nothing.
//!
//!   * DISCHARGE = VALIDITY -- requires z3 UNSAT on the NEGATION
//!     (`sugar-verifier/src/body_discharge.rs`: positive `=(6,6)` -> neg
//!     UNSAT -> discharged; negative `=(6,8)` -> neg SAT -> NOT discharged).
//!     A congruence-only lift's negation is SAT, so it can never be
//!     discharged -- at worst it is UNDECIDED (warranted coverage, unproven).
//!
//! The cardinal sin would be DISCHARGING a false claim. This test proves that
//! across the shapes that prompted the audit: teethed shapes REFUTE a wrong
//! value, congruence-only shapes leave it UNDECIDED, and a const-length
//! array-repeat is REFUSED outright -- in no case is a false claim discharged.
//!
//! z3-gated: every solver call degrades to `Z3Absent` when /usr/local/bin/z3
//! is missing, so the test is a no-op rather than a failure off the solver box.

use sugar_lift_rust_tests::lift_file;

fn parse(src: &str) -> syn::File {
    syn::parse_file(src).expect("fixture parses")
}

/// Run z3 on a compiled invariant. `Some(true)` = SAT, `Some(false)` = UNSAT,
/// `None` = z3 absent / ill-sorted (test then degrades to a no-op).
fn z3_sat(inv: &serde_json::Value, label: &str) -> Option<bool> {
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(inv).ok()?;
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if !std::path::Path::new(z3).exists() {
        return None;
    }
    let path = std::env::temp_dir().join(format!("teeth_guard_{label}.smt2"));
    std::fs::write(&path, &script).expect("write smt2");
    let out = std::process::Command::new(z3)
        .arg(&path)
        .output()
        .expect("run z3");
    let stdout = String::from_utf8_lossy(&out.stdout);
    if stdout.contains("unknown constant") || stdout.to_lowercase().contains("error") {
        return None;
    }
    Some(stdout.contains("sat") && !stdout.contains("unsat"))
}

/// Disposition of a single lifted assertion under both gates.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
enum Disp {
    /// Not lifted at all (no decl) -- the honest dark.
    Refused,
    /// inv UNSAT -> a false claim is caught (teeth).
    Refuted,
    /// neg UNSAT -> valid (teeth, or reflexive).
    Discharged,
    /// both SAT -> warranted coverage but no teeth (cannot prove or refute).
    Undecided,
    /// z3 unavailable -- test degrades to a no-op for this shape.
    Z3Absent,
}

fn disp_of(name: &str, src: &str) -> Disp {
    let out = lift_file(&parse(src), "audit/teeth.rs");
    if out.decls.is_empty() {
        return Disp::Refused;
    }
    let doc =
        sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&out.decls[0]));
    let parsed: serde_json::Value = serde_json::from_str(&doc).expect("decl marshals to json");
    let inv = parsed[0]["inv"].clone();
    let pos = z3_sat(&inv, &format!("{name}_pos"));
    let neg = serde_json::json!({ "kind": "not", "operands": [inv.clone()] });
    let neg_sat = z3_sat(&neg, &format!("{name}_neg"));
    match (pos, neg_sat) {
        (Some(false), _) => Disp::Refuted,
        (Some(true), Some(false)) => Disp::Discharged,
        (Some(true), Some(true)) => Disp::Undecided,
        _ => Disp::Z3Absent,
    }
}

#[test]
fn false_assertions_are_never_discharged_teeth_asymmetry() {
    // TEETHED shapes: lift grounds to a concrete value, so a WRONG right-hand
    // side makes the invariant UNSAT -> the false claim is actively REFUTED.
    for (name, src) in [
        (
            "literal_index_false",
            r#"#[test] fn t() { assert_eq!([7, 7, 7][1], 99); }"#,
        ),
        (
            "literal_repeat_false",
            r#"#[test] fn t() { assert_eq!([7; 3][1], 99); }"#,
        ),
    ] {
        let d = disp_of(name, src);
        assert!(
            d == Disp::Refuted || d == Disp::Z3Absent,
            "{name}: a teethed shape must REFUTE a false claim, got {d:?}"
        );
    }

    // CONGRUENCE-ONLY shapes: the lift is an opaque var / EUF ctor, SAT for any
    // right-hand side. A false claim is therefore UNDECIDED -- warranted
    // coverage, NOT discharged. (If a future recognizer grounds the value it
    // becomes Refuted instead; both satisfy the cardinal-sin guard.) The ONLY
    // forbidden outcome is Discharged.
    for (name, src) in [
        (
            "arrays_differ_false",
            r#"#[test] fn t() { assert_eq!([7, 7, 99], [7, 7, 7]); }"#,
        ),
        (
            "maybeuninit_false",
            r#"#[test] fn t() { assert_eq!(unsafe { core::mem::MaybeUninit::new(7).assume_init() }, 8); }"#,
        ),
    ] {
        let d = disp_of(name, src);
        assert_ne!(
            d,
            Disp::Discharged,
            "CARDINAL SIN: false claim `{name}` was DISCHARGED (got {d:?})"
        );
    }

    // REFUSED shape: a const-NAME array-repeat length is not a finite literal
    // construction, so it is refused outright -- never hollow-lifted into
    // warranted coverage.
    assert_eq!(
        disp_of(
            "const_name_repeat",
            r#"const SIZE: usize = 3; #[test] fn t() { assert_eq!([7; SIZE][1], 99); }"#,
        ),
        Disp::Refused,
        "const-name array-repeat must be refused, not hollow-lifted"
    );
}
