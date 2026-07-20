from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    factory_panic,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import ObjectField, ObjectMethodValue, ObjectValue
from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


@dataclass(frozen=True)
class ConstructorStrategy:
    class_name: str
    fields: tuple[tuple[str, SugarBody], ...]
    parameters: tuple[str, ...] = ()
    arguments: tuple[SugarBody, ...] = ()
    methods: tuple[ObjectMethodValue, ...] = ()
    class_fields: tuple[tuple[str, SugarBody], ...] = ()
    identity: str = ""

    def __post_init__(self) -> None:
        for _name, body in self.fields:
            if not isinstance(body, SugarBody):
                raise TypeError("ConstructorStrategy fields must be factory-built")
        for _name, body in self.class_fields:
            if not isinstance(body, SugarBody):
                raise TypeError(
                    "ConstructorStrategy class fields must be factory-built"
                )
        for argument in self.arguments:
            if not isinstance(argument, SugarBody):
                raise TypeError("ConstructorStrategy arguments must be factory-built")
        for method in self.methods:
            if not isinstance(method, ObjectMethodValue):
                raise TypeError("ConstructorStrategy methods must be factory-built")

    def emit(self, sugar, ctx) -> Outcome:
        del sugar
        arg_values = []
        for argument in self.arguments:
            argument_outcome = argument.reduce(ctx)
            if isinstance(argument_outcome, Incomplete):
                return argument_outcome
            arg_values.append(
                complete_value(
                    argument_outcome,
                    owner=f"{self.class_name} constructor argument",
                )
            )
        field_ctx = (
            _ctx_with_curried_args(ctx, self.parameters, tuple(arg_values))
            if self.parameters or arg_values
            else ctx
        )
        return Complete(
            ObjectValue(
                class_name=self.class_name,
                fields=tuple(
                    self._field(name, body, field_ctx) for name, body in self.fields
                ),
                methods=self.methods,
                class_fields=tuple(
                    self._class_field(name, body, ctx)
                    for name, body in self.class_fields
                ),
                identity=self.identity,
            )
        )

    def _field(self, name: str, body: SugarBody, ctx) -> ObjectField:
        try:
            value = complete_value(
                body.reduce(ctx),
                owner=f"{self.class_name}.{name}",
            )
        except TypeError as exc:
            info = FactoryGapInfo(
                owner="python.factory",
                blame=f"{self.class_name}.{name}",
                observed=type(exc).__name__,
                requested="constructor field floor",
                fix=f"write more constructor floor for `{self.class_name}.{name}`: {exc}",
                gap_kind=GapKind.CONSTRUCTOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
            factory_panic(
                info,
                FactoryAuditRow(
                    role="constructor field floor",
                    status=FactoryAuditStatus.FLOOR_GAP,
                    observed=info.observed,
                    blame=info.blame,
                    selected=None,
                    candidates=[],
                    message=info.message,
                ),
            )
        return ObjectField(name=name, value=value)

    def _class_field(self, name: str, body: SugarBody, ctx) -> ObjectField:
        value = complete_value(
            body.reduce(ctx),
            owner=f"{self.class_name}.{name}",
        )
        if isinstance(value, ObjectValue) and value.has_method("__set_name__"):
            info = FactoryGapInfo(
                owner="python.factory",
                blame=f"{self.class_name}.{name}",
                observed=f"{self.class_name}.{name}",
                requested="class descriptor __set_name__ effect",
                fix=(
                    f"add class-construction descriptor wiring for "
                    f"`{self.class_name}.{name}` or emit an explicit "
                    "__set_name__ effect"
                ),
                gap_kind=GapKind.CONSTRUCTOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
            factory_panic(
                info,
                FactoryAuditRow(
                    role="class descriptor __set_name__ effect",
                    status=FactoryAuditStatus.FLOOR_GAP,
                    observed=info.observed,
                    blame=info.blame,
                    selected=None,
                    candidates=[],
                    message=info.message,
                ),
            )
        return ObjectField(name=name, value=value)


@dataclass(frozen=True)
class SourceBodyConstructorStrategy:
    """Execute a source-backed ``__init__`` and recover its exact self rebind."""

    class_name: str
    body: SugarBody
    parameters: tuple[str, ...]
    arguments: tuple[SugarBody, ...]
    methods: tuple[ObjectMethodValue, ...] = ()
    identity: str = ""
    has_assertion: bool = False

    def emit(self, sugar, ctx) -> Outcome:
        del sugar
        from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.sugar.install_source_dig import (
            ContextualizedDigBody,
        )

        values = []
        for argument in self.arguments:
            outcome = argument.reduce(ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            values.append(
                complete_value(outcome, owner=f"{self.class_name} constructor argument")
            )
        receiver = ObjectValue(
            class_name=self.class_name,
            fields=(),
            methods=self.methods,
            identity=self.identity,
        )
        contextualized = self.body.sugar
        if not isinstance(contextualized, ContextualizedDigBody):
            raise TypeError(
                "SourceBodyConstructorStrategy requires a contextualized source body"
            )
        curried = _ctx_with_curried_args(ctx, self.parameters, (receiver, *values))
        final_ctx, assertions, terminal = contextualized.initializer_scope_after(
            curried
        )
        if terminal is not None:
            return Complete(terminal)
        field_prefix = f"{self.parameters[0]}."
        fields = tuple(
            ObjectField(
                name=binding.name.removeprefix(field_prefix), value=binding.value
            )
            for binding in final_ctx.temporal.bindings
            if binding.name.startswith(field_prefix)
        )
        if not fields and not self.has_assertion:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=self.identity,
                observed=f"{self.class_name} source initializer",
                requested="source-constructed object fields",
                fix=(
                    f"construct the exact `{self.class_name}.__init__` object "
                    "state or leave this initializer loud"
                ),
            )
        value = ObjectValue(
            class_name=self.class_name,
            fields=fields,
            methods=self.methods,
            identity=self.identity,
        )
        if assertions:
            from sugar_lift_py_tests.floor import ExceptionalExitValue, GuardedValue
            from sugar_lift_py_tests.floor.ground_assertion_error import (
                assertion_raise_effect,
            )

            for assertion in reversed(assertions):
                value = GuardedValue(
                    assertion.formula,
                    value,
                    ExceptionalExitValue(assertion_raise_effect(site=assertion.site)),
                )
        return Complete(value)


@dataclass(frozen=True)
class RuntimeConstructorStrategy:
    class_name: str
    arguments: tuple[SugarBody, ...]
    site: SourceFragment
    reason: str
    arity_error: bool = False
    runtime_operand: SugarBody | None = None
    # Set only when the arity mismatch is against a class's own, statically
    # authenticated __init__ signature (see _strategy_from_init) -- the
    # exact expected arity is fully known, so the TypeError is certain
    # regardless of argument values. Inherited/MRO-derived/generated arity
    # gaps (base class resolution, dataclass fields, ...) leave this False
    # and keep panicking loudly until that construction is built out.
    exact_signature: bool = False

    def __post_init__(self) -> None:
        if not all(isinstance(argument, SugarBody) for argument in self.arguments):
            raise TypeError(
                "RuntimeConstructorStrategy arguments must be factory-built"
            )
        if self.runtime_operand is not None and not isinstance(
            self.runtime_operand, SugarBody
        ):
            raise TypeError(
                "RuntimeConstructorStrategy runtime operand must be factory-built"
            )

    def emit(self, sugar, ctx) -> Outcome:
        del sugar
        values = []
        for argument in self.arguments:
            outcome = argument.reduce(ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            values.append(
                complete_value(outcome, owner=f"{self.class_name} constructor argument")
            )
        runtime_operand = None
        if self.runtime_operand is not None:
            runtime_operand = complete_value(
                self.runtime_operand.reduce(ctx),
                owner=f"{self.class_name} runtime constructor selection",
            )

        from sugar_lift_py_tests.effect import (
            ConstructorRuntimeEffect,
            TypeErrorRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.effect.runtime_effect import genuine_runtime_operand
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        call_term = ctor(
            "python:constructor_call",
            [
                str_const(self.class_name),
                *(floor_to_term(value, owner=self.class_name) for value in values),
            ],
        )
        effect_type = (
            TypeErrorRuntimeEffect if self.arity_error else ConstructorRuntimeEffect
        )
        chosen_operand = runtime_operand if runtime_operand is not None else call_term
        if self.arity_error and runtime_operand is None and self.exact_signature:
            # An arity TypeError is certain at every call regardless of the
            # (possibly ground) argument values -- Python decides it before
            # touching any value. The mismatch itself is only known once the
            # call executes against the constructor's real signature, so cite
            # it as a call: coordinate (runtime-by-nature per
            # is_lift_time_decidable) rather than a bare ground constructor
            # term, mirroring NoneValue.subtract's ground-operand door.
            try:
                genuine_runtime_operand("py.constructor", call_term)
            except TypeError:
                chosen_operand = ctor(
                    f"call:{self.class_name}.__init__",
                    [call_term],
                )
        return Incomplete(
            effect_type(
                self.reason,
                **runtime_effect_evidence(
                    "py.constructor",
                    chosen_operand,
                    self.site,
                ),
            )
        )
