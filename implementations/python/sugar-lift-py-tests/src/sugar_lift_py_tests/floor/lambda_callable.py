from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class LambdaCallable(FloorValue):
    parameter: str
    body: Any

    def apply(self, value: TermValue, ctx):
        from sugar_lift_py_tests.outcome import Incomplete, complete_value
        from sugar_lift_py_tests.temporal import bind_temporal

        next_ctx = bind_temporal(
            ctx,
            self.parameter,
            value,
            owner="LambdaCallable",
            blame="<lambda>",
        )
        outcome = self.body.reduce(next_ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        result = complete_value(outcome, owner="LambdaCallable")
        if not isinstance(result, TermValue):
            raise TypeError("LambdaCallable body must reduce to TermValue")
        return result
