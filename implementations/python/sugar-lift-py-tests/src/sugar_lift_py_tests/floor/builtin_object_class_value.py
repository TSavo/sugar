from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .class_value import ClassValue


@dataclass(frozen=True)
class BuiltinObjectClassValue(ClassValue):
    """Language-owned ``object`` class with its closed callable member floor."""

    _CALLABLE_MEMBERS: ClassVar[frozenset[str]] = frozenset(
        {
            "__format__",
            "__new__",
            "__reduce_ex__",
            "__repr__",
            "__str__",
        }
    )

    def attribute(self, name, site):
        if name in self._CALLABLE_MEMBERS:
            from sugar_lift_py_tests.floor.builtin_semantic_callable import (
                BuiltinSemanticCallable,
            )
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                BuiltinSemanticCallable(operation=f"python.object.{name}")
            )
        return super().attribute(name, site)
