"""A decorated ``def``/``class`` statement's value: ``d1(d2(<definition>))``.

Python evaluates a statement's decorator expressions in source order, then a
``def``'s defaults, builds the function (carrying those default values) or
class, then calls each decorator on it innermost first and binds the name to
the last result (the language reference, "Function definitions" and "Class
definitions").  So ``x = 1; @d def f(a=x): ...; x = 2`` binds ``a`` to 1 at
every call that omits it, through whatever ``d`` returned that calls the
function.  ``DecoratorApplicationSugar`` is that
application, and the only one (#7757): the statement reduces it once and binds
its result under the statement's evaluation key, a read of the name reads that
key, and a call of the name calls the value it holds
(``sugar_source_tree.nodes.DecoratedDefinitionRef``).

Each decorator was decided at construction from its binding where the
statement runs (``sugar_source_tree.nodes._decorator_step``) into one
``DecoratorStepV1``:

- ``identity``: a builtin the one builtin door names whose application returns
  its argument (``typing.final``, ``abc.abstractmethod``, a modeled
  ``dataclasses.dataclass``, ``functools.wraps(w)``);
- ``refused``: a source decorator this does not carry as a value (an
  ``async def`` or generator function used as a decorator), refused by name;
- ``unanswered``: an imported decorator (or a factory call of one), or a
  builtin with no modeled application (``functools.lru_cache``,
  ``typing.overload``, a builtin decorator factory).  Nothing here answers
  it, so its application is the ``undecided`` member under the target
  symbol (reason ``unanswered``, ``UnknownCalleeCallV1``) and the name is
  bound to that unanswered call's result, never the bare definition.  The
  statement completes: only a read or call of the name is undecided, never
  the run that binds it;
- ``apply``: a source ``def``, ``class`` or decorated definition (its
  value's sugar, the one read of its name), or any other expression: its
  value is called on the definition through the one call routine,
  ``callable_application_with`` (``enter_source_frame``, ``bind_call``,
  ``CallSiteValue.producer_outcome``), so every face of the decorator's body
  is the statement's.

An ``async def`` or generator function is no value this carries
(``uncarried``): its decorator expressions are evaluated, and what they make of
it is one unanswered call, the ``undecided`` citation under the outermost
decorator's target symbol where it has one.

An undecorated ``def`` read as a value is the same application with no
decorator to apply (``nodes.SourceUnit.function_definition_for_read``): the
function its statement built, its own frame, with no default evaluated at the
read.  Its statement bound each default under its per-parameter key
(``DefinitionDefaultsSugar``) and every call of the function reads those
keys, as a call by name does.

A method of a class that reads the class's name (``Box()`` inside
``Box.run``) is constructed while the class statement's own application is
under construction: the class sugar constructs its methods.  That read holds
no application of its own, only the reference it is the sugar of
(``reference``).  It reduces when the method is called, after the statement's
construction closed: it reads the statement's key where a reduction bound it,
and where none did it is the application, as every other read of the name is,
asked for again through the one memo door (``_application_read_again``).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair

# The statements whose application a read constructed under that statement's
# own construction is evaluating now (``_application_read_again``), by the
# statement's name and evaluation key.  A read of the name reached while its
# own application is being evaluated (a class body or a decorator reading the
# name the statement has not bound yet) is the application reading its own
# result: refused by name, never evaluated again inside itself.
_READ_AGAIN: ContextVar[frozenset] = ContextVar(
    "decorator_application_read_again", default=frozenset()
)


@dataclass(frozen=True)
class DecoratorStepV1:
    """One decorator of a statement, as its binding decided it."""

    kind: str
    site: object = field(compare=False)
    spelling: str = ""
    symbol: str | None = None
    refusal: str | None = None
    # ``unanswered``: what is evaluated, in order, before the result is
    # applied by nothing (an imported factory call, a builtin factory's
    # arguments).
    evaluate: tuple = field(default=(), compare=False)
    # ``apply``: the decorator is the value this sugar reduces to (a source
    # ``def`` read as a value among them: the one read of its name).
    callee: object = field(default=None, compare=False)

    @classmethod
    def identity(cls, site, spelling):
        return cls("identity", site, spelling)

    @classmethod
    def refused(cls, site, spelling, refusal):
        return cls("refused", site, spelling, refusal=refusal)

    @classmethod
    def unanswered(cls, site, spelling, symbol, *, evaluate=()):
        return cls(
            "unanswered", site, spelling, symbol=symbol, evaluate=tuple(evaluate)
        )

    @classmethod
    def apply(cls, site, spelling, *, callee):
        if callee is None:
            raise TypeError("DecoratorStepV1.apply takes the decorator's callee")
        return cls("apply", site, spelling, callee=callee)

    def evaluated(self, ctx, then) -> ExitSet:
        """The decorator expression evaluated where the statement runs, then
        ``then(decorator)``: the decorator's value for ``apply``, else None
        (nothing here is called)."""
        if self.kind == "refused":
            _refuse(self.site, self.refusal)
        if self.kind == "unanswered":
            return _evaluated_in_order(self.evaluate, ctx, lambda: then(None))
        if self.kind == "apply":
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
    # The key the ``def``/``class`` statement binds the application's result
    # under (``nodes._definition_evaluation_key``).  Python applies the
    # decorators once, where the statement runs: a read or call of the name
    # reads this key wherever the statement's reduction bound it, and never
    # applies the decorators again.  The statement's own application carries
    # None (``nodes._decorated_statement_sugar``).
    evaluation: str | None = None
    # The definition is an ``async def`` or generator function, no value this
    # carries: the application is one unanswered call (``_uncarried``).
    uncarried: bool = False
    # ``((key, sugar), ...)``: the ``def``'s defaults, left to right, under
    # their per-parameter keys (``nodes._definition_default_evaluations``).
    # Python evaluates them when the statement runs, after the decorator
    # expressions and before any decorator applies; the function value the
    # decorators receive carries them (``LambdaCallable.defaults``) and
    # every call of it binds them (``object_value.bind_call``).
    defaults: tuple = field(default=(), compare=False)
    # True on the statement's own application
    # (``nodes._decorated_statement_sugar``): a decorated ``class`` statement
    # runs its body there, once, as an undecorated one does
    # (``ClassDefinitionSugar.statement_run``), and the application carries
    # what the body's callees stored ahead of what the decorators' calls
    # stored, for the statement to lay in its record.  False on every read of
    # the name, which runs no class body's stores.
    runs_statement: bool = field(default=False, compare=False)
    # A read of a ``class``'s name constructed while that class statement's
    # own application was under construction up the stack (a method of the
    # class reading the class's name, ``nodes._decorator_application_sugar``):
    # the reference this read is the sugar of
    # (``nodes.DecoratedDefinitionRef``), the handle the application is asked
    # for again by where the read reduces (``_application_read_again``).  A
    # lookup aid, never testimony: the read is testified by its name, site
    # and key.  None on every other application, and on the statement's own
    # (``nodes._decorated_statement_sugar``).
    reference: object = field(
        default=None, compare=False, repr=False, metadata={"testimony": "lookup"}
    )

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
        # The read of the name is the key's wherever the statement bound it,
        # and the application itself where no reduction bound it (a module
        # function's read after import).  A read of a class's name
        # constructed while that class statement was under construction (a
        # method of the class reading the class's name) is the same read: the
        # key's, else the application, asked for where the read reduces
        # (``_application_read_again``).  Only an application that reads its
        # own result refuses.
        bound = self._bound_by_statement(ctx)
        if bound is not None:
            return ExitSet.completed(bound)
        if self.reference is not None:
            return self._application_read_again(ctx)
        if self.refusal is not None:
            _refuse(self.site, self.refusal)
        return self._evaluate(self.decorators, (), ctx)

    def _application_read_again(self, ctx) -> ExitSet:
        """The application this read stands for, read where the read reduces.

        The read was constructed while its class statement's application was
        under construction up the stack, so it holds none.  That was true of
        the construction, not of the program: a class statement's value never
        runs its methods' bodies, and a method reads the class's name only
        when it is called, after the statement ran.  So the reference's sugar
        is asked for again through the one memo door (``Node.sugar``, which
        serves a row only where the frames it asked about are open or closed
        as they were): with the statement's construction closed it is the
        application, and it reduces as every read of the name does.

        Refused by name, as before, where the application reads its own
        result: its construction is still open where this reduces, or it is
        being evaluated now (``_READ_AGAIN``: a class body or a decorator
        that reads the name before the statement bound it)."""
        reading = _READ_AGAIN.get()
        statement = (self.definition_name, self.evaluation)
        if statement in reading:
            _refuse(self.site, self.refusal)
        application = self.reference.sugar()
        if application.reference is not None:
            _refuse(self.site, self.refusal)
        token = _READ_AGAIN.set(reading | {statement})
        try:
            return application.desugar(ctx)
        finally:
            _READ_AGAIN.reset(token)

    def as_statement(self):
        """The statement's own application where a block runs it with no key
        to bind (``nodes._decorated_statement_sugar``): a decorated ``class``
        statement's in statement position (``ExprStatementSugar``,
        ``record_statement_value``), which lays what the body's callees and
        the decorators' calls stored in the statement's record, as the
        undecorated statement's (``ClassDefinitionSugar.as_statement``).
        Itself otherwise."""
        if not self.runs_statement or self.definition_class is None:
            return self
        from sugar_lift_py_tests.sugar.expr_statement_sugar import (
            ExprStatementSugar,
        )

        return ExprStatementSugar(value=self, site=self.site)

    def _bound_by_statement(self, ctx):
        """The value the statement bound the name to under its evaluation
        key (``AssignSugar`` over the statement's own application), or None
        where no reduction running the statement bound it here (a module
        function read after import): the read is then the application."""
        if self.evaluation is None:
            return None
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if temporal is None:
            return None
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            evaluation_read_here,
        )

        key = evaluation_read_here(temporal, self.evaluation)
        return temporal.value_read(key)

    def _evaluate(self, remaining: tuple, evaluated: tuple, ctx) -> ExitSet:
        # The decorator expressions, top to bottom, then the defaults, before
        # the definition.
        if remaining:
            head, *rest = remaining
            return head.evaluated(
                ctx,
                lambda decorator: self._evaluate(
                    tuple(rest), evaluated + ((head, decorator),), ctx
                ),
            )

        def define(defaults) -> ExitSet:
            if self.uncarried:
                return self._uncarried(ctx)
            return self._definition_value(defaults, ctx).and_then(
                lambda value: self._decorated(evaluated, value, ctx)
            )

        return self._evaluated_defaults(ctx, define)

    def _evaluated_defaults(self, ctx, then) -> ExitSet:
        """The ``def``'s defaults evaluated where the statement runs, left to
        right, each halt a face of the statement, then ``then(((key,
        value), ...))`` on every completed path: the operands of the
        function value, through the one operand door, as a lambda
        expression's are (``LambdaSugar``)."""
        if not self.defaults:
            return then(())
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
        )

        keys = tuple(key for key, _sugar in self.defaults)
        return reduce_operands(
            tuple(sugar for _key, sugar in self.defaults), ctx
        ).and_then(
            lambda values: consume_operands(
                lambda *completed: then(tuple(zip(keys, completed, strict=True))),
                *values,
            )
        )

    def _uncarried(self, ctx) -> ExitSet:
        """``d1(d2(<definition>))`` over a definition this carries no value
        of: one call nothing here answers, the ``undecided`` member under the
        outermost decorator's target symbol where it has one (reason
        ``unanswered``), completing with that call's own result."""
        outermost = self.decorators[0]
        return _unanswered_call(
            outermost.symbol,
            outermost.spelling or self.definition_name,
            (),
            outermost.site,
            ctx,
        )

    def _definition_value(self, defaults, ctx) -> ExitSet:
        if self.definition_class is not None:
            if self.runs_statement:
                # The class statement runs here: its body runs once, after
                # the decorator expressions, and each completed face is the
                # class carrying what the body's callees stored, as the
                # undecorated statement's run is
                # (``ClassDefinitionSugar.as_statement``).
                return self.definition_class.statement_run().desugar(ctx)
            return self.definition_class.desugar(ctx)
        return ExitSet.completed(
            _function_value(self.definition_frame, self.site, defaults=defaults)
        )

    def _decorated(self, evaluated: tuple, value, ctx) -> ExitSet:
        """The decorators applied to ``value``, the definition's value: an
        operand of the application (``consume_operands``).  The decorators
        receive the class beneath what its body's callees stored, and are
        called in the context those stores wrote (``written_by``): the body
        ran before them.  Each completed result carries the body's stores
        ahead of the decorators' own, Python's order; a halt of a decorator
        carries them first in its record."""
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            written_by,
        )

        after = written_by(value, ctx)
        return consume_operands(
            lambda definition: self._apply(evaluated, definition, after), value
        )

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


def _function_value(frame, site, *, defaults=()):
    """The function a source ``def`` builds: its own frame, called through
    the one callable protocol (``LambdaCallable.callable_application_with``),
    carrying the ``(key, value)`` of each default its statement evaluated
    (``defaults``), which every call binds."""
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
        defaults=tuple(defaults),
    )


def _evaluated_in_order(sugars, ctx, then) -> ExitSet:
    """Each of ``sugars`` evaluated in order, every face of each kept, then
    ``then()`` on every completed path."""
    if not sugars:
        return then()
    head, *rest = sugars
    return head.desugar(ctx).and_then(
        lambda _value: _evaluated_in_order(tuple(rest), ctx, then)
    )


def _unanswered_application(step, value, ctx) -> ExitSet:
    """``d(value)`` for a decorator nothing here answers: the ``undecided``
    member under its target symbol (``_unanswered_call``)."""
    return _unanswered_call(step.symbol, step.spelling, (value,), step.site, ctx)


def _unanswered_call(symbol, spelling, arguments, site, ctx) -> ExitSet:
    """A call of a decorator nothing here answers on ``arguments``: bound by
    the one binder, bodiless, and two-faced as every unanswered call is
    (``UnknownCalleeCallV1``): the ``undecided`` member under ``symbol``
    (the import table's or the builtin door's target symbol, None where the
    decorator has none), completing with this call's own result."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1
    from sugar_lift_py_tests.sugar.call_site_sugar import bind_source_frame_call

    name = (
        symbol[len("python:") :]
        if isinstance(symbol, str) and symbol.startswith("python:")
        else spelling
    )
    owner = str(site)
    callsite = bind_source_frame_call(
        name,
        tuple(arguments),
        (),
        frame=None,
        ctx=ctx,
        owner="DecoratorApplicationSugar",
        blame=site,
        term=ctor(
            call_symbol(name),
            [value.to_term(owner=owner) for value in arguments],
            symbol_kind="coordinate",
        ),
        authenticated_target_symbol=symbol,
    )
    return UnknownCalleeCallV1(name).faces(callsite, site)


def _refuse(site, observed):
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner="DecoratorApplicationSugar",
        blame=site,
        observed=observed,
        requested="a decorator application this lift answers",
        fix="model the decorator's application, or keep the statement loud",
    )
