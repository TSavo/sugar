from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap_info import (
    FactoryGapInfo,
    GapKind,
    GapLocus,
    gap_kind_status,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import complete_value

ROOT = Path(__file__).resolve().parents[1]


def _ctx_for_module(source: str) -> FactoryBuildContext:
    module = ast.parse(source)
    resolver = {
        stmt.name: stmt
        for stmt in module.body
        if isinstance(stmt, (ast.ClassDef, ast.FunctionDef))
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
        owner="factory gap info",
    )


def _build_expr(source: str, expr: str):
    ctx = _ctx_for_module(source)
    node = ast.parse(expr, mode="eval").body
    return ctx.build_body(SourceFragment.from_node(node, "t.py"), SugarRole.TERM), ctx


def test_to_json_carries_gap_kind_and_locus() -> None:
    info = FactoryGapInfo(
        owner="o",
        blame="b",
        observed="x",
        requested="r",
        fix="f",
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.REDUCE,
    )

    data = info.to_json()

    assert data["gap_kind"] == "Floor"
    assert data["gap_locus"] == "Reduce"


def test_to_json_defaults_present() -> None:
    info = FactoryGapInfo(owner="o", blame="b", observed="x", requested="r", fix="f")

    data = info.to_json()

    assert data["gap_kind"] == "Sugar"
    assert data["gap_locus"] == "AST"


def test_factory_gap_info_rejects_stringly_gap_kind_and_locus() -> None:
    with pytest.raises(TypeError) as kind_error:
        FactoryGapInfo(
            owner="o",
            blame="b",
            observed="x",
            requested="r",
            fix="f",
            gap_kind="Floor",
        )
    assert str(kind_error.value) == (
        "FactoryGapInfo.gap_kind must be GapKind: owner=FactoryGapInfo "
        "shape=str replacement=GapKind.FLOOR"
    )

    with pytest.raises(TypeError) as locus_error:
        FactoryGapInfo(
            owner="o",
            blame="b",
            observed="x",
            requested="r",
            fix="f",
            gap_locus="construction",
        )
    assert str(locus_error.value) == (
        "FactoryGapInfo.gap_locus must be GapLocus: owner=FactoryGapInfo "
        "shape=str replacement=GapLocus.CONSTRUCTION"
    )


def test_gap_locus_construction_canonicalizes_to_title_case() -> None:
    info = FactoryGapInfo(
        owner="o",
        blame="b",
        observed="x",
        requested="r",
        fix="f",
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )

    assert info.to_json()["gap_locus"] == "Construction"
    assert "write more Floor for this Construction" in info.message


def test_gap_kind_status_handles_each_member() -> None:
    assert gap_kind_status(GapKind.FLOOR) == "floor-gap"
    assert gap_kind_status(GapKind.SUGAR) == "sugar-gap"
    assert gap_kind_status(GapKind.CONSTRUCTOR) == "constructor-gap"
    assert gap_kind_status(GapKind.SUGAR_ORDERING) == "sugar-ambiguous"
    assert gap_kind_status(GapKind.OPERATION) == "operation-gap"
    assert gap_kind_status(GapKind.PROOFIR) == "proofir-gap"


def test_gap_kind_missing_arm_is_a_pyright_error(tmp_path: Path) -> None:
    planted = tmp_path / "planted_gap_kind.py"
    planted.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from dataclasses import dataclass",
                "from typing import Never, NoReturn",
                "",
                "from sugar_lift_py_tests.factory.factory_gap_info import GapKind",
                "",
                "@dataclass(frozen=True)",
                "class PendingGapKind:",
                "    value: str = 'Pending'",
                "",
                "Kind = GapKind | PendingGapKind",
                "",
                "def consume(kind: Kind) -> str:",
                "    if isinstance(kind, GapKind):",
                "        return kind.value",
                "    return _unhandled(kind)",
                "",
                "def _unhandled(kind: Never) -> NoReturn:",
                "    raise TypeError(type(kind).__name__)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pyright",
            "--project",
            str(ROOT / "pyrightconfig.json"),
            "--outputjson",
            str(planted),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    diagnostics = "\n".join(
        item["message"] for item in payload.get("generalDiagnostics", ())
    )
    assert "PendingGapKind" in diagnostics
    assert "Never" in diagnostics


def test_constructor_call_refusal_carries_structured_kind() -> None:
    source = """\
class Box:
    def __init__(self, value):
        self.value = value
"""
    body, ctx = _build_expr(source, "Box()")

    with pytest.raises(FactoryGap) as raised:
        body.reduce(ctx)

    assert raised.value.info["requested"] == "1 constructor arguments"
    assert raised.value.info["gap_kind"] == "Constructor"


def test_set_name_descriptor_gap_carries_structured_kind() -> None:
    source = """\
class Descriptor:
    def __set_name__(self, owner, name):
        return 1

class Box:
    value = Descriptor()
"""

    with pytest.raises(FactoryGap) as raised:
        _reduce_expr(source, "Box().value")

    assert raised.value.info["requested"] == "class descriptor __set_name__ effect"
    assert raised.value.info["gap_kind"] == "Constructor"
