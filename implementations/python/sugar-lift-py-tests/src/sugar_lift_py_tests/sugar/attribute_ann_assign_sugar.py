from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeAnnAssignSugar(Sugar, role=SugarRole.STATEMENT):
    receiver_name: str
    field_name: str
    receiver: SugarBody
    annotation: SugarBody
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "AnnAssign":
            return False
        target = site.annassign_target()
        return (
            target.observed == "Attribute"
            and target.attr_receiver().observed == "Name"
            and site.annassign_value() is not None
            and site.annassign_annotation().observed != "BinOp"
        )

    @classmethod
    def new(cls, site, ctx) -> "AttributeAnnAssignSugar":
        target = site.annassign_target()
        return cls(
            receiver_name=target.attr_receiver().name_id(),
            field_name=target.attr_name(),
            receiver=ctx.build_body(target.attr_receiver(), SugarRole.TERM),
            annotation=ctx.build_body(site.annassign_annotation(), SugarRole.TERM),
            value=ctx.build_body(site.annassign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    class E:\n"
            "        pass\n"
            "    e = E()\n"
            "    e.value: int = z\n"
            "    return e.value\n\n"
        )
        return _call_pair(
            name="attribute_annassign",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A(3) == 3\n",
            lying=prefix + "def test_a():\n    assert A(3) == 4\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        key = f"{self.receiver_name}.{self.field_name}"
        return self.receiver.reduce(ctx).and_then(
            lambda _receiver: self.value.reduce(ctx).and_then(
                lambda value: Complete(ScopeRebind(key, value))
            )
        )

    def walk_children(self):
        return (self.receiver, self.annotation, self.value)
