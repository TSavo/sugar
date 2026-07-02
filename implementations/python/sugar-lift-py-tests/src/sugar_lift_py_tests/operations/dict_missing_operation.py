from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import FloorValue, ObjectValue
from sugar_lift_py_tests.outcome import Outcome

from .object_method_call import call_object_method_value


@dataclass(frozen=True)
class DictMissingOperation:
    method_name: ClassVar[str] = "missing_with"
    key: FloorValue
    owner: str = "DictMissingOperation"
    blame: str = "<unknown>"

    def missing_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        return call_object_method_value(
            receiver,
            "__missing__",
            (self.key,),
            owner=self.owner,
            blame=self.blame,
        )
