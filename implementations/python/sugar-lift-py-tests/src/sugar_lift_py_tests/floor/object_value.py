from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from .object_field import ObjectField


@dataclass(frozen=True)
class ObjectValue(FloorValue):
    class_name: str
    fields: tuple[ObjectField, ...]

    def attribute_with(self, operation, ctx):
        return operation.attribute_object(self, ctx)
