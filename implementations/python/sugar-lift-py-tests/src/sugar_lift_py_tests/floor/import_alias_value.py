from __future__ import annotations

from dataclasses import dataclass, field
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
    import_target: str | None = None
    resolved_value: FloorValue | None = field(default=None, compare=False)
    install_source_checked: bool = field(default=False, compare=False)
    install_source_context: Any = field(default=None, compare=False, repr=False)

    def resolve_value(self):
        """Construct this source-backed value only when a consumer demands it."""
        if self.resolved_value is not None:
            return self.resolved_value
        if self.install_source_context is None:
            return None
        target = self.import_target or self.name
        if not target or "." not in target:
            return None
        from sugar_lift_py_tests.sugar.install_source_dig import (
            resolve_install_source_value,
        )

        return resolve_install_source_value(target, self.install_source_context)

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

    def qualified_class_attribute(self, attribute: str) -> ImportAliasValue | None:
        """Construct an exact imported class coordinate when Python proves it.

        A module import plus ``inspect.isclass(module.attribute)`` is concrete
        lift-time evidence for the type object's qualified identity.  A
        function, constant, missing attribute, or unavailable module does not
        claim this recognizer and remains on AttributeSugar's existing path.
        """
        import importlib
        import inspect

        module_name = self.import_target or self.name
        head, separator, _tail = module_name.partition(".")
        if self.import_target is None and separator and self.bound_name == head:
            # ``import package.submodule`` binds ``package``.  An explicit
            # alias (``as sub``) binds the full stated module instead.
            module_name = head
        if module_name.startswith("."):
            # Relative import spellings are not free-standing module coordinates.
            return None
        try:
            module = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError, TypeError, ValueError):
            return None
        candidate = getattr(module, attribute, None)
        if not inspect.isclass(candidate):
            return None
        qualified = f"{module_name}.{attribute}"
        return ImportAliasValue(
            qualified,
            attribute,
            import_target=qualified,
        )

    def qualified_attribute(self, attribute: str, site) -> ImportAliasValue | None:
        """Construct an exact coordinate for a concrete imported object member.

        ``from pandas import Timestamp`` fixes the receiver identity before
        lift.  When that exact target resolves to a module or class and Python
        receives a static requested name, ``getattr(Timestamp, "now")`` is the
        inert coordinate ``pandas.Timestamp.now``.  The coordinate records the
        requested lookup; it does not claim that Python lookup succeeds.
        An unavailable receiver returns ``None`` to the caller's loud floor.
        """
        target = self.import_target or self.name
        receiver = _resolve_qualified_import_object(target)
        if receiver is None:
            return None
        del site
        qualified = f"{target}.{attribute}"
        return ImportAliasValue(
            qualified,
            attribute,
            import_target=qualified,
        )

    def truth(self, site):
        """Construct decidable truthiness for an import binding.

        Law (#4981 / #4265 ground-operand): ``python:import_alias`` with string
        coordinates is lift-time ground. Emitting ``py.truthy(import_alias)`` and
        later minting RuntimeEffect authority is illegal — construct or panic.

        - Dug ``resolved_value`` answers with its own truth.
        - Module objects are always truthy in Python (``bool(importlib) is True``).
        - Attribute from-imports without a constructed value cannot invent a
          soft runtime condition over a ground coordinate: FactoryPanic.
        """
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        resolved_value = self.resolve_value()
        if resolved_value is not None:
            return resolved_value.truth(site)

        coordinate = self._checked_constant_coordinate()
        if coordinate is not None:
            return coordinate.truth(site)

        if _import_alias_binds_module(self):
            return Complete(TrueBoolLiteralSugar(site=site))

        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

        target = self.import_target or self.name
        factory_panic_gap(
            owner="ImportAliasValue.truth",
            blame=site,
            observed=(
                f"py.truthy(python:import_alias({self.bound_name!r}, {self.name!r}))"
            ),
            requested="construct decidable import-alias truthiness",
            fix=(
                f"Import binding `{self.bound_name} -> {self.name}` "
                f"(import_target={target!r}) has no resolved floor value and is "
                "not a module object. Module imports construct True "
                "(Python modules are always truthy). Attribute from-imports must "
                "dig install-source to the value and construct its truth. Ground "
                "python:import_alias cannot mint RuntimeEffect via py.truthy — "
                "replacement=resolve_install_source_value then truth(), or keep "
                "this FactoryPanic (never soft RuntimeEffect for ground cases)."
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise AssertionError("factory_panic_gap returned")

    def subscript(self, index, site):
        return self.py_subscript_coordinate(index, site)

    def getattr_static(self, name: str, site):
        """Keep an unresolvable ground alias lookup loud."""
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

        target = self.import_target or self.name
        factory_panic_gap(
            owner="ImportAliasValue",
            blame=site,
            observed=f"{target}.{name}",
            requested="qualified import attribute coordinate",
            fix=(
                f"Resolve imported receiver `{target}` to a concrete module/class "
                f"before constructing `{target}.{name}`. A ground static getattr "
                "cannot mint RuntimeEffect authority."
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise AssertionError("factory_panic_gap returned")

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

            return Complete(
                SymbolicValue(
                    ctor(
                        "|",
                        [
                            self.to_term(owner=str(site)),
                            other.to_term(owner=str(site)),
                        ],
                    )
                )
            )
        return super().bitwise_or(other, site)

    def unary_minus(self, site):
        return self._unary_runtime_effect(site, "-")

    def unary_plus(self, site):
        return self._unary_runtime_effect(site, "+")

    def bitwise_invert(self, site):
        return self._unary_runtime_effect(site, "~")

    def format_data_model(self, spec, site, ctx):
        resolved_value = self.resolve_value()
        if resolved_value is not None:
            return resolved_value.format_data_model(spec, site, ctx)
        return _runtime_alias_effect_at_site(
            self,
            shape=f"format({self.bound_name}, ...)",
            site=site,
            replacement="ImportedModuleFormatEffect",
        )

    def _binary_runtime_effect(self, other, site, operator):
        resolved = self.resolve_value() or self._checked_constant_coordinate()
        if resolved is not None:
            methods = {
                "+": "add",
                "-": "subtract",
                "*": "multiply",
                "/": "divide",
                "**": "power",
                "&": "bitwise_and",
                "^": "bitwise_xor",
            }
            return getattr(resolved, methods[operator])(other, site)
        return _runtime_alias_effect_at_site(
            self,
            shape=f"{self.bound_name} {operator} ...",
            site=site,
            replacement="ImportedModuleBinaryEffect",
        )

    def _unary_runtime_effect(self, site, operator):
        resolved_value = self.resolve_value()
        if resolved_value is not None:
            methods = {"-": "unary_minus", "+": "unary_plus", "~": "bitwise_invert"}
            return getattr(resolved_value, methods[operator])(site)
        return _runtime_alias_effect_at_site(
            self,
            shape=f"{operator}{self.bound_name}",
            site=site,
            replacement="ImportedModuleUnaryEffect",
        )

    def call_method_with(self, operation: Any, ctx: object):
        resolved_value = self.resolve_value()
        if resolved_value is not None:
            return resolved_value.call_method_with(operation, ctx)
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape=f"{self.bound_name}.{operation.name}(...)",
            replacement="ImportedModuleCallEffect",
        )

    def subscript_with(self, operation: Any, ctx: object):
        resolved_value = self.resolve_value()
        if resolved_value is not None:
            return resolved_value.subscript_with(operation, ctx)
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape=f"{self.bound_name}[...]",
            replacement="ImportedModuleSubscriptEffect",
        )

    def contains_with(self, operation: Any, ctx: object):
        resolved_value = self.resolve_value()
        if resolved_value is not None:
            return resolved_value.contains_with(operation, ctx)
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape="contains membership over imported module binding",
            replacement="ImportedModuleContainsEffect",
        )

    def attribute_assign_with(self, operation: Any, ctx: object):
        resolved_value = self.resolve_value()
        if resolved_value is not None:
            return resolved_value.attribute_assign_with(operation, ctx)
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape=f"{self.bound_name}.{operation.name} = ...",
            replacement="ImportedModuleAttributeAssignEffect",
        )

    def binary_operator_with(self, operation: Any, ctx: object):
        resolved_value = self.resolve_value()
        if resolved_value is not None:
            return resolved_value.binary_operator_with(operation, ctx)
        del ctx
        return _runtime_alias_effect(
            self,
            operation=operation,
            shape=f"{self.bound_name} {operation.operator} ...",
            replacement="ImportedModuleBinaryEffect",
        )

    def _checked_constant_coordinate(self):
        """Construct a coordinate only after the source door checked this target."""
        if not self.install_source_checked:
            return None
        import inspect
        from types import ModuleType

        target = self.import_target or self.name
        value = _resolve_qualified_import_object(target)
        if (
            value is None
            or isinstance(value, ModuleType)
            or inspect.isclass(value)
            or callable(value)
        ):
            return None
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const

        return SymbolicValue(
            ctor(
                "python:import_alias",
                [str_const(self.bound_name), str_const(target)],
            )
        )


def _import_alias_binds_module(value: ImportAliasValue) -> bool:
    """True when the import coordinate names an importable module object.

    ``import m`` / ``import pkg.sub`` / ``from pkg import sub`` (submodule)
    bind module objects, which are always truthy in Python. Attribute
    from-imports (``from pkg import HAS_FLAG``) are not modules.
    """
    import importlib.util

    target = value.import_target or value.name
    try:
        return importlib.util.find_spec(target) is not None
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError):
        return False


def _resolve_qualified_import_object(target: str) -> object | None:
    """Resolve one qualified import target without guessing split ownership."""
    import importlib

    if not target or target.startswith("."):
        # Relative spellings need a package context; bare coordinates do not.
        return None
    parts = target.split(".")
    for module_length in range(len(parts), 0, -1):
        module_name = ".".join(parts[:module_length])
        try:
            value: object = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError, TypeError, ValueError):
            continue
        for attribute in parts[module_length:]:
            sentinel = object()
            value = getattr(value, attribute, sentinel)
            if value is sentinel:
                return None
        return value
    return None


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
        # Every dispatched operation owns its site fragment; a blame-only
        # operation is a construction gap, not a soft fallback.
        site=operation.site,
        replacement=replacement,
    )


def _runtime_alias_effect_at_site(
    value: ImportAliasValue, *, shape: str, site, replacement: str
):
    import importlib.util

    target = value.import_target or value.name
    module_name = target.rsplit(".", 1)[0] if "." in target else target
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        spec = None
    origin = getattr(spec, "origin", None)
    if origin and origin.endswith((".py", ".pyi")):
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

        factory_panic_gap(
            owner="ImportAliasValue",
            blame=site,
            observed=target,
            requested="dig installed import source before applying floor operation",
            fix=f"route `{shape}` through install_source_dig for source `{origin}`",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )

    from sugar_lift_py_tests.effect import (
        ImportedModuleRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Incomplete

    alias = value.to_term(owner="ImportedModuleRuntimeEffect")
    operand = ctor("call:import_module", [alias])

    return Incomplete(
        ImportedModuleRuntimeEffect(
            "import alias runtime boundary: "
            f"`{shape}` requires evaluating imported module binding "
            f"`{value.bound_name} -> {value.name}` at runtime. "
            "The alias floor records name binding only; it does not fabricate "
            "module object semantics. "
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
