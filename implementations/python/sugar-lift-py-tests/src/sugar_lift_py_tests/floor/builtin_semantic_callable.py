from __future__ import annotations

from dataclasses import dataclass, field

from .closed_operation_witness import (
    ClosedSemanticOperationWitness,
    PythonRuntimeIdentity,
)
from .floor_value import FloorValue


@dataclass(frozen=True)
class BuiltinSemanticCallable(FloorValue):
    operation: str
    runtime_identity: PythonRuntimeIdentity = field(
        default_factory=PythonRuntimeIdentity.current
    )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:builtin_semantic_callable",
            [
                str_const(self.runtime_identity.implementation),
                str_const(
                    f"{self.runtime_identity.major}.{self.runtime_identity.minor}"
                ),
                str_const(self.operation),
            ],
            symbol_kind="builtin",
        )

    def callable_application_with(self, operation, ctx):
        del ctx
        if self.operation == "python.set.construct":
            return self._construct_set(operation)
        if self.operation != "python.issubclass":
            return super().callable_application_with(operation, None)
        if len(operation.arguments) != 2 or operation.keyword_names:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSemanticCallable.python.issubclass",
                blame=str(operation.site),
                observed=(len(operation.arguments), operation.keyword_names),
                requested="exactly two positional authenticated type operands",
                fix="construct Python issubclass arity exactly or keep it loud",
            )
        subtype, supertype = operation.arguments
        return subtype.test_python_subtype(supertype, operation.site)

    def _construct_set(self, operation):
        from sugar_lift_py_tests.floor import DictValue, ListValue, SetValue, TupleValue
        from sugar_lift_py_tests.outcome import Complete

        if operation.keyword_names or len(operation.arguments) > 1:
            return super().callable_application_with(operation, None)
        if not operation.arguments:
            return Complete(SetValue(()))
        source = operation.arguments[0]
        if isinstance(source, DictValue):
            return Complete(SetValue(tuple(key for key, _ in source.entries)))
        if isinstance(source, (ListValue, SetValue, TupleValue)):
            return Complete(SetValue(tuple(source.elements)))
        return super().callable_application_with(operation, None)

    def witness_for(self, operands, result) -> ClosedSemanticOperationWitness:
        return ClosedSemanticOperationWitness.mint(
            self.runtime_identity,
            self.operation,
            tuple(value.to_term(owner=self.operation) for value in operands),
            result.to_term(owner=self.operation),
        )
