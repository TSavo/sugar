from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import FloorValue, ObjectField, ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome

from .descriptor_operation import DescriptorOperation
from .object_method_call import call_object_method_value, raise_object_floor_gap
from .perform_operation import perform_operation


@dataclass(frozen=True)
class AttributeMutationOperation:
    method_name: ClassVar[str] = "attribute_assign_with"
    name: str
    value: FloorValue
    owner: str = "AttributeAssignSugar"
    blame: str = "<unknown>"

    def assign_object(self, receiver: ObjectValue, ctx) -> Outcome:
        descriptor = receiver.class_field_value(self.name)
        if isinstance(descriptor, ObjectValue) and descriptor.has_method("__set__"):
            return perform_operation(
                owner=self.owner,
                blame=self.blame,
                receiver=descriptor,
                operation=DescriptorOperation(
                    attribute=self.name,
                    slot="__set__",
                    obj=receiver,
                    owner_class=receiver.class_name,
                    value=self.value,
                    owner=self.owner,
                    blame=self.blame,
                ),
                ctx=ctx,
            )
        if receiver.has_method("__setattr__"):
            return call_object_method_value(
                receiver,
                "__setattr__",
                (StringValue(self.name), self.value),
                owner=self.owner,
                blame=self.blame,
            )
        return Complete(
            ObjectValue(
                class_name=receiver.class_name,
                fields=(
                    *(field for field in receiver.fields if field.name != self.name),
                    ObjectField(self.name, self.value),
                ),
                methods=receiver.methods,
                class_fields=receiver.class_fields,
                identity=receiver.identity,
            )
        )
