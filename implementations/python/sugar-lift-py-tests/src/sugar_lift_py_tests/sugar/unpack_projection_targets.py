"""Typed unpack projection targets — one obligation owns ``apply_member``.

Replaces string-tag leaf ladders with closed variants under a single typed
base: ``UnpackProjectionTarget``.  Application is left-to-right over an
``UnpackMemberRoster`` (positional members).  There is no kinds-tuple
``isinstance`` membrane at apply time — the target *is* the obligation.

A store leaf binds the **already-reduced** roster member under its member key
and runs the leaf's own statement (``Assign._store_statements``): the
single-target store ``o.x = <member>``, which reads the member there and
stores it exactly as ``o.x = v`` alone does.  No panic-on-desugar placeholder
Sugar stands in for the member field, and no second store door.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


class UnpackProjectionTarget(ABC):
    """One unpack leaf: owns how its positional roster member is applied.

    Construction (tree / tests) admits only concrete subclasses.  Apply is
    dispatch on the target object — never a closed-type ladder at the sugar.
    """

    @abstractmethod
    def apply_member(self, member, ctx) -> ExitSet:
        """Apply one authenticated roster member to this target leaf."""

    def occupies_star_slot(self) -> bool:
        """True only for the single starred middle leaf (UNPACK_EX layout)."""
        return False


def _rebind_name(name: str, member, evaluation: str | None) -> ExitSet:
    """Bind a lexical leaf's member under its projection of the statement's
    one evaluation when the statement was substituted (temporal choice 1:
    every later read is an ``EvaluationRef`` to that projection, and the name
    is not written); a statement never substituted rebinds the name."""
    from sugar_lift_py_tests.floor.scope_rebind import (
        ScopeRebind,
        ScopeRebinds,
        bind_unpack_projections,
    )

    if evaluation is None:
        return ExitSet.completed(ScopeRebind(name, member))
    return bind_unpack_projections(ScopeRebinds(((name, member),)), evaluation)


@dataclass(frozen=True)
class NameUnpackTarget(UnpackProjectionTarget):
    """Lexical name: rebind to the projected member."""

    name: str
    evaluation: str | None = None

    def apply_member(self, member, ctx) -> ExitSet:
        del ctx
        return _rebind_name(self.name, member, self.evaluation)


@dataclass(frozen=True)
class StarUnpackTarget(UnpackProjectionTarget):
    """Starred name: rebind to the projected middle ``ListValue``."""

    name: str
    evaluation: str | None = None

    def occupies_star_slot(self) -> bool:
        return True

    def apply_member(self, member, ctx) -> ExitSet:
        del ctx
        return _rebind_name(self.name, member, self.evaluation)


@dataclass(frozen=True)
class StoreUnpackTarget(UnpackProjectionTarget):
    """Store leaf: ``o.x`` / ``d[k]`` in ``a, o.x = v``.

    The member is bound under ``evaluation`` (the leaf's member key), then
    ``store`` runs: the leaf's own statement's sugar, the single-target store
    ``o.x = <member>`` reading the member there.  It is keyed and stores
    exactly as ``o.x = v`` alone is, so a later read of the object sees it.
    """

    evaluation: str
    store: Sugar

    def apply_member(self, member, ctx) -> ExitSet:
        from sugar_lift_py_tests.context import ReduceContext
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
        from sugar_lift_py_tests.sugar.assign_sugar import _reduce_targets
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

        if ctx is None:
            ctx = ReduceContext.root(owner="StoreUnpackTarget")
        # Member is already reduced (roster FloorValue): bound, never a
        # second value.desugar, never a panic placeholder Sugar field.
        active = ScopeRebind(evaluation_here(self.evaluation), member).extend_scope(
            ctx
        )
        return _reduce_targets((self.store,), active, ctx)


@dataclass(frozen=True)
class NestedUnpackTarget(UnpackProjectionTarget):
    """Nested level: ``(b, o.x)`` in ``a, (b, o.x) = v``.

    Python unpacks the level's member, then assigns each of its targets left
    to right, before the next sibling target.  The member is unpacked through
    the one positional unpack a statement submits
    (``DynamicUnpackStoreAssignSugar.unpack``), under this level's own site,
    never a second unpack law.
    """

    targets: tuple  # UnpackProjectionTarget per element, source order
    site: object = dataclass_field(compare=False)

    def apply_member(self, member, ctx) -> ExitSet:
        from sugar_lift_py_tests.sugar.assign_sugar import (
            DynamicUnpackStoreAssignSugar,
        )

        # The member is already reduced: the level has no value to evaluate.
        level = DynamicUnpackStoreAssignSugar(
            value=None, targets=self.targets, site=self.site
        )
        return level.unpack(member, ctx)


@dataclass(frozen=True)
class ApplyUnpackMemberSugar(Sugar):
    """One left-to-right step: typed target applies one roster member."""

    target: UnpackProjectionTarget
    member: object  # FloorValue
    site: object = dataclass_field(compare=False, default=None)
    # A record-less halt is a nested level's unpack, before any of its own
    # targets applies: what the earlier targets bound is the prefix of the
    # block these steps reduce in. A store target's halt carries its record.
    halts_at_statement_head: ClassVar[bool] = True

    def __post_init__(self) -> None:
        if not isinstance(self.target, UnpackProjectionTarget):
            raise TypeError(
                "ApplyUnpackMemberSugar.target must be UnpackProjectionTarget; "
                f"got {type(self.target).__name__}"
            )

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="unpack target apply",
            reason="DynamicUnpackStoreAssignSugar sequences ApplyUnpackMemberSugar",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # One obligation: the target owns apply_member. No kinds ladder.
        return self.target.apply_member(self.member, ctx)
