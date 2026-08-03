from __future__ import annotations

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

# Self-bootstrap the sibling package src trees onto sys.path. The kit imports
# sugar_lift_python_source (source_tables, at load via source_fragment) and
# sugar_source_tree (the tree lift / enumeration). When the lift-plugin resolver
# spawns this as a bare `python3 lift_rpc.py --rpc` -- dropping the manifest's
# PYTHONPATH -- those siblings are otherwise unreachable and initialize dies
# before the handshake. Add them here so the kit is spawnable however invoked.
_python_root = Path(__file__).resolve().parents[3]  # implementations/python
for _sibling in ("sugar-lift-python-source", "sugar-source-tree"):
    _src = _python_root / _sibling / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from sugar_lift_py_tests.effect import SourceOracleEffect, effect_reason, effect_status
from sugar_lift_py_tests.filename import cid_from_proof_stem
from sugar_lift_py_tests.idd.lift_coverage_accounting import (
    account_lift_coverage,
    paint_lines,
)
from sugar_lift_py_tests.idd.lift_coverage_census import census_paths
from sugar_lift_py_tests.kit_rpc import (
    EffectDto,
    LiftReportPayloadDto,
    RecoveredEffectDto,
    SuppressedAuditLocusDto,
)
from sugar_lift_py_tests.kit_rpc.rpc_value import to_rpc_value
from sugar_lift_py_tests.source_provenance import kit_source_provenance
from sugar_source_tree.panic import SourceTreePanic

KIT_ID = "python"
KIT_VERSION = "0.1.0"
NO_SOURCE_SITES_MESSAGE = "factory source contained no source sites"
LIFT_RPC_MODULE = "sugar_lift_py_tests.lift_rpc"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
COMPONENT_PLAN_RPC_METHOD = "sugar.component.plan"
RESOLVE_SOURCE_MEMENTO_RPC_METHOD = "sugar.plugin.resolve_source_memento"
ENUMERATE_RPC_METHOD = "sugar.enumerate"
BIND_CONTRACT_REFS_RPC_METHOD = "sugar.plugin.bind_contract_refs"
BIND_CALL_CONTRACT_REFS_RPC_METHOD = "sugar.plugin.bind_call_contract_refs"
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
_BOUND_CONTRACT_REFS = None
_BOUND_CALL_CONTRACT_REFS = None
# Phase-1->3 cross-request continuation: retained immutable universes keyed
# by linkUnitCid, and a def-memento index so resume reuses the SAME universe
# object (materialize-once) instead of reconstructing the function.
_RETAINED_LINK_UNITS = {}
_RETAINED_BY_MEMENTO = {}
# Provisional With/call demand table by resolved workspace root. Deriving it
# walks every enrolled ``*.py`` (authenticated import uses + With sites) —
# measured multi-minute on pandas (1421 files). Recensus builds it "once" in
# control_effect_recensus, but ``measure_file_via_enumerate`` never received
# that table: each D2 ``sugar.enumerate level=functions`` re-derived via
# ``tree_construction_context_for_workspace`` → hang-looking multi-minute
# per file. Process memo makes the paid scan real amortization within one
# process; k=8 still pays ×k cold startups unless shards LOAD a prebuilt
# table (see ``prebuilt_demand_table`` + ``install_provisional_contract_refs``).
_PROVISIONAL_CONTRACT_REFS_BY_ROOT: Dict[str, Any] = {}
# How many times ``_preconstruction_demand_rows`` actually walked a corpus.
# Unit tests count this (do not time it): a cold process given a prebuilt
# table must leave this at zero after install + measure.
_PRECONSTRUCTION_WALK_COUNT = 0
# D3 exposure telemetry, process-local because enumerate_rpc dispatches in-process.
# The wire DTO stays closed; the recensus consumer takes this observation after
# the facts demand.  One entry per source CID, popped by the consumer, so a
# prior file can never masquerade as confirmation for a later demand.
_D3_RESIDENCY_OBSERVATIONS: Dict[str, Dict[str, Any]] = {}


def _record_d3_residency_observation(
    source_cid: str, observation: Dict[str, Any]
) -> None:
    _D3_RESIDENCY_OBSERVATIONS[source_cid] = dict(observation)


def take_d3_residency_observation(source_cid: str) -> Dict[str, Any] | None:
    """Take the real audit-open observation for one D3 source demand."""
    row = _D3_RESIDENCY_OBSERVATIONS.pop(source_cid, None)
    return dict(row) if row is not None else None


def _context_manager_demand_rows(root: Path) -> List[Dict[str, Any]]:
    """Enroll typed With occurrences without constructing any Sugar.

    Import authority is joined later from ``_call_contract_demand_rows`` at the
    identical source coordinate.  This pass owns only the structural fact that
    a typed WithItem exists; it never reconstructs imports from spellings.
    """
    from sugar_lift_python_source.source_oracle import SourceUnavailable
    from sugar_source_tree.nodes import AsyncWith, With
    from sugar_source_tree.tree import SourceFile, SourceTree

    rows: List[Dict[str, Any]] = []
    for path in SourceTree(root).paths():
        try:
            source_file = SourceFile.from_path(path)
        except SourceUnavailable:
            continue
        for node in source_file.nodes():
            if not isinstance(node, (With, AsyncWith)):
                continue
            for item in node.items:
                expression = item.context_expr
                span = expression.line_col_span()
                coordinate = {
                    "sourceCid": source_file.unit.source_cid,
                    "startLine": span.start_line,
                    "startCol": span.start_col,
                    "endLine": span.end_line,
                    "endCol": span.end_col,
                }
                rows.append(
                    {
                        "schemaVersion": "1",
                        "kind": "context-manager-demand",
                        "useSite": coordinate,
                        "targetSymbol": None,
                        "importSignature": {"parameters": []},
                        "expectedKind": "context-manager-contract",
                        "gapKind": "runtime-selected",
                    }
                )
    return rows


def provisional_contract_refs_from_demand_rows(
    rows,
    *,
    table_cid: str | None = None,
    catalog_cid: str | None = None,
):
    """Project one already-authenticated demand table into construction refs.

    No corpus walk. When ``table_cid`` is omitted, the table is content-addressed
    from the CM demand rows so two identical row sets share one CID.
    """
    from types import MappingProxyType

    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        ResolvedContractRefsV1,
        SourceFragmentCoordinateV1,
        _hash_json,
    )
    from sugar_lift_python_source.canonical import cid_of_json

    resolutions = {}
    cm_rows = []
    for row in rows:
        if row.get("kind") != "context-manager-demand":
            continue
        cm_rows.append(row)
        site = SourceFragmentCoordinateV1.decode(row["useSite"])
        preimage = {
            key: row[key]
            for key in ("useSite", "targetSymbol", "importSignature", "expectedKind")
        }
        resolutions[site] = ContextManagerResolutionGapV1(
            _hash_json(preimage),
            site,
            row.get("targetSymbol"),
            row.get("gapKind") or "runtime-selected",
            (),
        )
    if table_cid is None:
        table_cid = cid_of_json(
            {"kind": "provisional-demand-table-rows", "rows": cm_rows}
        )
    if catalog_cid is None:
        catalog_cid = table_cid
    return ResolvedContractRefsV1(catalog_cid, table_cid, MappingProxyType(resolutions))


def provisional_contract_refs_from_demands(root: Path):
    """One typed gap row per enrolled With demand — census / unbinded construct door.

    Production replaces this table via ``bind_contract_refs`` with authenticated
    resolutions. Until that table is installed (or for instruments that construct
    without the Rust prebind), every With use-site must still appear so
    ``With._prebound_manager_resolution`` does not treat missing context as
    unconditional ``RuntimeSelectedContextManager`` (false red).

    Each demand lands as ``ContextManagerResolutionGapV1`` with the demand's
    ``gapKind`` (default ``runtime-selected``). Source-derived managers may still
    win via ``populate_source_derived_resource_refs`` after the context is
    installed — derived takes precedence over this provisional gap table.

    Process-memoized by resolved root: the walk is O(corpus), not O(file). A
    second open of the same workspace root must not re-scan every module.
    Prefer ``install_provisional_contract_refs`` / prebuilt load for cold
    shard processes so the walk is not paid again.
    """
    key = str(Path(root).resolve())
    cached = _PROVISIONAL_CONTRACT_REFS_BY_ROOT.get(key)
    if cached is not None:
        return cached
    refs = provisional_contract_refs_from_demand_rows(
        _preconstruction_demand_rows(root)
    )
    _PROVISIONAL_CONTRACT_REFS_BY_ROOT[key] = refs
    return refs


def install_provisional_contract_refs(root: Path, refs) -> None:
    """Seed the process demand-table memo without walking the corpus.

    Shards load a plan-time prebuilt table and call this once. Subsequent
    ``provisional_contract_refs_from_demands`` / D2 enumerate hits the memo.
    """
    key = str(Path(root).resolve())
    _PROVISIONAL_CONTRACT_REFS_BY_ROOT[key] = refs


def clear_provisional_contract_refs_memo() -> None:
    """Drop process demand-table memo (tests / hermetic process reuse)."""
    _PROVISIONAL_CONTRACT_REFS_BY_ROOT.clear()


def preconstruction_walk_count() -> int:
    """How many times the corpus was walked for provisional demand rows."""
    return _PRECONSTRUCTION_WALK_COUNT


def reset_preconstruction_walk_count() -> None:
    """Zero the walk counter (tests only)."""
    global _PRECONSTRUCTION_WALK_COUNT
    _PRECONSTRUCTION_WALK_COUNT = 0


def tree_construction_context_for_workspace(
    root: Path,
    *,
    contract_refs=None,
    call_contract_refs=None,
):
    """Tree handle for construction: bound refs, or provisional demand gaps.

    Always non-None. Bare ``fn.sugar()`` without this is the instrument defect
    that paints every With as RuntimeSelected regardless of resolvability.
    """
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    refs = (
        contract_refs
        if contract_refs is not None
        else provisional_contract_refs_from_demands(root)
    )
    return TreeConstructionContextV1(
        refs,
        call_contract_refs=call_contract_refs,
        workspace_root=str(root),
    )


def open_source_file_for_construction(
    path: Path,
    *,
    root: Path,
    reporter=None,
    contract_refs=None,
    call_contract_refs=None,
    construction_context=None,
    populate_derived: bool = True,
    resolution_session=None,
):
    """Open a SourceFile the way production enumerate does — never bare context.

    Injects ``TreeConstructionContextV1`` (bound or provisional) and, by default,
    freezes source-derived manager refs at exact use-sites. Callers that already
    hold a frozen context (shared demand table across a census) may pass it.

    ``resolution_session`` owns every source-resolution memo for this open. When
    omitted, this door uses the walk-scoped session for ``root`` so multi-file
    census / re-open of the same content amortize projection under one workspace
    authority (see ``walk_session_for``). Pass an explicit session to isolate.

    Roster-floor law: after SourceFile construction succeeds, N =
    ``len(functions())`` is banked on the open as ``function_roster_floor``.
    Any subsequent populate ``Exception`` is residualized and the SourceFile is
    returned — the board may not undercut N without naming why. Open failure
    *before* SourceFile still raises (empty denominator). Process-control
    exceptions (``BaseException`` outside ``Exception``) still halt.
    """
    from sugar_lift_python_source.resolution_session import walk_session_for
    from sugar_lift_python_source.source_oracle import workspace_path_source
    from sugar_source_tree.reporter import NULL_REPORTER
    from sugar_source_tree.tree import SourceFile

    if reporter is None:
        reporter = NULL_REPORTER
    if construction_context is None:
        construction_context = tree_construction_context_for_workspace(
            root,
            contract_refs=contract_refs,
            call_contract_refs=call_contract_refs,
        )
    source_file = SourceFile(
        workspace_path_source(str(path), root=str(root)),
        reporter=reporter,
        construction_context=construction_context,
    )
    # ROSTER FLOOR LAW (#7062 class close, #7075 second costume generalized):
    # If SourceFile produced N functions, the board may never report fewer
    # than N without naming why. Bank N *before* populate. Populate failure
    # becomes a residual; it cannot erase the denominator. Open-path failure
    # *before* this line still raises — correctly empty. A third costume is
    # not another allowlist entry: any Exception after the bank is residual.
    _bank_function_roster_floor(source_file)

    if populate_derived:
        from sugar_lift_python_source.manager_summary_derivation import (
            populate_source_derived_resource_refs,
        )

        # Multi-resolve owner: walk-scoped session when none given so census
        # and same-content re-open share projection memos under one root.
        session = (
            resolution_session
            if resolution_session is not None
            else walk_session_for(root)
        )
        # Catch Exception, not BaseException: KeyboardInterrupt / SystemExit /
        # GeneratorExit still halt the process. Do not enumerate SNW/TypeError
        # here — that was the two-costume allowlist that left the class open.
        try:
            populate_source_derived_resource_refs(
                source_file, root=root, path=path, session=session
            )
        except Exception as populate_gap:  # noqa: BLE001 — floor law; see above
            _record_populate_path_residual(source_file, populate_gap)
    return source_file


def _bank_function_roster_floor(source_file) -> int:
    """Bank N = len(SourceFile.functions()) as load-bearing open state.

    The floor is the proof that construction already succeeded. Callers and
    residual paths read it; populate cannot lower it. Returning the open after
    a residual keeps ``functions()`` live; the banked floor is the invariant
    pin when a board path would otherwise invent zero.
    """
    n = len(tuple(source_file.functions()))
    try:
        object.__setattr__(source_file, "function_roster_floor", n)
    except (AttributeError, TypeError):
        # If the SourceFile type forbids attributes, the live functions()
        # roster still carries the denominator after residual return.
        pass
    unit = getattr(source_file, "unit", None) or getattr(
        getattr(source_file, "root", None), "unit", None
    )
    context = getattr(unit, "construction_context", None) if unit is not None else None
    if context is not None:
        try:
            object.__setattr__(context, "function_roster_floor", n)
        except (AttributeError, TypeError):
            pass
    return n


def _record_populate_path_residual(source_file, error: BaseException) -> None:
    """Name a populate-path failure without discarding the banked roster floor.

    Residual is always typed by the *actual* exception class name — no allowlist
    of costumes. SugarNotWritten keeps its structured owner/observed/fix fields
    when present; every other Exception is residualized generically so a third
    costume cannot reintroduce the zero-function lie.
    """
    from sugar_source_tree.panic import SugarNotWritten

    err_type = type(error).__name__
    if isinstance(error, SugarNotWritten):
        owner = str(getattr(error, "owner", None) or err_type)
        observed = str(getattr(error, "observed", None) or error)
        requested = str(getattr(error, "requested", None) or "")
        fix = str(getattr(error, "fix", None) or "")
    else:
        owner = "open_source_file_for_construction.populate"
        observed = str(error) if str(error) else err_type
        requested = (
            "populate residual after successful SourceFile; function_roster_floor "
            f"preserved at {getattr(source_file, 'function_roster_floor', '?')}"
        )
        fix = (
            "cite this residual; never discard the banked SourceFile function "
            "roster. The floor law forbids empty denominators after construction"
        )

    unit = getattr(source_file, "unit", None) or getattr(
        getattr(source_file, "root", None), "unit", None
    )
    context = getattr(unit, "construction_context", None) if unit is not None else None
    residual = {
        "phase": "populate",
        "owner": owner,
        "type": err_type,
        "observed": observed,
        "requested": requested,
        "fix": fix,
        "functionRosterFloor": getattr(source_file, "function_roster_floor", None),
    }
    if context is None:
        return
    existing = getattr(context, "populate_residuals", None)
    if existing is None:
        try:
            object.__setattr__(context, "populate_residuals", [residual])
        except (AttributeError, TypeError):
            # Frozen / slots context: residual still exists as the exception
            # that was caught; roster preservation is the load-bearing law.
            return
    else:
        existing.append(residual)


def _call_contract_demand_rows(root: Path) -> List[Dict[str, Any]]:
    """Enroll imported plain calls by their source-authenticated use sites."""
    from sugar_lift_py_tests.import_binding import (
        authenticated_import_uses,
        authenticated_module_exports,
        module_name_for_path,
    )
    from sugar_lift_python_source.source_oracle import SourceUnavailable, path_source
    from sugar_source_tree.tree import SourceTree

    rows: List[Dict[str, Any]] = []
    units = []
    for path in SourceTree(root).paths():
        try:
            source, _filename, source_cid = path_source(str(path))
        except SourceUnavailable:
            continue
        units.append((path, source, source_cid))
    module_identities = {
        module_name_for_path(root, path): {
            "kind": "authenticated-python-module",
            "schemaVersion": "1",
            "moduleName": module_name_for_path(root, path),
            "sourceCid": source_cid,
        }
        for path, _source, source_cid in units
    }
    for path, source, source_cid in units:
        enrolled, _outcomes = authenticated_import_uses(
            root, path, source, source_cid, module_identities
        )
        rows.extend(authenticated_module_exports(root, path, source, source_cid))
        rows.extend(enrolled)
    return rows


def _memento_continuation_key(memento: Dict[str, Any]) -> str:
    """The retained-universe index key: a function's stable source identity
    (source_cid + span). Lets the resume path reuse the SAME retained universe
    without reconstructing the function."""
    span = memento.get("span") or {}
    return "|".join(
        str(part)
        for part in (
            memento.get("source_cid"),
            span.get("start_line"),
            span.get("start_col"),
            span.get("end_line"),
            span.get("end_col"),
        )
    )


def _parameter_contract_resume_rows(options: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Phase-3 resume: reuse the RETAINED universe for this linkUnitCid
    (materialize-once, NEVER reconstruct), verify the presented resolution set is
    bound to THIS continuation and forms the exact-complete bijection, attach the
    authenticated resolutions, and project post(). A lost continuation or any
    stale/foreign/incomplete set raises a loud ConstructionPanic; it never
    silently reconstructs through another path."""
    import dataclasses

    from sugar_lift_py_tests.caller_parameter_contract import (
        ParameterContractResolutionSetV1,
        ResumeStalePanic,
        resume_apply_resolutions,
    )
    from sugar_lift_py_tests.gap.info import GapKind, GapLocus
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    link_unit_cid = options.get("linkUnitCid")
    raw_set = options.get("resolutionSet")
    retained = _RETAINED_LINK_UNITS.get(link_unit_cid)
    if retained is None:
        construction_panic_gap(
            owner="parameter-contract-resume",
            blame=str(link_unit_cid),
            observed="no retained continuation for this linkUnitCid",
            requested="the retained universe enrolled in phase 1",
            fix="resume in the SAME server session that enrolled the link unit",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
    universe, def_memento_dto, def_memento, unit = retained
    try:
        resolution_set = ParameterContractResolutionSetV1.from_value(raw_set)
        accepted = resume_apply_resolutions(unit, resolution_set)
    except (ResumeStalePanic, ValueError) as exc:
        construction_panic_gap(
            owner="parameter-contract-resume",
            blame=unit.parameter_owned_contract.contract_cid,
            observed=str(exc),
            requested="an exact, replay-bound ParameterContractResolutionSetV1",
            fix="present the fold's authenticated resolution set for THIS continuation",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
    # Materialize-once + value correctness: replace each resolved candidate with
    # its retained .value and project the resumed record normally.
    from sugar_lift_py_tests.caller_parameter_contract import resume_project

    resolved = resume_project(universe, accepted)
    from sugar_lift_py_tests.ir import TermTableBuilder

    term_table = TermTableBuilder()
    rows = resolved.payload_rows(def_memento_dto)
    nodes = [
        {
            "memento": def_memento,
            "audit": dto.to_rpc_with_term_table(term_table),
            "payload": None,
        }
        for dto in rows
    ]
    return nodes


def _parameter_contract_link_unit_rows(root: Path) -> List[Dict[str, Any]]:
    """Phase-1 enrollment: one closed ParameterContractLinkUnitV1 per function
    that enrolled a parameter-contract demand. Builds each function's universe
    (never calls post()), projects its link unit, and RETAINS the immutable
    universe keyed by linkUnitCid + def-memento so Phase-3 resume reuses it.

    Soft-skip is only ``SugarNotWritten`` (typed tree frontier), matching
    universe enumerate. ``ConstructionPanic`` is *not* caught here — the sole
    production soft membranes are audit enumeration and
    ``_production_lift_child``; panics propagate to the process-terminal
    JSON-RPC error + SystemExit handler. Incomplete / non-Universe outcomes
    simply enroll no link unit (no owned demand).
    """
    from sugar_lift_py_tests import tree_enumerate as _tree
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_source_tree.panic import SugarNotWritten

    global _RETAINED_LINK_UNITS, _RETAINED_BY_MEMENTO
    _RETAINED_LINK_UNITS = {}
    _RETAINED_BY_MEMENTO = {}
    rows: List[Dict[str, Any]] = []
    for source_path in sorted(root.rglob("*.py")):
        file_rel = str(source_path.relative_to(root))
        # No broad skip: a source that cannot be read is a LOUD failure, never a
        # silently omitted file.
        sf = _tree.source_file(source_path)
        for fn in sf.functions():
            try:
                outcome = fn.sugar().desugar(None)
            except SugarNotWritten:
                # Typed tree frontier: no link unit to enroll. Gap remains
                # visible on the universe/audit scan; never catch
                # ConstructionPanic to soft-continue.
                continue
            if not isinstance(outcome, Complete):
                continue
            universe = outcome.value
            if not isinstance(universe, UniverseValue):
                continue
            def_memento_dto = _tree.function_def_memento(fn, file_rel)
            def_memento = def_memento_dto.to_rpc()
            # No broad skip: a projection failure is LOUD (it escapes), never a
            # silently dropped link unit. `None` is the typed "no owned demand".
            unit = universe.link_unit_projection(def_memento)
            if unit is None:
                continue
            _RETAINED_LINK_UNITS[unit.link_unit_cid] = (
                universe,
                def_memento_dto,
                def_memento,
                unit,
            )
            _RETAINED_BY_MEMENTO[_memento_continuation_key(def_memento)] = (
                unit.link_unit_cid
            )
            rows.append(unit.to_value())
    return rows


def _preconstruction_demand_rows(root: Path) -> List[Dict[str, Any]]:
    """Join authenticated call identity into With demands without dual ownership.

    A context-manager expression is constructed under its context-manager
    contract.  Its call coordinate supplies the authenticated import binding,
    but must not also enroll an independent function-contract demand for the
    same use site.

    Each call is one corpus walk (counted by ``preconstruction_walk_count``).
    Cold shards must load a prebuilt table instead of re-entering this door.
    """
    global _PRECONSTRUCTION_WALK_COUNT
    _PRECONSTRUCTION_WALK_COUNT += 1
    call_rows = _call_contract_demand_rows(root)
    calls_by_site = {
        json.dumps(row["useSite"], sort_keys=True): row
        for row in call_rows
        if row.get("kind") == "call-contract-demand"
    }
    cm_rows = _context_manager_demand_rows(root)
    cm_sites = set()
    for row in cm_rows:
        site = json.dumps(row["useSite"], sort_keys=True)
        cm_sites.add(site)
        call = calls_by_site.get(site)
        if call is None:
            row["targetSymbol"] = None
            row["gapKind"] = "runtime-selected"
            continue
        target = call["targetSymbol"]
        row["targetSymbol"] = target.removeprefix("python:")
        row["importBindingCid"] = call["importBindingCid"]
        row["importBinding"] = call["importBinding"]
        row["authenticatedImportUse"] = call["authenticatedImportUse"]
        row["gapKind"] = None
    remaining_call_rows = [
        row
        for row in call_rows
        if row.get("kind") != "call-contract-demand"
        or json.dumps(row["useSite"], sort_keys=True) not in cm_sites
    ]
    return cm_rows + remaining_call_rows


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
        for name in ("source_splitlines", "source_lines", "_parsed"):
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
                {"name": BIND_CONTRACT_REFS_RPC_METHOD, "required": False},
                {"name": BIND_CALL_CONTRACT_REFS_RPC_METHOD, "required": False},
                # lift is not a kit method: full-tree construction is sugar.enumerate only
                # {"name": "lift", "required": True},
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
        "contractDeclarations": [],
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
            SourceUnavailable,
            resolve_source_memento,
        )
    except ModuleNotFoundError:
        sibling_src = (
            Path(__file__).resolve().parents[3] / "sugar-lift-python-source" / "src"
        )
        if str(sibling_src) not in sys.path:
            sys.path.insert(0, str(sibling_src))
        from sugar_lift_python_source.source_oracle import (
            SourceUnavailable,
            resolve_source_memento,
        )
    return SourceUnavailable, resolve_source_memento


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
    SourceUnavailable, resolve_source_memento = _source_oracle_api()
    try:
        resolved = resolve_source_memento(workspace_root, memento)
    except SourceUnavailable as exc:
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
    left as a gap here, before a JSON-RPC response can be constructed.
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
    """Construct one closed enumeration result or leave a gap.

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


def _seat_roll_call_reporter(source_file, reporter) -> None:
    """Seat one audit consumer on an already prepared resident tree.

    Process residency owns parsed preparation, not consumer testimony.  A CID
    hit returns the prepared shell whose materialized nodes still carry the
    reporter used by the first opener (often ``NULL_REPORTER``).  Rebinding
    only ``SourceFile.reporter`` therefore leaves those nodes writing into the
    old channel and makes the roll call falsely clean.

    Walk the resident tree once, parent before child, rebinding and registering
    each existing node with this consumer's reporter.  Parent-first order also
    ensures any lazily materialized child is born on the same channel.  This
    does not parse, populate, or prepare the SourceFile again.
    """
    source_file.reporter = reporter
    for node in source_file.nodes():
        object.__setattr__(node, "reporter", reporter)
        reporter.register(node)


def _roll_call_audit_leaf(
    full_path: Path,
    file_rel: str,
    *,
    expected_source_cid: str | None = None,
) -> dict:
    from sugar_lift_py_tests.kit_rpc import AuditLeafEnvelopeDto

    """Project one construction roll call directly onto the legacy audit wire.

    The old wire names remain compatibility spelling only. They are populated
    at this serialization boundary from the one ``MinorityReport`` and its
    reporter testimony; no factory gap or audit model is reconstructed.
    """
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.roll_call import discharge
    from sugar_source_tree.tree import SourceFile

    from sugar_lift_py_tests.tree_enumerate import source_audit_from_report

    from sugar_source_tree.process_resident_file import get_resident

    reporter = CollectingReporter()
    resident_before_open = (
        get_resident(expected_source_cid) if expected_source_cid is not None else None
    )
    source_file = None
    try:
        source_file = SourceFile.from_path(str(full_path), reporter=reporter)
        _seat_roll_call_reporter(source_file, reporter)
        report = discharge(source_file)
    finally:
        if expected_source_cid is not None:
            _record_d3_residency_observation(
                expected_source_cid,
                {
                    "sourceCid": expected_source_cid,
                    "presentAtAuditOpen": resident_before_open is not None,
                    "auditOpenReusedResident": bool(
                        resident_before_open is not None
                        and source_file is resident_before_open.source_file
                    ),
                    "rootReporterSeatedAtAuditOpen": bool(
                        source_file is not None
                        and source_file.root.reporter is reporter
                    ),
                    "collectorRegisteredAtAuditExit": bool(reporter.registered),
                },
            )
    # ONE door: the same full-tuple presence projection as tree_enumerate.
    # Do not re-derive status by CID alone, and do not mix report.R with a
    # separately keyed warranted count (that pair already drifted).
    source_audit = source_audit_from_report(report, file_rel)

    demanded_source = f"module:{source_file.unit.source_cid}"
    panics = []

    # Key nodes by the roll-call identity (sealed CID + source coordinate +
    # kind) -- the SAME identity `MinorityReport` uses. One sealed fragment CID
    # is shared by equal source text at DISTINCT loci (e.g. `os` at 3:7 and Name
    # nodes at 197:28 / 206:14 all seal to one CID); those are distinct
    # obligations the minority counts separately. Keying panics by CID ALONE
    # would map every occurrence back to one node, emit duplicate owner
    # identities the Rust reader rejects, AND under-count R by fusing distinct
    # source sites. Carry the coordinate so each absent node yields its own
    # terminal locus, exactly matching `report.R`.
    def _coord_key(node) -> tuple:
        lc = node.line_col_span()
        return (node.fragment.seal().cid, lc.start_line, lc.start_col, node.kind)

    nodes_by_key: dict[tuple, Any] = {}
    for node in reporter.registered:
        nodes_by_key.setdefault(_coord_key(node), node)
    gaps_by_key: dict[tuple, Any] = {}
    for node, panic in reporter.gaps:
        key = _coord_key(node)
        nodes_by_key.setdefault(key, node)
        gaps_by_key.setdefault(key, panic)
    absent_keys = [
        (entry.cid, entry.start_line, entry.start_col, entry.kind)
        for entry in report.minority
    ]
    absent_seen = set(absent_keys)
    absent_keys.extend(key for key in gaps_by_key if key not in absent_seen)

    def _construction_trace(panic, *, owner: str, coordinate: str) -> list[dict]:
        trace = [
            {
                "kind": "source-construct",
                "constructOwner": owner,
                "coordinate": coordinate,
            }
        ]
        tb = getattr(panic, "__traceback__", None)
        while tb is not None:
            frame = tb.tb_frame
            trace.append(
                {
                    "kind": "dispatch-frame",
                    "module": str(frame.f_globals.get("__name__") or ""),
                    "qualname": frame.f_code.co_qualname,
                    "file": frame.f_code.co_filename,
                    "line": tb.tb_lineno,
                }
            )
            tb = tb.tb_next
        if len(trace) > 1:
            final = dict(trace[-1])
            final["kind"] = "panic-site"
            trace.append(final)
        return trace

    for key in absent_keys:
        node = nodes_by_key[key]
        panic = gaps_by_key.get(key)
        lc = node.line_col_span()
        locus = f"{file_rel}:{lc.start_line}:{lc.start_col}"
        terminal = (
            f"{file_rel}:{lc.start_line}:{lc.start_col}-"
            f"{lc.end_line}:{lc.end_col}[{node.kind}]"
        )
        panic_kind = (
            type(panic).__name__ if panic is not None else "UnaccountedConstruction"
        )
        reason = (
            panic.observed or str(panic)
            if panic is not None
            else f"{node.kind} registered but never answered the roll call"
        )
        authenticated_gap = {
            "blame": terminal,
            "kind": panic_kind,
            "nodeKind": node.kind,
            "reason": reason,
        }
        if panic is not None:
            owner = str(getattr(panic, "owner", node.kind))
            coordinate = terminal
            authenticated_gap.update(
                {
                    "owner": owner,
                    "coordinate": coordinate,
                    "observed": str(getattr(panic, "observed", reason)),
                    "requested": str(
                        getattr(panic, "requested", f"constructed {node.kind}")
                    ),
                    "fix": str(
                        getattr(panic, "fix", f"write {node.kind}.sugar")
                    ),
                    "entrance": "sugar.enumerate:facts:auditFrontier",
                    "observedEventType": (
                        f"{type(panic).__module__}.{type(panic).__qualname__}"
                    ),
                    "construction_trace": _construction_trace(
                        panic, owner=owner, coordinate=coordinate
                    ),
                }
            )
        panics.append(
            {
                # Closed-envelope discriminators required by the current Rust
                # reader. They construct no Python factory object and carry no
                # role; the direct roll-call answer lives in `gap` below.
                "kind": "ConstructionPanic",
                "status": "mandatory-panic",
                "reason": reason,
                "locus": locus,
                "demandedSource": demanded_source,
                "terminalGapLocus": terminal,
                "gap": authenticated_gap,
            }
        )

    # `kind` and `recoveryOverride` are closed-envelope discriminators required
    # by the current Rust reader. No recovery policy is consulted here; every
    # semantic value is projected from the roll call above.
    return AuditLeafEnvelopeDto.from_rpc(
        {
            "semanticCore": {
                "kind": "recovered-construction-audit",
                "recoveryOverride": True,
                "status": "failed" if panics else "clean",
                "panics": panics,
                "effects": [],
                "suppressedDescendants": [],
            },
            "auxiliaryRows": {"sourceAudit": source_audit},
        }
    ).to_rpc()


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
    if _BOUND_CONTRACT_REFS is not None:
        generation = options.get("contractRefs")
        if generation != {
            "catalogCid": _BOUND_CONTRACT_REFS.catalog_cid,
            "tableCid": _BOUND_CONTRACT_REFS.table_cid,
        }:
            raise ValueError(
                "semantic construction request has a stale contract-ref generation"
            )
    if _BOUND_CALL_CONTRACT_REFS is not None:
        generation = options.get("callContractRefs")
        if generation != {
            "catalogCid": _BOUND_CALL_CONTRACT_REFS.catalog_cid,
            "tableCid": _BOUND_CALL_CONTRACT_REFS.table_cid,
        }:
            raise ValueError(
                "semantic construction request has a stale call-contract-ref generation: "
                f"expected catalog={_BOUND_CALL_CONTRACT_REFS.catalog_cid} "
                f"table={_BOUND_CALL_CONTRACT_REFS.table_cid}, got {generation!r}"
            )
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
        if level == "contract-declarations":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"rows": []},
                }
            )
            return
        if level == "contract-demands":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"rows": _preconstruction_demand_rows(root)},
                }
            )
            return
        if level == "parameter-contract-link-units":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"rows": _parameter_contract_link_unit_rows(root)},
                }
            )
            return
        if level == "parameter-contract-resume":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"rows": _parameter_contract_resume_rows(options)},
                }
            )
            return
        if level == "context-manager-edges":
            if _BOUND_CONTRACT_REFS is None:
                raise ValueError(
                    "context-manager edge enumeration requires frozen contract refs"
                )
            from sugar_lift_python_source.source_oracle import path_source
            from sugar_source_tree.tree import SourceFile as _TreeSourceFile
            from sugar_lift_py_tests.context_manager_resolution import (
                TreeConstructionContextV1,
            )

            rows = []
            construction_context = TreeConstructionContextV1(_BOUND_CONTRACT_REFS)
            # One session for the whole package walk: the same dependency
            # definition projected for many consumer files amortizes once.
            from sugar_lift_python_source.resolution_session import walk_session_for

            package_session = walk_session_for(root)
            for source_path in sorted(root.rglob("*.py")):
                identity = path_source(str(source_path))
                source_file = _TreeSourceFile(
                    identity, construction_context=construction_context
                )
                from sugar_lift_python_source.manager_summary_derivation import (
                    populate_source_derived_resource_refs,
                )

                populate_source_derived_resource_refs(
                    source_file,
                    root=root,
                    path=source_path,
                    session=package_session,
                )
                for function in source_file.functions():
                    function_sugar = function.sugar()
                    rows.extend(
                        edge.to_rpc() for edge in function_sugar.context_manager_edges()
                    )
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"contextManagerEdges": rows},
                }
            )
            return
        if level == "source_files":
            # The source_files level IS SourceTree.fragments(): whole-file
            # fragments minted through the SourceOracle — identity without
            # parsing, no file read or hashed outside the oracle. The handler
            # only formats. An unreadable/undecodable file is a loud oracle
            # source-unavailable result recorded as a protocol gap, never served as a node
            # (previously it was hashed raw and masqueraded as enumerable).
            from sugar_lift_python_source.source_oracle import SourceUnavailable
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
                except SourceUnavailable as unavailable:
                    gaps.append(
                        {
                            "memento": _degenerate_file_memento(rel_path),
                            "reason": str(unavailable),
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
            "context-manager-resolutions",
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
                    SourceUnavailable,
                    path_source,
                )

                if level == "functions":
                    try:
                        identity = path_source(str(full_path))
                    except SourceUnavailable as unavailable:
                        _send_enumerate_result(
                            msg_id, [], [{"memento": at, "reason": str(unavailable)}]
                        )
                        return
                    _src, _fname, file_cid = identity
                    sf = _tree.source_file(full_path)
                    memento = _tree.module_definition_memento(sf, file_rel, file_cid)
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
                    expected_source_cid = None
                    if isinstance(at, dict):
                        expected_source_cid = at.get("source_cid") or at.get(
                            "file_cid"
                        )
                    leaf = _roll_call_audit_leaf(
                        full_path,
                        file_rel,
                        expected_source_cid=(
                            str(expected_source_cid)
                            if isinstance(expected_source_cid, str)
                            else None
                        ),
                    )
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

            if level in {"functions", "context-manager-resolutions"}:
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
                    SourceUnavailable,
                    path_source,
                )
                from sugar_source_tree.tree import SourceFile as _TreeSourceFile

                try:
                    identity = path_source(str(full_path))
                except SourceUnavailable as unavailable:
                    _send_enumerate_result(
                        msg_id, [], [{"memento": at, "reason": str(unavailable)}]
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
                # Always inject construction context. Leaving it None makes every
                # With unconditionally RuntimeSelectedContextManager (false red);
                # production bind_contract_refs replaces the provisional gap table.
                from sugar_lift_py_tests.context_manager_resolution import (
                    TreeConstructionContextV1,
                )

                if (
                    _BOUND_CONTRACT_REFS is not None
                    or _BOUND_CALL_CONTRACT_REFS is not None
                ):
                    construction_context = TreeConstructionContextV1(
                        (
                            _BOUND_CONTRACT_REFS
                            if _BOUND_CONTRACT_REFS is not None
                            else provisional_contract_refs_from_demands(root)
                        ),
                        call_contract_refs=_BOUND_CALL_CONTRACT_REFS,
                        workspace_root=str(root),
                    )
                else:
                    construction_context = tree_construction_context_for_workspace(root)
                tree_file = _TreeSourceFile(
                    identity, construction_context=construction_context
                )
                from sugar_lift_python_source.manager_summary_derivation import (
                    populate_source_derived_resource_refs,
                )
                from sugar_lift_python_source.resolution_session import walk_session_for

                # Walk-scoped multi-resolve owner: same session as other opens
                # under this workspace root (census / re-open amortization).
                from sugar_source_tree.panic import (
                    ContextManagerResolutionConstructionGap,
                )

                try:
                    populate_source_derived_resource_refs(
                        tree_file,
                        root=root,
                        path=full_path,
                        session=walk_session_for(root),
                    )
                except ContextManagerResolutionConstructionGap:
                    # Enumeration owns attendance, not construction. Provider-call
                    # projection can reach an unresolved With while enriching this
                    # table; retain the already-authenticated provisional rows so
                    # the context-manager edge conserves exact coordinates. The
                    # construction demand still reaches and reports this same panic.
                    pass
                if level == "context-manager-resolutions":
                    from sugar_lift_py_tests.context_manager_resolution import (
                        context_manager_resolution_outcome,
                        effective_context_manager_resolutions_for_source,
                    )

                    resolution_nodes = []
                    for coordinate, resolution in sorted(
                        effective_context_manager_resolutions_for_source(
                            construction_context, source_cid=file_cid
                        ).items()
                    ):
                        resolution_nodes.append(
                            {
                                "memento": {
                                    "kind": "context-manager-resolution",
                                    "file": file_rel,
                                    "source_cid": file_cid,
                                    "coordinate": coordinate.wire(),
                                },
                                "audit": {
                                    "observedEventType": (
                                        f"{type(resolution).__module__}."
                                        f"{type(resolution).__qualname__}"
                                    ),
                                    "outcome": context_manager_resolution_outcome(
                                        resolution
                                    ),
                                },
                                "payload": None,
                            }
                        )
                    _send_enumerate_result(msg_id, resolution_nodes, [])
                    _log_enumeration_demand(
                        str(level), at, cache="miss", started=demand_started
                    )
                    return
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
                        [
                            {
                                "memento": at,
                                "reason": "implications requires a call-site memento",
                            }
                        ],
                    )
                    return
                sf = _tree.source_file(full_path)
                span = at.get("span") if isinstance(at, dict) else None
                source_assert, assert_node = _tree.temporally_rewritten_assert(sf, span)
                if source_assert is None or assert_node is None:
                    _send_enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": "no call site for exact memento; leaving implication substitution open",
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
                targets = []
                seen_targets = set()
                implication_gaps: List[Dict[str, Any]] = []
                for call in _tree.call_nodes_in_assert(sf, span):
                    name = call.func.id
                    if name in seen_targets:
                        continue
                    seen_targets.add(name)
                    targets.append(name)
                    try:
                        fn = _tree.resolve_function_for_call(call)
                    except _tree.FunctionBindingMiss as miss:
                        # Named refuse from the construction door — gap row, not
                        # soft continue that reopens pre-#6946 soft-None.
                        implication_gaps.append(
                            {
                                "memento": at,
                                "reason": (
                                    f"FunctionBindingMiss name={miss.name!r} "
                                    f"reason={miss.reason}"
                                ),
                            }
                        )
                        continue
                    # No except/continue. Throws from unfinished body sugar rise.
                    # FunctionBindingMiss is named refuse (gap above); unfinished
                    # body sugar must not be reclassified as empty candidates.
                    # JOIN defect with sin-cluster-4: enumeration door must not
                    # re-preserve the Exception swallow around function_contract_rows.
                    def_memento, rows = _tree.function_contract_rows(fn, file_rel)
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
                    msg_id,
                    [node],
                    implication_gaps,
                    term_tables=[term_table.nodes],
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
                from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
                from sugar_source_tree.panic import SugarNotWritten

                sf = _tree.source_file(full_path)
                term_table = TermTableBuilder()
                universes = []  # (name, memento_dict, contract_dto)
                gaps = []
                # Phase-3: functions whose parameter-contract demands the caller
                # already discharged (fold -> resume) are served from the resume
                # path, not reconstructed here. Skipping them keeps post()
                # resume-exclusive: a plain universe enumerate (empty skip set)
                # of a pending-demand function STILL panics.
                resolved_mementos = set(
                    options.get("resolvedContinuationMementos") or []
                )
                for fn in sf.functions():
                    if (
                        resolved_mementos
                        and _memento_continuation_key(
                            _tree.function_def_memento(fn, file_rel).to_rpc()
                        )
                        in resolved_mementos
                    ):
                        continue
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
                # Abstract contracts keyed by authenticated def identity
                # (source_cid), never by callee spelling. Spelling by_name[t]
                # reopened first-match after FunctionBindingMiss (#6946 residual).
                by_source_cid = {
                    m["source_cid"]: (m, d) for _n, m, d in universes
                }
                cued = []
                cue_gaps: List[Dict[str, Any]] = []
                seen = set()
                for call in calls:
                    t = call.func.id
                    if t in seen:
                        continue
                    seen.add(t)
                    targets.append(t)
                    # Resolve by binding/coordinate at the call site — not
                    # first-match-by-spelling. Miss is a named throw; the dig
                    # records a gap and does not fall through to a spelling table.
                    try:
                        fn = _tree.resolve_function_for_call(call)
                    except _tree.FunctionBindingMiss as miss:
                        cue_gaps.append(
                            {
                                "memento": at,
                                "reason": (
                                    f"FunctionBindingMiss name={miss.name!r} "
                                    f"reason={miss.reason}"
                                ),
                            }
                        )
                        continue
                    # A call IS substitution: ground args fill the pre, so the
                    # dig serves the contract AS APPLIED at this call (a concrete
                    # iterable unrolls the callee's loop here; the fold
                    # coordinate collapses; a symbolic while's condition grounds
                    # and unrolls). An arg still carrying a hole leaves the
                    # abstract contract standing -- the callable floor. The
                    # applied dig is attempted even when the ABSTRACT universe is
                    # a gap: the applied substitution can succeed exactly where
                    # the abstract is still a hole (that is the whole point of
                    # filling the pre). Arity is the binder's job (vararg packs,
                    # defaults fill) — never len(args)==len(params).
                    if _tree._args_are_ground(call):
                        try:
                            keywords = tuple(
                                (keyword.arg, keyword.value)
                                for keyword in call.keywords
                                if keyword.arg is not None
                            )
                            memento, rows = _tree.applied_contract_rows(
                                fn, tuple(call.args), file_rel, keywords=keywords
                            )
                        except SugarNotWritten:
                            # Typed tree frontier: abstract identity fallback.
                            rows = None
                        except SourceCallBindingGap as bind_gap:
                            cue_gaps.append(
                                {
                                    "memento": at,
                                    "reason": f"SourceCallBindingGap: {bind_gap}",
                                }
                            )
                            rows = None
                        if rows:
                            cued.append(_node(memento.to_rpc(), rows[0]))
                            continue
                    # Abstract contract for THIS authenticated definition only.
                    def_rpc = _tree.function_def_memento(fn, file_rel).to_rpc()
                    abstract = by_source_cid.get(def_rpc["source_cid"])
                    if abstract is not None:
                        cued.append(_node(*abstract))
                    else:
                        cue_gaps.append(
                            {
                                "memento": at,
                                "reason": (
                                    "resolved callee has no abstract universe row "
                                    f"(name={t!r} source_cid={def_rpc['source_cid']})"
                                ),
                            }
                        )
                dig_gaps = list(cue_gaps)
                if not cued and not dig_gaps:
                    dig_gaps.append(
                        {
                            "memento": at,
                            "reason": (
                                "no universe for the callee(s) this call site cues: "
                                f"{targets or 'none'}"
                            ),
                        }
                    )
                _send_enumerate_result(
                    msg_id,
                    cued,
                    dig_gaps,
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
                            if (
                                seek
                                and at is not None
                                and not _memento_matches(memento, at)
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
    except SourceTreePanic:
        # Preserve the concrete tree taxonomy for the resident RPC boundary;
        # VocabularyMissing, BackendDefect, SugarNotWritten, and its
        # RuntimeSelected specialization are different repair roles. The
        # outer serve loop serializes them as typed-loud JSON-RPC errors
        # (never unclassified exit 1).
        raise
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
    sequence_path = os.environ.get("SUGAR_RPC_SEQUENCE_LOG")
    if sequence_path:
        suffix = ""
        if method == ENUMERATE_RPC_METHOD and isinstance(params, dict):
            suffix = f":{params.get('level', '')}"
        with Path(sequence_path).open("a", encoding="utf-8") as sequence_log:
            sequence_log.write(f"{method}{suffix}\n")

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
    elif method == BIND_CONTRACT_REFS_RPC_METHOD:
        from sugar_lift_py_tests.context_manager_resolution import (
            decode_resolved_contract_refs,
        )

        global _BOUND_CONTRACT_REFS
        if not isinstance(params, dict) or set(params) != {"contractRefs"}:
            raise ValueError("malformed preconstruction contract-ref bind")
        installed = decode_resolved_contract_refs(params["contractRefs"])
        if (
            _BOUND_CONTRACT_REFS is not None
            and _BOUND_CONTRACT_REFS.table_cid != installed.table_cid
        ):
            raise ValueError("contract-ref generation is already frozen")
        _BOUND_CONTRACT_REFS = installed
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tableCid": installed.table_cid,
                },
            }
        )
    elif method == BIND_CALL_CONTRACT_REFS_RPC_METHOD:
        from sugar_lift_py_tests.call_contract_resolution import (
            decode_resolved_call_contract_refs,
        )

        global _BOUND_CALL_CONTRACT_REFS
        installed = decode_resolved_call_contract_refs(params)
        if (
            _BOUND_CALL_CONTRACT_REFS is not None
            and _BOUND_CALL_CONTRACT_REFS.table_cid != installed.table_cid
        ):
            raise ValueError("call-contract-ref generation is already frozen")
        _BOUND_CALL_CONTRACT_REFS = installed
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tableCid": installed.table_cid},
            }
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


def _serialize_source_call_binding_gap(exc: BaseException) -> dict[str, Any] | None:
    """JSON-RPC data for SourceCallBindingGap only — never ConstructionPanic."""
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    if isinstance(exc, SourceCallBindingGap):
        return {
            "kind": "typed-loud",
            "exception_type": type(exc).__name__,
            "stage": "dispatch",
            "diagnostic": {
                "owner": "SourceCallFrame.bind_node_actuals",
                "observed": str(exc),
                "requested": "every call actual consumed by the authenticated frame",
                "fix": "bind or reject the unconsumed actual at the call frame",
            },
        }
    return None


def _serve() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

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
        except ConstructionPanic as panic:
            # Fatal to this resident: emit a protocol error then die. Never
            # convert ConstructionPanic into a successful result, None, or
            # keep-serving soft continue. Parent may use --allow-failed-components
            # to continue other components after this process exits.
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
            raise SystemExit(1) from panic
        except SourceTreePanic as panic:
            # Tree-gap (not ConstructionPanic): serialize as JSON-RPC error and
            # keep serving. Never exit 1 unclassified after the client has a row.
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {
                        "code": -32001,
                        "message": str(panic),
                        "data": {
                            "kind": "typed-loud",
                            "exception_type": type(panic).__name__,
                            "stage": "dispatch",
                            "diagnostic": {
                                "owner": panic.owner,
                                "observed": panic.observed,
                                "requested": panic.requested,
                                "fix": panic.fix,
                            },
                        },
                    },
                }
            )
            _log_resident_profile(request_count, msg.get("method"))
            continue
        except RecursionError as exc:
            # C-stack overflow: typed frame, keep resident for the next request.
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {
                        "code": -32603,
                        "message": f"recursion limit exceeded: {exc}",
                        "data": {
                            "exception_type": "RecursionError",
                            "stage": "dispatch",
                        },
                    },
                }
            )
            _log_resident_profile(request_count, msg.get("method"))
            continue
        except SourceCallBindingGap as exc:
            # Typed process membrane: serialize and keep serving.
            # Unrelated Exceptions are not held — they rise (honorable).
            typed = _serialize_source_call_binding_gap(exc)
            assert typed is not None
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {
                        "code": -32001,
                        "message": str(exc),
                        "data": typed,
                    },
                }
            )
            _log_resident_profile(request_count, msg.get("method"))
            continue
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
