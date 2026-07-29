"""Finite comprehensions transport exact item values or stay loudly unresolved."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    ComprehensionValue,
    ListValue,
    ObjectValue,
    RaiseValue,
    TermValue,
)
from sugar_lift_py_tests.floor.object_field import ObjectField
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_source_tree.nodes import ListComp, TargetPatternConstructionGapV1
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _source_list_comprehension(source: str):
    tree = SourceFile(
        (
            source,
            "tests/comprehension_item_value_transport.py",
            blake3_512_of(source.encode()),
        ),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(item for item in tree.nodes() if isinstance(item, ListComp))
    return node.sugar()


def _context_with_items(items) -> ReduceContext:
    ctx = ReduceContext.root(owner="comprehension item transport")
    return replace(ctx, temporal=ctx.temporal.bind_value("items", items))


def _objects() -> tuple[ObjectValue, ObjectValue]:
    return (
        ObjectValue("_NamedIntConstant", (), identity="member:first"),
        ObjectValue("_NamedIntConstant", (), identity="member:second"),
    )


def test_swapped_finite_members_preserve_each_object_identity() -> None:
    first, second = _objects()
    comprehension = _source_list_comprehension(
        "def build(items):\n    return [item for item in items]\n"
    )

    forward = comprehension.desugar(_context_with_items(ListValue((first, second))))
    swapped = comprehension.desugar(_context_with_items(ListValue((second, first))))

    assert isinstance(forward, Complete)
    assert isinstance(swapped, Complete)
    assert forward.value.finite_elements == (first, second)
    assert swapped.value.finite_elements == (second, first)
    assert swapped.value.finite_elements[0] is second
    assert swapped.value.finite_elements[1] is first


def test_filtered_out_member_never_reaches_element_binding() -> None:
    first = ObjectValue(
        "_NamedIntConstant",
        (ObjectField("keep", FalseBoolLiteralSugar(site="first.keep")),),
        identity="member:first",
    )
    second = ObjectValue(
        "_NamedIntConstant",
        (ObjectField("keep", TrueBoolLiteralSugar(site="second.keep")),),
        identity="member:second",
    )
    comprehension = _source_list_comprehension(
        "def build(items):\n    return [item for item in items if item.keep]\n"
    )

    outcome = comprehension.desugar(_context_with_items(ListValue((first, second))))

    assert isinstance(outcome, Complete)
    assert outcome.value.finite_elements == (second,)
    assert outcome.value.finite_elements[0] is second
    assert all(value is not first for value in outcome.value.finite_elements)


def test_halted_constructor_arm_is_absent_from_finite_items() -> None:
    first, second = _objects()
    first = replace(first, fields=(ObjectField("values", ListValue((TermValue(7),))),))
    second = replace(
        second, fields=(ObjectField("values", ListValue((TermValue(9),))),)
    )
    comprehension = _source_list_comprehension(
        "def build(items):\n    return [item.values[4] for item in items]\n"
    )

    outcome = comprehension.desugar(_context_with_items(ListValue((first, second))))

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert not isinstance(outcome.value, ComprehensionValue)


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
    comprehension = _source_list_comprehension(
        "def build(items):\n    return [item for item in items if item.keep]\n"
    )

    with pytest.raises(SugarNotWritten, match="finite|filter|undecided"):
        comprehension.desugar(_context_with_items(ObjectValue("UnknownIterable", ())))
