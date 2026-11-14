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
    """A method whose body refused at class construction.

    A ``def`` in a class body binds a function; the body runs only when the
    method is called.  The class statement completes; whoever reads the
    method's body or frame (its caller) constructs it again and meets the
    refusal there.  The refusal is never testimony about the class statement.
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
    # class body evaluated it (``ClassDefinitionSugar._class_body``), under
    # its per-parameter key (``nodes._default_evaluation_key``).  Python
    # stores the values on the function; every call that omits the formal
    # binds that one object (``object_value.bind_method_call`` passes them
    # to ``bind_call``'s ``defaults``, as a lambda value's are, and a class
    # call its constructor's, ``constructor_defaults``).
    method_defaults: tuple = field(default=(), compare=False)

    def __post_init__(self):
        if type(self.binding_target_occurrence) is not SourceFragmentCoordinateV1:
            raise TypeError(
                "ClassDefinitionValue binding target must be an exact "
                "SourceFragmentCoordinateV1"
            )

    def callable_application_with(self, operation, ctx):
        """``Cls(*args, **kw)`` reached as a value: the same call as by name.

        A class call applies the class statement's constructor frame
        (``ClassDef.source_visible_constructor_frame``: initializer, source
        ``__new__``, dataclass and inherited-exception arms) through the one
        application routine, ``CallSiteValue.producer_outcome``, exactly as
        ``CallSiteSugar`` applies it for a lexically named class.  Every face of
        the constructor, halts included, is this call's.  The call is bound
        where the class call reads the class statement
        (``ClassConstructorBodySugar.bind_class_call``), with the constructor
        defaults the class value carries (``constructor_defaults``).

        A class whose constructor its own statement does not decide (no
        source ``__new__`` shape, no ``dataclass``-written ``__init__``) and
        whose MRO does not construct by the laws the lifter reads
        (``ClassDef.construction_order`` is None: a base the lifter cannot
        read, or ``OSError``/``SyntaxError``/... anywhere in it) is the one
        unanswered call (``UnknownCalleeCallV1``), exactly as the same class
        called by name is: never the zero-formal ``object`` frame or the
        ``(*args)`` frame applied to a constructor nothing here read.
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
        if (
            definition._authenticated_new_constructor_shape() is None
            and definition._dataclass_generated_init_fields() is None
            and definition.construction_order() is None
        ):
            return self._unanswered_call(positional, keywords, operation.site)
        frame = definition.source_visible_constructor_frame()

        def refuse(*, owner, blame, observed, requested, fix):
            raise SugarNotWritten(
                owner=owner,
                blame=blame,
                observed=observed,
                requested=requested,
                fix=fix,
            )

        return frame.body.bind_class_call(
            ctx,
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
            ).producer_outcome(ctx),
            site=operation.site,
        )

    def _unanswered_call(self, positional, keywords, site):
        """``Cls(...)`` whose constructor nothing here read: the one
        unanswered call (``UnknownCalleeCallV1``), two-faced and owed, its
        completion the call's own result coordinate."""
        from sugar_lift_py_tests.call_symbol import call_symbol
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

        owner = str(site)
        callsite = CallSiteValue(
            target_name=self.class_name,
            arg_values=(*positional, *(value for _name, value in keywords)),
            parameters=(),
            term=ctor(
                call_symbol(self.class_name),
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
        return UnknownCalleeCallV1(self.class_name).faces(callsite, site)

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
        """Invoke one authenticated source method on the class object."""
        candidates = tuple(method for method in self.methods if method.name == name)
        if required_frame is not None:
            candidates = tuple(
                method
                for method in candidates
                if method.source_call_frame.frame_cid == required_frame.frame_cid
            )
        if len(candidates) != 1:
            raise SugarNotWritten(
                owner=owner,
                blame=blame,
                observed=f"{len(candidates)} source methods for {self.class_name}.{name}",
                requested="one authenticated class-method definition",
                fix="preserve unique method resolution or keep the call loud",
            )
        method = candidates[0]
        if method.descriptor_kind == "property":
            # ``Cls.p`` is the property object itself, which is not callable.
            raise SugarNotWritten(
                owner=owner,
                blame=blame,
                observed=f"{self.class_name}.{name} is a property read off its class",
                requested="a callable class attribute",
                fix="read the property off an instance, or keep the call loud",
            )
        frame = required_frame or method.source_call_frame
        from sugar_lift_py_tests.floor import ObjectMethodValue
        from sugar_lift_py_tests.floor.object_value import bind_method_call
        from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

        def refuse(*, owner, blame, observed, requested, fix):
            del owner, blame, requested, fix
            raise SourceCallBindingGap(observed)

        # ``Cls.m(...)`` binds through the one method door, which reads the
        # lookup's implicit first actual off the descriptor kind
        # (``object_value.implicit_arguments``): a plain function read off its
        # class is unbound and takes none, a ``classmethod`` takes the class,
        # a ``staticmethod`` none.  The class is ``m``'s lexical
        # ``__class__`` cell.
        return bind_method_call(
            self,
            ObjectMethodValue(
                method.name,
                frame.parameters,
                frame.body,
                frame.frame_cid,
                tuple(coordinate.cid for coordinate in frame.formal_coordinates),
                frame,
                method.descriptor_kind,
                defining_class=self,
            ),
            arguments,
            keywords,
            class_name=self.class_name,
            ctx=ctx,
            owner=owner,
            blame=blame,
            refuse=refuse,
            required_frame=required_frame,
        ).producer_outcome(ctx)

    def dispatch_super_method(
        self,
        receiver,
        name,
        arguments,
        *,
        owner,
        blame,
        ctx=None,
        keywords=(),
    ):
        """Run THIS class's own method ``name``, bound to an explicit
        ``receiver``.

        Zero-argument ``super()`` selects the class by its one lookup
        (``ClassDef.namespace_owner`` over ``type(receiver).__mro__`` after
        ``__class__``, ``BuiltinSuperValue``): this class's namespace binds
        ``name``, so the function its body wrote for it (the last ``def``,
        Python's live binding) is the one that runs -- never one this class
        inherits.  The original instance stays the bound ``self`` while the
        body reduces with ``__class__`` seeded to this class (its defining
        class), so a chained ``super`` inside it continues along the
        receiver's MRO after this class.  It is the same bound-method call
        as ``ObjectValue.call_method_value`` (``bind_method_call`` then
        ``producer_outcome``).  A name the body binds by anything but a
        ``def`` (an assignment, an import) has no method here and refuses by
        name.
        """
        from sugar_lift_py_tests.floor import ObjectMethodValue
        from sugar_lift_py_tests.floor.object_value import bind_method_call

        def refuse(*, owner, blame, observed, requested, fix):
            raise SugarNotWritten(
                owner=owner,
                blame=blame,
                observed=observed,
                requested=requested,
                fix=fix,
            )

        written = tuple(method for method in self.methods if method.name == name)
        if not written:
            raise SugarNotWritten(
                owner=owner,
                blame=blame,
                observed=f"{self.class_name}.{name}",
                requested="the source method zero-argument super selected",
                fix=f"construct a diggable body for `{self.class_name}.{name}` or keep loud",
            )
        method = written[-1]
        frame = method.source_call_frame
        return bind_method_call(
            receiver,
            ObjectMethodValue(
                method.name,
                frame.parameters,
                frame.body,
                frame.frame_cid,
                tuple(coordinate.cid for coordinate in frame.formal_coordinates),
                frame,
                method.descriptor_kind,
                defining_class=self,
            ),
            arguments,
            keywords,
            class_name=self.class_name,
            ctx=ctx,
            owner=owner,
            blame=blame,
            refuse=refuse,
        ).producer_outcome(ctx)

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
        from sugar_lift_py_tests.floor import ObjectMethodValue

        # ObjectValue searches from the end, so emit the reversed C3 lookup
        # tail before this class's methods.  A base method is retained with its
        # original authenticated source frame; nothing is reconstructed here.
        inherited = tuple(
            (base, method)
            for base in reversed(self._c3_tail())
            for method in base.methods
        )
        owned = (*inherited, *((self, method) for method in self.methods))
        return tuple(
            ObjectMethodValue(
                method.name,
                method.source_call_frame.parameters,
                method.source_call_frame.body,
                method.source_call_frame.frame_cid,
                tuple(
                    coordinate.cid
                    for coordinate in method.source_call_frame.formal_coordinates
                ),
                method.source_call_frame,
                method.descriptor_kind,
                defining_class=defining_class,
            )
            for defining_class, method in owned
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
