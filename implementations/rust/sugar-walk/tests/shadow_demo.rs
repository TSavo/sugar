// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Shadow source coverage tests for issue #368.
//
// Asserts the operational properties paper 07 commits to:
//   1. The shadow source mirrors the source AST: one slot per body
//      statement plus one slot for the function-entry "before any
//      statement" position.
//   2. Each AST node can carry N arrivals — one per callsite chain that
//      backward-WP-propagated through that node.
//   3. Each arrival is a memento: it has canonical_bytes (JCS) and a
//      self-identifying BLAKE3-512 CID; identical inputs yield identical
//      bytes and identical CIDs across runs.
//   4. Each arrival's edge memento is `(p, q)` over the free variables in
//      scope: `pre_wp → post_wp` per paper 07 §11.
//   5. The slot CID is independent of the order in which callees were
//      walked (it's a function of the slot's content, not its arrival
//      order).
//   6. Distinct callsite chains produce distinct arrivals at the same slot.

use sugar_walk::{
    atomic_ge, build_shadow_source, cid_of_value, const_int, edge_memento_cid, edge_memento_value,
    var, CalleeContract,
};
use syn::ItemFn;

const BARE_DEMO_SRC: &str = r#"
fn main() {
    let y: u32 = 42;
    let result = f(y);
    println!("{}", result);
}
"#;

const TWO_CALLSITES_SRC: &str = r#"
fn caller() {
    let y: u32 = 42;
    f(y);
    g(y);
}
"#;

const UNSAFE_CALLER_SRC: &str = r#"
fn unsafe_caller(input: u32) -> u32 {
    f(input)
}
"#;

fn parse_named(src: &str, name: &str) -> ItemFn {
    let file: syn::File = syn::parse_str(src).expect("source parses");
    file.items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == name => Some(f),
            _ => None,
        })
        .unwrap_or_else(|| panic!("{} not found in source", name))
}

fn pre_f() -> CalleeContract {
    CalleeContract {
        callee_name: "f".to_string(),
        formal_params: vec!["x".to_string()],
        precondition: atomic_ge(var("x"), const_int(10)),
    }
}

fn pre_g() -> CalleeContract {
    CalleeContract {
        callee_name: "g".to_string(),
        formal_params: vec!["z".to_string()],
        precondition: atomic_ge(var("z"), const_int(5)),
    }
}

#[test]
fn shadow_source_mirrors_body_plus_entry() {
    // main has 3 body statements: let y, let result, println!. The
    // shadow source should have 4 slots: one per body stmt + one
    // function-entry slot.
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s = build_shadow_source(&main_fn, &[pre_f()]);

    assert_eq!(s.fn_name, "main");
    assert_eq!(s.slots.len(), 4);
    // Slot indices are 0, 1, 2, 3 in source order.
    for (i, slot) in s.slots.iter().enumerate() {
        assert_eq!(slot.source_index, i);
    }
    // Last slot is the function-entry (source_index == body length).
    assert_eq!(s.slots.last().unwrap().source_kind_label, "function-entry");
}

#[test]
fn one_callsite_yields_one_arrival_per_slot_in_chain() {
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s = build_shadow_source(&main_fn, &[pre_f()]);

    // The walk for f(y) flows through:
    //  - slot 1 (the callsite f(y) lives in `let result = f(y);`)
    //  - slot 0 (let y: u32 = 42)
    //  - slot 3 (function-entry)
    // Each gets one arrival from the f-chain.
    // Slot 2 (println!) is NOT in the chain → no arrivals.
    assert_eq!(
        s.slots[0].arrivals.len(),
        1,
        "slot 0 (let y) has the let-binding arrival"
    );
    assert_eq!(
        s.slots[1].arrivals.len(),
        1,
        "slot 1 (callsite) has the callsite-root arrival"
    );
    assert_eq!(
        s.slots[2].arrivals.len(),
        0,
        "slot 2 (println!) is not in the f-chain"
    );
    assert_eq!(
        s.slots[3].arrivals.len(),
        1,
        "slot 3 (entry) has the entry arrival"
    );
}

#[test]
fn two_callsites_yield_n_arrivals_per_slot_at_shared_nodes() {
    // Both f(y) and g(y) flow backward through `let y = 42` and through
    // the function entry. Those two slots therefore carry N=2 arrivals,
    // one per callsite chain. The two callsite slots themselves carry
    // exactly one arrival each (their own root).
    let caller = parse_named(TWO_CALLSITES_SRC, "caller");
    let s = build_shadow_source(&caller, &[pre_f(), pre_g()]);

    // Body shape: let y (idx 0), f(y) (idx 1), g(y) (idx 2), entry (idx 3).
    assert_eq!(s.slots.len(), 4);

    // let y is on BOTH chains: 2 arrivals.
    assert_eq!(s.slots[0].arrivals.len(), 2);
    // f's callsite slot: only the f-chain root.
    assert_eq!(s.slots[1].arrivals.len(), 1);
    assert_eq!(s.slots[1].arrivals[0].callee_name, "f");
    // g's callsite slot: only the g-chain root.
    assert_eq!(s.slots[2].arrivals.len(), 1);
    assert_eq!(s.slots[2].arrivals[0].callee_name, "g");
    // function entry: both chains terminate here.
    assert_eq!(s.slots[3].arrivals.len(), 2);

    // The two arrivals at slot 0 belong to different callsite chains.
    let chains: std::collections::HashSet<_> = s.slots[0]
        .arrivals
        .iter()
        .map(|a| a.callee_root_cid.clone())
        .collect();
    assert_eq!(
        chains.len(),
        2,
        "two distinct callsite chains land at slot 0"
    );
}

#[test]
fn shadow_source_cid_is_self_identifying_blake3_512() {
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s = build_shadow_source(&main_fn, &[pre_f()]);
    assert!(s.cid.starts_with("blake3-512:"));
    assert_eq!(s.cid.len(), 139);
    for slot in &s.slots {
        assert!(slot.cid.starts_with("blake3-512:"));
        assert_eq!(slot.cid.len(), 139);
        for arrival in &slot.arrivals {
            assert!(arrival.cid.starts_with("blake3-512:"));
            assert_eq!(arrival.cid.len(), 139);
        }
    }
}

#[test]
fn shadow_source_cid_is_deterministic_across_runs() {
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s1 = build_shadow_source(&main_fn, &[pre_f()]);
    let s2 = build_shadow_source(&main_fn, &[pre_f()]);

    assert_eq!(s1.cid, s2.cid);
    assert_eq!(s1.canonical_bytes, s2.canonical_bytes);
    assert_eq!(s1.slots.len(), s2.slots.len());
    for (a, b) in s1.slots.iter().zip(s2.slots.iter()) {
        assert_eq!(a.cid, b.cid);
        assert_eq!(a.canonical_bytes, b.canonical_bytes);
        for (aa, ba) in a.arrivals.iter().zip(b.arrivals.iter()) {
            assert_eq!(aa.cid, ba.cid);
            assert_eq!(aa.canonical_bytes, ba.canonical_bytes);
        }
    }
}

#[test]
fn shadow_source_cid_is_callee_walk_order_independent() {
    // Walking [f, g] vs [g, f] should produce the same shadow source CID,
    // because the slot's arrival list is sorted by arrival CID before
    // canonicalization. This is the byte-determinism guarantee the
    // substrate relies on for cross-machine/cross-organization sharing.
    let caller = parse_named(TWO_CALLSITES_SRC, "caller");
    let s_fg = build_shadow_source(&caller, &[pre_f(), pre_g()]);
    let s_gf = build_shadow_source(&caller, &[pre_g(), pre_f()]);
    assert_eq!(
        s_fg.cid, s_gf.cid,
        "walk order must not affect the source CID"
    );
    assert_eq!(s_fg.canonical_bytes, s_gf.canonical_bytes);
}

#[test]
fn distinct_callee_preconditions_produce_distinct_arrivals() {
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s_a = build_shadow_source(&main_fn, &[pre_f()]);
    let s_b = build_shadow_source(
        &main_fn,
        &[CalleeContract {
            callee_name: "f".to_string(),
            formal_params: vec!["x".to_string()],
            precondition: atomic_ge(var("x"), const_int(20)),
        }],
    );
    assert_ne!(s_a.cid, s_b.cid);
    // The arrivals at slot 0 (let y) carry different WPs and therefore
    // different CIDs.
    assert_ne!(s_a.slots[0].arrivals[0].cid, s_b.slots[0].arrivals[0].cid);
}

#[test]
fn arrival_predecessor_chain_points_data_flow_upstream() {
    // Within a single callsite chain, predecessor_cid points data-flow
    // upstream — toward the allocation, not toward the callsite. This
    // matches paper 07's framing: facts flow from the allocation (the
    // "over x" anchor) to the callsite (the consumer).
    //
    // For the bare demo:
    //  - allocation = function entry (slot 3), predecessor=None
    //  - let y    = slot 0, predecessor = entry's CID
    //  - callsite = slot 1, predecessor = let's CID
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s = build_shadow_source(&main_fn, &[pre_f()]);

    let f_root_cid = s.slots[1].arrivals[0].callee_root_cid.clone();

    let entry = &s.slots[3].arrivals[0];
    let let_y = &s.slots[0].arrivals[0];
    let callsite = &s.slots[1].arrivals[0];

    // All three arrivals belong to the same callsite chain.
    assert_eq!(entry.callee_root_cid, f_root_cid);
    assert_eq!(let_y.callee_root_cid, f_root_cid);
    assert_eq!(callsite.callee_root_cid, f_root_cid);

    // The allocation (entry) is the chain's data-flow root: predecessor=None.
    assert!(entry.predecessor_cid.is_none());
    // let_y points to entry; callsite points to let_y.
    assert_eq!(let_y.predecessor_cid.as_ref().unwrap(), &entry.cid);
    assert_eq!(callsite.predecessor_cid.as_ref().unwrap(), &let_y.cid);
}

#[test]
fn allocation_cid_anchors_the_over_x_question() {
    // The allocation arrival has allocation_cid = None — it IS the
    // allocation. Every other arrival in the chain points to the
    // allocation by CID, encoding the "over x is answered by where the
    // allocation occurred" framing as a single-field lookup.
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s = build_shadow_source(&main_fn, &[pre_f()]);

    let entry = &s.slots[3].arrivals[0];
    let let_y = &s.slots[0].arrivals[0];
    let callsite = &s.slots[1].arrivals[0];

    // Allocation arrival: allocation_cid = None.
    assert!(
        entry.allocation_cid.is_none(),
        "the allocation arrival is its own answer; allocation_cid is None"
    );
    // Other arrivals point to the allocation by CID.
    assert_eq!(let_y.allocation_cid.as_ref().unwrap(), &entry.cid);
    assert_eq!(callsite.allocation_cid.as_ref().unwrap(), &entry.cid);
}

#[test]
fn allocation_memento_is_self_contained_and_cacheable() {
    // The allocation arrival is its own content-addressable memento. It
    // can be transmitted independently and looked up by CID. This is
    // what "another cache-addressable memento that travels with the
    // arrival" means operationally: a separate signed artifact, linked
    // by CID from the dependent arrivals.
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s = build_shadow_source(&main_fn, &[pre_f()]);

    let entry = &s.slots[3].arrivals[0];

    // The allocation memento has its own bytes and its own CID.
    assert!(!entry.canonical_bytes.is_empty());
    assert!(entry.cid.starts_with("blake3-512:"));

    // The CID is a function of the bytes.
    let recomputed = sugar_walk::cid_of_value(&sugar_walk::serde_to_canonical(
        serde_json::from_slice(&entry.canonical_bytes).unwrap(),
    ));
    assert_eq!(recomputed, entry.cid);
}

#[test]
fn edge_memento_emits_p_implies_q_over_x() {
    // The edge memento for an arrival is `p → q over x`: pre_wp implies
    // post_wp where free variables (over x) are universally quantified
    // in the substrate's logic. We assert the memento structure carries
    // p, q, and a witness placeholder, and that its CID is stable.
    let main_fn = parse_named(BARE_DEMO_SRC, "main");
    let s = build_shadow_source(&main_fn, &[pre_f()]);

    // Pick the callsite arrival (slot 1, the chain root).
    let callsite_arrival = &s.slots[1].arrivals[0];
    let value = edge_memento_value(callsite_arrival);
    let cid_a = cid_of_value(&value);
    let cid_b = edge_memento_cid(callsite_arrival);
    assert_eq!(cid_a, cid_b);
    assert!(cid_a.starts_with("blake3-512:"));

    // Spot-check the memento's JSON structure exposes pre, post, and evidence.
    // The edge memento now emits kind:"contract" (schemaVersion "2") with
    // pre/post instead of the old p/q fields, and evidence wrapping the witness.
    let json = serde_json::to_string(&serialize_value(&value)).unwrap();
    assert!(
        json.contains("\"pre\""),
        "expected pre field in contract memento: {}",
        json
    );
    assert!(
        json.contains("\"post\""),
        "expected post field in contract memento: {}",
        json
    );
    assert!(
        json.contains("\"evidence\""),
        "expected evidence field in contract memento: {}",
        json
    );
    assert!(
        json.contains("\"kind\":\"contract\""),
        "expected kind:contract in memento: {}",
        json
    );
}

#[test]
fn unsafe_caller_yields_non_ground_entry_wp() {
    let caller = parse_named(UNSAFE_CALLER_SRC, "unsafe_caller");
    let s = build_shadow_source(&caller, &[pre_f()]);

    // body has 1 stmt + 1 entry slot = 2 slots total.
    assert_eq!(s.slots.len(), 2);
    // Slot 0 is the callsite, slot 1 is the entry.
    let entry_slot = &s.slots[1];
    assert_eq!(entry_slot.source_kind_label, "function-entry");
    assert_eq!(entry_slot.arrivals.len(), 1);
    let entry_arrival = &entry_slot.arrivals[0];

    // Entry WP should retain `input` as a free variable — non-ground.
    let formula_json = serde_json::to_string(entry_arrival.pre_wp.as_formula()).unwrap();
    assert!(
        formula_json.contains("\"input\""),
        "expected entry WP to retain `input` as a free variable: {}",
        formula_json
    );
}

// Helper: turn a canonicalizer Value into a serde_json::Value for spot-
// checking memento JSON in tests. Walks the small Arc<Value> tree and
// emits the equivalent serde shape.
fn serialize_value(v: &sugar_canonicalizer::Value) -> serde_json::Value {
    use sugar_canonicalizer::Value as V;
    match v {
        V::Null => serde_json::Value::Null,
        V::Bool(b) => serde_json::Value::Bool(*b),
        // Precision-safe i128 -> JSON: serde_json::Number has no From<i128> and a
        // bare >u64 number would parse back as a lossy f64. A value within i64/u64
        // stays a Number (byte-identical); a wider value is carried as a decimal
        // string (mirrors sugar_ir_symbolic::convert::int_to_json).
        V::Integer(n) => {
            if let Ok(i) = i64::try_from(*n) {
                serde_json::Value::Number(i.into())
            } else if let Ok(u) = u64::try_from(*n) {
                serde_json::Value::Number(u.into())
            } else {
                serde_json::Value::String(n.to_string())
            }
        }
        V::String(s) => serde_json::Value::String(s.clone()),
        V::Array(items) => {
            serde_json::Value::Array(items.iter().map(|x| serialize_value(x)).collect())
        }
        V::Object(entries) => {
            let mut map = serde_json::Map::new();
            for (k, vv) in entries {
                map.insert(k.clone(), serialize_value(vv));
            }
            serde_json::Value::Object(map)
        }
    }
}
