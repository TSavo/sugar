from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome

from .temporal_binding import TemporalBinding


@dataclass(frozen=True)
class TemporalContext:
    bindings: tuple[TemporalBinding, ...] = ()

    @classmethod
    def empty(cls) -> "TemporalContext":
        from .builtin_name_bindings import builtin_name_temporal

        return builtin_name_temporal()

    def value_for(self, name: str, *, blame: str = "<temporal>") -> FloorValue:
        for binding in reversed(self.bindings):
            if binding.name == name:
                return binding.value
        self._gap(
            owner="TemporalContext",
            blame=blame,
            observed=name,
            requested="value",
            fix=f"bind `{name}` before reducing NameSugar",
        )

    def value_outcome_for(self, name: str) -> Outcome:
        for binding in reversed(self.bindings):
            if binding.name == name:
                return Complete(binding.value)
        factory_panic_gap(
            owner="TemporalContext",
            blame="<temporal>",
            observed=name,
            requested="value",
            fix=f"bind `{name}` before reducing NameSugar",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )

    def receiver_for(self, name: str) -> FloorValue:
        return self.value_for(name)

    def value_if_bound(self, name: str) -> FloorValue | None:
        for binding in reversed(self.bindings):
            if binding.name == name:
                return binding.value
        return None

    def bind_value(
        self, name: str, value: FloorValue, *, blame: str | None = None
    ) -> "TemporalContext":
        return self._bind_value(name, value, blame=blame)

    def unbind_names(self, names: tuple[str, ...]) -> "TemporalContext":
        """Return a scope with every deleted name absent.

        Deletion removes bindings instead of installing a sentinel or retaining
        history. A later NameSugar lookup therefore reaches the ordinary loud
        unbound-name floor rather than observing a stale pre-delete value.
        """
        for name in names:
            self.value_for(name)
        deleted = frozenset(names)
        return TemporalContext(
            tuple(binding for binding in self.bindings if binding.name not in deleted)
        )

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
            factory_panic,
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
        factory_panic(
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
