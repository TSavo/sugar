// SPDX-License-Identifier: MIT OR Apache-2.0
//
// If-condition context coverage for issue #368.
//
// "Every if is a free post." When a callsite sits inside `if cond { ... }`
// the substrate has `cond` available as a premise to discharge the
// callee's free pre. This test asserts the walk's if-condition tracking
// produces the right premise structure at the callsite arrival.
//
// Cases:
//   1. guarded_caller: callsite inside `if input >= 10 { f(input) }`.
//      The condition `input >= 10` matches f's lifted precondition
//      `x ≥ 10`. The arrival's WP becomes `(input ≥ 10) → (input ≥ 10)`,
//      a trivially-true implication. DAG closes ground-true.
//   2. unguarded_caller: same callsite without the if-guard. WP retains
//      the free variable `input`; non-ground; gap.

use sugar_walk::{build_shadow_source, lift_function_precondition, CalleeContract};
use syn::ItemFn;

const GUARDED_DEMO_SRC: &str = r#"
fn f(x: u32) -> u32 {
    if x < 10 { panic!(); }
    x * 2
}

fn guarded_caller(input: u32) -> u32 {
    if input >= 10 {
        f(input)
    } else {
        0
    }
}
"#;

const UNGUARDED_DEMO_SRC: &str = r#"
fn f(x: u32) -> u32 {
    if x < 10 { panic!(); }
    x * 2
}

fn unguarded_caller(input: u32) -> u32 {
    f(input)
}
"#;

fn parse_named(src: &str, name: &str) -> ItemFn {
    let file: syn::File = syn::parse_str(src).unwrap();
    file.items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == name => Some(f),
            _ => None,
        })
        .unwrap_or_else(|| panic!("{} not in source", name))
}

#[test]
fn guarded_callsite_carries_if_condition_as_premise() {
    let f_fn = parse_named(GUARDED_DEMO_SRC, "f");
    let caller = parse_named(GUARDED_DEMO_SRC, "guarded_caller");
    let pre_f = lift_function_precondition(&f_fn);

    let s = build_shadow_source(
        &caller,
        &[CalleeContract {
            callee_name: "f".to_string(),
            formal_params: vec!["x".to_string()],
            precondition: pre_f,
        }],
    );

    // The callsite to f should be discoverable inside the if-block.
    // Find the slot with at least one arrival where the WP carries an
    // `Implies` premise from the surrounding if-condition.
    let arrivals_with_premise: Vec<_> = s
        .all_arrivals()
        .filter_map(|(_slot, arrival)| {
            let json = serde_json::to_string(arrival.pre_wp.as_formula()).ok()?;
            if json.contains("\"implies\"") {
                Some(arrival)
            } else {
                None
            }
        })
        .collect();

    assert!(
        !arrivals_with_premise.is_empty(),
        "expected at least one arrival whose WP carries the if-condition as a premise"
    );

    // Specifically: at the callsite (the source-index of the if-statement),
    // the WP should be `(input ≥ 10) → (input ≥ 10)` — premise discharges
    // the obligation tautologically.
    let json = serde_json::to_string(arrivals_with_premise[0].pre_wp.as_formula()).unwrap();
    assert!(
        json.contains("\"input\""),
        "expected `input` to appear in both premise and consequent: {}",
        json
    );
    assert!(
        json.contains("\"≥\""),
        "expected the ≥ predicate from the lifted f.pre and the if-condition: {}",
        json
    );
}

#[test]
fn bool_path_callsite_guard_is_not_silently_dropped() {
    let src = r#"
        fn f(x: u32) -> u32 {
            if x == 0 { panic!(); }
            x
        }

        fn bool_guarded_caller(input: u32, ready: bool) -> u32 {
            if ready {
                f(input)
            } else {
                0
            }
        }
    "#;
    let f_fn = parse_named(src, "f");
    let caller = parse_named(src, "bool_guarded_caller");
    let pre_f = lift_function_precondition(&f_fn);

    let s = build_shadow_source(
        &caller,
        &[CalleeContract {
            callee_name: "f".to_string(),
            formal_params: vec!["x".to_string()],
            precondition: pre_f,
        }],
    );

    let guarded_arrivals: Vec<_> = s
        .all_arrivals()
        .filter_map(|(_slot, arrival)| {
            let json = serde_json::to_string(arrival.pre_wp.as_formula()).ok()?;
            if json.contains("\"implies\"") && json.contains("\"ready\"") {
                Some(json)
            } else {
                None
            }
        })
        .collect();

    assert!(
        !guarded_arrivals.is_empty(),
        "boolean path guard must become an explicit premise, not disappear as None"
    );
    assert!(
        guarded_arrivals[0].contains("\"Bool\"") && guarded_arrivals[0].contains("true"),
        "premise should compare the bool term against true: {}",
        guarded_arrivals[0]
    );
}

#[test]
fn unguarded_callsite_has_no_premise_and_retains_free_variable() {
    let f_fn = parse_named(UNGUARDED_DEMO_SRC, "f");
    let caller = parse_named(UNGUARDED_DEMO_SRC, "unguarded_caller");
    let pre_f = lift_function_precondition(&f_fn);

    let s = build_shadow_source(
        &caller,
        &[CalleeContract {
            callee_name: "f".to_string(),
            formal_params: vec!["x".to_string()],
            precondition: pre_f,
        }],
    );

    // The callsite arrival is at slot 0 (the only stmt). Its WP is just
    // `input ≥ 10` (after substitution); no premise from any surrounding
    // if-condition.
    let callsite_arrival = &s.slots[0].arrivals[0];
    let json = serde_json::to_string(callsite_arrival.pre_wp.as_formula()).unwrap();
    assert!(
        !json.contains("\"implies\""),
        "unguarded callsite should have no implies-premise: {}",
        json
    );
    assert!(
        json.contains("\"input\""),
        "WP should reference `input`: {}",
        json
    );
}

#[test]
fn else_branch_callsite_carries_negated_condition_as_premise() {
    // Callsite in the else-branch of an if-statement gets the negated
    // condition as its premise.
    let src = r#"
        fn f(x: u32) -> u32 {
            if x < 10 { panic!(); }
            x * 2
        }

        fn else_caller(input: u32) -> u32 {
            if input < 10 {
                0
            } else {
                f(input)
            }
        }
    "#;
    let f_fn = parse_named(src, "f");
    let caller = parse_named(src, "else_caller");
    let pre_f = lift_function_precondition(&f_fn);

    let s = build_shadow_source(
        &caller,
        &[CalleeContract {
            callee_name: "f".to_string(),
            formal_params: vec!["x".to_string()],
            precondition: pre_f,
        }],
    );

    let arrivals_with_not: Vec<_> = s
        .all_arrivals()
        .filter_map(|(_slot, arrival)| {
            let json = serde_json::to_string(arrival.pre_wp.as_formula()).ok()?;
            // Else-branch contributes `Not(input < 10)` as the premise.
            if json.contains("\"not\"") && json.contains("\"<\"") {
                Some(arrival)
            } else {
                None
            }
        })
        .collect();

    assert!(
        !arrivals_with_not.is_empty(),
        "expected at least one arrival with a `Not` premise from the else-branch context"
    );
}
