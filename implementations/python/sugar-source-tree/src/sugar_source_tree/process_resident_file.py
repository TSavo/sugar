"""Enumeration protocol §4 — process-resident file context under content CID.

Law (``protocol/specs/2026-07-08-enumeration-protocol.md`` §4):

    Inside the Python kit, demanded file context is process-resident under the
    whole-file content CID. A file request parses and prepares module temporal
    context once for that CID; distinct demanded descendants reuse it. Changing
    the file changes the CID and therefore misses without a staleness check.

This is not a new invention and not an optional cache. The protocol makes
re-deriving the same content for every consumer **unrepresentable**: same CID
answers from residency; different bytes mint a different CID and miss.

Boundary (load-bearing):
    Shared product is the **content-derived preparation** — SourceUnit +
    MaterializeModule tree + unit construction_cache for that body, and the
    **lexical import pass** (call/value rows) for that content. It is not a
    consumer workspace projection shell carrying another open's live seating
    authority or reporter. Seat-bound receipts are minted per demand with the
    caller's root/path; the pass product is not.

Identity is not the key. ``h = h(p)``: the whole-file content CID *is* the key.
"""

from __future__ import annotations

import collections
import os
from dataclasses import dataclass
from typing import Any, Optional, Tuple


def _resident_limit() -> int:
    raw = os.environ.get("SUGAR_PROCESS_RESIDENT_FILE_LIMIT", "512")
    try:
        return max(1, int(raw))
    except ValueError:
        return 512


@dataclass
class ProcessResidentFileContext:
    """One whole-file content CID's prepared body, process-resident.

    ``prepare_count`` is the number of times this CID paid MaterializeModule
    in this process (protocol: must be 1 after first demand).
    """

    source_cid: str
    source: str
    filename: str
    source_file: Any  # SourceFile — structural shell after prepare
    prepare_count: int


# content CID -> resident context (LRU by access)
_RESIDENT: collections.OrderedDict[str, ProcessResidentFileContext] = (
    collections.OrderedDict()
)
# Teeth: prepare counts even after eviction from the LRU window
_PREPARE_COUNTS: dict[str, int] = {}

# §4 module temporal context: lexical import preparation (call + value rows).
# Content-derived; not a consumer projection shell. Keyed by content CID plus
# the module's package role (relative-import meaning), never by who asked.
_LEXICAL: collections.OrderedDict[tuple, Any] = collections.OrderedDict()
_LEXICAL_PREPARE_COUNTS: dict[str, int] = {}


def prepare_count_for(source_cid: str) -> int:
    """How many times this content CID has paid full SourceFile prepare."""
    return int(_PREPARE_COUNTS.get(source_cid, 0))


def lexical_prepare_count_for(source_cid: str) -> int:
    """How many times this content CID has paid the lexical import walk."""
    return int(_LEXICAL_PREPARE_COUNTS.get(source_cid, 0))


def resident_size() -> int:
    return len(_RESIDENT)


def clear_process_resident_files() -> None:
    """Test door: drop residency and prepare counters."""
    _RESIDENT.clear()
    _PREPARE_COUNTS.clear()
    _LEXICAL.clear()
    _LEXICAL_PREPARE_COUNTS.clear()


def _remember(source_cid: str, ctx: ProcessResidentFileContext) -> None:
    _RESIDENT[source_cid] = ctx
    _RESIDENT.move_to_end(source_cid)
    while len(_RESIDENT) > _resident_limit():
        _RESIDENT.popitem(last=False)


def get_resident(source_cid: str) -> ProcessResidentFileContext | None:
    hit = _RESIDENT.get(source_cid)
    if hit is not None:
        _RESIDENT.move_to_end(source_cid)
    return hit


def source_file_from_identity(
    identity: Tuple[str, str, str],
    *,
    backend: Any = None,
    reporter: Any = None,
    construction_context: object | None = None,
) -> Any:
    """Return SourceFile for identity, preparing at most once per content CID.

    Implements §4 at the construction door every demand already walks.
    """
    from .reporter import NULL_REPORTER
    from .tree import SourceFile, _default_backend

    source, filename, source_cid = identity
    if not source_cid:
        # No content address → no residency (cannot key). Pay full prepare.
        return SourceFile._prepare_uncached(
            identity,
            backend=backend,
            reporter=NULL_REPORTER if reporter is None else reporter,
            construction_context=construction_context,
        )

    hit = get_resident(source_cid)
    if hit is not None:
        # Protocol: distinct demanded descendants reuse preparation.
        # Rebind consumer construction_context when provided so seating writes
        # land on the caller's tables when this open owns seating — without
        # re-running MaterializeModule. structural tree + construction_cache stay.
        sf = hit.source_file
        if construction_context is not None:
            object.__setattr__(sf.unit, "construction_context", construction_context)
        if reporter is not None:
            sf.reporter = reporter
        return sf

    # Miss: content CID not prepared. Pay once; changing bytes → new CID → miss.
    _PREPARE_COUNTS[source_cid] = _PREPARE_COUNTS.get(source_cid, 0) + 1
    sf = SourceFile._prepare_uncached(
        identity,
        backend=backend if backend is not None else _default_backend(),
        reporter=NULL_REPORTER if reporter is None else reporter,
        construction_context=construction_context,
    )
    _remember(
        source_cid,
        ProcessResidentFileContext(
            source_cid=source_cid,
            source=source,
            filename=filename,
            source_file=sf,
            prepare_count=_PREPARE_COUNTS[source_cid],
        ),
    )
    return sf


def _lexical_key(
    source_cid: str,
    module_is_package: bool,
    module_identities: dict | None,
) -> tuple:
    """Content CID + package role + identity map — not seat/path spelling.

    Protocol §4 keys preparation by content CID. Package role matters for
    ``__init__.py`` vs module file of the same bytes; asker path does not.
    """
    identities = module_identities or {}
    id_items = tuple(sorted((str(k), str(v)) for k, v in identities.items()))
    return (source_cid, module_is_package, id_items)


def get_or_prepare_lexical_import_pass(
    module,
    *,
    root,
    path,
    source: str,
    source_cid: str,
    module_identities: dict | None = None,
) -> Any:
    """§4: lexical import pass once per content CID (+ package role).

    Returns the content-derived ``_Pass`` product (rows, value_rows, outcomes).
    Callers mint seat-bound receipts with their own root/path. The pass itself
    is pure in file content + package role + identity map — not who asks.
    """
    from pathlib import Path

    from sugar_lift_py_tests.import_binding import (
        _run_lexical_import_pass_on_module,
    )

    root_p = Path(root)
    path_p = Path(path)
    module_is_package = path_p.name == "__init__.py"
    key = _lexical_key(source_cid, module_is_package, module_identities)
    hit = _LEXICAL.get(key)
    if hit is not None:
        _LEXICAL.move_to_end(key)
        return hit

    _LEXICAL_PREPARE_COUNTS[source_cid] = _LEXICAL_PREPARE_COUNTS.get(source_cid, 0) + 1
    runner = _run_lexical_import_pass_on_module(
        module,
        root=root_p,
        path=path_p,
        source=source,
        source_cid=source_cid,
        module_identities=module_identities,
    )
    _LEXICAL[key] = runner
    _LEXICAL.move_to_end(key)
    while len(_LEXICAL) > _resident_limit():
        _LEXICAL.popitem(last=False)
    return runner
