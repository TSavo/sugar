from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue, ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Outcome

from .object_method_call import call_object_method_value, raise_object_floor_gap


@dataclass(frozen=True)
class DescriptorOperation:
    attribute: str
    slot: str
    obj: FloorValue
    owner_class: str
    value: FloorValue | None = None
    owner: str = "DescriptorOperation"
    blame: str = "<unknown>"

    def descriptor_object(self, descriptor: ObjectValue, ctx) -> Outcome:
        del ctx
        if self.slot == "__get__":
            return call_object_method_value(descriptor,
                "__get__",
                (self.obj, StringValue(self.owner_class)),
                owner=self.owner,
                blame=self.blame,
            )
        if self.slot == "__set__" and self.value is not None:
            return call_object_method_value(descriptor,
                "__set__",
                (self.obj, self.value),
                owner=self.owner,
                blame=self.blame,
            )
        if self.slot == "__delete__":
            return call_object_method_value(descriptor,
                "__delete__",
                (self.obj,),
                owner=self.owner,
                blame=self.blame,
            )
        raise_object_floor_gap(
            descriptor,
            owner=self.owner,
            blame=self.blame,
            observed=f"{descriptor.class_name}.{self.slot}",
            requested="descriptor data-model slot",
            fix=(
                f"add DescriptorOperation support for `{self.slot}` on "
                f"`{self.attribute}`"
            ),
        )
