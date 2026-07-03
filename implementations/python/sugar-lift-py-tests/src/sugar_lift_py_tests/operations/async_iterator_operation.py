from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, NoReturn

from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import bind_temporal

from .dunder_force import force_dunder_floor_or_runtime_effect
from .object_method_call import call_object_method_value


@dataclass(frozen=True)
class AsyncIteratorOperation:
    method_name: ClassVar[str] = "async_iter_with"
    body: SugarBody
    target_name: str
    owner: str = "AsyncForSugar"
    blame: str = "<unknown>"

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError("AsyncIteratorOperation body must be factory-built")

    def async_iter_object(self, receiver: ObjectValue, ctx) -> Outcome:
        iterator = _force_dunder(
            receiver,
            "__aiter__",
            (),
            ctx,
            owner=f"{self.owner}.__aiter__",
            blame=self.blame,
        )
        if isinstance(iterator, Incomplete):
            return iterator
        from sugar_lift_py_tests.operations.perform_operation import perform_operation

        return perform_operation(
            owner=f"{self.owner}.__aiter__",
            blame=self.blame,
            receiver=iterator,
            operation=AsyncNextOperation(
                body=self.body,
                target_name=self.target_name,
                owner=self.owner,
                blame=self.blame,
            ),
            ctx=ctx,
        )


@dataclass(frozen=True)
class AsyncNextOperation:
    method_name: ClassVar[str] = "async_next_with"
    body: SugarBody
    target_name: str
    owner: str = "AsyncForSugar"
    blame: str = "<unknown>"

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError("AsyncNextOperation body must be factory-built")

    def async_next_object(self, receiver: ObjectValue, ctx) -> Outcome:
        item = _force_dunder(
            receiver,
            "__anext__",
            (),
            ctx,
            owner=f"{self.owner}.__anext__",
            blame=self.blame,
        )
        if isinstance(item, Incomplete):
            return item
        body_ctx = bind_temporal(
            ctx,
            self.target_name,
            item,
            owner=self.owner,
            blame=self.blame,
        )
        body_outcome = self.body.reduce(body_ctx)
        if isinstance(body_outcome, Incomplete):
            return body_outcome
        _raise_stop_floor_gap(self.blame)


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


def _raise_stop_floor_gap(blame: str) -> NoReturn:
    info = FactoryGapInfo(
        owner="AsyncForSugar",
        blame=blame,
        observed="AsyncFor.__anext__",
        requested="async iteration stop floor",
        fix=(
            "add protocol-owned StopAsyncIteration/cardinality floor before "
            "reducing AsyncForSugar as a complete loop"
        ),
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role="async iteration stop floor",
            status="floor-gap",
            observed=info.observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )
