from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import (
    AttributeStoreRuntimeEffect,
    runtime_effect_witness,
)
from sugar_lift_py_tests.factory import factory_panic_gap
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ImportAliasValue,
    ObjectValue,
    OpaqueOpCallsite,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SelectedAttributeAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """Store through an attribute receiver selected by a call or subscript."""

    receiver: SugarBody
    field_name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        return (
            len(targets) == 1
            and targets[0].observed == "Attribute"
            and site.assign_target_dotted_attribute_path() is None
        )

    @classmethod
    def new(cls, site, ctx) -> "SelectedAttributeAssignSugar":
        target = site.assign_targets()[0]
        return cls(
            receiver=ctx.build_body(target.attr_receiver(), SugarRole.TERM),
            field_name=target.attr_name(),
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="selected_attribute_store_runtime_effect",
            owner_sugar=cls.__name__,
            source=("def A(items):\n" "    items[0].value = 1\n" "    return 1\n"),
            effect_class="AttributeStoreRuntimeEffect",
            reason_needle="runtime-selected receiver",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="runtime-selected subscript key",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.value.reduce(ctx).and_then(
                lambda value: self._store(receiver, value, ctx)
            )
        )

    def _store(self, receiver, value, ctx) -> Outcome:
        if isinstance(receiver, ObjectValue):
            descriptor = receiver.class_field_value(self.field_name)
            if isinstance(descriptor, ObjectValue) and descriptor.has_method("__set__"):
                return descriptor.call_method_value(
                    "__set__",
                    (receiver, value),
                    owner=type(self).__name__,
                    blame=self.site,
                    ctx=ctx,
                )
            if receiver.has_method("__setattr__"):
                return receiver.call_method_value(
                    "__setattr__",
                    (StringValue(self.field_name), value),
                    owner=type(self).__name__,
                    blame=self.site,
                    ctx=ctx,
                )
            factory_panic_gap(
                owner=type(self).__name__,
                blame=self.site,
                observed="ObjectValue",
                requested="citable selected-receiver attribute store",
                fix="add the real object-state construction arm",
            )

        if isinstance(
            receiver,
            (SymbolicValue, CallSiteValue, OpaqueOpCallsite, ImportAliasValue),
        ):
            return Incomplete(
                AttributeStoreRuntimeEffect(
                    "attribute store dispatch depends on the runtime-selected "
                    f"receiver and its descriptor protocol; field={self.field_name}",
                    witness=runtime_effect_witness("py.setattr", receiver, self.site),
                )
            )

        factory_panic_gap(
            owner=type(self).__name__,
            blame=self.site,
            observed=type(receiver).__name__,
            requested="citable selected-receiver attribute store",
            fix="add the real receiver-specific construction arm",
        )

    def walk_children(self):
        return (self.receiver, self.value)
