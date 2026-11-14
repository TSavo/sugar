from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.floor import FloorValue

from .temporal_binding import TemporalBinding

# A statement's one evaluation is bound under this prefix plus its coordinate
# (``Statement._evaluation_key``). A Python identifier never holds ``:``, so
# an evaluation key can never be read as a source name.
EVALUATION_PREFIX = "evaluation:"


def projection_key(evaluation: str, name: str) -> str:
    """The key of target ``name``'s projection of one statement's evaluation.

    ``a, b = f()`` evaluates ``f()`` once and unpacks it; ``a`` and ``b`` are
    two projections of that one evaluation, each bound under its own key.
    The key keeps the evaluation's prefix, so it is never a source name and
    an ``if`` carries it out of an arm like any other evaluation.
    """
    return f"{evaluation}/{name}"


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

    def value_if_bound(self, name: str) -> FloorValue | None:
        for binding in reversed(self.bindings):
            if binding.name == name:
                return binding.value
        return None

    def latest(self, *names: str) -> TemporalBinding | None:
        """The binding of whichever of ``names`` was bound last, or None."""
        for binding in reversed(self.bindings):
            if binding.name in names:
                return binding
        return None

    def evaluations(self) -> tuple[TemporalBinding, ...]:
        """Every statement evaluation this temporal holds, by its key."""
        return tuple(
            binding
            for binding in self.bindings
            if binding.name.startswith(EVALUATION_PREFIX)
        )

    def bind_value(
        self, name: str, value: FloorValue, *, blame: str | None = None
    ) -> "TemporalContext":
        """The one way a binding enters the temporal: a rebind shadows the old."""
        remaining = tuple(binding for binding in self.bindings if binding.name != name)
        return TemporalContext(remaining + (TemporalBinding(name, value, blame),))

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
