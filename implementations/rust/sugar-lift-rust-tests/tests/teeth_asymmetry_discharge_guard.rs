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
    //
    // This now INCLUDES a CONST-length array-repeat (lever H): a const-NAME or
    // const-ARITHMETIC length (`const SIZE: usize = 3`, `const CAP: usize = 2*B-1`)
    // resolves through scope (`repeat_count_in_scope`) and grounds to the same
    // `[7, 7, 7]` a literal `[7; 3]` does, so `[7; SIZE][1] == 99` REFUTES exactly
    // like the literal repeat. PREVIOUSLY the const-length repeat refused the whole
    // index (the false claim was dark / unwarranted) -- grounding it is strictly
    // stronger: a dark false claim becomes an actively-refuted one, never discharged.
    for (name, src) in [
        (
            "literal_index_false",
            r#"#[test] fn t() { assert_eq!([7, 7, 7][1], 99); }"#,
        ),
        (
            "literal_repeat_false",
            r#"#[test] fn t() { assert_eq!([7; 3][1], 99); }"#,
        ),
        (
            "const_name_repeat_false",
            r#"const SIZE: usize = 3; #[test] fn t() { assert_eq!([7; SIZE][1], 99); }"#,
        ),
        (
            "const_arith_repeat_false",
            r#"const B: usize = 2; const CAP: usize = 2 * B - 1; #[test] fn t() { assert_eq!([7; CAP][1], 99); }"#,
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
    //
    // TWO array-repeat shapes belong here -- the finite-or-refuse boundary of lever H,
    // which grounds a CONCRETE const LENGTH but never fabricates a value the text does
    // not determine:
    //   * non-literal ELEMENT (`[compute(); 3]`): the length is a literal `3`, but the
    //     element is an opaque call that cannot const-eval, so the indexed read stays an
    //     uninterpreted aggregate -- congruence-only, never discharged.
    //   * const-GENERIC LENGTH (`[7; N]`, no concrete registry initializer): the length
    //     is symbolic, so `repeat_count_in_scope` declines and the index stays the
    //     uninterpreted `index(..)` ctor -- congruence-only, never discharged. This is
    //     the key discrimination: lever H grounds `const SIZE = 3` but NOT a symbolic `N`.
    // (The `Disp::Refused` no-decl disposition for a non-finite repeat is exercised in a
    // SEQUENCE context by `for_array_repeat_non_literal_element_refuses` in
    // `assertion_lift.rs`; in an INDEX operand position the read always leaves at least a
    // symbolic congruence-only decl, i.e. UNDECIDED.)
    for (name, src) in [
        (
            "arrays_differ_false",
            r#"#[test] fn t() { assert_eq!([7, 7, 99], [7, 7, 7]); }"#,
        ),
        (
            "maybeuninit_false",
            r#"#[test] fn t() { assert_eq!(unsafe { core::mem::MaybeUninit::new(7).assume_init() }, 8); }"#,
        ),
        (
            "opaque_element_repeat_false",
            r#"#[test] fn t() { assert_eq!([compute(); 3][1], 99); }"#,
        ),
        (
            "const_generic_repeat_false",
            r#"fn sized<const N: usize>() { assert_eq!([7; N][1], 99); } #[test] fn t() { sized::<3>(); }"#,
        ),
    ] {
        let d = disp_of(name, src);
        assert_ne!(
            d,
            Disp::Discharged,
            "CARDINAL SIN: false claim `{name}` was DISCHARGED (got {d:?})"
        );
    }
}

// ── The SYMMETRIC floor: no false REFUTATION (no fake dragons) ────────────────
//
// `false_assertions_are_never_discharged_*` above pins one direction (no fake
// LIGHTS). This pins the inverse cardinal sin: a TRUE literal-domain assertion
// must NEVER be `refuted`. Marking correct code as a dragon is as unsound as
// marking a false claim proven. Correct outcomes for a true claim: `discharged`
// (if tracked), `undecided` (no teeth), or `refused` (out of text) -- NEVER
// `refuted`. The two-sided floor is `false_discharges == 0 ∧ false_refutations == 0`.
#[test]
fn true_assertions_are_never_refuted() {
    // Every assertion here is TRUE in real Rust. None may come back `Refuted`.
    for (name, src) in [
        ("literal_index_true", r#"#[test] fn t() { assert_eq!([7, 7, 7][1], 7); }"#),
        ("literal_arith_true", r#"#[test] fn t() { assert_eq!(2 + 2, 4); }"#),
        ("literal_repeat_true", r#"#[test] fn t() { assert_eq!([7; 3][1], 7); }"#),
        ("same_arrays_true", r#"#[test] fn t() { assert_eq!([7, 7, 99], [7, 7, 99]); }"#),
        // Opaque-but-true: an uninterpreted value the kit cannot ground. Correct
        // outcome is UNDECIDED (no teeth), never a refutation.
        (
            "maybeuninit_true",
            r#"#[test] fn t() { assert_eq!(unsafe { core::mem::MaybeUninit::new(7).assume_init() }, 7); }"#,
        ),
    ] {
        let d = disp_of(name, src);
        assert_ne!(
            d,
            Disp::Refuted,
            "FALSE REFUTATION (fake dragon): true claim `{name}` was REFUTED (got {d:?})"
        );
    }
}

// borrow4's stale-`&mut` case, pinned specifically. This is a KNOWN-CURRENT hole,
// empirically confirmed end-to-end (lift -> discharge): `*r += 1` is refused, so
// `x` stays stale at its initializer 5, BUT `assert_eq!(x, 6)` is still emitted as
// a WARRANTED obligation with inv `=(5, 6)` -> the discharge gate REFUTES a TRUE
// assertion (x really is 6). A false refutation -- a fake dragon -- live today.
//
// The fix is the untrackable-deref-mutation refuse (the no-false-refutation accuracy-
// gate, #16): a local mutated through a refused `*r OP= ..` no longer grounds to its
// stale initializer -- the read REFUSES by name (`ambiguous temporal identity`) instead
// of lifting `5 == 6`. LANDED here: with the gate, no decl is emitted, so `disp_of`
// returns `Refused` (not `Refuted`). This is the durable regression net -- it must stay
// green (Disp != Refuted) forever after. (The post-mutation WARRANT -- x == 6 SAT -- is
// the separate attended SSA arm, T3 #6; this gate only stops the false refutation.)
#[test]
fn borrow4_stale_mut_assignment_must_not_false_refute() {
    let d = disp_of(
        "borrow4_stale_mut",
        r#"#[test] fn t() { let mut x = 5; let r = &mut x; *r += 1; assert_eq!(x, 6); }"#,
    );
    assert_ne!(
        d,
        Disp::Refuted,
        "FALSE REFUTATION: stale-&mut `assert_eq!(x,6)` (x really is 6) was REFUTED as `5==6` (got {d:?})"
    );
}

// ── Lane 5: ASCII char-predicate concrete-fold discrimination twins ────────────
//
// `desugar_char_class` now evaluates the predicate on the host char literal and
// lowers to `eq(bool(result), bool(true))`.  A true claim must DISCHARGE; the
// bad-twin (a false assertion) must REFUTE.  The two directions together pin the
// invariant: no false light, no fake dragon.
#[test]
fn ascii_char_predicates_discharge_correct_and_refute_bad_twin() {
    for (name, src, expect_discharged) in [
        // ── is_ascii_digit ──
        (
            "digit_true_5",
            r#"#[test] fn t() { assert!('5'.is_ascii_digit()); }"#,
            true,
        ),
        (
            // BAD-TWIN: 'a' is NOT an ASCII digit — invariant eq(false,true) → REFUTED
            "digit_false_a_badtwin",
            r#"#[test] fn t() { assert!('a'.is_ascii_digit()); }"#,
            false,
        ),
        // ── is_ascii_alphabetic ──
        (
            "alpha_true_a",
            r#"#[test] fn t() { assert!('a'.is_ascii_alphabetic()); }"#,
            true,
        ),
        (
            // BAD-TWIN: '5' is NOT alphabetic
            "alpha_false_5_badtwin",
            r#"#[test] fn t() { assert!('5'.is_ascii_alphabetic()); }"#,
            false,
        ),
        // ── is_ascii_uppercase ──
        (
            "upper_true_A",
            r#"#[test] fn t() { assert!('A'.is_ascii_uppercase()); }"#,
            true,
        ),
        (
            // BAD-TWIN: 'a' is lowercase, NOT uppercase
            "upper_false_a_badtwin",
            r#"#[test] fn t() { assert!('a'.is_ascii_uppercase()); }"#,
            false,
        ),
        // ── is_ascii_lowercase ──
        (
            "lower_true_a",
            r#"#[test] fn t() { assert!('a'.is_ascii_lowercase()); }"#,
            true,
        ),
        (
            // BAD-TWIN: 'A' is NOT lowercase
            "lower_false_A_badtwin",
            r#"#[test] fn t() { assert!('A'.is_ascii_lowercase()); }"#,
            false,
        ),
        // ── is_ascii_alphanumeric ──
        (
            "alnum_true_9",
            r#"#[test] fn t() { assert!('9'.is_ascii_alphanumeric()); }"#,
            true,
        ),
        (
            // BAD-TWIN: '!' is NOT alphanumeric
            "alnum_false_bang_badtwin",
            r#"#[test] fn t() { assert!('!'.is_ascii_alphanumeric()); }"#,
            false,
        ),
        // ── is_ascii_hexdigit ──
        (
            "hex_true_f",
            r#"#[test] fn t() { assert!('f'.is_ascii_hexdigit()); }"#,
            true,
        ),
        (
            // BAD-TWIN: 'g' is NOT a hex digit
            "hex_false_g_badtwin",
            r#"#[test] fn t() { assert!('g'.is_ascii_hexdigit()); }"#,
            false,
        ),
        // ── is_ascii_whitespace ──
        (
            "ws_true_space",
            r#"#[test] fn t() { assert!(' '.is_ascii_whitespace()); }"#,
            true,
        ),
        (
            // BAD-TWIN: 'x' is NOT ASCII whitespace
            "ws_false_x_badtwin",
            r#"#[test] fn t() { assert!('x'.is_ascii_whitespace()); }"#,
            false,
        ),
        // ── eq_ignore_ascii_case ──
        (
            "eqcase_true",
            r#"#[test] fn t() { assert!("abc".eq_ignore_ascii_case("ABC")); }"#,
            true,
        ),
        (
            // BAD-TWIN: "Ürl" vs "ürl" — non-ASCII → compared literally → NOT equal
            "eqcase_false_nonascii_badtwin",
            r#"#[test] fn t() { assert!("Ürl".eq_ignore_ascii_case("ürl")); }"#,
            false,
        ),
    ] {
        let d = disp_of(name, src);
        if expect_discharged {
            assert!(
                d == Disp::Discharged || d == Disp::Z3Absent,
                "Lane 5: `{name}` (correct assertion) should DISCHARGE or be Z3Absent, got {d:?}\nsrc: {src}"
            );
        } else {
            // Bad-twin: a FALSE assertion — must be REFUTED (teeth), never discharged.
            assert!(
                d == Disp::Refuted || d == Disp::Z3Absent,
                "Lane 5 BAD-TWIN: `{name}` (false assertion) must REFUTE, got {d:?}\nsrc: {src}"
            );
        }
    }
}
