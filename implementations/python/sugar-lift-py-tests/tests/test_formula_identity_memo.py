"""Formula identity built over memoized children is the fresh identity.

``_formula_identity`` retains each live formula's (content key, hash) and,
when keying a new formula, reuses a child's retained identity instead of
re-walking it.  The hash is structural over child hashes, so a formula keyed
over memoized children and a structurally equal formula keyed from scratch
must agree on key AND hash, and the key must be exactly the content key.  A
recycled ``id()`` must never hand a dead formula's identity to a new one.
A guard grown by conjunction must key in linear, not quadratic, time.
"""

from __future__ import annotations

import gc
import time

from sugar_lift_py_tests.ir import (
    _formula_content_key,
    _formula_identity,
    and_,
    atomic,
    make_var,
    not_,
    or_,
)


def _shape(tag: str):
    a = atomic("p", [make_var(f"x{tag}")])
    b = atomic("q", [make_var("y")])
    return a, b, or_([and_([a, not_(b)]), not_(a)])


def test_memo_path_and_fresh_path_agree_on_key_and_hash():
    a, b, memo_formula = _shape("0")
    # Retain every child first: the parent is then keyed over memoized children.
    for child in (a, b, not_(b), and_([a, not_(b)])):
        _formula_identity(child)
    memo_key, memo_hash = _formula_identity(memo_formula)

    # A structurally equal formula whose children were never keyed.
    _, _, fresh_formula = _shape("0")
    fresh_key, fresh_hash = _formula_identity(fresh_formula)

    assert memo_key == fresh_key == _formula_content_key(fresh_formula)
    assert memo_hash == fresh_hash
    assert memo_formula == fresh_formula
    assert hash(memo_formula) == hash(fresh_formula)


def test_distinct_formulas_never_share_identity():
    _, _, left = _shape("1")
    _, _, right = _shape("2")
    assert _formula_identity(left)[0] != _formula_identity(right)[0]
    assert left != right


def test_recycled_id_never_returns_a_dead_formulas_key():
    seen = {}
    for index in range(2000):
        formula = and_([atomic("r", [make_var(f"v{index}")]), atomic("s", [])])
        key, hashed = _formula_identity(formula)
        assert key == _formula_content_key(formula)
        previous = seen.get(id(formula))
        if previous is not None:
            assert previous != key  # a reused address got its own identity
        seen[id(formula)] = key
        del formula
        if index % 100 == 0:
            gc.collect()


def test_long_conjunction_chain_keys_in_linear_time():
    guard = atomic("g", [make_var("g0")])
    hash(guard)
    started = time.perf_counter()
    for index in range(1, 3000):
        guard = and_([guard, atomic("g", [make_var(f"g{index}")])])
        hash(guard)
    assert time.perf_counter() - started < 5.0
