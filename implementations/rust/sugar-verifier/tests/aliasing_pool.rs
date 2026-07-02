// SPDX-License-Identifier: Apache-2.0
//
// AliasingMemento pool integration tests. Verifies that MementoPool
// correctly indexes aliasing-memento entries and answers
// has_aliasing_memento queries with canonical pair ordering.

use libsugar::compose::OpacityMementoLookup;
use sugar_verifier::types::{MementoCid, MementoPool};

fn blake3_cid(data: &str) -> MementoCid {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(
        format!("{data}-{}", COUNTER.fetch_add(1, Ordering::Relaxed)).as_bytes(),
    ))
    .expect("test CID must parse")
}

fn make_aliasing_memento(formal_a: &str, formal_b: &str, status: &str) -> serde_json::Value {
    use serde_json::json;
    json!({
        "envelope": {
            "header": {
                "kind": "aliasing-memento",
                "formal_a": formal_a,
                "formal_b": formal_b,
            },
            "metadata": {
                "status": status,
            }
        }
    })
}

#[test]
fn aliasing_memento_pool_insert_and_query() {
    let mut pool = MementoPool::default();
    let memento = make_aliasing_memento("x", "y", "Disjoint");
    let cid = blake3_cid("test");
    pool.insert(cid.clone(), memento);
    assert!(
        pool.has_aliasing_memento("x", "y"),
        "pool must find aliasing memento for (x, y) "
    );
    assert!(
        pool.has_aliasing_memento("y", "x"),
        "pool must find aliasing memento for (y, x): order-independent lookup "
    );
    assert!(
        pool.has_aliasing_memento("x", "y"),
        "pool must find aliasing memento for (x, y): idempotent "
    );
}

#[test]
fn aliasing_memento_pool_swapped_order_still_queryable() {
    let mut pool = MementoPool::default();
    let memento = make_aliasing_memento("alpha", "beta", "Disjoint");
    let cid = blake3_cid("test");
    pool.insert(cid.clone(), memento);
    assert!(
        pool.has_aliasing_memento("alpha", "beta"),
        "pool must find memento for canonical order (alpha, beta) "
    );
    assert!(
        pool.has_aliasing_memento("beta", "alpha"),
        "pool must find memento when queried in reverse order (beta, alpha) "
    );
}

#[test]
fn aliasing_memento_pool_rejects_missing_pair() {
    let mut pool = MementoPool::default();
    let memento = make_aliasing_memento("p", "q", "MaybeAlias");
    let cid = blake3_cid("test");
    pool.insert(cid.clone(), memento);
    assert!(
        !pool.has_aliasing_memento("p", "r"),
        "pool must not find aliasing memento for unregistered pair (p, r) "
    );
    assert!(
        !pool.has_aliasing_memento("other", "thing"),
        "pool must not find aliasing memento for completely unrelated pair "
    );
}

#[test]
fn aliasing_memento_pool_multiple_pairs() {
    let mut pool = MementoPool::default();

    let m1 = make_aliasing_memento("a", "b", "Disjoint");
    pool.insert(blake3_cid("m1"), m1);

    let m2 = make_aliasing_memento("b", "c", "MaybeAlias");
    pool.insert(blake3_cid("m2"), m2);

    assert!(pool.has_aliasing_memento("a", "b"), "must find (a, b) ");
    assert!(
        pool.has_aliasing_memento("b", "a"),
        "must find (a, b) reversed "
    );
    assert!(pool.has_aliasing_memento("b", "c"), "must find (b, c) ");
    assert!(
        pool.has_aliasing_memento("c", "b"),
        "must find (b, c) reversed "
    );
    assert!(
        !pool.has_aliasing_memento("a", "c"),
        "must NOT find (a, c): no memento for that pair "
    );
}

#[test]
fn aliasing_memento_pool_lexicographic_canonical_order() {
    let mut pool = MementoPool::default();
    let memento = make_aliasing_memento("zebra", "apple", "Disjoint");
    let cid = blake3_cid("test");
    pool.insert(cid.clone(), memento);
    assert!(
        pool.has_aliasing_memento("zebra", "apple"),
        "pool must store and find pair regardless of input lex order "
    );
    assert!(
        pool.has_aliasing_memento("apple", "zebra"),
        "pool must canonicalize: find when querying with swapped lex order "
    );
}
