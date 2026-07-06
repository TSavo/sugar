from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.effect import FactoryGapEffect
from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome

from .temporal_binding import TemporalBinding


@dataclass(frozen=True)
class TemporalContext:
    bindings: tuple[TemporalBinding, ...] = ()

    @classmethod
    def empty(cls) -> "TemporalContext":
        return cls()

    def value_for(self, name: str) -> FloorValue:
        for binding in reversed(self.bindings):
            if binding.name == name:
                return binding.value
        self._gap(
            owner="TemporalContext",
            blame="<temporal>",
            observed=name,
            requested="value",
            fix=f"bind `{name}` before reducing NameSugar",
        )

    def value_outcome_for(self, name: str) -> Outcome:
        for binding in reversed(self.bindings):
            if binding.name == name:
                return Complete(binding.value)
        return Incomplete(
            FactoryGapEffect(
                owner="TemporalContext",
                blame="<temporal>",
                observed=name,
                requested="value",
                fix=f"bind `{name}` before reducing NameSugar",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )

    def receiver_for(self, name: str) -> FloorValue:
        return self.value_for(name)

    def bind_value(
        self, name: str, value: FloorValue, *, blame: str | None = None
    ) -> "TemporalContext":
        return self._bind_value(name, value, blame=blame)

    def _bind_value(
        self, name: str, value: FloorValue, *, blame: str | None = None
    ) -> "TemporalContext":
        remaining = tuple(binding for binding in self.bindings if binding.name != name)
        return TemporalContext(remaining + (TemporalBinding(name, value, blame),))

    def bind_with(self, operation, ctx):
        return operation.bind_context(self, ctx)

    def curry_with(self, operation, ctx):
        return operation.curry_context(self, ctx)

    def rewrite_with(self, operation, ctx):
        return operation.rewrite_context(self, ctx)

    def _gap(
        self,
        *,
        owner: str,
        blame: str,
        observed: str,
        requested: str,
        fix: str,
    ) -> NoReturn:
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGap,
            FactoryGapInfo,
            GapKind,
            GapLocus,
        )

        info = FactoryGapInfo(
            owner=owner,
            blame=blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role=requested,
                status="floor-gap",
                observed=observed,
                blame=blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
