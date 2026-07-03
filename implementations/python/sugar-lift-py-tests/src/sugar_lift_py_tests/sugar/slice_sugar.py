from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import FloorValue, SliceValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import slice_string_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SliceSugar(Sugar, role=SugarRole.TERM):
    lower: SugarBody | None
    upper: SugarBody | None
    step: SugarBody | None

    def __post_init__(self) -> None:
        for name, body in (
            ("lower", self.lower),
            ("upper", self.upper),
            ("step", self.step),
        ):
            if body is not None and not isinstance(body, SugarBody):
                raise TypeError(f"SliceSugar {name} must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Slice"

    @classmethod
    def build(cls, site, ctx) -> "SliceSugar":
        sugar = cls.from_site(
            site,
            lower=_build_optional(site.slice_lower(), ctx),
            upper=_build_optional(site.slice_upper(), ctx),
            step=_build_optional(site.slice_step(), ctx),
        )
        if sugar is None:
            raise TypeError("SliceSugar claim built a non-slice")
        return sugar

    @classmethod
    def witnesses(cls):
        return slice_string_return_witness()

    @classmethod
    def from_site(
        cls,
        site,
        *,
        lower: SugarBody | None,
        upper: SugarBody | None,
        step: SugarBody | None,
    ) -> "SliceSugar | None":
        if site.observed != "Slice":
            return None
        return cls(lower=lower, upper=upper, step=step)

    def desugar(self, ctx) -> Outcome:
        lower = _reduce_optional(self.lower, ctx, "lower")
        if isinstance(lower, Incomplete):
            return lower
        upper = _reduce_optional(self.upper, ctx, "upper")
        if isinstance(upper, Incomplete):
            return upper
        step = _reduce_optional(self.step, ctx, "step")
        if isinstance(step, Incomplete):
            return step
        return Complete(SliceValue(lower=lower, upper=upper, step=step))


def _build_optional(site, ctx) -> SugarBody | None:
    if site is None:
        return None
    return ctx.build_body(site, SugarRole.TERM)


def _reduce_optional(
    body: SugarBody | None, ctx, name: str
) -> FloorValue | Incomplete | None:
    if body is None:
        return None
    outcome = body.reduce(ctx)
    if isinstance(outcome, Incomplete):
        return outcome
    return complete_value(outcome, owner=f"SliceSugar {name}")
