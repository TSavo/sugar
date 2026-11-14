"""The calls a reduction leaves unanswered: each one becomes an ``undecided`` member.

Step 8 (PR B on #7766): a Python call whose callee nothing here resolved is
recorded once, as an ``undecided`` member with ``reason: unanswered``. Its
``symbol`` is the import door's target symbol when the call is an enrolled
imported call, else ``None`` (Q5: a call with no symbol is still a member).
Its ``site`` is the call's ``SourceFragmentCoordinateV1``.

There is one place a call is left unanswered: ``UnknownCalleeCallV1.faces``,
the two-faced call to a callee the lifter does not have (#7585). It records
the call here when a collector is active. Only the universe full scan that
mint packages opens a collector, so the preliminary fold and every seek see
exactly what they saw before. The member records the call and nothing about
what answers it, so it is the same staged or unstaged (row 0a.4).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE: ContextVar[list | None] = ContextVar("sugar_unanswered_calls", default=None)


@contextmanager
def collecting():
    """Collect the unanswered calls of the reductions run inside this extent."""
    calls: list = []
    token = _ACTIVE.set(calls)
    try:
        yield calls
    finally:
        _ACTIVE.reset(token)


def replay(calls) -> None:
    """Hand calls an earlier reduction recorded to the open collector, if any.

    A reduction read from ``tree_enumerate.owner_reduction``'s memo is not run
    again, so its unanswered calls reach the current collector this way.
    """
    collected = _ACTIVE.get()
    if collected is not None:
        collected.extend(calls)


def record(symbol: str | None, site) -> None:
    """Record one unanswered call at ``site``, if a collector is open."""
    calls = _ACTIVE.get()
    if calls is None:
        return
    if site is None:
        # Never dropped: a call the proof must owe has to have a site.
        raise ValueError("an unanswered call reached the collector with no site")
    from sugar_lift_py_tests.caller_parameter_contract import source_coordinate

    calls.append((symbol, source_coordinate(site)))
