from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class DelItemOperation:
    index: FloorValue
    owner: str = "SubscriptDeleteSugar"
    blame: str = "<unknown>"

    def delitem_object(self, receiver, ctx: object) -> Outcome:
        del ctx
        return receiver.call_method_value(
            "__delitem__",
            (self.index,),
            owner=self.owner,
            blame=self.blame,
        )
