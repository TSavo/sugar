from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from .object_field import ObjectField
from .object_method_value import ObjectMethodValue


@dataclass(frozen=True)
class ObjectValue(FloorValue):
    class_name: str
    fields: tuple[ObjectField, ...]
    methods: tuple[ObjectMethodValue, ...] = ()
    identity: str = ""

    def attribute_with(self, operation, ctx):
        return operation.attribute_object(self, ctx)

    def call_method_with(self, operation, ctx):
        return operation.call_object_method(self, ctx)
