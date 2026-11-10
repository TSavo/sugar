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
from contextvars import ContextVar

_PATH: ContextVar[tuple[str, ...]] = ContextVar("sugar_occurrence_path", default=())


def current_path() -> tuple[str, ...]:
    """The occurrence path of the reduction running now (outermost first)."""
    return _PATH.get()


def occurrence_key(site, path: tuple[str, ...] | None = None) -> str:
    """``str(site)`` qualified by the occurrence path of this evaluation."""
    if path is None:
        path = _PATH.get()
    text = str(site)
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


def call_frame_path(call_site, call_path: tuple[str, ...]) -> tuple[str, ...]:
    """The path a callee body reduces under: its call's path plus the call."""
    return (*call_path, f"call:{call_site}")
