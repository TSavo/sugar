from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .receiver_field_store_value import ReceiverFieldStoreValue


@dataclass(frozen=True)
class GuardedReceiverFieldStoreValue(ReceiverFieldStoreValue):
    guard: Formula

    def guarded(self, formula):
        from sugar_lift_py_tests.ir import and_

        return GuardedReceiverFieldStoreValue(
            self.receiver,
            self.attr,
            self.value,
            and_([formula, self.guard]),
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, formula_term

        return ctor(
            "python:guarded-receiver-field-store",
            [formula_term(self.guard), super().to_term(owner=owner)],
        )
