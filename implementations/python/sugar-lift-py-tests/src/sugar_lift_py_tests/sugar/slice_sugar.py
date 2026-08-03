"""A slice `lower:upper:step` (as it appears in `xs[1:2]`, `xs[::2]`, ...).

A slice is a value: `slice(lower, upper, step)`. It reduces each present bound
and stands as the `py.slice` coordinate over their terms; an omitted bound is
`None` (its NoneValue term), exactly as Python fills it. The container's
subscript floor consumes this coordinate -- this only constructs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
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
        # slice bounds.  Sequence each present bound through ``and_then`` so
        # Incomplete short-circuits later desugars while ExitSet / pending
        # still thread.
        #
        # Pending parameter-contract demands on bounds (``xs[p[0]:]``) still
        # accumulate and re-attach via the same pending/rewrap door collections
        # use (#6352), without re-entering the eager map.
        from dataclasses import replace

        from sugar_lift_py_tests.caller_parameter_contract import merge_demands
        from sugar_lift_py_tests.floor.single_outcome_law import (
            pending_demand,
            rewrap_pending,
        )
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.outcome import true_guard
        from sugar_lift_py_tests.outcome.exit_set import factored_operand

        positions = (self.lower, self.upper, self.step)
        pending = None
        # Seed: no bounds reduced yet.  Each present bound desugars only after
        # the prior outcome continues (Complete / ExitSet completed arms).
        outcome: Outcome = Complete(())
        for bound in positions:
            if bound is None:
                # Omitted position: Python fills None; do not desugar.
                outcome = outcome.and_then(
                    lambda collected: Complete((*collected, None))
                )
                continue

            def _step(collected, bound_sugar=bound):
                nonlocal pending
                bound_out = bound_sugar.desugar(ctx)
                entry, plain = pending_demand(bound_out, true_guard())
                if entry is not None:
                    pending = (
                        entry
                        if pending is None
                        else replace(
                            pending,
                            demands=merge_demands(pending.demands, entry.demands),
                        )
                    )
                factored = factored_operand(plain)
                return factored.and_then(lambda value: Complete((*collected, value)))

            outcome = outcome.and_then(_step)

        built = outcome.and_then(
            lambda values: Complete(SliceValue(values[0], values[1], values[2]))
        )
        return rewrap_pending(pending, built, owner="SliceSugar", blame=str(self.site))
