from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
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
    # The class value this call read the class statement's one outcome as
    # (``enter``): set on the body a class call binds, so the initializer is
    # entered on that value and the statement is read once per call.
    class_value: object | None = field(default=None, compare=False)
    # The inherited-exception frame's ``*args`` formal coordinate
    # (``ClassDef.source_visible_constructor_frame``): a class whose
    # constructor is BaseException's.  ``BaseException_new`` stores the
    # call's positional actuals as ``args`` (Objects/exceptions.c), so the
    # instance the call makes carries them.
    exception_args_coordinate_cid: str | None = field(default=None, compare=False)
    # The initializer's first positional formal as its ``def`` declares it
    # (``__init__(this, ...)`` declares ``this``): the frame local the fresh
    # receiver is, which a zero-argument ``super()`` in the body reads
    # (``builtin_semantic_callable.zero_argument_super_receiver``).  None when
    # the initializer has no positional formal, or the body is not a source
    # ``__init__`` (a dataclass's generated stores, a source ``__new__``).
    receiver_formal: str | None = field(default=None, compare=False)

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

    def desugar(self, ctx: object = None) -> ExitSet:
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

        def initialize(value, initializer_ctx):
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )
            from sugar_lift_py_tests.floor import BlockValue
            from sugar_lift_py_tests.floor import EllipsisValue
            from sugar_source_tree.panic import SugarNotWritten

            # The outer CallSiteValue.force_floor already curried constructor
            # formals into ``ctx`` (formal_coordinate_cids → actuals). Reduce the
            # initializer under that ctx directly. A nested empty CallSiteValue
            # (parameters=(), arg_values=()) was previously used as a force_floor
            # wrapper; after store ExitSet composition, that path left
            # BindingCoordinateRef formals unbound and raised bare
            # SugarNotWritten during source-derived manager construction.
            outcome = self.initializer_body.desugar(initializer_ctx)
            if isinstance(outcome, NativeOperationExitCarrierV1):
                return outcome
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

        return self.enter_initializer(ctx, initialize)

    def enter(self, ctx, step, *, at_call=False, call_site=None) -> ExitSet:
        """The class statement's one outcome, read once per class call
        (#7794): its halted faces and what its arms owe are the call's, never
        dropped.  On each completed face, ``step(value, body)``: ``value`` the
        class value, ``body`` this constructor entered on it, whose
        ``enter_initializer`` reads that value and not the statement again.
        A body already entered answers ``step`` on its class value.

        ``at_call``: read by the class call's own door (``bind_class_call``)
        at ``call_site``, as the body's application read it before
        (``CallSiteValue.producer_outcome``): in the call's frame
        (``occurrence.call_frame_path``), its halts the Call's own faces
        (``call_site_value.call_owned``)."""
        if self.class_value is not None:
            return step(self.class_value, self)
        from dataclasses import replace

        if at_call and call_site is not None:
            from sugar_lift_py_tests.occurrence import (
                call_frame_path,
                current_path,
                occurrence_path,
            )

            with occurrence_path(call_frame_path(call_site, current_path())):
                statement = self.definition.desugar(ctx)
        else:
            # A module-level statement is reduced once, and this reads it.
            statement = self.definition.desugar(ctx)
        if at_call:
            from sugar_lift_py_tests.floor.call_site_value import (
                at_the_call,
                call_owned,
            )
            from sugar_lift_py_tests.outcome import Halted

            # The class statement's halt leaves it at the call, in the
            # caller's record there (``at_the_call``).
            statement = ExitSet(
                tuple(
                    Halted(
                        exit_.guard,
                        call_owned(exit_.effect),
                        at_the_call(ctx),
                        exit_.faces,
                        exit_.owed,
                    )
                    if isinstance(exit_, Halted)
                    else exit_
                    for exit_ in statement.exits
                )
            )
        return statement.and_then(
            lambda value: step(value, replace(self, class_value=value))
        )

    def bind_class_call(self, ctx, bind, *, site) -> ExitSet:
        """THE class call ``Cls(...)`` at ``site``: the class statement's one
        outcome is read (``enter``), and on each completed face the call is
        bound and applied by ``bind(defaults, body)``.

        ``defaults`` are the ``(key, value)`` pairs the class value carries
        for its constructor (``ClassDefinitionValue.constructor_defaults``):
        what the ``__init__`` / ``__new__`` ``def`` statement evaluated when
        its class body ran.  ``bind`` hands them to ``object_value.bind_call``
        (``defaults``), so a formal the call omits binds that value
        (``DefaultValueSugar``), never its default expression evaluated at
        the call.  ``body`` is this constructor entered on the class value,
        the body the bound call applies."""
        return self.enter(
            ctx,
            lambda value, body: bind(constructor_defaults(value), body),
            at_call=True,
            call_site=site,
        )

    def enter_initializer(self, ctx, initialize) -> ExitSet:
        """THE class call up to its ``__init__``: the one place a receiver is
        made for an initializer to run on.

        The class statement's one outcome is read (#7794, ``enter``): by the
        class call that bound this body (``bind_class_call``), else here.  On
        each completed face, an unrun source ``__new__`` is refused by name, the
        fresh receiver is seated at the receiver coordinate with the PEP 3135
        ``__class__`` cell and the initializer's declared receiver formal
        (``receiver_formal``), and ``initialize(value, ctx)`` runs
        the initializer in that context.  A class with no initializer
        completes with the fresh receiver itself.

        ``desugar`` passes the class call's initializer body; an ``__init__``
        universe (``tree_enumerate.function_universe_outcome``) passes the
        initializer's own universe, so it runs on the receiver the class call
        makes and carries every halt the class call has before ``__init__``.
        """

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
            receiver = value.construct_receiver_state_from_block(
                None, self.receiver_coordinate_cid
            )
            if self.initializer_body is None:
                if self.exception_args_coordinate_cid is not None:
                    receiver = self._carrying_exception_args(receiver, ctx)
                return ExitSet.completed(receiver)
            # Constructor CallSiteValue formals omit the receiver formal — they
            # are the class-call arguments. Zero-argument ``super()`` still
            # needs the PEP 3135 ``__class__`` cell and the bound first
            # formal, under the name the initializer declares it
            # (``receiver_formal``), never a spelling (#7757).
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
            if self.receiver_formal is not None:
                # The initializer's own frame local: it shadows whatever an
                # enclosing frame binds under the same name.
                temporal = temporal.bind_value(
                    self.receiver_formal,
                    receiver,
                    blame=(
                        f"{value.class_name}.__init__"
                        if isinstance(value, ClassDefinitionValue)
                        else "ClassConstructorBodySugar.receiver"
                    ),
                )
            return initialize(value, ctx.with_temporal(temporal))

        return self.enter(ctx, lambda value, _body: construct(value))

    def _carrying_exception_args(self, receiver, ctx):
        """``receiver`` with ``args``: the tuple the frame's ``*args`` formal
        bound, which is every positional actual of the call.  A formal the
        call did not bind is refused by name, never read as empty."""
        from dataclasses import replace

        from sugar_lift_py_tests.floor import ObjectField, ObjectValue, TupleValue
        from sugar_source_tree.panic import SugarNotWritten

        args = ctx.temporal.value_if_bound(self.exception_args_coordinate_cid)
        if type(args) is not TupleValue or not isinstance(receiver, ObjectValue):
            raise SugarNotWritten(
                blame=self.site,
                owner="ClassConstructorBodySugar.exception_args",
                observed=(
                    f"{type(args).__name__} bound at the *args formal of a "
                    f"{type(receiver).__name__} receiver"
                ),
                requested="the call's positional actuals as one tuple",
                fix="bind the inherited-exception frame's *args before construction",
            )
        return replace(receiver, fields=(*receiver.fields, ObjectField("args", args)))


def constructor_defaults(value) -> tuple:
    """The ``(key, value)`` pairs a class call binds where it binds its
    actuals: each method default the class value and every class of its
    MRO carries (``ClassDefinitionValue.constructor_defaults``), among them
    its ``__init__``'s, own or inherited, and its source ``__new__``'s.  A
    class value that is no source class statement's carries none."""
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )

    if not isinstance(value, ClassDefinitionValue):
        return ()
    return value.constructor_defaults()
