from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SliceValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SliceSugar(Sugar, role=SugarRole.TERM):
    """A general ``lower:upper:step`` construction.

    Every present bound is built and reduced through its own term owner. Missing
    bounds remain absent. An unowned bound reaches its own loud factory None arm.
    """

    lower: SugarBody | None
    upper: SugarBody | None
    step: SugarBody | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Slice"

    @classmethod
    def new(cls, site, ctx) -> "SliceSugar":
        return cls(
            lower=cls._build_bound(site.slice_lower(), ctx),
            upper=cls._build_bound(site.slice_upper(), ctx),
            step=cls._build_bound(site.slice_step(), ctx),
            site=site,
        )

    @staticmethod
    def _build_bound(bound, ctx) -> SugarBody | None:
        return ctx.build_body(bound, SugarRole.TERM) if bound is not None else None

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    xs = [1, 2, 3]\n"
            "    part = xs[z:]\n"
            "    return 1\n\n"
        )
        return _call_pair(
            name="general_slice_return",
            owner_sugar="SliceSugar",
            truthful=prefix + "def test_a():\n    assert A(1) == 1\n",
            lying=prefix + "def test_a():\n    assert A(1) == 2\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._reduce_bound(
            self.lower,
            ctx,
            lambda lower: self._reduce_bound(
                self.upper,
                ctx,
                lambda upper: self._reduce_bound(
                    self.step,
                    ctx,
                    lambda step: Complete(SliceValue(lower, upper, step)),
                ),
            ),
        )

    @staticmethod
    def _reduce_bound(body: SugarBody | None, ctx, continuation) -> Outcome:
        if body is None:
            return continuation(None)
        return body.reduce(ctx).and_then(continuation)

    def walk_children(self):
        return tuple(
            bound for bound in (self.lower, self.upper, self.step) if bound is not None
        )
