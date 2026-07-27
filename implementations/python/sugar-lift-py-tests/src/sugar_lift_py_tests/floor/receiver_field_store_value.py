from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ReceiverFieldStoreValue(FloorValue):
    receiver: FloorValue
    attr: str
    value: FloorValue

    def guarded(self, formula):
        from .guarded_receiver_field_store_value import (
            GuardedReceiverFieldStoreValue,
        )

        return GuardedReceiverFieldStoreValue(
            self.receiver, self.attr, self.value, formula
        )

    def extend_scope(self, ctx):
        """Advance every binding that names this exact constructed receiver."""
        from .object_value import ObjectValue

        if not isinstance(self.receiver, ObjectValue):
            return ctx
        updated = self.receiver.with_field_store(self.attr, self.value)
        temporal = ctx.temporal
        matched = False
        for binding in ctx.temporal.bindings:
            if binding.value is self.receiver:
                temporal = temporal.bind_value(
                    binding.name, updated, blame=binding.blame
                )
                matched = True
        return ctx.with_temporal(temporal) if matched else ctx

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:receiver-field-store",
            [
                self.receiver.to_term(owner=owner),
                str_const(self.attr),
                self.value.to_term(owner=owner),
            ],
        )
