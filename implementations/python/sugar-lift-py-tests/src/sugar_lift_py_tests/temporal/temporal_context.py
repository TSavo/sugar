from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.floor import FloorValue

from .temporal_binding import GuardedTemporalBinding, TemporalBinding


@dataclass(frozen=True)
class TemporalContext:
    bindings: tuple[TemporalBinding, ...] = ()
    guarded_bindings: tuple[GuardedTemporalBinding, ...] = ()

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

    def value_if_bound(self, name: str) -> FloorValue | None:
        for binding in reversed(self.bindings):
            if binding.name == name:
                return binding.value
        return None

    def bind_value(
        self, name: str, value: FloorValue, *, blame: str | None = None
    ) -> "TemporalContext":
        return self._bind_value(name, value, blame=blame)

    def bind_guarded(
        self,
        guard,
        name: str,
        value: FloorValue,
        *,
        blame: str | None = None,
    ) -> "TemporalContext":
        remaining = tuple(
            candidate
            for candidate in self.guarded_bindings
            if not (candidate.guard == guard and candidate.binding.name == name)
        )
        return TemporalContext(
            self.bindings,
            remaining
            + (GuardedTemporalBinding(guard, TemporalBinding(name, value, blame)),),
        )

    def activate_guard(self, guard) -> "TemporalContext":
        """Expose exactly the bindings warranted by this branch condition."""
        active = self
        for candidate in self.guarded_bindings:
            if candidate.guard == guard:
                active = active._bind_value(
                    candidate.binding.name,
                    candidate.binding.value,
                    blame=candidate.binding.blame,
                )
        return active

    def _bind_value(
        self, name: str, value: FloorValue, *, blame: str | None = None
    ) -> "TemporalContext":
        remaining = tuple(binding for binding in self.bindings if binding.name != name)
        guarded = tuple(
            binding for binding in self.guarded_bindings if binding.binding.name != name
        )
        return TemporalContext(
            remaining + (TemporalBinding(name, value, blame),),
            guarded,
        )

    def bind_with(self, operation, ctx):
        return operation.bind_context(self, ctx)

    def curry_with(self, operation, ctx):
        return operation.curry_context(self, ctx)

    def _gap(
        self,
        *,
        owner: str,
        blame: str,
        observed: str,
        requested: str,
        fix: str,
    ) -> NoReturn:
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        info = ConstructionGap(
            owner=owner,
            blame=blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)
