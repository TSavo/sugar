from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue, TermValue

from .temporal_binding import TemporalBinding
from .temporal_rewrite_step import TemporalRewriteStep


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

    def receiver_for(self, name: str) -> FloorValue:
        return self.value_for(name)

    def bind_value(
        self, name: str, value: FloorValue, *, blame: str | None = None
    ) -> "TemporalContext":
        remaining = tuple(binding for binding in self.bindings if binding.name != name)
        return TemporalContext(remaining + (TemporalBinding(name, value, blame),))

    def apply_step(self, step: TemporalRewriteStep) -> "TemporalContext":
        if step.kind == "add_assign":
            current = self.value_for(step.name)
            if not isinstance(current, TermValue) or not isinstance(step.value, TermValue):
                self._gap(
                    owner="TemporalContext",
                    blame=step.blame,
                    observed=f"{type(current).__name__}+={type(step.value).__name__}",
                    requested="TermValue add_assign",
                    fix="add temporal rewrite support for this assignment shape",
                )
            return self.bind_value(
                step.name,
                TermValue(current.value + step.value.value),
                blame=step.blame,
            )
        self._gap(
            owner="TemporalContext",
            blame=step.blame,
            observed=step.kind,
            requested="temporal rewrite",
            fix="add a TemporalRewriteStep handler for this mutation",
        )

    def _gap(
        self,
        *,
        owner: str,
        blame: str,
        observed: str,
        requested: str,
        fix: str,
    ) -> None:
        from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo

        info = FactoryGapInfo(
            owner=owner,
            blame=blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind="Floor",
            gap_locus="construction",
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
