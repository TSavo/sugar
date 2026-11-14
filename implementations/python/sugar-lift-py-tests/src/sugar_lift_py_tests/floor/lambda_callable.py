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
    ``ComputedCallSugar.captured``).  ``callable_application_with`` (the
    lambda passed on and called there) knows no such binding and refuses
    them by name.
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
        carries is bound before the body reduces.
        """
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.sugar.call_site_sugar import (
            bind_source_frame_call,
            enter_source_frame,
            require_frame_captures,
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
        # The lambda reads enclosing locals (``Lambda._captured_bindings``):
        # Python reads their cells when the callback runs, and nothing here
        # knows what the enclosing scope binds then.  Never the bindings it
        # was made under: refused by name, as any call that does not carry
        # its callee's captured names is (``require_frame_captures``).
        require_frame_captures(frame, (), site=operation.site)
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
            frame, ctx, owner=owner, blame=operation.site
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
