"""PEP 1.7.0 newline-delimited JSON-RPC server for the unittest emitter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from typing import Any

from .emitter import EmitPlan, emit
from .plugin_memento import PLUGIN_MEMENTO


def run_rpc() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        method = ""
        try:
            request = json.loads(line)
            method = str(request.get("method", ""))
            response = dispatch(request)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"PARSE_ERROR: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface plugin errors to the host
            response = _error(None, -32603, f"{exc}\n{traceback.format_exc()}")
        _send(response)
        if method == "sugar.plugin.shutdown":
            break


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    msg_id = request.get("id")
    method = str(request.get("method", ""))
    params = request.get("params")
    if params is None:
        params = {}

    if method == "sugar.plugin.describe":
        return {"jsonrpc": "2.0", "id": msg_id, "result": PLUGIN_MEMENTO}

    if method == "sugar.plugin.invoke":
        if not isinstance(params, dict):
            return _error(msg_id, -32602, "INVALID_PARAMS: params must be an object")
        emission = emit(EmitPlan.from_params(params))
        return {"jsonrpc": "2.0", "id": msg_id, "result": emission.to_json()}

    if method == "sugar.plugin.check":
        if not isinstance(params, dict):
            return _error(msg_id, -32602, "INVALID_PARAMS: params must be an object")
        out_dir = params.get("out_dir")
        if not isinstance(out_dir, str) or not out_dir:
            return _error(msg_id, -32602, "INVALID_PARAMS: missing out_dir")
        return {"jsonrpc": "2.0", "id": msg_id, "result": _check_unittest(out_dir)}

    if method == "sugar.plugin.shutdown":
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}

    return _error(msg_id, -32601, f"METHOD_NOT_FOUND: {method}")


def _check_unittest(out_dir: str) -> dict[str, Any]:
    python = os.environ.get("PYTHON") or sys.executable or "python3"
    completed = subprocess.run(
        [python, "-m", "unittest", "discover", "-s", "."],
        cwd=out_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "command": f"{python} -m unittest discover -s .",
        "cwd": out_dir,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exitCode": completed.returncode,
    }


def _send(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
