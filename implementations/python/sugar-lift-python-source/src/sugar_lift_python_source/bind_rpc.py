from __future__ import annotations

import argparse
import json
import sys
import traceback
from typing import Any

from .bind_lifter import lift_paths

VERSION = "0.1.0"
SURFACE = "python-bind"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"


def initialize_result() -> dict[str, Any]:
    return {
        "name": "sugar-lift-python-bind",
        "version": VERSION,
        "protocol_version": "pep/1.7.0",
        "capabilities": {
            "authoring_surfaces": ["python", "python-bind"],
            "ir_version": "bind-ir/1.0.0",
            "emits_signed_mementos": False,
        },
    }


def kit_declaration_result() -> dict[str, Any]:
    return {
        "kit": {
            "id": SURFACE,
            "language": "python",
            "version": VERSION,
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": True},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": True},
                {"name": "lift", "required": True},
                {"name": "shutdown", "required": False},
            ]
        },
        "proofResolution": {"strategy": "pip"},
        "effectKinds": [],
        "effectLeaves": [],
        "guardPredicates": [],
        "controlCarriers": [],
        "residueCategories": [],
    }


def run_rpc() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = dispatch(request)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"PARSE_ERROR: {exc}")
        except Exception as exc:
            response = _error(None, -32603, f"{exc}\n{traceback.format_exc()}")
        _send(response)


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    msg_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": initialize_result()}
    if method == KIT_DECLARATION_RPC_METHOD:
        return {"jsonrpc": "2.0", "id": msg_id, "result": kit_declaration_result()}
    if method == "lift":
        return _lift(msg_id, params)
    if method == "shutdown":
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}
    return _error(msg_id, -32601, f"METHOD_NOT_FOUND: {method}")


def _lift(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    source_paths = params.get("source_paths")
    paths: list[str]
    if isinstance(source_paths, list):
        paths = [str(path) for path in source_paths if str(path)]
    else:
        paths = ["."]
    if not paths:
        paths = ["."]

    options_value = params.get("options")
    options = options_value if isinstance(options_value, dict) else {}
    # This kit IS the library-bindings (sugar) surface, so default to that layer
    # — which enables zero-code-changes universal lift (every module-level
    # function is sugar). The direct `lift_source(layer="all")` unit tests are
    # unaffected (they don't go through this RPC).
    layer = str(options.get("layer") or "library-bindings")
    result = lift_paths(str(params.get("workspace_root", ".")), paths, layer=layer)
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "kind": "ir-document",
            "ir": result.ir,
            "diagnostics": result.diagnostics,
        },
    }


def _send(obj: dict[str, Any]) -> None:
    # Write bytes with errors="replace": a single pathological source character
    # (e.g. an astral emoji whose surrogate pair got split during source slicing)
    # would otherwise raise UnicodeEncodeError ("surrogates not allowed") and
    # kill the ENTIRE response. A lifter must be robust to one bad byte in one
    # function out of thousands, so unencodable chars become U+FFFD rather than
    # aborting the run.
    line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rpc", action="store_true", help="run bind JSON-RPC over stdio"
    )
    parser.add_argument("--bind-rpc", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.rpc or args.bind_rpc:
        run_rpc()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
