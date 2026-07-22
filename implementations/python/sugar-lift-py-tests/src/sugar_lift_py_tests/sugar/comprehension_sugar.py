"""Simple symbolic comprehensions as non-hunting transform coordinates.

Concrete comprehensions dissolve to displays in the source tree.  When the
single iterable is symbolic, the comprehension instead retains the iterable,
binding name, and transform term.  A call such as ``f(x)`` therefore remains
the ordinary ``call:f(x)`` dig cue; this sugar never opens or copies ``f``.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ComprehensionSugar(Sugar):
    kind: str
    target: str
    iterable: Sugar
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
        return self.iterable.desugar(ctx).and_then(
            lambda iterable: self._with_iterable(iterable, ctx)
        )

    def _with_iterable(self, iterable, ctx: object) -> Outcome:
        if self.key is not None:
            return self.key.desugar(ctx).and_then(
                lambda key: self.element.desugar(ctx).and_then(
                    lambda element: self._complete(iterable, element, key)
                )
            )
        return self.element.desugar(ctx).and_then(
            lambda element: self._complete(iterable, element)
        )

    def _complete(self, iterable, element, key=None) -> Outcome:
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.ir import bound_transform, ctor

        owner = str(self.site)
        templates = []
        if key is not None:
            templates.append(key.to_term(owner=owner))
        templates.append(element.to_term(owner=owner))
        args = [
            iterable.to_term(owner=owner),
            bound_transform(self.target, templates),
        ]
        return Complete(
            ComprehensionValue(ctor(self.kind, args, symbol_kind="coordinate"))
        )
