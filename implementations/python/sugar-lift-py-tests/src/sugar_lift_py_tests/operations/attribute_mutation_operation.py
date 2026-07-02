from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue, ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Outcome

from .descriptor_operation import DescriptorOperation
from .perform_operation import perform_operation


@dataclass(frozen=True)
class AttributeMutationOperation:
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
                method_name="descriptor_with",
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
            return receiver.call_method_value(
                "__setattr__",
                (StringValue(self.name), self.value),
                owner=self.owner,
                blame=self.blame,
            )
        return receiver._floor_gap(
            owner=self.owner,
            blame=self.blame,
            observed=f"{receiver.class_name}.{self.name}",
            requested="object attribute mutation effect",
            fix=(
                f"define `__setattr__` on `{receiver.class_name}`, add a "
                f"`__set__` descriptor for `{self.name}`, or emit a real "
                "attribute-mutation effect"
            ),
        )
