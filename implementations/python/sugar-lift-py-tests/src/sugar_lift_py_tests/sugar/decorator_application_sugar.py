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

A read of a ``class``'s name never runs the class statement, and a read of a
decorated ``def``'s name never applies its decorators again (#7757 item 21).
Python runs the statement once, where it stands, and the read is the value
that run bound under the statement's key (``_bound_by_statement``): the
binding the reduction the read stands in made, and, for a statement the
module body runs, read where nothing in that reduction bound the key (a
function called after import), the binding the module's one run made
(``call_site_sugar.ModuleFinalValue``, ``tree_enumerate.module_end_contexts``).
Where that run completes on no arm, no import completes and the read is the
run's halts, each carried as the run reached it
(``tree_enumerate.module_run_halts``): ``class Box: limit = 1 // 0`` makes a
function that calls ``Box()`` halt with the ``ZeroDivisionError`` the import
raises, never complete and never refuse.  Any other key neither holds is
refused by name, as every read of an unbound key is
(``evaluation_ref_sugar.refuse_unbound_evaluation``): the statement is never
reduced again in the read's place.

A method of a class that reads the class's name (``Box()`` inside
``Box.run``) is constructed while the class statement's own application is
under construction: the class sugar constructs its methods.  That read holds
no application of its own.  It reduces when the method is called, after the
statement ran, and is the same read of the same key.
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
    # The sugar of each annotation Python evaluates where the ``def``
    # statement runs (``nodes._evaluated_annotations``), after the defaults
    # and before the function is built.  Its value is bound under no key;
    # every face of it is the statement's (``def f(a: Missing)`` raises
    # NameError where the statement runs).
    annotations: tuple = field(default=(), compare=False)
    # True on the statement's own application
    # (``nodes._decorated_statement_sugar``): a decorated ``class`` statement
    # runs its body there, once, as an undecorated one does
    # (``ClassDefinitionSugar.statement_run``), and the application carries
    # what the body's callees stored ahead of what the decorators' calls
    # stored, for the statement to lay in its record.  False on every read of
    # the name, which runs no class body's stores.
    runs_statement: bool = field(default=False, compare=False)
    # The source unit whose module body runs the ``class`` statement or
    # decorated ``def`` (``SourceUnit.module_execution_site``: a statement
    # the module runs at import), else None (an undecorated ``def`` read as
    # a value, or a statement that runs only when some function is called).  A read of the name that the
    # reduction it stands in bound no key for reads what that unit's one
    # module run bound the key to (``_bound_by_statement``).  A lookup aid,
    # never testimony: the read is testified by its name, site and key.
    module_run: object = field(
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
        # A local plain ``def`` binds its name to the function value its
        # statement built, carrying the default it evaluated there: the call
        # of the name is the call of that value (``nodes._binds_function_value``).
        local = (
            "def A(z):\n"
            "    def g(a=z):\n"
            "        return a + 1\n"
            "    return g()\n\n"
        )
        return (
            _call_pair(
                name="decorator_application",
                owner_sugar="DecoratorApplicationSugar",
                truthful=prefix + "def test_a():\n    assert A(2) == 20\n",
                lying=prefix + "def test_a():\n    assert A(2) == 2\n",
            ),
            _call_pair(
                name="local_def_value",
                owner_sugar="DecoratorApplicationSugar",
                truthful=local + "def test_a():\n    assert A(2) == 3\n",
                lying=local + "def test_a():\n    assert A(2) == 2\n",
            ),
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:decorator-application",
            (self.occurrence_term(owner=owner), str_const(self.definition_name)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # The read of the name is the key's wherever the statement bound it
        # (``_bound_by_statement``).  A read constructed while its own
        # statement was under construction (a method of a class reading the
        # class's name) is the same read of the same key.  Where nothing
        # bound the key: an application that reads its own result refuses;
        # and a read of a ``class``'s or decorated ``def``'s name is the
        # module run's halts where that run completes on no arm
        # (``_module_run_halts``), else refused by name as a read of an
        # unbound key (``_unbound_read``) -- the statement runs, and its
        # decorators apply, only where it is the statement
        # (``runs_statement``), never again at a read of its name.  Only an
        # undecorated ``def`` read as a value (no key, no class) is the
        # application itself: its function, no decorator to apply.
        bound = self._bound_by_statement(ctx)
        if bound is not None:
            return ExitSet.completed(bound)
        if self.refusal is not None:
            _refuse(self.site, self.refusal)
        if not self.runs_statement and (
            self.definition_class is not None or self.evaluation is not None
        ):
            halts = self._module_run_halts()
            if halts:
                return ExitSet(halts)
            self._unbound_read(ctx)
        return self._evaluate(self.decorators, (), ctx)

    def _module_run_halts(self) -> tuple:
        """The halted arms of the module's one run, where the module body
        runs this ``class`` statement or decorated ``def`` (``module_run``)
        and that run completes on no arm (``tree_enumerate.module_run_halts``);
        else empty.

        Python runs the statement once, at import.  Where every arm of that
        run halts (the class body, a base, a decorator raises, or any
        statement of the module body does), no import completes, so no route
        reaches this read but through one of those halts: the read is them,
        each the run's own arm, read off the one reduction (#7757 item 21,
        #7766).  The statement is never reduced again for the reader, and
        the halts are never a completion.  Where some arm completes, a
        function is called after that import, and the read is the value it
        bound (``_bound_by_statement``) or, bound by none, refused by
        name."""
        if self.module_run is None or self.evaluation is None:
            return ()
        from sugar_lift_py_tests.tree_enumerate import module_run_halts

        return module_run_halts(self.module_run)

    def _unbound_read(self, ctx):
        """A read of a ``class``'s or decorated ``def``'s name whose
        statement's key nothing bound
        where the read reduces: no reduction the read stands in ran the
        statement, and the module's one run bound nothing under it (the
        statement does not run in the module body, the run is under way, or
        no completed arm ran the statement; a run that completes on no arm
        is its halts, ``_module_run_halts``).  Refused by name, the
        one refusal of a read of an unbound key
        (``evaluation_ref_sugar.refuse_unbound_evaluation``): the function
        that reads it is undecided by that name
        (``tree_enumerate.refused_function_row``).  The statement is never
        reduced, nor its decorators applied, in the read's place."""
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            evaluation_read_here,
            refuse_unbound_evaluation,
        )

        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        key = (
            self.evaluation
            if self.evaluation is None
            else evaluation_read_here(temporal, self.evaluation)
        )
        refuse_unbound_evaluation(
            name=self.definition_name,
            key=key,
            evaluation=self.evaluation,
            site=self.site,
        )

    def as_statement(self):
        """The statement's own application where a block runs it with no key
        to bind: a decorated ``class`` statement's in statement position
        (a body's ``class`` statement always binds its key,
        ``nodes._decorated_statement_sugar``, so only an application run
        with none reaches this) (``ExprStatementSugar``,
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
        where nothing bound it.

        The binding the reduction this read stands in made, first: the
        statement ran in it (a function's own ``class`` statement, the
        module body's while the module runs), or its frame entry bound the
        key (``call_site_sugar.with_module_final_globals``).  Where that
        reduction holds nothing under the key and the module body runs the
        statement (``module_run``), the binding the module's one run made:
        the read stands in a frame called after import, which no statement
        of the module body runs in, and the value is the one that run bound
        the key to on its completed arms (``ModuleFinalValue.read``,
        ``tree_enumerate.module_end_contexts``: asked for here, at the read,
        its refusal this read's).  Empty while that run is under way: the
        statement has not run where this read stands."""
        if self.evaluation is None:
            return None
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if temporal is not None:
            from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
                evaluation_read_here,
            )

            bound = temporal.value_read(
                evaluation_read_here(temporal, self.evaluation)
            )
            if bound is not None:
                return bound
        if self.module_run is None:
            return None
        from sugar_lift_py_tests.sugar.call_site_sugar import ModuleFinalValue

        return ModuleFinalValue(self.module_run, self.evaluation).read()

    def _evaluate(self, remaining: tuple, evaluated: tuple, ctx) -> ExitSet:
        # The decorator expressions, top to bottom, then the defaults, then
        # the evaluated annotations, before the definition.
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

        return self._evaluated_defaults(
            ctx,
            lambda defaults: _evaluated_in_order(
                self.annotations, ctx, lambda: define(defaults)
            ),
        )

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
            # The class statement runs here, and only here: this is the
            # statement's own application (``runs_statement``; a read of the
            # name never reaches this, ``desugar``).  Its body runs once,
            # after the decorator expressions, and each completed face is
            # the class carrying what the body's callees stored, as the
            # undecorated statement's run is
            # (``ClassDefinitionSugar.as_statement``).
            return self.definition_class.statement_run().desugar(ctx)
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
