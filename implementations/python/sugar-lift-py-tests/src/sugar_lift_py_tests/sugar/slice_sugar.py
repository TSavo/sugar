"""A slice `lower:upper:step` (as it appears in `xs[1:2]`, `xs[::2]`, ...).

A slice is a value: `slice(lower, upper, step)`. It reduces each present bound
and stands as the `py.slice` coordinate over their terms; an omitted bound is
`None` (its NoneValue term), exactly as Python fills it. The container's
subscript floor consumes this coordinate -- this only constructs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet, Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class SliceSugar(ConstructedTermSugar):
    lower: ConstructedTermSugar | None
    upper: ConstructedTermSugar | None
    step: ConstructedTermSugar | None
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for name, bound in (
            ("lower", self.lower),
            ("upper", self.upper),
            ("step", self.step),
        ):
            if bound is not None:
                require_constructed_term_sugar(bound, owner=f"SliceSugar.{name}")

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        def bound_term(bound):
            return (
                ctor("python:omitted-slice-bound", ())
                if bound is None
                else bound.to_term(owner=owner)
            )

        return ctor(
            "python:slice-construction",
            (
                self.occurrence_term(owner=owner),
                bound_term(self.lower),
                bound_term(self.upper),
                bound_term(self.step),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Bounds are ordinary operands evaluated **left-to-right**: lower, then
        # upper, then step.  A lower-bound halt must not evaluate upper/step
        # (Python source order).  Collection ``_reduce_into`` eagerly maps
        # ``desugar`` over every element before folding — that is wrong for
        # slice bounds.  Sequence each present bound through ``and_then`` so a
        # halted arm short-circuits later desugars while completed arms and
        # pending carriers still thread.
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        positions = (self.lower, self.upper, self.step)
        # Seed: no bounds reduced yet.  Each present bound desugars only after
        # the prior outcome continues (its completed arms).
        outcome: Outcome = ExitSet.completed(())
        for bound in positions:
            if bound is None:
                # Omitted position: Python fills None; do not desugar.
                outcome = outcome.and_then(
                    lambda collected: ExitSet.completed((*collected, None))
                )
                continue

            def _step(collected, bound_sugar=bound):
                factored = factored_operand(bound_sugar.desugar(ctx))
                return factored.and_then(
                    lambda value: ExitSet.completed((*collected, value))
                )

            outcome = outcome.and_then(_step)

        # The bounds are operands: a walrus in one binds once, through the one
        # operand door (an omitted bound is ``None`` and carries nothing).
        from sugar_lift_py_tests.floor.named_expression_value import consume_operands

        return outcome.and_then(
            lambda values: consume_operands(
                lambda lower, upper, step: ExitSet.completed(
                    SliceValue(lower, upper, step)
                ),
                *values,
            )
        )
