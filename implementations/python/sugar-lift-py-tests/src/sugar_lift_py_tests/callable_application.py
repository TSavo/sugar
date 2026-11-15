from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import FloorValue
    from sugar_lift_py_tests.outcome import ExitSet


@dataclass(frozen=True)
class CallableApplication:
    """Apply already-constructed arguments to an already-constructed callable."""

    arguments: tuple["FloorValue", ...]
    keyword_names: tuple[str, ...]
    site: object

    owner: str = "ComputedCallableSugar"
    call_occurrence: SourceFragmentCoordinateV1 | None = None
    # Exception construction only: the class a ``raise`` authenticated for
    # the callee (``ComputedCallSugar``).  A source class's constructor
    # hands it to the call it binds, so the instance it builds carries it
    # (``ClassDefinitionValue.callable_application_with``); every other
    # callable ignores it.
    exception_type_coordinate: object = None
    exception_type_mro: tuple | None = None
    # ``((name, coordinate cid, value), ...)``: what the call read, at the
    # call, for each enclosing local the called function's body reads
    # (``Call._closure_cells``, ``read_captured_values``).  Python reads a
    # closure cell when the function runs, so the function value applied
    # here binds these under its frame's captured coordinates
    # (``LambdaCallable.callable_application_with``), as a call by name of
    # the function did; never the binding the function was made under.
    # Empty where the call carries none (every callable that is not a
    # function value ignores it).
    captured: tuple = ()

    def __post_init__(self) -> None:
        if (
            self.call_occurrence is not None
            and type(self.call_occurrence) is not SourceFragmentCoordinateV1
        ):
            raise TypeError(
                "CallableApplication.call_occurrence must be SourceFragmentCoordinateV1"
            )

    def apply(self, receiver: "FloorValue", ctx: "ReduceContext | None") -> "ExitSet":
        return receiver.callable_application_with(self, ctx)
