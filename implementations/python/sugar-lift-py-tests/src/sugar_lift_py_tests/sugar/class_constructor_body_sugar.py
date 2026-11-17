from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def refuse_unrun_source_new(definition, *, new_method, site, owner):
    """Refuse a class call that would skip the class's own source ``__new__``.

    ``Cls(...)`` is ``type.__call__``: it runs ``Cls.__new__`` first and only
    then ``type(obj).__init__`` on whatever object ``__new__`` returned.  A
    source ``__new__`` may return an instance of another class (pandas
    ``ExcelWriter.__new__`` returns ``object.__new__(get_writer(engine))``),
    so running ``Cls.__init__`` on a fresh ``Cls`` receiver constructs an
    object Python never builds.  The one ``__new__`` arm is the dispatched
    one (``ClassDef.returned_new``, ``ClassConstructorBodySugar.
    _returned_by_new``), which never reaches here; every other source
    ``__new__`` refuses here by name (#7757 A4: no ``__new__`` body is read
    in place).
    """
    if new_method is None:
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
    # The object the class call returns where a dataclass's generated
    # ``__init__`` runs here: a read of the receiver after its last store
    # (``nodes._read_where_the_body_ends``), reduced in the context the
    # stores' end record left (``_receiver_where_it_ends``).  None for any
    # other constructor (a source ``__new__`` is dispatched,
    # ``returned_new_formal_cids``; a source ``__init__`` is dispatched,
    # ``initializer_formals``).  No source ``def``'s body runs here.
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
    # The class's own ``def __new__`` the call runs (``ClassDef.
    # returned_new``): the frame's formal coordinates, its formals after
    # ``cls``, in order.  The call dispatches that ``__new__`` on the actuals
    # bound there, then ``__init__`` on what it returned
    # (``_returned_by_new``).  None for every other constructor.
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

        def initialize(value, initializer_ctx):
            from sugar_lift_py_tests.floor import BlockValue
            from sugar_lift_py_tests.floor import EllipsisValue
            from sugar_lift_py_tests.sugar.function_universe_sugar import (
                _ReducedBlock,
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
            del value
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
        whose end binds no receiver is refused by name."""
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
        dataclass's generated stores, the class's own code with no source
        ``def`` (a source ``__init__`` and a source ``__new__`` are
        dispatched instead, ``_dispatched_initializer``,
        ``_returned_by_new``).

        On the class this constructor was entered on (``enter``), an unrun
        source ``__new__`` is refused by name, the fresh receiver is seated at
        the receiver coordinate, and ``initialize(value, ctx)`` runs the
        stores in that context.  A class with nothing to run completes with
        the fresh receiver itself.
        """

        def construct(value):
            if self.returned_new_formal_cids is not None:
                return self._returned_by_new(value, ctx)
            refuse_unrun_source_new(
                value,
                new_method=self.constructed_new_method,
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
            # The stores read the receiver through its coordinate.
            temporal = ctx.temporal.bind_value(
                self.receiver_coordinate_cid, receiver
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
        from sugar_lift_py_tests.receiver_dispatch import module_attribute_names
        from sugar_source_tree.panic import SugarNotWritten

        owner = "ClassConstructorBodySugar.__init__"
        refuse_unrun_source_new(
            value,
            new_method=self.constructed_new_method,
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

        return call.and_then(self._initialized(receiver, symbol, site, owner))

    def _initialized(self, receiver, symbol, site, owner):
        """``type.__call__``'s tail over one completed face of the
        ``__init__`` call it dispatched on ``receiver`` (the fresh instance,
        ``_dispatched_initializer``, or what a source ``__new__`` returned,
        ``_returned_by_new``): under ``<result> is None`` the class call
        completes with the instance as the call left it
        (``InitializedInstanceValue``: ``symbol`` the class it is stated of,
        None where that is not decided); under its complement it raises
        CPython's ``TypeError: __init__() should return None``.  Prove
        decides the guard where the ``__init__``'s contract is joined; where
        it is not, both faces stand."""
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.ir import eq, not_
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome.exit_set import partition
        from sugar_lift_py_tests.receiver_dispatch import receiver_after_dispatch

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

        return initialized

    def _returned_by_new(self, value, ctx) -> ExitSet:
        """``Cls(*args)`` over a class whose own ``def __new__`` runs and
        whose ``__init__`` is ``object``'s (``ClassDef.returned_new``, the
        one ``__new__`` door, #7757 A4), as ``type.__call__`` runs it:

        1. ``obj = Cls.__new__(Cls, *args)``: the static method read off its
           class through the one method door (``ClassDefinitionValue.
           call_method_value``), the one dispatched call looked up on the
           class object at prove (``_dispatched_on_class``), on the actuals
           the class call bound to the frame's formals.  Its body is never
           read here; every face of that call, halts included (its asserts
           and raises, its own contract's panic loci), is the class call's.
        2. ``type(obj).__init__(obj, *args)`` on each completed face: the one
           dispatched method call on what ``__new__`` returned
           (``receiver_dispatch.dispatch_edge_call``).  Python runs it only
           where ``obj`` is an instance of ``Cls``, by ``obj``'s own class;
           neither is decided here, so no class is stated for its receiver
           (no ``py.class("0", ...)``): prove resolves no ``__init__`` for it
           and the call stays owed, both faces standing, never a resolved
           ``__init__`` of a class nothing decided.
        3. ``type.__call__``'s tail (``_initialized``): the call completes
           with ``obj`` as that call left it, its class undecided
           (``InitializedInstanceValue`` with no class symbol), under
           ``<result> is None``; ``TypeError`` under the complement."""
        from sugar_lift_py_tests.receiver_dispatch import dispatch_edge_call
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

        def initialize(made):
            call = dispatch_edge_call("__init__", made, None, actuals, (), site)
            return call.and_then(self._initialized(made, None, site, owner))

        return value.call_method_value(
            "__new__", (value, *actuals), owner=owner, blame=site, ctx=ctx
        ).and_then(initialize)

    def _carrying_exception_args(self, receiver, ctx):
        """``receiver`` with ``args``: what the frame's ``*args`` formal
        holds, which is every positional actual of the call.

        Two binders bind that formal, and each value is exactly what
        ``BaseException_new`` stores (Objects/exceptions.c): a call's binder
        (``bind_actuals``) the tuple of its positional actuals; the class's
        own constructor contract (``tree_enumerate.class_universe_outcome``)
        the formal itself, standing free as every contract formal does, so
        the contract states ``args`` as the formal a call's edge supplies
        packed (#7757 step 6).  A formal bound to anything else, or bound at
        all where nothing bound it, is refused by name, never read as
        empty."""
        from dataclasses import replace

        from sugar_lift_py_tests.floor import (
            ObjectField,
            ObjectValue,
            SymbolicValue,
            TupleValue,
        )
        from sugar_lift_py_tests.ir import _Var
        from sugar_source_tree.panic import SugarNotWritten

        args = ctx.temporal.value_if_bound(self.exception_args_coordinate_cid)
        free_formal = type(args) is SymbolicValue and isinstance(args.term, _Var)
        if (
            not (type(args) is TupleValue or free_formal)
            or not isinstance(receiver, ObjectValue)
        ):
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
          (``source_call_resolution.object_after_call``), #7757 step 7;
        - under ``python:plain_read(<class>, "<name>")`` (``receiver_dispatch.
          PLAIN_READ``, ``<class>`` the instance's class term,
          ``receiver_dispatch.class_value``), that every read of the name --
          the one undecided read over that object (``CallSiteValue.
          attribute``) -- is the field and completes: ``forall k.
          python:attribute_result(<name>, python:after(out, "out"), k) ==
          attr:<name>(...)`` and its ``python:attribute_op.completes`` atom
          (``stored_field_facts``), ``k`` the read's key.  Prove decides
          the guard on the namespace rows (``consistency::plain_read_holds``:
          no ``__getattribute__``, ``__getattr__``, ``__slots__``,
          ``__dict__`` and no binding of the name in the order); the lift
          never decides whether the read is the ``__dict__`` entry (#7757
          H1).  Where no class term is decided (an instance not current, a
          stored ``__class__``), the read is not stated and stays owed.

        A field the construction did not decide, or one whose value names an
        object of this reduction, is not stated: a read of it stays owed.

        On every completed face, the class of the instance
        (``receiver_dispatch.constructed_class_facts``, #7757 step 8):
        ``python:type_is(python:after(out, "out"), <class>)`` and
        ``python:may_hold(python:after(out, "out"), <name>)`` for each name
        its ``__dict__`` holds, where the face decides them;
        ``python:class_undecided(python:after(out, "out"))`` where it does
        not.  Prove binds a caller's dispatch over the result to them."""
        from sugar_lift_py_tests.floor.object_identity import (
            contents_current,
            holds_stale,
            instance_stale,
        )
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.ir import and_, atomic, implies, str_const
        from sugar_lift_py_tests.receiver_dispatch import (
            PLAIN_READ,
            class_value,
            constructed_class_facts,
        )
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
        # The class term prove decides each read's plainness over: none
        # where the face does not decide the instance's class (as
        # ``constructed_class_facts``), and then no read is stated.
        class_term = None if "__class__" in latest else class_value(instance)
        for name, value in latest.items():
            if not current and name not in instance.stored_fields:
                continue
            # A field holding a container whose contents are not current (a
            # global, an object a call may have changed) is not stated: its
            # display would be contents the object may no longer hold, and a
            # read of it stays owed (#7757 H7).
            if holds_stale(value) or instance_stale(value):
                continue
            term = value.to_term(owner="ConstructedInstanceValue.post")
            if _names_an_object(term):
                continue
            value_fact, read_completes = stored_field_facts(constructed, name, term)
            facts.append(value_fact)
            if class_term is not None:
                plain = atomic(PLAIN_READ, [class_term, str_const(name)])
                facts.append(implies(plain, read_completes))
        return and_(facts)


@dataclass(frozen=True)
class InitializedInstanceValue(FloorValue):
    """What a class's constructor contract returns on a completed arm where
    the class call dispatched ``__init__`` on the object it made: the fresh
    instance (``ClassConstructorBodySugar._dispatched_initializer``, #7757
    B3) or what its source ``__new__`` returned (``_returned_by_new``,
    #7757 A4).  ``instance``, that object; ``after``, the object as the
    ``__init__`` call left it (``receiver_dispatch.receiver_after_dispatch``,
    ``python:after(<call>, "0")``), or None where no dispatched edge names it;
    ``class_symbol``, the join symbol of the class the call made it of, or
    None where code may store its ``__class__`` or a source ``__new__`` made
    it (its class is not decided here).

    The post never states which object it is (each call makes a fresh one)
    and never reads ``__init__``'s or ``__new__``'s body
    (``post_formula``)."""

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
          holding nothing (``consistency::initialized_instance``);
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


# The bound variable of a contract's field-read fact: the read's key
# (``floor_value.undecided_attribute_result``'s ``occurrence_key``).  A name
# no contract formal or Python identifier spells.
_READ_KEY = "python:read_key"


def stored_field_facts(obj, name: str, value) -> tuple:
    """``(value_fact, read_completes)``: the one shape a contract states a field
    it leaves in an object by -- a class's constructor contract the
    instance it makes (``ConstructedInstanceValue.post_formula``), a
    function a field it stores on a parameter (``UniverseValue.
    field_facts``, #7757 step 7):

    - ``value_fact``: ``attr:<name>(<obj>) == <value>``, ``<obj>`` the object as
      the call left it (``python:after(out, <label>)``), the field's value
      (what prove reads an instance's fields off,
      ``consistency::stated_instance_fields``);
    - ``read_completes``: ``forall k. and(python:attribute_result(<name>,
      <obj>, k) == attr:<name>(<obj>), python:attribute_op.completes(
      python:attribute_op(python:attribute_result(<name>, <obj>, k), k)))``,
      ``k`` the read's key: the caller's read, the one undecided read
      (``floor_value.undecided_attribute_result`` over ``<obj>``), is the
      field and completes, so it is answered at prove.  The caller states it
      only where the read is the ``__dict__`` entry; elsewhere the read
      stays owed."""
    from sugar_lift_py_tests.floor.floor_value import undecided_result_terms
    from sugar_lift_py_tests.ir import (
        Int,
        and_,
        ctor,
        eq,
        forall,
        make_var,
        str_const,
    )

    field = ctor(f"attr:{name}", [obj], symbol_kind="method-coordinate")
    value_fact = eq(field, value)
    read, completes = undecided_result_terms(
        "attribute", (str_const(name), obj), make_var(_READ_KEY)
    )
    read_completes = forall(
        _READ_KEY,
        # The key ranges over the sort a site key lowers to where it stands:
        # an argument of the ``python:attribute_result`` coordinate, whose
        # string constants the SMT backend declares as opaque ``Int``
        # constants (``strlit_*``).  Bound over ``String`` the quantified
        # read was another function to the solver, and z3 refused the row.
        Int(),
        and_([eq(read, field), completes]),
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


@dataclass(frozen=True)
class UnreadConstructorCallSugar(Sugar):
    """``Cls(*args, **kwargs)`` as the contract of a class whose constructor
    is not read (``ClassDef.constructor_is_read``: an imported base, a
    metaclass, a ``Protocol``/``Generic``/``ABC`` base, or a decorator the one
    class-namespace lookup does not decide) returns it
    (``tree_enumerate.class_universe_outcome``).

    No lookup decides which ``__new__`` and ``__init__`` the call runs, nor
    the signature it binds, so the contract takes every actual a call may
    pass (``args``, ``kwargs``: its free formals, whose contents no frame
    holds) and states the call through the one spread-call door
    (``SpreadCallSugar._finish``) on ``class_value``, what the class
    statement's key holds: with no exact roster it is the one unanswered
    call (``UnknownCalleeCallV1``), two-faced and owed -- its result and its
    halt both carried undecided, never a completion and never a refusal of
    the class.  The same call a caller of the class makes
    (``ClassDefinitionValue.callable_application_with``)."""

    class_name: str
    class_value: object = field(compare=False)
    actuals: tuple = field(compare=False)
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="CallSiteValue",
            reason="a class whose constructor is not read states its call unanswered",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar

        call = SpreadCallSugar(
            callee_name=self.class_name,
            callee=None,
            arguments=(("star", None, None), ("double-star", None, None)),
            site=self.site,
        )
        # The actuals are already values (the contract's formals): the
        # door's own finish, as ``SpreadCallSugar.desugar`` reaches it once
        # its callee and operands are evaluated.
        return call._finish(self.class_value, tuple(self.actuals), ctx)
