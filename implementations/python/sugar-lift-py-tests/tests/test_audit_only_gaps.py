from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.audit_only import collect_construction_gaps
from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.factory import FactoryGap, build_node
from sugar_lift_py_tests.floor import ObjectValue, TermValue
from sugar_lift_py_tests.operations import perform_operation
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.array_literal_sugar import ArrayLiteralSugar
from sugar_lift_py_tests.sugar_body import SugarBody


class _ObjectValueSugar:
    def desugar(self):
        return Complete(ObjectValue(class_name="object", fields=()))


def test_audit_only_collects_multiple_construction_gaps() -> None:
    def missing_sugar():
        build_node(
            ast.parse("x + 1", mode="eval").body,
            filename="fixture.py",
            role=SugarRole.TERM,
            catalog=SugarCatalog([]),
        )

    def missing_floor():
        perform_operation(
            owner="python-test",
            blame="fixture.py:3:4",
            receiver=TermValue(1),
            method_name="map_with",
            operation=object(),
            ctx=None,
        )

    gaps = collect_construction_gaps(
        [
            ("ok", lambda: "complete"),
            ("missing-sugar", missing_sugar),
            ("missing-floor", missing_floor),
        ]
    )

    assert [gap.label for gap in gaps] == ["missing-sugar", "missing-floor"]
    assert gaps[0].message.startswith("write more Sugar for this AST")
    assert gaps[0].info == {
        "owner": "python.factory",
        "blame": "fixture.py:1:0",
        "observed": "BinOp",
        "requested": "term",
        "fix": "create sugar_lift_py_tests.sugar.bin_op.bin_op_sugar",
        "gap_kind": "Sugar",
        "gap_locus": "AST",
    }
    assert gaps[0].audit_row.to_json()["status"] == "sugar-gap"
    assert gaps[1].message.startswith("write more Floor for this construction")
    assert gaps[1].info == {
        "owner": "python-test",
        "blame": "fixture.py:3:4",
        "observed": "TermValue",
        "requested": "map_with",
        "fix": "add map_with to TermValue or emit a real effect",
        "gap_kind": "Floor",
        "gap_locus": "construction",
    }
    assert gaps[1].audit_row.to_json()["status"] == "floor-gap"
    assert [gap.to_json()["message"] for gap in gaps] == [
        gaps[0].message,
        gaps[1].message,
    ]


def test_audit_only_does_not_swallow_unexpected_exceptions() -> None:
    def broken_walker():
        raise ValueError("not a construction gap")

    with pytest.raises(ValueError, match="not a construction gap"):
        collect_construction_gaps([("broken", broken_walker)])


def test_audit_only_collects_loud_floor_type_errors() -> None:
    def missing_floor_projection():
        raise TypeError(
            "write more Floor for StringSubscriptSugar receiver: "
            "expected StringValue got SymbolicValue"
        )

    gaps = collect_construction_gaps([("fixture.py", missing_floor_projection)])

    assert len(gaps) == 1
    assert gaps[0].message == (
        "write more Floor for StringSubscriptSugar receiver: "
        "expected StringValue got SymbolicValue"
    )
    assert gaps[0].info == {
        "owner": "StringSubscriptSugar receiver",
        "blame": "fixture.py",
        "observed": "SymbolicValue",
        "requested": "StringValue",
        "fix": "write the missing floor",
    }
    assert gaps[0].audit_row.to_json()["status"] == "floor-gap"


def test_audit_only_accepts_object_values_in_array_literals() -> None:
    def object_array_element():
        ArrayLiteralSugar(
            elements=(
                SugarBody(
                    _ObjectValueSugar(),
                    role=SugarRole.TERM,
                ),
            )
        ).desugar()

    gaps = collect_construction_gaps([("fixture.py", object_array_element)])

    assert gaps == []


def test_audit_only_does_not_swallow_unmarked_type_errors() -> None:
    def broken_walker():
        raise TypeError("plain type error")

    with pytest.raises(TypeError, match="plain type error"):
        collect_construction_gaps([("broken", broken_walker)])


def test_normal_mode_still_panics_immediately() -> None:
    with pytest.raises(FactoryGap):
        build_node(
            ast.parse("x + 1", mode="eval").body,
            filename="fixture.py",
            role=SugarRole.TERM,
            catalog=SugarCatalog([]),
        )
