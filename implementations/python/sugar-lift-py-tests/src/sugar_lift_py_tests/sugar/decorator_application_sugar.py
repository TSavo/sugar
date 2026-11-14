"""A decorated ``def``/``class`` statement's value: ``d1(d2(<definition>))``.

Python evaluates a statement's decorator expressions in source order, builds
the function or class, then calls each decorator on it innermost first and
binds the name to the last result (the language reference, "Function
definitions" and "Class definitions").  ``DecoratorApplicationSugar`` is that
application, and the only one (#7757): the statement reduces it, a read of the
name is it, and a call of the name calls its value
(``sugar_source_tree.nodes.DecoratedDefinitionRef``).

Each decorator was decided at construction from its binding where the
statement runs (``sugar_source_tree.nodes._decorator_step``) into one
``DecoratorStepV1``:

- ``identity``: a builtin the one builtin door names whose application returns
  its argument (``typing.final``, ``abc.abstractmethod``, a modeled
  ``dataclasses.dataclass``, ``functools.wraps(w)``);
- ``refused``: a builtin with no modeled application, refused by name;
- ``unanswered``: an imported decorator (or a factory call of one).  Nothing
  here answers it, so its application is the ``undecided`` member under the
  import table's target symbol (reason ``unanswered``, ``UnknownCalleeCallV1``)
  and the name is bound to that unanswered call's result, never the bare
  definition;
- ``apply``: a source ``def`` (its frame), a ``class`` or decorated
  definition (its value's sugar), or any other expression: its value is
  called on the definition through the one call routine,
  ``callable_application_with`` (``enter_source_frame``, ``bind_call``,
  ``CallSiteValue.producer_outcome``), so every face of the decorator's body
  is the statement's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class DecoratorStepV1:
    """One decorator of a statement, as its binding decided it."""

    kind: str
    site: object = field(compare=False)
    spelling: str = ""
    symbol: str | None = None
    refusal: str | None = None
    # ``unanswered``: a factory call evaluated before its result is applied.
    evaluate: object = field(default=None, compare=False)
    # ``apply``: the decorator is this source ``def``'s function ...
    frame: object = field(default=None, compare=False)
    # ... or the value this sugar reduces to.
    callee: object = field(default=None, compare=False)

    @classmethod
    def identity(cls, site, spelling):
        return cls("identity", site, spelling)

    @classmethod
    def refused(cls, site, spelling, refusal):
        return cls("refused", site, spelling, refusal=refusal)

    @classmethod
    def unanswered(cls, site, spelling, symbol, *, evaluate=None):
        return cls("unanswered", site, spelling, symbol=symbol, evaluate=evaluate)

    @classmethod
    def apply(cls, site, spelling, *, frame=None, callee=None):
        if (frame is None) == (callee is None):
            raise TypeError("DecoratorStepV1.apply takes exactly one of frame, callee")
        return cls("apply", site, spelling, frame=frame, callee=callee)

    def evaluated(self, ctx, then) -> ExitSet:
        """The decorator expression evaluated where the statement runs, then
        ``then(decorator)``: the decorator's value for ``apply``, else None
        (nothing here is called)."""
        if self.kind == "refused":
            _refuse(self.site, self.refusal)
        if self.kind == "unanswered":
            if self.evaluate is None:
                return then(None)
            return self.evaluate.desugar(ctx).and_then(lambda _value: then(None))
        if self.kind == "apply":
            if self.frame is not None:
                return then(_function_value(self.frame, self.site))
            return self.callee.desugar(ctx).and_then(
                lambda value: _returned(value, ctx).and_then(then)
            )
        return then(None)

    def applied(self, decorator, value, ctx) -> ExitSet:
        """``decorator(value)``: this decorator applied to ``value``."""
        if self.kind == "identity":
            return ExitSet.completed(value)
        if self.kind == "unanswered":
            return _unanswered_application(self, value, ctx)
        from sugar_lift_py_tests.callable_application import CallableApplication

        return decorator.callable_application_with(
            CallableApplication((value,), (), self.site, owner="DecoratorApplication"),
            ctx,
        ).and_then(lambda result: _returned(result, ctx))


@dataclass(frozen=True)
class DecoratorApplicationSugar(ConstructedTermSugar):
    """``d1(d2(<definition>))``: a decorated statement's one value."""

    definition_name: str
    decorators: tuple[DecoratorStepV1, ...]
    # The ``def``'s own call frame, or the ``class`` statement's sugar.
    definition_frame: object = field(compare=False)
    definition_class: object = field(compare=False)
    refusal: str | None
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        # A source decorator replaces the function: the call returns what the
        # decorator's result returns, never what the bare body returns.
        prefix = (
            "def ten(fn):\n"
            "    return lambda z: z * 10\n\n"
            "@ten\n"
            "def A(z):\n"
            "    return z\n\n"
        )
        return _call_pair(
            name="decorator_application",
            owner_sugar="DecoratorApplicationSugar",
            truthful=prefix + "def test_a():\n    assert A(2) == 20\n",
            lying=prefix + "def test_a():\n    assert A(2) == 2\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:decorator-application",
            (self.occurrence_term(owner=owner), str_const(self.definition_name)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        if self.refusal is not None:
            _refuse(self.site, self.refusal)
        return self._evaluate(self.decorators, (), ctx)

    def _evaluate(self, remaining: tuple, evaluated: tuple, ctx) -> ExitSet:
        # The decorator expressions, top to bottom, before the definition.
        if remaining:
            head, *rest = remaining
            return head.evaluated(
                ctx,
                lambda decorator: self._evaluate(
                    tuple(rest), evaluated + ((head, decorator),), ctx
                ),
            )
        return self._definition_value(ctx).and_then(
            lambda value: self._apply(evaluated, value, ctx)
        )

    def _definition_value(self, ctx) -> ExitSet:
        if self.definition_class is not None:
            return self.definition_class.desugar(ctx)
        return ExitSet.completed(_function_value(self.definition_frame, self.site))

    def _apply(self, evaluated: tuple, value, ctx) -> ExitSet:
        # Innermost (last written) first.
        if not evaluated:
            return ExitSet.completed(value)
        *outer, (step, decorator) = evaluated
        return step.applied(decorator, value, ctx).and_then(
            lambda result: self._apply(tuple(outer), result, ctx)
        )


def _returned(value, ctx) -> ExitSet:
    """What a call returned, as a value: a source call's one authenticated
    return (``project_operation_receiver_outcome``), the value itself for
    anything else."""
    return value.project_operation_receiver_outcome(
        ctx, owner="DecoratorApplicationSugar"
    )


def _function_value(frame, site):
    """The function a source ``def`` builds: its own frame, called through
    the one callable protocol (``LambdaCallable.callable_application_with``)."""
    from sugar_lift_py_tests.floor import LambdaCallable

    owner = getattr(frame, "owner", None)
    sealed = (owner.fragment if owner is not None else site).seal()
    return LambdaCallable(
        parameters=tuple(frame.parameters),
        body=frame.body,
        construction_identity=(
            f"{sealed.source_cid}@{sealed.start}:{sealed.end}#{sealed.cid}"
        ),
        source_call_frame=frame,
    )


def _unanswered_application(step, value, ctx) -> ExitSet:
    """``d(value)`` for a decorator nothing here answers: bound by the one
    binder, bodiless, and two-faced as every unanswered call is
    (``UnknownCalleeCallV1``): the ``undecided`` member under the import
    table's target symbol, completing with this call's own result."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1
    from sugar_lift_py_tests.sugar.call_site_sugar import bind_source_frame_call

    symbol = step.symbol
    name = (
        symbol[len("python:") :]
        if isinstance(symbol, str) and symbol.startswith("python:")
        else step.spelling
    )
    owner = str(step.site)
    callsite = bind_source_frame_call(
        name,
        (value,),
        (),
        frame=None,
        ctx=ctx,
        owner="DecoratorApplicationSugar",
        blame=step.site,
        term=ctor(
            call_symbol(name),
            [value.to_term(owner=owner)],
            symbol_kind="coordinate",
        ),
        authenticated_target_symbol=symbol,
    )
    return UnknownCalleeCallV1(name).faces(callsite, step.site)


def _refuse(site, observed):
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner="DecoratorApplicationSugar",
        blame=site,
        observed=observed,
        requested="a decorator application this lift answers",
        fix="model the decorator's application, or keep the statement loud",
    )
