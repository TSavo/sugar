from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BuiltinSuperMethodValue(FloorValue):
    """One selected method on an authenticated zero-argument ``super``."""

    receiver: object
    name: str

    def callable_application_with(self, operation, ctx):
        keyword_count = len(operation.keyword_names)
        positional = (
            operation.arguments[:-keyword_count]
            if keyword_count
            else operation.arguments
        )
        keywords = (
            tuple(zip(operation.keyword_names, operation.arguments[-keyword_count:]))
            if keyword_count
            else ()
        )
        return self.receiver.call_method_value(
            self.name,
            positional,
            owner="BuiltinSuperMethodValue",
            blame=operation.site,
            ctx=ctx,
            keywords=keywords,
        )


@dataclass(frozen=True)
class BuiltinSuperValue(FloorValue):
    """Authenticated zero-argument ``super()`` language receiver."""

    current_class: object
    receiver: object

    def attribute(self, name, site):
        del site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(BuiltinSuperMethodValue(self, name))

    def call_method_value(
        self,
        name,
        arguments,
        *,
        owner,
        blame,
        ctx=None,
        keywords=(),
        required_frame=None,
    ):
        del owner, ctx
        if required_frame is not None:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSuperValue.call_method_value",
                blame=blame,
                observed=name,
                requested="authenticated builtin super method",
                fix="model the selected base method or keep it loud",
            )
        bases = getattr(self.current_class, "base_classes", ())
        if len(bases) != 1:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSuperValue.call_method_value",
                blame=blame,
                observed=f"{len(bases)} direct bases",
                requested="one authenticated next class in the MRO",
                fix="construct C3 super selection before dispatching this method",
            )
        base = bases[0]
        if name == "__new__" and getattr(base, "name", None) == "type":
            return self._type_new(arguments, keywords, blame)
        from sugar_lift_py_tests.floor.builtin_dict_class_value import (
            BuiltinDictClassValue,
        )
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import Complete

        if (
            name == "__init__"
            and isinstance(base, BuiltinDictClassValue)
            and not arguments
            and not keywords
        ):
            return Complete(NoneValue())
        if (
            name == "__setitem__"
            and isinstance(base, BuiltinDictClassValue)
            and len(arguments) == 2
            and not keywords
        ):
            from sugar_lift_py_tests.floor.mapping_object_value import (
                MappingObjectValue,
            )
            from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
                ReceiverOwnedMutationResult,
            )

            if not isinstance(self.receiver, MappingObjectValue):
                construction_panic_gap(
                    owner="BuiltinSuperValue.call_method_value",
                    blame=blame,
                    observed=type(self.receiver).__name__,
                    requested="authenticated mapping receiver for dict.__setitem__",
                    fix="preserve the source method receiver through zero-arg super",
                )
            key, value = arguments
            return self.receiver.mapping_builtin_setitem(key, value, blame).and_then(
                lambda updated: Complete(
                    ReceiverOwnedMutationResult(
                        self.receiver, updated, NoneValue()
                    )
                )
            )
        construction_panic_gap(
            owner="BuiltinSuperValue.call_method_value",
            blame=blame,
            observed=f"{type(base).__name__}.{name}",
            requested="authenticated selected-base method semantics",
            fix="model the selected base method or keep it loud",
        )

    def _type_new(self, arguments, keywords, blame):
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue
        from sugar_lift_py_tests.floor.runtime_class_value import RuntimeClassValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import Complete

        if len(arguments) != 4:
            construction_panic_gap(
                owner="BuiltinSuperValue.type.__new__",
                blame=blame,
                observed=f"arity={len(arguments)}",
                requested="metaclass, class name, bases, and namespace",
                fix="retain exact type.__new__ operands or keep the call loud",
            )
        _metaclass, name, bases, namespace = arguments
        if (
            not isinstance(name, StringValue)
            or not isinstance(bases, TupleValue)
            or not isinstance(namespace, (DictValue, MappingObjectValue))
        ):
            construction_panic_gap(
                owner="BuiltinSuperValue.type.__new__",
                blame=blame,
                observed=tuple(type(value).__name__ for value in arguments),
                requested="authenticated class name, bases, and mapping namespace",
                fix="transport metaclass __new__ actuals without symbolic projection",
            )
        # ``**kwds`` is evaluated and authenticated by MethodCallSugar.  It does
        # not alter the namespace identity represented by this Floor.
        del keywords
        return Complete(
            RuntimeClassValue(
                name=name.value,
                bases=tuple(bases.elements),
                record=namespace,
                namespace=namespace,
            )
        )
