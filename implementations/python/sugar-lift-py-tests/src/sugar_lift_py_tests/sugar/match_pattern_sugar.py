"""Factory-selected match-pattern sugars.

MatchSugar builds each case pattern through ``SugarRole.PATTERN``. Pattern
sugars own their AST shape via ``SourceFragment.observed`` and structural
accessors; ground selection is ``match_ground``. Unsupported residual patterns
stay loud under MatchSugar's construction-gap owner, never RuntimeEffect.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Protocol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


class MatchPattern(Protocol):
    """Closed surface MatchSugar consumes for ground pattern selection."""

    def match_ground(
        self, subject: object, match_site: object
    ) -> tuple[bool, str | None]: ...


_RESIDUAL_MATCH_PATTERNS = frozenset(
    {
        "MatchClass",
        "MatchSequence",
        "MatchMapping",
        "MatchStar",
    }
)


def _unsupported_match_pattern(observed: str, match_site: object) -> None:
    from sugar_lift_py_tests.factory import factory_panic_gap

    factory_panic_gap(
        owner="MatchSugar",
        blame=match_site,
        observed=observed,
        requested="constructible ground match pattern",
        fix=(
            f"construct `{observed}` matching from reduced pattern evidence; "
            "do not classify a ground construction gap as runtime"
        ),
    )


@dataclass(frozen=True)
class MatchValuePatternSugar(Sugar, role=SugarRole.PATTERN):
    """``case <constant>`` — ground equality against a Constant payload."""

    expected: object | None
    supported: bool
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "MatchValue"

    @classmethod
    def new(cls, site, ctx) -> "MatchValuePatternSugar":
        del ctx
        value = site.match_value()
        if value.observed in {"PrimitiveLiteral", "Constant"}:
            return cls(expected=value.literal_value(), supported=True, site=site)
        return cls(expected=None, supported=False, site=site)

    @classmethod
    def witnesses(cls):
        # Verdicts for literal patterns live on MatchSugar.
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import SupportValue

        return Complete(SupportValue())

    def match_ground(
        self, subject: object, match_site: object
    ) -> tuple[bool, str | None]:
        if not self.supported:
            _unsupported_match_pattern(self.site.observed, match_site)
        return subject == self.expected, None


@dataclass(frozen=True)
class MatchSingletonPatternSugar(Sugar, role=SugarRole.PATTERN):
    """``case True`` / ``case False`` / ``case None`` — identity match."""

    expected: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "MatchSingleton"

    @classmethod
    def new(cls, site, ctx) -> "MatchSingletonPatternSugar":
        del ctx
        return cls(expected=site.match_singleton_value(), site=site)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import SupportValue

        return Complete(SupportValue())

    def match_ground(
        self, subject: object, match_site: object
    ) -> tuple[bool, str | None]:
        del match_site
        return subject is self.expected, None


@dataclass(frozen=True)
class MatchOrPatternSugar(Sugar, role=SugarRole.PATTERN):
    """``case A | B | ...`` — first matching arm wins, source order."""

    arms: tuple[MatchPattern, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "MatchOr"

    @classmethod
    def new(cls, site, ctx) -> "MatchOrPatternSugar":
        return cls(
            arms=tuple(
                ctx.build_body(arm, SugarRole.PATTERN).sugar
                for arm in site.match_or_patterns()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import SupportValue

        return Complete(SupportValue())

    def match_ground(
        self, subject: object, match_site: object
    ) -> tuple[bool, str | None]:
        for arm in self.arms:
            matched, capture = arm.match_ground(subject, match_site)
            if matched:
                return True, capture
        return False, None


@dataclass(frozen=True)
class MatchAsPatternSugar(Sugar, role=SugarRole.PATTERN):
    """``case _`` / ``case name`` / ``case <pat> as name`` capture patterns."""

    name: str | None
    nested: MatchPattern | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "MatchAs"

    @classmethod
    def new(cls, site, ctx) -> "MatchAsPatternSugar":
        nested_site = site.match_as_pattern()
        return cls(
            name=site.match_as_name(),
            nested=(
                ctx.build_body(nested_site, SugarRole.PATTERN).sugar
                if nested_site is not None
                else None
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import SupportValue

        return Complete(SupportValue())

    def match_ground(
        self, subject: object, match_site: object
    ) -> tuple[bool, str | None]:
        if self.nested is None:
            return True, self.name
        matched, capture = self.nested.match_ground(subject, match_site)
        if not matched:
            return False, None
        return True, self.name if self.name else capture


@dataclass(frozen=True)
class ResidualMatchPatternSugar(Sugar, role=SugarRole.PATTERN):
    """Unsupported match-pattern shapes: loud construction gap, not runtime."""

    observed: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed in _RESIDUAL_MATCH_PATTERNS

    @classmethod
    def new(cls, site, ctx) -> "ResidualMatchPatternSugar":
        del ctx
        return cls(observed=site.observed, site=site)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import SupportValue

        return Complete(SupportValue())

    def match_ground(
        self, subject: object, match_site: object
    ) -> tuple[bool, str | None]:
        del subject
        _unsupported_match_pattern(self.observed, match_site)
        raise AssertionError("factory_panic_gap must not return")
