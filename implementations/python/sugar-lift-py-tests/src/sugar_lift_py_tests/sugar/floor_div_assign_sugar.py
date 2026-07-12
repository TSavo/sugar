from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class FloorDivAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """`x //= v`: floor-divide the old binding, then rebind the name."""

    target_name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "AugAssign" or site.aug_assign_op() != "FloorDiv":
            return False
        return site.aug_assign_target().observed == "Name"

    @classmethod
    def new(cls, site, ctx) -> "FloorDivAssignSugar":
        return cls(
            target_name=site.aug_assign_target().name_id(),
            value=ctx.build_body(site.aug_assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    x = 7\n    x //= 2\n    return x\n\n"
        return _call_pair(
            name="floor_div_assign_return",
            owner_sugar="FloorDivAssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 3\n",
            lying=prefix + "def test_a():\n    assert A(5) == 4\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.reduce(ctx).and_then(
            lambda arg: (
                ctx.temporal.value_for(self.target_name)
                .answer(ctx)
                .and_then(
                    lambda old: old.floor_divide(arg, self.site).and_then(
                        lambda updated: Complete(ScopeRebind(self.target_name, updated))
                    )
                )
            )
        )

    def walk_children(self):
        return (self.value,)
