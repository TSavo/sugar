"""``a <op> b`` on a source-class instance dispatches to the class's own method.

Python evaluates ``a < b`` as ``type(a).__lt__(a, b)``.  The lifter invokes the
left operand's authenticated source ``__lt__`` / ``__le__`` / ``__gt__`` /
``__ge__`` frame (the same mechanism ``==`` uses for ``__eq__``) and yields that
body's result.  A left operand without the method, a non-boolean
(``NotImplemented``) result, or an unauthenticated (cross-class) method order
still refuses by name.  A constructed operand whose construction may raise is
compared on each receiver face it can be; the construction halt leaves as
itself.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.receiver_state_partition_value import (
    ReceiverStatePartitionValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _returned(source: str):
    tree = SourceFile(
        (source, "rich_ordering.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    outcome = function_universe_outcome(function)
    value = outcome.completed_value()
    assert value is not None
    (statement,) = value.record.statements
    return statement.value


_BOX = (
    "class Box:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "    def {dunder}(self, other):\n"
    "        return {body}\n"
    "def f():\n"
    "    return {expression}\n"
)


def _box(dunder: str, body: str, expression: str) -> str:
    return _BOX.format(dunder=dunder, body=body, expression=expression)


def test_less_than_dispatches_to_the_source_lt_and_yields_its_result():
    source = _box("__lt__", "self.n < other.n", "Box(1) < Box(2)")
    native: dict = {}
    exec(source, native)
    assert native["f"]() is True

    assert isinstance(_returned(source), TrueBoolLiteralSugar)


def test_less_than_yields_the_source_body_not_a_default_ordering():
    # The method decides, even against the fields' natural order.
    source = _box("__lt__", "self.n > other.n", "Box(1) < Box(2)")
    native: dict = {}
    exec(source, native)
    assert native["f"]() is False

    assert isinstance(_returned(source), FalseBoolLiteralSugar)


def test_greater_equal_dispatches_to_the_source_ge():
    source = _box("__ge__", "self.n >= other.n", "Box(3) >= Box(2)")
    native: dict = {}
    exec(source, native)
    assert native["f"]() is True

    assert isinstance(_returned(source), TrueBoolLiteralSugar)


def test_a_class_without_the_method_still_refuses_by_name():
    # Box defines __ge__ only: ``<`` has no source method on the left.
    source = _box("__ge__", "True", "Box(1) < Box(2)")
    with pytest.raises(ConstructionPanic, match="FloorValue.less_than_from_left"):
        _returned(source)


def test_a_not_implemented_result_is_refused_not_accepted():
    source = _box("__lt__", "NotImplemented", "Box(1) < Box(2)")
    with pytest.raises(ConstructionPanic, match="ObjectValue.less_than"):
        _returned(source)


def test_a_cross_class_method_order_is_refused():
    source = (
        "class Box:\n"
        "    def __init__(self, n):\n"
        "        self.n = n\n"
        "    def __le__(self, other):\n"
        "        return True\n"
        "class Other:\n"
        "    def __init__(self, n):\n"
        "        self.n = n\n"
        "def f():\n"
        "    return Box(1) <= Other(2)\n"
    )
    with pytest.raises(ConstructionPanic, match="ObjectValue.less_equal"):
        _returned(source)


@dataclass(frozen=True)
class _Fixed(ConstructedTermSugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    def to_term(self, *, owner: str):
        return TermValue(0).to_term(owner=owner)


def test_a_partitioned_operand_compares_on_each_receiver_and_keeps_its_halt():
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
    from sugar_lift_py_tests.outcome.exit_set import true_guard
    from sugar_source_tree.nodes import Name

    text = "Box(value) < limit\n"
    tree = SourceFile((text, "partitioned.py", blake3_512_of(text.encode())))
    site = next(node for node in tree.nodes() if isinstance(node, Name)).fragment
    raised = ground_exceptional_exit(
        exception_name="ValueError", site=site, owner="test"
    ).value
    halts = (Halted(true_guard(), raised.effect, None, frozenset()),)
    partition = ReceiverStatePartitionValue(
        exits=ExitSet((*halts, Completed(true_guard(), TermValue(1))))
    )

    outcome = ComparisonOpSugar(
        "Lt", _Fixed(partition), _Fixed(TermValue(2)), site=site
    ).desugar(None)

    exits = outcome.exits
    assert [face.effect for face in exits if isinstance(face, Halted)] == [
        face.effect for face in halts
    ]
    completed = [face for face in exits if isinstance(face, Completed)]
    assert len(completed) == 1
    assert isinstance(completed[0].value, TrueBoolLiteralSugar)
