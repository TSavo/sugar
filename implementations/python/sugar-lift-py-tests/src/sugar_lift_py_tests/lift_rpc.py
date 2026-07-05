from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sugar_lift_py_tests.audit_only import collect_construction_gaps
from sugar_lift_py_tests.effect import SourceOracleEffect, effect_reason, effect_status
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.kit_rpc import LiftReportPayloadDto
from sugar_lift_py_tests.lib import lift_source

KIT_ID = "python"
KIT_VERSION = "0.1.0"
NO_SOURCE_SITES_MESSAGE = "factory source contained no source sites"
LIFT_RPC_MODULE = "sugar_lift_py_tests.lift_rpc"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
COMPONENT_PLAN_RPC_METHOD = "sugar.component.plan"
RESOLVE_SOURCE_MEMENTO_RPC_METHOD = "sugar.plugin.resolve_source_memento"
COMPONENT_PROTOCOL_VERSION = "sugar-component/1"
LIFT_PROTOCOL_VERSION = "pep/1.7.0"
PYTHON_SURFACE = "python"
PYTHON_LIFT_NAME = "python-lift"
PYTHON_SOURCE_ORACLE_NAME = "python-source-oracle"
COMPONENT_PLAN_INTENTS = {"lift", "prove", "verify"}
PARSE_ERROR = object()


def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _recv() -> Optional[Dict[str, Any]] | object:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return PARSE_ERROR
    return value if isinstance(value, dict) else PARSE_ERROR


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
                {"name": COMPONENT_PLAN_RPC_METHOD, "required": False},
                {"name": RESOLVE_SOURCE_MEMENTO_RPC_METHOD, "required": False},
                {"name": "lift", "required": True},
                {"name": "sugar.plugin.lift_implications", "required": False},
                {"name": "sugar.plugin.resolve_dependency_proofs", "required": False},
                {"name": "shutdown", "required": False},
            ]
        },
    }


def _iter_python_files(workspace_root: str, source_paths: List[Any]) -> List[str]:
    root = os.path.abspath(workspace_root)
    out: List[str] = []
    for raw_path in source_paths or ["."]:
        path = str(raw_path)
        full_path = os.path.abspath(
            path if os.path.isabs(path) else os.path.join(root, path)
        )
        if os.path.isfile(full_path):
            if full_path.endswith(".py"):
                out.append(full_path)
            continue
        for dirpath, _, filenames in os.walk(full_path):
            for filename in filenames:
                if filename.endswith(".py"):
                    out.append(os.path.abspath(os.path.join(dirpath, filename)))
    return sorted(set(out))


def _items_from_params(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for evidence_key in (
        "project_forensics",
        "projectForensics",
        "workspace_evidence",
        "workspaceEvidence",
    ):
        evidence = params.get(evidence_key)
        if not isinstance(evidence, dict):
            continue
        items = evidence.get("items")
        if not isinstance(items, list):
            continue
        out.extend(item for item in items if isinstance(item, dict))
    return out


def _language_evidence_from_params(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for evidence_key in ("workspace_evidence", "workspaceEvidence"):
        evidence = params.get(evidence_key)
        if not isinstance(evidence, dict):
            continue
        languages = evidence.get("languages")
        if not isinstance(languages, list):
            continue
        out.extend(item for item in languages if isinstance(item, dict))
    return out


def _path_is_python(path: Any) -> bool:
    return str(path).endswith(".py")


def _item_mentions_python(item: Dict[str, Any]) -> bool:
    language = item.get("language_hint", item.get("languageHint"))
    return language == "python" or _path_is_python(item.get("path", ""))


def _first_python_claim(params: Dict[str, Any], workspace_root: str) -> Optional[str]:
    for item in _items_from_params(params):
        if not _item_mentions_python(item):
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            return item_id
        path = item.get("path")
        if isinstance(path, str) and path:
            return f"file:{path}"

    for language in _language_evidence_from_params(params):
        if language.get("language") != "python":
            continue
        path = language.get("path")
        if isinstance(path, str) and path:
            return f"file:{path}"

    root = Path(workspace_root)
    if root.is_dir():
        for path in sorted(root.rglob("*.py")):
            try:
                relative = path.relative_to(root)
            except ValueError:
                relative = path
            return f"file:{relative.as_posix()}"
    return None


def _component_plan_result(params: Dict[str, Any]) -> Dict[str, Any]:
    intent = str(params.get("intent", "lift"))
    if intent not in COMPONENT_PLAN_INTENTS:
        return {
            "decision": "decline",
            "languages": [PYTHON_SURFACE],
            "reason": f"unsupported plan intent: {intent}",
        }
    workspace_root = str(params.get("workspace_root", "."))
    claim_item = _first_python_claim(params, workspace_root)
    if claim_item is None:
        return {
            "decision": "decline",
            "reason": "no Python source evidence",
        }
    return {
        "decision": "claim",
        "claims": [
            {
                "item": claim_item,
                "role": "source-lifter",
                "surface": PYTHON_SURFACE,
            }
        ],
        "plugins": [
            {
                "name": PYTHON_LIFT_NAME,
                "kind": "lift",
                "surface": PYTHON_SURFACE,
                "emit": "ir-document",
            }
        ],
        "lift_manifests": [
            {
                "surface": PYTHON_SURFACE,
                "name": PYTHON_LIFT_NAME,
                "version": KIT_VERSION,
                "protocol_version": LIFT_PROTOCOL_VERSION,
                "kind": "lift",
                "command": _runtime_lift_command(),
                "working_dir": ".",
            }
        ],
        "source_oracles": [
            {
                "surface": PYTHON_SURFACE,
                "name": PYTHON_SOURCE_ORACLE_NAME,
                "version": KIT_VERSION,
                "method": RESOLVE_SOURCE_MEMENTO_RPC_METHOD,
                "command": _runtime_lift_command(),
                "working_dir": ".",
            }
        ],
        "diagnostics": [],
    }


def _runtime_lift_command() -> List[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--rpc"]


def _source_oracle_api():
    try:
        from sugar_lift_python_source.source_oracle import (
            SourceOracleRefusal,
            resolve_source_memento,
        )
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.source_oracle import (
            SourceOracleRefusal,
            resolve_source_memento,
        )
    return SourceOracleRefusal, resolve_source_memento


def _source_memento_from_params(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = (
        params.get("memento")
        or params.get("sourceMemento")
        or params.get("source_memento")
    )
    if not isinstance(raw, dict):
        return None
    out = dict(raw)
    aliases = {
        "sourceFunctionName": "source_function_name",
        "sourceCid": "source_cid",
        "templateCid": "template_cid",
        "paramNames": "param_names",
    }
    for camel, snake in aliases.items():
        if snake not in out and camel in out:
            out[snake] = out[camel]
    out.setdefault("kind", "source-memento")
    return out


def _source_memento_response(
    original: Dict[str, Any], resolved: Dict[str, Any]
) -> Dict[str, Any]:
    out = dict(original)
    out["kind"] = "source-memento"
    for field_name in ("source_cid", "template_cid", "param_names"):
        if resolved.get(field_name) is not None:
            out[field_name] = resolved[field_name]
    for forbidden in (
        "body_text",
        "ast_template",
        "bodyText",
        "astTemplate",
        "sourceOracle",
    ):
        out.pop(forbidden, None)
    return out


def _source_lines_for_memento(
    workspace_root: str, memento: Dict[str, Any]
) -> List[Dict[str, Any]]:
    file_name = memento.get("file")
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}
    start_line = span.get("start_line")
    end_line = span.get("end_line", start_line)
    if not isinstance(file_name, str) or not isinstance(start_line, int):
        return []
    if not isinstance(end_line, int):
        end_line = start_line
    try:
        source_lines = (
            (Path(workspace_root) / file_name).read_text(encoding="utf-8").splitlines()
        )
    except OSError:
        return []
    start_index = max(start_line - 1, 0)
    end_index = max(end_line, start_line)
    return [
        {"line": start_index + offset + 1, "source": source.rstrip()}
        for offset, source in enumerate(source_lines[start_index:end_index])
    ]


def _source_memento_display(memento: Dict[str, Any]) -> str:
    file_name = str(memento.get("file", "<unknown>"))
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}
    start_line = span.get("start_line", "?")
    start_col = span.get("start_col", "?")
    end_line = span.get("end_line", "?")
    end_col = span.get("end_col", "?")
    name = memento.get("source_function_name") or memento.get("sourceFunctionName")
    source_cid = memento.get("source_cid") or memento.get("sourceCid")
    pieces = [f"{file_name}:{start_line}:{start_col}-{end_line}:{end_col}"]
    if isinstance(name, str) and name:
        pieces.append(name)
    if isinstance(source_cid, str) and source_cid:
        pieces.append(source_cid)
    return " ".join(pieces)


def _source_oracle_effect_result(
    effect: SourceOracleEffect,
    memento: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": effect_status(effect),
        "reason": effect_reason(effect),
        "memento": _source_memento_response(memento, {}),
    }


def _resolve_source_memento_result(params: Dict[str, Any]) -> Dict[str, Any]:
    workspace_root = str(params.get("workspace_root", "."))
    memento = _source_memento_from_params(params)
    if memento is None:
        return {
            "status": "absent",
            "reason": "invalid source memento shape",
        }
    SourceOracleRefusal, resolve_source_memento = _source_oracle_api()
    try:
        resolved = resolve_source_memento(workspace_root, memento)
    except SourceOracleRefusal as exc:
        return _source_oracle_effect_result(
            SourceOracleEffect(reason=str(exc)), memento
        )
    body_text = str(resolved.get("body_text") or "").strip()
    lean_memento = _source_memento_response(memento, resolved)
    return {
        "status": "resolved",
        "source": body_text,
        "bodyText": body_text,
        "sourceLines": _source_lines_for_memento(workspace_root, lean_memento),
        "display": _source_memento_display(lean_memento),
        "memento": lean_memento,
    }


def _handle_initialize(msg_id: Any) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "name": "sugar-lift-python",
                "version": KIT_VERSION,
                "kit_id": KIT_ID,
                "component_protocol_version": COMPONENT_PROTOCOL_VERSION,
            },
        }
    )


def _handle_lift(
    msg_id: Any, params: Dict[str, Any], *, audit_only: bool = False
) -> None:
    workspace_root = str(params.get("workspace_root", "."))
    source_paths = list(params.get("source_paths", ["."]))
    contract_bindings = params.get("contract_bindings") or []
    if not isinstance(contract_bindings, list):
        contract_bindings = []
    try:
        if audit_only:
            _handle_lift_audit_only(
                msg_id,
                workspace_root=workspace_root,
                source_paths=source_paths,
                contract_bindings=contract_bindings,
            )
            return
        payload = LiftReportPayloadDto(source_ledger={})
        bindings_backed_pass = bool(contract_bindings)
        root = Path(workspace_root).resolve()
        for path in _iter_python_files(workspace_root, source_paths):
            full_path = Path(path)
            try:
                rel_path = full_path.resolve().relative_to(root).as_posix()
            except ValueError:
                rel_path = full_path.name
            with open(path, "r", encoding="utf-8") as handle:
                try:
                    result = lift_source(
                        path,
                        handle.read(),
                        memento_file=rel_path,
                        contract_bindings=contract_bindings,
                    )
                except ValueError as exc:
                    if str(exc) == NO_SOURCE_SITES_MESSAGE:
                        continue
                    raise
            if hasattr(result, "payload"):
                file_payload = result.payload
                if bindings_backed_pass:
                    payload.call_edges.extend(file_payload.call_edges)
                    payload.implications.extend(file_payload.implications)
                    payload.diagnostics.extend(file_payload.diagnostics)
                    continue
                payload.ir.extend(file_payload.ir)
                payload.source_mementos.extend(file_payload.source_mementos)
                _merge_source_ledger(payload.source_ledger, file_payload.source_ledger)
                payload.source_audits.extend(file_payload.source_audits)
                payload.factory_audits.extend(file_payload.factory_audits)
                payload.factory_walk.extend(file_payload.factory_walk)
                payload.call_edges.extend(file_payload.call_edges)
                payload.implications.extend(file_payload.implications)
                payload.diagnostics.extend(file_payload.diagnostics)
        _send({"jsonrpc": "2.0", "id": msg_id, "result": payload.to_rpc()})
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


def _handle_lift_audit_only(
    msg_id: Any,
    *,
    workspace_root: str,
    source_paths: List[Any],
    contract_bindings: list,
) -> None:
    root = Path(workspace_root).resolve()
    walkers = []
    for path in _iter_python_files(workspace_root, source_paths):
        full_path = Path(path)
        try:
            rel_path = full_path.resolve().relative_to(root).as_posix()
        except ValueError:
            rel_path = full_path.name
        source = full_path.read_text(encoding="utf-8")

        def walk(
            *,
            path: str = path,
            source: str = source,
            rel_path: str = rel_path,
        ) -> object:
            try:
                return lift_source(
                    path,
                    source,
                    memento_file=rel_path,
                    contract_bindings=contract_bindings,
                )
            except ValueError as exc:
                if str(exc) == NO_SOURCE_SITES_MESSAGE:
                    return None
                raise

        walkers.append((path, walk))

    gaps = collect_construction_gaps(walkers)
    if gaps:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": "audit-only construction gaps",
                    "data": {
                        "auditOnlyGaps": [gap.to_json() for gap in gaps],
                    },
                },
            }
        )
        return
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": LiftReportPayloadDto(source_ledger={}).to_rpc(),
        }
    )


def _merge_source_ledger(
    current: Dict[str, int],
    incoming: Dict[str, int] | None,
) -> None:
    if incoming is None:
        return
    for key, value in incoming.items():
        current[key] = current.get(key, 0) + int(value)


def _handle_resolve_dependency_proofs(msg_id: Any, params: Dict[str, Any]) -> None:
    """Surface dependency `.proof` files from the project's `.sugar/imports/` so the
    rust verifier folds the vendor universe into the proof pool. Mirrors lsp.py's
    handler -- the factory kit must answer this for cross-project federation."""
    import base64

    project_root = str(
        params.get("project_root") or params.get("workspace_root") or "."
    )
    imports_dir = Path(project_root) / ".sugar" / "imports"
    proofs: List[Dict[str, Any]] = []
    if imports_dir.is_dir():
        for path in sorted(imports_dir.glob("blake3-512_*.proof")):
            if not path.is_file():
                continue
            # Normalize the on-disk filename stem (blake3-512_<hex>) to the
            # canonical colon form (blake3-512:<hex>) so the Rust verifier's
            # Rule-1 check (expected_cid == blake3_512_of(bytes)) compares
            # apples-to-apples.  The filename uses underscore for Windows
            # path-safety; the in-memory CID always uses colon.
            stem = path.name[: -len(".proof")]
            cid = (
                stem.replace("blake3-512_", "blake3-512:", 1)
                if stem.startswith("blake3-512_")
                else stem
            )
            proofs.append(
                {
                    "cid": cid,
                    "bytes_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "source": f"sugar-imports:{path.name}",
                }
            )
    _send({"jsonrpc": "2.0", "id": msg_id, "result": {"proofs": proofs}})


def main(argv: Optional[List[str]] = None) -> None:
    argv = argv or []
    audit_only = "--audit-only" in argv
    while True:
        msg = _recv()
        if msg is None:
            break
        if msg is PARSE_ERROR:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "parse error: line was not a JSON-RPC object",
                    },
                }
            )
            continue
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "initialize":
            _handle_initialize(msg_id)
        elif method == KIT_DECLARATION_RPC_METHOD:
            _send({"jsonrpc": "2.0", "id": msg_id, "result": _kit_declaration_result()})
        elif method == COMPONENT_PLAN_RPC_METHOD:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": _component_plan_result(
                        params if isinstance(params, dict) else {}
                    ),
                }
            )
        elif method == RESOLVE_SOURCE_MEMENTO_RPC_METHOD:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": _resolve_source_memento_result(
                        params if isinstance(params, dict) else {}
                    ),
                }
            )
        elif method == "lift":
            _handle_lift(
                msg_id,
                params if isinstance(params, dict) else {},
                audit_only=audit_only,
            )
        elif method == "sugar.plugin.lift_implications":
            _handle_lift(
                msg_id,
                params if isinstance(params, dict) else {},
                audit_only=audit_only,
            )
        elif method == "sugar.plugin.resolve_dependency_proofs":
            _handle_resolve_dependency_proofs(
                msg_id, params if isinstance(params, dict) else {}
            )
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
