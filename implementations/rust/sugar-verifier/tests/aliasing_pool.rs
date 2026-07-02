// SPDX-License-Identifier: Apache-2.0
//
// AliasingMemento pool integration tests. Verifies that MementoPool
// correctly indexes aliasing-memento entries and answers
// has_aliasing_memento queries with canonical pair ordering.

use libsugar::compose::OpacityMementoLookup;
use sugar_verifier::types::{AnchoredMember, MementoCid, MementoPool};

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

fn insert_aliasing_memento(pool: &mut MementoPool, memento: serde_json::Value) {
    let cid = MementoCid::try_parse(sugar_proof_envelope::recompute_member_cid(&memento))
        .expect("computed test CID must parse");
    let member = AnchoredMember::new(cid, memento).expect("test member must anchor");
    pool.insert(member);
}

#[test]
fn aliasing_memento_pool_insert_and_query() {
    let mut pool = MementoPool::default();
    let memento = make_aliasing_memento("x", "y", "Disjoint");
    insert_aliasing_memento(&mut pool, memento);
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
    insert_aliasing_memento(&mut pool, memento);
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
    insert_aliasing_memento(&mut pool, memento);
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
    insert_aliasing_memento(&mut pool, m1);

    let m2 = make_aliasing_memento("b", "c", "MaybeAlias");
    insert_aliasing_memento(&mut pool, m2);

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
    insert_aliasing_memento(&mut pool, memento);
    assert!(
        pool.has_aliasing_memento("zebra", "apple"),
        "pool must store and find pair regardless of input lex order "
    );
    assert!(
        pool.has_aliasing_memento("apple", "zebra"),
        "pool must canonicalize: find when querying with swapped lex order "
    );
}
