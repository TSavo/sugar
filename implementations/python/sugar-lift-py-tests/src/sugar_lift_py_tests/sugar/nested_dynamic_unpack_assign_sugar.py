"""Nested Name-only unpack against a non-display RHS.

``(a, b), (c, d) = mask_info`` — target is a tree of Names; RHS is not a display
``Assign._destructured_binding`` can zip. Flat ``DynamicUnpackAssignSugar`` only
admits flat Name leaves. This sugar owns the nested Name-only tree.

Same law as flat dynamic unpack: evaluate RHS once, then ask the reduced value
what it unpacks to. Nested structure is real (outer arity then inner), never
flattened into a four-name demand that would lie about FormalRef unpack.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness

# Pattern tree: leaf name, or tuple of sub-patterns.
NameUnpackPattern = str | tuple["NameUnpackPattern", ...]


def flatten_pattern_names(pattern: NameUnpackPattern) -> tuple[str, ...]:
    if isinstance(pattern, str):
        return (pattern,)
    names: list[str] = []
    for part in pattern:
        names.extend(flatten_pattern_names(part))
    return tuple(names)


def pattern_desc(pattern: NameUnpackPattern) -> str:
    if isinstance(pattern, str):
        return pattern
    return "(" + ", ".join(pattern_desc(p) for p in pattern) + ")"


@dataclass(frozen=True)
class NestedDynamicUnpackAssignSugar(Sugar):
    """``(a, b), (c, d) = <rhs>`` Name-only nested targets, non-display RHS."""

    pattern: tuple[NameUnpackPattern, ...]
    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="nested_sequence_unpack_runtime_effect",
            owner_sugar="NestedDynamicUnpackAssignSugar",
            source=(
                "def A(mask_info, v):\n"
                "    (a, b), (c, d) = mask_info\n"
                "    return v\n"
            ),
            effect_class="SequenceUnpackRuntimeEffect",
            reason_needle="nested sequence unpack",
            blame_needle="arity=2",
            wrong_reason_needle="exactly 4 members",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.desugar(ctx).and_then(
            lambda value: self._project(value, self.pattern, ctx)
        )

    def _project(
        self, value: Any, pattern: tuple[NameUnpackPattern, ...], ctx: object
    ) -> Outcome:
        from sugar_lift_py_tests.operations.sequence_projection_operation import (
            SequenceProjectionOperation,
        )

        if all(isinstance(part, str) for part in pattern):
            return SequenceProjectionOperation(
                target_names=tuple(pattern),  # type: ignore[arg-type]
                owner=type(self).__name__,
                blame=self.site,
            ).submit(value, ctx)

        members = _authenticated_finite_members(value)
        if members is None:
            return self._runtime_nested(value, pattern)

        if len(members) != len(pattern):
            return SequenceProjectionOperation(
                target_names=tuple(
                    p if isinstance(p, str) else f"@{i}" for i, p in enumerate(pattern)
                ),
                owner=type(self).__name__,
                blame=self.site,
            )._arity_mismatch_exit(value, len(members), "nested-unpack")

        return self._bind_nested_authenticated(members, pattern, ctx)

    def _bind_nested_authenticated(
        self,
        members: tuple[Any, ...],
        pattern: tuple[NameUnpackPattern, ...],
        ctx: object,
    ) -> Outcome:
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds

        collected: list[tuple[str, Any]] = []

        def step(index: int) -> Outcome:
            if index == len(pattern):
                return Complete(ScopeRebinds(tuple(collected)))
            part = pattern[index]
            member = members[index]
            if isinstance(part, str):
                collected.append((part, member))
                return step(index + 1)
            sub = self._project(member, part, ctx)
            if not isinstance(sub, Complete):
                return sub
            if isinstance(sub.value, ScopeRebinds):
                collected.extend(sub.value.bindings)
            else:
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=self.site,
                    owner="NestedDynamicUnpackAssignSugar",
                    observed=f"nested unpack sub-project produced {type(sub.value).__name__}",
                    requested="ScopeRebinds of leaf names",
                    fix="nested Name-only unpack must rebind leaves through ScopeRebinds",
                )
            return step(index + 1)

        return step(0)

    def _runtime_nested(
        self, value: Any, pattern: tuple[NameUnpackPattern, ...]
    ) -> Outcome:
        from sugar_lift_py_tests.effect import (
            SequenceUnpackRuntimeEffect,
            runtime_effect_evidence_from_terms,
        )
        from sugar_lift_py_tests.ir import ctor, num
        from sugar_lift_py_tests.outcome import Incomplete

        term = value.to_term(owner=f"{type(self).__name__}.value")
        arity = len(pattern)
        operation = ctor(
            "python:unpack.destructure",
            [term, num(arity)],
            symbol_kind="coordinate",
        )
        desc = pattern_desc(pattern)
        leaves = ", ".join(flatten_pattern_names(pattern))
        return Incomplete(
            SequenceUnpackRuntimeEffect(
                "nested sequence unpack runtime boundary: unpack demands "
                f"nested pattern {desc} (outer arity={arity}, leaves=({leaves})) "
                "but the right-hand side carries no authenticated cardinality -- "
                "iteration count belongs to Python's runtime __iter__; "
                f"arity={arity} nested=True site={self.site}",
                **runtime_effect_evidence_from_terms(operation, operation, self.site),
            )
        )


def _authenticated_finite_members(value: Any) -> tuple[Any, ...] | None:
    items = getattr(value, "items", None)
    if isinstance(items, tuple):
        return items
    finite = getattr(value, "finite_elements", None)
    if isinstance(finite, tuple):
        return finite
    return None
