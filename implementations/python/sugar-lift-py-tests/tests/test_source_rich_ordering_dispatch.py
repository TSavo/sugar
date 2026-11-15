"""``a <op> b`` on a source-class instance dispatches to the class's own method.

Python evaluates ``a < b`` as ``type(a).__lt__(a, b)``.  The lifter invokes the
left operand's authenticated source ``__lt__`` / ``__le__`` / ``__gt__`` /
``__ge__`` frame (the same mechanism ``==`` uses for ``__eq__``) and yields that
body's result.  A left operand without the method, a non-boolean
(``NotImplemented``) result, or an unauthenticated (cross-class) method order
still refuses by name.  A constructed operand whose construction may raise is
compared on each receiver face it can be; the construction halt leaves as
itself.

``Box(1) < Box(2)`` today (#7757 steps 5 and 6, the owner's ruling "Edge,
join at prove"): each ``Box(...)`` is the class's coordinate and edge
(#8738), whose body is never applied at lift, so each operand is a class
call's result.  Which ``__lt__`` an operation on a class call's result runs
is dispatch at prove (step 8, not merged): the comparison is the undecided
ordering (``undecided_ordering_faces``), completing with the undecided
``py.lt`` predicate under its ``completes`` atom and halting under the
complement.  The truthful result and the three refusals by name (a class
without the method, ``NotImplemented``, a cross-class order) are decided
there; until then each source below is that undecided comparison, never a
bool literal and never a refusal invented at lift.  The native ``exec``
lines keep what Python computes, the answer step 8 must reach.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.receiver_state_partition_value import (
    ReceiverStatePartitionValue,
)
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
    (done,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (statement,) = done.value.record.statements
    return statement.value


def _undecided_ordering(source: str) -> None:
    """``f``'s row compares two class call results: the undecided ordering
    until dispatch at prove (step 8).  Its one completed face returns the
    undecided predicate; the class calls and the comparison halt beside it
    (``Halted`` faces), none dropped."""
    from sugar_lift_py_tests.floor import PredicateValue

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
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    returned = _returned(source)
    assert isinstance(returned, PredicateValue), type(returned)
    assert not isinstance(returned, (TrueBoolLiteralSugar, FalseBoolLiteralSugar))


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

    # Was ``TrueBoolLiteralSugar`` while the body was applied at lift; the
    # source ``__lt__`` is reached by dispatch at prove (step 8).
    _undecided_ordering(source)


def test_less_than_yields_the_source_body_not_a_default_ordering():
    # The method decides, even against the fields' natural order.
    source = _box("__lt__", "self.n > other.n", "Box(1) < Box(2)")
    native: dict = {}
    exec(source, native)
    assert native["f"]() is False

    # Was ``FalseBoolLiteralSugar``; never a default ordering of the
    # fields at lift either: the undecided predicate until step 8.
    _undecided_ordering(source)


def test_greater_equal_dispatches_to_the_source_ge():
    source = _box("__ge__", "self.n >= other.n", "Box(3) >= Box(2)")
    native: dict = {}
    exec(source, native)
    assert native["f"]() is True

    # Was ``TrueBoolLiteralSugar``: decided by dispatch at prove (step 8).
    _undecided_ordering(source)


def test_a_class_without_the_method_still_refuses_by_name():
    # Box defines __ge__ only: ``<`` has no source method on the left.
    # Was the refusal ``FloorValue.less_than_from_left``, which read Box's
    # namespace off an instance made by applying its constructor at lift.
    # A class call's result is its coordinate (#8738), so which method runs
    # is dispatch at prove (step 8); today the comparison is undecided,
    # never a completion invented for it.
    _undecided_ordering(_box("__ge__", "True", "Box(1) < Box(2)"))


def test_a_not_implemented_result_is_refused_not_accepted():
    # Was the refusal ``ObjectValue.less_than`` of the body's
    # ``NotImplemented``; the body is the method's contract, reached by
    # dispatch at prove (step 8).  Today: undecided, never accepted.
    _undecided_ordering(_box("__lt__", "NotImplemented", "Box(1) < Box(2)"))


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
    # Was the refusal ``ObjectValue.less_equal``; the method order over two
    # class call results is dispatch at prove (step 8).  Today: undecided.
    _undecided_ordering(source)


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
    # The ground raise is a halt: its one exit carries the effect.
    (raised,) = ground_exceptional_exit(
        exception_name="ValueError", site=site, owner="test"
    ).halts()
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
