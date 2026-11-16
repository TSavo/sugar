from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor.floor_value import FloorValue
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
    # class's own contract, on the read of the statement's key in the state
    # the module's one run left (``tree_enumerate.class_universe_outcome``).
    # None on the frame's
    # own body (``ClassDef.source_visible_constructor_frame``), which is
    # entered on no class and refuses by name.
    class_value: object | None = field(default=None, compare=False)
    # The inherited-exception frame's ``*args`` formal coordinate
    # (``ClassDef.source_visible_constructor_frame``): a class whose
    # constructor is BaseException's.  ``BaseException_new`` stores the
    # call's positional actuals as ``args`` (Objects/exceptions.c), so the
    # instance the call makes carries them.
    exception_args_coordinate_cid: str | None = field(default=None, compare=False)
    # The class statement whose body defines the function this body runs:
    # the PEP 3135 ``__class__`` cell a zero-argument ``super()`` in it reads:
    # the class itself for its own ``__new__``.  None when the body is no
    # source function's (a dataclass's generated stores have no cell, and a
    # source ``__init__`` is dispatched, never run here).
    cell_class_definition: object | None = field(default=None, compare=False)
    # The object the class call returns where a dataclass's generated
    # ``__init__`` runs here: a read of the receiver after its last store
    # (``nodes._read_where_the_body_ends``), reduced in the context the
    # stores' end record left (``_receiver_where_it_ends``).  None for any
    # other constructor (a source ``__new__`` returns its own; a source
    # ``__init__`` is dispatched, ``initializer_formals``).
    receiver_at_end: Sugar | None = field(default=None, compare=False)
    # The source ``__init__`` this call runs, as the dispatched
    # ``type(obj).__init__(obj, *args, **kw)`` on the fresh instance it
    # makes (#7757 B3, ``_dispatched_initializer``): each formal of the
    # constructor frame it forwards, ``((coordinate cid, kind, name), ...)``.
    # None for every other constructor.
    initializer_formals: tuple | None = field(default=None, compare=False)
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
        if self.initializer_formals is not None:
            # A source ``__init__``: dispatched on the fresh instance, joined
            # at prove; its body is never reduced here (#7757 B3).
            return self.enter(
                lambda value, _body: self._dispatched_initializer(value, ctx)
            )

        def project_new_return(definition, block):
            """The receiver the authenticated source ``__new__`` returns.

            The body seated for it is everything ``__new__`` runs after its
            allocation -- its field stores and its ``return``
            (``ClassDef._source_visible_body``) -- so the value is what that
            ``return`` returns, the one authenticated return of the block
            (``project_authenticated_source_return``): the receiver after
            the stores.  A block is never read as the return, and no
            statement of it stands for one.  Only the authenticated source
            ``__new__`` arm may return this value; a dataclass's generated
            stores return the receiver as they left it
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
                block_record,
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
                # Each face it completes on is the suite's record
                # (``block_values``).  What runs here is a dataclass's
                # generated stores or a source ``__new__``'s stores, never a
                # source ``__init__`` (dispatched, ``_dispatched_initializer``),
                # so no ``assert`` of a body is split here: an ``__init__``'s
                # asserts are halts of its own contract (#8961), reached
                # through its edge.
                return records.and_then(
                    lambda state: ExitSet.completed(block_record(state))
                )
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
        """The object the class call returns on one completed face of a
        dataclass's generated stores: the receiver as a read of it after the
        last store gives it (``receiver_at_end``), reduced in the context the
        face's end record left (``record.context``).  The stores hold no
        ``return``, so every completed face falls through.  A constructor
        whose end binds no receiver (a source ``__new__`` whose return is not
        the authenticated receiver) is refused by name."""
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
        return self.receiver_at_end.desugar(context)

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
        read by whoever entered the constructor: the class's own contract,
        in the state the module's one run left
        (``tree_enumerate.class_universe_outcome``).
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

    def enter_initializer(self, ctx, initialize) -> ExitSet:
        """The class call up to what it runs here on the receiver it makes: a
        dataclass's generated stores or a source ``__new__``'s stores (a
        source ``__init__`` is dispatched instead,
        ``_dispatched_initializer``).

        On the class this constructor was entered on (``enter``), an unrun
        source ``__new__`` is refused by name, the fresh receiver is seated at
        the receiver coordinate with the PEP 3135 ``__class__`` cell, and
        ``initialize(value, ctx)`` runs the stores in that context.  A class
        with nothing to run completes with the fresh receiver itself.
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
            # The stores read the receiver through its coordinate; a source
            # ``__new__``'s zero-argument ``super()`` reads the PEP 3135
            # ``__class__`` cell.
            temporal = ctx.temporal.bind_value(
                self.receiver_coordinate_cid, receiver
            )
            from sugar_lift_py_tests.floor.class_definition_value import (
                ClassDefinitionValue,
            )

            # The cell is the class whose body defines the function the call
            # runs (``cell_class_definition``), read as the class value this
            # call's MRO holds for that statement (#7757).
            cell = (
                value.class_value_of_statement(self.cell_class_definition)
                if isinstance(value, ClassDefinitionValue)
                else None
            )
            if cell is not None:
                temporal = temporal.bind_value(
                    "__class__",
                    cell,
                    blame=f"{cell.class_name}.__new__",
                )
            return initialize(value, ctx.with_temporal(temporal))

        return self.enter(lambda value, _body: construct(value))

    def _dispatched_initializer(self, value, ctx) -> ExitSet:
        """``Cls(*args, **kw)`` over a class whose source ``__init__`` the
        call runs (#7757 B3): ``type.__call__`` makes a fresh instance of
        ``value`` (an unrun source ``__new__`` refused by name, as
        ``enter_initializer`` refuses it) and calls ``type(obj).__init__(obj,
        *args, **kw)`` on it.

        That call is the one dispatched method call on an instance this
        construction made (``ObjectValue._dispatched_or_owed``): its
        coordinate and the dispatched edge over ``python:instance(<class>)``
        (the fresh ``__dict__`` is empty), forwarding each formal of the
        constructor frame as the class call bound it -- a positional formal
        by position, a keyword-only one by keyword.  Prove looks ``__init__``
        up on the class's order and joins its contract (one MRO lookup, as
        every dispatched call), so each halt the ``__init__``'s contract
        states -- its asserts and raises (#8961) -- is a halt of this call,
        and what it leaves in ``self`` is what the instance holds
        (``consistency::initialized_instance``).  A frame with a ``*args`` or
        ``**kwargs`` formal forwards a spread no edge states: the one
        unanswered call of ``__init__``, owed, its halt kept.

        On each completed face of that call, ``type.__call__`` checks what
        ``__init__`` returned: under ``<result> is None`` the class call
        completes with the instance as the call left it
        (``InitializedInstanceValue``); under its complement it raises
        CPython's ``TypeError: __init__() should return None``.  Prove
        decides the guard where the ``__init__``'s contract is joined; where
        it is not, both faces stand."""
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.ir import eq, not_
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome.exit_set import partition
        from sugar_lift_py_tests.receiver_dispatch import (
            module_attribute_names,
            receiver_after_dispatch,
        )
        from sugar_source_tree.panic import SugarNotWritten

        owner = "ClassConstructorBodySugar.__init__"
        refuse_unrun_source_new(
            value,
            new_method=self.constructed_new_method,
            runs_new=False,
            site=self.site,
            owner="ClassConstructorBodySugar.__new__",
        )
        receiver = value.fresh_receiver(self.receiver_coordinate_cid, **self._made())
        temporal = getattr(ctx, "temporal", None)
        positional: list = []
        keywords: list = []
        spread = False
        for cid, kind, name in self.initializer_formals:
            actual = None if temporal is None else temporal.value_if_bound(cid)
            if actual is None:
                raise SugarNotWritten(
                    owner=owner,
                    blame=self.site,
                    observed=f"the __init__ formal `{name}` the class call did not bind",
                    requested="the actual the class call bound to each constructor formal",
                    fix="bind the class call's actuals to its constructor frame first",
                )
            if kind in ("positional_only", "positional_or_keyword"):
                positional.append(actual)
            elif kind == "keyword_only":
                keywords.append((name, actual))
            else:
                spread = True
        site = self.site
        if spread:
            call = receiver.unanswered_method_call(
                "__init__", tuple(positional), tuple(keywords), site
            )
        else:
            call = receiver._dispatched_or_owed(
                "__init__", tuple(positional), tuple(keywords), site
            )
        symbol = None
        definition = getattr(value, "class_definition", None)
        unit = getattr(site, "unit", None)
        if (
            definition is not None
            and unit is not None
            and not module_attribute_names(unit)[1]
        ):
            # ``type(obj)`` is the class the call made it of unless code may
            # store its ``__class__`` (a dynamic module).
            symbol = definition.bridge_source_symbol()

        def initialized(result):
            after = receiver_after_dispatch(receiver, result)
            returned = peel_walrus_binds(result)[1]
            returned_none = eq(
                returned.to_term(owner=owner),
                NoneValue().to_term(owner=owner),
            )
            made, other = partition(("class_initializer_return", occurrence_key(site)))
            instance = ExitSet.completed(
                InitializedInstanceValue(receiver, after, symbol)
            ).guarded(returned_none, made)
            raised = ground_exceptional_exit(
                exception_name="TypeError", site=site, owner=owner
            ).guarded(not_(returned_none), other)
            return instance.union(raised)

        return call.and_then(initialized)

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


@dataclass(frozen=True)
class ConstructedInstanceValue(FloorValue):
    """What a class's constructor contract returns on one completed arm
    (``tree_enumerate.class_universe_outcome``, #7757 step 6): the instance
    the class call makes, as its construction left it (``instance``).

    The post states what the construction left, never which object it is:
    each call makes a fresh object, so ``out`` is never equated to the one
    receiver this reduction allocated (``post_formula``).  It states each
    field the construction set (``attr:<name>(python:after(out, "out")) ==
    <value>``, the instance as the construction left it,
    ``source_call_resolution.object_after_call``) whose value names no
    object of this reduction: a field holding an object made here (the
    receiver itself, another instance) is not stated, since that object's
    identity is fresh per call as well."""

    instance: FloorValue

    def to_term(self, *, owner: str):
        return self.instance.to_term(owner=owner)

    def guarded(self, formula):
        del formula
        return self

    def post_formula(self, out):
        """For each field the construction left on the instance where it is
        the instance's field now (``object_identity.contents_current``, or a
        store of this frame), the last binding of each name, in field order:

        - ``attr:<name>(python:after(out, "out")) == <value>``: the field of
          the instance as the construction left it
          (``source_call_resolution.object_after_call``), the one term a
          caller's read of a field of the call's result names
          (``CallSiteValue.attribute``, #7757 step 7);
        - where a read of the name is the ``__dict__`` entry by Python's own
          rule (``ObjectValue.reads_plain_field``), that every such read
          completes: ``forall k. python:attribute.completes(
          python:attribute(python:after(out, "out"), <name>, k))``, ``k``
          the read's site key, so the caller's read is answered at prove.

        A field the construction did not decide, or one whose value names an
        object of this reduction, is not stated: a read of it stays owed.

        On every completed face, the class of the instance
        (``receiver_dispatch.constructed_class_facts``, #7757 step 8):
        ``python:type_is(python:after(out, "out"), <class>)`` and
        ``python:may_hold(python:after(out, "out"), <name>)`` for each name
        its ``__dict__`` holds, where the face decides them;
        ``python:class_undecided(python:after(out, "out"))`` where it does
        not.  Prove binds a caller's dispatch over the result to them."""
        from sugar_lift_py_tests.floor.object_identity import contents_current
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.ir import and_
        from sugar_lift_py_tests.receiver_dispatch import constructed_class_facts
        from sugar_lift_py_tests.source_call_resolution import (
            CALL_RESULT_LABEL,
            object_after_call,
        )

        instance = self.instance
        constructed = object_after_call(out, CALL_RESULT_LABEL)
        facts = constructed_class_facts(instance, constructed)
        if not isinstance(instance, ObjectValue):
            return and_(facts)
        current = contents_current(instance)
        latest = {}
        for item in instance.fields:
            latest[item.name] = item.value
        for name, value in latest.items():
            if not current and name not in instance.stored_fields:
                continue
            if name in instance.deleted_instance_fields:
                continue
            term = value.to_term(owner="ConstructedInstanceValue.post")
            if _names_an_object(term):
                continue
            value_fact, read_completes = stored_field_facts(constructed, name, term)
            facts.append(value_fact)
            if instance.reads_plain_field(name):
                facts.append(read_completes)
        return and_(facts)


@dataclass(frozen=True)
class InitializedInstanceValue(FloorValue):
    """What a class's constructor contract returns on a completed arm where
    the class call dispatched its source ``__init__`` on the fresh instance
    it made (``ClassConstructorBodySugar._dispatched_initializer``, #7757
    B3): ``instance``, that fresh instance; ``after``, the instance as the
    ``__init__`` call left it (``receiver_dispatch.receiver_after_dispatch``,
    ``python:after(<call>, "0")``), or None where no dispatched edge names it;
    ``class_symbol``, the join symbol of the class the call made it of, or
    None where code may store its ``__class__``.

    The post never states which object it is (each call makes a fresh one)
    and never reads ``__init__``'s body (``post_formula``)."""

    instance: FloorValue
    after: FloorValue | None
    class_symbol: str | None

    def to_term(self, *, owner: str):
        held = self.after if self.after is not None else self.instance
        return held.to_term(owner=owner)

    def guarded(self, formula):
        del formula
        return self

    def post_formula(self, out):
        """Over ``python:after(out, "out")``, the instance a caller reads the
        call's result by:

        - ``python:type_is(<it>, "<class>")`` where the class is decided
          (``class_symbol``) and a dispatched edge names the instance
          (``after``), ``python:class_undecided(<it>)`` otherwise: a row
          stating ``type_is`` with no ``__init__`` edge reads as an instance
          holding nothing (``consistency::constructed_instance``);
        - ``<it> == python:after(<__init__ call>, "0")`` where the dispatched
          edge names the instance after it (``after``): every field a
          caller reads of the result is the field the ``__init__``'s
          contract states it leaves in ``self``, joined at prove through
          that edge (the binder pairs ``"0"`` with the receiver formal,
          ``consistency::argument_key_aliases``).

        What its ``__dict__`` may hold is never stated here: prove composes
        it from the ``__init__``'s own contract (``consistency::
        initialized_instance``), which also leaves the instance undecided
        wherever that contract does not decide it."""
        from sugar_lift_py_tests.ir import and_, atomic, eq, str_const
        from sugar_lift_py_tests.receiver_dispatch import CLASS_UNDECIDED, TYPE_IS
        from sugar_lift_py_tests.source_call_resolution import (
            CALL_RESULT_LABEL,
            object_after_call,
        )

        constructed = object_after_call(out, CALL_RESULT_LABEL)
        if self.class_symbol is None or self.after is None:
            # No dispatched ``__init__`` edge names the instance after it (a
            # spread forwarded to the unanswered call): what its ``__dict__``
            # holds is decided nowhere, so its class is never stated alone.
            facts = [atomic(CLASS_UNDECIDED, [constructed])]
        else:
            facts = [atomic(TYPE_IS, [constructed, str_const(self.class_symbol)])]
        if self.after is not None:
            facts.append(
                eq(constructed, self.after.to_term(owner="InitializedInstanceValue"))
            )
        return facts[0] if len(facts) == 1 else and_(facts)


# The bound variable of a contract's field-read fact: the read's site key
# (``FloorValue.undecided_attribute``'s ``occurrence_key``).  A name no
# contract formal or Python identifier spells.
_READ_KEY = "python:read_key"


def stored_field_facts(obj, name: str, value) -> tuple:
    """``(value_fact, read_completes)``: the one shape a contract states a field
    it leaves in an object by -- a class's constructor contract the
    instance it makes (``ConstructedInstanceValue.post_formula``), a
    function a field it stores on a parameter (``UniverseValue.
    field_facts``, #7757 step 7):

    - ``value_fact``: ``attr:<name>(<obj>) == <value>``, ``<obj>`` the object as
      the call left it (``python:after(out, <label>)``), the one term a
      caller's read of the field names;
    - ``read_completes``: ``forall k. python:attribute.completes(
      python:attribute(<obj>, <name>, k))``, ``k`` the read's site key: a
      read of it completes, so the caller's read is answered at prove.  The
      caller states it only where the read is the ``__dict__`` entry."""
    from sugar_lift_py_tests.ir import (
        Int,
        atomic,
        ctor,
        eq,
        forall,
        make_var,
        str_const,
    )

    read = ctor(f"attr:{name}", [obj], symbol_kind="method-coordinate")
    value_fact = eq(read, value)
    read_completes = forall(
        _READ_KEY,
        # The key ranges over the sort a site key lowers to where it stands:
        # an argument of the ``python:attribute`` coordinate, whose string
        # constants the SMT backend declares as opaque ``Int`` constants
        # (``strlit_*``).  Bound over ``String`` the quantified read was
        # another function to the solver, and z3 refused the row (``unknown
        # constant python:attribute``).
        Int(),
        atomic(
            "python:attribute.completes",
            [ctor("python:attribute", (obj, str_const(name), make_var(_READ_KEY)))],
        ),
    )
    return value_fact, read_completes


def _names_an_object(term) -> bool:
    """Whether ``term`` mentions an object's identity
    (``py.object.*``): a value no two calls share."""
    from sugar_lift_py_tests.ir import _Ctor

    pending = [term]
    while pending:
        current = pending.pop()
        if isinstance(current, _Ctor):
            if current.name.startswith("py.object"):
                return True
            pending.extend(current.args)
    return False


@dataclass(frozen=True)
class ConstructedInstanceSugar(Sugar):
    """The class call's constructor (``constructor``: the
    ``ClassConstructorBodySugar`` entered on the class value) as its
    contract returns it: each completed arm the instance its construction
    left (``ConstructedInstanceValue``), each halt the constructor's own.
    Read only by the class's own contract
    (``tree_enumerate.class_universe_outcome``)."""

    constructor: Sugar
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ConstructedInstanceValue",
            reason="a class's contract states what its constructor leaves",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # An instance a dispatched ``__init__`` left states itself
        # (``InitializedInstanceValue``, #7757 B3).
        return self.constructor.desugar(ctx).and_then(
            lambda value: ExitSet.completed(
                value
                if isinstance(value, InitializedInstanceValue)
                else ConstructedInstanceValue(value)
            )
        )
