from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar, FloorValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ChainedBindings(FloorValue):
    bindings: tuple[BoundVar, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        temporal = ctx.temporal
        for binding in self.bindings:
            temporal = temporal.bind_value(binding.name, binding)
        return replace(ctx, temporal=temporal)


@dataclass(frozen=True)
class ChainedAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """Chained all-name assignment ``a = b = value``.

    Every target aliases the same rhs source under the same definition scope.
    Tuple, list, starred, attribute, subscript, and mixed chains stay unowned.
    """

    names: tuple[str, ...]
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        return len(targets) > 1 and all(target.observed == "Name" for target in targets)

    @classmethod
    def new(cls, site, ctx) -> "ChainedAssignSugar":
        targets = site.assign_targets()
        return cls(
            names=tuple(target.name_id() for target in targets),
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    a = b = 5\n    return a + b\n\n"
        return _call_pair(
            name="chained_assign_return",
            owner_sugar="ChainedAssignSugar",
            truthful=prefix + "def test_a():\n    assert A() == 10\n",
            lying=prefix + "def test_a():\n    assert A() == 11\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return Complete(
            ChainedBindings(
                tuple(BoundVar(name, self.value, scope=ctx) for name in self.names)
            )
        )

    def walk_children(self):
        return (self.value,)
