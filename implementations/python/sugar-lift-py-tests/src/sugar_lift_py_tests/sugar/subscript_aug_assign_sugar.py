from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SubscriptAugAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """``receiver[index] += value`` is read, add, then subscript store."""

    receiver: SugarBody
    receiver_name: str | None
    index: SugarBody
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "AugAssign" or site.aug_assign_op() != "Add":
            return False
        target = site.aug_assign_target()
        return target.observed == "Subscript" and target.subscript_index().observed != "Slice"

    @classmethod
    def new(cls, site, ctx) -> "SubscriptAugAssignSugar":
        target = site.aug_assign_target()
        receiver = target.subscript_receiver()
        return cls(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_name=receiver.name_id() if receiver.observed == "Name" else None,
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            value=ctx.build_body(site.aug_assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    xs = [1]\n    xs[0] += 2\n    return xs[0]\n\n"
        return _call_pair(
            name="subscript_aug_assign_return",
            owner_sugar="SubscriptAugAssignSugar",
            truthful=prefix + "def test_a():\n    assert A() == 3\n",
            lying=prefix + "def test_a():\n    assert A() == 1\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.index.reduce(ctx).and_then(
                lambda index: receiver.subscript(index, self.site).and_then(
                    lambda old: self.value.reduce(ctx).and_then(
                        lambda value: old.add(value, self.site).and_then(
                            lambda updated: receiver.setitem(index, updated, self.site).and_then(
                                self._cite_update
                            )
                        )
                    )
                )
            )
        )

    def _cite_update(self, updated) -> Outcome:
        if self.receiver_name is not None:
            return Complete(ScopeRebind(self.receiver_name, updated))
        from sugar_lift_py_tests.effect import runtime_effect_witness

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "subscript augmented assignment completed on a non-name receiver "
                f"whose post-state cannot be rebound; site={self.site}",
                witness=runtime_effect_witness("py.setitem", updated, self.site),
            )
        )

    def walk_children(self):
        return (self.receiver, self.index, self.value)
