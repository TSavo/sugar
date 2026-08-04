"""PEP 1.7.0 newline-delimited JSON-RPC server for the pytest emitter plugin.

Reads one JSON-RPC request per line on stdin, writes one response per line to
stdout. Mirrors the emitter protocol shape of the java sibling
(``sugar-emit-java-junit``).

Supported methods:

- ``sugar.plugin.describe``  - plugin self-description (capabilities +
  supported predicates).
- ``sugar.plugin.invoke``    - emit a pytest test module from an
  :class:`~sugar_emit_python_pytest.emitter.EmitPlan` carried in
  ``params``; returns an :class:`~sugar_emit_python_pytest.emitter.Emission`.
- ``sugar.plugin.shutdown``  - exit.

There is no body-emit, no assembly, no platform semantics: the emitter is a
predicate -> assertion table plus a test-module shell.
"""

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
        request: Any = None
        try:
            request = json.loads(line)
            method = str(request.get("method", ""))
            response = dispatch(request)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"PARSE_ERROR: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface any plugin error to the host
            response = _dispatch_error(request, exc)
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
        # The result IS the plugin memento (loader.rs:parse_and_validate).
        # The loader recomputes header.cid and refuses on mismatch, so the
        # memento must be the full {envelope, header, metadata} shape, not a
        # flat capability object. Capabilities live inside header.content.
        return {"jsonrpc": "2.0", "id": msg_id, "result": PLUGIN_MEMENTO}

    if method == "sugar.plugin.invoke":
        if not isinstance(params, dict):
            return _error(msg_id, -32602, "INVALID_PARAMS: params must be an object")
        plan = EmitPlan.from_params(params)
        emission = emit(plan)
        return {"jsonrpc": "2.0", "id": msg_id, "result": emission.to_json()}

    if method == "sugar.plugin.check":
        if not isinstance(params, dict):
            return _error(msg_id, -32602, "INVALID_PARAMS: params must be an object")
        out_dir = params.get("out_dir")
        if not isinstance(out_dir, str) or not out_dir:
            return _error(msg_id, -32602, "INVALID_PARAMS: missing out_dir")
        return {"jsonrpc": "2.0", "id": msg_id, "result": _check_pytest(out_dir)}

    if method == "sugar.plugin.shutdown":
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}

    return _error(msg_id, -32601, f"METHOD_NOT_FOUND: {method}")


def _check_pytest(out_dir: str) -> dict[str, Any]:
    python = os.environ.get("PYTHON") or sys.executable or "python3"
    completed = subprocess.run(
        [python, "-m", "pytest", ".", "-q"],
        cwd=out_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "command": f"{python} -m pytest . -q",
        "cwd": out_dir,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exitCode": completed.returncode,
    }


def _send(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def _dispatch_error(request: object, exc: Exception) -> dict[str, Any]:
    exception_type = type(exc).__name__
    msg_id = request.get("id") if isinstance(request, dict) else None
    response = _error(
        msg_id,
        -32603,
        f"{exception_type}: {exc}\n{traceback.format_exc()}",
    )
    response["error"]["data"] = {
        "exception_type": exception_type,
        "stage": "dispatch",
    }
    return response
