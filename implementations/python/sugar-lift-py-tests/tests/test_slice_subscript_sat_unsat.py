from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def _write_assertion(project: Path, body: str) -> None:
    project.mkdir()
    (project / "test_slice_subscript.py").write_text(
        body,
        encoding="utf-8",
    )


def _formula_status(formula: dict) -> str:
    assert formula["kind"] == "atomic"
    assert formula["name"] in {"=", "≠"}
    left, right = formula["args"]
    same = left == right
    if formula["name"] == "=":
        return "sat" if same else "unsat"
    return "unsat" if same else "sat"


def _first_inv(doc: dict) -> dict:
    return doc["ir"][0]["inv"]


def test_concrete_string_slice_lift_rpc_emits_sat_and_unsat_twins(
    tmp_path: Path,
) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_assertion(
        good,
        "def test_concrete_string_slice():\n" "    assert 'abcdef'[1:3] == 'bc'\n",
    )
    _write_assertion(
        bad,
        "def test_concrete_string_slice():\n" "    assert 'abcdef'[1:3] == 'zz'\n",
    )

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    assert _formula_status(_first_inv(good_doc)) == "sat"
    assert _formula_status(_first_inv(bad_doc)) == "unsat"
    assert _first_inv(good_doc)["args"] == [
        {
            "kind": "const",
            "sort": {"kind": "primitive", "name": "String"},
            "value": "bc",
        },
        {
            "kind": "const",
            "sort": {"kind": "primitive", "name": "String"},
            "value": "bc",
        },
    ]


def test_symbolic_slice_lift_rpc_emits_sat_and_unsat_twins(
    tmp_path: Path,
) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_assertion(
        good,
        "def test_symbolic_slice(values):\n" "    assert values[::2] == values[::2]\n",
    )
    _write_assertion(
        bad,
        "def test_symbolic_slice(values):\n" "    assert values[::2] != values[::2]\n",
    )

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    assert _formula_status(_first_inv(good_doc)) == "sat"
    assert _formula_status(_first_inv(bad_doc)) == "unsat"
    left, right = _first_inv(good_doc)["args"]
    assert left == right
    assert left == {
        "kind": "ctor",
        "name": "py.subscript",
        "args": [
            {"kind": "var", "name": "values"},
            {
                "kind": "ctor",
                "name": "py.slice",
                "args": [
                    {"kind": "ctor", "name": "None", "args": []},
                    {"kind": "ctor", "name": "None", "args": []},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 2,
                    },
                ],
            },
        ],
    }
