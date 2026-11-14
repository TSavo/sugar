"""What each assert reduced to inside its owner's one reduction (#7757, item 28).

An assert means what it means at its place in its function (or module): after
every binding before it, under the path that reaches it. So it is reduced once,
inside its owner's reduction, and nowhere alone. ``AssertSugar.desugar``
records ``(site coordinate, outcome)`` here when a collector is open; the one
collector is opened by ``tree_enumerate.owner_reduction``, and every reader of
an assert (the universe rows, ``facts``, ``implications``) reads that record.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE: ContextVar[list | None] = ContextVar("sugar_assert_reductions", default=None)


@contextmanager
def collecting():
    """Collect what every assert reduced inside this extent reduced to."""
    reduced: list = []
    token = _ACTIVE.set(reduced)
    try:
        yield reduced
    finally:
        _ACTIVE.reset(token)


def record(site, outcome) -> None:
    """Record one reduction of the assert at ``site``, if a collector is open."""
    reduced = _ACTIVE.get()
    if reduced is None:
        return
    from sugar_lift_py_tests.caller_parameter_contract import source_coordinate

    reduced.append((source_coordinate(site), outcome))
