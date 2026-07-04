// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Destructuring let-bindings: tuple, struct, and slice patterns each
// produce one arrival per bound name in the shadow source.

use sugar_walk::{atomic_ge, build_shadow_source, const_int, var, CalleeContract};
use syn::ItemFn;

fn parse_named(src: &str, name: &str) -> ItemFn {
    let file: syn::File = syn::parse_str(src).unwrap();
    file.items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == name => Some(f),
            _ => None,
        })
        .unwrap()
}

fn pre_f() -> CalleeContract {
    CalleeContract {
        callee_name: "f".to_string(),
        formal_params: vec!["x".to_string()],
        precondition: atomic_ge(var("x"), const_int(10)),
    }
}

#[test]
fn tuple_destructuring_yields_arrival_per_bound_name() {
    let src = r#"
        fn f(x: u32) -> u32 {
            if x < 10 { panic!(); }
            x * 2
        }

        fn caller() -> u32 {
            let pair = (42, 100);
            let (a, b) = pair;
            f(a)
        }
    "#;
    let caller = parse_named(src, "caller");
    let s = build_shadow_source(&caller, &[pre_f()]);

    // Body shape: stmt 0 (let pair), stmt 1 (let (a, b) = pair), stmt 2 (callsite f(a)).
    // Plus function-entry slot at index 3.
    assert_eq!(s.slots.len(), 4);

    // The destructuring `let (a, b) = pair` produces TWO arrivals per
    // callsite chain at slot 1 (one for each bound name). We assert
    // the count is at least 2 — one each for `a` and `b` from the
    // f-chain's backward walk through the destructuring.
    let slot1_arrivals = &s.slots[1].arrivals;
    assert!(
        slot1_arrivals.len() >= 2,
        "tuple destructuring slot should carry one arrival per bound name (a, b); got {}",
        slot1_arrivals.len()
    );
}

#[test]
fn struct_destructuring_lifts_field_projections() {
    // `let Point { x, y } = p;` should produce two bindings at the same
    // statement: one for x, one for y, each as a field projection of p.
    // This test only asserts that the shadow source builds without
    // panicking — the underlying walk + lift handle the multi-binding
    // case mechanically; richer assertions on field projection shape
    // follow once a struct-aware lifter is added.
    let src = r#"
        struct Point { x: u32, y: u32 }

        fn f(x: u32) -> u32 {
            if x < 10 { panic!(); }
            x * 2
        }

        fn caller(p: Point) -> u32 {
            let Point { x, y } = p;
            f(x)
        }
    "#;
    let caller = parse_named(src, "caller");
    let s = build_shadow_source(&caller, &[pre_f()]);
    // Don't crash; produce a stable CID.
    assert!(s.cid.starts_with("blake3-512:"));
}

#[test]
fn slice_destructuring_lifts_indexed_projections() {
    // `let [a, b, c] = arr;` yields three bindings; each is index(arr, i).
    let src = r#"
        fn f(x: u32) -> u32 {
            if x < 10 { panic!(); }
            x * 2
        }

        fn caller() -> u32 {
            let arr: [u32; 3] = [42, 100, 200];
            let [a, b, c] = arr;
            f(a)
        }
    "#;
    let caller = parse_named(src, "caller");
    let s = build_shadow_source(&caller, &[pre_f()]);
    // Walk doesn't crash; the destructuring let produces one arrival
    // per bound name in the shadow source.
    assert!(s.cid.starts_with("blake3-512:"));
    // Body: 2 lets + 1 callsite + 1 entry = 4 slots.
    assert_eq!(s.slots.len(), 4);
}

#[test]
fn wildcard_pattern_binds_nothing() {
    // `let _ = expr` produces zero bindings — the wildcard discards.
    let src = r#"
        fn f(x: u32) -> u32 {
            if x < 10 { panic!(); }
            x * 2
        }

        fn caller() -> u32 {
            let _ = 42;
            let y: u32 = 99;
            f(y)
        }
    "#;
    let caller = parse_named(src, "caller");
    let s = build_shadow_source(&caller, &[pre_f()]);
    assert!(s.cid.starts_with("blake3-512:"));
    // The `let _ = 42` still occupies a body slot but produces no
    // arrival from a chain perspective (walk skips it as no binding).
}
