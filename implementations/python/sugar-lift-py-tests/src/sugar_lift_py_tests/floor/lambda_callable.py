from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class LambdaCallable(FloorValue):
    """In-source lambda floor: parameters + body SugarBody for dig/apply.

    ``to_term`` is a *callable identity* coordinate
    ``python:lambda(<param>, ...)`` -- parameter names only. Body FOL under a
    free-var binding needs a reduction context ``to_term`` does not receive;
    fabricating a body term from a synthetic empty ctx would lie about free-
    variable capture. Apply remains the path that lowers the body under a
    real binding. Never invent a computed value.
    """

    parameters: tuple[str, ...]
    body: Any
    vararg_parameter: str | None = None
    kwarg_parameter: str | None = None

    @property
    def parameter(self) -> str:
        # Single-param readers (apply, older tests).
        if len(self.parameters) != 1:
            raise AttributeError(
                f"LambdaCallable.parameter requires exactly one formal, "
                f"got {self.parameters!r}"
            )
        return self.parameters[0]

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        # Source IR uses python:lambda(params…). Factory projection of a
        # first-class callable value without a reduction ctx carries identity
        # only (parameter names) -- honest opaque coordinate, not body FOL.
        encoded_parameters = [str_const(p) for p in self.parameters]
        if self.vararg_parameter is not None:
            encoded_parameters.append(str_const(f"*{self.vararg_parameter}"))
        if self.kwarg_parameter is not None:
            encoded_parameters.append(str_const(f"**{self.kwarg_parameter}"))
        return ctor("python:lambda", encoded_parameters)

    def apply(self, value: TermValue, ctx):
        from sugar_lift_py_tests.outcome import Incomplete, complete_value
        from sugar_lift_py_tests.temporal import bind_temporal

        if (
            len(self.parameters) != 1
            or self.vararg_parameter is not None
            or self.kwarg_parameter is not None
        ):
            raise TypeError(
                "LambdaCallable.apply owns single-parameter apply only; "
                f"got formals {self.parameters!r}, "
                f"vararg={self.vararg_parameter!r}, "
                f"kwarg={self.kwarg_parameter!r}"
            )
        next_ctx = bind_temporal(
            ctx,
            self.parameters[0],
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
