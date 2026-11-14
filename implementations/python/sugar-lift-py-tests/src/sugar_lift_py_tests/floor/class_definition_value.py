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

    def builtin_initializer_class(self):
        """The builtin exception class whose ``__init__`` is the first of this
        class's MRO (``ClassDef.initializer_entry``), as the builtin namespace
        binds it; None when that ``__init__`` is a source class's,
        ``object``'s, or is not decided."""
        definition = self.class_definition
        if definition is None:
            return None
        owner = definition.initializer_entry()
        if not isinstance(owner, str) or owner == "object":
            return None
        from sugar_lift_py_tests.floor.builtin_exception_class_value import (
            BuiltinExceptionClassValue,
        )
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_name_temporal,
        )

        value = builtin_name_temporal().value_if_bound(owner)
        return value if isinstance(value, BuiltinExceptionClassValue) else None

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
        """Run method ``name`` resolved from THIS class's MRO, bound to an
        explicit ``receiver``.

        Zero-argument ``super()`` uses this to invoke a selected source-defined
        base method: the original instance stays the bound ``self`` while the
        base body reduces with ``__class__`` seeded to the method's defining
        class, so a chained ``super`` inside that body selects the next class.
        It is the same bound-method call as ``ObjectValue.call_method_value``
        (``bind_method_call`` then ``producer_outcome``); only the method table (this
        class's ``_object_methods`` MRO) and the explicit receiver differ.
        """
        from sugar_lift_py_tests.floor.object_value import bind_method_call

        def refuse(*, owner, blame, observed, requested, fix):
            raise SugarNotWritten(
                owner=owner,
                blame=blame,
                observed=observed,
                requested=requested,
                fix=fix,
            )

        if name == "__init__":
            # The first ``__init__`` of this class's MRO, by the one base
            # walk: a builtin exception's is BaseException's law on the
            # receiver, wherever a source class stands after it.
            builtin = self.builtin_initializer_class()
            if builtin is not None:
                return builtin.initialize_instance(
                    receiver, arguments, keywords, blame=blame, owner=owner
                )
        for method in reversed(self._object_methods()):
            if method.name != name:
                continue
            return bind_method_call(
                receiver,
                method,
                arguments,
                keywords,
                class_name=self.class_name,
                ctx=ctx,
                owner=owner,
                blame=blame,
                refuse=refuse,
            ).producer_outcome(ctx)
        raise SugarNotWritten(
            owner=owner,
            blame=blame,
            observed=f"{self.class_name}.{name}",
            requested="a source-defined base method for zero-argument super",
            fix=f"construct a diggable body for `{self.class_name}.{name}` or keep loud",
        )

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

    def construct_receiver_state_from_block(self, block, receiver_coordinate_cid):
        from sugar_lift_py_tests.floor import (
            GuardedReceiverFieldStoreValue,
            GuardedReceiverStateValue,
            MappingObjectValue,
            ObjectField,
            ObjectMethodValue,
            ObjectValue,
            ReceiverFieldStoreValue,
            ReceiverStatePartitionValue,
        )
        from sugar_lift_py_tests.ir import (
            _term_content_cid,
            ctor,
            str_const,
        )
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.outcome.exit_set import partition

        receiver_type = (
            MappingObjectValue if self._has_authenticated_dict_base() else ObjectValue
        )
        receiver = receiver_type(
            self.class_name,
            (),
            methods=self._object_methods(),
            class_fields=self.class_fields,
            identity=receiver_coordinate_cid or self.class_definition_cid,
            defining_class=self,
        )
        if block is None:
            return receiver
        # A builtin's transition of this receiver (``super().__init__(...)``
        # into BaseException's ``__init__``,
        # ``BuiltinExceptionClassValue.initialize_instance``) is the receiver
        # it left: a snapshot of this receiver's state, never dropped.
        block = _receiver_transitions_applied(block, receiver.identity)
        # The initializer may reduce directly to the CONSTRUCTED receiver -- an
        # ObjectValue that already carries __init__'s field stores -- rather
        # than to pending ReceiverFieldStoreValue statements. The same-module
        # path leaves stores pending; the import/frame door completes them into
        # the receiver (its ObjectValue.identity is exactly this receiver
        # coordinate). A block that is exactly this receiver IS the receiver;
        # rebuilding an empty one here dropped every __init__ field on the
        # frame door (enter-may-halt ObjectValue.attribute, plan Cut 6).
        if (
            len(block.statements) == 1
            and isinstance(block.statements[0], (ObjectValue, MappingObjectValue))
            and getattr(
                block.statements[0].defining_class, "class_definition_cid", None
            )
            == self.class_definition_cid
            and block.statements[0].identity == receiver.identity
        ):
            return block.statements[0]
        guarded_updates = tuple(
            statement
            for statement in block.statements
            if isinstance(
                statement, (GuardedReceiverFieldStoreValue, GuardedReceiverStateValue)
            )
        )
        if guarded_updates:
            # Completed snapshots retain the allocation's initial state on the
            # unwritten face as well; no face gets another face's field table.
            initial = (
                (receiver,)
                if any(
                    isinstance(update, GuardedReceiverStateValue)
                    for update in guarded_updates
                )
                else ()
            )
            # Each arm's value is the stores written on its path. A plain
            # statement continues every arm; a guarded store splits every arm
            # into its two faces, each a continuation beneath that arm.
            states = ExitSet.completed(initial)
            for statement in block.statements:
                if isinstance(statement, ObjectValue) or (
                    isinstance(statement, ReceiverFieldStoreValue)
                    and not isinstance(statement, GuardedReceiverFieldStoreValue)
                ):
                    states = states.sequence(
                        lambda stores, written=statement: ExitSet.completed(
                            (*stores, written)
                        )
                    )
                    continue
                if not isinstance(
                    statement, (GuardedReceiverFieldStoreValue, GuardedReceiverStateValue)
                ):
                    continue
                store = statement
                then_face, else_face = partition(
                    (
                        "receiver-field-store",
                        store.to_term(owner=self.class_definition_cid),
                    )
                )
                written = (
                    store.receiver
                    if isinstance(store, GuardedReceiverStateValue)
                    else ReceiverFieldStoreValue(store.receiver, store.attr, store.value)
                )
                states = states.sequence(
                    _store_split(store.guard, written, then_face, else_face)
                )
            return ReceiverStatePartitionValue(
                states.sequence(
                    lambda stores: ExitSet.completed(
                        self.construct_receiver_state_from_block(
                            type(block)(stores), receiver_coordinate_cid
                        )
                    )
                )
            )
        fields: dict[str, object] = {}
        snapshot = None
        for statement in block.statements:
            if isinstance(statement, ObjectValue):
                if (
                    statement.identity != receiver.identity
                    or getattr(statement.defining_class, "class_definition_cid", None)
                    != self.class_definition_cid
                ):
                    from sugar_lift_py_tests.gap.panic import construction_panic_gap

                    construction_panic_gap(
                        owner="ClassDefinitionValue.construct_receiver_state",
                        blame=receiver_coordinate_cid,
                        observed="foreign constructed receiver snapshot",
                        requested="the exact source-defined receiver being constructed",
                        fix="retain the receiver coordinate and defining class across guarded state projection",
                    )
                # A snapshot replaces fields it actually recorded. Earlier
                # extras this snapshot omits stay; they are this face's
                # already-applied writes, not a sibling branch. Unioning a
                # field the snapshot names would leak a sibling value.
                snapshot = statement
                incoming = {field.name: field.value for field in statement.fields}
                for name, value in fields.items():
                    if name not in incoming:
                        incoming[name] = value
                fields = incoming
                continue
            if not isinstance(statement, ReceiverFieldStoreValue):
                continue
            if statement.receiver.identity != receiver.identity:
                raise SugarNotWritten(
                    blame=receiver_coordinate_cid,
                    owner="ClassDefinitionValue.construct_receiver_state",
                    observed="receiver coordinate mismatch",
                    requested="stores projected from this exact constructed receiver",
                    fix="preserve BindingCoordinateV1 through initializer reduction",
                )
            fields[statement.attr] = statement.value
        ordered = tuple(
            ObjectField(name, value) for name, value in sorted(fields.items())
        )
        if snapshot is not None:
            from dataclasses import replace

            return replace(snapshot, fields=ordered)
        identity_term = ctor(
            "python:constructed-object-state",
            [
                str_const(self.class_definition_cid),
                *(
                    ctor(
                        "python:field",
                        [
                            str_const(field.name),
                            field.value.to_term(owner=self.class_definition_cid),
                        ],
                    )
                    for field in ordered
                ),
            ],
        )
        return receiver_type(
            self.class_name,
            ordered,
            methods=self._object_methods(),
            class_fields=self.class_fields,
            identity=_term_content_cid(identity_term),
            defining_class=self,
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


def _receiver_transitions_applied(block, identity):
    """``block`` with each ``ReceiverOwnedMutationResult`` of the receiver
    ``identity`` read as the receiver it left (``receiver_after``)."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
        ReceiverOwnedMutationResult,
    )

    statements = tuple(
        (
            statement.receiver_after
            if isinstance(statement, ReceiverOwnedMutationResult)
            and getattr(statement.receiver_before, "identity", None) == identity
            else statement
        )
        for statement in block.statements
    )
    if all(new is old for new, old in zip(statements, block.statements)):
        return block
    return replace(block, statements=statements)


def _store_split(guard, written, then_face, else_face):
    """One guarded store's two faces beneath an arm whose value is the stores
    written on its path: ``written`` appended under ``guard``, nothing under
    its complement, each stamped with its face of the store's split."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import complement_guard

    def split(stores):
        return (
            ExitSet.completed((*stores, written))
            .guarded(guard, then_face)
            .union(
                ExitSet.completed(stores).guarded(complement_guard(guard), else_face)
            )
        )

    return split


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
