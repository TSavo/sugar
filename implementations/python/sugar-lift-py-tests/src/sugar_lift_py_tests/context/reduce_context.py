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
    # The DIG QUEUE. When BridgeStrategy.emit emits a bridge `call:h(args)`, it appends
    # `(callee_name, arg_value)` here -- a bridge OBLIGATES the dig of the tower it points at
    # (h now needs a universe). A bridge without its enqueued dig is a dangling uninterpreted
    # symbol, a false discharge. None when no driver is draining (a plain reduce).
    dig_sink: Any = None

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
