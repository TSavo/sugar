// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Round-trip serde tests for the v1.5.0 Sort enum extensions.
//
// Source of truth:
//   protocol/sugar-ir.cddl  (Sort = ... / FunctionSort / DependentSort)
//
// Issue context:
//   #330 (grammar grow), #361 (rust gap closed by this PR)
//
// These tests pin:
//   * `Sort::Function` serializes to `{"kind": "function", "args": [...], "return": ...}`
//     and round-trips through serde_json without loss.
//   * `Sort::Dependent` serializes to `{"kind": "dependent", "name": ..., "indexVar": ..., "indexSort": ...}`
//     and round-trips through serde_json without loss.
//   * `Sort::Primitive` continues to deserialize from the v1.4 wire shape
//     (backward compatibility: existing kits emit only Primitive today).

use sugar_ir_types::Sort;

// ---------------------------------------------------------------------------
// Backward-compat: Sort::Primitive still parses/serializes as before.
// ---------------------------------------------------------------------------

#[test]
fn primitive_sort_v14_backward_compat() {
    let json = r#"{"kind":"primitive","name":"Int"}"#;
    let parsed: Sort = serde_json::from_str(json).expect("parse primitive sort");
    match &parsed {
        Sort::Primitive { name } => assert_eq!(name, "Int"),
        _ => panic!("expected Primitive variant, got {:?}", parsed),
    }

    let serialized = serde_json::to_string(&parsed).expect("serialize primitive sort");
    let reparsed: Sort = serde_json::from_str(&serialized).expect("re-parse");
    assert_eq!(parsed, reparsed);
}

// ---------------------------------------------------------------------------
// FunctionSort
// ---------------------------------------------------------------------------

#[test]
fn function_sort_serializes_to_cddl_shape() {
    let sort = Sort::Function {
        args: vec![Sort::Primitive { name: "Int".into() }],
        ret: Box::new(Sort::Primitive {
            name: "Bool".into(),
        }),
    };

    let serialized = serde_json::to_string(&sort).expect("serialize function sort");
    let value: serde_json::Value = serde_json::from_str(&serialized).expect("re-parse to Value");

    // Shape check: exactly the keys CDDL specifies.
    let obj = value
        .as_object()
        .expect("function sort should serialize as object");
    assert_eq!(obj.get("kind").and_then(|v| v.as_str()), Some("function"));
    assert!(obj.contains_key("args"), "function sort must have `args`");
    assert!(
        obj.contains_key("return"),
        "function sort must have `return`"
    );
    // No leaked rust field name (`ret`): must be JSON `return`.
    assert!(
        !obj.contains_key("ret"),
        "rust field `ret` must serialize as `return`"
    );

    // args is a list of one Sort.
    let args = obj
        .get("args")
        .and_then(|v| v.as_array())
        .expect("args is array");
    assert_eq!(args.len(), 1);
    let arg0 = args[0].as_object().expect("arg0 is object");
    assert_eq!(arg0.get("kind").and_then(|v| v.as_str()), Some("primitive"));
    assert_eq!(arg0.get("name").and_then(|v| v.as_str()), Some("Int"));

    // return is a Sort.
    let ret = obj
        .get("return")
        .and_then(|v| v.as_object())
        .expect("return is object");
    assert_eq!(ret.get("kind").and_then(|v| v.as_str()), Some("primitive"));
    assert_eq!(ret.get("name").and_then(|v| v.as_str()), Some("Bool"));
}

#[test]
fn function_sort_round_trip_preserves_value() {
    let sort = Sort::Function {
        args: vec![
            Sort::Primitive { name: "Int".into() },
            Sort::Primitive {
                name: "String".into(),
            },
        ],
        ret: Box::new(Sort::Primitive {
            name: "Bool".into(),
        }),
    };

    let serialized = serde_json::to_string(&sort).expect("serialize");
    let parsed: Sort = serde_json::from_str(&serialized).expect("parse back");
    assert_eq!(sort, parsed);
}

#[test]
fn function_sort_deserializes_from_cddl_wire_shape() {
    // Wire shape exactly as v1.5.0 spec defines (post-JCS, alphabetic key order
    // the network would actually see).
    let json = r#"{"args":[{"kind":"primitive","name":"Int"}],"kind":"function","return":{"kind":"primitive","name":"Bool"}}"#;
    let parsed: Sort = serde_json::from_str(json).expect("parse function sort");
    match parsed {
        Sort::Function { args, ret } => {
            assert_eq!(args.len(), 1);
            match &args[0] {
                Sort::Primitive { name } => assert_eq!(name, "Int"),
                _ => panic!("arg0 should be Primitive Int"),
            }
            match *ret {
                Sort::Primitive { name } => assert_eq!(name, "Bool"),
                _ => panic!("return should be Primitive Bool"),
            }
        }
        _ => panic!("expected Function variant"),
    }
}

// ---------------------------------------------------------------------------
// DependentSort
// ---------------------------------------------------------------------------

#[test]
fn dependent_sort_serializes_to_cddl_shape() {
    let sort = Sort::Dependent {
        name: "Vec".into(),
        index_var: "n".into(),
        index_sort: Box::new(Sort::Primitive { name: "Int".into() }),
    };

    let serialized = serde_json::to_string(&sort).expect("serialize dependent sort");
    let value: serde_json::Value = serde_json::from_str(&serialized).expect("re-parse to Value");

    let obj = value
        .as_object()
        .expect("dependent sort should serialize as object");
    assert_eq!(obj.get("kind").and_then(|v| v.as_str()), Some("dependent"));
    assert_eq!(obj.get("name").and_then(|v| v.as_str()), Some("Vec"));
    assert_eq!(obj.get("indexVar").and_then(|v| v.as_str()), Some("n"));
    assert!(
        obj.contains_key("indexSort"),
        "dependent sort must have `indexSort`"
    );
    // No leaked rust snake_case field names.
    assert!(
        !obj.contains_key("index_var"),
        "rust field `index_var` must serialize as `indexVar`"
    );
    assert!(
        !obj.contains_key("index_sort"),
        "rust field `index_sort` must serialize as `indexSort`"
    );

    let index_sort = obj
        .get("indexSort")
        .and_then(|v| v.as_object())
        .expect("indexSort is object");
    assert_eq!(
        index_sort.get("kind").and_then(|v| v.as_str()),
        Some("primitive")
    );
    assert_eq!(index_sort.get("name").and_then(|v| v.as_str()), Some("Int"));
}

#[test]
fn dependent_sort_round_trip_preserves_value() {
    let sort = Sort::Dependent {
        name: "Vec".into(),
        index_var: "n".into(),
        index_sort: Box::new(Sort::Primitive { name: "Int".into() }),
    };

    let serialized = serde_json::to_string(&sort).expect("serialize");
    let parsed: Sort = serde_json::from_str(&serialized).expect("parse back");
    assert_eq!(sort, parsed);
}

#[test]
fn dependent_sort_deserializes_from_cddl_wire_shape() {
    // Wire shape (alphabetic key order, JCS-canonical).
    let json = r#"{"indexSort":{"kind":"primitive","name":"Int"},"indexVar":"n","kind":"dependent","name":"Vec"}"#;
    let parsed: Sort = serde_json::from_str(json).expect("parse dependent sort");
    match parsed {
        Sort::Dependent {
            name,
            index_var,
            index_sort,
        } => {
            assert_eq!(name, "Vec");
            assert_eq!(index_var, "n");
            match *index_sort {
                Sort::Primitive { name } => assert_eq!(name, "Int"),
                _ => panic!("indexSort should be Primitive Int"),
            }
        }
        _ => panic!("expected Dependent variant"),
    }
}

// ---------------------------------------------------------------------------
// Recursive nesting (Function inside Dependent inside Function)
// ---------------------------------------------------------------------------

#[test]
fn nested_sorts_round_trip() {
    // (Vec<n: Int> -> Bool): a function that takes a length-indexed Vec and
    // returns Bool. Exercises Box<Sort> recursion through both new variants.
    let sort = Sort::Function {
        args: vec![Sort::Dependent {
            name: "Vec".into(),
            index_var: "n".into(),
            index_sort: Box::new(Sort::Primitive { name: "Int".into() }),
        }],
        ret: Box::new(Sort::Primitive {
            name: "Bool".into(),
        }),
    };

    let serialized = serde_json::to_string(&sort).expect("serialize");
    let parsed: Sort = serde_json::from_str(&serialized).expect("parse back");
    assert_eq!(sort, parsed);
}
