from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


def ground_match_value(value) -> tuple[bool, object]:
    """Project the exact Python value carried by a supported ground floor."""
    from sugar_lift_py_tests.floor import NoneValue, StringValue, TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    if type(value) is TermValue or type(value) is StringValue:
        return True, value.value
    if type(value) is TrueBoolLiteralSugar:
        return True, True
    if type(value) is FalseBoolLiteralSugar:
        return True, False
    if type(value) is NoneValue:
        return True, None
    return False, None


class MatchPatternSugar(Sugar, FloorValue):
    """A factory-recognized match pattern that owns ground selection behavior."""

    def select_ground(self, subject, *, matched, missed, ctx) -> Outcome:
        raise NotImplementedError


@dataclass(frozen=True)
class MatchValuePatternSugar(MatchPatternSugar, role=SugarRole.PATTERN):
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "MatchValue"

    @classmethod
    def new(cls, site, ctx) -> "MatchValuePatternSugar":
        return cls(
            value=ctx.build_body(
                site.match_value_pattern_value(),
                SugarRole.TERM,
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(self)

    def select_ground(self, subject, *, matched, missed, ctx) -> Outcome:
        return self.value.reduce(ctx).and_then(
            lambda value: self._select_value(value, subject, matched, missed)
        )

    def _select_value(self, value, subject, matched, missed) -> Outcome:
        known, expected = ground_match_value(value)
        if not known:
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="MatchValuePatternSugar",
                blame=self.site,
                observed=type(value).__name__,
                requested="ground value-pattern evidence",
                fix=(
                    "construct the pattern value through a ground Floor; "
                    "unimplemented pattern machinery must remain loud"
                ),
            )
        return matched(None) if subject == expected else missed()

    def walk_children(self):
        return (self.value,)


@dataclass(frozen=True)
class MatchSingletonPatternSugar(MatchPatternSugar, role=SugarRole.PATTERN):
    value: bool | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "MatchSingleton"

    @classmethod
    def new(cls, site, ctx) -> "MatchSingletonPatternSugar":
        del ctx
        return cls(value=site.match_singleton_pattern_value(), site=site)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(self)

    def select_ground(self, subject, *, matched, missed, ctx) -> Outcome:
        del ctx
        return matched(None) if subject is self.value else missed()


@dataclass(frozen=True)
class MatchOrPatternSugar(MatchPatternSugar, role=SugarRole.PATTERN):
    patterns: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "MatchOr"

    @classmethod
    def new(cls, site, ctx) -> "MatchOrPatternSugar":
        return cls(
            patterns=tuple(
                ctx.build_body(pattern, SugarRole.PATTERN)
                for pattern in site.match_or_pattern_arms()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(self)

    def select_ground(self, subject, *, matched, missed, ctx) -> Outcome:
        return self._select_arm(self.patterns, subject, matched, missed, ctx)

    def _select_arm(self, patterns, subject, matched, missed, ctx) -> Outcome:
        if not patterns:
            return missed()
        head, *rest = patterns
        return head.reduce(ctx).and_then(
            lambda pattern: pattern.select_ground(
                subject,
                matched=matched,
                missed=lambda: self._select_arm(
                    tuple(rest), subject, matched, missed, ctx
                ),
                ctx=ctx,
            )
        )

    def walk_children(self):
        return self.patterns


@dataclass(frozen=True)
class MatchAsPatternSugar(MatchPatternSugar, role=SugarRole.PATTERN):
    pattern: SugarBody | None
    name: str | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "MatchAs"

    @classmethod
    def new(cls, site, ctx) -> "MatchAsPatternSugar":
        pattern = site.match_as_pattern_inner()
        return cls(
            pattern=(
                ctx.build_body(pattern, SugarRole.PATTERN)
                if pattern is not None
                else None
            ),
            name=site.match_as_pattern_name(),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(self)

    def select_ground(self, subject, *, matched, missed, ctx) -> Outcome:
        if self.pattern is None:
            return matched(self.name)
        return self.pattern.reduce(ctx).and_then(
            lambda pattern: pattern.select_ground(
                subject,
                matched=lambda capture: matched(self.name or capture),
                missed=missed,
                ctx=ctx,
            )
        )

    def walk_children(self):
        return () if self.pattern is None else (self.pattern,)
