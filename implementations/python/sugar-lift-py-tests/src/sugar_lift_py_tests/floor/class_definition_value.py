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
    # binds that one object (``object_value.bind_method_call`` passes them
    # to ``bind_call``'s ``defaults``, as a lambda value's are, and a class
    # call its constructor's, ``constructor_defaults``).
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
        class's name is its statement's evaluation key).  It applies the
        class statement's constructor frame
        (``ClassDef.source_visible_constructor_frame``: initializer, source
        ``__new__``, dataclass and inherited-exception arms) through the one
        application routine, ``CallSiteValue.producer_outcome``.  Every face of the
        constructor, halts included, is this call's.  The call is bound on
        this value (``ClassConstructorBodySugar.bind_class_call``, entered
        with ``class_value``), with the constructor defaults it carries
        (``constructor_defaults``); the class statement already ran where
        the value was built and is never reduced again here.

        A class whose constructor its own statement does not decide (no
        source ``__new__`` shape, no ``dataclass``-written ``__init__``) and
        whose MRO does not construct by the laws the lifter reads
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
        generated = definition._dataclass_generated_init_fields()
        if generated is not None:
            new_decided, own_new = definition.dataclass_new_entry()
            unanswered = not new_decided or own_new is not None
        else:
            unanswered = not definition.new_entry()[0] or (
                definition._authenticated_new_constructor_shape() is None
                and (
                    definition.construction_order() is None
                    or definition.initializer_entry() is None
                )
            )
        if unanswered:
            return self._unanswered_call(
                self.class_name, positional, keywords, operation.site
            )
        frame = definition.source_visible_constructor_frame()
        # The call reads the class it was given: this value, the class the
        # statement's run built and the name's read (its evaluation key)
        # answered.  The constructor is entered on it (``class_value``), at
        # this call (``call_site``); the class statement is never reduced
        # again at the call (#7757).
        from dataclasses import replace

        body = replace(frame.body, class_value=self, call_site=operation.site)

        def refuse(*, owner, blame, observed, requested, fix):
            raise SugarNotWritten(
                owner=owner,
                blame=blame,
                observed=observed,
                requested=requested,
                fix=fix,
            )

        return body.bind_class_call(
            lambda defaults, body: bind_call(
                self.class_name,
                positional,
                keywords,
                frame=frame,
                parameters=frame.parameters,
                body=body,
                frame_cid=frame.frame_cid,
                formal_coordinate_cids=tuple(
                    coordinate.cid for coordinate in frame.formal_coordinates
                ),
                ctx=ctx,
                owner="ClassDefinitionValue.callable_application_with",
                blame=operation.site,
                refuse=refuse,
                defaults=defaults,
                # The class a raise authenticated for this callee: the
                # instance the constructor builds is of it, so the call
                # carries it, as a plain call of a builtin exception does
                # (``RaiseSugar._effect`` reads the class off the value).
                exception_type_coordinate=getattr(
                    operation, "exception_type_coordinate", None
                ),
                exception_type_mro=getattr(operation, "exception_type_mro", None),
            ).producer_outcome(ctx),
        )

    def _unanswered_call(self, target, positional, keywords, site):
        """``Cls(...)`` whose constructor nothing here read, or ``Cls.m(...)``
        whose ``m`` the one class-namespace lookup does not decide: the one
        unanswered call of ``target`` (``UnknownCalleeCallV1``), two-faced
        and owed, its completion the call's own result coordinate."""
        from sugar_lift_py_tests.call_symbol import call_symbol
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

        owner = str(site)
        callsite = CallSiteValue(
            target_name=target,
            arg_values=(*positional, *(value for _name, value in keywords)),
            parameters=(),
            term=ctor(
                call_symbol(target),
                [value.to_term(owner=owner) for value in positional]
                + [
                    ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
                    for name, value in keywords
                ],
                symbol_kind="coordinate",
            ),
            body=None,
            keyword_names=tuple(name for name, _value in keywords),
            site=site,
        )
        return UnknownCalleeCallV1(target).faces(callsite, site)

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
        this class's type is -- the one class-namespace lookup (#7757), and
        the one resolution every reader of a class member reads: an
        instance's attribute read, call, comparison and store
        (``ObjectValue.class_member``), ``Cls.m`` (``call_method_value``) and
        ``super().m`` (``after``: the lookup from the class after the
        ``__class__`` cell, ``BuiltinSuperValue``).

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
        """The function ``method`` of this class's roster as the one method
        door binds it (``object_value.bind_method_call``): its source frame,
        with this class -- the class whose body wrote it -- as its lexical
        ``__class__`` cell."""
        from sugar_lift_py_tests.floor import ObjectMethodValue

        frame = method.source_call_frame
        return ObjectMethodValue(
            method.name,
            frame.parameters,
            frame.body,
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
        """``Cls.m(...)``: the member the one class-namespace lookup selects
        for ``m`` on this class (``namespace_member``), read off the class
        and called.  Nothing selects it again by name.

        - A ``def`` the holding class's body left last runs with that class
          as its ``__class__`` cell, through the one method door, whose
          implicit first actual the descriptor kind reads
          (``object_value.implicit_arguments``): a plain function read off
          its class is unbound and takes none, a ``classmethod`` takes the
          class, a ``staticmethod`` none.  A frame the call form
          authenticated must be that function's own.
        - A function the class namespace holds as a field (``f = lambda x:
          x``, ``m = some_def``), read off its class, is the function itself,
          unbound: the function's own call applies the written actuals
          (``LambdaCallable.callable_application_with``).
        - A lookup it does not decide is the unanswered call; a name no
          source class of the order holds, a property (the property object
          is not callable) and any other value refuse by name."""
        decided, found, holder, method, value = self.namespace_member(name)
        if not decided:
            return self._unanswered_call(
                f"{self.class_name}.{name}",
                arguments,
                keywords,
                blame,
            )
        if method is not None:
            if method.descriptor_kind == "property":
                # ``Cls.p`` is the property object itself, which is not callable.
                raise SugarNotWritten(
                    owner=owner,
                    blame=blame,
                    observed=f"{self.class_name}.{name} is a property read off its class",
                    requested="a callable class attribute",
                    fix="read the property off an instance, or keep the call loud",
                )
            if (
                required_frame is not None
                and method.source_call_frame.frame_cid != required_frame.frame_cid
            ):
                raise SugarNotWritten(
                    owner=owner,
                    blame=blame,
                    observed=(
                        f"{self.class_name}.{name}: the authenticated frame is not "
                        "the selected method's"
                    ),
                    requested="the frame of the method the one lookup selected",
                    fix="authenticate the call against the selected method's frame",
                )
            from sugar_lift_py_tests.floor.object_value import bind_method_call
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

            def refuse(*, owner, blame, observed, requested, fix):
                del owner, blame, requested, fix
                raise SourceCallBindingGap(observed)

            return bind_method_call(
                self,
                holder.object_method(method),
                arguments,
                keywords,
                class_name=self.class_name,
                ctx=ctx,
                owner=owner,
                blame=blame,
                refuse=refuse,
                required_frame=required_frame,
            ).producer_outcome(ctx)
        from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable

        if isinstance(value, LambdaCallable) and required_frame is None:
            from sugar_lift_py_tests.callable_application import CallableApplication

            return value.callable_application_with(
                CallableApplication(
                    (*arguments, *(actual for _keyword, actual in keywords)),
                    tuple(keyword for keyword, _actual in keywords),
                    blame,
                ),
                ctx,
            )
        raise SugarNotWritten(
            owner=owner,
            blame=blame,
            observed=(
                f"{self.class_name}.{name} is held by "
                f"{getattr(found, 'name', found)}"
            ),
            requested="one authenticated class-method definition",
            fix="preserve unique method resolution or keep the call loud",
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
        twice is two classes).  Every other operand -- an instance of another
        class or of a subclass, one that arrived by binding, a value whose
        type is not read here -- is not decided here: the one undecided type
        test (``FloorValue.test_python_type``)."""
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
        return super().test_python_type(value, site)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:class-definition",
            [str_const(self.class_definition_cid)],
            symbol_kind="coordinate",
        )

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
        where the receiver reached ``__init__`` by binding)."""
        from sugar_lift_py_tests.floor import MappingObjectValue, ObjectValue

        receiver_type = (
            MappingObjectValue if self._has_authenticated_dict_base() else ObjectValue
        )
        return receiver_type(
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

    def _has_authenticated_dict_base(self) -> bool:
        from sugar_lift_py_tests.floor.builtin_dict_class_value import (
            BuiltinDictClassValue,
        )

        pending = list(self.base_classes)
        seen: set[int] = set()
        while pending:
            base = pending.pop()
            if isinstance(base, BuiltinDictClassValue):
                return True
            if not isinstance(base, ClassDefinitionValue) or id(base) in seen:
                continue
            seen.add(id(base))
            pending.extend(base.base_classes)
        return False


def _instance_held_by(value):
    """The object ``value`` holds: itself, or -- for a call that already ran
    its body (a class call: the receiver its constructor left) -- the floor
    that call completed with (``CallSiteValue._dig_floor_or_none``), under
    the callee stores it carries.  None where a call's floor is not one
    completed value, and where the call has not run: the type test never
    applies a body again."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds

    _binds, held = peel_walrus_binds(value)
    if isinstance(held, CallSiteValue):
        if held.retained_source_completion_outcome() is None:
            return None
        return held._dig_floor_or_none(
            None, owner="ClassDefinitionValue.test_python_type"
        )
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
