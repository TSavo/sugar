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
from sugar_lift_py_tests.context import ReduceContext

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

ROOT = sugar_lift_py_tests_package_root()


def test_reduce_context_sink_fields_are_typed_protocols() -> None:
    annotations = ReduceContext.__annotations__
    assert annotations["construction_audit_sink"] == "AuditSink | None"
    assert annotations["proof_sink"] == "ProofSink | None"
    assert annotations["external_bridge_sink"] == "ExternalBridgeSink | None"


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
                "from sugar_lift_py_tests.context import ReduceContext",
                "from sugar_lift_py_tests.temporal import TemporalContext",
                "",
                "class WrongAuditSink:",
                "    def append(self, row: int) -> str:",
                "        return str(row)",
                "",
                "def build() -> ReduceContext:",
                "    return ReduceContext(",
                "        temporal=TemporalContext.empty(),",
                "        construction_audit_sink=WrongAuditSink(),",
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


def _with_src_on_pythonpath() -> str:
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(ROOT / "src")]
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)
