from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue, StringValue
from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class DescriptorOperation:
    attribute: str
    slot: str
    obj: FloorValue
    owner_class: str
    value: FloorValue | None = None
    owner: str = "DescriptorOperation"
    blame: str = "<unknown>"

    def descriptor_object(self, descriptor, ctx) -> Outcome:
        del ctx
        if self.slot == "__get__":
            return descriptor.call_method_value(
                "__get__",
                (self.obj, StringValue(self.owner_class)),
                owner=self.owner,
                blame=self.blame,
            )
        if self.slot == "__set__" and self.value is not None:
            return descriptor.call_method_value(
                "__set__",
                (self.obj, self.value),
                owner=self.owner,
                blame=self.blame,
            )
        if self.slot == "__delete__":
            return descriptor.call_method_value(
                "__delete__",
                (self.obj,),
                owner=self.owner,
                blame=self.blame,
            )
        return descriptor._floor_gap(
            owner=self.owner,
            blame=self.blame,
            observed=f"{descriptor.class_name}.{self.slot}",
            requested="descriptor data-model slot",
            fix=(
                f"add DescriptorOperation support for `{self.slot}` on "
                f"`{self.attribute}`"
            ),
        )
