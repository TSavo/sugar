from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

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
        owner="object call slot",
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


def _write_object_call_assertion(project: Path, *, expected: int) -> None:
    project.mkdir()
    (project / "test_object_call_slot.py").write_text(
        (
            "class CallableReturningOne:\n"
            "    def __call__(self):\n"
            "        return 1\n"
            "\n"
            "def test_object_call_slot():\n"
            f"    assert [10, 20, 30][CallableReturningOne()()] == {expected}\n"
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


def test_object_call_projects_to_dunder_call_bridge() -> None:
    source = """\
class Callable:
    def __call__(self, x):
        return x + 1
"""

    value = _reduce_expr(source, "Callable()(1)")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object call slot")) == fol(
        ctor(
            "call:Callable.__call__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Callable"), str_const("t.py:1:0")],
                ),
                num(1),
            ],
        )
    )


def test_object_call_can_drive_array_index_value_demand() -> None:
    source = """\
class CallableReturningOne:
    def __call__(self):
        return 1
"""

    value = _reduce_expr(source, "[10, 20, 30][CallableReturningOne()()]")

    assert value == TermValue(20)


def test_object_call_lift_rpc_emits_sat_and_unsat_twins(tmp_path: Path) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_object_call_assertion(good, expected=20)
    _write_object_call_assertion(bad, expected=10)

    good_inv = _first_inv(_run_lift_rpc(good))
    bad_inv = _first_inv(_run_lift_rpc(bad))

    assert _formula_status(good_inv) == "sat"
    assert _formula_values(good_inv) == (20, 20)
    assert _formula_status(bad_inv) == "unsat"
    assert _formula_values(bad_inv) == (20, 10)
