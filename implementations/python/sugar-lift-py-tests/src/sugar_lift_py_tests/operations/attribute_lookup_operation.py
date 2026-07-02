from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome

from .descriptor_operation import DescriptorOperation
from .perform_operation import perform_operation


@dataclass(frozen=True)
class AttributeLookupOperation:
    name: str
    owner: str = "AttributeSugar"
    blame: str = "<unknown>"

    def attribute_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        if receiver.has_method("__getattribute__"):
            return receiver.call_method_value(
                "__getattribute__",
                (StringValue(self.name),),
                owner=self.owner,
                blame=self.blame,
            )
        return self._default_attribute_object(receiver, ctx)

    def _default_attribute_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        descriptor = receiver.class_field_value(self.name)
        if _is_data_descriptor(descriptor):
            return self._descriptor_get(receiver, descriptor, ctx)
        for field in reversed(receiver.fields):
            if field.name == self.name:
                return Complete(field.value)
        if isinstance(descriptor, ObjectValue):
            if descriptor.has_method("__get__"):
                return self._descriptor_get(receiver, descriptor, ctx)
            return Complete(descriptor)
        if descriptor is not None:
            return Complete(descriptor)
        for method in reversed(receiver.methods):
            if method.name == self.name:
                return self._floor_gap(
                    observed=f"{receiver.class_name}.{self.name}",
                    requested="bound method attribute floor",
                    fix=(
                        f"add bound-method attribute floor for "
                        f"`{receiver.class_name}.{self.name}`"
                    ),
                )
        if receiver.has_method("__getattr__"):
            return receiver.call_method_value(
                "__getattr__",
                (StringValue(self.name),),
                owner=self.owner,
                blame=self.blame,
            )
        return self._floor_gap(
            observed=f"{receiver.class_name}.{self.name}",
            requested="constructor-bound field",
            fix=(
                f"bind `self.{self.name}` in `{receiver.class_name}.__init__`, "
                f"define `__getattr__` on `{receiver.class_name}`, "
                "or add the floor that owns this attribute"
            ),
        )

    def _descriptor_get(
        self, receiver: ObjectValue, descriptor: ObjectValue, ctx: object
    ) -> Outcome:
        return perform_operation(
            owner=self.owner,
            blame=self.blame,
            receiver=descriptor,
            method_name="descriptor_with",
            operation=DescriptorOperation(
                attribute=self.name,
                slot="__get__",
                obj=receiver,
                owner_class=receiver.class_name,
                owner=self.owner,
                blame=self.blame,
            ),
            ctx=ctx,
        )

    def _floor_gap(self, *, observed: str, requested: str, fix: str) -> None:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind=(
                "Constructor" if requested.startswith("constructor-bound ") else "Floor"
            ),
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role=requested,
                status="floor-gap",
                observed=observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
def _is_data_descriptor(value: object) -> bool:
    return (
        isinstance(value, ObjectValue)
        and value.has_method("__get__")
        and (value.has_method("__set__") or value.has_method("__delete__"))
    )
