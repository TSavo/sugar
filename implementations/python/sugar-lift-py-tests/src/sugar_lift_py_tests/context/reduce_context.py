from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from sugar_lift_py_tests.context.sink_protocols import (
    AuditSink,
    ExternalBridgeSink,
    ProofSink,
)
from sugar_lift_py_tests.temporal import TemporalContext


@dataclass
class ReduceContext:
    temporal: TemporalContext
    module_temporal: TemporalContext | None = None
    source_oracle: Any = None
    proof_sink: ProofSink | None = None
    report_sink: Any = None
    construction_audit_sink: AuditSink | None = None
    # The DIG QUEUE. When a bridge emits `call:h(args)`, it appends the actual
    # CallSiteValue here -- a bridge OBLIGATES the dig of the tower it points at.
    # A bridge without its enqueued dig is a dangling uninterpreted symbol, a false
    # discharge. None when no driver is draining (a plain reduce).
    dig_sink: Any = None
    # Optional external-bridge recorder carried by the reduction context.
    # CallSugar.ExternalBridgeStrategy reads this during body dig reduce; missing
    # the attribute crashed the numpy/pandas package audit as unstructured exit=2
    # after opaque body dig started reducing vendor-bridged bodies.
    external_bridge_sink: ExternalBridgeSink | None = None
    in_flight_effects: tuple[tuple[str, object], ...] = ()
    observed_effects: tuple[tuple[str, object], ...] = ()
    # Ground ifs fold with true_guard/false_guard and no longer publish
    # BranchResultAuthentication (#7487). The assignment phi after the if
    # still reads a BranchResultRef of that slot; record the folded bool
    # here so the phi can drop the dead arm without inventing BRA.to_term.
    ground_branch_results: dict = field(default_factory=dict)
    # Names a live loop body (``LoopRecurrenceSugar``'s per-item recurrence)
    # carries: an assignment to one binds its value under the statement's
    # write of the name (``assigned_value.carried_write_key``), which the
    # next statement and the next item read.
    live_loop_names: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def root(
        cls, *, owner: str, dig_sink=None, external_bridge_sink=None
    ) -> "ReduceContext":
        """Front door for a fresh reduction environment."""
        return cls(
            temporal=TemporalContext.empty(),
            dig_sink=dig_sink,
            external_bridge_sink=external_bridge_sink,
        )

    @classmethod
    def derived(cls, source: "ReduceContext", *, owner: str) -> "ReduceContext":
        """Front door for reduction that carries an existing temporal context."""
        return cls(
            temporal=source.temporal,
            module_temporal=getattr(source, "module_temporal", None),
            source_oracle=source.source_oracle,
            proof_sink=source.proof_sink,
            report_sink=source.report_sink,
            construction_audit_sink=source.construction_audit_sink,
            dig_sink=source.dig_sink,
            external_bridge_sink=getattr(source, "external_bridge_sink", None),
            in_flight_effects=getattr(source, "in_flight_effects", ()),
            observed_effects=getattr(source, "observed_effects", ()),
            ground_branch_results=getattr(source, "ground_branch_results", {}),
            live_loop_names=getattr(source, "live_loop_names", frozenset()),
        )

    def with_temporal(self, temporal: TemporalContext) -> "ReduceContext":
        return replace(self, temporal=temporal)

    def with_in_flight_effect(self, slot_id: str, effect: object) -> "ReduceContext":
        return replace(
            self, in_flight_effects=(*self.in_flight_effects, (slot_id, effect))
        )

    def in_flight_effect_for(self, slot_id: str):
        for candidate_slot, effect in reversed(self.in_flight_effects):
            if candidate_slot == slot_id:
                return effect
        return None

    def with_observed_effect(self, slot_id: str, effect: object) -> "ReduceContext":
        return replace(
            self, observed_effects=(*self.observed_effects, (slot_id, effect))
        )

    def observed_effect_for(self, slot_id: str):
        for candidate_slot, effect in reversed(self.observed_effects):
            if candidate_slot == slot_id:
                return effect
        return None
