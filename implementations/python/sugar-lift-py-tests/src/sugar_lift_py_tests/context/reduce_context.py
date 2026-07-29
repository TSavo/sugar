from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
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
    global_names: frozenset[str] = field(default_factory=frozenset)
    nonlocal_names: frozenset[str] = field(default_factory=frozenset)
    source_oracle: Any = None
    proof_sink: ProofSink | None = None
    report_sink: Any = None
    construction_audit_sink: AuditSink | None = None
    operation_log: list[tuple[str, str, str]] = field(default_factory=list)
    module_rewrite_log: list[Any] = field(default_factory=list)
    prefer_ground_module_bindings: bool = False
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
    def derived(
        cls, source: "ReduceContext", *, owner: str
    ) -> "ReduceContext":
        """Front door for reduction that carries an existing temporal context."""
        return cls(
            temporal=source.temporal,
            module_temporal=getattr(source, "module_temporal", None),
            global_names=getattr(source, "global_names", frozenset()),
            nonlocal_names=getattr(source, "nonlocal_names", frozenset()),
            source_oracle=source.source_oracle,
            proof_sink=source.proof_sink,
            report_sink=source.report_sink,
            construction_audit_sink=source.construction_audit_sink,
            operation_log=source.operation_log,
            module_rewrite_log=getattr(source, "module_rewrite_log", []),
            prefer_ground_module_bindings=getattr(
                source, "prefer_ground_module_bindings", False
            ),
            dig_sink=source.dig_sink,
            external_bridge_sink=getattr(source, "external_bridge_sink", None),
            in_flight_effects=getattr(source, "in_flight_effects", ()),
            observed_effects=getattr(source, "observed_effects", ()),
        )

    def record_operation(
        self, *, owner: str, method_name: str, operation: object
    ) -> None:
        operation_name = type(operation).__name__
        self.operation_log.append((owner, method_name, operation_name))
        logging.getLogger("sugar_lift_py_tests.engine").debug(
            json.dumps(
                {
                    "schema": "sugar.engine.log.v1",
                    "event": "operation",
                    "owner": owner,
                    "method": method_name,
                    "operation": operation_name,
                    "operation_sequence": len(self.operation_log),
                },
                sort_keys=True,
            )
        )

    def with_temporal(self, temporal: TemporalContext) -> "ReduceContext":
        return ReduceContext(
            temporal=temporal,
            module_temporal=self.module_temporal,
            global_names=self.global_names,
            nonlocal_names=self.nonlocal_names,
            source_oracle=self.source_oracle,
            proof_sink=self.proof_sink,
            report_sink=self.report_sink,
            construction_audit_sink=self.construction_audit_sink,
            operation_log=self.operation_log,
            module_rewrite_log=self.module_rewrite_log,
            prefer_ground_module_bindings=self.prefer_ground_module_bindings,
            dig_sink=self.dig_sink,
            external_bridge_sink=self.external_bridge_sink,
            in_flight_effects=self.in_flight_effects,
            observed_effects=self.observed_effects,
        )

    def with_in_flight_effect(self, slot_id: str, effect: object) -> "ReduceContext":
        return ReduceContext(
            temporal=self.temporal,
            module_temporal=self.module_temporal,
            global_names=self.global_names,
            nonlocal_names=self.nonlocal_names,
            source_oracle=self.source_oracle,
            proof_sink=self.proof_sink,
            report_sink=self.report_sink,
            construction_audit_sink=self.construction_audit_sink,
            operation_log=self.operation_log,
            module_rewrite_log=self.module_rewrite_log,
            prefer_ground_module_bindings=self.prefer_ground_module_bindings,
            dig_sink=self.dig_sink,
            external_bridge_sink=self.external_bridge_sink,
            in_flight_effects=(*self.in_flight_effects, (slot_id, effect)),
            observed_effects=self.observed_effects,
        )

    def in_flight_effect_for(self, slot_id: str):
        for candidate_slot, effect in reversed(self.in_flight_effects):
            if candidate_slot == slot_id:
                return effect
        return None

    def with_observed_effect(self, slot_id: str, effect: object) -> "ReduceContext":
        from dataclasses import replace

        return replace(
            self, observed_effects=(*self.observed_effects, (slot_id, effect))
        )

    def observed_effect_for(self, slot_id: str):
        for candidate_slot, effect in reversed(self.observed_effects):
            if candidate_slot == slot_id:
                return effect
        return None
