from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import BuilderState
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class MaterializeOperation:
    method_name: ClassVar[str] = "materialize_with"
    owner: str = "ToListSugar"
    blame: str = "<unknown>"

    def materialize_builder(self, receiver: BuilderState, ctx: object) -> Outcome:
        del ctx
        return Complete(receiver.current)
