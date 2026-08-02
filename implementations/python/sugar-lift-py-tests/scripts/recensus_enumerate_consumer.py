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

_INSTRUMENT_BLIND_CATEGORIES = frozenset(
    {
        "backend-defect",
        "instrument-defect-unresolvable-dispatch",
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
        "R_instrument_blind": 1 if category in _INSTRUMENT_BLIND_CATEGORIES else 0,
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


def _classify_honest_residual(
    error: BaseException,
) -> tuple[str, str, bool]:
    """Return (type_name, message, is_honest_residual) for residual errors.

    Honest residuals (E/H/L/Λ class after the 159 lies): named refusals that
    name the artifact they cannot see. Instrument-blind TypeError/AttributeError
    remain dishonest until converted to SugarNotWritten at the source.
    """
    name = type(error).__name__
    msg = str(error)
    # Already-named CM / With construction gaps (E-class).
    if name in {
        "ContextManagerResolutionConstructionGap",
        "WithConstructionGap",
        "SugarNotWritten",
    } or "CONTEXT MANAGER RESOLUTION GAP" in msg:
        return name if name != "Exception" else "ContextManagerResolutionConstructionGap", msg, True
    if name == "RecursionError" or "maximum recursion depth" in msg:
        return "ConstructionRecursionGap", msg, True
    if "LoopProjectedBinding" in msg or "LoopProjectedBinding" in name:
        return "LoopProjectedBindingReadGap", msg, True
    if "LambdaSugar" in msg or name == "LambdaSugar":
        return "LambdaBodyTestimonyGap", msg, True
    # SugarNotWritten subclasses often report via str with owner line.
    if "SUGAR NOT WRITTEN" in msg or "SugarNotWritten" in name:
        return name, msg, True
    return name, msg, False


def _enrolled_demand_unresolved_wire(
    error: BaseException,
) -> dict[str, Any] | None:
    """C3 A: project EnrolledDemandUnresolved ground → board wire fields.

    Returns None when the residual has no sealed C3 ground (kit-incomplete,
    raw TypeError, etc.). The five artifact fields name what source could not
    see — not merely the exception type.
    """
    decidability = getattr(error, "decidability", None)
    if decidability is None:
        return None
    try:
        from sugar_lift_py_tests.sealed_ground import EnrolledDemandUnresolved
    except ImportError:
        if type(decidability).__name__ != "EnrolledDemandUnresolved":
            return None
    else:
        if not isinstance(decidability, EnrolledDemandUnresolved):
            return None
    art = getattr(decidability, "artifact", None)
    if art is None:
        return None
    return {
        "decidabilityKind": "EnrolledDemandUnresolved",
        "demandFamily": str(getattr(art, "demand_family", "") or ""),
        "demandCid": str(getattr(art, "demand_cid", "") or ""),
        "useSite": str(getattr(art, "use_site", "") or ""),
        "gapKind": str(getattr(art, "gap_kind", "") or ""),
        "expectedRefType": str(getattr(art, "expected_ref_type", "") or ""),
    }


def _source_undecidable_refusal_row(
    *,
    file_rel: str,
    err_type: str,
    err_msg: str,
    wire: Mapping[str, Any],
) -> dict[str, Any]:
    """One C3 inhabitant for R_source_undecidable_refusals (compose input)."""
    return {
        "file": file_rel,
        "type": err_type,
        "message": err_msg,
        "decidabilityKind": wire["decidabilityKind"],
        "demandFamily": wire["demandFamily"],
        "demandCid": wire["demandCid"],
        "useSite": wire["useSite"],
        "gapKind": wire["gapKind"],
        "expectedRefType": wire["expectedRefType"],
    }


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
    # C3 B: live mint path → named list (compose banks R_source_undecidable_refusals)
    source_undecidable_refusals: list[dict[str, Any]] = []

    if function_gaps and not function_nodes:
        # File-level roster demand failed — true empty denominator.
        reason = function_gaps[0].get("reason") or "functions demand gap"
        return _empty_shell(
            file_rel=file_rel,
            category="backend-defect",
            functions_total=0,
            functions_enumerated=0,
            defect={
                "file": file_rel,
                "type": "EnumerateFunctionsGap",
                "message": str(reason),
            },
            functions_clean=0,
            clean_ratio_refused=False,
            ast_fn=ast_fn,
        )

    # --- roster banked ---
    functions_total = len(function_nodes)
    functions_enumerated = functions_total

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

    if residual_phase_failed and residual_error is not None:
        err_type, err_msg, honest = _classify_honest_residual(residual_error)
        # C3 A: attach sealed-ground artifact fields on the defect row when present.
        defect_row: dict[str, Any] = {
            "file": file_rel,
            "type": err_type,
            "message": err_msg,
            "phase": "residual",
            "honestResidual": honest,
        }
        c3_wire = _enrolled_demand_unresolved_wire(residual_error)
        if c3_wire is not None:
            defect_row.update(c3_wire)
            source_undecidable_refusals.append(
                _source_undecidable_refusal_row(
                    file_rel=file_rel,
                    err_type=err_type,
                    err_msg=err_msg,
                    wire=c3_wire,
                )
            )
            families["EnrolledDemandUnresolved"] += 1
        defects.append(defect_row)
        families[f"residual:{err_type}"] += 1

    clean, clean_refused, clean_reason = _honest_functions_clean(
        functions_total=functions_total,
        audit=audit,
        panics=panics,
        construction_panics=construction_panics,
        residual_phase_failed=residual_phase_failed,
    )

    if residual_phase_failed:
        category = "backend-defect"
        if construction_panics:
            category = "construction-panic"
        elif residual_error is not None and _classify_honest_residual(residual_error)[2]:
            # C3: honest unwritten refuses specifically as designed-gap, not
            # instrument-blind backend-defect.
            category = "designed-gap"
    elif construction_panics and not panics:
        category = "construction-panic"
    elif defects and not function_nodes:
        category = "backend-defect"
    elif residual_phase_failed:
        category = "backend-defect"
    else:
        category = "completed"

    # Mid-residual failure with banked roster: still construction-panic if panics,
    # designed-gap if honest residual, else backend-defect — functionsTotal stays.
    if residual_phase_failed and not construction_panics:
        if residual_error is not None and _classify_honest_residual(residual_error)[2]:
            category = "designed-gap"
        else:
            category = "backend-defect"

    row = _empty_shell(
        file_rel=file_rel,
        category=category,
        functions_total=functions_total,
        functions_enumerated=functions_enumerated,
        defect=defects[0] if defects and category != "completed" else None,
        panic=construction_panics[0] if construction_panics else None,
        families=dict(families),
        functions_clean=clean,
        clean_ratio_refused=clean_refused,
        clean_refuse_reason=clean_reason,
        ast_fn=ast_fn if ast_fn is not None else functions_total,
    )
    row["enumerateFunctionMementos"] = len(function_nodes)
    if construction_panics:
        row["constructionPanics"] = construction_panics
        row["enumerateConstructionPanics"] = construction_panics
    if category == "construction-panic" and construction_panics:
        row["panic"] = construction_panics[0]
    if defects and category != "completed":
        row["defect"] = defects[0]
    # C3 B: always present (empty when no EnrolledDemandUnresolved mint).
    row["sourceUndecidableRefusals"] = list(source_undecidable_refusals)
    row["R_source_undecidable_refusals"] = len(source_undecidable_refusals)
    # Roster was banked; instrument-blind only if residual failed without construction.
    if residual_phase_failed:
        row["R_instrument_blind"] = 1
        row["rosterPreservedAfterResidualFailure"] = True
    else:
        row["R_instrument_blind"] = 0
        row["rosterPreservedAfterResidualFailure"] = False
    return row


def measure_file_via_enumerate(
    *,
    workspace_root: Path,
    file_rel: str,
    source_cid: str | None = None,
    contract_refs=None,
) -> dict[str, Any]:
    """Produce one terminal solely from sugar.enumerate demands.

    ``contract_refs`` — when provided, installed into the process provisional
    demand-table memo BEFORE D2 so ``tree_construction_context_for_workspace``
    does not re-walk the corpus. Plan-time prebuilt tables are the production
    source; omitting this re-derives (process-memoized after first cold pay).

    Never raises after a roster is banked — residual failure becomes a terminal
    row with functionsTotal preserved (defect 1 / #7073 regression).
    """
    if contract_refs is not None:
        from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs

        install_provisional_contract_refs(Path(workspace_root), contract_refs)

    path = (workspace_root / file_rel).resolve()
    ast_fn = count_ast_function_defs(path)

    def _is_process_control(error: BaseException) -> bool:
        # ConstructionPanic is BaseException-by-design (I-want-the-panic).
        # Catch it as residual; never swallow KeyboardInterrupt / SystemExit.
        return isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit))

    # --- D2: roster ---
    try:
        function_nodes, function_gaps = demand_function_roster(
            workspace_root=workspace_root,
            file_rel=file_rel,
            source_cid=source_cid,
        )
    except BaseException as error:  # noqa: BLE001 — includes ConstructionPanic
        if _is_process_control(error):
            raise
        # No roster banked. AST population still names the gap when parseable
        # (instrument-blind mass, not a silent zero when the file has functions).
        auth = int(ast_fn) if ast_fn is not None else 0
        err_type, err_msg, honest = _classify_honest_residual(error)
        defect: dict[str, Any] = {
            "file": file_rel,
            "type": err_type,
            "message": err_msg,
            "phase": "roster",
            "honestResidual": honest,
        }
        source_undecidable: list[dict[str, Any]] = []
        c3_wire = _enrolled_demand_unresolved_wire(error)
        if c3_wire is not None:
            defect.update(c3_wire)
            source_undecidable.append(
                _source_undecidable_refusal_row(
                    file_rel=file_rel,
                    err_type=err_type,
                    err_msg=err_msg,
                    wire=c3_wire,
                )
            )
        shell = _empty_shell(
            file_rel=file_rel,
            category="designed-gap" if honest else "backend-defect",
            functions_total=auth,
            functions_enumerated=0,
            defect=defect,
            functions_clean=None if auth > 0 else 0,
            clean_ratio_refused=auth > 0,
            clean_refuse_reason=(
                "roster demand failed; clean not measured" if auth > 0 else None
            ),
            ast_fn=ast_fn,
        )
        shell["sourceUndecidableRefusals"] = source_undecidable
        shell["R_source_undecidable_refusals"] = len(source_undecidable)
        if source_undecidable:
            fam = dict(shell.get("families") or {})
            fam["EnrolledDemandUnresolved"] = (
                int(fam.get("EnrolledDemandUnresolved") or 0) + len(source_undecidable)
            )
            shell["families"] = fam
        return shell

    if function_gaps and not function_nodes:
        return terminal_from_enumerate(
            file_rel=file_rel,
            function_nodes=function_nodes,
            function_gaps=function_gaps,
            audit=None,
            construction_gaps=[],
            ast_fn=ast_fn,
        )

    # --- D3: residual (must not erase roster) ---
    # ConstructionPanic subclasses BaseException, not Exception. Catching only
    # Exception re-raised the #7073 mass-erase (panic escaped, outer shell banked 0).
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
        # Allow the name only inside this guard / docstring law statements.
        if text.count(name) > 2:
            raise AssertionError(
                f"recensus_enumerate_consumer must not use side door {name!r}"
            )
