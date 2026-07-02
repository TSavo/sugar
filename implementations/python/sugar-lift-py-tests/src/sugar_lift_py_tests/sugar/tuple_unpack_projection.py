from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.operations.perform_operation import perform_operation
from sugar_lift_py_tests.operations.sequence_projection_operation import (
    SequenceProjectionOperation,
)
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleUnpackProjection:
    receiver: SugarBody
    index: int
    blame: str = "<unknown>"

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
        return perform_operation(
            owner="TupleUnpackProjection",
            blame=self.blame,
            receiver=receiver,
            operation=SequenceProjectionOperation(
                index=self.index,
                owner="TupleUnpackProjection",
                blame=self.blame,
            ),
            ctx=ctx,
        )
