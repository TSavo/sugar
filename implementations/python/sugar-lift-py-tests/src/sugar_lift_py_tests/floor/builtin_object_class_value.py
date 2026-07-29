from __future__ import annotations

from dataclasses import dataclass

from .class_value import ClassValue


@dataclass(frozen=True)
class BuiltinObjectClassValue(ClassValue):
    """Language-owned ``object`` class with its closed callable member floor."""

    def attribute(self, name, site):
        if name == "__str__":
            from sugar_lift_py_tests.floor.builtin_semantic_callable import (
                BuiltinSemanticCallable,
            )
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                BuiltinSemanticCallable(operation="python.object.__str__")
            )
        return super().attribute(name, site)
