"""Finite comprehensions transport exact item values or stay loudly unresolved."""

from __future__ import annotations

from dataclasses import replace

import pytest
from frame_fresh import FRAME_FRESH, fresh

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, ObjectValue, TermValue
from sugar_lift_py_tests.floor.object_field import ObjectField
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_source_tree.nodes import (
    FunctionDef,
    ListComp,
    Return,
    TargetPatternConstructionGapV1,
)
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (
            source,
            "tests/comprehension_item_value_transport.py",
            blake3_512_of(source.encode()),
        ),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _source_list_comprehension(source: str):
    """The comprehension as the function's body rewrite constructs it: its
    iterable ``items`` is the formal's reference (``FormalRef``), which reads
    the formal's coordinate, never the name."""
    (ret,) = _function(source).substitute({}).body
    assert isinstance(ret, Return) and isinstance(ret.value, ListComp)
    return ret.value.sugar()


def _context_with_items(source: str, items) -> ReduceContext:
    """A context in which ``build``'s formal ``items`` holds ``items``: bound
    under the formal's coordinate, as a followed call binds its actual."""
    (formal,) = _function(source).formal_coordinates()
    ctx = ReduceContext.root(owner="comprehension item transport")
    return replace(
        ctx, temporal=ctx.temporal.bind_value(formal.coordinate_cid, items)
    )


def _objects() -> tuple[ObjectValue, ObjectValue]:
    return (
        ObjectValue(
            "_NamedIntConstant", (), identity="member:first", allocation=FRAME_FRESH
        ),
        ObjectValue(
            "_NamedIntConstant", (), identity="member:second", allocation=FRAME_FRESH
        ),
    )


def test_swapped_finite_members_preserve_each_object_identity() -> None:
    first, second = _objects()
    source = "def build(items):\n    return [item for item in items]\n"
    comprehension = _source_list_comprehension(source)

    forward = comprehension.desugar(
        _context_with_items(source, fresh(ListValue, (first, second)))
    )
    swapped = comprehension.desugar(
        _context_with_items(source, fresh(ListValue, (second, first)))
    )

    assert forward.completed_value() is not None
    assert swapped.completed_value() is not None
    assert forward.completed_value().finite_elements == (first, second)
    assert swapped.completed_value().finite_elements == (second, first)
    assert swapped.completed_value().finite_elements[0] is second
    assert swapped.completed_value().finite_elements[1] is first


def test_filtered_out_member_never_reaches_element_binding() -> None:
    first = ObjectValue(
        "_NamedIntConstant",
        (ObjectField("keep", FalseBoolLiteralSugar(site="first.keep")),),
        identity="member:first",
        allocation=FRAME_FRESH,
    )
    second = ObjectValue(
        "_NamedIntConstant",
        (ObjectField("keep", TrueBoolLiteralSugar(site="second.keep")),),
        identity="member:second",
        allocation=FRAME_FRESH,
    )
    source = "def build(items):\n    return [item for item in items if item.keep]\n"
    comprehension = _source_list_comprehension(source)

    outcome = comprehension.desugar(
        _context_with_items(source, fresh(ListValue, (first, second)))
    )

    assert outcome.completed_value() is not None
    assert outcome.completed_value().finite_elements == (second,)
    assert outcome.completed_value().finite_elements[0] is second
    assert all(value is not first for value in outcome.completed_value().finite_elements)


def test_a_subscript_of_an_arrived_items_field_keeps_its_halt_undecided() -> None:
    first, second = _objects()
    first = replace(
        first, fields=(ObjectField("values", fresh(ListValue, (TermValue(7),))),)
    )
    second = replace(
        second, fields=(ObjectField("values", fresh(ListValue, (TermValue(9),))),)
    )
    source = "def build(items):\n    return [item.values[4] for item in items]\n"
    comprehension = _source_list_comprehension(source)

    outcome = comprehension.desugar(
        _context_with_items(source, fresh(ListValue, (first, second)))
    )

    # ``items`` is the formal's actual: it reaches ``build`` by binding, so
    # neither it nor anything in it is current (the one currency rule,
    # ``object_identity.arrived``, #8131/#8151).  Nothing binds a formal with
    # the caller's currency any more: a same-file call is its coordinate and
    # edge (#8705, #8751, #7757 step 6), never a followed frame.  So
    # ``item.values[4]`` is the undecided subscript, not the decided
    # ``IndexError`` this test read off the caller's contents before: the
    # halt is kept and no completion is decided here.  Whether the caller's
    # list holds a long enough ``values`` is decided at prove (step 9).
    assert outcome.halts()
    from sugar_lift_py_tests.outcome.exit_set import Completed

    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert all(
        "python:subscript_op.completes" in repr(arm.guard) for arm in completed
    ), completed


def test_tuple_target_coordinate_swap_is_refused_by_source_owner() -> None:
    comprehension = _source_list_comprehension(
        "def build(pairs):\n    return [item for index, item in pairs]\n"
    )
    generator = comprehension.generators[0]

    with pytest.raises(
        TargetPatternConstructionGapV1, match="target-coordinate-order-mismatch"
    ):
        replace(
            generator,
            target_coordinates=tuple(reversed(generator.target_coordinates)),
        )


def test_nonfinite_iterable_with_undecided_filter_owes_the_filter_read() -> None:
    """Over an iterable that is no finite container the comprehension is the
    symbolic fold, and its condition ``item.keep`` reads an attribute of the
    symbolic member: the one two-faced undecided read (#7757 item 13, #8090),
    never a decided keep or drop.

    Until #8090 (``eef6b95e5``) that read refused the whole run by name
    (``SugarNotWritten``: "undecided receiver runtime type or member
    semantics: SymbolicValue.keep"), which this test pinned as "stays loud".
    #8090 made "not decided here" one way: the read completes only under its
    ``python:attribute.completes`` atom, halts with an undetermined raise under
    the complement, and both arms owe the ``undecided`` member at the read's
    site (step 8's one member kind).  Still loud, by that member: the filter
    is undecided, nothing is projected, and no exception is named.

    The iterable is a list that arrived by binding, whose contents are not
    current (``object_identity.contents_stale``): no finite container, so
    the fold runs ``iter`` on it first, the one undecided iteration
    (``ListValue.iter_with``), as a ``for`` over it does.  (Until the
    comprehension ran ``iter`` this used a class-less ``ObjectValue``,
    whose ``iter`` -- its class's ``__iter__``, which no class binds -- is
    refused by name.)"""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    source = "def build(items):\n    return [item for item in items if item.keep]\n"
    comprehension = _source_list_comprehension(source)
    first, second = _objects()

    outcome = comprehension.desugar(
        _context_with_items(
            source,
            ListValue((first, second), allocation=None, arrival="arrived-items"),
        )
    )

    assert isinstance(outcome, ExitSet), outcome
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    halts = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    # ``iter`` of the iterable and the filter read may each raise: both
    # halts are kept, naming no exception.
    assert len(halts) >= 2, outcome
    assert all(type(arm.effect) is UndeterminedRaiseEffect for arm in halts), outcome
    assert any(arm.effect.producer_node_owner == "ListValue.iter" for arm in halts)
    # The completed arm stands only under both completes atoms.
    assert "python:iter_op.completes" in repr(done.guard), done.guard
    assert "python:attribute.completes" in repr(done.guard), done.guard
    # Nothing is projected: the value is the comprehension's own coordinate,
    # its kind over its occurrence and this evaluation of it.  The filter's
    # read is stated where it ran (its halt and its debt, above), never
    # inside that term.
    value = peel_walrus_binds(done.value)[1]
    assert isinstance(value, ComprehensionValue), value
    assert value.finite_elements is None
    assert value.term.name == "py.listcomp", value.term
    occurrence, evaluation = value.term.args
    assert occurrence.name == "python:source-occurrence", value.term
    assert evaluation.name == "python:occurrence", value.term
    assert "attr:keep" not in repr(value.term), value.term
    # Every arm owes the read as the one ``undecided`` member (no symbol: a
    # read is not an import-bound call).
    owed = owed_calls(outcome)
    assert owed and all(item.symbol is None for item in owed), owed
    assert all(arm.owed for arm in outcome.exits), outcome


# A comprehension whose every member is in hand is decided whole: the
# reduction projects its members (``ComprehensionSugar._run_in_hand``) and the
# value's ``display`` is the list they build.  A read by index is that list's
# ``__getitem__`` (``ComprehensionValue.subscript``), as its truth and its
# operators are.  Before #8957 the rewrite dissolved it into the list itself;
# after it, the index read was the undecided ``py.subscript`` coordinate, so
# ``xs[0] + xs[1]`` was not decided (#7757).
_READ_BY_INDEX = """\
def test_index():
    xs = [j + 1 for j in (10, 20)]
    assert xs[0] + xs[1] == {claim}
"""


def test_a_comprehension_in_hand_is_read_by_index_as_its_display(tmp_path) -> None:
    from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

    truthful = run_source_through_real_solver(
        tmp_path / "t", _READ_BY_INDEX.format(claim=32)
    )
    lying = run_source_through_real_solver(
        tmp_path / "l", _READ_BY_INDEX.format(claim=33)
    )

    assert truthful.verdict == "sat", truthful.prove_doc
    assert lying.verdict == "unsat", lying.prove_doc
