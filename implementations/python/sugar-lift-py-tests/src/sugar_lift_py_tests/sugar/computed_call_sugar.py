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
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ComputedCallSugar(ConstructedTermSugar):
    callee: ConstructedTermSugar
    args: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)
    keywords: tuple[tuple[str, ConstructedTermSugar], ...] = ()
    source_call_frame: object | None = dataclass_field(default=None, compare=False)
    # ``((name, coordinate cid, sugar), ...)``: a call of a lambda carries,
    # for each enclosing local its body reads, the binding the calling scope
    # holds at the call (``Call._closure_cells``), as a call of a local
    # ``def`` does (``CallSiteSugar.captured``).  Read here, at the call, and
    # bound under the frame's captured coordinate before the body runs
    # (``with_captured_values``); never the binding the lambda was made in.
    captured: tuple = dataclass_field(default=(), compare=False)

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
        prefix = "def A(fs, x):\n    return fs[0](x)\n\n"
        return _call_pair(
            name="computed_call_return",
            owner_sugar="ComputedCallSugar",
            truthful=prefix + "def test_a():\n    assert A([lambda z: z], 5) == 5\n",
            lying=prefix + "def test_a():\n    assert A([lambda z: z], 5) == 6\n",
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
        # actual's walrus.
        from sugar_lift_py_tests.floor.named_expression_value import written_by

        return self.callee.desugar(ctx).and_then(
            lambda callee: self._collect(
                callee, self.args, (), written_by(callee, ctx)
            )
        )

    def _collect(self, callee, remaining: tuple, accumulated: tuple, ctx) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import written_by

        if remaining:
            head, *rest = remaining
            return head.desugar(ctx).and_then(
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
        from sugar_lift_py_tests.floor.named_expression_value import written_by

        if remaining:
            (name, sugar), *rest = remaining
            return sugar.desugar(ctx).and_then(
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
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.sugar.call_site_sugar import read_captured_values

        owner = str(self.site)
        keyword_terms = [
            ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
            for name, value in kw_values
        ]
        # What the lambda reads from its enclosing scope is an input of this
        # call as its actuals are (``CallSiteSugar._collect_kwargs``).
        captured_values = read_captured_values(self.captured, ctx, site=self.site)
        closure_terms = [
            ctor("py.closure", [str_const(name), value.to_term(owner=owner)])
            for name, _cid, value in captured_values
        ]
        term = ctor(
            "py.call",
            [callee.to_term(owner=owner)]
            + [value.to_term(owner=owner) for value in positional]
            + keyword_terms
            + closure_terms,
            symbol_kind="coordinate",
        )
        frame = self.source_call_frame
        if frame is not None:
            # A lambda called where it is written: the plain call's routine,
            # so its body runs here and every face of it is this call's.
            from sugar_lift_py_tests.sugar.call_site_sugar import (
                bind_source_frame_call,
                enter_source_frame,
                with_captured_values,
            )

            ctx, module_halt = enter_source_frame(
                frame,
                ctx,
                owner="ComputedCallSugar.desugar",
                blame=self.site,
                covered=frozenset(name for name, _cid, _value in captured_values),
            )
            # Every name the lambda reads from its enclosing function is bound
            # from the calling scope at this call, as a local ``def``'s call
            # binds it, or the call is refused by name: the body never reads
            # the binding the lambda was made under.
            ctx = with_captured_values(
                ctx, frame, captured_values, site=self.site, blame="py.call"
            )
            if module_halt is not None:
                return module_halt
            from sugar_lift_py_tests.floor import LambdaCallable

            return bind_source_frame_call(
                "py.call",
                positional,
                kw_values,
                frame=frame,
                ctx=ctx,
                owner="ComputedCallSugar.desugar",
                blame=self.site,
                term=term,
                # The defaults the called lambda value's expression evaluated
                # (``LambdaCallable.defaults``).
                defaults=(
                    callee.defaults if isinstance(callee, LambdaCallable) else ()
                ),
            ).producer_outcome(ctx)
        from sugar_lift_py_tests.floor import (
            BoundMethodValue,
            ClassDefinitionValue,
            LambdaCallable,
        )

        if isinstance(
            callee, (ClassDefinitionValue, BoundMethodValue, LambdaCallable)
        ):
            from sugar_lift_py_tests.callable_application import CallableApplication

            # A computed callee that reduced to a source class is constructor
            # application (``cls(None)`` after a classmethod binds cls); one
            # that reduced to a bound method is that method's call; one that
            # reduced to a lambda (``fs[0](x)``, a formal given a lambda) is
            # the lambda's call.  Each binds and applies through the one
            # routine.  Any other computed callee is the unanswered call
            # below; this does not invent calling an import member or an
            # unknown formal.
            return callee.callable_application_with(
                CallableApplication(
                    positional + tuple(value for _, value in kw_values),
                    tuple(name for name, _ in kw_values),
                    self.site,
                ),
                ctx,
            )
        callsite = CallSiteValue(
            target_name="py.call",
            arg_values=(callee, *positional, *(value for _, value in kw_values)),
            parameters=(),
            term=term,
            body=None,  # the dig is CUED, not inlined here
            site=self.site,
        )
        # No frame, and the callee is no class, bound method or lambda the
        # one routine applies: a formal, an opaque call's result, a value
        # (``len = 5; len(x)``), whatever it is, nothing here resolved what
        # runs.  The call is the one unanswered citation, two-faced and owed
        # (#7585, #7757), never a completion.
        from sugar_lift_py_tests.ir import _Var
        from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

        callee_term = callee.to_term(owner=owner)
        name = callee_term.name if type(callee_term) is _Var else "py.call"
        return UnknownCalleeCallV1(name).faces(callsite, self.site)
