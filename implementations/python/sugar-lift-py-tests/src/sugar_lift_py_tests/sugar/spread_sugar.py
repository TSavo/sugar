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

    for sugar in sugars:
        before = (*earlier, *values)
        operand_ctx = ctx
        for value in before:
            operand_ctx = written_by(value, operand_ctx)
        desugared = evaluated_after(before, sugar, operand_ctx)
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
    return leave(finished, prefix=prefix, halted=halted)


def _spread_members(value):
    """The members ``*value`` yields, in order, when this frame holds them:
    a ``list`` or ``tuple`` whose contents are current.  None otherwise -- an
    iterable whose iteration this frame does not decide (a set's order, a
    generator, a value that arrived with contents not current)."""
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.object_identity import holds_stale
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if type(value) not in (ListValue, TupleValue) or holds_stale(value):
        return None
    return tuple(value.elements)


def _display_members(wrappers: tuple, values: tuple):
    """The members of ``[a, *b]`` in order, each ``*`` operand contributing
    the members it yields; None when a ``*`` operand's members are not held
    here (``_spread_members``)."""
    members: list = []
    for wrapper, value in zip(wrappers, values, strict=True):
        if wrapper is None:
            members.append(value)
            continue
        spread = _spread_members(value)
        if spread is None:
            return None
        members.extend(spread)
    return tuple(members)


def _built_display(kind: str, members, site):
    """``[a, *b]`` / ``(a, *b)`` / ``{a, *b}``: the display its non-spread
    sibling builds (``collection_sugar``) over ``members``
    (``_display_members``)."""
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.object_identity import made_at
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.collection_sugar import _built_set

    # The display makes a new object here (``made_at``): a spread is
    # evaluated at runtime, never a folded constant.
    if kind == "list":
        return ExitSet.completed(ListValue(members, allocation=made_at(site)))
    if kind == "tuple":
        return ExitSet.completed(TupleValue(members, allocation=made_at(site)))
    # ``kind`` is ``set``: the three displays a ``*`` operand appears in.
    return _built_set(members, site)


def _spread_dict_pairs(spread_flags: tuple, values: tuple):
    """The pairs of ``{k: v, **d}`` in order, each ``**`` operand
    contributing its entries; None when a ``**`` operand is not a dict whose
    contents are current."""
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.object_identity import holds_stale

    pairs: list = []
    value_iter = iter(values)
    for spread in spread_flags:
        if spread:
            mapping = next(value_iter)
            if type(mapping) is not DictValue or holds_stale(mapping):
                return None
            pairs.extend(mapping.entries)
            continue
        key = next(value_iter)
        pairs.append((key, next(value_iter)))
    return tuple(pairs)


def _call_keywords(arguments: tuple, values: tuple):
    """The keyword actuals of a spread call, ``(name, value)`` in source
    order: a ``name=v`` as written, each ``**d`` operand its entries.

    ``**d`` is read by the one ``**`` reader (``_spread_dict_pairs``): a
    dict whose contents are current (``object_identity.contents_current``).
    None when an operand is not one, or holds a key that is not a string
    (Python raises ``TypeError`` there): the call has no exact keyword
    roster, and is not bound from it."""
    from sugar_lift_py_tests.floor import StringValue

    keywords: list = []
    for (role, name, _), value in zip(arguments, values):
        if role == "keyword":
            keywords.append((name, value))
        elif role == "double-star":
            pairs = _spread_dict_pairs((True,), (value,))
            if pairs is None:
                return None
            for key, item in pairs:
                if type(key) is not StringValue:
                    return None
                keywords.append((key.value, item))
    return tuple(keywords)


def _call_positional(arguments: tuple, values: tuple):
    """The positional actuals of a spread call, in source order: a plain
    actual as written, each ``*t`` operand the members it yields.

    ``*t`` is read by the one ``*`` reader (``_spread_members``), the reader
    the ``[*t]`` display uses: a ``list`` or ``tuple`` whose contents are
    current.  None when an operand is not one -- a set, a generator, a
    call's result, a container that arrived or a call may have changed:
    the call has no exact positional roster, and is not bound from it."""
    positional: list = []
    for (role, _name, _), value in zip(arguments, values):
        if role == "positional":
            positional.append(value)
        elif role == "star":
            members = _spread_members(value)
            if members is None:
                return None
            positional.extend(members)
    return tuple(positional)


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
            from sugar_lift_py_tests.floor.named_expression_value import (
                consume_operands,
                peel_walrus_binds,
            )
            from sugar_lift_py_tests.ir import ctor

            wrappers = tuple(wrapper for wrapper, _ in self.elements)
            presented = tuple(peel_walrus_binds(value)[1] for value in values)
            if _display_members(wrappers, presented) is not None:
                # The one operand door: a walrus operand's bind still reaches
                # the enclosing statement.
                return consume_operands(
                    lambda *held: _built_display(
                        self.kind, _display_members(wrappers, held), self.site
                    ),
                    *values,
                )
            from sugar_lift_py_tests.floor.object_identity import identity_term

            owner = str(self.site)
            terms = []
            # Each operand as the display finds it (``identity_term``): a
            # spread container whose contents are not current by its
            # identity, never by contents prove would read as the display's.
            for position, ((wrapper, _), value) in enumerate(
                zip(self.elements, values)
            ):
                term = identity_term(
                    value, self.site, f"element{position}", owner=owner
                )
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
            from sugar_lift_py_tests.floor.named_expression_value import (
                consume_operands,
                peel_walrus_binds,
            )
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.sugar.collection_sugar import _built_dict

            spread_flags = tuple(key is None for key, _ in self.entries)
            presented = tuple(peel_walrus_binds(value)[1] for value in values)
            if _spread_dict_pairs(spread_flags, presented) is not None:
                # The one operand door (``consume_operands``).
                return consume_operands(
                    lambda *held: _built_dict(
                        _spread_dict_pairs(spread_flags, held), self.site
                    ),
                    *values,
                )
            from sugar_lift_py_tests.floor.object_identity import identity_term

            owner = str(self.site)
            value_iter = iter(values)
            terms = []
            # Each operand as the display finds it (``identity_term``): a
            # ``**d`` whose contents are not current by its identity, never
            # by entries prove would read as the display's (#7757 H7).
            for position, (key, _) in enumerate(self.entries):
                if key is None:
                    key_term = ctor("None", [])
                    value_term = identity_term(
                        next(value_iter), self.site, f"spread{position}", owner=owner
                    )
                else:
                    key_term = identity_term(
                        next(value_iter), self.site, f"key{position}", owner=owner
                    )
                    value_term = identity_term(
                        next(value_iter), self.site, f"value{position}", owner=owner
                    )
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
        #
        # Its keyword actuals are read by the one ``**`` reader
        # (``_call_keywords`` over ``_spread_dict_pairs``, the reader the
        # ``{**d}`` display uses): a ``**d`` operand whose contents are not
        # current has no exact keyword roster, and the call is the one
        # unanswered call below, never bound from entries code this frame
        # does not see may have changed (#7757 H2).
        #
        # Its positional actuals are read by the one ``*`` reader
        # (``_call_positional`` over ``_spread_members``, the reader the
        # ``[*t]`` display uses): a current list or tuple yields its members
        # in order; any other ``*`` operand has no exact positional roster,
        # and the call is the same unanswered call (#7757 S3).
        keywords = _call_keywords(self.arguments, values)
        positional = _call_positional(self.arguments, values)
        if (
            keywords is not None
            and positional is not None
            and isinstance(
                callee_value, (BoundMethodValue, ClassDefinitionValue, LambdaCallable)
            )
        ):
            from sugar_lift_py_tests.callable_application import CallableApplication

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
        from sugar_lift_py_tests.floor.object_identity import identity_term
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = str(self.site)
        callee_term = (
            str_const(self.callee_name)
            if self.callee_name is not None
            else identity_term(callee_value, self.site, "callee", owner=owner)
        )
        arg_terms = []
        # Each operand as the call finds it (``identity_term``): a ``*xs`` or
        # ``**d`` whose contents are not current by its identity (#7757 H7).
        for position, ((role, name, _), value) in enumerate(
            zip(self.arguments, values)
        ):
            term = identity_term(value, self.site, f"argument{position}", owner=owner)
            if role == "star":
                term = ctor("python:starred_arg", [term])
            elif role == "double-star":
                term = ctor("python:double_starred_kwarg", [term])
            elif role == "keyword":
                term = ctor("python:kwarg", [str_const(name), term])
            arg_terms.append(term)
        term = ctor("python:call", [callee_term, *arg_terms])

        # No value this applies answered the callee, or a ``*`` or ``**``
        # operand gave no exact roster (``_call_positional``,
        # ``_call_keywords``): no body, contract or
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
