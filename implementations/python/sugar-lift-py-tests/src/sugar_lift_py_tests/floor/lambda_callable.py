from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


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
    ``ComputedCallSugar.captured``).  A lambda passed to a callee that runs
    it during the call (``Call._carry_argument_cells``) is called while the
    caller's bindings stand as they were at that call, so the value carries
    them (``captured``: ``((name, coordinate cid, value), ...)``) and
    ``callable_application_with`` binds them under the frame's captured
    coordinates.  A lambda value that does not carry every captured name
    (returned, stored, or passed to a callee that may keep it) is refused by
    name there.
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
    captured: tuple[tuple[str, str, Any], ...] = ()

    @property
    def parameter(self) -> str:
        # Single-param readers (older tests).
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
        # Two values of one lambda carrying different bindings of what its
        # body reads from the caller are different callables.
        for _name, coordinate, value in self.captured:
            encoded_parameters.append(
                ctor(
                    "python:lambda_captured_cell",
                    [str_const(coordinate), value.to_term(owner="LambdaCallable")],
                )
            )
        return ctor(
            "python:lambda",
            [str_const(self.construction_identity), *encoded_parameters],
        )

    def callable_application_with(self, operation, ctx):
        """Call the lambda where a value of it is called: a callback.

        ``key(item)`` inside a function given ``key=lambda v: ...``, or
        ``fs[0](x)`` over a list of lambdas, is the same call as a lambda
        called where it is written: the frame is entered
        (``enter_source_frame``), the actuals are bound by the one binder
        (``bind_call``) and the body is applied by
        ``CallSiteValue.producer_outcome``, so every face of the body --
        its raises among them -- is this call's.  The closure the value
        carries is bound before the body reduces, and so is each enclosing
        binding it carries from the call it was passed to (``captured``).
        """
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.sugar.call_site_sugar import (
            bind_source_frame_call,
            enter_source_frame,
            with_captured_values,
        )
        from sugar_source_tree.panic import SugarNotWritten

        owner = "LambdaCallable.callable_application_with"
        frame = self.source_call_frame
        if frame is None:
            raise SugarNotWritten(
                blame=operation.site,
                owner=owner,
                observed=f"lambda {self.construction_identity} has no source frame",
                requested="the ordinary SourceCallFrameV1 call door",
                fix="carry the lambda's source-visible frame or keep the call loud",
            )
        keyword_count = len(operation.keyword_names)
        positional = (
            operation.arguments[:-keyword_count]
            if keyword_count
            else operation.arguments
        )
        keywords = (
            tuple(zip(operation.keyword_names, operation.arguments[-keyword_count:]))
            if keyword_count
            else ()
        )
        site = str(operation.site)
        term = ctor(
            "py.call",
            [self.to_term(owner=site)]
            + [value.to_term(owner=site) for value in positional]
            + [
                ctor("py.kwarg", [str_const(name), value.to_term(owner=site)])
                for name, value in keywords
            ],
            symbol_kind="coordinate",
        )
        ctx, module_halt = enter_source_frame(
            frame,
            ctx,
            owner=owner,
            blame=operation.site,
            covered=frozenset(name for name, _cid, _value in self.captured),
        )
        # The lambda reads enclosing locals (``Lambda._captured_bindings``):
        # Python reads their cells when the callback runs.  The value carries
        # the caller's binding of each from the call it was passed to, whose
        # callee runs it during that call (``captured``); it is bound under
        # the frame's captured coordinate.  A value that does not carry every
        # one is refused by name (``with_captured_values``), never read at
        # the bindings it was made under.
        ctx = with_captured_values(
            ctx, frame, self.captured, site=operation.site, blame="py.call"
        )
        if module_halt is not None:
            return module_halt
        return bind_source_frame_call(
            "py.call",
            tuple(positional),
            keywords,
            frame=frame,
            ctx=ctx,
            owner=owner,
            blame=operation.site,
            term=term,
            closure=self.closure,
        ).producer_outcome(ctx)
