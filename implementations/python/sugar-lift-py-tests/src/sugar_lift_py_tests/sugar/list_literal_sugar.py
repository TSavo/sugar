from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ListValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ListLiteralSugar(Sugar, role=SugarRole.TERM):
    """A list literal. It reduces each element, and the result is a list of them.
    Incomplete elements propagate -- no partial list. Its own sugar, its own type;
    the list is the reduced elements in construction order, no fork."""

    elements: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "List"

    @classmethod
    def new(cls, site, ctx) -> "ListLiteralSugar":
        # Elements are factory-built (audited), never reduced here.
        return cls(
            elements=tuple(
                ctx.build_body(elt, SugarRole.TERM) for elt in site.list_elts()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # A bare list literal reduces as a statement body step, then returns z. Lists do
        # not compare by == to a literal easily in the witness harness, so the pair
        # discriminates on the returned face -- the list itself is just present.
        prefix = "def A(z):\n    [1, 2]\n    return z\n\n"
        return _call_pair(
            name="list_literal_return",
            owner_sugar="ListLiteralSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce each element; the result is a list of them.
        return self._collect(self.elements, (), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            return Complete(ListValue(accumulated))
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._collect(tuple(rest), (*accumulated, value), ctx)
        )

    def walk_children(self):
        return self.elements
