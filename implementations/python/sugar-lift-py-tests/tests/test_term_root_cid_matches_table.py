"""A term's content CID is the root CID the wire term table mints.

``_term_content_cid`` hashes the root's term graph (Merkle, #7757: a row's
CID is the hash of the row itself, children named by their CIDs) without
building a full ``TermTableBuilder`` (one node dict per subterm).  The
coordinate must be byte-identical to the table's root CID for leaves, spines,
and shared DAG children, and minting it costs the graph's size, never the
size of the term written out.
"""

from __future__ import annotations

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


def test_a_doubling_chain_of_forty_conditionals_mints_in_graph_size():
    """``GuardedValue.to_term`` builds ``py.conditional(guard, a, b)`` with
    ``a`` containing ``b``: each level doubles the term written out (2**40
    copies of ``x`` here).  The table holds three rows per level and every
    CID is minted from them, so this finishes at once; hashing the written-out
    term would never finish."""
    term = make_var("x")
    for i in range(40):
        term = ctor(
            "py.conditional", [make_var(f"g{i}"), ctor("py.box", [term]), term]
        )
    table = TermTableBuilder()
    root = table.reference(term)["cid"]
    assert len(table.nodes) == 3 * 40 + 1
    assert TermTableBuilder.root_cid(term) == root
    assert _term_content_cid(term) == root
    row = table.nodes[root]
    assert row["name"] == "py.conditional"
    assert [arg["kind"] for arg in row["args"]] == ["term-ref"] * 3
