from __future__ import annotations

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
    # Names declared ``global`` in the function currently being reduced. This
    # routes later stores through the statically known module frame.
    global_names: frozenset[str] = field(default_factory=frozenset[str])
    # Names declared ``nonlocal`` in the function currently being reduced.
    # Reads use the captured lexical temporal. Stores remain a loud
    # NonlocalRoute gap until cross-frame mutation is constructed.
    nonlocal_names: frozenset[str] = field(default_factory=frozenset[str])
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
    construction_audit_sink: AuditSink | None = None
    proof_sink: ProofSink | None = None
    report_sink: Any = None
    operation_log: list[tuple[str, str, str]] = field(
        default_factory=list[tuple[str, str, str]]
    )
    # Module-name reads that recompose a definition are assertion-local rewrite
    # testimony. EqualitySugar consumes this ledger into ProofIR provenance.
    module_rewrite_log: list[Any] = field(default_factory=list[Any])
    prefer_ground_module_bindings: bool = False
    # Executing a module-level ``def`` must construct decorators/defaults now,
    # but its body is demanded only by a later call. The module seed opts into
    # carrying those body statements to SequentialDigBody without recursively
    # factory-building every descendant.
    defer_function_body_construction: bool = False
    dig_sink: Any = None
    record_operation: OperationRecorder | None = None
    # The set of callee names whose body is CURRENTLY being built, up the build stack.
    # A callee already in this set hits the install-source cycle guard: eagerly
    # building a recursive universe never terminates, so the missing finite
    # recursive coordinate stays a typed loud ConstructionPanic rather than opacity.
    building: frozenset[str] = field(default_factory=frozenset[str])
    # Opt-in: when True, a resolved callee whose body cannot open during dig
    # emits symbolic call:f (ExternalBridge) so outer towers can finish.
    # Default False keeps top-level force_floor Incomplete on nested gaps so
    # ambient strip posts stay logo-safe (str.suffixof sorts).
    nested_external_bridge: bool = False
    in_flight_effects: tuple[tuple[str, object], ...] = ()
    # Same observed-effect slot surface as ReduceContext — except* as-binding
    # and EffectRef projection share one typed operation, not a ladder of
    # implementation kinds.
    observed_effects: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.construction_audit_sink is None and self.audit_sink is not None:
            object.__setattr__(self, "construction_audit_sink", self.audit_sink)

    def with_temporal(self, temporal: TemporalContext) -> "FactoryBuildContext":
        return FactoryBuildContext(
            filename=self.filename,
            catalog=self.catalog,
            temporal=temporal,
            module_temporal=self.module_temporal,
            global_names=self.global_names,
            nonlocal_names=self.nonlocal_names,
            source_oracle=self.source_oracle,
            expected_role=self.expected_role,
            name_resolver=self.name_resolver,
            import_aliases=self.import_aliases,
            from_imports=self.from_imports,
            contract_bindings=self.contract_bindings,
            external_bridge_sink=self.external_bridge_sink,
            audit_sink=self.audit_sink,
            construction_audit_sink=self.construction_audit_sink,
            proof_sink=self.proof_sink,
            report_sink=self.report_sink,
            operation_log=self.operation_log,
            module_rewrite_log=self.module_rewrite_log,
            prefer_ground_module_bindings=self.prefer_ground_module_bindings,
            defer_function_body_construction=self.defer_function_body_construction,
            dig_sink=self.dig_sink,
            record_operation=self.record_operation,
            building=self.building,
            nested_external_bridge=self.nested_external_bridge,
            in_flight_effects=self.in_flight_effects,
            observed_effects=self.observed_effects,
        )

    def with_in_flight_effect(
        self, slot_id: str, effect: object
    ) -> "FactoryBuildContext":
        from dataclasses import replace

        return replace(
            self,
            in_flight_effects=(*self.in_flight_effects, (slot_id, effect)),
        )

    def in_flight_effect_for(self, slot_id: str):
        for candidate_slot, effect in reversed(self.in_flight_effects):
            if candidate_slot == slot_id:
                return effect
        return None

    def with_observed_effect(
        self, slot_id: str, effect: object
    ) -> "FactoryBuildContext":
        """Shared typed surface with ReduceContext — except* as-binding."""
        from dataclasses import replace

        return replace(
            self,
            observed_effects=(*self.observed_effects, (slot_id, effect)),
        )

    def observed_effect_for(self, slot_id: str):
        for candidate_slot, effect in reversed(self.observed_effects):
            if candidate_slot == slot_id:
                return effect
        return None
