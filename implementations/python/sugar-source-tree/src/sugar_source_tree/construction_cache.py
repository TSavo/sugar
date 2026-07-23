"""Work memoization for typed construction — field *data*, not Node shells.

Each ``(ref, reporter, control_context)`` site owns a field row. Slots resolve
at most once into that row on first need. ``materialize`` may construct Node
shells freely; each shell reads the shared row. Source and shadow backends use
the same map (different ``ref``).
"""

from __future__ import annotations

from typing import Any


class ConstructionCache:
    """Shared field rows keyed by backend site + reporter + control context."""

    __slots__ = ("fields",)

    def __init__(self) -> None:
        # key -> {slot_name: resolved value}
        self.fields: dict[tuple, dict[str, Any]] = {}

    @staticmethod
    def key(
        ref: object,
        reporter: object,
        control_context: object,
    ) -> tuple:
        loop_targets = getattr(control_context, "loop_targets", ())
        exception_slots = getattr(control_context, "exception_slots", ())
        return (id(ref), id(reporter), loop_targets, exception_slots)
