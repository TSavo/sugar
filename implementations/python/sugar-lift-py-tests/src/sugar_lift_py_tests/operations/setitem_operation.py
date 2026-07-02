from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import FloorValue, ObjectValue
from sugar_lift_py_tests.outcome import Outcome

from .object_method_call import call_object_method_value


@dataclass(frozen=True)
class SetItemOperation:
    method_name: ClassVar[str] = "setitem_with"
    index: FloorValue
    value: FloorValue
    owner: str = "SubscriptAssignSugar"
    blame: str = "<unknown>"

    def setitem_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        return call_object_method_value(
            receiver,
            "__setitem__",
            (self.index, self.value),
            owner=self.owner,
            blame=self.blame,
        )
