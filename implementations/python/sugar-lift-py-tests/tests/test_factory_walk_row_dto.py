from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import (
    FactoryWalkCompleteRowDto,
    FactoryWalkRedRowDto,
    FactoryWalkStatus,
)

ROOT = Path(__file__).resolve().parents[1]


def _with_src_on_pythonpath() -> str:
    src = str(ROOT / "src")
    existing = os.environ.get("PYTHONPATH")
    return src if not existing else os.pathsep.join([src, existing])


def test_unknown_status_is_unrepresentable():
    """An illegal status cannot even be constructed: the enum IS the guard."""
    with pytest.raises(ValueError):
        FactoryWalkStatus("bogus")


def test_red_row_without_grounds_is_unconstructible() -> None:
    with pytest.raises(TypeError, match="red verdict carries no grounds"):
        FactoryWalkRedRowDto(
            file="wall.py",
            line=7,
            requested_role="term",
            ast_kind="Call",
            selected="CallSugar",
            status=FactoryWalkStatus.COVERAGE_GAP,
            output={},
            source_memento={"kind": "source-memento"},
            reason="",
        )


def test_red_row_without_grounds_is_a_pyright_error(tmp_path: Path) -> None:
    planted = tmp_path / "planted_groundless_red.py"
    planted.write_text(
        "\n".join(
            (
                "from sugar_lift_py_tests.kit_rpc import (",
                "    FactoryWalkRedRowDto,",
                "    FactoryWalkStatus,",
                ")",
                "",
                "FactoryWalkRedRowDto(",
                "    file='wall.py',",
                "    line=7,",
                "    requested_role='term',",
                "    ast_kind='Call',",
                "    selected='CallSugar',",
                "    status=FactoryWalkStatus.COVERAGE_GAP,",
                "    output={},",
                "    source_memento={'kind': 'source-memento'},",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )

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
        env={**os.environ, "PYTHONPATH": _with_src_on_pythonpath()},
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
    assert "reason" in diagnostics, diagnostics


def test_red_row_with_grounds_constructs() -> None:
    row = FactoryWalkRedRowDto(
        file="wall.py",
        line=7,
        requested_role="term",
        ast_kind="Call",
        selected="CallSugar",
        status=FactoryWalkStatus.COVERAGE_GAP,
        output={},
        source_memento={"kind": "source-memento"},
        reason="via unresolved call `op` at wall.py:3",
    )
    assert row.reason is not None


def test_green_row_needs_no_grounds() -> None:
    row = FactoryWalkCompleteRowDto(
        file="wall.py",
        line=7,
        requested_role="term",
        ast_kind="Call",
        selected="CallSugar",
        status=FactoryWalkStatus.WARRANTED,
        output={},
        source_memento={"kind": "source-memento"},
    )
    assert row.status is FactoryWalkStatus.WARRANTED
