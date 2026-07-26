"""Identity derivation is paid once per distinct object, never per comparison.

The gate for #6305 commit 1. ``ExitSet.normalize`` compares each incoming exit
against every prior one, so a coordinate that reminted on every ``__hash__`` /
``__eq__`` made identity work scale with *comparisons*. These tests pin the
scaling to *distinct objects*, and pin that memoization did not become identity:
the same structural formula still yields the same key, in or out of an intern
scope, before or after eviction, and cyclic formulas are never published.
"""

from __future__ import annotations

from sugar_lift_py_tests import ir
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.ir import (
    _Connective,
    _evict_formula_content_key,
    _formula_content_key,
    _formula_content_key_mints,
    and_,
    atomic,
    gt,
    make_var,
    num,
    term_intern_scope,
)


def _distinct_guards(count: int) -> list:
    return [
        and_([gt(make_var(f"v{i}"), num(i)), gt(num(i), num(0))]) for i in range(count)
    ]


def test_formula_identity_work_scales_with_objects_not_comparisons() -> None:
    guards = _distinct_guards(24)
    for guard in guards:  # prime: one walk apiece
        hash(guard)

    before = _formula_content_key_mints()
    comparisons = 0
    for left in guards:
        for right in guards:
            left == right
            hash(left)
            comparisons += 1

    assert comparisons == 24 * 24
    # The all-pairs scan is the shape normalize produces. Not one walk of it.
    assert _formula_content_key_mints() == before


def test_first_derivation_walks_each_distinct_node_exactly_once() -> None:
    guard = and_([gt(make_var("fresh_a"), num(7)), gt(make_var("fresh_b"), num(9))])

    before = _formula_content_key_mints()
    _formula_content_key(guard)
    first_walk = _formula_content_key_mints() - before

    # Root plus its two operands; the shared leaf terms are the term memo's job.
    assert first_walk == 3

    _formula_content_key(guard)
    assert _formula_content_key_mints() - before == first_walk


def test_memo_is_cache_control_not_identity() -> None:
    guard = and_([gt(make_var("evict_me"), num(3))])
    minted = _formula_content_key(guard)

    assert _evict_formula_content_key(guard) is True
    # Recomputation after eviction is deterministic and total, and republishes.
    assert _formula_content_key(guard) == minted
    assert _evict_formula_content_key(guard) is True


def test_cached_key_is_scope_stable() -> None:
    guard = and_([gt(make_var("scoped"), num(11))])
    outside = _formula_content_key(guard)

    with term_intern_scope():
        assert _formula_content_key(guard) == outside

    assert _formula_content_key(guard) == outside


def test_structural_twins_agree_whether_or_not_either_is_cached() -> None:
    left = and_([gt(make_var("twin"), num(5))])
    cached = _formula_content_key(left)

    right = _Connective("and", (gt(make_var("twin"), num(5)),))

    assert _formula_content_key(right) == cached
    assert left == right
    assert hash(left) == hash(right)


def test_cyclic_formula_nodes_are_never_published_to_the_memo() -> None:
    inner = atomic("cyclic_probe", [make_var("c")])
    cycle = _Connective("and", (inner,))
    object.__setattr__(cycle, "operands", (inner, cycle))

    # Finite and repeatable — the walk's cycle marker still does its job.
    assert _formula_content_key(cycle) == _formula_content_key(cycle)

    # A node reached inside a cycle carries an ancestor-relative marker, so it
    # must not be cached: ``inner`` standing alone has its own coordinate.
    assert _formula_content_key(inner) == _formula_content_key(
        atomic("cyclic_probe", [make_var("c")])
    )


def test_callsite_identity_is_memoized_per_object(monkeypatch) -> None:
    calls = [
        CallSiteValue("opaque", (), (), make_var(f"site{i}"), None) for i in range(16)
    ]
    for call in calls:
        hash(call)  # prime

    # Memo *size* is the wrong gate: it counts distinct terms, so it is flat
    # with or without this mechanism. Count the derivations themselves.
    derivations = 0
    real = ir._term_content_cid

    def counting(term):
        nonlocal derivations
        derivations += 1
        return real(term)

    monkeypatch.setattr(ir, "_term_content_cid", counting)

    comparisons = 0
    for left in calls:
        for right in calls:
            left == right
            comparisons += 1

    assert comparisons == 16 * 16
    # 512 coordinate derivations without the memo; none with it.
    assert derivations == 0


def test_callsite_memo_does_not_leak_into_the_dataclass_surface() -> None:
    call = CallSiteValue("opaque", (), (), make_var("surface"), None)
    hash(call)

    assert "_identity_key" not in repr(call)
    assert all(f.name != "_identity_key" for f in call.__dataclass_fields__.values())
