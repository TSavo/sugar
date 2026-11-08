from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue
from .object_value import ObjectValue


@dataclass(frozen=True)
class GuardedReceiverStateValue(FloorValue):
    """An immutable receiver snapshot retained only on its source branch."""

    receiver: ObjectValue
    guard: Formula

    def __post_init__(self):
        if not isinstance(self.receiver, ObjectValue):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="GuardedReceiverStateValue",
                blame="receiver-state",
                observed=type(self.receiver).__name__,
                requested="a constructed ObjectValue snapshot",
                fix="retain the exact source receiver state before guarding it",
            )

    def guarded(self, formula):
        from sugar_lift_py_tests.ir import and_

        return GuardedReceiverStateValue(self.receiver, and_([formula, self.guard]))

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, formula_term, str_const

        return ctor(
            "python:guarded-receiver-state",
            [
                formula_term(self.guard),
                self.receiver.to_term(owner=owner),
                *(
                    ctor(
                        "python:field",
                        [str_const(field.name), field.value.to_term(owner=owner)],
                    )
                    for field in self.receiver.fields
                ),
            ],
            symbol_kind="coordinate",
        )
