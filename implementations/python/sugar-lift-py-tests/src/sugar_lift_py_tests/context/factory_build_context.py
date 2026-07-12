from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.context.sink_protocols import (
    AuditSink,
    ExternalBridgeSink,
    OperationRecorder,
    ProofSink,
)
from sugar_lift_py_tests.temporal import TemporalContext

if TYPE_CHECKING:
    from sugar_lift_py_tests.factory.factory_build_result import FactoryBuildResult
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class FactoryBuildContext:
    filename: str
    catalog: SugarCatalog
    temporal: TemporalContext = field(default_factory=TemporalContext.empty)
    # Module declarations are the lexical floor for every function body. Keep
    # them separate from the live temporal, which may also contain caller
    # locals when a same-module callee body is attached for dig.
    module_temporal: TemporalContext | None = None
    source_oracle: Any = None
    expected_role: SugarRole | None = None
    name_resolver: Any = None
    import_aliases: dict[str, str] = field(default_factory=dict[str, str])
    from_imports: dict[str, tuple[str, str]] = field(
        default_factory=dict[str, tuple[str, str]]
    )
    contract_bindings: list[Any] = field(default_factory=list[Any])
    external_bridge_sink: ExternalBridgeSink | None = None
    audit_sink: AuditSink | None = None
    factory_audit_sink: AuditSink | None = None
    proof_sink: ProofSink | None = None
    report_sink: Any = None
    operation_log: list[tuple[str, str, str]] = field(
        default_factory=list[tuple[str, str, str]]
    )
    dig_sink: Any = None
    record_operation: OperationRecorder | None = None
    # The set of callee names whose body is CURRENTLY being built, up the build stack.
    # CallSugar.build emits a construction-gap effect for a callee already in this
    # set: eagerly building a recursive universe never terminates, and an infinite
    # recursion is not finitely constructible -> the bridge stays the vendor's axiom
    # rather than hanging the lifter.
    building: frozenset[str] = field(default_factory=frozenset[str])
    # Opt-in: when True, a resolved callee whose body cannot open during dig
    # emits symbolic call:f (ExternalBridge) so outer towers can finish.
    # Default False keeps top-level force_floor Incomplete on nested gaps so
    # ambient strip posts stay logo-safe (str.suffixof sorts).
    nested_external_bridge: bool = False

    def __post_init__(self) -> None:
        if self.factory_audit_sink is None and self.audit_sink is not None:
            object.__setattr__(self, "factory_audit_sink", self.audit_sink)

    def build_child(
        self, node: ast.AST | SourceFragment | None, role: SugarRole
    ) -> FactoryBuildResult:
        from sugar_lift_py_tests.factory.build import build_node

        return build_node(
            node,
            filename=self.filename,
            role=role,
            catalog=self.catalog,
            ctx=self,
        )

    def build_body(
        self, node: ast.AST | SourceFragment | None, role: SugarRole
    ) -> "SugarBody[Any]":
        from sugar_lift_py_tests.factory.build import build_node
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment
        from sugar_lift_py_tests.sugar_body import SugarBody

        # Accept a SourceFragment directly (idempotent) or an ast node.
        if isinstance(node, SourceFragment):
            site = node
            result = build_node(
                site,
                filename=self.filename,
                role=role,
                catalog=self.catalog,
                ctx=self,
            )
        else:
            result = self.build_child(node, role)
        return SugarBody(sugar=result.sugar, role=role, audit_row=result.audit_row)

    def with_temporal(self, temporal: TemporalContext) -> "FactoryBuildContext":
        return FactoryBuildContext(
            filename=self.filename,
            catalog=self.catalog,
            temporal=temporal,
            module_temporal=self.module_temporal,
            source_oracle=self.source_oracle,
            expected_role=self.expected_role,
            name_resolver=self.name_resolver,
            import_aliases=self.import_aliases,
            from_imports=self.from_imports,
            contract_bindings=self.contract_bindings,
            external_bridge_sink=self.external_bridge_sink,
            audit_sink=self.audit_sink,
            factory_audit_sink=self.factory_audit_sink,
            proof_sink=self.proof_sink,
            report_sink=self.report_sink,
            operation_log=self.operation_log,
            dig_sink=self.dig_sink,
            record_operation=self.record_operation,
            building=self.building,
            nested_external_bridge=self.nested_external_bridge,
        )
