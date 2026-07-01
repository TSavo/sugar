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
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

ROOT = Path(__file__).resolve().parents[4]
PY_TESTS = ROOT / "implementations/python/sugar-lift-py-tests"


def _ctx_for_module(
    source: str,
    *,
    import_aliases: dict[str, str] | None = None,
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
        import_aliases=import_aliases or {},
        from_imports=from_imports or {},
    )


def _reduce_expr(
    source: str,
    expr: str,
    *,
    import_aliases: dict[str, str] | None = None,
    from_imports: dict[str, tuple[str, str]] | None = None,
):
    ctx = _ctx_for_module(
        source,
        import_aliases=import_aliases,
        from_imports=from_imports,
    )
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


def _write_divmod_dunder_assertion(
    project: Path,
    *,
    method_name: str,
    expression: str,
    expected: int,
) -> None:
    project.mkdir()
    (project / "test_divmod_dunder.py").write_text(
        (
            "class Box:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "\n"
            f"    def {method_name}(self, other):\n"
            "        return self.x\n"
            "\n"
            "def test_divmod_dunder():\n"
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


def test_divmod_builtin_projects_left_object_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __divmod__(self, other):
        return 1
"""

    value = _reduce_expr(source, "divmod(Box(), 2)")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__divmod__"
    assert fol(floor_to_term(value, owner="divmod dunder bridge")) == fol(
        ctor(
            "call:Box.__divmod__",
            [
                _object_identity("Box", "t.py:1:7"),
                num(2),
            ],
        )
    )


def test_divmod_builtin_projects_right_object_to_reflected_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __rdivmod__(self, other):
        return 1
"""

    value = _reduce_expr(source, "divmod(2, Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__rdivmod__"
    assert fol(floor_to_term(value, owner="reflected divmod dunder bridge")) == fol(
        ctor(
            "call:Box.__rdivmod__",
            [
                _object_identity("Box", "t.py:1:10"),
                num(2),
            ],
        )
    )


@pytest.mark.parametrize(
    ("builtin_name", "method_name"),
    [
        ("abs", "__abs__"),
        ("round", "__round__"),
        ("floor", "__floor__"),
        ("ceil", "__ceil__"),
        ("trunc", "__trunc__"),
    ],
)
def test_unary_numeric_builtin_projects_to_dunder_method_bridge(
    builtin_name: str, method_name: str
) -> None:
    source = f"""\
class Box:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(source, f"{builtin_name}(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"Box.{method_name}"
    assert len(value.arg_values) == 1


@pytest.mark.parametrize(
    ("builtin_name", "method_name"),
    [
        ("abs", "__abs__"),
        ("round", "__round__"),
        ("floor", "__floor__"),
        ("ceil", "__ceil__"),
        ("trunc", "__trunc__"),
    ],
)
def test_unary_numeric_builtin_dunder_can_drive_array_index_value_demand(
    builtin_name: str, method_name: str
) -> None:
    source = f"""\
class Box:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(source, f"[10, 20, 30][{builtin_name}(Box())]")

    assert value == TermValue(20)


def test_imported_math_floor_stays_external_bridge() -> None:
    source = """\
class Box:
    def __floor__(self):
        return 1
"""

    value = _reduce_expr(
        source,
        "floor(Box())",
        from_imports={"floor": ("math", "floor")},
    )

    assert isinstance(value, SymbolicValue)
    assert fol(value.term) == fol(
        ctor("call:math.floor", [_object_identity("Box", "t.py:1:6")])
    )


@pytest.mark.parametrize(
    ("call_expr", "method_name", "object_blame", "import_aliases"),
    [
        ("int(Box())", "__int__", "t.py:1:4", None),
        ("float(Box())", "__float__", "t.py:1:6", None),
        ("complex(Box())", "__complex__", "t.py:1:8", None),
        ("operator.index(Box())", "__index__", "t.py:1:15", {"operator": "operator"}),
    ],
)
def test_numeric_conversion_builtin_projects_to_dunder_method_bridge(
    call_expr: str,
    method_name: str,
    object_blame: str,
    import_aliases: dict[str, str] | None,
) -> None:
    import_prefix = "import operator\n\n" if import_aliases else ""
    source = f"""\
{import_prefix}\
class Box:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(source, call_expr, import_aliases=import_aliases)

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"Box.{method_name}"
    assert fol(
        floor_to_term(value, owner=f"{method_name} numeric conversion bridge")
    ) == fol(ctor(f"call:Box.{method_name}", [_object_identity("Box", object_blame)]))


@pytest.mark.parametrize(
    ("call_expr", "method_name", "import_aliases"),
    [
        ("int(Box())", "__int__", None),
        ("operator.index(Box())", "__index__", {"operator": "operator"}),
    ],
)
def test_numeric_conversion_dunder_can_drive_array_index_value_demand(
    call_expr: str,
    method_name: str,
    import_aliases: dict[str, str] | None,
) -> None:
    import_prefix = "import operator\n\n" if import_aliases else ""
    source = f"""\
{import_prefix}\
class Box:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(
        source,
        f"[10, 20, 30][{call_expr}]",
        import_aliases=import_aliases,
    )

    assert value == TermValue(20)


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


def test_divmod_builtin_dunder_lift_rpc_emits_sat_and_unsat_twins(
    tmp_path: Path,
) -> None:
    for method_name, expression in (
        ("__divmod__", "divmod(Box(1), 2)"),
        ("__rdivmod__", "divmod(2, Box(1))"),
    ):
        good = tmp_path / f"{method_name}_good"
        bad = tmp_path / f"{method_name}_bad"
        _write_divmod_dunder_assertion(
            good,
            method_name=method_name,
            expression=expression,
            expected=20,
        )
        _write_divmod_dunder_assertion(
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
