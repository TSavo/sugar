"""The structure-keyed content-CID memo gives the CID the fresh path mints.

A lift mints structurally equal terms as fresh objects (pinned pandas
``tests/io/pytables/test_subclass.py``: 144,444 root CIDs over 310 distinct
structures), and each fresh object re-serialized and re-hashed its whole
expanded form.  ``_term_content_cid`` now memoizes on a structural key built
from exactly what the canonical text encodes.  That is only admissible if the
memo answer is byte-identical to the fresh ``TermTableBuilder.root_cid`` for
every term, and if structures that encode differently never share an entry.
"""

from __future__ import annotations

import random

from sugar_lift_py_tests import ir
from sugar_lift_py_tests.ir import (
    PrimitiveSort,
    TermTableBuilder,
    _structural_cid,
    _term_content_cid,
    ctor,
    make_var,
)


def _leaves():
    sort_int = PrimitiveSort("Int")
    sort_str = PrimitiveSort("String")
    return [
        make_var("x"),
        make_var("y"),
        ir._ConstInt(7, sort_int),
        ir._ConstInt(8, sort_int),
        ir._ConstStr("7", sort_str),
        ir._ConstBool(True, PrimitiveSort("Bool")),
        ir._ConstReal("0.5", PrimitiveSort("Real")),
    ]


def _random_term(rng: random.Random, depth: int, pool: list):
    if depth == 0 or rng.random() < 0.25:
        return rng.choice(pool)
    roll = rng.random()
    if roll < 0.1:
        return ir._Lambda(
            rng.choice(["a", "b"]),
            PrimitiveSort(rng.choice(["Int", "Value"])),
            _random_term(rng, depth - 1, pool),
        )
    arity = rng.randrange(0, 4)
    node = ctor(
        rng.choice(["f", "g", "h"]),
        [_random_term(rng, depth - 1, pool) for _ in range(arity)],
    )
    if rng.random() < 0.3:
        pool.append(node)  # shared DAG children
    return node


def _rebuild(term):
    """A fresh, structurally equal object graph (no shared identities)."""
    if isinstance(term, ir._Ctor):
        return ir._Ctor(term.name, tuple(_rebuild(arg) for arg in term.args))
    if isinstance(term, ir._Lambda):
        return ir._Lambda(term.param_name, term.param_sort, _rebuild(term.body))
    return type(term)(**term.__dict__)


def test_memo_cid_equals_fresh_root_cid_for_random_terms():
    rng = random.Random(7664)
    for _ in range(400):
        term = _random_term(rng, 6, _leaves())
        fresh = TermTableBuilder.root_cid(term)
        assert _structural_cid(term) == fresh
        # A fresh twin is answered from the structure memo, identically.
        twin = _rebuild(term)
        assert twin is not term
        assert _structural_cid(twin) == fresh
        assert _term_content_cid(twin) == fresh


def test_structures_that_encode_differently_never_share_a_cid():
    sort_int = PrimitiveSort("Int")
    sort_str = PrimitiveSort("String")
    pairs = [
        (ir._ConstInt(7, sort_int), ir._ConstStr("7", sort_str)),
        (ctor("f", [make_var("x"), make_var("y")]), ctor("f", [make_var("y"), make_var("x")])),
        (ctor("f", [make_var("x")]), ctor("g", [make_var("x")])),
        (ctor("f", []), make_var("f")),
        (
            ir._Lambda("a", sort_int, make_var("a")),
            ir._Lambda("a", PrimitiveSort("Value"), make_var("a")),
        ),
        (
            ir._Lambda("a", sort_int, make_var("a")),
            ir._Lambda("b", sort_int, make_var("a")),
        ),
    ]
    for left, right in pairs:
        assert TermTableBuilder.root_cid(left) != TermTableBuilder.root_cid(right)
        assert _structural_cid(left) != _structural_cid(right)
        assert _structural_cid(left) == TermTableBuilder.root_cid(left)
        assert _structural_cid(right) == TermTableBuilder.root_cid(right)


def test_fresh_twins_do_not_reserialize():
    spine = make_var("x")
    for i in range(300):
        spine = ctor("s", [spine, make_var(f"v{i % 5}")])
    expected = TermTableBuilder.root_cid(spine)
    assert _structural_cid(spine) == expected
    calls = []
    original = TermTableBuilder.root_cid
    try:
        TermTableBuilder.root_cid = staticmethod(
            lambda root: calls.append(root) or original(root)
        )
        assert _structural_cid(_rebuild(spine)) == expected
    finally:
        TermTableBuilder.root_cid = staticmethod(original)
    assert calls == []
