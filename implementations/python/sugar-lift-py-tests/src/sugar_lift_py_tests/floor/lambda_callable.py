from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class LambdaCallable(FloorValue):
    """In-source lambda floor: parameters + body SugarBody for dig/apply.

    ``to_term`` is a *callable identity* coordinate
    ``python:lambda(<param>, ..., <body>)``. The source tree has already masked
    formals and substituted authenticated lexical captures before constructing
    the body sugar, so its term is a faithful callable body, not reconstruction.
    """

    parameters: tuple[str, ...]
    body: Any
    default_values: tuple[Any, ...] = ()
    keyword_only_parameters: tuple[str, ...] = ()
    keyword_only_default_values: tuple[Any | None, ...] = ()
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

        from sugar_lift_py_tests.outcome import complete_value

        body_value = complete_value(self.body.desugar(), owner="LambdaCallable")
        default_offset = len(self.parameters) - len(self.default_values)
        encoded_parameters = []
        for index, parameter in enumerate(self.parameters):
            if index < default_offset:
                encoded_parameters.append(str_const(parameter))
                continue
            default = self.default_values[index - default_offset]
            encoded_parameters.append(
                ctor(
                    "python:lambda_default",
                    [str_const(parameter), default.to_term(owner="LambdaCallable")],
                )
            )
        if self.vararg_parameter is not None:
            encoded_parameters.append(str_const(f"*{self.vararg_parameter}"))
        for parameter, default in zip(
            self.keyword_only_parameters,
            self.keyword_only_default_values,
            strict=True,
        ):
            if default is None:
                encoded_parameters.append(
                    ctor("python:lambda_kwonly", [str_const(parameter)])
                )
            else:
                encoded_parameters.append(
                    ctor(
                        "python:lambda_kwonly_default",
                        [
                            str_const(parameter),
                            default.to_term(owner="LambdaCallable"),
                        ],
                    )
                )
        if self.kwarg_parameter is not None:
            encoded_parameters.append(str_const(f"**{self.kwarg_parameter}"))
        return ctor(
            "python:lambda",
            [
                *encoded_parameters,
                body_value.to_term(owner="LambdaCallable.body"),
            ],
        )

    def apply(self, value: TermValue, ctx):
        from sugar_lift_py_tests.outcome import Incomplete, complete_value
        from sugar_lift_py_tests.temporal import bind_temporal

        if (
            len(self.parameters) != 1
            or self.keyword_only_parameters
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
        outcome = self.body.desugar(next_ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        result = complete_value(outcome, owner="LambdaCallable")
        if not isinstance(result, TermValue):
            raise TypeError("LambdaCallable body must reduce to TermValue")
        return result
