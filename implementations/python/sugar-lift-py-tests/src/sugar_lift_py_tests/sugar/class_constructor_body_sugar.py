from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ReceiverAtReturnValue(FloorValue):
    """What a ``return`` of a class call's initializer leaves with, as the
    class call reads it: the receiver as it stood at that ``return``
    (``InitializerReturnSugar``), and the value the ``return`` names
    (``returned``: ``None`` for a bare ``return``), from the ``return`` at
    ``site``.  The call returns that object on the face that leaves by the
    ``return`` (``ClassConstructorBodySugar``) when ``returned`` is
    ``None``, and raises CPython's ``TypeError: __init__() should return
    None`` when it is not; never the value itself.

    ``past_exits``: the read (unreduced) of the receiver past the code that
    runs after the ``return`` before the frame is left -- a ``finally``'s
    stores on ``self``, a ``with``'s exit -- where that code touches it
    (``nodes._receiver_past_exits``).  That code runs after the ``return``
    is reduced, so the class call reads it where the face ends, in the
    context that code left (``ClassConstructorBodySugar._leaving_by``)."""

    receiver: FloorValue
    returned: object = None
    site: object = field(default=None, compare=False)
    past_exits: object = field(default=None, compare=False)

    def to_term(self, *, owner: str):
        return self.receiver.to_term(owner=owner)


@dataclass(frozen=True)
class InitializerReturnSugar(Sugar):
    """A ``return`` of a class call's initializer (``nodes.InitializerReturn``):
    its value is evaluated, as any ``return``'s is, and it leaves with the
    receiver read where it stands -- after every store and call before it,
    and after the stores its own value's calls carry (``written_by``) --
    which the read after the initializer's last statement is not."""

    value: Sugar | None
    receiver: Sugar
    site: object = field(compare=False)
    # The receiver's read past the code that runs after the ``return``
    # (``ReceiverAtReturnValue.past_exits``), reduced where the face ends.
    past_exits: Sugar | None = None
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ReturnValue",
            reason="a class call reads the receiver its return leaves with",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
            written_by,
        )
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.return_value import ReturnValue

        def leaving(at, returned):
            return self.receiver.desugar(at).and_then(
                lambda receiver: ExitSet.completed(
                    ReturnValue(
                        ReceiverAtReturnValue(
                            peel_walrus_binds(receiver)[1],
                            returned,
                            self.site,
                            self.past_exits,
                        )
                    )
                )
            )

        if self.value is None:
            return leaving(ctx, NoneValue())
        return self.value.desugar(ctx).and_then(
            lambda value: leaving(written_by(value, ctx), peel_walrus_binds(value)[1])
        )


def _returns_none(value, site) -> "bool | None":
    """Whether the value an initializer ``return`` names is ``None``, as
    ``value is None`` decides it (``object_identity.object_identity``, the
    one place ``is`` is asked of objects): True or False where decided,
    None where not.  A ``return`` that names nothing (``returned`` unset)
    returns ``None``.  A call's value is read as an operation reads it
    (``CallSiteValue.project_operation_receiver``: its body's one
    authenticated return), else it stays undecided."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.none_value import NoneValue

    if isinstance(value, CallSiteValue):
        value = value.project_operation_receiver(
            None, owner="ClassConstructorBodySugar.init_return"
        )
    if value is None or type(value) is NoneValue:
        return True
    from sugar_lift_py_tests.floor.object_identity import object_identity
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    if type(value) is TrueBoolLiteralSugar or type(value) is FalseBoolLiteralSugar:
        return False
    if not callable(getattr(value, "callsites", None)):
        # No reduced value the identity question can name: undecided.
        return None
    answer = object_identity(value, NoneValue(), site).completed_value()
    if type(answer) is TrueBoolLiteralSugar:
        return True
    if type(answer) is FalseBoolLiteralSugar:
        return False
    return None


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
    # The class statement this is the constructor of: its sugar, the body's
    # identity.  Never reduced here (#7757 item 21): the class is the value
    # the statement bound under its evaluation key (``class_value``).
    definition: Sugar
    initializer_body: Sugar | None
    receiver_coordinate_cid: str | None
    site: object = field(compare=False)
    constructed_new_method: object | None = field(default=None, compare=False)
    # The class this constructor is entered on (``enter``): the value the
    # class statement bound under its evaluation key, which a read of the
    # class's name answered.  Set where the constructor is entered: by the
    # class call, on its callee
    # (``ClassDefinitionValue.callable_application_with``), and by an
    # ``__init__``'s own universe, on the read of the statement's key in the
    # state the module's one run left
    # (``tree_enumerate.function_universe_outcome``).  None on the frame's
    # own body (``ClassDef.source_visible_constructor_frame``), which is
    # entered on no class and refuses by name.
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
    # The class statement whose body defines the function this body runs:
    # the PEP 3135 ``__class__`` cell a zero-argument ``super()`` in it reads.
    # The class whose ``__init__`` the call runs -- for an inherited one, the
    # base that wrote it (``ClassDef.initializer_entry``), never the called
    # class; the class itself for its own ``__new__``.  None when the body is
    # no source function's (a dataclass's generated stores have no cell).
    cell_class_definition: object | None = field(default=None, compare=False)
    # The object the class call returns: a read of the receiver after the
    # initializer's last statement (``nodes._read_where_the_body_ends``),
    # reduced in the context the initializer's end record left
    # (``_receiver_where_it_ends``) -- after every store on it, after every
    # call the one exposure rule lets reach it, by the object's identity and
    # never by the formal's name.  A face that leaves by a ``return`` reads
    # the receiver that ``return`` carries (``InitializerReturnSugar``).
    # None when no initializer binds the receiver by name (a source
    # ``__new__`` returns its own).
    receiver_at_end: Sugar | None = field(default=None, compare=False)
    # The class call's own site, set where the call enters this body on its
    # class value (``ClassDefinitionValue.callable_application_with``): the
    # construction that makes the instance in
    # the calling frame (``object_identity.made_at``), its ``allocation``.
    # None when no class call of the reading frame entered it (an
    # initializer's own universe): that receiver reached ``__init__`` by
    # binding and its fields are not current.
    call_site: object | None = field(default=None, compare=False)
    # The class's own ``def __new__`` whose result the call returns as it is
    # (``ClassDef.returned_new``): the frame's formal coordinates, its
    # formals after ``cls``, in order.  The call runs that ``__new__`` on
    # the actuals bound there (``_returned_by_new``).  None for every other
    # constructor.
    returned_new_formal_cids: tuple | None = field(default=None, compare=False)

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
            """The receiver the authenticated source ``__new__`` returns.

            The body seated for it is everything ``__new__`` runs after its
            allocation -- its field stores and its ``return``
            (``ClassDef._source_visible_body``) -- so the value is what that
            ``return`` returns, the one authenticated return of the block
            (``project_authenticated_source_return``): the receiver after
            the stores.  A block is never read as the return, and no
            statement of it stands for one.  Only the authenticated source
            ``__new__`` arm may return this value; an ``__init__`` call
            returns its receiver as the initializer left it
            (``_receiver_where_it_ends``).
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
            from sugar_lift_py_tests.sugar.function_universe_sugar import (
                _ReducedBlock,
                block_values,
                reduce_block_to_exitset,
            )
            from sugar_source_tree.panic import SugarNotWritten

            # The outer CallSiteValue.force_floor already curried constructor
            # formals into ``ctx`` (formal_coordinate_cids → actuals). Reduce the
            # initializer under that ctx directly. A nested empty CallSiteValue
            # (parameters=(), arg_values=()) was previously used as a force_floor
            # wrapper; after store ExitSet composition, that path left
            # BindingCoordinateRef formals unbound and raised bare
            # SugarNotWritten during source-derived manager construction.
            # Each completed face is the initializer's end record (its
            # entries and the context it ended in), from which the receiver
            # is read where it ends.
            records = reduce_block_to_exitset(
                self.initializer_body.statements, initializer_ctx
            )
            if isinstance(records, NativeOperationExitCarrierV1):
                return block_values(records)
            # One unconditional completed face is the whole initializer; only
            # then does an ellipsis-only body mean a stub constructor.
            sole = records.completed_value() is not None

            def receiver_of(record):
                if not isinstance(record, _ReducedBlock):
                    raise SugarNotWritten(
                        blame=self.site,
                        owner="ClassConstructorBodySugar.desugar",
                        observed=(
                            f"an initializer face whose record is a "
                            f"{type(record).__name__}"
                        ),
                        requested="the initializer's end record",
                        fix="complete every initializer face with its block record",
                    )
                block = BlockValue(
                    record.entries,
                    fall_through=record.fall_through,
                    can_fall_through=record.can_fall_through,
                )
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
                    # The object the call made: named by its construction,
                    # whatever the state ``__new__`` returned carried.
                    from dataclasses import replace

                    return ExitSet.completed(replace(returned, **self._made()))
                return self._receiver_where_it_ends(record, initializer_ctx)

            # ``Cls(x)`` is a call: the initializer's halted faces are the
            # call's halted faces, each completed face its own receiver, under
            # its own guard, carrying what it owes. Packing them inside one
            # completed value hid the halts from the caller (#7756).
            return records.and_then(receiver_of)

        return self.enter_initializer(ctx, initialize)

    def _receiver_where_it_ends(self, record, ctx) -> ExitSet:
        """The object the class call returns on one completed face of its
        initializer: ``type.__call__`` returns the object ``__init__`` ran
        on, in the state ``__init__`` left it -- after the one exposure
        rule's rebinding (``g(self)``) the receiver is its value after that
        call, after a call that states what it did to it
        (``self.helper()``, ``super().__init__()``) its value as the call
        left it, and after a later store that value with the store.  It is
        the object, read by its identity, never whatever the formal's name
        is bound to (``self = other``), and never rebuilt from the
        initializer's stores collected again.

        On a face that fell through, the receiver as a read of it after the
        initializer's last statement gives it (``receiver_at_end``), reduced
        in the context the face's end record left (``record.context``).  On
        a face that left by a ``return``, the receiver that ``return``
        carries (``InitializerReturnSugar``), read where it stood; a face
        that went on past a guarded ``return`` is split where the block
        splits it (``past_prior_returns``).  An initializer whose end binds
        no receiver is refused by name."""
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            past_prior_returns,
        )
        from sugar_source_tree.panic import SugarNotWritten

        if self.receiver_at_end is None:
            raise SugarNotWritten(
                blame=self.site,
                owner="ClassConstructorBodySugar.receiver",
                observed="an initializer whose end binds no receiver",
                requested="the receiver as the initializer left it on this face",
                fix="bind the receiver formal where the initializer ends",
            )
        context = record.context if record.context is not None else ctx

        def ended(part):
            return part.context if part.context is not None else context

        if not record.can_fall_through:
            return self._receiver_at_its_returns(record, context)
        return past_prior_returns(
            record,
            context,
            lambda went_on: self.receiver_at_end.desugar(ended(went_on)),
            lambda returned: self._receiver_at_its_returns(returned, ended(returned)),
        )

    def _receiver_at_its_returns(self, record, context=None) -> ExitSet:
        """The object the class call returns on a face of its initializer
        that left by a ``return``: the receiver each ``return`` of the record
        carries (``ReceiverAtReturnValue``), under that ``return``'s own
        guard, where the value it returned is ``None``; a ``TypeError``
        where it is not (``_leaving_by``).  ``context`` is the context the
        face ends in, past the code that ran after the ``return``.  A
        ``return`` that carries none (no name held the receiver where it
        stood) is refused by name, as is a face that left by no
        ``return``."""
        from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.ir import and_
        from sugar_source_tree.panic import SugarNotWritten

        def refuse(observed):
            raise SugarNotWritten(
                blame=self.site,
                owner="ClassConstructorBodySugar.receiver",
                observed=observed,
                requested="the receiver as the initializer left it on this face",
                fix="read the receiver where each return leaves the initializer",
            )

        def guard_of(entry):
            if len(entry.guards) == 1:
                return entry.guards[0]
            return and_(list(entry.guards))

        unguarded = [entry for entry in record.entries if type(entry) is ReturnValue]
        guarded = [
            entry for entry in record.entries if isinstance(entry, GuardedReturn)
        ]
        if not unguarded and not guarded:
            refuse("an initializer face that left by no return and cannot go on")
        if unguarded and (guarded or len(unguarded) > 1):
            refuse("an initializer face that left by more than one unguarded return")
        for entry in (*unguarded, *guarded):
            if not isinstance(entry.value, ReceiverAtReturnValue):
                refuse(
                    "an initializer face that left by a return that carries "
                    "no receiver (no name held it where the return stood)"
                )
        if unguarded:
            return self._leaving_by(unguarded[0].value, context=context)
        arms = [
            self._leaving_by(entry.value, guard_of(entry), context)
            for entry in guarded
        ]
        return ExitSet(()).union(*arms)

    def _leaving_by(
        self, left: ReceiverAtReturnValue, guard=None, context=None
    ) -> ExitSet:
        """The class call leaving by one ``return`` of its initializer (under
        ``guard``): ``type.__call__`` checks what ``__init__`` returned
        after the frame is left -- past every ``finally`` and ``__exit__``,
        out of reach of the initializer's own handlers -- and returns the
        object only when it is ``None``.

        The object is the receiver as the frame left it: where code that
        ran after the ``return`` touched it (``left.past_exits``: a
        ``finally``'s store on ``self``), its read past that code, reduced in
        ``context`` -- the context the face ends in, after that code ran;
        else the receiver the ``return`` read where it stood.

        The returned value's ``None``-ness is asked as ``is`` asks it
        (``object_identity.object_identity``): ``None`` completes with the
        receiver the ``return`` carries; a value decided not ``None`` is
        CPython's ``TypeError: __init__() should return None, not '<type>'``
        raised at the call (``ground_exceptional_exit``); a value whose
        ``None``-ness is undecided is two-faced owing (``ExitSet.two_faced``):
        the receiver under the site-keyed ``...completes`` atom, that
        ``TypeError`` on the other face."""
        if left.past_exits is not None:
            from dataclasses import replace

            from sugar_lift_py_tests.floor.named_expression_value import (
                peel_walrus_binds,
            )

            return left.past_exits.desugar(context).and_then(
                lambda receiver: self._leaving_by(
                    replace(
                        left,
                        receiver=peel_walrus_binds(receiver)[1],
                        past_exits=None,
                    ),
                    guard,
                )
            )
        site = left.site if left.site is not None else self.site
        verdict = _returns_none(left.returned, site)
        if verdict is True:
            return ExitSet.completed(left.receiver, guard)
        from sugar_lift_py_tests.floor import ExceptionValue
        from sugar_lift_py_tests.floor.ground_exit import (
            ground_exceptional_exit,
            ground_raise_effect,
        )

        owner = "ClassConstructorBodySugar.init_return"
        if verdict is False:
            raised = ground_exceptional_exit(
                exception_name="TypeError", site=site, owner=owner
            )
        else:
            from sugar_lift_py_tests.ir import atomic, ctor
            from sugar_lift_py_tests.occurrence import occurrence_term

            raised = ExitSet.two_faced(
                left.receiver,
                ground_raise_effect(
                    exception_name="TypeError",
                    site=site,
                    owner=owner,
                    raised_value=ExceptionValue("TypeError", (), site),
                ),
                guard=atomic(
                    "python:init_return_none.completes",
                    [ctor("python:init_return_none", (occurrence_term(site),))],
                ),
                site=site,
            )
        return raised if guard is None else raised.guarded(guard)

    def _made(self) -> dict:
        """The ``allocation`` and ``arrival`` of the instance this class call
        makes, as the keywords its constructor takes.  At a call: the call's
        site (``object_identity.made_at``), its fields its fields now.  With
        no call (an initializer's own universe): none, and its ``arrival``
        is the receiver coordinate it reached ``__init__`` through."""
        from sugar_lift_py_tests.floor.object_identity import made_at

        allocation = made_at(self.call_site)
        if allocation is not None:
            return {"allocation": allocation, "arrival": None}
        return {"allocation": None, "arrival": self.receiver_coordinate_cid}

    def enter(self, step) -> ExitSet:
        """``step(value, body)`` on the class this constructor is entered on
        (``class_value``) and this body.

        The class is the value its statement bound under its evaluation key,
        read by whoever entered the constructor: a class call's callee
        (``ClassDefinitionValue.callable_application_with``), or the read of
        that key an ``__init__``'s own universe makes in the state the
        module's one run left (``tree_enumerate.function_universe_outcome``).
        The class statement is never reduced here (#7757 item 21): Python
        ran it once, where it stands, and a halt of it is a face of the run
        that ran it, never of a call of the class.  A body entered on no
        class value (the constructor frame's own body) is refused by name."""
        if self.class_value is None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=self.site,
                owner="ClassConstructorBodySugar.enter",
                observed="a class constructor entered on no class value",
                requested=(
                    "the class its statement bound under its evaluation key, "
                    "read where the constructor is entered"
                ),
                fix=(
                    "enter the constructor on the value a read of the class's "
                    "name answered; never reduce the class statement here"
                ),
            )
        return step(self.class_value, self)

    def bind_class_call(self, bind) -> ExitSet:
        """THE class call ``Cls(...)``: the call is bound and applied by
        ``bind(defaults, body)`` on the class this constructor was entered on
        (``enter``).

        ``defaults`` are the ``(key, value)`` pairs the class value carries
        for its constructor (``ClassDefinitionValue.constructor_defaults``):
        what the ``__init__`` / ``__new__`` ``def`` statement evaluated when
        its class body ran.  ``bind`` hands them to ``object_value.bind_call``
        (``defaults``), so a formal the call omits binds that value
        (``DefaultValueSugar``), never its default expression evaluated at
        the call.  ``body`` is this constructor entered on the class value,
        the body the bound call applies."""
        return self.enter(lambda value, body: bind(constructor_defaults(value), body))

    def enter_initializer(self, ctx, initialize) -> ExitSet:
        """THE class call up to its ``__init__``: the one place a receiver is
        made for an initializer to run on.

        On the class this constructor was entered on (``enter``), an unrun
        source ``__new__`` is refused by name, the
        fresh receiver is seated at the receiver coordinate with the PEP 3135
        ``__class__`` cell and the initializer's declared receiver formal
        (``receiver_formal``), and ``initialize(value, ctx)`` runs
        the initializer in that context.  A class with no initializer
        completes with the fresh receiver itself.

        ``desugar`` passes the class call's initializer body; an ``__init__``
        universe (``tree_enumerate.function_universe_outcome``) passes the
        initializer's own universe, so it runs on the receiver the class call
        makes.
        """

        def construct(value):
            if self.returned_new_formal_cids is not None:
                return self._returned_by_new(value, ctx)
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
            receiver = value.fresh_receiver(
                self.receiver_coordinate_cid, **self._made()
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

            # The cell is the class whose body defines the function the call
            # runs (``cell_class_definition``), read as the class value this
            # call's MRO holds for that statement: for an inherited
            # ``__init__`` the base that wrote it, so a ``super()`` in it
            # searches after that base, not after the called class (#7757).
            cell = (
                value.class_value_of_statement(self.cell_class_definition)
                if isinstance(value, ClassDefinitionValue)
                else None
            )
            if cell is not None:
                temporal = temporal.bind_value(
                    "__class__",
                    cell,
                    blame=f"{cell.class_name}.__init__",
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

        return self.enter(lambda value, _body: construct(value))

    def _returned_by_new(self, value, ctx) -> ExitSet:
        """``Cls(*args)`` over a class whose own ``def __new__`` runs and
        whose ``__init__`` is ``object``'s (``ClassDef.returned_new``):
        ``type.__call__`` calls ``Cls.__new__(Cls, *args)`` -- the function
        read off its class, through the one method door
        (``ClassDefinitionValue.call_method_value``), on the actuals the
        class call bound to the frame's formals -- and every face of that
        call, halts included, is the class call's.

        On each completed face the object ``__new__`` returned is what the
        class call returns where ``returned_as_it_is`` decides it.  Anywhere
        else ``type(obj).__init__`` may run on it, which nothing here read:
        that face is the one unanswered call of the class (two-faced, owed),
        and no completion is invented for it."""
        from sugar_source_tree.panic import SugarNotWritten

        owner = "ClassConstructorBodySugar.__new__"
        site = self.call_site if self.call_site is not None else self.site
        temporal = getattr(ctx, "temporal", None)
        actuals = tuple(
            None if temporal is None else temporal.value_if_bound(cid)
            for cid in self.returned_new_formal_cids
        )
        if any(actual is None for actual in actuals):
            raise SugarNotWritten(
                owner=owner,
                blame=site,
                observed="a __new__ formal the class call did not bind",
                requested="the actual the class call bound to each __new__ formal",
                fix="bind the class call's actuals to its constructor frame first",
            )

        def returned(made):
            if returned_as_it_is(made):
                return ExitSet.completed(made)
            return value._unanswered_call(value.class_name, actuals, (), site)

        return value.call_method_value(
            "__new__", (value, *actuals), owner=owner, blame=site, ctx=ctx
        ).and_then(returned)

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


def returned_as_it_is(made) -> bool:
    """Whether ``type.__call__`` returns ``made``, what a class's own
    ``__new__`` returned (``ClassDef.returned_new``), as it is.

    ``type_call`` (Objects/typeobject.c) returns the object at once when it
    is no instance of the class.  The class's order is source classes and
    ``object`` alone (``ClassDef.returned_new``), so every instance of it
    has a source class in its MRO, and a value a literal made has none: an
    ``int`` or ``float`` (a ``TermValue`` holding exactly one), ``None``,
    ``True``, ``False``.  The value is read as an operation reads it: past
    the writes it carries (``peel_walrus_binds``), a call's value the one
    authenticated return its body's reduction retained
    (``project_operation_receiver_outcome``).

    False for anything else: an object of a class whose ``__init__`` may
    then run on it, or a value whose class is not decided here."""
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    presented = peel_walrus_binds(made)[1]
    project = getattr(presented, "project_operation_receiver_outcome", None)
    if project is not None:
        presented = project(
            None, owner="ClassConstructorBodySugar.__new__"
        ).completed_value()
    if type(presented) is TermValue:
        return type(presented.value) in (int, float)
    return type(presented) in (NoneValue, TrueBoolLiteralSugar, FalseBoolLiteralSugar)


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
