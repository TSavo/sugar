// SPDX-License-Identifier: MIT OR Apache-2.0
//
// End-to-end demo for issue #368: walk the bare program from paper 07's
// example fixture and assert the WP at function entry is exactly what
// Dijkstra's substitution rule predicts.
//
// The bare program:
//
//   fn f(x: u32) -> u32 {
//       if x < 10 { panic!("x must be >= 10"); }
//       x * 2
//   }
//
//   fn main() {
//       let y: u32 = 42;
//       let result = f(y);
//       println!("{}", result);
//   }
//
// `f`'s lifted precondition (from the if-guard) is `x ≥ 10`. At the
// callsite `f(y)` in `main`, the actual argument `y` substitutes for
// `x`, giving `y ≥ 10`. Walking backward through `let y: u32 = 42;`
// substitutes `42` for `y`, giving `42 ≥ 10`. That is the WP at
// `main`'s function entry — the proof obligation `main`'s caller would
// need to discharge (and it discharges trivially because 42 ≥ 10 is
// constant true).

use serde_json::Value as JsonValue;
use sugar_ir_types::{IrFormula, IrTerm, Sort, Value};
use sugar_walk::walk::ArrivalKind;
use sugar_walk::{atomic_ge, const_int, var, walk_callsites_to_entry};
use syn::ItemFn;

const BARE_DEMO_SRC: &str = r#"
fn main() {
    let y: u32 = 42;
    let result = f(y);
    println!("{}", result);
}
"#;

fn parse_main(src: &str) -> ItemFn {
    let file: syn::File = syn::parse_str(src).expect("bare demo parses");
    file.items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == "main" => Some(f),
            _ => None,
        })
        .expect("main function present")
}

#[test]
fn walk_bare_demo_yields_constant_true_at_entry() {
    let main_fn = parse_main(BARE_DEMO_SRC);

    // f's lifted precondition: x ≥ 10
    let pre_f = atomic_ge(var("x"), const_int(10));

    let walks = walk_callsites_to_entry(&main_fn, "f", &["x".to_string()], pre_f);

    // Exactly one callsite to `f` in this body.
    assert_eq!(walks.len(), 1, "expected one callsite to f");
    let walk = &walks[0];

    // Three arrivals: callsite, the let y = 42 binding, function entry.
    assert_eq!(
        walk.arrivals.len(),
        3,
        "expected 3 arrivals (callsite + 1 let + entry), got {}",
        walk.arrivals.len()
    );

    // Arrival 0: callsite. After substituting y for x, WP is `y ≥ 10`.
    let callsite = &walk.arrivals[0];
    assert!(matches!(
        callsite.kind,
        ArrivalKind::Callsite { ref callee } if callee == "f"
    ));
    assert_eq!(
        callsite.wp.as_formula(),
        &atomic_ge(var("y"), const_int(10)).into_formula(),
        "callsite WP after formal-actual substitution"
    );

    // Arrival 1: let y = 42. After substituting 42 for y, WP is `42 ≥ 10`.
    let let_arrival = &walk.arrivals[1];
    assert!(matches!(
        let_arrival.kind,
        ArrivalKind::LetBinding { ref name } if name == "y"
    ));
    assert_eq!(
        let_arrival.wp.as_formula(),
        &atomic_ge(const_int(42), const_int(10)).into_formula(),
        "WP at let y = 42 binding"
    );

    // Arrival 2: function entry. No further allocations to walk through;
    // WP is unchanged from the let arrival.
    let entry = &walk.arrivals[2];
    assert!(matches!(
        entry.kind,
        ArrivalKind::FunctionEntry { ref fn_name } if fn_name == "main"
    ));
    assert_eq!(
        entry.wp.as_formula(),
        &atomic_ge(const_int(42), const_int(10)).into_formula(),
        "WP at function entry"
    );

    // The WP at function entry has fully resolved: no free variables,
    // just a comparison between two constants. This is the "discharged
    // by ground evaluation" case — `42 ≥ 10` is trivially true and any
    // SMT solver returns sat in microseconds. No human in the loop.
    assert!(
        wp_is_ground_true(entry.wp.as_formula()),
        "expected entry WP to be a constant-true ground predicate"
    );
}

#[test]
fn unsafe_caller_yields_unconstrained_input_at_entry() {
    // If the caller does not constrain its input, the WP at entry remains
    // a predicate over the free variable. This is the "missing edge" case
    // — the substrate would flag that `unconstrained(input) → input ≥ 10`
    // is not in the cache and either look up a witness or refuse to compile.

    let src = r#"
        fn unsafe_caller(input: u32) -> u32 {
            f(input)
        }
    "#;
    let file: syn::File = syn::parse_str(src).expect("parses");
    let caller = file
        .items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == "unsafe_caller" => Some(f),
            _ => None,
        })
        .expect("unsafe_caller present");

    let pre_f = atomic_ge(var("x"), const_int(10));
    let walks = walk_callsites_to_entry(&caller, "f", &["x".to_string()], pre_f);

    assert_eq!(walks.len(), 1);
    let walk = &walks[0];

    // Two arrivals: callsite, function entry. No allocations between.
    assert_eq!(walk.arrivals.len(), 2);

    let entry = &walk.arrivals[1];
    assert_eq!(
        entry.wp.as_formula(),
        &atomic_ge(var("input"), const_int(10)).into_formula(),
        "WP at unsafe_caller's entry retains the free variable `input`"
    );

    // The WP is NOT ground. The substrate would mark this as a missing
    // edge unless `unsafe_caller` itself signs a precondition `input ≥ 10`,
    // which would propagate to its callers.
    assert!(
        !wp_is_ground_true(entry.wp.as_formula()),
        "expected entry WP to be non-ground (free variable present)"
    );
}

/// Returns true if the formula is a syntactically-evident ground truth:
/// e.g. `42 ≥ 10`, where both arguments are concrete integer constants
/// and the relation holds. Mirrors what a downstream SMT solver would
/// confirm in microseconds; included here for the demo so the test
/// asserts the property without needing an SMT dependency.
fn wp_is_ground_true(formula: &IrFormula) -> bool {
    match formula {
        IrFormula::Atomic { name, args } if name == "true" && args.is_empty() => true,
        IrFormula::Atomic { name, args } if args.len() == 2 => {
            let lhs = as_const_int(&args[0]);
            let rhs = as_const_int(&args[1]);
            match (lhs, rhs, name.as_str()) {
                (Some(a), Some(b), "≥") => a >= b,
                (Some(a), Some(b), ">") => a > b,
                (Some(a), Some(b), "≤") => a <= b,
                (Some(a), Some(b), "<") => a < b,
                (Some(a), Some(b), "=") => a == b,
                _ => false,
            }
        }
        _ => false,
    }
}

fn as_const_int(term: &IrTerm) -> Option<i64> {
    match term {
        IrTerm::Const {
            value: JsonValue::Number(n),
            sort: Sort::Primitive { name },
        } if name == "Int" => n.as_i64(),
        _ => None,
    }
}

// Suppress unused-import warnings: `Value` is used as a type-namespace alias
// only when working with serde_json values from outside the helper above.
#[allow(dead_code)]
fn _unused_value_alias() -> Option<Value> {
    None
}
