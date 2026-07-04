// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Structural tests for the kit constructors. Pins:
//   - `must` and `contract` push into the collector; `finish` drains.
//   - reset_collector clears state; multiple cycles work.
//   - connective constructors produce the right arity (not=1, implies=2,
//     and/or = caller-provided).
//   - atomic predicate names round-trip including Unicode (>, <, =, ≠/≤/≥).
//   - forall / exists generate fresh, sequential bound names.
//   - quantifier counter resets on reset_collector.

use std::rc::Rc;

use sugar_ir_symbolic::{
    and_, atomic_, begin_collecting, choice, contract, eq, exists, finish, forall, gt, gte,
    implies, lambda, let_term, lt, lte, must, ne, not_, num, or_, out, parse_int, real_const,
    reset_collector, str_const, ConstValue, ContractArgs, Formula, Int, Sort, Term,
};

// ---------------------------------------------------------------------------
// Collector lifecycle
// ---------------------------------------------------------------------------

#[test]
fn must_pushes_pre_into_collector_with_default_out_binding() {
    reset_collector();
    must("parseInt", forall(Int(), |n| gt(n, num(0))));
    let decls = finish();
    assert_eq!(decls.len(), 1);
    assert_eq!(decls[0].name, "parseInt");
    assert!(decls[0].pre.is_some());
    assert!(decls[0].post.is_none());
    assert!(decls[0].inv.is_none());
    assert_eq!(decls[0].out_binding, "out");
}

#[test]
fn contract_with_explicit_out_binding() {
    reset_collector();
    contract(
        "myContract",
        ContractArgs {
            pre: Some(forall(Int(), |n| gt(n, num(0)))),
            out_binding: Some("result".into()),
            ..Default::default()
        },
    );
    let decls = finish();
    assert_eq!(decls.len(), 1);
    assert_eq!(decls[0].out_binding, "result");
}

#[test]
fn finish_drains_collector_so_subsequent_finish_is_empty() {
    reset_collector();
    must("a", forall(Int(), |n| gt(n, num(0))));
    let first = finish();
    assert_eq!(first.len(), 1);
    let second = finish();
    assert_eq!(second.len(), 0, "finish must drain the collector");
}

#[test]
fn multiple_collect_cycles_work_with_reset() {
    reset_collector();
    must("a", forall(Int(), |n| gt(n, num(0))));
    let cycle_a = finish();
    assert_eq!(cycle_a.len(), 1);

    reset_collector();
    must("b", forall(Int(), |n| lt(n, num(100))));
    must("c", forall(Int(), |n| eq(n, num(42))));
    let cycle_b = finish();
    assert_eq!(cycle_b.len(), 2);
    assert_eq!(cycle_b[0].name, "b");
    assert_eq!(cycle_b[1].name, "c");
}

#[test]
fn begin_collecting_clears_pending_state() {
    reset_collector();
    must("residue", forall(Int(), |n| gt(n, num(0))));
    begin_collecting();
    must("real", forall(Int(), |n| gt(n, num(1))));
    let decls = finish();
    assert_eq!(decls.len(), 1);
    assert_eq!(decls[0].name, "real");
}

#[test]
#[should_panic(expected = "at least one of pre/post/inv")]
fn empty_contract_panics_in_kit() {
    // Note: this is the kit's panic, distinct from mint_contract's
    // EmptyContract Result error. Spec says fail loud at authoring time.
    reset_collector();
    contract("noop", ContractArgs::default());
}

#[test]
fn contract_with_only_post_succeeds() {
    reset_collector();
    contract(
        "p",
        ContractArgs {
            post: Some(eq(out(), num(0))),
            ..Default::default()
        },
    );
    let decls = finish();
    assert_eq!(decls.len(), 1);
    assert!(decls[0].pre.is_none());
    assert!(decls[0].post.is_some());
}

#[test]
fn contract_with_only_inv_succeeds() {
    reset_collector();
    contract(
        "p",
        ContractArgs {
            inv: Some(and_(vec![])),
            ..Default::default()
        },
    );
    let decls = finish();
    assert_eq!(decls.len(), 1);
    assert!(decls[0].inv.is_some());
}

// ---------------------------------------------------------------------------
// Quantifier: fresh bound names
// ---------------------------------------------------------------------------

#[test]
fn forall_generates_fresh_sequential_names_after_reset() {
    reset_collector();
    let f0 = forall(Int(), |_| and_(vec![]));
    let f1 = forall(Int(), |_| and_(vec![]));
    match (f0.as_ref(), f1.as_ref()) {
        (Formula::Quantifier { name: n0, .. }, Formula::Quantifier { name: n1, .. }) => {
            assert_eq!(n0, "_x0");
            assert_eq!(n1, "_x1");
        }
        _ => panic!("not quantifiers"),
    }
}

#[test]
fn exists_uses_same_counter_as_forall() {
    reset_collector();
    let f0 = forall(Int(), |_| and_(vec![]));
    let f1 = exists(Int(), |_| and_(vec![]));
    let bindings = [&f0, &f1];
    let names: Vec<&str> = bindings
        .iter()
        .map(|f| match f.as_ref() {
            Formula::Quantifier { name, .. } => name.as_str(),
            _ => panic!(),
        })
        .collect();
    assert_eq!(names, vec!["_x0", "_x1"]);
}

#[test]
fn reset_collector_resets_quantifier_counter() {
    reset_collector();
    let _ = forall(Int(), |_| and_(vec![]));
    let _ = forall(Int(), |_| and_(vec![]));
    reset_collector();
    let f = forall(Int(), |_| and_(vec![]));
    match f.as_ref() {
        Formula::Quantifier { name, .. } => assert_eq!(name, "_x0"),
        _ => panic!(),
    }
}

#[test]
fn forall_kind_is_forall_and_exists_kind_is_exists() {
    reset_collector();
    let f = forall(Int(), |_| and_(vec![]));
    let e = exists(Int(), |_| and_(vec![]));
    match f.as_ref() {
        Formula::Quantifier { kind, .. } => assert_eq!(kind, "forall"),
        _ => panic!(),
    }
    match e.as_ref() {
        Formula::Quantifier { kind, .. } => assert_eq!(kind, "exists"),
        _ => panic!(),
    }
}

#[test]
fn forall_passes_bound_var_to_body_callback() {
    reset_collector();
    let f = forall(Int(), |n| {
        match n.as_ref() {
            Term::Var { name } => assert_eq!(name, "_x0"),
            _ => panic!("body got non-var"),
        }
        and_(vec![])
    });
    drop(f);
}

// ---------------------------------------------------------------------------
// Connective shapes
// ---------------------------------------------------------------------------

fn arity_of_connective(f: &Rc<Formula>) -> usize {
    match f.as_ref() {
        Formula::Connective { operands, .. } => operands.len(),
        _ => panic!("not a connective"),
    }
}

fn kind_of_connective(f: &Rc<Formula>) -> String {
    match f.as_ref() {
        Formula::Connective { kind, .. } => kind.clone(),
        _ => panic!("not a connective"),
    }
}

#[test]
fn not_has_exactly_one_operand() {
    reset_collector();
    let f = not_(and_(vec![]));
    assert_eq!(arity_of_connective(&f), 1);
    assert_eq!(kind_of_connective(&f), "not");
}

#[test]
fn implies_has_exactly_two_operands() {
    reset_collector();
    let f = implies(and_(vec![]), and_(vec![]));
    assert_eq!(arity_of_connective(&f), 2);
    assert_eq!(kind_of_connective(&f), "implies");
}

#[test]
fn and_passes_through_caller_arity() {
    reset_collector();
    assert_eq!(arity_of_connective(&and_(vec![])), 0);
    assert_eq!(arity_of_connective(&and_(vec![and_(vec![])])), 1);
    assert_eq!(
        arity_of_connective(&and_(vec![and_(vec![]), and_(vec![]), and_(vec![])])),
        3
    );
    assert_eq!(kind_of_connective(&and_(vec![])), "and");
}

#[test]
fn or_passes_through_caller_arity() {
    reset_collector();
    assert_eq!(arity_of_connective(&or_(vec![])), 0);
    assert_eq!(arity_of_connective(&or_(vec![and_(vec![])])), 1);
    assert_eq!(kind_of_connective(&or_(vec![])), "or");
}

// ---------------------------------------------------------------------------
// Atomic predicate names: Unicode round-trip
// ---------------------------------------------------------------------------

fn atomic_name(f: &Rc<Formula>) -> String {
    match f.as_ref() {
        Formula::Atomic { name, .. } => name.clone(),
        _ => panic!("not atomic"),
    }
}

#[test]
fn atomic_predicate_names_round_trip() {
    let one = num(1);
    let two = num(2);
    assert_eq!(atomic_name(&gt(one.clone(), two.clone())), ">");
    assert_eq!(atomic_name(&lt(one.clone(), two.clone())), "<");
    assert_eq!(atomic_name(&eq(one.clone(), two.clone())), "=");
    assert_eq!(atomic_name(&ne(one.clone(), two.clone())), "\u{2260}");
    assert_eq!(atomic_name(&gte(one.clone(), two.clone())), "\u{2265}");
    assert_eq!(atomic_name(&lte(one, two)), "\u{2264}");
}

#[test]
fn atomic_named_constructor_accepts_arbitrary_predicate_names() {
    let f = atomic_("myPred", vec![num(1), num(2), num(3)]);
    match f.as_ref() {
        Formula::Atomic { name, args } => {
            assert_eq!(name, "myPred");
            assert_eq!(args.len(), 3);
        }
        _ => panic!("not atomic"),
    }
}

// ---------------------------------------------------------------------------
// Term primitives
// ---------------------------------------------------------------------------

#[test]
fn num_is_int_const() {
    let t = num(42);
    match t.as_ref() {
        Term::Const { value, sort } => {
            match value {
                ConstValue::Int(n) => assert_eq!(*n, 42),
                _ => panic!("expected Int const"),
            }
            assert_eq!(sort.name, "Int");
        }
        _ => panic!("expected Const"),
    }
}

#[test]
fn str_const_is_string_const() {
    let t = str_const("hello");
    match t.as_ref() {
        Term::Const { value, sort } => {
            match value {
                ConstValue::String(s) => assert_eq!(s, "hello"),
                _ => panic!("expected String const"),
            }
            assert_eq!(sort.name, "String");
        }
        _ => panic!("expected Const"),
    }
}

#[test]
fn real_const_is_real_const() {
    let t = real_const("2.0");
    match t.as_ref() {
        Term::Const { value, sort } => {
            match value {
                ConstValue::Real(s) => assert_eq!(s, "2.0"),
                _ => panic!("expected Real const"),
            }
            assert_eq!(sort.name, "Real");
        }
        _ => panic!("expected Const"),
    }
}

#[test]
fn out_is_var_named_out() {
    let t = out();
    match t.as_ref() {
        Term::Var { name } => assert_eq!(name, "out"),
        _ => panic!("expected Var"),
    }
}

#[test]
fn parse_int_is_ctor_with_one_arg() {
    let t = parse_int(str_const("42"));
    match t.as_ref() {
        Term::Ctor { name, args } => {
            assert_eq!(name, "parseInt");
            assert_eq!(args.len(), 1);
        }
        _ => panic!("expected Ctor"),
    }
}

// ---------------------------------------------------------------------------
// Sort constructors
// ---------------------------------------------------------------------------

#[test]
fn primitive_sorts_have_correct_names() {
    assert_eq!(Sort::int().name, "Int");
    assert_eq!(Sort::real().name, "Real");
    assert_eq!(Sort::string().name, "String");
    assert_eq!(Sort::bool().name, "Bool");
}

// ---------------------------------------------------------------------------
// Lambda terms
// ---------------------------------------------------------------------------

#[test]
fn lambda_has_param_name_sort_and_body() {
    let lam = lambda("x".into(), Int(), num(42));
    match lam.as_ref() {
        Term::Lambda {
            param_name,
            param_sort,
            body,
        } => {
            assert_eq!(param_name, "x");
            assert_eq!(param_sort.name, "Int");
            match body.as_ref() {
                Term::Const { value, .. } => match value {
                    ConstValue::Int(n) => assert_eq!(*n, 42),
                    _ => panic!("expected Int"),
                },
                _ => panic!("expected const body"),
            }
        }
        _ => panic!("expected Lambda"),
    }
}

#[test]
fn lambda_param_is_bound_in_body_scope() {
    reset_collector();
    let lam = lambda("x".into(), Int(), {
        let x_var = sugar_ir_symbolic::make_var("x");
        x_var
    });
    match lam.as_ref() {
        Term::Lambda { param_name, .. } => assert_eq!(param_name, "x"),
        _ => panic!("expected Lambda"),
    }
}

// ---------------------------------------------------------------------------
// Let terms
// ---------------------------------------------------------------------------

#[test]
fn let_has_bindings_and_body() {
    let let_expr = let_term(
        vec![sugar_ir_symbolic::LetBinding {
            name: "x".into(),
            bound_term: num(1),
        }],
        num(2),
    );
    match let_expr.as_ref() {
        Term::Let { bindings, body } => {
            assert_eq!(bindings.len(), 1);
            assert_eq!(bindings[0].name, "x");
            match bindings[0].bound_term.as_ref() {
                Term::Const { value, .. } => match value {
                    ConstValue::Int(n) => assert_eq!(*n, 1),
                    _ => panic!("expected Int"),
                },
                _ => panic!("expected const binding"),
            }
            match body.as_ref() {
                Term::Const { value, .. } => match value {
                    ConstValue::Int(n) => assert_eq!(*n, 2),
                    _ => panic!("expected Int"),
                },
                _ => panic!("expected const body"),
            }
        }
        _ => panic!("expected Let"),
    }
}

#[test]
fn let_with_multiple_bindings_is_sequential() {
    let let_expr = let_term(
        vec![
            sugar_ir_symbolic::LetBinding {
                name: "x".into(),
                bound_term: num(1),
            },
            sugar_ir_symbolic::LetBinding {
                name: "y".into(),
                bound_term: num(2),
            },
        ],
        num(3),
    );
    match let_expr.as_ref() {
        Term::Let { bindings, .. } => {
            assert_eq!(bindings.len(), 2);
            assert_eq!(bindings[0].name, "x");
            assert_eq!(bindings[1].name, "y");
        }
        _ => panic!("expected Let"),
    }
}

// ---------------------------------------------------------------------------
// Choice formulas
// ---------------------------------------------------------------------------

#[test]
fn choice_has_var_name_sort_and_body() {
    let c = choice("x".into(), Int(), |v| eq(v, num(0)));
    match c.as_ref() {
        Formula::Choice {
            var_name,
            sort,
            body,
        } => {
            assert_eq!(var_name, "x");
            assert_eq!(sort.name, "Int");
            match body.as_ref() {
                Formula::Atomic { name, .. } => assert_eq!(name, "="),
                _ => panic!("expected atomic body"),
            }
        }
        _ => panic!("expected Choice"),
    }
}

#[test]
fn choice_body_can_reference_bound_var() {
    reset_collector();
    let c = choice("result".into(), Int(), |v| {
        match v.as_ref() {
            Term::Var { name } => assert_eq!(name, "result"),
            _ => panic!("expected var"),
        }
        gt(v, num(0))
    });
    drop(c);
}
