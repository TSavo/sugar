#!/usr/bin/env python3
"""Recensus terminals via sugar.enumerate only — no private walk.

Binding law: protocol/specs/2026-08-02-recensus-as-enumerate-consumer.md
  AUTHORITY(work) = sugar.enumerate
  _measure_file is a retired side door and is not imported here.

Demands per enrolled file:
  D2: level=functions  → function roster (functionsTotal)
  D3: level=facts + options.auditFrontier → construction residual
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

SCOREBOARD_AUTHORITY = False

# Hard law: this module must never open SourceFile for measurement.
_FORBIDDEN_IMPORTS = frozenset(
    {
        "open_source_file_for_construction",
        "_measure_file",
    }
)


def enumerate_rpc(
    *,
    level: str,
    workspace_root: Path,
    at: dict[str, Any] | None = None,
    seek: bool = False,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One real sugar.enumerate demand (in-process handler = wire door)."""
    from sugar_lift_py_tests import lift_rpc

    options = dict(options or {})
    captured: list[dict[str, Any]] = []
    original_send = lift_rpc._send
    lift_rpc._send = captured.append
    try:
        lift_rpc._dispatch_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sugar.enumerate",
                "params": {
                    "level": level,
                    "workspace_root": str(workspace_root.resolve()),
                    "at": at,
                    "seek": seek,
                    "options": options,
                },
            }
        )
    finally:
        lift_rpc._send = original_send
    if len(captured) != 1:
        raise RuntimeError(f"sugar.enumerate produced {len(captured)} responses")
    response = captured[0]
    if "error" in response:
        raise RuntimeError(f"sugar.enumerate error: {response['error']}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("sugar.enumerate result is not an object")
    return result


def file_memento(*, file_rel: str, source_cid: str | None = None) -> dict[str, Any]:
    """Minimal file `at` for enumerate (kit resolves path under workspace_root)."""
    memo: dict[str, Any] = {
        "kind": "source-memento",
        "file": file_rel,
    }
    if source_cid is not None:
        memo["source_cid"] = source_cid
        memo["file_cid"] = source_cid
    return memo


def demand_function_roster(
    *,
    workspace_root: Path,
    file_rel: str,
    source_cid: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """D2: sugar.enumerate level=functions → (function nodes, gaps)."""
    at = file_memento(file_rel=file_rel, source_cid=source_cid)
    result = enumerate_rpc(
        level="functions",
        workspace_root=workspace_root,
        at=at,
        seek=False,
    )
    nodes = list(result.get("nodes") or [])
    gaps = list(result.get("gaps") or [])
    return nodes, gaps


def demand_construction_residual(
    *,
    workspace_root: Path,
    file_rel: str,
    source_cid: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """D3: sugar.enumerate level=facts + auditFrontier → construction residual.

    Returns (audit_leaf_or_none, gaps). Construction panics/gaps live on the
    audit envelope produced by the kit's enumerate path — not a private walk.
    """
    at = file_memento(file_rel=file_rel, source_cid=source_cid)
    result = enumerate_rpc(
        level="facts",
        workspace_root=workspace_root,
        at=at,
        seek=True,
        options={"auditFrontier": True, "allowedBrokenComponents": ["python"]},
    )
    gaps = list(result.get("gaps") or [])
    nodes = list(result.get("nodes") or [])
    if not nodes:
        return None, gaps
    audit = nodes[0].get("audit")
    return (audit if isinstance(audit, dict) else None), gaps


def terminal_from_enumerate(
    *,
    file_rel: str,
    function_nodes: list[dict[str, Any]],
    function_gaps: list[dict[str, Any]],
    audit: dict[str, Any] | None,
    construction_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map enumerate products → one recensus terminal row (compose input)."""
    functions_total = len(function_nodes)
    families: Counter[str] = Counter()
    construction_panics: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []

    if function_gaps and not function_nodes:
        # File-level demand failed — instrument/terminal defect, not a quiet zero.
        reason = function_gaps[0].get("reason") or "functions demand gap"
        return {
            "category": "backend-defect",
            "defect": {
                "file": file_rel,
                "type": "EnumerateFunctionsGap",
                "message": str(reason),
            },
            "functionsTotal": 0,
            "functionsClean": 0,
            "functionsEnumerated": 0,
            "functionsNotEnumerated": 0,
            "functionsEnumerationComplete": False,
            "families": {},
            "backendDefects": {},
            "R_backend_defects": 0,
            "cmResolutions": {},
            "unrecognizedCmResolutionKinds": {},
            "R_cm_derived_contract": 0,
            "astSites": {},
            "desugarFamilies": {},
            "desugarCategories": {},
            "desugarByCategoryOwner": {},
            "desugarConstructionPanics": [],
            "desugarDefects": [],
            "desugarDesignedGaps": [],
            "enumerateSource": True,
        }

    panics: list[dict[str, Any]] = []
    if isinstance(audit, dict):
        core = audit.get("semanticCore") or audit
        if isinstance(core, dict):
            raw_panics = core.get("panics") or []
            if isinstance(raw_panics, list):
                panics = [p for p in raw_panics if isinstance(p, dict)]

    for panic in panics:
        gap = panic.get("gap") if isinstance(panic.get("gap"), dict) else {}
        kind = str(gap.get("kind") or panic.get("kind") or "ConstructionPanic")
        families[kind] += 1
        if kind == "ConstructionPanic" or panic.get("kind") == "ConstructionPanic":
            construction_panics.append(
                {
                    "file": file_rel,
                    "type": "ConstructionPanic",
                    "message": str(
                        panic.get("reason") or gap.get("reason") or kind
                    ),
                    "gap": gap,
                    "locus": panic.get("locus"),
                }
            )
        elif "instrument" in kind.lower() or kind in {
            "AttributeError",
            "ImportError",
        }:
            defects.append(
                {
                    "file": file_rel,
                    "type": kind,
                    "message": str(panic.get("reason") or gap.get("reason") or ""),
                }
            )
        else:
            # Named construction gap family (SugarNotWritten, etc.)
            pass

    for gap in construction_gaps:
        families["EnumerateConstructionGap"] += 1
        defects.append(
            {
                "file": file_rel,
                "type": "EnumerateConstructionGap",
                "message": str(gap.get("reason") or gap),
            }
        )

    # Clean count: roster size minus distinct panic loci when status failed.
    # Prefer explicit clean from audit sourceAudit when present.
    functions_clean = functions_total
    if isinstance(audit, dict):
        core = audit.get("semanticCore") or {}
        if isinstance(core, dict) and core.get("status") == "failed":
            # At least one construction residual; do not claim full clean.
            functions_clean = max(0, functions_total - min(functions_total, len(panics)))
        aux = audit.get("auxiliaryRows") or {}
        source_audit = aux.get("sourceAudit") if isinstance(aux, dict) else None
        if isinstance(source_audit, dict) and "functionsClean" in source_audit:
            try:
                functions_clean = int(source_audit["functionsClean"])
            except (TypeError, ValueError):
                pass

    if construction_panics and not panics:
        category = "construction-panic"
    elif defects and not function_nodes:
        category = "backend-defect"
    else:
        category = "completed"

    row: dict[str, Any] = {
        "category": category,
        "functionsTotal": functions_total,
        "functionsClean": functions_clean,
        "functionsEnumerated": functions_total,
        "functionsNotEnumerated": 0,
        "functionsEnumerationComplete": True,
        "families": dict(families),
        "backendDefects": {},
        "R_backend_defects": 0,
        "cmResolutions": {},
        "unrecognizedCmResolutionKinds": {},
        "R_cm_derived_contract": 0,
        "astSites": {"site:function-def": functions_total},
        "desugarFamilies": {},
        "desugarCategories": {},
        "desugarByCategoryOwner": {},
        "desugarConstructionPanics": [],
        "desugarDefects": [],
        "desugarDesignedGaps": [],
        "enumerateSource": True,
        "enumerateFunctionMementos": len(function_nodes),
    }
    if category == "construction-panic" and construction_panics:
        row["panic"] = construction_panics[0]
        row["constructionPanics"] = construction_panics
    if defects and category != "completed":
        row["defect"] = defects[0]
    # Always attach full panic list for compose aggregation when present.
    if construction_panics:
        row["enumerateConstructionPanics"] = construction_panics
    return row


def measure_file_via_enumerate(
    *,
    workspace_root: Path,
    file_rel: str,
    source_cid: str | None = None,
) -> dict[str, Any]:
    """Produce one terminal solely from sugar.enumerate demands."""
    function_nodes, function_gaps = demand_function_roster(
        workspace_root=workspace_root,
        file_rel=file_rel,
        source_cid=source_cid,
    )
    audit, construction_gaps = demand_construction_residual(
        workspace_root=workspace_root,
        file_rel=file_rel,
        source_cid=source_cid,
    )
    return terminal_from_enumerate(
        file_rel=file_rel,
        function_nodes=function_nodes,
        function_gaps=function_gaps,
        audit=audit,
        construction_gaps=construction_gaps,
    )


def assert_no_side_door_imports() -> None:
    """Tooth: this module's source must not name the retired private walk."""
    text = Path(__file__).read_text(encoding="utf-8")
    for name in _FORBIDDEN_IMPORTS:
        # Allow the name only inside this guard / docstring law statements.
        if text.count(name) > 2:
            raise AssertionError(
                f"recensus_enumerate_consumer must not use side door {name!r}"
            )
