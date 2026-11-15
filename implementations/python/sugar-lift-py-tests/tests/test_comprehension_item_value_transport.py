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
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect import RaiseEffect


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


def test_halted_constructor_arm_is_absent_from_finite_items() -> None:
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

    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    assert isinstance(outcome.halts()[0].effect, RaiseEffect)


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


def test_nonfinite_iterable_with_undecided_filter_stays_loud() -> None:
    source = "def build(items):\n    return [item for item in items if item.keep]\n"
    comprehension = _source_list_comprehension(source)

    with pytest.raises(SugarNotWritten, match="finite|filter|undecided"):
        comprehension.desugar(
            _context_with_items(
                source, ObjectValue("UnknownIterable", (), allocation=FRAME_FRESH)
            )
        )
