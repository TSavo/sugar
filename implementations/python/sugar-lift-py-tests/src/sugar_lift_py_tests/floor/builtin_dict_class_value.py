from __future__ import annotations

from dataclasses import dataclass

from .builtin_semantic_callable import BuiltinSemanticCallable


@dataclass(frozen=True)
class BuiltinDictClassValue(BuiltinSemanticCallable):
    """Authenticated builtin ``dict`` class and constructor coordinate.

    This keeps the existing closed constructor law while giving source-class
    base transport a typed capability.  Consumers do not infer it from the
    spelling of a base expression.
    """
