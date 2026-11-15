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

from sugar_lift_py_tests.call_symbol import call_target
from sugar_lift_py_tests.effect import SourceOracleEffect, effect_reason, effect_status
from sugar_lift_py_tests.kit_rpc import (
    EffectDto,
    LiftReportPayloadDto,
    RecoveredEffectDto,
    SuppressedAuditLocusDto,
)
from sugar_lift_py_tests.kit_rpc.rpc_value import to_rpc_value
from sugar_lift_py_tests.source_provenance import (
    kit_source_provenance,
    loaded_python_source_identity,
)
from sugar_source_tree.panic import SourceTreePanic

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
# Phase-1->3 cross-request continuation: the link units enrolled in phase 1,
# keyed by linkUnitCid, so resume checks a resolution set against the unit it
# was folded for.
_RETAINED_LINK_UNITS = {}
# The per-source With demand table by resolved workspace root: the one
# derivation of a With item's row (``_PerSourceDemandRows``), memoized so a
# second open of the same root reuses the sources already derived. Nothing
# installs a table here in place of the derivation (#7757 item 46).
_PROVISIONAL_CONTRACT_REFS_BY_ROOT: Dict[str, Any] = {}
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


def _context_manager_rows_for_paths(paths, *, root: Path) -> List[Dict[str, Any]]:
    """The typed With occurrences of exactly these files, in the order given.

    A With row is a function of its own file; the per-source door below is
    its only caller. This pass owns only the structural fact that a typed
    WithItem exists, without constructing any Sugar; import authority is
    joined from ``_call_use_rows_for_units`` at the identical source
    coordinate, never reconstructed from spellings.

    Each file is opened by the opener's first stage (``_open_at_seat``), at
    the seat the opener reads, so the row reads the same bytes at the same
    seat the enumerate levels construct. It opens with no construction
    context: these rows are what the context's table is built from. The unit
    it parses is the one the opener later attaches its context to; the file is
    parsed once.
    """
    from sugar_lift_py_tests.context_manager_resolution import UNDECIDED_GAP_KIND
    from sugar_lift_python_source.source_oracle import SourceUnavailable
    from sugar_source_tree.nodes import AsyncWith, With

    rows: List[Dict[str, Any]] = []
    for path in paths:
        try:
            source_file = _open_at_seat(path, root=Path(root))
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
                        "gapKind": UNDECIDED_GAP_KIND,
                    }
                )
    return rows


def _context_manager_resolutions_from_demand_rows(rows):
    """Typed gap resolution per With demand row of one source.

    The one projection from demand rows to construction refs; the per-source
    door is its only caller.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        UNDECIDED_GAP_KIND,
        ContextManagerResolutionGapV1,
        SourceFragmentCoordinateV1,
        _hash_json,
    )

    resolutions = {}
    for row in rows:
        site = SourceFragmentCoordinateV1.decode(row["useSite"])
        preimage = {
            key: row[key]
            for key in ("useSite", "targetSymbol", "importSignature", "expectedKind")
        }
        # A demand row's resolution is undecided until derivation answers it:
        # one statement, never a label read from the row or a default
        # (#7757 item 4).
        resolutions[site] = ContextManagerResolutionGapV1(
            _hash_json(preimage),
            site,
            row.get("targetSymbol"),
            UNDECIDED_GAP_KIND,
            (),
        )
    return resolutions


class _PerSourceDemandRows:
    """The one derivation of the With demand rows: one source CID at a time.

    Opening this reads and content-addresses the enrolled files (the import
    join needs every module's identity) and parses nothing. Rows for a source
    are the With items of the files carrying that source CID, read from the
    one opened file (``_open_at_seat``), each joined to the authenticated
    import use at its coordinate -- every row's use site names its own source
    CID. Files with identical bytes share one source CID and are derived
    together, in tree order.

    What still reads a row (#7757 item 46): ``With``'s require door reads its
    item's row on every construction (``With._seated_manager_resolution``),
    and the board door's with-item census projects one row per item
    (``effective_context_manager_resolutions_for_source``). Every row is the
    ``undecided`` gap: the manager is what the head reduces to.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._units_by_source_cid: Dict[str, list] | None = None
        self._module_identities: Dict[str, Dict[str, Any]] | None = None

    def _open(self) -> Dict[str, list]:
        if self._units_by_source_cid is None:
            units = _corpus_source_units(self.root)
            grouped: Dict[str, list] = {}
            for unit in units:
                grouped.setdefault(unit[2], []).append(unit)
            self._module_identities = _module_identities_for_units(self.root, units)
            self._units_by_source_cid = grouped
        return self._units_by_source_cid

    def source_cids(self) -> tuple[str, ...]:
        return tuple(self._open())

    def identity_cid(self) -> str:
        """Content address of what every row here is a function of."""
        from sugar_lift_python_source.canonical import cid_of_json

        grouped = self._open()
        return cid_of_json(
            {
                "kind": "per-source-provisional-demand-table",
                "sources": [
                    {
                        "path": path.relative_to(self.root).as_posix(),
                        "sourceCid": source_cid,
                    }
                    for source_cid, units in grouped.items()
                    for path, _source, _cid in units
                ],
            }
        )

    def rows_for_source(self, source_cid: str) -> List[Dict[str, Any]]:
        units = self._open().get(source_cid, ())
        assert self._module_identities is not None
        return _join_call_identity_into_with_demands(
            _call_use_rows_for_units(self.root, units, self._module_identities),
            _context_manager_rows_for_paths(
                [path for path, _source, _cid in units], root=self.root
            ),
        )


def per_source_provisional_contract_refs(root: Path):
    """Provisional With-demand refs whose rows are derived per source, on demand.

    A lookup pays for the source it asks about and no other.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        PerSourceResolutionsV1,
        ResolvedContractRefsV1,
    )

    demands = _PerSourceDemandRows(root)

    def derive(source_cid: str):
        return _context_manager_resolutions_from_demand_rows(
            demands.rows_for_source(source_cid)
        )

    table_cid = demands.identity_cid()
    return ResolvedContractRefsV1(
        table_cid,
        table_cid,
        PerSourceResolutionsV1(demands.source_cids, derive),
    )


def provisional_contract_refs_from_demands(root: Path):
    """One typed gap row per enrolled With demand: the table every open reads.

    The one door onto the With demand rows (#7757 item 46): the enumerate
    levels, the board door, the supervised worker and every instrument come
    here, and nothing installs a table in its place.

    Each demand lands as ``ContextManagerResolutionGapV1`` of the one kind
    ``undecided`` (#7757 item 4): its manager is what the head reduces to
    (``With._reduced_manager_sugar``). The row must still be there: an item
    nobody seated a row for halts by name at the require door
    (``With._prebound_manager_resolution``).

    Rows are derived per source on first demand: asking about one file costs
    that file, not the corpus. Process-memoized by resolved root so a second
    open reuses the sources already derived.
    """
    key = str(Path(root).resolve())
    cached = _PROVISIONAL_CONTRACT_REFS_BY_ROOT.get(key)
    if cached is not None:
        return cached
    refs = per_source_provisional_contract_refs(Path(root))
    _PROVISIONAL_CONTRACT_REFS_BY_ROOT[key] = refs
    return refs


def clear_provisional_contract_refs_memo() -> None:
    """Drop process demand-table memo (tests / hermetic process reuse)."""
    _PROVISIONAL_CONTRACT_REFS_BY_ROOT.clear()


def tree_construction_context_for_workspace(
    root: Path,
    *,
    contract_refs=None,
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
    return TreeConstructionContextV1(refs, workspace_root=str(root))


def _locus_root(
    path: Path, *, root: Path, source_workspace_root: Path | None = None
) -> Path:
    """The root a file's seat is stated against: one derivation, for every open.

    ``source_workspace_root`` when the driver carries one; otherwise the
    install root the file's own distribution records; otherwise ``root``.
    """
    from sugar_lift_python_source.source_oracle import install_root_for

    # TWO ROOTS, not one. `root` is the WORKSPACE authority: which tree this
    # open belongs to, what `file_rel` resolves against, which walk session and
    # construction context own it. `source_workspace_root` is the LOCUS
    # authority: the root the minted address is stated against. For a
    # first-party tree they coincide and this reads as before. For an INSTALLED
    # corpus they must not: seats are recorded relative to the install root, so
    # opening `.../site-packages/pandas/_testing/_hypothesis.py` under
    # `root=.../site-packages/pandas` mints `_testing/_hypothesis.py` -- not a
    # different spelling of the seat, an address no other checkout resolves,
    # which `require_recorded_seat` refuses by name.
    #
    # The locus root is DERIVED ONCE, from the distribution's own manifest
    # (`install_root_for`): by the driver when it carries one, else here.
    # Nothing on this path adds or strips a package prefix at comparison time:
    # there is one spelling, minted once, against the root that states it.
    if source_workspace_root is not None:
        return Path(source_workspace_root)
    install_root = install_root_for(str(path))
    return Path(root) if install_root is None else Path(install_root)


def _read_at_seat(
    path: Path, *, root: Path, source_workspace_root: Path | None = None
) -> tuple[str, str, str]:
    """The file's bytes read at its seat: the oracle's ``(source, seat, CID)``."""
    from sugar_lift_python_source.source_oracle import workspace_path_source

    locus_root = _locus_root(
        path, root=root, source_workspace_root=source_workspace_root
    )
    return workspace_path_source(str(path), root=str(locus_root))


def _open_at_seat(
    path: Path | None,
    *,
    root: Path | None,
    source_workspace_root: Path | None = None,
    backend=None,
    reporter=None,
    construction_context=None,
    seated: tuple[str, str, str] | None = None,
):
    """The opener's first stage: the one open of a file, at its seat.

    A file becomes a node tree here and nowhere else (#7757 item 5): its bytes
    are read at its seat (``_read_at_seat``) and parsed into the resident unit.
    ``open_source_file_for_construction`` is this stage under a construction
    context. The two step-3 readers (the With rows and the
    lexical import pass) call this stage with no context, because their rows
    are what that context's table is built from; they read the same seat, the
    same bytes and the same resident unit the opener does. The files are step
    2's file list; no dependency module is opened anywhere.

    The one entry: this is the only caller of
    ``process_resident_file._source_file_from_identity``, and every other
    construction of a ``SourceFile`` comes through here (``SourceFile(identity)``
    forwards here with ``seated=identity``; the source oracle, the memento
    resolvers, the typed parse and the contract-expression reader pass the
    identity they read as ``seated``). So no caller can pick a resident unit up
    some other way.

    One parse per file: opened with no context, the unit is parsed once with no
    context; the opener's open under its context attaches that context to the
    same unit (``SourceUnit.attach_construction_context``) rather than parsing
    the file again. Opened after the opener, a contextless open gets the
    opener's unit.

    ``seated`` is the identity the caller already read at this seat (the opener
    reads once to consult its memo; the oracle reads before it parses);
    otherwise it is read here from ``path`` and ``root``.
    ``reporter=None`` leaves a resident file's reporter as it is.
    """
    from sugar_source_tree.process_resident_file import _source_file_from_identity

    if seated is None and (path is None or root is None):
        raise TypeError(
            "_open_at_seat reads a file at its seat: it takes a path and its "
            "root, or an identity already read (seated=)"
        )
    identity = (
        seated
        if seated is not None
        else _read_at_seat(
            path, root=root, source_workspace_root=source_workspace_root
        )
    )
    return _source_file_from_identity(
        identity,
        backend=backend,
        reporter=reporter,
        construction_context=construction_context,
    )


def _enumerate_contract_refs(root: Path):
    """The table every ``sugar.enumerate`` level constructs against: the
    provisional demand table for ``root`` (process-memoized per root).
    """
    return provisional_contract_refs_from_demands(root)


def _open_session(root: Path, resolution_session=None):
    """The resolution session an open runs under: the caller's, else the
    walk-scoped session for ``root``, whose roster is step 2's file list for
    ``root`` (``project_file_roster``) and nothing else."""
    from sugar_lift_python_source.resolution_session import (
        project_file_roster,
        walk_session_for,
    )

    if resolution_session is not None:
        return resolution_session
    return walk_session_for(root, enrolled_distributions=project_file_roster(root))


def _context_minter(table, root: Path):
    """Mints the opener's construction context on ``table`` for ``root``."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )

    return lambda: TreeConstructionContextV1(table, workspace_root=str(root))


def construction_context_for_open(
    path: Path,
    *,
    root: Path,
    contract_refs=None,
    resolution_session=None,
    source_workspace_root: Path | None = None,
):
    """The context the opener opens this file under when the caller names none.

    Built on ``contract_refs``, else on ``_enumerate_contract_refs`` (the Rust
    prebind's bound refs when installed), and minted once per file and
    authority (``process_resident_file.open_context``). A caller that passes it
    to the opener explicitly (the audit leaf) and a caller that passes nothing
    (the enumerate levels) open the same unit: one parse.
    """
    from sugar_source_tree.process_resident_file import open_context

    session = _open_session(root, resolution_session)
    table = contract_refs if contract_refs is not None else _enumerate_contract_refs(root)
    _source, seat, source_cid = _read_at_seat(
        path, root=root, source_workspace_root=source_workspace_root
    )
    return open_context(
        source_cid,
        seat,
        str(root),
        (table, session),
        mint=_context_minter(table, root),
    )


def open_source_file_for_construction(
    path: Path,
    *,
    root: Path,
    reporter=None,
    contract_refs=None,
    construction_context=None,
    resolution_session=None,
    source_workspace_root: Path | None = None,
):
    """THE one way a Python file is opened for construction (#7757 item 5).

    The open (``_open_at_seat``) reads the file at its seat and parses it
    under a construction context.  Nothing reads a function body here: a
    ``with``'s manager is what its head reduces to, at reduce (#7757).
    There is no other open, so every reader -- every ``sugar.enumerate``
    level, the audit leaf, the console census, the caller-parameter
    contract, the attribution instruments, the scripts -- reads the same
    tree.

    The context, when the caller names none, is built on
    ``_enumerate_contract_refs``: the Rust prebind's bound refs when installed,
    otherwise the provisional demand table for ``root``. ``contract_refs``
    names a table already derived for this root (a census shares one);
    ``construction_context`` a frozen context the caller already holds. The
    context the opener builds is minted once per file and authority
    (``construction_context_for_open``), so passing it back explicitly is the
    same open as passing nothing.

    One parse per file (#7757 item 5): when the step-3 readers already opened
    the file through the first stage, which parses with no context, the first
    stage attaches this open's context to that unit instead of parsing again.

    ``resolution_session`` owns every source-resolution memo for this open. When
    omitted, this door uses the walk-scoped session for ``root``, whose roster is
    step 2's file list for ``root`` (``project_file_roster``) and nothing else,
    so multi-file census / re-open of the same content amortize projection under
    one workspace authority (see ``walk_session_for``). Pass an explicit session
    to isolate.

    A file is opened once per authority: the same bytes at the same seat,
    under the same table (or caller-held context), the same session and the
    same ``root``, return the unit this door already opened
    (``process_resident_file.get_opened``), with its reporter rebound and its
    roll call reseated. A walk that reopens its files --
    the enumerate levels, the caller-parameter contract asked once per
    question -- pays the parse once.
    """
    from sugar_source_tree.process_resident_file import (
        get_opened,
        open_context,
        remember_opened,
    )
    from sugar_source_tree.reporter import NULL_REPORTER

    if reporter is None:
        reporter = NULL_REPORTER
    # Multi-resolve owner: walk-scoped session when none given so census and
    # same-content re-open share projection memos under one root. Its roster
    # is the files this root lists (step 2), with no extras.
    session = _open_session(root, resolution_session)
    seated = _read_at_seat(
        path, root=root, source_workspace_root=source_workspace_root
    )
    _source, seat, source_cid = seated
    # The authority this open constructs under: the table the opener builds
    # its own context on, with the session. A context the caller holds that
    # the opener did not mint is its own authority.
    if construction_context is None:
        table = (
            contract_refs
            if contract_refs is not None
            else _enumerate_contract_refs(root)
        )
        construction_context = open_context(
            source_cid,
            seat,
            str(root),
            (table, session),
            mint=_context_minter(table, root),
        )
    else:
        table = getattr(construction_context, "contract_refs", None)
    own = (table, session)
    if open_context(source_cid, seat, str(root), own) is construction_context:
        authority = own
    else:
        authority = (construction_context, session)
    source_file = get_opened(source_cid, seat, str(root), authority)
    opened_before = source_file is not None
    if opened_before:
        source_file.reporter = reporter
    else:
        source_file = _open_at_seat(
            path,
            root=root,
            source_workspace_root=source_workspace_root,
            reporter=reporter,
            construction_context=construction_context,
            seated=seated,
        )
    # THE BINDING LEAK (#7171 class, third costume). `SourceFile.__init__` on a
    # process-residency HIT rebinds `self.reporter` and nothing else: the shell
    # was already materialized, so every node in it still carries the FIRST
    # opener's reporter -- `NULL_REPORTER` whenever that first open was a
    # dependency resolution. Passing `reporter=` therefore does NOT seat the
    # tree; it only relabels the file object, and the nodes keep writing into a
    # channel that owns no registration. A memo hit is the same case.
    #
    # Seat the roll call onto the existing nodes, the same walk the audit leaf
    # does. This parses nothing and prepares nothing.
    if reporter is not NULL_REPORTER:
        _seat_roll_call_reporter(source_file, reporter)
    if opened_before:
        return source_file
    remember_opened(source_cid, seat, str(root), authority, source_file)
    return source_file


def _corpus_source_units(root: Path) -> list:
    """``(path, source, source_cid)`` per readable enrolled file, in tree order."""
    from sugar_lift_python_source.source_oracle import SourceUnavailable, path_source
    from sugar_source_tree.tree import SourceTree

    units = []
    for path in SourceTree(root).paths():
        try:
            source, _filename, source_cid = path_source(str(path))
        except SourceUnavailable:
            continue
        units.append((path, source, source_cid))
    return units


def _module_identities_for_units(root: Path, units) -> Dict[str, Dict[str, Any]]:
    """Module name -> authenticated module identity for the whole corpus."""
    from sugar_lift_py_tests.import_binding import module_name_for_path

    return {
        module_name_for_path(root, path): {
            "kind": "authenticated-python-module",
            "schemaVersion": "1",
            "moduleName": module_name_for_path(root, path),
            "sourceCid": source_cid,
        }
        for path, _source, source_cid in units
    }


def _call_use_rows_for_units(
    root: Path, units, module_identities
) -> List[Dict[str, Any]]:
    """Imported call uses of exactly these units, against corpus identities.

    The lexical pass's imported plain calls, by their authenticated use
    sites. Read only by the With join; never rows of the demand table.
    """
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    rows: List[Dict[str, Any]] = []
    for path, source, source_cid in units:
        enrolled, _outcomes = authenticated_import_uses(
            root, path, source, source_cid, module_identities
        )
        rows.extend(enrolled)
    return rows


def _parameter_contract_resume(options: Dict[str, Any]) -> None:
    """Phase-3 resume: verify the presented resolution set is bound to the
    link unit retained for this linkUnitCid and names no demand. A lost
    continuation or any stale/foreign set raises a loud ConstructionPanic.

    The resume answers the resolution only; it states no row. Every
    function's rows, its refused member and its undecided members come from
    the universe full scan, the one door (#7757)."""
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
            requested="the link unit enrolled in phase 1",
            fix="resume in the SAME server session that enrolled the link unit",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
    try:
        resolution_set = ParameterContractResolutionSetV1.from_value(raw_set)
        resume_apply_resolutions(retained, resolution_set)
    except (ResumeStalePanic, ValueError) as exc:
        construction_panic_gap(
            owner="parameter-contract-resume",
            blame=retained.parameter_owned_contract.contract_cid,
            observed=str(exc),
            requested="an exact, replay-bound ParameterContractResolutionSetV1",
            fix="present the fold's authenticated resolution set for THIS continuation",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )


def _parameter_contract_link_unit_rows(root: Path) -> List[Dict[str, Any]]:
    """Phase-1 enrollment: one closed ParameterContractLinkUnitV1 per function
    with a formal, read off the def itself (``function_link_unit``): its name
    and formal coordinates. Nothing of the body is reduced here, so nothing
    here refuses a function or states a row of it: the universe full scan is
    the one door for those (#7757). Each unit is retained keyed by
    linkUnitCid so Phase-3 resume checks its resolution set against it.

    Nothing is soft-skipped: a refusal propagates to the typed-loud JSON-RPC
    error handler.
    """
    from sugar_lift_py_tests import tree_enumerate as _tree
    from sugar_lift_py_tests.caller_parameter_contract import function_link_unit
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceTree

    global _RETAINED_LINK_UNITS
    _RETAINED_LINK_UNITS = {}
    rows: List[Dict[str, Any]] = []
    # Step 2's file list, the one `source_files` serves (#7757 item 45).
    for source_path in SourceTree(root).paths():
        file_rel = str(source_path.relative_to(root))
        # No broad skip: a source that cannot be read is a LOUD failure, never a
        # silently omitted file. The tree opens through the one construction
        # door every enumerate level opens it through.
        sf = open_source_file_for_construction(
            source_path, root=root, reporter=CollectingReporter()
        )
        for fn in sf.functions():
            def_memento = _tree.function_def_memento(fn, file_rel).to_rpc()
            # No broad skip: a projection failure is LOUD (it escapes), never a
            # silently dropped link unit. `None` is a def with no formal.
            unit = function_link_unit(fn, def_memento)
            if unit is None:
                continue
            _RETAINED_LINK_UNITS[unit.link_unit_cid] = unit
            rows.append(unit.to_value())
    return rows


def _join_call_identity_into_with_demands(
    call_rows: List[Dict[str, Any]], cm_rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """The With demands, each joined to the authenticated call at its coordinate.

    Its call coordinate supplies the authenticated import binding. The table
    carries With demands only: no call-contract demand or export row is
    enrolled beside them (nothing reads one)."""
    from sugar_lift_py_tests.context_manager_resolution import UNDECIDED_GAP_KIND

    calls_by_site = {
        json.dumps(row["useSite"], sort_keys=True): row for row in call_rows
    }
    for row in cm_rows:
        site = json.dumps(row["useSite"], sort_keys=True)
        call = calls_by_site.get(site)
        if call is None:
            row["targetSymbol"] = None
            row["gapKind"] = UNDECIDED_GAP_KIND
            continue
        target = call["targetSymbol"]
        row["targetSymbol"] = target.removeprefix("python:")
        row["importBindingCid"] = call["importBindingCid"]
        row["importBinding"] = call["importBinding"]
        row["authenticatedImportUse"] = call["authenticatedImportUse"]
        row["gapKind"] = None
    return cm_rows


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
                # lift is not a kit method: full-tree construction is sugar.enumerate only
                # {"name": "lift", "required": True},
                {"name": "sugar.plugin.lift_implications", "required": False},
                {"name": "shutdown", "required": False},
            ]
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

    from sugar_source_tree.tree import SourceTree

    root = Path(workspace_root)
    if root.is_dir():
        # Step 2's file list (#7757 item 45).
        for path in SourceTree(root).paths():
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
        and (call_target(name) is not None or name.startswith("method:"))
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

    THE LIVE WALK IS NOT THE WHOLE TREE.  ``Node.__getattr__`` memoizes child
    slots under a key that includes ``self.reporter``, so seating a parent does
    not move its children -- it makes the next read mint FRESH child shells on
    the new reporter.  ``source_file.nodes()`` is exactly that read.  It
    therefore seats a tree the walk itself is creating, and never visits the
    shells materialized at ``Backend.materialize_module`` time and handed to
    ``SourceUnit.bind_typed_module``.

    That bind-time roster is not inert.  ``SourceUnit`` reads a call's owning
    definition out of ``unit.function_nodes``, and that FunctionDef becomes
    ``SourceVisibleCallFrameV1.owner`` -- the exact producer
    ``Call._project_constructed_value_for_testimony`` hands to
    ``retain_registered_node_from``.  Left on the first opener's
    ``NULL_REPORTER`` it owns no registration table, and retention refuses it as
    ABSENT.  That refusal is right; the stale roster is what is wrong.

    So seat the bind-time roster FIRST, then the live walk.  Both, and in that
    order: the roster is what the frame owner is read from, and the walk is what
    ordinary construction traverses.
    """
    source_file.reporter = reporter
    # id -> node, never a bare set of ids. The live walk mints shells nothing
    # else holds, so a set would let one be collected and its address reused by
    # the next shell, which would then be skipped as already seated -- silent
    # under-seating, the exact failure this function exists to end. The mapping
    # keeps every seated node alive for the duration of the walk.
    seated: dict[int, object] = {}

    def seat(node) -> None:
        if id(node) in seated:
            return
        seated[id(node)] = node
        object.__setattr__(node, "reporter", reporter)
        # Rebinding alone is not seating: it moves the label and registers
        # nothing, which turns the ABSENT refusal into the FOREIGN one -- the
        # same hole, renamed.  The two must stay one operation.
        reporter.register(node)

    unit = source_file.unit
    for node in getattr(unit, "function_nodes", ()) or ():
        seat(node)
    for statements in (getattr(unit, "module_direct_bindings", None) or {}).values():
        for statement in statements:
            seat(statement)
    for node in source_file.nodes():
        seat(node)


def enumerate_construction_context(root: Path):
    """The ONE preconstruction authority every ``sugar.enumerate`` level opens with.

    Every level of ``_handle_enumerate`` opens its file through
    ``open_source_file_for_construction`` with this context, so every level
    reads the same tree under the same authority. A level that opened the file
    any other way answered according to whichever level happened to make the
    file process-resident first.

    Bound authenticated refs when the Rust prebind installed them; otherwise the
    provisional demand table for this workspace root. Never ``None`` and never an
    empty stand-in: a tree opened without this authority makes every ``With``
    report ``RuntimeSelectedContextManager`` regardless of resolvability, which
    is a manufactured frontier, not a measurement.

    This does NOT manufacture a contract ref. It supplies the table the use-site
    is looked up in; a use-site with no row still resolves to a typed
    ``ContextManagerResolutionGapV1`` and stays a countable construction panic.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )

    return TreeConstructionContextV1(
        _enumerate_contract_refs(root),
        workspace_root=str(root),
    )


def _roll_call_audit_leaf(
    full_path: Path,
    file_rel: str,
    *,
    root: Path,
    locus_root: Path | None = None,
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

    from sugar_lift_py_tests.tree_enumerate import source_audit_from_report

    from sugar_source_tree.process_resident_file import get_resident

    reporter = CollectingReporter()
    resident_before_open = None
    source_file = None
    try:
        if expected_source_cid is not None:
            # Observed at the seat the opener reads, the one residency keys.
            seat = _read_at_seat(
                full_path, root=root, source_workspace_root=locus_root
            )[1]
            resident_before_open = get_resident(expected_source_cid, seat)
        # THE CONSTRUCTION DOOR, never the bare one. `discharge` drives
        # `.sugar()` over the whole tree, so this scope CONSTRUCTS. Opening
        # through the bare path door gave the tree no construction context,
        # and a context-less tree paints every `With`
        # `RuntimeSelectedContextManager` regardless of resolvability -- one
        # panic per file, at the file's FIRST `with`, masking everything behind
        # it. See scripts/construction_context_door_law.py; every production
        # level opens this way.
        #
        # The context is named here, on the authenticated table when the Rust
        # prebind installed one, and it is the same context the enumerate
        # levels open this file under (``construction_context_for_open``), so
        # the leaf shares their parse.
        source_file = open_source_file_for_construction(
            full_path,
            root=root,
            reporter=reporter,
            construction_context=construction_context_for_open(
                full_path, root=root, source_workspace_root=locus_root
            ),
            source_workspace_root=locus_root,
        )
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
        if panic is None and gaps_by_key:
            # The full roll-call minority remains carried by sourceAudit.  A
            # registered node that never answered because a node on this roll
            # refused by name (its descendant, its ancestor, an earlier
            # sibling: the refusal stopped the construction that would have
            # reached it) has no independent panic payload and therefore
            # cannot be relabelled as a ConstructionPanic product terminal.
            # The leaf is already loud by that refusal.
            continue
        # With no refusal anywhere on the roll, nothing explains a node that
        # never answered: it is its own terminal (``UnaccountedConstruction``).
        # A file whose roll has a silent absentee is never ``clean``.
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
                    "fix": str(getattr(panic, "fix", f"write {node.kind}.sugar")),
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
    walk (`fold_enumerate_source_tree`: `source_files` -> per-file
    `universe`) and the board door's levels
    (`scripts/recensus_enumerate_consumer.py`). `level` selects the
    granularity; `at` is the parent (the file) every level scans. The one
    seek answered is the board door's `facts` leaf under `auditFrontier`; the
    seeks by a node's own memento and by a call-site cue had no driver and
    are deleted (#7757).
    """
    demand_started = time.monotonic()
    level = params.get("level")
    workspace_root = str(params.get("workspace_root", "."))
    at = params.get("at") if isinstance(params.get("at"), dict) else None
    seek = bool(params.get("seek", False))
    options = params.get("options") if isinstance(params.get("options"), dict) else {}
    # auditFrontier selects the board door's per-file construction roll call at
    # level `facts` (see the audit_walk branch below). allowedBrokenComponents
    # was the factory's panic-recovery gate; with no factory audit walk it is
    # inert.
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
        if seek and not audit_walk:
            # Every level is a scan of its parent. The seeks that read one
            # node back (a file, a function, a universe by its own memento or
            # by a call-site cue) had no driver and are deleted (#7757); a seek
            # is refused by name, never answered with the whole scan.
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32602,
                        "message": (
                            f"sugar.enumerate: seek at level {level!r} is not "
                            "answered; the one seek is level 'facts' under "
                            "auditFrontier (the board door's D3 leaf), every "
                            "other level is a scan"
                        ),
                    },
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
            # The answer keeps the enumeration wire shape and carries no
            # node: the function's rows are the universe scan's.
            _parameter_contract_resume(options)
            _send_enumerate_result(msg_id, [], [])
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
                nodes.append({"memento": memento, "audit": None, "payload": None})
            _send_enumerate_result(msg_id, nodes, gaps)
            _log_enumeration_demand(
                str(level), at, cache="miss", started=demand_started
            )
            return

        if level in (
            "functions",
            "context-manager-resolutions",
            "relation-membership",
            "facts",
            "universe",
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
            # The LOCUS authority for every open under this demand. `root` says
            # which tree `file_rel` resolves against; this says which root the
            # minted address is stated against. They differ for an installed
            # corpus (seats are recorded against the install root) and coincide
            # for a first-party tree, where the option is absent and `root`
            # stands. Read ONCE here so no level can quietly answer differently.
            demand_locus_root = options.get("sourceWorkspaceRoot")
            locus_root = (
                Path(demand_locus_root)
                if isinstance(demand_locus_root, str) and demand_locus_root
                else None
            )
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
                # auditFrontier is the board door's construction demand (D3 in
                # scripts/recensus_enumerate_consumer.py): ONE facts leaf per
                # file, sought at the file's own memento, whose roll call walks
                # the whole file with a CollectingReporter. Every node whose own
                # sugar() reaches the base throw self-reports; that count IS R.
                # status is `failed` when the file has any unwritten sugar,
                # `clean` when fully sugared -- no false green. No other level
                # answers under auditFrontier (#7806).
                if level != "facts":
                    _send(
                        {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {
                                "code": -32602,
                                "message": (
                                    "sugar.enumerate: auditFrontier is answered "
                                    f"at level 'facts' only, not {level!r}; "
                                    "the construction frontier is the board door "
                                    "(scripts/control_effect_recensus.py, #7806)"
                                ),
                            },
                        }
                    )
                    return
                expected_source_cid = None
                if isinstance(at, dict):
                    expected_source_cid = at.get("source_cid") or at.get("file_cid")
                leaf = _roll_call_audit_leaf(
                    full_path,
                    file_rel,
                    root=root,
                    locus_root=locus_root,
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

            if level == "facts":
                # `facts` is the board door's audit leaf only. The assertion ->
                # fact descent that read one assert's reduction was driven by
                # `sugar lift`'s second door and the Rust typed descent, both
                # deleted: the whole-tree walk is mint's (source_files ->
                # universe), #7757 entry 5 / item 25.
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32602,
                            "message": (
                                "sugar.enumerate: level 'facts' is answered under "
                                "auditFrontier only (the board door's D3 leaf); "
                                "the whole-tree walk is source_files -> universe"
                            ),
                        },
                    }
                )
                return

            if level in {
                "functions",
                "context-manager-resolutions",
                "relation-membership",
            }:
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
                from sugar_lift_py_tests import tree_enumerate as _tree
                from sugar_lift_python_source.source_oracle import SourceUnavailable
                from sugar_source_tree.reporter import CollectingReporter

                # SEAT THE REGISTRATION CHANNEL (#7171 class, second costume):
                # this door CONSTRUCTS sugar, so the tree must be opened
                # on a reporter that can hold a registration. The one opener
                # seats it.
                try:
                    tree_file = open_source_file_for_construction(
                        full_path,
                        root=root,
                        reporter=CollectingReporter(),
                        source_workspace_root=locus_root,
                    )
                except SourceUnavailable as unavailable:
                    _send_enumerate_result(
                        msg_id, [], [{"memento": at, "reason": str(unavailable)}]
                    )
                    return
                file_cid = tree_file.unit.source_cid
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
                # The opener above already opened this tree under the walk
                # session for this root (step 2's file list). Construction
                # terminals stay loud here. The recensus consumer preserves the
                # already-authenticated provisional key manifest alongside the
                # panic; this producer never converts panic into a completed
                # resolution response.
                if level == "context-manager-resolutions":
                    from sugar_lift_py_tests.context_manager_resolution import (
                        context_manager_resolution_outcome,
                        effective_context_manager_resolutions_for_source,
                    )

                    resolution_nodes = []
                    for coordinate, resolution in sorted(
                        effective_context_manager_resolutions_for_source(
                            tree_file.unit.construction_context, source_cid=file_cid
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
                                    "kind": getattr(resolution, "kind", None),
                                    "targetSymbol": (
                                        getattr(resolution, "target_symbol", None)
                                        or getattr(resolution, "target_name", None)
                                    ),
                                },
                                "payload": None,
                            }
                        )
                    # This level answers here and nowhere else. Falling out of
                    # this branch reaches the generic function-memento tail,
                    # which would answer a With question with function rows and
                    # report every With item unconstructed (#7381).
                    _send_enumerate_result(msg_id, resolution_nodes, [])
                    _log_enumeration_demand(
                        str(level), at, cache="miss", started=demand_started
                    )
                    return
                if level == "relation-membership":
                    # WHO this file's ONE structural walk saw, per relation.
                    # The producer answers; this level only transports the
                    # answer onto the wire. A roster that raises leaves by its
                    # own name (a lifter panic as the typed-loud error,
                    # anything else as this request's error), never an empty
                    # membership and never a result row: a shard that cannot
                    # say who it saw must not be able to look like a shard
                    # that saw nobody.
                    roster = tree_file.unit.relation_membership_roster()
                    membership_nodes = []
                    membership_gaps = []
                    for relation in sorted(roster):
                        sides = roster[relation]
                        for role in ("expected", "observed"):
                            for occurrence in sides[role]:
                                membership_nodes.append(
                                    {
                                        "memento": {
                                            "kind": "relation-membership",
                                            "file": file_rel,
                                            "source_cid": file_cid,
                                            "relation": relation,
                                            "role": role,
                                            "occurrence": {
                                                "file": occurrence.file,
                                                "sourceCid": occurrence.source_cid,
                                                "start": occurrence.start,
                                                "end": occurrence.end,
                                                "nodeKind": occurrence.node_kind,
                                            },
                                        },
                                        "audit": None,
                                        "payload": None,
                                    }
                                )
                    _send_enumerate_result(
                        msg_id, membership_nodes, membership_gaps
                    )
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
                    nodes.append({"memento": memento, "audit": None, "payload": None})
                _send_enumerate_result(msg_id, nodes, [])
                _log_enumeration_demand(
                    str(level), at, cache="miss", started=demand_started
                )
                return
            # (audit_walk already answered or refused above; this is the live
            # path.)
            if level == "universe":
                # Every function's contract, served from the tree. Each
                # function's FunctionDef.sugar() reduces to a UniverseValue
                # whose payload_rows project the function-contract DTO (post +
                # invs). A file scan only, the one mint packages: the seek by a
                # universe's own memento or by a call-site cue, and the
                # `call_sites` level that minted the cue, had no driver and are
                # deleted (#7757).
                from sugar_lift_py_tests import tree_enumerate as _tree
                from sugar_lift_py_tests import unanswered_calls as _unanswered
                from sugar_lift_py_tests.ir import TermTableBuilder
                from sugar_source_tree.panic import BackendDefect, LifterRefusal
                from sugar_source_tree.reporter import CollectingReporter

                sf = open_source_file_for_construction(
                    full_path,
                    root=root,
                    reporter=CollectingReporter(),
                    source_workspace_root=locus_root,
                )
                term_table = TermTableBuilder()
                # Every row of every function's one reduction (#7766): the
                # function-contract AND each assertion row.
                scan_rows = []  # (memento_dict, dto)
                # One `undecided` row per unanswered call site in this file: a
                # call inlined into several functions' reductions is one call.
                recorded_calls: set = set()
                # Every function's rows, refused member and undecided members
                # come from this one scan (#7757): no function is skipped for
                # another door to state.
                for fn in sf.functions():
                    try:
                        def_memento, rows = _tree.function_contract_rows(
                            fn, file_rel
                        )
                        # Every call the reduction's final arms owe is written
                        # once, as an `undecided` row (step 8; PR B on #7766).
                        calls = _unanswered.owed_calls(
                            _tree.owner_reduction(fn).outcome
                        )
                    except BackendDefect:
                        # The backend or adapter is broken: not the function's
                        # refusal, and never recorded as one.
                        raise
                    except LifterRefusal as refusal:
                        # One rule (step 8, the owner 2026-11-12): every
                        # refusal by name raised constructing or reducing this
                        # function (either family: a free variable outside its
                        # declared scope, sugar not written, an undecided
                        # module global, ...) is this function's refused
                        # member, with the refusal's name and reason, and the
                        # rest of the file is served. One `undecided` row,
                        # which mint writes as the function's member. The
                        # proof never silently lacks the function's claims.
                        scan_rows.append(
                            (
                                _tree.function_def_memento(fn, file_rel).to_rpc(),
                                _tree.refused_function_row(fn, file_rel, refusal),
                            )
                        )
                        continue
                    for row in _tree.unanswered_call_rows(calls, file_rel):
                        key = json.dumps(
                            row.to_rpc_with_term_table(None), sort_keys=True
                        )
                        if key not in recorded_calls:
                            recorded_calls.add(key)
                            scan_rows.append((def_memento.to_rpc(), row))
                    if rows is None:
                        continue  # an effect, not a contract
                    scan_rows.extend((def_memento.to_rpc(), row) for row in rows)
                # Each exception class the module defines states its ancestry,
                # named by its target symbol, so a consumer's `except` against
                # the imported class is decided at prove through the join
                # (#7757).
                scan_rows.extend(_tree.exception_ancestry_rows(sf, file_rel))

                nodes = [
                    {
                        "memento": memento,
                        "audit": dto.to_rpc_with_term_table(term_table),
                        "payload": None,
                    }
                    for memento, dto in scan_rows
                ]
                _send_enumerate_result(
                    msg_id, nodes, [], term_tables=[term_table.nodes]
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
                "loaded_source_identity": loaded_python_source_identity(),
            },
        }
    )


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
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
    from sugar_source_tree.panic import LifterRefusal

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
        except LifterRefusal as refusal:
            # The one refusal, one answer (#7757): a refusal of one request is
            # that request's typed-loud JSON-RPC error naming the refusal (its
            # class, message and locus), never a result; the resident keeps
            # serving the next request.
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {
                        "code": -32001,
                        "message": str(refusal),
                        "data": {
                            "kind": "typed-loud",
                            "exception_type": type(refusal).__name__,
                            "stage": "dispatch",
                            "diagnostic": refusal.diagnostic(),
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
            "the construction frontier is the board door "
            "(scripts/control_effect_recensus.py, #7806)"
        )
    _serve()


if __name__ == "__main__":
    main(sys.argv[1:])
