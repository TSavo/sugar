"""A term's content CID is the root CID the wire term table mints.

``_term_content_cid`` hashes the root's expanded canonical text once instead
of building a full ``TermTableBuilder`` (one blake3 and one node per
subterm).  The coordinate must be byte-identical to the table's root CID for
leaves, spines, and shared DAG children, and a deep spine must not pay the
per-node table.
"""

from __future__ import annotations

import time

from sugar_lift_py_tests.ir import (
    TermTableBuilder,
    _term_content_cid,
    ctor,
    make_var,
)


def _table_root(term) -> str:
    return TermTableBuilder().reference(term)["cid"]


def test_root_cid_equals_table_root_for_leaf_spine_and_shared_dag():
    leaf = make_var("x")
    shared = ctor("pair", [leaf, make_var("y")])
    dag = ctor("triple", [shared, shared, ctor("wrap", [shared])])
    spine = leaf
    for i in range(50):
        spine = ctor(f"s{i % 3}", [spine, make_var(f"v{i}")])
    for term in (leaf, shared, dag, spine):
        assert TermTableBuilder.root_cid(term) == _table_root(term)
        assert _term_content_cid(term) == _table_root(term)


def test_structurally_equal_terms_share_cid_distinct_terms_differ():
    a = ctor("f", [make_var("x"), ctor("g", [make_var("y")])])
    b = ctor("f", [make_var("x"), ctor("g", [make_var("y")])])
    c = ctor("f", [make_var("x"), ctor("g", [make_var("z")])])
    assert a is not b
    assert _term_content_cid(a) == _term_content_cid(b)
    assert _term_content_cid(a) != _term_content_cid(c)


def test_root_cid_skips_the_per_node_table():
    spine = make_var("x")
    for i in range(400):
        spine = ctor("s", [spine, make_var(f"v{i}")])
    started = time.perf_counter()
    root = TermTableBuilder.root_cid(spine)
    root_elapsed = time.perf_counter() - started
    started = time.perf_counter()
    table = _table_root(spine)
    table_elapsed = time.perf_counter() - started
    assert root == table
    assert root_elapsed < table_elapsed
