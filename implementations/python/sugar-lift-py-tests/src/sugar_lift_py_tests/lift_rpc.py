from __future__ import annotations

import ast
import collections
import dataclasses
import gc
import json
import logging
import os
import sys
import time
import traceback
import tracemalloc
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sugar_lift_py_tests.audit_only import AuditOnlyGap, gap_from_factory_panic
from sugar_lift_py_tests.effect import SourceOracleEffect, effect_reason, effect_status
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo
from sugar_lift_py_tests.filename import cid_from_proof_stem
from sugar_lift_py_tests.idd.lift_coverage_accounting import (
    account_lift_coverage,
    paint_lines,
)
from sugar_lift_py_tests.idd.lift_coverage_census import census_paths
from sugar_lift_py_tests.kit_rpc import (
    LiftReportPayloadDto,
    RecoveredAuditDto,
    RecoveredEffectDto,
    RecoveredFactoryPanicDto,
    SuppressedAuditLocusDto,
)
from sugar_lift_py_tests.kit_rpc.rpc_value import to_rpc_value
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus
from sugar_lift_py_tests.source_provenance import kit_source_provenance

KIT_ID = "python"
KIT_VERSION = "0.1.0"
NO_SOURCE_SITES_MESSAGE = "factory source contained no source sites"
LIFT_RPC_MODULE = "sugar_lift_py_tests.lift_rpc"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
COMPONENT_PLAN_RPC_METHOD = "sugar.component.plan"
RESOLVE_SOURCE_MEMENTO_RPC_METHOD = "sugar.plugin.resolve_source_memento"
ENUMERATE_RPC_METHOD = "sugar.enumerate"
COMPONENT_PROTOCOL_VERSION = "sugar-component/1"
LIFT_PROTOCOL_VERSION = "pep/1.7.0"
PYTHON_SURFACE = "python"
PYTHON_LIFT_NAME = "python-lift"
PYTHON_SOURCE_ORACLE_NAME = "python-source-oracle"
COMPONENT_PLAN_INTENTS = {"lift", "prove", "verify"}
PARSE_ERROR = object()
_TRANSPORT_LOG = logging.getLogger("sugar.kit.transport")
# Passive, process-lifetime context paid for by an enumeration demand. The
# outer identity is the file content CID; the path seat is retained because
# source mementos carry the workspace-relative filename even for identical
# bytes at two seats. Descendant questions reuse this already-demanded file
# result instead of reducing every definition again.
_ENUMERATION_FILE_CONTEXTS: collections.OrderedDict[
    str,
    Dict[
        str,
        tuple[
            List[Dict[str, Any]],
            List[Dict[str, Any]],
            Dict[str, Dict[str, Any]],
        ],
    ],
] = collections.OrderedDict()


def _enumeration_cache_limit() -> int:
    raw = os.environ.get("SUGAR_ENUMERATION_FILE_CACHE_LIMIT", "2")
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def _remember_file_context(
    cache: collections.OrderedDict, key: str, value: Any
) -> None:
    """Keep only the hottest file contexts in the resident enumeration kit."""
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _enumeration_cache_limit():
        cache.popitem(last=False)


class _StructuredTransportFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for field in (
            "direction",
            "bytes",
            "message_id",
            "method",
            "stage",
            "cid",
            "cache",
            "elapsed_ms",
            "file",
            "level_name",
            "index",
            "total",
            "definitions",
            "rows",
            "rows_added",
            "contracts",
            "symbol",
            "at",
            "seek",
            "request_count",
            "rss_kib",
            "peak_rss_kib",
            "heap_current_kib",
            "heap_peak_kib",
            "gc_gen0",
            "gc_gen1",
            "gc_gen2",
            "audit_contexts",
            "enumeration_contexts",
            "install_source_entries",
            "source_table_entries",
            "allocation_file",
            "allocation_line",
            "allocation_size_kib",
            "allocation_count",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _configure_transport_logging() -> None:
    path = os.environ.get("SUGAR_KIT_LOG")
    if not path or _TRANSPORT_LOG.handlers:
        return
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(_StructuredTransportFormatter())
    _TRANSPORT_LOG.addHandler(handler)
    _TRANSPORT_LOG.setLevel(os.environ.get("SUGAR_KIT_LOG_LEVEL", "INFO").upper())
    _TRANSPORT_LOG.propagate = False

    previous_hook = sys.excepthook

    def log_unhandled(
        exc_type: type[BaseException], exc: BaseException, tb: Any
    ) -> None:
        _TRANSPORT_LOG.critical(
            "unhandled_exception",
            exc_info=(exc_type, exc, tb),
            extra={"stage": "process.exit"},
        )
        for log_handler in _TRANSPORT_LOG.handlers:
            log_handler.flush()
        previous_hook(exc_type, exc, tb)

    sys.excepthook = log_unhandled


def _profile_interval(name: str) -> int:
    try:
        return max(0, int(os.environ.get(name, "0")))
    except ValueError:
        return 0


def _resident_rss_kib() -> tuple[int | None, int | None]:
    """Current/peak resident bytes from the process, without a new dependency."""
    try:
        fields = {}
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                name, value, *_unit = line.split()
                fields[name.rstrip(":")] = int(value)
        return fields.get("VmRSS"), fields.get("VmHWM")
    except (OSError, ValueError):
        return None, None


def _cache_cardinalities() -> tuple[int, int]:
    install_entries = 0
    install_module = sys.modules.get("sugar_lift_py_tests.sugar.install_source_dig")
    if install_module is not None:
        for name in (
            "_module_sibling_function_nodes",
            "resolve_install_source_funcdef",
            "resolve_install_source_class_method",
        ):
            cached = getattr(install_module, name, None)
            if cached is not None and hasattr(cached, "cache_info"):
                install_entries += cached.cache_info().currsize

    source_entries = 0
    source_module = sys.modules.get("sugar_lift_python_source.source_tables")
    if source_module is not None:
        for name in ("source_splitlines", "source_lines", "_parsed", "parsed_parents"):
            cached = getattr(source_module, name, None)
            if cached is not None and hasattr(cached, "cache_info"):
                source_entries += cached.cache_info().currsize
    return install_entries, source_entries


def _log_resident_profile(request_count: int, method: Any) -> None:
    every = _profile_interval("SUGAR_KIT_PROFILE_EVERY")
    if every <= 0 or request_count % every:
        return
    rss_kib, peak_rss_kib = _resident_rss_kib()
    heap_current, heap_peak = tracemalloc.get_traced_memory()
    gc_counts = gc.get_count()
    install_entries, source_entries = _cache_cardinalities()
    _TRANSPORT_LOG.info(
        "resident_profile",
        extra={
            "stage": "resident.profile",
            "method": method,
            "request_count": request_count,
            "rss_kib": rss_kib,
            "peak_rss_kib": peak_rss_kib,
            "heap_current_kib": heap_current // 1024,
            "heap_peak_kib": heap_peak // 1024,
            "gc_gen0": gc_counts[0],
            "gc_gen1": gc_counts[1],
            "gc_gen2": gc_counts[2],
            "audit_contexts": len(_AUDIT_FILE_CONTEXTS),
            "enumeration_contexts": len(_ENUMERATION_FILE_CONTEXTS),
            "install_source_entries": install_entries,
            "source_table_entries": source_entries,
        },
    )
    top_every = _profile_interval("SUGAR_KIT_PROFILE_TOP_EVERY")
    if top_every <= 0 or request_count % top_every:
        return
    for statistic in tracemalloc.take_snapshot().statistics("lineno")[:20]:
        frame = statistic.traceback[0]
        _TRANSPORT_LOG.info(
            "resident_allocation",
            extra={
                "stage": "resident.profile.allocation",
                "request_count": request_count,
                "allocation_file": frame.filename,
                "allocation_line": frame.lineno,
                "allocation_size_kib": statistic.size // 1024,
                "allocation_count": statistic.count,
            },
        )


def _log_enumeration_demand(
    level: str,
    at: Optional[Dict[str, Any]],
    *,
    cache: str,
    started: float,
) -> None:
    cid = "workspace"
    if at is not None:
        cid = str(
            at.get("source_cid")
            or at.get("sourceCid")
            or at.get("file_cid")
            or "unaddressed"
        )
    _TRANSPORT_LOG.info(
        "enumeration_node_demand",
        extra={
            "cid": cid,
            "cache": cache,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "level_name": level,
            "stage": "enumerate.node",
        },
    )


# UTF-16 surrogate code points. Python's json.dumps emits them as \\udxxx;
# serde_json rejects unpaired surrogates with "unexpected end of hex escape"
# and aborts the whole lift (pandas wall never writes report.json). Scrub at
# the RPC boundary so stdout carries only framed JSON the Rust client accepts.
_SURROGATE_MIN = 0xD800
_SURROGATE_MAX = 0xDFFF


def _scrub_lone_surrogates(value: Any) -> Any:
    """Replace unpaired UTF-16 surrogates so JSON is serde_json-safe.

    Source text can legally contain lone surrogates (pandas tests that assert
    on them). Those must not travel on the kit->cli JSON-RPC channel as raw
    ``\\udxxx`` escapes -- the Rust client dies mid-parse and the wall has no
    report. U+FFFD is the loud, standard stand-in for invalid Unicode.
    """
    if isinstance(value, str):
        if not any(_SURROGATE_MIN <= ord(ch) <= _SURROGATE_MAX for ch in value):
            return value
        return "".join(
            "\ufffd" if _SURROGATE_MIN <= ord(ch) <= _SURROGATE_MAX else ch
            for ch in value
        )
    if isinstance(value, dict):
        return {
            (
                _scrub_lone_surrogates(key) if isinstance(key, str) else key
            ): _scrub_lone_surrogates(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_lone_surrogates(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_lone_surrogates(item) for item in value)
    return value


def _send(obj: Dict[str, Any]) -> None:
    # stdout is the framed JSON-RPC channel only. Scrub before dumps so a lone
    # surrogate in an IR string constant cannot break the Rust parse of the
    # whole response line (#4155 / #4102 wall transport).
    started = time.monotonic()
    _TRANSPORT_LOG.info("response_scrub_enter", extra={"stage": "response.scrub"})
    safe = _scrub_lone_surrogates(obj)
    _TRANSPORT_LOG.info(
        "response_scrub_exit",
        extra={
            "stage": "response.scrub",
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        },
    )
    started = time.monotonic()
    _TRANSPORT_LOG.info("response_encode_enter", extra={"stage": "response.json.dumps"})
    frame = json.dumps(safe, separators=(",", ":")) + "\n"
    _TRANSPORT_LOG.info(
        "response_encode_exit",
        extra={
            "stage": "response.json.dumps",
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "bytes": len(frame.encode()),
        },
    )
    _TRANSPORT_LOG.info(
        "response_about_to_send",
        extra={
            "direction": "kit_to_cli",
            "bytes": len(frame.encode()),
            "message_id": safe.get("id"),
            "method": None,
            "stage": "stdout.write",
        },
    )
    sys.stdout.write(frame)
    _TRANSPORT_LOG.info(
        "flush_enter", extra={"direction": "kit_to_cli", "stage": "stdout.flush"}
    )
    sys.stdout.flush()
    _TRANSPORT_LOG.info(
        "flush_exit", extra={"direction": "kit_to_cli", "stage": "stdout.flush"}
    )


def _recv() -> Optional[Dict[str, Any]] | object:
    _TRANSPORT_LOG.info(
        "read_enter", extra={"direction": "cli_to_kit", "stage": "stdin.readline"}
    )
    line = sys.stdin.readline()
    _TRANSPORT_LOG.info(
        "read_exit",
        extra={
            "direction": "cli_to_kit",
            "bytes": len(line.encode()),
            "stage": "stdin.readline",
        },
    )
    if not line:
        return None
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return PARSE_ERROR
    if isinstance(value, dict):
        _TRANSPORT_LOG.info(
            "request_received",
            extra={
                "direction": "cli_to_kit",
                "bytes": len(line.encode()),
                "message_id": value.get("id"),
                "method": value.get("method"),
                "stage": "dispatch",
            },
        )
        return value
    return PARSE_ERROR


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
                {"name": ENUMERATE_RPC_METHOD, "required": False},
                {"name": "lift", "required": True},
                {"name": "sugar.plugin.lift_implications", "required": False},
                {"name": "sugar.plugin.resolve_dependency_proofs", "required": False},
                {"name": "shutdown", "required": False},
            ]
        },
        # PART 6 FIX (2026-07-08, discovered by `Kit::rendezvous` against a
        # real python kit for the first time -- no prior rust test exercised
        # this path with the python kit; the strong `KitDeclaration` schema
        # (`sugar-claim-envelope`) requires `proofResolution.strategy`
        # non-empty; this kit's proof-resolution mechanism is exactly its
        # `sugar.plugin.resolve_dependency_proofs` handler below.
        "proofResolution": {
            "strategy": "rpc-proof-bytes",
            "rpcMethod": "sugar.plugin.resolve_dependency_proofs",
        },
        "residueCategories": [],
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


def _python_source_verify_api():
    try:
        from sugar_lift_python_source.verify_rpc import lift_workspace
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.verify_rpc import lift_workspace
    return lift_workspace


def _python_source_lifter_api():
    try:
        from sugar_lift_python_source.lifter import lift_source as source_lift_source
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.lifter import lift_source as source_lift_source
    return source_lift_source


def _python_source_public_reexport_map(root: Path) -> dict[str, tuple[str, str]]:
    try:
        from sugar_lift_python_source.bind_lifter import _public_reexport_map
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.bind_lifter import _public_reexport_map
    return _public_reexport_map(root) or {}


def _is_python_test_file(path: Path) -> bool:
    name = path.name
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith(
        "_test.py"
    )


def _is_true_formula(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("kind") == "atomic"
        and value.get("name") == "true"
        and value.get("args") in (None, [])
    )


def _source_precondition_only_contracts(
    workspace_root: str, existing_contracts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    source_lift_source = _python_source_lifter_api()
    root = Path(workspace_root or ".").resolve()
    public_reexports = _python_source_public_reexport_map(root)
    existing_names = {
        str(item.get("fnName") or item.get("name"))
        for item in existing_contracts
        if isinstance(item, dict) and (item.get("fnName") or item.get("name"))
    }
    out: List[Dict[str, Any]] = []
    for filename in _iter_python_files(str(root), ["."]):
        path = Path(filename)
        if _is_python_test_file(path):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.name
        lifted = source_lift_source(source, rel)
        for item in lifted.ir:
            if not isinstance(item, dict) or item.get("kind") != "function-contract":
                continue
            fn_name = item.get("fnName")
            if not isinstance(fn_name, str) or fn_name.startswith("<source-unit"):
                continue
            if fn_name in existing_names:
                continue
            precondition = item.get("pre")
            if _is_true_formula(precondition):
                continue
            contract = {
                "schemaVersion": item.get("schemaVersion", "1"),
                "kind": "function-contract",
                "fnName": fn_name,
                "formals": list(item.get("formals") or []),
                "formalSorts": list(item.get("formalSorts") or []),
                "returnSort": item.get(
                    "returnSort", {"kind": "primitive", "name": "Value"}
                ),
                "pre": precondition,
                "bodyDischargeEligible": False,
                "bodyDischargeRefusalReason": (
                    "precondition-only source guard contract; report path imports "
                    "the source-lifter-owned precondition without importing the raw "
                    "Python body as a dischargeable post"
                ),
                "locus": item.get("locus"),
            }
            contract["bridgeSourceSymbol"] = _source_contract_bridge_symbol(
                fn_name, public_reexports
            )
            out.append(contract)
            existing_names.add(fn_name)
    return out


def _source_contract_bridge_symbol(
    fn_name: str, public_reexports: dict[str, tuple[str, str]]
) -> str:
    public = public_reexports.get(fn_name)
    if public is not None:
        return public[1]
    for constructor_suffix in (".__new__", ".__init__"):
        if not fn_name.endswith(constructor_suffix):
            continue
        class_symbol = fn_name[: -len(constructor_suffix)]
        public_class = public_reexports.get(class_symbol)
        if public_class is not None:
            return public_class[1]
    parts = fn_name.split(".")
    for index in range(len(parts) - 1, 0, -1):
        owner_symbol = ".".join(parts[:index])
        public_owner = public_reexports.get(owner_symbol)
        if public_owner is None:
            continue
        member_suffix = ".".join(parts[index:])
        return f"{public_owner[1]}.{member_suffix}"
    return fn_name


def _source_lifter_function_contracts(
    workspace_root: str,
) -> tuple[List["SourceFunctionContractDto"], List[Dict[str, Any]]]:
    from sugar_lift_py_tests.kit_rpc.source_function_contract_dto import (
        SourceFunctionContractDto,
    )

    lift_workspace = _python_source_verify_api()
    ir_items, diagnostics = lift_workspace(workspace_root, "bare")
    contracts = [
        item
        for item in ir_items
        if isinstance(item, dict) and item.get("kind") == "function-contract"
    ]
    contracts.extend(_source_precondition_only_contracts(workspace_root, contracts))
    return [
        SourceFunctionContractDto(dict(contract)) for contract in contracts
    ], diagnostics


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


def _degenerate_file_memento(
    rel_path: str, source_cid: Optional[str] = None
) -> Dict[str, Any]:
    """The file-level locator (Part 6 Phase 2's "degenerate memento shape"):
    a `source-memento` with only `file` populated -- span/source_cid/
    template_cid absent (`null`), since a whole file has no single body/AST
    template to CID. `SourceFile` is the one node type whose locator does not
    name a function body."""
    return {
        "kind": "source-memento",
        "file": rel_path,
        "function_name": "",
        "span": None,
        "param_names": [],
        "source_cid": source_cid,
        "template_cid": None,
    }


def _enumerate_file_of(at: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(at, dict):
        return None
    file_name = at.get("file")
    return file_name if isinstance(file_name, str) and file_name else None


def _span_is_degenerate(span: Any) -> bool:
    """All-zero / missing span is a degenerate (file/name-only) locator."""
    if not isinstance(span, dict):
        return True
    return all(
        span.get(key) in (0, None)
        for key in ("start_line", "start_col", "end_line", "end_col")
    )


def _span_contains(outer: Any, inner: Any) -> bool:
    """True when inner span lies within outer (line/col order). Degenerate → False."""
    if _span_is_degenerate(outer) or _span_is_degenerate(inner):
        return False
    outer_start = (int(outer.get("start_line") or 0), int(outer.get("start_col") or 0))
    outer_end = (int(outer.get("end_line") or 0), int(outer.get("end_col") or 0))
    inner_start = (int(inner.get("start_line") or 0), int(inner.get("start_col") or 0))
    inner_end = (int(inner.get("end_line") or 0), int(inner.get("end_col") or 0))
    return inner_start >= outer_start and inner_end <= outer_end


def _call_site_under_function(
    site_memento: Dict[str, Any],
    target_fn: Any,
    target_span: Any,
) -> bool:
    """Whether a contract memento is under the parent function for call_sites.

    Prefer span containment when the parent memento has a non-degenerate span
    (self-locating SourceMemento locus). Fall back to function-name match when span
    is absent so degenerate locators still work.
    """
    if not _span_is_degenerate(target_span):
        site_span = site_memento.get("span")
        if _span_contains(target_span, site_span):
            return True
        # Parent has a real span but site is outside it — not under this fn.
        # Still allow name match only when site span is also degenerate (no locus).
        if not _span_is_degenerate(site_span):
            return False
    if target_fn:
        item_fn = (
            site_memento.get("source_function_name")
            or site_memento.get("sourceFunctionName")
            or site_memento.get("function_name")
        )
        return item_fn == target_fn
    return True


def _memento_matches(candidate: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Primary-key equality for the tree's locator (the plan's "memento is
    the primary key"): same file + same span + same source_cid. Only span
    fields present on BOTH sides are compared, so a degenerate (file-only)
    target matches on file alone."""
    if candidate.get("file") != target.get("file"):
        return False
    target_source_cid = target.get("source_cid") or target.get("sourceCid")
    if target_source_cid:
        if candidate.get("source_cid") != target_source_cid:
            return False
    target_span = target.get("span")
    # The Rust client's `SourceMemento` has no optional span -- a
    # degenerate (file-only) locator round-trips through it as an
    # all-zero span (`SrcSpan{0,0,0,0}`), not `null` (see `tree.rs`'s
    # `decode_memento` doc). Treat an all-zero span the SAME as "no span
    # constraint" so a file-level seek survives that round trip.
    if isinstance(target_span, dict) and any(
        target_span.get(key) not in (0, None)
        for key in ("start_line", "start_col", "end_line", "end_col")
    ):
        candidate_span = candidate.get("span") or {}
        for key in ("start_line", "start_col", "end_line", "end_col"):
            if key in target_span and candidate_span.get(key) != target_span.get(key):
                return False
    target_fn = (
        target.get("function_name")
        or target.get("sourceFunctionName")
        or target.get("source_function_name")
    )
    if target_fn:
        candidate_fn = (
            candidate.get("function_name")
            or candidate.get("sourceFunctionName")
            or candidate.get("source_function_name")
        )
        if candidate_fn != target_fn:
            return False
    return True


def _call_site_seek_matches(candidate: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Match a typed call-site cursor by its durable source locus.

    Rust ``SourceMemento`` stores one function spelling. Decoding a call-site
    wire memento selects its source owner, so the assertion-only
    ``function_name`` alias is not available when that cursor is emitted again.
    File + span + source CID remain the complete call-site address.
    """
    locus = dict(target)
    locus.pop("function_name", None)
    locus.pop("sourceFunctionName", None)
    locus.pop("source_function_name", None)
    return _memento_matches(candidate, locus)


def _universe_bridge_matches(candidate: Any, call_site_bridge: str) -> bool:
    """Whether a callable universe is the target of this call-site bridge."""
    if not isinstance(candidate, str):
        return False
    if candidate == call_site_bridge:
        return True
    _, separator, spelling = call_site_bridge.partition(":")
    return bool(
        separator
        and spelling
        and (candidate == spelling or candidate.endswith(f".{spelling}"))
    )


def _lift_file_for_enumeration(workspace_root: str, root: Path, file_rel: str) -> tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    Dict[str, Dict[str, Any]],
]:
    """Lift ONE file server-side (Part 6 Phase 3: "it is ACCEPTABLE ... for
    the first cut to lift the WHOLE file ... and slice/serve the requested
    level from that one parse" -- file-granular laziness, not per-node wire
    laziness).

    Returns `(ir_items, call_edges, term_table)` from the same payload-owned
    wire projection. Keeping the table beside the rows is construction law:
    no enumeration slice may retain a term-ref after dropping its resolver.
    - `ir`: `kind="function-contract"` = function/universe rows;
      `kind="contract"` = claim rows that already bundle locus + formula
      (call-site ≡ assertion is **factory truth**, not a protocol fold —
      see protocol Section 4 / `_handle_enumerate`)
    - `callEdges`: batch join keys with first-class `targetSymbol`
      (`call:len`, `method:count`) — sliced onto call_sites audit as
      `bridgeSourceSymbol` (do not re-invent prefixes from FOL alone;
      method calls are `method:` on the edge even when FOL uses `call:`).
      Edges are join metadata, not a second site-record set.
    """
    from sugar_lift_py_tests.canonicalizer import blake3_512_of

    full_path = (root / file_rel).resolve()
    source = full_path.read_text(encoding="utf-8")
    file_cid = blake3_512_of(source.encode())
    seats = _ENUMERATION_FILE_CONTEXTS.get(file_cid)
    if seats is not None and file_rel in seats:
        _ENUMERATION_FILE_CONTEXTS.move_to_end(file_cid)
        _TRANSPORT_LOG.info(
            "enumeration_file_context_hit",
            extra={
                "stage": "enumerate.file_context",
                "cid": file_cid,
                "file": file_rel,
                "cache": "hit",
            },
        )
        return seats[file_rel]
    file_payload = lift_file_payload(source, file_rel)
    file_rpc = file_payload.to_rpc()
    ir_items = file_rpc["ir"]
    call_edges = file_rpc["callEdges"]
    term_table = file_rpc["termTable"]
    result = (ir_items, call_edges, term_table)
    seats = _ENUMERATION_FILE_CONTEXTS.setdefault(file_cid, {})
    seats[file_rel] = result
    _remember_file_context(_ENUMERATION_FILE_CONTEXTS, file_cid, seats)
    _TRANSPORT_LOG.info(
        "enumeration_file_context_miss",
        extra={
            "stage": "enumerate.file_context",
            "cid": file_cid,
            "file": file_rel,
            "cache": "miss",
        },
    )
    return result


def lift_file_payload(source: str, filename: str) -> LiftReportPayloadDto:
    """The RPC door over the collapse. Build each def through the factory,
    slam it, and serve the value's payload_rows: a universe mints a
    function-contract plus inv rows; testimony mints only ::assertion fact
    rows (no post, no contract). Enumeration is functions by design: module
    statements no FunctionDefSugar owns are not lifted here.

    Mandatory FactoryPanic is fail-fast here. Diagnostic continuation is a
    separate `RecoveredAuditDto` lane and can never be returned from this door.
    """
    from sugar_lift_py_tests.ir import constructor_symbol_kinds, term_intern_scope

    with term_intern_scope():
        started = time.monotonic()
        _TRANSPORT_LOG.info(
            "lift_file_enter", extra={"stage": "lift_file.audit", "file": filename}
        )
        payload, _gaps = audit_lift_file(source, filename)
        symbol_kinds = constructor_symbol_kinds()
        _TRANSPORT_LOG.info(
            "lift_file_exit",
            extra={
                "stage": "lift_file.audit",
                "file": filename,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                "contracts": len(payload.ir),
                "rows": len(symbol_kinds),
            },
        )
        return replace(payload, symbol_kinds=symbol_kinds)


@dataclasses.dataclass(frozen=True)
class _SeedPanicEvidence:
    """Immutable audit data copied out of a transient FactoryPanic."""

    locus: str
    demanded_source: str
    info: FactoryGapInfo


def _module_import_temporal(
    module, catalog, *, recovered_panics=None, assertion_sink=None
) -> "object":
    """Bind constructed module declarations into a TemporalContext.

    Deeper floors: names introduced by ``import pytest`` / ``from x import Y``
    must stand when reducing function bodies. Without this, TemporalContext
    panics on unbound import names even though the source stated the import.
    Imports use the same ``ImportAliasValue`` constructed by ``AliasSugar``.
    A valued single-name Assign or AnnAssign uses the same factory-built
    ``BoundVar`` representation as ``_ctx_with_module_global_binds``. Each
    assignment is independent: an unowned or runtime-effect RHS stays unbound
    without poisoning siblings. Annotation-only declarations bind nothing.
    """
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
    from sugar_lift_py_tests.floor import BlockValue, ClassValue, ImportAliasValue
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.temporal import TemporalContext

    temporal = TemporalContext.empty()
    module_function_resolver = {
        stmt.function_name(): stmt.node
        for stmt in module.statements()
        if stmt.observed == "FunctionDef"
    }
    for stmt in module.statements():
        observed = stmt.observed
        if observed == "Import":
            for name, asname in stmt.import_names():
                bound = asname or name.split(".")[0]
                # ``import a.b as c`` binds c; ``import a.b`` binds a
                if asname is None and "." in name:
                    bound = name.split(".")[0]
                    mod_term = name.split(".")[0]
                else:
                    mod_term = name
                temporal = temporal.bind_value(
                    bound,
                    ImportAliasValue(mod_term, bound, import_target=mod_term),
                )
        elif observed == "ImportFrom":
            for name, asname in stmt.importfrom_names():
                if name == "*":
                    continue  # star-import stays loud / unsupported
                bound = asname or name
                import_target = (
                    f"{stmt.importfrom_module()}.{name}"
                    if stmt.importfrom_module()
                    else name
                )
                from sugar_lift_py_tests.sugar.install_source_dig import (
                    resolve_install_source_value,
                )

                import_ctx = FactoryBuildContext(
                    filename=stmt.filename,
                    catalog=catalog,
                    temporal=temporal,
                    module_temporal=temporal,
                )
                try:
                    resolved_value = resolve_install_source_value(
                        import_target, import_ctx
                    )
                except FactoryPanic as panic:
                    if recovered_panics is None:
                        raise
                    recovered_panics.append(
                        _SeedPanicEvidence(
                            locus=f"{stmt.filename}:{stmt.line}:{stmt.col}",
                            demanded_source=import_target,
                            info=panic.info,
                        )
                    )
                    resolved_value = None
                temporal = temporal.bind_value(
                    bound,
                    ImportAliasValue(
                        name,
                        bound,
                        import_target=import_target,
                        resolved_value=resolved_value,
                    ),
                )
        elif observed == "ClassDef":
            name = stmt.class_name()
            temporal = temporal.bind_value(
                name,
                ClassValue(name=name, bases=(), record=BlockValue(())),
            )
        elif observed == "FunctionDef":
            ctx = FactoryBuildContext(
                filename=stmt.filename,
                catalog=catalog,
                temporal=temporal,
                module_temporal=temporal,
                name_resolver=module_function_resolver,
            )
            try:
                callable_value = ctx.build_body(stmt, SugarRole.STATEMENT).reduce(ctx)
            except FactoryPanic:
                if recovered_panics is None:
                    raise
                # A FunctionDef owns its body panic. Module seeding only needs
                # to leave the failed callable unbound; the per-definition
                # audit records the locus exactly once. Projecting it here as a
                # module seed would duplicate the same independent panic when
                # the function leaf is audited.
                continue
            if isinstance(callable_value, Incomplete):
                continue
            temporal = callable_value.extend_scope(ctx).temporal
        elif observed in {"Assign", "AnnAssign", "Assert"}:
            if observed == "Assert":
                ctx = FactoryBuildContext(
                    filename=stmt.filename,
                    catalog=catalog,
                    temporal=temporal,
                    module_temporal=temporal,
                )
                try:
                    outcome = ctx.build_body(stmt, SugarRole.STATEMENT).reduce(ctx)
                except FactoryPanic as panic:
                    if recovered_panics is None:
                        raise
                    recovered_panics.append(
                        _SeedPanicEvidence(
                            locus=f"{stmt.filename}:{stmt.line}:{stmt.col}",
                            demanded_source=f"assert:{stmt.line}:{stmt.col}",
                            info=panic.info,
                        )
                    )
                    continue
                if isinstance(outcome, Incomplete):
                    continue
                if assertion_sink is not None:
                    assertion_sink.extend(outcome.contribution())
                temporal = outcome.extend_scope(ctx).temporal
                continue
            if observed == "Assign":
                name = stmt.assign_target_name()
            else:
                try:
                    name = stmt.annassign_target_id()
                except TypeError:
                    continue
                if stmt.annassign_value() is None:
                    continue
            if name is None:
                continue
            ctx = FactoryBuildContext(
                filename=stmt.filename,
                catalog=catalog,
                temporal=temporal,
            )
            try:
                outcome = ctx.build_body(stmt, SugarRole.STATEMENT).reduce(ctx)
            except FactoryPanic as panic:
                if recovered_panics is None:
                    raise
                recovered_panics.append(
                    _SeedPanicEvidence(
                        locus=f"{stmt.filename}:{stmt.line}:{stmt.col}",
                        demanded_source=f"binding:{name}",
                        info=panic.info,
                    )
                )
                continue
            except (TypeError, ValueError, AssertionError):
                continue
            if isinstance(outcome, Incomplete):
                continue
            temporal = outcome.extend_scope(ctx).temporal
    return temporal


def _iter_liftable_function_defs(module):
    """Yield every function-definition fragment owned by the audit frontier.

    Both synchronous and asynchronous definitions are independent source loci:
    unsupported async construction must reach the recovered panic boundary
    instead of disappearing into a false-clean file. Class bodies are walked
    recursively because pytest class-based tests put ``test_*`` methods there.
    """
    stack = list(module.statements())
    while stack:
        stmt = stack.pop(0)
        observed = stmt.observed
        if observed in {"FunctionDef", "AsyncFunctionDef"}:
            yield stmt
        elif observed == "ClassDef":
            # class body may contain methods and nested classes
            try:
                stack[0:0] = list(stmt.class_body())
            except Exception:
                continue


def _module_import_maps(module) -> "tuple[dict, dict]":
    """Return (import_aliases, from_imports) for FactoryBuildContext.

    Vendor dig: CallSugar / MethodCallSugar / dig resolve need the same maps
    SourceFragment.call_import_target_name uses — temporal SymbolicValue alone
    does not populate them. Closed, structural: only what the module states.
    """
    import_aliases: dict[str, str] = {}
    from_imports: dict[str, tuple[str, str]] = {}
    for stmt in module.statements():
        observed = stmt.observed
        if observed == "Import":
            for name, asname in stmt.import_names():
                bound = asname or name.split(".")[0]
                # ``import a.b as c`` binds c -> a.b; ``import a.b`` binds a -> a
                if asname is not None:
                    import_aliases[bound] = name
                else:
                    import_aliases[name.split(".")[0]] = name.split(".")[0]
        elif observed == "ImportFrom":
            mod = stmt.importfrom_module() or ""
            for name, asname in stmt.importfrom_names():
                if name == "*":
                    continue
                bound = asname or name
                from_imports[bound] = (mod, name)
    return import_aliases, from_imports


def _qualified_callable_spelling(filename: str, callable_name: str) -> str:
    """Content-independent callable spelling rooted at its Python module."""
    module_parts = list(Path(filename).with_suffix("").parts)
    if module_parts and module_parts[-1] == "__init__":
        module_parts.pop()
    module = ".".join(part for part in module_parts if part not in ("", "."))
    if not module or callable_name == module or callable_name.startswith(f"{module}."):
        return callable_name
    return f"{module}.{callable_name}"


@dataclasses.dataclass(frozen=True)
class _AuditFileContext:
    source: str
    filename: str
    file_cid: str
    catalog: Any
    module: Any
    module_temporal: Any
    seed_panics: tuple[_SeedPanicEvidence, ...]
    module_assertions: tuple[Any, ...]
    import_aliases: dict[str, str]
    from_imports: dict[str, tuple[str, str]]
    name_resolver: dict[str, Any]
    definitions: tuple[Any, ...]
    definitions_by_cid: dict[str, Any]


# Bounded process-lifetime context for the resident kit. File content CID is
# the sole key; _remember_file_context applies the same explicit capacity as
# enumeration contexts so evicted source/AST ownership is collectible.
_AUDIT_FILE_CONTEXTS: collections.OrderedDict[str, _AuditFileContext] = (
    collections.OrderedDict()
)


def _audit_file_context(
    source: str,
    filename: str,
    file_cid: str,
    *,
    hold_seed_panics: bool = True,
) -> _AuditFileContext:
    started = time.monotonic()
    # Contexts that intentionally hold seed failures are safe to memoize: the
    # caller consumes those failures as audit data. Normal lifting must
    # reconstruct the context without a recovery sink so the first seed
    # FactoryPanic propagates and no completed payload can be emitted.
    cached = _AUDIT_FILE_CONTEXTS.get(file_cid) if hold_seed_panics else None
    if cached is not None:
        _AUDIT_FILE_CONTEXTS.move_to_end(file_cid)
        _TRANSPORT_LOG.info(
            "enumeration_file_context",
            extra={
                "cid": file_cid,
                "cache": "hit",
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                "file": filename,
                "stage": "enumerate.context",
            },
        )
        return cached

    from sugar_lift_py_tests.factory.build import default_catalog
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    catalog = default_catalog()
    source_root = SourceFragment.from_source(source, filename)
    roots = source_root.statements()
    # A zero-statement Module is still the lawful source node for this file.
    # Keep it as the context root so enumeration can answer with its honest
    # empty child set instead of throwing outside the recovered-audit door.
    module = roots[0] if roots else source_root
    seed_panics: list[_SeedPanicEvidence] = []
    module_assertions: list[Any] = []
    module_temporal = _module_import_temporal(
        module,
        catalog,
        recovered_panics=seed_panics if hold_seed_panics else None,
        assertion_sink=module_assertions,
    )
    import_aliases, from_imports = _module_import_maps(module)
    definitions = tuple(_iter_liftable_function_defs(module))
    definitions_by_cid = {
        to_rpc_value(definition.memento())["source_cid"]: definition
        for definition in definitions
    }
    name_resolver: dict[str, Any] = {
        stmt.function_name(): stmt.node
        for stmt in definitions
        if stmt.observed == "FunctionDef"
    }
    for stmt in module.statements():
        if stmt.observed != "ClassDef":
            continue
        cname = stmt.class_name()
        for body_stmt in stmt.class_body():
            if body_stmt.observed == "FunctionDef":
                name_resolver[f"{cname}.{body_stmt.function_name()}"] = body_stmt.node
            elif body_stmt.observed == "ClassDef":
                nested = body_stmt.class_name()
                for nested_stmt in body_stmt.class_body():
                    if nested_stmt.observed == "FunctionDef":
                        name_resolver[f"{nested}.{nested_stmt.function_name()}"] = (
                            nested_stmt.node
                        )
    context = _AuditFileContext(
        source=source,
        filename=filename,
        file_cid=file_cid,
        catalog=catalog,
        module=module,
        module_temporal=module_temporal,
        seed_panics=tuple(seed_panics),
        module_assertions=tuple(module_assertions),
        import_aliases=import_aliases,
        from_imports=from_imports,
        name_resolver=name_resolver,
        definitions=definitions,
        definitions_by_cid=definitions_by_cid,
    )
    if hold_seed_panics:
        _remember_file_context(_AUDIT_FILE_CONTEXTS, file_cid, context)
    _TRANSPORT_LOG.info(
        "enumeration_file_context",
        extra={
            "cid": file_cid,
            "cache": "miss",
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "file": filename,
            "stage": "enumerate.context",
        },
    )
    return context


def audit_lift_file(
    source: str,
    filename: str,
    *,
    hold_panic: Literal[False] = False,
    recover_panics: bool = False,
    target_memento: Optional[Dict[str, Any]] = None,
    audit_context: Optional[_AuditFileContext] = None,
) -> tuple[LiftReportPayloadDto, list[AuditOnlyGap]] | RecoveredAuditDto:
    """Lift normally, or enumerate panics as a disjoint recovered audit.

    The legacy ``hold_panic`` lane returned partial ``LiftReportPayloadDto``
    values and is deliberately rejected. Only ``recover_panics=True`` may
    continue, and that branch returns ``RecoveredAuditDto`` with no IR lane.
    """
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.factory.build import build_node
    from sugar_lift_py_tests.outcome import complete_value
    from sugar_lift_py_tests.sugar_body import SugarBody

    if hold_panic:
        raise TypeError(
            "hold_panic partial lift artifacts are retired; use "
            "recover_panics=True for a diagnostic-only RecoveredAuditDto"
        )

    payload = LiftReportPayloadDto(source_ledger={})
    gaps: list[AuditOnlyGap] = []
    recovered_panics: list[RecoveredFactoryPanicDto] = []
    recovered_effects: list[RecoveredEffectDto] = []
    suppressed_descendants: list[SuppressedAuditLocusDto] = []
    if audit_context is None:
        from sugar_lift_py_tests.canonicalizer import blake3_512_of

        try:
            audit_context = _audit_file_context(
                source,
                filename,
                blake3_512_of(source.encode()),
                hold_seed_panics=recover_panics,
            )
        except ValueError:
            audit_context = None
    if audit_context is None:
        # Empty/comment-only modules have no source site to construct. Their
        # honest audit result is the empty set, not an indexing crash and not a
        # fabricated support row.
        from sugar_lift_py_tests.idd.lift_coverage_census import (
            reconcile_body_owner_loci,
        )

        object.__setattr__(
            payload,
            "source_factory_conservation",
            reconcile_body_owner_loci(source, file=filename, factory_rows=[]),
        )
        if recover_panics:
            return RecoveredAuditDto()
        return payload, gaps
    catalog = audit_context.catalog
    module = audit_context.module
    seed_panics = audit_context.seed_panics
    module_assertions = audit_context.module_assertions
    module_temporal = audit_context.module_temporal
    target_owner = (
        target_memento.get("function_name")
        or target_memento.get("sourceFunctionName")
        or target_memento.get("source_function_name")
        if target_memento
        else None
    )
    target_is_module = target_owner == "<module>"
    for evidence in (
        (seed_panics or ()) if target_memento is None or target_is_module else ()
    ):
        recovered_panics.append(
            RecoveredFactoryPanicDto(
                locus=evidence.locus,
                demanded_source=evidence.demanded_source,
                terminal_gap_locus=evidence.info.blame,
                reason=evidence.info.message,
                gap=evidence.info.to_json(),
            )
        )
    import_aliases = audit_context.import_aliases
    from_imports = audit_context.from_imports
    if target_is_module:
        return RecoveredAuditDto(panics=recovered_panics)
    if module_assertions:
        from sugar_lift_py_tests.floor import BlockValue, TestimonyValue

        module_testimony = TestimonyValue(
            name="<module>",
            formals=(),
            record=BlockValue(tuple(module_assertions)),
        )
        payload.ir.extend(module_testimony.payload_rows(None))
        payload.call_edges.extend(module_testimony.call_edges())
    # Same-module name_resolver: bare f() and Class.method dig bodies.
    name_resolver = audit_context.name_resolver
    definitions = audit_context.definitions
    if target_memento is not None:
        target_cid = target_memento.get("source_cid") or target_memento.get("sourceCid")
        target_definition = audit_context.definitions_by_cid.get(str(target_cid))
        definitions = (target_definition,) if target_definition is not None else ()
    definition_total = len(definitions)
    for definition_index, stmt in enumerate(definitions):
        # Every discovered def reaches construction. An owned FunctionDef or
        # test_* testimony takes its Some arm; an unowned shape must reach the
        # None arm so this audit door can hold and paint the gap red.
        label = f"{filename}:{stmt.line}:{stmt.col}"
        definition_started = time.monotonic()
        _TRANSPORT_LOG.info(
            "definition_enter",
            extra={
                "stage": "lift_file.definition",
                "file": filename,
                "index": definition_index,
                "total": definition_total,
            },
        )
        try:
            lexical_temporal = module_temporal
            for class_stmt in module.statements():
                if class_stmt.observed != "ClassDef":
                    continue
                body = class_stmt.class_body()
                if not any(item.node is stmt.node for item in body):
                    continue
                for item in body:
                    if item.node is stmt.node:
                        break
                    if item.observed != "Assign" or item.assign_target_name() is None:
                        continue
                    seed_ctx = FactoryBuildContext(
                        filename=filename,
                        catalog=catalog,
                        temporal=lexical_temporal,
                        module_temporal=module_temporal,
                        import_aliases=import_aliases,
                        from_imports=from_imports,
                        name_resolver=name_resolver,
                    )
                    seed = build_node(
                        item, filename=filename, role=SugarRole.STATEMENT, ctx=seed_ctx
                    ).sugar.desugar(seed_ctx)
                    lexical_temporal = seed.extend_scope(seed_ctx).temporal
                break
            ctx = FactoryBuildContext(
                filename=filename,
                catalog=catalog,
                temporal=lexical_temporal,
                module_temporal=module_temporal,
                import_aliases=import_aliases,
                from_imports=from_imports,
                name_resolver=name_resolver,
            )
            # Every def enumerated by this audit door with a real
            # universe/testimony claimant is a definition root, including class
            # methods. Executable defs encountered while reducing a body still
            # use STATEMENT and bind a FunctionCallable.
            definition_candidates = catalog.candidates_for(SugarRole.DEFINITION, stmt)
            root_role = (
                SugarRole.DEFINITION if definition_candidates else SugarRole.STATEMENT
            )
            result = build_node(stmt, filename=filename, role=root_role, ctx=ctx)
            root = SugarBody(
                sugar=result.sugar,
                role=root_role,
                audit_row=result.audit_row,
            )
            walk_start = len(payload.factory_walk)
            payload.factory_walk.extend(root.factory_walk_rows())
            payload.factory_audits.extend(root.factory_audit_rows())
            outcome = result.sugar.desugar(ctx)
            _TRANSPORT_LOG.info(
                "definition_desugar_exit",
                extra={
                    "stage": "lift_file.definition.desugar",
                    "file": filename,
                    "index": definition_index,
                    "total": definition_total,
                    "elapsed_ms": round(
                        (time.monotonic() - definition_started) * 1000, 3
                    ),
                },
            )
            if recover_panics:
                from sugar_lift_py_tests.outcome import Incomplete

                if isinstance(outcome, Incomplete):
                    # The recovered audit enumerates construction gaps. A typed
                    # runtime effect is already an honest Some => effect arm,
                    # so it contributes no FactoryPanic and cannot be projected
                    # to a completed value. Keep walking independent roots.
                    from sugar_lift_py_tests.effect import (
                        effect_kind,
                        effect_reason,
                        effect_status,
                    )

                    recovered_effects.append(
                        RecoveredEffectDto(
                            locus=label,
                            effect=type(outcome.effect).__name__,
                            category=effect_kind(outcome.effect),
                            status=effect_status(outcome.effect),
                            reason=effect_reason(outcome.effect),
                        )
                    )
                    continue
            value = complete_value(outcome, owner="lift_file_payload")
            from sugar_lift_py_tests.floor import FunctionCallable, UniverseValue

            if isinstance(value, FunctionCallable):
                # A def statement constructs and binds a callable. It is not a
                # body universe and therefore mints no function-contract row.
                continue
            if isinstance(value, UniverseValue):
                owner = _definition_class_owner(module, stmt)
                if owner is not None:
                    value = dataclasses.replace(value, name=f"{owner}.{value.name}")
                bridge_source_symbol = value.bridge_source_symbol or value.name
                qualified_name = _qualified_callable_spelling(filename, value.name)
                value = dataclasses.replace(
                    value,
                    name=qualified_name,
                    bridge_source_symbol=bridge_source_symbol,
                )
                _qualify_factory_walk_owner(
                    payload.factory_walk, walk_start, qualified_name
                )
            def_memento = dataclasses.replace(
                stmt.memento(),
                source_function_name=value.name,
                role="function-contract",
            )
            rows_started = time.monotonic()
            rows = value.payload_rows(def_memento)
            payload.ir.extend(rows)
            payload.call_edges.extend(value.call_edges())
            payload.source_mementos.append(def_memento)
            _TRANSPORT_LOG.info(
                "definition_exit",
                extra={
                    "stage": "lift_file.definition.payload_rows",
                    "file": filename,
                    "index": definition_index,
                    "total": definition_total,
                    "rows_added": len(rows),
                    "rows": len(payload.ir),
                    "elapsed_ms": round((time.monotonic() - rows_started) * 1000, 3),
                },
            )
        except FactoryPanic as panic:
            _TRANSPORT_LOG.info(
                "definition_gap",
                extra={
                    "stage": "lift_file.definition.gap",
                    "file": filename,
                    "index": definition_index,
                    "total": definition_total,
                    "elapsed_ms": round(
                        (time.monotonic() - definition_started) * 1000, 3
                    ),
                },
            )
            if not recover_panics:
                raise
            # Diagnostic recovery records the panic but never returns `payload`.
            gap = gap_from_factory_panic(label, panic)
            gaps.append(gap)
            payload.factory_walk.append(_factory_walk_red_from_gap(gap))
            if recover_panics:
                recovered_panics.append(
                    RecoveredFactoryPanicDto(
                        locus=label,
                        demanded_source=f"definition:{stmt.function_name()}",
                        terminal_gap_locus=panic.info.blame,
                        reason=panic.info.message,
                        gap=panic.info.to_json(),
                    )
                )
                from sugar_lift_py_tests.idd.lift_coverage_census import (
                    body_owner_descendant_loci,
                )

                for descendant in body_owner_descendant_loci(stmt.node, file=filename):
                    suppressed_descendants.append(
                        SuppressedAuditLocusDto(
                            locus=f"{descendant.file}:{descendant.line}:{descendant.col}"
                        )
                    )
    # Conservation is a file-level accounting pass. A keyed leaf contributes
    # only its recovered audit vector; rerunning whole-file conservation for
    # every leaf is both semantically duplicate and quadratic.
    if recover_panics and target_memento is not None:
        return RecoveredAuditDto(
            panics=recovered_panics,
            effects=recovered_effects,
            suppressed_descendants=suppressed_descendants,
        )

    from sugar_lift_py_tests.idd.lift_coverage_census import reconcile_body_owner_loci

    conservation_started = time.monotonic()
    _TRANSPORT_LOG.info(
        "conservation_enter",
        extra={"stage": "lift_file.conservation", "file": filename},
    )
    conservation = reconcile_body_owner_loci(
        source, file=filename, factory_rows=payload.factory_walk
    )
    _TRANSPORT_LOG.info(
        "conservation_exit",
        extra={
            "stage": "lift_file.conservation",
            "file": filename,
            "elapsed_ms": round((time.monotonic() - conservation_started) * 1000, 3),
        },
    )
    object.__setattr__(payload, "source_factory_conservation", conservation)
    if conservation.violations:
        from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow

        for violation in conservation.violations:
            locus = violation.locus
            message = (
                "source→factory conservation violation: body-owning source locus "
                f"{locus.identity} disappeared before factory classification"
            )
            audit = FactoryAuditRow(
                role="statement",
                status=FactoryAuditStatus.SUGAR_GAP,
                observed=locus.kind,
                blame=f"{locus.file}:{locus.line}:{locus.col}",
                selected=None,
                candidates=[],
                message=message,
            )
            gap = AuditOnlyGap(
                label=locus.identity,
                info={
                    "gap_kind": "Conservation",
                    "gap_locus": locus.identity,
                    "observed": locus.kind,
                    "requested": "source→factory classification",
                    "fix": "remove the pre-factory skip or classify an explicit boundary",
                },
                audit_row=audit,
                message=message,
            )
            gaps.append(gap)
            payload.factory_walk.append(_factory_walk_red_from_gap(gap))
            if recover_panics:
                # Conservation is an independent producer. Its typed gap must
                # cross the recovered-audit boundary just like a FactoryPanic;
                # otherwise the final DTO discards ``gaps`` and can claim a
                # false-clean frontier for source that disappeared pre-factory.
                # A root already present in another terminal bucket is not a
                # producer gap: keep the buckets disjoint and do not count it
                # twice merely because the factory red row names the inner
                # observed shape rather than its poisoned definition owner.
                locus_label = f"{locus.file}:{locus.line}:{locus.col}"
                terminal_loci = {
                    item.locus
                    for item in (
                        *recovered_panics,
                        *recovered_effects,
                        *suppressed_descendants,
                    )
                }
                if locus_label not in terminal_loci:
                    recovered_panics.append(
                        RecoveredFactoryPanicDto(
                            locus=locus.identity,
                            demanded_source=f"conservation:{locus.identity}",
                            terminal_gap_locus=locus.identity,
                            reason=message,
                            gap=gap.info,
                        )
                    )
    if recover_panics:
        return RecoveredAuditDto(
            panics=recovered_panics,
            effects=recovered_effects,
            suppressed_descendants=suppressed_descendants,
        )
    return payload, gaps


def _definition_class_owner(module, definition) -> str | None:
    """Qualified lexical class owner for a discovered definition, if any."""

    def search(class_site, prefix: str) -> str | None:
        qualified = (
            f"{prefix}.{class_site.class_name()}" if prefix else class_site.class_name()
        )
        for item in class_site.class_body():
            if item.node is definition.node:
                return qualified
            if item.observed == "ClassDef":
                found = search(item, qualified)
                if found is not None:
                    return found
        return None

    for statement in module.statements():
        if statement.observed != "ClassDef":
            continue
        found = search(statement, "")
        if found is not None:
            return found
    return None


def _qualify_factory_walk_owner(rows, start: int, qualified_name: str) -> None:
    """Stamp the class-qualified definition identity on this root's audit rows."""
    from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto

    for index in range(start, len(rows)):
        row = rows[index]
        memento = row.source_memento
        if isinstance(memento, SourceMementoDto):
            memento = dataclasses.replace(memento, source_function_name=qualified_name)
        elif isinstance(memento, dict):
            memento = {
                **memento,
                "source_function_name": qualified_name,
                "sourceFunctionName": qualified_name,
            }
        rows[index] = dataclasses.replace(row, source_memento=memento)


def _factory_walk_red_from_gap(gap: AuditOnlyGap):
    """Project a held FactoryPanic as a factory-walk red row.

    status=unclassified serializes to unresolved/verdict=gap so
    visual_factory_walk_rows takes the existing RED-with-grounds arm.
    """
    from sugar_lift_py_tests.canonicalizer import blake3_512_of
    from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import (
        FactoryWalkRedRowDto,
        FactoryWalkStatus,
    )
    from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
    from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto

    audit = gap.audit_row
    blame = str(audit.blame or gap.info.get("blame") or gap.label or "")
    file, line, col = _parse_blame_locus(blame)
    if not file:
        # Fall back to the def label (filename:line:col) when blame is bare.
        file, line, col = _parse_blame_locus(gap.label)
    memento = SourceMementoDto(
        file=file or "<unknown>",
        span=SourceSpanDto(
            start_line=line,
            start_col=col,
            end_line=line,
            end_col=col,
        ),
        source_cid=blake3_512_of(b""),
    )
    reason = gap.message or audit.message or "factory gap"
    return FactoryWalkRedRowDto(
        file=file or "<unknown>",
        line=line,
        requested_role=str(audit.role or gap.info.get("requested") or "statement"),
        ast_kind=str(audit.observed or gap.info.get("observed") or "unknown"),
        selected=audit.selected,
        status=FactoryWalkStatus.UNCLASSIFIED,
        output=str(audit.status or FactoryAuditStatus.SUGAR_GAP),
        source_memento=memento,
        reason=reason,
        extra={
            "candidates": list(audit.candidates),
            "blame": blame,
            "gap_kind": str(gap.info.get("gap_kind") or ""),
            "gap_locus": str(gap.info.get("gap_locus") or ""),
        },
    )


def _parse_blame_locus(site: str) -> tuple[str, int, int]:
    """Parse 'path:line:col' from the right (paths may contain colons)."""
    if not site:
        return "", 0, 0
    parts = site.rsplit(":", 2)
    if len(parts) == 3:
        file, line_s, col_s = parts
        try:
            return file, int(line_s), int(col_s)
        except ValueError:
            return site, 0, 0
    if len(parts) == 2:
        file, line_s = parts
        try:
            return file, int(line_s), 0
        except ValueError:
            return site, 0, 0
    return site, 0, 0


def _item_memento(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    warrants = item.get("sourceWarrants")
    if isinstance(warrants, list) and warrants and isinstance(warrants[0], dict):
        return warrants[0]
    return None


def _item_fact_formula(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return item.get("inv") if item.get("inv") is not None else item.get("post")


def _find_item_by_memento(
    items: List[Dict[str, Any]], target: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if not isinstance(target, dict):
        return None
    for item in items:
        memento = _item_memento(item)
        if memento is not None and _memento_matches(memento, target):
            return item
    return None


def _first_bridge_ctor_name(
    node: Any,
    term_table: Optional[Dict[str, Dict[str, Any]]] = None,
    active: frozenset[str] = frozenset(),
) -> Optional[str]:
    """First `call:` / `method:` ctor head in a closed FOL term graph."""
    if not isinstance(node, dict):
        return None
    if node.get("kind") == "term-ref" and term_table is not None:
        cid = node.get("cid")
        if isinstance(cid, str) and cid not in active:
            return _first_bridge_ctor_name(
                term_table.get(cid), term_table, active | {cid}
            )
        return None
    name = node.get("name")
    if (
        node.get("kind") == "ctor"
        and isinstance(name, str)
        and (name.startswith("call:") or name.startswith("method:"))
    ):
        return name
    for value in node.values():
        if isinstance(value, dict):
            found = _first_bridge_ctor_name(value, term_table, active)
            if found is not None:
                return found
        elif isinstance(value, list):
            for child in value:
                found = _first_bridge_ctor_name(child, term_table, active)
                if found is not None:
                    return found
    return None


def _contract_bridge_identity(
    item: Dict[str, Any],
    term_table: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    """Callee identity for a `kind=contract` assertion: FOL ctor head, else name.

    Used to join a call-site record to a `function-contract` universe via
    `bridgeSourceSymbol` (e.g. `call:add` → `mathy::add::callable`).
    Returns the `call:` / `method:` form with prefix preserved — never a bare
    name when a first-class bridge identity is available.
    """
    formula = _item_fact_formula(item)
    if isinstance(formula, dict):
        # Prefer the left-hand side of an equality assertion (the call).
        if formula.get("kind") == "atomic" and formula.get("name") == "=":
            args = formula.get("args")
            if isinstance(args, list) and args:
                found = _first_bridge_ctor_name(args[0], term_table)
                if found is not None:
                    return found
        found = _first_bridge_ctor_name(formula, term_table)
        if found is not None:
            return found
    raw_name = item.get("name")
    if isinstance(raw_name, str):
        for prefix in ("call:", "method:"):
            idx = raw_name.find(prefix)
            if idx < 0:
                continue
            rest = raw_name[idx:]
            end = 0
            while end < len(rest) and (rest[end].isalnum() or rest[end] in (":", "_")):
                end += 1
            if end > len(prefix):
                return rest[:end]
    return None


def _edge_target_symbol_for_contract(
    item: Dict[str, Any],
    call_edges: Optional[List[Dict[str, Any]]],
    term_table: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    """Batch call-edge target for this exact contract-row locus, if any.

    ``sourceContract`` is only the owner bucket: one caller can own many edges.
    Exact call-site coordinates select inside that bucket. Older built-in edges
    without a locus may still join by an exact carried/FOL bridge identity.
    Ambiguous or absent evidence refuses substitution instead of choosing the
    first edge owned by the caller.
    """
    if not call_edges:
        return None
    name = item.get("name")
    if not isinstance(name, str) or not name:
        return None

    owner_edges: List[Dict[str, Any]] = []
    for edge in call_edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("sourceContract") or edge.get("source_contract")
        if source == name or name.startswith(f"{source}::"):
            owner_edges.append(edge)

    memento = _item_memento(item) or {}
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}

    def at_item_locus(edge: Dict[str, Any]) -> bool:
        locus = edge.get("callSiteLocus") or edge.get("call_site_locus")
        if not isinstance(locus, dict) or _span_is_degenerate(span):
            return False
        locus_file = locus.get("file")
        if locus_file and locus_file != memento.get("file"):
            return False
        line = locus.get("line")
        col = locus.get("col")
        if col is None:
            col = locus.get("column")
        if not isinstance(line, int):
            return False
        start_line = int(span.get("start_line") or 0)
        end_line = int(span.get("end_line") or 0)
        if not start_line <= line <= end_line:
            return False
        if isinstance(col, int) and start_line == end_line == line:
            return (
                int(span.get("start_col") or 0) <= col <= int(span.get("end_col") or 0)
            )
        return True

    locus_edges = [edge for edge in owner_edges if at_item_locus(edge)]
    if len(locus_edges) == 1:
        target = locus_edges[0].get("targetSymbol") or locus_edges[0].get(
            "target_symbol"
        )
        if isinstance(target, str) and target.startswith(("call:", "method:")):
            return target

    bridge = _contract_bridge_identity(item, term_table)
    identity_edges = [
        edge
        for edge in (locus_edges or owner_edges)
        if (edge.get("targetSymbol") or edge.get("target_symbol")) == bridge
    ]
    if len(identity_edges) == 1:
        return bridge
    return None


def _call_site_node_audit(
    item: Dict[str, Any],
    call_edges: Optional[List[Dict[str, Any]]] = None,
    term_table: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Enumerate audit for `call_sites` / `assertions` nodes.

    Stamps first-class `bridgeSourceSymbol` (`call:len`, `method:count`, …)
    onto the wire audit so the tree client can decode
    `CallSite.bridge_source_symbol` without re-mining FOL. Precedence:
    1. batch `callEdges.targetSymbol` for this contract (authoritative
       method:/call: split — do not invent prefixes)
    2. IR-stamped `bridgeSourceSymbol` already in call:/method: form
    3. FOL / name via `_contract_bridge_identity`
    The prefix is never normalized away. `name` rides along from the IR item.
    """
    audit = dict(item)
    edge_sym = _edge_target_symbol_for_contract(item, call_edges, term_table)
    if edge_sym is not None:
        audit["bridgeSourceSymbol"] = edge_sym
        return audit
    existing = audit.get("bridgeSourceSymbol")
    if isinstance(existing, str) and (
        existing.startswith("call:") or existing.startswith("method:")
    ):
        return audit
    bridge = _contract_bridge_identity(item, term_table)
    if bridge is not None:
        audit["bridgeSourceSymbol"] = bridge
    return audit


def _universe_node_from_item(
    item: Dict[str, Any],
    file_rel: str,
    *,
    resolved_bridge: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a `level=universe` wire node from a function-contract IR row.

    Stamps the batch `name` (e.g. `len::builtin-universe`) onto the memento's
    function_name fields so client-side collectors that only see
    `SourceMemento::to_json()` still recover the universe member key.
    """
    name = item.get("name") if isinstance(item.get("name"), str) else ""
    base = _item_memento(item)
    if base is None:
        memento: Dict[str, Any] = {
            "kind": "source-memento",
            "file": file_rel,
            "function_name": name,
            "source_function_name": name,
            "sourceFunctionName": name,
            "span": None,
            "param_names": [],
            "source_cid": None,
            "template_cid": None,
        }
    else:
        memento = dict(base)
    if name:
        # Batch universe member key — must survive decode_memento → to_json.
        memento["function_name"] = name
        memento["source_function_name"] = name
        memento["sourceFunctionName"] = name
        memento["name"] = name
    audit = dict(item)
    if resolved_bridge is not None:
        prefix, separator, spelling = resolved_bridge.partition(":")
        audit["bridgeSourceSymbol"] = (
            spelling if separator and prefix in {"call", "method"} else resolved_bridge
        )
    return {
        "memento": memento,
        "audit": audit,
        "payload": _item_fact_formula(item),
    }


def _implication_node_for_callsite(
    at: Dict[str, Any],
    ir_items: List[Dict[str, Any]],
    call_edges: List[Dict[str, Any]],
    term_table: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Describe one per-callsite linker question, never answer it in the kit."""
    call_item = _find_item_by_memento(ir_items, at)
    if call_item is None or call_item.get("kind") != "contract":
        return {
            "memento": at,
            "audit": {
                "kind": "implication-question",
                "sourceContract": "<unknown caller>",
                "targetSymbol": "unknown",
                "candidateCount": 0,
            },
            "payload": None,
        }

    bridge_candidates: List[str] = []
    edge_symbol = _edge_target_symbol_for_contract(call_item, call_edges, term_table)
    if edge_symbol is not None:
        bridge_candidates.append(edge_symbol)
    fol_symbol = _contract_bridge_identity(call_item, term_table)
    if fol_symbol is not None and fol_symbol not in bridge_candidates:
        bridge_candidates.append(fol_symbol)
    target_symbol = bridge_candidates[0] if bridge_candidates else "unknown"

    matches: Dict[tuple[Any, Any], tuple[Dict[str, Any], str]] = {}
    for bridge in bridge_candidates:
        for item in ir_items:
            if item.get("kind") != "function-contract":
                continue
            if not _universe_bridge_matches(item.get("bridgeSourceSymbol"), bridge):
                continue
            memento = _item_memento(item) or {}
            identity = (
                memento.get("source_cid") or memento.get("sourceCid"),
                item.get("name") or item.get("bridgeSourceSymbol"),
            )
            matches.setdefault(identity, (item, bridge))

    source_memento = _item_memento(call_item) or at
    source_cid = str(
        source_memento.get("source_cid")
        or source_memento.get("sourceCid")
        or "blake3-512:missing-source"
    )
    caller_context = _item_fact_formula(call_item)
    target_candidates: List[Dict[str, Any]] = []
    for target, bridge in matches.values():
        target_memento = _item_memento(target) or {}
        target_cid = str(
            target_memento.get("source_cid")
            or target_memento.get("sourceCid")
            or "blake3-512:missing-target"
        )
        callee_pre = target.get("pre")
        target_candidates.append(
            {
                "bridgeSourceSymbol": bridge,
                "contract": {
                    "name": str(target.get("name") or target_symbol.split(":", 1)[-1]),
                    "kit": "python-source",
                    "contract_cid": target_cid,
                    "pre_json": callee_pre,
                    "post_json": target.get("post"),
                },
            }
        )
    span = source_memento.get("span")
    span = span if isinstance(span, dict) else {}
    demand = {
        "sourceContract": {
            "name": str(call_item.get("name") or "<unknown caller>"),
            "kit": "python-source",
            "contract_cid": source_cid,
            "pre_json": None,
            "post_json": caller_context,
        },
        "targetCandidates": target_candidates,
        "callEdge": {
            "source_contract_cid": source_cid,
            "target_contract_cid": None,
            "target_symbol": target_symbol,
            "call_site_locus": {
                "file": str(source_memento.get("file") or ""),
                "line": span.get("start_line"),
                "column": span.get("start_col"),
            },
        },
    }
    return {
        "memento": at,
        "audit": {
            "kind": "implication-question",
            "sourceContract": call_item.get("name", "<unknown caller>"),
            "targetSymbol": target_symbol,
            "candidateCount": len(target_candidates),
            "callSiteMemento": at,
        },
        "payload": demand,
    }


def _term_ref_cids(value: Any):
    """Yield every term reference in a response-owned value.

    A term-ref is a leaf in the wire graph. Malformed reference objects are
    refused here, before a JSON-RPC response can be constructed.
    """
    if isinstance(value, dict):
        if value.get("kind") == "term-ref":
            cid = value.get("cid")
            if not isinstance(cid, str) or not cid:
                raise ValueError(
                    "term position must be a `{kind: term-ref, cid}` object"
                )
            yield cid
            return
        for child in value.values():
            yield from _term_ref_cids(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _term_ref_cids(child)


def _closed_enumerate_result(
    nodes: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
    *,
    term_tables: Optional[List[Dict[str, Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Construct one closed enumeration result or refuse it.

    The response is the ownership boundary for its term DAG. Every reachable
    term-ref brings exactly one canonical row with it; omitted/dangling tables,
    cycles, conflicting rows, malformed children, and CID/content mismatch are
    impossible to serialize through this constructor.
    """
    result: Dict[str, Any] = {"nodes": nodes, "gaps": gaps}
    roots = tuple(dict.fromkeys(_term_ref_cids(result)))
    if not roots:
        return result
    if term_tables is None:
        raise ValueError(
            "sugar.enumerate response contains term-ref but is missing required `termTable`"
        )

    merged: Dict[str, Dict[str, Any]] = {}
    for table in term_tables:
        if not isinstance(table, dict):
            raise ValueError("sugar.enumerate `termTable` must be an object")
        for cid, node in table.items():
            if cid in merged and merged[cid] != node:
                raise ValueError(
                    f"term-table CID `{cid}` has conflicting producer rows"
                )
            merged[cid] = node

    from sugar_lift_py_tests.canonicalizer import jcs_hash
    from sugar_lift_py_tests.ir import _json_like_to_value

    reachable: Dict[str, Dict[str, Any]] = {}
    resolved: Dict[str, Dict[str, Any]] = {}
    active: set[str] = set()

    def resolve(cid: str) -> Dict[str, Any]:
        cached = resolved.get(cid)
        if cached is not None:
            return cached
        if cid in active:
            raise ValueError(f"cyclic term-table reference at CID `{cid}`")
        node = merged.get(cid)
        if not isinstance(node, dict):
            raise ValueError(f"missing term-table CID `{cid}`")
        active.add(cid)
        kind = node.get("kind")
        if kind == "var":
            if not isinstance(node.get("name"), str):
                raise ValueError(f"term-table CID `{cid}` missing `name`")
            canonical = {"kind": "var", "name": node["name"]}
        elif kind == "const":
            if "value" not in node or "sort" not in node:
                raise ValueError(f"term-table CID `{cid}` missing const value or sort")
            canonical = {
                "kind": "const",
                "value": node["value"],
                "sort": node["sort"],
            }
        elif kind == "ctor":
            if not isinstance(node.get("name"), str):
                raise ValueError(f"term-table CID `{cid}` missing `name`")
            args = node.get("args")
            if not isinstance(args, list):
                raise ValueError(f"term-table CID `{cid}` missing ctor args")
            resolved_args = []
            for reference in args:
                if (
                    not isinstance(reference, dict)
                    or reference.get("kind") != "term-ref"
                ):
                    raise ValueError(
                        f"term-table CID `{cid}` has invalid child: expected kind `term-ref`"
                    )
                child_cid = reference.get("cid")
                if not isinstance(child_cid, str) or not child_cid:
                    raise ValueError(f"term-table CID `{cid}` has invalid term-ref")
                resolved_args.append(resolve(child_cid))
            canonical = {
                "kind": "ctor",
                "name": node["name"],
                "args": resolved_args,
            }
        else:
            raise ValueError(f"term-table CID `{cid}` has unknown kind `{kind}`")
        active.remove(cid)
        actual = jcs_hash(_json_like_to_value(canonical))
        if actual != cid:
            raise ValueError(
                f"term-table CID mismatch: key `{cid}` resolves to `{actual}`"
            )
        resolved[cid] = canonical
        reachable[cid] = node
        return canonical

    for root in roots:
        resolve(root)
    result["termTable"] = reachable
    return result


def _send_enumerate_result(
    msg_id: Any,
    nodes: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
    *,
    term_tables: Optional[List[Dict[str, Dict[str, Any]]]] = None,
) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": _closed_enumerate_result(nodes, gaps, term_tables=term_tables),
        }
    )


def _handle_enumerate(msg_id: Any, params: Dict[str, Any]) -> None:
    """`sugar.enumerate`: the ONE wire method behind the Rust `tree` module's
    lazy accessors (Part 6 Phase 2,
    `protocol/specs/2026-07-08-enumeration-protocol.md`). `level` selects the
    granularity; `at` is the parent's (scan) or this node's own (seek)
    memento; `seek=true` asks for exactly the ONE node matching `at` rather
    than every child of it.
    """
    demand_started = time.monotonic()
    level = params.get("level")
    workspace_root = str(params.get("workspace_root", "."))
    at = params.get("at") if isinstance(params.get("at"), dict) else None
    seek = bool(params.get("seek", False))
    options = params.get("options") if isinstance(params.get("options"), dict) else {}
    audit_walk = options.get("auditFrontier") is True
    allowed_broken_components = options.get("allowedBrokenComponents", [])
    recovery_allowed = (
        audit_walk
        and isinstance(allowed_broken_components, list)
        and KIT_ID in allowed_broken_components
    )
    root = Path(workspace_root).resolve()
    _TRANSPORT_LOG.info(
        "enumeration_request",
        extra={
            "stage": "enumerate.request",
            "level_name": str(level),
            "at": at,
            "seek": seek,
        },
    )

    try:
        if level == "source_files":
            from sugar_lift_py_tests.canonicalizer import blake3_512_of

            nodes = []
            for full_path in _iter_python_files(workspace_root, ["."]):
                try:
                    rel_path = Path(full_path).resolve().relative_to(root).as_posix()
                except ValueError:
                    rel_path = Path(full_path).name
                file_bytes = Path(full_path).read_bytes()
                memento = _degenerate_file_memento(rel_path, blake3_512_of(file_bytes))
                if seek and at is not None and not _memento_matches(memento, at):
                    continue
                nodes.append({"memento": memento, "audit": None, "payload": None})
            _send_enumerate_result(msg_id, nodes, [])
            _log_enumeration_demand(
                str(level), at, cache="miss", started=demand_started
            )
            return

        if level in (
            "functions",
            "call_sites",
            "assertions",
            "facts",
            "universe",
            "implications",
        ):
            file_rel = _enumerate_file_of(at)
            if file_rel is None:
                _send_enumerate_result(
                    msg_id,
                    [],
                    [
                        {
                            "memento": at,
                            "reason": f"sugar.enumerate level={level!r} requires `at.file`",
                        }
                    ],
                )
                return
            full_path = root / file_rel
            # SECURITY (macroscope on #3862): a forged memento with an
            # absolute path (pathlib join discards root) or a ../ traversal
            # could enumerate files OUTSIDE the workspace. Require the
            # resolved path to stay under the resolved workspace root.
            resolved_root = root.resolve()
            resolved_full = full_path.resolve()
            if not (
                resolved_full == resolved_root or resolved_root in resolved_full.parents
            ):
                _send_enumerate_result(
                    msg_id,
                    [],
                    [
                        {
                            "memento": at,
                            "reason": (
                                "invalid: memento file escapes the workspace root "
                                f"({file_rel!r})"
                            ),
                        }
                    ],
                )
                return
            if not full_path.is_file():
                _send_enumerate_result(
                    msg_id,
                    [],
                    [{"memento": at, "reason": f"no such file: {file_rel}"}],
                )
                return
            if audit_walk and level == "functions":
                source_bytes = full_path.read_bytes()
                source = source_bytes.decode("utf-8")
                from sugar_lift_py_tests.canonicalizer import blake3_512_of

                file_cid = blake3_512_of(source_bytes)
                requested_cid = at.get("source_cid") if at else None
                if requested_cid and requested_cid != file_cid:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": "source memento CID no longer matches file",
                            }
                        ],
                    )
                    return
                context_hit = file_cid in _AUDIT_FILE_CONTEXTS
                context = _audit_file_context(
                    source,
                    file_rel,
                    file_cid,
                    hold_seed_panics=recovery_allowed,
                )
                nodes = []
                # The module owner exists only when the source has a statement
                # to own. Empty package markers are leaf files, so their
                # function-child answer is the empty set.
                if context.module.statements():
                    module_key = _degenerate_file_memento(file_rel, file_cid)
                    module_key["function_name"] = "<module>"
                    module_key["source_function_name"] = "<module>"
                    module_key["file_cid"] = file_cid
                    nodes.append(
                        {"memento": module_key, "audit": None, "payload": None}
                    )
                for definition in context.definitions:
                    key = to_rpc_value(definition.memento())
                    key["function_name"] = definition.function_name()
                    key["source_function_name"] = definition.function_name()
                    key["file_cid"] = file_cid
                    nodes.append({"memento": key, "audit": None, "payload": None})
                _send_enumerate_result(msg_id, nodes, [])
                _log_enumeration_demand(
                    str(level),
                    at,
                    cache="hit" if context_hit else "miss",
                    started=demand_started,
                )
                return
            if audit_walk and level == "facts":
                source_bytes = full_path.read_bytes()
                source = source_bytes.decode("utf-8")
                from sugar_lift_py_tests.canonicalizer import blake3_512_of

                actual_file_cid = blake3_512_of(source_bytes)
                requested_file_cid = at.get("file_cid")
                if requested_file_cid and requested_file_cid != actual_file_cid:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": "ancestor file CID no longer matches file",
                            }
                        ],
                    )
                    return
                file_cid = actual_file_cid
                context_hit = file_cid in _AUDIT_FILE_CONTEXTS
                context = _audit_file_context(
                    source,
                    file_rel,
                    file_cid,
                    hold_seed_panics=recovery_allowed,
                )
                from sugar_lift_py_tests.ir import term_intern_scope

                with term_intern_scope():
                    recovered = audit_lift_file(
                        source,
                        file_rel,
                        recover_panics=recovery_allowed,
                        target_memento=at,
                        audit_context=context,
                    )
                if not isinstance(recovered, RecoveredAuditDto):
                    raise TypeError("audit leaf returned a lift artifact")
                _send_enumerate_result(
                    msg_id,
                    [{"memento": at, "audit": recovered.to_rpc(), "payload": None}],
                    [],
                )
                _log_enumeration_demand(
                    str(level),
                    at,
                    cache="hit" if context_hit else "miss",
                    started=demand_started,
                )
                return
            ir_items, call_edges, term_table = _lift_file_for_enumeration(
                workspace_root, root, file_rel
            )

            if level == "functions":
                # A function gets a node either because it OWNS a
                # function-contract (kind="function-contract") or because it
                # merely ENCLOSES a call-site assertion (kind="contract",
                # whose memento's own source_function_name names its caller
                # -- e.g. a test function with no contract of its own but
                # real assertions inside it). Both are real functions in the
                # source; a driver walking source_files -> functions must be
                # able to reach either kind of call site underneath.
                # Dedup key is (name, span) so same-named nested functions with
                # distinct spans each get a node (self-locating SourceMemento).
                seen_keys: set = set()
                contract_names: set = set()
                for item in ir_items:
                    if item.get("kind") == "function-contract":
                        contract_names.add(item.get("name"))
                nodes = []

                def _fn_key(memento):
                    fn_name = (
                        memento.get("source_function_name")
                        or memento.get("sourceFunctionName")
                        or memento.get("function_name")
                    )
                    span = (
                        memento.get("span")
                        if isinstance(memento.get("span"), dict)
                        else {}
                    )
                    if _span_is_degenerate(span):
                        return (fn_name, None)
                    return (
                        fn_name,
                        (
                            span.get("start_line"),
                            span.get("start_col"),
                            span.get("end_line"),
                            span.get("end_col"),
                        ),
                    )

                def _emit(memento, audit):
                    key = _fn_key(memento)
                    if key[0] is None:
                        return
                    if key in seen_keys:
                        return
                    if seek and at is not None and not _memento_matches(memento, at):
                        return
                    seen_keys.add(key)
                    nodes.append({"memento": memento, "audit": audit, "payload": None})

                for item in ir_items:
                    if item.get("kind") != "function-contract":
                        continue
                    memento = _item_memento(item)
                    if memento is None:
                        continue
                    _emit(
                        memento,
                        {
                            "kind": item.get("kind"),
                            "name": item.get("name"),
                            "formals": item.get("formals"),
                            "bridgeSourceSymbol": item.get("bridgeSourceSymbol"),
                        },
                    )
                for item in ir_items:
                    if item.get("kind") != "contract":
                        continue
                    memento = _item_memento(item)
                    if memento is None:
                        continue
                    fn_name = memento.get("source_function_name") or memento.get(
                        "sourceFunctionName"
                    )
                    if not fn_name:
                        continue
                    if fn_name in contract_names:
                        # The function already owns a contract row; the
                        # enclosing-only fallback must not mint a duplicate.
                        continue
                    # Degenerate span: enclosing-only functions have no body
                    # contract locus; call_sites falls back to name scoping.
                    _emit(
                        {
                            "kind": "source-memento",
                            "file": file_rel,
                            "function_name": fn_name,
                            "source_function_name": fn_name,
                            "span": None,
                            "param_names": [],
                            "source_cid": None,
                            "template_cid": None,
                        },
                        {
                            "kind": "function",
                            "name": fn_name,
                            "note": "no function-contract of its own; reachable "
                            "because it encloses a call-site assertion",
                        },
                    )
                _send_enumerate_result(msg_id, nodes, [])
                return

            if level == "call_sites":
                # Scope under parent function (`at`): prefer SPAN containment when
                # `at.span` is non-degenerate (self-locating memento locus).
                # Fall back to function-name match when span is absent
                # (degenerate file/fn locators). Same-named nested functions with
                # distinct spans no longer cross-contaminate.
                target_fn = (
                    (
                        at.get("function_name")
                        or at.get("sourceFunctionName")
                        or at.get("source_function_name")
                    )
                    if at
                    else None
                )
                target_span = at.get("span") if isinstance(at, dict) else None
                built = []
                for item in ir_items:
                    if item.get("kind") != "contract":
                        continue
                    memento = _item_memento(item)
                    if memento is None:
                        continue
                    if not _call_site_under_function(memento, target_fn, target_span):
                        continue
                    if seek and at is not None and not _memento_matches(memento, at):
                        continue
                    # First-class bridge identity on the wire audit
                    # (`call:` / `method:` — prefix preserved from callEdges).
                    built.append(
                        {
                            "memento": memento,
                            "audit": _call_site_node_audit(
                                item, call_edges, term_table
                            ),
                            "payload": None,
                        }
                    )
                gaps = (
                    [
                        {
                            "memento": at,
                            "reason": "no call site for exact memento; refusing call-site substitution",
                        }
                    ]
                    if seek and at is not None and not built
                    else []
                )
                _send_enumerate_result(msg_id, built, gaps, term_tables=[term_table])
                return

            if level == "assertions":
                # Seek-only: a call site's own kind=contract item IS its
                # assertion. 1:1 is factory truth (batch IR has no dual
                # site/claim records) — protocol Section 4, not a collapse.
                # Same bridgeSourceSymbol stamp as call_sites.
                item = _find_item_by_memento(ir_items, at)
                if item is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [{"memento": at, "reason": "no call site for this memento"}],
                    )
                    return
                _send_enumerate_result(
                    msg_id,
                    [
                        {
                            "memento": _item_memento(item),
                            "audit": _call_site_node_audit(
                                item, call_edges, term_table
                            ),
                            "payload": None,
                        }
                    ],
                    [],
                    term_tables=[term_table],
                )
                return

            if level == "facts":
                item = _find_item_by_memento(ir_items, at)
                if item is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [{"memento": at, "reason": "no assertion for this memento"}],
                    )
                    return
                formula = _item_fact_formula(item)
                if formula is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": _item_memento(item),
                                "reason": "assertion carries no post/inv fact",
                            }
                        ],
                    )
                    return
                _send_enumerate_result(
                    msg_id,
                    [
                        {
                            "memento": _item_memento(item),
                            "audit": item,
                            "payload": formula,
                        }
                    ],
                    [],
                    term_tables=[term_table],
                )
                return

            if level == "implications":
                if at is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": "implications requires a call-site memento",
                            }
                        ],
                    )
                    return
                call_item = _find_item_by_memento(ir_items, at)
                if call_item is None or call_item.get("kind") != "contract":
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": "no call site for exact memento; refusing implication substitution",
                            }
                        ],
                    )
                    return
                _send_enumerate_result(
                    msg_id,
                    [
                        _implication_node_for_callsite(
                            at, ir_items, call_edges, term_table
                        )
                    ],
                    [],
                    term_tables=[term_table],
                )
                return

            if level == "universe":
                # Body/operator universes are `kind="function-contract"` rows
                # (including `len::builtin-universe`). CallSite::universe seeks
                # the universe linked to a call-site memento via
                # bridgeSourceSymbol / FOL callee identity. File-level scan
                # (`seek=false`) lists every universe in the file.
                universe_items = [
                    item
                    for item in ir_items
                    if isinstance(item, dict)
                    and item.get("kind") == "function-contract"
                ]

                if seek and at is not None:
                    # Call-site linkage path first: match a kind=contract
                    # assertion, then join on bridge identity.
                    #
                    # Dual-candidate (Task 9 / Important residual): try
                    # callEdges BSS first (`method:count`) and FOL
                    # `_contract_bridge_identity` second (`call:count`). A
                    # method site whose FOL ctor says `call:count` must still
                    # join a universe stamped `method:count` (and vice versa).
                    call_item = None
                    for item in ir_items:
                        if item.get("kind") != "contract":
                            continue
                        memento = _item_memento(item)
                        if memento is not None and _call_site_seek_matches(memento, at):
                            call_item = item
                            break
                    if call_item is not None:
                        candidates: List[str] = []
                        edge_sym = _edge_target_symbol_for_contract(
                            call_item, call_edges, term_table
                        )
                        if edge_sym is not None:
                            candidates.append(edge_sym)
                        fol_sym = _contract_bridge_identity(call_item, term_table)
                        if fol_sym is not None and fol_sym not in candidates:
                            candidates.append(fol_sym)
                        matches: Dict[tuple[Any, Any], tuple[Dict[str, Any], str]] = {}
                        for bridge in candidates:
                            for universe_item in universe_items:
                                if _universe_bridge_matches(
                                    universe_item.get("bridgeSourceSymbol"), bridge
                                ):
                                    memento = _item_memento(universe_item) or {}
                                    identity = (
                                        memento.get("source_cid")
                                        or memento.get("sourceCid"),
                                        universe_item.get("name")
                                        or universe_item.get("bridgeSourceSymbol"),
                                    )
                                    matches.setdefault(
                                        identity, (universe_item, bridge)
                                    )
                        if len(matches) == 1:
                            matched, resolved_bridge = next(iter(matches.values()))
                            _send_enumerate_result(
                                msg_id,
                                [
                                    _universe_node_from_item(
                                        matched,
                                        file_rel,
                                        resolved_bridge=resolved_bridge,
                                    )
                                ],
                                [],
                                term_tables=[term_table],
                            )
                            return
                        callee = candidates[0] if candidates else "unknown"
                        if len(matches) > 1:
                            qualified = sorted(
                                str(item.get("name") or item.get("bridgeSourceSymbol"))
                                for item, _ in matches.values()
                            )
                            _send_enumerate_result(
                                msg_id,
                                [],
                                [
                                    {
                                        "memento": at,
                                        "reason": (
                                            "ambiguous universe sugar for callee "
                                            f"{callee}; candidates=[{', '.join(qualified)}]"
                                        ),
                                    }
                                ],
                            )
                            return
                        _send_enumerate_result(
                            msg_id,
                            [],
                            [
                                {
                                    "memento": at,
                                    "reason": (
                                        f"no universe sugar for callee {callee}"
                                    ),
                                }
                            ],
                        )
                        return

                    # Direct universe seek (scan/seek coherence on a universe
                    # node's own memento, including the stamped name).
                    nodes = []
                    for universe_item in universe_items:
                        node = _universe_node_from_item(universe_item, file_rel)
                        if _memento_matches(node["memento"], at):
                            nodes.append(node)
                    gaps = (
                        []
                        if nodes
                        else [
                            {
                                "memento": at,
                                "reason": "no call site for exact memento; refusing universe substitution",
                            }
                        ]
                    )
                    _send_enumerate_result(
                        msg_id, nodes, gaps, term_tables=[term_table]
                    )
                    return

                # Scan: every function-contract universe in the file.
                nodes = [
                    _universe_node_from_item(universe_item, file_rel)
                    for universe_item in universe_items
                ]
                _send_enumerate_result(msg_id, nodes, [], term_tables=[term_table])
                return

        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32602,
                    "message": f"sugar.enumerate: unknown level {level!r}",
                },
            }
        )
    except Exception as exc:
        _TRANSPORT_LOG.exception(
            "enumeration_request_failed",
            extra={
                "stage": "enumerate.error",
                "level_name": str(level),
                "at": at,
                "seek": seek,
            },
        )
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
                "kit_source": kit_source_provenance(),
            },
        }
    )


def _handle_lift(msg_id: Any, params: Dict[str, Any]) -> None:
    workspace_root = str(params.get("workspace_root", "."))
    source_paths = list(params.get("source_paths", ["."]))
    contract_bindings = params.get("contract_bindings") or []
    if not isinstance(contract_bindings, list):
        contract_bindings = []
    options = params.get("options") if isinstance(params.get("options"), dict) else {}
    audit_frontier = options.get("auditFrontier") is True
    try:
        if audit_frontier:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": "auditFrontier is served only by recursive sugar.enumerate leaf requests",
                    },
                }
            )
            return
        payload = LiftReportPayloadDto(source_ledger={})
        bindings_backed_pass = bool(contract_bindings)
        root = Path(workspace_root).resolve()
        lifted_paths: List[Path] = []
        if not bindings_backed_pass:
            contracts, diagnostics = _source_lifter_function_contracts(workspace_root)
            payload.ir.extend(contracts)
            payload.diagnostics.extend(diagnostics)
        for file_index, path in enumerate(
            _iter_python_files(workspace_root, source_paths)
        ):
            full_path = Path(path)
            lifted_paths.append(full_path)
            try:
                rel_path = full_path.resolve().relative_to(root).as_posix()
            except ValueError:
                rel_path = full_path.name
            file_started = time.monotonic()
            _TRANSPORT_LOG.info(
                "workspace_file_enter",
                extra={
                    "stage": "lift.workspace.file",
                    "file": rel_path,
                    "index": file_index,
                },
            )
            with open(path, "r", encoding="utf-8") as handle:
                file_payload = lift_file_payload(handle.read(), rel_path)
            if bindings_backed_pass:
                # Implications are not projected from the collapse yet (named
                # gap). callEdges ride on the source-lifted path below.
                continue
            payload.ir.extend(file_payload.ir)
            _merge_symbol_kinds(payload.symbol_kinds, file_payload.symbol_kinds)
            payload.call_edges.extend(file_payload.call_edges)
            payload.factory_walk.extend(file_payload.factory_walk)
            payload.factory_audits.extend(file_payload.factory_audits)
            payload.source_mementos.extend(file_payload.source_mementos)
            _TRANSPORT_LOG.info(
                "workspace_file_exit",
                extra={
                    "stage": "lift.workspace.file",
                    "file": rel_path,
                    "index": file_index,
                    "contracts": len(payload.ir),
                    "elapsed_ms": round((time.monotonic() - file_started) * 1000, 3),
                },
            )
        rpc_started = time.monotonic()
        _TRANSPORT_LOG.info(
            "payload_to_rpc_enter",
            extra={
                "stage": "lift.workspace.to_rpc",
                "contracts": len(payload.ir),
            },
        )
        rpc_payload = payload.to_rpc()
        _TRANSPORT_LOG.info(
            "payload_to_rpc_exit",
            extra={
                "stage": "lift.workspace.to_rpc",
                "contracts": len(payload.ir),
                "elapsed_ms": round((time.monotonic() - rpc_started) * 1000, 3),
            },
        )
        # #4013: dual-axis lift coverage as first-class --report line items.
        # Independent AST census (second computation) vs this payload's accounting.
        # Serialize once through the payload-owned term-table door, then attach
        # the coverage computed from that exact wire projection.
        if not bindings_backed_pass and lifted_paths:
            coverage_started = time.monotonic()
            _TRANSPORT_LOG.info(
                "lift_coverage_enter",
                extra={
                    "stage": "lift.workspace.coverage",
                    "total": len(lifted_paths),
                },
            )
            coverage = _build_lift_coverage(
                root=root, paths=lifted_paths, payload_rpc=rpc_payload
            )
            rpc_payload["liftCoverage"] = coverage
            _TRANSPORT_LOG.info(
                "lift_coverage_exit",
                extra={
                    "stage": "lift.workspace.coverage",
                    "total": len(lifted_paths),
                    "elapsed_ms": round(
                        (time.monotonic() - coverage_started) * 1000, 3
                    ),
                },
            )
        _send({"jsonrpc": "2.0", "id": msg_id, "result": rpc_payload})
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


def _merge_source_ledger(
    current: Dict[str, int],
    incoming: Dict[str, int] | None,
) -> None:
    if incoming is None:
        return
    for key, value in incoming.items():
        current[key] = current.get(key, 0) + int(value)


def _merge_symbol_kinds(current: Dict[str, str], incoming: Dict[str, str]) -> None:
    from sugar_lift_py_tests.ir import merge_constructor_symbol_kind

    for symbol, kind in incoming.items():
        merge_constructor_symbol_kind(current, symbol, kind)


def _build_lift_coverage(
    *,
    root: Path,
    paths: List[Path],
    payload_rpc: Dict[str, Any],
) -> Dict[str, Any]:
    """Independent AST census + partition vs the just-built lift payload.

    Assertions (default report body): silently_unaccounted is the RED gate.
    Minority (bodies): un_asserted is the VISIBLE scope remainder (not red).
    """
    started = time.monotonic()
    _TRANSPORT_LOG.info(
        "coverage_census_enter",
        extra={"stage": "lift.coverage.census_paths", "total": len(paths)},
    )
    disk = census_paths(paths, root=root)
    _TRANSPORT_LOG.info(
        "coverage_census_exit",
        extra={
            "stage": "lift.coverage.census_paths",
            "total": len(paths),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        },
    )
    # Account against the same RPC shape the report serializes — built without
    # liftCoverage to avoid self-reference (coverage is the field being filled).
    started = time.monotonic()
    _TRANSPORT_LOG.info(
        "coverage_projection_enter",
        extra={
            "stage": "lift.coverage.payload_projection",
            "contracts": len(payload_rpc.get("ir", [])),
        },
    )
    interim = {
        "sourceAudits": payload_rpc.get("sourceAudits", []),
        "sourceMementos": payload_rpc.get("sourceMementos", []),
        "assertionSurfaceAudits": payload_rpc.get("assertionSurfaceAudits", []),
        "diagnostics": payload_rpc.get("diagnostics", []),
        "sourceLedger": payload_rpc.get("sourceLedger", {}),
        # Minority projection joins function-contract rows to call_edges.
        "ir": payload_rpc.get("ir", []),
        "callEdges": payload_rpc.get("callEdges", []),
        # Doctrine: factory instrument engagement must be visible to coverage
        # accounting so unimplemented becomes a loud gap, never silent (#4016).
        "factoryAuditSummary": payload_rpc.get("factoryAuditSummary", {}),
        "factoryAudits": payload_rpc.get("factoryAudits", []),
    }
    _TRANSPORT_LOG.info(
        "coverage_projection_exit",
        extra={
            "stage": "lift.coverage.payload_projection",
            "contracts": len(payload_rpc.get("ir", [])),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        },
    )
    started = time.monotonic()
    _TRANSPORT_LOG.info(
        "coverage_account_enter", extra={"stage": "lift.coverage.account"}
    )
    coverage = account_lift_coverage(disk, interim)
    body = coverage.to_json()
    _TRANSPORT_LOG.info(
        "coverage_account_exit",
        extra={
            "stage": "lift.coverage.account",
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        },
    )
    # Per-file line paint for --visual consumers.
    paints: Dict[str, Any] = {}
    paint_started = time.monotonic()
    _TRANSPORT_LOG.info(
        "coverage_paint_enter",
        extra={"stage": "lift.coverage.paint_lines", "total": len(paths)},
    )
    for path_index, path in enumerate(paths):
        path = path.resolve()
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.name
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        paints[rel] = paint_lines(source, coverage, file=rel)
        _TRANSPORT_LOG.info(
            "coverage_paint_file",
            extra={
                "stage": "lift.coverage.paint_lines",
                "file": rel,
                "index": path_index,
                "total": len(paths),
            },
        )
    body["line_paint"] = paints
    _TRANSPORT_LOG.info(
        "coverage_paint_exit",
        extra={
            "stage": "lift.coverage.paint_lines",
            "total": len(paths),
            "elapsed_ms": round((time.monotonic() - paint_started) * 1000, 3),
        },
    )
    return body


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
            cid = cid_from_proof_stem(stem) or stem
            proofs.append(
                {
                    "cid": cid,
                    "bytes_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "source": f"sugar-imports:{path.name}",
                }
            )
    _send({"jsonrpc": "2.0", "id": msg_id, "result": {"proofs": proofs}})


def _dispatch_request(msg: Dict[str, Any]) -> bool:
    """Dispatch one accepted request; return whether the session should continue."""
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
        )
    elif method == "sugar.plugin.lift_implications":
        _handle_lift(
            msg_id,
            params if isinstance(params, dict) else {},
        )
    elif method == "sugar.plugin.resolve_dependency_proofs":
        _handle_resolve_dependency_proofs(
            msg_id, params if isinstance(params, dict) else {}
        )
    elif method == ENUMERATE_RPC_METHOD:
        _handle_enumerate(msg_id, params if isinstance(params, dict) else {})
    elif method == "shutdown":
        _send({"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True}})
        return False
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
    return True


def _serve() -> None:
    request_count = 0
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
        request_count += 1
        try:
            keep_serving = _dispatch_request(msg)
        except RecursionError:
            # Loud and typed: the request is rejected with an error frame; the
            # transport stays alive for the next request.
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {
                        "code": -32603,
                        "message": (
                            "recursion limit exceeded while serving request: "
                            "input nests deeper than the lifter's bounded "
                            "recursion depth"
                        ),
                        "data": {
                            "exception_type": "RecursionError",
                            "stage": "dispatch",
                        },
                    },
                }
            )
            _log_resident_profile(request_count, msg.get("method"))
            continue
        except FactoryPanic as panic:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {
                        "code": -32603,
                        "message": str(panic),
                        "data": {
                            "exception_type": type(panic).__name__,
                            "stage": "dispatch",
                            "diagnostic": panic.info.to_json(),
                        },
                    },
                }
            )
            _log_resident_profile(request_count, msg.get("method"))
            raise SystemExit(1) from panic
        _log_resident_profile(request_count, msg.get("method"))
        if not keep_serving:
            break


def main(argv: Optional[List[str]] = None) -> None:
    _configure_transport_logging()
    if _profile_interval("SUGAR_KIT_PROFILE_EVERY") > 0:
        tracemalloc.start(1)
    argv = argv or []
    if "--audit-only" in argv:
        raise SystemExit(
            "--audit-only no longer enables construction-gap recovery; "
            "use sugar lift --audit-frontier --allowed-broken-components python"
        )
    _serve()


if __name__ == "__main__":
    main(sys.argv[1:])
