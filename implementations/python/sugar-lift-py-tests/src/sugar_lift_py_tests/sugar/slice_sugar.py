"""A slice `lower:upper:step` (as it appears in `xs[1:2]`, `xs[::2]`, ...).

A slice is a value: `slice(lower, upper, step)`. It reduces each present bound
and stands as the `py.slice` coordinate over their terms; an omitted bound is
`None` (its NoneValue term), exactly as Python fills it. The container's
subscript floor consumes this coordinate -- this only constructs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
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

    def desugar(self, ctx: object = None) -> ExitSet:
        # Bounds are ordinary operands evaluated **left-to-right**: lower, then
        # upper, then step.  A lower-bound halt must not evaluate upper/step
        # (Python source order), each under the state after the ones before it.
        # The one left-to-right operand fold (``reduce_operands``) sequences
        # each present bound through ``and_then`` so a halted arm
        # short-circuits later desugars while completed arms and pending
        # carriers still thread; an omitted position is ``None``, never
        # desugared.
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
        )
        from sugar_lift_py_tests.floor.slice_value import SliceValue

        outcome = reduce_operands(
            (self.lower, self.upper, self.step), ctx, factored=True
        )

        # The bounds are operands: a walrus in one binds once, through the one
        # operand door (an omitted bound is ``None`` and carries nothing).
        return outcome.and_then(
            lambda values: consume_operands(
                lambda lower, upper, step: ExitSet.completed(
                    SliceValue(lower, upper, step)
                ),
                *values,
            )
        )
