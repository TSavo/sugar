use sugar_ir_symbolic::{ConstValue, Formula, Term};
use sugar_lift_rust_tests::{lift_file, lift_file_with_options, LiftOptions, TargetCfg};

fn parse(src: &str) -> syn::File {
    syn::parse_file(src).expect("fixture parses")
}

fn inv_operands(decl: &sugar_ir_symbolic::ContractDecl) -> &[std::rc::Rc<Formula>] {
    match decl.inv.as_deref() {
        Some(Formula::Connective { kind, operands }) if kind == "and" => operands,
        other => panic!("expected and inv, got {other:?}"),
    }
}

fn assert_eq_atom(formula: &Formula, expected_rhs: i64) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Int(value),
                    ..
                } => assert_eq!(*value, expected_rhs),
                other => panic!("expected int rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

fn assert_int_call_eq_atom(
    formula: &Formula,
    expected_lhs: i64,
    expected_call: &str,
    expected_arg: i64,
) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Const {
                    value: ConstValue::Int(value),
                    ..
                } => assert_eq!(*value, expected_lhs),
                other => panic!("expected int lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, expected_call);
                    assert_eq!(args.len(), 1);
                    match args[0].as_ref() {
                        Term::Const {
                            value: ConstValue::Int(value),
                            ..
                        } => assert_eq!(*value, expected_arg),
                        other => panic!("expected int call argument, got {other:?}"),
                    }
                }
                other => panic!("expected call term rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

fn assert_int_zero_arg_call_eq_atom(formula: &Formula, expected_call: &str, expected_rhs: i64) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, expected_call);
                    assert!(args.is_empty());
                }
                other => panic!("expected call term lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Int(value),
                    ..
                } => assert_eq!(*value, expected_rhs),
                other => panic!("expected int rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

fn assert_string_call_eq_atom(formula: &Formula, expected_call: &str, expected_rhs: &str) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, expected_call),
                other => panic!("expected call term lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::String(value),
                    ..
                } => assert_eq!(value, expected_rhs),
                other => panic!("expected string rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

fn assert_real_call_eq_atom(formula: &Formula, expected_call: &str, expected_rhs: &str) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, expected_call),
                other => panic!("expected call term lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Real(value),
                    sort,
                } => {
                    assert_eq!(value, expected_rhs);
                    assert_eq!(sort.name, "Real");
                }
                other => panic!("expected real rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

fn assert_float_refinement_atom(formula: &Formula, expected_name: &str, expected_call: &str) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, expected_name);
            assert_eq!(args.len(), 1);
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, expected_call),
                other => panic!("expected refined call term, got {other:?}"),
            }
        }
        other => panic!("expected float refinement atom, got {other:?}"),
    }
}

fn assert_float_refinement_var_atom(formula: &Formula, expected_name: &str, expected_var: &str) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, expected_name);
            assert_eq!(args.len(), 1);
            match args[0].as_ref() {
                Term::Var { name } => assert_eq!(name, expected_var),
                other => panic!("expected refined var term, got {other:?}"),
            }
        }
        other => panic!("expected float refinement atom, got {other:?}"),
    }
}

fn assert_int_call_cmp_atom(
    formula: &Formula,
    expected_op: &str,
    expected_call: &str,
    expected_rhs: i64,
) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, expected_op);
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, expected_call),
                other => panic!("expected call term lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Int(value),
                    ..
                } => assert_eq!(*value, expected_rhs),
                other => panic!("expected int rhs, got {other:?}"),
            }
        }
        other => panic!("expected comparison atom, got {other:?}"),
    }
}

fn assert_method_call_eq_compound_rhs(
    formula: &Formula,
    expected_call: &str,
    expected_rhs_ctor: &str,
    expected_lhs: i64,
    expected_rhs: i64,
) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, expected_call),
                other => panic!("expected method call lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, expected_rhs_ctor);
                    assert_eq!(args.len(), 2);
                    match args[0].as_ref() {
                        Term::Const {
                            value: ConstValue::Int(value),
                            ..
                        } => assert_eq!(*value, expected_lhs),
                        other => panic!("expected int compound lhs, got {other:?}"),
                    }
                    match args[1].as_ref() {
                        Term::Const {
                            value: ConstValue::Int(value),
                            ..
                        } => assert_eq!(*value, expected_rhs),
                        other => panic!("expected int compound rhs, got {other:?}"),
                    }
                }
                other => panic!("expected compound rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

fn assert_string_predicate_atom(formula: &Formula, expected_name: &str, expected_strings: &[&str]) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, expected_name);
            assert_eq!(args.len(), expected_strings.len());
            for (arg, expected) in args.iter().zip(expected_strings) {
                match arg.as_ref() {
                    Term::Const {
                        value: ConstValue::String(value),
                        sort,
                    } => {
                        assert_eq!(value, expected);
                        assert_eq!(sort.name, "String");
                    }
                    other => panic!("expected string arg {expected:?}, got {other:?}"),
                }
            }
        }
        other => panic!("expected string predicate atom, got {other:?}"),
    }
}

fn assert_string_len_cmp_atom(
    formula: &Formula,
    expected_op: &str,
    expected_lhs: &str,
    expected_rhs: i64,
) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, expected_op);
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "str.len");
                    assert_eq!(args.len(), 1);
                    match args[0].as_ref() {
                        Term::Const {
                            value: ConstValue::String(value),
                            sort,
                        } => {
                            assert_eq!(value, expected_lhs);
                            assert_eq!(sort.name, "String");
                        }
                        other => panic!("expected string len receiver, got {other:?}"),
                    }
                }
                other => panic!("expected str.len term lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Int(value),
                    ..
                } => assert_eq!(*value, expected_rhs),
                other => panic!("expected int rhs, got {other:?}"),
            }
        }
        other => panic!("expected string length comparison atom, got {other:?}"),
    }
}

fn assert_type_id_cmp_atom(
    formula: &Formula,
    expected_op: &str,
    expected_static_type: &str,
    expected_cast_type: &str,
    expected_receiver: &str,
) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, expected_op);
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, &format!("type_id::{expected_static_type}"));
                    assert!(args.is_empty());
                }
                other => panic!("expected static TypeId term lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "method:type_id");
                    assert_eq!(args.len(), 1);
                    match args[0].as_ref() {
                        Term::Ctor { name, args } => {
                            assert_eq!(name, &format!("cast:{expected_cast_type}"));
                            assert_eq!(args.len(), 1);
                            match args[0].as_ref() {
                                Term::Ctor { name, args } => {
                                    assert_eq!(name, "ref");
                                    assert_eq!(args.len(), 1);
                                    match args[0].as_ref() {
                                        Term::Var { name } => assert_eq!(name, expected_receiver),
                                        other => panic!(
                                            "expected referenced receiver var, got {other:?}"
                                        ),
                                    }
                                }
                                other => panic!("expected ref receiver term, got {other:?}"),
                            }
                        }
                        other => panic!("expected cast receiver term, got {other:?}"),
                    }
                }
                other => panic!("expected dynamic type_id term rhs, got {other:?}"),
            }
        }
        other => panic!("expected TypeId comparison atom, got {other:?}"),
    }
}

enum ExpectedScalar {
    Int(i64),
    Bool(bool),
}

enum ExpectedOperatorArg {
    Constructor(&'static str, ExpectedScalar),
}

fn assert_scalar_const(term: &Term, expected: ExpectedScalar) {
    match (term, expected) {
        (
            Term::Const {
                value: ConstValue::Int(value),
                ..
            },
            ExpectedScalar::Int(expected),
        ) => assert_eq!(*value, expected),
        (
            Term::Const {
                value: ConstValue::Bool(value),
                ..
            },
            ExpectedScalar::Bool(expected),
        ) => assert_eq!(*value, expected),
        (other, _) => panic!("expected scalar const, got {other:?}"),
    }
}

fn assert_const_index_eq(
    formula: &Formula,
    expected_base: &str,
    expected_index: i64,
    expected: i64,
) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "index");
                    assert_eq!(args.len(), 2);
                    match args[0].as_ref() {
                        Term::Var { name } => assert_eq!(name, expected_base),
                        other => panic!("expected const index base, got {other:?}"),
                    }
                    assert_scalar_const(&args[1], ExpectedScalar::Int(expected_index));
                }
                other => panic!("expected index term lhs, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Int(expected));
        }
        other => panic!("expected const-index equality atom, got {other:?}"),
    }
}

fn assert_operator_arg(term: &Term, expected: &ExpectedOperatorArg) {
    match expected {
        ExpectedOperatorArg::Constructor(expected_name, expected_arg) => match term {
            Term::Ctor { name, args } => {
                assert_eq!(name, expected_name);
                assert_eq!(args.len(), 1);
                match expected_arg {
                    ExpectedScalar::Int(value) => {
                        assert_scalar_const(&args[0], ExpectedScalar::Int(*value));
                    }
                    ExpectedScalar::Bool(value) => {
                        assert_scalar_const(&args[0], ExpectedScalar::Bool(*value));
                    }
                }
            }
            other => panic!("expected constructor operator arg, got {other:?}"),
        },
    }
}

fn assert_operator_bool_atom(
    formula: &Formula,
    expected_call: &str,
    expected_args: &[ExpectedOperatorArg],
    expected_result: bool,
) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, expected_call);
                    assert_eq!(args.len(), expected_args.len());
                    for (actual, expected) in args.iter().zip(expected_args.iter()) {
                        assert_operator_arg(actual, expected);
                    }
                }
                other => panic!("expected operator call lhs, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Bool(expected_result));
        }
        other => panic!("expected operator result equality atom, got {other:?}"),
    }
}

fn formula_contains_atomic_name(formula: &Formula, expected_name: &str) -> bool {
    match formula {
        Formula::Atomic { name, .. } => name == expected_name,
        Formula::Connective { operands, .. } => operands
            .iter()
            .any(|operand| formula_contains_atomic_name(operand, expected_name)),
        Formula::Quantifier { body, .. } => formula_contains_atomic_name(body, expected_name),
        _ => false,
    }
}

fn formula_contains_relation_name(formula: &Formula, expected_name: &str) -> bool {
    formula_contains_atomic_name(formula, expected_name)
}

fn formula_count_atomic_name(formula: &Formula, expected_name: &str) -> usize {
    match formula {
        Formula::Atomic { name, .. } => usize::from(name == expected_name),
        Formula::Connective { operands, .. } => operands
            .iter()
            .map(|operand| formula_count_atomic_name(operand, expected_name))
            .sum(),
        Formula::Quantifier { body, .. } => formula_count_atomic_name(body, expected_name),
        _ => 0,
    }
}

fn formula_count_connective_kind(formula: &Formula, expected_kind: &str) -> usize {
    match formula {
        Formula::Connective { kind, operands } => {
            usize::from(kind == expected_kind)
                + operands
                    .iter()
                    .map(|operand| formula_count_connective_kind(operand, expected_kind))
                    .sum::<usize>()
        }
        Formula::Quantifier { body, .. } => formula_count_connective_kind(body, expected_kind),
        _ => 0,
    }
}

fn assert_await_call_eq_atom(formula: &Formula, expected_call: &str, expected_rhs: i64) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "await");
                    assert_eq!(args.len(), 1);
                    match args[0].as_ref() {
                        Term::Ctor { name, args } => {
                            assert_eq!(name, expected_call);
                            assert!(args.is_empty());
                        }
                        other => panic!("expected awaited call term, got {other:?}"),
                    }
                }
                other => panic!("expected await term lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Int(value),
                    ..
                } => assert_eq!(*value, expected_rhs),
                other => panic!("expected int rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn lifts_single_assert_eq_as_inv_only_consistency_contract() {
    let src = r#"
fn make_value() -> i32 { 6 }

#[test]
fn scalar_is_six() {
    assert_eq!(make_value(), 6);
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "src/lib.rs::scalar_is_six::make_value#euf#c:callresult_make_value_a0()::assertion"
    );
    assert!(decl.pre.is_none());
    assert!(decl.post.is_none());
    assert!(decl.evidence.is_none());
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_eq_atom(&operands[0], 6);
}

#[test]
fn conjoins_contradictory_assert_eq_atoms_in_one_inv() {
    let src = r#"
fn make_value() -> i32 { 6 }

#[test]
fn scalar_contradiction() {
    assert_eq!(make_value(), 6);
    assert_eq!(make_value(), 7);
}
"#;
    let out = lift_file(&parse(src), "tests/contradiction.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "tests/contradiction.rs::scalar_contradiction::make_value#euf#c:callresult_make_value_a0()::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    assert_eq_atom(&operands[0], 6);
    assert_eq_atom(&operands[1], 7);
}

// A byte literal `b'0'` is pure sugar for a u8 constant (48). It must dissolve to
// the SAME concrete-Int-with-u8-sort form `48u8` lifts to — value-faithful, and
// distinct byte literals must stay distinct so a false twin cannot coalesce into a
// vacuous discharge (the masked-contradiction failure mode the sweep can't catch).
fn byte_literal_eq_atom_value_and_sort(formula: &Formula) -> (i64, String) {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Int(value),
                    sort,
                } => (*value, sort.name.clone()),
                other => panic!("expected int-const byte-literal rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn byte_literal_dissolves_to_u8_constant() {
    // Positive: `b'0'` lifts to the int value 48 with u8 sort (sugar in, constraint
    // out). `byte_val()` is the EUF call-result LHS; the byte literal is the RHS.
    let src = r#"
fn byte_val() -> u8 { 48 }

#[test]
fn byte_is_zero() {
    assert_eq!(byte_val(), b'0');
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    let (value, sort) = byte_literal_eq_atom_value_and_sort(&operands[0]);
    assert_eq!(value, 48, "b'0' must lift to its u8 value 48");
    assert_eq!(sort, "u8", "byte literal carries u8 sort");
}

#[test]
fn distinct_byte_literals_stay_distinct_no_coalesce() {
    // Break-the-twin: `b'0'` (48) and `b'1'` (49) must lift to DISTINCT constants so
    // the conjoined obligation is genuinely refutable (a single receiver cannot equal
    // both) — not silently coalesced into a vacuously-satisfiable claim.
    let src = r#"
fn byte_val() -> u8 { 48 }

#[test]
fn byte_contradiction() {
    assert_eq!(byte_val(), b'0');
    assert_eq!(byte_val(), b'1');
}
"#;
    let out = lift_file(&parse(src), "tests/byte_contradiction.rs");
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 2, "two distinct byte-literal atoms");
    let (v0, _) = byte_literal_eq_atom_value_and_sort(&operands[0]);
    let (v1, _) = byte_literal_eq_atom_value_and_sort(&operands[1]);
    assert_eq!(v0, 48);
    assert_eq!(v1, 49);
    assert_ne!(v0, v1, "distinct byte literals must not coalesce");
}

// `assert_eq!(left, &mut [1, 2, 3])`: slice/array PartialEq is BY VALUE, so the
// `&mut [literal]` RHS denotes the pinned array value, not a pointer. It lifts as
// `ref_mut(<array value>)` -- the SAME immutable-value class as `&mut <scalar lit>`.
// Distinct array literals must stay distinct (no false coalesce); a `&mut <variable>`
// must STILL stay residual (the pointer-identity guard, asserted elsewhere).
fn ref_mut_array_rhs_var_name(formula: &Formula) -> String {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[1].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "ref_mut", "RHS must be a ref_mut term");
                    assert_eq!(args.len(), 1);
                    match args[0].as_ref() {
                        Term::Var { name } => name.clone(),
                        other => panic!("expected array-value var inside ref_mut, got {other:?}"),
                    }
                }
                other => panic!("expected ref_mut ctor rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn mut_ref_to_array_literal_lifts_as_ref_mut_of_pinned_value() {
    // Positive: the pinned array value rides inside ref_mut (sugar in, constraint
    // out). `make_slice()` is the EUF call-result LHS.
    let src = r#"
fn make_slice() -> &'static mut [i32] { todo!() }

#[test]
fn slice_is_123() {
    assert_eq!(make_slice(), &mut [1, 2, 3]);
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    let name = ref_mut_array_rhs_var_name(&operands[0]);
    assert_eq!(
        name, "literal:Array(i:1,i:2,i:3)",
        "the array literal value must be pinned by content"
    );
}

#[test]
fn distinct_mut_ref_array_literals_stay_distinct_no_coalesce() {
    // Break-the-twin: `&mut [1,2,3]` and `&mut [4,5,6]` must lift to DISTINCT pinned
    // values so the conjoined obligation is genuinely refutable -- a single receiver
    // cannot equal both. If they coalesced, a false assert would discharge vacuously
    // (the masked contradiction the consistency sweep cannot catch).
    let src = r#"
fn make_slice() -> &'static mut [i32] { todo!() }

#[test]
fn slice_contradiction() {
    assert_eq!(make_slice(), &mut [1, 2, 3]);
    assert_eq!(make_slice(), &mut [4, 5, 6]);
}
"#;
    let out = lift_file(&parse(src), "tests/slice_contradiction.rs");
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 2, "two distinct array-literal atoms");
    let n0 = ref_mut_array_rhs_var_name(&operands[0]);
    let n1 = ref_mut_array_rhs_var_name(&operands[1]);
    assert_eq!(n0, "literal:Array(i:1,i:2,i:3)");
    assert_eq!(n1, "literal:Array(i:4,i:5,i:6)");
    assert_ne!(n0, n1, "distinct array literals must not coalesce");
}

#[test]
fn transparent_assert_helper_reduces_to_assert_eq_base_lifter() {
    let src = r#"
fn assert_same(actual: i32, expected: i32) {
    assert_eq!(actual, expected);
}

fn make_value() -> i32 { 6 }

#[test]
fn scalar_is_six() {
    assert_same(make_value(), 6);
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "src/lib.rs::scalar_is_six::make_value#euf#c:callresult_make_value_a0()::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_eq_atom(&operands[0], 6);
}

#[test]
fn transparent_assert_helper_preserves_same_subject_contradiction() {
    let src = r#"
fn assert_same(actual: i32, expected: i32) {
    assert_eq!(actual, expected);
}

fn make_value() -> i32 { 6 }

#[test]
fn scalar_contradiction() {
    assert_same(make_value(), 6);
    assert_same(make_value(), 7);
}
"#;
    let out = lift_file(&parse(src), "tests/contradiction.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "tests/contradiction.rs::scalar_contradiction::make_value#euf#c:callresult_make_value_a0()::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    assert_eq_atom(&operands[0], 6);
    assert_eq_atom(&operands[1], 7);
}

#[test]
fn transparent_assert_helper_keys_subjects_to_callsite_actuals_not_helper_params() {
    let src = r#"
fn assert_same(actual: i32, expected: i32) {
    assert_eq!(actual, expected);
}

fn first_value() -> i32 { 6 }
fn second_value() -> i32 { 7 }

#[test]
fn distinct_calls() {
    assert_same(first_value(), 6);
    assert_same(second_value(), 7);
}
"#;
    let out = lift_file(&parse(src), "tests/helpers.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 2, "decls: {:?}", out.decls);
    assert_eq!(
        out.decls[0].name,
        "tests/helpers.rs::distinct_calls::first_value#euf#c:callresult_first_value_a0()::assertion"
    );
    assert_eq!(
        out.decls[1].name,
        "tests/helpers.rs::distinct_calls::second_value#euf#c:callresult_second_value_a0()::assertion"
    );
    assert_eq_atom(&inv_operands(&out.decls[0])[0], 6);
    assert_eq_atom(&inv_operands(&out.decls[1])[0], 7);
}

#[test]
fn lifts_assert_binary_equality() {
    let src = r#"
fn make_value() -> i32 { 6 }

#[test]
fn scalar_assert_binary() {
    assert!(make_value() == 6);
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(
        out.decls[0].name,
        "src/lib.rs::scalar_assert_binary::make_value#euf#c:callresult_make_value_a0()::assertion"
    );
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    assert_eq_atom(&operands[0], 6);
}

#[test]
fn direct_call_result_assertion_uses_euf_callsite_key_from_rhs() {
    let src = r#"
fn decoded_len_estimate(n: usize) -> usize { n - 1 }

#[test]
fn decoded_len_est() {
    assert_eq!(3, decoded_len_estimate(4));
}
"#;
    let out = lift_file(&parse(src), "src/decode.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "src/decode.rs::decoded_len_est::decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_int_call_eq_atom(&operands[0], 3, "call:decoded_len_estimate", 4);
}

#[test]
fn direct_generic_call_result_assertions_include_type_args_in_euf_key() {
    let src = r#"
fn size_of<T>() -> usize { 1 }

#[test]
fn generic_identity_is_distinct() {
    assert_eq!(size_of::<u8>(), 1);
    assert_eq!(size_of::<u16>(), 2);
}
"#;
    let out = lift_file(&parse(src), "tests/mem.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 2);

    let names = out
        .decls
        .iter()
        .map(|decl| decl.name.as_str())
        .collect::<Vec<_>>();
    assert_eq!(
        names,
        vec![
            "size_of::<u8>#euf#c:callresult_size_of___u8__a0()::assertion",
            "size_of::<u16>#euf#c:callresult_size_of___u16__a0()::assertion",
        ]
    );

    let first = inv_operands(&out.decls[0]);
    assert_eq!(first.len(), 1);
    assert_int_zero_arg_call_eq_atom(&first[0], "call:size_of::<u8>", 1);
    let second = inv_operands(&out.decls[1]);
    assert_eq!(second.len(), 1);
    assert_int_zero_arg_call_eq_atom(&second[0], "call:size_of::<u16>", 2);
}

#[test]
fn cfg_gated_test_functions_lift_only_when_active_for_explicit_target_cfg() {
    let src = r#"
fn size_of<T>() -> usize { 1 }

#[test]
#[cfg(target_pointer_width = "32")]
fn size_of_32() {
    assert_eq!(size_of::<usize>(), 4);
}

#[test]
#[cfg(target_pointer_width = "64")]
fn size_of_64() {
    assert_eq!(size_of::<usize>(), 8);
}

#[test]
#[cfg(all(unix, target_pointer_width = "64"))]
fn size_of_unix_64() {
    assert_eq!(size_of::<*const usize>(), 8);
}

#[test]
#[cfg(any(windows, target_pointer_width = "32"))]
fn size_of_inactive_any() {
    assert_eq!(size_of::<*const usize>(), 4);
}
"#;
    let cfg = TargetCfg::from_rustc_cfg_facts([
        "unix",
        "target_pointer_width=\"64\"",
        "target_arch=\"x86_64\"",
    ])
    .expect("target cfg parses");
    let out = lift_file_with_options(
        &parse(src),
        "tests/mem.rs",
        &LiftOptions::for_target_cfg(cfg),
    );

    assert_eq!(out.seen, 2);
    assert_eq!(out.lifted, 2, "warnings: {:?}", out.warnings);
    let names = out
        .decls
        .iter()
        .map(|decl| decl.name.as_str())
        .collect::<Vec<_>>();
    assert_eq!(
        names,
        vec![
            "size_of::<usize>#euf#c:callresult_size_of___usize__a0()::assertion",
            "size_of::<* const usize>#euf#c:callresult_size_of_____const_usize__a0()::assertion",
        ]
    );
    assert_int_zero_arg_call_eq_atom(&inv_operands(&out.decls[0])[0], "call:size_of::<usize>", 8);
    assert_int_zero_arg_call_eq_atom(
        &inv_operands(&out.decls[1])[0],
        "call:size_of::<* const usize>",
        8,
    );
    assert!(
        out.warnings
            .iter()
            .any(|w| w.reason.contains("inactive cfg") && w.item_name.ends_with("size_of_32")),
        "inactive cfg residual must be named: {:?}",
        out.warnings
    );
    assert!(
        out.warnings
            .iter()
            .any(|w| w.reason.contains("inactive cfg")
                && w.item_name.ends_with("size_of_inactive_any")),
        "inactive any cfg residual must be named: {:?}",
        out.warnings
    );
}

#[test]
fn cfg_gated_assertions_are_skipped_without_explicit_target_cfg() {
    let src = r#"
fn size_of<T>() -> usize { 1 }

#[test]
#[cfg(target_pointer_width = "64")]
fn size_of_64() {
    assert_eq!(size_of::<usize>(), 8);
}
"#;
    let out = lift_file(&parse(src), "tests/mem.rs");

    assert_eq!(out.seen, 0);
    assert_eq!(out.lifted, 0);
    assert!(
        out.decls.is_empty(),
        "cfg-gated claim requires explicit target cfg"
    );
    assert_eq!(out.warnings.len(), 1);
    assert!(out.warnings[0].reason.contains("ambiguous cfg"));
    assert!(out.warnings[0].reason.contains("target_pointer_width"));
}

#[test]
fn cfg_test_modules_lift_without_explicit_target_cfg() {
    let src = r#"
fn make_value() -> i32 { 6 }

#[cfg(test)]
mod tests {
    use super::make_value;

    #[test]
    fn scalar_is_six() {
        assert_eq!(make_value(), 6);
    }
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");

    assert_eq!(out.seen, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name,
        "src/lib.rs::tests::scalar_is_six::make_value#euf#c:callresult_make_value_a0()::assertion"
    );
}

#[test]
fn cfg_test_modules_are_active_without_explicit_target_cfg() {
    let src = r#"
fn decoded_len_estimate(_: usize) -> usize { 3 }

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decoded_len_est() {
        assert_eq!(3, decoded_len_estimate(4));
    }
}
"#;
    let out = lift_file(&parse(src), "src/decode.rs");

    assert_eq!(out.seen, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name,
        "src/decode.rs::tests::decoded_len_est::decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion"
    );
    assert_int_call_eq_atom(
        &inv_operands(&out.decls[0])[0],
        3,
        "call:decoded_len_estimate",
        4,
    );
}

#[test]
fn cfg_gated_statement_assertions_lift_only_active_assertions() {
    let src = r#"
fn value() -> i32 { 1 }

#[test]
fn cfg_statements() {
    #[cfg(target_pointer_width = "32")]
    assert_eq!(value(), 4);

    #[cfg(target_pointer_width = "64")]
    assert_eq!(value(), 8);

    #[cfg(all(unix, not(target_pointer_width = "32")))]
    assert_eq!(value(), 9);

    #[cfg(target_feature = "definitely-not-a-real-feature")]
    assert_eq!(value(), 99);
}
"#;
    let cfg = TargetCfg::from_rustc_cfg_facts(["unix", "target_pointer_width=\"64\""])
        .expect("target cfg parses");
    let out = lift_file_with_options(
        &parse(src),
        "tests/cfg.rs",
        &LiftOptions::for_target_cfg(cfg),
    );

    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 2);
    assert_eq_atom(&operands[0], 8);
    assert_eq_atom(&operands[1], 9);
    assert!(
        out.warnings
            .iter()
            .any(|w| w.reason.contains("inactive cfg") && w.reason.contains("32")),
        "inactive statement cfg residual must be named: {:?}",
        out.warnings
    );
    assert!(
        out.warnings
            .iter()
            .any(|w| w.reason.contains("inactive cfg")
                && w.reason.contains("definitely-not-a-real-feature")),
        "inactive target_feature statement cfg residual must be named: {:?}",
        out.warnings
    );
}

#[test]
fn type_id_of_and_dyn_any_receiver_lift_as_keyed_reflection_terms() {
    let src = r#"
use core::any::TypeId;

#[test]
fn any_fixed_vec_type_id() {
    let test = [0_u8; 3];
    assert_eq!(TypeId::of::<[u8; 3]>(), (&test as &dyn core::any::Any).type_id());
    assert!(TypeId::of::<[u8; 4]>() != (&test as &dyn core::any::Any).type_id());
}
"#;
    let out = lift_file(&parse(src), "coretests/tests/any.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert!(
        out.warnings.is_empty(),
        "unexpected lift warnings: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(decl.name, "coretests/tests/any.rs::any_fixed_vec_type_id");
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    assert_type_id_cmp_atom(&operands[0], "=", "[u8;3]", "&dyn core::any::Any", "test");
    assert_type_id_cmp_atom(
        &operands[1],
        "\u{2260}",
        "[u8;4]",
        "&dyn core::any::Any",
        "test",
    );
}

#[test]
fn any_is_positive_and_negative_share_the_same_call_result_key() {
    let src = r#"
use core::any::*;

#[test]
fn any_referenced() {
    let a = &5 as &dyn Any;
    assert!(a.is::<i32>());
    assert!(!a.is::<i32>());
}
"#;
    let out = lift_file(&parse(src), "coretests/tests/any.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert!(
        out.warnings.is_empty(),
        "unexpected lift warnings: {:?}",
        out.warnings
    );
    assert_eq!(
        out.decls.len(),
        1,
        "positive and negated Any::is on the same receiver/type must coalesce"
    );

    let decl = &out.decls[0];
    assert!(
        decl.name.starts_with("method:is::<i32>#euf#"),
        "Any::is should be keyed as a method call result, got {}",
        decl.name
    );
    assert!(
        decl.name.contains("tests/any.rs::any_referenced::a"),
        "Any::is receiver should keep test-local identity in key, got {}",
        decl.name
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    let rendered = format!("{operands:?}");
    assert!(
        rendered.contains("Bool(true)") && rendered.contains("Bool(false)"),
        "expected positive and negated Any::is atoms in one row, got {rendered}"
    );
}

#[test]
fn direct_method_call_result_string_assertion_uses_euf_callsite_key() {
    let src = r#"
struct Name;

impl Name {
    fn to_string(&self) -> String { "hello".to_owned() }
}

#[test]
fn string_call_result() {
    let a = Name;
    assert_eq!(a.to_string(), "hello");
}
"#;
    let out = lift_file(&parse(src), "tests/fmt.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "method:to_string#euf#c:callresult_method_to_string_a1(v:tests/fmt.rs::string_call_result::a)::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_string_call_eq_atom(&operands[0], "method:to_string", "hello");
}

#[test]
fn direct_method_call_result_float_assertion_uses_euf_callsite_key() {
    let src = r#"
struct Duration;

impl Duration {
    fn div_duration_f64(&self, _other: Duration) -> f64 { 2.0 }
}

#[test]
fn float_call_result() {
    let d = Duration;
    assert_eq!(d.div_duration_f64(Duration), 2.0);
}
"#;
    let out = lift_file(&parse(src), "tests/time.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "method:div_duration_f64#euf#c:callresult_method_div_duration_f64_a2(v:tests/time.rs::float_call_result::d,v:tests/time.rs::float_call_result::Duration)::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_real_call_eq_atom(&operands[0], "method:div_duration_f64", "2.0");
}

#[test]
fn mixed_supported_and_refinement_assertions_lift_supported_rows() {
    let src = r#"
struct Duration;

impl Duration {
    fn div_duration_f64(&self, _other: Duration) -> f64 { 2.0 }
}

#[test]
fn float_mixed_refinement_gap() {
    let d = Duration;
    assert_eq!(d.div_duration_f64(Duration), 2.0);
    assert!(d.div_duration_f64(Duration).is_nan());
    assert!(!d.div_duration_f64(Duration).is_nan());
}
"#;
    let out = lift_file(&parse(src), "tests/time.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(
        out.warnings.len(),
        0,
        "width-known NaN refinements over method float results are liftable"
    );
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "method:div_duration_f64#euf#c:callresult_method_div_duration_f64_a2(v:tests/time.rs::float_mixed_refinement_gap::d,v:tests/time.rs::float_mixed_refinement_gap::Duration)::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 3);
    assert_real_call_eq_atom(&operands[0], "method:div_duration_f64", "2.0");
    assert_float_refinement_atom(&operands[1], "float.f64.is_nan", "method:div_duration_f64");
    match operands[2].as_ref() {
        Formula::Connective { kind, operands } if kind == "not" => {
            assert_eq!(operands.len(), 1);
            assert_float_refinement_atom(
                operands[0].as_ref(),
                "float.f64.is_nan",
                "method:div_duration_f64",
            );
        }
        other => panic!("expected negated float refinement atom, got {other:?}"),
    }
}

#[test]
fn exponent_float_literals_normalize_to_exact_real_constants() {
    let src = r#"
fn value() -> f64 { 0.001 }

#[test]
fn exponent_float_literal() {
    assert_eq!(value(), 1e-3);
    assert_eq!(value(), 12.50e+2);
}
"#;
    let out = lift_file(&parse(src), "tests/num/floats.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(decl.name, "tests/num/floats.rs::exponent_float_literal::value#euf#c:callresult_value_a0()::assertion");
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    assert_real_call_eq_atom(&operands[0], "call:value", "0.001");
    assert_real_call_eq_atom(&operands[1], "call:value", "1250");
}

#[test]
fn width_known_infinite_refinement_lifts_as_predicate_atom() {
    let src = r#"
struct Duration;

impl Duration {
    fn div_duration_f32(&self, _other: Duration) -> f32 { f32::INFINITY }
}

#[test]
fn float_infinite_refinement() {
    let d = Duration;
    assert!(d.div_duration_f32(Duration).is_infinite());
}
"#;
    let out = lift_file(&parse(src), "tests/time.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "method:div_duration_f32#euf#c:callresult_method_div_duration_f32_a2(v:tests/time.rs::float_infinite_refinement::d,v:tests/time.rs::float_infinite_refinement::Duration)::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_float_refinement_atom(
        &operands[0],
        "float.f32.is_infinite",
        "method:div_duration_f32",
    );
}

#[test]
fn typed_float_locals_lift_sign_and_normal_refinements_as_predicate_atoms() {
    let src = r#"
#[test]
fn typed_float_refinements() {
    let max: f64 = f32::MAX.into();
    assert!(max.is_normal());
    assert!(max.is_sign_positive());
    assert!(!max.is_sign_negative());
}
"#;
    let out = lift_file(&parse(src), "tests/num/mod.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(decl.name, "tests/num/mod.rs::typed_float_refinements");
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 3);
    assert_float_refinement_var_atom(&operands[0], "float.f64.is_normal", "max");
    assert_float_refinement_var_atom(&operands[1], "float.f64.is_sign_positive", "max");
    match operands[2].as_ref() {
        Formula::Connective { kind, operands } if kind == "not" => {
            assert_eq!(operands.len(), 1);
            assert_float_refinement_var_atom(
                operands[0].as_ref(),
                "float.f64.is_sign_negative",
                "max",
            );
        }
        other => panic!("expected negated float sign refinement atom, got {other:?}"),
    }
}

#[test]
fn typed_float_width_scope_follows_statement_order_across_shadowing() {
    let src = r#"
#[test]
fn typed_float_shadowing() {
    let value: f64 = 1.0;
    assert!(value.is_sign_positive());
    let value: f32 = 1.0;
    assert!(value.is_sign_positive());
}
"#;
    let out = lift_file(&parse(src), "tests/num/mod.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(decl.name, "tests/num/mod.rs::typed_float_shadowing");
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    assert_float_refinement_var_atom(&operands[0], "float.f64.is_sign_positive", "value@def1");
    assert_float_refinement_var_atom(&operands[1], "float.f32.is_sign_positive", "value@def2");
}

#[test]
fn parse_unwrap_float_receiver_recovers_turbofish_width_for_nan_predicate() {
    let src = r#"
#[test]
fn parsed_nan_refinement() {
    assert!("NaN".parse::<f32>().unwrap().is_nan());
    assert!("-NaN".parse::<f64>().unwrap().is_nan());
}
"#;
    let out = lift_file(&parse(src), "tests/num/dec2flt/mod.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 2);

    let f32_operands = inv_operands(&out.decls[0]);
    assert_eq!(f32_operands.len(), 1);
    assert_float_refinement_atom(&f32_operands[0], "float.f32.is_nan", "method:unwrap");

    let f64_operands = inv_operands(&out.decls[1]);
    assert_eq!(f64_operands.len(), 1);
    assert_float_refinement_atom(&f64_operands[0], "float.f64.is_nan", "method:unwrap");
}

#[test]
fn method_call_result_euf_keys_scope_local_receivers_to_avoid_false_collisions() {
    let src = r#"
struct Cursor;

impl Cursor {
    fn get_ref(&self) -> Vec<u8> { Vec::new() }
}

#[test]
fn first_local_cursor() {
    let c = Cursor;
    assert_eq!(c.get_ref().len(), 1);
}

#[test]
fn second_local_cursor() {
    let c = Cursor;
    assert_eq!(c.get_ref().len(), 2);
}
"#;
    let out = lift_file(&parse(src), "src/engine/tests.rs");
    assert_eq!(out.seen, 2);
    assert_eq!(out.lifted, 2, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 2);

    let names = out
        .decls
        .iter()
        .map(|decl| decl.name.as_str())
        .collect::<Vec<_>>();
    assert_eq!(
        names,
        vec![
            "method:len#euf#c:callresult_method_len_a1(c:method:get_ref(v:src/engine/tests.rs::first_local_cursor::c))::assertion",
            "method:len#euf#c:callresult_method_len_a1(c:method:get_ref(v:src/engine/tests.rs::second_local_cursor::c))::assertion",
        ]
    );
}

#[test]
fn method_chain_predicate_assertion_uses_euf_callsite_key() {
    let src = r#"
struct Layout;
struct ResultLike;

impl Layout {
    fn align_to(&self, _align: usize) -> ResultLike { ResultLike }
}

impl ResultLike {
    fn is_err(&self) -> bool { true }
}

#[test]
fn layout_errors() {
    let layout = Layout;
    assert!(layout.align_to(3).is_err());
}
"#;
    let out = lift_file(&parse(src), "tests/alloc.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "method:is_err#euf#c:callresult_method_is_err_a1(c:method:align_to(v:tests/alloc.rs::layout_errors::layout,i:3))::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, "method:is_err"),
                other => panic!("expected method-chain predicate call, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Bool(value),
                    ..
                } => assert!(*value),
                other => panic!("expected bool true rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn reassigned_receiver_versions_method_chain_subjects_to_avoid_false_coalescing() {
    let src = r#"
#[test]
fn range_rebinds() {
    let r = 1u32..5;
    assert!(!r.contains(&0));

    let r = 0u32..=u32::MAX;
    assert!(r.contains(&0));
}
"#;
    let out = lift_file(&parse(src), "tests/ops.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 2);

    let names = out
        .decls
        .iter()
        .map(|decl| decl.name.as_str())
        .collect::<Vec<_>>();
    assert_eq!(
        names,
        vec![
            "method:contains#euf#c:callresult_method_contains_a2(v:tests/ops.rs::range_rebinds::r@def1,c:ref(i:0))::assertion",
            "method:contains#euf#c:callresult_method_contains_a2(v:tests/ops.rs::range_rebinds::r@def2,c:ref(i:0))::assertion",
        ]
    );
}

#[test]
fn post_reassignment_claims_within_one_receiver_version_still_coalesce() {
    let src = r#"
#[test]
fn post_rebind_same_version() {
    let mut r = 1u32..5;
    r = 10u32..20;

    assert!(r.contains(&11));
    assert!(r.contains(&11));
}
"#;
    let out = lift_file(&parse(src), "tests/ops.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name,
        "method:contains#euf#c:callresult_method_contains_a2(v:tests/ops.rs::post_rebind_same_version::r@def2,c:ref(i:11))::assertion"
    );
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 2);
}

#[test]
fn standalone_receiver_mutation_boundary_versions_later_method_chain_subject() {
    let src = r#"
#[test]
fn inclusive_range_after_next() {
    let mut r = 1u32..=1;
    r.next().unwrap();

    assert!(!r.contains(&1));
}
"#;
    let out = lift_file(&parse(src), "tests/ops.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name,
        "method:contains#euf#c:callresult_method_contains_a2(v:tests/ops.rs::inclusive_range_after_next::r@def2,c:ref(i:1))::assertion"
    );
}

#[test]
fn conditional_receiver_reassignment_is_ambiguous_and_skipped() {
    let src = r#"
fn coin() -> bool { true }

#[test]
fn conditional_rebind() {
    let mut r = 1u32..5;
    if coin() {
        r = 10u32..20;
    }

    assert!(r.contains(&1));
}
"#;
    let out = lift_file(&parse(src), "tests/ops.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0, "decls: {:?}", out.decls);
    assert!(out.decls.is_empty(), "decls: {:?}", out.decls);
    assert!(
        out.warnings.iter().any(|warning| {
            warning
                .reason
                .contains("ambiguous temporal identity for receiver `r`; skipped assertion")
        }),
        "warnings: {:?}",
        out.warnings
    );
}

#[test]
fn loop_receiver_mutation_is_ambiguous_and_skipped() {
    let src = r#"
#[test]
fn loop_rebind() {
    let mut r = 1u32..=1;
    for _ in 0..1 {
        r.next().unwrap();
    }

    assert!(r.contains(&1));
}
"#;
    let out = lift_file(&parse(src), "tests/ops.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0, "decls: {:?}", out.decls);
    assert!(out.decls.is_empty(), "decls: {:?}", out.decls);
    assert!(
        out.warnings.iter().any(|warning| {
            warning
                .reason
                .contains("ambiguous temporal identity for receiver `r`; skipped assertion")
        }),
        "warnings: {:?}",
        out.warnings
    );
}

#[test]
fn alias_receiver_identity_is_ambiguous_and_skipped() {
    let src = r#"
#[test]
fn alias_rebind() {
    let mut r = 1u32..=1;
    let alias = &mut r;
    alias.next().unwrap();

    assert!(r.contains(&1));
}
"#;
    let out = lift_file(&parse(src), "tests/ops.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0, "decls: {:?}", out.decls);
    assert!(out.decls.is_empty(), "decls: {:?}", out.decls);
    assert!(
        out.warnings.iter().any(|warning| {
            warning
                .reason
                .contains("ambiguous temporal identity for receiver `r`; skipped assertion")
        }),
        "warnings: {:?}",
        out.warnings
    );
}

#[test]
fn method_chain_predicate_range_contains_keys_bounds_and_reference_arg() {
    let src = r#"
#[test]
fn test_range_contains() {
    assert!(!(1u32..5).contains(&0u32));
    assert!((1u32..5).contains(&1u32));
}
"#;
    let out = lift_file(&parse(src), "tests/ops.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 2);

    let names = out
        .decls
        .iter()
        .map(|decl| decl.name.as_str())
        .collect::<Vec<_>>();
    assert_eq!(
        names,
        vec![
            "method:contains#euf#c:callresult_method_contains_a2(c:range(i:1:u32,i:5),c:ref(i:0:u32))::assertion",
            "method:contains#euf#c:callresult_method_contains_a2(c:range(i:1:u32,i:5),c:ref(i:1:u32))::assertion",
        ]
    );
    let first = inv_operands(&out.decls[0]);
    assert_eq!(first.len(), 1);
    match first[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Bool(value),
                    ..
                } => assert!(!*value),
                other => panic!("expected bool false rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn method_call_result_with_bitwise_rhs_uses_euf_callsite_key() {
    let src = r#"
struct AtomicLike;
struct SeqCst;

impl AtomicLike {
    fn load(&self, _ordering: SeqCst) -> usize { 0 }
}

#[test]
fn uint_and() {
    let x = AtomicLike;
    assert_eq!(x.load(SeqCst), 0xf731 & 0x137f);
}
"#;
    let out = lift_file(&parse(src), "tests/atomic.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "method:load#euf#c:callresult_method_load_a2(v:tests/atomic.rs::uint_and::x,v:tests/atomic.rs::uint_and::SeqCst)::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_method_call_eq_compound_rhs(&operands[0], "method:load", "bit-and", 0xf731, 0x137f);
}

#[test]
fn constructor_call_expected_value_stays_location_keyed() {
    let src = r#"
struct AtomicLike;
struct SeqCst;

impl AtomicLike {
    fn compare_exchange(
        &self,
        _current: bool,
        _new: bool,
        _success: SeqCst,
        _failure: SeqCst,
    ) -> Result<bool, bool> {
        Ok(false)
    }
}

#[test]
fn bool_compare_exchange() {
    let a = AtomicLike;
    assert_eq!(a.compare_exchange(false, true, SeqCst, SeqCst), Ok(false));
}
"#;
    let out = lift_file(&parse(src), "tests/atomic.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(out.decls[0].name, "tests/atomic.rs::bool_compare_exchange");
    match inv_operands(&out.decls[0])[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "call:eq:Ok");
                    assert_eq!(args.len(), 2);
                    match args[0].as_ref() {
                        Term::Ctor { name, .. } => assert_eq!(name, "method:compare_exchange"),
                        other => panic!("expected compare_exchange lhs, got {other:?}"),
                    }
                    match args[1].as_ref() {
                        Term::Ctor { name, args } => {
                            assert_eq!(name, "call:Ok");
                            assert_eq!(args.len(), 1);
                            match args[0].as_ref() {
                                Term::Const {
                                    value: ConstValue::Bool(value),
                                    ..
                                } => assert!(!*value),
                                other => panic!("expected bool constructor arg, got {other:?}"),
                            }
                        }
                        other => panic!("expected Ok constructor rhs, got {other:?}"),
                    }
                }
                other => panic!("expected operator call lhs, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Bool(true));
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn nullary_option_constructor_expected_value_uses_operator_dispatch() {
    // Vendor shape: rust-src library/coretests/tests/iter/range.rs::test_range_nth.
    // `None` is the nullary Option constructor, not a local variable. Keeping it
    // as a constructor lets the user-overridable equality dispatch stay
    // explicit and location-keyed instead of pretending this is scalar `=`.
    let src = r#"
#[test]
fn test_range_nth() {
    assert_eq!((10..15).nth(5), None);
}
"#;
    let out = lift_file(&parse(src), "tests/iter/range.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(out.decls[0].name, "tests/iter/range.rs::test_range_nth");

    match inv_operands(&out.decls[0])[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "call:eq:None");
                    assert_eq!(args.len(), 2);
                    match args[0].as_ref() {
                        Term::Ctor { name, .. } => assert_eq!(name, "method:nth"),
                        other => panic!("expected nth lhs, got {other:?}"),
                    }
                    match args[1].as_ref() {
                        Term::Ctor { name, args } => {
                            assert_eq!(name, "call:None");
                            assert!(args.is_empty());
                        }
                        other => panic!("expected None constructor rhs, got {other:?}"),
                    }
                }
                other => panic!("expected operator call lhs, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Bool(true));
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn option_test_and_constructor_rows_stay_location_keyed() {
    // Vendor shape: rust-src library/coretests/tests/option.rs::test_and.
    // The inputs are immutable Option values; the equality itself is still
    // Option::eq, so this is one location-keyed operator-dispatch contract.
    let src = r#"
use core::option::*;

#[test]
fn test_and() {
    let x: Option<isize> = Some(1);
    assert_eq!(x.and(Some(2)), Some(2));
    assert_eq!(x.and(None::<isize>), None);

    let x: Option<isize> = None;
    assert_eq!(x.and(Some(2)), None);
    assert_eq!(x.and(None::<isize>), None);

    const FOO: Option<isize> = Some(1);
    const A: Option<isize> = FOO.and(Some(2));
    const B: Option<isize> = FOO.and(None);
    assert_eq!(A, Some(2));
    assert_eq!(B, None);

    const BAR: Option<isize> = None;
    const C: Option<isize> = BAR.and(Some(2));
    const D: Option<isize> = BAR.and(None);
    assert_eq!(C, None);
    assert_eq!(D, None);
}
"#;
    let out = lift_file(&parse(src), "tests/option.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(out.decls[0].name, "tests/option.rs::test_and");

    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 8);
    for operand in operands {
        match operand.as_ref() {
            Formula::Atomic { name, args } => {
                assert_eq!(name, "=");
                assert_eq!(args.len(), 2);
                match args[0].as_ref() {
                    Term::Ctor { name, args } => {
                        assert!(
                            name == "call:eq:Some" || name == "call:eq:None",
                            "unexpected operator-dispatch call: {name}"
                        );
                        assert_eq!(args.len(), 2);
                    }
                    other => panic!("expected operator-dispatch lhs, got {other:?}"),
                }
                assert_scalar_const(&args[1], ExpectedScalar::Bool(true));
            }
            other => panic!("expected equality atom, got {other:?}"),
        }
    }
}

#[test]
fn constructor_operator_comparisons_lift_as_uninterpreted_operator_results() {
    let src = r#"
struct Int(i32);
struct RevInt(i32);
struct Fool(bool);

#[test]
fn cmp_default() {
    assert!(Int(2) > Int(1));
    assert!(Int(2) >= Int(1));
    assert!(Int(1) >= Int(1));
    assert!(Int(1) < Int(2));
    assert!(Int(1) <= Int(2));
    assert!(Int(1) <= Int(1));
    assert!(RevInt(2) < RevInt(1));
    assert!(RevInt(2) <= RevInt(1));
    assert!(RevInt(1) <= RevInt(1));
    assert!(RevInt(1) > RevInt(2));
    assert!(RevInt(1) >= RevInt(2));
    assert!(RevInt(1) >= RevInt(1));
    assert_eq!(Fool(true), Fool(false));
    assert!(Fool(true) != Fool(true));
    assert!(Fool(false) != Fool(false));
    assert_eq!(Fool(false), Fool(true));
}
"#;
    let out = lift_file(&parse(src), "tests/cmp.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(out.decls[0].name, "tests/cmp.rs::cmp_default");

    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 16);
    assert_operator_bool_atom(
        &operands[0],
        "call:gt:Int",
        &[
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(2)),
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(1)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[1],
        "call:ge:Int",
        &[
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(2)),
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(1)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[2],
        "call:ge:Int",
        &[
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(1)),
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(1)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[3],
        "call:lt:Int",
        &[
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(1)),
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(2)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[4],
        "call:le:Int",
        &[
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(1)),
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(2)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[5],
        "call:le:Int",
        &[
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(1)),
            ExpectedOperatorArg::Constructor("call:Int", ExpectedScalar::Int(1)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[6],
        "call:lt:RevInt",
        &[
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(2)),
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(1)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[7],
        "call:le:RevInt",
        &[
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(2)),
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(1)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[8],
        "call:le:RevInt",
        &[
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(1)),
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(1)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[9],
        "call:gt:RevInt",
        &[
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(1)),
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(2)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[10],
        "call:ge:RevInt",
        &[
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(1)),
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(2)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[11],
        "call:ge:RevInt",
        &[
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(1)),
            ExpectedOperatorArg::Constructor("call:RevInt", ExpectedScalar::Int(1)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[12],
        "call:eq:Fool",
        &[
            ExpectedOperatorArg::Constructor("call:Fool", ExpectedScalar::Bool(true)),
            ExpectedOperatorArg::Constructor("call:Fool", ExpectedScalar::Bool(false)),
        ],
        true,
    );
    assert_operator_bool_atom(
        &operands[13],
        "call:eq:Fool",
        &[
            ExpectedOperatorArg::Constructor("call:Fool", ExpectedScalar::Bool(true)),
            ExpectedOperatorArg::Constructor("call:Fool", ExpectedScalar::Bool(true)),
        ],
        false,
    );
    assert_operator_bool_atom(
        &operands[14],
        "call:eq:Fool",
        &[
            ExpectedOperatorArg::Constructor("call:Fool", ExpectedScalar::Bool(false)),
            ExpectedOperatorArg::Constructor("call:Fool", ExpectedScalar::Bool(false)),
        ],
        false,
    );
    assert_operator_bool_atom(
        &operands[15],
        "call:eq:Fool",
        &[
            ExpectedOperatorArg::Constructor("call:Fool", ExpectedScalar::Bool(false)),
            ExpectedOperatorArg::Constructor("call:Fool", ExpectedScalar::Bool(true)),
        ],
        true,
    );
}

#[test]
fn ordinary_call_result_rhs_does_not_become_a_ground_value() {
    let src = r#"
fn left() -> i32 { 1 }
fn right() -> i32 { 1 }

#[test]
fn two_calls() {
    assert_eq!(left(), right());
}
"#;
    let out = lift_file(&parse(src), "tests/calls.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(out.decls[0].name, "tests/calls.rs::two_calls");
}

#[test]
fn literal_array_receiver_method_chain_gets_stable_euf_key() {
    // Vendor shape: rust-src library/coretests/tests/array.rs::iterator_last.
    let src = r#"
#[test]
fn iterator_last_literal_array() {
    assert_eq!(IntoIterator::into_iter([0]).last().unwrap(), 0);
}
"#;
    let out = lift_file(&parse(src), "tests/array.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert!(
        out.warnings.is_empty(),
        "literal array receiver should not leave a residual: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name,
        "method:unwrap#euf#c:callresult_method_unwrap_a1(c:method:last(c:call:IntoIterator::into_iter(v:literal:Array(i:0))))::assertion"
    );
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "method:unwrap");
                    assert_eq!(args.len(), 1);
                    match args[0].as_ref() {
                        Term::Ctor { name, args } => {
                            assert_eq!(name, "method:last");
                            assert_eq!(args.len(), 1);
                            match args[0].as_ref() {
                                Term::Ctor { name, args } => {
                                    assert_eq!(name, "call:IntoIterator::into_iter");
                                    assert_eq!(args.len(), 1);
                                    match args[0].as_ref() {
                                        Term::Var { name } => {
                                            assert_eq!(name, "literal:Array(i:0)");
                                        }
                                        other => {
                                            panic!("expected Array literal identity, got {other:?}")
                                        }
                                    }
                                }
                                other => {
                                    panic!("expected IntoIterator::into_iter term, got {other:?}")
                                }
                            }
                        }
                        other => panic!("expected last method receiver, got {other:?}"),
                    }
                }
                other => panic!("expected unwrap method term, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Int(0));
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn tuple_expected_value_gets_stable_euf_key() {
    // Vendor shape: rust-src library/coretests/tests/iter/sources.rs::test_repeat_take.
    let src = r#"
#[test]
fn repeat_take_size_hint() {
    assert_eq!(repeat(42).take(3).size_hint(), (3, Some(3)));
}
"#;
    let out = lift_file(&parse(src), "tests/iter/sources.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert!(
        out.warnings.is_empty(),
        "tuple expected value should not leave a residual: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name,
        "method:size_hint#euf#c:callresult_method_size_hint_a1(c:method:take(c:call:repeat(i:42),i:3))::assertion"
    );
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "method:size_hint");
                    assert_eq!(args.len(), 1);
                }
                other => panic!("expected size_hint lhs, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Var { name } => {
                    assert_eq!(name, "literal:Tuple(i:3,c:call:Some(i:3))");
                }
                other => panic!("expected Tuple literal identity, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn const_block_wrapped_method_call_result_gets_stable_euf_key() {
    // Vendor shape: rust-src library/coretests/tests/array.rs::const_array_ops.
    let src = r#"
#[test]
fn const_array_ops() {
    const fn doubler(x: usize) -> usize {
        x * 2
    }
    assert_eq!(const { [5, 6, 1, 2].map(doubler) }, [10, 12, 2, 4]);
    assert_eq!(const { std::array::from_fn::<_, 5, _>(doubler) }, [0, 2, 4, 6, 8]);
}
"#;
    let out = lift_file(&parse(src), "tests/array.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert!(
        out.warnings.is_empty(),
        "expression-only const block should not leave a residual: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 2);
    let names = out
        .decls
        .iter()
        .map(|decl| decl.name.as_str())
        .collect::<Vec<_>>();
    assert_eq!(
        names,
        vec![
            "method:map#euf#c:callresult_method_map_a2(v:literal:Array(i:5,i:6,i:1,i:2),v:tests/array.rs::const_array_ops::doubler)::assertion",
            "std::array::from_fn::<_,const:5,_>#euf#c:callresult_std__array__from_fn_____const_5____a1(v:tests/array.rs::const_array_ops::doubler)::assertion",
        ]
    );
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "method:map");
                    assert_eq!(args.len(), 2);
                }
                other => panic!("expected map method term, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Var { name } => {
                    assert_eq!(name, "literal:Array(i:10,i:12,i:2,i:4)");
                }
                other => panic!("expected Array literal identity, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn nested_const_block_arguments_stay_residual_until_keyed_deliberately() {
    let src = r#"
fn apply(_: fn(usize) -> usize) -> usize { 0 }

#[test]
fn nested_const_arg() {
    const fn doubler(x: usize) -> usize {
        x * 2
    }
    assert_eq!(apply(const { doubler }), 0);
}
"#;
    let out = lift_file(&parse(src), "tests/array.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0);
    assert!(out.decls.is_empty());
    assert!(
        out.warnings.iter().any(|warning| warning
            .reason
            .contains("unsupported term `const { doubler }`")),
        "nested const block should stay residual, warnings: {:?}",
        out.warnings
    );
}

#[test]
fn immutable_index_in_pointer_eq_predicate_stays_location_keyed() {
    // Vendor shape: rust-src library/coretests/tests/array.rs::array_from_ref.
    // The index expression is pure identity syntax here, but pointer equality is
    // only claimed at the test locus. Cross-proof pointer identity is not a
    // federated call-result key.
    let src = r#"
#[test]
fn array_from_ref() {
    const VALUE: &&str = &"Hello World!";
    const ARR: &[&str; 1] = core::array::from_ref(VALUE);
    assert!(core::ptr::eq(VALUE, &ARR[0]));
}
"#;
    let out = lift_file(&parse(src), "tests/array.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert!(
        out.warnings.is_empty(),
        "immutable index inside pointer equality should lift: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    assert_eq!(out.decls[0].name, "tests/array.rs::array_from_ref");

    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "call:core::ptr::eq");
                    assert_eq!(args.len(), 2);
                    match args[1].as_ref() {
                        Term::Ctor { name, args } => {
                            assert_eq!(name, "ref");
                            assert_eq!(args.len(), 1);
                            match args[0].as_ref() {
                                Term::Ctor { name, args } => {
                                    assert_eq!(name, "index");
                                    assert_eq!(args.len(), 2);
                                }
                                other => panic!("expected index term, got {other:?}"),
                            }
                        }
                        other => panic!("expected ref indexed argument, got {other:?}"),
                    }
                }
                other => panic!("expected ptr::eq call lhs, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Bool(true));
        }
        other => panic!("expected pointer equality atom, got {other:?}"),
    }
}

#[test]
fn immutable_index_equality_lifts() {
    // An immutable (non-mut) container's index equality lifts as
    // index(xs, 0) == 1.
    let src = r#"
#[test]
fn indexed_value() {
    let xs = [1, 2, 3];
    assert_eq!(xs[0], 1);
}
"#;
    let out = lift_file(&parse(src), "tests/index.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(
        out.lifted, 1,
        "immutable index equality must lift: {:?}",
        out.warnings
    );
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 1);
    match ops[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, "index"),
                other => panic!("expected index ctor lhs, got {other:?}"),
            }
        }
        other => panic!("expected equality, got {other:?}"),
    }
}

#[test]
fn std_ptr_eq_alias_stays_location_keyed_not_euf() {
    let src = r#"
#[test]
fn std_ptr_eq_alias() {
    let x = 1;
    assert!(std::ptr::eq(&x, &x));
}
"#;
    let out = lift_file(&parse(src), "tests/ptr.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name, "tests/ptr.rs::std_ptr_eq_alias",
        "std::ptr::eq must remain location-keyed; cross-proof pointer equality is not federated"
    );

    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, "call:std::ptr::eq"),
                other => panic!("expected std::ptr::eq call, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Bool(true));
        }
        other => panic!("expected pointer equality atom, got {other:?}"),
    }
}

#[test]
fn waker_vtable_pointer_eq_vendor_shape_lifts_location_keyed() {
    // Vendor shape: rust-src library/coretests/tests/waker.rs::test_waker_getters.
    // The casted data() rows and the two ptr::eq(vtable, &WAKER_VTABLE)
    // assertions survive per-assertion under the same location-keyed claim.
    let src = r#"
use std::ptr;
use std::task::{RawWaker, RawWakerVTable, Waker};

#[test]
fn test_waker_getters() {
    let raw_waker = RawWaker::new(ptr::without_provenance_mut(42usize), &WAKER_VTABLE);
    let waker = unsafe { Waker::from_raw(raw_waker) };
    assert_eq!(waker.data() as usize, 42);
    assert!(ptr::eq(waker.vtable(), &WAKER_VTABLE));

    let waker2 = waker.clone();
    assert_eq!(waker2.data() as usize, 43);
    assert!(ptr::eq(waker2.vtable(), &WAKER_VTABLE));
}

static WAKER_VTABLE: RawWakerVTable = RawWakerVTable::new(
    |data| RawWaker::new(ptr::without_provenance_mut(data as usize + 1), &WAKER_VTABLE),
    |_| {},
    |_| {},
    |_| {},
);
"#;
    let out = lift_file(&parse(src), "tests/waker.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(out.decls[0].name, "tests/waker.rs::test_waker_getters");

    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 4);
    let mut cast_values = Vec::new();
    let mut pointer_atoms = 0;
    for operand in operands {
        match operand.as_ref() {
            Formula::Atomic {
                name,
                args: eq_args,
            } => {
                assert_eq!(name, "=");
                match eq_args[0].as_ref() {
                    Term::Ctor {
                        name,
                        args: term_args,
                    } => {
                        if name == "cast:usize" {
                            assert_eq!(term_args.len(), 1);
                            match term_args[0].as_ref() {
                                Term::Ctor { name, args } => {
                                    assert_eq!(name, "method:data");
                                    assert_eq!(args.len(), 1);
                                }
                                other => panic!("expected data method call, got {other:?}"),
                            }
                            match eq_args[1].as_ref() {
                                Term::Const {
                                    value: ConstValue::Int(value),
                                    ..
                                } => cast_values.push(*value),
                                other => panic!("expected cast rhs int, got {other:?}"),
                            }
                        } else {
                            assert_eq!(name, "call:ptr::eq");
                            assert_eq!(term_args.len(), 2);
                            match term_args[0].as_ref() {
                                Term::Ctor { name, args } => {
                                    assert_eq!(name, "method:vtable");
                                    assert_eq!(args.len(), 1);
                                }
                                other => panic!("expected vtable method call, got {other:?}"),
                            }
                            match term_args[1].as_ref() {
                                Term::Ctor { name, args } => {
                                    assert_eq!(name, "ref");
                                    assert_eq!(args.len(), 1);
                                }
                                other => {
                                    panic!("expected reference to WAKER_VTABLE, got {other:?}")
                                }
                            }
                            pointer_atoms += 1;
                        }
                    }
                    other => panic!("expected casted data or ptr::eq call, got {other:?}"),
                }
            }
            other => panic!("expected waker getter atom, got {other:?}"),
        }
    }
    cast_values.sort_unstable();
    assert_eq!(cast_values, vec![42, 43]);
    assert_eq!(pointer_atoms, 2);
}

#[test]
fn scalar_integer_cast_call_result_stays_location_keyed_not_euf() {
    let src = r#"
#[test]
fn cast_result() {
    assert_eq!(source() as usize, 42);
}
"#;
    let out = lift_file(&parse(src), "tests/cast.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name, "tests/cast.rs::cast_result",
        "casted call-result claims stay location-keyed; cast semantics are not federated"
    );
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "cast:usize");
                    assert_eq!(args.len(), 1);
                    match args[0].as_ref() {
                        Term::Ctor { name, args } => {
                            assert_eq!(name, "call:source");
                            assert!(args.is_empty());
                        }
                        other => panic!("expected source call under cast, got {other:?}"),
                    }
                }
                other => panic!("expected scalar cast lhs, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Int(42));
        }
        other => panic!("expected cast equality atom, got {other:?}"),
    }
}

#[test]
fn pointer_target_cast_stays_residual() {
    let src = r#"
#[test]
fn pointer_cast_result() {
    assert_eq!(source() as *const u8, source());
}
"#;
    let out = lift_file(&parse(src), "tests/cast.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0);
    assert!(out.decls.is_empty());
    assert!(
        out.warnings.iter().any(|warning| warning
            .reason
            .contains("unsupported term `source () as * const u8`")),
        "pointer-target casts must stay residual: {:?}",
        out.warnings
    );
}

#[test]
fn const_index_value_assertions_lift_location_keyed() {
    // Vendor shape: coretests/tests/intrinsics.rs::test_write_bytes_in_const_contexts.
    // These are exact expression claims about a const path indexed by integer
    // literals. They stay location-keyed; the lifter does not add index
    // semantics or federate them as call results.
    let src = r#"
#[test]
const fn test_write_bytes_in_const_contexts() {
    const TEST: [u32; 3] = [0, 0, 3];
    assert!(TEST[0] == 0);
    assert!(TEST[1] == 0);
    assert!(TEST[2] == 3);

    const TEST2: [u32; 3] = [16843009, 16843009, 3];
    assert!(TEST2[0] == 16843009);
    assert!(TEST2[1] == 16843009);
    assert!(TEST2[2] == 3);
}
"#;
    let out = lift_file(&parse(src), "tests/intrinsics.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name, "tests/intrinsics.rs::test_write_bytes_in_const_contexts",
        "const-index rows stay location-keyed"
    );
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 6);
    assert_const_index_eq(&operands[0], "TEST", 0, 0);
    assert_const_index_eq(&operands[1], "TEST", 1, 0);
    assert_const_index_eq(&operands[2], "TEST", 2, 3);
    assert_const_index_eq(&operands[3], "TEST2", 0, 16843009);
    assert_const_index_eq(&operands[4], "TEST2", 1, 16843009);
    assert_const_index_eq(&operands[5], "TEST2", 2, 3);
}

#[test]
fn immutable_local_index_lifts_as_index_term() {
    // `let xs` (non-mut) is provably immutable by the compiler (free axiom), so
    // xs[0] is a temporally-stable index term and lifts as index(xs, 0).
    let src = r#"
#[test]
fn local_index() {
    let xs = [1, 2, 3];
    assert!(xs[0] == 1);
}
"#;
    let out = lift_file(&parse(src), "tests/index.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(
        out.lifted, 1,
        "immutable index must lift: {:?}",
        out.warnings
    );
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 1);
    match ops[0].as_ref() {
        Formula::Atomic { args, .. } => match args[0].as_ref() {
            Term::Ctor { name, .. } => assert_eq!(name, "index"),
            other => panic!("expected index ctor, got {other:?}"),
        },
        other => panic!("expected equality, got {other:?}"),
    }
}

#[test]
fn mutable_local_index_stays_residual() {
    // `let mut xs` is conservatively unstable: it may be index-assigned or
    // method-mutated in ways the syntactic tracker cannot follow, so xs[0]
    // stays residual (sound refusal).
    let src = r#"
#[test]
fn local_index() {
    let mut xs = [1, 2, 3];
    assert!(xs[0] == 1);
}
"#;
    let out = lift_file(&parse(src), "tests/index.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0, "mutable container index must stay residual");
    assert!(out.decls.is_empty());
}

#[test]
fn mutable_reference_pointer_eq_stays_residual() {
    let src = r#"
#[test]
fn mutable_pointer_identity() {
    let mut x = 1;
    assert!(std::ptr::eq(&mut x, &mut x));
}
"#;
    let out = lift_file(&parse(src), "tests/ptr.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0);
    assert!(out.decls.is_empty());
    assert!(
        out.warnings
            .iter()
            .any(|warning| warning.reason.contains("unsupported term `& mut x`")),
        "mutable pointer identity must stay residual: {:?}",
        out.warnings
    );
}

#[test]
fn vendor_string_predicates_lift_to_string_theory_atoms_under_euf_keys() {
    // Vendor source: rust-src library/alloctests/tests/str.rs contains these
    // point-wise assertions in test_starts_with, test_ends_with, and contains.
    let src = r#"
#[test]
fn test_starts_with() {
    assert!("abc".starts_with("a"));
    assert!(!"a".starts_with("abc"));
}

#[test]
fn test_ends_with() {
    assert!("abc".ends_with("c"));
}

#[test]
fn contains() {
    assert!("abcde".contains("bcd"));
    assert!(!"abcde".contains("def"));
    assert!("abc".contains('b'));
}
"#;
    let out = lift_file(&parse(src), "tests/str.rs");
    assert_eq!(out.seen, 3);
    assert_eq!(out.lifted, 3, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 6);

    let names = out
        .decls
        .iter()
        .map(|decl| decl.name.as_str())
        .collect::<Vec<_>>();
    assert_eq!(
        names,
        vec![
            "method:starts_with#euf#c:callresult_method_starts_with_a2(s:\"abc\",s:\"a\")::assertion",
            "method:starts_with#euf#c:callresult_method_starts_with_a2(s:\"a\",s:\"abc\")::assertion",
            "method:ends_with#euf#c:callresult_method_ends_with_a2(s:\"abc\",s:\"c\")::assertion",
            "method:contains#euf#c:callresult_method_contains_a2(s:\"abcde\",s:\"bcd\")::assertion",
            "method:contains#euf#c:callresult_method_contains_a2(s:\"abcde\",s:\"def\")::assertion",
            "method:contains#euf#c:callresult_method_contains_a2(s:\"abc\",s:\"b\")::assertion",
        ]
    );

    assert_string_predicate_atom(&inv_operands(&out.decls[0])[0], "prefix-of", &["a", "abc"]);
    match inv_operands(&out.decls[1])[0].as_ref() {
        Formula::Connective { kind, operands } => {
            assert_eq!(kind, "not");
            assert_eq!(operands.len(), 1);
            assert_string_predicate_atom(&operands[0], "prefix-of", &["abc", "a"]);
        }
        other => panic!("expected negated prefix atom, got {other:?}"),
    }
    assert_string_predicate_atom(&inv_operands(&out.decls[2])[0], "suffix-of", &["c", "abc"]);
    assert_string_predicate_atom(
        &inv_operands(&out.decls[3])[0],
        "contains",
        &["abcde", "bcd"],
    );
    match inv_operands(&out.decls[4])[0].as_ref() {
        Formula::Connective { kind, operands } => {
            assert_eq!(kind, "not");
            assert_eq!(operands.len(), 1);
            assert_string_predicate_atom(&operands[0], "contains", &["abcde", "def"]);
        }
        other => panic!("expected negated contains atom, got {other:?}"),
    }
    assert_string_predicate_atom(&inv_operands(&out.decls[5])[0], "contains", &["abc", "b"]);
}

#[test]
fn vendor_ascii_and_len_predicates_lift_conservatively() {
    // Vendor source: rust-src library/coretests/tests/ascii.rs::test_is_ascii
    // and library/alloctests/tests/str.rs:157.
    let src = r#"
#[test]
fn test_is_ascii() {
    assert!("".is_ascii());
    assert!("banana\0\u{7F}".is_ascii());
}

#[test]
fn test_len() {
    assert_eq!("～～～～～".len(), 15);
}
"#;
    let out = lift_file(&parse(src), "tests/ascii.rs");
    assert_eq!(out.seen, 2);
    assert_eq!(out.lifted, 2, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 3);

    assert_eq!(
        out.decls[0].name,
        "method:is_ascii#euf#c:callresult_method_is_ascii_a1(s:\"\")::assertion"
    );
    assert_string_predicate_atom(&inv_operands(&out.decls[0])[0], "str.is_ascii", &[""]);
    assert_eq!(
        out.decls[1].name,
        "method:is_ascii#euf#c:callresult_method_is_ascii_a1(s:\"banana\\0\\u{7f}\")::assertion"
    );
    assert_string_predicate_atom(
        &inv_operands(&out.decls[1])[0],
        "str.is_ascii",
        &["banana\0\u{7F}"],
    );
    assert_eq!(
        out.decls[2].name,
        "method:len#euf#c:callresult_method_len_a1(s:\"～～～～～\")::assertion"
    );
    assert_string_len_cmp_atom(&inv_operands(&out.decls[2])[0], "=", "～～～～～", 15);
}

#[test]
fn vendor_char_ascii_class_lifts_and_unicode_alphabetic_stays_residual() {
    // Vendor source: rust-src library/core/src/char/methods.rs doc examples.
    let src = r#"
#[test]
fn char_ascii_classes() {
    assert!('A'.is_ascii_alphabetic());
    assert!(!'0'.is_ascii_alphabetic());
    assert!('a'.is_ascii());
    assert!('a'.is_alphabetic());
    assert!('0'.is_ascii_digit());
    assert!('f'.is_ascii_hexdigit());
    assert!('z'.is_ascii_lowercase());
    assert!('Z'.is_ascii_uppercase());
    assert!(' '.is_ascii_whitespace());
}
"#;
    let out = lift_file(&parse(src), "core/src/char/methods.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 8);
    assert_eq!(out.warnings.len(), 1);
    assert!(out.warnings[0]
        .reason
        .contains("unicode char predicate is_alphabetic is not lifted"));

    assert_eq!(
        out.decls[0].name,
        "method:is_ascii_alphabetic#euf#c:callresult_method_is_ascii_alphabetic_a1(s:\"A\")::assertion"
    );
    assert_string_predicate_atom(
        &inv_operands(&out.decls[0])[0],
        "str.is_ascii_alphabetic",
        &["A"],
    );
    match inv_operands(&out.decls[1])[0].as_ref() {
        Formula::Connective { kind, operands } => {
            assert_eq!(kind, "not");
            assert_eq!(operands.len(), 1);
            assert_string_predicate_atom(&operands[0], "str.is_ascii_alphabetic", &["0"]);
        }
        other => panic!("expected negated ascii alphabetic atom, got {other:?}"),
    }
    assert_string_predicate_atom(&inv_operands(&out.decls[2])[0], "str.is_ascii", &["a"]);
    assert_string_predicate_atom(
        &inv_operands(&out.decls[3])[0],
        "str.is_ascii_digit",
        &["0"],
    );
    assert_string_predicate_atom(
        &inv_operands(&out.decls[4])[0],
        "str.is_ascii_hexdigit",
        &["f"],
    );
    assert_string_predicate_atom(
        &inv_operands(&out.decls[5])[0],
        "str.is_ascii_lowercase",
        &["z"],
    );
    assert_string_predicate_atom(
        &inv_operands(&out.decls[6])[0],
        "str.is_ascii_uppercase",
        &["Z"],
    );
    assert_string_predicate_atom(
        &inv_operands(&out.decls[7])[0],
        "str.is_ascii_whitespace",
        &[" "],
    );
}

#[test]
fn vendor_literal_iterator_all_any_and_byte_slices_lift_soundly() {
    // Vendor source: rust-src library/coretests/tests/ascii.rs::test_is_ascii.
    let src = r#"
#[test]
fn test_is_ascii() {
    assert!(b"".is_ascii());
    assert!(b"banana\0\x7F".is_ascii());
    assert!(b"banana\0\x7F".iter().all(|b| b.is_ascii()));
    assert!(!b"Vi\xe1\xbb\x87t Nam".is_ascii());
    assert!(!b"Vi\xe1\xbb\x87t Nam".iter().all(|b| b.is_ascii()));
    assert!(!b"\xe1\xbb\x87".iter().any(|b| b.is_ascii()));
    assert!("".is_ascii());
    assert!("banana\0\x7F".is_ascii());
    assert!("banana\0\x7F".chars().all(|c| c.is_ascii()));
    assert!(!"ประเทศไทย中华Việt Nam".chars().all(|c| c.is_ascii()));
    assert!(!"ประเทศไทย中华ệ ".chars().any(|c| c.is_ascii()));
}
"#;
    let out = lift_file(&parse(src), "coretests/tests/ascii.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert!(
        out.warnings.is_empty(),
        "unexpected lift warnings: {:?}",
        out.warnings
    );
    assert_eq!(
        out.decls.len(),
        3,
        "expected two direct rows and one iterator/byte row"
    );
    let named_ascii = out
        .decls
        .iter()
        .filter(|decl| decl.name.starts_with("method:is_ascii#"))
        .count();
    assert_eq!(named_ascii, 2, "expected two direct string is_ascii rows");
    assert!(
        out.decls.iter().any(|decl| {
            decl.name == "coretests/tests/ascii.rs::test_is_ascii"
                && decl
                    .inv
                    .as_deref()
                    .is_some_and(|inv| formula_count_atomic_name(inv, "str.is_ascii") >= 10)
        }),
        "expected unrolled iterator/byte row in {:?}",
        out.decls
    );
    assert!(
        out.decls.iter().any(|decl| {
            decl.inv
                .as_deref()
                .is_some_and(|inv| formula_contains_relation_name(inv, "≥"))
        }),
        "expected byte iterator to lower to arithmetic range checks in {:?}",
        out.decls
    );
}

#[test]
fn vendor_assert_all_and_assert_none_macros_expand_to_bounded_claims() {
    // Vendor macro shape: rust-src library/coretests/tests/ascii.rs.
    let src = r#"
#[test]
fn test_is_ascii_alphabetic() {
    assert_all!(is_ascii_alphabetic, "Az",);
    assert_none!(is_ascii_digit, "aZ",);
}
"#;
    let out = lift_file(&parse(src), "coretests/tests/ascii.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert!(
        out.warnings.is_empty(),
        "unexpected lift warnings: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name,
        "coretests/tests/ascii.rs::test_is_ascii_alphabetic"
    );

    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 8);
    let inv = out.decls[0].inv.as_deref().expect("macro row has inv");
    assert_eq!(formula_count_atomic_name(inv, "str.is_ascii_alphabetic"), 2);
    assert_eq!(formula_count_atomic_name(inv, "str.is_ascii_digit"), 2);
    assert!(
        formula_count_atomic_name(inv, "\u{2265}") >= 4,
        "expected byte predicates to lower to arithmetic ranges: {inv:?}"
    );
    assert!(
        formula_count_connective_kind(inv, "not") >= 4,
        "assert_none! must negate each bounded element: {inv:?}"
    );
}

#[test]
fn assertion_macros_refuse_dynamic_sources_and_unicode_predicates() {
    let src = r#"
#[test]
fn dynamic_or_unicode_macro_sources() {
    let dynamic = "123";
    assert_all!(is_ascii_digit, dynamic);
    assert_all!(is_alphabetic, "A");
}
"#;
    let out = lift_file(&parse(src), "coretests/tests/ascii.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0);
    assert_eq!(out.decls.len(), 0);
    assert_eq!(out.warnings.len(), 2, "warnings: {:?}", out.warnings);
    assert!(out.warnings[0]
        .reason
        .contains("assert_all!: expected string literal source"));
    assert!(out.warnings[0]
        .reason
        .contains("unicode char predicate is_alphabetic is not lifted"));
    assert!(out.warnings[1]
        .reason
        .contains("no liftable scalar assertions"));
}

#[test]
fn call_result_comparison_assertions_use_fol_atoms_and_euf_key() {
    let src = r#"
fn value() -> i32 { 6 }

#[test]
fn comparison_atoms() {
    assert!(value() > 3);
    assert!(value() <= 9);
    assert!(value() != 7);
}
"#;
    let out = lift_file(&parse(src), "tests/compare.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(decl.name, "tests/compare.rs::comparison_atoms::value#euf#c:callresult_value_a0()::assertion");
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 3);
    assert_int_call_cmp_atom(&operands[0], ">", "call:value", 3);
    assert_int_call_cmp_atom(&operands[1], "\u{2264}", "call:value", 9);
    assert_int_call_cmp_atom(&operands[2], "\u{2260}", "call:value", 7);
}

#[test]
fn same_callsite_connectives_lift_as_fol_connectives_under_euf_key() {
    let src = r#"
fn value() -> i32 { 6 }

#[test]
fn connective_atoms() {
    assert!(value() > 3 && value() < 9);
    assert!(value() < 3 || value() > 5);
}
"#;
    let out = lift_file(&parse(src), "tests/compare.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(decl.name, "tests/compare.rs::connective_atoms::value#euf#c:callresult_value_a0()::assertion");
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    match operands[0].as_ref() {
        Formula::Connective { kind, operands } => {
            assert_eq!(kind, "and");
            assert_eq!(operands.len(), 2);
            assert_int_call_cmp_atom(&operands[0], ">", "call:value", 3);
            assert_int_call_cmp_atom(&operands[1], "<", "call:value", 9);
        }
        other => panic!("expected and connective, got {other:?}"),
    }
    match operands[1].as_ref() {
        Formula::Connective { kind, operands } => {
            assert_eq!(kind, "or");
            assert_eq!(operands.len(), 2);
            assert_int_call_cmp_atom(&operands[0], "<", "call:value", 3);
            assert_int_call_cmp_atom(&operands[1], ">", "call:value", 5);
        }
        other => panic!("expected or connective, got {other:?}"),
    }
}

#[test]
fn negated_call_result_comparison_lifts_as_fol_not_under_euf_key() {
    let src = r#"
fn value() -> i32 { 6 }

#[test]
fn negated_comparison() {
    assert!(value() >= 3);
    assert!(!(value() < 3));
}
"#;
    let out = lift_file(&parse(src), "tests/compare.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(decl.name, "tests/compare.rs::negated_comparison::value#euf#c:callresult_value_a0()::assertion");
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    assert_int_call_cmp_atom(&operands[0], "\u{2265}", "call:value", 3);
    match operands[1].as_ref() {
        Formula::Connective { kind, operands } => {
            assert_eq!(kind, "not");
            assert_eq!(operands.len(), 1);
            assert_int_call_cmp_atom(&operands[0], "<", "call:value", 3);
        }
        other => panic!("expected not connective, got {other:?}"),
    }
}

#[test]
fn non_call_assertions_stay_location_keyed() {
    let src = r#"
#[test]
fn scalar_var_is_six() {
    let value = 6;
    assert_eq!(value, 6);
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    assert_eq!(out.decls[0].name, "src/lib.rs::scalar_var_is_six");
}

#[test]
fn lifts_tokio_async_test_assertion_across_await_boundary() {
    let src = r#"
async fn make_value() -> i32 { 6 }

#[tokio::test]
async fn async_scalar_is_six() {
    assert_eq!(make_value().await, 6);
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(decl.name, "src/lib.rs::async_scalar_is_six");
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_await_call_eq_atom(&operands[0], "call:make_value", 6);
}

#[test]
fn conjoins_contradictory_tokio_async_assertions_across_same_await_shape() {
    let src = r#"
async fn make_value() -> i32 { 6 }

#[tokio::test]
async fn async_scalar_contradiction() {
    assert_eq!(make_value().await, 6);
    assert_eq!(make_value().await, 7);
}
"#;
    let out = lift_file(&parse(src), "tests/tokio_contradiction.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "tests/tokio_contradiction.rs::async_scalar_contradiction"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    assert_await_call_eq_atom(&operands[0], "call:make_value", 6);
    assert_await_call_eq_atom(&operands[1], "call:make_value", 7);
}

#[test]
fn await_effect_is_syntax_derived_not_tokio_name_derived() {
    let src = r#"
async fn make_value() -> i32 { 6 }

#[demo_runtime::test]
async fn async_scalar_is_six() {
    assert_eq!(make_value().await, 6);
}
"#;
    let out = lift_file(&parse(src), "src/lib.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    assert_await_call_eq_atom(&operands[0], "call:make_value", 6);
}

// --- infinity-equality conjunction tests ---

fn assert_float_refinement_conj_var(
    formula: &Formula,
    expected_infinite_pred: &str,
    expected_sign_pred: &str,
    expected_var: &str,
) {
    match formula {
        Formula::Connective { kind, operands } if kind == "and" => {
            assert_eq!(
                operands.len(),
                2,
                "infinity conjunction must have 2 operands"
            );
            assert_float_refinement_var_atom(
                operands[0].as_ref(),
                expected_infinite_pred,
                expected_var,
            );
            assert_float_refinement_var_atom(
                operands[1].as_ref(),
                expected_sign_pred,
                expected_var,
            );
        }
        other => panic!("expected and-conjunction for infinity equality, got {other:?}"),
    }
}

#[test]
fn assert_eq_f64_infinity_lifts_to_is_infinite_and_is_sign_positive_conjunction() {
    // RED: assert_eq!(x_f64, f64::INFINITY) must lift to
    // and(float.f64.is_infinite(x_f64), float.f64.is_sign_positive(x_f64)).
    let src = r#"
#[test]
fn check_pos_infinity() {
    let x_f64: f64 = 1.0;
    assert_eq!(x_f64, f64::INFINITY);
}
"#;
    let out = lift_file(&parse(src), "tests/num/mod.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_float_refinement_conj_var(
        operands[0].as_ref(),
        "float.f64.is_infinite",
        "float.f64.is_sign_positive",
        "x_f64",
    );
}

#[test]
fn assert_eq_f32_neg_infinity_lifts_to_is_infinite_and_is_sign_negative_conjunction() {
    // RED: assert_eq!(x_f32, f32::NEG_INFINITY) must lift to
    // and(float.f32.is_infinite(x_f32), float.f32.is_sign_negative(x_f32)).
    let src = r#"
#[test]
fn check_neg_infinity() {
    let x_f32: f32 = -1.0;
    assert_eq!(x_f32, f32::NEG_INFINITY);
}
"#;
    let out = lift_file(&parse(src), "tests/num/mod.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_float_refinement_conj_var(
        operands[0].as_ref(),
        "float.f32.is_infinite",
        "float.f32.is_sign_negative",
        "x_f32",
    );
}

#[test]
fn assert_infinity_eq_reversed_operand_order_lifts_correctly() {
    // Operand order reversed: f64::INFINITY == x_f64 (assert! form, binary eq).
    let src = r#"
#[test]
fn check_pos_infinity_reversed() {
    let x_f64: f64 = 1.0;
    assert!(f64::INFINITY == x_f64);
}
"#;
    let out = lift_file(&parse(src), "tests/num/mod.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    assert_float_refinement_conj_var(
        operands[0].as_ref(),
        "float.f64.is_infinite",
        "float.f64.is_sign_positive",
        "x_f64",
    );
}

#[test]
fn finite_float_equality_is_not_rerouted_to_infinity_conjunction() {
    // Discrimination: assert_eq!(x_f64, 1.5f64) must NOT trigger the infinity path.
    // It must remain a standard Real-equality row, not a conjunction.
    let src = r#"
#[test]
fn check_finite_eq() {
    let x_f64: f64 = 1.5;
    assert_eq!(x_f64, 1.5f64);
}
"#;
    let out = lift_file(&parse(src), "tests/num/mod.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);

    let decl = &out.decls[0];
    let inv = decl.inv.as_deref().expect("finite eq must have inv");
    // Must NOT be an and-conjunction at the top level (not an infinity conjunction).
    match inv {
        Formula::Connective { kind, .. } if kind == "and" => {
            // and-conjunction is OK only if it contains equality atoms, not float predicates.
            // The infinity path would produce float.fXX.is_infinite predicates.
            // Check the conjunction does NOT contain is_infinite.
            let inv_str = format!("{inv:?}");
            assert!(
                !inv_str.contains("is_infinite"),
                "finite equality must not produce is_infinite predicate, got: {inv_str}"
            );
        }
        Formula::Atomic { name, .. } => {
            assert_eq!(
                name, "=",
                "finite equality should use = relation, got {name}"
            );
        }
        other => panic!("unexpected inv shape for finite eq: {other:?}"),
    }
}

#[test]
fn unknown_width_infinity_eq_is_skipped_as_residual() {
    // If width is unknown (no f32/f64 annotation), the infinity eq is refused (skipped).
    // This is SOUND: silence is correct; a wrong row would be a bug.
    let src = r#"
#[test]
fn unknown_width_infinity() {
    let x = 1.0;
    assert_eq!(x, f64::INFINITY);
}
"#;
    let out = lift_file(&parse(src), "tests/num/mod.rs");
    assert_eq!(out.seen, 1);
    // Either lifted=0 (skipped) or the assertion is warned/skipped.
    // The key invariant: no falsePass. If it lifts, it must not be a broken row.
    // But the width-unknown path must not silently produce a wrong row.
    if out.lifted == 1 {
        // If lifted, the decl must have a sound conjunction using f64 width
        // derived from the constant side (f64::INFINITY determines width).
        let decl = &out.decls[0];
        let inv = decl.inv.as_deref().expect("lifted row must have inv");
        let inv_str = format!("{inv:?}");
        assert!(
            inv_str.contains("float.f64"),
            "if lifted, width must be f64 from the constant: {inv_str}"
        );
    }
    // If lifted=0 (skipped), that is also correct (conservative).
}

// --- is_finite predicate lift tranche ---

#[test]
fn is_finite_on_typed_local_lifts_as_predicate_atom() {
    // RED before: is_finite is not in is_liftable_float_refinement_method, so
    // the lifter refuses it with a warning and lifted=0.
    // GREEN after: it lifts as float.f64.is_finite(pos) and
    // not(float.f32.is_finite(nan)).
    let src = r#"
#[test]
fn finite_predicate_typed_local() {
    let pos: f64 = 42.8;
    let nan: f32 = f32::NAN;
    assert!(pos.is_finite());
    assert!(!nan.is_finite());
}
"#;
    let out = lift_file(&parse(src), "tests/num/floats_direct.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "tests/num/floats_direct.rs::finite_predicate_typed_local"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 2);
    assert_float_refinement_var_atom(&operands[0], "float.f64.is_finite", "pos");
    match operands[1].as_ref() {
        Formula::Connective { kind, operands } if kind == "not" => {
            assert_eq!(operands.len(), 1);
            assert_float_refinement_var_atom(operands[0].as_ref(), "float.f32.is_finite", "nan");
        }
        other => panic!("expected negated is_finite atom, got {other:?}"),
    }
}

#[test]
fn is_finite_discrimination_does_not_reroute_is_normal_or_is_infinite() {
    // Discrimination: adding is_finite must not alter the lift of is_normal or
    // is_infinite on the same receiver. Each predicate must emit its own atom
    // unchanged.
    let src = r#"
#[test]
fn mixed_finite_normal_infinite() {
    let x: f64 = 1.5;
    assert!(x.is_normal());
    assert!(x.is_finite());
    assert!(!x.is_infinite());
}
"#;
    let out = lift_file(&parse(src), "tests/num/floats_direct.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    assert_eq!(out.decls.len(), 1);

    let decl = &out.decls[0];
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 3);
    // first: is_normal -- must not have been replaced by is_finite
    assert_float_refinement_var_atom(&operands[0], "float.f64.is_normal", "x");
    // second: is_finite -- the new predicate
    assert_float_refinement_var_atom(&operands[1], "float.f64.is_finite", "x");
    // third: not(is_infinite) -- must not have been replaced by not(is_finite)
    match operands[2].as_ref() {
        Formula::Connective { kind, operands } if kind == "not" => {
            assert_eq!(operands.len(), 1);
            assert_float_refinement_var_atom(operands[0].as_ref(), "float.f64.is_infinite", "x");
        }
        other => panic!("expected not(is_infinite) atom, got {other:?}"),
    }
}

#[test]
fn is_finite_without_width_annotation_is_refused_not_silently_lifted() {
    // Width-unknown receiver must not silently produce a wrong row.
    // Conservative: if lifted=0 (warned/skipped), that is correct.
    let src = r#"
#[test]
fn finite_no_width() {
    let x = 1.0;
    assert!(x.is_finite());
}
"#;
    let out = lift_file(&parse(src), "tests/num/floats_direct.rs");
    // If it lifts, verify no falsePass: the name must contain is_finite.
    if out.lifted == 1 {
        let decl = &out.decls[0];
        let inv = decl.inv.as_deref().expect("lifted row must have inv");
        let inv_str = format!("{inv:?}");
        assert!(
            inv_str.contains("is_finite"),
            "if lifted, atom must name is_finite: {inv_str}"
        );
    }
    // lifted=0 is also acceptable (conservative refusal).
}

#[test]
fn is_some_predicate_on_const_path_lifts_with_euf_key() {
    // Vendor shape: option.rs::const_get_or_insert_default
    // assert!(OPT_DEFAULT.is_some()) where OPT_DEFAULT is a const item.
    // Receiver is an immutable constant; no mutation or alias possible.
    let src = r#"
#[test]
fn const_get_or_insert_default() {
    const OPT_DEFAULT: Option<Vec<bool>> = {
        let mut x = None;
        x
    };
    assert!(OPT_DEFAULT.is_some());
}
"#;
    let out = lift_file(&parse(src), "tests/option.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "method:is_some#euf#c:callresult_method_is_some_a1(v:tests/option.rs::const_get_or_insert_default::OPT_DEFAULT)::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, "method:is_some"),
                other => panic!("expected method:is_some ctor, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Bool(value),
                    ..
                } => assert!(*value, "expected bool true rhs"),
                other => panic!("expected bool true rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn is_none_predicate_on_call_result_lifts_with_euf_key() {
    // Vendor shape: is_none() on a direct call-result receiver.
    // The receiver is a call result of an immutable method call: stable key.
    let src = r#"
struct Opt;

impl Opt {
    fn get(&self) -> Option<i32> { None }
}

#[test]
fn call_result_is_none() {
    let obj = Opt;
    assert!(obj.get().is_none());
}
"#;
    let out = lift_file(&parse(src), "tests/option.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    let decl = &out.decls[0];
    assert_eq!(
        decl.name,
        "method:is_none#euf#c:callresult_method_is_none_a1(c:method:get(v:tests/option.rs::call_result_is_none::obj))::assertion"
    );
    let operands = inv_operands(decl);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            match args[0].as_ref() {
                Term::Ctor { name, .. } => assert_eq!(name, "method:is_none"),
                other => panic!("expected method:is_none ctor, got {other:?}"),
            }
            match args[1].as_ref() {
                Term::Const {
                    value: ConstValue::Bool(value),
                    ..
                } => assert!(*value, "expected bool true rhs"),
                other => panic!("expected bool true rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn mutable_receiver_is_some_stays_residual_via_temporal_guard() {
    // Discrimination test: a reassigned mutable local whose new value is
    // conditionally set must stay residual (ambiguous temporal identity).
    // This is the exact shape that would falsePass if the temporal guard
    // did not apply to is_some/is_none as it does to contains.
    let src = r#"
fn maybe_none() -> Option<i32> { None }

#[test]
fn conditional_rebind_is_some() {
    let mut x: Option<i32> = Some(1);
    if maybe_none().is_some() {
        x = None;
    }
    assert!(x.is_some());
}
"#;
    let out = lift_file(&parse(src), "tests/option.rs");
    assert_eq!(out.seen, 1);
    // The assertion on x (which may have been conditionally reassigned)
    // must be skipped; only the is_some() call inside the if-condition
    // might lift (it is on a direct call result, not x).
    // Crucially: x.is_some() at the end must NOT produce a lifted row.
    let x_rows: Vec<_> = out
        .decls
        .iter()
        .filter(|d| d.name.contains("::x"))
        .collect();
    assert!(
        x_rows.is_empty(),
        "mutable conditionally-reassigned receiver must stay residual, got rows: {x_rows:?}"
    );
}

// --- assert_ne! macro lift tranche (sugar for a != b, federated to the != path) ---

// The load-bearing property: assert_ne!(a, b) must lift to the BYTE-IDENTICAL
// atom as assert!(a != b). Same logical claim -> same atom -> same CID. We prove
// it by lifting both and comparing the inv structurally.
fn single_inv_debug(src: &str) -> String {
    let out = lift_file(&parse(src), "tests/macros.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.decls.len(), 1);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    format!("{:?}", operands[0])
}

#[test]
fn assert_ne_primitive_lifts_identically_to_not_equal_operator() {
    // assert_ne!(a(), 1) must equal assert!(a() != 1): both -> ne(call:a(), 1).
    let via_macro = single_inv_debug(
        r#"
fn a() -> i32 { 7 }
#[test]
fn t() { assert_ne!(a(), 1); }
"#,
    );
    let via_operator = single_inv_debug(
        r#"
fn a() -> i32 { 7 }
#[test]
fn t() { assert!(a() != 1); }
"#,
    );
    assert_eq!(
        via_macro, via_operator,
        "assert_ne! must lift byte-identically to the != operator"
    );
    assert!(
        via_macro.contains('≠'),
        "primitive assert_ne should produce the not-equal relation atom: {via_macro}"
    );
}

#[test]
fn assert_ne_user_type_lifts_identically_to_not_equal_operator_as_dispatch_false() {
    // On user-typed (constructor) operands, != is sugar for !a.eq(b): both
    // assert_ne!(Foo(1), Foo(2)) and assert!(Foo(1) != Foo(2)) must lift to the
    // operator-dispatch atom eq(call:eq:Foo(..), false) -- invariant 9x.
    let via_macro = single_inv_debug(
        r#"
#[test]
fn t() { assert_ne!(Foo(1), Foo(2)); }
"#,
    );
    let via_operator = single_inv_debug(
        r#"
#[test]
fn t() { assert!(Foo(1) != Foo(2)); }
"#,
    );
    assert_eq!(
        via_macro, via_operator,
        "assert_ne! on user types must federate to the same operator-dispatch atom as !="
    );
    assert!(
        via_macro.contains("call:eq:Foo"),
        "user-typed assert_ne should dispatch to call:eq:Foo, not FOL: {via_macro}"
    );
}

#[test]
fn assert_ne_does_not_reroute_assert_eq_rows() {
    // Discrimination: a file with both assert_eq! and assert_ne! produces a
    // positive equality atom AND a distinct ne atom, not two of the same.
    let out = lift_file(
        &parse(
            r#"
fn a() -> i32 { 1 }
fn b() -> i32 { 2 }
#[test]
fn mixed_eq_ne() {
    assert_eq!(a(), 1);
    assert_ne!(b(), 1);
}
"#,
        ),
        "tests/macros.rs",
    );
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    // Across all decls/atoms, assert_eq! contributes a positive equality and
    // assert_ne! contributes a not-equal -- both present, regardless of how the
    // two assertions are grouped into decls.
    let all = format!("{:?}", out.decls);
    assert!(
        all.contains('≠'),
        "expected a not-equal atom from assert_ne!: {all}"
    );
    assert!(
        all.contains("\"=\""),
        "expected a positive equality atom from assert_eq!: {all}"
    );
}

#[test]
fn assert_ne_trailing_comma_lifts() {
    // assert_ne!(1, 2,) -- trailing comma is handled, lifts the ne(1,2) atom.
    let out = lift_file(
        &parse(
            r#"
#[test]
fn t() { assert_ne!(1, 2,); }
"#,
        ),
        "tests/macros.rs",
    );
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
}

// ---- debug_assert* family ----
//
// RED-FIRST: before the cfg-gated routing was added, debug_assert_eq! hit the
// catch-all arm and returned Err("debug_assert_eq!: unsupported assertion
// macro"), which caused the row to be skipped (lifted=0, 1 warning). The
// tests below capture the new correct behaviour (lifted=1 when
// debug_assertions is Active) and the discrimination case (skipped when
// debug_assertions is not Active).

fn options_with_debug_assertions() -> LiftOptions {
    LiftOptions::for_target_cfg(
        TargetCfg::from_rustc_cfg_facts(["debug_assertions"]).expect("valid cfg fact"),
    )
}

/// Lift with debug_assertions=Active and return the single invariant operand
/// debug string, mirroring single_inv_debug for the debug_assert* family.
fn single_inv_debug_with_da(src: &str) -> String {
    let opts = options_with_debug_assertions();
    let out = lift_file_with_options(&parse(src), "tests/macros.rs", &opts);
    assert_eq!(out.seen, 1, "expected 1 test fn seen");
    assert_eq!(
        out.lifted, 1,
        "expected 1 lifted row; warnings: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    format!("{:?}", operands[0])
}

// --- RED-first regression: debug_assert_eq! previously errored as unsupported
//
// This test would have FAILED before the routing change with:
//   thread '...' panicked at 'assertion failed: `(left == right)`
//   left: `0`, right: `1`: expected 1 lifted row; warnings: [LiftWarning {
//   ... reason: "debug_assert_eq!: unsupported assertion macro" }]'
//
// After the change it lifts exactly one row when debug_assertions is Active.
#[test]
fn debug_assert_eq_lifts_when_debug_assertions_active() {
    let opts = options_with_debug_assertions();
    let out = lift_file_with_options(
        &parse(
            r#"
fn a() -> i32 { 1 }
#[test]
fn t() { debug_assert_eq!(a(), 1); }
"#,
        ),
        "tests/macros.rs",
        &opts,
    );
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
}

// --- Federation: debug_assert_eq! atom is byte-identical to assert_eq! atom
//
// Soundness: the CLAIM asserted by debug_assert_eq!(a, b) when
// debug_assertions is Active is identical to the claim of assert_eq!(a, b).
// The only difference (compiling out in release) is an effect invisible to
// the lifter. The atoms must be byte-identical.
#[test]
fn debug_assert_eq_lifts_byte_identically_to_assert_eq() {
    let via_debug = single_inv_debug_with_da(
        r#"
fn a() -> i32 { 7 }
#[test]
fn t() { debug_assert_eq!(a(), 1); }
"#,
    );
    let via_plain = single_inv_debug(
        r#"
fn a() -> i32 { 7 }
#[test]
fn t() { assert_eq!(a(), 1); }
"#,
    );
    assert_eq!(
        via_debug, via_plain,
        "debug_assert_eq! must lift byte-identically to assert_eq! when debug_assertions is Active"
    );
}

// --- Federation: debug_assert! atom is byte-identical to assert! atom
#[test]
fn debug_assert_lifts_byte_identically_to_assert() {
    let via_debug = single_inv_debug_with_da(
        r#"
fn a() -> bool { true }
#[test]
fn t() { debug_assert!(a()); }
"#,
    );
    let via_plain = single_inv_debug(
        r#"
fn a() -> bool { true }
#[test]
fn t() { assert!(a()); }
"#,
    );
    assert_eq!(
        via_debug, via_plain,
        "debug_assert! must lift byte-identically to assert! when debug_assertions is Active"
    );
}

// --- Federation: debug_assert_ne! atom is byte-identical to assert_ne! atom
#[test]
fn debug_assert_ne_lifts_byte_identically_to_assert_ne() {
    let via_debug = single_inv_debug_with_da(
        r#"
fn a() -> i32 { 7 }
#[test]
fn t() { debug_assert_ne!(a(), 1); }
"#,
    );
    let via_plain = single_inv_debug(
        r#"
fn a() -> i32 { 7 }
#[test]
fn t() { assert_ne!(a(), 1); }
"#,
    );
    assert_eq!(
        via_debug, via_plain,
        "debug_assert_ne! must lift byte-identically to assert_ne! when debug_assertions is Active"
    );
    assert!(
        via_debug.contains('≠'),
        "debug_assert_ne! should produce the not-equal relation atom: {via_debug}"
    );
}

// --- Discrimination: debug_assert_eq! is REFUSED when debug_assertions is not Active
//
// Without a target_cfg that confirms debug_assertions, the macro expands to a
// no-op in release builds. Lifting it unconditionally would overclaim
// (falsePass). The lifter must skip the row and record a warning.
#[test]
fn debug_assert_eq_refused_when_debug_assertions_not_active() {
    // lift_file has no target_cfg -> debug_assertions is Ambiguous -> refused
    let out = lift_file(
        &parse(
            r#"
fn a() -> i32 { 1 }
#[test]
fn t() { debug_assert_eq!(a(), 1); }
"#,
        ),
        "tests/macros.rs",
    );
    assert_eq!(
        out.lifted, 0,
        "debug_assert_eq! must NOT lift when debug_assertions is not confirmed Active"
    );
    assert!(
        !out.warnings.is_empty(),
        "expected at least one warning when debug_assertions is not Active"
    );
    let debug_warn = out
        .warnings
        .iter()
        .find(|w| w.reason.contains("debug_assert_eq!"))
        .unwrap_or_else(|| panic!("no warning mentioning debug_assert_eq!: {:?}", out.warnings));
    assert!(
        debug_warn.reason.contains("ambiguous"),
        "warning should cite ambiguous cfg(debug_assertions): {:?}",
        debug_warn.reason
    );
}

// --- ptr::eq as a base lowerer in the reducer path ---
//
// The dedicated translate_pointer_eq_assertion arm fires for DIRECT assert!(ptr::eq(...))
// calls in test bodies. The reducer path must also handle ptr::eq when it appears
// inside an assertion helper body. This test proves that a transparent helper
// wrapping assert!(ptr::eq(a, b)) reduces BYTE-IDENTICALLY through the unified
// walk: the old hardcoded-arm-only path could NOT reduce through a helper call.
#[test]
fn ptr_eq_through_reducer_helper_produces_location_keyed_row() {
    // The helper assert_same_ptr is a transparent wrapper: its body is a single
    // assert!(ptr::eq(a, b)) statement. The reducer descends into the helper and
    // encounters ptr::eq as a base lowerer, yielding the same location-keyed atom
    // as a direct assert!(ptr::eq(a, b)) call at the test site.
    let src = r#"
fn assert_same_ptr(a: *const u8, b: *const u8) {
    assert!(ptr::eq(a, b));
}

#[test]
fn same_pointer_via_helper() {
    let x: u8 = 42;
    assert_same_ptr(&x, &x);
}
"#;
    let out = lift_file(&parse(src), "tests/ptr_reducer.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(
        out.lifted, 1,
        "ptr::eq inside a helper body must reduce through the base lowerer path: {:?}",
        out.warnings
    );
    assert!(
        out.warnings.is_empty(),
        "no warnings expected for transparent ptr::eq helper: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    assert_eq!(
        out.decls[0].name,
        "tests/ptr_reducer.rs::same_pointer_via_helper"
    );

    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            match args[0].as_ref() {
                Term::Ctor {
                    name,
                    args: ctor_args,
                } => {
                    assert_eq!(
                        name, "call:ptr::eq",
                        "ptr::eq through reducer must remain location-keyed with the callee key"
                    );
                    assert_eq!(ctor_args.len(), 2);
                }
                other => panic!("expected ptr::eq call term, got {other:?}"),
            }
            assert_scalar_const(&args[1], ExpectedScalar::Bool(true));
        }
        other => panic!("expected pointer equality atom from reducer path, got {other:?}"),
    }
}

// RED-first: byte-string literal tests.  The first two assert CURRENT
// behaviour (no row, warns "unsupported"), then are expected to FAIL once
// translate_lit handles Lit::ByteStr.  They are marked #[should_panic] so
// the suite stays green during the RED phase.  After the implementation the
// #[should_panic] attribute is removed.

/// Before the fix: assert_eq!(call(), b"abc") produces no row because
/// translate_lit refuses Lit::ByteStr.  After the fix it lifts one row whose
/// RHS is a literal:bytes(...) opaque var.
#[test]
fn bytestr_literal_rhs_lifts_content_keyed_opaque_term() {
    let src = r#"
fn encoded() -> Vec<u8> { vec![97, 98, 99] }

#[test]
fn encode_abc() {
    assert_eq!(encoded(), b"abc");
}
"#;
    let out = lift_file(&parse(src), "src/codec.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(
        out.lifted, 1,
        "byte-string literal must lift one row; warnings: {:?}",
        out.warnings
    );
    assert!(
        out.warnings.is_empty(),
        "no warnings expected for byte-string literal assertion: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    match operands[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            assert_eq!(args.len(), 2);
            // RHS must be an opaque literal:bytes(...) var
            match args[1].as_ref() {
                Term::Var { name } => {
                    assert!(
                        name.starts_with("literal:bytes("),
                        "RHS must be a literal:bytes(...) opaque var, got `{name}`"
                    );
                    // b"abc" = 0x61 0x62 0x63
                    assert!(
                        name.contains("616263"),
                        "literal:bytes key must contain hex 616263 for b\"abc\", got `{name}`"
                    );
                }
                other => panic!("expected literal:bytes Var rhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

/// Two DIFFERENT byte literals must produce distinct opaque terms.
/// Congruence: two SAME byte literals must produce equal opaque terms.
#[test]
fn bytestr_discrimination_different_literals_produce_distinct_terms() {
    let src_abc = r#"
fn encoded() -> Vec<u8> { vec![97, 98, 99] }

#[test]
fn encode_abc() {
    assert_eq!(encoded(), b"abc");
}
"#;
    let src_abd = r#"
fn encoded() -> Vec<u8> { vec![97, 98, 100] }

#[test]
fn encode_abd() {
    assert_eq!(encoded(), b"abd");
}
"#;
    let src_abc2 = r#"
fn encoded() -> Vec<u8> { vec![97, 98, 99] }

#[test]
fn encode_abc_again() {
    assert_eq!(encoded(), b"abc");
}
"#;

    fn extract_bytestr_var_name(src: &str, fixture: &str) -> String {
        let out = lift_file(&syn::parse_file(src).expect("fixture parses"), fixture);
        assert_eq!(
            out.lifted, 1,
            "bytestr discrimination fixture must lift one row; warnings: {:?}",
            out.warnings
        );
        let operands = inv_operands(&out.decls[0]);
        match operands[0].as_ref() {
            Formula::Atomic { args, .. } => match args[1].as_ref() {
                Term::Var { name } => name.clone(),
                other => panic!("expected Var rhs, got {other:?}"),
            },
            other => panic!("expected atom, got {other:?}"),
        }
    }

    let name_abc = extract_bytestr_var_name(src_abc, "src/codec.rs");
    let name_abd = extract_bytestr_var_name(src_abd, "src/codec.rs");
    let name_abc2 = extract_bytestr_var_name(src_abc2, "src/codec2.rs");

    // Congruence: same bytes -> same key
    assert_eq!(
        name_abc, name_abc2,
        "same byte literal b\"abc\" must produce the same opaque term (congruence)"
    );
    // Discrimination: different bytes -> different key
    assert_ne!(
        name_abc, name_abd,
        "different byte literals b\"abc\" vs b\"abd\" must produce distinct opaque terms"
    );
}

/// Contradiction: same call asserted == b"abc" AND == b"abd" in one test.
/// The lifted IR must contain TWO equality atoms whose RHS terms are distinct
/// opaque literal:bytes vars.  The conjunction is z3-UNSAT (caught) because
/// the two distinct vars are treated as unequal opaque constants.
#[test]
fn bytestr_contradiction_two_different_literals_are_distinct_in_ir() {
    let src = r#"
fn encoded() -> Vec<u8> { vec![] }

#[test]
fn contradictory_encode() {
    assert_eq!(encoded(), b"abc");
    assert_eq!(encoded(), b"abd");
}
"#;
    let out = lift_file(&parse(src), "src/codec.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(
        out.lifted, 1,
        "contradictory byte-string literals must still lift one combined row; warnings: {:?}",
        out.warnings
    );
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(
        operands.len(),
        2,
        "two contradictory assertions must produce two atoms"
    );

    let mut bytestr_vars: Vec<String> = operands
        .iter()
        .map(|op| match op.as_ref() {
            Formula::Atomic { args, .. } => match args[1].as_ref() {
                Term::Var { name } => {
                    assert!(
                        name.starts_with("literal:bytes("),
                        "each RHS must be a literal:bytes var, got `{name}`"
                    );
                    name.clone()
                }
                other => panic!("expected literal:bytes Var rhs, got {other:?}"),
            },
            other => panic!("expected equality atom, got {other:?}"),
        })
        .collect();

    bytestr_vars.sort();
    bytestr_vars.dedup();
    assert_eq!(
        bytestr_vars.len(),
        2,
        "two different byte literals must produce two DISTINCT opaque vars (z3 would catch UNSAT)"
    );
}

// --- macro-invocation-as-EUF-term tranche (T-FORMAT) ---

fn eq_lhs_name(formula: &Formula) -> String {
    match formula {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            match args[0].as_ref() {
                Term::Var { name } => name.clone(),
                other => panic!("expected Var lhs, got {other:?}"),
            }
        }
        other => panic!("expected equality atom, got {other:?}"),
    }
}

#[test]
fn format_roundtrip_lifts_as_macro_term() {
    // RED before: format!(..) in term position is "unsupported term"; lifted=0.
    // GREEN after: it lifts as an uninterpreted macro: term equal to the literal.
    let src = r#"
#[test]
fn fmt_roundtrip() {
    let x = 5;
    assert_eq!(format!("{x:?}"), "5");
}
"#;
    let out = lift_file(&parse(src), "tests/fmt.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    assert_eq!(out.warnings.len(), 0);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 1);
    let lhs = eq_lhs_name(&ops[0]);
    assert!(
        lhs.starts_with("macro:") && lhs.contains("format"),
        "lhs must be a macro term naming format, got {lhs}"
    );
}

#[test]
fn identical_format_calls_coalesce_congruence() {
    // Teeth: two identical format! calls must produce the SAME term, so a
    // contradiction over them is UNSAT. This is the non-vacuity guarantee.
    let src = r#"
#[test]
fn fmt_twice() {
    let x = 5;
    assert_eq!(format!("{x:?}"), "a");
    assert_eq!(format!("{x:?}"), "b");
}
"#;
    let out = lift_file(&parse(src), "tests/fmt.rs");
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 2);
    assert_eq!(
        eq_lhs_name(&ops[0]),
        eq_lhs_name(&ops[1]),
        "identical format! calls must coalesce to one term (consistency teeth)"
    );
}

#[test]
fn distinct_format_calls_do_not_coalesce() {
    // Distinctness: different macro source must produce different terms.
    let src = r#"
#[test]
fn fmt_distinct() {
    let x = 5;
    let y = 5;
    assert_eq!(format!("{x:?}"), "a");
    assert_eq!(format!("{y:?}"), "a");
}
"#;
    let out = lift_file(&parse(src), "tests/fmt.rs");
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 2);
    assert_ne!(
        eq_lhs_name(&ops[0]),
        eq_lhs_name(&ops[1]),
        "distinct format! calls must not coalesce"
    );
}

#[test]
fn vec_and_offset_of_lift_as_macro_terms() {
    // Generality: the arm is not format-specific; any macro in term position lifts.
    let src = r#"
#[test]
fn other_macros() {
    assert_eq!(vec![1, 2, 3], vec![1, 2, 3]);
    assert_eq!(offset_of!(Foo, x), 0);
}
"#;
    let out = lift_file(&parse(src), "tests/fmt.rs");
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 2);
    // vec! == vec! is reflexive over one coalesced term.
    assert_eq!(eq_lhs_name(&ops[0]), {
        match ops[0].as_ref() {
            Formula::Atomic { args, .. } => match args[1].as_ref() {
                Term::Var { name } => name.clone(),
                other => panic!("expected Var rhs for vec! == vec!, got {other:?}"),
            },
            other => panic!("expected equality, got {other:?}"),
        }
    });
    let off = eq_lhs_name(&ops[1]);
    assert!(
        off.starts_with("macro:") && off.contains("offset_of"),
        "offset_of! must lift as a macro term, got {off}"
    );
}

#[test]
fn non_macro_terms_unchanged_discrimination() {
    // The new arm must not perturb ordinary term lifting.
    let src = r#"
#[test]
fn plain() {
    let a = 1;
    assert_eq!(a, 1);
}
"#;
    let out = lift_file(&parse(src), "tests/fmt.rs");
    assert_eq!(out.lifted, 1);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 1);
    let lhs = eq_lhs_name(&ops[0]);
    assert!(
        !lhs.starts_with("macro:"),
        "plain local must not be a macro term, got {lhs}"
    );
}

// --- deref and reference structural terms tranche (T-DEREF) ---

#[test]
fn deref_lifts_as_deref_term() {
    // RED before: *b is an unsupported unary term; lifted=0.
    // GREEN after: *b lifts as deref(b).
    let src = r#"
#[test]
fn deref_eq() {
    let b = 5;
    assert_eq!(*b, 5);
}
"#;
    let out = lift_file(&parse(src), "tests/clone.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 1);
    match ops[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            match args[0].as_ref() {
                Term::Ctor { name, args } => {
                    assert_eq!(name, "deref");
                    assert_eq!(args.len(), 1);
                }
                other => panic!("expected deref ctor lhs, got {other:?}"),
            }
        }
        other => panic!("expected equality, got {other:?}"),
    }
}

#[test]
fn deref_congruence_same_pointer_coalesces() {
    // Teeth: *b used twice is the same term, so a contradiction is UNSAT.
    let src = r#"
#[test]
fn deref_twice() {
    let b = 5;
    assert_eq!(*b, 1);
    assert_eq!(*b, 2);
}
"#;
    let out = lift_file(&parse(src), "tests/clone.rs");
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 2);
    let lhs = |f: &Formula| match f {
        Formula::Atomic { args, .. } => format!("{:?}", args[0]),
        other => panic!("{other:?}"),
    };
    assert_eq!(lhs(&ops[0]), lhs(&ops[1]), "*b must coalesce (teeth)");
}

#[test]
fn deref_does_not_enable_mut_ref_lifting() {
    // Soundness boundary: adding deref must NOT make `&mut x` liftable. A
    // mutable referent can change between observations (temporal identity), so
    // it stays residual, consistent with mutable_reference_pointer_eq_stays_residual.
    let src = r#"
#[test]
fn mut_ref_residual() {
    let mut x = 1;
    assert_eq!(&mut x, &mut x);
}
"#;
    let out = lift_file(&parse(src), "tests/clone.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(out.lifted, 0, "&mut must stay residual: {:?}", out.warnings);
    assert!(
        out.warnings
            .iter()
            .any(|w| w.reason.contains("unsupported term `& mut x`")),
        "mut ref must be a named refusal: {:?}",
        out.warnings
    );
}

// --- stdlib internal-macro lift / honest-refusal tests ---
//
// These tests cover the coretests corpus macros that previously fell through
// to the generic "unsupported assertion macro" bucket. Each macro has:
//   positive  -- correct outcome (lifted atom or named refusal)
//   discrimination -- neighbouring assert_eq! is unaffected
//   teeth (lowered only) -- contradiction twin is UNSAT
//
// Macro source citations match the definitions read from the toolchain tree.

// ---- assert_eq_const_safe! ----
//
// Defined: coretests/tests/lib.rs ~line 137
//   macro_rules! assert_eq_const_safe {
//     ($t:ty: $left:expr, $right:expr) => { ... assert_eq!($left, $right) ... }
//   }
// Decision: lower to equality (discard the $t:ty scaffold argument).

#[test]
fn assert_eq_const_safe_lowers_to_equality() {
    // Source-based: the macro_rules! definition is IN SCOPE, so the expander
    // walks into it and lowers `$t: $l, $r` to assert_eq!($l, $r). No hardcoded
    // arm: the lifter recognizes the macro only because it can read its source.
    let src = r#"
macro_rules! assert_eq_const_safe {
    ($t:ty: $left:expr, $right:expr) => { assert_eq!($left, $right) };
}

fn make_val() -> u8 { 42 }

#[test]
fn t() {
    assert_eq_const_safe!(u8: make_val(), 42);
}
"#;
    let out = lift_file(&parse(src), "tests/const_safe.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(
        out.lifted, 1,
        "assert_eq_const_safe! must lift via source expansion; warnings: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    assert_eq_atom(&operands[0], 42);
}

#[test]
fn assert_eq_const_safe_discrimination_does_not_reroute_assert_eq() {
    // assert_eq! in the same file must still lift independently; the new arm
    // must not shadow or absorb the existing assert_eq! arm.
    let src = r#"
fn make_val() -> u8 { 7 }

#[test]
fn t() {
    assert_eq!(make_val(), 7);
}
"#;
    let out = lift_file(&parse(src), "tests/disc.rs");
    assert_eq!(
        out.lifted, 1,
        "plain assert_eq! must still lift; warnings: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 1);
    assert_eq_atom(&operands[0], 7);
}

#[test]
fn assert_eq_const_safe_contradiction_is_unsat() {
    // Two assert_eq_const_safe! calls claiming different values for the same
    // function must produce a contradictory (UNSAT) conjunction, exactly as
    // assert_eq! does. The teeth test confirms we did not accidentally lose
    // the contradiction guard by mis-routing to a wrong lower path.
    let src = r#"
macro_rules! assert_eq_const_safe {
    ($t:ty: $left:expr, $right:expr) => { assert_eq!($left, $right) };
}

fn make_val() -> u8 { 42 }

#[test]
fn t() {
    assert_eq_const_safe!(u8: make_val(), 42);
    assert_eq_const_safe!(u8: make_val(), 99);
}
"#;
    let out = lift_file(&parse(src), "tests/const_safe_contradiction.rs");
    assert_eq!(
        out.lifted, 1,
        "contradiction pair must still lift; warnings: {:?}",
        out.warnings
    );
    assert_eq!(out.decls.len(), 1);
    let operands = inv_operands(&out.decls[0]);
    assert_eq!(operands.len(), 2, "must produce a conjunction of two atoms");
    assert_eq_atom(&operands[0], 42);
    assert_eq_atom(&operands[1], 99);
}

// ---- assert_almost_eq! ----
//
// Defined: std/tests/time.rs (and similar):
//   macro_rules! assert_almost_eq { ($a:expr, $b:expr) => {
//     let (a, b) = ($a, $b);
//     if a != b { assert!((a-b).abs() < Duration::from_micros(200)); }
//   }}
// Decision: HONEST NAMED REFUSAL -- tolerance comparison, not exact equality.

#[test]
fn assert_almost_eq_is_honest_named_refusal() {
    // Source-based: with the real tolerance definition in scope, the expander
    // walks into it and finds the assert lives under an `if a != b { .. }`
    // guard -- a conditional, not a point-wise equality. It is refused (not
    // lifted as a == b, which would be a false-pass). The reason is derived
    // from the real body, not a hardcoded string.
    let src = r#"
macro_rules! assert_almost_eq {
    ($a:expr, $b:expr) => {
        let (a, b) = ($a, $b);
        if a != b {
            assert!(a - b < 200);
        }
    };
}

fn elapsed_ns() -> u64 { 1000 }

#[test]
fn t() {
    assert_almost_eq!(elapsed_ns(), 1000);
}
"#;
    let out = lift_file(&parse(src), "tests/almost_eq.rs");
    assert_eq!(
        out.lifted, 0,
        "assert_almost_eq! must NOT lift (tolerance comparison under a guard)"
    );
    assert!(
        !out.skip_reasons.is_empty(),
        "assert_almost_eq! must be a named refusal, not silent: {:?}",
        out.skip_reasons
    );
}

#[test]
fn assert_almost_eq_discrimination_does_not_affect_assert_eq() {
    // assert_eq! in the same source must still lift normally; the almost_eq
    // refusal arm must not bleed into neighbouring macros.
    let src = r#"
fn get_val() -> i32 { 5 }

#[test]
fn t() {
    assert_eq!(get_val(), 5);
}
"#;
    let out = lift_file(&parse(src), "tests/almost_disc.rs");
    assert_eq!(
        out.lifted, 1,
        "assert_eq! must lift even after almost_eq refusal arm added; warnings: {:?}",
        out.warnings
    );
}

// ---- assert_float_result_bits_eq! ----
//
// Defined: coretests/tests/num/dec2flt/parse.rs ~line 74:
//   macro_rules! assert_float_result_bits_eq {
//     ($bits:literal, $ty:ty, $str:literal) => {{
//       let p = dec2flt::<$ty>($str);
//       assert_eq!(p.map(|x| x.to_bits()), Ok($bits));
//     }};
//   }
// Decision: HONEST NAMED REFUSAL -- result+closure shape, not direct equality.

#[test]
fn assert_float_result_bits_eq_is_honest_named_refusal() {
    // Source-based: with the real definition in scope, the expander walks into
    // it and finds the equality LHS is `p.map(|x| x.to_bits())` -- a method call
    // with a closure argument, not a point-wise term. It is refused, not lifted.
    let src = r#"
macro_rules! assert_float_result_bits_eq {
    ($bits:literal, $ty:ty, $str:literal) => {{
        let p = dec2flt($str);
        assert_eq!(p.map(|x| x.to_bits()), Ok($bits));
    }};
}

fn dec2flt(s: &str) -> u64 { 0 }

#[test]
fn t() {
    assert_float_result_bits_eq!(0x3FF0000000000000u64, f64, "1.0");
}
"#;
    let out = lift_file(&parse(src), "tests/float_bits.rs");
    assert_eq!(
        out.lifted, 0,
        "assert_float_result_bits_eq! must NOT lift (closure in the equality LHS)"
    );
    assert!(
        !out.skip_reasons.is_empty(),
        "assert_float_result_bits_eq! must be a named refusal, not silent: {:?}",
        out.skip_reasons
    );
}

// --- collector totality / named-refusal tranche (T-SILENT) ---

fn refusal_reasons(out: &sugar_lift_rust_tests::AdapterOutput) -> Vec<String> {
    out.skip_reasons.clone()
}

#[test]
fn assert_in_for_loop_is_named_refusal_not_silent() {
    // A loop the lifter cannot read as a clean universal (here a runtime
    // collection, no concrete range to transcribe as a guard) is refused with a
    // "for context" reason, not silently dropped. (A concrete bounded loop with
    // a pure body lifts as a forall instead; see bounded_for_loop_lifts_as_forall.)
    let src = r#"
#[test]
fn loop_test() {
    for i in items {
        assert_eq!(i, i);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/iter.rs");
    assert_eq!(out.seen, 1);
    assert_eq!(
        out.assertions_lifted, 0,
        "non-range loop body assert must not lift"
    );
    assert!(
        refusal_reasons(&out)
            .iter()
            .any(|r| r.contains("for context")),
        "for-loop assert must be a named refusal: {:?}",
        refusal_reasons(&out)
    );
}

#[test]
fn assert_in_if_branch_is_refused_not_lifted() {
    // Soundness: a conditional assert only holds under the guard; lifting it
    // unconditionally would be a false-pass. It must be refused.
    let src = r#"
#[test]
fn cond_test() {
    let c = true;
    if c {
        assert_eq!(1, 2);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/cond.rs");
    assert_eq!(out.assertions_lifted, 0, "conditional assert must not lift");
    assert!(
        out.decls.is_empty(),
        "no discharged row for a conditional assert"
    );
    assert!(
        refusal_reasons(&out)
            .iter()
            .any(|r| r.contains("if context")),
        "if-branch assert must be a named refusal: {:?}",
        refusal_reasons(&out)
    );
}

#[test]
fn assert_in_match_arm_is_refused() {
    let src = r#"
#[test]
fn match_test() {
    let n = 1;
    match n {
        1 => assert_eq!(n, 1),
        _ => assert_eq!(n, 0),
    }
}
"#;
    let out = lift_file(&parse(src), "tests/m.rs");
    assert_eq!(out.assertions_lifted, 0);
    assert!(
        refusal_reasons(&out)
            .iter()
            .any(|r| r.contains("match context")),
        "match-arm assert must be a named refusal: {:?}",
        refusal_reasons(&out)
    );
}

#[test]
fn assert_in_non_test_helper_fn_is_refused() {
    // A non-#[test] helper's assert is reachable only via call-site inlining.
    // When the reducer cannot inline it, it must be a named refusal, not silent.
    let src = r#"
fn helper() {
    assert_eq!(some_runtime_value(), 7);
}

#[test]
fn the_test() {
    assert_eq!(1, 1);
}
"#;
    let out = lift_file(&parse(src), "tests/h.rs");
    assert!(
        refusal_reasons(&out)
            .iter()
            .any(|r| r.contains("non-#[test] item")),
        "helper-fn assert must be a named refusal: {:?}",
        refusal_reasons(&out)
    );
}

#[test]
fn assert_in_unconditional_block_still_lifts() {
    // Discrimination: an unconditional plain block is point-wise; recurse + lift.
    let src = r#"
#[test]
fn block_test() {
    {
        assert_eq!(1, 1);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/b.rs");
    assert_eq!(
        out.assertions_lifted, 1,
        "unconditional block assert must lift"
    );
    assert_eq!(out.decls.len(), 1);
}

#[test]
fn top_level_assert_unchanged_after_totality() {
    // Regression: a plain top-level assert lifts exactly as before.
    let src = r#"
#[test]
fn plain_test() {
    let a = 1;
    assert_eq!(a, 1);
}
"#;
    let out = lift_file(&parse(src), "tests/p.rs");
    assert_eq!(out.assertions_lifted, 1);
    assert_eq!(out.decls.len(), 1);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 1);
}

// --- totality finalization: async / impl-method / let-init refusals ---

#[test]
fn assert_in_async_block_is_refused_not_silent() {
    let src = r#"
#[test]
fn async_test() {
    let _f = async {
        assert_eq!(1, 2);
    };
}
"#;
    let out = lift_file(&parse(src), "tests/future.rs");
    assert_eq!(out.assertions_lifted, 0, "async-block assert must not lift");
    assert!(
        !out.skip_reasons.is_empty(),
        "async-block assert must be accounted (refused), not silent: {:?}",
        out.skip_reasons
    );
}

#[test]
fn assert_in_impl_method_is_refused_not_silent() {
    let src = r#"
struct Helper { done: bool }
impl Helper {
    fn step(&self) {
        assert!(!self.done, "already done");
    }
}

#[test]
fn the_test() {
    assert_eq!(1, 1);
}
"#;
    let out = lift_file(&parse(src), "tests/iter.rs");
    assert!(
        out.skip_reasons.iter().any(|r| r.contains("impl method")),
        "impl-method assert must be a named refusal: {:?}",
        out.skip_reasons
    );
}

#[test]
fn assert_in_let_initializer_is_refused_not_silent() {
    // A CONDITIONAL let-initializer (assert inside a closure) is not a top-level
    // point-wise assertion: it stays a named refusal, not silent. An
    // unconditional value-block let-init is lifted instead (see
    // value_block_let_init_asserts_are_lifted).
    let src = r#"
#[test]
fn let_init_test() {
    let _x = (0..2).map(|i| { assert_eq!(i, 1); i }).count();
}
"#;
    let out = lift_file(&parse(src), "tests/m.rs");
    assert_eq!(
        out.assertions_lifted, 0,
        "conditional let-init assert must not lift"
    );
    assert!(
        !out.skip_reasons.is_empty(),
        "conditional let-init assert must be a named refusal: {:?}",
        out.skip_reasons
    );
}

// --- aggregate element-wise lift tranche (T-AGGREGATE) ---

#[test]
fn tuple_with_non_literal_elements_lifts_as_agg_term() {
    // RED before: a tuple with a call element was refused ("contains non-literal
    // element"). GREEN after: it lifts as agg:Tuple(<element terms>).
    let src = r#"
fn f() -> i32 { 1 }
fn g() -> i32 { 2 }

#[test]
fn tup() {
    assert_eq!((f(), g()), (1, 2));
}
"#;
    let out = lift_file(&parse(src), "tests/t.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 1);
    match ops[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            match args[0].as_ref() {
                Term::Var { name } => assert!(
                    name.starts_with("agg:Tuple("),
                    "non-literal tuple must be an agg term, got {name}"
                ),
                other => panic!("expected agg Var, got {other:?}"),
            }
        }
        other => panic!("expected equality, got {other:?}"),
    }
}

#[test]
fn all_literal_tuple_keeps_literal_key_discrimination() {
    // No regression: an all-literal aggregate keeps the literal: key.
    let src = r#"
#[test]
fn lit_tup() {
    assert_eq!((1, 2), (1, 2));
}
"#;
    let out = lift_file(&parse(src), "tests/t.rs");
    assert_eq!(out.assertions_lifted, 1);
    let ops = inv_operands(&out.decls[0]);
    match ops[0].as_ref() {
        Formula::Atomic { args, .. } => match args[0].as_ref() {
            Term::Var { name } => assert!(
                name.starts_with("literal:Tuple("),
                "all-literal tuple must keep literal key, got {name}"
            ),
            other => panic!("got {other:?}"),
        },
        other => panic!("got {other:?}"),
    }
}

// --- item-level const assertion accounting (totality to zero) ---

#[test]
fn const_item_assertion_is_refused_not_silent() {
    // A compile-time `const _: () = assert!(...)` at item level (inside a module)
    // must be accounted, not silently dropped. This was the last silent-drop
    // class in coretests cmp.rs (mod const_cmp).
    let src = r#"
mod const_cmp {
    struct S(i32);
    const _: () = assert!(1 == 1);
    const _: () = assert!(0 != 1);
}
"#;
    let out = lift_file(&parse(src), "tests/cmp.rs");
    let refused: Vec<_> = out
        .skip_reasons
        .iter()
        .filter(|r| r.contains("const-item assertion"))
        .collect();
    assert_eq!(
        refused.len(),
        2,
        "both const-item asserts must be named refusals: {:?}",
        out.skip_reasons
    );
}

#[test]
fn deeply_nested_assert_is_accounted_by_safety_net() {
    // An assert in an AST position no specific arm enumerates (here, inside a
    // method-call closure argument as a statement) must still be accounted via
    // the exhaustive counter + totality safety net, never silent.
    let src = r#"
#[test]
fn nested() {
    (0..3).for_each(|i| { assert_eq!(i, i); });
}
"#;
    let out = lift_file(&parse(src), "tests/iter.rs");
    assert_eq!(
        out.assertions_lifted, 0,
        "nested closure assert must not lift"
    );
    assert!(
        !out.skip_reasons.is_empty(),
        "nested closure assert must be accounted (refused), not silent: {:?}",
        out.skip_reasons
    );
}

// --- panic-locus lifting tranche ---

fn panic_locus_lhs_rhs(out: &sugar_lift_rust_tests::AdapterOutput) -> (String, String) {
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 1);
    match ops[0].as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "=");
            (format!("{:?}", args[0]), format!("{:?}", args[1]))
        }
        other => panic!("expected equality, got {other:?}"),
    }
}

#[test]
fn panic_guarded_match_lifts_variant_predicate() {
    // RED before: a match with a panic arm was refused "under match context".
    // GREEN after: it lifts variant_of(subject) == "variant::Poll::Ready".
    let src = r#"
#[test]
fn ready() {
    let p = poll_it();
    match p {
        Poll::Ready(v) => v,
        Poll::Pending => panic!("pending"),
    };
}
"#;
    let out = lift_file(&parse(src), "tests/poll.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let (lhs, rhs) = panic_locus_lhs_rhs(&out);
    assert!(
        lhs.contains("variant_of"),
        "lhs must be variant_of(..): {lhs}"
    );
    assert!(
        rhs.contains("Poll::Ready"),
        "rhs must tag Poll::Ready: {rhs}"
    );
}

#[test]
fn panic_locus_ready_vs_pending_same_subject_is_contradiction() {
    // Teeth: asserting the same subject is both Ready and Pending must produce
    // two atoms over the same variant_of(subject) equal to distinct string tags
    // (UNSAT). We verify the shared LHS and the distinct RHS tags.
    let src = r#"
#[test]
fn both() {
    let p = poll_it();
    match p { Poll::Ready(v) => v, Poll::Pending => panic!() };
    match p { Poll::Pending => {}, Poll::Ready(v) => panic!() };
}
"#;
    let out = lift_file(&parse(src), "tests/poll.rs");
    assert_eq!(out.assertions_lifted, 2, "warnings: {:?}", out.skip_reasons);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 2);
    let lhs = |f: &Formula| match f {
        Formula::Atomic { args, .. } => format!("{:?}", args[0]),
        other => panic!("{other:?}"),
    };
    let rhs = |f: &Formula| match f {
        Formula::Atomic { args, .. } => format!("{:?}", args[1]),
        other => panic!("{other:?}"),
    };
    assert_eq!(
        lhs(&ops[0]),
        lhs(&ops[1]),
        "same subject -> same variant_of term"
    );
    assert_ne!(
        rhs(&ops[0]),
        rhs(&ops[1]),
        "Ready vs Pending tags must differ (teeth)"
    );
}

#[test]
fn ordinary_match_without_panic_arm_stays_refused() {
    // Discrimination: a match whose arms do NOT diverge is not a panic-locus
    // assertion; it stays a named refusal, not a (wrong) lift.
    let src = r#"
#[test]
fn plain() {
    let p = thing();
    match p {
        A => do_a(),
        B => do_b(),
    };
}
"#;
    let out = lift_file(&parse(src), "tests/m.rs");
    assert_eq!(out.assertions_lifted, 0, "non-panic match must not lift");
}

#[test]
fn if_let_else_panic_lifts_variant_predicate() {
    let src = r#"
#[test]
fn iflet() {
    let r = compute();
    if let Ok(v) = r {
        let _ = v;
    } else {
        panic!("not ok");
    }
}
"#;
    let out = lift_file(&parse(src), "tests/r.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let (lhs, rhs) = panic_locus_lhs_rhs(&out);
    assert!(lhs.contains("variant_of"), "lhs: {lhs}");
    assert!(rhs.contains("Ok"), "rhs must tag Ok: {rhs}");
}

// --- string predicate over opaque receiver tranche ---

#[test]
fn starts_with_over_opaque_receiver_lifts() {
    // `cid.starts_with("blake3-512:")` where cid is a computed value (not a
    // literal) lifts as prefix-of("blake3-512:", cid) -- the receiver is
    // type-guaranteed a string, so no type info is needed.
    let src = r#"
#[test]
fn t() {
    let cid = compute();
    assert!(cid.starts_with("blake3-512:"));
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let decl = format!("{:?}", out.decls[0]);
    assert!(
        decl.contains("prefix-of") || decl.contains("prefix"),
        "must be prefix-of: {decl}"
    );
    assert!(
        decl.contains("blake3-512:"),
        "must carry the literal prefix: {decl}"
    );
}

// --- bare boolean place tranche (assert!(flag)) ---

#[test]
fn bare_boolean_path_lifts_as_eq_true() {
    // assert!(has_effect) -> has_effect == true (assert! guarantees bool).
    let src = r#"
#[test]
fn t() {
    let has_effect = compute();
    assert!(has_effect);
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let decl = format!("{:?}", out.decls[0]);
    assert!(decl.contains("has_effect"), "must carry the place: {decl}");
    assert!(decl.contains("Bool(true)"), "must equate to true: {decl}");
}

#[test]
fn bare_boolean_true_and_false_over_same_place_is_contradiction() {
    // Teeth: assert!(flag) and assert!(!flag) over the same place are
    // flag==true ∧ flag==false -> UNSAT (distinct RHS over the same LHS).
    let src = r#"
#[test]
fn t() {
    let flag = compute();
    assert!(flag);
    assert!(!flag);
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 2, "warnings: {:?}", out.skip_reasons);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 2);
    // Both atoms are over the same `flag` place: one equates it to true, the
    // negation to false, so the two cannot both hold (flag==true ∧ flag==false).
    let dump = format!("{:?}", out.decls[0]);
    assert!(dump.contains("flag"), "{dump}");
    assert!(
        dump.contains("Bool(true)"),
        "assert!(flag) -> flag==true: {dump}"
    );
    assert!(
        dump.contains("Bool(false)"),
        "assert!(!flag) -> flag==false: {dump}"
    );
}

// --- matches! discriminant tranche (assert!(matches!(x, Type::Variant))) ---

#[test]
fn matches_macro_lifts_variant_predicate() {
    // assert!(matches!(p, Poll::Ready(_))) lifts the SAME discriminant atom a
    // panic-locus match lifts: variant_of(p) == "variant::Poll::Ready".
    let src = r#"
#[test]
fn t() {
    let p = poll_it();
    assert!(matches!(p, Poll::Ready(_)));
}
"#;
    let out = lift_file(&parse(src), "tests/poll.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let (lhs, rhs) = panic_locus_lhs_rhs(&out);
    assert!(
        lhs.contains("variant_of"),
        "lhs must be variant_of(..): {lhs}"
    );
    assert!(
        rhs.contains("Poll::Ready"),
        "rhs must tag Poll::Ready: {rhs}"
    );
}

#[test]
fn matches_macro_struct_pattern_lifts() {
    // A struct pattern with `{ .. }` (the dominant corpus shape) lifts the
    // discriminant; the value-subpattern is ignored (we lift the weaker,
    // always-implied discriminant fact).
    let src = r#"
#[test]
fn t() {
    let rhs = build();
    assert!(matches!(rhs, IrTerm::Let { .. }));
}
"#;
    let out = lift_file(&parse(src), "tests/lift.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let (lhs, tag) = panic_locus_lhs_rhs(&out);
    assert!(lhs.contains("variant_of"), "lhs: {lhs}");
    assert!(
        tag.contains("IrTerm::Let"),
        "rhs must tag IrTerm::Let: {tag}"
    );
}

#[test]
fn matches_macro_ready_vs_pending_is_contradiction() {
    // Teeth: claiming the same subject matches two distinct variants yields two
    // atoms over the same variant_of(subject) with distinct string tags (UNSAT).
    let src = r#"
#[test]
fn t() {
    let p = poll_it();
    assert!(matches!(p, Poll::Ready(_)));
    assert!(matches!(p, Poll::Pending));
}
"#;
    let out = lift_file(&parse(src), "tests/poll.rs");
    assert_eq!(out.assertions_lifted, 2, "warnings: {:?}", out.skip_reasons);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 2);
    let lhs = |f: &Formula| match f {
        Formula::Atomic { args, .. } => format!("{:?}", args[0]),
        other => panic!("{other:?}"),
    };
    let rhs = |f: &Formula| match f {
        Formula::Atomic { args, .. } => format!("{:?}", args[1]),
        other => panic!("{other:?}"),
    };
    assert_eq!(
        lhs(&ops[0]),
        lhs(&ops[1]),
        "same subject -> same variant_of term"
    );
    assert_ne!(
        rhs(&ops[0]),
        rhs(&ops[1]),
        "Ready vs Pending tags must differ (teeth)"
    );
}

#[test]
fn matches_macro_negation_lifts_negated_predicate() {
    // assert!(!matches!(p, Poll::Pending)) lifts the negation of the discriminant
    // atom (routed through the existing Unary(Not) path).
    let src = r#"
#[test]
fn t() {
    let p = poll_it();
    assert!(!matches!(p, Poll::Pending));
}
"#;
    let out = lift_file(&parse(src), "tests/poll.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let decl = format!("{:?}", out.decls[0]);
    assert!(decl.contains("variant_of"), "must carry variant_of: {decl}");
    assert!(
        decl.contains("Poll::Pending"),
        "must tag Poll::Pending: {decl}"
    );
    assert!(
        decl.contains("\"not\""),
        "must be a negated (not-connective) atom: {decl}"
    );
}

#[test]
fn matches_macro_with_guard_lifts_discriminant() {
    // A passing `matches!(p, Poll::Ready(v) if v > 0)` means p matched
    // Poll::Ready AND v>0, so the discriminant variant_of(p)=="variant::Poll::Ready"
    // is IMPLIED. We lift that (sound, weaker) fact and drop the guard; the
    // single-pattern matches! macro has none of the multi-arm ambiguity that makes
    // panic-locus refuse guards.
    let src = r#"
#[test]
fn t() {
    let p = poll_it();
    assert!(matches!(p, Poll::Ready(v) if v > 0));
}
"#;
    let out = lift_file(&parse(src), "tests/poll.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let (lhs, rhs) = panic_locus_lhs_rhs(&out);
    assert!(
        lhs.contains("variant_of"),
        "lhs must be variant_of(..): {lhs}"
    );
    assert!(
        rhs.contains("Poll::Ready"),
        "rhs must tag Poll::Ready: {rhs}"
    );
}

#[test]
fn matches_macro_binding_pattern_refused_by_name() {
    // Discrimination: a single-segment lowercase pattern is a catch-all BINDING
    // (always matches), not an unambiguous variant. Refused by name.
    let src = r#"
#[test]
fn t() {
    let p = poll_it();
    assert!(matches!(p, anything));
}
"#;
    let out = lift_file(&parse(src), "tests/poll.rs");
    assert_eq!(out.assertions_lifted, 0, "binding matches! must not lift");
    assert!(
        out.skip_reasons
            .iter()
            .any(|r| r.contains("unambiguous qualified variant")),
        "refusal must name the ambiguity: {:?}",
        out.skip_reasons
    );
}

#[test]
fn matches_macro_nested_some_lifts_inner_discriminant() {
    // matches!(x, Some(Decision::Widen { .. })) lifts BOTH the outer Some
    // discriminant and the inner Widen discriminant (the meaningful claim).
    let src = r#"
#[test]
fn t() {
    let d = lookup();
    assert!(matches!(d, Some(Decision::Widen { .. })));
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let decl = format!("{:?}", out.decls[0]);
    assert!(
        decl.contains("variant::Some"),
        "outer Some discriminant: {decl}"
    );
    assert!(decl.contains("payload:Some"), "payload accessor: {decl}");
    assert!(
        decl.contains("variant::Decision::Widen"),
        "inner discriminant: {decl}"
    );
}

#[test]
fn matches_macro_nested_some_distinct_inner_is_contradiction() {
    // Teeth: same subject claimed Some(Widen) AND Some(Halt) -> two atoms over the
    // same payload:Some(d) with distinct inner tags -> UNSAT.
    let src = r#"
#[test]
fn t() {
    let d = lookup();
    assert!(matches!(d, Some(Decision::Widen { .. })));
    assert!(matches!(d, Some(Decision::Halt { .. })));
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 2, "warnings: {:?}", out.skip_reasons);
    let decl = format!("{:?}", out.decls[0]);
    assert!(decl.contains("Decision::Widen"), "Widen present: {decl}");
    assert!(decl.contains("Decision::Halt"), "Halt present: {decl}");
}

#[test]
fn matches_macro_some_wildcard_lifts_outer_only() {
    // matches!(x, Some(_)) pins only that x is Some (no inner discriminant).
    let src = r#"
#[test]
fn t() {
    let d = lookup();
    assert!(matches!(d, Some(_)));
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let (lhs, rhs) = panic_locus_lhs_rhs(&out);
    assert!(lhs.contains("variant_of"), "lhs: {lhs}");
    assert!(rhs.contains("variant::Some"), "rhs must tag Some: {rhs}");
}

// --- array-repeat literal tranche (assert_eq!(x, [elem; N])) ---

#[test]
fn array_repeat_literal_is_congruent_to_explicit_array() {
    // `[0xab; 3]` is the same value as `[0xab, 0xab, 0xab]` -> the SAME term.
    let repeat = r#"
#[test]
fn t() { let x = mk(); assert_eq!(x, [0xabu8; 3]); }
"#;
    let explicit = r#"
#[test]
fn t() { let x = mk(); assert_eq!(x, [0xabu8, 0xabu8, 0xabu8]); }
"#;
    let dr = format!("{:?}", lift_file(&parse(repeat), "src/x.rs").decls[0]);
    let de = format!("{:?}", lift_file(&parse(explicit), "src/x.rs").decls[0]);
    assert_eq!(
        dr, de,
        "[e; N] must lift congruently to the N-fold explicit array"
    );
}

#[test]
fn array_repeat_distinct_elems_are_contradiction() {
    // Teeth: the same subject equated to two distinct repeats yields distinct
    // RHS terms over the same LHS (UNSAT).
    let src = r#"
#[test]
fn t() {
    let x = mk();
    assert_eq!(x, [0xabu8; 4]);
    assert_eq!(x, [0xcdu8; 4]);
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 2, "warnings: {:?}", out.skip_reasons);
    let ops = inv_operands(&out.decls[0]);
    let rhs = |f: &Formula| match f {
        Formula::Atomic { args, .. } => format!("{:?}", args[1]),
        other => panic!("{other:?}"),
    };
    assert_ne!(
        rhs(&ops[0]),
        rhs(&ops[1]),
        "0xab vs 0xcd repeats must differ (teeth)"
    );
}

#[test]
fn array_repeat_nonliteral_length_refused_by_name() {
    // Discrimination: a const/path length is not a finite construction -> refused.
    let src = r#"
#[test]
fn t() {
    const LEN: usize = 32;
    let x = mk();
    assert_eq!(x, [0u8; LEN]);
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(
        out.assertions_lifted, 0,
        "non-literal-length repeat must not lift"
    );
    assert!(
        out.skip_reasons
            .iter()
            .any(|r| r.contains("non-literal length")),
        "refusal must name the non-literal length: {:?}",
        out.skip_reasons
    );
}

// --- struct-literal equality tranche (assert_eq!(x, Type { f: v })) ---

#[test]
fn struct_literal_equality_lifts() {
    // assert_eq!(s, Sort::Primitive { name: "Int" }) lifts the RHS as a Ctor
    // term keyed by the path with a sorted field sub-ctor.
    let src = r#"
#[test]
fn t() {
    let s = translate();
    assert_eq!(s, Sort::Primitive { name: "Int" });
}
"#;
    let out = lift_file(&parse(src), "src/sort_translate.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
    let decl = format!("{:?}", out.decls[0]);
    assert!(decl.contains("struct:Sort::Primitive"), "ctor name: {decl}");
    assert!(decl.contains("field:name"), "field sub-ctor: {decl}");
    assert!(decl.contains("Int"), "field value: {decl}");
}

#[test]
fn struct_literal_field_order_is_canonical() {
    // Same value, different source field order -> SAME term (fields sorted).
    let a = r#"
#[test]
fn t() { let s = f(); assert_eq!(s, Pair { a: 1, b: 2 }); }
"#;
    let b = r#"
#[test]
fn t() { let s = f(); assert_eq!(s, Pair { b: 2, a: 1 }); }
"#;
    let da = format!("{:?}", lift_file(&parse(a), "src/x.rs").decls[0]);
    let db = format!("{:?}", lift_file(&parse(b), "src/x.rs").decls[0]);
    assert_eq!(da, db, "field order must not change the canonical term");
}

#[test]
fn struct_literal_distinct_variants_are_contradiction() {
    // Teeth: the same subject equated to two distinct struct literals yields two
    // distinct Ctor RHS terms over the same LHS (UNSAT).
    let src = r#"
#[test]
fn t() {
    let s = f();
    assert_eq!(s, Sort::Primitive { name: "Int" });
    assert_eq!(s, Sort::Primitive { name: "Bool" });
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 2, "warnings: {:?}", out.skip_reasons);
    let ops = inv_operands(&out.decls[0]);
    assert_eq!(ops.len(), 2);
    let rhs = |f: &Formula| match f {
        Formula::Atomic { args, .. } => format!("{:?}", args[1]),
        other => panic!("{other:?}"),
    };
    assert_ne!(
        rhs(&ops[0]),
        rhs(&ops[1]),
        "Int vs Bool literals must differ (teeth)"
    );
}

#[test]
fn struct_literal_with_rest_refused_by_name() {
    // Discrimination: `..base` means the value is not fully pinned -> refused.
    let src = r#"
#[test]
fn t() {
    let base = mk();
    let s = f();
    assert_eq!(s, Config { name: "x", ..base });
}
"#;
    let out = lift_file(&parse(src), "src/x.rs");
    assert_eq!(out.assertions_lifted, 0, "..rest struct must not lift");
    assert!(
        out.skip_reasons
            .iter()
            .any(|r| r.contains("..rest") || r.contains("not fully pinned")),
        "refusal must name the ..rest: {:?}",
        out.skip_reasons
    );
}

// --- unconditional-block recursion (block_on / value-block) tranche ---

#[test]
fn block_on_async_asserts_are_lifted() {
    // rt.block_on(async { .. }) runs the future to completion once; its
    // top-level asserts are unconditional and lift.
    let src = r#"
#[test]
fn t() {
    rt.block_on(async {
        assert_eq!(compute(), 1);
    });
}
"#;
    let out = lift_file(&parse(src), "tests/rt.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
}

#[test]
fn value_block_let_init_asserts_are_lifted() {
    let src = r#"
#[test]
fn t() {
    let _x = {
        assert_eq!(compute(), 1);
        5
    };
}
"#;
    let out = lift_file(&parse(src), "tests/v.rs");
    assert_eq!(out.assertions_lifted, 1, "warnings: {:?}", out.skip_reasons);
}

#[test]
fn spawned_async_assert_stays_refused() {
    // A spawned future may never run: its asserts are NOT unconditional and
    // must stay refused, not lifted (false-pass guard).
    let src = r#"
#[test]
fn t() {
    tokio::spawn(async {
        assert_eq!(compute(), 1);
    });
}
"#;
    let out = lift_file(&parse(src), "tests/s.rs");
    assert_eq!(
        out.assertions_lifted, 0,
        "spawned async assert must not lift"
    );
    assert!(
        !out.skip_reasons.is_empty(),
        "spawned async assert must be accounted (refused): {:?}",
        out.skip_reasons
    );
}

#[test]
fn closure_arg_assert_stays_refused() {
    let src = r#"
#[test]
fn t() {
    let _x = (0..3).map(|i| { assert_eq!(i, i); i }).count();
}
"#;
    let out = lift_file(&parse(src), "tests/c.rs");
    assert_eq!(out.assertions_lifted, 0, "closure assert must not lift");
}

// --- bounded loop -> universal quantifier (L5) ---

fn inv_formula(decl: &sugar_ir_symbolic::ContractDecl) -> std::rc::Rc<Formula> {
    decl.inv.clone().expect("decl has inv")
}

fn contains_forall(f: &Formula) -> bool {
    match f {
        Formula::Quantifier { kind, body, .. } => kind == "forall" || contains_forall(body),
        Formula::Connective { operands, .. } => operands.iter().any(|o| contains_forall(o)),
        _ => false,
    }
}

#[test]
fn bounded_for_loop_lifts_as_forall() {
    // for x in 0..3 { assert_eq!(g(x), 1) } reads as forall x. (0<=x<3 => g(x)==1).
    let src = r#"
#[test]
fn t() {
    for x in 0..3 {
        assert_eq!(g(x), 1);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/loop.rs");
    assert_eq!(
        out.assertions_lifted, 1,
        "loop must lift; warnings: {:?}",
        out.skip_reasons
    );
    assert_eq!(out.decls.len(), 1);
    assert!(
        contains_forall(&inv_formula(&out.decls[0])),
        "lifted loop must contain a forall quantifier"
    );
}

#[test]
fn for_loop_over_runtime_collection_stays_refused() {
    // No concrete range to transcribe as a guard: gutter (refused), not lifted.
    let src = r#"
#[test]
fn t() {
    for x in items {
        assert_eq!(g(x), 1);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/loop.rs");
    assert_eq!(out.assertions_lifted, 0, "non-range loop must stay refused");
}

#[test]
fn for_loop_with_mutated_accumulator_body_stays_refused() {
    // The body does not compute to a truth value of x (count is mutated across
    // iterations): gutter the whole loop rather than emit a false universal.
    let src = r#"
#[test]
fn t() {
    let mut count = 0;
    for x in 0..3 {
        count = count + 1;
        assert_eq!(count, x);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/loop.rs");
    assert_eq!(
        out.assertions_lifted, 0,
        "mutated-accumulator loop must not lift as forall"
    );
}

#[test]
fn for_loop_over_literal_array_unrolls() {
    // `for x in [1, 2, 3] { assert_eq!(g(x), 1) }` is the FINITE conjunction
    // g(1)==1 ∧ g(2)==1 ∧ g(3)==1 -- a complete unroll over the constructed
    // element terms, each instance concrete (full point-wise teeth).
    let src = r#"
#[test]
fn t() {
    for x in [1, 2, 3] {
        assert_eq!(g(x), 1);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/loop.rs");
    assert_eq!(
        out.assertions_lifted, 1,
        "literal-array loop must lift; warnings: {:?}",
        out.skip_reasons
    );
    let decl = format!("{:?}", out.decls[0]);
    // All three concrete instances must be present (the unroll substituted x).
    assert!(decl.contains("Int(1)"), "instance x=1 missing: {decl}");
    assert!(decl.contains("Int(2)"), "instance x=2 missing: {decl}");
    assert!(decl.contains("Int(3)"), "instance x=3 missing: {decl}");
    // It is a finite conjunction, NOT a forall (the domain is enumerated).
    assert!(
        !contains_forall(&inv_formula(&out.decls[0])),
        "literal-array unroll is a conjunction, not a forall: {decl}"
    );
}

#[test]
fn for_loop_over_empty_array_not_lifted() {
    // An empty array means the loop never runs -> nothing asserted (vacuous);
    // leave it to the refusal path rather than emit a vacuous `true`.
    let src = r#"
#[test]
fn t() {
    for x in [] {
        assert_eq!(g(x), 1);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/loop.rs");
    assert_eq!(out.assertions_lifted, 0, "empty-array loop must not lift");
}

#[test]
fn for_loop_over_opaque_collection_names_bin2_provenance() {
    // A runtime collection is refused WITH provenance: the refusal names it an
    // OPAQUE collection (bin-2), so the bin classifier can prove (not presume) it.
    let src = r#"
#[test]
fn t() {
    for x in items {
        assert_eq!(g(x), 1);
    }
}
"#;
    let out = lift_file(&parse(src), "tests/loop.rs");
    assert_eq!(out.assertions_lifted, 0, "opaque loop must stay refused");
    assert!(
        out.skip_reasons
            .iter()
            .any(|r| r.contains("OPAQUE collection")),
        "refusal must name the opaque-collection provenance: {:?}",
        out.skip_reasons
    );
}

// ── Source-audit value-contract emission (emit_value_contract) ──────────────
// A warrant is real only if the kit EMITS the ProofIR. These pin the slice-1
// char-class predicate emitter: matches! body -> `out <-> membership` contract.

#[test]
fn emit_value_contract_emits_char_class_predicate() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn =
        syn::parse_str("fn is_up(c: char) -> bool { matches!(c, 'A'..='Z') }").unwrap();
    let decl = emit_value_contract("is_up", &f.block).expect("char-class body emits a contract");
    assert_eq!(decl.out_binding, "out");
    let inv = format!("{:?}", decl.inv.expect("inv present"));
    // bounds are the code points of 'A' (65) and 'Z' (90), and `out` is related.
    assert!(inv.contains("65"), "lower bound 'A'=65 present: {inv}");
    assert!(inv.contains("90"), "upper bound 'Z'=90 present: {inv}");
    assert!(inv.contains("out"), "return value `out` is related: {inv}");
    assert!(inv.contains("implies"), "biconditional via implies: {inv}");
}

#[test]
fn emit_value_contract_handles_or_of_matches() {
    use sugar_lift_rust_tests::emit_value_contract;
    // core's is_ascii_alphanumeric shape: OR of three matches! predicates.
    let f: syn::ItemFn = syn::parse_str(
        "fn alnum(c: char) -> bool { matches!(c, '0'..='9') | matches!(c, 'A'..='Z') | matches!(c, 'a'..='z') }",
    )
    .unwrap();
    let decl = emit_value_contract("alnum", &f.block).expect("OR-of-matches emits");
    let inv = format!("{:?}", decl.inv.expect("inv present"));
    for cp in ["48", "57", "65", "90", "97", "122"] {
        assert!(inv.contains(cp), "alnum bound {cp} present: {inv}");
    }
}

#[test]
fn emit_value_contract_refuses_unemittable_bodies() {
    use sugar_lift_rust_tests::emit_value_contract;
    // A panic method (unwrap -> divergence), a mutating multi-statement body, and
    // a guarded matches! over a NESTED pattern (match_arm_discriminant refuses
    // nested binders -> ambiguous payload positions) are NOT emittable here ->
    // None, so the caller routes them to effect_refusal/unclassified (never a
    // hollow warrant). (Value-position calls like v.len() DO emit as EUF; a
    // dead-let prefix + liftable tail DOES warrant; a guarded matches! over a
    // FLAT pattern with a pure-predicate guard DOES warrant -- see the
    // guarded-matches tests below.)
    for src in [
        "fn f(r: Result<i32, ()>) -> i32 { r.unwrap() }",
        "fn f(p: Option<Result<i32, ()>>) -> bool { matches!(p, Some(Ok(n)) if n > 0) }",
        "fn f(x: i32) -> i32 { let mut a = x; a += 1; a }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        assert!(
            emit_value_contract("f", &f.block).is_none(),
            "must not emit a contract for: {src}"
        );
    }
}

// Step 7: the emitted relation must actually COMPOSE -- compile to SMT-LIB and
// be well-sorted + consistent under z3 -- not merely classify. This feeds the
// REAL marshalled bytes of emit_value_contract through the same compiler the
// prove path uses.
#[test]
fn emit_value_contract_char_class_composes_through_compiler() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn =
        syn::parse_str("fn is_up(c: char) -> bool { matches!(c, 'A'..='Z') }").unwrap();
    let decl = emit_value_contract("is_up", &f.block).unwrap();
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();

    // 1) it compiles to SMT-LIB (composes), not a vacuous/ill-sorted classify.
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("emitted char-class inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);

    // 2) z3 (if present) must find it well-sorted and SATISFIABLE: the relation
    //    out <-> (65 <= c <= 90) is consistent (real teeth, not a contradiction).
    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_char_class_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3)
            .arg(&path)
            .output()
            .expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "emitted relation must be well-sorted for z3:\n{stdout}\n--- script ---\n{script}"
        );
        assert!(
            stdout.contains("sat"),
            "emitted consistency relation must be satisfiable:\n{stdout}\n--- script ---\n{script}"
        );
    }
}

// Slice 17: STRING-literal `matches!` membership. core/std are full of pure
// `fn is_x(name: &str) -> bool { matches!(name, "a" | "b" | ..) }` predicates --
// `is_io_method`, `is_known_pure_method`, `is_panic_leaf` are this exact shape.
// They are side-effect-free (a pattern match over a &str against string
// literals), so they WARRANT as `out <-> (name == "a" \/ name == "b" \/ ..)` in
// the compiler's String-theory regime. Before this slice the membership emitter
// only handled char/byte/int code points, so a string scrutinee fell out as a
// hollow `opaque macro matches!` unclassified locus.
#[test]
fn emit_value_contract_string_matches_membership_warrants() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str(
        "fn is_io(name: &str) -> bool { matches!(name, \"write\" | \"write_all\" | \"read\") }",
    )
    .unwrap();
    let decl = emit_value_contract("is_io", &f.block).expect("string-membership body emits");
    assert_eq!(decl.out_binding, "out");
    let inv = format!("{:?}", decl.inv.expect("inv present"));
    for lit in ["write", "write_all", "read"] {
        assert!(inv.contains(lit), "membership literal {lit} present: {inv}");
    }
    assert!(inv.contains("out"), "return value `out` is related: {inv}");
    assert!(inv.contains("implies"), "biconditional via implies: {inv}");
}

// Step 7 for string membership: the emitted relation must COMPOSE through the
// real compiler -- well-sorted under z3's String theory AND satisfiable (the
// scrutinee can be one of the literals -> out=true, or anything else -> out=false:
// real teeth, not a contradiction).
#[test]
fn emit_value_contract_string_matches_composes_through_compiler() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str(
        "fn is_io(name: &str) -> bool { matches!(name, \"write\" | \"write_all\" | \"read\") }",
    )
    .unwrap();
    let decl = emit_value_contract("is_io", &f.block).unwrap();
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();

    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("emitted string-membership inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);

    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_string_matches_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3)
            .arg(&path)
            .output()
            .expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "emitted string-membership relation must be well-sorted for z3:\n{stdout}\n--- script ---\n{script}"
        );
        assert!(
            stdout.contains("sat"),
            "emitted string-membership relation must be satisfiable:\n{stdout}\n--- script ---\n{script}"
        );
    }
}

// Slice 18: GUARDED `matches!` (matches!(x, Pat if guard)). Pervasive in core:
// matches!(token, TokenTree::Punct(p) if p.as_char() == ',') and friends. The
// match is side-effect-free (pattern test + a pure guard predicate), so it
// warrants `out <-> (variant_of(x) == "variant::Pat" /\ guard[p := payload(x)])`
// -- the discriminant conjoined with the guard, with the pattern binding mapped
// to its payload accessor via the SAME match_arm_discriminant machinery a value
// `match` uses. A nested pattern or a non-predicate guard stays None (refused).
#[test]
fn emit_value_contract_guarded_matches_warrants() {
    use sugar_lift_rust_tests::emit_value_contract;
    // A flat enum-variant pattern with a pure comparison guard over the binding.
    let f: syn::ItemFn = syn::parse_str(
        "fn pos(p: Option<i32>) -> bool { matches!(p, Some(n) if n > 0) }",
    )
    .unwrap();
    let decl = emit_value_contract("pos", &f.block).expect("guarded matches! warrants");
    assert_eq!(decl.out_binding, "out");
    let inv = format!("{:?}", decl.inv.expect("inv present"));
    assert!(inv.contains("variant_of"), "discriminant present: {inv}");
    assert!(inv.contains("payload:"), "binding mapped to payload accessor: {inv}");
    assert!(inv.contains("out"), "return value related: {inv}");
}

// Discrimination: a binding-only catch-all guard (matches!(v, x if x == 5))
// reduces to `out <-> v == 5` -- the binding maps straight to the scrutinee, no
// variant discriminant. This is the shape that USED to be refused (a guard was a
// blanket None) and now warrants, because the guard is a pure predicate.
#[test]
fn emit_value_contract_guarded_matches_binding_only_warrants() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn =
        syn::parse_str("fn isfive(v: i32) -> bool { matches!(v, x if x == 5) }").unwrap();
    let decl = emit_value_contract("isfive", &f.block).expect("binding-only guard warrants");
    let inv = format!("{:?}", decl.inv.expect("inv present"));
    // the guard reduces to v == 5 (the binding x maps straight to v, no variant_of).
    assert!(inv.contains('5'), "guard reduced to v == 5: {inv}");
    assert!(!inv.contains("variant_of"), "no discriminant for a binding pattern: {inv}");
}

// Step 7 for guarded matches!: the emitted relation must COMPOSE -- well-sorted
// under z3 AND satisfiable (real teeth: some p makes it true, some false).
#[test]
fn emit_value_contract_guarded_matches_composes_through_compiler() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str(
        "fn pos(p: Option<i32>) -> bool { matches!(p, Some(n) if n > 0) }",
    )
    .unwrap();
    let decl = emit_value_contract("pos", &f.block).unwrap();
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();

    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("emitted guarded-matches inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);

    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_guarded_matches_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3)
            .arg(&path)
            .output()
            .expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "emitted guarded-matches relation must be well-sorted for z3:\n{stdout}\n--- script ---\n{script}"
        );
        assert!(
            stdout.contains("sat"),
            "emitted guarded-matches relation must be satisfiable:\n{stdout}\n--- script ---\n{script}"
        );
    }
}

// Slice 19: UNGUARDED enum-variant `matches!` (matches!(x, Enum::Variant(..))).
// The ubiquitous discriminator predicate -- is_ipv4 { matches!(self, IpAddr::V4(_)) },
// is_some, is_ok, ... The unguarded membership path only handled scalar/string
// code points; an enum-variant pattern fell through to a hollow "opaque macro
// matches!" unclassified. Route it (when scalar membership is None) through
// match_arm_discriminant -> `out <-> variant_of(x) == "variant::Variant"`.
#[test]
fn emit_value_contract_unguarded_enum_variant_matches_warrants() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str(
        "fn is_v4(s: &IpKind) -> bool { matches!(s, IpKind::V4(_)) }",
    )
    .unwrap();
    let decl = emit_value_contract("is_v4", &f.block).expect("enum-variant matches! warrants");
    let inv = format!("{:?}", decl.inv.expect("inv present"));
    assert!(inv.contains("variant_of"), "discriminant present: {inv}");
    assert!(inv.contains("V4"), "the matched variant tag is present: {inv}");
}

// Discrimination: is_v4 and is_v6 over the same subject are DISTINCT discriminants
// (variant::V4 vs variant::V6), and a bare binding/wildcard pattern (always
// matches -> no teeth) stays None.
#[test]
fn emit_value_contract_unguarded_enum_variant_discrimination() {
    use sugar_lift_rust_tests::emit_value_contract;
    let v4: syn::ItemFn =
        syn::parse_str("fn f(s: &IpKind) -> bool { matches!(s, IpKind::V4(_)) }").unwrap();
    let v6: syn::ItemFn =
        syn::parse_str("fn f(s: &IpKind) -> bool { matches!(s, IpKind::V6(_)) }").unwrap();
    let i4 = format!("{:?}", emit_value_contract("f", &v4.block).unwrap().inv.unwrap());
    let i6 = format!("{:?}", emit_value_contract("f", &v6.block).unwrap().inv.unwrap());
    assert!(i4.contains("V4") && !i4.contains("V6"), "v4 discriminant: {i4}");
    assert!(i6.contains("V6") && !i6.contains("V4"), "v6 discriminant: {i6}");
    // a bare binding pattern is always-true (vacuous) -> not warranted.
    let bind: syn::ItemFn =
        syn::parse_str("fn f(s: &IpKind) -> bool { matches!(s, _anything) }").unwrap();
    assert!(
        emit_value_contract("f", &bind.block).is_none(),
        "a vacuous always-matching pattern must not warrant"
    );
}

#[test]
fn emit_value_contract_unguarded_enum_variant_composes_through_compiler() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str(
        "fn is_v4(s: &IpKind) -> bool { matches!(s, IpKind::V4(_)) }",
    )
    .unwrap();
    let decl = emit_value_contract("is_v4", &f.block).unwrap();
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();

    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("emitted enum-variant inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);

    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_enum_variant_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3).arg(&path).output().expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "enum-variant relation must be well-sorted for z3:\n{stdout}\n--- {script}"
        );
        assert!(
            stdout.contains("sat"),
            "enum-variant relation must be satisfiable:\n{stdout}\n--- {script}"
        );
    }
}

// Slice 20: `char` cast (`x as char`, `(*self as u8) as char`). translate_term
// handled integer-scalar casts but not `as char`, so core's char-conversion
// bodies (to_ascii_uppercase/lowercase: if cond { (*self as u8).f() as char }
// else { *self }) fell out at the cast. `as char` is a pure code-point
// conversion -> the opaque EUF ctor cast:char(x), same standard as the integer
// casts, Int/opaque regime so it composes.
#[test]
fn emit_value_contract_char_cast_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    // a bare char cast, and the to_ascii_uppercase shape (if + nested casts).
    let f: syn::ItemFn = syn::parse_str(
        "fn up(c: char) -> char { if c.is_ascii_lowercase() { (c as u8) as char } else { c } }",
    )
    .unwrap();
    let decl = emit_value_contract("up", &f.block).expect("char-cast if-body warrants");
    let inv_dbg = format!("{:?}", decl.inv.clone().expect("inv present"));
    assert!(inv_dbg.contains("cast:char"), "char cast ctor present: {inv_dbg}");
    assert!(inv_dbg.contains("cast:u8"), "nested u8 cast ctor present: {inv_dbg}");

    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("char-cast inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_char_cast_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3).arg(&path).output().expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "char-cast relation must be well-sorted for z3:\n{stdout}\n--- {script}"
        );
        assert!(stdout.contains("sat"), "char-cast relation must be satisfiable:\n{stdout}\n--- {script}");
    }
}

// Discrimination: a cast to a NON-scalar/unhandled target (e.g. `as *const T`)
// stays unemittable -> None (never a hollow warrant over an opaque pointer cast).
#[test]
fn emit_value_contract_unhandled_cast_refused() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn =
        syn::parse_str("fn p(x: &u8) -> *const u8 { x as *const u8 }").unwrap();
    assert!(
        emit_value_contract("p", &f.block).is_none(),
        "a raw-pointer cast must not warrant"
    );
}

// Slice 21: early-return GUARD CLAUSE -- `(if COND { return RET; })+ TAIL`. The
// ?/let-else family of bin-1: a guard-clause body is semantically
// `if COND { RET } else { TAIL }`, so it warrants with the value-if encoding:
// out==RET under COND (and earlier guards negated), out==TAIL under all negated.
// Plus unary negation of a non-literal (`-x` -> 0 - x) which a guard tail like
// `{ if a > 0 { return a; } -a }` needs.
#[test]
fn emit_value_contract_guard_return_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str(
        "fn sign(a: i32) -> i32 { if a > 0 { return 1; } if a < 0 { return 2; } 0 }",
    )
    .unwrap();
    let decl = emit_value_contract("sign", &f.block).expect("guard-clause body warrants");
    let inv_dbg = format!("{:?}", decl.inv.clone().expect("inv present"));
    assert!(inv_dbg.contains("implies"), "guard clauses encode via implies: {inv_dbg}");
    assert!(inv_dbg.contains("out"), "return value related: {inv_dbg}");

    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("guard-clause inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_guard_return_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3).arg(&path).output().expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "guard-clause relation must be well-sorted for z3:\n{stdout}\n--- {script}"
        );
        assert!(stdout.contains("sat"), "guard-clause relation must be satisfiable:\n{stdout}");
    }
}

// Unary negation of a non-literal: `{ if a > 0 { return a; } -a }` -- the guard
// returns a, the tail is `-a` (0 - a). Warrants now (was refused: unary neg of a
// non-literal had no term).
#[test]
fn emit_value_contract_unary_neg_tail_warrants() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn =
        syn::parse_str("fn abs_ish(a: i32) -> i32 { if a > 0 { return a; } -a }").unwrap();
    let decl = emit_value_contract("abs_ish", &f.block).expect("unary-neg guard tail warrants");
    assert!(decl.inv.is_some(), "inv present");
}

// Discrimination: a guard clause whose TAIL is not an EUF value (e.g. a mutating
// or unmodelable tail) stays None -- never a partial/hollow warrant.
#[test]
fn emit_value_contract_guard_return_non_value_tail_refused() {
    use sugar_lift_rust_tests::emit_value_contract;
    // tail is a loop expression (not an EUF value) -> None.
    let f: syn::ItemFn = syn::parse_str(
        "fn f(a: i32) -> i32 { if a > 0 { return a; } loop { } }",
    )
    .unwrap();
    assert!(
        emit_value_contract("f", &f.block).is_none(),
        "a non-value guard tail must not warrant"
    );
}

// Slice 22: array/slice-pattern `matches!` (matches!(scrut, [169, 254, ..])).
// core::net is full of these -- is_documentation { matches!(self.octets(),
// [192, 0, 2, _]) }, is_link_local { matches!(self.octets(), [169, 254, ..]) }.
// Pure: an array pattern test over a (method-call) scrutinee. Warrants as the
// conjunction of fixed-front positions: index(scrut, i) == lit, over the
// existing `index` accessor. Trailing `..` leaves the rest unconstrained.
#[test]
fn emit_value_contract_slice_pattern_matches_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str(
        "fn is_doc(o: [u8; 4]) -> bool { matches!(o, [192, 0, 2, _]) }",
    )
    .unwrap();
    let decl = emit_value_contract("is_doc", &f.block).expect("slice-pattern matches! warrants");
    let inv_dbg = format!("{:?}", decl.inv.clone().expect("inv present"));
    assert!(inv_dbg.contains("index"), "index accessor present: {inv_dbg}");
    for lit in ["192", "2"] {
        assert!(inv_dbg.contains(lit), "fixed byte {lit} present: {inv_dbg}");
    }

    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("slice-pattern inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_slice_pattern_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3).arg(&path).output().expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "slice-pattern relation must be well-sorted for z3:\n{stdout}\n--- {script}"
        );
        assert!(stdout.contains("sat"), "slice-pattern relation must be satisfiable:\n{stdout}");
    }
}

// Discrimination: a trailing `..` is fine (front-indexed), but a NON-trailing
// rest (`[.., 1]`, back-indexing) and an all-wildcard pattern (no teeth) stay
// None.
#[test]
fn emit_value_contract_slice_pattern_discrimination() {
    use sugar_lift_rust_tests::emit_value_contract;
    let trailing: syn::ItemFn =
        syn::parse_str("fn f(o: [u8; 4]) -> bool { matches!(o, [169, 254, ..]) }").unwrap();
    assert!(
        emit_value_contract("f", &trailing.block).is_some(),
        "trailing-rest slice pattern warrants"
    );
    let leading: syn::ItemFn =
        syn::parse_str("fn f(o: [u8; 4]) -> bool { matches!(o, [.., 1]) }").unwrap();
    assert!(
        emit_value_contract("f", &leading.block).is_none(),
        "a non-trailing rest (back-indexing) must not warrant"
    );
    let allwild: syn::ItemFn =
        syn::parse_str("fn f(o: [u8; 4]) -> bool { matches!(o, [_, _, ..]) }").unwrap();
    assert!(
        emit_value_contract("f", &allwild.block).is_none(),
        "an all-wildcard slice pattern has no teeth -> not warranted"
    );
}

// Slice 23: `const { EXPR }` value blocks. core uses const blocks for
// const-generic / intrinsic constants (const { type_name::<T>() }, const { 4*8 }).
// A const block is compile-time evaluation -- PURE, its value IS EXPR's value --
// so it warrants as EXPR's term. The general term path lacked the Expr::Const arm
// the assertion path already had.
#[test]
fn emit_value_contract_const_block_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str("fn k() -> usize { const { 4 * 8 } }").unwrap();
    let decl = emit_value_contract("k", &f.block).expect("const-block value warrants");
    let inv_dbg = format!("{:?}", decl.inv.clone().expect("inv present"));
    assert!(inv_dbg.contains("out"), "return value related: {inv_dbg}");

    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("const-block inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_const_block_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3).arg(&path).output().expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "const-block relation must be well-sorted for z3:\n{stdout}\n--- {script}"
        );
        assert!(stdout.contains("sat"), "const-block relation must be satisfiable:\n{stdout}");
    }
}

// NEW DOCTRINE -- the vendor is the referee. A body's warrant is not checked for
// purity; it is INSTANTIATED at a vendor call's arguments, conjoined with the
// vendor's sworn output, and handed to z3. SAT = the warrant coexists with the
// answer (holds); UNSAT = the derived constraint can't be true against the sworn
// answer -> refuse. The interior is an unopened EUF box; order/effects never enter.
fn z3_verdict(inv: &serde_json::Value, label: &str) -> Option<bool> {
    // Some(true) = SAT, Some(false) = UNSAT, None = z3 absent.
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(inv)
        .expect("conjoined inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if !std::path::Path::new(z3).exists() {
        return None;
    }
    // Unique path per call: cargo runs tests in parallel; a shared temp file
    // races (one test reads another's script).
    let path = std::env::temp_dir().join(format!("sugar_vendor_check_{label}.smt2"));
    std::fs::write(&path, &script).expect("write smt2");
    let out = std::process::Command::new(z3).arg(&path).output().expect("run z3");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
        "conjoined relation must be well-sorted:\n{stdout}\n--- {script}"
    );
    Some(stdout.contains("sat") && !stdout.contains("unsat"))
}

fn inv_json(decl: &sugar_ir_symbolic::ContractDecl) -> serde_json::Value {
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    parsed[0]["inv"].clone()
}

#[test]
fn vendor_pin_confirms_correct_warrant_sat() {
    use sugar_lift_rust_tests::{emit_value_contract, warrant_conjoined_with_vendor};
    // body: double(x) = x * 2. Vendor GOOD twin: double(3) == 6.
    let f: syn::ItemFn = syn::parse_str("fn double(x: i32) -> i32 { x * 2 }").unwrap();
    let decl = emit_value_contract("double", &f.block).expect("warrants");
    let conjoined = warrant_conjoined_with_vendor(&decl, &[("x", 3)], 6);
    if let Some(sat) = z3_verdict(&inv_json(&conjoined), "good") {
        assert!(sat, "warrant out=x*2 at x=3 must coexist with the sworn answer 6 (SAT)");
    }
}

#[test]
fn vendor_pin_refutes_wrong_warrant_unsat() {
    use sugar_lift_rust_tests::{emit_value_contract, warrant_conjoined_with_vendor};
    // body: double(x) = x * 2. Vendor BAD twin: double(3) == 7. The derived
    // constraint (out=6) cannot coexist with the sworn answer (out=7) -> UNSAT ->
    // refuse, carrying the contradiction. This is the teeth: the check, not a
    // purity sniff, is what catches a wrong answer.
    let f: syn::ItemFn = syn::parse_str("fn double(x: i32) -> i32 { x * 2 }").unwrap();
    let decl = emit_value_contract("double", &f.block).expect("warrants");
    let conjoined = warrant_conjoined_with_vendor(&decl, &[("x", 3)], 7);
    if let Some(sat) = z3_verdict(&inv_json(&conjoined), "bad") {
        assert!(!sat, "warrant out=x*2 at x=3 must CONTRADICT the sworn answer 7 (UNSAT)");
    }
}

// The broad functional fallback must COMPOSE (warranted <=> composes through z3):
// a body with no structural shape (a loop) warrants `out = call:f(params)` --
// bare functionality -- and that relation is well-sorted and satisfiable.
#[test]
fn broad_functional_warrant_composes_through_compiler() {
    use sugar_lift_rust_tests::broad_functional_warrant;
    let f: syn::ItemFn =
        syn::parse_str("fn sum(a: i32) -> i32 { let mut s = 0; for i in 0..a { s += i; } s }")
            .unwrap();
    let decl = broad_functional_warrant("sum", &f.sig, &f.block).expect("value body warrants");
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("functional warrant must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_broad_functional_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3).arg(&path).output().expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "functional warrant must be well-sorted:\n{stdout}\n--- {script}"
        );
        assert!(stdout.contains("sat"), "functional warrant must be satisfiable:\n{stdout}");
    }
}

// ── Slice 2: value-term emission (out = <side-effect-free term>) ────────────

#[test]
fn emit_value_contract_emits_side_effect_free_value_term() {
    use sugar_lift_rust_tests::emit_value_contract;
    // pure arithmetic / read / constructor bodies -> out = <term>.
    for src in [
        "fn f(x: i32) -> i32 { x * 2 + 1 }",
        "fn f(a: u32, b: u32) -> u32 { (a ^ b) & 0xff }",
        "fn f(a: u32) -> u32 { a >> 2 }",
        "fn f(p: (i32, i32)) -> i32 { p.0 + p.1 }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("side-effect-free value term must emit: {src}"));
        let inv = format!("{:?}", decl.inv.expect("inv present"));
        assert!(
            inv.contains("out"),
            "out is the return value: {src} -> {inv}"
        );
    }
}

#[test]
fn emit_value_contract_warrants_value_position_calls_as_euf() {
    use sugar_lift_rust_tests::emit_value_contract;
    // method-call-as-EUF (the goal's sanctioned shape, mirroring Python's
    // value-position policy): a value-position call is an uninterpreted
    // deterministic function -> out = m(recv, args) / f(args), warranted.
    for src in [
        "fn f(v: Vec<u8>) -> usize { v.len() }",
        "fn f() -> i32 { g() }",
        "fn f(x: i32) -> i32 { helper(x) + 1 }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        assert!(
            emit_value_contract("f", &f.block).is_some(),
            "value-position call must warrant as EUF: {src}"
        );
    }
    // But a known PANIC method (divergence), await, or macro does NOT emit here
    // -> routed to effect_refusal/unclassified, never a pure warrant.
    for src in [
        "fn f(r: Result<i32, ()>) -> i32 { r.unwrap() }",
        "fn f(o: Option<i32>) -> i32 { o.expect(\"x\") }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        assert!(
            emit_value_contract("f", &f.block).is_none(),
            "panic method must not warrant as pure EUF: {src}"
        );
    }
}

#[test]
fn emit_value_contract_value_term_composes_through_compiler() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str("fn f(x: i32) -> i32 { x * 2 + 1 }").unwrap();
    let decl = emit_value_contract("f", &f.block).unwrap();
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("emitted value-term inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_value_term_compose.smt2");
        std::fs::write(&path, &script).expect("write smt2");
        let out = std::process::Command::new(z3)
            .arg(&path)
            .output()
            .expect("run z3");
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "value-term relation must be well-sorted:\n{stdout}\n--- script ---\n{script}"
        );
        assert!(
            stdout.contains("sat"),
            "value-term consistency relation must be satisfiable:\n{stdout}\n--- script ---\n{script}"
        );
    }
}

// ── Slice 4: bounded-output universe (clamp) -- a rust-native universe lift ──
// The rust analog of Python's no-suffix universe: a total primitive (clamp)
// whose source bounds the output for every input. The teeth are the verdict
// flip -- an out-of-bound bad twin goes UNSAT against the walked bound.

#[test]
fn emit_value_contract_clamp_emits_bounded_output_universe() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str("fn f(x: i32) -> i32 { x.clamp(0, 10) }").unwrap();
    let decl = emit_value_contract("f", &f.block).expect("clamp emits a bounded-output universe");
    let inv = format!("{:?}", decl.inv.expect("inv"));
    assert!(
        inv.contains("out"),
        "bound is over the return value `out`: {inv}"
    );
    assert!(
        inv.contains('0') && inv.contains("10"),
        "bounds 0 and 10 present: {inv}"
    );
}

#[test]
fn clamp_universe_refutes_out_of_bound_bad_twin() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str("fn f(x: i32) -> i32 { x.clamp(0, 10) }").unwrap();
    let decl = emit_value_contract("f", &f.block).unwrap();
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let universe = parsed[0]["inv"].clone();
    let z3 = "/usr/local/bin/z3";
    if !std::path::Path::new(z3).exists() {
        return;
    }
    let eq_out = |v: i64| {
        serde_json::json!({"kind":"atomic","name":"=","args":[
            {"kind":"var","name":"out"},
            {"kind":"const","value":v,"sort":{"kind":"primitive","name":"Int"}}]})
    };
    let verdict = |val: i64| -> String {
        let conj = serde_json::json!({"kind":"and","operands":[universe.clone(), eq_out(val)]});
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&conj).expect("compile");
        let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
        let path = std::env::temp_dir().join(format!("sugar_clamp_{val}.smt2"));
        std::fs::write(&path, &script).unwrap();
        let out = std::process::Command::new(z3).arg(&path).output().unwrap();
        String::from_utf8_lossy(&out.stdout).to_string()
    };
    // GOOD twin: out == 5 is within [0,10] -> SAT (discharges).
    let good = verdict(5);
    assert!(
        good.contains("sat") && !good.contains("unsat"),
        "good twin (out=5) must discharge: {good}"
    );
    // BAD twin: out == 11 is out of bound -> UNSAT (statically refuted by the bound).
    let bad = verdict(11);
    assert!(
        bad.contains("unsat"),
        "bad twin (out=11) must be refuted: {bad}"
    );
}

#[test]
fn euf_call_value_composes_through_compiler() {
    use sugar_lift_rust_tests::emit_value_contract;
    let f: syn::ItemFn = syn::parse_str("fn f(v: Vec<u8>) -> usize { v.len() }").unwrap();
    let decl = emit_value_contract("f", &f.block).unwrap();
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let inv = parsed[0]["inv"].clone();
    let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
        .expect("EUF call inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let z3 = "/usr/local/bin/z3";
    if std::path::Path::new(z3).exists() {
        let path = std::env::temp_dir().join("sugar_euf_call_compose.smt2");
        std::fs::write(&path, &script).unwrap();
        let out = std::process::Command::new(z3).arg(&path).output().unwrap();
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
            "EUF call relation must be well-sorted:\n{stdout}\n--- {script}"
        );
        assert!(
            stdout.contains("sat"),
            "EUF relation must be satisfiable:\n{stdout}"
        );
    }
}

#[test]
fn euf_value_decls_compose_across_diverse_shapes() {
    // The method-EUF warrant must COMPOSE for the variety of real value bodies it
    // emits, not just one shape -- otherwise 'warranted' would be hollow. Compile
    // each real emitted decl through the prove compiler + z3.
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    let bodies = [
        "fn f(v: &[u8]) -> usize { v.len() }",
        "fn f(s: &str) -> usize { s.len() + 1 }",
        "fn f(x: u32) -> u32 { x.swap_bytes() }",
        "fn f(p: P) -> u64 { p.field.count_ones() as u64 }",
        "fn f(a: u8, b: u8) -> u8 { a.wrapping_add(b) }",
        "fn f(x: i32) -> i32 { helper(x) + g(x) * 2 }",
        "fn f(v: &[u32]) -> u32 { v[0] & 0xff }",
        "fn f(x: u64) -> u64 { x.rotate_left(13) ^ x }",
    ];
    for src in bodies {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let Some(decl) = emit_value_contract("f", &f.block) else {
            panic!("expected an EUF/value warrant for: {src}");
        };
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let inv = parsed[0]["inv"].clone();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
            .unwrap_or_else(|e| panic!("must compile to SMT-LIB: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_euf_diverse.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "must be well-sorted: {src}:\n{so}\n--- {script}"
            );
            assert!(so.contains("sat"), "must be satisfiable: {src}:\n{so}");
        }
    }
}

// ── Slice 6: leading immutable-let prefix + EUF tail (multi-statement drain) ──

#[test]
fn emit_value_contract_let_prefix_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        "fn f(x: i32) -> i32 { let y = x * 2; y + 1 }",
        "fn f(v: &[u8]) -> usize { let n = v.len(); n + 1 }",
        "fn f(a: u32, b: u32) -> u32 { let m = a & 0xff; let k = b >> 2; m ^ k }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("let-prefix EUF body must warrant: {src}"));
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let inv = parsed[0]["inv"].clone();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_letprefix.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}

#[test]
fn emit_value_contract_let_prefix_refuses_mut_and_letelse() {
    use sugar_lift_rust_tests::emit_value_contract;
    // mutation (let mut + compound assign) and let-else (divergence) are NOT this
    // shape -> None -> routed to effect_refusal / unclassified, never warranted.
    for src in [
        "fn f(x: i32) -> i32 { let mut a = x; a += 1; a }",
        "fn f(o: Option<i32>) -> i32 { let Some(y) = o else { return 0 }; y }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        assert!(
            emit_value_contract("f", &f.block).is_none(),
            "mut/let-else must not warrant via let-prefix: {src}"
        );
    }
}

// ── Slice 8: value-position if/else-if/else -> ite via implies/and (no compiler ctor) ──

#[test]
fn emit_value_contract_if_else_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        "fn f(x: i32, a: i32, b: i32) -> i32 { if x > 0 { a } else { b } }",
        "fn f(x: i32) -> i32 { if x > 10 { 1 } else if x > 5 { 2 } else { 3 } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("if/else value must warrant: {src}"));
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let inv = parsed[0]["inv"].clone();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&inv)
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_if.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}

#[test]
fn emit_value_contract_if_refuses_non_total_and_if_let() {
    use sugar_lift_rust_tests::emit_value_contract;
    // no final else (out undefined on a branch) and if-let (cond is not a bool
    // formula) are NOT this shape -> None (routed to unclassified/effect_refusal).
    for src in [
        "fn f(x: i32) { if x > 0 { let _ = x; } }",
        "fn f(o: Option<i32>) -> i32 { if let Some(x) = o { x } else { 0 } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        assert!(
            emit_value_contract("f", &f.block).is_none(),
            "non-total / if-let must not warrant via the if path: {src}"
        );
    }
}

// ── Slice 9: bool-predicate body (comparison / && / || / predicate) -> out <-> F ──

#[test]
fn emit_value_contract_bool_predicate_body_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        "fn f(a: usize, b: usize) -> bool { a <= b }",
        "fn f(x: i32) -> bool { x == 0 }",
        "fn f(a: i32, b: i32) -> bool { a < b && b < 100 }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("bool predicate body must warrant: {src}"));
        let inv = format!("{:?}", decl.inv.clone().expect("inv"));
        assert!(inv.contains("out"), "out related: {src}");
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&parsed[0]["inv"])
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_boolpred.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}

// ── Slice 10: value-position scalar match (literal/range/_ arms) -> ite ──

#[test]
fn emit_value_contract_scalar_match_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        "fn f(x: i32) -> i32 { match x { 0 => 10, 1..=5 => 20, _ => 30 } }",
        "fn f(x: u8) -> u8 { match x { 0 | 1 => 1, _ => 0 } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("scalar match must warrant: {src}"));
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&parsed[0]["inv"])
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_match.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}

#[test]
fn emit_value_contract_match_refuses_guarded_and_nested() {
    use sugar_lift_rust_tests::emit_value_contract;
    // an arm guard and a NESTED binding pattern (a sub-pattern that isn't a plain
    // ident/wild) are NOT this shape -> None.
    for src in [
        "fn f(x: i32) -> i32 { match x { n if n > 0 => 1, _ => 0 } }",
        "fn f(o: Option<Option<i32>>) -> i32 { match o { Some(Some(x)) => x, _ => 0 } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        assert!(
            emit_value_contract("f", &f.block).is_none(),
            "guarded / nested-pattern match must not warrant: {src}"
        );
    }
}

#[test]
fn emit_value_contract_multifield_enum_match_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        "fn f(p: Pair) -> i32 { match p { Pair(a, b) => a + b, _ => 0 } }",
        "fn f(e: E) -> i32 { match e { E::P { x, y } => x + y, _ => 0 } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("multi-field enum match must warrant: {src}"));
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&parsed[0]["inv"])
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_multifield.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}

#[test]
fn emit_value_contract_enum_match_warrants_and_composes() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        // Option payload binding: Some(x) -> variant_of==Some & out=payload:Some(o); None -> ¬earlier.
        "fn f(o: Option<i32>) -> i32 { match o { Some(x) => x, None => 0 } }",
        // ignored payload + qualified unit variant.
        "fn f(r: Result<i32, ()>) -> i32 { match r { Ok(_) => 1, Err(_) => 0 } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("enum match must warrant: {src}"));
        let inv = format!("{:?}", decl.inv.clone().expect("inv"));
        assert!(
            inv.contains("variant_of"),
            "uses variant_of discriminant: {src}"
        );
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&parsed[0]["inv"])
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_enummatch.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}

// ── Slice 11: leading let-prefix + control-flow/bool tail (multi-statement) ──

#[test]
fn emit_value_contract_let_prefix_with_control_flow_tail() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        "fn f(x: i32, a: i32, b: i32) -> i32 { let t = x + 1; if t > 0 { a } else { b } }",
        "fn f(x: u32) -> bool { let m = x & 0xff; m == 0 }",
        "fn f(x: i32) -> i32 { let y = x; match y { 0 => 1, _ => 2 } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("let-prefix + control-flow tail must warrant: {src}"));
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&parsed[0]["inv"])
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_letctrl.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}

// ── Slice 14: unsafe/plain block is value-transparent ──

#[test]
fn emit_value_contract_unsafe_and_block_are_value_transparent() {
    use sugar_lift_rust_tests::emit_value_contract;
    for src in [
        "fn f(x: usize) -> usize { unsafe { id(x) } }",
        "fn f(x: i32) -> i32 { unsafe { let y = x + 1; y * 2 } }",
        "fn f(x: i32) -> i32 { { x + 1 } }",
        "fn f(x: i32, a: i32, b: i32) -> i32 { unsafe { if x > 0 { a } else { b } } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("unsafe/plain block must be value-transparent: {src}"));
        // The unwrapped inner inv must still COMPOSE (the unsafe wrapper introduces
        // no new shape -- it must inherit a composing inv).
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&parsed[0]["inv"])
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        let z3 = "/usr/local/bin/z3";
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_unsafe.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}

// ── Slice 15: tuple-destructuring let prefix ──

#[test]
fn emit_value_contract_tuple_destructuring_let() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        "fn f(p: (i32, i32)) -> i32 { let (a, b) = p; a + b }",
        "fn f(t: usize) -> usize { let (s, a) = (sz(t), al(t)); unsafe { mk(s, a) } }",
        "fn f(p: (i32, i32, i32)) -> i32 { let (a, _, c) = p; a + c }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("tuple-destructuring let must warrant: {src}"));
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&parsed[0]["inv"])
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        let _ = z3;
    }
    // a `let mut` tuple still refuses (mutation).
    let f: syn::ItemFn =
        syn::parse_str("fn f(p: (i32, i32)) -> i32 { let (mut a, b) = p; a += b; a }").unwrap();
    assert!(emit_value_contract("f", &f.block).is_none());
}

// ── Slice 16: value-if with a bool-returning call/EUF condition ──

#[test]
fn emit_value_contract_if_with_call_condition() {
    use sugar_lift_rust_tests::emit_value_contract;
    let z3 = "/usr/local/bin/z3";
    for src in [
        "fn f(x: usize, a: i32, b: i32) -> i32 { if is_valid(x) { a } else { b } }",
        "fn f(s: &str, a: i32, b: i32) -> i32 { if s.is_empty() { a } else { b } }",
    ] {
        let f: syn::ItemFn = syn::parse_str(src).unwrap();
        let decl = emit_value_contract("f", &f.block)
            .unwrap_or_else(|| panic!("if with call cond must warrant: {src}"));
        let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(&decl));
        let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
        let parts = sugar_ir_compiler_smt_lib::compile_asserted_to_parts(&parsed[0]["inv"])
            .unwrap_or_else(|e| panic!("must compile: {src}: {e:?}"));
        if std::path::Path::new(z3).exists() {
            let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
            let path = std::env::temp_dir().join("sugar_ifcall.smt2");
            std::fs::write(&path, &script).unwrap();
            let out = std::process::Command::new(z3).arg(&path).output().unwrap();
            let so = String::from_utf8_lossy(&out.stdout);
            assert!(
                !so.contains("unknown constant") && !so.to_lowercase().contains("error"),
                "well-sorted: {src}:\n{so}"
            );
            assert!(so.contains("sat"), "satisfiable: {src}:\n{so}");
        }
    }
}
