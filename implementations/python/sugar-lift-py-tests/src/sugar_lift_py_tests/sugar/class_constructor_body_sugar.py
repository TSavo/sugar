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
    constructed_new_method: object | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.constructed_new_method is None:
            return
        from sugar_lift_py_tests.floor.class_definition_value import (
            ConstructedClassMethodV1,
        )
        from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1

        method = self.constructed_new_method
        if (
            type(method) is not ConstructedClassMethodV1
            or type(method.source_call_frame) is not SourceVisibleCallFrameV1
            or method.definition_fragment_cid
            != method.source_call_frame.definition_fragment_cid
        ):
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

            raise SourceCallBindingGap(
                "constructor body carries malformed __new__ method testimony"
            )

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
            from sugar_lift_py_tests.floor import (
                EllipsisValue,
                ReceiverStatePartitionValue,
            )
            from sugar_lift_py_tests.outcome import Incomplete
            from sugar_lift_py_tests.outcome import Completed, Halted
            from sugar_lift_py_tests.outcome.exit_set import ExitSet
            from sugar_source_tree.panic import SugarNotWritten

            # The outer CallSiteValue.force_floor already curried constructor
            # formals into ``ctx`` (formal_coordinate_cids → actuals). Reduce the
            # initializer under that ctx directly. A nested empty CallSiteValue
            # (parameters=(), arg_values=()) was previously used as a force_floor
            # wrapper; after store ExitSet composition, that path left
            # BindingCoordinateRef formals unbound and raised bare
            # SugarNotWritten during source-derived manager construction.
            receiver = value.construct_receiver_state_from_block(
                None, self.receiver_coordinate_cid
            )
            initializer_ctx = ctx.with_temporal(
                ctx.temporal.bind_value(self.receiver_coordinate_cid, receiver)
            )
            outcome = self.initializer_body.desugar(initializer_ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            if isinstance(outcome, ExitSet):
                projected = []
                for face in outcome.exits:
                    if isinstance(face, Halted):
                        projected.append(face)
                        continue
                    assert isinstance(face, Completed)
                    block = face.value
                    if not isinstance(block, BlockValue):
                        block = BlockValue((block,), can_fall_through=True)
                    projected.append(
                        Completed(
                            face.guard,
                            value.construct_receiver_state_from_block(
                                block, self.receiver_coordinate_cid
                            ),
                            face.faces,
                            face.pending_contracts,
                        )
                    )
                return Complete(
                    ReceiverStatePartitionValue(ExitSet(tuple(projected)).normalize())
                )
            if not isinstance(outcome, Complete):
                return outcome
            block = outcome.value
            if not isinstance(block, BlockValue):
                # Single-entry reduction (rare): wrap as a block of stores.
                block = BlockValue(
                    (block,),
                    can_fall_through=True,
                )
            if block.statements and all(
                isinstance(statement, EllipsisValue) for statement in block.statements
            ):
                raise SugarNotWritten(
                    blame=self.site,
                    owner="ClassConstructorBodySugar.desugar",
                    observed="initializer body is EllipsisValue only",
                    requested="one source-visible runtime initializer implementation",
                    fix="keep overload-only or stub-only constructors typed loud",
                )
            return Complete(
                value.construct_receiver_state_from_block(
                    block, self.receiver_coordinate_cid
                )
            )

        return self.definition.desugar(ctx).and_then(construct)
