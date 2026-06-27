from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.lib import lift_source


KIT_ID = "python"
KIT_VERSION = "0.1.0"
LIFT_RPC_MODULE = "sugar_lift_py_tests.lift_rpc"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"


def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _recv() -> Optional[Dict[str, Any]]:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _kit_declaration_result() -> Dict[str, Any]:
    return {
        "kit": {
            "id": KIT_ID,
            "language": "python",
            "version": KIT_VERSION,
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": True},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": True},
                {"name": "lift", "required": True},
                {"name": "shutdown", "required": False},
            ]
        },
    }


def _iter_python_files(workspace_root: str, source_paths: List[Any]) -> List[str]:
    root = os.path.abspath(workspace_root)
    out: List[str] = []
    for raw_path in source_paths or ["."]:
        path = str(raw_path)
        full_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(root, path))
        if os.path.isfile(full_path):
            if full_path.endswith(".py"):
                out.append(full_path)
            continue
        for dirpath, _, filenames in os.walk(full_path):
            for filename in filenames:
                if filename.endswith(".py"):
                    out.append(os.path.abspath(os.path.join(dirpath, filename)))
    return sorted(set(out))


def _handle_initialize(msg_id: Any) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "name": "sugar-lift-python",
                "version": KIT_VERSION,
                "kit_id": KIT_ID,
            },
        }
    )


def _handle_lift(msg_id: Any, params: Dict[str, Any]) -> None:
    workspace_root = str(params.get("workspace_root", "."))
    source_paths = list(params.get("source_paths", ["."]))
    try:
        for path in _iter_python_files(workspace_root, source_paths):
            with open(path, "r", encoding="utf-8") as handle:
                lift_source(path, handle.read())
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "kind": "ir-document",
                    "ir": [],
                    "diagnostics": [],
                    "warnings": [],
                },
            }
        )
    except FactoryGap as exc:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(exc),
                    "data": {
                        "info": exc.info,
                        "factoryAudit": exc.audit_row.to_json(),
                    },
                },
            }
        )
    except Exception as exc:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(exc),
                    "data": traceback.format_exc(),
                },
            }
        )


def main(argv: Optional[List[str]] = None) -> None:
    del argv
    while True:
        msg = _recv()
        if msg is None:
            break
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "initialize":
            _handle_initialize(msg_id)
        elif method == KIT_DECLARATION_RPC_METHOD:
            _send({"jsonrpc": "2.0", "id": msg_id, "result": _kit_declaration_result()})
        elif method == "lift":
            _handle_lift(msg_id, params if isinstance(params, dict) else {})
        elif method == "shutdown":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True}})
            break
        else:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"method '{method}' not found",
                    },
                }
            )


if __name__ == "__main__":
    main(sys.argv[1:])
