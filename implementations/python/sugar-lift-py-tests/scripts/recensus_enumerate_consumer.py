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
from typing import Any, Mapping

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


def _qualified_type(value: object) -> str:
    kind = type(value)
    return f"{kind.__module__}.{kind.__qualname__}"


def _function_key_manifest(
    *, file_rel: str, source_cid: str, function_nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    keys: list[dict[str, Any]] = []
    for node in function_nodes:
        memento = node.get("memento") if isinstance(node, dict) else None
        if not isinstance(memento, dict):
            continue
        keys.append(
            {
                "sourceCid": source_cid,
                "file": file_rel,
                "functionSourceCid": memento.get("source_cid"),
                "functionName": memento.get("source_function_name")
                or memento.get("function_name"),
                "span": memento.get("span"),
            }
        )
    return keys


def _terminal_input_key(
    *, file_rel: str, source_cid: str, function_keys: list[dict[str, Any]]
) -> dict[str, Any]:
    from compose_control_effect_board import key_manifest_cid

    return {
        "sourceCid": source_cid,
        "file": file_rel,
        "functionKeyManifest": list(function_keys),
        "functionKeyCid": key_manifest_cid(function_keys),
    }


def _exception_trace(
    error: BaseException,
    *,
    owner: str,
    coordinate: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "kind": "source-construct",
            "constructOwner": owner,
            "coordinate": coordinate,
        }
    ]
    tb = error.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        rows.append(
            {
                "kind": "dispatch-frame",
                "module": str(frame.f_globals.get("__name__") or ""),
                "qualname": frame.f_code.co_qualname,
                "file": frame.f_code.co_filename,
                "line": tb.tb_lineno,
            }
        )
        tb = tb.tb_next
    if len(rows) > 1:
        final = dict(rows[-1])
        final["kind"] = "panic-site"
        rows.append(final)
    return rows


def _panic_from_exception(
    error: BaseException, *, file_rel: str, phase: str
) -> dict[str, Any] | None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_source_tree.panic import SugarNotWritten

    if isinstance(error, ConstructionPanic):
        info = error.info.to_json()
        owner = str(info["owner"])
        coordinate = str(info["blame"])
        observed = str(info["observed"])
        requested = str(info["requested"])
        fix = str(info["fix"])
    elif isinstance(error, SugarNotWritten):
        owner = str(error.owner)
        coordinate = str(error.blame)
        observed = str(error.observed)
        requested = str(error.requested)
        fix = str(error.fix)
    else:
        return None
    entrance = f"sugar.enumerate:{phase}"
    return {
        "owner": owner,
        "coordinate": coordinate,
        "observed": observed,
        "requested": requested,
        "fix": fix,
        "entrance": entrance,
        "construction_trace": _exception_trace(
            error, owner=owner, coordinate=coordinate
        ),
        "observedEventType": _qualified_type(error),
        "file": file_rel,
        "message": str(error),
    }


def _panic_from_audit(raw: Mapping[str, Any], *, file_rel: str) -> dict[str, Any] | None:
    gap = raw.get("gap")
    if not isinstance(gap, dict):
        return None
    required = {
        "owner",
        "coordinate",
        "observed",
        "requested",
        "fix",
        "entrance",
        "construction_trace",
        "observedEventType",
    }
    if not required.issubset(gap) or not isinstance(gap["construction_trace"], list):
        return None
    return {
        **{field: gap[field] for field in required},
        "file": file_rel,
        "message": str(raw.get("reason") or gap.get("observed") or raw),
    }


def _attest_terminal_row(
    row: dict[str, Any],
    *,
    file_rel: str,
    source_cid: str,
    function_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    from compose_control_effect_board import (
        EDGE_ENUMERATE_FILE,
        STAGE_ENUMERATE_FILE_TERMINAL,
        canonical_cid,
        key_edge_witness,
    )

    function_keys = _function_key_manifest(
        file_rel=file_rel, source_cid=source_cid, function_nodes=function_nodes
    )
    input_key = _terminal_input_key(
        file_rel=file_rel, source_cid=source_cid, function_keys=function_keys
    )
    row["inputKey"] = input_key
    row["rowId"] = canonical_cid({"inputKey": input_key})
    row["stageId"] = STAGE_ENUMERATE_FILE_TERMINAL
    terminal_kind = "construction-panic" if row.get("panic") else "constructed"
    row["terminalKind"] = terminal_kind
    row["observedEventType"] = (
        row["panic"].get("observedEventType")
        if terminal_kind == "construction-panic"
        else "builtins.dict"
    )
    trace = row["panic"].get("construction_trace") if row.get("panic") else None
    row["observed_chain_length"] = len(trace) if isinstance(trace, list) else 1
    row["blocking_terminal_count"] = 1 if terminal_kind == "construction-panic" else 0
    row["final_terminal"] = terminal_kind
    row.setdefault("edgeWitnesses", {})[EDGE_ENUMERATE_FILE] = key_edge_witness(
        stage_id=STAGE_ENUMERATE_FILE_TERMINAL,
        input_keys=function_keys,
        output_keys=function_keys,
    )
    return row


def _instrument_failure_row(
    error: BaseException | str,
    *,
    file_rel: str,
    phase: str,
    source_cid: str | None,
    function_nodes: list[dict[str, Any]],
    functions_total: int,
    functions_enumerated: int,
) -> dict[str, Any]:
    observed_type = _qualified_type(error) if isinstance(error, BaseException) else "builtins.str"
    functions_not_enumerated = max(0, functions_total - functions_enumerated)
    row: dict[str, Any] = {
        "functionsTotal": functions_total,
        "functionsEnumerated": functions_enumerated,
        "functionsNotEnumerated": functions_not_enumerated,
        "functionsEnumerationComplete": (
            functions_total > 0
            and functions_enumerated == functions_total
            and functions_not_enumerated == 0
        ),
        "functionsClean": None,
        "cleanRatioRefused": True,
        "cleanRefuseReason": f"instrument failure during {phase}",
        "functionsAuthenticated": functions_total,
        "astSites": (
            {"site:function-def": functions_total} if functions_total else {}
        ),
        "rosterPreservedAfterResidualFailure": bool(
            phase in {"residual", "outer-shell-escape"}
            and functions_total > 0
            and functions_enumerated > 0
        ),
        "enumerateSource": True,
        "enumerateFunctionMementos": functions_enumerated,
        "families": {},
        "instrumentFailure": {
            "file": file_rel,
            "stageId": "recensus-enumerate-file-terminal/v1",
            "observedEventType": observed_type,
            "phase": phase,
            "message": str(error),
        },
    }
    if source_cid:
        function_keys = _function_key_manifest(
            file_rel=file_rel, source_cid=source_cid, function_nodes=function_nodes
        )
        row["inputKey"] = _terminal_input_key(
            file_rel=file_rel, source_cid=source_cid, function_keys=function_keys
        )
    return row


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


def demand_context_manager_resolution_events(
    *,
    workspace_root: Path,
    file_rel: str,
    source_cid: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Enumerate the raw, coordinate-keyed table With construction consumed."""
    result = enumerate_rpc(
        level="context-manager-resolutions",
        workspace_root=workspace_root,
        at=file_memento(file_rel=file_rel, source_cid=source_cid),
        seek=False,
    )
    events: list[dict[str, Any]] = []
    for node in result.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        memento = node.get("memento")
        audit = node.get("audit")
        coordinate = memento.get("coordinate") if isinstance(memento, dict) else None
        if not isinstance(coordinate, dict) or not isinstance(audit, dict):
            continue
        events.append(
            {
                "inputKey": dict(coordinate),
                "observedEventType": audit.get("observedEventType"),
                "outcome": audit.get("outcome"),
            }
        )
    return events, list(result.get("gaps") or [])


def _provisional_resolution_events(
    *, contract_refs: object, source_cid: str
) -> list[dict[str, Any]]:
    """Project the exact canonical fallback keys after enrichment panics.

    ``contract_refs`` is the same installed table the enumerate request used.
    This projects its coordinate-keyed rows directly; it never reconstructs
    membership from counters or deleted resolution-kind names.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        context_manager_resolution_outcome,
    )

    events: list[dict[str, Any]] = []
    for coordinate, resolution in sorted(
        (getattr(contract_refs, "by_use_site", None) or {}).items()
    ):
        if getattr(coordinate, "source_cid", None) != source_cid:
            continue
        events.append(
            {
                "inputKey": coordinate.wire(),
                "observedEventType": _qualified_type(resolution),
                "outcome": context_manager_resolution_outcome(resolution),
            }
        )
    return events


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


def _clear_d3_audit_open_observation(source_cid: str) -> None:
    from sugar_lift_py_tests.lift_rpc import take_d3_residency_observation

    take_d3_residency_observation(source_cid)


def _take_d3_audit_open_observation(source_cid: str) -> dict[str, Any] | None:
    from sugar_lift_py_tests.lift_rpc import take_d3_residency_observation

    return take_d3_residency_observation(source_cid)


def _complete_d3_residency_observation(
    *, source_cid: str, present_before_demand: bool
) -> dict[str, Any]:
    """Join the pre-demand sample to the actual audit-open observation.

    Both samples observe opens the production path already performs.  They do
    not open a SourceFile, clear residency, or change a gate verdict.
    """
    row: dict[str, Any] = {
        "sourceCid": source_cid,
        "reached": True,
        "presentBeforeDemand": bool(present_before_demand),
    }
    audit_open = _take_d3_audit_open_observation(source_cid)
    if isinstance(audit_open, dict):
        row.update(audit_open)
        row["presenceConfirmed"] = (
            row.get("presentBeforeDemand") == row.get("presentAtAuditOpen")
        )
    else:
        row["presenceConfirmed"] = False
    return row


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
    roster_preserved_after_residual_failure: bool = False,
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
            roster_preserved_after_residual_failure
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
    source_cid: str | None = None,
    context_manager_resolution_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map enumerate products → one recensus terminal (compose input).

    Roster-preserved mass: when function_nodes is non-empty, functionsTotal is
    len(function_nodes) even if residual_phase_failed.
    """
    if function_gaps and not function_nodes:
        return _instrument_failure_row(
            str(function_gaps[0]),
            file_rel=file_rel,
            phase="roster-gap",
            source_cid=source_cid,
            function_nodes=function_nodes,
            functions_total=0,
            functions_enumerated=0,
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
        authenticated = _panic_from_audit(panic, file_rel=file_rel)
        if authenticated is None:
            return _instrument_failure_row(
                f"audit panic lacks authenticated payload: {panic}",
                file_rel=file_rel,
                phase="audit-panic-decode",
                source_cid=source_cid,
                function_nodes=function_nodes,
                functions_total=functions_total,
                functions_enumerated=functions_enumerated,
            )
        construction_panics.append(authenticated)
    for gap in construction_gaps:
        return _instrument_failure_row(
            f"construction gap lacks terminal witness: {gap}",
            file_rel=file_rel,
            phase="residual-gap-decode",
            source_cid=source_cid,
            function_nodes=function_nodes,
            functions_total=functions_total,
            functions_enumerated=functions_enumerated,
        )

    residual_panic: dict[str, Any] | None = None
    if residual_phase_failed and residual_error is not None:
        residual_panic = _panic_from_exception(
            residual_error, file_rel=file_rel, phase="residual"
        )
        if residual_panic is None:
            return _instrument_failure_row(
                residual_error,
                file_rel=file_rel,
                phase="residual",
                source_cid=source_cid,
                function_nodes=function_nodes,
                functions_total=functions_total,
                functions_enumerated=functions_enumerated,
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
        roster_preserved_after_residual_failure=(
            residual_phase_failed
            and functions_total > 0
            and functions_enumerated > 0
        ),
    )
    if construction_panics:
        row["constructionPanics"] = list(construction_panics)
        row["enumerateConstructionPanics"] = list(construction_panics)
    row["contextManagerResolutionEvents"] = list(
        context_manager_resolution_events or []
    )
    if source_cid is not None:
        row = _attest_terminal_row(
            row,
            file_rel=file_rel,
            source_cid=source_cid,
            function_nodes=function_nodes,
        )
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
    from sugar_lift_py_tests.lift_rpc import (
        install_provisional_contract_refs,
        provisional_contract_refs_from_demands,
    )

    if contract_refs is None:
        contract_refs = provisional_contract_refs_from_demands(Path(workspace_root))
    install_provisional_contract_refs(Path(workspace_root), contract_refs)

    path = (workspace_root / file_rel).resolve()
    ast_fn = count_ast_function_defs(path)

    try:
        from sugar_lift_python_source.source_oracle import path_source

        _source, _filename, observed_source_cid = path_source(str(path))
    except BaseException as error:  # noqa: BLE001 — source identity is attendance
        if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        return _instrument_failure_row(
            error,
            file_rel=file_rel,
            phase="source-identity",
            source_cid=None,
            function_nodes=[],
            functions_total=int(ast_fn or 0),
            functions_enumerated=0,
        )
    if source_cid is not None and source_cid != observed_source_cid:
        return _instrument_failure_row(
            "requested source CID no longer matches loaded file",
            file_rel=file_rel,
            phase="source-identity",
            source_cid=observed_source_cid,
            function_nodes=[],
            functions_total=int(ast_fn or 0),
            functions_enumerated=0,
        )
    source_cid = observed_source_cid

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
        panic = _panic_from_exception(error, file_rel=file_rel, phase="roster")
        if panic is None:
            return _instrument_failure_row(
                error,
                file_rel=file_rel,
                phase="roster",
                source_cid=source_cid,
                function_nodes=[],
                functions_total=auth,
                functions_enumerated=0,
            )
        row = _empty_shell(
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
        return _attest_terminal_row(
            row,
            file_rel=file_rel,
            source_cid=source_cid,
            function_nodes=[],
        )

    if function_gaps and not function_nodes:
        return terminal_from_enumerate(
            file_rel=file_rel,
            function_nodes=function_nodes,
            function_gaps=function_gaps,
            audit=None,
            construction_gaps=[],
            ast_fn=ast_fn,
            source_cid=source_cid,
        )

    try:
        cm_events, cm_gaps = demand_context_manager_resolution_events(
            workspace_root=workspace_root,
            file_rel=file_rel,
            source_cid=source_cid,
        )
    except BaseException as error:  # noqa: BLE001 — distinct instrument/product paths
        if _is_process_control(error):
            raise
        panic = _panic_from_exception(
            error, file_rel=file_rel, phase="context-manager-resolutions"
        )
        if panic is None:
            return _instrument_failure_row(
                error,
                file_rel=file_rel,
                phase="context-manager-resolutions",
                source_cid=source_cid,
                function_nodes=function_nodes,
                functions_total=len(function_nodes),
                functions_enumerated=len(function_nodes),
            )
        row = _empty_shell(
            file_rel=file_rel,
            category="panic",
            functions_total=len(function_nodes),
            functions_enumerated=len(function_nodes),
            defect=panic,
            panic=panic,
            functions_clean=None,
            clean_ratio_refused=True,
            clean_refuse_reason="CM resolution panic after roster; clean not measured",
            ast_fn=ast_fn,
        )
        row["constructionPanics"] = [panic]
        row["enumerateConstructionPanics"] = [panic]
        row["contextManagerResolutionEvents"] = _provisional_resolution_events(
            contract_refs=contract_refs,
            source_cid=source_cid,
        )
        return _attest_terminal_row(
            row,
            file_rel=file_rel,
            source_cid=source_cid,
            function_nodes=function_nodes,
        )
    if cm_gaps:
        return _instrument_failure_row(
            f"context-manager resolution enumeration gaps: {cm_gaps}",
            file_rel=file_rel,
            phase="context-manager-resolutions",
            source_cid=source_cid,
            function_nodes=function_nodes,
            functions_total=len(function_nodes),
            functions_enumerated=len(function_nodes),
        )

    # Exposure instrument only: D3 follows earlier file demands, but eligibility
    # is not attendance.  Sample the existing resident map immediately before
    # the real D3 call, then join it to the audit-open observation afterward.
    # get_resident's LRU touch is the same touch the immediately-following open
    # performs, so this adds no open and leaves the post-open cache order intact.
    from sugar_source_tree.process_resident_file import get_resident

    _clear_d3_audit_open_observation(source_cid)
    d3_present_before_demand = get_resident(source_cid) is not None
    try:
        audit, construction_gaps = demand_construction_residual(
            workspace_root=workspace_root,
            file_rel=file_rel,
            source_cid=source_cid,
        )
    except BaseException as error:  # noqa: BLE001 — residual failed; roster stands
        if _is_process_control(error):
            raise
        row = terminal_from_enumerate(
            file_rel=file_rel,
            function_nodes=function_nodes,
            function_gaps=[],
            audit=None,
            construction_gaps=[],
            residual_phase_failed=True,
            residual_error=error,
            ast_fn=ast_fn,
            source_cid=source_cid,
            context_manager_resolution_events=cm_events,
        )
        row["d3Residency"] = _complete_d3_residency_observation(
            source_cid=source_cid,
            present_before_demand=d3_present_before_demand,
        )
        return row

    row = terminal_from_enumerate(
        file_rel=file_rel,
        function_nodes=function_nodes,
        function_gaps=function_gaps,
        audit=audit,
        construction_gaps=construction_gaps,
        residual_phase_failed=False,
        ast_fn=ast_fn,
        source_cid=source_cid,
        context_manager_resolution_events=cm_events,
    )
    row["d3Residency"] = _complete_d3_residency_observation(
        source_cid=source_cid,
        present_before_demand=d3_present_before_demand,
    )
    return row


def assert_no_side_door_imports() -> None:
    """Tooth: this module's source must not name the retired private walk."""
    text = Path(__file__).read_text(encoding="utf-8")
    for name in _FORBIDDEN_IMPORTS:
        if text.count(name) > 2:
            raise AssertionError(
                f"recensus_enumerate_consumer must not use side door {name!r}"
            )
