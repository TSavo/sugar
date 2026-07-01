from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PY_TESTS = ROOT / "implementations/python/sugar-lift-py-tests"


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


def _write_dunder_assertion(
    project: Path,
    *,
    method_name: str,
    expression: str,
    expected: int,
) -> None:
    project.mkdir()
    if method_name.startswith("__r"):
        return_expr = "self.x"
    else:
        return_expr = "other.x"
    (project / "test_object_dunder.py").write_text(
        (
            "class X:\n"
            "    def __init__(self, y):\n"
            "        self.x = y\n"
            "\n"
            f"    def {method_name}(self, other):\n"
            f"        return {return_expr}\n"
            "\n"
            "def test_object_dunder():\n"
            f"    assert [10, 20, 30][{expression}] == {expected}\n"
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
    ("method_name", "expression"),
    [
        ("__add__", "X(0) + X(1)"),
        ("__sub__", "X(0) - X(1)"),
        ("__mul__", "X(0) * X(1)"),
        ("__radd__", "2 + X(1)"),
        ("__rsub__", "2 - X(1)"),
        ("__rmul__", "2 * X(1)"),
    ],
)
def test_object_binary_dunder_lift_rpc_emits_sat_and_unsat_twins(
    tmp_path: Path,
    method_name: str,
    expression: str,
) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_dunder_assertion(
        good,
        method_name=method_name,
        expression=expression,
        expected=20,
    )
    _write_dunder_assertion(
        bad,
        method_name=method_name,
        expression=expression,
        expected=10,
    )

    good_inv = _first_inv(_run_lift_rpc(good))
    bad_inv = _first_inv(_run_lift_rpc(bad))

    assert _formula_status(good_inv) == "sat"
    assert _formula_values(good_inv) == (20, 20)
    assert _formula_status(bad_inv) == "unsat"
    assert _formula_values(bad_inv) == (20, 10)
