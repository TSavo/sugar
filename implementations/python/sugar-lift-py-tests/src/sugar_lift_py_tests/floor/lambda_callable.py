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

    ``to_term`` is the value stated as its join symbol where it names one
    (``python:function``, ``_function_term``): a call of it at prove is an
    edge to that symbol.  Otherwise it is an opaque callable identity
    coordinate containing parameter names only.  Neither is a binder;
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

        stated = self._function_term()
        if stated is not None:
            return stated
        encoded_parameters = [str_const(parameter) for parameter in self.parameters]
        for key, default in self.defaults:
            encoded_parameters.append(
                ctor(
                    "python:lambda_default",
                    [str_const(key), default.to_term(owner="LambdaCallable")],
                )
            )
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

    def _function_term(self):
        """This function value as its join symbol (#7757 step 9):
        ``python:function(<symbol>, py.default(<param>, <value>)...,
        py.closure(<name>, <value>)...)``, ``<symbol>`` the join symbol of
        the ``def`` or lambda that built it (``bridge_source_symbol``, #8682),
        each default its statement evaluated under the formal it defaults,
        and each captured cell the value carries under its name: exactly the
        inputs a call of it supplies (``definition_edge_call``).  A post that
        returns the value states it so, and prove joins a call whose callee
        is this term to that symbol's contract through the one binder, as it
        joins any edge.

        None, and the opaque ``python:lambda`` identity stands, where the
        value names no symbol (no workspace root, the edge's
        ``fallback_target``), where its defaults cannot be paired with the
        formals they default, or where it carries an enclosing
        comprehension's cell (``closure``), which no input of its contract
        takes: a call of it stays owed."""
        from sugar_lift_py_tests.ir import ctor, str_const

        frame = self.source_call_frame
        definition = getattr(frame, "owner", None)
        if definition is None or self.closure:
            return None
        symbol_of = getattr(definition, "bridge_source_symbol", None)
        if symbol_of is None:
            return None
        # A unit seated under a workspace root by an absolute locus refuses
        # by name here, as the edge of a call of it does
        # (``definition_edge_call``): a refusal is never held and continued.
        symbol = symbol_of()
        if not symbol:
            return None
        defaulted = tuple(
            parameter.name
            for parameter in getattr(definition, "params", ())
            if getattr(parameter, "default", None) is not None
        )
        if len(defaulted) != len(self.defaults):
            return None
        inputs = [
            ctor(
                "py.default",
                [str_const(name), value.to_term(owner="LambdaCallable")],
            )
            for name, (_key, value) in zip(defaulted, self.defaults, strict=True)
        ]
        inputs += [
            ctor("py.closure", [str_const(name), value.to_term(owner="LambdaCallable")])
            for name, _coordinate, value in self.captured
        ]
        return ctor("python:function", [str_const(symbol), *inputs])

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
            packed=variadic_formals(frame),
            positional=positional,
            keywords=keywords,
            captured=captured,
            actuals=tuple(bound.arg_values),
            site=operation.site,
            call_occurrence=operation.call_occurrence,
            caller_ctx=caller_ctx,
            fallback_target=self.construction_identity,
        )


def variadic_formals(frame) -> tuple[str, ...]:
    """The ``*args`` and ``**kwargs`` formals of ``frame``'s signature, by
    name, in formal order (its ``parameter_kinds``): what a same-file
    definition's edge supplies packed (``definition_edge_call``)."""
    return tuple(
        name
        for name, kind in zip(
            getattr(frame, "parameters", ()),
            getattr(frame, "parameter_kinds", ()),
            strict=False,
        )
        if kind in ("vararg", "kwarg")
    )


def definition_edge_call(
    *,
    symbol_definition,
    signature,
    parameters,
    packed: tuple[str, ...],
    positional,
    keywords,
    captured,
    actuals,
    site,
    call_occurrence,
    caller_ctx,
    fallback_target: str,
    implicit: int = 0,
    **testimony,
):
    """THE call of a same-file definition as its coordinate and edge (#7757
    steps 5 and 6, the owner's ruling of 2026-11-15, "Edge, join at prove"):
    a function value (``LambdaCallable``), a class
    (``ClassDefinitionValue.callable_application_with``) and a method a
    class names explicitly (``Cls.m(...)``, ``super().m(...)``:
    ``object_value.method_edge_call``) alike.  A method called on an
    instance is the dispatched call instead
    (``receiver_dispatch.dispatch_edge_call``, #7757 step 8).
    The callee's body is never applied here.

    ``call:<target>(<actuals>, py.kwarg(...), py.default(...),
    py.closure(...), py.global(...))``, ``<target>`` the join symbol of
    ``symbol_definition`` (``bridge_source_symbol``) without its ``python:``
    namespace, carrying exactly what prove's one binder binds the callee's
    contract with:

    - each positional actual and each keyword actual as written; when the
      signature takes ``*args`` or ``**kwargs`` (``packed``, those formals
      by name), every formal by name, ``actuals`` in formal order: a
      parameter as ``py.kwarg(<name>, <value>)`` and each variadic formal
      as ``py.packed(<name>, <tuple|dict>)``, the packed value the call's
      own binding made.  A ``py.kwarg`` is always a keyword argument as
      Python reads one: it binds a named parameter, or goes into
      ``**kwargs``, never a variadic formal by its name; ``py.packed`` is
      the one spelling of a variadic formal supplied as it stands;
    - ``py.default(<param>, <value>)`` for each formal the call omits that
      ``signature`` (the ``def`` whose formals the contract states, or None)
      defaults, the value its ``def`` statement bound;
    - ``py.closure(<name>, <value>)`` for each captured name, the binding the
      call read;
    - ``py.global(<name>, <value>)`` for each ``global:`` input of the
      signature's contract, the binding where the call runs
      (``global_value_at_call``);
    - ``py.class(<argument key>, <class>)`` for each actual whose class is
      decided here (``receiver_dispatch.class_arguments``, step 8), and
      ``py.class("cell:<name>", <class>)`` for each captured cell whose
      value's class is (step 7).

    Sent down the path an imported call takes: the one unanswered call
    (``UnknownCalleeCallV1.faces``: completes under its ``completes`` atom,
    halts under the complement, both arms owe it), whose edge and
    ``undecided`` member carry the join symbol, so prove joins it to the
    callee's contract and each halt the contract states reaches the caller
    (#8690).  A callee with no join symbol (no workspace root) is the same
    call under ``fallback_target`` with no symbol: owed, joined to nothing.
    ``testimony`` is what the call form authenticated about the result
    (a class call's exception type), carried on the value unchanged.

    The completed value names, for each operand whose object the call may
    change, the formal of the callee's contract the binder binds it to
    (``CallSiteValue.after_labels``, ``_after_labels``): the call's
    completed face binds them under the call's key
    (``call_site_value.bind_after_call``), and the caller reads each such
    object after the call as ``python:after(<call result>, <formal>)``
    (#7757 step 7).  ``implicit`` is how many leading ``positional``
    actuals the call form supplied itself (a method's receiver), which no
    source operand is."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1
    from sugar_lift_py_tests.sugar.call_site_sugar import (
        _global_inputs,
        global_value_at_call,
        global_read_at_call,
    )
    from sugar_source_tree.nodes import current_module_execution_site

    owner_name = str(site)
    parameters = tuple(parameters)
    actuals = tuple(actuals)
    term_of = _edge_actual_terms(
        tuple(zip(parameters, actuals))
        if packed
        else (
            *((f"arg:{index}", value) for index, value in enumerate(positional)),
            *((f"kw:{name}", value) for name, value in keywords),
        ),
        site,
        owner_name,
    )
    if packed:
        # A formal ``*args`` / ``**kwargs`` is the packed value the call
        # binds, never one positional actual: every formal by name, each
        # variadic one as ``py.packed`` (a ``py.kwarg`` naming it would be a
        # keyword argument, which Python puts in ``**kwargs``).
        arguments = [
            ctor(
                "py.packed" if name in packed else "py.kwarg",
                [str_const(name), term_of(value)],
            )
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
            [term_of(value) for value in positional]
            + [
                ctor("py.kwarg", [str_const(name), term_of(value)])
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
    # The class of each captured cell's value where it is decided here,
    # keyed by the input it supplies (``cell:<name>``): what the callee's
    # ``class:cell:<name>`` input is bound to where its contract mutates the
    # cell's object through a method or an item store (#7757 step 7).
    from sugar_lift_py_tests.contract_input import CELL_INPUT, input_formal

    arguments += class_arguments(
        (),
        tuple(
            (input_formal(CELL_INPUT, name), value) for name, _cid, value in captured
        ),
    )
    # The value each module global the callee's contract reads is bound to
    # where the call runs (``global_read_at_call``, the value its
    # ``py.global`` states): an input of the contract as an actual is, so
    # the alias rule asks of it too (below).  A global the call supplies no
    # one value for is bound to a variable no contract binds, no object.
    globals_read = ()
    if signature is not None:
        module_site = current_module_execution_site()
        globals_read = tuple(
            value
            for value in (
                global_read_at_call(
                    signature, item.coordinate.name, caller_ctx, module_site=module_site
                )
                for item in _global_inputs(signature)
            )
            if value is not None
        )
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
    # The callee's contract states its post over its formals and inputs as
    # distinct objects: its own proof has no way to know two of them are one.
    # A call that binds one object to two of them -- or one and a container
    # holding it (``f(xs, xs)``, ``f(xs, [xs])``), or a formal and a module
    # global or captured cell the callee reads (``g(G)`` where ``g`` reads
    # ``G``) -- is not that contract's call: a store through one would leave
    # the other's entry value standing at prove, a lie.  It is the call no
    # contract answers, owed and joined to nothing, the alias rule's own test
    # (``object_identity.actuals_share_an_object``).
    from .object_identity import actuals_share_an_object

    if symbol is not None and actuals_share_an_object(
        (
            *positional,
            *(value for _name, value in keywords),
            *(value for _name, _cid, value in captured),
            *globals_read,
        )
    ):
        symbol = None
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
        after_labels=(
            ()
            if symbol is None
            else _after_labels(
                symbol_definition,
                signature,
                parameters,
                packed,
                positional,
                keywords,
                captured,
                implicit,
            )
        ),
        **testimony,
    )
    return UnknownCalleeCallV1(target).faces(callsite, site)


def _edge_actual_terms(operands, site, owner_name):
    """The term each actual of a same-file definition's edge stands as, by
    the one alias rule (``object_identity.as_bound_formals``).

    The callee's contract holds two formals as two objects
    (``container_mutation.same_object``: each formal its own coordinate), so
    it states, for ``def grow(a, b): a.append(1); return len(b)``, that the
    result is ``len(b)`` at entry.  That is false where one object reaches
    two actuals (``grow(xs, xs)``): binding the caller's contents to both
    formals would refute the truth and let the lie read ``sat``.  So an
    actual another actual of the same call may be, or hold, one of its
    objects is bound arrived (``arrived_as``, named by its operand) and
    stands as its object's identity (``identity_term``:
    ``python:object_read(<call>, <operand>, <arrival>)``), never the
    contents it arrived with: nothing the contract states about it decides
    the caller's claim.  Every other actual is its own term.

    ``operands`` are ``(label, value)`` pairs; the result maps a value to
    its term."""
    from .object_identity import as_bound_formals, identity_term

    labels = tuple(label for label, _value in operands)
    values = tuple(value for _label, value in operands)
    bound = as_bound_formals(values, labels)
    shared = {}
    for label, value, held in zip(labels, values, bound):
        if held is not value and id(value) not in shared:
            shared[id(value)] = identity_term(
                held, site, f"edge-actual/{label}", owner=owner_name
            )

    def term_of(value):
        term = shared.get(id(value))
        return value.to_term(owner=owner_name) if term is None else term

    return term_of


def _after_labels(
    symbol_definition,
    signature,
    parameters,
    packed,
    positional,
    keywords,
    captured,
    implicit,
):
    """``((slot, formal), ...)``: for each operand of a same-file
    definition's call whose object the call may change, the formal of the
    callee's contract the one binder binds it to (``CallSiteValue.
    after_labels``, #7757 step 7).  The slots are the exposure rule's
    (``container_mutation._call_slot``):

    - ``("arg", i)``: the ``i``-th source positional actual, bound to the
      parameter at its position (after the ``implicit`` actuals the call
      form supplied), and ``("kw", name)``: a keyword actual, bound to the
      parameter of its name -- only where the contract's formals are the
      signature's own (a function or a method, never a class whose
      constructor states them), the signature packs nothing (a ``*args`` or
      ``**kwargs`` formal binds what it packs), and the value is one a call
      may change (an immutable value is the same value after it);
    - ``("cell", name)``: each closure cell the call carries, bound to the
      contract input ``cell:<name>``, where the callee declares it
      ``nonlocal`` (it may rebind it) or it holds a value a call may
      change;
    - ``("global", name)``: each module global the callee declares
      ``global`` (it may rebind it), bound to the contract formal
      ``global:<name>`` its post states the global after the call over
      (``FunctionDef._cells_where_the_body_ends``)."""
    from sugar_lift_py_tests.contract_input import (
        CELL_INPUT,
        GLOBAL_INPUT,
        input_formal,
    )
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _immutable

    labels = []
    if signature is symbol_definition and not packed:
        parameters = tuple(parameters)
        for index, value in enumerate(tuple(positional)[implicit:]):
            position = implicit + index
            if position < len(parameters) and not _immutable(value):
                labels.append((("arg", index), parameters[position]))
        for name, value in keywords:
            if name in parameters and not _immutable(value):
                labels.append((("kw", name), name))
    rebound = _declared_nonlocal(symbol_definition) if captured else frozenset()
    for name, _cid, value in captured:
        if name in rebound or not _immutable(value):
            labels.append((("cell", name), input_formal(CELL_INPUT, name)))
    for name in _declared_global(symbol_definition):
        labels.append((("global", name), input_formal(GLOBAL_INPUT, name)))
    return tuple(labels)


def _declared_nonlocal(definition) -> frozenset:
    """The names ``definition`` (a ``def``) declares ``nonlocal``, read off
    CPython's symtable; none for any other definition (a lambda declares
    none)."""
    from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef

    if not isinstance(definition, (FunctionDef, AsyncFunctionDef)):
        return frozenset()
    table = definition.unit.function_symtable(
        definition.name, definition.line_col_span().start_line
    )
    return frozenset(
        symbol.get_name() for symbol in table.get_symbols() if symbol.is_nonlocal()
    )


def _declared_global(definition) -> tuple:
    """The names ``definition`` (a ``def``) declares ``global``, in name
    order, read off CPython's symtable; none for any other definition (a
    lambda declares none)."""
    from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef

    if not isinstance(definition, (FunctionDef, AsyncFunctionDef)):
        return ()
    table = definition.unit.function_symtable(
        definition.name, definition.line_col_span().start_line
    )
    return tuple(
        sorted(
            symbol.get_name()
            for symbol in table.get_symbols()
            if symbol.is_declared_global()
        )
    )


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
