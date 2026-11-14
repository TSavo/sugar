"""Enumeration protocol §4 — process-resident file context under content CID + seat.

Law (``protocol/specs/2026-07-08-enumeration-protocol.md`` §4):

    Inside the Python kit, demanded file context is process-resident under the
    whole-file content CID and source seat. A file request parses and prepares
    module temporal context once for that identity; a different seat is a
    different typed object and therefore misses.

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

The one opener's populated file (``get_opened`` / ``remember_opened``) is
seat-bound and authority-bound: it is keyed by the workspace root and the
table/session it was opened under as well as the CID and seat, so it is shared
only by opens that would have produced the same unit.

ONE ENTRY, ONE PARSE PER FILE (#7757 item 5). Residency is entered from one
place: the opener's first stage, ``lift_rpc._open_at_seat`` (``SourceFile(...)``
forwards to it). A unit parsed with no construction context (the step-3
readers, or any other contextless open, all through that entry) waits for the
opener: the opener's open under a context attaches that context to the
resident unit (``SourceUnit.attach_construction_context``) instead of parsing
the file a second time. The slot is still written once: a unit that already
carries a context is never given another one, and an open under a different
context prepares its own unit (#7772).

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

    ``prepare_count`` is the number of times this CID/seat paid MaterializeModule
    in this process (protocol: must be 1 after first demand).
    """

    source_cid: str
    source: str
    filename: str
    source_file: Any  # SourceFile — structural shell after prepare
    prepare_count: int


# (content CID, source seat) -> resident context (LRU by access)
_RESIDENT: collections.OrderedDict[tuple[str, str], ProcessResidentFileContext] = (
    collections.OrderedDict()
)
# Teeth: prepare counts even after eviction from the LRU window
_PREPARE_COUNTS: dict[tuple[str, str], int] = {}

# §4 module temporal context: lexical import preparation (call + value rows).
# Content-derived; not a consumer projection shell. Keyed by content CID plus
# the module's package role (relative-import meaning), never by who asked.
_LEXICAL: collections.OrderedDict[tuple, Any] = collections.OrderedDict()
_LEXICAL_PREPARE_COUNTS: dict[str, int] = {}

# The one opener's product (``lift_rpc.open_source_file_for_construction``): a
# file parsed under a construction context and POPULATED. Keyed by content CID
# and seat, like residency, plus the workspace root and the authority it was
# opened under (the table or caller-held context, and the resolution session).
# The authority objects are held in the value, so an ``id`` in the key cannot be
# reused while its row lives, and a hit is confirmed by identity.
_OPENED: collections.OrderedDict[tuple, tuple[tuple, Any]] = (
    collections.OrderedDict()
)
# The construction context the opener opens a file under for an authority it
# derives itself (the table and the session): minted once, so a caller that
# names it (the audit leaf) and a caller that does not (the enumerate levels)
# open under the same object and share one parse and one population. Keyed
# like ``_OPENED``.
_OPEN_CONTEXTS: collections.OrderedDict[tuple, tuple[tuple, Any]] = (
    collections.OrderedDict()
)


def prepare_count_for(source_cid: str, source_seat: str | None = None) -> int:
    """How many times this CID (optionally seat) paid full SourceFile prepare."""
    if source_seat is not None:
        return int(_PREPARE_COUNTS.get((source_cid, source_seat), 0))
    return sum(n for (cid, _seat), n in _PREPARE_COUNTS.items() if cid == source_cid)


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
    _OPENED.clear()
    _OPEN_CONTEXTS.clear()


def _opened_key(
    source_cid: str, source_seat: str, workspace_root: str, authority: tuple
) -> tuple:
    return (source_cid, source_seat, workspace_root, tuple(id(a) for a in authority))


def get_opened(
    source_cid: str, source_seat: str, workspace_root: str, authority: tuple
) -> Any | None:
    """The opener's populated file for these bytes, seat, root and authority."""
    key = _opened_key(source_cid, source_seat, workspace_root, authority)
    hit = _OPENED.get(key)
    if hit is None:
        return None
    held, source_file = hit
    if len(held) != len(authority) or not all(
        a is b for a, b in zip(held, authority)
    ):
        return None
    _OPENED.move_to_end(key)
    return source_file


def remember_opened(
    source_cid: str,
    source_seat: str,
    workspace_root: str,
    authority: tuple,
    source_file: Any,
) -> None:
    """Record a file the opener opened and populated; bounded like residency."""
    key = _opened_key(source_cid, source_seat, workspace_root, authority)
    _OPENED[key] = (tuple(authority), source_file)
    _OPENED.move_to_end(key)
    while len(_OPENED) > _resident_limit():
        evicted, _held = _OPENED.popitem(last=False)
        # The context leaves with the file it populated: a later open mints a
        # fresh one and prepares its own unit, never populates this one twice.
        _OPEN_CONTEXTS.pop(evicted, None)


def open_context(
    source_cid: str,
    source_seat: str,
    workspace_root: str,
    authority: tuple,
    mint: Any = None,
) -> Any | None:
    """The context the opener opens these bytes under for this authority.

    Minted by ``mint`` the first time it is asked for, then the same object.
    With no ``mint``, ``None`` when none was minted.
    """
    key = _opened_key(source_cid, source_seat, workspace_root, authority)
    hit = _OPEN_CONTEXTS.get(key)
    if hit is not None:
        held, context = hit
        if len(held) == len(authority) and all(
            a is b for a, b in zip(held, authority)
        ):
            _OPEN_CONTEXTS.move_to_end(key)
            return context
    if mint is None:
        return None
    context = mint()
    _OPEN_CONTEXTS[key] = (tuple(authority), context)
    _OPEN_CONTEXTS.move_to_end(key)
    while len(_OPEN_CONTEXTS) > _resident_limit():
        _OPEN_CONTEXTS.popitem(last=False)
    return context


def forget_open_context(
    source_cid: str, source_seat: str, workspace_root: str, authority: tuple
) -> None:
    """Drop the context of an open whose population halted: it is not reused."""
    _OPEN_CONTEXTS.pop(
        _opened_key(source_cid, source_seat, workspace_root, authority), None
    )


def _remember(source_cid: str, source_seat: str, ctx: ProcessResidentFileContext) -> None:
    key = (source_cid, source_seat)
    _RESIDENT[key] = ctx
    _RESIDENT.move_to_end(key)
    while len(_RESIDENT) > _resident_limit():
        _RESIDENT.popitem(last=False)


def get_resident(source_cid: str, source_seat: str) -> ProcessResidentFileContext | None:
    hit = _RESIDENT.get((source_cid, source_seat))
    if hit is not None:
        _RESIDENT.move_to_end((source_cid, source_seat))
    return hit


def _source_file_from_identity(
    identity: Tuple[str, str, str],
    *,
    backend: Any = None,
    reporter: Any = None,
    construction_context: object | None = None,
) -> Any:
    """Return SourceFile for identity, preparing at most once per CID and seat.

    Implements §4 at the construction door every demand already walks. Private
    to the opener's first stage (``lift_rpc._open_at_seat``), the one entry:
    nothing else reaches residency, so every contextless open is a first-stage
    open and every unit without a context is one the opener may attach to.

    A contextless open parses the file with no context; the opener's open under
    its context attaches that context to the same unit, so the file is parsed
    once (#7757 item 5).
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

    hit = get_resident(source_cid, filename)
    if hit is not None:
        unit = hit.source_file.unit
        if (
            construction_context is None
            or unit.construction_context is construction_context
        ):
            pass
        elif unit.construction_context is None:
            # The first stage parsed this file with no context; the opener
            # attaches its context instead of parsing it again. The one write
            # of the slot (#7757 item 5).
            unit.attach_construction_context(construction_context)
        else:
            # A unit keeps the construction context it was prepared under;
            # nothing writes that slot again. An open that carries a different
            # context is a different open and takes the miss path below
            # (#7772).
            hit = None
    if hit is not None:
        # Protocol: distinct demanded descendants reuse preparation.
        sf = hit.source_file
        if reporter is not None:
            sf.reporter = reporter
        return sf

    # Miss: this CID/seat not prepared under this context. Changing bytes, seat
    # or construction context misses.
    count_key = (source_cid, filename)
    _PREPARE_COUNTS[count_key] = _PREPARE_COUNTS.get(count_key, 0) + 1
    sf = SourceFile._prepare_uncached(
        identity,
        backend=backend if backend is not None else _default_backend(),
        reporter=NULL_REPORTER if reporter is None else reporter,
        construction_context=construction_context,
    )
    _remember(
        source_cid,
        filename,
        ProcessResidentFileContext(
            source_cid=source_cid,
            source=source,
            filename=filename,
            source_file=sf,
            prepare_count=_PREPARE_COUNTS[count_key],
        ),
    )
    return sf


def _lexical_key(
    source_cid: str,
    module_name: str | None,
    module_is_package: bool,
    module_identities: dict | None,
) -> tuple:
    """Content CID + module name + package role + identity map.

    Protocol §4 keys preparation by content CID. Package role matters for
    ``__init__.py`` vs module file of the same bytes. The module name
    matters too: a relative import (``from .errors import E``) resolves
    against it, so the same bytes in two packages bind two different targets
    (#7757). The rest of the asker's path does not.
    """
    identities = module_identities or {}
    id_items = tuple(sorted((str(k), str(v)) for k, v in identities.items()))
    return (source_cid, module_name, module_is_package, id_items)


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
        module_name_for_path,
    )

    root_p = Path(root)
    path_p = Path(path)
    module_is_package = path_p.name == "__init__.py"
    try:
        module_name = module_name_for_path(root_p, path_p)
    except ValueError:
        # Outside the root: the pass itself refuses this seat on a miss.
        module_name = None
    key = _lexical_key(source_cid, module_name, module_is_package, module_identities)
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
