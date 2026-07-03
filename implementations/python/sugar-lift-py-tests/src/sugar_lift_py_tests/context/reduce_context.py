from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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

    @classmethod
    def root(cls, *, owner: str, dig_sink=None) -> "ReduceContext":
        """Front door for a fresh reduction environment."""
        return cls(temporal=TemporalContext.empty(), dig_sink=dig_sink)

    @classmethod
    def derived(cls, source, *, owner: str) -> "ReduceContext":
        """Front door for reduction that carries an existing temporal context."""
        return cls(
            temporal=source.temporal,
            source_oracle=getattr(source, "source_oracle", None),
            proof_sink=getattr(source, "proof_sink", None),
            report_sink=getattr(source, "report_sink", None),
            factory_audit_sink=getattr(
                source, "factory_audit_sink", getattr(source, "audit_sink", None)
            ),
            operation_log=getattr(source, "operation_log", []),
            dig_sink=getattr(source, "dig_sink", None),
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
        )
