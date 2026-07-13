from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class YieldSugar(Sugar, role=SugarRole.TERM):
    value: SugarBody | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Yield" and site.has_enclosing_function()

    @classmethod
    def new(cls, site, ctx) -> "YieldSugar":
        value = site.yield_value()
        return cls(
            value=(ctx.build_body(value, SugarRole.TERM) if value is not None else None),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="GeneratorYieldRuntimeEffect",
            reason="yield suspends a deferred generator at a runtime protocol boundary",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if self.value is None:
            from sugar_lift_py_tests.ir import ctor

            return self._effect(ctor("None", []))
        return self.value.reduce(ctx).and_then(
            lambda value: self._effect(value.to_term(owner=str(self.site)))
        )

    def _effect(self, yielded) -> Incomplete:
        from sugar_lift_py_tests.effect import (
            GeneratorYieldRuntimeEffect,
            RuntimeEffectWitness,
        )
        from sugar_lift_py_tests.ir import ctor

        return Incomplete(
            GeneratorYieldRuntimeEffect(
                "generator suspension is runtime-dependent: "
                f"py.generator_yield(value={yielded!r}, locus={self.site})",
                witness=RuntimeEffectWitness(
                    operation=ctor("py.generator_yield", [yielded]),
                    operand=yielded,
                    locus=str(self.site),
                ),
            )
        )

    def walk_children(self):
        return (self.value,) if self.value is not None else ()
