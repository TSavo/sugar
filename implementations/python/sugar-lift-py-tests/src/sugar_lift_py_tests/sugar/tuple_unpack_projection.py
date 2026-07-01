from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleUnpackProjection:
    receiver: SugarBody
    index: int

    def __post_init__(self) -> None:
        if not isinstance(self.receiver, SugarBody):
            raise TypeError("TupleUnpackProjection receiver must be factory-built")

    def desugar(self, ctx):
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = complete_value(
            receiver_outcome, owner="TupleUnpackProjection receiver"
        )
        return Complete(
            SymbolicValue(
                ctor(
                    "py.unpack",
                    [
                        floor_to_term(receiver, owner="TupleUnpackProjection receiver"),
                        num(self.index),
                    ],
                )
            )
        )
