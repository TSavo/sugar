from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.temporal import TemporalContext


@dataclass(frozen=True)
class FactoryBuildContext:
    filename: str
    catalog: SugarCatalog
    temporal: TemporalContext = field(default_factory=TemporalContext.empty)
    source_oracle: Any = None
    expected_role: SugarRole | None = None
    name_resolver: Any = None
    import_aliases: dict[str, str] = field(default_factory=dict)
    from_imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    contract_bindings: list[Any] = field(default_factory=list)
    external_bridge_sink: Any = None
    audit_sink: Any = None
    factory_audit_sink: Any = None
    proof_sink: Any = None
    report_sink: Any = None
    operation_log: list[tuple[str, str, str]] = field(default_factory=list)
    dig_sink: Any = None
    record_operation: Any = None
    # The set of callee names whose body is CURRENTLY being built, up the build stack.
    # CallSugar.build refuses a callee already in this set: eagerly building a recursive
    # universe never terminates, and an infinite recursion is not finitely constructible ->
    # the bridge stays the vendor's axiom rather than hanging the lifter.
    building: frozenset = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.factory_audit_sink is None and self.audit_sink is not None:
            object.__setattr__(self, "factory_audit_sink", self.audit_sink)

    def build_child(self, node, role: SugarRole):
        from sugar_lift_py_tests.factory.build import build_node

        return build_node(
            node,
            filename=self.filename,
            role=role,
            catalog=self.catalog,
            ctx=self,
        )

    def build_body(self, node, role: SugarRole):
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
        )
