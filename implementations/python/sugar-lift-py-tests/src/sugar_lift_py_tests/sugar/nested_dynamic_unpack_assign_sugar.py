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
from typing import Any, ClassVar

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
    # A record-less halt is the right-hand side's, or a level's unpack before
    # any leaf was bound (the outer one; an inner one first in its parent):
    # its pre-halt record is the block's prefix, or, after a walrus in the
    # right-hand side bound, the record of that bind (``consume_operands``).
    # An inner level that halts after a leaf was bound carries the record of
    # what was bound (``_bound_record``).
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="nested_sequence_unpack_undetermined_raise",
            owner_sugar="NestedDynamicUnpackAssignSugar",
            source=(
                "def A(mask_info, v):\n"
                "    (a, b), (c, d) = mask_info\n"
                "    return v\n"
            ),
            effect_class="UndeterminedRaiseEffect",
            reason_needle="undetermined exception identity",
            blame_needle="SourceFragment",
            wrong_reason_needle="raise ValueError",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            written_by,
        )
        from sugar_lift_py_tests.floor.scope_rebind import bind_unpack_projections

        # The unpack consumes the evaluated right-hand side through the one
        # operand door: a walrus in it (``(a, b), c = (w := v)``) is bound
        # before any level unpacks, so the outer level's halt carries it
        # (``consume_operands``), an inner level's record is built on it
        # (``_bound_record``), and the completed face carries it on.
        def unpack(value):
            after = written_by(value, ctx)

            def step(presented):
                projected = self._project(presented, self.pattern, after)
                if self.evaluation is None:
                    return projected
                return projected.and_then(
                    lambda rebinds: bind_unpack_projections(rebinds, self.evaluation)
                )

            return consume_operands(step, value)

        return self.value.desugar(ctx).and_then(unpack)

    def _project(
        self, value: Any, pattern: tuple[NameUnpackPattern, ...], ctx: object
    ) -> ExitSet:
        return project_nested_pattern(
            value, pattern, ctx, site=self.site, record=self._bound_record(ctx)
        )

    def _bound_record(self, ctx: object):
        """The record an inner level's halt carries: ``(name, member)`` of
        every leaf Python bound before that level unpacked, bound as the
        statement's completed face binds them (under their projections of
        ``evaluation`` when the statement was substituted), in the context
        the statement halted in.

        CPython stores each target of a level before it unpacks the next
        nested one (``(a, b), (c, d) = v``: ``a`` and ``b`` are bound when
        the second unpack raises), and never unbinds them: a handler
        around the statement reads them.
        """
        from sugar_lift_py_tests.floor.scope_rebind import (
            ScopeRebinds,
            bind_unpack_projections,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import halt_record

        def record(bindings):
            bound = bind_unpack_projections(
                ScopeRebinds(tuple(bindings)), self.evaluation
            ).completed_value()
            return halt_record(bound.extend_scope(ctx))

        return record


_OWNER = "NestedDynamicUnpackAssignSugar"


def project_nested_pattern(
    value: Any,
    pattern: tuple[NameUnpackPattern, ...],
    ctx: object,
    *,
    site,
    bound: tuple = (),
    record=None,
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
    resumed value through it (``YieldAssignUnpackV1.project``). Each gives
    ``record``: the statement's the context with the leaves bound, the
    resume's its generator frame with them bound.

    A starred leaf (``(a, *b, (c, d))``) takes the list of the members
    between its fixed neighbours.

    ``bound``: the ``(name, member)`` of every leaf bound before this level
    unpacks (the earlier targets of every enclosing level).  ``record``
    (``bindings -> record``): where given, a halt of this level's unpack
    after a leaf was bound carries ``record(bound)``, the record of those
    bindings; a halt before any leaf was bound offers none, and the
    statement records it at its head.
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
        # Every earlier target of this level is bound before the nested
        # one unpacks.
        return project_nested_pattern(
            member,
            pattern[int(name[1:])],
            ctx,
            site=site,
            bound=(*bound, *collected),
            record=record,
        ).and_then(
            lambda sub: splice(
                bindings, index + 1, (*collected, *rebinds_of(sub))
            )
        )

    unpacked = operation.submit(value, ctx)
    if record is not None and bound:
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halts_recorded,
        )

        unpacked = halts_recorded(unpacked, record(bound))
    return unpacked.and_then(lambda level: splice(rebinds_of(level), 0, ()))
