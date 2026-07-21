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
    EffectDto,
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
_ENUMERATION_PHASES: Dict[str, tuple[int, float, float]] = {}
_ENUMERATION_REQUEST_COUNT = 0
_ENUMERATION_ACTIVE = False
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
            "phase",
            "phase_count",
            "phase_total_ms",
            "phase_mean_ms",
            "phase_max_ms",
            "rss_before_kib",
            "rss_after_kib",
            "error",
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


def _observe_enumeration_phase(phase: str, elapsed_ms: float) -> None:
    count, total_ms, max_ms = _ENUMERATION_PHASES.get(phase, (0, 0.0, 0.0))
    _ENUMERATION_PHASES[phase] = (
        count + 1,
        total_ms + elapsed_ms,
        max(max_ms, elapsed_ms),
    )


def _enumeration_phase_snapshot() -> list[dict[str, Any]]:
    rows = []
    for phase, (count, total_ms, max_ms) in _ENUMERATION_PHASES.items():
        rows.append(
            {
                "phase": phase,
                "phase_count": count,
                "phase_total_ms": round(total_ms, 3),
                "phase_mean_ms": round(total_ms / count, 3),
                "phase_max_ms": round(max_ms, 3),
            }
        )
    return sorted(rows, key=lambda row: row["phase_total_ms"], reverse=True)


def _log_enumeration_phase_profile(request_count: int) -> None:
    every = _profile_interval("SUGAR_KIT_PROFILE_EVERY")
    if every <= 0 or request_count % every:
        return
    for row in _enumeration_phase_snapshot():
        _TRANSPORT_LOG.info(
            "enumeration_phase_profile",
            extra={
                "stage": "enumerate.phase_profile",
                "request_count": request_count,
                **row,
            },
        )


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
    every = _profile_interval("SUGAR_KIT_MEMORY_PROFILE_EVERY")
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


_MALLOC_TRIM: Any = None


def _malloc_trim() -> bool:
    """Return freed glibc arenas to the OS. False where unavailable (e.g. musl,
    macOS); resolved once and cached."""
    global _MALLOC_TRIM
    if _MALLOC_TRIM is None:
        try:
            import ctypes
            import ctypes.util

            libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
            _MALLOC_TRIM = libc.malloc_trim
        except (OSError, AttributeError):
            _MALLOC_TRIM = False
    if not _MALLOC_TRIM:
        return False
    try:
        _MALLOC_TRIM(0)
        return True
    except OSError as exc:  # never crash the plugin, but surface the anomaly
        _TRANSPORT_LOG.warning(
            "malloc_trim_failed",
            extra={"stage": "resident.trim", "error": repr(exc)},
        )
        return False


def _maybe_trim_resident(request_count: int) -> None:
    """Hand freed arenas back to the OS on a fixed request cadence.

    A long wall run parses hundreds of thousands of tiny AST nodes per file;
    when freed, glibc keeps the arenas, so RSS ratchets even though the live
    object set stays modest. A periodic gc.collect() + malloc_trim(0) returns
    that transient memory. Gated (default off) so ordinary lifting pays nothing;
    the wall workflows opt in via SUGAR_KIT_TRIM_EVERY. This bounds the
    arena-fragmentation component of resident growth only -- it does not release
    memory pinned by live references (see #4584 profiling notes)."""
    every = _profile_interval("SUGAR_KIT_TRIM_EVERY")
    if every <= 0 or request_count % every:
        return
    rss_before, _ = _resident_rss_kib()
    gc.collect()
    if not _malloc_trim():
        return
    rss_after, _ = _resident_rss_kib()
    _TRANSPORT_LOG.info(
        "resident_trim",
        extra={
            "stage": "resident.trim",
            "request_count": request_count,
            "rss_before_kib": rss_before,
            "rss_after_kib": rss_after,
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
    scrub_ms = (time.monotonic() - started) * 1000
    if _ENUMERATION_ACTIVE:
        _observe_enumeration_phase("response.scrub", scrub_ms)
    _TRANSPORT_LOG.info(
        "response_scrub_exit",
        extra={
            "stage": "response.scrub",
            "elapsed_ms": round(scrub_ms, 3),
        },
    )
    started = time.monotonic()
    _TRANSPORT_LOG.info("response_encode_enter", extra={"stage": "response.json.dumps"})
    frame = json.dumps(safe, separators=(",", ":")) + "\n"
    encode_ms = (time.monotonic() - started) * 1000
    if _ENUMERATION_ACTIVE:
        _observe_enumeration_phase("response.encode", encode_ms)
    _TRANSPORT_LOG.info(
        "response_encode_exit",
        extra={
            "stage": "response.json.dumps",
            "elapsed_ms": round(encode_ms, 3),
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


def _module_import_temporal(
    module,
    catalog,
    *,
    filename=None,
    recovered_panics=None,
    assertion_sink=None,
    definition_temporal_sink=None,
) -> "object":
    """Bind constructed module declarations into a TemporalContext.

    Deeper floors: names introduced by ``import pytest`` / ``from x import Y``
    must stand when reducing function bodies. Without this, TemporalContext
    panics on unbound import names even though the source stated the import.
    Imports use the same ``ImportAliasValue`` constructed by ``AliasSugar``.
    A valued single-name Assign or AnnAssign uses the same factory-built
    ``BoundVar`` representation as ``StatementFunctionDefSugar.module_context_for``. Multi-target
    / tuple-unpack Assign reduces through the same factory door
    (``TupleUnpackAssignSugar`` and siblings) so leaf names like ``START``/``END``
    stand for later NameSugar. Each assignment is independent: an unowned or
    runtime-effect RHS stays unbound without poisoning siblings.
    Annotation-only declarations bind nothing.

    Module-level ``try`` / ``except`` declarations (optional imports that bind
    the same name on both faces) reduce through ordinary TrySugar so continuing
    path joins seed ``GuardedValue`` bindings. Skipping Try left names like
    ``charset_normalizer`` unbound and panicked later NameSugar reductions.
    """
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
    from sugar_lift_py_tests.floor import (
        BlockValue,
        ClassValue,
        ImportAliasValue,
        StringValue,
    )
    from sugar_lift_py_tests.floor.local_exception_class_value import (
        module_class_value,
    )
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.temporal import TemporalContext

    temporal = (
        TemporalContext.empty()
        .bind_value("__file__", StringValue(filename or module.filename))
        .bind_value(
            "__builtins__",
            ImportAliasValue(
                name="builtins",
                bound_name="__builtins__",
                import_target="builtins",
            ),
        )
    )
    # Same ClassDef enrollment as audit_context name_resolver: without bare
    # class nodes, module-seed FunctionCallable dig bodies fall ConstructorCallSugar
    # → opaque CallSugar for `Box()`, so dunder bridges never attach method bodies
    # and Derived EUF residue soft-SATs (#4387 builtin_dunder_hash / divmod).
    module_function_resolver: dict[str, Any] = {
        stmt.function_name(): stmt.node
        for stmt in module.statements()
        if stmt.observed == "FunctionDef"
    }
    for stmt in module.statements():
        if stmt.observed != "ClassDef":
            continue
        cname = stmt.class_name()
        module_function_resolver[cname] = stmt.node
        for body_stmt in stmt.class_body():
            if body_stmt.observed == "FunctionDef":
                module_function_resolver[f"{cname}.{body_stmt.function_name()}"] = (
                    body_stmt.node
                )
            elif body_stmt.observed == "ClassDef":
                nested = body_stmt.class_name()
                module_function_resolver[nested] = body_stmt.node
                for nested_stmt in body_stmt.class_body():
                    if nested_stmt.observed == "FunctionDef":
                        module_function_resolver[
                            f"{nested}.{nested_stmt.function_name()}"
                        ] = nested_stmt.node
    for stmt in module.statements():
        observed = stmt.observed
        if definition_temporal_sink is not None and observed in {
            "FunctionDef",
            "AsyncFunctionDef",
        }:
            # Python constructs decorators/defaults at this exact execution
            # coordinate. Preserve the factory-threaded prefix; a later module
            # binding may serve the deferred body, but must never backfill an
            # eager definition face.
            definition_temporal_sink[id(stmt.node)] = temporal
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
                # Absolute-ize relative imports the same way `_module_import_maps`
                # does, so install-source dig can resolve package exceptions to
                # ExceptionClassValue (e.g. `from .exceptions import InvalidURL`).
                mod = stmt.importfrom_module() or ""
                level = stmt.importfrom_level()
                if level and stmt.filename is not None:
                    defining_module = _installed_module_name_from_filename(
                        stmt.filename
                    )
                    if defining_module is not None:
                        from sugar_lift_py_tests.sugar.install_source_dig import (
                            _absolute_import_from_module,
                        )

                        mod = (
                            _absolute_import_from_module(
                                defining_module, mod or None, level
                            )
                            or mod
                        )
                import_target = f"{mod}.{name}" if mod else name
                import_ctx = FactoryBuildContext(
                    filename=stmt.filename,
                    catalog=catalog,
                    temporal=temporal,
                    module_temporal=temporal,
                )
                temporal = temporal.bind_value(
                    bound,
                    ImportAliasValue(
                        name,
                        bound,
                        import_target=import_target,
                        install_source_checked=True,
                        install_source_context=import_ctx,
                    ),
                )
        elif observed == "ClassDef":
            name = stmt.class_name()
            temporal = temporal.bind_value(
                name,
                module_class_value(
                    name=name,
                    base_names=tuple(
                        base.name_id()
                        for base in stmt.class_bases()
                        if base.observed == "Name"
                    ),
                    temporal=temporal,
                    record=BlockValue(()),
                ),
            )
        elif observed == "Try":
            # Optional-import / continuing-path joins: reduce TrySugar and
            # extend temporal with ScopeRebind faces (often GuardedValue).
            # Construct-or-panic — never invent a None-only or import-only face.
            ctx = FactoryBuildContext(
                filename=stmt.filename,
                catalog=catalog,
                temporal=temporal,
                module_temporal=temporal,
                name_resolver=module_function_resolver,
                defer_function_body_construction=True,
            )
            # FactoryPanic propagates (#5238); no seed soft-continue.
            outcome = ctx.build_body(stmt, SugarRole.STATEMENT).reduce(ctx)
            if isinstance(outcome, Incomplete):
                continue
            temporal = outcome.extend_scope(ctx).temporal
        elif observed == "FunctionDef":
            ctx = FactoryBuildContext(
                filename=stmt.filename,
                catalog=catalog,
                temporal=temporal,
                module_temporal=temporal,
                name_resolver=module_function_resolver,
                defer_function_body_construction=True,
            )
            # FunctionDef owns body panics; seed must not swallow them (#5238).
            callable_value = ctx.build_body(stmt, SugarRole.STATEMENT).reduce(ctx)
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
                outcome = ctx.build_body(stmt, SugarRole.STATEMENT).reduce(ctx)
                if isinstance(outcome, Incomplete):
                    continue
                if assertion_sink is not None:
                    assertion_sink.extend(outcome.contribution())
                temporal = outcome.extend_scope(ctx).temporal
                continue
            if observed == "Assign":
                # Single-name Assign uses assign_target_name. Multi-target /
                # tuple-unpack Assign returns None for that helper, but
                # TupleUnpackAssignSugar (and siblings) still own the shape and
                # bind every leaf name through ordinary reduction. Skipping the
                # multi-target door left module unpacks like `START, END = …`
                # unbound for later NameSugar — a TemporalContext residual that
                # was already constructed correctly inside function bodies.
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
            # #5238: FactoryPanic is process-terminal; no seed recovery soft path.
            # Incomplete leaves the binding unbound without inventing a value.
            outcome = ctx.build_body(stmt, SugarRole.STATEMENT).reduce(ctx)
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
            # class body may contain methods and nested classes.
            # #4203: class_body is total for ClassDef; soft Exception continue
            # hid nested methods from the recovered frontier (false-clean file).
            stack[0:0] = list(stmt.class_body())


def _module_import_maps(module, filename: str | None = None) -> "tuple[dict, dict]":
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
            level = stmt.importfrom_level()
            if level and filename is not None:
                defining_module = _installed_module_name_from_filename(filename)
                if defining_module is not None:
                    from sugar_lift_py_tests.sugar.install_source_dig import (
                        _absolute_import_from_module,
                    )

                    mod = (
                        _absolute_import_from_module(
                            defining_module, mod or None, level
                        )
                        or mod
                    )
            for name, asname in stmt.importfrom_names():
                if name == "*":
                    continue
                bound = asname or name
                from_imports[bound] = (mod, name)
    return import_aliases, from_imports


def _installed_module_name_from_filename(filename: str) -> str | None:
    """Derive a dotted module only when package boundaries are evidenced."""
    path = Path(filename)
    parts = path.with_suffix("").parts
    for marker in ("site-packages", "dist-packages"):
        if marker in parts:
            suffix = list(parts[parts.index(marker) + 1 :])
            if suffix and suffix[-1] == "__init__":
                suffix.pop()
            return ".".join(suffix) or None
    if not path.is_absolute() and len(parts) > 1:
        relative = list(parts)
        if relative[-1] == "__init__":
            relative.pop()
        return ".".join(relative) or None

    # Local exact sources can prove their package chain with __init__.py files.
    package: list[str] = []
    parent = path.parent
    while (parent / "__init__.py").is_file():
        package.append(parent.name)
        parent = parent.parent
    if not package:
        return None
    package.reverse()
    if path.stem != "__init__":
        package.append(path.stem)
    return ".".join(package)


def _module_spelling_from_filename(filename: str) -> str:
    """Module path spelling for a source file (package parts + stem)."""
    module_parts = list(Path(filename).with_suffix("").parts)
    if module_parts and module_parts[-1] == "__init__":
        module_parts.pop()
    return ".".join(part for part in module_parts if part not in ("", "."))


def _qualified_callable_spelling(
    filename: str,
    callable_name: str,
    *,
    relative_to_module: bool = False,
) -> str:
    """Content-independent callable spelling rooted at its Python module.

    `relative_to_module=True` means `callable_name` is a path relative to the
    module (bare def leaf or `Class.method` / `Outer.Inner.method`). The module
    root is always applied. This is load-bearing when a class stem equals the
    module stem: class `datetime` in `datetime.py` must become
    `datetime.datetime._cmp`, never collapse onto module-level `datetime._cmp`
    via a false "already module-qualified" short-circuit (#4325).
    """
    module = _module_spelling_from_filename(filename)
    if not module:
        return callable_name
    if relative_to_module:
        if not callable_name or callable_name == module:
            return module
        return f"{module}.{callable_name}"
    if callable_name == module or callable_name.startswith(f"{module}."):
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
    definition_temporals: dict[int, Any]
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
_AUDIT_FILE_CONTEXTS: collections.OrderedDict[tuple[str, str], _AuditFileContext] = (
    collections.OrderedDict()
)


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


def _factory_walk_red_from_gap(
    gap: AuditOnlyGap,
    *,
    recovered_owner_span: tuple[int, int] | None = None,
):
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
    extra = {
        "candidates": list(audit.candidates),
        "blame": blame,
        "gap_kind": str(gap.info.get("gap_kind") or ""),
        "gap_locus": str(gap.info.get("gap_locus") or ""),
        # Recognition outcome already computed for this callee's gap, when
        # the producer computes one (#5252/#5913 audit). Empty when the
        # producer (e.g. conservation violations) has no callee to classify.
        "resolution_kind": str(gap.info.get("resolution_kind") or ""),
    }
    if recovered_owner_span is not None:
        extra.update(
            {
                "reportRecoveredPanic": True,
                "recoveredOwnerStartLine": recovered_owner_span[0],
                "recoveredOwnerEndLine": recovered_owner_span[1],
            }
        )
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
        extra=extra,
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
    # The audit frontier's factory census is deleted; auditFrontier now short-
    # circuits to an empty frontier (its R census re-homes onto the source
    # tree's reporter channel, not yet wired). allowedBrokenComponents was the
    # factory's panic-recovery gate; with no factory audit walk it is inert.
    audit_walk = options.get("auditFrontier") is True
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
            # The source_files level IS SourceTree.fragments(): whole-file
            # fragments minted through the SourceOracle — identity without
            # parsing, no file read or hashed outside the oracle. The handler
            # only formats. An unreadable/undecodable file is a loud oracle
            # refusal recorded as a protocol gap, never served as a node
            # (previously it was hashed raw and masqueraded as enumerable).
            from sugar_lift_python_source.source_oracle import SourceOracleRefusal
            from sugar_source_tree.tree import SourceTree

            nodes = []
            gaps = []
            tree = SourceTree(root)
            for path in tree.paths():
                try:
                    rel_path = path.resolve().relative_to(root).as_posix()
                except ValueError:
                    rel_path = path.name
                try:
                    fragment = tree.fragment_of(path)
                except SourceOracleRefusal as refusal:
                    gaps.append(
                        {
                            "memento": _degenerate_file_memento(rel_path),
                            "reason": str(refusal),
                        }
                    )
                    continue
                memento = _degenerate_file_memento(rel_path, fragment.source_cid)
                if seek and at is not None and not _memento_matches(memento, at):
                    continue
                nodes.append({"memento": memento, "audit": None, "payload": None})
            _send_enumerate_result(msg_id, nodes, gaps)
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

            if audit_walk:
                # The recovered-construction frontier, re-homed onto the tree
                # (the factory census is gone). The Rust driver walks
                # source_files -> functions -> facts; we serve it at MODULE
                # granularity: one demanded body per file whose audit leaf
                # walks the whole file with a CollectingReporter. Every node
                # whose own sugar() reaches the base throw self-reports; that
                # count IS R. status is `failed` when the file has any unwritten
                # sugar, `clean` when fully sugared -- no false green.
                from sugar_lift_py_tests import tree_enumerate as _tree
                from sugar_lift_python_source.source_oracle import (
                    SourceOracleRefusal,
                    path_source,
                )

                if level == "functions":
                    try:
                        identity = path_source(str(full_path))
                    except SourceOracleRefusal as refusal:
                        _send_enumerate_result(
                            msg_id, [], [{"memento": at, "reason": str(refusal)}]
                        )
                        return
                    _src, _fname, file_cid = identity
                    sf = _tree.source_file(full_path)
                    memento = _tree.module_definition_memento(
                        sf, file_rel, file_cid
                    )
                    _send_enumerate_result(
                        msg_id,
                        [{"memento": memento, "audit": None, "payload": None}],
                        [],
                    )
                    _log_enumeration_demand(
                        str(level), at, cache="miss", started=demand_started
                    )
                    return

                if level == "facts":
                    leaf = _tree.frontier_leaf_rpc(full_path, file_rel)
                    _send_enumerate_result(
                        msg_id,
                        [{"memento": at, "audit": leaf, "payload": None}],
                        [],
                    )
                    _log_enumeration_demand(
                        str(level), at, cache="miss", started=demand_started
                    )
                    return

                # No other level participates in the frontier walk.
                _send_enumerate_result(msg_id, [], [])
                _log_enumeration_demand(
                    str(level), at, cache="miss", started=demand_started
                )
                return

            if level == "functions":
                # The functions level IS SourceFile.functions(): every function
                # definition in the file, enumerated from the typed tree over
                # oracle-pinned text. No lift runs, no IR rows are consulted,
                # and nothing is reconstructed: the ~100 lines of dedup keys,
                # contract-name sets, and enclosing-only fallback mementos this
                # replaces existed only because the factory threw the tree away
                # and the wire had to rebuild syntax from lift output.
                #
                # Classes are namespaces: enumeration is transitive through
                # class bodies, so test methods are functions here, in source
                # order. Every function is visible — one with no testimony
                # simply answers empty at the deeper levels. The `audit`
                # annotation (contract name, formals) is meaning and arrives
                # when FunctionDef.sugar() is written; syntax does not wait
                # for it.
                from sugar_lift_python_source.source_oracle import (
                    SourceOracleRefusal,
                    path_source,
                )
                from sugar_source_tree.tree import SourceFile as _TreeSourceFile

                try:
                    identity = path_source(str(full_path))
                except SourceOracleRefusal as refusal:
                    _send_enumerate_result(
                        msg_id, [], [{"memento": at, "reason": str(refusal)}]
                    )
                    return
                _source, _fname, file_cid = identity
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
                tree_file = _TreeSourceFile(identity)
                nodes = []
                for fn in tree_file.functions():
                    lc = fn.line_col_span()
                    sealed = fn.fragment.seal()
                    memento = {
                        "kind": "source-memento",
                        "file": file_rel,
                        "function_name": fn.name,
                        "source_function_name": fn.name,
                        "span": {
                            "start_line": lc.start_line,
                            "start_col": lc.start_col,
                            "end_line": lc.end_line,
                            "end_col": lc.end_col,
                        },
                        "source_cid": sealed.cid,
                        "file_cid": file_cid,
                        "template_cid": None,
                        "param_names": [],
                    }
                    if seek and at is not None and not _memento_matches(memento, at):
                        continue
                    nodes.append({"memento": memento, "audit": None, "payload": None})
                _send_enumerate_result(msg_id, nodes, [])
                _log_enumeration_demand(
                    str(level), at, cache="miss", started=demand_started
                )
                return
            # Levels below `functions` served by the AST tree, not the factory.
            # Invoking the RPC is invoking the source tree enumeration: walk the
            # function's Assert nodes and ask each for its sugar and its fact.
            # For a bare `assert`, call_site and assertion are the same locus
            # (1:1, protocol Section 4); the fact is the desugared InvValue.
            # (audit_walk already returned empty above; this is the live path.)
            if level == "implications":
                # The linker question, served from the tree: this caller's INV
                # against the callee contract(s) its call site CUES, joined by
                # the callEdge. The kit describes the demand; it never answers it
                # (the discharge is the linker's, the other side of the RPC).
                # Digs cue digs: the callee's own universe post carries its own
                # call coordinates, which become the next implications.
                from sugar_lift_py_tests import tree_enumerate as _tree
                from sugar_lift_py_tests.ir import TermTableBuilder
                from sugar_lift_py_tests.outcome import Complete

                if at is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [{"memento": at, "reason": "implications requires a call-site memento"}],
                    )
                    return
                sf = _tree.source_file(full_path)
                span = at.get("span") if isinstance(at, dict) else None
                source_assert, assert_node = _tree.temporally_rewritten_assert(
                    sf, span
                )
                if source_assert is None or assert_node is None:
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

                term_table = TermTableBuilder()
                caller_memento = _tree.assert_memento(source_assert, file_rel)
                caller_cid = caller_memento["source_cid"]
                caller_post = None
                caller_outcome = assert_node.sugar().desugar(None)
                if isinstance(caller_outcome, Complete):
                    formula = getattr(caller_outcome.value, "formula", None)
                    if formula is not None:
                        caller_post = term_table.formula(formula)

                target_candidates = []
                targets = _tree.call_target_names(sf, span)
                for name in targets:
                    fn = _tree.find_function_by_name(sf, name)
                    if fn is None:
                        continue
                    try:
                        def_memento, rows = _tree.function_contract_rows(fn, file_rel)
                    except Exception:
                        continue
                    if rows is None:
                        continue
                    post = rows[0].post
                    target_candidates.append(
                        {
                            "bridgeSourceSymbol": f"call:{name}",
                            "contract": {
                                "name": name,
                                "kit": "python-source",
                                "contract_cid": def_memento.source_cid,
                                "pre_json": None,
                                "post_json": (
                                    term_table.formula(post.ir_formula)
                                    if post is not None
                                    else None
                                ),
                            },
                        }
                    )

                target_symbol = f"call:{targets[0]}" if targets else "unknown"
                sp = span if isinstance(span, dict) else {}
                demand = {
                    "sourceContract": {
                        "name": "",
                        "kit": "python-source",
                        "contract_cid": caller_cid,
                        "pre_json": None,
                        "post_json": caller_post,
                    },
                    "targetCandidates": target_candidates,
                    "callEdge": {
                        "source_contract_cid": caller_cid,
                        "target_contract_cid": None,
                        "target_symbol": target_symbol,
                        "call_site_locus": {
                            "file": file_rel,
                            "line": sp.get("start_line"),
                            "column": sp.get("start_col"),
                        },
                    },
                }
                node = {
                    "memento": at,
                    "audit": {
                        "kind": "implication-question",
                        "sourceContract": "",
                        "targetSymbol": target_symbol,
                        "candidateCount": len(target_candidates),
                        "callSiteMemento": at,
                    },
                    "payload": demand,
                }
                _send_enumerate_result(
                    msg_id, [node], [], term_tables=[term_table.nodes]
                )
                _log_enumeration_demand(
                    str(level), at, cache="miss", started=demand_started
                )
                return

            if level == "universe":
                # The callee contract, served from the tree. Each function's
                # FunctionDef.sugar() reduces to a UniverseValue whose
                # payload_rows project the function-contract DTO (post + invs) --
                # the dig RESULT. Callee resolution is by NAME, directly: a
                # call-site cue (`at` on a call site) resolves to the function
                # whose name the call names, no bridge-matching. Three modes:
                # file scan (seek=false), a universe's own memento, or a
                # call-site cue.
                from sugar_lift_py_tests import tree_enumerate as _tree
                from sugar_lift_py_tests.ir import TermTableBuilder
                from sugar_source_tree.panic import SugarNotWritten

                sf = _tree.source_file(full_path)
                term_table = TermTableBuilder()
                universes = []  # (name, memento_dict, contract_dto)
                gaps = []
                for fn in sf.functions():
                    try:
                        def_memento, rows = _tree.function_contract_rows(fn, file_rel)
                    except SugarNotWritten as gap:
                        gaps.append(
                            {
                                "memento": _tree.function_def_memento(
                                    fn, file_rel
                                ).to_rpc(),
                                "reason": gap.observed,
                            }
                        )
                        continue
                    if rows is None:
                        continue  # an effect, not a contract
                    universes.append((fn.name, def_memento.to_rpc(), rows[0]))

                def _node(memento, dto):
                    return {
                        "memento": memento,
                        "audit": dto.to_rpc_with_term_table(term_table),
                        "payload": None,
                    }

                if not (seek and at is not None):
                    nodes = [_node(m, d) for _n, m, d in universes]
                    _send_enumerate_result(
                        msg_id, nodes, gaps, term_tables=[term_table.nodes]
                    )
                    _log_enumeration_demand(
                        str(level), at, cache="miss", started=demand_started
                    )
                    return

                # seek: a universe's own memento, else a call-site cue -> callee.
                direct = [
                    _node(m, d) for _n, m, d in universes if _memento_matches(m, at)
                ]
                if direct:
                    _send_enumerate_result(
                        msg_id, direct, [], term_tables=[term_table.nodes]
                    )
                    return
                calls = _tree.call_nodes_in_assert(
                    sf, at.get("span") if isinstance(at, dict) else None
                )
                targets = []
                by_name = {name: (m, d) for name, m, d in universes}
                cued = []
                seen = set()
                for call in calls:
                    t = call.func.id
                    if t in seen:
                        continue
                    seen.add(t)
                    targets.append(t)
                    fn = _tree.find_function_by_name(sf, t)
                    # A call IS substitution: ground args fill the pre, so the
                    # dig serves the contract AS APPLIED at this call (a concrete
                    # iterable unrolls the callee's loop here; the fold
                    # coordinate collapses; a symbolic while's condition grounds
                    # and unrolls). An arg still carrying a hole leaves the
                    # abstract contract standing -- the callable floor. The
                    # applied dig is attempted even when the ABSTRACT universe is
                    # a gap: the applied substitution can succeed exactly where
                    # the abstract is still a hole (that is the whole point of
                    # filling the pre).
                    if (
                        fn is not None
                        and len(call.args) == len(fn.params)
                        and _tree._args_are_ground(call)
                    ):
                        try:
                            memento, rows = _tree.applied_contract_rows(
                                fn, tuple(call.args), file_rel
                            )
                        except SugarNotWritten:
                            rows = None
                        if rows:
                            cued.append(_node(memento.to_rpc(), rows[0]))
                            continue
                    if t in by_name:
                        cued.append(_node(*by_name[t]))
                _send_enumerate_result(
                    msg_id,
                    cued,
                    []
                    if cued
                    else [
                        {
                            "memento": at,
                            "reason": (
                                "no universe for the callee(s) this call site cues: "
                                f"{targets or 'none'}"
                            ),
                        }
                    ],
                    term_tables=[term_table.nodes],
                )
                _log_enumeration_demand(
                    str(level), at, cache="miss", started=demand_started
                )
                return

            if level in ("call_sites", "assertions", "facts"):
                from sugar_lift_py_tests import tree_enumerate as _tree

                sf = _tree.source_file(full_path)

                if level in ("call_sites", "assertions"):
                    # at is the parent function (scan) — enumerate its assertions.
                    fn = _tree.find_function(
                        sf,
                        (at or {}).get("function_name")
                        or (at or {}).get("source_function_name"),
                        (at or {}).get("span") if isinstance(at, dict) else None,
                    )
                    built = []
                    if fn is not None:
                        for a in _tree.asserts_of(fn):
                            memento = _tree.assert_memento(a, file_rel)
                            if seek and at is not None and not _memento_matches(
                                memento, at
                            ):
                                continue
                            built.append(
                                {"memento": memento, "audit": None, "payload": None}
                            )
                    _send_enumerate_result(msg_id, built, [])
                    _log_enumeration_demand(
                        str(level), at, cache="miss", started=demand_started
                    )
                    return

                # facts: at is an assertion memento — desugar THAT assert.
                source_node, node = _tree.temporally_rewritten_assert(
                    sf, at.get("span") if isinstance(at, dict) else None
                )
                if source_node is None or node is None:
                    _send_enumerate_result(
                        msg_id, [], [{"memento": at, "reason": "no assertion here"}]
                    )
                    return
                formula = _tree.fact_of(node)
                if formula is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": _tree.assert_memento(source_node, file_rel),
                                "reason": "assertion emits no fact",
                            }
                        ],
                    )
                    return
                _send_enumerate_result(
                    msg_id,
                    [
                        {
                            "memento": _tree.assert_memento(source_node, file_rel),
                            "audit": None,
                            "payload": formula,
                        }
                    ],
                    [],
                )
                _log_enumeration_demand(
                    str(level), at, cache="miss", started=demand_started
                )
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
    elif method == "sugar.plugin.resolve_dependency_proofs":
        _handle_resolve_dependency_proofs(
            msg_id, params if isinstance(params, dict) else {}
        )
    elif method == ENUMERATE_RPC_METHOD:
        global _ENUMERATION_ACTIVE, _ENUMERATION_REQUEST_COUNT
        enumerate_started = time.monotonic()
        _ENUMERATION_ACTIVE = True
        try:
            _handle_enumerate(msg_id, params if isinstance(params, dict) else {})
        finally:
            _observe_enumeration_phase(
                "request.total", (time.monotonic() - enumerate_started) * 1000
            )
            _ENUMERATION_REQUEST_COUNT += 1
            _log_enumeration_phase_profile(_ENUMERATION_REQUEST_COUNT)
            _ENUMERATION_ACTIVE = False
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
        _maybe_trim_resident(request_count)
        if not keep_serving:
            break


def main(argv: Optional[List[str]] = None) -> None:
    _configure_transport_logging()
    if _profile_interval("SUGAR_KIT_MEMORY_PROFILE_EVERY") > 0:
        tracemalloc.start(1)
    argv = argv or []
    if "--audit-only" in argv:
        raise SystemExit(
            "--audit-only no longer enables construction-gap recovery; "
            "use sugar lift --audit-frontier --continue-on-construction-gaps "
            "--allowed-broken-components python"
        )
    _serve()


if __name__ == "__main__":
    main(sys.argv[1:])
