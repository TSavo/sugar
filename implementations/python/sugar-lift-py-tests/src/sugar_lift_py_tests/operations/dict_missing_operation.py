from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class DictMissingOperation:
    key: FloorValue
    owner: str = "DictMissingOperation"
    blame: str = "<unknown>"

    def missing_object(self, receiver, ctx: object) -> Outcome:
        del ctx
        return receiver.call_method_value(
            "__missing__",
            (self.key,),
            owner=self.owner,
            blame=self.blame,
        )
