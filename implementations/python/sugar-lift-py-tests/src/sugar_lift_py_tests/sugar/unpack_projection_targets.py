"""Typed unpack projection targets — one obligation owns ``apply_member``.

Replaces string-tag leaf ladders with closed variants under a single typed
base: ``UnpackProjectionTarget``.  Application is left-to-right over an
``UnpackMemberRoster`` (positional members).  There is no kinds-tuple
``isinstance`` membrane at apply time — the target *is* the obligation.

Store leaves route the **already-reduced** roster member through the shared
store projection doors (``AttributeStoreEffectSugar.project_setattr`` /
``SubscriptStoreEffectSugar.project_setitem``).  No panic-on-desugar placeholder
Sugar stands in for the member field.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


class UnpackProjectionTarget(ABC):
    """One unpack leaf: owns how its positional roster member is applied.

    Construction (tree / tests) admits only concrete subclasses.  Apply is
    dispatch on the target object — never a closed-type ladder at the sugar.
    """

    @abstractmethod
    def apply_member(self, member, ctx) -> Outcome:
        """Apply one authenticated roster member to this target leaf."""

    def occupies_star_slot(self) -> bool:
        """True only for the single starred middle leaf (UNPACK_EX layout)."""
        return False


@dataclass(frozen=True)
class NameUnpackTarget(UnpackProjectionTarget):
    """Lexical name: rebind to the projected member."""

    name: str

    def apply_member(self, member, ctx) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        return Complete(ScopeRebind(self.name, member))


@dataclass(frozen=True)
class StarUnpackTarget(UnpackProjectionTarget):
    """Starred name: rebind to the projected middle ``ListValue``."""

    name: str

    def occupies_star_slot(self) -> bool:
        return True

    def apply_member(self, member, ctx) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        return Complete(ScopeRebind(self.name, member))


@dataclass(frozen=True)
class AttributeUnpackTarget(UnpackProjectionTarget):
    """Attribute store leaf: ``receiver.attr = member`` via shared setattr door."""

    receiver: Sugar
    attr: str
    site: object = dataclass_field(compare=False)

    def apply_member(self, member, ctx) -> Outcome:
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            AttributeStoreEffectSugar,
        )

        # Member is already reduced (roster FloorValue). Shared projection —
        # never a second value.desugar, never a panic placeholder Sugar field.
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: AttributeStoreEffectSugar.project_setattr(
                receiver, self.attr, member, self.site
            )
        )


@dataclass(frozen=True)
class SubscriptUnpackTarget(UnpackProjectionTarget):
    """Subscript store leaf: ``receiver[index] = member`` via shared setitem door."""

    receiver: Sugar
    index: Sugar
    site: object = dataclass_field(compare=False)

    def apply_member(self, member, ctx) -> Outcome:
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            SubscriptStoreEffectSugar,
        )

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: SubscriptStoreEffectSugar.project_setitem(
                    receiver, index, member, self.site
                )
            )
        )


@dataclass(frozen=True)
class ApplyUnpackMemberSugar(Sugar):
    """One left-to-right step: typed target applies one roster member."""

    target: UnpackProjectionTarget
    member: object  # FloorValue
    site: object = dataclass_field(compare=False, default=None)

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

    def desugar(self, ctx: object = None) -> Outcome:
        # One obligation: the target owns apply_member. No kinds ladder.
        return self.target.apply_member(self.member, ctx)
