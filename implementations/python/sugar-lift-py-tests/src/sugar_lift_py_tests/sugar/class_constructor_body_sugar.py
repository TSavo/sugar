from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ClassConstructorBodySugar(Sugar):
    definition: Sugar
    initializer_body: Sugar | None
    receiver_coordinate_cid: str | None
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ObjectValue",
            reason="a class call projects its ordinary definition and initializer",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        def construct(value):
            if self.initializer_body is None:
                return Complete(
                    value.construct_receiver_state_from_block(
                        None, self.receiver_coordinate_cid
                    )
                )
            from sugar_lift_py_tests.floor import BlockValue
            from sugar_lift_py_tests.outcome import Incomplete
            from sugar_lift_py_tests.outcome.exit_set import ExitSet

            # The outer CallSiteValue.force_floor already curried constructor
            # formals into ``ctx`` (formal_coordinate_cids → actuals). Reduce the
            # initializer under that ctx directly. A nested empty CallSiteValue
            # (parameters=(), arg_values=()) was previously used as a force_floor
            # wrapper; after store ExitSet composition, that path left
            # BindingCoordinateRef formals unbound and raised bare
            # SugarNotWritten during source-derived manager construction.
            outcome = self.initializer_body.desugar(ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            if isinstance(outcome, ExitSet):
                collapsed = outcome.collapse()
                if not isinstance(collapsed, Complete):
                    return outcome
                outcome = collapsed
            if not isinstance(outcome, Complete):
                return outcome
            block = outcome.value
            if not isinstance(block, BlockValue):
                # Single-entry reduction (rare): wrap as a block of stores.
                block = BlockValue(
                    (block,),
                    can_fall_through=True,
                )
            return Complete(
                value.construct_receiver_state_from_block(
                    block, self.receiver_coordinate_cid
                )
            )

        return self.definition.desugar(ctx).and_then(construct)
