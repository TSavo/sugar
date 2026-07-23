"""Symbolic comprehensions as nested guarded iterator recurrences."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ComprehensionGeneratorSugar:
    target: str
    iterable: Sugar
    filters: tuple[Sugar, ...]


@dataclass(frozen=True)
class ComprehensionSugar(Sugar):
    kind: str
    generators: tuple[ComprehensionGeneratorSugar, ...]
    element: Sugar
    key: Sugar | None = None
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        prefix = "def A(xs):\n    return [x for x in xs]\n\n"
        return _call_pair(
            name="symbolic_list_comprehension",
            owner_sugar="ComprehensionSugar",
            truthful=prefix + "def test_a():\n    assert A([1]) == [1]\n",
            lying=prefix + "def test_a():\n    assert A([1]) == [2]\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if not self.generators:
            raise ValueError("comprehension recurrence requires a generator")
        return self._desugar_generators(0, (), ctx)

    def _desugar_generators(self, index, resolved, ctx):
        if index == len(self.generators):
            if self.key is not None:
                return self.key.desugar(ctx).and_then(
                    lambda key: self.element.desugar(ctx).and_then(
                        lambda element: self._complete(resolved, element, key)
                    )
                )
            return self.element.desugar(ctx).and_then(
                lambda element: self._complete(resolved, element)
            )
        generator = self.generators[index]
        return generator.iterable.desugar(ctx).and_then(
            lambda iterable: self._desugar_filters(
                generator, 0, (), iterable, index, resolved, ctx
            )
        )

    def _desugar_filters(
        self, generator, filter_index, filters, iterable, index, resolved, ctx
    ):
        if filter_index == len(generator.filters):
            return self._desugar_generators(
                index + 1,
                (*resolved, (generator.target, iterable, filters)),
                ctx,
            )
        return generator.filters[filter_index].desugar(ctx).and_then(
            lambda guard: self._desugar_filters(
                generator,
                filter_index + 1,
                (*filters, guard),
                iterable,
                index,
                resolved,
                ctx,
            )
        )

    def _complete(self, resolved, element, key=None) -> Outcome:
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.ir import PrimitiveSort, _Lambda, _intern_term, ctor
        from sugar_lift_py_tests.outcome import Complete

        owner = str(self.site)
        element_term = (
            ctor(
                "python:dict_entry",
                [key.to_term(owner=owner), element.to_term(owner=owner)],
                symbol_kind="coordinate",
            )
            if key is not None
            else element.to_term(owner=owner)
        )
        body = element_term
        recurrence_rows = []
        for target, iterable, filters in reversed(resolved):
            for guard in reversed(filters):
                body = ctor(
                    "python:loop.filter_guard",
                    [
                        guard.to_term(owner=owner),
                        body,
                        ctor("python:loop.latch", [], symbol_kind="coordinate"),
                    ],
                    symbol_kind="coordinate",
                )
            recurrence_rows.append((target, iterable, body))
            body = ctor(
                "python:loop.flat_map",
                [
                    iterable.to_term(owner=owner),
                    _intern_term(_Lambda(target, PrimitiveSort("Value"), body)),
                    ctor("python:loop.exhaustion", [], symbol_kind="coordinate"),
                ],
                symbol_kind="coordinate",
            )
        outer_target, outer_iterable, outer_body = recurrence_rows[-1]
        term = ctor(
            self.kind,
            [
                outer_iterable.to_term(owner=owner),
                _intern_term(
                    _Lambda(outer_target, PrimitiveSort("Value"), outer_body)
                ),
                ctor("python:loop.exhaustion", [], symbol_kind="coordinate"),
            ],
            symbol_kind="coordinate",
        )
        return Complete(ComprehensionValue(term))
