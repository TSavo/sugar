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

    ``closure`` is each final-member coordinate the body reads through an
    enclosing comprehension's cell, with what the cell holds once the
    comprehension is done (#7757 item 7, ``LambdaSugar.closure_coordinates``).
    The body is reduced after the comprehension, so the call binds these
    (``CallSiteValue.closure``); ``to_term`` names them, since two lambdas
    built at one site over different finals are different callables.

    The enclosing function's locals the body reads are not in ``closure``:
    Python reads them when the lambda is called, so a call binds each from
    its own scope (``Lambda._captured_bindings``, ``Call._closure_cells``,
    ``ComputedCallSugar.captured``).  ``apply`` (the lambda passed on) knows
    no such binding and refuses them by name.
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
    closure: tuple[tuple[str, Any], ...] = ()

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
        for coordinate, value in self.closure:
            encoded_parameters.append(
                ctor(
                    "python:lambda_closure_cell",
                    [str_const(coordinate), value.to_term(owner="LambdaCallable")],
                )
            )
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
        captured = tuple(getattr(frame, "captured_names", ()) or ())
        if captured:
            # The lambda reads enclosing locals (``Lambda._captured_bindings``):
            # Python reads their cells when the callback runs, and nothing
            # here knows what the enclosing scope binds then.  Never the
            # bindings it was made under.
            raise SugarNotWritten(
                blame=self.construction_identity,
                owner="LambdaCallable.apply",
                observed=(
                    "lambda passed on reads enclosing locals whose binding at "
                    f"the call is not known: {captured!r}"
                ),
                requested="the enclosing scope's binding of each name at the call",
                fix=(
                    "call the lambda where its enclosing scope binds each "
                    "captured name, or keep the callback loud"
                ),
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
            closure=self.closure,
        )
