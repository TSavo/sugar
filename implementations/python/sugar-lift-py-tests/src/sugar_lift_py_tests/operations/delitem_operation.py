from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue, ObjectValue
from sugar_lift_py_tests.outcome import Outcome

from .object_method_call import call_object_method_value


@dataclass(frozen=True)
class DelItemOperation:
    index: FloorValue
    owner: str = "SubscriptDeleteSugar"
    blame: str = "<unknown>"

    def delitem_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        return call_object_method_value(receiver,
            "__delitem__",
            (self.index,),
            owner=self.owner,
            blame=self.blame,
        )
