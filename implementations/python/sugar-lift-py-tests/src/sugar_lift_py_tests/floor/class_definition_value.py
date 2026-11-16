from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_source_tree.panic import SugarNotWritten

from .guard_stable_value import GuardStableValue


@dataclass(frozen=True)
class ConstructedClassMethodV1:
    name: str
    definition_fragment_cid: str
    body: object = field(compare=False)
    source_call_frame: object = field(compare=False)
    descriptor_kind: str | None = None


@dataclass(frozen=True)
class DeferredClassMethodV1:
    """A method whose body refused at class construction, or whose body was
    under construction up the stack (a recursion seat,
    ``SourceCallFrameCycle``).

    A ``def`` in a class body binds a function; the body runs only when the
    method is called.  The class statement completes; whoever reads the
    method's body or frame (its caller) constructs it again and meets the
    refusal, or the seat, there.  The refusal is never testimony about the class statement.
    The definition itself is testified by ``definition_fragment_cid``; the
    node is only the handle a caller constructs from.
    """

    name: str
    definition_fragment_cid: str
    definition: object = field(compare=False, metadata={"testimony": "lookup"})
    descriptor_kind: str | None = None

    @property
    def body(self):
        return self.definition.sugar()

    @property
    def source_call_frame(self):
        return self.definition.source_visible_call_frame()


@dataclass(frozen=True)
class ConstructedClassFieldV1:
    name: str
    definition_fragment_cid: str
    value_sugar: object = field(compare=False)
    binding_target_occurrence: SourceFragmentCoordinateV1
    evaluation_group_cid: str | None = None
    # The key a later read of the field's name in the class body references
    # (``Assign.target_evaluations``, ``AnnAssign.target_evaluations``).  The
    # class body binds the field's value under it, as an assignment anywhere
    # else does.
    evaluation_key: str | None = field(default=None, compare=False)

    def __post_init__(self):
        if type(self.binding_target_occurrence) is not SourceFragmentCoordinateV1:
            raise TypeError(
                "ConstructedClassFieldV1 binding target must be an exact "
                "SourceFragmentCoordinateV1"
            )


@dataclass(frozen=True)
class ClassDefinitionValue(GuardStableValue):
    class_name: str
    class_definition_cid: str
    methods: tuple[ConstructedClassMethodV1, ...]
    initializer: ConstructedClassMethodV1 | None
    binding_target_occurrence: SourceFragmentCoordinateV1 = field(compare=False)
    class_fields: tuple[object, ...] = ()
    docstring_cid: str | None = None
    annotation_cids: tuple[str, ...] = ()
    decorator_cids: tuple[str, ...] = ()
    base_classes: tuple[object, ...] = ()
    # The class statement this value was built from.  ``Cls(x)`` applies its
    # one constructor frame, however the class is reached.
    class_definition: object = field(default=None, compare=False)
    # ``(key, value)``: each default of each method ``def`` statement, as the
    # class body's block bound it (``ClassDefinitionSugar._namespace``), under
    # its per-parameter key (``nodes._default_evaluation_key``).  Python
    # stores the values on the function; every call that omits the formal
    # binds that one object (a class call passes its constructor's to
    # ``bind_call``'s ``defaults``, ``constructor_defaults``, as a lambda
    # value's are; a method call is the dispatched call, bound at prove).
    method_defaults: tuple = field(default=(), compare=False)
    # What the class body's callees stored is no part of the class: the
    # body ran once, at the class statement, whose record lays those stores
    # (``ClassDefinitionSugar.statement_run``).  The class contributes and
    # scopes as any value does, so a read of it anywhere applies nothing.

    def __post_init__(self):
        if type(self.binding_target_occurrence) is not SourceFragmentCoordinateV1:
            raise TypeError(
                "ClassDefinitionValue binding target must be an exact "
                "SourceFragmentCoordinateV1"
            )

    def callable_application_with(self, operation, ctx):
        """``Cls(*args, **kw)``: the one call of a source class.

        Every call of a source class is a call of its value (a read of the
        class's name is its statement's evaluation key).  It is its
        coordinate and an edge to the class's join symbol
        (``definition_edge_call``, ``python:<module>.<Class>``), joined at
        prove to the class's constructor contract
        (``tree_enumerate.class_universe_outcome``) as a call of a ``def``
        is: the owner's ruling of 2026-11-15, #7757 step 6.  The
        constructor's body is never applied here; every halt its contract
        states reaches this call at prove.  The call is bound to the
        constructor frame's signature
        (``ClassDef.source_visible_constructor_frame``) with the constructor
        defaults this value carries (``constructor_defaults``), only to read
        what the edge supplies; the class statement already ran where the
        value was built and is never reduced again here.

        A class whose constructor its own statement does not decide (no
        ``dataclass``-written ``__init__``) and whose MRO does not construct
        by the laws the lifter reads
        (``ClassDef.construction_order`` is None: a base the lifter cannot
        read, or ``OSError``/``SyntaxError``/... anywhere in it) is the one
        unanswered call (``UnknownCalleeCallV1``), exactly as the same class
        called by name is: never the zero-formal ``object`` frame or the
        ``(*args)`` frame applied to a constructor nothing here read.  So is a
        class whose ``__init__`` the one class-namespace lookup does not
        decide as a source ``def`` or a builtin's
        (``ClassDef.initializer_entry`` is None: a store to it, a base's
        generated one, a conditional ``def``), and a class whose ``__new__``
        it does not decide as the class's own ``def`` or a builtin's
        (``ClassDef.new_entry``: a store to it, a base's ``def __new__``).
        The ``dataclass`` arm asks the same lookup, reading its
        ``typing.Generic`` base by its own law (``ClassDef.dataclass_new_entry``):
        it constructs only over a builtin's ``__new__``; a ``__new__`` of the
        class's own, or one not decided, runs before the generated
        ``__init__`` and the call is the unanswered call.
        """
        from sugar_lift_py_tests.floor.object_value import bind_call

        definition = self.class_definition
        if definition is None:
            raise SugarNotWritten(
                owner="ClassDefinitionValue.callable_application_with",
                blame=operation.site,
                observed=f"{self.class_name} value carries no class statement",
                requested="the class statement whose constructor frame the call applies",
                fix="build the class value from its ClassDef so its frame is applied",
            )
        keyword_count = len(operation.keyword_names)
        positional = (
            operation.arguments[:-keyword_count]
            if keyword_count
            else operation.arguments
        )
        keywords = (
            tuple(zip(operation.keyword_names, operation.arguments[-keyword_count:]))
            if keyword_count
            else ()
        )
        if not definition.constructor_is_read():
            return self._unanswered_call(
                self.class_name, positional, keywords, operation.site
            )
        frame = definition.source_visible_constructor_frame()
        from sugar_lift_py_tests.floor.lambda_callable import (
            _refuse,
            definition_edge_call,
            variadic_formals,
        )

        # The one binder binds the call to the constructor's signature (a
        # call that does not fit is refused by name there), each formal the
        # call omits reading the default the class value carries for it
        # (``constructor_defaults``): what the edge supplies as
        # ``py.default``.  No body is bound: the constructor is the class's
        # contract (``tree_enumerate.class_universe_outcome``), joined at
        # prove (#7757 step 6).
        bound = bind_call(
            self.class_name,
            positional,
            keywords,
            frame=frame,
            parameters=frame.parameters,
            frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(
                coordinate.cid for coordinate in frame.formal_coordinates
            ),
            ctx=ctx,
            owner="ClassDefinitionValue.callable_application_with",
            blame=operation.site,
            refuse=_refuse,
            defaults=self.constructor_defaults(),
        )
        return definition_edge_call(
            symbol_definition=definition,
            signature=definition.constructor_definition(),
            parameters=tuple(frame.parameters),
            packed=variadic_formals(frame),
            positional=positional,
            keywords=keywords,
            captured=(),
            actuals=tuple(bound.arg_values),
            site=operation.site,
            call_occurrence=getattr(operation, "call_occurrence", None),
            caller_ctx=ctx,
            fallback_target=self.class_name,
            # The class a raise authenticated for this callee: the instance
            # the call makes is of it (its ``__new__`` is a builtin's or one
            # the constructor reads, ``constructor_is_read``), so the call
            # carries it, as a plain call of a builtin exception does
            # (``RaiseSugar._effect`` reads the class off the value).
            exception_type_coordinate=getattr(
                operation, "exception_type_coordinate", None
            ),
            exception_type_mro=getattr(operation, "exception_type_mro", None),
            # The instance as its construction left it: its fields are read
            # through the class's contract (``CallSiteValue.attribute``,
            # #7757 step 7).
            constructed_by_edge=True,
            # Its class, wherever ``type.__call__`` makes it with a builtin
            # ``__new__`` (no source ``__new__``, no metaclass): an instance
            # of exactly this class, whatever its ``__init__`` does.  The
            # class's contract states that class on every completed face
            # (``ConstructedInstanceValue.post_formula``), and a method call
            # and a ``with``'s implicit ``__enter__``/``__exit__`` on the
            # result are dispatched over it at prove (#7757 step 8).
            instance_of=_instance_class_symbol(definition),
        )

    def _unanswered_call(self, target, positional, keywords, site):
        """``Cls(...)`` whose constructor nothing here read, or ``Cls.m(...)``
        whose ``m`` the one class-namespace lookup does not decide: the one
        unanswered call of ``target`` (``UnknownCalleeCallV1``), two-faced
        and owed, its completion the call's own result coordinate."""
        from sugar_lift_py_tests.call_symbol import call_symbol
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.object_identity import call_operand_terms
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

        owner = str(site)
        callsite = CallSiteValue(
            target_name=target,
            arg_values=(*positional, *(value for _name, value in keywords)),
            parameters=(),
            term=ctor(
                call_symbol(target),
                # Each actual as the call finds it (``identity_term``).
                call_operand_terms(positional, keywords, site, owner=owner),
                symbol_kind="coordinate",
            ),
            body=None,
            keyword_names=tuple(name for name, _value in keywords),
            site=site,
        )
        return UnknownCalleeCallV1(target).faces(callsite, site)

    def _dispatched_on_class(self, name, positional, keywords, site, *, after=None):
        """``Cls.<name>(...)`` -- ``after``: ``super().<name>(...)`` in a
        ``classmethod`` of the class ``after`` names, with this class its
        ``cls`` -- as the one dispatched call looked up on this class object
        (``receiver_dispatch.dispatch_edge_call`` with ``on_class``, #7757
        entry 6): no receiver, the written actuals as written.  Prove looks
        ``name`` up on the order this class's own proof states, from the
        class after ``after`` where it is given, and binds it by the kind
        its namespace row states (``consistency::dispatched_target``).
        Where this class names no join symbol (no workspace root) or the
        call has no site, no edge could name it: the one unanswered call of
        ``Cls.<name>``, owed."""
        definition = self.class_definition
        symbol = None if definition is None else definition.bridge_source_symbol()
        if symbol is None or site is None:
            return self._unanswered_call(
                f"{self.class_name}.{name}", positional, keywords, site
            )
        from sugar_lift_py_tests.receiver_dispatch import dispatch_edge_call

        return dispatch_edge_call(
            name,
            None,
            None,
            tuple(positional),
            tuple(keywords),
            site,
            on_class=symbol,
            after=after,
        )

    def constructor_defaults(self) -> tuple:
        """``(key, value)``: the method defaults a call of the class binds
        where it binds its actuals (``object_value.bind_call``'s
        ``defaults``): this class's own (``method_defaults``: its source
        ``__new__``, its own ``__init__``) and, when the ``__init__`` the call
        runs is inherited, those of the class that wrote it
        (``initializer_class``, read off the one base walk).  Each default's
        key names its own ``def`` (``nodes._default_evaluation_key``), so the
        one each omitted formal reads is the value its ``def`` statement
        evaluated when that class body ran."""
        owner = self.initializer_class()
        if owner is None or owner is self:
            return self.method_defaults
        return (*self.method_defaults, *owner.method_defaults)

    def initializer_class(self) -> "ClassDefinitionValue | None":
        """The class value whose source ``__init__`` a call of this class
        runs: the first ``__init__`` of the class's MRO read by binding
        (``ClassDef.initializer_entry``, the one base walk), found among this
        value and its C3 tail by its class statement's occurrence.  None when
        that ``__init__`` is a builtin's, is not decided, or its class has no
        value here."""
        definition = self.class_definition
        if definition is None:
            return None
        owner = definition.initializer_entry()
        if owner is None or isinstance(owner, str):
            return None
        return self.class_value_of_statement(owner)

    def class_value_of_statement(self, owner) -> "ClassDefinitionValue | None":
        """The class value built from the class statement ``owner``: this
        value, or the class of its C3 tail whose statement is that
        occurrence.  None when ``owner`` is None or no class here is it."""
        from sugar_source_tree.occurrence import SourceOccurrenceIdentityV1

        if owner is None:
            return None
        if owner is self.class_definition:
            return self
        identity = SourceOccurrenceIdentityV1.of(owner)
        return next(
            (
                cls
                for cls in (self, *self._c3_tail())
                if cls.class_definition is not None
                and SourceOccurrenceIdentityV1.of(cls.class_definition) == identity
            ),
            None,
        )

    def namespace_member(self, name, roster=None, *, after=None) -> tuple:
        """``(decided, found, holder, method, value)``: what ``name`` read on
        this class's type is -- the one class-namespace lookup (#7757) every
        lift reader of a class member's value reads: an instance's attribute
        read, call, comparison and store (``ObjectValue.class_member``), a
        class-body field read off its class (``attribute``), the namespace
        row (``tree_enumerate``).  A call off a class object (``Cls.m``,
        ``call_method_value``) and ``super().m`` never read it: they state
        the dispatched call, and prove's one walk decides the member and
        whether the lookup raises (``consistency::dispatch_walk``, #7757
        NEW-7).

        - ``found`` is the class of the MRO that holds ``name``
          (``ClassDef.namespace_owner``): a ``ClassDef``, a builtin class
          name, or None when no class of the order binds it.
        - ``holder`` is the class value built from ``found`` (this value or
          one of its C3 tail).
        - The member is the binding ``found``'s body left last
          (``ClassDef.body_binder``).  A ``def`` there is ``method``: the
          function of ``roster(holder)`` that very statement wrote
          (``_written_by``; ``roster`` defaults to the holder's own
          ``methods``).  Any other binding (an assignment, a nested class)
          is ``value``, the class-body field it bound.  Never both: a
          ``def`` after a ``property`` of the same name, or an assignment
          after a ``def``, is the member, and the earlier binding is gone.

        Not decided -- ``(False, None, None, None, None)``, the one
        unanswered form, never a later class's member -- when the lookup is
        not (an unread base, a decorator, a store, a conditional binding),
        when the class that holds it holds a value its body did not bind
        (``ClassDef.namespace_value_is_body``), when that class has no class
        value here, when the ``def`` it holds is decorated by anything but a
        builtin descriptor or an identity decorator (its value is the
        decorator's result, ``ClassDef.method_value_is_written``), when the
        ``def``'s function is not in the roster, and when the binding's
        value is not carried here.  A class value built with no class
        statement has no lookup to read: not decided."""
        from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef

        undecided = (False, None, None, None, None)
        definition = self.class_definition
        if definition is None:
            return undecided
        decided, found = definition.namespace_owner(name, after=after)
        if not decided:
            return undecided
        if found is None or isinstance(found, str):
            return True, found, None, None, None
        if not found.namespace_value_is_body(name):
            return undecided
        holder = self.class_value_of_statement(found)
        if holder is None:
            return undecided
        binder = found.body_binder(name)
        if isinstance(binder, (FunctionDef, AsyncFunctionDef)):
            methods = holder.methods if roster is None else roster(holder)
            method = next(
                (method for method in methods if _written_by(method, binder)), None
            )
            if method is None or not found.method_value_is_written(binder):
                return undecided
            return True, found, holder, method, None
        value = next(
            (
                field.value
                for field in reversed(holder.class_fields)
                if getattr(field, "name", None) == name
            ),
            None,
        )
        if value is None:
            return undecided
        return True, found, holder, None, value

    def object_method(self, method):
        """The function ``method`` of this class's roster as a member of the
        one class-namespace lookup: its source frame, with this class -- the
        class whose body wrote it -- as its lexical ``__class__`` cell."""
        from sugar_lift_py_tests.floor import ObjectMethodValue

        frame = method.source_call_frame
        return ObjectMethodValue(
            method.name,
            frame.parameters,
            frame.frame_cid,
            tuple(coordinate.cid for coordinate in frame.formal_coordinates),
            frame,
            method.descriptor_kind,
            defining_class=self,
        )

    def call_method_value(
        self,
        name,
        arguments,
        *,
        owner,
        blame,
        ctx=None,
        keywords=(),
        required_frame=None,
    ):
        """``Cls.m(...)``: the one dispatched call looked up on this class
        object (``_dispatched_on_class``), whatever the class's order holds
        for ``m``.  The lift states the call and nothing about which member
        it finds (#7757 NEW-7): prove's one walk of the order this class's
        own proof states (``consistency::dispatch_walk``) decides which
        member runs and how ``__get__(None, cls)`` binds it (a plain
        function, a function field or a ``staticmethod`` unbound, the
        written actuals as they stand; a ``classmethod`` with the class
        first), and the raise the lookup itself takes: a property read off
        its class is the property object, which is not callable
        (``TypeError``).  A name no class of the order binds stays owed
        there (the metaclass, which no row states, may answer it).  Every
        other lookup prove does not decide stays owed, both faces standing.
        Where this class names no join symbol (no workspace root) or the
        call has no site, the one unanswered call of ``Cls.<name>``, owed.

        No frame is selected here, so none is checked against one a call
        form authenticated (``required_frame``)."""
        del owner, ctx, required_frame
        return self._dispatched_on_class(name, arguments, keywords, blame)

    def attribute(self, name, site, ctx):
        """``Cls.name``: a read off the class object itself.

        CPython reads it by ``type.__getattribute__`` (``type_getattro``,
        Objects/typeobject.c): a data descriptor the metaclass's MRO binds
        for ``name`` wins; else the first class of ``Cls.__mro__`` whose
        ``__dict__`` holds ``name`` answers, through that value's
        ``__get__(None, Cls)`` when its type has one; else a metaclass
        attribute; else ``AttributeError``.

        Decided here only where every step is read:

        - the metaclass is ``type`` (``_metaclass_is_type``: the order is
          read and no class statement of it is created with a keyword), and
          ``type`` (with ``object``) holds no data descriptor named ``name``;
        - the one class-namespace lookup (``namespace_member``, the lookup
          an instance's read of a class field reads, ``ObjectValue.class_member``)
          decides a class-body field -- not a ``def``, not a builtin base's
          member, not a name no class binds;
        - the field's value is an immutable builtin all the way down
          (``_immutable_builtin``: a number, ``str``, ``bytes``, ``None``,
          ``bool``, a tuple of those), whose type has no ``__get__``, so the
          value read is the value the class body bound.

        Every other read is the one undecided attribute read
        (``floor_value.undecided_attribute_result``), two-faced and owed:
        never a value assumed and never an ``AttributeError`` named."""
        del ctx
        if self._metaclass_is_type() and not _type_data_descriptor(name):
            decided, _found, _holder, method, value = self.namespace_member(name)
            if (
                decided
                and method is None
                and value is not None
                and _immutable_builtin(value)
            ):
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(value)
        from sugar_lift_py_tests.floor.floor_value import undecided_attribute_result

        return undecided_attribute_result(
            self, name, site, owner="ClassDefinitionValue.attribute"
        )

    def _metaclass_is_type(self) -> bool:
        """Whether this class's metaclass is decided to be ``type``: its
        statement and every class statement of its MRO is created with no
        keyword (a ``metaclass=`` keyword, or one a base's metaclass reads),
        and the order is read (an unread base may carry any metaclass).  The
        builtin entries of a read order (``object``, ``dict``, ``type``, the
        builtin exceptions) are each of metaclass ``type``."""
        from sugar_source_tree.nodes import ClassDef

        definition = self.class_definition
        if definition is None:
            return False
        order = definition.method_resolution_order()
        if order is None:
            return False
        return not any(
            isinstance(entry, ClassDef) and entry.keywords for entry in order
        )

    def test_python_type(self, value, site):
        """``isinstance(value, Cls)`` for this source class.

        CPython answers ``True`` before any ``__instancecheck__`` when
        ``type(value) is Cls``.  ``value`` is that when it is an instance a
        call of this very class value made in the frame reading it
        (``fresh_receiver``'s ``defining_class``; its class is the one it was
        made with while its contents are current) and no store in this frame
        reassigned its ``__class__``.  The class is this value itself, never
        another run of the same statement (a ``class`` in a function called
        twice is two classes).

        Every other operand -- a class call's result, an instance of another
        class or of a subclass, one that arrived by binding, a value whose
        type is not read here -- is the term ``python:isinstance(<x>,
        "<class symbol>")`` (#7757), where this class has a join symbol and
        its metaclass is ``type`` (``_metaclass_is_type``: no
        ``__instancecheck__`` but ``type``'s runs).  Prove relates it to the
        class a contract states of ``<x>`` by one law
        (``consistency::with_isinstance_law``): ``python:type_is(<x>, D)``
        and ``D``'s order, read off its namespace row, containing this class
        give ``python:isinstance(<x>, "<C>") == true``.  A class call's
        result is named by the state its class's contract states the class
        of, ``python:after(<call result>, "out")`` (as a field read of it
        is, ``CallSiteValue.attribute``).  A class whose metaclass is not
        decided to be ``type`` (its ``__instancecheck__`` may be anything)
        keeps the one refusal (``FloorValue.test_python_type``).

        That term is two-faced (``_isinstance_faces``): where ``type(x)`` is
        no subclass of this class, ``type.__instancecheck__``
        (``object_isinstance``, Objects/abstract.c) reads ``x.__class__``,
        and a class of ``type(x)``'s order that binds ``__class__`` (a
        property) or ``__getattribute__`` runs code there that may raise.
        The test completes only under ``python:isinstance.completes``, which
        prove's isinstance law decides from the class a contract states of
        ``x``; its halt face is owed, never dropped."""
        from sugar_lift_py_tests.floor.object_identity import contents_current
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        instance = _instance_held_by(value)
        if (
            isinstance(instance, ObjectValue)
            and contents_current(instance)
            and "__class__" not in (field.name for field in instance.fields)
            and instance.defining_class is self
        ):
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        tested = self._isinstance_faces(value, site)
        if tested is not None:
            return tested
        return super().test_python_type(value, site)

    def _isinstance_faces(self, value, site):
        """The two faces of ``isinstance(<value>, <this class>)``
        (``test_python_type``), or None where this class has no join symbol
        or its metaclass is not decided to be ``type``.

        The value is ``python:isinstance(<value>, "<class symbol>")``; it
        completes under ``python:isinstance.completes(<that term>, <key>)``,
        keyed on the exact source site (two tests of one object may read a
        ``__class__`` that answers differently), and halts with an
        ``UndeterminedRaiseEffect`` under the complement, owed at the site
        (``ExitSet.two_faced``).  Prove's isinstance law
        (``consistency::isinstance_law_facts``) decides the completion where
        a contract states ``python:type_is(<value>, "<D>")`` and either
        ``D``'s order holds this class (``True`` before anything runs) or
        every class of ``D``'s order has a namespace row binding neither
        ``__class__`` nor ``__getattribute__`` and the only builtin in it is
        ``object`` (``x.__class__`` is ``object.__class__``'s getter, which
        never raises and returns ``D``: the test is ``False``).  Nothing else
        decides it, so the halt stays owed."""
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.floor_value import _siteless_undecided_read
        from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.receiver_dispatch import (
            ISINSTANCE,
            ISINSTANCE_COMPLETES,
        )
        from sugar_lift_py_tests.source_call_resolution import (
            CALL_RESULT_LABEL,
            object_after_call,
        )

        definition = self.class_definition
        if definition is None or not self._metaclass_is_type():
            return None
        symbol = definition.bridge_source_symbol()
        if symbol is None:
            return None
        owner = "ClassDefinitionValue.test_python_type"
        if site is None:
            _siteless_undecided_read(
                owner, f"isinstance(..., {self.class_name})", "Call"
            )
        _binds, held = peel_walrus_binds(value)
        term_owner = str(site)
        subject = value.to_term(owner=term_owner)
        if isinstance(held, CallSiteValue) and held.constructed_by_edge:
            subject = object_after_call(
                held.to_term(owner=term_owner), CALL_RESULT_LABEL
            )
        tested = ctor(ISINSTANCE, [subject, str_const(symbol)])
        key = occurrence_key(site)
        return ExitSet.two_faced(
            SymbolicValue(tested),
            UndeterminedRaiseEffect(
                blame=str(site),
                occurrence=key,
                producer_node_owner=owner,
                site=site,
            ),
            guard=atomic(ISINSTANCE_COMPLETES, [tested, str_const(key)]),
            site=site,
        )

    def to_term(self, *, owner: str):
        del owner
        return class_definition_term(self.class_definition_cid)

    def setitem(self, index, value, site, ctx):
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ClassDefinitionValue.setitem",
        )

    def delitem(self, index, site, ctx):
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ClassDefinitionValue.delitem",
        )

    def fresh_receiver(self, receiver_coordinate_cid, *, allocation, arrival=None):
        """The object a class call makes for its initializer to run on: no
        instance fields yet, identified by the call's receiver coordinate.
        What the call returns is that object as the initializer left it
        (``ClassConstructorBodySugar._receiver_where_it_ends``).

        ``allocation`` is the construction that made it in the frame
        reading it (``object_identity.made_at`` of the class call's site):
        its fields are its fields now (``object_identity.contents_current``).
        Required: None, with the ``arrival`` that names it, when no class
        call of the reading frame made it (an initializer's own universe,
        where the receiver reached ``__init__`` by binding).

        A ``dict`` subclass's instance is this same instance: its members,
        ``dict``'s among them, are read and called through the one
        class-namespace lookup and the dispatched call prove's walk decides
        (#7757 S1), never answered from base storage held here."""
        from sugar_lift_py_tests.floor import ObjectValue

        return ObjectValue(
            self.class_name,
            (),
            methods=self._object_methods(),
            class_fields=self.class_fields,
            identity=receiver_coordinate_cid or self.class_definition_cid,
            defining_class=self,
            allocation=allocation,
            arrival=arrival,
        )

    def _object_methods(self):
        # The frames of every source method of the class and its C3 tail,
        # each with the class value whose body wrote it.  Which one a name
        # selects is never read off this roster's order: the one
        # class-namespace lookup names the class that holds it
        # (``namespace_member``), and its method here is the one that class
        # wrote.  A base method is retained with its original authenticated
        # source frame; nothing is reconstructed here.
        inherited = tuple(
            (base, method)
            for base in reversed(self._c3_tail())
            for method in base.methods
        )
        owned = (*inherited, *((self, method) for method in self.methods))
        return tuple(
            defining_class.object_method(method) for defining_class, method in owned
        )

    def _c3_tail(self) -> tuple["ClassDefinitionValue", ...]:
        source_bases = tuple(
            base for base in self.base_classes if isinstance(base, ClassDefinitionValue)
        )
        return c3_tail(
            source_bases,
            lambda base: base._c3_tail(),
            blame=self.class_definition_cid,
            owner="ClassDefinitionValue._c3_tail",
        )


def _instance_class_symbol(definition) -> str | None:
    """The join symbol of the class ``definition`` states, when a call of it
    is decided to make an instance of exactly that class: the call is
    ``type.__call__`` (no metaclass, no keyword, an order read) and the
    ``__new__`` it runs is a builtin's (``ClassDef.call_yields_an_instance``),
    which makes an instance of the class called.  Its ``__init__``, source
    or not, runs on that instance and cannot give it another class but by a
    store to ``__class__``, which the class's contract reads
    (``ConstructedInstanceValue.post_formula``: a ``__class__`` field, or an
    instance handed to code, states no class).

    None where a source ``__new__`` or a metaclass ``__call__`` makes the
    result (or the order is not read): its class is undecided, by name.

    What the instance's ``__dict__`` holds is not read here: the class's
    contract states it with the class, and prove binds a dispatch over the
    result to that statement (#7757 step 8)."""
    if not definition.call_yields_an_instance(definition.unit.class_namespace_stores):
        return None
    return definition.bridge_source_symbol()


def _instance_held_by(value):
    """The object ``value`` holds: itself.  None for a call's result: no
    callee body is applied at lift (#7757 step 6), so the type test reads no
    object off a call; what the call returns is its contract's, joined at
    prove."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds

    _binds, held = peel_walrus_binds(value)
    if isinstance(held, CallSiteValue):
        return None
    return held


def _written_by(method, binder) -> bool:
    """Whether the roster function ``method`` is the one the class-body
    ``def`` statement ``binder`` wrote: its definition is that very source
    occurrence (a deferred method carries its ``definition``; a built one
    its frame's ``owner``).  Never matched by name."""
    from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef
    from sugar_source_tree.occurrence import SourceOccurrenceIdentityV1

    statement = getattr(method, "definition", None)
    if statement is None:
        statement = getattr(method.source_call_frame, "owner", None)
    return isinstance(
        statement, (FunctionDef, AsyncFunctionDef)
    ) and SourceOccurrenceIdentityV1.of(statement) == SourceOccurrenceIdentityV1.of(
        binder
    )


def c3_tail(bases, tail_of, *, blame, owner: str) -> tuple:
    """The C3 linearization after the head, for a head with these direct bases.

    ``tail_of(base)`` is that base's own tail.  Shared by the Floor's class
    values and the source absence proof over class definitions, so both read
    one MRO law.  An inconsistent base order refuses (CPython raises at class
    creation; nothing here chooses an order).
    """
    bases = tuple(bases)
    if not bases:
        return ()
    sequences = [list((base, *tail_of(base))) for base in bases]
    sequences.append(list(bases))
    result = []
    while any(sequences):
        sequences = [sequence for sequence in sequences if sequence]
        candidate = next(
            (
                sequence[0]
                for sequence in sequences
                if not any(sequence[0] in other[1:] for other in sequences)
            ),
            None,
        )
        if candidate is None:
            raise SugarNotWritten(
                blame=blame,
                owner=owner,
                observed="inconsistent authenticated local base order",
                requested="one valid C3 linearization",
                fix="keep inconsistent or dynamic inheritance loud",
            )
        result.append(candidate)
        for sequence in sequences:
            if sequence and sequence[0] == candidate:
                sequence.pop(0)
    return tuple(result)


def class_definition_term(class_definition_cid: str):
    """The term a source class object is spelled by wherever a reduction
    reads it (``ClassDefinitionValue.to_term``):
    ``python:class-definition(<class definition cid>)``.  A class's namespace
    row states it (``tree_enumerate.class_namespace_row``,
    ``python:class_object``), so a ``classmethod`` dispatched at prove binds
    the very term a reading of the class here is (#7757 step 8)."""
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:class-definition",
        [str_const(class_definition_cid)],
        symbol_kind="coordinate",
    )


def _type_data_descriptor(name: str) -> bool:
    """Whether the metaclass ``type`` binds ``name`` to a data descriptor
    along its own MRO (``type``, ``object``): ``__name__``, ``__qualname__``,
    ``__doc__``, ``__module__``, ``__dict__``, ``__class__``, ... .  Such a
    binding wins over the class's own ``__dict__`` in ``type_getattro``, so a
    read of it off a class is not the class-body field
    (``ClassDefinitionValue.attribute``)."""
    for meta in type.__mro__:
        held = vars(meta).get(name)
        if held is None:
            continue
        kind = type(held)
        return hasattr(kind, "__set__") or hasattr(kind, "__delete__")
    return False


def _immutable_builtin(value) -> bool:
    """Whether ``value`` is an immutable builtin all the way down: a number
    (``TermValue``), ``str``, ``bytes``, ``None``, ``True``/``False``, or a
    tuple of those.  None of those types has a ``__get__``, and none of them
    can be changed after the class body bound it, so the value a read of the
    class field gets is the one the body bound."""
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    if type(value) in (
        TermValue,
        StringValue,
        BytesValue,
        NoneValue,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
    ):
        return True
    if type(value) is TupleValue:
        return all(_immutable_builtin(element) for element in value.elements)
    return False
