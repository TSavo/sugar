"""Reference-shaped construction for Python starred/spread expressions."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
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
    """
    from sugar_lift_py_tests.outcome.exit_set import (
        ExitSet,
        Halted,
        _and_guards,
        _is_true,
        outcome_to_exitset,
        true_guard,
    )

    prefix_guard = true_guard()
    values = list(done)
    halted: list = []

    for sugar in sugars:
        factors = outcome_to_exitset(sugar.desugar(ctx)).factor_completed()
        completed = None
        for exit_ in factors.exits:
            if isinstance(exit_, Halted):
                halted.append(
                    Halted(
                        _and_guards(prefix_guard, exit_.guard),
                        exit_.effect,
                        exit_.state,
                    )
                )
            else:
                completed = exit_
        if completed is None:
            # Every path through this operand halts: there is no completed
            # continuation to hand to ``finish``, and the halted face is the
            # whole meaning.
            return ExitSet(tuple(halted)).normalize().collapse()
        prefix_guard = _and_guards(prefix_guard, completed.guard)
        values.append(completed.value)

    tail = outcome_to_exitset(finish(tuple(values)))
    if not _is_true(prefix_guard):
        tail = tail.guarded(prefix_guard)
    # ``collapse`` restores the linear ``Outcome`` for the unconditional case, so
    # a spread with no guarded operand desugars to exactly what it did before.
    return ExitSet((*halted, *tail.exits)).normalize().collapse()


@dataclass(frozen=True)
class SpreadCollectionSugar(Sugar):
    """A display containing spread operands, as encoded by the reference lifter.

    ``elements`` is ``(wrapper-or-None, child-sugar)`` in source order.
    """

    kind: str
    elements: tuple
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="spread_collection_len",
            owner_sugar="SpreadCollectionSugar",
            body="len([*z])",
            truthful="len(z)",
            lying="len(z) + 1",
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
            return Complete(SymbolicValue(ctor(f"python:{self.kind}", terms)))

        return _collect(sugars, ctx, (), finish)


@dataclass(frozen=True)
class SpreadDictSugar(Sugar):
    """A dict display whose entries include reference ``None``-key spreads."""

    entries: tuple  # (key-sugar-or-None, value-sugar), source order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="spread_dict_len",
            owner_sugar="SpreadDictSugar",
            body="len({**z})",
            truthful="len(z)",
            lying="len(z) + 1",
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
            return Complete(SymbolicValue(ctor("python:dict", terms)))

        return _collect(flattened, ctx, (), finish)


@dataclass(frozen=True)
class SpreadCallSugar(Sugar):
    """A call containing ``*``/``**``, using the reference call vocabulary."""

    callee_name: str | None
    callee: Sugar | None
    arguments: tuple  # (role, optional-name, sugar), source order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="spread_call",
            owner_sugar="SpreadCallSugar",
            body="tuple((*z,))",
            truthful="tuple(z)",
            lying="tuple((*z, 0))",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        def after_callee(callee_value):
            sugars = tuple(sugar for _, _, sugar in self.arguments)
            return _collect(
                sugars,
                ctx,
                (),
                lambda values: self._finish(callee_value, values),
            )

        if self.callee is None:
            return after_callee(None)
        return self.callee.desugar(ctx).and_then(after_callee)

    def _finish(self, callee_value, values) -> Outcome:
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
        return Complete(
            CallSiteValue(
                target_name=self.callee_name or "python:call",
                arg_values=tuple(values),
                parameters=(),
                term=term,
                body=None,
                site=self.site,
            )
        )
