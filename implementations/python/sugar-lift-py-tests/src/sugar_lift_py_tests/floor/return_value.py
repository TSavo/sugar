from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ReturnValue(FloorValue):
    """The outcome of a `return` statement: the value the path returns. A block
    carries it; when a body becomes a universe, a ReturnValue under its guards
    becomes `out == value`."""

    value: object

    def project_callsite_with(self, operation, ctx):
        return operation.project_return(self, ctx)
