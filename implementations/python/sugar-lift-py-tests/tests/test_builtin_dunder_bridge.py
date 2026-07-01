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
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

ROOT = Path(__file__).resolve().parents[4]
PY_TESTS = ROOT / "implementations/python/sugar-lift-py-tests"


def _ctx_for_module(
    source: str,
    *,
    from_imports: dict[str, tuple[str, str]] | None = None,
) -> FactoryBuildContext:
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
        from_imports=from_imports or {},
    )


def _reduce_expr(
    source: str,
    expr: str,
    *,
    from_imports: dict[str, tuple[str, str]] | None = None,
):
    ctx = _ctx_for_module(source, from_imports=from_imports)
    node = ast.parse(expr, mode="eval").body
    return complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="builtin dunder bridge",
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


def _write_builtin_dunder_assertion(
    project: Path,
    *,
    builtin_name: str,
    method_name: str,
    expected: int,
) -> None:
    project.mkdir()
    (project / f"test_{builtin_name}_dunder.py").write_text(
        (
            "class Box:\n"
            f"    def {method_name}(self):\n"
            "        return 1\n"
            "\n"
            f"def test_{builtin_name}_dunder():\n"
            f"    assert [10, 20, 30][{builtin_name}(Box())] == {expected}\n"
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


def _object_identity(class_name: str, blame: str):
    return ctor("py.object.identity", [str_const(class_name), str_const(blame)])


def test_len_builtin_projects_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __len__(self):
        return 1
"""

    value = _reduce_expr(source, "len(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__len__"
    assert fol(floor_to_term(value, owner="len dunder bridge")) == fol(
        ctor("call:Box.__len__", [_object_identity("Box", "t.py:1:4")])
    )


def test_len_builtin_dunder_can_drive_array_index_value_demand() -> None:
    source = """\
class Box:
    def __len__(self):
        return 1
"""

    value = _reduce_expr(source, "[10, 20, 30][len(Box())]")

    assert value == TermValue(20)


def test_hash_builtin_projects_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __hash__(self):
        return 1
"""

    value = _reduce_expr(source, "hash(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__hash__"
    assert fol(floor_to_term(value, owner="hash dunder bridge")) == fol(
        ctor("call:Box.__hash__", [_object_identity("Box", "t.py:1:5")])
    )


def test_imported_builtin_like_call_stays_external_bridge() -> None:
    source = """\
class Box:
    def __len__(self):
        return 1
"""

    value = _reduce_expr(
        source,
        "external_len(Box())",
        from_imports={"external_len": ("vendor", "len")},
    )

    assert isinstance(value, SymbolicValue)
    assert fol(value.term) == fol(
        ctor("call:vendor.len", [_object_identity("Box", "t.py:1:13")])
    )


def test_imported_builtin_like_same_name_call_stays_external_bridge() -> None:
    source = """\
class Box:
    def __len__(self):
        return 1
"""

    value = _reduce_expr(
        source,
        "len(Box())",
        from_imports={"len": ("vendor", "len")},
    )

    assert isinstance(value, SymbolicValue)
    assert fol(value.term) == fol(
        ctor("call:vendor.len", [_object_identity("Box", "t.py:1:4")])
    )


def test_len_and_hash_builtin_lift_rpc_emit_sat_and_unsat_twins(
    tmp_path: Path,
) -> None:
    for builtin_name, method_name in (
        ("len", "__len__"),
        ("hash", "__hash__"),
    ):
        good = tmp_path / f"{builtin_name}_good"
        bad = tmp_path / f"{builtin_name}_bad"
        _write_builtin_dunder_assertion(
            good,
            builtin_name=builtin_name,
            method_name=method_name,
            expected=20,
        )
        _write_builtin_dunder_assertion(
            bad,
            builtin_name=builtin_name,
            method_name=method_name,
            expected=10,
        )

        good_inv = _first_inv(_run_lift_rpc(good))
        bad_inv = _first_inv(_run_lift_rpc(bad))

        assert _formula_status(good_inv) == "sat"
        assert _formula_values(good_inv) == (20, 20)
        assert _formula_status(bad_inv) == "unsat"
        assert _formula_values(bad_inv) == (20, 10)
