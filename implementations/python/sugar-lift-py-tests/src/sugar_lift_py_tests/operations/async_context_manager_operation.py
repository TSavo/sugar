from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from sugar_lift_py_tests.floor import ObjectValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import bind_temporal

from .dunder_force import force_dunder_floor_or_runtime_effect
from .object_method_call import call_object_method_value

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext


@dataclass(frozen=True)
class AsyncContextManagerOperation:
    method_name: ClassVar[str] = "async_context_manager_with"
    body: SugarBody
    optional_name: str | None = None
    owner: str = "AsyncWithSugar"
    blame: str = "<unknown>"

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError("AsyncContextManagerOperation body must be factory-built")

    def async_context_object(
        self, receiver: ObjectValue, ctx: FactoryBuildContext | None
    ) -> Outcome:
        entered = _force_dunder(
            receiver,
            "__aenter__",
            (),
            ctx,
            owner=f"{self.owner}.__aenter__",
            blame=self.blame,
        )
        if isinstance(entered, Incomplete):
            return entered
        body_ctx = ctx
        if self.optional_name is not None:
            body_ctx = bind_temporal(
                ctx,
                self.optional_name,
                entered,
                owner=self.owner,
                blame=self.blame,
            )
        body_outcome = self.body.reduce(body_ctx)
        if isinstance(body_outcome, Incomplete):
            return body_outcome
        exited = _force_dunder(
            receiver,
            "__aexit__",
            (_none_value(), _none_value(), _none_value()),
            body_ctx,
            owner=f"{self.owner}.__aexit__",
            blame=self.blame,
        )
        if isinstance(exited, Incomplete):
            return exited
        return body_outcome


def _force_dunder(
    receiver: ObjectValue,
    name: str,
    arguments: tuple,
    ctx,
    *,
    owner: str,
    blame: str,
):
    value = complete_value(
        call_object_method_value(
            receiver,
            name,
            arguments,
            owner=owner,
            blame=blame,
        ),
        owner=owner,
    )
    return force_dunder_floor_or_runtime_effect(
        value,
        ctx,
        owner=owner,
        project_callsite=False,
    )


def _none_value() -> SymbolicValue:
    return SymbolicValue(ctor("None", []))
