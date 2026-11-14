from __future__ import annotations

from dataclasses import dataclass

from .bound_method_value import BoundMethodValue
from .floor_value import FloorValue


@dataclass(frozen=True)
class BuiltinSuperMethodValue(BoundMethodValue):
    """One selected method on an authenticated zero-argument ``super``."""


@dataclass(frozen=True)
class BuiltinSuperValue(FloorValue):
    """Authenticated zero-argument ``super()`` language receiver."""

    current_class: object
    receiver: object

    def attribute(self, name, site, ctx):
        del site, ctx
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(BuiltinSuperMethodValue(self, name))

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
        del owner
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
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_type_class,
        )

        # The builtin ``type`` by the object the builtin namespace binds,
        # never a base that merely spells ``type``.
        if name == "__new__" and base is builtin_type_class():
            return self._type_new(arguments, keywords, blame)
        from sugar_lift_py_tests.floor.builtin_dict_class_value import (
            BuiltinDictClassValue,
        )
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

        if (
            name == "__init__"
            and isinstance(base, BuiltinDictClassValue)
            and not arguments
            and not keywords
        ):
            return ExitSet.completed(NoneValue())
        if (
            name != "__init__"
            and isinstance(base, BuiltinDictClassValue)
            and not keywords
        ):
            answered = self._dict_base_call(name, arguments, blame, ctx)
            if answered is not None:
                return answered
        from sugar_lift_py_tests.floor.builtin_exception_class_value import (
            BuiltinExceptionClassValue,
        )
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )

        if name == "__init__" and isinstance(base, BuiltinExceptionClassValue):
            # Zero-arg super into a builtin exception base: its ``__init__``
            # is BaseException's law on the original instance receiver.
            return base.initialize_instance(
                self.receiver,
                arguments,
                keywords,
                blame=blame,
                owner="BuiltinSuperValue.call_method_value",
            )
        if isinstance(base, ClassDefinitionValue):
            # Zero-arg super into a source-defined next class: run the selected
            # base method on the original instance receiver.  The base body
            # reduces with __class__ seeded to its defining class, so a further
            # super() inside it selects the class after the base.
            return base.dispatch_super_method(
                self.receiver,
                name,
                arguments,
                owner="BuiltinSuperValue.call_method_value",
                blame=blame,
                ctx=ctx,
                keywords=keywords,
            )
        construction_panic_gap(
            owner="BuiltinSuperValue.call_method_value",
            blame=blame,
            observed=f"{type(base).__name__}.{name}",
            requested="authenticated selected-base method semantics",
            fix="model the selected base method or keep it loud",
        )

    def _dict_base_call(self, name, arguments, blame, ctx):
        """``super().<name>(...)`` that selects ``dict``: dict's own method
        on the receiver's base storage, through the mapping's one door per
        operation (``MappingObjectValue.dict_base_call``) -- the door a call
        the MRO resolves to ``dict`` takes.  A mutation (``__setitem__``,
        ``__delitem__``) is the receiver's transition with dict's ``None``
        result kept apart (``ReceiverOwnedMutationResult``), which the source
        override's store reads back.  None when dict's ``name`` at this arity
        is not one of those doors."""
        from sugar_lift_py_tests.floor.mapping_object_value import (
            MappingObjectValue,
        )
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
            ReceiverOwnedMutationResult,
        )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

        if not isinstance(self.receiver, MappingObjectValue):
            construction_panic_gap(
                owner="BuiltinSuperValue.call_method_value",
                blame=blame,
                observed=type(self.receiver).__name__,
                requested=f"authenticated mapping receiver for dict.{name}",
                fix="preserve the source method receiver through zero-arg super",
            )
        answered = self.receiver.dict_base_call(name, arguments, blame, ctx)
        if answered is None or name not in ("__setitem__", "__delitem__"):
            return answered
        return answered.and_then(
            lambda updated: ExitSet.completed(
                ReceiverOwnedMutationResult(self.receiver, updated, NoneValue())
            )
        )

    def _type_new(self, arguments, keywords, blame):
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue
        from sugar_lift_py_tests.floor.runtime_class_value import RuntimeClassValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

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
        return ExitSet.completed(
            RuntimeClassValue(
                name=name.value,
                bases=tuple(bases.elements),
                record=namespace,
                namespace=namespace,
            )
        )
