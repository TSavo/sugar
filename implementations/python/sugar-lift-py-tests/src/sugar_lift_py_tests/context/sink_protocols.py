from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sugar_lift_py_tests.operations.floor_operation import FloorOperation

__all__ = [
    "AuditSink",
    "ProofSink",
    "ExternalBridgeSink",
    "OperationRecorder",
]


@runtime_checkable
class AuditSink(Protocol):
    """The audit-row carrier: `factory.build` appends one row per selection.

    `audit_sink` and `factory_audit_sink` on `FactoryBuildContext`, and
    `factory_audit_sink` on `ReduceContext`, are all this shape: a list-like
    collector, never read back by the lifter. Callers append `FactoryAuditDto`
    TypedDicts, plain dicts, or (pre-`.to_json()`) `FactoryAuditRow` values
    depending on call site, so the row stays `Any`: the typed edge this
    protocol pins is "is a collector", not the exact row shape.
    """

    def append(self, row: Any, /) -> None: ...


@runtime_checkable
class ProofSink(Protocol):
    """The proof-row carrier threaded alongside the audit sink for discharge rows."""

    def append(self, row: Any, /) -> None: ...


@runtime_checkable
class ExternalBridgeSink(Protocol):
    """The bridge-obligation carrier: one row per `call:f(args)` bridge emitted."""

    def append(self, row: Any, /) -> None: ...


@runtime_checkable
class OperationRecorder(Protocol):
    """The dispatch-recorder edge: `perform_operation` calls this before dispatch."""

    def __call__(
        self, *, owner: str, method_name: str, operation: "FloorOperation"
    ) -> None: ...
