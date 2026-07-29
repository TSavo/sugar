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
            floored = self._construct_set(operation)
            if floored is not None:
                return floored
            return self._unhandled_construct(operation, "set")
        if self.operation == "python.tuple.construct":
            floored = self._construct_tuple(operation)
            if floored is not None:
                return floored
            return self._unhandled_construct(operation, "tuple")
        if self.operation == "python.isinstance":
            return self._isinstance(operation)
        if self.operation == "python.len":
            return self._len(operation)
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
        subtype = self._resolve_type_operand(subtype, operation.site)
        supertype = self._resolve_type_operand(supertype, operation.site)
        return subtype.test_python_subtype(supertype, operation.site)

    def _unhandled_construct(self, operation, name: str):
        """Opaque construct operands stay a dig cue, not a ConstructionPanic.

        ``tuple(opaque_genexp)`` must remain a CallSiteValue coordinate so later
        force_floor / field projection can refuse with a stage-keyed residual
        rather than aborting the whole manager factory membrane.
        """
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        args = operation.arguments
        owner = str(operation.site)
        return Complete(
            CallSiteValue(
                target_name=name,
                arg_values=args,
                parameters=(),
                term=ctor(
                    f"call:{name}",
                    [value.to_term(owner=owner) for value in args],
                    symbol_kind="builtin",
                ),
                body=None,
                site=operation.site,
            )
        )

    def _len(self, operation):
        """Exact ``len(container)`` over floors that already know their size."""
        if operation.keyword_names or len(operation.arguments) != 1:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSemanticCallable.python.len",
                blame=str(operation.site),
                observed=(len(operation.arguments), operation.keyword_names),
                requested="exactly one positional authenticated len operand",
                fix="construct Python len arity exactly or keep it loud",
            )
        container = operation.arguments[0]
        length = getattr(container, "length", None)
        if not callable(length):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSemanticCallable.python.len",
                blame=str(operation.site),
                observed=type(container).__name__,
                requested="container floor with source-visible length",
                fix="project finite containers before len or keep the call loud",
            )
        return length(operation.site)

    def _isinstance(self, operation):
        """Exact ``isinstance(obj, classinfo)`` over authenticated floors.

        ``classinfo`` is a type coordinate or a finite tuple of them. The type
        owns the test via ``test_python_type``; the object answers through
        ``python_isinstance``. Dual-mode EffectBoundary factories (RaisesExc)
        gate ``expected_exceptions`` on ``isinstance(x, tuple)`` — without this
        arm the condition stays a bodyless CallSiteValue and ``not`` refuses.
        """
        if len(operation.arguments) != 2 or operation.keyword_names:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSemanticCallable.python.isinstance",
                blame=str(operation.site),
                observed=(len(operation.arguments), operation.keyword_names),
                requested="exactly two positional authenticated isinstance operands",
                fix="construct Python isinstance arity exactly or keep it loud",
            )
        obj, classinfo = operation.arguments
        classinfo = self._resolve_type_operand(classinfo, operation.site)
        return classinfo.test_python_type(obj, operation.site)

    def _resolve_type_operand(self, classinfo, site):
        """Map a free builtin type name (SymbolicValue Var) to a type coordinate.

        NameSugar leaves free names as ``SymbolicValue(_Var(name))``. Inside
        source-visible method bodies those free names are language builtins
        (``tuple``, ``type``, ``BaseException``), not call formals. Resolve the
        closed builtin vocabulary to ClassValue / exception floors so
        ``isinstance(x, tuple)`` and ``isinstance(x, type)`` ground.
        """
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import _Var

        if not isinstance(classinfo, SymbolicValue):
            return classinfo
        term = classinfo.term
        if not isinstance(term, _Var):
            return classinfo
        name = term.name
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            BUILTIN_EXCEPTION_NAMES,
            builtin_name_temporal,
        )

        temporal = builtin_name_temporal()
        bound = temporal.value_if_bound(name)
        if bound is not None:
            return bound
        # ``type`` is a ClassValue in the builtin temporal; if missing, keep loud.
        del site
        return classinfo

    def _construct_set(self, operation):
        from sugar_lift_py_tests.floor import DictValue, ListValue, SetValue, TupleValue
        from sugar_lift_py_tests.outcome import Complete

        if operation.keyword_names or len(operation.arguments) > 1:
            return None
        if not operation.arguments:
            return Complete(SetValue(()))
        source = operation.arguments[0]
        if isinstance(source, DictValue):
            return Complete(SetValue(tuple(key for key, _ in source.entries)))
        if isinstance(source, (ListValue, SetValue, TupleValue)):
            return Complete(SetValue(tuple(source.elements)))
        return None

    def _construct_tuple(self, operation):
        """Exact ``tuple(iterable)`` over finite authenticated containers.

        Generator expressions that projected ``finite_elements`` and ordinary
        list/tuple/set floors become ``TupleValue`` here. Opaque iterables stay
        a dig cue (via ``_unhandled_construct``) rather than inventing
        cardinality or panicking the factory membrane.
        """
        from sugar_lift_py_tests.floor import (
            ComprehensionValue,
            DictValue,
            ListValue,
            SetValue,
            TupleValue,
        )
        from sugar_lift_py_tests.outcome import Complete

        if operation.keyword_names or len(operation.arguments) > 1:
            return None
        if not operation.arguments:
            return Complete(TupleValue(()))
        source = operation.arguments[0]
        if isinstance(source, TupleValue):
            return Complete(source)
        if isinstance(source, (ListValue, SetValue)):
            return Complete(TupleValue(tuple(source.elements)))
        if isinstance(source, DictValue):
            return Complete(TupleValue(tuple(key for key, _ in source.entries)))
        if isinstance(source, ComprehensionValue) and source.finite_elements is not None:
            return Complete(TupleValue(tuple(source.finite_elements)))
        if isinstance(source, ComprehensionValue):
            from sugar_lift_py_tests.context_manager_resolution import (
                SourceFragmentCoordinateV1,
            )
            from sugar_lift_py_tests.floor.tuple_coordinate_value import (
                TupleCoordinateValue,
            )

            if type(operation.call_occurrence) is SourceFragmentCoordinateV1:
                return Complete(
                    TupleCoordinateValue._from_builtin_construct(
                        source=source,
                        call_occurrence=operation.call_occurrence,
                        runtime=self.runtime_identity,
                    )
                )
        return None

    def test_python_type(self, value, site):
        """Constructor builtins that are also types answer isinstance tests.

        ``tuple`` / ``set`` are both callables and type objects. Binding them as
        construct callables must not lose ``isinstance(x, tuple)`` — RaisesExc
        gates on that exact condition.
        """
        type_name = {
            "python.tuple.construct": "tuple",
            "python.set.construct": "set",
        }.get(self.operation)
        if type_name is None:
            return super().test_python_type(value, site)
        from sugar_lift_py_tests.ir import ctor, str_const

        return value.python_isinstance(
            type_name,
            ctor("python:type", [str_const(type_name)]),
            site,
        )

    def witness_for(self, operands, result) -> ClosedSemanticOperationWitness:
        return ClosedSemanticOperationWitness.mint(
            self.runtime_identity,
            self.operation,
            tuple(value.to_term(owner=self.operation) for value in operands),
            result.to_term(owner=self.operation),
        )
