from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class LambdaCallable(FloorValue):
    parameter: str
    body: Any

    def apply(self, value: TermValue, ctx) -> TermValue:
        from sugar_lift_py_tests.outcome import complete_value

        next_ctx = ctx.with_temporal(ctx.temporal.bind_value(self.parameter, value))
        result = complete_value(self.body.reduce(next_ctx), owner="LambdaCallable")
        if not isinstance(result, TermValue):
            raise TypeError("LambdaCallable body must reduce to TermValue")
        return result
