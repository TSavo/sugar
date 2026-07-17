from __future__ import annotations

from dataclasses import dataclass

from .class_value import ClassValue


@dataclass(frozen=True)
class LocalExceptionClassValue(ClassValue):
    """Source-proven local class with exact exception ancestry."""


def module_class_value(*, name: str, base_names: tuple[str, ...], temporal, record):
    """Seed a module class without losing exact exception ancestry."""
    from .builtin_exception_class_value import BuiltinExceptionClassValue
    from .exception_class_value import ExceptionClassValue
    from .import_alias_value import ImportAliasValue

    for base_name in base_names:
        bound = temporal.value_if_bound(base_name)
        if type(bound) in (
            BuiltinExceptionClassValue,
            ExceptionClassValue,
            LocalExceptionClassValue,
        ) or (
            isinstance(bound, ImportAliasValue)
            and isinstance(bound.resolved_value, ExceptionClassValue)
        ):
            return LocalExceptionClassValue(name=name, bases=(), record=record)
    return ClassValue(name=name, bases=(), record=record)
