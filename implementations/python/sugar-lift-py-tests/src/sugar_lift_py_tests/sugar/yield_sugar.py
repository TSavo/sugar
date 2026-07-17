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
            value=(
                ctx.build_body(value, SugarRole.TERM) if value is not None else None
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness

        return typed_red_effect_witness(
            name="yield_runtime_effect",
            owner_sugar=cls.__name__,
            source="def A(z):\n    yield z\n",
            effect_class="GeneratorYieldRuntimeEffect",
            reason_needle="generator suspension is runtime-dependent",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="owner=AwaitSugar",
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
            runtime_effect_evidence_from_terms,
        )
        from sugar_lift_py_tests.ir import ctor, make_var

        resume_value = make_var(f"py.generator_resume@{self.site}")

        return Incomplete(
            GeneratorYieldRuntimeEffect(
                "generator suspension is runtime-dependent: "
                f"py.generator_yield(value={yielded!r}, "
                f"resume={resume_value!r}, locus={self.site})",
                **runtime_effect_evidence_from_terms(
                    ctor("py.generator_yield", [yielded]),
                    resume_value,
                    self.site,
                ),
            )
        )

    def walk_children(self):
        return (self.value,) if self.value is not None else ()
