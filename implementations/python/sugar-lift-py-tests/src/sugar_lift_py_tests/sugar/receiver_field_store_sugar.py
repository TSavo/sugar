from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ReceiverFieldStoreSugar(Sugar):
    receiver: Sugar
    value: Sugar
    attr: str
    site: object = field(compare=False)
    # Nothing binds before a halt of the receiver or the value: its pre-halt
    # record is the block's prefix.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ReceiverFieldStoreValue",
            reason="initializer state is testimony from already-constructed children",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.receiver_field_store_value import (
            ReceiverFieldStoreValue,
        )

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.value.desugar(ctx).and_then(
                lambda value: ExitSet.completed(
                    ReceiverFieldStoreValue(receiver, self.attr, value)
                )
            )
        )
