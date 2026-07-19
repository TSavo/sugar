"""#5338 — CallSiteValue term cycle keys must not re-CID whole term DAGs.

Product residual after #5449 (exact-nine last hard timeout):
``sklearn/utils/tests/test_stats.py`` · ``reduce_body`` · tip ``AddOpSugar``
@ ``sklearn/utils/stats.py:205`` (``array[...] + array[...]``).

Profile under ``term_intern_scope`` / product ``lift_file_payload``:

  - ``AddOpSugar.desugar`` only twice, ~5s each
  - wall: ``CallSiteValue.add`` → ``_dig_or_symbolic_binop`` → dig cycle
    bookkeeping + ``CallSiteValue.__hash__`` / ``__eq__``
  - root cause: ``_term_cycle_key`` built a fresh ``TermTableBuilder`` CID
    (full blake3 materialization) for every dig/hash/eq on deep callsite terms

Microbench before fix (depth 250, under intern scope):

  - 10× ``_term_cycle_key`` ≈ 2.1s
  - 20× ``hash``+``eq`` on one CallSiteValue ≈ 11.5s

That is the same shared mechanism as #5435's formula-key thrash, now on the
callsite dig/identity door rather than formula intern.

Replacement architecture (#5569):
  cycle keys are **always** permanent content CIDs (scope-stable). Under
  ``term_intern_scope``, memoize CID by interned object so repeated keys do
  not re-pay blake3 — never use ``id()`` as the identity itself.

This instrument stays red while CallSiteValue identity/dig keys re-pay full
CID materialization under an active intern scope. Never soft-complete; never
raise the product bound; never mint RuntimeEffect laundry.
"""

from __future__ import annotations

import time

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue, _term_cycle_key
from sugar_lift_py_tests.ir import (
    TermTableBuilder,
    ctor,
    make_var,
    term_intern_scope,
)


def _deep_term(depth: int):
    term = make_var("leaf")
    for index in range(depth):
        term = ctor(f"ssa:{index}", [term])
    return term


def test_term_cycle_key_under_intern_scope_stays_under_budget() -> None:
    """Repeated cycle keys on a deep interned DAG must not re-pay CID walks."""
    depth = 250
    repeats = 20
    budget_seconds = 0.05
    with term_intern_scope():
        term = _deep_term(depth)
        warm = _term_cycle_key(term)  # first materialize may pay; must be content CID
        started = time.perf_counter()
        keys = [_term_cycle_key(term) for _ in range(repeats)]
        elapsed = time.perf_counter() - started
    assert warm.startswith("blake3-512:")
    assert len(set(keys)) == 1 and keys[0] == warm
    assert not warm.startswith("term-id:"), (
        "term-id: keys are the scope-dependent #5477 bug (#5569)."
    )
    assert elapsed < budget_seconds, (
        f"R=1 memoized _term_cycle_key×{repeats} over depth={depth} paid "
        f"{elapsed:.3f}s (budget {budget_seconds}s after first materialize). "
        "Replacement: memoize content CID under term_intern_scope "
        "(never id() as identity). "
        "Do not raise product timeout, soft-complete, or mint RuntimeEffect."
    )


def test_callsite_hash_eq_under_intern_scope_stays_under_budget() -> None:
    """CallSiteValue hash/eq is the product seat for dig-set membership thrash."""
    depth = 250
    repeats = 40
    budget_seconds = 0.08
    with term_intern_scope():
        term = _deep_term(depth)
        twin = _deep_term(depth)
        assert term is twin
        left = CallSiteValue("xp.searchsorted", (), (), term, None)
        right = CallSiteValue("xp.searchsorted", (), (), twin, None)
        assert hash(left) == hash(right) and left == right  # warm CID memo
        started = time.perf_counter()
        for _ in range(repeats):
            assert hash(left) == hash(right)
            assert left == right
        elapsed = time.perf_counter() - started
    assert elapsed < budget_seconds, (
        f"R=1 CallSiteValue hash/eq×{repeats} depth={depth} paid {elapsed:.3f}s "
        f"(budget {budget_seconds}s after warm). __hash__/__eq__ must use "
        "memoized content CID via _term_cycle_key (scope-stable, #5569)."
    )


def test_callsite_add_on_deep_terms_does_not_rebuild_cid_keys() -> None:
    """Symbolic add on opaque deep callsites must not CID-thrash cycle keys.

    Product shape: ``array[i] + array[j]`` where both sides are CallSiteValue
    (subscript / method coordinates) with diggable-or-opaque bodies. Dig cycle
    bookkeeping and any set membership on the callsite must stay O(1) after
    term intern.
    """
    depth = 200
    budget_seconds = 0.15
    with term_intern_scope():
        left_term = _deep_term(depth)
        right_term = ctor("pair", [left_term, make_var("other")])
        left = CallSiteValue(
            "array.__getitem__",
            (),
            (),
            left_term,
            None,  # opaque body → dig returns None → symbolic +
        )
        right = CallSiteValue(
            "array.__getitem__",
            (),
            (),
            right_term,
            None,
        )
        started = time.perf_counter()
        for _ in range(8):
            outcome = left.add(right, site="stats.py:205")
            assert outcome is not None
        elapsed = time.perf_counter() - started
    assert elapsed < budget_seconds, (
        f"R=1 CallSiteValue.add×8 over depth={depth} paid {elapsed:.3f}s "
        f"(budget {budget_seconds}s). Dig cycle keys must not rebuild "
        "TermTableBuilder CIDs under term_intern_scope (#5338 test_stats)."
    )


def test_outside_intern_scope_cycle_key_still_matches_content_cid() -> None:
    """Outside scope, keep content CID identity (legacy heap-backed contract)."""
    term = _deep_term(80)
    assert _term_cycle_key(term) == TermTableBuilder().reference(term)["cid"]
