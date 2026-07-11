from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """``receiver.field = value`` for ``Name.attr`` targets.

    Threads the rhs as a ScopeRebind under key ``receiver.field`` so nested
    methods (e.g. ``e.payload = None`` under try/except) construct without a
    factory gap. Not a full object-mutation model — recognition + binding.
    """

    receiver_name: str
    field_name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        return (
            site.assign_target_attribute_receiver_name() is not None
            and site.assign_target_attribute_name() is not None
        )

    @classmethod
    def new(cls, site, ctx) -> "AttributeAssignSugar":
        return cls(
            receiver_name=site.assign_target_attribute_receiver_name(),
            field_name=site.assign_target_attribute_name(),
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Discrimination rides assign face: bound field value on return path.
        prefix = (
            "def A(z):\n"
            "    class E:\n"
            "        pass\n"
            "    e = E()\n"
            "    e.payload = z\n"
            "    return e.payload\n"
            "\n"
        )
        return _call_pair(
            name="attr_assign_return",
            owner_sugar="AttributeAssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        key = f"{self.receiver_name}.{self.field_name}"
        return self.value.reduce(ctx).and_then(
            lambda val: Complete(ScopeRebind(key, val))
        )

    def walk_children(self):
        return (self.value,)
