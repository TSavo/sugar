from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from .compiler import compile_ir_document
from .lifter import _iter_python_files, lift_paths, lift_source

SURFACE = "python-source"
VERSION = "0.1.0-draft"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
# The ONE construction door. There is no `lift` kit method: full-tree
# construction is `sugar.enumerate` over the SourceTree (#6222). Level protocol:
# `protocol/specs/2026-07-08-enumeration-protocol.md`.
ENUMERATE_RPC_METHOD = "sugar.enumerate"


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
                # lift is not a kit method: full-tree construction is
                # sugar.enumerate only (#6222). Same eviction the other kits made.
                {"name": ENUMERATE_RPC_METHOD, "required": True},
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
    if method == ENUMERATE_RPC_METHOD:
        return _enumerate(msg_id, params)
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


# ---------------------------------------------------------------------------
# `sugar.enumerate` -- the ONE construction door
# ---------------------------------------------------------------------------
#
# This kit is per-file independent: `lift_source(source, display_path)` is
# already the whole-file unit `lift_paths` loops over, and it carries no
# cross-file state. So `universe` is exactly that call for the ONE demanded
# file, and full-tree construction is the Rust fold walking `source_files` and
# asking `universe` per file. There is no residency problem to solve here.


def _degenerate_file_memento(
    rel_path: str, source_cid: str | None = None
) -> dict[str, Any]:
    """The file-level locator: a `source-memento` with only `file` and the
    file's content CID populated. A whole file has no single body span or AST
    template, so those stay absent. Same shape every other kit seals."""
    return {
        "kind": "source-memento",
        "file": rel_path,
        "function_name": "",
        "span": None,
        "param_names": [],
        "source_cid": source_cid,
        "template_cid": None,
    }


def _enumerate_result(
    msg_id: Any, nodes: list[dict[str, Any]], gaps: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"nodes": nodes, "gaps": gaps},
    }


def _memento_matches(candidate: dict[str, Any], target: dict[str, Any]) -> bool:
    """Primary-key equality for a file locator: same file, and same content CID
    when the target pins one. A degenerate (file-only) target matches on file
    alone."""
    if candidate.get("file") != target.get("file"):
        return False
    target_cid = target.get("source_cid") or target.get("sourceCid")
    if target_cid and candidate.get("source_cid") != target_cid:
        return False
    return True


def _resolved_under_root(root: Path, rel: str) -> Path | None:
    """A forged memento carrying an absolute path (pathlib join discards the
    root) or a `../` traversal could otherwise enumerate files OUTSIDE the
    workspace. Require the resolved path to stay under the resolved root."""
    try:
        full = (root / rel).resolve()
    except OSError:
        return None
    try:
        full.relative_to(root)
    except ValueError:
        return None
    return full


def _enumerate(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    """`sugar.enumerate`: `source_files` censuses the workspace's real source
    closure; `universe` constructs the ONE demanded file's IR.

    Only the two levels full-tree construction needs are served. Every other
    level is a LOUD refusal rather than an empty success: this kit does see
    functions and call sites, so answering an empty census for them would be a
    false zero, and a false zero is worse than a named gap. That is not a
    regression -- before this door existed the whole method was
    METHOD_NOT_FOUND.
    """
    from .source_oracle import SourceUnavailable, path_source

    level = params.get("level")
    root = Path(str(params.get("workspace_root", "."))).resolve()
    at = params.get("at") if isinstance(params.get("at"), dict) else None
    seek = bool(params.get("seek", False))

    if level == "source_files":
        nodes: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        for file_path in sorted(_iter_python_files(root)):
            rel_path = os.path.relpath(file_path, root)
            try:
                # Identity is MINTED through the oracle, never hashed here, so
                # this kit addresses a file exactly as every other kit does.
                _source, _filename, cid = path_source(str(file_path))
            except SourceUnavailable as unavailable:
                # An unreadable/undecodable file is a loud protocol gap, never
                # a node with a made-up identity.
                gaps.append(
                    {
                        "memento": _degenerate_file_memento(rel_path),
                        "reason": str(unavailable),
                    }
                )
                continue
            memento = _degenerate_file_memento(rel_path, cid)
            if seek and at is not None and not _memento_matches(memento, at):
                continue
            nodes.append({"memento": memento, "audit": None, "payload": None})
        return _enumerate_result(msg_id, nodes, gaps)

    if level == "universe":
        rel_path = at.get("file") if at else None
        if not isinstance(rel_path, str) or not rel_path:
            return _enumerate_result(
                msg_id,
                [],
                [
                    {
                        "memento": at,
                        "reason": "sugar.enumerate level='universe' requires `at.file`",
                    }
                ],
            )
        full_path = _resolved_under_root(root, rel_path)
        if full_path is None:
            return _enumerate_result(
                msg_id,
                [],
                [
                    {
                        "memento": at,
                        "reason": (
                            f"path '{rel_path}' escapes workspace root '{root}'"
                        ),
                    }
                ],
            )
        try:
            source, _filename, cid = path_source(str(full_path))
        except SourceUnavailable as unavailable:
            return _enumerate_result(
                msg_id,
                [],
                [
                    {
                        "memento": _degenerate_file_memento(rel_path),
                        "reason": str(unavailable),
                    }
                ],
            )
        memento = _degenerate_file_memento(rel_path, cid)
        # The per-file unit `lift_paths` already loops over. Same rows, same
        # order -- this is the SAME construction the retired `lift` performed,
        # reached through the one door instead of the retired method.
        file_result = lift_source(source, rel_path)
        nodes = [
            {"memento": memento, "audit": row, "payload": None}
            for row in file_result.ir
        ]
        # A refusal is this file's construction saying why a row is absent. It
        # is a first-class gap, never a silently shorter node list.
        gaps = [
            {"memento": memento, "reason": json.dumps(refusal, sort_keys=True)}
            for refusal in file_result.refusals
        ]
        return _enumerate_result(msg_id, nodes, gaps)

    return _error(
        msg_id,
        -32602,
        f"sugar.enumerate: level {level!r} is not served by surface "
        f"`{SURFACE}`. This kit serves `source_files` and `universe`, which "
        f"together reproduce the construction the retired `lift` method "
        f"performed. Serving another level means constructing it here -- "
        f"answering an empty census would be a false zero.",
    )


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
