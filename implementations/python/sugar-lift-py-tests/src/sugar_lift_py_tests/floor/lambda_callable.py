from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class LambdaCallable(FloorValue):
    """One-parameter lambda floor: apply lowers the body; to_term is identity.

    Lift-probe (before): keyword/positional lambda as a callsite actual hit
    ``floor_to_term`` → FactoryGap ``implement LambdaCallable.to_term``.
    Mechanism: missing floor projection (not a missing AST recognizer —
    LambdaSugar already owns ``Lambda`` and reduces here).

    ``to_term`` is a *callable identity* coordinate ``python:lambda(<param>)``.
    Body FOL under a free-var binding needs a reduction context ``to_term`` does
    not receive; fabricating a body term from a synthetic empty ctx would lie
    about free-variable capture. Apply remains the path that lowers the body
    under a real binding. Never invent a computed value.
    """

    parameter: str
    body: Any

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        # Source IR uses python:lambda(params…, body). Factory projection of a
        # first-class callable value without a reduction ctx carries identity
        # only (parameter name) — honest opaque coordinate, not body FOL.
        return ctor("python:lambda", [str_const(self.parameter)])

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
