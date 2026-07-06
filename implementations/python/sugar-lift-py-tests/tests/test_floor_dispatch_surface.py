from __future__ import annotations

import importlib
import inspect
import json
import os
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

import sugar_lift_py_tests.operations as operations_package
import sugar_lift_py_tests.floor as floor_package
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import (
    FLOOR_OPERATION_METHOD_NAMES,
    REGISTERED_FLOOR_TYPES,
    FloorDispatchSurface,
    FloorValue,
    TermValue,
)
from sugar_lift_py_tests.operations import NextOperation, perform_operation

ROOT = Path(__file__).resolve().parents[1]


def test_protocol_surface_matches_declared_operation_methods() -> None:
    assert tuple(_declared_operation_method_names()) == FLOOR_OPERATION_METHOD_NAMES


def test_registered_floors_match_discoverable_floor_values() -> None:
    assert tuple(_discoverable_floor_value_names()) == tuple(
        floor_type.__name__ for floor_type in REGISTERED_FLOOR_TYPES
    )


def test_registered_floors_satisfy_runtime_protocol() -> None:
    for floor_type in REGISTERED_FLOOR_TYPES:
        assert issubclass(floor_type, FloorDispatchSurface), floor_type.__name__


def test_inherited_construction_gap_keeps_production_owner_blame() -> None:
    with pytest.raises(FactoryGap) as raised:
        perform_operation(
            owner="dispatch-owner",
            blame="dispatch.py:3:4",
            receiver=TermValue(1),
            operation=NextOperation(owner="operation-owner", blame="operation.py:1:2"),
            ctx=None,
        )

    assert raised.value.info.to_json() == {
        "owner": "dispatch-owner",
        "blame": "dispatch.py:3:4",
        "observed": "TermValue",
        "requested": "next_with",
        "fix": "add next_with to TermValue or emit a real effect",
        "gap_kind": "Floor",
        "gap_locus": "Construction",
    }


def test_planted_floor_without_protocol_surface_reds_pyright(tmp_path: Path) -> None:
    planted = tmp_path / "planted_floor_protocol_miss.py"
    planted.write_text(
        "\n".join(
            (
                "from sugar_lift_py_tests.floor import require_floor_dispatch_surface",
                "",
                "class PlantedFloor:",
                "    def add_with(self, operation: object, ctx: object) -> object:",
                "        return None",
                "",
                "require_floor_dispatch_surface(PlantedFloor)",
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
    assert "PlantedFloor" in diagnostics
    assert "FloorDispatchSurface" in diagnostics


def test_planted_binary_operator_wrong_signature_reds_pyright(tmp_path: Path) -> None:
    planted = tmp_path / "planted_binary_operator_signature_miss.py"
    planted.write_text(
        "\n".join(
            (
                "from sugar_lift_py_tests.floor import FloorDispatchSurface, FloorValue",
                "",
                "class WrongBinaryOperatorFloor(FloorValue):",
                "    def binary_operator_with(self, operation: object, ctx: object) -> object:",
                "        return object()",
                "",
                "def require_surface(floor: FloorDispatchSurface) -> None:",
                "    pass",
                "",
                "require_surface(WrongBinaryOperatorFloor())",
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
    assert "WrongBinaryOperatorFloor" in diagnostics
    assert "binary_operator_with" in diagnostics
    assert "BinaryOperatorOperation" in diagnostics


def test_planted_next_operation_wrong_signature_reds_pyright(tmp_path: Path) -> None:
    planted = tmp_path / "planted_next_operation_signature_miss.py"
    planted.write_text(
        "\n".join(
            (
                "from sugar_lift_py_tests.floor import FloorDispatchSurface, FloorValue",
                "",
                "class WrongNextFloor(FloorValue):",
                "    def next_with(self, operation: object, ctx: object) -> object:",
                "        return object()",
                "",
                "def require_surface(floor: FloorDispatchSurface) -> None:",
                "    pass",
                "",
                "require_surface(WrongNextFloor())",
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
    assert "WrongNextFloor" in diagnostics
    assert "next_with" in diagnostics
    assert "NextOperation" in diagnostics


def _declared_operation_method_names() -> list[str]:
    names: set[str] = set()
    prefix = operations_package.__name__ + "."
    for module_info in pkgutil.iter_modules(operations_package.__path__, prefix):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__:
                continue
            method_name = getattr(cls, "method_name", None)
            if isinstance(method_name, str):
                names.add(method_name)
    return sorted(names)


def _discoverable_floor_value_names() -> list[str]:
    names: set[str] = set()
    prefix = floor_package.__name__ + "."
    for module_info in pkgutil.iter_modules(floor_package.__path__, prefix):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__:
                continue
            if cls is not FloorValue and issubclass(cls, FloorValue):
                names.add(cls.__name__)
    return sorted(names)


def _with_src_on_pythonpath() -> str:
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(ROOT / "src")]
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)
