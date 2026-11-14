"""Reference-shaped construction for Python starred/spread expressions."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet, Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    Sugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


def _collect(sugars: tuple, ctx, done: tuple, finish):
    """Sequence spread operands by COMPOSING factors, never distributing them.

    #6309. The previous body chained ``and_then`` once per operand, and
    ``ExitSet.sequence`` appends every exit of the tail under every completed
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

    Every operand, and ``finish``, runs beneath the PREFIX -- the one completed
    arm the operands so far left through -- by ``ExitSet.sequence``: what it
    produces takes the prefix's guard, faces and ``owed``. Its halts leave the
    fold there; its completed face is the next prefix. Only the one prefix arm
    is sequenced each step, never the halts collected so far, so the work stays
    linear in the operand count.
    """
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        outcome_to_exitset,
    )

    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    # Truth before the first operand; afterwards the operands' completed path.
    prefix = ExitSet.completed(None)
    values = list(done)
    halted: list = []

    def leave(following, *, prefix, halted):
        """The fold's exits: every collected halt, then ``following`` beneath
        the prefix."""
        beneath = prefix.sequence(lambda _last: following)
        return ExitSet((*halted, *beneath.exits)).normalize()

    for index, sugar in enumerate(sugars):
        # A deferred native-operation operand is not an ExitSet. Forcing it
        # through outcome_to_exitset panics; IfExp and BoolOp already keep
        # that carrier until discharge. The remaining operands and finish
        # wait via and_then so the list does not invent a completed message.
        # The operands before it already ran: once the carrier discharges, its
        # exits leave beneath their prefix beside every halt they collected. A
        # halt is never dropped.
        desugared = sugar.desugar(ctx)
        if isinstance(desugared, NativeOperationExitCarrierV1):
            already = tuple(values)
            remaining = sugars[index + 1 :]
            collected = tuple(halted)
            return desugared.and_then(
                lambda value: _collect(remaining, ctx, already + (value,), finish)
            ).after_discharge(
                lambda projected, *, prefix=prefix: leave(
                    projected, prefix=prefix, halted=collected
                )
            )
        factors = outcome_to_exitset(desugared).factor_completed()
        stepped = prefix.sequence(lambda _last, *, factors=factors: factors)
        halted.extend(stepped.halts())
        completed = tuple(
            exit_ for exit_ in stepped.exits if isinstance(exit_, Completed)
        )
        if not completed:
            # Every path through this operand halts: there is no completed
            # continuation to hand to ``finish``, and the halted face is the
            # whole meaning.
            return ExitSet(tuple(halted)).normalize()
        # ``factor_completed`` left one completed face.
        prefix = ExitSet(completed)
        values.append(completed[0].value)

    return leave(
        outcome_to_exitset(finish(tuple(values))), prefix=prefix, halted=halted
    )


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
        return _call_return_pair(
            name="spread_collection_len",
            owner_sugar="SpreadCollectionSugar",
            body="len([*z])",
            truthful="len(z)",
            lying="len(z) + 1",
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

    def desugar(self, ctx: object = None) -> Outcome:
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
        return _call_return_pair(
            name="spread_dict_len",
            owner_sugar="SpreadDictSugar",
            body="len({**z})",
            truthful="len(z)",
            lying="len(z) + 1",
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

    def desugar(self, ctx: object = None) -> Outcome:
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

    When an authenticated source-visible callee frame is enrolled (class
    constructor / function body), typed ``**`` expansions project through that
    frame so the CallSiteValue carries the factory-built body. Opaque spreads
    without a frame keep the reference bodyless coordinate.
    """

    callee_name: str | None
    callee: Sugar | None
    arguments: tuple  # (role, optional-name, sugar), source order
    site: object = dataclass_field(compare=False)
    source_call_frame: object | None = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="spread_call",
            owner_sugar="SpreadCallSugar",
            body="tuple((*z,))",
            truthful="tuple(z)",
            lying="tuple((*z, 0))",
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

    def desugar(self, ctx: object = None) -> Outcome:
        def after_callee(callee_value):
            sugars = tuple(sugar for _, _, sugar in self.arguments)
            return _collect(
                sugars,
                ctx,
                (),
                lambda values: self._finish(callee_value, values, ctx),
            )

        if self.callee is None:
            return after_callee(None)
        return self.callee.desugar(ctx).and_then(after_callee)

    def _finish(self, callee_value, values, ctx=None) -> Outcome:
        from sugar_lift_py_tests.floor import BoundMethodValue

        # A bound method (a source method read off its receiver, or one
        # selected through zero-arg ``super``) is called through the
        # receiver's own method dispatch, as ``MethodCallSugar`` does.
        if isinstance(callee_value, BoundMethodValue):
            if any(role == "star" for role, _, _ in self.arguments):
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    owner="SpreadCallSugar._finish",
                    blame=self.site,
                    observed="starred positional actual to a bound method",
                    requested="an exact positional roster",
                    fix="project the starred operand exactly or keep the call loud",
                )
            positional = tuple(
                value
                for (role, _name, _), value in zip(self.arguments, values)
                if role == "positional"
            )
            keywords = tuple(
                (("**" if role == "double-star" else name), value)
                for (role, name, _), value in zip(self.arguments, values)
                if role in {"keyword", "double-star"}
            )
            return callee_value.receiver.call_method_value(
                callee_value.name,
                positional,
                owner="SpreadCallSugar._finish",
                blame=self.site,
                ctx=ctx,
                keywords=keywords,
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

        framed = self._body_bearing_callsite(values, term, ctx)
        if framed is not None:
            return self._produce_framed(framed, ctx)

        callsite = CallSiteValue(
            target_name=self.callee_name or "python:call",
            arg_values=tuple(values),
            parameters=(),
            term=term,
            body=None,
            site=self.site,
        )
        if self.site is None:
            return ExitSet.completed(callsite)
        return _unprojected_spread_call_faces(
            callsite, self.callee_name or "python:call", self.site
        )

    def _produce_framed(self, framed, ctx) -> Outcome:
        """A projected source body is reduced once, at the Call, as CallSiteSugar does.

        Its halts are the call's own faces and its completion is retained on
        the CallSiteValue, so a consumer never replays the body.
        """
        from sugar_lift_py_tests.context.reduce_context import ReduceContext
        from sugar_source_tree.panic import SugarNotWritten

        if ctx is not None and not isinstance(ctx, ReduceContext):
            raise SugarNotWritten(
                owner="SpreadCallSugar._finish",
                blame=self.site,
                observed="source-visible call under a temporal-only reduction context",
                requested="a ReduceContext that can record the call",
                fix=(
                    "keep the call loud until allocate carries a reduction "
                    "context; do not invent the callee body"
                ),
            )
        return framed.producer_outcome(
            ctx, carrier_actuals=framed.bound_native_actuals_by_coordinate
        )

    def _body_bearing_callsite(self, values, term, ctx) -> object | None:
        """Project ``*``/``**`` actuals onto an enrolled source frame when lawful.

        A star operand projects only when it is a decided ``TupleValue``. A
        double-star must be a constructed DictValue so bind_actuals can merge
        keys onto formals — the same law FunctionCallable uses for ``**``.
        """
        frame = self.source_call_frame
        if frame is None:
            return None
        from sugar_lift_py_tests.floor import CallSiteValue, TupleValue
        from sugar_lift_py_tests.source_call_frame import (
            SourceCallBindingGap,
            SourceVisibleCallFrameV1,
        )

        if not isinstance(frame, SourceVisibleCallFrameV1):
            return None
        positional: list = []
        keywords: list = []
        for (role, name, _), value in zip(self.arguments, values):
            if role == "positional":
                positional.append(value)
            elif role == "star":
                # ``*t`` over a decided tuple is its elements, in order, at
                # this position of the positional roster (Python's call-time
                # iterable unpacking).  Any other operand keeps the call
                # bodyless rather than inventing an arity.
                if type(value) is not TupleValue:
                    return None
                positional.extend(value.elements)
            elif role == "keyword":
                keywords.append((name, value))
            elif role == "double-star":
                keywords.append(("**", value))
            else:
                return None
        try:
            bound = frame.bind_actuals(tuple(positional), tuple(keywords), ctx)
        except SourceCallBindingGap:
            return None
        source_body = frame.body
        owner = getattr(frame, "owner", None)
        if owner is not None and hasattr(owner, "source_visible_constructor_frame"):
            source_body = owner.source_visible_constructor_frame().body
        return CallSiteValue(
            target_name=self.callee_name or "python:call",
            arg_values=bound.actuals,
            parameters=frame.parameters,
            term=term,
            body=source_body,
            site=self.site,
            source_call_frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(item.cid for item in frame.formal_coordinates),
            bound_source_actuals=bound,
        )


def _unprojected_spread_call_faces(callsite, callee: str, site):
    """``g(*a, **k)`` with no source frame projected here: two faces.

    No body, contract or floor answered for the callee at this site, so the
    call may raise anything.  It completes only under
    ``python:spread_call.completes(python:spread_call(<callee>, <occurrence>))``
    with the value ``python:call_result(<call term>, <occurrence>)`` -- each
    evaluation its own unknown -- and halts with an ``UndeterminedRaiseEffect``
    (owner ``UnprojectedSpreadCall:<callee>``) under the complement: the #7585
    law for an unprojected call.  Completing it totally would claim the callee
    never raises.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import ExitSet
    from sugar_lift_py_tests.source_call_resolution import _occurrence_result

    key = occurrence_key(site)
    completes = atomic(
        "python:spread_call.completes",
        [ctor("python:spread_call", (str_const(callee), str_const(key)))],
    )
    return ExitSet.two_faced(
        _occurrence_result(callsite, site),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=f"UnprojectedSpreadCall:{callee}",
        ),
        guard=completes,
    )
