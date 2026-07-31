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
        def project_new_return(definition, block):
            """Return the shadow receiver state produced by source ``__new__``.

            ``ReceiverFieldStoreStateSugar`` updates the immutable receiver in
            the substituted method body.  Re-scanning that body for the old
            ReceiverFieldStoreValue statement shape discards the constructed
            return and recreates the pre-store receiver.  Only the authenticated
            source ``__new__`` arm may return this value; ``__init__`` keeps its
            ordinary receiver-construction path below.
            """
            if (
                self.constructed_new_method is None
                or definition.initializer is not None
            ):
                return None
            from sugar_lift_py_tests.floor import ObjectValue
            from sugar_lift_py_tests.floor.source_return_projection import (
                project_authenticated_receiver_mutation_chain,
                project_authenticated_source_return,
            )

            returned = project_authenticated_source_return(block)
            if returned is block:
                returned = project_authenticated_receiver_mutation_chain(block)
            if (
                returned is block
                and len(block.statements) == 1
                and isinstance(block.statements[0], ObjectValue)
            ):
                # reduce_body has already projected the sole ReturnValue and
                # retained its value as the block's only completed statement.
                returned = block.statements[0]
            if (
                isinstance(returned, ObjectValue)
                and getattr(returned.defining_class, "class_definition_cid", None)
                == definition.class_definition_cid
            ):
                return returned
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=self.site,
                owner="ClassConstructorBodySugar.__new__",
                observed=type(returned).__name__,
                requested="the authenticated immutable receiver returned by source __new__",
                fix="preserve the shadow receiver binding through the source return",
            )

        def construct(value):
            if self.initializer_body is None:
                return Complete(
                    value.construct_receiver_state_from_block(
                        None, self.receiver_coordinate_cid
                    )
                )
            from sugar_lift_py_tests.floor import BlockValue
            from sugar_lift_py_tests.floor import EllipsisValue
            from sugar_lift_py_tests.outcome import Incomplete
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
                if self.constructed_new_method is not None and value.initializer is None:
                    projected = []
                    for face in outcome.exits:
                        if isinstance(face, Halted):
                            projected.append(face)
                            continue
                        assert isinstance(face, Completed)
                        block = face.value
                        if not isinstance(block, BlockValue):
                            block = BlockValue((block,), can_fall_through=True)
                        returned = project_new_return(value, block)
                        projected.append(
                            Completed(
                                face.guard,
                                (
                                    returned
                                    if returned is not None
                                    else value.construct_receiver_state_from_block(
                                        block, self.receiver_coordinate_cid
                                    )
                                ),
                                face.faces,
                                face.pending_contracts,
                            )
                        )
                    return Complete(
                        ReceiverStatePartitionValue(
                            ExitSet(tuple(projected)).normalize()
                        )
                    )
                return value.project_initializer_outcome(
                    outcome, receiver, self.receiver_coordinate_cid
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
            returned = project_new_return(value, block)
            if returned is not None:
                return Complete(returned)
            return value.project_initializer_outcome(
                Complete(block), receiver, self.receiver_coordinate_cid
            )

        return self.definition.desugar(ctx).and_then(construct)
