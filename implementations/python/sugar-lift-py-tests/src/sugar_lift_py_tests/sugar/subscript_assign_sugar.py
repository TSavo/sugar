from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.subscript_store_post_state import (
    cite_subscript_post_state,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SubscriptAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """One ``receiver[index] = value`` assignment.

    The three expressions are factory-built sources. A named concrete receiver
    rebinds to the cited post-state; a runtime-owned store is a typed effect.
    Slice targets and every other Assign shape remain unowned and panic.
    """

    receiver: SugarBody
    receiver_coordinate: str | None
    index: SugarBody
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        return len(targets) == 1 and targets[0].observed == "Subscript"

    @classmethod
    def new(cls, site, ctx) -> "SubscriptAssignSugar":
        target = site.assign_targets()[0]
        receiver = target.subscript_receiver()
        return cls(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_coordinate=receiver.dotted_expr_name(),
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    xs = [1, 2, 3]\n    xs[1] = 9\n    return xs[1]\n\n"
        return _call_pair(
            name="subscript_assign_post_state",
            owner_sugar="SubscriptAssignSugar",
            truthful=prefix + "def test_a():\n    assert A() == 9\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.index.reduce(ctx).and_then(
                lambda index: self.value.reduce(ctx).and_then(
                    lambda value: receiver.setitem(index, value, self.site).and_then(
                        lambda updated: self._cite_update(receiver, updated)
                    )
                )
            )
        )

    def _cite_update(self, receiver, updated) -> Outcome:
        return cite_subscript_post_state(
            receiver_coordinate=self.receiver_coordinate,
            receiver=receiver,
            updated=updated,
            operation="py.setitem",
            site=self.site,
        )

    def walk_children(self):
        return (self.receiver, self.index, self.value)
