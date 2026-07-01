from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue

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

    def apply_step(self, step: TemporalRewriteStep, *, ctx=None) -> "TemporalContext":
        if step.kind == "add_assign":
            from sugar_lift_py_tests.operations import AddOperation, perform_operation
            from sugar_lift_py_tests.outcome import complete_value

            current = self.value_for(step.name)
            rewritten = complete_value(
                perform_operation(
                    owner="TemporalContext",
                    blame=step.blame,
                    receiver=current,
                    method_name="add_with",
                    operation=AddOperation(
                        operand=step.value,
                        owner="TemporalContext",
                        blame=step.blame,
                    ),
                    ctx=ctx,
                ),
                owner="TemporalContext add_assign",
            )
            return self.bind_value(
                step.name,
                rewritten,
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
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGap,
            FactoryGapInfo,
        )

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
