from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue


@dataclass(frozen=True)
class ScopeUnbind(FloorValue):
    """A lexical deletion carried to the remaining statement scope."""

    names: tuple[str, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        return replace(ctx, temporal=ctx.temporal.unbind_names(self.names))
