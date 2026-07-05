// SPDX-License-Identifier: MIT OR Apache-2.0
//
// IR-JSON serializer + canonical-Value tests. Pins:
//
// `formula_to_value` and `term_to_value` produce a Value tree whose
// JCS-encoding is deterministic and whose BLAKE3-512 hash matches an
// independently computed reference.
//
// The kit's text serializer (marshal_declarations) emits in INSERTION
// order; the canonical-Value path (formula_to_value) emits in
// JCS-sorted order at hash time. Both are tested.

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_ir_symbolic::serialize::{
    formula_to_value, marshal_declarations, sort_to_value, term_to_value,
};
use sugar_ir_symbolic::{
    and_, choice, eq, exists, forall, gt, implies, lambda, let_term, must, not_, num, or_, out,
    parse_int, real_const, reset_collector, str_const, ConstValue, Int, Sort, Term,
};

// ---------------------------------------------------------------------------
// sort_to_value
// ---------------------------------------------------------------------------

#[test]
fn sort_to_value_emits_kind_primitive_and_name() {
    let v = sort_to_value(&Sort::int());
    let s = encode_jcs(&v);
    assert_eq!(s, "{\"kind\":\"primitive\",\"name\":\"Int\"}");
}

#[test]
fn sort_to_value_round_trips_for_all_primitives() {
    for s in [Sort::int(), Sort::real(), Sort::string(), Sort::bool()] {
        let v = sort_to_value(&s);
        let encoded = encode_jcs(&v);
        assert!(encoded.contains(&format!("\"name\":\"{}\"", s.name)));
        assert!(encoded.contains("\"kind\":\"primitive\""));
    }
}

// ---------------------------------------------------------------------------
// term_to_value
// ---------------------------------------------------------------------------

#[test]
fn term_var_emits_kind_var_and_name() {
    let v = term_to_value(&Term::Var { name: "n".into() });
    let s = encode_jcs(&v);
    assert_eq!(s, "{\"kind\":\"var\",\"name\":\"n\"}");
}

#[test]
fn term_const_int_emits_value_and_sort() {
    let t = Term::Const {
        value: ConstValue::Int(42),
        sort: Sort::int(),
    };
    let v = term_to_value(&t);
    let s = encode_jcs(&v);
    // JCS sorts: kind, sort, value.
    assert_eq!(
        s,
        "{\"kind\":\"const\",\"sort\":{\"kind\":\"primitive\",\"name\":\"Int\"},\"value\":42}"
    );
}

#[test]
fn term_const_wide_int_emits_decimal_string_value() {
    let wide = 170141183460469231731687303715884105727i128;
    let t = Term::Const {
        value: ConstValue::Int(wide),
        sort: Sort::int(),
    };
    let v = term_to_value(&t);
    let s = encode_jcs(&v);
    assert!(
        s.contains("\"value\":\"170141183460469231731687303715884105727\""),
        "wide Int must be precision-safe decimal string JSON, not a lossy number: {s}"
    );
}

#[test]
fn term_const_real_emits_decimal_string_value_and_sort() {
    let t = real_const("2.0");
    let v = term_to_value(t.as_ref());
    let s = encode_jcs(&v);
    assert_eq!(
        s,
        "{\"kind\":\"const\",\"sort\":{\"kind\":\"primitive\",\"name\":\"Real\"},\"value\":\"2.0\"}"
    );
}

#[test]
fn term_const_string_emits_string_value() {
    let t = Term::Const {
        value: ConstValue::String("hello".into()),
        sort: Sort::string(),
    };
    let v = term_to_value(&t);
    let s = encode_jcs(&v);
    assert!(s.contains("\"value\":\"hello\""));
    assert!(s.contains("\"kind\":\"const\""));
    assert!(s.contains("\"name\":\"String\""));
}

#[test]
fn term_const_bool_emits_bool_value() {
    let t = Term::Const {
        value: ConstValue::Bool(true),
        sort: Sort::bool(),
    };
    let v = term_to_value(&t);
    let s = encode_jcs(&v);
    assert!(s.contains("\"value\":true"));
}

#[test]
fn term_ctor_emits_kind_name_args() {
    let t = parse_int(str_const("42"));
    let v = term_to_value(&t);
    let s = encode_jcs(&v);
    // JCS sorts: args, kind, name.
    assert!(s.starts_with("{\"args\":["));
    assert!(s.contains("\"kind\":\"ctor\""));
    assert!(s.contains("\"name\":\"parseInt\""));
}

// ---------------------------------------------------------------------------
// formula_to_value: every kind serializes correctly
// ---------------------------------------------------------------------------

#[test]
fn formula_atomic_serializes_with_kind_name_args() {
    reset_collector();
    let f = gt(num(1), num(2));
    let s = encode_jcs(&formula_to_value(&f));
    assert!(s.contains("\"kind\":\"atomic\""));
    assert!(s.contains("\"name\":\">\""));
    assert!(s.contains("\"args\":["));
}

#[test]
fn formula_connective_and_serializes_correctly() {
    reset_collector();
    let f = and_(vec![gt(num(1), num(2)), gt(num(3), num(4))]);
    let s = encode_jcs(&formula_to_value(&f));
    // JCS sorts: kind, operands.
    assert!(s.contains("\"kind\":\"and\""));
    assert!(s.contains("\"operands\":["));
}

#[test]
fn formula_connective_or_serializes_correctly() {
    reset_collector();
    let f = or_(vec![gt(num(1), num(2)), eq(num(3), num(3))]);
    let s = encode_jcs(&formula_to_value(&f));
    assert!(s.contains("\"kind\":\"or\""));
}

#[test]
fn formula_connective_not_serializes_correctly() {
    reset_collector();
    let f = not_(gt(num(1), num(2)));
    let s = encode_jcs(&formula_to_value(&f));
    assert!(s.contains("\"kind\":\"not\""));
}

#[test]
fn formula_connective_implies_serializes_correctly() {
    reset_collector();
    let f = implies(gt(num(1), num(2)), eq(num(3), num(3)));
    let s = encode_jcs(&formula_to_value(&f));
    assert!(s.contains("\"kind\":\"implies\""));
}

#[test]
fn formula_quantifier_forall_serializes_with_body_kind_name_sort() {
    reset_collector();
    let f = forall(Int(), |n| gt(n, num(0)));
    let s = encode_jcs(&formula_to_value(&f));
    // JCS sort: body, kind, name, sort.
    assert!(s.contains("\"kind\":\"forall\""));
    assert!(s.contains("\"body\":"));
    assert!(s.contains("\"sort\":{\"kind\":\"primitive\",\"name\":\"Int\"}"));
}

#[test]
fn formula_quantifier_exists_serializes_correctly() {
    reset_collector();
    let f = exists(Int(), |n| eq(n, num(0)));
    let s = encode_jcs(&formula_to_value(&f));
    assert!(s.contains("\"kind\":\"exists\""));
}

// ---------------------------------------------------------------------------
// HASH LOCK: cross-language reference vector
// ---------------------------------------------------------------------------
//
// `forall n: Int. n > 0` (the parseInt pre): this hash is what the
// C++/Go/TS peers must also produce when they JCS-encode their
// equivalent canonical-Value tree. The Rust kit's bound name is "_x0"
// (after reset_collector); cross-language tests must use that name.

#[test]
fn parseint_pre_canonical_bytes_pin_known_hash() {
    reset_collector();
    let f = forall(Int(), |n| gt(n, num(0)));
    let v = formula_to_value(&f);
    let canonical = encode_jcs(&v);

    // The exact JCS bytes are pinned here so any future change to the
    // IR shape, the JCS encoder, or the kit's bound-name scheme breaks
    // this test loud.
    assert_eq!(
        canonical,
        "{\"body\":{\"args\":[{\"kind\":\"var\",\"name\":\"_x0\"},\
         {\"kind\":\"const\",\"sort\":{\"kind\":\"primitive\",\"name\":\"Int\"},\"value\":0}],\
         \"kind\":\"atomic\",\"name\":\">\"},\
         \"kind\":\"forall\",\"name\":\"_x0\",\
         \"sort\":{\"kind\":\"primitive\",\"name\":\"Int\"}}"
    );

    // And the BLAKE3-512 of those exact bytes: pinned so the C++/Go/TS
    // peers can use this as their cross-language reference. Any drift
    // in the IR shape, the JCS encoder, or the hash function flips
    // this exact byte string and breaks the test loud.
    let h = blake3_512_of(canonical.as_bytes());
    assert_eq!(h, EXPECTED_PARSEINT_PRE_HASH);

    // Independently recomputed from a different formula (sanity: the
    // hash is genuinely a function of the canonical bytes).
    let v2 = formula_to_value(&forall(Int(), |n| gt(n, num(1))));
    assert_ne!(blake3_512_of(encode_jcs(&v2).as_bytes()), h);
}

/// Pinned BLAKE3-512 of the JCS-canonical encoding of
/// `forall n: Int. n > 0` with bound name "_x0" (the kit's first
/// quantifier name after reset_collector). Cross-language peers MUST
/// produce this exact value when they hash the same byte sequence
/// asserted in `parseint_pre_canonical_bytes_pin_known_hash`.
const EXPECTED_PARSEINT_PRE_HASH: &str =
    "blake3-512:d1bb4fdb761efb53eefdd046c3a17773174c9ae67a58a990eff89dc3adaa1acd26893d16b17b38c820f98065f4fc73e3a3536eefd80629e14b34927457a409b9";

#[test]
fn forall_n_gt_0_hash_is_independently_reproducible() {
    // Hand-build the exact same canonical bytes (without going through
    // the kit's quantifier counter) and assert the same hash. This is
    // the cross-language byte-sequence anchor.
    reset_collector();
    let kit_bytes = encode_jcs(&formula_to_value(&forall(Int(), |n| gt(n, num(0)))));
    let kit_hash = blake3_512_of(kit_bytes.as_bytes());

    // Hand-build with the exact same shape: var name "_x0", forall name "_x0".
    let hand = Value::object([
        ("kind", Value::string("forall")),
        ("name", Value::string("_x0")),
        (
            "sort",
            Value::object([
                ("kind", Value::string("primitive")),
                ("name", Value::string("Int")),
            ]),
        ),
        (
            "body",
            Value::object([
                ("kind", Value::string("atomic")),
                ("name", Value::string(">")),
                (
                    "args",
                    Value::array(vec![
                        Value::object([
                            ("kind", Value::string("var")),
                            ("name", Value::string("_x0")),
                        ]),
                        Value::object([
                            ("kind", Value::string("const")),
                            ("value", Value::integer(0)),
                            (
                                "sort",
                                Value::object([
                                    ("kind", Value::string("primitive")),
                                    ("name", Value::string("Int")),
                                ]),
                            ),
                        ]),
                    ]),
                ),
            ]),
        ),
    ]);
    let hand_bytes = encode_jcs(&hand);
    assert_eq!(kit_bytes, hand_bytes);
    assert_eq!(blake3_512_of(hand_bytes.as_bytes()), kit_hash);
}

// ---------------------------------------------------------------------------
// marshal_declarations: kit-shape (insertion-order) JSON
// ---------------------------------------------------------------------------

#[test]
fn marshal_declarations_emits_insertion_order_kind_name_outbinding_pre() {
    reset_collector();
    must("parseInt", forall(Int(), |n| gt(n, num(0))));
    let decls = sugar_ir_symbolic::finish();
    let s = marshal_declarations(&decls);
    // The kit emits: [{"kind":"contract","name":"...","outBinding":"...","pre":...}]
    let i_kind = s.find("\"kind\":\"contract\"").expect("kind first");
    let i_name = s.find("\"name\":\"parseInt\"").expect("name second");
    let i_ob = s.find("\"outBinding\":\"out\"").expect("outBinding third");
    let i_pre = s.find("\"pre\":").expect("pre fourth");
    assert!(i_kind < i_name);
    assert!(i_name < i_ob);
    assert!(i_ob < i_pre);
}

#[test]
fn marshal_declarations_handles_empty_decl_list() {
    let s = marshal_declarations(&[]);
    assert_eq!(s, "[]");
}

#[test]
fn marshal_declarations_separates_multiple_decls_with_commas() {
    reset_collector();
    must("a", forall(Int(), |n| gt(n, num(0))));
    must("b", forall(Int(), |n| eq(n, num(0))));
    let decls = sugar_ir_symbolic::finish();
    let s = marshal_declarations(&decls);
    assert!(s.starts_with("[{"));
    assert!(s.contains("},{"));
    assert!(s.ends_with("}]"));
}

#[test]
fn marshal_declarations_emits_post_when_present() {
    reset_collector();
    sugar_ir_symbolic::contract(
        "p",
        sugar_ir_symbolic::ContractArgs {
            pre: Some(forall(Int(), |n| gt(n, num(0)))),
            post: Some(eq(out(), num(0))),
            ..Default::default()
        },
    );
    let decls = sugar_ir_symbolic::finish();
    let s = marshal_declarations(&decls);
    assert!(s.contains("\"pre\":"));
    assert!(s.contains("\"post\":"));
}

#[test]
fn marshal_declarations_emits_inv_when_present() {
    reset_collector();
    sugar_ir_symbolic::contract(
        "p",
        sugar_ir_symbolic::ContractArgs {
            inv: Some(and_(vec![])),
            ..Default::default()
        },
    );
    let decls = sugar_ir_symbolic::finish();
    let s = marshal_declarations(&decls);
    assert!(s.contains("\"inv\":"));
}

#[test]
fn marshal_declarations_emits_wide_int_as_decimal_string() {
    reset_collector();
    sugar_ir_symbolic::contract(
        "wide",
        sugar_ir_symbolic::ContractArgs {
            inv: Some(eq(
                num(170141183460469231731687303715884105727i128),
                num(170141183460469231731687303715884105727i128),
            )),
            ..Default::default()
        },
    );
    let decls = sugar_ir_symbolic::finish();
    let s = marshal_declarations(&decls);
    assert!(
        s.contains("\"value\":\"170141183460469231731687303715884105727\""),
        "wide Int must not be emitted as a bare JSON number: {s}"
    );
    assert!(
        !s.contains("E+") && !s.contains("e+"),
        "wide Int JSON must not use exponent notation: {s}"
    );
}

// ---------------------------------------------------------------------------
// Round-trip JCS determinism
// ---------------------------------------------------------------------------

#[test]
fn formula_to_value_is_deterministic_across_calls() {
    reset_collector();
    let f = forall(Int(), |n| gt(n, num(0)));
    let v1 = formula_to_value(&f);
    let v2 = formula_to_value(&f);
    assert_eq!(encode_jcs(&v1), encode_jcs(&v2));
}

#[test]
fn nested_quantifier_serializes_recursively() {
    reset_collector();
    let f = forall(Int(), |a| exists(Int(), move |b| eq(a.clone(), b)));
    let s = encode_jcs(&formula_to_value(&f));
    assert!(s.contains("\"kind\":\"forall\""));
    assert!(s.contains("\"kind\":\"exists\""));
}

#[test]
fn deeply_nested_connective_serializes() {
    reset_collector();
    let f = and_(vec![
        or_(vec![gt(num(1), num(2)), eq(num(3), num(4))]),
        not_(gt(num(5), num(6))),
        implies(gt(num(7), num(8)), eq(num(9), num(10))),
    ]);
    let s = encode_jcs(&formula_to_value(&f));
    // All four kinds should appear.
    assert!(s.contains("\"kind\":\"and\""));
    assert!(s.contains("\"kind\":\"or\""));
    assert!(s.contains("\"kind\":\"not\""));
    assert!(s.contains("\"kind\":\"implies\""));
}

// ---------------------------------------------------------------------------
// Sensitivity of hash to formula contents
// ---------------------------------------------------------------------------

#[test]
fn changing_predicate_changes_hash() {
    reset_collector();
    let h_gt = blake3_512_of(encode_jcs(&formula_to_value(&gt(num(1), num(2)))).as_bytes());
    let h_lt = blake3_512_of(
        encode_jcs(&formula_to_value(&sugar_ir_symbolic::lt(num(1), num(2)))).as_bytes(),
    );
    assert_ne!(h_gt, h_lt);
}

#[test]
fn changing_arg_value_changes_hash() {
    reset_collector();
    let h_a = blake3_512_of(encode_jcs(&formula_to_value(&gt(num(1), num(2)))).as_bytes());
    let h_b = blake3_512_of(encode_jcs(&formula_to_value(&gt(num(1), num(3)))).as_bytes());
    assert_ne!(h_a, h_b);
}

#[test]
fn structurally_equivalent_formulas_with_same_bound_names_hash_equal() {
    reset_collector();
    let f1 = forall(Int(), |n| gt(n, num(0)));
    reset_collector();
    let f2 = forall(Int(), |n| gt(n, num(0)));
    let h1 = blake3_512_of(encode_jcs(&formula_to_value(&f1)).as_bytes());
    let h2 = blake3_512_of(encode_jcs(&formula_to_value(&f2)).as_bytes());
    assert_eq!(h1, h2);
}

// ---------------------------------------------------------------------------
// Lambda term serialization
// ---------------------------------------------------------------------------

#[test]
fn lambda_serializes_to_value_with_param_sort_and_body() {
    let lam = lambda("x".into(), Int(), num(42));
    let v = term_to_value(&lam);
    let s = encode_jcs(&v);
    assert!(s.contains("\"kind\":\"lambda\""));
    assert!(s.contains("\"paramName\":\"x\""));
    assert!(s.contains("\"paramSort\":{\"kind\":\"primitive\",\"name\":\"Int\"}"));
    assert!(s.contains("\"body\":{\"kind\":\"const\""));
}

#[test]
fn lambda_hash_is_deterministic() {
    let lam1 = lambda("x".into(), Int(), num(42));
    let lam2 = lambda("x".into(), Int(), num(42));
    let h1 = blake3_512_of(encode_jcs(&term_to_value(&lam1)).as_bytes());
    let h2 = blake3_512_of(encode_jcs(&term_to_value(&lam2)).as_bytes());
    assert_eq!(h1, h2);
}

// ---------------------------------------------------------------------------
// Let term serialization
// ---------------------------------------------------------------------------

#[test]
fn let_serializes_to_value_with_bindings_and_body() {
    let let_expr = let_term(
        vec![sugar_ir_symbolic::LetBinding {
            name: "x".into(),
            bound_term: num(1),
        }],
        num(2),
    );
    let v = term_to_value(&let_expr);
    let s = encode_jcs(&v);
    assert!(s.contains("\"kind\":\"let\""));
    assert!(s.contains("\"bindings\""));
    assert!(s.contains("\"name\":\"x\""));
    assert!(s.contains("\"body\":{\"kind\":\"const\""));
}

#[test]
fn let_hash_is_deterministic() {
    let l1 = let_term(
        vec![sugar_ir_symbolic::LetBinding {
            name: "x".into(),
            bound_term: num(1),
        }],
        num(2),
    );
    let l2 = let_term(
        vec![sugar_ir_symbolic::LetBinding {
            name: "x".into(),
            bound_term: num(1),
        }],
        num(2),
    );
    let h1 = blake3_512_of(encode_jcs(&term_to_value(&l1)).as_bytes());
    let h2 = blake3_512_of(encode_jcs(&term_to_value(&l2)).as_bytes());
    assert_eq!(h1, h2);
}

// ---------------------------------------------------------------------------
// Choice formula serialization
// ---------------------------------------------------------------------------

#[test]
fn choice_serializes_to_value_with_var_name_sort_and_body() {
    let c = choice("x".into(), Int(), |v| eq(v, num(0)));
    let v = formula_to_value(&c);
    let s = encode_jcs(&v);
    println!("choice serialization: {}", s);
    assert!(s.contains("\"kind\":\"choice\""));
    assert!(s.contains("\"varName\":\"x\""));
    assert!(s.contains("\"sort\":{\"kind\":\"primitive\",\"name\":\"Int\"}"));
    // JCS sorts keys; body may appear before or after other fields
    assert!(s.contains("\"body\":"));
    assert!(s.contains("\"kind\":\"atomic\""));
}

#[test]
fn choice_hash_is_deterministic() {
    let c1 = choice("x".into(), Int(), |v| eq(v, num(0)));
    let c2 = choice("x".into(), Int(), |v| eq(v, num(0)));
    let h1 = blake3_512_of(encode_jcs(&formula_to_value(&c1)).as_bytes());
    let h2 = blake3_512_of(encode_jcs(&formula_to_value(&c2)).as_bytes());
    assert_eq!(h1, h2);
}
