from __future__ import annotations

from dataclasses import dataclass, replace

from .class_value import ClassValue


@dataclass(frozen=True)
class RuntimeClassValue(ClassValue):
    """Class object minted by authenticated ``type.__new__`` arguments."""

    namespace: object = None

    def __post_init__(self) -> None:
        # ``type.__new__`` mints both fields from one authenticated namespace
        # actual.  Equal content at another coordinate is not the same class
        # construction and may not be substituted afterward.
        if self.record is not self.namespace:
            raise TypeError(
                "RuntimeClassValue record and namespace must be the identical "
                "authenticated type.__new__ actual"
            )

    def _namespace_entries(self):
        if hasattr(self.namespace, "mapping_entries"):
            return self.namespace.mapping_entries()
        return self.namespace.entries

    def attribute(self, name, site):
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import Complete

        if name == "__dict__":
            return Complete(self.namespace)
        if name == "__mro__":
            return Complete(TupleValue((self, *self.bases)))
        for key, value in reversed(self._namespace_entries()):
            if getattr(key, "value", object()) == name:
                return Complete(value)
        # ``type.__new__`` retained the exact source base values.  Ask only
        # those source definitions for their constructed C3 member; an opaque
        # or builtin base does not gain a speculative lookup arm here.
        for base in self.bases:
            if isinstance(base, ClassDefinitionValue):
                inherited = base.class_member_value(name)
                if inherited is not None:
                    return Complete(inherited)
        return super().attribute(name, site)

    def with_field_store(self, name, value):
        """Return this runtime class after one source-visible class store."""
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue
        from sugar_lift_py_tests.floor.string_value import StringValue

        key = StringValue(name)
        entries = tuple(
            (candidate, existing)
            for candidate, existing in self._namespace_entries()
            if not (
                isinstance(candidate, StringValue) and candidate.value == name
            )
        )
        entries = (*entries, (key, value))
        if isinstance(self.namespace, MappingObjectValue):
            namespace = self.namespace.mapping_with_entries(entries)
        elif isinstance(self.namespace, DictValue):
            namespace = DictValue(entries)
        else:
            raise TypeError(
                "RuntimeClassValue namespace must retain its authenticated mapping floor"
            )
        return replace(self, record=namespace, namespace=namespace)
