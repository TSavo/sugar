"""Route-time authentication of preallocated effect coordinates.

Syntax (the tree) creates stable slots and rewrites names to EffectRef /
ObservationRef before sugar. Routing later associates a matched Halted
payload with a slot. This module holds that association for the duration of
one function-body reduction — it is not a lexical name map and not a second
construction door.

  syntax creates the coordinate;
  routing supplies its testimony.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from sugar_lift_py_tests.effect import Effect, require_effect

# Mutable map for the active reduction wave. Never a name→value scope.
_AUTH: ContextVar[dict[str, Effect] | None] = ContextVar(
    "effect_slot_auth", default=None
)


@contextmanager
def effect_auth_wave() -> Iterator[dict[str, Effect]]:
    """Open an empty authentication table for one function-body reduction."""
    table: dict[str, Effect] = {}
    token = _AUTH.set(table)
    try:
        yield table
    finally:
        _AUTH.reset(token)


def authenticate_slot(slot_id: str, effect: Effect) -> None:
    """Record that routing matched this slot to this effect payload."""
    table = _AUTH.get()
    if table is None:
        raise RuntimeError(
            "authenticate_slot outside effect_auth_wave: routing must only "
            "authenticate coordinates during a function-body reduction"
        )
    table[slot_id] = require_effect(effect)


def lookup_slot(slot_id: str) -> Effect | None:
    """The authenticated effect for this slot, or None if still open."""
    table = _AUTH.get()
    if table is None:
        return None
    return table.get(slot_id)
