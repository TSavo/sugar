"""A computed callee call `<callee>(<args>)` -- the callee is an expression,
not a bare name or attribute (`fs[0](x)`, `d["k"](x)`). A COMPOSITION, not a
new mechanism: the callee reduces like any value (whatever sugar its own node
built -- SubscriptSugar for `fs[0]`, and so on), and the call stands as the
coordinate `py.call(callee, args)` with `symbol_kind="coordinate"`. There is no
receiver whose runtime type selects a method body here (the callee itself IS
the thing being invoked), so no `runtime_dispatch_receiver` rides this value --
unlike MethodCallSugar's attribute-callee case.

A callee whose own node has no `.sugar()` (a Lambda called inline, for example)
stays loud through the ordinary recursion: this sugar never masks that gap.

Keyword arguments and ``**`` spreads ride as explicit ``py.kwarg`` operands,
the same bridge vocabulary used by named and method calls. They are pointed at,
not interpreted or silently expanded here.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


@dataclass(frozen=True)
class ComputedCallSugar(ConstructedTermSugar):
    callee: ConstructedTermSugar
    args: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)
    keywords: tuple[tuple[str, ConstructedTermSugar], ...] = ()
    source_call_frame: object | None = dataclass_field(default=None, compare=False)
    # ``((name, coordinate cid, sugar), ...)``: a call of a lambda, or of a
    # local ``def``'s function value, carries, for each enclosing local its
    # body reads, the binding the calling scope holds at the call
    # (``Call._closure_cells``).  Read here, at the call, and bound under the
    # frame's captured coordinate before the body runs (``with_captured_values``,
    # ``LambdaCallable.callable_application_with``); never the binding the
    # function was made in.
    captured: tuple = dataclass_field(default=(), compare=False)
    # Where the call is (``Node.source_occurrence``): stamped on the call the
    # applied function value binds (``CallableApplication.call_occurrence``).
    call_occurrence: object = dataclass_field(default=None, compare=False)
    # Exception construction only: the class a ``raise`` (or an exception
    # group's member) authenticated for this call's callee
    # (``Raise._raised_operand_sugar``), as ``CallSiteSugar`` and
    # ``MethodCallSugar`` carry it.  The instance a source class's
    # constructor builds carries it (``ClassDefinitionValue``); any other
    # callee's call is unanswered and carries none.
    exception_type_coordinate: object = dataclass_field(default=None, compare=False)
    exception_type_mro: tuple | None = dataclass_field(default=None, compare=False)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.callee, owner="ComputedCallSugar.callee")
        for argument in self.args:
            require_constructed_term_sugar(argument, owner="ComputedCallSugar.args")
        for _name, argument in self.keywords:
            require_constructed_term_sugar(argument, owner="ComputedCallSugar.keywords")

    @classmethod
    def witnesses(cls):
        # fs[0] is a real computed callee with a decidable shape: the
        # coordinate's identity against a contradicting asserted value.
        return _assertion_pair(
            name="computed_call_return",
            owner_sugar="ComputedCallSugar",
            statements="fs = [lambda z: z]\nx = 5",
            truthful="fs[0](x) == 5",
            lying="fs[0](x) == 6",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        frame = self.source_call_frame
        authority = (
            ctor("python:no-source-call-frame", ())
            if frame is None
            else ctor(
                "python:source-call-frame",
                (str_const(frame.frame_cid),),
                symbol_kind="coordinate",
            )
        )
        return ctor(
            "python:computed-call-construction",
            (
                self.occurrence_term(owner=owner),
                self.callee.to_term(owner=owner),
                ctor(
                    "python:positional-arguments",
                    tuple(argument.to_term(owner=owner) for argument in self.args),
                ),
                ctor(
                    "python:keyword-arguments",
                    tuple(
                        ctor(
                            "python:keyword-argument",
                            (str_const(name), argument.to_term(owner=owner)),
                        )
                        for name, argument in self.keywords
                    ),
                ),
                authority,
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # The callee, then each actual, then the call: each is evaluated with
        # the walrus writes of the ones before it applied (``written_by``), so
        # a later actual and the closure cells the call reads see an earlier
        # actual's walrus, and an actual's halt carries every write before
        # it (``evaluated_after``).
        from sugar_lift_py_tests.floor.named_expression_value import written_by

        return self.callee.desugar(ctx).and_then(
            lambda callee: self._collect(
                callee, self.args, (), written_by(callee, ctx)
            )
        )

    def _collect(self, callee, remaining: tuple, accumulated: tuple, ctx) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            evaluated_after,
            written_by,
        )

        if remaining:
            head, *rest = remaining
            return evaluated_after((callee, *accumulated), head, ctx).and_then(
                lambda value: self._collect(
                    callee,
                    tuple(rest),
                    accumulated + (value,),
                    written_by(value, ctx),
                )
            )
        return self._collect_kwargs(callee, self.keywords, (), accumulated, ctx)

    def _collect_kwargs(
        self, callee, remaining: tuple, kw_values: tuple, positional: tuple, ctx
    ) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            evaluated_after,
            written_by,
        )

        if remaining:
            (name, sugar), *rest = remaining
            earlier = (callee, *positional, *(value for _name, value in kw_values))
            return evaluated_after(earlier, sugar, ctx).and_then(
                lambda value: self._collect_kwargs(
                    callee,
                    tuple(rest),
                    kw_values + ((name, value),),
                    positional,
                    written_by(value, ctx),
                )
            )
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )

        # The callee and the actuals are the call's operands: a walrus in any
        # of them binds once, through the one operand door.
        names = tuple(name for name, _value in kw_values)
        count = len(positional)
        return consume_operands(
            lambda presented_callee, *values: self._call(
                presented_callee,
                tuple(values[:count]),
                tuple(zip(names, values[count:])),
                ctx,
            ),
            callee,
            *positional,
            *(value for _name, value in kw_values),
        )

    def _call(self, callee, positional: tuple, kw_values: tuple, ctx) -> ExitSet:
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.sugar.call_site_sugar import read_captured_values

        owner = str(self.site)
        # What the lambda reads from its enclosing scope is an input of this
        # call as its actuals are (``CallSiteSugar._collect_kwargs``).
        captured_values = read_captured_values(self.captured, ctx, site=self.site)
        closure_terms = [
            ctor("py.closure", [str_const(name), value.to_term(owner=owner)])
            for name, _cid, value in captured_values
        ]
        term = value_call_term(callee, positional, kw_values, owner, closure_terms)
        # A lambda called where it is written, ``(lambda x: ...)(y)``, or
        # through the name an assignment bound it to, is the call of the
        # lambda's value like any other (``apply_callee``,
        # ``LambdaCallable.callable_application_with``): its coordinate and
        # edge, joined at prove (#7757 step 6).  Its body is never applied
        # here; the frame ``Call._construct_sugar`` seated only names the
        # closure cells the call reads (``captured``).
        #
        # A same-file definition's edge carries, on its completed face, what
        # it names of what it was handed (its cells, its actuals, the globals
        # it declares), under this call's key, exactly as a call by name does
        # (``CallSiteSugar._collect_kwargs``): the exposure rule reads each
        # object it may have changed there, ``python:after(<call result>,
        # <formal>)`` (#7757 step 7).
        from sugar_lift_py_tests.floor.call_site_value import bind_after_call

        def unanswered():
            return unanswered_value_call(
                callee, positional, kw_values, self.site, term=term
            )

        return bind_after_call(
            apply_callee(
                callee,
                positional,
                kw_values,
                self.site,
                ctx,
                unanswered,
                exception_type_coordinate=self.exception_type_coordinate,
                exception_type_mro=self.exception_type_mro,
                captured=captured_values,
                call_occurrence=self.call_occurrence,
            ),
            self.site,
        )


def value_call_term(callee, positional, kw_values, owner, extra=()):
    """``py.call(<callee>, <positional>..., py.kwarg(...)..., <extra>...)``:
    the coordinate of a call of a value nothing here resolved
    (``unanswered_value_call``), its callee the value's own term."""
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "py.call",
        [callee.to_term(owner=owner)]
        + [value.to_term(owner=owner) for value in positional]
        + [
            ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
            for name, value in kw_values
        ]
        + list(extra),
        symbol_kind="coordinate",
    )


def unanswered_value_call(callee, positional, kw_values, site, *, term=None):
    """``callee(*positional, **kw_values)`` for a called value nothing here
    resolved (``apply_callee``'s ``unanswered``): the one unanswered call of
    a value, two-faced and owed (``UnknownCalleeCallV1``), over ``term``
    (``value_call_term`` when None), named by the callee's variable where its
    term is one, else ``py.call``.  A call written ``f(x)`` over such a value
    (``ComputedCallSugar``) and a decorator applied to its function
    (``DecoratorStepV1.applied``) are this one call."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import _Var
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    owner = str(site)
    if term is None:
        term = value_call_term(callee, positional, kw_values, owner)
    callsite = CallSiteValue(
        target_name="py.call",
        arg_values=(callee, *positional, *(value for _, value in kw_values)),
        parameters=(),
        term=term,
        body=None,  # the dig is CUED, not inlined here
        site=site,
    )
    callee_term = callee.to_term(owner=owner)
    name = callee_term.name if type(callee_term) is _Var else "py.call"
    return UnknownCalleeCallV1(name).faces(callsite, site)


def apply_callee(
    callee,
    positional,
    kw_values,
    site,
    ctx,
    unanswered,
    *,
    exception_type_coordinate=None,
    exception_type_mro=None,
    captured=(),
    call_occurrence=None,
) -> ExitSet:
    """``callee(*positional, **kw_values)`` for a callee already reduced to a
    value: the one routine a called value is applied by.

    A source class is constructor application (``cls(None)`` after a
    classmethod binds cls); a bound method is that method's call (the one
    dispatched call, ``BoundMethodValue``); a lambda (``fs[0](x)``, a formal given a lambda,
    an instance field holding one) is the lambda's call.  Each binds and
    applies through ``callable_application_with``.  Any other callee -- a
    formal, an opaque call's result, a value (``len = 5; len(x)``), an
    undecided attribute read -- is a callee nothing here resolved: the call
    is ``unanswered()``, the caller's one unanswered citation, two-faced and
    owed (#7585, #7757), never a completion.  This does not invent calling an
    import member or an unknown formal.

    ``exception_type_coordinate``/``exception_type_mro``: the class a raise
    authenticated for the callee (``ComputedCallSugar``), handed to the
    application so the instance a source class's constructor builds carries
    it (``ClassDefinitionValue.callable_application_with``).

    ``captured``: what the call read at the call for each enclosing local
    the called function's body reads (``read_captured_values``), and
    ``call_occurrence``: where the call is.  A function value binds the
    first under its frame's captured coordinates and stamps the second on
    the call it binds (``LambdaCallable.callable_application_with``).
    """
    from sugar_lift_py_tests.floor import (
        BoundMethodValue,
        ClassDefinitionValue,
        LambdaCallable,
    )
    from sugar_lift_py_tests.floor.builtin_descriptor_value import (
        BuiltinDescriptorValue,
        PropertyAccessorValue,
    )

    # A builtin descriptor (``staticmethod(f)`` calls ``f``; a
    # ``classmethod`` or ``property`` object is not callable) and a
    # property's ``x.setter`` (the property copy) answer their own call
    # (#7757, A5).
    applicable = (
        ClassDefinitionValue,
        BoundMethodValue,
        LambdaCallable,
        BuiltinDescriptorValue,
        PropertyAccessorValue,
    )
    if not isinstance(callee, applicable):
        return unanswered()
    from sugar_lift_py_tests.callable_application import CallableApplication

    return callee.callable_application_with(
        CallableApplication(
            tuple(positional) + tuple(value for _, value in kw_values),
            tuple(name for name, _ in kw_values),
            site,
            call_occurrence=call_occurrence,
            exception_type_coordinate=exception_type_coordinate,
            exception_type_mro=exception_type_mro,
            captured=tuple(captured),
        ),
        ctx,
    )
