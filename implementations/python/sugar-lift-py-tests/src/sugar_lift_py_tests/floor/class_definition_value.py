from __future__ import annotations

from dataclasses import dataclass, field

from sugar_source_tree.panic import SugarNotWritten

from .floor_value import FloorValue


@dataclass(frozen=True)
class ConstructedClassMethodV1:
    name: str
    definition_fragment_cid: str
    body: object = field(compare=False)
    source_call_frame: object = field(compare=False)


@dataclass(frozen=True)
class ClassDefinitionValue(FloorValue):
    class_name: str
    class_definition_cid: str
    methods: tuple[ConstructedClassMethodV1, ...]
    initializer: ConstructedClassMethodV1 | None

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:class-definition",
            [str_const(self.class_definition_cid)],
            symbol_kind="coordinate",
        )

    def construct_receiver_state_from_block(self, block, receiver_coordinate_cid):
        from sugar_lift_py_tests.floor import (
            ObjectField,
            ObjectValue,
            ReceiverFieldStoreValue,
        )
        from sugar_lift_py_tests.ir import _term_content_cid, ctor, str_const

        receiver = ObjectValue(
            self.class_name,
            (),
            identity=receiver_coordinate_cid or self.class_definition_cid,
        )
        if block is None:
            return receiver
        fields: dict[str, object] = {}
        for statement in block.statements:
            if not isinstance(statement, ReceiverFieldStoreValue):
                continue
            if statement.receiver.identity != receiver.identity:
                raise SugarNotWritten(
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
        return ObjectValue(
            self.class_name,
            ordered,
            identity=_term_content_cid(identity_term),
        )
