"""Reference-shaped construction for Python starred/spread expressions."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    Sugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


def _collect(sugars: tuple, ctx, done: tuple, finish, *, earlier: tuple = ()):
    """Sequence spread operands by COMPOSING factors, never distributing them.

    #6309. The previous body chained ``and_then`` once per operand, and
    ``ExitSet.and_then`` appends every exit of the tail under every completed
    exit of the prefix. With k operands of m arms each that is m ** k
    materialized arms — and it is the arm POPULATION, not the per-merge cost,
    that walled ``pandas/core/generic.py``: an observed 1,317-wide arm set with
    a heavy tail (63% of normalize calls at one arm, three above 256), at guard
    nesting depth only 4.

    Each operand keeps its complete ExitSet as a FACTOR:

    - its completed face is factored to one arm carrying a guarded value
      (``ExitSet.factor_completed``), so k operands contribute k guarded values
      to ONE arm instead of one arm per tuple in the product;
    - its halted arms are lifted to the exit level under the prefix's completed
      guard, where one arm per operand per effect is already linear;
    - ``finish`` runs ONCE, on the factored value tuple, under the conjunction of
      the operands' completed guards.

    Both faces are retained in full. Nothing is pruned, no arm is capped, and
    success is never assumed: an operand whose every path halts ends the fold
    with only halted arms, which is exactly what the product said.

    ``finish`` is also invoked once rather than once per completed tuple. The old
    chain re-``desugar``ed each tail operand once per prefix arm; the fold walks
    the operands in the same source order, once each.

    Each operand is evaluated after the ones before it (``evaluated_after``):
    in the context their writes left (``written_by`` of ``earlier`` -- what
    the expression evaluated before its first operand, a spread call's
    callee -- and of every value collected), so ``[*(a := xs), *a]`` reads
    ``a``, and its halts carry those writes, the callee stores first in
    their records' entries.

    Every operand, and ``finish``, runs beneath the PREFIX -- the one completed
    arm the operands so far left through -- by ``ExitSet.and_then``: what it
    produces takes the prefix's guard, faces and ``owed``. Its halts leave the
    fold there; its completed face is the next prefix. Only the one prefix arm
    is sequenced each step, never the halts collected so far, so the work stays
    linear in the operand count.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed

    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor.named_expression_value import (
        evaluated_after,
        written_by,
    )

    # Truth before the first operand; afterwards the operands' completed path.
    prefix = ExitSet.completed(None)
    values = list(done)
    # Each operand's halted face, in operand order: siblings of whatever the
    # fold finally leaves through, joined once (``ExitSet.union``).
    halted: list = []

    def leave(following, *, prefix, halted):
        """The fold's exits: every collected halt, then ``following`` beneath
        the prefix, joined through the one join."""
        return ExitSet(()).union(*halted, prefix.and_then(lambda _last: following))

    for index, sugar in enumerate(sugars):
        # A deferred native-operation operand is not an ExitSet. IfExp and
        # BoolOp keep that carrier until discharge. The remaining operands and finish
        # wait via and_then so the list does not invent a completed message.
        # The operands before it already ran: once the carrier discharges, its
        # exits leave beneath their prefix beside every halt they collected. A
        # halt is never dropped.
        before = (*earlier, *values)
        operand_ctx = ctx
        for value in before:
            operand_ctx = written_by(value, operand_ctx)
        desugared = evaluated_after(before, sugar, operand_ctx)
        if isinstance(desugared, NativeOperationExitCarrierV1):
            already = tuple(values)
            remaining = sugars[index + 1 :]
            collected = tuple(halted)
            return desugared.and_then(
                lambda value: _collect(
                    remaining, ctx, already + (value,), finish, earlier=earlier
                )
            ).after_discharge(
                lambda projected, *, prefix=prefix: leave(
                    projected, prefix=prefix, halted=collected
                )
            )
        factors = desugared.factor_completed()
        stepped = prefix.and_then(lambda _last, *, factors=factors: factors)
        halted.append(ExitSet(stepped.halts()))
        completed = tuple(
            exit_ for exit_ in stepped.exits if isinstance(exit_, Completed)
        )
        if not completed:
            # Every path through this operand halts: there is no completed
            # continuation to hand to ``finish``, and the halted face is the
            # whole meaning.
            return ExitSet(()).union(*halted)
        # ``factor_completed`` left one completed face.
        prefix = ExitSet(completed)
        values.append(completed[0].value)

    finished = finish(tuple(values))
    if isinstance(finished, NativeOperationExitCarrierV1):
        # ``finish`` itself waits on a caller's actual (a call whose callee
        # or receiver is a formal): exactly as a deferred operand, its exits
        # leave beneath the prefix beside every collected halt once the
        # carrier discharges.
        collected = tuple(halted)
        return finished.after_discharge(
            lambda projected, *, prefix=prefix: leave(
                projected, prefix=prefix, halted=collected
            )
        )
    return leave(finished, prefix=prefix, halted=halted)


@dataclass(frozen=True)
class SpreadCollectionSugar(ConstructedTermSugar):
    """A display containing spread operands, as encoded by the reference lifter.

    ``elements`` is ``(wrapper-or-None, child-sugar)`` in source order.

    ConstructedTermSugar: a list/tuple/set display with ``*`` IS nested
    construction testimony — the same meaning ListSugar/TupleSugar/SetSugar
    admit without stars. Parent slots that require ConstructedTermSugar are
    truthful; this class was missing the base and ``to_term``. Promoting is
    not a convenience widen of the slot.
    """

    kind: str
    elements: tuple
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for _wrapper, sugar in self.elements:
            require_constructed_term_sugar(
                sugar, owner="SpreadCollectionSugar.elements"
            )

    @classmethod
    def witnesses(cls):
        # ``[*z]`` spreads the tuple `z` into a list display of its members.
        return _assertion_pair(
            name="spread_collection_len",
            owner_sugar="SpreadCollectionSugar",
            statements="z = (1, 2)",
            truthful="len([*z]) == 2",
            lying="len([*z]) == 3",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        element_terms = []
        for wrapper, sugar in self.elements:
            term = require_constructed_term_sugar(
                sugar, owner="SpreadCollectionSugar.elements"
            ).to_term(owner=owner)
            if wrapper is not None:
                term = ctor(wrapper, [term])
            element_terms.append(term)
        return ctor(
            f"python:{self.kind}-construction",
            (
                self.occurrence_term(owner=owner),
                ctor(f"python:{self.kind}-elements", tuple(element_terms)),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        sugars = tuple(sugar for _, sugar in self.elements)

        def finish(values):
            from sugar_lift_py_tests.floor import SymbolicValue
            from sugar_lift_py_tests.ir import ctor

            owner = str(self.site)
            terms = []
            for (wrapper, _), value in zip(self.elements, values):
                term = value.to_term(owner=owner)
                terms.append(ctor(wrapper, [term]) if wrapper is not None else term)
            return ExitSet.completed(
                SymbolicValue(ctor(f"python:{self.kind}", terms))
            )

        return _collect(sugars, ctx, (), finish)


@dataclass(frozen=True)
class SpreadDictSugar(ConstructedTermSugar):
    """A dict display whose entries include reference ``None``-key spreads.

    ConstructedTermSugar for the same reason as SpreadCollectionSugar: ``{**d}``
    is a constructed dict term, not an over-wide slot.
    """

    entries: tuple  # (key-sugar-or-None, value-sugar), source order
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for key, value in self.entries:
            if key is not None:
                require_constructed_term_sugar(key, owner="SpreadDictSugar.entries.key")
            require_constructed_term_sugar(value, owner="SpreadDictSugar.entries.value")

    @classmethod
    def witnesses(cls):
        # ``{**z}`` spreads the two entries of the dict `z` into a display:
        # one spread entry that holds two, so a count of display entries lies.
        return _assertion_pair(
            name="spread_dict_len",
            owner_sugar="SpreadDictSugar",
            statements="z = {1: 2, 3: 4}",
            truthful="len({**z}) == 2",
            lying="len({**z}) == 1",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        entry_terms = []
        for key, value in self.entries:
            value_term = require_constructed_term_sugar(
                value, owner="SpreadDictSugar.entries.value"
            ).to_term(owner=owner)
            if key is None:
                key_term = ctor("None", [])
            else:
                key_term = require_constructed_term_sugar(
                    key, owner="SpreadDictSugar.entries.key"
                ).to_term(owner=owner)
            entry_terms.append(ctor("python:dict-entry", (key_term, value_term)))
        return ctor(
            "python:dict-construction",
            (
                self.occurrence_term(owner=owner),
                ctor("python:dict-entries", tuple(entry_terms)),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        flattened = tuple(
            sugar
            for key, value in self.entries
            for sugar in ((value,) if key is None else (key, value))
        )

        def finish(values):
            from sugar_lift_py_tests.floor import SymbolicValue
            from sugar_lift_py_tests.ir import ctor

            owner = str(self.site)
            value_iter = iter(values)
            terms = []
            for key, _ in self.entries:
                if key is None:
                    key_term = ctor("None", [])
                    value_term = next(value_iter).to_term(owner=owner)
                else:
                    key_term = next(value_iter).to_term(owner=owner)
                    value_term = next(value_iter).to_term(owner=owner)
                terms.append(ctor("python:dict_entry", [key_term, value_term]))
            return ExitSet.completed(SymbolicValue(ctor("python:dict", terms)))

        return _collect(flattened, ctx, (), finish)


@dataclass(frozen=True)
class SpreadCallSugar(ConstructedTermSugar):
    """A call containing ``*``/``**``, using the reference call vocabulary.

    A callee whose value is a function, a source class or a bound method
    (a plain ``def``'s value among them: ``Call._function_value_call``,
    ``Call._named_function_value``) is applied through that value's one
    application (``_finish``), as ``f(...)`` is.  Any other spread call --
    a callee by name that is an import, a builtin, a generator function or
    ``async def``, a recursion seat -- is the one unanswered call
    (``UnknownCalleeCallV1``).  No spread call seats a definition's frame by
    its name (#7757).
    """

    callee_name: str | None
    callee: Sugar | None
    arguments: tuple  # (role, optional-name, sugar), source order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # ``f(*z)`` spreads the tuple `z` into the positional actuals of the
        # local lambda `f`, applied through its one application: a = 1, b = 2.
        return _assertion_pair(
            name="spread_call",
            owner_sugar="SpreadCallSugar",
            statements="z = (1, 2)\nf = lambda a, b: a - b",
            truthful="f(*z) == -1",
            lying="f(*z) == 1",
        )

    def to_term(self, *, owner: str):
        """Project the same call coordinate used by completed spread reduction."""
        from sugar_lift_py_tests.ir import ctor, str_const

        if self.callee_name is not None:
            callee_term = str_const(self.callee_name)
        else:
            callee = require_constructed_term_sugar(
                self.callee, owner="SpreadCallSugar.callee"
            )
            callee_term = callee.to_term(owner=owner)
        arg_terms = []
        for role, name, sugar in self.arguments:
            term = require_constructed_term_sugar(
                sugar, owner="SpreadCallSugar.arguments"
            ).to_term(owner=owner)
            if role == "star":
                term = ctor("python:starred_arg", [term])
            elif role == "double-star":
                term = ctor("python:double_starred_kwarg", [term])
            elif role == "keyword":
                term = ctor("python:kwarg", [str_const(name), term])
            arg_terms.append(term)
        return ctor("python:call", [callee_term, *arg_terms])

    def desugar(self, ctx: object = None) -> ExitSet:
        def after_callee(callee_value):
            # The callee is evaluated before the arguments: they read its
            # writes and their halts carry them (``_collect``'s ``earlier``).
            sugars = tuple(sugar for _, _, sugar in self.arguments)
            return _collect(
                sugars,
                ctx,
                (),
                lambda values: self._finish(callee_value, values, ctx),
                earlier=() if callee_value is None else (callee_value,),
            )

        if self.callee is None:
            return after_callee(None)
        return self.callee.desugar(ctx).and_then(after_callee)

    def _finish(self, callee_value, values, ctx=None) -> ExitSet:
        from sugar_lift_py_tests.floor import (
            BoundMethodValue,
            ClassDefinitionValue,
            LambdaCallable,
        )

        # A callee value the computed call applies (``ComputedCallSugar``) is
        # applied here the same way: a bound method (a source method read off
        # its receiver, or one selected through zero-arg ``super``), a source
        # class, or a function value -- the value a decorated definition's
        # name is bound to among them (``DecoratorApplicationSugar``), never
        # the plain definition's frame.  Its own application binds through
        # the one binder and applies the body (#7756, #7757).
        if isinstance(
            callee_value, (BoundMethodValue, ClassDefinitionValue, LambdaCallable)
        ):
            from sugar_lift_py_tests.callable_application import CallableApplication
            from sugar_lift_py_tests.floor import TupleValue

            roster: list = []
            for (role, _name, _), value in zip(self.arguments, values):
                if role == "positional":
                    roster.append(value)
                elif role == "star":
                    # ``*t`` over a decided tuple is its elements, in order, at
                    # this position of the positional roster (Python's
                    # call-time iterable unpacking); any other operand has no
                    # exact roster.
                    if type(value) is not TupleValue:
                        from sugar_source_tree.panic import SugarNotWritten

                        raise SugarNotWritten(
                            owner="SpreadCallSugar._finish",
                            blame=self.site,
                            observed=(
                                "starred positional actual that is not a decided "
                                f"tuple, to a {type(callee_value).__name__}"
                            ),
                            requested="an exact positional roster",
                            fix=(
                                "project the starred operand exactly or keep "
                                "the call loud"
                            ),
                        )
                    roster.extend(value.elements)
            positional = tuple(roster)
            keywords = tuple(
                (("**" if role == "double-star" else name), value)
                for (role, name, _), value in zip(self.arguments, values)
                if role in {"keyword", "double-star"}
            )
            return callee_value.callable_application_with(
                CallableApplication(
                    positional + tuple(value for _name, value in keywords),
                    tuple(name for name, _value in keywords),
                    self.site,
                    owner="SpreadCallSugar._finish",
                ),
                ctx,
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = str(self.site)
        callee_term = (
            str_const(self.callee_name)
            if self.callee_name is not None
            else callee_value.to_term(owner=owner)
        )
        arg_terms = []
        for (role, name, _), value in zip(self.arguments, values):
            term = value.to_term(owner=owner)
            if role == "star":
                term = ctor("python:starred_arg", [term])
            elif role == "double-star":
                term = ctor("python:double_starred_kwarg", [term])
            elif role == "keyword":
                term = ctor("python:kwarg", [str_const(name), term])
            arg_terms.append(term)
        term = ctor("python:call", [callee_term, *arg_terms])

        # No value this applies answered the callee: no body, contract or
        # floor answered for it at this site, so it is the one unanswered
        # call, two-faced and owed (#7585, #7757), never a completion.
        from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

        callsite = CallSiteValue(
            target_name=self.callee_name or "python:call",
            arg_values=tuple(values),
            parameters=(),
            term=term,
            body=None,
            site=self.site,
        )
        return UnknownCalleeCallV1(self.callee_name or "python:call").faces(
            callsite, self.site
        )
