"""Typed unpack projection targets — each owns how one member is applied.

Replaces string-tag leaf ladders (``\"name\"`` / ``\"attr\"`` / …) with closed
variants: Name, Star, Attribute store, Subscript store.  Application is
left-to-right over an ``UnpackMemberRoster`` (positional members).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class NameUnpackTarget:
    """Lexical name: rebind to the projected member."""

    name: str

    def apply_member(self, member, ctx) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        return Complete(ScopeRebind(self.name, member))


@dataclass(frozen=True)
class StarUnpackTarget:
    """Starred name: rebind to the projected middle ``ListValue``."""

    name: str

    def apply_member(self, member, ctx) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        return Complete(ScopeRebind(self.name, member))


@dataclass(frozen=True)
class AttributeUnpackTarget:
    """Attribute store leaf: ``receiver.attr = member`` via shared setattr door."""

    receiver: Sugar
    attr: str
    site: object = dataclass_field(compare=False)

    def apply_member(self, member, ctx) -> Outcome:
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            AttributeStoreEffectSugar,
        )

        return AttributeStoreEffectSugar(
            receiver=self.receiver,
            value=_MemberViaDesugarStore(),
            attr=self.attr,
            site=self.site,
        ).desugar_store(ctx, member)


@dataclass(frozen=True)
class SubscriptUnpackTarget:
    """Subscript store leaf: ``receiver[index] = member`` via shared setitem door."""

    receiver: Sugar
    index: Sugar
    site: object = dataclass_field(compare=False)

    def apply_member(self, member, ctx) -> Outcome:
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            SubscriptStoreEffectSugar,
        )

        return SubscriptStoreEffectSugar(
            receiver=self.receiver,
            index=self.index,
            value=_MemberViaDesugarStore(),
            site=self.site,
        ).desugar_store(ctx, member)


# Closed set of projection-target kinds (construction admits only these).
UNPACK_PROJECTION_TARGET_TYPES = (
    NameUnpackTarget,
    StarUnpackTarget,
    AttributeUnpackTarget,
    SubscriptUnpackTarget,
)


@dataclass(frozen=True)
class _MemberViaDesugarStore(Sugar):
    """Placeholder value field — member arrives only via ``desugar_store``."""

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="pre-reduced unpack member",
            reason="unpack store targets receive members via desugar_store",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        raise AssertionError(
            "unpack store member must arrive via desugar_store, not value.desugar"
        )


@dataclass(frozen=True)
class ApplyUnpackMemberSugar(Sugar):
    """One left-to-right step: typed target applies one roster member."""

    target: object  # one of UNPACK_PROJECTION_TARGET_TYPES
    member: object  # FloorValue
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="unpack target apply",
            reason="DynamicUnpackStoreAssignSugar sequences ApplyUnpackMemberSugar",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if not isinstance(self.target, UNPACK_PROJECTION_TARGET_TYPES):
            raise AssertionError(
                f"unknown unpack projection target: {type(self.target).__name__}"
            )
        return self.target.apply_member(self.member, ctx)
