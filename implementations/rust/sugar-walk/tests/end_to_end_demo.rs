// SPDX-License-Identifier: MIT OR Apache-2.0
//
// End-to-end demo: lift + walk + shadow, with NO hand-supplied
// preconditions. The bare demo source is parsed in full; `f`'s precondition
// is lifted from `if x < 10 { panic!() }`; `main` is walked against that
// lifted precondition; the resulting shadow source's entry arrival has a
// ground-true WP, signaling DAG closure.
//
// This is the full-loop demonstration of paper 07's machinery on a single
// pair of Rust functions. Every step is mechanical: parse → lift → walk
// → shadow → CID. No model in any of it.

use serde_json::Value as JsonValue;
use sugar_ir_types::{IrFormula, IrTerm};
use sugar_walk::{build_shadow_source, lift_function_precondition, CalleeContract};

const BARE_DEMO_SRC: &str = r#"
fn f(x: u32) -> u32 {
    if x < 10 {
        panic!("x must be >= 10");
    }
    x * 2
}

fn main() {
    let y: u32 = 42;
    let result = f(y);
    println!("{}", result);
}
"#;

#[test]
fn end_to_end_lift_walk_shadow_dag_closes_ground_true() {
    let file: syn::File = syn::parse_str(BARE_DEMO_SRC).expect("bare demo parses");
    let mut f_fn = None;
    let mut main_fn = None;
    for item in file.items {
        if let syn::Item::Fn(item_fn) = item {
            match item_fn.sig.ident.to_string().as_str() {
                "f" => f_fn = Some(item_fn),
                "main" => main_fn = Some(item_fn),
                _ => {}
            }
        }
    }
    let f_fn = f_fn.expect("f is present");
    let main_fn = main_fn.expect("main is present");

    // 1. Lift f's precondition from its body. NO hand-supplied predicate.
    let lifted_pre = lift_function_precondition(&f_fn);

    // It should be `x ≥ 10` — the negation of `x < 10`.
    let formula_json = serde_json::to_string(lifted_pre.as_formula()).unwrap();
    assert!(
        formula_json.contains("\"≥\"") && formula_json.contains("\"x\""),
        "expected lifted precondition to be `x ≥ 10`: {}",
        formula_json
    );

    // 2. Walk main against f's lifted precondition.
    let callee = CalleeContract {
        callee_name: "f".to_string(),
        formal_params: vec!["x".to_string()],
        precondition: lifted_pre,
    };
    let s = build_shadow_source(&main_fn, &[callee]);

    // 3. The shadow source mirrors main's body (3 stmts + 1 entry).
    assert_eq!(s.slots.len(), 4);

    // 4. The entry arrival is the chain's allocation. Its WP is the proof
    // obligation; for the bare demo it should be ground-true (`42 ≥ 10`).
    let entry_arrival = &s.slots[3].arrivals[0];
    assert!(
        entry_arrival.allocation_cid.is_none(),
        "entry IS the allocation"
    );

    // 5. The entry arrival's pre_wp should have NO free variables —
    // both args of the comparison are integer constants. We assert this
    // by walking the IrFormula and checking no IrTerm::Var appears.
    let formula = entry_arrival.pre_wp.as_formula();
    assert!(
        is_ground(formula),
        "expected entry WP to be ground (no free variables); got {}",
        serde_json::to_string(formula).unwrap()
    );

    // 6. The entry WP is concretely `42 ≥ 10`, which a downstream solver
    // (Z3, etc.) would discharge in microseconds. We assert ground-truth
    // here without invoking the solver, mirroring paper 07's discharge
    // story.
    assert!(
        ground_truth(formula),
        "expected entry WP to evaluate to true"
    );
}

#[test]
fn end_to_end_lift_walk_shadow_unsafe_caller_has_non_ground_entry() {
    // Same f, different caller: an unsafe_caller that doesn't constrain
    // its input. After walking, the entry arrival's WP retains the free
    // variable `input`, signaling a missing edge the substrate would
    // refuse to discharge without further proof.
    let src = r#"
        fn f(x: u32) -> u32 {
            if x < 10 { panic!(); }
            x * 2
        }

        fn unsafe_caller(input: u32) -> u32 {
            f(input)
        }
    "#;

    let file: syn::File = syn::parse_str(src).unwrap();
    let mut f_fn = None;
    let mut caller_fn = None;
    for item in file.items {
        if let syn::Item::Fn(item_fn) = item {
            match item_fn.sig.ident.to_string().as_str() {
                "f" => f_fn = Some(item_fn),
                "unsafe_caller" => caller_fn = Some(item_fn),
                _ => {}
            }
        }
    }

    let lifted_pre = lift_function_precondition(&f_fn.unwrap());
    let callee = CalleeContract {
        callee_name: "f".to_string(),
        formal_params: vec!["x".to_string()],
        precondition: lifted_pre,
    };
    let s = build_shadow_source(&caller_fn.unwrap(), &[callee]);

    // unsafe_caller has 1 body stmt (f(input)) + 1 entry slot.
    assert_eq!(s.slots.len(), 2);
    let entry = &s.slots[1].arrivals[0];

    // The entry WP retains `input` as a free variable.
    let json = serde_json::to_string(entry.pre_wp.as_formula()).unwrap();
    assert!(
        json.contains("\"input\""),
        "expected entry WP to retain `input`: {}",
        json
    );
}

// ----- helpers -----

/// True if the formula has no free variable (no `IrTerm::Var` anywhere).
fn is_ground(formula: &IrFormula) -> bool {
    match formula {
        IrFormula::Atomic { args, .. } => args.iter().all(is_ground_term),
        IrFormula::And { operands }
        | IrFormula::Or { operands }
        | IrFormula::Not { operands }
        | IrFormula::Implies { operands } => operands.iter().all(is_ground),
        IrFormula::Forall { body, .. }
        | IrFormula::Exists { body, .. }
        | IrFormula::Choice { body, .. } => is_ground(body),
        IrFormula::Substitute { target, term, .. } => is_ground(target) && is_ground_term(term),
        IrFormula::Apply { args, .. } => args.iter().all(is_ground),
        IrFormula::DivergenceBetween { source, target } => is_ground(source) && is_ground(target),
    }
}

fn is_ground_term(term: &IrTerm) -> bool {
    match term {
        IrTerm::Var { .. } => false,
        IrTerm::Const { .. } => true,
        IrTerm::Ctor { args, .. } => args.iter().all(is_ground_term),
        IrTerm::Lambda { body, .. } => is_ground_term(body),
        IrTerm::Let { body, bindings, .. } => {
            is_ground_term(body) && bindings.iter().all(|b| is_ground_term(&b.bound_term))
        }
    }
}

/// True if the formula is a ground predicate that mathematically holds.
/// Mirrors what an SMT solver would confirm for trivially-true comparisons
/// between integer constants. Demo helper; the real substrate would dispatch
/// to Z3/Coq/etc.
fn ground_truth(formula: &IrFormula) -> bool {
    match formula {
        IrFormula::Atomic { name, args } if name == "true" && args.is_empty() => true,
        IrFormula::Atomic { name, args } if args.len() == 2 => {
            let lhs = const_int(&args[0]);
            let rhs = const_int(&args[1]);
            match (lhs, rhs, name.as_str()) {
                (Some(a), Some(b), "≥") => a >= b,
                (Some(a), Some(b), ">") => a > b,
                (Some(a), Some(b), "≤") => a <= b,
                (Some(a), Some(b), "<") => a < b,
                (Some(a), Some(b), "=") => a == b,
                (Some(a), Some(b), "≠") => a != b,
                _ => false,
            }
        }
        IrFormula::And { operands } => operands.iter().all(ground_truth),
        _ => false,
    }
}

fn const_int(term: &IrTerm) -> Option<i64> {
    match term {
        IrTerm::Const {
            value: JsonValue::Number(n),
            sort: sugar_ir_types::Sort::Primitive { name },
        } if name == "Int" => n.as_i64(),
        _ => None,
    }
}
