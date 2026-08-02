#!/usr/bin/env python3
"""Recensus terminals via sugar.enumerate only — no private walk.

Binding law: protocol/specs/2026-08-02-recensus-as-enumerate-consumer.md
  AUTHORITY(work) = sugar.enumerate
  _measure_file is a retired side door and is not imported here.

Demands per enrolled file:
  D2: level=functions  → function roster (functionsTotal population when banked)
  D3: level=facts + options.auditFrontier → construction residual

Denominator laws (restored after #7073 regression):
  1. Roster-preserved mass: when D2 returns a non-empty roster, functionsTotal
     is that roster size even if a later phase (D3) fails or panics. The retired
     door banked full functionsTotal on mid-file ConstructionPanic; dropping to
     0 on residual failure is the clean%-over-shrunken-set lie one level up.
  2. Open/roster-absent failure still banks functionsTotal=0 (true empty).
  3. Clean is never a tautology: do not default functionsClean = functionsTotal.
     Honest clean comes from sourceAudit.functionsClean or an explicit residual
     count; otherwise functionsClean is null and cleanRatioRefused=True.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

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


def count_ast_function_defs(path: Path) -> int | None:
    """Authenticated AST FunctionDef population (site prevalence, not clean%).

    Returns None when the file cannot be parsed (true open failure for AST).
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    return sum(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)
    )


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


def _empty_shell(
    *,
    file_rel: str,
    category: str,
    functions_total: int,
    functions_enumerated: int,
    defect: dict[str, Any] | None = None,
    panic: dict[str, Any] | None = None,
    families: dict[str, Any] | None = None,
    functions_clean: int | None = None,
    clean_ratio_refused: bool = True,
    clean_refuse_reason: str | None = None,
    ast_fn: int | None = None,
) -> dict[str, Any]:
    """Common terminal fields; never default clean to total."""
    not_enum = max(0, functions_total - functions_enumerated)
    row: dict[str, Any] = {
        "category": category,
        "functionsTotal": functions_total,
        "functionsEnumerated": functions_enumerated,
        "functionsNotEnumerated": not_enum,
        "functionsEnumerationComplete": functions_total > 0
        and functions_enumerated == functions_total
        and not_enum == 0,
        "functionsClean": functions_clean,
        "cleanRatioRefused": bool(clean_ratio_refused),
        "cleanRefuseReason": clean_refuse_reason
        if clean_ratio_refused
        else None,
        "families": dict(families or {}),
        "backendDefects": {},
        "R_backend_defects": 0,
        "cmResolutions": {},
        "unrecognizedCmResolutionKinds": {},
        "R_cm_derived_contract": 0,
        "astSites": (
            {"site:function-def": int(ast_fn)}
            if ast_fn is not None
            else ({"site:function-def": functions_total} if functions_total else {})
        ),
        "functionsAuthenticated": int(ast_fn)
        if ast_fn is not None
        else functions_total,
        "desugarFamilies": {},
        "desugarCategories": {},
        "desugarByCategoryOwner": {},
        "desugarConstructionPanics": [],
        "desugarDefects": [],
        "desugarDesignedGaps": [],
        "enumerateSource": True,
    }
    if defect is not None:
        row["defect"] = defect
    if panic is not None:
        row["panic"] = panic
        row["constructionPanics"] = [panic]
    return row


def _honest_functions_clean(
    *,
    functions_total: int,
    audit: dict[str, Any] | None,
    panics: list[dict[str, Any]],
    construction_panics: list[dict[str, Any]],
    residual_phase_failed: bool,
) -> tuple[int | None, bool, str | None]:
    """Return (clean, refused, reason). Never default clean == total.

    Honest sources (in order):
      1. sourceAudit.functionsClean when present (kit-authored residual count)
      2. residual_phase_failed after a banked roster → refuse (no per-fn walk)
      3. construction panics / audit panics with known total → total - min(total, n)
      4. completed residual phase, zero panics, zero construction_panics → total
         (earned clean, residual phase testified empty)
      5. otherwise refuse
    """
    if functions_total <= 0:
        # Empty population: clean is 0, not a ratio claim.
        return 0, False, None

    if isinstance(audit, dict):
        aux = audit.get("auxiliaryRows") or {}
        source_audit = aux.get("sourceAudit") if isinstance(aux, dict) else None
        if isinstance(source_audit, dict) and "functionsClean" in source_audit:
            try:
                clean = int(source_audit["functionsClean"])
            except (TypeError, ValueError):
                return (
                    None,
                    True,
                    "sourceAudit.functionsClean unreadable; refuse clean ratio",
                )
            if clean < 0 or clean > functions_total:
                return (
                    None,
                    True,
                    f"sourceAudit.functionsClean={clean} outside [0,{functions_total}]",
                )
            return clean, False, None

    if residual_phase_failed:
        return (
            None,
            True,
            "residual phase failed after roster; clean not measured (refuse tautology)",
        )

    residual_n = len(construction_panics) if construction_panics else len(panics)
    if residual_n > 0:
        # Distinct residual events subtract from clean, never inflate total.
        return max(0, functions_total - min(functions_total, residual_n)), False, None

    if isinstance(audit, dict):
        core = audit.get("semanticCore") or audit
        if isinstance(core, dict) and core.get("status") == "failed":
            # Failed without countable panics — refuse, do not claim full clean.
            return (
                None,
                True,
                "semanticCore.status=failed without countable panics; refuse clean",
            )
        # Residual phase returned an audit with no panics → earned full clean.
        return functions_total, False, None

    # No audit at all after residual demand — refuse.
    return (
        None,
        True,
        "no audit and no residual count; refuse clean ratio (would be tautological)",
    )





def terminal_from_enumerate(
    *,
    file_rel: str,
    function_nodes: list[dict[str, Any]],
    function_gaps: list[dict[str, Any]],
    audit: dict[str, Any] | None,
    construction_gaps: list[dict[str, Any]],
    residual_phase_failed: bool = False,
    residual_error: BaseException | None = None,
    ast_fn: int | None = None,
) -> dict[str, Any]:
    """Map enumerate products → one recensus terminal row (compose input).

    Roster-preserved mass: when function_nodes is non-empty, functionsTotal is
    len(function_nodes) even if residual_phase_failed.
    """
    families: Counter[str] = Counter()
    construction_panics: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []
