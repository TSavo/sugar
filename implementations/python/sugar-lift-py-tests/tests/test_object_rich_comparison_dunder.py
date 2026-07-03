from __future__ import annotations

import ast

import pytest
from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.object_rich_comparison_term_sugar import (
    ObjectRichComparisonTermSugar,
)

def _ctx_for_module(source: str) -> FactoryBuildContext:
    module = ast.parse(source)
    resolver = {
        stmt.name: stmt
        for stmt in module.body
        if isinstance(stmt, (ast.FunctionDef, ast.ClassDef))
    }
    return FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver=resolver,
    )


def _reduce_expr(source: str, expr: str):
    ctx = _ctx_for_module(source)
    node = ast.parse(expr, mode="eval").body
    return complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="object rich comparison",
    )


@pytest.mark.parametrize(
    ("method_name", "expression", "right_col"),
    [
        ("__ne__", "X() != X()", 7),
        ("__lt__", "X() < X()", 6),
        ("__le__", "X() <= X()", 7),
        ("__gt__", "X() > X()", 6),
        ("__ge__", "X() >= X()", 7),
    ],
)
def test_object_rich_comparison_projects_to_dunder_method_bridge(
    method_name: str,
    expression: str,
    right_col: int,
) -> None:
    source = f"""\
class X:
    def {method_name}(self, other):
        return 1
"""

    ctx = _ctx_for_module(source)
    node = ast.parse(expression, mode="eval").body
    assert ctx.build_child(node, SugarRole.TERM).sugar.__class__ is (
        ObjectRichComparisonTermSugar
    )
    value = _reduce_expr(source, expression)

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"X.{method_name}"
    assert fol(floor_to_term(value, owner="object rich comparison bridge")) == fol(
        ctor(
            f"call:X.{method_name}",
            [
                ctor(
                    "py.object.identity",
                    [str_const("X"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("X"), str_const(f"t.py:1:{right_col}")],
                ),
            ],
        )
    )


def test_object_rich_comparison_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, x):
        self.x = x

    def __lt__(self, other):
        return other.x
"""

    value = _reduce_expr(source, "[10, 20, 30][X(0) < X(1)]")

    assert value == TermValue(20)


def test_identity_assertions_do_not_route_through_rich_comparison_dunders() -> None:
    report = build_literal_call_report(
        source=(
            "class X:\n"
            "    def __eq__(self, other):\n"
            "        return True\n"
            "\n"
            "    def __ne__(self, other):\n"
            "        return False\n"
            "\n"
            "def test_object_identity():\n"
            "    assert X() is X()\n"
            "    assert X() is not X()\n"
        ),
        filename="test_object_identity.py",
        memento_file="test_object_identity.py",
    )

    assert report is not None
    assert [contract.source_warrants[0].role for contract in report.payload.ir] == [
        "python.identity-assertion-sugar",
        "python.identity-assertion-sugar",
    ]
    assert "X.__eq__" not in repr(report.payload.ir)
    assert "X.__ne__" not in repr(report.payload.ir)


def test_symbolic_comparison_assertion_stays_on_comparison_assertion_path() -> None:
    report = build_literal_call_report(
        source=("def test_symbolic_order(x, y):\n" "    assert x < y\n"),
        filename="test_symbolic_order.py",
        memento_file="test_symbolic_order.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.comparison-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "<",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "var", "name": "y"},
        ],
    }
