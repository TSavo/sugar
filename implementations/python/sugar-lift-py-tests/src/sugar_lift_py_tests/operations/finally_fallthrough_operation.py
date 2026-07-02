from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value

from .control_flow_guard_operation import ControlFlowGuardOperation
from .perform_operation import perform_operation


@dataclass(frozen=True)
class FinallyFallthroughOperation:
    incoming_block: BlockValue
    owner: str = "TrySugar.finally"
    blame: str = "<unknown>"

    def merge_finally_block(self, receiver: BlockValue, ctx) -> Outcome:
        guarded = list(receiver.statements)
        if receiver.fall_through:
            incoming = complete_value(
                perform_operation(
                    owner=self.owner,
                    blame=self.blame,
                    receiver=self.incoming_block,
                    method_name="guard_with",
                    operation=ControlFlowGuardOperation(
                        receiver.fall_through,
                        owner=self.owner,
                        blame=self.blame,
                    ),
                    ctx=ctx,
                ),
                owner="finally incoming fallthrough",
            )
            if not isinstance(incoming, BlockValue):
                raise TypeError("finally fallthrough guard must produce BlockValue")
            guarded.extend(incoming.statements)
        return Complete(BlockValue(tuple(guarded)))
