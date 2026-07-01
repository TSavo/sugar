from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[4]
PY_TESTS = ROOT / "implementations/python/sugar-lift-py-tests"


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


def _run_lift_rpc(project: Path) -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": str(PY_TESTS / "src"),
    }
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "lift",
                "params": {"workspace_root": str(project), "source_paths": ["."]},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
    )

    completed = subprocess.run(
        [sys.executable, "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    response = next(item for item in responses if item.get("id") == 2)
    assert "error" not in response, response
    return response["result"]


def _write_comparison_assertion(project: Path, *, expected: int) -> None:
    project.mkdir()
    (project / "test_object_rich_compare.py").write_text(
        (
            "class X:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "\n"
            "    def __lt__(self, other):\n"
            "        return other.x\n"
            "\n"
            "def test_object_rich_compare():\n"
            f"    assert [10, 20, 30][X(0) < X(1)] == {expected}\n"
        ),
        encoding="utf-8",
    )


def _first_inv(doc: dict) -> dict:
    return doc["ir"][0]["inv"]


def _formula_status(formula: dict) -> str:
    assert formula["kind"] == "atomic"
    assert formula["name"] == "="
    left, right = formula["args"]
    return "sat" if left == right else "unsat"


def _formula_values(formula: dict) -> tuple[int, int]:
    left, right = formula["args"]
    return left["value"], right["value"]


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


def test_object_rich_comparison_lift_rpc_emits_sat_and_unsat_twins(
    tmp_path: Path,
) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_comparison_assertion(good, expected=20)
    _write_comparison_assertion(bad, expected=10)

    good_inv = _first_inv(_run_lift_rpc(good))
    bad_inv = _first_inv(_run_lift_rpc(bad))

    assert _formula_status(good_inv) == "sat"
    assert _formula_values(good_inv) == (20, 20)
    assert _formula_status(bad_inv) == "unsat"
    assert _formula_values(bad_inv) == (20, 10)


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
