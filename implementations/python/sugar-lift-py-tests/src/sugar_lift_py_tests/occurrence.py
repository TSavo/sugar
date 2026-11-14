"""The dynamic occurrence of a source site: which evaluation of it this is.

A site key (``file [start, end) node``) names where an operation is written,
not which evaluation of it ran. An unrolled loop reduces its body once per
iteration and a source function's body is reduced once per call, so the same
site is evaluated several times. An opaque atom keyed on the site alone --
``python:source_call.completes(.., site)``, a C call's result, the exception an
undetermined raise threw -- names ONE unknown for all of them: it claims that
iteration 2's call completes iff iteration 1's did and returns the same object.

The law: every site key carries the dynamic occurrence path, the iteration
index of each enclosing unrolled loop and the call occurrence of each enclosing
source frame, so each evaluation of a site is its own atom. A site evaluated
outside any loop iteration or callee frame keeps its plain spelling.

The path is the dynamic extent of a reduction, so it lives in a ``ContextVar``
that the loop unroller and the callee-frame reducer set while they reduce. A
value that keys a term on its site captures the key when it is minted, never
when its term is later read outside that extent.
"""

from __future__ import annotations

from contextlib import contextmanager

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_source_tree.construction_cache import AmbientVar

# Ambient to memo rows: a row that read the path is served only under it.
_PATH: AmbientVar = AmbientVar("sugar_occurrence_path", default=())


def current_path() -> tuple[str, ...]:
    """The occurrence path of the reduction running now (outermost first)."""
    return _PATH.get()


def occurrence_key(site, path: tuple[str, ...] | None = None) -> str:
    """The site's coordinate CID qualified by the occurrence path of this
    evaluation (#7808): content, never the site object's ``repr``."""
    if path is None:
        path = _PATH.get()
    text = site_coordinate_cid(site)
    if not path:
        return text
    return f"{text}@{'/'.join(path)}"


@contextmanager
def occurrence_path(path: tuple[str, ...]):
    """Reduce under exactly ``path`` (a callee frame: its call's path + itself)."""
    token = _PATH.set(tuple(path))
    try:
        yield
    finally:
        _PATH.reset(token)


@contextmanager
def entered(segment: str):
    """Reduce one level deeper: an iteration of an enclosing unrolled loop."""
    with occurrence_path((*_PATH.get(), segment)):
        yield


def loop_iteration_segment(target_cid: str, index: int) -> str:
    digest = target_cid.split(":", 1)[-1][:16]
    return f"loop:{digest}#{index}"


def site_coordinate_cid(site) -> str:
    """The identity of an occurrence's site, as content, never as a repr.

    - a source fragment: the CID of its ``SourceFragmentCoordinateV1``
      (``source_cid`` plus line/col span). The same on every mint and every
      machine; a fragment's ``repr`` embedded ``unit.filename``;
    - a ``SourceFragmentCoordinateV1``: its CID;
    - a string: a synthetic call's content-addressed slot id (a manager
      protocol's ``__enter__``/``__exit__`` call has no source call of its
      own; its site is the with-item's ``…#exit_face`` slot, already content);
      a string spelling a fragment's repr is refused.

    Anything else is refused by name, never spelled some other way (#7808).
    """
    from sugar_lift_py_tests.caller_parameter_contract import source_coordinate
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    if isinstance(site, SourceFragmentCoordinateV1):
        return site.cid
    if hasattr(site, "line_col_span") and hasattr(site, "source_cid"):
        return source_coordinate(site).cid
    if isinstance(site, str) and site and not site.startswith("<SourceFragment"):
        return site
    from sugar_lift_py_tests.gap.info import GapKind, GapLocus
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="occurrence.site_coordinate_cid",
        blame=None if site is None else type(site).__name__,
        observed="an occurrence with no source coordinate",
        requested="a source fragment, its coordinate, or a content-addressed slot id",
        fix="carry the call's source fragment to the occurrence",
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )


def call_frame_path(call_site, call_path: tuple[str, ...]) -> tuple[str, ...]:
    """The path a callee body reduces under: its call's path plus the call.

    The call is named by its site's coordinate CID (#7808), never its repr.
    """
    return (*call_path, call_symbol(site_coordinate_cid(call_site)))


def occurrence_term(site, path: tuple[str, ...] | None = None):
    """``python:occurrence(<site coordinate CID>, <path segment>…)``: one
    evaluation of a call site, as a term (#7808).

    The static site first, as its ``SourceFragmentCoordinateV1`` CID, then the
    dynamic occurrence path (each enclosing unrolled loop iteration and callee
    frame). It replaces ``occurrence_key``'s ``str(site)@path`` string in the
    call terms ``python:call_result`` and ``python:unknown_callee_call``.
    """
    from sugar_lift_py_tests.ir import ctor, str_const

    if path is None:
        path = _PATH.get()
    return ctor(
        "python:occurrence",
        (str_const(site_coordinate_cid(site)), *(str_const(seg) for seg in path)),
    )
