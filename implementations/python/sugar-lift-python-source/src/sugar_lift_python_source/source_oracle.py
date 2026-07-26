# SPDX-License-Identifier: MIT OR Apache-2.0
#
# The Source Oracle.
#
# The `.proof` does not carry source. A SourceMemento is a pointer + two hashes:
#   { source_function_name, file, span, source_cid, template_cid }
# zero content. The source already lives on disk (pip/npm/cargo shipped it); the
# `.proof` only LOCATES it (file, span) and PINS it (source_cid, template_cid).
#
# You do not ask the `.proof` for `body_text`/`ast_template` -- you ask the Source
# Oracle. Its contract is one line:
#
#   given a locus + CID, return the source IFF it recomputes to the CID;
#   else SOURCE UNAVAILABLE, loudly.
#
# That source-unavailable result is the BINARY axis of the three-axis pin made operational, checked
# at every resolution: a tampered or wrong-version package -> CID mismatch ->
# source unavailable -> the sugar cannot resolve -> you KNOW the on-disk source is not what was
# proven. exact-or-source-unavailable, no silent loss (supra omnia, rectum).

from __future__ import annotations

import importlib.machinery
import importlib.metadata
import os
import sys
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from . import typed_node_api as typed
from .ast_template import (
    expr_to_template,
    function_param_names,
    stmt_to_template,
)
from .bind_lifter import _body_source_locator
from .canonical import blake3_512_of, template_cid_of_json
from .source_tables import source_segment, source_splitlines


def _source_file_cls():
    """Lazy SourceFile import — tree imports this module for path_source."""
    _tree_src = Path(__file__).resolve().parents[3] / "sugar-source-tree" / "src"
    if _tree_src.is_dir() and str(_tree_src) not in sys.path:
        sys.path.insert(0, str(_tree_src))
    from sugar_source_tree.backend import BackendCouldNotParse
    from sugar_source_tree.tree import SourceFile

    return SourceFile, BackendCouldNotParse


class SourceUnavailable(Exception):
    """Raised LOUDLY when on-disk source does not recompute to the pinned CID:
    the source has drifted from what the `.proof` pins. Never a silent fallback."""


INSTALLED_SOURCE_CAPACITY = 64
# Success-only resident answers. Key is (module_name, source_seat, source_cid):
# authenticated content + seat identity. Absence, I/O failure, and parse failure
# never publish — a negative cannot poison a later successful construction.
_INSTALLED_MODULE_SOURCE_CACHE: OrderedDict[
    tuple[str, str, str], tuple[str, str, str]
] = OrderedDict()


def installed_module_source(
    module_name: str,
    *,
    source_seat: str | None = None,
) -> tuple[str, str, str] | None:
    """Resolve installed Python source once through the SourceOracle boundary.

    The returned identity is ``(source, filename, content CID)``.  Callers may
    derive views from it, but must not independently discover/read/parse the
    module.  ``SourceFile`` is the parse gate; residual dual-path consumers
    may still re-parse for template recompute until those paths are drained.

    Successful answers partition by authenticated source CID and source seat.
    Discovery re-reads installed bytes so content drift and late appearance
    cannot reuse a prior answer; only a successful parse is published.
    """
    if not module_name:
        return None
    parts = module_name.split(".")
    search_path = None
    spec = None
    try:
        for index in range(1, len(parts) + 1):
            qualified = ".".join(parts[:index])
            lookup_name = qualified if search_path is None else parts[index - 1]
            spec = importlib.machinery.PathFinder.find_spec(lookup_name, search_path)
            if spec is None:
                return None
            if index < len(parts):
                search_path = spec.submodule_search_locations
                if search_path is None:
                    return None
        origin = getattr(spec, "origin", None)
        if not origin or not origin.endswith((".py", ".pyi")):
            return None
        source = Path(origin).read_text(encoding="utf-8")
    except (
        ImportError,
        ModuleNotFoundError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        # Absence and read failures are not reusable successes.
        return None

    source_cid = blake3_512_of(source.encode("utf-8"))
    seat = str(source_seat or origin)
    key = (module_name, seat, source_cid)
    cached = _INSTALLED_MODULE_SOURCE_CACHE.get(key)
    if cached is not None:
        _INSTALLED_MODULE_SOURCE_CACHE.move_to_end(key)
        return cached

    # Parse before publishing a successful oracle answer. Syntax failures are
    # not cached as completed source. SourceFile is the sole parse door —
    # adapters own foreign grammar; this layer only admits successfully typed
    # modules into the oracle cache.
    SourceFile, BackendCouldNotParse = _source_file_cls()
    try:
        SourceFile((source, origin, source_cid))
    except (SyntaxError, BackendCouldNotParse, UnicodeError, ValueError):
        return None

    result = (source, origin, source_cid)
    _INSTALLED_MODULE_SOURCE_CACHE[key] = result
    while len(_INSTALLED_MODULE_SOURCE_CACHE) > INSTALLED_SOURCE_CAPACITY:
        _INSTALLED_MODULE_SOURCE_CACHE.popitem(last=False)
    return result


def _installed_module_source_cache_clear() -> None:
    _INSTALLED_MODULE_SOURCE_CACHE.clear()


installed_module_source.cache_clear = (  # type: ignore[attr-defined]
    _installed_module_source_cache_clear
)


def path_source(path: str) -> tuple[str, str, str]:
    """Path-addressed minting door — ORACLE-CONTRACT EXTENSION (#5940 tree).

    Second address form beside `installed_module_source`: the module door
    serves *installed-module* source; a `SourceTree` enumerates *paths*.
    Identity is the same `(source, filename, content CID)` triple, minted
    HERE so no parser ever reads or hashes a file itself.

    Minting only: read + decode + CID. No parse gate — which parses is the
    backend's question, and marking source unavailable here would decide it for every backend.
    Unreadable/undecodable is a LOUD `SourceUnavailable`, never `None`:
    callers record it as a source-unavailable result, not an absence.
    """
    try:
        source = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise SourceUnavailable(f"cannot read source `{path}`: {exc}") from exc
    return (source, str(path), blake3_512_of(source.encode("utf-8")))


def workspace_path_source(path: str, *, root: str) -> tuple[str, str, str]:
    """The workspace-relative half of `path_source` — the construction door.

    `path_source` mints the locus from the read path, so a corpus opened by
    absolute path carries an absolute locus. Every ground exceptional exit
    (`ground_index_error` and its siblings) refuses an absolute locus, because
    a `SourceMemento` addresses `{file, span}` workspace-relative and
    `resolve_span_memento` re-reads it as `project_root / file`. An absolute
    locus is therefore not a longer spelling of the same address: it is an
    address that cannot be resolved against any other checkout.

    This door reads through the same minting path — one read, one CID — and
    states the locus relative to the workspace `root`. A path outside `root`
    has no workspace-relative name at all; that is a LOUD `SourceUnavailable`,
    never a silent fall back to the absolute spelling.
    """
    source, _absolute, source_cid = path_source(path)
    try:
        relative = Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError as exc:
        raise SourceUnavailable(
            f"source `{path}` lies outside workspace root `{root}`: {exc}"
        ) from exc
    locus = relative.as_posix()
    require_recorded_seat(path, locus)
    return (source, locus, source_cid)


def require_recorded_seat(path: str, locus: str) -> None:
    """For an installed file, the locus must BE the seat its distribution recorded.

    ``is_absolute()`` is a string test standing in for a property. The law it
    serves is "another checkout can resolve this address"; what it checks is
    "this string starts with a slash". Strip the slash and the two come apart::

        workspace_path_source(".../site-packages/pandas/core/frame.py", root="/")
          -> "Users/tsavo/provekit/.venv/lib/python3.14/site-packages/pandas/core/frame.py"

    That locus is exactly as machine-specific and unresolvable as the absolute
    path it was derived from, and ``is_absolute()`` accepts it. So does every
    intermediate root: ``root=.../pandas`` yields ``core/frame.py`` and
    ``root=.../pandas/core`` yields ``frame.py`` -- three different addresses
    for one file, all accepted, none of them what any other checkout would
    resolve.

    An installed distribution states the answer itself. Its RECORD lists the
    seat of every file it installed, relative to the install root, and
    ``dependency_artifact.py`` rejects an absolute seat structurally rather
    than by string inspection. So for a file the RECORD covers, the locus is
    decidable: it must EQUAL that seat, or the door refuses by name.

    Scoped to sources that HAVE a RECORD. A first-party file has no
    distribution, so the workspace-relative law remains its whole law and this
    arm never fires -- a refusal is not widened to a population that cannot
    satisfy it. A file inside an install root that the RECORD does not cover
    (a stray, a build artifact) has no seat to be checked against, so there is
    nothing to authenticate and nothing is claimed.
    """
    seat = recorded_seat_for(path)
    if seat is None or locus == seat:
        return
    raise SourceUnavailable(
        f"source `{path}` is installed and its distribution records the seat "
        f"`{seat}`, but this locus states `{locus}`. An installed file's "
        "address is the seat its distribution recorded -- a locus derived from "
        "some other root is not a different spelling of that address, it is an "
        "address no other checkout resolves. Open it relative to the install "
        "root, or through the module door."
    )


def install_root_for(path: str) -> str | None:
    """The directory this file's seat is stated relative to, or ``None``.

    A driver measuring an installed corpus needs the SAME root the RECORD
    states seats against, or it mints an address the seat law refuses. Deriving
    it here -- from the distribution's own manifest, by the same walk
    ``recorded_seat_for`` uses -- means the driver and the law cannot disagree.
    A driver that computed the root some other way would be a second addressing
    convention, which is the thing we are avoiding.

    Accepts a file or a directory, because a corpus driver is handed a package
    directory (``.../site-packages/pandas``) and must root at the install root
    (``.../site-packages``) that its seats are stated against.

    ``None`` means no distribution states an address for anything here, so the
    caller's own root stands.
    """
    resolved = Path(path).resolve()
    for parent in resolved.parents:
        seats = _recorded_seats(str(parent))
        if seats is None:
            continue
        candidate = resolved.relative_to(parent).as_posix()
        if candidate in seats:
            return str(parent)
        # A directory is inside the distribution when it is the stated parent
        # of at least one recorded seat. Checked against the manifest, never
        # inferred from the directory's name or position.
        prefix = candidate + "/"
        if any(seat.startswith(prefix) for seat in seats):
            return str(parent)
        return None
    return None


def recorded_seat_for(path: str) -> str | None:
    """The seat this file's distribution recorded for it, or ``None``.

    ``None`` means "no distribution states an address for this file" -- a
    first-party source, or a file no RECORD covers. It never means "the seat
    is unavailable, carry on with a guess".
    """
    resolved = Path(path).resolve()
    for parent in resolved.parents:
        seats = _recorded_seats(str(parent))
        if seats is None:
            continue
        candidate = resolved.relative_to(parent).as_posix()
        return candidate if candidate in seats else None
    return None


@lru_cache(maxsize=16)
def _recorded_seats(install_root: str) -> frozenset[str] | None:
    """Every seat recorded by the distributions installed at ``install_root``.

    ``None`` when this directory is not an install root at all. Cached per
    root: a corpus run asks once per directory, not once per file.
    """
    root = Path(install_root)
    try:
        if not any(root.glob("*.dist-info")):
            return None
    except OSError:
        return None
    seats: set[str] = set()
    for distribution in importlib.metadata.distributions(path=[install_root]):
        for recorded in distribution.files or ():
            seats.add(PurePosixPath(str(recorded)).as_posix())
    return frozenset(seats)


def dependency_artifact_file(path: str) -> tuple[bytes, str, str]:
    """Mint one recorded dependency file as ``(bytes, seat, content CID)``.

    The dependency artifact graph supplies the seat; this door only reads and
    content-addresses it.  It performs no module lookup, import, or execution.
    Binary files are admitted because a distribution artifact authenticates
    every recorded byte, not only Python source files.
    """
    try:
        content = Path(path).read_bytes()
    except (OSError, ValueError) as exc:
        raise SourceUnavailable(
            f"cannot read dependency artifact file `{path}`: {exc}"
        ) from exc
    return content, str(path), blake3_512_of(content)


def resolve_span_memento(
    memento: dict[str, Any], project_root: str | None = None
) -> dict[str, Any]:
    """Resolve a span-addressed SourceMemento by RECOMPUTE — exact or source unavailable.

    ORACLE-CONTRACT EXTENSION (#5940 tree), the resolution half of
    `path_source`. Memento shape: `{file, span: {start, end}, source_cid,
    cid}` — file plus a half-open codepoint span into it, pinned twice:
    the whole file (`source_cid`) and the sliced segment (`cid`). Reads the
    on-disk file through `path_source`, re-slices, and returns the identity
    plus segment IFF both CIDs recompute; else raises `SourceUnavailable`.
    """
    file = memento.get("file")
    if not isinstance(file, str) or not file:
        raise SourceUnavailable("span memento missing `file`")
    span = memento.get("span")
    if not isinstance(span, dict):
        raise SourceUnavailable("span memento missing `span`")
    start, end = span.get("start"), span.get("end")
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or not (0 <= start <= end)
    ):
        raise SourceUnavailable(f"span memento has degenerate span {span!r}")

    path = str(Path(project_root) / file) if project_root else file
    source, filename, source_cid = path_source(path)

    pinned_source_cid = memento.get("source_cid")
    if pinned_source_cid is not None and source_cid != pinned_source_cid:
        raise SourceUnavailable(
            f"source CID misaligned for `{file}`: pinned {pinned_source_cid}, "
            f"on-disk {source_cid} -- the source drifted from the memento"
        )
    if end > len(source):
        raise SourceUnavailable(
            f"span [{start}, {end}) exceeds `{file}` length {len(source)}"
        )
    segment = source[start:end]
    segment_cid = blake3_512_of(segment.encode("utf-8"))
    pinned_cid = memento.get("cid")
    if pinned_cid is not None and segment_cid != pinned_cid:
        raise SourceUnavailable(
            f"segment CID misaligned for `{file}` [{start}, {end}): pinned "
            f"{pinned_cid}, on-disk {segment_cid} -- the segment drifted"
        )
    return {
        "source": source,
        "filename": filename,
        "source_cid": source_cid,
        "segment": segment,
        "cid": segment_cid,
        "span": {"start": start, "end": end},
    }


def resolve_source_memento(
    project_root: str, memento: dict[str, Any]
) -> dict[str, Any]:
    """Resolve a SourceMemento to its `{body_text, ast_template}` by RECOMPUTE.

    Reads the on-disk source at the memento's locus, re-derives the pinned
    function body or source node with the same machinery that minted it, and
    returns the source/AST IFF the recomputed `source_cid`/`template_cid` equal
    the pinned ones. Otherwise raises `SourceUnavailable`.
    """
    file = memento.get("file")
    if not isinstance(file, str) or not file:
        raise SourceUnavailable("source memento missing `file`")
    function_name = memento.get("source_function_name")
    pinned_source_cid = memento.get("source_cid")
    pinned_template_cid = memento.get("template_cid")
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}

    path = Path(project_root) / file
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceUnavailable(f"cannot read source `{path}`: {exc}") from exc

    source_cid = blake3_512_of(source.encode("utf-8"))
    # SourceFile / typed Nodes are the sole recompute path: locate, body text,
    # and template projection all speak typed currency (bind_lifter/ast_template
    # already drain onto typed Nodes).
    SourceFile, BackendCouldNotParse = _source_file_cls()
    try:
        source_file = SourceFile((source, str(path), source_cid))
    except (SyntaxError, BackendCouldNotParse, UnicodeError, ValueError) as exc:
        raise SourceUnavailable(f"cannot parse source `{path}`: {exc}") from exc

    node = _locate_function(source_file, function_name, span)
    if node is None:
        raise SourceUnavailable(
            f"source function `{function_name}` not found in `{file}` near line "
            f"{span.get('start_line')}"
        )

    rel = file.replace(os.sep, "/")
    if memento.get("source_kind") in {"python.ast-stmt", "python.ast-expr"}:
        recomputed = _node_source_locator(
            node,
            rel,
            source,
            span,
            str(memento.get("source_kind")),
        )
    else:
        recomputed = _body_source_locator(node, rel, list(source_splitlines(source)))
    # The Source Oracle's whole job is to RECONSTRUCT source + ast_template from
    # disk. Function mementos resolve to whole bodies; statement/expression
    # mementos resolve to the exact node that warranted the proof row.

    if (
        pinned_source_cid is not None
        and recomputed.get("source_cid") != pinned_source_cid
    ):
        raise SourceUnavailable(
            f"source CID misaligned for `{function_name}` in `{file}`: "
            f"pinned {pinned_source_cid}, on-disk {recomputed.get('source_cid')} "
            "-- the source drifted from the proof"
        )
    if (
        pinned_template_cid is not None
        and recomputed.get("template_cid") != pinned_template_cid
    ):
        raise SourceUnavailable(
            f"template CID misaligned for `{function_name}` in `{file}`: "
            f"pinned {pinned_template_cid}, on-disk {recomputed.get('template_cid')} "
            "-- the AST drifted from the proof"
        )

    return {
        "body_text": recomputed.get("body_text"),
        "ast_template": recomputed.get("ast_template"),
        "source_cid": recomputed.get("source_cid"),
        "template_cid": recomputed.get("template_cid"),
        "param_names": recomputed.get("param_names"),
    }


def _span_of(node: typed.AST) -> dict[str, int]:
    return {
        "start_line": node.lineno,
        "start_col": node.col_offset,
        "end_line": node.end_lineno,
        "end_col": node.end_col_offset,
    }


def _locate_function(
    source_file: Any,
    function_name: Any,
    span: dict[str, Any],
) -> typed.FunctionDef | typed.AsyncFunctionDef | None:
    """Find the typed FunctionDef matching the memento's name (and span)."""
    start = span.get("start_line")
    function_leaf = (
        function_name.rsplit(".", 1)[-1] if isinstance(function_name, str) else None
    )
    matches = [
        n
        for n in source_file.functions()
        if isinstance(n, (typed.FunctionDef, typed.AsyncFunctionDef))
        and (
            function_name is None or n.name == function_name or n.name == function_leaf
        )
    ]
    if not matches:
        return None
    if isinstance(start, int) and len(matches) > 1:
        for n in matches:
            n_start = min((d.lineno for d in n.decorators), default=n.lineno)
            if n_start <= start <= (n.end_lineno or n.lineno):
                return n
    return matches[0]


def _locate_spanned_node(
    fn: typed.FunctionDef | typed.AsyncFunctionDef,
    span: dict[str, Any],
    source_kind: str,
) -> typed.AST | None:
    if source_kind == "python.ast-stmt":
        node_type: type = typed.stmt
    elif source_kind == "python.ast-expr":
        node_type = typed.expr
    else:
        return None
    wanted = {
        "start_line": span.get("start_line"),
        "start_col": span.get("start_col"),
        "end_line": span.get("end_line"),
        "end_col": span.get("end_col"),
    }
    for node in fn.walk():
        if not isinstance(node, node_type):
            continue
        if _span_of(node) == wanted:
            return node
    return None


def _node_source_locator(
    fn: typed.FunctionDef | typed.AsyncFunctionDef,
    rel_path: str,
    source: str,
    span: dict[str, Any],
    source_kind: str,
) -> dict[str, Any]:
    """Statement/expression recompute through typed Nodes only."""
    node = _locate_spanned_node(fn, span, source_kind)
    if node is None:
        raise SourceUnavailable(
            f"{source_kind} source node not found in `{rel_path}` near line "
            f"{span.get('start_line')}"
        )
    body_text = source_segment(source, node)
    if body_text is None:
        raise SourceUnavailable(
            f"{source_kind} source node in `{rel_path}` had no source segment"
        )
    params = function_param_names(fn)
    if isinstance(node, typed.stmt):
        ast_template = stmt_to_template(node, params)
    elif isinstance(node, typed.expr):
        ast_template = expr_to_template(node, params)
    else:
        raise SourceUnavailable(f"unsupported source node kind `{type(node).__name__}`")
    return {
        "file": rel_path,
        "source_cid": blake3_512_of(body_text.encode("utf-8")),
        "span": _span_of(node),
        "template_cid": template_cid_of_json(ast_template),
        "param_names": params,
        "ast_template": ast_template,
        "body_text": body_text,
    }


def resolve_from_roots(memento: dict[str, Any], roots: list[str]) -> dict[str, Any]:
    """Resolve a SourceMemento against the first root whose on-disk source aligns
    to the pinned CIDs. The source already lives SOMEWHERE on disk (the consumer's
    project, or the vendor's installed package); try each candidate root, reporting
    source unavailable loudly only if none aligns."""
    last: SourceUnavailable | None = None
    for root in roots:
        if not root:
            continue
        try:
            return resolve_source_memento(root, memento)
        except SourceUnavailable as exc:
            last = exc
    raise last or SourceUnavailable("no root resolved the source memento")


def importlib_package_root(file: str) -> str | None:
    """Root R such that R/<file> is the installed source for a vendor `.proof`
    whose `file` is `pkg/mod.py` — found via the package manager (pip/importlib),
    the same ecosystem-native resolution the kit uses for `.proof`s themselves."""
    if not isinstance(file, str) or not file:
        return None
    package = file.replace("\\", "/").split("/", 1)[0]
    try:
        from importlib.util import find_spec

        spec = find_spec(package)
    except Exception:
        return None
    if spec is None:
        return None
    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        return str(Path(next(iter(locations))).parent)
    origin = getattr(spec, "origin", None)
    return str(Path(origin).parent) if origin else None


def importlib_library_dir(library_tag: str) -> str | None:
    """Directory D such that D/<file> is the installed source when a `.proof`'s
    `file` is RELATIVE TO THE PACKAGE ITSELF (e.g. `lib/_function_base_impl.py`
    for a binding minted with `--project <site-packages>/numpy`).

    `importlib_package_root` returns the package's PARENT (good for `numpy/...`
    file paths). This returns the package DIR ITSELF, keyed by the binding's
    authoritative `target_library_tag` (`numpy`) rather than the file's first
    path segment (`lib`, a private submodule that is not an importable package).
    Found ecosystem-natively via importlib — pip already shipped the source."""
    if not isinstance(library_tag, str) or not library_tag:
        return None
    try:
        from importlib.util import find_spec

        spec = find_spec(library_tag)
    except Exception:
        return None
    if spec is None:
        return None
    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        return str(Path(next(iter(locations))))
    origin = getattr(spec, "origin", None)
    return str(Path(origin).parent) if origin else None
