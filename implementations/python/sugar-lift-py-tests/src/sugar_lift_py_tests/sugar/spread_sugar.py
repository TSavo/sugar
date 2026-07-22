"""Reference-shaped construction for Python starred/spread expressions."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


def _collect(sugars: tuple, ctx, done: tuple, finish):
    if not sugars:
        return finish(done)
    head, *tail = sugars
    return head.desugar(ctx).and_then(
        lambda value: _collect(tuple(tail), ctx, (*done, value), finish)
    )


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
