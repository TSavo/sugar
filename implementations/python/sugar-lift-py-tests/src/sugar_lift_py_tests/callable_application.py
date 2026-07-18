from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.floor import FloorValue
    from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class CallableApplication:
    """Apply already-constructed arguments to an already-constructed callable."""

    arguments: tuple["FloorValue", ...]
    keyword_names: tuple[str, ...]
    site: object

    owner: str = "ComputedCallableSugar"

    def apply(
        self, receiver: "FloorValue", ctx: "FactoryBuildContext | None"
    ) -> "Outcome":
        return receiver.callable_application_with(self, ctx)
