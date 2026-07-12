from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar, ModuleBoundVar
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AssignSugar(Sugar, role=SugarRole.STATEMENT):
    """A `name = <rhs>` statement. The rhs is built as a SugarBody (the SOURCE),
    never reduced in new. Desugar yields a BoundVar that aliases the name to that
    source under the DEFINITION scope -- the block threads it as a let; a
    reference recomposes it."""

    name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Single Name target only; tuple/attr/subscript targets stay loud gaps.
        return site.observed == "Assign" and site.assign_target_name() is not None

    @classmethod
    def new(cls, site, ctx) -> "AssignSugar":
        # The rhs is factory-built (audited), never reduced here -- it IS the source.
        return cls(
            name=site.assign_target_name(),
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # `x = z; return x` aliases through the source: the truthful twin rides the
        # identity, the lying twin asserts another -- the pair discriminates.
        prefix = "def A(z):\n    x = z\n    return x\n\n"
        return _call_pair(
            name="assign_return",
            owner_sugar="AssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Capture the DEFINITION scope: ctx still holds the OLD binding for the name
        # (the block threads the new one AFTER this), so a self-referential rebind
        # reads the old value. The rhs stays as source -- not reduced here.
        binding = ModuleBoundVar if self.name in ctx.global_names else BoundVar
        return Complete(binding(self.name, self.value, scope=ctx))

    def walk_children(self):
        return (self.value,)
