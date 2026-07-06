from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class ImportAliasValue(FloorValue):
    """An inert import binding discovered in source.

    `import numpy as np` warrants the local binding `np -> numpy`; it does not
    warrant a predicate by itself. Later sugars may use the binding to resolve a
    symbol before emitting a bridge or digging source.
    """

    name: str
    bound_name: str

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:import_alias", [str_const(self.bound_name), str_const(self.name)]
        )

    def call_method_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape=f"{self.bound_name}.{operation.name}(...)",
            replacement="ImportedModuleCallEffect",
        )

    def subscript_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape=f"{self.bound_name}[...]",
            replacement="ImportedModuleSubscriptEffect",
        )

    def contains_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape="contains membership over imported module binding",
            replacement="ImportedModuleContainsEffect",
        )

    def attribute_assign_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape=f"{self.bound_name}.{operation.name} = ...",
            replacement="ImportedModuleAttributeAssignEffect",
        )

    def binary_operator_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape=f"{self.bound_name} {operation.operator} ...",
            replacement="ImportedModuleBinaryEffect",
        )


def _runtime_alias_effect(
    value: ImportAliasValue,
    *,
    operation: Any,
    shape: str,
    replacement: str,
):
    from sugar_lift_py_tests.effect import RuntimeEffect
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(
        RuntimeEffect(
            "import alias runtime boundary: "
            f"`{shape}` requires evaluating imported module binding "
            f"`{value.bound_name} -> {value.name}` at runtime. "
            "The alias floor records name binding only; it does not fabricate "
            "module object semantics. "
            f"replacement={replacement}; blame={operation.blame}"
        )
    )
