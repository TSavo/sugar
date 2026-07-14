from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AssertSugar(Sugar, role=SugarRole.STATEMENT):
    """`assert <condition>`. It reduces the condition, and the result states
    itself: a symbolic predicate states an inv (the fact the record emits --
    first encounter a fact to discharge, a later consumer meets it as a
    warrant, a constraint; that duality is protocol position, never this
    sugar's), ground True states nothing, ground False is the named halt.
    The sugar owns no distinction; the value answers."""

    condition: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Assert"

    @classmethod
    def new(cls, site, ctx) -> "AssertSugar":
        # The condition is factory-built (audited), never reduced here.
        return cls(
            condition=ctx.build_body(site.assert_test(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # The stated inv IS the discriminator: the truthful twin's assert holds
        # in the body's universe, the lying twin's contradicts it.
        return _call_pair(
            name="assert_return",
            owner_sugar="AssertSugar",
            truthful=(
                "def A(z):\n    return z\n\n" "def test_a():\n    assert A(5) == 5\n"
            ),
            lying=(
                "def A(z):\n    return z\n\n" "def test_a():\n    assert A(5) == 6\n"
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce the condition, and the result states itself.
        return self.condition.reduce(ctx).and_then(
            lambda value: value.stated(self.site)
        )

    def walk_children(self):
        return (self.condition,)
