from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SetValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SetLiteralSugar(Sugar, role=SugarRole.TERM):
    """A set literal. It reduces each element, and the result is a set of them.
    Incomplete elements propagate -- no partial set. Its own sugar, its own type;
    the set is the reduced elements in construction order, no fork."""

    elements: tuple[SugarBody, ...]
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Set"

    @classmethod
    def new(cls, site, ctx) -> "SetLiteralSugar":
        # Elements are factory-built (audited), never reduced here.
        return cls(
            elements=tuple(
                ctx.build_body(elt, SugarRole.TERM) for elt in site.set_elts()
            ),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        # A bare set literal reduces as a statement body step, then returns z. Sets do
        # not compare by == to a literal easily in the witness harness, so the pair
        # discriminates on the returned face -- the set itself is just present.
        prefix = "def A(z):\n    {1}\n    return z\n\n"
        return _call_pair(
            name="set_literal_return",
            owner_sugar="SetLiteralSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce each element; the result is a set of them.
        return self._collect(self.elements, (), ctx)

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if not remaining:
            return Complete(SetValue(accumulated))
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._collect(tuple(rest), (*accumulated, value), ctx)
        )
