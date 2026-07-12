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

    def extend_scope(self, ctx):
        """Thread the source-stated import binding into following statements."""
        return ctx.with_temporal(ctx.temporal.bind_value(self.bound_name, self))

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:import_alias", [str_const(self.bound_name), str_const(self.name)]
        )

    def test_python_type(self, value, site):
        from sugar_lift_py_tests.floor.type_tester import native_type_tester
        from sugar_lift_py_tests.ir import ctor, str_const

        return native_type_tester(
            value,
            ctor("python:type", [str_const(self.name)]),
            site,
        )

    def truth(self, site):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import Complete

        return Complete(PredicateValue(py_truthy(self.to_term(owner="truth")), site))

    def subscript(self, index, site):
        return self.py_subscript_coordinate(index, site)

    def guarded(self, formula):
        del formula
        return self

    def add(self, other, site):
        return self._binary_runtime_effect(other, site, "+")

    def subtract(self, other, site):
        return self._binary_runtime_effect(other, site, "-")

    def multiply(self, other, site):
        return self._binary_runtime_effect(other, site, "*")

    def divide(self, other, site):
        return self._binary_runtime_effect(other, site, "/")

    def power(self, other, site):
        return self._binary_runtime_effect(other, site, "**")

    def bitwise_and(self, other, site):
        return self._binary_runtime_effect(other, site, "&")

    def bitwise_xor(self, other, site):
        return self._binary_runtime_effect(other, site, "^")

    def unary_minus(self, site):
        return self._unary_runtime_effect(site, "-")

    def unary_plus(self, site):
        return self._unary_runtime_effect(site, "+")

    def bitwise_invert(self, site):
        return self._unary_runtime_effect(site, "~")

    def format_data_model(self, spec, site, ctx):
        del spec, ctx
        return _runtime_alias_effect_at_site(
            self,
            shape=f"format({self.bound_name}, ...)",
            blame=str(site),
            replacement="ImportedModuleFormatEffect",
        )

    def _binary_runtime_effect(self, other, site, operator):
        del other
        return _runtime_alias_effect_at_site(
            self,
            shape=f"{self.bound_name} {operator} ...",
            blame=str(site),
            replacement="ImportedModuleBinaryEffect",
        )

    def _unary_runtime_effect(self, site, operator):
        return _runtime_alias_effect_at_site(
            self,
            shape=f"{operator}{self.bound_name}",
            blame=str(site),
            replacement="ImportedModuleUnaryEffect",
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
    return _runtime_alias_effect_at_site(
        value,
        shape=shape,
        blame=operation.blame,
        replacement=replacement,
    )


def _runtime_alias_effect_at_site(
    value: ImportAliasValue, *, shape: str, blame: str, replacement: str
):
    from sugar_lift_py_tests.effect import ImportedModuleRuntimeEffect
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(
        ImportedModuleRuntimeEffect(
            "import alias runtime boundary: "
            f"`{shape}` requires evaluating imported module binding "
            f"`{value.bound_name} -> {value.name}` at runtime. "
            "The alias floor records name binding only; it does not fabricate "
            "module object semantics. "
            f"replacement={replacement}; blame={blame}"
        )
    )
