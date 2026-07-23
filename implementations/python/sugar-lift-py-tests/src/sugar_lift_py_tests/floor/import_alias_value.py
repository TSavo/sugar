from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class ImportAliasValue(FloorValue):
    """An inert source-stated import binding, never a value resolver.

    Import-to-contract resolution has exactly one owner: authenticated
    preconstruction.  This legacy floor records a coordinate only and has no
    source-oracle, module-import, re-export-walk, or value-resolution door.
    """

    name: str
    bound_name: str
    import_target: str | None = None

    def extend_scope(self, ctx):
        return ctx.with_temporal(ctx.temporal.bind_value(self.bound_name, self))

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:import_alias", [str_const(self.bound_name), str_const(self.name)])

    def test_python_type(self, value, site):
        from sugar_lift_py_tests.floor.type_tester import native_type_tester
        from sugar_lift_py_tests.ir import ctor, str_const

        return native_type_tester(value, ctor("python:type", [str_const(self.name)]), site)

    def qualified_class_attribute(self, attribute: str) -> ImportAliasValue | None:
        del attribute
        return None

    def qualified_attribute(self, attribute: str, site) -> ImportAliasValue | None:
        del attribute, site
        return None

    def truth(self, site):
        from sugar_lift_py_tests.gap.info import GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        target = self.import_target or self.name
        construction_panic_gap(
            owner="ImportAliasValue.truth",
            blame=site,
            observed=f"py.truthy(python:import_alias({self.bound_name!r}, {self.name!r}))",
            requested="authenticated import value truthiness",
            fix=(
                f"Import binding `{self.bound_name} -> {target}` has no authenticated "
                "contract-backed value. Consume ResolvedCallContractRefV1 directly; "
                "never open installed source or execute the module."
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise AssertionError("construction_panic_gap returned")

    def subscript(self, index, site):
        return self.py_subscript_coordinate(index, site)

    def getattr_static(self, name: str, site):
        from sugar_lift_py_tests.gap.info import GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        target = self.import_target or self.name
        construction_panic_gap(
            owner="ImportAliasValue",
            blame=site,
            observed=f"{target}.{name}",
            requested="authenticated import attribute coordinate",
            fix="consume an authenticated contract bridge; no source-hunt fallback exists",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise AssertionError("construction_panic_gap returned")

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

    def bitwise_or(self, other, site):
        if site.is_within_annotation():
            from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete

            return Complete(SymbolicValue(ctor("|", [self.to_term(owner=str(site)), other.to_term(owner=str(site))])))
        return super().bitwise_or(other, site)

    def unary_minus(self, site):
        return self._unary_runtime_effect(site, "-")

    def unary_plus(self, site):
        return self._unary_runtime_effect(site, "+")

    def bitwise_invert(self, site):
        return self._unary_runtime_effect(site, "~")

    def format_data_model(self, spec, site, ctx):
        del spec, ctx
        return _runtime_alias_effect_at_site(
            self, shape=f"format({self.bound_name}, ...)", site=site,
            replacement="ImportedModuleFormatEffect",
        )

    def _binary_runtime_effect(self, other, site, operator):
        del other
        return _runtime_alias_effect_at_site(
            self, shape=f"{self.bound_name} {operator} ...", site=site,
            replacement="ImportedModuleBinaryEffect",
        )

    def _unary_runtime_effect(self, site, operator):
        return _runtime_alias_effect_at_site(
            self, shape=f"{operator}{self.bound_name}", site=site,
            replacement="ImportedModuleUnaryEffect",
        )

    def call_method_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(self, operation=operation,
            shape=f"{self.bound_name}.{operation.name}(...)",
            replacement="ImportedModuleCallEffect")

    def subscript_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(self, operation=operation,
            shape=f"{self.bound_name}[...]", replacement="ImportedModuleSubscriptEffect")

    def contains_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(self, operation=operation,
            shape="contains membership over imported module binding",
            replacement="ImportedModuleContainsEffect")

    def attribute_assign_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(self, operation=operation,
            shape=f"{self.bound_name}.{operation.name} = ...",
            replacement="ImportedModuleAttributeAssignEffect")

    def binary_operator_with(self, operation: Any, ctx: object):
        del ctx
        return _runtime_alias_effect(self, operation=operation,
            shape=f"{self.bound_name} {operation.operator} ...",
            replacement="ImportedModuleBinaryEffect")


def _runtime_alias_effect(value: ImportAliasValue, *, operation: Any, shape: str, replacement: str):
    return _runtime_alias_effect_at_site(
        value, shape=shape, site=operation.site, replacement=replacement
    )


def _runtime_alias_effect_at_site(
    value: ImportAliasValue, *, shape: str, site, replacement: str
):
    from sugar_lift_py_tests.effect import (
        ImportedModuleRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Incomplete

    target = value.import_target or value.name
    alias = value.to_term(owner="ImportedModuleRuntimeEffect")
    operand = ctor("call:import_module", [alias])
    return Incomplete(
        ImportedModuleRuntimeEffect(
            "import alias runtime boundary: "
            f"`{shape}` requires evaluating imported binding `{value.bound_name} -> {target}`. "
            "No authenticated contract-backed value was installed; source hunting is cut. "
            f"replacement={replacement}; blame={site}",
            **runtime_effect_evidence_from_terms(
                ctor(
                    "python:import_floor_operation",
                    [operand, str_const(replacement), str_const(shape)],
                ),
                operand,
                site,
            ),
        )
    )
