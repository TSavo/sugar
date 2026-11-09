from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .receiver_field_store_value import ReceiverFieldStoreValue


@dataclass(frozen=True)
class GuardedReceiverFieldStoreValue(ReceiverFieldStoreValue):
    guard: Formula

    def guarded(self, formula):
        from sugar_lift_py_tests.outcome.exit_set import _and_guards, _is_true

        combined = _and_guards(formula, self.guard)
        if _is_true(combined):
            return ReceiverFieldStoreValue(self.receiver, self.attr, self.value)
        return GuardedReceiverFieldStoreValue(
            self.receiver,
            self.attr,
            self.value,
            combined,
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, formula_term

        return ctor(
            "python:guarded-receiver-field-store",
            [formula_term(self.guard), super().to_term(owner=owner)],
        )
