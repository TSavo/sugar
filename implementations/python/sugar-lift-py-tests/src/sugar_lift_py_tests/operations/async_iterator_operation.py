from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import bind_temporal


@dataclass(frozen=True)
class AsyncIteratorOperation:
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
            method_name="async_next_with",
            operation=self,
            ctx=ctx,
        )

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
        receiver.call_method_value(
            name,
            arguments,
            owner=owner,
            blame=blame,
        ),
        owner=owner,
    )
    try:
        return force_floor(value, ctx, owner=owner)
    except TypeError as exc:
        return Incomplete(
            RuntimeEffect(
                f"{owner} reduced to a runtime effect or opaque callsite: {exc}"
            )
        )


def _raise_stop_floor_gap(blame: str) -> None:
    info = FactoryGapInfo(
        owner="AsyncForSugar",
        blame=blame,
        observed="AsyncFor.__anext__",
        requested="async iteration stop floor",
        fix=(
            "add protocol-owned StopAsyncIteration/cardinality floor before "
            "reducing AsyncForSugar as a complete loop"
        ),
        gap_kind="Floor",
        gap_locus="construction",
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
