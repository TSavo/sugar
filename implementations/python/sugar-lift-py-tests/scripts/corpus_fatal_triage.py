"""Shared corpus terminal taxonomy retained after factory scanner deletion."""

from __future__ import annotations

import importlib.util
import json
import signal
import subprocess
from pathlib import Path
from typing import Any


PACKAGES = ("numpy", "pandas")
DEFAULT_FILE_TIMEOUT_SECONDS = 30
TRANSPORT_MARKERS = (
    "closed stdout",
    "transport",
    "json-rpc",
    "jsonrpc",
    "broken pipe",
)


def package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).resolve().parent


def python_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )


def _parse_child_stdout(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "outcome" in value:
            return value
    return None


def _transport_text(*parts: str) -> bool:
    text = "\n".join(parts).lower()
    return any(marker in text for marker in TRANSPORT_MARKERS)


def _classify_child(
    *,
    rel: str,
    result: subprocess.CompletedProcess[str] | None,
    timed_out: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    if timed_out:
        return {
            "file": rel,
            "category": "timeout-or-hang",
            "reason": f"child exceeded {timeout_seconds}s",
        }
    assert result is not None
    signal_number = -result.returncode if result.returncode < 0 else None
    if signal_number is not None:
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"signal-{signal_number}"
        return {
            "file": rel,
            "category": "process-crash-or-overflow",
            "returncode": result.returncode,
            "signal": signal_name,
            "reason": result.stderr[-2000:],
        }

    testimony = _parse_child_stdout(result.stdout)
    if testimony is not None and testimony.get("outcome") == "completed":
        return {"file": rel, "category": "completed", "testimony": testimony}
    if testimony is not None and testimony.get("outcome") == "factory-panic":
        return {
            "file": rel,
            "category": "factory-construction-panic",
            "testimony": testimony,
        }
    reason = str(testimony.get("reason") or "") if testimony is not None else ""
    category = (
        "transport-disconnect"
        if _transport_text(reason, result.stdout, result.stderr)
        else "bare-exception"
    )
    return {
        "file": rel,
        "category": category,
        "returncode": result.returncode,
        "testimony": testimony,
        "reason": reason or result.stderr[-2000:] or "child emitted no testimony",
    }
