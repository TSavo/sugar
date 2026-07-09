from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.temporal import TemporalContext


@dataclass
class ReduceContext:
    temporal: TemporalContext
    source_oracle: Any = None
    proof_sink: Any = None
    report_sink: Any = None
    factory_audit_sink: Any = None
    operation_log: list[tuple[str, str, str]] = field(default_factory=list)
    # The DIG QUEUE. When a bridge emits `call:h(args)`, it appends the actual
    # CallSiteValue here -- a bridge OBLIGATES the dig of the tower it points at.
    # A bridge without its enqueued dig is a dangling uninterpreted symbol, a false
    # discharge. None when no driver is draining (a plain reduce).
    dig_sink: Any = None
    # Optional external-bridge recorder (same field on FactoryBuildContext).
    # CallSugar.ExternalBridgeStrategy reads this during body dig reduce; missing
    # the attribute crashed the numpy/pandas package audit as unstructured exit=2
    # after opaque body dig started reducing vendor-bridged bodies.
    external_bridge_sink: Any = None

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
        cls, source: "FactoryBuildContext | ReduceContext", *, owner: str
    ) -> "ReduceContext":
        """Front door for reduction that carries an existing temporal context."""
        return cls(
            temporal=source.temporal,
            source_oracle=source.source_oracle,
            proof_sink=source.proof_sink,
            report_sink=source.report_sink,
            factory_audit_sink=source.factory_audit_sink,
            operation_log=source.operation_log,
            dig_sink=source.dig_sink,
            external_bridge_sink=getattr(source, "external_bridge_sink", None),
        )

    def record_operation(
        self, *, owner: str, method_name: str, operation: object
    ) -> None:
        self.operation_log.append((owner, method_name, type(operation).__name__))

    def with_temporal(self, temporal: TemporalContext) -> "ReduceContext":
        return ReduceContext(
            temporal=temporal,
            source_oracle=self.source_oracle,
            proof_sink=self.proof_sink,
            report_sink=self.report_sink,
            factory_audit_sink=self.factory_audit_sink,
            operation_log=self.operation_log,
            dig_sink=self.dig_sink,
            external_bridge_sink=self.external_bridge_sink,
        )
