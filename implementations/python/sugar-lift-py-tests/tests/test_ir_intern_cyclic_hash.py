"""IR term intern must not SEGV on cyclic / over-deep constructor graphs.

Illegal shape (vendor wall, sklearn fenwick / #5340 mechanism 3):
  ``_intern_term`` used ``table.setdefault(term, term)``, which invokes the
  frozen-dataclass recursive ``__hash__`` of ``_Ctor``. A cyclic args graph
  (or a spine past the CPython recursion limit) overflows into SIGSEGV.

Replacement shape:
  Iterative, bottom-up hash-cons keyed by finite structural tuples (child
  identity after child intern). Cycles are a construction bug and raise
  ``FactoryPanic`` — loud, typed, never soft-complete, never timeout.

R_native_crashes vendor wall: this retires the fenwick overflow-class SEGV
seat when the file remeasures as FactoryPanic or completes; the historical
board row stays on the crash axis until remeasured.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.ir import (
    _Ctor,
    _Var,
    _intern_term,
    ctor,
    make_var,
    num,
    term_intern_scope,
)


def _cyclic_ctor(name: str = "loop") -> _Ctor:
    node = _Ctor(name, ())
    # Frozen terms are DAGs by construction; a cycle only appears when the
    # args tuple is rewritten after mint (the illegal shape the intern must
    # refuse loudly rather than hash into SEGV).
    object.__setattr__(node, "args", (node,))
    return node


def test_cyclic_ctor_intern_is_factory_panic_not_recursion_or_segv() -> None:
    """R=1 while intern still blows the stack on a cyclic _Ctor graph."""
    cyclic = _cyclic_ctor("call:fenwick.cycle")
    with term_intern_scope():
        with pytest.raises(FactoryPanic) as raised:
            _intern_term(cyclic)

    info = raised.value.info
    assert info.owner == "ir._intern_term", (
        f"R=1 cyclic intern owner wrong: {info.owner!r}; "
        "replacement=FactoryPanic from ir._intern_term naming the cyclic graph"
    )
    assert "cyclic" in info.observed, (
        f"R=1 observed must name the cyclic IR term shape, got {info.observed!r}"
    )
    assert "DAG" in info.requested or "hash-cons" in info.requested
    assert "RuntimeEffect" in info.fix or "timeout" in info.fix.lower()


def test_cyclic_ctor_via_public_ctor_parent_is_factory_panic() -> None:
    """CallSiteValue.add → ctor('+', [cyclic, ...]) must panic, not SEGV."""
    cyclic = _cyclic_ctor("call:left")
    with term_intern_scope():
        with pytest.raises(FactoryPanic) as raised:
            ctor("+", [cyclic, num(1)])

    assert raised.value.info.owner == "ir._intern_term"
    assert "cyclic" in raised.value.info.observed


def test_deep_ctor_spine_interns_without_recursive_hash() -> None:
    """Deep linear spines must hash-cons iteratively (no recursion cliff)."""
    depth = 5_000
    with term_intern_scope():
        term = make_var("leaf")
        for index in range(depth):
            term = ctor(f"ssa:{index}", [term])
        again = make_var("leaf")
        for index in range(depth):
            again = ctor(f"ssa:{index}", [again])
        assert term is again


def test_structurally_equal_uninterned_trees_share_after_intern() -> None:
    left = _Ctor("+", (_Var("x"), _Ctor("num", ())))
    right = _Ctor("+", (_Var("x"), _Ctor("num", ())))
    assert left is not right
    with term_intern_scope():
        a = _intern_term(left)
        b = _intern_term(right)
    assert a is b
