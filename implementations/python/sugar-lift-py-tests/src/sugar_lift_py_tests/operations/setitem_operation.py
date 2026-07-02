from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class SetItemOperation:
    index: FloorValue
    value: FloorValue
    owner: str = "SubscriptAssignSugar"
    blame: str = "<unknown>"

    def setitem_object(self, receiver, ctx: object) -> Outcome:
        del ctx
        return receiver.call_method_value(
            "__setitem__",
            (self.index, self.value),
            owner=self.owner,
            blame=self.blame,
        )
