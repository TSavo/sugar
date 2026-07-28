"""CHAINED ASSIGNMENT LAW.

Concrete:

    a = b = expr
    a = o.x = expr

Acceptance:

  - RHS evaluates once (one desugar of the value sugar)
  - the same reduced value is presented to every store leaf
  - stores run left-to-right in source order
  - first-store halt blocks later stores (no second desugar_store)
  - pure-name chain constructs ``ChainedAssignSugar``; substitute spends names
  - mixed name+store chain keeps bindings on the sugar and sequences stores

Owner path: ``ChainedAssignSugar`` / ``_PreconstructedStoreSugar.desugar_store``.
No carrier/ExitSet/import edits.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset
from sugar_lift_py_tests.sugar.assign_sugar import ChainedAssignSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _Site:
    filename: str = "chained_assign.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


SITE = _Site()


def _root(owner: str = "chain"):
    return ReduceContext.root(owner=owner)


class _CountRhs(Sugar):
    """RHS sugar that counts desugar calls — must be exactly one."""

    def __init__(self, n: int = 7):
        self.n = n
        self.calls = 0
        self.site = SITE

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        self.calls += 1
        return Complete(TermValue(self.n))


class _RecordingStore(Sugar):
    def __init__(self, label: str):
        self.label = label
        self.site = SITE
        self.calls = 0
        self.seen_value = None
        self.order_log: list | None = None

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        raise AssertionError("chained stores use desugar_store, not desugar")

    def desugar_store(self, ctx, value):
        self.calls += 1
        self.seen_value = value
        if self.order_log is not None:
            self.order_log.append(self.label)
        return Complete(BlockValue((), can_fall_through=True))


class _HaltStore(Sugar):
    def __init__(self, effect, label: str = "halt"):
        self.effect = effect
        self.label = label
        self.site = SITE
        self.calls = 0
        self.order_log: list | None = None

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        raise AssertionError("chained stores use desugar_store, not desugar")

    def desugar_store(self, ctx, value):
        self.calls += 1
        if self.order_log is not None:
            self.order_log.append(self.label)
        return Incomplete(self.effect)


def _tree(source: str, name: str = "chained_assign.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


# ---------------------------------------------------------------------------
# Single RHS evaluation
# ---------------------------------------------------------------------------


def test_chained_stores_evaluate_rhs_once() -> None:
    rhs = _CountRhs(7)
    first = _RecordingStore("first")
    second = _RecordingStore("second")
    sugar = ChainedAssignSugar(
        bindings=(),
        stores=(first, second),
        value=rhs,
        site=SITE,
    )
    out = sugar.desugar(_root("once"))
    assert isinstance(out, Complete)
    assert rhs.calls == 1
    assert first.calls == 1 and second.calls == 1
    assert first.seen_value == TermValue(7)
    assert second.seen_value == TermValue(7)
    # Same reduced cell presented to both stores (single evaluation).
    assert first.seen_value is second.seen_value


def test_pure_name_chain_still_desugars_rhs_once() -> None:
    """Even with no store leaves, the sugar door evaluates the RHS once."""
    rhs = _CountRhs(9)
    sugar = ChainedAssignSugar(
        bindings=(("a", rhs), ("b", rhs)),
        stores=(),
        value=rhs,
        site=SITE,
    )
    out = sugar.desugar(_root("names"))
    assert isinstance(out, Complete)
    assert rhs.calls == 1


# ---------------------------------------------------------------------------
# Ordered stores; first halt blocks later
# ---------------------------------------------------------------------------


def test_stores_run_left_to_right() -> None:
    order: list[str] = []
    rhs = _CountRhs(1)
    a = _RecordingStore("a")
    b = _RecordingStore("b")
    c = _RecordingStore("c")
    a.order_log = b.order_log = c.order_log = order
    sugar = ChainedAssignSugar(
        bindings=(),
        stores=(a, b, c),
        value=rhs,
        site=SITE,
    )
    sugar.desugar(_root("order"))
    assert order == ["a", "b", "c"]


def test_first_store_halt_blocks_later_stores() -> None:
    order: list[str] = []
    effect = NameErrorEffect(name="x", site=SITE)
    rhs = _CountRhs(3)
    halt = _HaltStore(effect, label="halt")
    later = _RecordingStore("later")
    halt.order_log = later.order_log = order
    sugar = ChainedAssignSugar(
        bindings=(),
        stores=(halt, later),
        value=rhs,
        site=SITE,
    )
    out = sugar.desugar(_root("halt"))
    assert rhs.calls == 1
    assert halt.calls == 1
    assert later.calls == 0
    assert order == ["halt"]
    # Halt surface: ExitSet with Halted, or Incomplete after collapse.
    if isinstance(out, ExitSet):
        halted = [e for e in out.exits if isinstance(e, Halted)]
        assert len(halted) == 1
        assert halted[0].effect is effect
    else:
        assert isinstance(out, Incomplete)
        assert out.effect is effect


def test_halt_after_earlier_completed_store_still_blocks_tail() -> None:
    order: list[str] = []
    effect = NameErrorEffect(name="y", site=SITE)
    rhs = _CountRhs(4)
    first = _RecordingStore("first")
    halt = _HaltStore(effect, label="halt")
    third = _RecordingStore("third")
    first.order_log = halt.order_log = third.order_log = order
    sugar = ChainedAssignSugar(
        bindings=(),
        stores=(first, halt, third),
        value=rhs,
        site=SITE,
    )
    out = sugar.desugar(_root("mid-halt"))
    assert first.calls == 1
    assert halt.calls == 1
    assert third.calls == 0
    assert order == ["first", "halt"]
    if isinstance(out, ExitSet):
        assert any(isinstance(e, Halted) and e.effect is effect for e in out.exits)
    else:
        assert isinstance(out, Incomplete) and out.effect is effect


# ---------------------------------------------------------------------------
# Source construction
# ---------------------------------------------------------------------------


def test_source_pure_name_chain_is_chained_assign_sugar() -> None:
    source = "def f(p):\n    x = y = p\n    return x\n"
    tree = _tree(source)
    function = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    sugar = function.sugar()
    chained = [
        st for st in sugar.statements if type(st).__name__ == "ChainedAssignSugar"
    ]
    assert len(chained) == 1
    assert chained[0].stores == ()
    assert {name for name, _ in chained[0].bindings} == {"x", "y"}


def test_source_mixed_name_and_attr_store_chain() -> None:
    source = "def f(o):\n    a = o.x = 5\n    return a\n"
    tree = _tree(source)
    function = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    sugar = function.sugar()
    chained = [
        st for st in sugar.statements if type(st).__name__ == "ChainedAssignSugar"
    ]
    assert len(chained) == 1
    assert any(name == "a" for name, _ in chained[0].bindings)
    assert len(chained[0].stores) == 1
    store = chained[0].stores[0]
    assert type(store).__name__ == "AttributeStoreEffectSugar"
    assert store.attr == "x"


def test_source_pure_name_chain_return_is_rhs_value() -> None:
    """Substitute spends the chain: ``a = b = 5; return a`` → TermValue(5)."""
    source = "def f():\n    a = b = 5\n    return a\n"
    tree = _tree(source)
    function = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    out = function.sugar().desugar(None)
    assert isinstance(out, Complete)
    record = out.value.record
    from sugar_lift_py_tests.floor import ReturnValue

    rets = [e for e in record.statements if isinstance(e, ReturnValue)]
    assert rets and rets[0].value == TermValue(5)


# ---------------------------------------------------------------------------
# Twin: reordered stores change call order (law is order-sensitive)
# ---------------------------------------------------------------------------


def test_reordered_stores_change_execution_order() -> None:
    order_ab: list[str] = []
    order_ba: list[str] = []
    for stores, log in (
        (
            (_RecordingStore("a"), _RecordingStore("b")),
            order_ab,
        ),
        (
            (_RecordingStore("b"), _RecordingStore("a")),
            order_ba,
        ),
    ):
        for s in stores:
            s.order_log = log
        ChainedAssignSugar(
            bindings=(),
            stores=stores,
            value=_CountRhs(0),
            site=SITE,
        ).desugar(_root("order-twin"))
    assert order_ab == ["a", "b"]
    assert order_ba == ["b", "a"]
    assert order_ab != order_ba
