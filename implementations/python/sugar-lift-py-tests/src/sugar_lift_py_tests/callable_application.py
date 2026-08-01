from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import FloorValue
    from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class CallableApplication:
    """Apply already-constructed arguments to an already-constructed callable."""

    arguments: tuple["FloorValue", ...]
    keyword_names: tuple[str, ...]
    site: object

    owner: str = "ComputedCallableSugar"
    call_occurrence: SourceFragmentCoordinateV1 | None = None

    def __post_init__(self) -> None:
        if (
            self.call_occurrence is not None
            and type(self.call_occurrence) is not SourceFragmentCoordinateV1
        ):
            raise TypeError(
                "CallableApplication.call_occurrence must be SourceFragmentCoordinateV1"
            )

    def apply(self, receiver: "FloorValue", ctx: "ReduceContext | None") -> "Outcome":
        return receiver.callable_application_with(self, ctx)
