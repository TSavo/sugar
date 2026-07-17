from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import (
    AttributeAugAssignRuntimeEffect,
    runtime_effect_witness,
)
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SelectedAttributeAugAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """Keep an in-place update through a selected receiver at runtime.

    Python evaluates the receiver once, then performs attribute lookup, in-place
    addition, and descriptor-backed storage. A call/subscript receiver does not
    have a stable temporal binding that the lift may update. Preserve the full
    receiver-plus-increment coordinate as a typed runtime effect.
    """

    receiver: SugarBody
    field_name: str
    increment: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "AugAssign" or site.aug_assign_op() != "Add":
            return False
        target = site.aug_assign_target()
        return (
            target.observed == "Attribute" and target.attr_receiver().observed != "Name"
        )

    @classmethod
    def new(cls, site, ctx) -> "SelectedAttributeAugAssignSugar":
        target = site.aug_assign_target()
        return cls(
            receiver=ctx.build_body(target.attr_receiver(), SugarRole.TERM),
            field_name=target.attr_name(),
            increment=ctx.build_body(site.aug_assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="selected_attribute_augassign_runtime_effect",
            owner_sugar=cls.__name__,
            source=(
                "def A(obj):\n" "    type(obj).called_wrap += 1\n" "    return 1\n"
            ),
            effect_class="AttributeAugAssignRuntimeEffect",
            reason_needle="runtime-selected receiver",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="runtime-selected subscript key",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.increment.reduce(ctx).and_then(
                lambda increment: self._runtime_effect(receiver, increment)
            )
        )

    def _runtime_effect(self, receiver, increment) -> Outcome:
        coordinate = SymbolicValue(
            ctor(
                "py.attribute_iadd",
                [
                    receiver.to_term(owner=str(self.site)),
                    str_const(self.field_name),
                    increment.to_term(owner=str(self.site)),
                ],
            )
        )
        return Incomplete(
            AttributeAugAssignRuntimeEffect(
                "attribute augmented assignment depends on the runtime-selected "
                "receiver and its descriptor protocol; "
                f"field={self.field_name}; site={self.site}",
                witness=runtime_effect_witness(
                    "py.attribute_iadd", coordinate, self.site
                ),
            )
        )

    def walk_children(self):
        return (self.receiver, self.increment)
