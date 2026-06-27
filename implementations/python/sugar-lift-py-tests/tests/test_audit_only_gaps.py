from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.audit_only import collect_construction_gaps
from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.factory import FactoryGap, build_node
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.operations import perform_operation


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
    }
    assert gaps[0].audit_row.to_json()["status"] == "sugar-gap"
    assert gaps[1].message.startswith("write more Floor for this construction")
    assert gaps[1].info == {
        "owner": "python-test",
        "blame": "fixture.py:3:4",
        "observed": "TermValue",
        "requested": "map_with",
        "fix": "add map_with to TermValue or emit a real effect",
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


def test_normal_mode_still_panics_immediately() -> None:
    with pytest.raises(FactoryGap):
        build_node(
            ast.parse("x + 1", mode="eval").body,
            filename="fixture.py",
            role=SugarRole.TERM,
            catalog=SugarCatalog([]),
        )
