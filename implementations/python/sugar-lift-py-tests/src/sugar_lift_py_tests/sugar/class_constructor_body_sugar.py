from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def refuse_unrun_source_new(definition, *, new_method, runs_new, site, owner):
    """Refuse a class call that would skip the class's own source ``__new__``.

    ``Cls(...)`` is ``type.__call__``: it runs ``Cls.__new__`` first and only
    then ``type(obj).__init__`` on whatever object ``__new__`` returned.  A
    source ``__new__`` may return an instance of another class (pandas
    ``ExcelWriter.__new__`` returns ``object.__new__(get_writer(engine))``),
    so running ``Cls.__init__`` on a fresh ``Cls`` receiver constructs an
    object Python never builds.  The only ``__new__`` arm constructed today is
    the authenticated allocation-then-field-stores shape on a class without
    ``__init__``; every other source ``__new__`` refuses here by name.
    """
    if new_method is None or runs_new:
        return
    from sugar_source_tree.panic import SugarNotWritten

    class_name = getattr(definition, "class_name", type(definition).__name__)
    raise SugarNotWritten(
        blame=site,
        owner=owner,
        observed=(
            f"{class_name}.__new__ is source the class call does not run "
            "(its return value and the runtime class whose __init__ runs are "
            "not constructed)"
        ),
        requested=(
            "the object returned by source __new__, then __init__ dispatched "
            "on that object's runtime class"
        ),
        fix=(
            "construct the source __new__ return before __init__; never run "
            "__init__ on a fresh receiver of the called class"
        ),
    )


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
                project_authenticated_source_return,
            )

            returned = project_authenticated_source_return(block)
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
            refuse_unrun_source_new(
                value,
                new_method=self.constructed_new_method,
                runs_new=(
                    getattr(value, "initializer", None) is None
                    and self.initializer_body is not None
                ),
                site=self.site,
                owner="ClassConstructorBodySugar.__new__",
            )
            if self.initializer_body is None:
                return ExitSet.completed(
                    value.construct_receiver_state_from_block(
                        None, self.receiver_coordinate_cid
                    )
                )
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )
            from sugar_lift_py_tests.floor import BlockValue
            from sugar_lift_py_tests.floor import EllipsisValue
            from sugar_lift_py_tests.outcome import outcome_to_exitset
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
            # Constructor CallSiteValue formals omit ``self`` — they are the
            # class-call arguments. Zero-argument ``super()`` still needs the
            # PEP 3135 ``__class__`` cell and the bound first formal.
            # ``ClassDefinitionValue`` already carries both when ``__init__``
            # is invoked as a method; this door is the class call
            # ``RaisesExc(...)`` used by a factory ``return``.
            temporal = ctx.temporal.bind_value(
                self.receiver_coordinate_cid, receiver
            )
            from sugar_lift_py_tests.floor.class_definition_value import (
                ClassDefinitionValue,
            )

            if isinstance(value, ClassDefinitionValue):
                temporal = temporal.bind_value(
                    "__class__",
                    value,
                    blame=f"{value.class_name}.__init__",
                )
            if temporal.value_if_bound("self") is None:
                temporal = temporal.bind_value(
                    "self",
                    receiver,
                    blame=(
                        f"{value.class_name}.__init__"
                        if isinstance(value, ClassDefinitionValue)
                        else "ClassConstructorBodySugar.receiver"
                    ),
                )
            initializer_ctx = ctx.with_temporal(temporal)
            outcome = self.initializer_body.desugar(initializer_ctx)
            if isinstance(outcome, NativeOperationExitCarrierV1):
                return outcome
            outcome = outcome_to_exitset(outcome)
            # One unconditional completed face is the whole initializer; only
            # then does an ellipsis-only body mean a stub constructor.
            sole = outcome.completed_value() is not None

            def receiver_of(block):
                if not isinstance(block, BlockValue):
                    # Single-entry reduction (rare): wrap as a block of stores.
                    block = BlockValue((block,), can_fall_through=True)
                if (
                    sole
                    and block.statements
                    and all(
                        isinstance(statement, EllipsisValue)
                        for statement in block.statements
                    )
                ):
                    raise SugarNotWritten(
                        blame=self.site,
                        owner="ClassConstructorBodySugar.desugar",
                        observed="initializer body is EllipsisValue only",
                        requested=(
                            "one source-visible runtime initializer implementation"
                        ),
                        fix="keep overload-only or stub-only constructors typed loud",
                    )
                returned = project_new_return(value, block)
                if returned is not None:
                    return returned
                return value.construct_receiver_state_from_block(
                    block, self.receiver_coordinate_cid
                )

            # ``Cls(x)`` is a call: the initializer's halted faces are the
            # call's halted faces, each completed face its own receiver, under
            # its own guard, carrying what it owes. Packing them inside one
            # completed value hid the halts from the caller (#7756).
            return outcome.sequence(
                lambda block: ExitSet.completed(receiver_of(block))
            )

        # The class statement's one outcome: a module-level statement is
        # reduced once, and this call reads it (#7794).
        return self.definition.desugar(ctx).and_then(construct)
