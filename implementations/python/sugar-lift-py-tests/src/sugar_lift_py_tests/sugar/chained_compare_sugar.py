"""Evaluate a multi-operand Python Compare without re-evaluating its middle."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _boolop_wrapped_pair

if TYPE_CHECKING:
    from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
    from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar


@dataclass(frozen=True)
class ChainedCompareSugar(ConstructedTermSugar):
    """Adjacent comparison legs sharing each reduced middle operand."""

    values: tuple[ComparisonOpSugar | EqualityOpSugar, ...]
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        if len(self.values) < 2:
            self._panic(
                observed=f"{len(self.values)} comparison legs",
                requested="at least two ordered legs for a chained Compare",
                fix=(
                    "construct a single Compare leg directly; reserve "
                    "ChainedCompareSugar for len(ops) > 1"
                ),
            )
        for index, (left_leg, right_leg) in enumerate(
            zip(self.values, self.values[1:])
        ):
            if left_leg.right is not right_leg.left:
                self._panic(
                    observed=f"legs {index} and {index + 1} do not share one middle sugar",
                    requested="adjacent Compare legs sharing the same constructed middle operand",
                    fix=(
                        "construct all adjacent legs once at "
                        "Compare._construct_sugar and preserve operand identity"
                    ),
                )

    def _panic(self, *, observed: str, requested: str, fix: str) -> None:
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="ChainedCompareSugar",
            blame=self.site,
            observed=observed,
            requested=requested,
            fix=fix,
        )

    @classmethod
    def witnesses(cls):
        return _boolop_wrapped_pair(
            name="chained_compare",
            owner_sugar="ChainedCompareSugar",
            truthful="1 < 2 < 3",
            lying="3 < 2 < 1",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar

        return BoolOpSugar("And", self.values, self.site).to_term(owner=owner)

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        first = self.values[0]
        return factored_operand(first.left.desugar(ctx)).and_then(
            lambda left: self._reduce_from(0, left, ctx)
        )

    def _reduce_from(self, index: int, left, ctx: object) -> Outcome:
        from sugar_lift_py_tests.outcome.exit_set import factored_operand
        from sugar_lift_py_tests.sugar.bool_op_sugar import select_boolop_operand

        leg = self.values[index]

        def apply(right):
            compared = factored_operand(leg.apply_reduced(left, right, ctx))
            if index == len(self.values) - 1:
                return compared
            return compared.and_then(
                lambda value: select_boolop_operand(
                    value,
                    op_kind="And",
                    site=self.site,
                    index=index,
                    on_continue=lambda: self._reduce_from(index + 1, right, ctx),
                )
            )

        return factored_operand(leg.right.desugar(ctx)).and_then(apply)
