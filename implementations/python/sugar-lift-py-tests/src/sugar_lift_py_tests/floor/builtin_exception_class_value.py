from __future__ import annotations

from dataclasses import dataclass

from .class_value import ClassValue


@dataclass(frozen=True)
class BuiltinExceptionClassValue(ClassValue):
    """Exact lexical identity for an exception class owned by ``builtins``.

    This is seeded from a static language vocabulary. A same-spelled user binding
    replaces this floor in the temporal scope and therefore cannot inherit builtin
    constructor semantics by leaf-name coincidence.
    """
