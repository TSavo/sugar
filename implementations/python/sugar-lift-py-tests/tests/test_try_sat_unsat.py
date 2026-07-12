from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PY_TESTS = ROOT / "implementations/python/sugar-lift-py-tests"


def _run_lift_rpc_process(project: Path) -> subprocess.CompletedProcess[str]:
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

    return subprocess.run(
        [sys.executable, "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _run_lift_rpc(project: Path) -> dict:
    completed = _run_lift_rpc_process(project)
    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    response = next(item for item in responses if item.get("id") == 2)
    assert "error" not in response, response
    return response["result"]


def _write_project(
    project: Path, *, body: str, expected: int, argument: int = 5
) -> None:
    project.mkdir()
    (project / "test_try_wrapped.py").write_text(
        (
            "def wrapped(x):\n"
            f"{body}\n"
            "\n"
            "def test_wrapped():\n"
            f"    assert wrapped({argument}) == {expected}\n"
        ),
        encoding="utf-8",
    )


def _callsite_values(doc: dict, *, argument: int = 5) -> list[int]:
    values: list[int] = []
    for contract in doc["ir"]:
        if not contract["name"].endswith("::assertion"):
            continue
        inv = contract["inv"]
        assert inv["kind"] == "atomic"
        assert inv["name"] == "py.eq"
        left, right = inv["args"]
        if left == _wrapped_call_term(argument):
            values.append(right["value"])
    assert values
    return values


def _wrapped_call_term(argument: int = 5) -> dict:
    return {
        "kind": "ctor",
        "name": "call:wrapped",
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": argument,
            }
        ],
    }


def _post_rhs(doc: dict) -> dict:
    post_contracts = [contract for contract in doc["ir"] if contract.get("post")]
    assert len(post_contracts) == 1
    post = post_contracts[0]["post"]
    assert post["kind"] == "atomic"
    assert post["name"] == "="
    left, right = post["args"]
    assert left == {"kind": "var", "name": "out"}
    return right


def _post(doc: dict) -> dict:
    post_contracts = [contract for contract in doc["ir"] if contract.get("post")]
    assert len(post_contracts) == 1
    return post_contracts[0]["post"]


def _add_rhs(addend: int) -> dict:
    return {
        "kind": "ctor",
        "name": "+",
        "args": [
            {"kind": "var", "name": "x"},
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": addend,
            },
        ],
    }


def _nested_add_rhs(first: int, second: int) -> dict:
    return {
        "kind": "ctor",
        "name": "+",
        "args": [
            {
                "kind": "ctor",
                "name": "+",
                "args": [
                    {"kind": "var", "name": "x"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": first,
                    },
                ],
            },
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": second,
            },
        ],
    }


def _var_x() -> dict:
    return {"kind": "var", "name": "x"}


def _gt_zero_guard() -> dict:
    return {
        "kind": "atomic",
        "name": ">",
        "args": [
            {"kind": "var", "name": "x"},
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 0,
            },
        ],
    }


def _except_guard(name: str) -> dict:
    return {
        "kind": "atomic",
        "name": "py.except",
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "String"},
                "value": name,
            }
        ],
    }


def _threaded_try_post(body_post: dict, exception: str, handler_rhs: dict) -> dict:
    return {
        "kind": "and",
        "operands": [
            body_post,
            {
                "kind": "implies",
                "operands": [
                    _except_guard(exception),
                    {
                        "kind": "atomic",
                        "name": "=",
                        "args": [{"kind": "var", "name": "out"}, handler_rhs],
                    },
                ],
            },
        ],
    }


def _guarded_add_post(*, true_addend: int, false_addend: int) -> dict:
    guard = _gt_zero_guard()
    return {
        "kind": "and",
        "operands": [
            {
                "kind": "implies",
                "operands": [
                    guard,
                    {
                        "kind": "atomic",
                        "name": "=",
                        "args": [{"kind": "var", "name": "out"}, _add_rhs(true_addend)],
                    },
                ],
            },
            {
                "kind": "implies",
                "operands": [
                    {"kind": "not", "operands": [guard]},
                    {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            _add_rhs(false_addend),
                        ],
                    },
                ],
            },
        ],
    }


def _guarded_post(*, true_rhs: dict, false_rhs: dict) -> dict:
    guard = _gt_zero_guard()
    return {
        "kind": "and",
        "operands": [
            {
                "kind": "implies",
                "operands": [
                    guard,
                    {
                        "kind": "atomic",
                        "name": "=",
                        "args": [{"kind": "var", "name": "out"}, true_rhs],
                    },
                ],
            },
            {
                "kind": "implies",
                "operands": [
                    {"kind": "not", "operands": [guard]},
                    {
                        "kind": "atomic",
                        "name": "=",
                        "args": [{"kind": "var", "name": "out"}, false_rhs],
                    },
                ],
            },
        ],
    }


def _selected_sugars(doc: dict) -> list[str]:
    return [row["selected"] for row in doc["factoryAuditSummary"]["factoryWalk"]]


def test_try_body_lift_rpc_emits_callsite_values(tmp_path: Path) -> None:
    body = (
        "    try:\n"
        "        return x + 1\n"
        "    except Exception:\n"
        "        return 99\n"
    )
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_project(good, body=body, expected=6)
    _write_project(bad, body=body, expected=7)

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    assert _post(good_doc) == _threaded_try_post(
        {
            "kind": "atomic",
            "name": "=",
            "args": [{"kind": "var", "name": "out"}, _add_rhs(1)],
        },
        "Exception",
        {
            "kind": "const",
            "sort": {"kind": "primitive", "name": "Int"},
            "value": 99,
        },
    )
    assert _callsite_values(good_doc) == [6]
    assert _callsite_values(bad_doc) == [7]
    assert "TrySugar" in _selected_sugars(good_doc)


def test_try_except_raise_lift_rpc_emits_callsite_values(
    tmp_path: Path,
) -> None:
    body = (
        "    try:\n"
        "        raise ValueError('boom')\n"
        "    except ValueError:\n"
        "        return x + 1\n"
    )
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_project(good, body=body, expected=6)
    _write_project(bad, body=body, expected=7)

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    assert _post(good_doc) == {
        "kind": "implies",
        "operands": [
            _except_guard("ValueError"),
            {
                "kind": "atomic",
                "name": "=",
                "args": [{"kind": "var", "name": "out"}, _add_rhs(1)],
            },
        ],
    }
    assert _callsite_values(good_doc) == [6]
    assert _callsite_values(bad_doc) == [7]
    assert "TrySugar" in _selected_sugars(good_doc)


def test_try_finally_override_stays_a_loud_construction_gap(
    tmp_path: Path,
) -> None:
    body = (
        "    try:\n" "        return x + 1\n" "    finally:\n" "        return x + 2\n"
    )
    project = tmp_path / "loud"
    _write_project(project, body=body, expected=7)

    completed = _run_lift_rpc_process(project)

    assert completed.returncode == 1
    assert "observed=Try requested=statement" in completed.stderr
    assert "FACTORY PANIC" in completed.stderr


def test_try_finally_inert_body_stays_a_loud_construction_gap(
    tmp_path: Path,
) -> None:
    body = "    try:\n" "        return x + 1\n" "    finally:\n" "        'cleanup'\n"
    project = tmp_path / "loud"
    _write_project(project, body=body, expected=6)

    completed = _run_lift_rpc_process(project)

    assert completed.returncode == 1
    assert "observed=Try requested=statement" in completed.stderr
    assert "FACTORY PANIC" in completed.stderr


def test_try_conditional_raise_except_curries_guarded_universe_through_lift_rpc(
    tmp_path: Path,
) -> None:
    body = (
        "    try:\n"
        "        if x > 0:\n"
        "            raise ValueError('boom')\n"
        "        return x + 1\n"
        "    except ValueError:\n"
        "        return x + 2\n"
    )
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_project(good, body=body, expected=7)
    _write_project(bad, body=body, expected=6)

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    expected = _threaded_try_post(
        {
            "kind": "atomic",
            "name": "=",
            "args": [{"kind": "var", "name": "out"}, _add_rhs(1)],
        },
        "ValueError",
        _add_rhs(2),
    )
    assert _post(good_doc) == expected
    assert _post(bad_doc) == expected
    assert _callsite_values(good_doc) == [7]
    assert _callsite_values(bad_doc) == [6]
    assert "TrySugar" in _selected_sugars(good_doc)


def test_try_conditional_raise_except_uses_raise_scope_in_lift_rpc(
    tmp_path: Path,
) -> None:
    body = (
        "    try:\n"
        "        y = x + 1\n"
        "        if x > 0:\n"
        "            raise ValueError('boom')\n"
        "        return x\n"
        "    except ValueError:\n"
        "        return y + 2\n"
    )
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_project(good, body=body, expected=8)
    _write_project(bad, body=body, expected=5)

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    expected = _threaded_try_post(
        {
            "kind": "atomic",
            "name": "=",
            "args": [{"kind": "var", "name": "out"}, _var_x()],
        },
        "ValueError",
        _nested_add_rhs(1, 2),
    )
    assert _post(good_doc) == expected
    assert _post(bad_doc) == expected
    assert _callsite_values(good_doc) == [8]
    assert _callsite_values(bad_doc) == [5]
    assert "TrySugar" in _selected_sugars(good_doc)
