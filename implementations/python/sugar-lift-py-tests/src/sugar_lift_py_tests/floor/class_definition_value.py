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
    # True when the class was projected over the methods its instances run
    # and this one is not among them (#7664): its body was never attempted.
    # False when the body was attempted and refused (#7659).
    unprojected: bool = False

    @property
    def body(self):
        return self.definition.sugar()

    @property
    def source_call_frame(self):
        return self.definition.source_visible_call_frame()


    def object_method(self, defining_class):
        """The instance's view of this method: bound, its body not constructed.

        An instance's method table names every method its class binds, but
        building the instance runs none of them.  The body stands as
        :class:`DeferredMethodBodySugar`, which refuses by name wherever the
        method is actually run, so a deferred method never silently completes.
        """
        from sugar_lift_py_tests.floor import ObjectMethodValue
        from sugar_lift_py_tests.sugar.deferred_method_body_sugar import (
            DeferredMethodBodySugar,
        )

        return ObjectMethodValue(
            self.name,
            tuple(param.name for param in self.definition.params),
            DeferredMethodBodySugar(self),
            None,
            (),
            None,
            self.descriptor_kind,
            defining_class=defining_class,
        )


@dataclass(frozen=True)
class ConstructedClassFieldV1:
    name: str
    definition_fragment_cid: str
    value_sugar: object = field(compare=False)
    binding_target_occurrence: SourceFragmentCoordinateV1
    evaluation_group_cid: str | None = None

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
        the constructor, halts included, is this call's.
        """
        from sugar_lift_py_tests.floor.object_value import bind_call

        if self.class_definition is None:
            raise SugarNotWritten(
                owner="ClassDefinitionValue.callable_application_with",
                blame=operation.site,
                observed=f"{self.class_name} value carries no class statement",
                requested="the class statement whose constructor frame the call applies",
                fix="build the class value from its ClassDef so its frame is applied",
            )
        frame = self.class_definition.source_visible_constructor_frame()
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

        def refuse(*, owner, blame, observed, requested, fix):
            raise SugarNotWritten(
                owner=owner,
                blame=blame,
                observed=observed,
                requested=requested,
                fix=fix,
            )

        return bind_call(
            self.class_name,
            positional,
            keywords,
            frame=frame,
            parameters=frame.parameters,
            body=frame.body,
            frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(
                coordinate.cid for coordinate in frame.formal_coordinates
            ),
            ctx=ctx,
            owner="ClassDefinitionValue.callable_application_with",
            blame=operation.site,
            refuse=refuse,
        ).producer_outcome(ctx)

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
        frame = required_frame or method.source_call_frame
        bound = frame.bind_actuals((self, *arguments), keywords, ctx)
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        call = CallSiteValue(
            target_name=f"{self.class_name}.{name}",
            arg_values=bound.actuals,
            parameters=frame.parameters,
            term=ctor(
                f"call:{self.class_name}.{name}",
                tuple(value.to_term(owner=owner) for value in bound.actuals),
                symbol_kind="contract-target",
            ),
            body=frame.body,
            site=blame,
            source_call_frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(
                coordinate.cid for coordinate in frame.formal_coordinates
            ),
            bound_source_actuals=bound,
        )
        method_ctx = ctx.with_temporal(
            ctx.temporal.bind_value(
                "__class__", self, blame=f"{self.class_name}.{name}"
            )
        )
        return call.producer_outcome(method_ctx)

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

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ClassDefinitionValue.setitem",
        )

    def delitem(self, index, site):
        del index
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
        from sugar_lift_py_tests.outcome import Completed, ExitSet
        from sugar_lift_py_tests.outcome.exit_set import (
            _and_guards,
            complement_guard,
            partition,
            true_guard,
        )

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
            states = [(true_guard(), initial, frozenset())]
            for statement in block.statements:
                if isinstance(statement, ObjectValue) or (
                    isinstance(statement, ReceiverFieldStoreValue)
                    and not isinstance(statement, GuardedReceiverFieldStoreValue)
                ):
                    states = [
                        (guard, (*stores, statement), faces)
                        for guard, stores, faces in states
                    ]
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
                next_states = []
                for guard, stores, faces in states:
                    next_states.append(
                        (
                            _and_guards(guard, store.guard),
                            (
                                *stores,
                                (
                                    store.receiver
                                    if isinstance(store, GuardedReceiverStateValue)
                                    else ReceiverFieldStoreValue(
                                        store.receiver, store.attr, store.value
                                    )
                                ),
                            ),
                            faces | {then_face},
                        )
                    )
                    next_states.append(
                        (
                            _and_guards(guard, complement_guard(store.guard)),
                            stores,
                            faces | {else_face},
                        )
                    )
                states = next_states
            exits = tuple(
                Completed(
                    guard,
                    self.construct_receiver_state_from_block(
                        type(block)(stores), receiver_coordinate_cid
                    ),
                    faces,
                )
                for guard, stores, faces in states
            )
            return ReceiverStatePartitionValue(ExitSet(exits).normalize())
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
            method.object_method(defining_class)
            if isinstance(method, DeferredClassMethodV1) and method.unprojected
            else ObjectMethodValue(
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
