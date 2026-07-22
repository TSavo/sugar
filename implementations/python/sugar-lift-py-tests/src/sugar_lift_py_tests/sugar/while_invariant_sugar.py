"""The invariant stated by an assert-only symbolic ``while`` body."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class WhileInvariantSugar(Sugar):
    test: Sugar
    body: tuple
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import implies
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements

        condition = self.test.desugar(ctx)
        if isinstance(condition, Incomplete):
            return condition
        formula = getattr(
            getattr(condition.value.truth(self.site), "value", None), "formula", None
        )
        if formula is None:
            raise NotImplementedError(
                "symbolic while invariant requires a predicate condition"
            )

        entries, _falls, _ft = reduce_statements(self.body)
        wrapped = []
        for entry in entries:
            site = getattr(entry, "site", None) or self.site
            wrapped.extend(
                InvValue(implies(formula, fact), site)
                for fact in entry.inv_contribution()
            )
        return Complete(BlockValue(tuple(wrapped), can_fall_through=True))
