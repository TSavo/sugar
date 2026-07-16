from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from dataclasses import replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class EqualityOpSugar(Sugar, role=SugarRole.TERM):
    """The `==` operator. One of the comparison family (`!=`, `<`, ... are their own
    sugars, their own types -- no operator field to switch on). It reduces both sides
    and asks the left whether it equals the right: the left stands on the equals floor
    and gives back a True or False literal."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["Eq"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "EqualityOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        start = len(ctx.module_rewrite_log)
        outcome = self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.equals(right, self.site)
            )
        )
        rewrites = ctx.module_rewrite_log[start:]
        ground_rewrites = [rewrite for rewrite in rewrites if rewrite[4] is not None]
        if len(ground_rewrites) >= 2 and not ctx.prefer_ground_module_bindings:
            rerun_start = len(ctx.module_rewrite_log)
            ground_ctx = replace(ctx, prefer_ground_module_bindings=True)
            outcome = self.left.reduce(ground_ctx).and_then(
                lambda left: self.right.reduce(ground_ctx).and_then(
                    lambda right: left.equals(right, self.site)
                )
            )
            del ctx.module_rewrite_log[rerun_start:]

        from sugar_lift_py_tests.floor import PredicateValue
        from sugar_lift_py_tests.outcome import Complete

        if isinstance(outcome, Complete) and isinstance(outcome.value, PredicateValue):
            chains = tuple(
                (f"{name} = {replacement}", path, line)
                for name, replacement, path, line, _ground in rewrites
            )
            outcome = Complete(replace(outcome.value, rewrite_chains=chains))
        return outcome

    def walk_children(self):
        return (self.left, self.right)
