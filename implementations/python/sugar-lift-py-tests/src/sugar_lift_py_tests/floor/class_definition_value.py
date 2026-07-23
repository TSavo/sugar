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

    def construct_receiver_state(self, actuals: tuple[object, ...]):
        from sugar_lift_py_tests.floor import (
            CallSiteValue,
            ObjectField,
            ObjectValue,
            ReceiverFieldStoreValue,
        )
        from sugar_lift_py_tests.ir import _term_content_cid, ctor, str_const

        receiver = ObjectValue(self.class_name, (), identity=self.class_definition_cid)
        if self.initializer is None:
            return receiver
        frame = self.initializer.source_call_frame
        values = (receiver, *actuals)
        call = CallSiteValue(
            target_name="python:source-class-init",
            arg_values=values,
            parameters=frame.parameters,
            term=ctor(
                "python:source-class-init",
                [str_const(self.class_definition_cid)],
                symbol_kind="coordinate",
            ),
            body=frame.body,
            source_call_frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(item.cid for item in frame.formal_coordinates),
        )
        block = call.force_floor(
            None,
            owner="ClassDefinitionValue.construct_receiver_state",
            project_callsite=False,
        )
        fields: dict[str, object] = {}
        for statement in block.statements:
            if not isinstance(statement, ReceiverFieldStoreValue):
                continue
            if statement.receiver != receiver:
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
