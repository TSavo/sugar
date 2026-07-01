from __future__ import annotations

import argparse
import json
import sys
import traceback
from typing import Any

from .compiler import compile_ir_document
from .lifter import lift_paths

SURFACE = "python-source"
VERSION = "0.1.0-draft"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"


def initialize_result() -> dict[str, Any]:
    return {
        "name": "sugar-lift-python-source",
        "version": VERSION,
        "protocol_version": "sugar-lift/1",
        "dialect": SURFACE,
        "capabilities": {
            "authoring_surfaces": [SURFACE],
            "ir_version": "v1.1.0",
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
                {"name": "compile", "required": False},
                {"name": "shutdown", "required": False},
            ]
        },
        "proofResolution": {"strategy": "pip"},
        "effectKinds": ["panic-freedom"],
        "effectLeaves": [
            {
                "surface": SURFACE,
                "local": "python:raise",
                "concept": "concept:panic-freedom.leaf.runtime-failure-site",
            },
            {
                "surface": SURFACE,
                "local": "python:attribute",
                "concept": "concept:panic-freedom.leaf.runtime-failure-site",
            },
            {
                "surface": SURFACE,
                "local": "python:subscript",
                "concept": "concept:panic-freedom.leaf.runtime-failure-site",
            },
        ],
        "guardPredicates": [
            {
                "surface": SURFACE,
                "local": "is_some",
                "concept": "concept:panic-freedom.option.some",
            },
            {
                "surface": SURFACE,
                "local": "is_none",
                "concept": "concept:panic-freedom.option.none",
            },
        ],
        "controlCarriers": [
            {
                "surface": SURFACE,
                "local": "cf_guarded",
                "concept": "concept:panic-freedom.guard",
            },
            {
                "surface": SURFACE,
                "local": "cf_ite",
                "concept": "concept:panic-freedom.choice",
            },
        ],
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
    if method == "compile":
        return _compile(msg_id, params)
    if method == "shutdown":
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}
    return _error(msg_id, -32601, f"METHOD_NOT_FOUND: {method}")


def _lift(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    surface = params.get("surface", SURFACE)
    if surface != SURFACE:
        return _error(msg_id, 1003, f"SURFACE_NOT_SUPPORTED: {surface}")

    source_paths = params.get("source_paths")
    if not isinstance(source_paths, list) or not source_paths:
        return _error(msg_id, -32602, "source_paths must be a non-empty array")

    paths = [str(path) for path in source_paths if str(path)]
    if not paths:
        return _error(msg_id, -32602, "source_paths must contain strings")

    result = lift_paths(str(params.get("workspace_root", ".")), paths)
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "kind": "ir-document",
            "ir": result.ir,
            "callEdges": [],
            "diagnostics": result.diagnostics,
            "opacityReport": result.opacity_report,
            "refusals": result.refusals,
        },
    }


def _compile(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    ir = params.get("ir")
    if not isinstance(ir, list):
        return _error(msg_id, -32602, "ir must be an array")
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "kind": "compiled-formula",
            "body": compile_ir_document(ir),
        },
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc", action="store_true", help="run JSON-RPC over stdio")
    parser.add_argument(
        "--bind-rpc", action="store_true", help="run bind JSON-RPC over stdio"
    )
    args = parser.parse_args(argv)
    if args.bind_rpc:
        from .bind_rpc import run_rpc as run_bind_rpc

        run_bind_rpc()
    elif args.rpc:
        run_rpc()
    else:
        parser.print_help()
