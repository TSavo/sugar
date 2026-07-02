from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Outcome

from .descriptor_operation import DescriptorOperation
from .perform_operation import perform_operation


@dataclass(frozen=True)
class AttributeDeleteOperation:
    name: str
    owner: str = "AttributeDeleteSugar"
    blame: str = "<unknown>"

    def delete_object(self, receiver: ObjectValue, ctx) -> Outcome:
        descriptor = receiver.class_field_value(self.name)
        if isinstance(descriptor, ObjectValue) and descriptor.has_method("__delete__"):
            return perform_operation(
                owner=self.owner,
                blame=self.blame,
                receiver=descriptor,
                method_name="descriptor_with",
                operation=DescriptorOperation(
                    attribute=self.name,
                    slot="__delete__",
                    obj=receiver,
                    owner_class=receiver.class_name,
                    owner=self.owner,
                    blame=self.blame,
                ),
                ctx=ctx,
            )
        if receiver.has_method("__delattr__"):
            return receiver.call_method_value(
                "__delattr__",
                (StringValue(self.name),),
                owner=self.owner,
                blame=self.blame,
            )
        return receiver._floor_gap(
            owner=self.owner,
            blame=self.blame,
            observed=f"{receiver.class_name}.{self.name}",
            requested="object attribute deletion effect",
            fix=(
                f"define `__delattr__` on `{receiver.class_name}`, add a "
                f"`__delete__` descriptor for `{self.name}`, or emit a real "
                "attribute-deletion effect"
            ),
        )
