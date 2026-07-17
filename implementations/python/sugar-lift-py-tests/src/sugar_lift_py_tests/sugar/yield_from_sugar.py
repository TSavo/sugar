from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class YieldFromSugar(Sugar, role=SugarRole.TERM):
    """One generator delegation expression inside a function body."""

    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "YieldFrom" and site.has_enclosing_function()

    @classmethod
    def new(cls, site, ctx) -> "YieldFromSugar":
        value = site.yield_value()
        if value is None:
            raise TypeError("YieldFrom always carries a delegated expression")
        return cls(
            value=ctx.build_body(value, SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="yield_from_runtime_effect",
            owner_sugar=cls.__name__,
            source="def A(items):\n    yield from items\n",
            effect_class="GeneratorYieldRuntimeEffect",
            reason_needle="generator delegation suspension is runtime-dependent",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="owner=AwaitSugar",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.reduce(ctx).and_then(
            lambda value: self._effect(value.to_term(owner=str(self.site)))
        )

    def _effect(self, delegated) -> Incomplete:
        from sugar_lift_py_tests.effect import (
            GeneratorYieldRuntimeEffect,
            runtime_effect_evidence_from_terms,
        )
        from sugar_lift_py_tests.ir import ctor

        return Incomplete(
            GeneratorYieldRuntimeEffect(
                "generator delegation suspension is runtime-dependent: "
                f"py.generator_yield_from(value={delegated!r}, locus={self.site})",
                **runtime_effect_evidence_from_terms(
                    ctor("py.generator_yield_from", [delegated]),
                    delegated,
                    self.site,
                ),
            )
        )

    def walk_children(self):
        return (self.value,)
