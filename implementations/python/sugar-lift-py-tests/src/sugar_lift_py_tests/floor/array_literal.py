from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .import_alias_value import ImportAliasValue
from .object_value import ObjectValue
from .string_value import StringValue
from .symbolic_value import SymbolicValue
from .term_value import TermValue
from .tuple_literal_value import TupleLiteralValue


@dataclass(frozen=True)
class ArrayLiteral(FloorValue):
    # Each item is a scalar, object, symbolic parameter, nested array, or tuple literal.
    items: tuple[
        "TermValue | ObjectValue | StringValue | SymbolicValue | ImportAliasValue | ArrayLiteral | TupleLiteralValue",
        ...,
    ]

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("array", [item.to_term(owner=owner) for item in self.items])

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_array(self, ctx)

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_array(self, ctx)

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.binary_array(self, ctx)

    def attribute_with(self, operation: Any, ctx: Any) -> Any:
        del ctx
        from sugar_lift_py_tests.effect import (
            GetattrRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            GetattrRuntimeEffect(
                "attribute access runtime boundary: "
                f"ArrayLiteral.{operation.name} has no static attribute floor for "
                "attribute_with; Python resolves attributes through descriptor and "
                "__getattribute__ hooks at runtime. Keep as typed red until a "
                f"narrower attribute floor owns the shape. blame={operation.blame}",
                **runtime_effect_evidence("py.getattr", operation.name, operation),
            )
        )

    def contains_with(self, operation: Any, ctx: Any) -> Any:
        return operation.contains_array(self, ctx)

    def iter_with(self, operation: Any, ctx: Any) -> Any:
        """Iterate the authenticated members produced by a list-like floor."""
        del operation, ctx
        from sugar_lift_py_tests.floor.iterator_value import ListIteratorValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(ListIteratorValue(self.items, index=0))

    def delitem_with(self, operation: Any, ctx: Any) -> Any:
        return operation.delitem_array(self, ctx)

    def setitem_with(self, operation: Any, ctx: Any) -> Any:
        return operation.setitem_array(self, ctx)

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return operation.subscript_array(self, ctx)

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        del ctx
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            # Bare folded count; BuiltinCallSugar's one wrap re-attaches the
            # `call:len(...)` coordinate with this value as `computed`.
            return Complete(TermValue(len(self.items)))
        if operation.name == "__hash__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            # Non-folding pure builtin: marker only. BuiltinCallSugar wrap →
            # call:hash(...), computed=None (never fabricate a Python hash).
            return Complete(self)
        _call_method_gap(
            owner=operation.owner,
            blame=operation.blame,
            observed=f"ArrayLiteral.{operation.name}",
            requested="array builtin method floor",
            fix=f"add ArrayLiteral method floor for `{operation.name}`",
        )

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_array(self, ctx)

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_literal(self, ctx)

    def multiply(self, other, site):
        # Array repetition, through the one sequence-repetition law -- the same
        # law list and tuple were consolidated onto (#6060). This arm kept a
        # private copy that PANICKED above a static cap; the cap was abolished
        # there and the array was the straggler, still reaching for the deleted
        # `sugar.for_sugar` cap and raising ImportError instead of repeating.
        from sugar_lift_py_tests.floor.sequence_repetition import repeat_sequence

        return repeat_sequence(
            self, other, site, elements=self.items, rebuild=ArrayLiteral
        )


def _call_method_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
):
    from sugar_lift_py_tests.gap.panic import construction_panic
    from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

    info = ConstructionGap(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    construction_panic(info)
