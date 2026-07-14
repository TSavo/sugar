from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.attribute_assign_sugar import assign_attribute_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeAddAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """``receiver.field += value`` is one ordered read, add, store sequence."""

    receiver_name: str
    field_name: str
    receiver: SugarBody
    current_value: SugarBody
    increment: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "AugAssign" or site.aug_assign_op() != "Add":
            return False
        target = site.aug_assign_target()
        return (
            target.observed == "Attribute" and target.attr_receiver().observed == "Name"
        )

    @classmethod
    def new(cls, site, ctx) -> "AttributeAddAssignSugar":
        target = site.aug_assign_target()
        receiver = target.attr_receiver()
        return cls(
            receiver_name=receiver.name_id(),
            field_name=target.attr_name(),
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            current_value=ctx.build_body(target, SugarRole.TERM),
            increment=ctx.build_body(site.aug_assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    z.value = 1\n"
            "    z.value += 2\n"
            "    return z.value\n\n"
        )
        return _call_pair(
            name="attribute_add_assign_return",
            owner_sugar="AttributeAddAssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 3\n",
            lying=prefix + "def test_a():\n    assert A(5) == 4\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        key = f"{self.receiver_name}.{self.field_name}"
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.current_value.reduce(ctx).and_then(
                lambda old: self.increment.reduce(ctx).and_then(
                    lambda increment: old.add(increment, self.site).and_then(
                        lambda updated: assign_attribute_value(
                            receiver=receiver,
                            field_name=self.field_name,
                            value=updated,
                            key=key,
                            site=self.site,
                            ctx=ctx,
                            owner=type(self).__name__,
                        )
                    )
                )
            )
        )

    def walk_children(self):
        return (self.receiver, self.current_value, self.increment)
