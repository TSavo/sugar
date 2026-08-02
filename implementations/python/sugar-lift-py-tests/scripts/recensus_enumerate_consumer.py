#!/usr/bin/env python3
"""Recensus terminals via sugar.enumerate only — no private walk.

Binding law: protocol/specs/2026-08-02-recensus-as-enumerate-consumer.md
  AUTHORITY(work) = sugar.enumerate
  _measure_file is a retired side door and is not imported here.

Law: construct or panic. No residual kinds. A file either constructs or the
panic names what could not be built.

Roster-floor (survives): when D2 banks a non-empty function roster, that mass
stays even if D3 panics. Do not lose work already done.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

SCOREBOARD_AUTHORITY = False

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
    """Authenticated AST FunctionDef population (site prevalence, not clean%)."""
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
    """D3: sugar.enumerate level=facts + auditFrontier → construction residual."""
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


def _panic_payload(error: BaseException, *, file_rel: str, phase: str) -> dict[str, Any]:
    """What could not be built — type + message. No residual kind ladder."""
    return {
        "file": file_rel,
        "type": type(error).__name__,
        "message": str(error),
        "phase": phase,
    }


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
    """One terminal shell. category is completed or panic only."""
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
        "cleanRefuseReason": clean_refuse_reason if clean_ratio_refused else None,
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
        "enumerateFunctionMementos": functions_enumerated,
        "rosterPreservedAfterResidualFailure": bool(
            category == "panic" and functions_total > 0 and functions_enumerated > 0
        ),
    }
    if defect is not None:
        row["defect"] = defect
    if panic is not None:
        row["panic"] = panic
        row["constructionPanics"] = [panic]
    return row


def _functions_clean(
    *,
    functions_total: int,
    audit: dict[str, Any] | None,
    construction_panics: list[dict[str, Any]],
    residual_failed: bool,
) -> tuple[int | None, bool, str | None]:
    """Clean count without inventing full-clean tautologies."""
    if functions_total <= 0:
        return 0, False, None
    if residual_failed:
        return None, True, "residual panic after roster; clean not measured"
    if isinstance(audit, dict):
        aux = audit.get("auxiliaryRows") or {}
        source_audit = aux.get("sourceAudit") if isinstance(aux, dict) else None
        if isinstance(source_audit, dict) and "functionsClean" in source_audit:
            try:
                clean = int(source_audit["functionsClean"])
            except (TypeError, ValueError):
                return None, True, "sourceAudit.functionsClean unreadable"
            if clean < 0 or clean > functions_total:
                return None, True, f"functionsClean={clean} outside [0,{functions_total}]"
            return clean, False, None
    residual_n = len(construction_panics)
    if residual_n > 0:
        return max(0, functions_total - min(functions_total, residual_n)), False, None
    if isinstance(audit, dict):
        core = audit.get("semanticCore") or audit
        if isinstance(core, dict) and core.get("status") == "failed":
            return None, True, "semanticCore.status=failed without countable panics"
        return functions_total, False, None
    return None, True, "no audit after residual demand"


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
    """Map enumerate products → one recensus terminal (compose input).

    Roster-preserved mass: when function_nodes is non-empty, functionsTotal is
    len(function_nodes) even if residual_phase_failed.
    """
    if function_gaps and not function_nodes:
        reason = function_gaps[0].get("reason") or "functions demand gap"
        panic = {
            "file": file_rel,
            "type": "EnumerateFunctionsGap",
            "message": str(reason),
            "phase": "roster",
        }
        return _empty_shell(
            file_rel=file_rel,
            category="panic",
            functions_total=0,
            functions_enumerated=0,
            defect=panic,
            panic=panic,
            functions_clean=0,
            clean_ratio_refused=False,
            ast_fn=ast_fn,
        )

    functions_total = len(function_nodes)
    functions_enumerated = functions_total
    construction_panics: list[dict[str, Any]] = []

    panics: list[dict[str, Any]] = []
    if isinstance(audit, dict):
        core = audit.get("semanticCore") or audit
        if isinstance(core, dict):
            raw_panics = core.get("panics") or []
            if isinstance(raw_panics, list):
                panics = [p for p in raw_panics if isinstance(p, dict)]
    for panic in panics:
        gap = panic.get("gap") if isinstance(panic.get("gap"), dict) else {}
        construction_panics.append(
            {
                "file": file_rel,
                "type": str(gap.get("kind") or panic.get("kind") or "ConstructionPanic"),
                "message": str(panic.get("reason") or gap.get("reason") or ""),
                "gap": gap,
                "locus": panic.get("locus"),
            }
        )
    for gap in construction_gaps:
        construction_panics.append(
            {
                "file": file_rel,
                "type": "EnumerateConstructionGap",
                "message": str(gap.get("reason") or gap),
            }
        )

    residual_panic: dict[str, Any] | None = None
    if residual_phase_failed and residual_error is not None:
        residual_panic = _panic_payload(
            residual_error, file_rel=file_rel, phase="residual"
        )
        construction_panics.append(residual_panic)

    clean, clean_refused, clean_reason = _functions_clean(
        functions_total=functions_total,
        audit=audit,
        construction_panics=construction_panics,
        residual_failed=residual_phase_failed,
    )

    failed = residual_phase_failed or bool(construction_panics)
    category = "panic" if failed else "completed"
    primary_panic = residual_panic or (
        construction_panics[0] if construction_panics else None
    )

    row = _empty_shell(
        file_rel=file_rel,
        category=category,
        functions_total=functions_total,
        functions_enumerated=functions_enumerated,
        defect=primary_panic if category == "panic" else None,
        panic=primary_panic if category == "panic" else None,
        functions_clean=clean,
        clean_ratio_refused=clean_refused,
        clean_refuse_reason=clean_reason,
        ast_fn=ast_fn if ast_fn is not None else functions_total,
    )
    if construction_panics:
        row["constructionPanics"] = list(construction_panics)
        row["enumerateConstructionPanics"] = list(construction_panics)
    return row


def measure_file_via_enumerate(
    *,
    workspace_root: Path,
    file_rel: str,
    source_cid: str | None = None,
    contract_refs=None,
) -> dict[str, Any]:
    """Produce one terminal solely from sugar.enumerate demands.

    Never raises after a roster is banked — residual panic becomes a terminal
    row with functionsTotal preserved (roster-floor).
    """
    if contract_refs is not None:
        from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs

        install_provisional_contract_refs(Path(workspace_root), contract_refs)

    path = (workspace_root / file_rel).resolve()
    ast_fn = count_ast_function_defs(path)

    def _is_process_control(error: BaseException) -> bool:
        return isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit))

    try:
        function_nodes, function_gaps = demand_function_roster(
            workspace_root=workspace_root,
            file_rel=file_rel,
            source_cid=source_cid,
        )
    except BaseException as error:  # noqa: BLE001 — includes ConstructionPanic
        if _is_process_control(error):
            raise
        auth = int(ast_fn) if ast_fn is not None else 0
        panic = _panic_payload(error, file_rel=file_rel, phase="roster")
        return _empty_shell(
            file_rel=file_rel,
            category="panic",
            functions_total=auth,
            functions_enumerated=0,
            defect=panic,
            panic=panic,
            functions_clean=None if auth > 0 else 0,
            clean_ratio_refused=auth > 0,
            clean_refuse_reason=(
                "roster demand panicked; clean not measured" if auth > 0 else None
            ),
            ast_fn=ast_fn,
        )

    if function_gaps and not function_nodes:
        return terminal_from_enumerate(
            file_rel=file_rel,
            function_nodes=function_nodes,
            function_gaps=function_gaps,
            audit=None,
            construction_gaps=[],
            ast_fn=ast_fn,
        )

    try:
        audit, construction_gaps = demand_construction_residual(
            workspace_root=workspace_root,
            file_rel=file_rel,
            source_cid=source_cid,
        )
    except BaseException as error:  # noqa: BLE001 — residual failed; roster stands
        if _is_process_control(error):
            raise
        return terminal_from_enumerate(
            file_rel=file_rel,
            function_nodes=function_nodes,
            function_gaps=[],
            audit=None,
            construction_gaps=[],
            residual_phase_failed=True,
            residual_error=error,
            ast_fn=ast_fn,
        )

    return terminal_from_enumerate(
        file_rel=file_rel,
        function_nodes=function_nodes,
        function_gaps=function_gaps,
        audit=audit,
        construction_gaps=construction_gaps,
        residual_phase_failed=False,
        ast_fn=ast_fn,
    )


def assert_no_side_door_imports() -> None:
    """Tooth: this module's source must not name the retired private walk."""
    text = Path(__file__).read_text(encoding="utf-8")
    for name in _FORBIDDEN_IMPORTS:
        if text.count(name) > 2:
            raise AssertionError(
                f"recensus_enumerate_consumer must not use side door {name!r}"
            )
