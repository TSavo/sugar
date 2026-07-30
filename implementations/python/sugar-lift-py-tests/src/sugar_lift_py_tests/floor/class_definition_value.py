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

    def __post_init__(self):
        if type(self.binding_target_occurrence) is not SourceFragmentCoordinateV1:
            raise TypeError(
                "ClassDefinitionValue binding target must be an exact "
                "SourceFragmentCoordinateV1"
            )

    def callable_application_with(self, operation, ctx):
        """Construct one source class instance through its initializer frame."""
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.outcome import Complete

        receiver_coordinate = (
            self.initializer.source_call_frame.formal_coordinates[0].cid
            if self.initializer is not None
            else self.class_definition_cid
        )
        receiver = self.construct_receiver_state_from_block(None, receiver_coordinate)
        if self.initializer is None:
            if operation.arguments or operation.keyword_names:
                raise SugarNotWritten(
                    owner="ClassDefinitionValue.callable_application_with",
                    blame=operation.site,
                    observed="arguments supplied to source class without initializer",
                    requested="zero-argument source class construction",
                    fix="retain an initializer frame or keep the call loud",
                )
            return Complete(receiver)

        frame = self.initializer.source_call_frame
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
        bound = frame.bind_actuals(
            (receiver, *positional),
            keywords,
            ctx,
        )
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        call = CallSiteValue(
            target_name=f"{self.class_name}.__init__",
            arg_values=bound.actuals,
            parameters=frame.parameters,
            term=ctor(
                f"call:{self.class_name}.__init__",
                tuple(
                    value.to_term(owner=self.class_definition_cid)
                    for value in bound.actuals
                ),
                symbol_kind="contract-target",
            ),
            body=frame.body,
            site=operation.site,
            source_call_frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(
                coordinate.cid for coordinate in frame.formal_coordinates
            ),
            bound_source_actuals=bound,
        )
        method_ctx = ctx.with_temporal(
            ctx.temporal.bind_value(
                "__class__", self, blame=f"{self.class_name}.__init__"
            )
        )
        outcome = call.reduce_source_outcome(method_ctx)

        def project(value):
            block = value if isinstance(value, BlockValue) else BlockValue((value,))
            return Complete(
                self.construct_receiver_state_from_block(block, receiver_coordinate)
            )

        return outcome.and_then(project)

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
            MappingObjectValue,
            ObjectField,
            ObjectMethodValue,
            ObjectValue,
            ReceiverFieldStoreValue,
            ReceiverStatePartitionValue,
        )
        from sugar_lift_py_tests.ir import (
            _term_content_cid,
            and_,
            ctor,
            not_,
            str_const,
        )
        from sugar_lift_py_tests.outcome import Completed, ExitSet
        from sugar_lift_py_tests.outcome.exit_set import partition, true_guard

        receiver_type = (
            MappingObjectValue if self._has_authenticated_dict_base() else ObjectValue
        )
        receiver = receiver_type(
            self.class_name,
            (),
            methods=self._object_methods(),
            class_fields=self.class_fields,
            identity=receiver_coordinate_cid or self.class_definition_cid,
            **({"defining_class": self} if receiver_type is MappingObjectValue else {}),
        )
        if block is None:
            return receiver
        guarded_stores = tuple(
            statement
            for statement in block.statements
            if isinstance(statement, GuardedReceiverFieldStoreValue)
        )
        if guarded_stores:
            states = [(true_guard(), (), frozenset())]
            for statement in block.statements:
                if isinstance(statement, ReceiverFieldStoreValue) and not isinstance(
                    statement, GuardedReceiverFieldStoreValue
                ):
                    states = [
                        (guard, (*stores, statement), faces)
                        for guard, stores, faces in states
                    ]
                    continue
                if not isinstance(statement, GuardedReceiverFieldStoreValue):
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
                            and_([guard, store.guard]),
                            (
                                *stores,
                                ReceiverFieldStoreValue(
                                    store.receiver, store.attr, store.value
                                ),
                            ),
                            faces | {then_face},
                        )
                    )
                    next_states.append(
                        (
                            and_([guard, not_(store.guard)]),
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
        for statement in block.statements:
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
            **({"defining_class": self} if receiver_type is MappingObjectValue else {}),
        )

    def _object_methods(self):
        from sugar_lift_py_tests.floor import ObjectMethodValue

        # ObjectValue searches from the end, so emit the reversed C3 lookup
        # tail before this class's methods.  A base method is retained with its
        # original authenticated source frame; nothing is reconstructed here.
        inherited = tuple(
            method for base in reversed(self._c3_tail()) for method in base.methods
        )
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
            )
            for method in (*inherited, *self.methods)
        )

    def _c3_tail(self) -> tuple["ClassDefinitionValue", ...]:
        source_bases = tuple(
            base for base in self.base_classes if isinstance(base, ClassDefinitionValue)
        )
        if not source_bases:
            return ()
        sequences = [list((base, *base._c3_tail())) for base in source_bases]
        sequences.append(list(source_bases))
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
                    blame=self.class_definition_cid,
                    owner="ClassDefinitionValue._c3_tail",
                    observed="inconsistent authenticated local base order",
                    requested="one valid C3 linearization",
                    fix="keep inconsistent or dynamic inheritance loud",
                )
            result.append(candidate)
            for sequence in sequences:
                if sequence and sequence[0] == candidate:
                    sequence.pop(0)
        return tuple(result)

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
