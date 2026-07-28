from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class LambdaCallable(FloorValue):
    """In-source lambda floor: parameters + body SugarBody for dig/apply.

    ``to_term`` is an opaque callable identity coordinate containing parameter
    names only.  ``python:lambda`` is an ordinary ctor in ProofIR, not a binder;
    placing the body beneath it would leak formal variables into global scope.
    """

    parameters: tuple[str, ...]
    body: Any
    construction_identity: str
    source_call_frame: Any = None
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
            [str_const(self.construction_identity), *encoded_parameters],
        )

    def apply(self, value: TermValue, ctx):
        del ctx
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_source_tree.panic import SugarNotWritten

        frame = self.source_call_frame
        if frame is None or len(self.parameters) != 1:
            raise SugarNotWritten(
                blame=self.construction_identity,
                owner="LambdaCallable.apply",
                observed="lambda has no single-actual source frame",
                requested="the ordinary SourceCallFrameV1 call door",
                fix="carry a source-visible frame or keep the callback loud",
            )
        return CallSiteValue(
            target_name="py.call",
            arg_values=(value,),
            parameters=frame.parameters,
            term=ctor(
                "py.call",
                [
                    self.to_term(owner="LambdaCallable"),
                    value.to_term(owner="LambdaCallable"),
                ],
            ),
            body=frame.body,
            source_call_frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(item.cid for item in frame.formal_coordinates),
        )
