from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome

from .descriptor_operation import DescriptorOperation
from .object_method_call import call_object_method_value, raise_object_floor_gap
from .perform_operation import perform_operation


@dataclass(frozen=True)
class AttributeDeleteOperation:
    method_name: ClassVar[str] = "attribute_delete_with"
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
            return call_object_method_value(
                receiver,
                "__delattr__",
                (StringValue(self.name),),
                owner=self.owner,
                blame=self.blame,
            )
        fields = tuple(field for field in receiver.fields if field.name != self.name)
        if len(fields) != len(receiver.fields):
            return Complete(
                ObjectValue(
                    class_name=receiver.class_name,
                    fields=fields,
                    methods=receiver.methods,
                    class_fields=receiver.class_fields,
                    identity=receiver.identity,
                )
            )
        raise_object_floor_gap(
            receiver,
            owner=self.owner,
            blame=self.blame,
            observed=f"{receiver.class_name}.{self.name}",
            requested="existing object attribute field",
            fix=(
                f"assign `{self.name}` on `{receiver.class_name}` before deletion, "
                f"define `__delattr__`, add a `__delete__` descriptor for "
                f"`{self.name}`, or emit a real attribute-deletion effect"
            ),
        )
