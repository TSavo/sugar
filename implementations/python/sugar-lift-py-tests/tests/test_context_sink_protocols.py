from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sugar_lift_py_tests.context import (
    AuditSink,
    ExternalBridgeSink,
    OperationRecorder,
    ProofSink,
)
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext

ROOT = Path(__file__).resolve().parents[1]


def test_factory_build_context_sink_fields_are_typed_protocols() -> None:
    annotations = FactoryBuildContext.__annotations__
    assert annotations["audit_sink"] == "AuditSink | None"
    assert annotations["factory_audit_sink"] == "AuditSink | None"
    assert annotations["proof_sink"] == "ProofSink | None"
    assert annotations["external_bridge_sink"] == "ExternalBridgeSink | None"
    assert annotations["record_operation"] == "OperationRecorder | None"
    assert annotations["building"] == "frozenset[str]"


def test_bare_object_satisfies_no_sink_protocol_at_runtime() -> None:
    class NotASink:
        pass

    not_a_sink = NotASink()
    assert not isinstance(not_a_sink, AuditSink)
    assert not isinstance(not_a_sink, ProofSink)
    assert not isinstance(not_a_sink, ExternalBridgeSink)


def test_list_satisfies_append_shaped_sink_protocols_at_runtime() -> None:
    rows: list[object] = []
    assert isinstance(rows, AuditSink)
    assert isinstance(rows, ProofSink)
    assert isinstance(rows, ExternalBridgeSink)


def test_bound_method_satisfies_operation_recorder_at_runtime() -> None:
    calls: list[tuple[str, str]] = []

    def recorder(*, owner: str, method_name: str, operation: object) -> None:
        calls.append((owner, method_name))

    assert isinstance(recorder, OperationRecorder)
    recorder(owner="dispatch", method_name="next_with", operation=object())
    assert calls == [("dispatch", "next_with")]


def test_planted_wrong_signature_audit_sink_reds_pyright(tmp_path: Path) -> None:
    planted = tmp_path / "planted_wrong_audit_sink.py"
    planted.write_text(
        "\n".join(
            (
                "from sugar_lift_py_tests.context import FactoryBuildContext",
                "from sugar_lift_py_tests.claim import SugarCatalog",
                "",
                "class WrongAuditSink:",
                "    def append(self, row: int) -> str:",
                "        return str(row)",
                "",
                "def build(catalog: SugarCatalog) -> FactoryBuildContext:",
                "    return FactoryBuildContext(",
                "        filename='planted.py',",
                "        catalog=catalog,",
                "        audit_sink=WrongAuditSink(),",
                "    )",
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
    assert "WrongAuditSink" in diagnostics
    assert "AuditSink" in diagnostics


def test_planted_wrong_signature_operation_recorder_reds_pyright(
    tmp_path: Path,
) -> None:
    planted = tmp_path / "planted_wrong_operation_recorder.py"
    planted.write_text(
        "\n".join(
            (
                "from sugar_lift_py_tests.context import FactoryBuildContext",
                "from sugar_lift_py_tests.claim import SugarCatalog",
                "",
                "def wrong_recorder(owner: str, method_name: str) -> None:",
                "    pass",
                "",
                "def build(catalog: SugarCatalog) -> FactoryBuildContext:",
                "    return FactoryBuildContext(",
                "        filename='planted.py',",
                "        catalog=catalog,",
                "        record_operation=wrong_recorder,",
                "    )",
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
    assert "record_operation" in diagnostics
    assert "OperationRecorder" in diagnostics
    assert "Missing keyword parameter" in diagnostics


def _with_src_on_pythonpath() -> str:
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(ROOT / "src")]
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)
