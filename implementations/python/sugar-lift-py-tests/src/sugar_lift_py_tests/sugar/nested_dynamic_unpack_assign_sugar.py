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

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness

# Pattern tree: leaf name, or tuple of sub-patterns.  A starred leaf
# (``*rest``) is its name behind ``STAR``: a Python identifier never starts
# with ``*``, so it is never a plain leaf.  At most one per level.
NameUnpackPattern = str | tuple["NameUnpackPattern", ...]
STAR = "*"


def is_star_leaf(part: NameUnpackPattern) -> bool:
    return isinstance(part, str) and part.startswith(STAR)


def flatten_pattern_names(pattern: NameUnpackPattern) -> tuple[str, ...]:
    if isinstance(pattern, str):
        return (pattern[len(STAR) :] if is_star_leaf(pattern) else pattern,)
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
    # The statement's one evaluation: every leaf's member is bound under its
    # projection of this key too (temporal choice 1; DynamicUnpackAssignSugar).
    evaluation: str | None = None

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
            reason_needle="sequence unpack",
            blame_needle="arity=2",
            wrong_reason_needle="exactly 4 members",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        if self.evaluation is None:
            return self.value.desugar(ctx).and_then(
                lambda value: self._project(value, self.pattern, ctx)
            )
        from sugar_lift_py_tests.floor.scope_rebind import bind_unpack_projections

        return self.value.desugar(ctx).and_then(
            lambda value: self._project(value, self.pattern, ctx).and_then(
                lambda rebinds: bind_unpack_projections(rebinds, self.evaluation)
            )
        )

    def _project(
        self, value: Any, pattern: tuple[NameUnpackPattern, ...], ctx: object
    ) -> ExitSet:
        return project_nested_pattern(value, pattern, ctx, site=self.site)


_OWNER = "NestedDynamicUnpackAssignSugar"


def project_nested_pattern(
    value: Any, pattern: tuple[NameUnpackPattern, ...], ctx: object, *, site
) -> ExitSet:
    """The one nested Name-only unpack of an already-evaluated ``value``.

    Each level is the sequence-projection unpack (``SequenceProjectionOperation``,
    the one a flat ``a, b = e`` / ``a, *b = e`` submits), each nested member
    standing in its slot as ``@<index>`` (``@`` is never in an identifier),
    then each such member unpacked by its own sub-pattern, leaves in source
    order.  Its completed faces are the ``ScopeRebinds`` of every leaf; its
    halted faces are each level's halt (an arity mismatch, or the runtime
    cardinality halt beside a value's completed projections), an inner
    level's beneath the outer one's completed face (``ExitSet.and_then``).
    The statement's sugar (``NestedDynamicUnpackAssignSugar``) unpacks its
    right-hand side through it; a yield assignment's resume unpacks the
    resumed value through it (``YieldAssignUnpackV1.project``).

    A starred leaf (``(a, *b, (c, d))``) takes the list of the members
    between its fixed neighbours.
    """
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
    from sugar_lift_py_tests.operations.sequence_projection_operation import (
        SequenceProjectionOperation,
    )
    from sugar_source_tree.panic import SugarNotWritten

    slots = tuple(
        part if isinstance(part, str) else f"@{index}"
        for index, part in enumerate(pattern)
    )
    stars = [index for index, part in enumerate(pattern) if is_star_leaf(part)]
    if stars:
        star = stars[0]
        prefix = slots[:star]
        suffix = slots[star + 1 :]
        operation = SequenceProjectionOperation(
            target_names=(*prefix, *suffix),
            owner=_OWNER,
            blame=site,
            star_name=flatten_pattern_names(pattern[star])[0],
            prefix_names=prefix,
            suffix_names=suffix,
        )
    else:
        operation = SequenceProjectionOperation(
            target_names=slots,  # type: ignore[arg-type]
            owner=_OWNER,
            blame=site,
        )

    def rebinds_of(projected):
        if not isinstance(projected, ScopeRebinds):
            raise SugarNotWritten(
                blame=site,
                owner=_OWNER,
                observed=f"nested unpack level produced {type(projected).__name__}",
                requested="ScopeRebinds of leaf names",
                fix="a nested level must rebind its members through ScopeRebinds",
            )
        return projected.bindings

    def splice(bindings, index, collected) -> ExitSet:
        if index == len(bindings):
            return ExitSet.completed(ScopeRebinds(tuple(collected)))
        name, member = bindings[index]
        if not name.startswith("@"):
            return splice(bindings, index + 1, (*collected, (name, member)))
        return project_nested_pattern(
            member, pattern[int(name[1:])], ctx, site=site
        ).and_then(
            lambda sub: splice(
                bindings, index + 1, (*collected, *rebinds_of(sub))
            )
        )

    return operation.submit(value, ctx).and_then(
        lambda level: splice(rebinds_of(level), 0, ())
    )
