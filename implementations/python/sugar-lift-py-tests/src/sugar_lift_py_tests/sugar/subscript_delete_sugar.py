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
class SubscriptDeleteSugar(Sugar, role=SugarRole.STATEMENT):
    """One ``del receiver[index]`` routed through the subscript-store floor."""

    receiver: SugarBody
    receiver_name: str | None
    index: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Delete":
            return False
        targets = site.delete_targets()
        return (
            len(targets) == 1
            and targets[0].observed == "Subscript"
            and targets[0].subscript_index().observed != "Slice"
        )

    @classmethod
    def new(cls, site, ctx) -> "SubscriptDeleteSugar":
        target = site.delete_targets()[0]
        receiver = target.subscript_receiver()
        return cls(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_name=receiver.name_id() if receiver.observed == "Name" else None,
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A():\n"
            "    xs = [1, 2, 3]\n"
            "    del xs[1]\n"
            "    return xs[1]\n\n"
        )
        return _call_pair(
            name="subscript_delete_post_state",
            owner_sugar="SubscriptDeleteSugar",
            truthful=prefix + "def test_a():\n    assert A() == 3\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.index.reduce(ctx).and_then(
                lambda index: receiver.delitem(index, self.site).and_then(
                    lambda updated: self._cite_update(updated)
                )
            )
        )

    def _cite_update(self, updated) -> Outcome:
        if self.receiver_name is not None:
            return Complete(ScopeRebind(self.receiver_name, updated))
        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "subscript delete completed on a non-name receiver whose post-state "
                f"cannot be rebound; site={self.site}"
            )
        )

    def walk_children(self):
        return (self.receiver, self.index)
