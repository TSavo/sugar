"""Content identity is asked once per object, not once per comparison.

``Formula.__hash__``/``__eq__`` and ``CallSiteValue.__hash__``/``__eq__`` both
resolve to content coordinates: a formula content key, and a term wire CID.
Both used to re-walk the whole spine on every question. On
``pandas/core/generic.py`` that arrived as 35,339,381 ``_term_content_cid``
calls over 377,167 distinct Formula objects — identity work scaling with
COMPARISONS instead of with distinct OBJECTS.

The memos here are caches, never identity: ``id()`` is a memo index only, the
weakref ``is``-guard rejects a recycled id, and GC reclaims dead entries. The
coordinate is unchanged — no new digest, no wire identity, no repin.
"""

from __future__ import annotations

import gc

from sugar_lift_py_tests.ir import (
    _formula_content_key,
    _formula_content_key_memo_size,
    _term_content_cid,
    and_,
    atomic,
    ctor,
    make_var,
    not_,
    num,
)


def _guard(name: str):
    return atomic(name, [make_var("state")])


def test_formula_identity_work_scales_with_distinct_objects():
    guard = and_([_guard("p"), not_(_guard("q"))])
    first = _formula_content_key(guard)
    before = _formula_content_key_memo_size()
    for _ in range(500):
        assert _formula_content_key(guard) is first
    # Repeated identity questions about ONE object add no memo entries and
    # re-walk nothing: the key is the same object, not merely an equal tuple.
    assert _formula_content_key_memo_size() == before


def test_formula_identity_memo_survives_equal_but_distinct_objects():
    left = and_([_guard("p"), not_(_guard("q"))])
    right = and_([_guard("p"), not_(_guard("q"))])
    assert _formula_content_key(left) == _formula_content_key(right)
    assert left == right
    assert hash(left) == hash(right)


def test_term_content_cid_is_one_object_one_answer():
    term = ctor("call:f", [make_var("x"), num(3)])
    first = _term_content_cid(term)
    for _ in range(500):
        assert _term_content_cid(term) is first


def test_term_content_cid_is_the_same_coordinate_for_structural_twins():
    left = ctor("call:f", [make_var("x"), num(3)])
    right = ctor("call:f", [make_var("x"), num(3)])
    assert _term_content_cid(left) == _term_content_cid(right)


def test_identity_memo_does_not_pin_dead_formulas():
    before = _formula_content_key_memo_size()
    for index in range(200):
        _formula_content_key(and_([_guard(f"transient{index}"), not_(_guard("q"))]))
    gc.collect()
    after = _formula_content_key_memo_size()
    assert after <= before + 400, (
        f"memo grew from {before} to {after} over 200 discarded formulas; "
        "the weak memo must let GC reclaim dead entries"
    )
