from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class LambdaCallable(FloorValue):
    """In-source function floor: parameters + body SugarBody for dig/apply.

    A lambda's value, and the function a ``def`` statement builds before its
    decorators apply (``DecoratorApplicationSugar``): either is called
    through its own source frame by ``callable_application_with``.

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

    ``defaults`` are ``((key, value), ...)``: each default the lambda
    expression evaluated where it was evaluated, under the default's key
    (``nodes._default_evaluation_key``, ``LambdaSugar.defaults``).  Every
    call binds them (``bind_call``), so a formal the call omits binds the
    same object for every call; ``to_term`` names them, since two values of
    one lambda over different defaults are different callables.
    """

    parameters: tuple[str, ...]
    body: Any
    construction_identity: str
    source_call_frame: Any = None
    defaults: tuple[tuple[str, Any], ...] = ()
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

        encoded_parameters = [str_const(parameter) for parameter in self.parameters]
        for key, default in self.defaults:
            encoded_parameters.append(
                ctor(
                    "python:lambda_default",
                    [str_const(key), default.to_term(owner="LambdaCallable")],
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
        """Call the function where a value of it is called.

        A call of a same-file function value -- a module ``def``, a local
        ``def``, a lambda, a same-file decorator's result -- by name, through
        a name bound to it or as a callback (``key(item)`` inside a function
        given ``key=lambda v: ...``), is its coordinate and an edge, joined
        at prove exactly as an imported call is (the owner's ruling of
        2026-11-15, #7757 step 5).  Its body is never applied here: the
        frame is entered and the actuals bound by the one binder
        (``bind_call``) only to read what the call supplies, and the call is
        the one unanswered call (``UnknownCalleeCallV1``: two faces, owed)
        whose edge carries the callee's join symbol (``_edge_call``).  What
        the callee may do to the caller's objects takes the one exposure rule
        every unanswered call takes.  A generator function's or an ``async
        def``'s value keeps its frame's own application (``_applied_body``).
        """
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
        # Each actual is bound as the operation receiver it is
        # (``project_operation_receiver_outcome``), here and only here for
        # every call of a function's value -- a computed call, a spread
        # call, a call by name of a plain def or of a name bound to a lambda
        # (``CallSiteSugar._applied`` hands its actuals over as evaluated): a
        # constructed instance is the object its constructor's call
        # retained, so the alias rule at the one bind door
        # (``object_identity.as_bound_formals``) sees two formals given one
        # object (``poke(box, box)``) and binds each with its state unknown,
        # never two copies of the constructor's state.
        return as_operation_receivers(
            tuple(operation.arguments),
            ctx,
            lambda arguments: self._apply_to(operation, arguments, frame, ctx),
            owner="LambdaCallable.callable_application_with actual",
        )

    def _apply_to(self, operation, arguments, frame, ctx):
        """The application of ``callable_application_with`` over
        ``arguments``, the call's actuals as operation receivers."""
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.sugar.call_site_sugar import (
            enter_source_frame,
            with_captured_values,
        )

        owner = "LambdaCallable.callable_application_with"
        keyword_count = len(operation.keyword_names)
        positional = arguments[:-keyword_count] if keyword_count else arguments
        keywords = (
            tuple(zip(operation.keyword_names, arguments[-keyword_count:]))
            if keyword_count
            else ()
        )
        site = str(operation.site)
        # What the body reads from its enclosing scope is an input of this
        # call as its actuals are: two calls that read different values are
        # two coordinates (``ComputedCallSugar``'s ``py.closure`` operands).
        term = ctor(
            "py.call",
            [self.to_term(owner=site)]
            + [value.to_term(owner=site) for value in positional]
            + [
                ctor("py.kwarg", [str_const(name), value.to_term(owner=site)])
                for name, value in keywords
            ]
            + [
                ctor("py.closure", [str_const(name), value.to_term(owner=site)])
                for name, _cid, value in operation.captured
            ],
            symbol_kind="coordinate",
        )
        # The function reads enclosing locals (``FunctionDef._captured_bindings``,
        # ``Lambda._captured_bindings``): Python reads their cells when the
        # body runs.  A call standing where the enclosing scope does read
        # each there (``operation.captured``); a callback the caller handed
        # to a callee that runs it during that call carries them on its value
        # (``captured``).  Each is bound under the frame's captured
        # coordinate.  A call that carries not every one is refused by name
        # (``with_captured_values``), never read at the bindings the function
        # was made under.
        captured = operation.captured or self.captured
        caller_ctx = ctx
        ctx, module_halt = enter_source_frame(
            frame,
            ctx,
            owner=owner,
            blame=operation.site,
            covered=frozenset(name for name, _cid, _value in captured),
        )
        ctx = with_captured_values(
            ctx, frame, captured, site=operation.site, blame="py.call"
        )
        if module_halt is not None:
            return module_halt
        # The one binder binds the call (a call that does not fit the
        # signature is refused by name there), and each formal the call
        # omits reads the default its ``def`` statement or lambda expression
        # bound: what the edge supplies as ``py.default``.  No body is bound,
        # a generator function's and an ``async def``'s no more than any
        # other's: what its call returns is what its contract states, joined
        # at prove (#7757 step 6).
        from sugar_lift_py_tests.floor.object_value import bind_call

        bound = bind_call(
            "py.call",
            tuple(positional),
            keywords,
            frame=frame,
            parameters=frame.parameters,
            frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(
                item.cid for item in frame.formal_coordinates
            ),
            ctx=ctx,
            owner=owner,
            blame=operation.site,
            refuse=_refuse,
            term=term,
            defaults=self.defaults,
        )
        return self._edge_call(
            operation, positional, keywords, captured, bound, frame, caller_ctx
        )

    def _edge_call(
        self, operation, positional, keywords, captured, bound, frame, caller_ctx
    ):
        """The call of this function value as its coordinate and edge
        (#7757 step 5), through the one edge every call of a same-file
        definition stands as (``definition_edge_call``): the function's own
        ``def`` or lambda names the join symbol and states the signature."""
        return definition_edge_call(
            symbol_definition=frame.owner,
            signature=frame.owner,
            parameters=tuple(frame.parameters),
            packed=(
                self.vararg_parameter is not None or self.kwarg_parameter is not None
            ),
            positional=positional,
            keywords=keywords,
            captured=captured,
            actuals=tuple(bound.arg_values),
            site=operation.site,
            call_occurrence=operation.call_occurrence,
            caller_ctx=caller_ctx,
            fallback_target=self.construction_identity,
        )


def definition_edge_call(
    *,
    symbol_definition,
    signature,
    parameters,
    packed: bool,
    positional,
    keywords,
    captured,
    actuals,
    site,
    call_occurrence,
    caller_ctx,
    fallback_target: str,
    **testimony,
):
    """THE call of a same-file definition as its coordinate and edge (#7757
    steps 5 and 6, the owner's ruling of 2026-11-15, "Edge, join at prove"):
    a function value (``LambdaCallable``), a class
    (``ClassDefinitionValue.callable_application_with``) and a method whose
    receiver's class is decided (``object_value.method_edge_call``) alike.
    The callee's body is never applied here.

    ``call:<target>(<actuals>, py.kwarg(...), py.default(...),
    py.closure(...), py.global(...))``, ``<target>`` the join symbol of
    ``symbol_definition`` (``bridge_source_symbol``) without its ``python:``
    namespace, carrying exactly what prove's one binder binds the callee's
    contract with:

    - each positional actual and each keyword actual as written (every
      formal by name, ``py.kwarg``, when the signature takes ``*args`` or
      ``**kwargs`` -- ``packed`` -- its formal being the packed value the
      call binds, ``actuals`` in formal order);
    - ``py.default(<param>, <value>)`` for each formal the call omits that
      ``signature`` (the ``def`` whose formals the contract states, or None)
      defaults, the value its ``def`` statement bound;
    - ``py.closure(<name>, <value>)`` for each captured name, the binding the
      call read;
    - ``py.global(<name>, <value>)`` for each ``global:`` input of the
      signature's contract, the binding where the call runs
      (``global_value_at_call``);
    - ``py.class(<argument key>, <class>)`` for each actual whose class is
      decided here (``receiver_dispatch.class_arguments``, step 8).

    Sent down the path an imported call takes: the one unanswered call
    (``UnknownCalleeCallV1.faces``: completes under its ``completes`` atom,
    halts under the complement, both arms owe it), whose edge and
    ``undecided`` member carry the join symbol, so prove joins it to the
    callee's contract and each halt the contract states reaches the caller
    (#8690).  A callee with no join symbol (no workspace root) is the same
    call under ``fallback_target`` with no symbol: owed, joined to nothing.
    ``testimony`` is what the call form authenticated about the result
    (a class call's exception type), carried on the value unchanged."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1
    from sugar_lift_py_tests.sugar.call_site_sugar import (
        _global_inputs,
        global_value_at_call,
    )
    from sugar_source_tree.nodes import current_module_execution_site

    owner_name = str(site)
    parameters = tuple(parameters)
    actuals = tuple(actuals)
    if packed:
        # A formal ``*args`` / ``**kwargs`` is the packed value the call
        # binds, never one positional actual: every formal by name.
        arguments = [
            ctor("py.kwarg", [str_const(name), value.to_term(owner=owner_name)])
            for name, value in zip(parameters, actuals)
        ]
    else:
        supplied = set(parameters[: len(positional)]) | {
            name for name, _value in keywords
        }
        defaulted = {
            parameter.name
            for parameter in getattr(signature, "params", ())
            if getattr(parameter, "default", None) is not None
        }
        arguments = (
            [value.to_term(owner=owner_name) for value in positional]
            + [
                ctor("py.kwarg", [str_const(name), value.to_term(owner=owner_name)])
                for name, value in keywords
            ]
            + [
                ctor("py.default", [str_const(name), value.to_term(owner=owner_name)])
                for name, value in zip(parameters, actuals)
                if name not in supplied and name in defaulted
            ]
        )
    arguments += [
        ctor("py.closure", [str_const(name), value.to_term(owner=owner_name)])
        for name, _cid, value in captured
    ]
    # The class of each actual whose class is decided here, keyed by the
    # argument it is (``receiver_dispatch.class_arguments``, #7757 step 8):
    # what the callee's ``class:<param>`` input is bound to where its contract
    # dispatches a method call on that parameter.
    from sugar_lift_py_tests.receiver_dispatch import class_arguments

    if packed:
        arguments += class_arguments((), tuple(zip(parameters, actuals)))
    else:
        arguments += class_arguments(tuple(positional), tuple(keywords))
    if signature is not None:
        module_site = current_module_execution_site()
        arguments += [
            ctor(
                "py.global",
                [
                    str_const(item.coordinate.name),
                    global_value_at_call(
                        signature,
                        item.coordinate.name,
                        caller_ctx,
                        module_site=module_site,
                        call_site=site,
                    ),
                ],
            )
            for item in _global_inputs(signature)
        ]
    symbol = symbol_definition.bridge_source_symbol()
    target = (
        symbol[len(_PYTHON_NAMESPACE) :]
        if symbol is not None and symbol.startswith(_PYTHON_NAMESPACE)
        else fallback_target
    )
    callsite = CallSiteValue(
        target_name=target,
        arg_values=tuple(positional) + tuple(value for _n, value in keywords),
        parameters=(),
        term=ctor(call_symbol(target), arguments, symbol_kind="coordinate"),
        body=None,
        keyword_names=tuple(name for name, _value in keywords),
        site=site,
        call_occurrence=call_occurrence,
        authenticated_target_symbol=symbol,
        **testimony,
    )
    return UnknownCalleeCallV1(target).faces(callsite, site)


# The namespace a join symbol is spelled under (``SourceUnit.definition_symbol``).
_PYTHON_NAMESPACE = "python:"


def _refuse(*, owner, blame, observed, requested, fix):
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
    )


def as_operation_receivers(values, ctx, then, *, owner: str):
    """``then`` over ``values``, each projected to the operation receiver it
    is (``project_operation_receiver_outcome``) in order, on every face of
    each projection.  The one conversion of a call's actuals: the
    application of a function's value (``LambdaCallable.
    callable_application_with``) makes it for its actuals, and a call by
    name of any other callee (``CallSiteSugar._applied``) for its own, each
    actual once."""
    if not values:
        return then(())
    head, *rest = values
    return head.project_operation_receiver_outcome(ctx, owner=owner).and_then(
        lambda actual: as_operation_receivers(
            tuple(rest), ctx, lambda tail: then((actual, *tail)), owner=owner
        )
    )
