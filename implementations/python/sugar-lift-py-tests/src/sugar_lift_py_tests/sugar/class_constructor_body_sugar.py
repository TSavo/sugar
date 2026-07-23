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
            from sugar_lift_py_tests.floor import CallSiteValue
            from sugar_lift_py_tests.ir import ctor, str_const

            call = CallSiteValue(
                target_name="python:source-class-init",
                arg_values=(),
                parameters=(),
                term=ctor(
                    "python:source-class-init",
                    [str_const(value.class_definition_cid)],
                    symbol_kind="coordinate",
                ),
                body=self.initializer_body,
            )
            block = call.force_floor(
                ctx,
                owner="ClassConstructorBodySugar.desugar",
                project_callsite=False,
            )
            return Complete(
                value.construct_receiver_state_from_block(
                    block, self.receiver_coordinate_cid
                )
            )

        return self.definition.desugar(ctx).and_then(construct)
